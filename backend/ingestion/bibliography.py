"""Bibliographic fields declared by an ingested file."""

import pymupdf
from defusedxml import ElementTree

from connectors.scholarly import normalize_doi


def bibliography(content, content_type):
    if content_type == "application/pdf":
        with pymupdf.open(stream=content, filetype="pdf") as source:
            metadata = source.metadata or {}
            return {key: metadata[key].strip()[:600] for key in ("title", "author", "subject")
                    if isinstance(metadata.get(key), str) and metadata[key].strip()}
    root = ElementTree.fromstring(content)
    for element in root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]
    front = root.find(".//front")
    if front is None:
        return {}

    def copy(node):
        return " ".join(" ".join(node.itertext()).split()) if node is not None else ""

    authors = []
    for person in front.findall(".//contrib[@contrib-type='author']")[:500]:
        name = " ".join(filter(None, [copy(person.find(".//given-names")), copy(person.find(".//surname"))]))
        if name:
            authors.append(name)
    meta = {
        "title": copy(front.find(".//article-title"))[:600],
        "abstract": copy(front.find(".//abstract"))[:12_000],
        "journal": copy(front.find(".//journal-title"))[:600],
        "declared_doi": normalize_doi(front.findtext(".//article-id[@pub-id-type='doi']")),
        "year": copy(front.find(".//pub-date/year"))[:4],
        "authors": authors,
        "article_type": root.get("article-type"),
    }
    return {key: value for key, value in meta.items() if value}
