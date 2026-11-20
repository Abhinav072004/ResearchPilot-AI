from time import time
from uuid import uuid4

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

Payload = JSON().with_variant(JSONB, "postgresql")


class Identity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))


class User(Identity, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password: Mapped[str] = mapped_column(Text)


class Login(Base):
    __tablename__ = "logins"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires: Mapped[float] = mapped_column(Float, index=True)


class Organization(Identity, Base):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(150))


class Membership(Base):
    __tablename__ = "memberships"
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20))


class Project(Identity, Base):
    __tablename__ = "projects"
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(150))
    pending_deletion: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class Conversation(Identity, Base):
    __tablename__ = "conversations"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(150))


class Message(Identity, Base):
    __tablename__ = "messages"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    body: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float, default=time)


class Paper(Identity, Base):
    __tablename__ = "papers"
    doi: Mapped[str | None] = mapped_column(String(300), unique=True)
    title: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(Payload)
    retracted: Mapped[bool] = mapped_column(Boolean, default=False)


class Author(Identity, Base):
    __tablename__ = "authors"
    display_name: Mapped[str] = mapped_column(Text)


class PaperAuthor(Base):
    __tablename__ = "paper_authors"
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("authors.id"))


class Licence(Base):
    __tablename__ = "licences"
    url: Mapped[str] = mapped_column(String(512), primary_key=True)


class Source(Identity, Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("provider", "external_id"),)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    external_id: Mapped[str] = mapped_column(String(500))
    record: Mapped[dict] = mapped_column(Payload)
    fetched_at: Mapped[float] = mapped_column(Float, default=time)


class Asset(Identity, Base):
    __tablename__ = "file_assets"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(Text, unique=True)
    checksum: Mapped[str] = mapped_column(String(64))
    content_type: Mapped[str] = mapped_column(String(100))


class Document(Identity, Base):
    __tablename__ = "document_versions"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("file_assets.id", ondelete="CASCADE"), unique=True)
    paper_id: Mapped[str | None] = mapped_column(ForeignKey("papers.id"), index=True)
    title: Mapped[str] = mapped_column(Text)
    access: Mapped[str] = mapped_column(String(30), default="user_upload")
    provenance: Mapped[dict | None] = mapped_column(Payload)
    bibliography: Mapped[dict | None] = mapped_column(Payload)
    licence_url: Mapped[str | None] = mapped_column(ForeignKey("licences.url", name="fk_document_versions_licence"))


class Section(Identity, Base):
    __tablename__ = "sections"
    document_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    heading: Mapped[str] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(Integer)


class Passage(Identity, Base):
    __tablename__ = "passages"
    section_id: Mapped[str] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(30))
    page: Mapped[int | None] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer)
    anchor: Mapped[dict] = mapped_column(Payload, default=dict)


class DocumentArtifact(Identity, Base):
    __tablename__ = "document_artifacts"
    document_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    passage_id: Mapped[str] = mapped_column(ForeignKey("passages.id", ondelete="CASCADE"), unique=True)
    kind: Mapped[str] = mapped_column(String(30))
    ordinal: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(Payload)


class Experiment(Identity, Base):
    __tablename__ = "extracted_experiments"
    document_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    passage_id: Mapped[str] = mapped_column(ForeignKey("passages.id", ondelete="CASCADE"), index=True)
    domain: Mapped[str] = mapped_column(String(32))
    study_type: Mapped[str] = mapped_column(String(30))
    conditions: Mapped[dict] = mapped_column(Payload)


class Observation(Identity, Base):
    __tablename__ = "experimental_observations"
    passage_id: Mapped[str] = mapped_column(ForeignKey("passages.id", ondelete="CASCADE"), index=True)
    metric: Mapped[str] = mapped_column(String(100), index=True)
    domain: Mapped[str] = mapped_column(String(32), index=True, default="chemical_engineering",
                                        server_default="chemical_engineering")
    raw_value: Mapped[str] = mapped_column(String(50))
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(60))
    study_type: Mapped[str] = mapped_column(String(30))
    conditions: Mapped[dict] = mapped_column(Payload)
    confidence: Mapped[str] = mapped_column(String(20))
    measurement_anchor: Mapped[dict | None] = mapped_column(Payload)
    experiment_id: Mapped[str | None] = mapped_column(
        ForeignKey("extracted_experiments.id", name="fk_observation_experiment"), index=True
    )


class Job(Identity, Base):
    __tablename__ = "jobs"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    payload: Mapped[dict] = mapped_column(Payload)
    result: Mapped[dict | None] = mapped_column(Payload)
    error: Mapped[str | None] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float, default=time)
    updated: Mapped[float] = mapped_column(Float, default=time, onupdate=time)
    approval: Mapped[bool | None] = mapped_column(Boolean)


class ResearchQuery(Identity, Base):
    __tablename__ = "research_queries"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), index=True)
    query: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(30))
    domain: Mapped[str] = mapped_column(String(32))


class JobEvent(Identity, Base):
    __tablename__ = "job_events"
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    created: Mapped[float] = mapped_column(Float, default=time)
    stage: Mapped[str] = mapped_column(String(60))
    detail: Mapped[dict] = mapped_column(Payload, default=dict)


class Claim(Identity, Base):
    __tablename__ = "claims"
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)


class EvidenceLink(Base):
    __tablename__ = "evidence_links"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), primary_key=True)
    passage_id: Mapped[str] = mapped_column(ForeignKey("passages.id", ondelete="CASCADE"), primary_key=True)


class Usage(Identity, Base):
    __tablename__ = "usage_records"
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    model: Mapped[str] = mapped_column(String(150))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    estimated_cost: Mapped[float | None] = mapped_column(Float)


class RetrievalRun(Identity, Base):
    __tablename__ = "retrieval_runs"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    intent: Mapped[str] = mapped_column(String(30))
    routes: Mapped[list] = mapped_column(Payload)
    returned: Mapped[int] = mapped_column(Integer)
    elapsed_ms: Mapped[float] = mapped_column(Float)
    created: Mapped[float] = mapped_column(Float, default=time)


class AuditEvent(Identity, Base):
    __tablename__ = "audit_events"
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_ref: Mapped[str] = mapped_column(String(36))
    event: Mapped[str] = mapped_column(String(50))
    created: Mapped[float] = mapped_column(Float, default=time)
