import hashlib
from uuid import uuid4

from sqlalchemy import select

from app.models import Asset, Document, Observation, Paper, Passage, Section
from app.storage import get, malware_check
from ingestion.observations import extract
from ingestion.parser import parse


def ingest(db, job):
    asset = db.scalar(select(Asset).where(Asset.id == job.payload["asset_id"], Asset.project_id == job.project_id))
    if asset is None:
        raise ValueError("Asset unavailable")
    content = get(asset.key)
    if hashlib.sha256(content).hexdigest() != asset.checksum:
        raise ValueError("Stored asset checksum does not match the uploaded file")
    malware_check(content)
    blocks = parse(content, asset.content_type)
    paper = db.scalar(select(Paper).where(Paper.doi == job.payload["doi"])) if job.payload["doi"] else None
    document = Document(project_id=job.project_id, asset_id=asset.id, paper_id=paper.id if paper else None,
                        title=paper.title if paper else job.payload["title"])
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
