import hashlib
from uuid import uuid4

from sqlalchemy import select, text

from app.config import settings
from app.literature import persist
from app.models import Asset, Document, DocumentArtifact, Observation, Paper, Passage, Project, Section
from app.storage import get, malware_check, put, remove
from connectors import fulltext
from ingestion.bibliography import bibliography
from ingestion.observations import extract, extract_table
from ingestion.parser import parse


def licensed_document(db, project_id, doi):
    return db.scalar(select(Document).join(Paper).where(
        Document.project_id == project_id, Paper.doi == doi, Paper.retracted.is_(False),
        Document.access == "licensed_full_text",
    ).order_by(Document.id).limit(1))


def import_licensed(db, project_id, doi):
    existing = licensed_document(db, project_id, doi)
    if existing is not None:
        return {"document_id": existing.id, "reused": True}
    if db.scalar(select(Paper.id).where(Paper.doi == doi, Paper.retracted.is_(True))):
        raise ValueError("Retracted articles cannot be imported")
    db.rollback()  # Release the read transaction before network and parsing work.
    article = fulltext.fetch(doi, settings().upload_bytes)
    malware_check(article.content)
    blocks = parse(article.content, "application/xml")
    metadata = bibliography(article.content, "application/xml")
    persist(db, [article.record])
    key = f"{project_id}/originals/{uuid4()}.xml"
    try:
        project = db.scalar(select(Project).where(Project.id == project_id, Project.pending_deletion.is_(False))
                            .with_for_update())
        if project is None:
            raise ValueError("Project is unavailable for full-text import")
        existing = licensed_document(db, project_id, doi)
        if existing is not None:
            db.commit()
            return {"document_id": existing.id, "reused": True}
        paper = db.scalar(select(Paper).where(Paper.doi == doi, Paper.retracted.is_(False)))
        if paper is None:
            raise ValueError("The full-text article DOI could not be verified as eligible")
        asset = Asset(project_id=project_id, key=key, content_type="application/xml",
                      checksum=hashlib.sha256(article.content).hexdigest())
        db.add(asset)
        db.flush()
        result = store_document(db, asset, paper, article.record["title"], article.provenance, blocks, metadata)
        put(key, article.content)
        db.commit()
    except Exception:
        db.rollback()
        remove(key)
        raise
    return {**result, "reused": False}


def ingest(db, job):
    if "asset_id" not in job.payload:
        return import_licensed(db, job.project_id, job.payload["doi"])
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
    title = paper.title if paper and not provenance else job.payload["title"]
    return store_document(db, asset, paper, title, provenance, blocks, bibliography(content, asset.content_type))


def store_document(db, asset, paper, title, provenance, blocks, bibliography):
    licence_url = (provenance or {}).get("licence")
    if licence_url:
        db.execute(text("INSERT INTO licences (url) VALUES (:url) ON CONFLICT (url) DO NOTHING").bindparams(url=licence_url))
    document = Document(project_id=asset.project_id, asset_id=asset.id, paper_id=paper.id if paper else None,
                        title=title, access="licensed_full_text" if provenance else "user_upload",
                        provenance=provenance, bibliography=bibliography, licence_url=licence_url)
    db.add(document)
    db.flush()
    sections, passages, observations, artifacts = [], [], [], []
    for index, block in enumerate(blocks):
        if not sections or sections[-1].heading != block.heading:
            sections.append(Section(id=str(uuid4()), document_id=document.id,
                                    heading=block.heading, ordinal=len(sections) + 1))
        passage = Passage(id=str(uuid4()), section_id=sections[-1].id, text=block.text,
                          page=block.page, ordinal=index, kind=block.kind, anchor=block.anchor)
        passages.append(passage)
        if block.structure is not None:
            artifacts.append(DocumentArtifact(document_id=document.id, passage_id=passage.id, kind=block.kind,
                                              ordinal=index, payload=block.structure))
        if block.kind != "reference":
            measurements = extract_table(block.structure) if block.kind == "table" and block.structure else extract(block.text)
            observations.extend(Observation(passage_id=passage.id, **data) for data in measurements)
    db.add_all(sections)
    db.flush()
    db.add_all(passages)
    db.flush()
    db.add_all(observations)
    db.add_all(artifacts)
    return {"document_id": document.id, "passages": len(blocks), "artifacts": len(artifacts)}
