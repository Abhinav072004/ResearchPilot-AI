import re
from contextlib import contextmanager
from pathlib import Path
from time import time
from typing import TypedDict

import httpx

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import select

from agents.synthesis import propose, verify
from app.analysis import compare, facets
from app.config import settings
from app.models import Claim, Document, EvidenceLink, JobEvent, Paper, Passage
from connectors.scholarly import discover, resolve_doi
from ingestion.observations import ALIASES, METRICS
from rag.engine import plan, tokens
from rag.repository import evidence, evidence_query, retrieve
from rag.reranker import ModelBudget


class ResearchState(TypedDict, total=False):
    question: str
    deadline: float
    stage: str
    intent: str
    queries: list[str]
    doi: str | None
    discovery: list[dict]
    provider_errors: dict
    verified_metadata: list[dict]
    documents: list[str]
    passage_ids: list[str]
    proposed: list[dict]
    checked: list[dict]
    synthesis: list[dict]
    comparisons: dict
    output: dict
    gaps: list[str]


@contextmanager
def checkpointer():
    config = settings()
    if config.database_url.startswith("postgresql+psycopg://"):
        with PostgresSaver.from_conn_string(config.database_url.replace("+psycopg", "", 1)) as saver:
            yield saver
    else:
        path = Path(config.database_url.removeprefix("sqlite:///")).absolute()
        with SqliteSaver.from_conn_string(str(path.with_suffix(".checkpoints.sqlite"))) as saver:
            yield saver


