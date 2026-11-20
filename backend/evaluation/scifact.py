"""Evaluate scholarly retrieval on AI2 SciFact's published development labels."""

import argparse
import hashlib
import json
import os
import tarfile
from collections import Counter
from pathlib import Path

from evaluation.baselines import GraphAssisted, Hybrid, SparseLSA
from evaluation.retrieval_benchmark import evaluate, local_engine
from rag.engine import Evidence


def read_data(path):
    with tarfile.open(path, "r:gz") as archive:
        members = {Path(item.name).name: item for item in archive.getmembers() if item.isfile()
                   and Path(item.name).name in {"corpus.jsonl", "claims_dev.jsonl"}}
        if len(members) != 2 or any(item.size > 25_000_000 for item in members.values()):
            raise ValueError("Unexpected SciFact archive contents")
        with archive.extractfile(members["corpus.jsonl"]) as data:
            corpus = [item for line in data if line.strip() for item in [json.loads(line)]]
        with archive.extractfile(members["claims_dev.jsonl"]) as data:
            claims = [json.loads(line) for line in data if line.strip()]
    return corpus, claims


def benchmark(path, cutoff, *, dense):
    articles, claims = read_data(path)
    corpus = [Evidence(id=str(row["doc_id"]), document_id=str(row["doc_id"]), title=row["title"],
                       text=" ".join(row["abstract"]), section="Abstract", section_id="abstract",
                       access="abstract") for row in articles]
    labeled, evidence_counts = [], Counter()
    for entry in claims:
        evidence = entry.get("evidence", {})
        relevant = [str(identifier) for identifier, items in evidence.items() if items]
        if relevant:
            labeled.append({"query": entry["claim"], "relevant": relevant})
            evidence_counts.update({item["label"] for items in evidence.values() for item in items})
    if len(corpus) < 5000 or len(labeled) < 150:
        raise ValueError("SciFact benchmark corpus or development labels are incomplete")
    engines = {name: local_engine(corpus, name) for name in ("bm25", "metadata", "hierarchical", "adaptive")}
    engines["graph_assisted"] = GraphAssisted(corpus, engines["adaptive"])
    if dense:
        latent = SparseLSA(corpus)
        engines.update(dense_lsa=latent, hybrid_lsa=Hybrid(engines["adaptive"], latent))
    modes = {name: evaluate(corpus, labeled, engine, cutoff) for name, engine in engines.items()}
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    return {"dataset": "AI2 SciFact dev", "archive_sha256": digest, "corpus_abstracts": len(corpus),
            "development_claims": len(claims), "labeled_claims": len(labeled),
            "claims_without_evidence_labels": len(claims) - len(labeled),
            "labels": dict(evidence_counts), "cutoff": cutoff, "modes": modes}


def summarize(result, destination):
    with open(destination, "a", encoding="utf-8") as output:
        output.write(f"## SciFact abstract retrieval\n\n{result['labeled_claims']} labeled claims across "
                     f"{result['corpus_abstracts']} scientific abstracts. "
                     f"{result['claims_without_evidence_labels']} claims without evidence labels were excluded.\n\n"
                     f"Archive SHA-256 `{result['archive_sha256']}`\n\n")
        values = next(iter(result["modes"].values()))
        output.write("| Variant | " + " | ".join(values) + " |\n")
        output.write("| --- | " + " | ".join("---:" for _ in values) + " |\n")
        for name, metrics in result["modes"].items():
            output.write(f"| {name} | " + " | ".join(str(value) for value in metrics.values()) + " |\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--cutoff", type=int, choices=range(1, 21), default=5)
    parser.add_argument("--dense", action="store_true")
    args = parser.parse_args()
    result = benchmark(args.archive, args.cutoff, dense=args.dense)
    print(json.dumps(result, indent=2))
    if os.getenv("GITHUB_STEP_SUMMARY"):
        summarize(result, os.environ["GITHUB_STEP_SUMMARY"])
        print(f"::notice title=SciFact coverage::{result['corpus_abstracts']} abstracts, "
              f"{result['labeled_claims']} evidence-labeled claims, SHA-256 {result['archive_sha256']}")
        for name, metrics in result["modes"].items():
            scores = ", ".join(f"{metric}={value}" for metric, value in metrics.items())
            print(f"::notice title=SciFact {name}::{scores}")
