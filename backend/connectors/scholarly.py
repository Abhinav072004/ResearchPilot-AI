import re
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from time import sleep, time
from urllib.parse import quote

import httpx
from defusedxml import ElementTree

from app.config import settings

PROVIDERS = ("crossref", "openalex", "semantic_scholar", "arxiv", "pubmed", "europe_pmc", "core")
DOI = re.compile(r"10\.\d{4,9}/[^\s<>\"?#]+", re.I)


def normalize_doi(value):
    if not value:
        return None
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value.strip(), flags=re.I).lower()
    return value if len(value) <= 300 and DOI.fullmatch(value) else None


def request(url, params=None, headers=None):
    with httpx.Client(timeout=httpx.Timeout(6, connect=3), follow_redirects=False) as client:
        for attempt in range(2):
            try:
                response = client.get(url, params=params, headers=headers)
                if response.status_code in (429, 502, 503, 504) and attempt == 0:
                    delay = response.headers.get("Retry-After", "")
                    if delay and (not delay.isdecimal() or int(delay) > 1):
                        response.raise_for_status()
                    sleep(int(delay) if delay else 0.25)
                    continue
                return response.raise_for_status()
            except (httpx.ConnectError, httpx.TimeoutException):
                if attempt:
                    raise


def record(provider, identifier, title, *, doi=None, authors=(), year=None, url=None,
           abstract=None, journal=None, kind=None, licence=None, oa=False, retracted=None, relations=()):
    return {
        "provider": provider, "external_id": str(identifier), "title": title,
        "doi": normalize_doi(doi), "authors": list(authors), "year": year,
        "url": url, "abstract": abstract, "journal": journal, "publication_type": kind,
        "licence": licence, "open_access": oa, "access": "abstract" if abstract else "metadata_only",
        "retracted": retracted, "relations": list(relations),
    }


def crossref(item):
    doi = item.get("DOI")
    updates = item.get("update-to") or []
    incoming = item.get("updated-by") or []
    retractions = {"retraction", "withdrawal"}
    retracted = True if any(u.get("type") in retractions for u in incoming) else None
    notice = any(u.get("type") in retractions for u in updates)
    return record("crossref", doi, next(iter(item.get("title") or []), ""),
                  doi=doi, url=item.get("URL"), abstract=item.get("abstract"),
                  authors=[" ".join(filter(None, (a.get("given"), a.get("family") or a.get("name"))))
                           for a in item.get("author", [])],
                  year=(item.get("published", {}).get("date-parts") or [[None]])[0][0],
                  journal=next(iter(item.get("container-title") or []), None),
                  kind="retraction_notice" if notice else item.get("type"), licence=next((x.get("URL") for x in item.get("license", [])), None),
                  retracted=retracted, relations=[*incoming, *updates])


def openalex(item):
    location = item.get("primary_location") or {}
    source = location.get("source") or {}
    words = item.get("abstract_inverted_index") or {}
    abstract = " ".join(word for _, word in sorted((i, word) for word, positions in words.items() for i in positions))
    return record("openalex", item["id"], item.get("display_name"), doi=item.get("doi"),
                  year=item.get("publication_year"), url=location.get("landing_page_url"),
                  authors=[a["author"].get("display_name", "") for a in item.get("authorships", [])],
                  journal=source.get("display_name"), kind=item.get("type"), abstract=abstract,
                  licence=location.get("license"), oa=(item.get("open_access") or {}).get("is_oa", False),
                  retracted=item.get("is_retracted"))


def europe_pmc(item, provider="europe_pmc"):
    identifier = item.get("pmid") or item.get("id")
    return record(provider, identifier, item.get("title"), doi=item.get("doi"),
                  authors=(item.get("authorString") or "").split(", "), year=item.get("pubYear"),
                  journal=item.get("journalTitle") or (item.get("journalInfo") or {}).get("journal", {}).get("title"),
                  kind=item.get("pubType"), abstract=item.get("abstractText"),
                  url=f"https://europepmc.org/article/{item.get('source', 'MED')}/{identifier}",
                  oa=item.get("isOpenAccess") == "Y",
                  retracted=True if "retracted publication" in (item.get("pubType") or "").lower() else None)


def arxiv(data):
    ns = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
    return [record("arxiv", e.findtext("a:id", namespaces=ns), " ".join((e.findtext("a:title", namespaces=ns) or "").split()),
                   doi=e.findtext("x:doi", namespaces=ns), url=e.findtext("a:id", namespaces=ns), kind="preprint",
                   abstract=e.findtext("a:summary", namespaces=ns), year=(e.findtext("a:published", namespaces=ns) or "")[:4],
                   authors=[a.findtext("a:name", namespaces=ns) for a in e.findall("a:author", ns)])
            for e in ElementTree.fromstring(data).findall("a:entry", ns)]


