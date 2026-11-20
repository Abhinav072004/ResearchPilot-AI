# Database architecture

```mermaid
erDiagram
    USER ||--o{ MEMBERSHIP : joins
    ORGANIZATION ||--o{ MEMBERSHIP : grants
    ORGANIZATION ||--o{ PROJECT : owns
    PROJECT ||--o{ CONVERSATION : contains
    CONVERSATION ||--o{ MESSAGE : contains
    PROJECT ||--o{ RESEARCH_QUERY : initiates
    PROJECT ||--o{ PROJECT_PAPER : accesses
    PAPER ||--o{ PROJECT_PAPER : references
    PAPER ||--o{ SOURCE : verified_by
    PAPER ||--o{ PAPER_AUTHOR : credits
    AUTHOR ||--o{ PAPER_AUTHOR : writes
    LICENCE ||--o{ DOCUMENT_VERSION : governs
    PROJECT_PAPER ||--o{ DOCUMENT_VERSION : publishes
    FILE_ASSET ||--o{ DOCUMENT_VERSION : contains
    DOCUMENT_VERSION ||--o{ SECTION : contains
    SECTION ||--o{ PASSAGE : contains
    DOCUMENT_VERSION ||--o{ DOCUMENT_TABLE : contains
    DOCUMENT_VERSION ||--o{ FIGURE : contains
    DOCUMENT_VERSION ||--o{ EQUATION : contains
    DOCUMENT_VERSION ||--o{ REFERENCE : cites
    DOCUMENT_VERSION ||--o{ EXPERIMENT : describes
    EXPERIMENT ||--o{ OBSERVATION : records
    PASSAGE ||--o{ OBSERVATION : grounds
    RESEARCH_QUERY ||--o{ RETRIEVAL_RUN : triggers
    RESEARCH_QUERY ||--o{ AGENT_RUN : triggers
    RESEARCH_QUERY ||--o{ REPORT : produces
    REPORT ||--o{ CLAIM : contains
    CLAIM ||--o{ EVIDENCE_LINK : supports
    PASSAGE ||--o{ EVIDENCE_LINK : grounds
    CLAIM ||--o{ CITATION : cites
    ORGANIZATION ||--o{ AUDIT_EVENT : records
    ORGANIZATION ||--o{ USAGE_RECORD : accrues
```

Use UUID primary keys and foreign keys. Normalize DOI case and enforce uniqueness for non-null DOI. Preserve source-specific external IDs and fetched timestamps. Index tenant, project, version, job state and normalized metadata. Search indexes store derived text and can be rebuilt. Use relational columns for observation value, metric and unit, with JSONB for domain-specific conditions. Evidence links refer to immutable versions and passages. Every path to private content begins with the caller's project membership. Original assets live in private object storage. Define retention and backup policies for each deployment before onboarding confidential data.


## Current storage

Migrations include normalized authors and ordered paper credits, licence URLs, document versions, sections, passages, observations, and typed document artifacts. Tables, figures, equations and references share the artifact table with a type discriminator and retain a passage foreign key. Research, agent and report runs use typed job records and job events. Retrieval runs record routing, latency and result count. A claim's evidence links are its citations. The diagram describes the logical model. The executable schema is defined by the Alembic revisions.
