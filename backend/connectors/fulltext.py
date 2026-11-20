"""Fetch licensed JATS articles from Europe PMC's fixed API endpoints."""

import json
import re
from dataclasses import dataclass
from time import monotonic
from urllib.parse import urlsplit

import httpx
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from connectors.scholarly import europe_pmc, normalize_doi

EUROPE_PMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
PMCID = re.compile(r"PMC[1-9][0-9]{0,9}")
# Limit automatic reuse to explicit, unrestricted text licenses and public-domain dedication.
LICENSE_PATH = re.compile(r"/(?:licenses/by/(?:2\.0|2\.5|3\.0|4\.0)|publicdomain/zero/1\.0)/?")


@dataclass(frozen=True)
class LicensedArticle:
    content: bytes
    record: dict
    provenance: dict


def open_license(value):
    try:
        url = urlsplit(value.strip())
    except ValueError:
        return None
    if (url.scheme in {"https", "http"} and url.netloc.lower() in {"creativecommons.org", "www.creativecommons.org"}
            and not url.query and not url.fragment and LICENSE_PATH.fullmatch(url.path)):
        return "https://creativecommons.org" + url.path.rstrip("/") + "/"
    return None


def read_response(client, path, limit, params=None):
    started = monotonic()
    with client.stream("GET", EUROPE_PMC + path, params=params) as response:
        response.raise_for_status()
        content = bytearray()
        for chunk in response.iter_bytes(chunk_size=65536):
            if len(content) + len(chunk) > limit:
                raise ValueError("The full-text provider response exceeds the size limit")
            if monotonic() - started > 30:
                raise ValueError("The full-text provider response exceeded the download time limit")
            content.extend(chunk)
        return bytes(content)


def fetch(doi, limit):
    doi = normalize_doi(doi)
    if not doi:
        raise ValueError("A valid DOI is required for licensed import")
    try:
        with httpx.Client(timeout=httpx.Timeout(12, connect=5), follow_redirects=False) as client:
            data = json.loads(read_response(client, "/search", 512_000, {
                "query": f'DOI:"{doi}" AND IN_PMC:Y', "format": "json", "resultType": "core", "pageSize": 10,
            }))
            matching = [row for row in data["resultList"]["result"] if normalize_doi(row.get("doi")) == doi]
            eligible = [row for row in matching if row.get("isOpenAccess") == "Y" and row.get("title")
                        and PMCID.fullmatch(row.get("pmcid") or "")]
            if not eligible:
                raise ValueError("Europe PMC does not list open-access full text for this DOI")
            candidate = eligible[0]
            if any(europe_pmc(row)["retracted"] is True or "retraction" in (row.get("pubType") or "").lower()
                   for row in matching):
                raise ValueError("Retracted articles and retraction notices cannot be imported")
            pmcid = candidate["pmcid"]
            content = read_response(client, f"/{pmcid}/fullTextXML", limit)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise ValueError("Europe PMC did not return full text for this DOI") from exc
        raise ValueError("Europe PMC full-text service is unavailable") from exc
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("Europe PMC full-text service is unavailable or returned invalid metadata") from exc

    try:
        root = ElementTree.fromstring(content)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise ValueError("Europe PMC did not return valid article XML") from exc
    for element in root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]
    metadata = root.find("./front/article-meta")
    if root.tag != "article" or metadata is None or root.find("body") is None:
        raise ValueError("The provider response does not contain a complete JATS article")
    identifiers = {normalize_doi(node.text) for node in metadata.findall("article-id") if node.get("pub-id-type") == "doi"}
    if identifiers != {doi}:
        raise ValueError("The downloaded article DOI does not match the requested DOI")
    licences = metadata.findall("./permissions/license")
    approved = {
        open_license(node.get("{http://www.w3.org/1999/xlink}href", ""))
        for node in licences
    }
    if len(approved) != 1 or None in approved:
        raise ValueError("The article does not declare an eligible Creative Commons full-text licence")
    licence = approved.pop()
    record = europe_pmc(candidate)
    record.update(licence=licence, access="licensed_full_text", url=f"https://europepmc.org/articles/{pmcid}")
    return LicensedArticle(content, record, {
        "document_link": "verified_provider", "provider": "europe_pmc", "pmcid": pmcid,
        "source_url": record["url"], "licence": licence,
    })
