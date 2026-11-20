from typing import Literal

from pydantic import BaseModel


class AccountResponse(BaseModel):
    id: str
    email: str


class NamedResponse(BaseModel):
    id: str
    title: str


class MessageResponse(BaseModel):
    id: str
    body: str


class ConversationResponse(NamedResponse):
    messages: list[MessageResponse]


class EvidenceResponse(BaseModel):
    id: str
    document_id: str
    title: str
    text: str
    section: str
    section_id: str
    kind: str
    page: int | None
    doi: str | None
    access: str
    metadata: dict
    anchor: dict


class RetrievalResponse(BaseModel):
    intent: str
    evidence: list[EvidenceResponse]


class JobResponse(BaseModel):
    id: str
    kind: Literal["ingest", "research", "report", "purge"]
    status: Literal["queued", "running", "awaiting_approval", "succeeded", "failed", "rejected"]
    error: str | None
    created: float
    result: dict | None


class SourceResponse(BaseModel):
    provider: str
    external_id: str
    title: str
    doi: str | None
    authors: list[str | None]
    year: int | str | None
    url: str | None
    abstract: str | None
    journal: str | None
    publication_type: str | None
    licence: str | None
    open_access: bool | None
    access: str
    retracted: bool | None
    relations: list[dict]


class LiteratureResponse(BaseModel):
    records: list[SourceResponse]
    next_offset: int | None
