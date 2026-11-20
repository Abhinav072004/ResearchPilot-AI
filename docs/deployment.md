# Deployment and operations

## Local release rehearsal

Docker Engine with Compose v2 is required. Copy .env.example to .env, update the database password, and keep the local gateway bound to loopback. Run from the repository root.

```sh
cp .env.example .env
docker compose up -d --build --wait --wait-timeout 180
docker compose ps
```

The migration service upgrades PostgreSQL and initializes the LangGraph checkpoint schema. The gateway terminates HTTP in local development. Repository code and container configuration are shared with the production setup. The PostgreSQL and Redis ports are private to Compose.

A TLS-intercepting corporate build network can supply its trusted CA bundle as the BuildKit secret `researchpilot_build_ca` on each service's build. The Python install uses it as the pip CA bundle and the JS install uses it as additional CA material. Runtime Python HTTP clients can use a separately mounted trust bundle via `SSL_CERT_FILE`. Preserve TLS verification and keep build trust configuration outside application images.

```sh
RP_BUILD_CA_FILE="$SSL_CERT_FILE" docker compose -f docker-compose.yml \
  -f infrastructure/deployment/compose.build-ca.yml up -d --build --wait
```

The production smoke script creates synthetic disposable data and exercises authenticated ingestion, a worker-driven research run, evidence inspection and three export formats. Run from backend with the dependencies installed.

```sh
python -m evaluation.http_smoke http://localhost:8080 --large-corpus
# Optional Chromium UI check.
pip install playwright==1.65.2
playwright install chromium
python -m evaluation.browser_smoke http://localhost:8080
```

## HTTPS release

Use a single Caddy ingress and deploy APIs, workers and the job recovery scheduler separately. Set `RP_SITE_ADDRESS` to an HTTPS hostname with matching DNS, publish ports 80 and 443, set `RP_ENVIRONMENT=production`, `RP_SECURE_COOKIE=true`, and set `RP_ORIGIN` to the same scheme and host. Caddy enables automatic HTTPS for a real domain. Expose only the gateway. Uvicorn trusts forwarding headers from the private network. Restrict entry to that network so only the gateway can reach the API listener.

Use a managed PostgreSQL endpoint with `sslmode=verify-full`, an authenticated private Redis endpoint, and a private encrypted S3-compatible bucket. Set AWS credentials or attach an identity to API and worker deployments. Grant access only to this deployment's bucket. The worker scans input through a private ClamAV endpoint before parsing. Bring up the `scanner` Compose profile if running it locally and set `RP_CLAMD_HOST=scanner` after signature updates complete. Confirm S3 puts and reads and scanner use with the staging smoke before admitting traffic. Optional GROBID runs on a private network and receives the authorized PDF only.

Allow outgoing HTTPS to the enabled sources. Hostnames are `api.crossref.org`, `api.openalex.org`, `api.semanticscholar.org`, `export.arxiv.org`, `eutils.ncbi.nlm.nih.gov`, `www.ebi.ac.uk`, and `api.core.ac.uk`. OpenAlex and CORE use separately configured keys. Configure an approved model API and credentials only if project users may send their evidence there. Store credentials in the deployment secret manager.

## Release and rollback

CI runs tests, retrieval evaluation, dependency audits, frontend build and the local Compose smoke. Version tags publish both images to the repository's GitHub Container Registry. Pin release image digests in the deployment environment and retain the previous digests. Take a database backup and capture the object-storage version point before each release. Run a single migration job, bring up the API, then start the worker, scheduler and gateway. Run the smoke against staging first.

For rollback, pause new traffic, allow active jobs to drain and restore the previous digests if the schema changes are backward-compatible. If a migration made an incompatible change, restore the previous database and object-store state to a fresh location, validate with smoke, then switch traffic. Avoid running an Alembic downgrade against live data without testing it on an isolated copy.

## Backup and retention

From the repository root, `infrastructure/deployment/backup.sh <new-file>` makes and checks a PostgreSQL custom-format dump from the Compose database, including LangGraph checkpoints. `infrastructure/deployment/restore-drill.sh <file>` restores into a temporary database, verifies the schema and projects, then removes the temporary database. Run both on a disposable or adequately provisioned instance. Treat the dump as sensitive.

For a complete managed restore, enable PostgreSQL point-in-time recovery and S3 object versioning. Record a common restore point while writes are paused. Restore both into staging, compare checksums for representative original files, inspect their evidence pages, and download a report. Retain backups according to the organization policy. Project deletion purges active originals, generated reports, checkpoint threads and relational records. Versioned object history and backups expire under their own lifecycle rules.

## Monitoring and capacity

Poll /health/live and /health/ready and scrape /metrics directly from the private API network. Ship API request duration and status logs, worker failures and audit events to the deployment's log aggregation. Alert on elevated HTTP error or latency rates and queued job age. Check job and audit records when investigating individual failures. Worker readiness probes the Celery process through Redis.

The API records provider-reported token counts and estimated cost when prices are configured. Default research uses no paid model calls. External reranking and synthesis require project-user approval. Reranking sends at most twelve clipped passages per call. Set `RP_LLM_MAX_CALLS=3` to enable ranking, synthesis and claim checking in one run. The application reserves each model call before sending data and records provider-reported usage when available. Workers use prefetch one and a hard job time limit. Scale concurrency against observed queue age and parser memory pressure. PostgreSQL narrows candidates with a GIN index in larger corpora. Monitor its query plan and recompute corpus benchmarks when switching indexing strategies.
