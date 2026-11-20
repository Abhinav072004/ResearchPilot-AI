import httpx
import pytest

from connectors import scholarly
from ingestion.observations import extract
from rag.engine import Evidence, Vectorless, plan, rrf


@pytest.mark.parametrize(("text", "intent"), [
    ("Find the paper 10.1234/test", "paper"), ("Define solar albedo", "definition"),
    ("How much hydrogen yield?", "numerical"), ("Compare gasification versus combustion", "comparison"),
    ("Literature review of energy storage", "review"), ("Recommend a method to manage tar", "recommendation"),
])
def test_query_routes(text, intent):
    assert plan(text).intent == intent


def test_rank_fusion_and_deduplication():
    assert rrf([["a", "a", "b"], ["b", "c"]]) == ["b", "a", "c"]
    item = Evidence("a", "doc", "Photovoltaics", "Albedo is defined as reflectance.", "Methods", "m")
    duplicate = Evidence("copy", "doc", "Photovoltaics", item.text, "Results", "r")
    irrelevant = Evidence("b", "other", "Light", "A telescope collects light.", "Results", "n")
    engine = Vectorless([item, duplicate, irrelevant], reranker=lambda _, rows: ["nonexistent", rows[0].id])
    assert [row.id for row in engine.search('Define "albedo"')] == ["a"]


def test_extraction_preserves_uncertainty():
    assert not list(extract("Measured hydrogen yield was between 10 and 11 mol/kg."))
    assert not list(extract("Measured hydrogen yield was 10 mol/kg ± 1 mol/kg."))
    obs = list(extract("The simulation predicts HHV was 12.00 MJ/kg; pressure was 0.1 MPa."))[0]
    assert obs["raw_value"] == "12.00" and obs["study_type"] == "simulation"
    assert obs["conditions"] == {"pressure": "0.1 MPa"}


def test_upstream_retry_after_limit(monkeypatch):
    calls = []
    url = "https://upstream.example.test"

    def send(self, *args, **kwargs):
        calls.append(args)
        return httpx.Response(429, request=httpx.Request("GET", url), headers={"Retry-After": "30"})

    monkeypatch.setattr(httpx.Client, "get", send)
    with pytest.raises(httpx.HTTPStatusError):
        scholarly.request(url)
    assert len(calls) == 1
