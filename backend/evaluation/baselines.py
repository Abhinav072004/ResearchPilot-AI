"""Offline experimental baselines. The application does not import this module."""

import math
from collections import Counter, defaultdict

from rag.engine import rrf, tokens


class GraphAssisted:
    """Expand lexical seeds by same-section and shared rare-term edges."""

    def __init__(self, corpus, seeds):
        self.seeds = seeds
        self.edges = defaultdict(set)
        sections, postings = defaultdict(list), defaultdict(list)
        for row in corpus:
            sections[(row.document_id, row.section_id)].append(row.id)
            for token in sorted(set(tokens(row.text))):
                postings[token].append(row.id)
        for members in [*sections.values(), *(ids for ids in postings.values() if len(ids) <= 3)]:
            for key in members:
                self.edges[key].update(other for other in members if other != key)
        self.lookup = {row.id: row for row in corpus}

    def search(self, query, limit=10):
        primary = [row.id for row in self.seeds.search(query, max(limit, 6))]
        expansions = []
        query_terms = set(tokens(query))
        for key in primary[:3]:
            matching = [other for other in self.edges[key] if query_terms.intersection(tokens(self.lookup[other].text))]
            expansions.append(sorted(matching))
        return [self.lookup[key] for key in rrf([primary, primary, *expansions])[:limit]]


class DenseLSA:
    """Project TF-IDF passages and queries into a corpus-trained dense latent space."""

    def __init__(self, corpus, dimensions=8):
        import numpy as np

        self.np, self.corpus = np, corpus
        terms = [Counter(tokens(row.text)) for row in corpus]
        vocabulary = sorted(set().union(*terms))
        if not vocabulary or len(corpus) * len(vocabulary) > 2_000_000:
            raise ValueError("Dense LSA supports small corpora with a nonempty vocabulary")
        self.columns = {term: column for column, term in enumerate(vocabulary)}
        df = Counter(term for row in terms for term in row)
        self.weights = {term: math.log((len(corpus) + 1) / (df[term] + 1)) + 1 for term in vocabulary}
        matrix = np.stack([self.vector(row) for row in terms])
        _, _, basis = np.linalg.svd(matrix, full_matrices=False)
        self.basis = basis[:dimensions].T
        vectors = matrix @ self.basis
        norms = np.linalg.norm(vectors, axis=1)
        self.vectors = vectors / np.maximum(norms, 1e-12)[:, None]

    def vector(self, counts):
        vector = self.np.zeros(len(self.columns))
        for term, count in counts.items():
            if term in self.columns:
                vector[self.columns[term]] = count * self.weights[term]
        return vector

    def search(self, query, limit=10):
        vector = self.vector(Counter(tokens(query))) @ self.basis
        norm = self.np.linalg.norm(vector)
        if not norm:
            return []
        scores = self.vectors @ (vector / norm)
        return [self.corpus[i] for i in self.np.argsort(-scores, kind="stable") if scores[i] > 1e-12][:limit]


class Hybrid:
    def __init__(self, lexical, dense):
        self.lexical, self.dense = lexical, dense

    def search(self, query, limit=10):
        groups = [engine.search(query, max(12, limit)) for engine in (self.lexical, self.dense)]
        lookup = {row.id: row for rows in groups for row in rows}
        return [lookup[key] for key in rrf([[row.id for row in rows] for rows in groups])[:limit]]


class SparseLSA:
    """Fit a dense latent representation without materializing an entire TF-IDF matrix."""

    def __init__(self, corpus, dimensions=128):
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.preprocessing import normalize

        self.corpus = corpus
        self.normalizer = normalize
        self.vectorizer = TfidfVectorizer(tokenizer=tokens, token_pattern=None, lowercase=False, min_df=2)
        matrix = self.vectorizer.fit_transform(row.title + " " + row.text for row in corpus)
        self.projection = TruncatedSVD(n_components=min(dimensions, matrix.shape[1] - 1, matrix.shape[0] - 1),
                                        random_state=0, n_iter=5)
        self.vectors = normalize(self.projection.fit_transform(matrix))

    def search(self, query, limit=10):
        terms = self.vectorizer.transform([query])
        if terms.nnz == 0:
            return []
        vector = self.normalizer(self.projection.transform(terms))[0]
        scores = self.vectors @ vector
        return [self.corpus[index] for index in scores.argsort(kind="stable")[::-1] if scores[index] > 0][:limit]
