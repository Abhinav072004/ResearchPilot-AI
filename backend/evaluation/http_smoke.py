"""Exercise the deployed HTTP stack with synthetic evidence and a fresh test account."""

import argparse
import secrets
from time import monotonic, sleep

import httpx

from app.reports import MIME


def smoke(origin, large_corpus=False, live_model=False):
    base = origin.rstrip("/") + "/api/v1"
    with httpx.Client(timeout=12) as client:
        def call(method, path, **kwargs):
            response = client.request(method, base + path, **kwargs)
            response.raise_for_status()
            return response

        def wait(job_id, expected="succeeded"):
            expires = monotonic() + 45
            while monotonic() < expires:
                state = call("GET", f"/jobs/{job_id}").json()
                if state["status"] not in ("queued", "running"):
                    assert state["status"] == expected, state
                    return state
                sleep(0.4)
            raise TimeoutError(f"Timed out waiting for job {job_id}")

        client.get(origin.rstrip("/") + "/health/ready").raise_for_status()
        account = secrets.token_hex(6)
        call("POST", "/auth/register", json={"email": f"smoke-{account}@example.test",
                                             "password": secrets.token_urlsafe(24)})
        project = call("POST", "/projects", json={"title": "Synthetic release smoke"}).json()["id"]
        scope = "/projects/" + project
        evidence = "Synthetic albedo is defined as the fraction of incoming light reflected by a surface."
        filler = "".join(f"<p>Unrelated telescope paragraph {i}.</p>" for i in range(4100)) if large_corpus else ""
        xml = f"<article><body>{filler}<p>{evidence}</p></body></article>".encode()
        upload = call("POST", scope + "/papers", files={"file": ("smoke.xml", xml, "application/xml")},
                      data={"title": "Synthetic release fixture", "permitted": "true"})
        wait(upload.json()["id"])
        run_id = call("POST", scope + "/research", json={"query": "What is albedo?"}).json()["id"]
        run = wait(run_id)
        claim = run["result"]["claims"][0]
        passage = call("GET", "/evidence/" + claim["passage_id"]).json()
        assert claim["text"] == evidence and evidence in passage["text"]
        if live_model:
            model_run = call("POST", scope + "/research", json={
                "query": "What fraction does the fixture use to define albedo?",
                "external_model": True, "synthesize": True,
            }).json()["id"]
            wait(model_run, "awaiting_approval")
            call("POST", f"/jobs/{model_run}/approval", json={"approved": True})
            checked = wait(model_run)["result"]["claims"]
            grounded = [item for item in checked if item["type"] == "model_checked_synthesis"]
            assert grounded and all(
                "albedo" in item["text"].lower() and "reflect" in item["text"].lower()
                and all(quote in evidence for quote in item["quotes"])
                for item in grounded
            ), "Configured model failed the synthetic albedo grounding check"
            print(f"Live model passed the known-answer grounding check with {len(grounded)} model-checked claims.")
        report_id = call("POST", scope + "/reports", json={"research_id": run_id, "title": "Smoke"}).json()["id"]
        wait(report_id)
        for output_type, (mime, _) in MIME.items():
            export = call("GET", f"/reports/{report_id}/export", params={"format": output_type})
            assert export.headers["content-type"].split(";")[0] == mime and export.content
        call("POST", "/auth/logout")
        assert client.get(base + "/evidence/" + claim["passage_id"]).status_code == 401
        print("Passed readiness, authentication, worker ingestion, cited research, evidence lookup and all report exports.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin", help="URL for a disposable deployment")
    parser.add_argument("--large-corpus", action="store_true", help="Exercise the indexed PostgreSQL candidate path")
    parser.add_argument("--live-model", action="store_true", help="Evaluate an approved configured model on a synthetic question")
    args = parser.parse_args()
    smoke(args.origin, args.large_corpus, args.live_model)
