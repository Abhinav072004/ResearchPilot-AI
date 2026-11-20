import httpx
import pymupdf
from fastapi.testclient import TestClient
from sqlalchemy import select

from agents import supervisor
from app.config import settings
from app.db import Session
from app.main import app
from app.models import Job, ResearchQuery, RetrievalRun
from ingestion import docling_client
from ingestion.observations import extract
from test_application import BASE, account, get_job, project, upload
from test_document_ingestion import DOI, META, simulate_europe_pmc


def test_research_discovers_imports_cites_and_reuses_licensed_paper(client, monkeypatch):
    calls, _ = simulate_europe_pmc(monkeypatch)
    monkeypatch.setattr(supervisor, "resolve_doi", lambda doi, _: {
        "doi": doi, "title": META["title"], "retracted": False, "publication_type": "journal-article",
    })
    account(client, "autodiscovery@example.test")
    scope = project(client)
    conversation = client.post(scope + "/conversations", json={"title": "Discovery history"}).json()["id"]
    for reused in (False, True):
        response = client.post(scope + "/research", json={"query": f"What hydrogen yield was reported in {DOI}?",
                                                          "discover": True, "domain": "chemical_engineering",
                                                          "conversation_id": conversation})
        assert response.status_code == 202
        job_id = response.json()["id"]
        run = get_job(client, job_id)
        assert run["status"] == "succeeded", run
        imported, = run["result"]["imported_papers"]
        assert imported["reused"] is reused
        claim = run["result"]["claims"][0]
        evidence = client.get(BASE + "/evidence/" + claim["passage_id"]).json()
        assert evidence["doi"] == DOI and evidence["access"] == "licensed_full_text"
        assert claim["text"] in evidence["text"]
        with Session() as db:
            measurement = db.scalar(select(RetrievalRun).where(RetrievalRun.job_id == job_id))
            assert measurement.returned and measurement.elapsed_ms >= 0
            history = db.scalar(select(ResearchQuery).where(ResearchQuery.job_id == job_id))
            assert history.conversation_id == conversation and history.domain == "chemical_engineering"
    assert len(calls) == 2 and len(client.get(scope + "/papers").json()) == 1


def test_verified_partial_results_are_available_before_model_synthesis(client, monkeypatch):
    account(client, "progress-excerpts@example.test")
    scope = project(client)
    upload(client, scope, b"<article><body><p>The experiment measured yield using a calibrated instrument.</p></body></article>")
    config = settings()
    monkeypatch.setattr(config, "llm_model", "fixture")
    monkeypatch.setattr(config, "llm_url", "https://model.example.test")
    monkeypatch.setattr(config, "llm_key", "fixture")
    monkeypatch.setattr(config, "llm_max_calls", 3)
    monkeypatch.setattr(supervisor.ModelBudget, "rerank", lambda *_: [])
    response = client.post(scope + "/research", json={
        "query": "How was yield measured?", "external_model": True, "synthesize": True,
    })
    job_id = response.json()["id"]
    assert get_job(client, job_id)["status"] == "awaiting_approval"
    observed = []

    def inspect_progress(*_):
        with Session() as db:
            job = db.get(Job, job_id)
            observed.append([job.status, job.result["claims"][0]["claim_id"]])
        return []

    monkeypatch.setattr(supervisor, "propose", inspect_progress)
    assert client.post(BASE + f"/jobs/{job_id}/approval", json={"approved": True}).status_code == 202
    final = get_job(client, job_id)
    assert observed == [["running", final["result"]["claims"][0]["claim_id"]]]


