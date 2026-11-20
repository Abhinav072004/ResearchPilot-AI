# ResearchPilot AI

ResearchPilot AI is a research workspace for scholarly discovery, source-linked numerical comparison, and evidence-grounded reports. It uses adaptive vectorless retrieval and a checkpointed LangGraph workflow.

- [System architecture](docs/architecture.md)
- [Database and ER diagram](docs/database.md)
- [API contract](docs/api.md)
- [Security and privacy](docs/security.md)
- [Deployment, backup and rollback](docs/deployment.md)
- [Retrieval evaluation](docs/evaluation.md)
- [Changelog](CHANGELOG.md)

## Run locally

With Docker and Compose v2, copy .env.example to .env and run `docker compose up -d --build --wait`. Open the gateway at `http://localhost:8080`, register, create a project, and upload an authorized PDF or XML file. The scholarly workspace queries official APIs when those hosts are reachable. The research workflow also runs locally against uploaded documents with external discovery and reranking disabled.

For a lightweight coding loop, use Python 3.12, Node.js 24, and Tesseract with English language data. In the repository root, create a virtual environment and install backend dependencies.

```sh
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt pytest
(cd backend && ../.venv/bin/python -m app.release)
(cd backend && ../.venv/bin/uvicorn app.main:app --reload --port 8000)
```

In another shell, `cd frontend && npm ci && npm run dev`. Vite proxies same-origin API requests. The lightweight path uses SQLite, local object files and in-process background tasks. Compose uses PostgreSQL, Redis and separate workers.

```sh
(cd backend && ../.venv/bin/python -m pytest -q)
(cd backend && ../.venv/bin/python -m evaluation.retrieval_benchmark)
(cd frontend && npm run build)
```

## Implemented scope

Start from a suggested question or add your own papers. The published-source example runs a real DOI search and licensed import. The sidebar reopens saved research runs, and citation buttons open the supporting passage.

The workspace provides accounts, owner-managed workspace roles, projects and conversations, scholarly search and DOI resolution, page-anchored PDF and structured XML ingestion, adaptive retrieval, checkpointed research with streaming verified excerpts, domain-aware comparison, and Markdown, DOCX and PDF exports. Enable discovery on a question to verify candidate DOIs, reuse or import eligible licensed full text, and cite the resulting passages in the same run. Document processing and report generation run as jobs. After project-user approval, an optional LLM can rerank passages and propose a synthesis. Synthesized claims require stored quotes and a separate model judgment and are labeled in the report. The default workflow extracts and verifies quotes locally.

The PDF pipeline extracts native text, detects table grids, and runs Tesseract on scanned pages without a text layer. Optional private GROBID and Docling services enrich structure. JATS imports preserve bibliography and separate table cells, equations, references and figure captions with source anchors. The Library can import eligible full text from Europe PMC or PubMed Central by DOI and preserve the source and reuse licence with every excerpt. Scholarly provider availability, licence, retraction coverage and full-text access vary by source. Numerical extraction uses explicit metric, unit and comparison-context profiles for chemical engineering, energy, computing, medicine, physics, biology, environmental science, materials and business. These are bounded profiles. Unfamiliar measures remain available as cited text, and values with missing context remain unmatched.

## Deploy with GitHub Actions

The **Verify and package** workflow tests the stack and can publish immutable images and deploy them to a configured HTTPS Docker host. See [production setup and rollout](docs/deployment.md#github-actions-production-deployment).
