import asyncio
import hashlib
import json
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, StringConstraints, model_validator
from sqlalchemy import func, select, update

from app.analysis import compare, observation_data
from app.auth import CurrentUser, Db, require_project
from app.config import settings
from app.db import Session
from app.models import Asset, AuditEvent, Document, Job, JobEvent, Observation, Paper, Passage, Section, Usage
from app.schemas import EvidenceResponse, JobResponse, RetrievalResponse
from app.reports import MIME, references
from app.storage import get, put, remove
from app.worker import schedule
from app.workspace import CleanTitle
from connectors.scholarly import normalize_doi
from rag.engine import plan
from rag.repository import evidence, evidence_query, observation_query, retrieve

router = APIRouter()


class Question(BaseModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)]


class RetrievalRequest(Question):
    limit: int = Field(10, ge=1, le=30)
    document_ids: list[str] = Field(default_factory=list, max_length=50)
    year: int | None = Field(None, ge=1500, le=2200)
    metric: str | None = Field(None, max_length=100)
    unit: str | None = Field(None, max_length=60)
    minimum: float | None = Field(None, allow_inf_nan=False)
    maximum: float | None = Field(None, allow_inf_nan=False)

    @model_validator(mode="after")
    def coherent_range(self):
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("Minimum must be at most maximum")
        return self


class ResearchRequest(Question):
    external_model: bool = False
    discover: bool = False
    synthesize: bool = False


class Decision(BaseModel):
    approved: bool


class Comparison(BaseModel):
    document_ids: list[str] = Field(default_factory=list, max_length=50)
    metric: str = Field(min_length=2, max_length=100)


class ImportRequest(BaseModel):
    doi: str = Field(max_length=330)


class ReportRequest(BaseModel):
    research_id: str = Field(max_length=36)
    title: CleanTitle



def create_job(db, project_id, kind, payload):
    job = Job(project_id=project_id, kind=kind, payload=payload)
    db.add(job)
    db.commit()
    return job


def require_job(db, user, job_id, *, write=False):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    require_project(db, user, job.project_id, write=write)
    return job


def job_data(job, *, summary=False):
    result = job.result
    if job.kind == "report" and result:
        result = {"formats": result["formats"]}
    return {"id": job.id, "kind": job.kind, "status": job.status, "error": job.error,
            "created": job.created, "result": None if summary else result}


@router.post("/projects/{project_id}/papers", status_code=202, response_model=JobResponse)
def upload(project_id: str, db: Db, user: CurrentUser, tasks: BackgroundTasks,
           file: Annotated[UploadFile, File()], title: Annotated[CleanTitle, Form()],
           permitted: Annotated[bool, Form()], doi: Annotated[str | None, Form(max_length=330)] = None):
    require_project(db, user, project_id, write=True)
    if not permitted:
        raise HTTPException(422, "Confirm that you have permission to process this file")
    config = settings()
    content = file.file.read(config.upload_bytes + 1)
    if len(content) > config.upload_bytes:
        raise HTTPException(413, "Upload too large")
    if content.startswith(b"%PDF-"):
        content_type = "application/pdf"
    elif content.lstrip().startswith(b"<"):
        content_type = "application/xml"
    else:
        raise HTTPException(415, "Provide a PDF or XML file")
    normalized = normalize_doi(doi)
    if doi and (not normalized or db.scalar(select(Paper.id).where(Paper.doi == normalized)) is None):
        raise HTTPException(422, "Resolve the DOI through scholarly lookup before linking the document")
    key = f"{project_id}/originals/{uuid4()}"
    put(key, content)
    try:
        checksum = hashlib.sha256(content).hexdigest()
        asset = Asset(project_id=project_id, key=key, checksum=checksum, content_type=content_type)
        db.add(asset)
        db.flush()
        job = create_job(db, project_id, "ingest", {"asset_id": asset.id, "title": title, "doi": normalized})
    except Exception:
        remove(key)
        raise
    schedule(tasks, job.id)
    return job_data(job)