def pubmed(query, limit, offset):
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    ids = request(base + "esearch.fcgi", {"db": "pubmed", "term": query, "retmax": limit, "retstart": offset,
                                         "retmode": "json"}).json()["esearchresult"]["idlist"]
    if not ids:
        return []
    data = request(base + "efetch.fcgi", {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}).content
    results = []
    for entry in ElementTree.fromstring(data).findall("PubmedArticle"):
        citation = entry.find("MedlineCitation")
        article = citation.find("Article")
        identifier = citation.findtext("PMID")
        results.append(record(
            "pubmed", identifier, "".join(article.find("ArticleTitle").itertext()),
            url=f"https://pubmed.ncbi.nlm.nih.gov/{identifier}/",
            doi=next((e.text for e in entry.findall(".//ArticleId") if e.get("IdType") == "doi"), None),
            authors=[" ".join(filter(None, (a.findtext("ForeName"), a.findtext("LastName") or a.findtext("CollectiveName"))))
                     for a in article.findall("AuthorList/Author")],
            year=article.findtext("Journal/JournalIssue/PubDate/Year"), journal=article.findtext("Journal/Title"),
            abstract="\n".join("".join(a.itertext()) for a in article.findall("Abstract/AbstractText")),
            kind=", ".join(p.text or "" for p in article.findall("PublicationTypeList/PublicationType")),
            retracted=True if any(p.text == "Retracted Publication" for p in article.findall("PublicationTypeList/PublicationType")) else None,
        ))
    return results


@lru_cache(maxsize=256)
def search(provider, query, limit, offset, cache_window):
    config = settings()
    if provider == "crossref":
        data = request("https://api.crossref.org/works", {"query.bibliographic": query, "rows": limit,
                                                          "offset": offset}).json()
        return [crossref(i) for i in data["message"]["items"]]
    if provider == "openalex":
        if not config.openalex_key:
            raise ValueError("OpenAlex API key is required")
        data = request("https://api.openalex.org/works", {"search": query, "per_page": limit,
                                                         "page": offset // limit + 1, "api_key": config.openalex_key}).json()
        return [openalex(i) for i in data["results"]]
    if provider == "semantic_scholar":
        headers = {"x-api-key": config.semantic_scholar_key} if config.semantic_scholar_key else None
        data = request("https://api.semanticscholar.org/graph/v1/paper/search",
                       {"query": query, "limit": limit, "offset": offset,
                        "fields": "title,abstract,authors,year,url,externalIds,journal,publicationTypes,isOpenAccess"}, headers).json()
        return [record(provider, i["paperId"], i.get("title"), doi=(i.get("externalIds") or {}).get("DOI"),
                       authors=[a.get("name", "") for a in i.get("authors") or []], year=i.get("year"),
                       url=i.get("url"), abstract=i.get("abstract"), journal=(i.get("journal") or {}).get("name"),
                       kind=", ".join(i.get("publicationTypes") or []), oa=i.get("isOpenAccess"))
                for i in data.get("data") or []]
    if provider == "arxiv":
        return arxiv(request("https://export.arxiv.org/api/query", {"search_query": f"all:{query}",
                                                                   "start": offset, "max_results": limit}).content)
    if provider == "pubmed":
        return pubmed(query, limit, offset)
    if provider == "europe_pmc":
        data = request("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                       {"query": query, "format": "json", "resultType": "core", "pageSize": limit, "page": offset // limit + 1}).json()
        return [europe_pmc(i) for i in data["resultList"]["result"]]
    if provider == "core":
        if not config.core_key:
            raise ValueError("CORE API key is required")
        data = request("https://api.core.ac.uk/v3/search/works", {"q": query, "limit": limit, "offset": offset},
                       {"Authorization": f"Bearer {config.core_key}"}).json()
        return [record(provider, i["id"], i.get("title"), doi=i.get("doi"), year=i.get("yearPublished"),
                       authors=[a.get("name", "") for a in i.get("authors") or []],
                       abstract=i.get("abstract"), url=i.get("downloadUrl")) for i in data["results"]]
    raise ValueError("Unknown provider")


def discover(query, providers, limit=8, offset=0):
    def run(provider):
        try:
            return provider, [r for r in search(provider, query, limit, offset, int(time() // 300))
                              if r["title"] and r["external_id"] not in ("None", "")], None
        except (httpx.HTTPError, KeyError, TypeError, ValueError, ElementTree.ParseError):
            return provider, [], "Provider unavailable or not configured"

    with ThreadPoolExecutor(max_workers=min(4, len(providers))) as pool:
        batches = list(pool.map(run, providers))
    return [r for _, rows, _ in batches for r in rows], {p: error for p, _, error in batches if error}


@lru_cache(maxsize=256)
def resolve_doi(doi, cache_window):
    result = crossref(request("https://api.crossref.org/works/" + quote(doi, safe="/")).json()["message"])
    if result["doi"] != doi:
        raise ValueError("Resolver identifier mismatch")
    return result
