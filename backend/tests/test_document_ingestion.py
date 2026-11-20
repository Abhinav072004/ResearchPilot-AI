import json

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.main import app
from connectors import fulltext
from test_application import BASE, account, get_job, project, upload

DOI = "10.1234/fictional"
PMCID = "PMC123456789"
LICENSE = "https://creativecommons.org/licenses/by/4.0/"
TEXT = "The measured hydrogen yield is based on an independently calibrated experiment."
META = {"id": "123456", "source": "MED", "pmcid": PMCID, "doi": DOI, "isOpenAccess": "Y",
        "title": "Synthetic publication", "authorString": "Example A", "pubYear": "2024"}


def simulate_europe_pmc(monkeypatch, *, licence=LICENSE, article_doi=DOI, record=None):
    calls = []
    jats = f'''<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta>
      <article-id pub-id-type="doi">{article_doi}</article-id>
      <permissions><license xlink:href="{licence}"/></permissions>
      </article-meta></front><body><sec><title>Results</title><p>{TEXT}</p></sec></body></article>'''.encode()

    def read_response(client, path, limit, params=None):
        calls.append(path)
        if path == "/search":
            assert DOI in params["query"]
            return json.dumps({"resultList": {"result": [META if record is None else record]}}).encode()
        assert path == f"/{PMCID}/fullTextXML"
        return jats

    monkeypatch.setattr(fulltext, "read_response", read_response)
    return calls, jats


def test_licensed_import_persists_provenance_and_authorizes_download(client, monkeypatch):
    calls, jats = simulate_europe_pmc(monkeypatch)
    account(client, "licensed@example.test")
    scope = project(client)
    response = client.post(scope + "/papers/import", json={"doi": DOI.upper()})
    assert response.status_code == 202, response.text
    job = get_job(client, response.json()["id"])
    assert job["status"] == "succeeded", job
    assert calls == ["/search", f"/{PMCID}/fullTextXML"]
    document = job["result"]["document_id"]
    passages = client.get(scope + f"/papers/{document}/passages").json()
    assert passages[0]["text"] == TEXT
    assert passages[0]["access"] == "licensed_full_text"
    assert passages[0]["metadata"]["licence"] == LICENSE
    assert passages[0]["metadata"]["document_link"] == "verified_provider"
    assert client.get(scope + f"/papers/{document}/original").content == jats
    assert client.post(scope + "/papers/import", json={"doi": DOI}).status_code == 409
    assert client.post(scope + "/papers/import", json={"doi": "https://example.test/file"}).status_code == 422
    with TestClient(app) as outsider:
        account(outsider, "licensed-outsider@example.test")
        assert outsider.get(scope + f"/papers/{document}/original").status_code == 404
        assert outsider.post(scope + "/papers/import", json={"doi": DOI}).status_code == 404


@pytest.mark.parametrize(("opts", "message"), [
    ({"licence": "https://creativecommons.org/licenses/by-nc/4.0/"}, "licence"),
    ({"licence": "https://creativeCOMMONS.org.example.test/licenses/by/4.0/"}, "licence"),
    ({"article_doi": "10.1234/other"}, "DOI"),
    ({"record": {**META, "isOpenAccess": "N"}}, "open-access"),
    ({"record": {**META, "pubType": "Retracted Publication"}}, "Retracted"),
    ({"record": {**META, "pmcid": "../../unexpected"}}, "open-access"),
])
def test_full_text_rejects_unverified_rights_or_identity(monkeypatch, opts, message):
    simulate_europe_pmc(monkeypatch, **opts)
    with pytest.raises(ValueError, match=message):
        fulltext.fetch(DOI, 200_000)


def scanned_fixture():
    with pymupdf.open() as source:
        page = source.new_page(width=480, height=240)
        page.insert_text((25, 75), "Hydrogen yield from wheat straw", fontsize=25)
        page.insert_text((25, 115), "was measured in a pilot reactor.", fontsize=25)
        raster = page.get_pixmap(dpi=200, alpha=False)
        with pymupdf.open() as scanned:
            target = scanned.new_page(width=480, height=240)
            target.insert_image(target.rect, pixmap=raster)
            assert target.get_text() == ""
            return scanned.tobytes()


def test_image_only_pdf_becomes_searchable_with_page_and_ocr_anchors(client):
    account(client, "ocr@example.test")
    scope = project(client)
    result = upload(client, scope, scanned_fixture())
    assert result["status"] == "succeeded", result
    response = client.post(scope + "/retrieve", json={"query": "hydrogen yield wheat straw"})
    passage = response.json()["evidence"][0]
    assert "Hydrogen yield from wheat straw" in passage["text"]
    assert passage["page"] == 1
    assert passage["anchor"]["extractor"] == "tesseract"
    assert 0 <= passage["anchor"]["ocr_confidence"] <= 100
    assert passage["anchor"]["bbox"][2] > passage["anchor"]["bbox"][0]
