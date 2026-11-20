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

## GitHub Actions production deployment

The **Verify and package** workflow exercises the frontend build, backend tests, migrations, a Compose HTTP smoke, dependency audits, S3-compatible operations and ClamAV detection. On trusted repository pushes it also runs a public Crossref and licensed Europe PMC check. A version tag or a manually requested production release publishes the API and gateway images to GitHub Container Registry. Deployment requires passing checks and uses image digests.

Prepare a Linux Docker host with Compose v2, an SSH user authorized to run Docker, enough memory for ClamAV, and a DNS name resolving to the host. Publish ports 80 and 443 for Caddy. Use a private PostgreSQL endpoint with `sslmode=verify-full`, authenticated private Redis, and a private encrypted S3 bucket. Grant the runtime identity the minimum required object permissions for project keys and the temporary `release-health/` prefix. Configure GHCR pull access on the host for private images. Keep the API and workers on the private Compose network.

Create the deployment root on the server and copy [the production environment template](../infrastructure/deployment/production.env.example) there as `.env`. Restrict access to the file. Set the real HTTPS hostname in both `RP_SITE_ADDRESS` and `RP_ORIGIN`. Supply database, Redis and storage settings through the host configuration. Caddy manages HTTPS certificates for the public hostname. ClamAV downloads signature updates and scans documents before parsing.

Configure a `production` environment in the repository's GitHub settings with these values.

| GitHub environment setting | Purpose |
| --- | --- |
| Variable `DEPLOY_HOST` | Reachable Docker server hostname or IPv4 address |
| Variable `DEPLOY_PORT` | SSH port if different from 22 |
| Variable `DEPLOY_USER` | Deployment SSH user |
| Variable `DEPLOY_ROOT` | Absolute directory with the host-only `.env` |
| Variable `DEPLOY_URL` | Public HTTPS origin |
| Secret `DEPLOY_SSH_KEY` | Private key for the deployment account |
| Secret `DEPLOY_KNOWN_HOSTS` | Trusted SSH host-key entry for the exact server and port |

From **Actions → Verify and package → Run workflow**, select `main` and enable **production**. To deploy automatically on version tags, set the repository variable `DEPLOY_ON_TAG=true` and protect release tags. The job pulls the pinned images, verifies the configured S3 bucket and ClamAV before installing the application, runs migrations, starts workers and gateways, and checks HTTPS readiness. Its release pointer advances after that check passes.

Allow outgoing HTTPS to the scholarly APIs you use. The built-in source hosts are `api.crossref.org`, `api.openalex.org`, `api.semanticscholar.org`, `export.arxiv.org`, `eutils.ncbi.nlm.nih.gov`, `www.ebi.ac.uk`, and `api.core.ac.uk`. OpenAlex and CORE use separately configured keys. Configure a model URL and credentials only for an approved provider. GROBID is optional and should use a private endpoint.

For integration checks on a disposable stack, run `infrastructure/deployment/verify-integrations.sh` after building the local Compose images. It checks the S3 API against Moto and scans a clean file and an inert EICAR fixture with ClamAV. The release runs the same storage and scanner probe against the configured production services.

For live validation from a permitted network, run from `backend`.

```sh
python -m evaluation.live_integrations
python -m evaluation.http_smoke https://staging.example.org --live-model
```

The second command uses the configured model with a synthetic question and requires `RP_LLM_MAX_CALLS=3` in the staging deployment. It checks approval, quote provenance and a known-answer judgement. Wider model quality requires a representative evaluation corpus.

## Release rollback

Take a database backup and capture the object-storage version point before releases. The deployment host retains prior release manifests and image digests under `releases/`. If rollout fails, the release script reapplies the previous image digests when available. Keep migrations backward-compatible for image rollback. For an incompatible schema change, restore the database and object store into a fresh location, run smoke checks there, and then switch traffic.

## Backup and retention

From the repository root, `infrastructure/deployment/backup.sh <new-file>` makes and checks a PostgreSQL custom-format dump from the Compose database, including LangGraph checkpoints. `infrastructure/deployment/restore-drill.sh <file>` restores into a temporary database, verifies the schema and projects, then removes the temporary database. Run both on a disposable or adequately provisioned instance. Treat the dump as sensitive.

For a complete managed restore, enable PostgreSQL point-in-time recovery and S3 object versioning. Record a common restore point while writes are paused. Restore both into staging, compare checksums for representative original files, inspect their evidence pages, and download a report. Retain backups according to the organization policy. Project deletion purges active originals, generated reports, checkpoint threads and relational records. Versioned object history and backups expire under their own lifecycle rules.

## Monitoring and capacity

Poll /health/live and /health/ready and scrape /metrics directly from the private API network. Ship API request duration and status logs, worker failures and audit events to the deployment's log aggregation. Alert on elevated HTTP error or latency rates and queued job age. Check job and audit records when investigating individual failures. Worker readiness probes the Celery process through Redis.

The API records provider-reported token counts and estimated cost when prices are configured. Default research uses no paid model calls. External reranking and synthesis require project-user approval. Reranking sends at most twelve clipped passages per call. Set `RP_LLM_MAX_CALLS=3` to enable ranking, synthesis and claim checking in one run. The application reserves each model call before sending data and records provider-reported usage when available. Workers use prefetch one and a hard job time limit. Scale concurrency against observed queue age and parser memory pressure. PostgreSQL narrows candidates with a GIN index in larger corpora. Monitor its query plan and recompute corpus benchmarks when switching indexing strategies.
