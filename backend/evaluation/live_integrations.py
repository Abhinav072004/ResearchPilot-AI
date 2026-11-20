"""Check public scholarly APIs with a real, open-access publication."""

from time import time

from connectors.fulltext import fetch
from connectors.scholarly import resolve_doi
from ingestion.parser import parse

DOI = "10.1371/journal.pmed.1000097"


def check_scholarly():
    metadata = resolve_doi(DOI, int(time() // 300))
    assert metadata["doi"] == DOI and "PRISMA" in metadata["title"]
    article = fetch(DOI, 15 * 1024 * 1024)
    assert article.record["doi"] == DOI and article.provenance["licence"].startswith("https://creativecommons.org/")
    blocks = parse(article.content, "application/xml")
    assert len(blocks) > 10 and any("PRISMA" in block.text for block in blocks)
    print(f"Crossref DOI and Europe PMC licensed JATS passed for {DOI}. Parsed {len(blocks)} blocks.")


if __name__ == "__main__":
    check_scholarly()
