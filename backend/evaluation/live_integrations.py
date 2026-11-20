"""Check public scholarly APIs with a real, open-access publication."""

import os
from time import time

import httpx

from connectors.fulltext import fetch
from connectors.scholarly import resolve_doi
from ingestion.parser import parse

DOI = "10.1371/journal.pmed.1000097"


def check_crossref():
    metadata = resolve_doi(DOI, int(time() // 300))
    if metadata["doi"] != DOI or "prisma" not in metadata["title"].casefold():
        raise ValueError("Unexpected Crossref identity for the benchmark DOI")
    return f"Resolved {DOI} and checked the article title."


def check_europe_pmc():
    article = fetch(DOI, 15 * 1024 * 1024)
    if article.record["doi"] != DOI or not article.provenance["licence"].startswith("https://creativecommons.org/"):
        raise ValueError("Unexpected Europe PMC identity or licence for the benchmark DOI")
    blocks = parse(article.content, "application/xml")
    if len(blocks) <= 10 or not any("PRISMA" in block.text for block in blocks):
        raise ValueError("The imported JATS did not contain the expected PRISMA article content")
    return f"Verified the reuse licence and parsed {len(blocks)} blocks."


def report(provider, check):
    try:
        print(f"{provider} passed. {check()}")
    except (ValueError, KeyError, TypeError, httpx.HTTPError) as exc:
        if isinstance(exc, httpx.HTTPStatusError):
            reason = f"HTTP {exc.response.status_code}"
        elif isinstance(exc, httpx.HTTPError):
            reason = type(exc).__name__
        else:
            reason = str(exc)
        detail = reason.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        prefix = f"::error title={provider} live check::" if os.getenv("GITHUB_ACTIONS") else f"{provider} failed. "
        print(prefix + detail)
        return False
    return True


if __name__ == "__main__":
    results = (report("Crossref", check_crossref), report("Europe PMC", check_europe_pmc))
    raise SystemExit(0 if all(results) else 1)