def test_table_cells_and_reference_are_stored_as_citable_artifacts(client):
    account(client, "structured-paper@example.test")
    scope = project(client)
    source = b'''<article><front><article-meta><title-group><article-title>Trial sample</article-title></title-group>
      <abstract><p>The trial measured diagnostic sensitivity.</p></abstract></article-meta></front>
      <body><table-wrap><caption><p>Results from a measured trial.</p></caption>
      <table><thead><tr><th>Population</th><th>Diagnostic sensitivity (%)</th></tr></thead>
      <tbody><tr><td>Adults</td><td>98.20</td></tr></tbody></table></table-wrap></body>
      <back><ref-list><ref><label>1</label><mixed-citation>Reference paper <pub-id pub-id-type="doi">10.1234/ref</pub-id>
      </mixed-citation></ref></ref-list></back></article>'''
    job = upload(client, scope, source)
    assert job["status"] == "succeeded", job
    document_id = job["result"]["document_id"]
    result = client.get(scope + f"/papers/{document_id}/structure").json()
    assert result["bibliography"]["title"] == "Trial sample"
    table, reference = result["artifacts"]
    assert table["data"]["cells"][-1]["text"] == "98.20"
    assert table["anchor"]["xml_path"] and reference["data"]["doi"] == "10.1234/ref"
    measurements = client.get(scope + "/observations", params={"domain": "medicine"}).json()
    observation, = measurements
    assert observation["value"] == "98.20" and observation["unit"] == "%"
    assert observation["measurement_anchor"] == {"row": 1, "column": 1}
    assert observation["passage_id"] == table["passage_id"]
    experiments = client.get(scope + "/experiments", params={"domain": "medicine"}).json()
    experiment, = experiments
    assert experiment["id"] == observation["experiment_id"]
    assert experiment["conditions"]["population"] == "adults"
    assert client.get(scope + "/observations", params={"domain": "physics"}).json() == []


def test_docling_adapter_converts_table_provenance(monkeypatch):
    monkeypatch.setattr(settings(), "docling_url", "http://docling.private:5001")
    response = {
        "status": "success", "document": {"json_content": {
            "pages": {"2": {"size": {"height": 800}}},
            "tables": [{"prov": [{"page_no": 2, "bbox": {"l": 10, "t": 700, "r": 30, "b": 650,
                                                        "coord_origin": "BOTTOMLEFT"}}],
                        "data": {"table_cells": [{
                            "start_row_offset_idx": 0, "start_col_offset_idx": 0,
                            "row_span": 1, "col_span": 2, "column_header": True, "text": "Performance",
                        }]}}],
        }},
    }

    def stream(method, url, **kwargs):
        assert kwargs["files"]["files"][1] == b"%PDF"
        assert kwargs["follow_redirects"] is False
        return httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response))).stream(method, url)

    monkeypatch.setattr(docling_client.httpx, "stream", stream)
    table, = docling_client.extract_tables(b"%PDF")
    assert table[:2] == (2, [10.0, 100.0, 30.0, 150.0])
    assert table[2]["cells"][0]["colspan"] == 2


def test_physics_units_are_case_sensitive_and_raw_value_is_preserved():
    observation, = list(extract("Measured electrical resistivity was 2.20 Ω·m at temperature of 290 K."))
    assert observation["domain"] == "physics" and observation["raw_value"] == "2.20"
    assert not list(extract("Measured electrical resistivity was 2.20 Ω·cm²."))
    assert not list(extract("The trial reported odds ratio was 1.10–1.85."))
    ratio, = list(extract("The trial reported odds ratio was 1.10."))
    assert ratio["raw_value"] == "1.10" and ratio["unit"] == "unitless"


def test_workspace_owner_grants_changes_and_revokes_roles(client):
    account(client, "workspace-owner@example.test")
    scope = project(client)
    team_path = scope + "/team"
    with TestClient(app) as member:
        account(member, "workspace-viewer@example.test")
        assert member.get(scope).status_code == 404
        invitation = client.post(team_path, json={"email": "workspace-viewer@example.test", "role": "viewer"})
        assert invitation.status_code == 201, invitation.text
        member_id = invitation.json()["id"]
        assert member.get(scope).status_code == 200
        assert member.patch(scope, json={"title": "Viewer revision"}).status_code == 404
        assert member.post(team_path, json={"email": "workspace-owner@example.test", "role": "editor"}).status_code == 403
        assert client.patch(team_path + "/" + member_id, json={"role": "editor"}).status_code == 200
        assert member.patch(scope, json={"title": "Editor revision"}).status_code == 200
        assert client.delete(team_path + "/" + member_id).status_code == 204
        assert member.get(scope).status_code == 404


def test_native_pdf_tables_link_to_the_page_without_optional_service(client):
    from evaluation.docling_smoke import sample

    account(client, "pdf-table@example.test")
    scope = project(client)
    job = upload(client, scope, sample())
    assert job["status"] == "succeeded", job
    document_id = job["result"]["document_id"]
    structure = client.get(scope + f"/papers/{document_id}/structure").json()
    table = next(entry for entry in structure["artifacts"] if entry["kind"] == "table")
    assert table["page"] == 1 and table["anchor"]["extractor"] == "pymupdf-table"
    assert {"Hydrogen yield", "12.50", "mol/kg"} <= {cell["text"] for cell in table["data"]["cells"]}
