"""Fetch licensed JATS from fixed scholarly provider endpoints."""

import json
import re
from dataclasses import dataclass
from time import monotonic, time
from urllib.parse import urlsplit

import httpx
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from connectors.scholarly import europe_pmc, normalize_doi, resolve_doi

EUROPE_PMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
PMC = "https://pmc.ncbi.nlm.nih.gov"
ENTREZ = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PMCID = re.compile(r"PMC[1-9][0-9]{0,9}")
# Limit automatic reuse to explicit, unrestricted text licenses and public-domain dedication.
LICENSE_PATH = re.compile(r"/(?:licenses/by/(?:2\.0|2\.5|3\.0|4\.0)|publicdomain/zero/1\.0)/?")


class ProviderUnavailable(ValueError):
    pass


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


def read_response(client, path, limit, params=None, *, base=EUROPE_PMC):
    started = monotonic()
    with client.stream("GET", base + path, params=params) as response:
        response.raise_for_status()
        content = bytearray()
        for chunk in response.iter_bytes(chunk_size=65536):
            if len(content) + len(chunk) > limit:
                raise ValueError("The full-text provider response exceeds the size limit")
            if monotonic() - started > 30:
                raise ValueError("The full-text provider response exceeded the download time limit")
            content.extend(chunk)
        return bytes(content)


def europe_pmc_document(client, doi, limit):
    stage = "metadata search"
    try:
        data = json.loads(read_response(client, "/search", 512_000, {
            "query": f'DOI:"{doi}"', "format": "json", "resultType": "core", "pageSize": 10,
        }))
        if not isinstance(data, dict) or not isinstance(data.get("resultList"), dict):
            raise ProviderUnavailable("Europe PMC returned an invalid search response")
        matching = [row for row in data["resultList"].get("result", [])
                    if isinstance(row, dict) and normalize_doi(row.get("doi")) == doi]
        eligible = [row for row in matching if row.get("isOpenAccess") == "Y" and row.get("title")
                    and PMCID.fullmatch(row.get("pmcid") or "")]
        if not eligible:
            raise ValueError("Europe PMC does not list open-access full text for this DOI")
        candidate = eligible[0]
        if any("retract" in (row.get("pubType") or "").lower() for row in matching):
            raise ValueError("Retracted articles and retraction notices cannot be imported")
        pmcid = candidate["pmcid"]
        stage = "full-text download"
        content = read_response(client, f"/{pmcid}/fullTextXML", limit)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404:
            raise ValueError("Europe PMC did not return full text for this DOI") from exc
        raise ProviderUnavailable(f"Europe PMC {stage} returned HTTP {status}") from exc
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ProviderUnavailable(f"Europe PMC {stage} failed ({type(exc).__name__})") from exc
    return content, europe_pmc(candidate), pmcid, f"https://europepmc.org/articles/{pmcid}"


def pubmed_central_document(client, doi, limit):
    stage = "identifier lookup"
    try:
        data = json.loads(read_response(client, "/tools/idconv/api/v1/articles/", 128_000, {
            "ids": doi, "format": "json",
        }, base=PMC))
        pmcid = next((row["pmcid"] for row in data.get("records", [])
                      if normalize_doi(row.get("doi")) == doi and PMCID.fullmatch(row.get("pmcid") or "")), None)
        if pmcid is None:
            raise ValueError("PubMed Central did not resolve the DOI to a PMCID")
        stage = "DOI verification"
        record = resolve_doi(doi, int(time() // 300))
        if record["retracted"] or record["publication_type"] == "retraction_notice":
            raise ValueError("Retracted articles and retraction notices cannot be imported")
        stage = "full-text download"
        content = read_response(client, "/efetch.fcgi", limit, {
            "db": "pmc", "id": pmcid[3:], "retmode": "xml",
        }, base=ENTREZ)
    except httpx.HTTPStatusError as exc:
        raise ProviderUnavailable(f"PubMed Central {stage} returned HTTP {exc.response.status_code}") from exc
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ProviderUnavailable(f"PubMed Central {stage} failed ({type(exc).__name__})") from exc
    record.update(provider="pubmed_central", external_id=pmcid)
    return content, record, pmcid, f"{PMC}/articles/{pmcid}/"


def verify_article(content, doi):
    try:
        root = ElementTree.fromstring(content)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise ValueError("The provider did not return valid article XML") from exc
    for element in root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]
    if root.tag in {"pmc-articleset", "article-set"} and len(root) == 1:
        root = root[0]
    metadata = root.find("./front/article-meta")
    if root.tag != "article" or metadata is None or root.find("body") is None:
        raise ValueError("The provider response does not contain a complete JATS article")
    if "retract" in root.get("article-type", "").lower():
        raise ValueError("Retracted articles and retraction notices cannot be imported")
    identifiers = {normalize_doi(node.text) for node in metadata.findall("article-id") if node.get("pub-id-type") == "doi"}
    if identifiers != {doi}:
        raise ValueError("The downloaded article DOI does not match the requested DOI")
    licences = metadata.findall("./permissions/license")
    approved = {open_license(node.get("{http://www.w3.org/1999/xlink}href", "")) for node in licences}
    if len(approved) != 1 or None in approved:
        raise ValueError("The article does not declare an eligible Creative Commons full-text licence")
    return approved.pop()


def fetch(doi, limit):
    doi = normalize_doi(doi)
    if not doi:
        raise ValueError("A valid DOI is required for licensed import")
    with httpx.Client(timeout=httpx.Timeout(12, connect=5), follow_redirects=False) as client:
        try:
            content, record, pmcid, url = europe_pmc_document(client, doi, limit)
        except ProviderUnavailable as primary_error:
            try:
                content, record, pmcid, url = pubmed_central_document(client, doi, limit)
            except ValueError as fallback_error:
                raise ValueError(f"{primary_error}. {fallback_error}") from fallback_error
    licence = verify_article(content, doi)
    record.update(licence=licence, access="licensed_full_text", url=url)
    return LicensedArticle(content, record, {
        "document_link": "verified_provider", "provider": record["provider"], "pmcid": pmcid,
        "source_url": url, "licence": licence,
    })
