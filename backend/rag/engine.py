import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Protocol

from connectors.scholarly import DOI

TOKEN = re.compile(r"[^\W_]+(?:[-/][^\W_]+)*", re.UNICODE)
STOP = frozenset("a an and are at by did do for from how in is it of on or paper study the to was were what when where which who with".split())


def tokens(text):
    return [t for t in TOKEN.findall(text.casefold()) if t not in STOP]


@dataclass(frozen=True)
class Evidence:
    id: str
    document_id: str
    title: str
    text: str
    section: str
    section_id: str
    kind: str = "paragraph"
    page: int | None = None
    doi: str | None = None
    access: str = "user_upload"
    metadata: dict = field(default_factory=dict)
    anchor: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class Plan:
    intent: str
    queries: tuple[str, ...]
    routes: tuple[str, ...]
    doi: str | None
    phrases: tuple[str, ...]


def plan(query):
    lower = query.casefold()
    doi_match = DOI.search(query)
    doi = doi_match.group().rstrip(".,;)").lower() if doi_match else None
    phrases = tuple(re.findall(r'"([^"]+)"|“([^”]+)”', query))
    exact = tuple(left or right for left, right in phrases)
    if doi or re.search(r"\b(?:find|locate|identify|summarize) (?:the |a )?(?:paper|article)\b", lower):
        intent, routes = "paper", ("metadata", "phrase", "bm25")
    elif re.search(r"\b(?:compare|versus|vs\.?|difference between|contradict)\b", lower):
        intent, routes = "comparison", ("bm25", "sql", "hierarchy", "captions")
    elif re.search(r"\b(?:recommend|design|optimi[sz]e|should (?:we|i)|trade-offs?)\b", lower):
        intent, routes = "recommendation", ("bm25", "sql", "hierarchy", "captions")
    elif re.search(r"\b(?:literature review|systematic review|survey|state of the art|research gaps|overview)\b", lower):
        intent, routes = "review", ("hierarchy", "bm25", "metadata")
    elif re.search(r"\b(?:how much|how many|numerical|measured|yield|efficiency|concentration|temperature|pressure|hhv|cge|cce)\b", lower):
        intent, routes = "numerical", ("sql", "captions", "bm25", "phrase")
    elif re.search(r"\b(?:define|definition|meaning of|what (?:is|are))\b", lower):
        intent, routes = "definition", ("definition", "phrase", "bm25")
    else:
        intent, routes = "general", ("bm25", "phrase", "metadata")
    queries = [query]
    if intent in ("comparison", "review", "recommendation"):
        queries.extend(part.strip() for part in re.split(r"\b(?:versus|vs\.?|compared with|and)\b|[;?]", query, flags=re.I)
                       if len(tokens(part)) >= 2)
    return Plan(intent, tuple(dict.fromkeys(queries))[:4], routes, doi, exact)


class Retriever(Protocol):
    def search(self, query: str, limit: int = 10) -> list[Evidence]: ...


class Reranker(Protocol):
    def __call__(self, query: str, candidates: list[Evidence]) -> list[str]: ...


class BM25:
    def __init__(self, corpus):
        self.terms = [Counter(tokens(row.text)) for row in corpus]
        self.lengths = [sum(counts.values()) for counts in self.terms]
        self.average = sum(self.lengths) / max(1, len(corpus)) or 1
        self.df = Counter(word for counts in self.terms for word in counts)

    def score(self, query):
        terms = set(tokens(query))
        count = len(self.terms)
        weights = {word: math.log1p((count - self.df[word] + 0.5) / (self.df[word] + 0.5))
                   for word in terms}
        return [
            sum(weights[word] * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * length / self.average))
                for word in terms if (frequency := frequencies[word]))
            for frequencies, length in zip(self.terms, self.lengths, strict=True)
        ]


def ranked(weights):
    return [index for index in sorted(range(len(weights)), key=lambda i: -weights[i]) if weights[index] > 0]


def rrf(rankings, constant=60):
    scores = defaultdict(float)
    for ranking in rankings:
        for rank, key in enumerate(dict.fromkeys(ranking), 1):
            scores[key] += 1 / (constant + rank)
    return sorted(scores, key=lambda key: -scores[key])