@router.post("/projects/{project_id}/papers/import", status_code=202, response_model=JobResponse)
def import_paper(project_id: str, body: ImportRequest, db: Db, user: CurrentUser, tasks: BackgroundTasks):
    require_project(db, user, project_id, write=True)
    doi = normalize_doi(body.doi)
    if not doi:
        raise HTTPException(422, "A valid DOI is required for licensed import")
    existing = db.scalar(select(Document.id).join(Paper).where(Document.project_id == project_id,
                         Paper.doi == doi, Document.access == "licensed_full_text"))
    if existing:
        raise HTTPException(409, "The licensed full text is already in this project")
    pending = db.scalar(select(Job.id).where(Job.project_id == project_id, Job.kind == "ingest",
                        Job.status.in_(("queued", "running")), Job.payload["doi"].as_string() == doi,
                        Job.payload["method"].as_string() == "licensed_full_text").limit(1))
    if pending:
        return job_data(db.get(Job, pending))
    job = create_job(db, project_id, "ingest", {"doi": doi, "method": "licensed_full_text"})
    schedule(tasks, job.id)
    return job_data(job)


@router.get("/projects/{project_id}/papers")
def papers(project_id: str, db: Db, user: CurrentUser):
    require_project(db, user, project_id)
    return [{"id": d.id, "title": d.title, "access": d.access, "doi": p.doi if p else None}
            for d, p in db.execute(select(Document, Paper).outerjoin(Paper, Paper.id == Document.paper_id)
                                   .where(Document.project_id == project_id).order_by(Document.title).limit(100))]


@router.get("/projects/{project_id}/papers/{document_id}/passages", response_model=list[EvidenceResponse])
def passages(project_id: str, document_id: str, db: Db, user: CurrentUser, offset: int = 0):
    require_project(db, user, project_id)
    rows = db.execute(evidence_query(project_id).where(Document.id == document_id).order_by(Passage.ordinal)
                      .offset(max(0, offset)).limit(100))
    return [evidence(row).to_dict() for row in rows]


@router.get("/projects/{project_id}/jobs", response_model=list[JobResponse])
def project_jobs(project_id: str, db: Db, user: CurrentUser):
    require_project(db, user, project_id)
    return [job_data(job, summary=True) for job in db.scalars(
        select(Job).where(Job.project_id == project_id).order_by(Job.created.desc()).limit(100))]


@router.get("/jobs/{job_id}", response_model=JobResponse)
def job_status(job_id: str, db: Db, user: CurrentUser):
    return job_data(require_job(db, user, job_id))


@router.get("/jobs/{job_id}/timeline")
def timeline(job_id: str, db: Db, user: CurrentUser):
    require_job(db, user, job_id)
    events = db.scalars(select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.created, JobEvent.id).limit(200))
    return [{"stage": item.stage, "created": item.created, "detail": item.detail} for item in events]


@router.get("/jobs/{job_id}/events")
async def events(job_id: str, db: Db, user: CurrentUser):
    require_job(db, user, job_id)
    db.close()

    async def stream():
        previous = None
        for _ in range(120):
            with Session() as session:
                job = session.get(Job, job_id)
                if job is None:
                    break
                event = job_data(job)
            if event != previous:
                yield f"data: {json.dumps(event)}\n\n"
                previous = event
            if event["status"] not in ("queued", "running"):
                break
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/jobs/{job_id}/approval", status_code=202, response_model=JobResponse)
def decision(job_id: str, body: Decision, db: Db, user: CurrentUser, tasks: BackgroundTasks):
    job = require_job(db, user, job_id, write=True)
    changed = db.execute(update(Job).where(Job.id == job.id, Job.status == "awaiting_approval")
                         .values(status="queued", approval=body.approved, result=None)).rowcount
    if not changed:
        raise HTTPException(409, "This run is not awaiting approval")
    event = "approved" if body.approved else "rejected_by_user"
    db.add(JobEvent(job_id=job.id, stage=event))
    project = require_project(db, user, job.project_id)
    db.add(AuditEvent(organization_id=project.organization_id, actor_id=user.id, project_ref=project.id,
                      event="external_model_" + event))
    db.commit()
    schedule(tasks, job.id)
    return job_data(job)


@router.post("/projects/{project_id}/retrieve", response_model=RetrievalResponse)
def retrieval(project_id: str, body: RetrievalRequest, db: Db, user: CurrentUser):
    require_project(db, user, project_id)
    try:
        rows = retrieve(db, project_id, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"intent": plan(body.query).intent, "evidence": [row.to_dict() for row in rows]}


@router.get("/evidence/{passage_id}", response_model=EvidenceResponse)
def inspect_evidence(passage_id: str, db: Db, user: CurrentUser):
    project_id = db.scalar(select(Document.project_id).join(Section, Section.document_id == Document.id)
                           .join(Passage, Passage.section_id == Section.id).where(Passage.id == passage_id))
    if project_id is None:
        raise HTTPException(404, "Evidence not found")
    require_project(db, user, project_id)
    entry = db.execute(evidence_query(project_id).where(Passage.id == passage_id)).one()
    return evidence(entry).to_dict()


