import hashlib
from uuid import uuid4

from sqlalchemy import select

from app.config import settings
from app.literature import persist
from app.models import Asset, Document, Observation, Paper, Passage, Section
from app.storage import get, malware_check, put, remove
from connectors import fulltext
from ingestion.observations import extract
from ingestion.parser import parse


def prepare_licensed_asset(db, job):
    doi = job.payload["doi"]
    if db.scalar(select(Paper.id).where(Paper.doi == doi, Paper.retracted.is_(True))):
        raise ValueError("Retracted articles cannot be imported")
    article = fulltext.fetch(doi, settings().upload_bytes)
    persist(db, [article.record])
    key = f"{job.project_id}/originals/{job.id}.xml"
    put(key, article.content)
    try:
        asset = Asset(project_id=job.project_id, key=key, content_type="application/xml",
                      checksum=hashlib.sha256(article.content).hexdigest())
        db.add(asset)
        db.flush()
        job.payload = {**job.payload, "asset_id": asset.id, "title": article.record["title"],
                       "provenance": article.provenance}
        db.commit()
    except Exception:
        remove(key)
        raise


def ingest(db, job):
    if "asset_id" not in job.payload:
        prepare_licensed_asset(db, job)
    asset = db.scalar(select(Asset).where(Asset.id == job.payload["asset_id"], Asset.project_id == job.project_id))
    if asset is None:
        raise ValueError("Asset unavailable")
    content = get(asset.key)
    if hashlib.sha256(content).hexdigest() != asset.checksum:
        raise ValueError("Stored asset checksum does not match the uploaded file")
    malware_check(content)
    blocks = parse(content, asset.content_type)
    paper = db.scalar(select(Paper).where(Paper.doi == job.payload["doi"])) if job.payload["doi"] else None
    provenance = job.payload.get("provenance")
    if provenance and (paper is None or paper.retracted):
        raise ValueError("The full-text article DOI could not be verified as eligible")
    document = Document(project_id=job.project_id, asset_id=asset.id, paper_id=paper.id if paper else None,
                        title=job.payload["title"] if provenance or not paper else paper.title,
                        access="licensed_full_text" if provenance else "user_upload", provenance=provenance)
    db.add(document)
    db.flush()
    sections, passages, observations = [], [], []
    for index, block in enumerate(blocks):
        if not sections or sections[-1].heading != block.heading:
            sections.append(Section(id=str(uuid4()), document_id=document.id,
                                    heading=block.heading, ordinal=len(sections) + 1))
        passage = Passage(id=str(uuid4()), section_id=sections[-1].id, text=block.text,
                          page=block.page, ordinal=index, kind=block.kind, anchor=block.anchor)
        passages.append(passage)
        if block.kind != "reference":
            observations.extend(Observation(passage_id=passage.id, **data) for data in extract(block.text))
    db.add_all(sections)
    db.flush()
    db.add_all(passages)
    db.flush()
    db.add_all(observations)
    return {"document_id": document.id, "passages": len(blocks)}