def deduplicate(rows):
    seen = set()
    for row in rows:
        key = (row.document_id, " ".join(row.text.casefold().split()))
        if key not in seen:
            seen.add(key)
            yield row


class Vectorless:
    def __init__(self, corpus, *, numerical=None, reranker=None, mode="adaptive",
                 decompose=True, disabled_routes=()):
        self.rows = list(deduplicate(row for row in corpus if row.kind != "reference"))
        self.bm25 = BM25(self.rows)
        self.numerical = numerical
        self.reranker = reranker
        self.mode = mode
        self.decompose = decompose
        self.disabled_routes = frozenset(disabled_routes)

    def search(self, query, limit=10):
        retrieval = plan(query)
        rows = self.rows
        if retrieval.doi and self.mode in ("adaptive", "metadata") and "metadata" not in self.disabled_routes:
            exact = [row for row in rows if row.doi == retrieval.doi]
            return exact[:limit]
        rankings = []
        routes = {"bm25": ("bm25",), "metadata": ("bm25", "metadata"),
                  "hierarchical": ("bm25", "hierarchy")}.get(self.mode, retrieval.routes)
        for subquery in retrieval.queries if self.mode == "adaptive" and self.decompose else (query,):
            weights = self.bm25.score(subquery)
            lexical = ranked(weights)[:80]
            for route in (route for route in routes if route not in self.disabled_routes):
                if route == "bm25":
                    rankings.append(lexical)
                elif route == "phrase":
                    phrase = retrieval.phrases or (" ".join(tokens(subquery)),)
                    rankings.append(ranked([sum(bool(p) and p.casefold() in row.text.casefold() for p in phrase)
                                            for row in rows])[:80])
                elif route == "metadata":
                    keywords = set(tokens(subquery))
                    target_text = re.sub(r"^(?:find|locate|identify|summarize) (?:the |a )?(?:paper|article)\s*",
                                         "", subquery, flags=re.I)
                    target = " ".join(tokens(target_text))
                    scores = []
                    for row in rows:
                        metadata = " ".join(str(row.metadata.get(key) or "") for key in ("authors", "year", "journal"))
                        title = tokens(row.title)
                        scores.append(len(keywords.intersection(set(title + tokens(metadata))))
                                      + 100 * (bool(target) and target == " ".join(title)))
                    rankings.append(ranked(scores)[:80])
                elif route == "sql" and self.numerical:
                    ids = set(self.numerical(subquery))
                    ranking = ranked([1 + weights[i] if row.id in ids else 0 for i, row in enumerate(rows)])
                    rankings.extend([ranking[:80]] * 2)
                elif route == "captions":
                    rankings.append([i for i in lexical if rows[i].kind in ("table", "figure_caption")])
                elif route == "definition":
                    rankings.append([i for i in lexical if re.search(r"\b(?:defined as|refers to|means)\b", rows[i].text, re.I)])
                elif route == "hierarchy":
                    scores = defaultdict(list)
                    for i in lexical:
                        row = rows[i]
                        section_bonus = len(set(tokens(row.section)).intersection(tokens(subquery)))
                        scores[(row.document_id, row.section_id)].append((weights[i] + section_bonus, i))
                    ordered = sorted(scores.values(), key=lambda items: -max(items)[0])
                    rankings.append([max(items)[1] for items in ordered])
        candidates = [rows[i] for i in rrf(rankings)[:max(limit, 24)]]
        if self.reranker and candidates:
            window = candidates[:12]
            ids = self.reranker(query, window)
            lookup = {row.id: row for row in window}
            head = [lookup[key] for key in dict.fromkeys(ids) if key in lookup]
            candidates = head + [row for row in candidates if row not in head]
        if retrieval.intent in ("review", "comparison", "recommendation") and self.mode == "adaptive":
            seen = set()
            head = []
            for row in candidates:
                if row.document_id not in seen:
                    seen.add(row.document_id)
                    head.append(row)
            candidates = head + [row for row in candidates if row not in head]
        return candidates[:limit]