@router.post("/projects/{project_id}/research", status_code=202, response_model=JobResponse)
def research(project_id: str, body: ResearchRequest, db: Db, user: CurrentUser, tasks: BackgroundTasks):
    require_project(db, user, project_id, write=True)
    config = settings()
    if body.synthesize and (not body.external_model or config.llm_max_calls < 3):
        raise HTTPException(422, "External synthesis requires an approved provider and at least three model calls per run")
    if body.external_model and not (config.llm_url and config.llm_model and config.llm_key and config.llm_max_calls > 0):
        raise HTTPException(422, "External model access is not configured")
    job = create_job(db, project_id, "research", body.model_dump())
    schedule(tasks, job.id)
    return job_data(job)


@router.get("/projects/{project_id}/observations")
def observations(project_id: str, db: Db, user: CurrentUser, metric: str | None = None, offset: int = 0):
    require_project(db, user, project_id)
    query = observation_query(project_id)
    if metric:
        query = query.where(Observation.metric == metric.lower())
    return [observation_data(row, doc) for row, doc in db.execute(
        query.order_by(Observation.id).offset(max(0, offset)).limit(100))]


@router.post("/projects/{project_id}/compare")
def comparison(project_id: str, body: Comparison, db: Db, user: CurrentUser):
    require_project(db, user, project_id)
    return compare(db, project_id, body.document_ids, body.metric)


@router.post("/projects/{project_id}/reports", status_code=202, response_model=JobResponse)
def create_report(project_id: str, body: ReportRequest, db: Db, user: CurrentUser, tasks: BackgroundTasks):
    require_project(db, user, project_id, write=True)
    prior = require_job(db, user, body.research_id)
    if prior.project_id != project_id or prior.kind != "research" or prior.status != "succeeded":
        raise HTTPException(404, "Completed research run not found")
    job = create_job(db, project_id, "report", body.model_dump())
    schedule(tasks, job.id)
    return job_data(job)


@router.get("/reports/{job_id}/export")
def export(job_id: str, db: Db, user: CurrentUser, format: Literal["markdown", "docx", "pdf"] = "markdown"):
    job = require_job(db, user, job_id)
    if job.kind != "report" or job.status != "succeeded":
        raise HTTPException(404, "Completed report not found")
    mime, suffix = MIME[format]
    return Response(get(job.result["keys"][format]), media_type=mime,
                    headers={"Content-Disposition": f'attachment; filename="research-report.{suffix}"'})


@router.get("/projects/{project_id}/usage")
def usage(project_id: str, db: Db, user: CurrentUser):
    require_project(db, user, project_id)
    rows = db.execute(
        select(Usage.model, func.count(Usage.id), func.sum(Usage.input_tokens), func.sum(Usage.output_tokens),
               func.sum(Usage.estimated_cost), func.count(Usage.estimated_cost))
        .join(Job, Job.id == Usage.job_id).where(Job.project_id == project_id)
        .group_by(Usage.model).order_by(Usage.model)
    )
    return [{"model": model, "tracked_calls": calls, "input_tokens": inputs, "output_tokens": outputs,
             "estimated_cost": cost, "priced_calls": priced}
            for model, calls, inputs, outputs, cost, priced in rows]


@router.get("/projects/{project_id}/papers/{document_id}/original")
def download_original(project_id: str, document_id: str, db: Db, user: CurrentUser):
    require_project(db, user, project_id)
    asset = db.scalar(select(Asset).join(Document, Document.asset_id == Asset.id).where(
        Document.id == document_id, Document.project_id == project_id, Asset.project_id == project_id
    ))
    if asset is None:
        raise HTTPException(404, "Document not found")
    suffix = "pdf" if asset.content_type == "application/pdf" else "xml"
    return Response(get(asset.key), media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="original.{suffix}"'})


@router.get("/reports/{job_id}/references")
def download_references(job_id: str, db: Db, user: CurrentUser, style: Literal["apa", "ieee"] = "apa"):
    job = require_job(db, user, job_id)
    if job.kind != "report" or job.status != "succeeded":
        raise HTTPException(404, "Completed report not found")
    run = db.scalar(select(Job).where(Job.id == job.payload["research_id"], Job.project_id == job.project_id))
    if run is None or run.kind != "research" or run.status != "succeeded":
        raise HTTPException(404, "Source research run not found")
    return Response(references(run.result, style), media_type="text/plain",
                    headers={"Content-Disposition": f'attachment; filename="references-{style}.txt"'})
