# HTTP contract

JSON endpoints use /api/v1. Collection endpoints take pagination where applicable. Private endpoints require a valid session and project membership. Errors use HTTP status with a human-readable detail. Invalid input returns 422, conflicts return 409, exhausted rate limits return 429, and unavailable upstream providers return 502 or 503. Nonmembers receive 404 for private resources.

| Method and path | Request → response |
| --- | --- |
| POST /auth/register, /auth/login | Email and password → identity and session |
| GET /auth/me | Session → identity |
| POST /auth/logout | Session → revoked session |
| GET, POST /projects | Paging or title → projects or created project |
| GET, PATCH, DELETE /projects/{project_id} | Project ID and optional title → project or queued deletion |
| GET, POST /projects/{project_id}/conversations | Paging or title → conversations or created conversation |
| GET, PATCH, DELETE /conversations/{id} | Conversation ID and optional title → conversation or deletion |
| POST /conversations/{id}/messages | Message body → persisted message |
| GET /literature/search | Query, provider, limit, cursor → source records |
| GET /literature/doi | DOI → verified metadata and access classification |
| POST /projects/{project_id}/papers | Multipart authorized upload → ingestion job |
| POST /projects/{project_id}/papers/import | DOI → queued Europe PMC licence and full-text import |
| GET /projects/{project_id}/papers | → available versions and ingestion states |
| GET /projects/{project_id}/papers/{document_id}/passages | Offset → page-anchored passages |
| GET /projects/{project_id}/papers/{document_id}/original | → authorized original download |
| GET /projects/{project_id}/jobs | → recent ingestion, research and report jobs |
| GET /projects/{project_id}/usage | → project-scoped model usage and estimated costs |
| GET /jobs/{id}/timeline | → recorded agent and job stages |
| GET /jobs/{id} | → current status, result or error |
| GET /jobs/{id}/events | → durable status events via SSE |
| POST /projects/{project_id}/retrieve | Query and filters → ranked evidence |
| POST /projects/{project_id}/research | Query and optional research settings → run job |
| POST /jobs/{id}/approval | Approval decision → updated run |
| GET /evidence/{id} | → authorized original passage and provenance |
| GET /projects/{project_id}/observations | Metric and unit filters → source-linked results |
| POST /projects/{project_id}/compare | Paper IDs and metric → matched findings and gaps |
| POST /projects/{project_id}/reports | Verified research run and title → export job |
| GET /reports/{id}/export | Format → authorized artifact |
| GET /reports/{id}/references | APA or IEEE style → bibliographic text download |
| GET /health/live, /health/ready | → process and dependency health |

The generated OpenAPI schema describes the implemented contract. The architecture table includes later endpoints.
