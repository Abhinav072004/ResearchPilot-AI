# Changelog

## Unreleased

- Added Tesseract OCR for image-only PDF pages with bounding boxes and word-confidence provenance.
- Added DOI-based Europe PMC imports for verified open-licence JATS full text.
- Added live scholarly checks, a ClamAV and S3-compatible service rehearsal, and a GitHub Actions production rollout with digest-pinned images and rollback.

- Milestone 0 documents the system, agent workflow, retrieval, ingestion, data model, HTTP contract and threat model.
- Milestone 1 adds database-backed accounts, cookie sessions, tenant-scoped projects and conversations.
- Milestone 2 adds official scholarly adapters with DOI resolution, provenance, bounded requests and pagination.
- Milestone 3 adds versioned PDF and XML ingestion, object storage, page and XML anchors, and source-linked numerical extraction.
- Milestone 4 adds adaptive vectorless retrieval, BM25, metadata and structural routes, SQL numerical filtering, rank fusion and an opt-in provider reranker.
- Milestone 5 adds supervised LangGraph execution, durable checkpoints, approval, event traces, extractive verification and optional model-checked synthesis.
- Milestone 6 adds structured observations, conservative comparison, and Markdown, DOCX and PDF report rendering.
- Milestone 7 adds fixture-based retrieval metrics, end-to-end permission and citation tests, rate limits, audit events, deletion, usage accounting, and dependency security checks.
- Milestone 8 adds the Compose stack, Docker images, release CI, health and metrics endpoints, export smoke test, and backup and restore scripts.
