from time import time
from uuid import uuid4
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth import CurrentUser, Db
from app.models import Author, Paper, PaperAuthor, Source
from app.schemas import LiteratureResponse, SourceResponse
from connectors.scholarly import discover, normalize_doi, resolve_doi

Provider = Literal["crossref", "openalex", "semantic_scholar", "arxiv", "pubmed", "europe_pmc", "core"]
router = APIRouter()


def persist(db, records):
    for record in records:
        try:
            with db.begin_nested():
                source = db.scalar(select(Source).where(Source.provider == record["provider"],
                                                        Source.external_id == record["external_id"]))
                paper = db.get(Paper, source.paper_id) if source else None
                if paper is None and record["doi"]:
                    paper = db.scalar(select(Paper).where(Paper.doi == record["doi"]))
                if paper is None:
                    paper = Paper(title=record["title"], doi=record["doi"], metadata_json=record,
                                  retracted=record["retracted"] is True)
                    db.add(paper)
                    db.flush()
                elif record["retracted"] is True:
                    paper.retracted = True
                if record.get("authors") and db.scalar(
                    select(PaperAuthor.author_id).where(PaperAuthor.paper_id == paper.id).limit(1)
                ) is None:
                    authors = [(index, Author(id=str(uuid4()), display_name=name)) for index, name in
                               enumerate(record["authors"][:500], 1) if isinstance(name, str) and name.strip()]
                    db.add_all(author for _, author in authors)
                    db.flush()
                    db.add_all(PaperAuthor(paper_id=paper.id, position=index, author_id=author.id)
                               for index, author in authors)
                if source is None:
                    db.add(Source(paper_id=paper.id, provider=record["provider"],
                                  external_id=record["external_id"], record=record))
                else:
                    source.record = record
                    source.fetched_at = time()
        except IntegrityError:
            # A concurrent discovery may have inserted either identity.
            continue
    db.commit()


@router.get("/literature/search", response_model=LiteratureResponse)
def search_literature(db: Db, user: CurrentUser, q: str = Query(min_length=2, max_length=300),
                      provider: Provider = "crossref", limit: int = Query(10, ge=1, le=25),
                      offset: int = Query(0, ge=0, le=400)):
    if provider in ("openalex", "europe_pmc") and offset % limit:
        raise HTTPException(422, "This provider requires offset to be a multiple of limit")
    results, errors = discover(q, (provider,), limit, offset)
    if not results and errors:
        raise HTTPException(502, errors[provider])
    persist(db, results)
    return {"records": results, "next_offset": offset + limit if len(results) == limit else None}


@router.get("/literature/doi", response_model=SourceResponse)
def lookup_doi(db: Db, user: CurrentUser, doi: str = Query(max_length=330)):
    normalized = normalize_doi(doi)
    if not normalized:
        raise HTTPException(422, "Invalid DOI")
    try:
        result = resolve_doi(normalized, int(time() // 300))
    except httpx.HTTPStatusError as exc:
        raise HTTPException(404 if exc.response.status_code == 404 else 502, "DOI resolution failed") from exc
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise HTTPException(502, "DOI resolver unavailable") from exc
    persist(db, [result])
    return result