def run_research(db, job):
    model = ModelBudget(db, job.id) if job.payload.get("external_model") else None
    def event(stage, detail=None):
        db.add(JobEvent(job_id=job.id, stage=stage, detail=detail or {}))
        db.commit()

    def timed(stage, step):
        def node(state):
            limit = state.get("deadline", 0)
            if limit and time() > limit:
                raise TimeoutError("Research run exceeded its execution budget")
            event(stage)
            return {**step(state), "stage": stage}
        return node

    def understanding(state):
        result = plan(state["question"])
        return {"intent": result.intent, "doi": result.doi}

    def planner(state):
        return {"queries": list(plan(state["question"]).queries)}

    def discovery(state):
        if not job.payload.get("discover"):
            return {"discovery": []}
        records, errors = discover(state["queries"][0], ("crossref", "openalex"), limit=5)
        return {"discovery": records, "provider_errors": errors}

    def verification(state):
        if not job.payload.get("discover"):
            return {"verified_metadata": []}
        identifiers = list(dict.fromkeys([state.get("doi")] + [x["doi"] for x in state.get("discovery", [])]))
        verified = []
        for doi in [item for item in identifiers if item][:2]:
            try:
                verified.append(resolve_doi(doi, int(time() // 300)))
            except (httpx.HTTPError, ValueError, KeyError, IndexError):
                continue
        gaps = ["Discovered records are metadata leads until an authorized full text is ingested."] if verified else []
        return {"verified_metadata": verified, "gaps": gaps}

    def approval(state):
        task = "ranking, synthesis and claim verification" if job.payload.get("synthesize") else "relevance ranking"
        approved = interrupt({"operation": "external_model", "passage_limit": 12,
                              "purpose": f"Send snippets to the configured model provider for {task}."})
        if not approved:
            return {"stage": "rejected", "output": {"status": "rejected", "claims": []}}
        return {"stage": "approval", "deadline": time() + 100}

    def document_intelligence(state):
        documents = db.scalars(select(Document.id).outerjoin(Paper, Document.paper_id == Paper.id)
                               .where(Document.project_id == job.project_id,
                                      Paper.id.is_(None) | Paper.retracted.is_(False))).all()
        return {"documents": documents}

    def vectorless_retrieval(state):
        if not state["documents"]:
            return {"passage_ids": []}
        rank = model.rerank if model else None
        rows = retrieve(db, job.project_id, state["question"], 10, reranker=rank)
        return {"passage_ids": [row.id for row in rows]}

    def records(state):
        rows = db.execute(evidence_query(job.project_id).where(
            Passage.id.in_(state.get("passage_ids", [])), Paper.id.is_(None) | Paper.retracted.is_(False)
        ))
        return {entry.id: entry for entry in map(evidence, rows)}

    def analyst(state):
        entries = records(state)
        candidates = []
        terms = set(tokens(state["question"]))
        for identifier in state["passage_ids"]:
            if identifier not in entries:
                continue
            row = entries[identifier]
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", row.text) if 30 <= len(s.strip()) <= 700]
            allowed = [s for s in sentences if not re.search(
                r"\b(?:ignore (?:all|previous|prior)|system prompt|assistant instruction|send (?:your|all)|you must)\b", s, re.I)]
            best = max(allowed, key=lambda s: len(terms.intersection(tokens(s))), default="")
            if best and (terms.intersection(tokens(best)) or state.get("doi")):
                candidates.append({"passage_id": identifier, "text": best, "facets": facets(best),
                                   "type": "direct_excerpt"})
        result = {"proposed": candidates}
        if model and job.payload.get("synthesize") and entries:
            ordered = [entries[key] for key in state["passage_ids"] if key in entries]
            result["synthesis"] = [item.model_dump() for item in propose(model, state["question"], ordered)]
        return result

    def domain_expert(state):
        if state["intent"] != "comparison":
            return {}
        metrics = [ALIASES.get(metric.lower(), metric.lower()) for metric in METRICS
                   if metric.lower() in state["question"].lower()]
        return {"comparisons": {metric: compare(db, job.project_id, state["documents"], metric)
                                for metric in dict.fromkeys(metrics)}}

    def fact_checker(state):
        entries = records(state)
        checked = []
        for claim in state["proposed"]:
            row = entries.get(claim["passage_id"])
            if row is not None and claim["text"] in row.text:
                checked.append({**claim, "evidence": row.to_dict()})
        if model and state.get("synthesis"):
            synthesis = []
            for claim in verify(model, state["synthesis"], entries):
                links = [entries[support.id].to_dict() for support in claim.supports]
                synthesis.append({"text": claim.text, "type": "model_checked_synthesis",
                                  "facets": facets(claim.text), "passage_id": links[0]["id"],
                                  "evidence": links[0], "supporting_evidence": links,
                                  "quotes": [support.quote for support in claim.supports]})
            checked = synthesis + checked
        return {"checked": checked}

    def report_generator(state):
        gaps = list(state.get("gaps", []))
        if not state["checked"]:
            gaps.append("The project corpus did not yield a directly supporting passage.")
        if job.payload.get("synthesize") and not any(c["type"] == "model_checked_synthesis" for c in state["checked"]):
            gaps.append("The model did not return synthesis that passed citation and claim checks.")
        if state["intent"] == "recommendation":
            gaps.append("Review transferability, operating conditions and primary sources before acting.")
        return {"output": {"status": "succeeded", "intent": state["intent"], "claims": state["checked"],
                           "gaps": gaps, "metadata_leads": state.get("verified_metadata", []),
                           "provider_errors": state.get("provider_errors", {}),
                           "comparisons": state.get("comparisons", {})}}

    steps = {
        "understanding": understanding, "planner": planner, "discovery": discovery, "verification": verification,
        "document_intelligence": document_intelligence, "vectorless_retrieval": vectorless_retrieval,
        "analyst": analyst, "domain_expert": domain_expert, "fact_checker": fact_checker,
        "report_generator": report_generator,
    }
    sequence = list(steps)
    graph = StateGraph(ResearchState)
    for stage, worker in steps.items():
        graph.add_node(stage, timed(stage, worker))
    graph.add_node("supervisor", timed("supervisor", lambda state: {}))
    graph.add_node("approval", approval)
    graph.add_edge(START, "supervisor")
    graph.add_edge("supervisor", sequence[0])
    for before, after in zip(sequence, sequence[1:]):
        if before != "verification":
            graph.add_edge(before, after)
    graph.add_conditional_edges("verification", lambda _: "approval" if job.payload.get("external_model") else "document_intelligence",
                                ["approval", "document_intelligence"])
    graph.add_conditional_edges("approval", lambda state: END if state["stage"] == "rejected" else "document_intelligence",
                                [END, "document_intelligence"])
    graph.add_edge("report_generator", END)
    config = {"configurable": {"thread_id": job.id}, "recursion_limit": 20}
    with checkpointer() as saver:
        workflow = graph.compile(checkpointer=saver)
        snapshot = workflow.get_state(config)
        if snapshot.interrupts:
            if job.approval is None:
                return "awaiting_approval", {"approval": snapshot.interrupts[0].value}
            state = workflow.invoke(Command(resume=job.approval), config)
        elif snapshot.values and not snapshot.next:
            state = snapshot.values
        elif snapshot.values:
            state = workflow.invoke(None, config)
        else:
            state = workflow.invoke({"question": job.payload["query"], "deadline": time() + 100}, config)
        if state.get("__interrupt__"):
            return "awaiting_approval", {"approval": state["__interrupt__"][0].value}
    output = state["output"]
    for item in output["claims"]:
        claim = Claim(job_id=job.id, text=item["text"])
        db.add(claim)
        db.flush()
        identifiers = {source["id"] for source in item.get("supporting_evidence", [item["evidence"]])}
        db.add_all(EvidenceLink(claim_id=claim.id, passage_id=identifier) for identifier in identifiers)
        item["claim_id"] = claim.id
    return output["status"], output
