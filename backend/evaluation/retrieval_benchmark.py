"""Repeatable smoke benchmark. All default records and labels are synthetic."""

import argparse
import json
import math
from pathlib import Path
from statistics import median
from time import perf_counter

from rag.engine import Evidence, Vectorless
from evaluation.baselines import GraphAssisted


def local_engine(corpus, mode):
    by_id = {row.id: row for row in corpus}
    disable = {"without_hierarchy": ("hierarchy",), "without_metadata": ("metadata",)}
    return Vectorless(
        corpus, mode=mode if mode in ("bm25", "metadata", "hierarchical") else "adaptive",
        decompose=mode != "without_decomposition", disabled_routes=disable.get(mode, ()),
        numerical=lambda q: [key for key, row in by_id.items()
                             if row.metadata.get("metric") and row.metadata["metric"] in q.lower()],
    )


def evaluate(corpus, cases, engine, cutoff):
    by_id = {row.id: row for row in corpus}
    precision, recall, reciprocal, ndcg, latency = [], [], [], [], []
    for case in cases:
        truth = set(case["relevant"])
        if not truth or not truth <= by_id.keys():
            raise ValueError(f"Invalid evidence labels for {case['query']!r}")
        started = perf_counter()
        result = engine.search(case["query"], cutoff)
        latency.append((perf_counter() - started) * 1000)
        hits = [int(row.id in truth) for row in result]
        precision.append(sum(hits) / cutoff)
        recall.append(sum(hits) / len(truth))
        reciprocal.append(next((1 / rank for rank, hit in enumerate(hits, 1) if hit), 0))
        dcg = sum(hit / math.log2(rank + 1) for rank, hit in enumerate(hits, 1))
        ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(cutoff, len(truth)) + 1))
        ndcg.append(dcg / ideal)
    return {**{metric: round(sum(values) / len(cases), 4) for metric, values in (
        (f"precision@{cutoff}", precision), (f"recall@{cutoff}", recall),
        ("mrr", reciprocal), (f"ndcg@{cutoff}", ndcg))},
        "p50_query_ms": round(median(latency), 3)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=Path(__file__).with_name("synthetic.json"))
    parser.add_argument("--cutoff", type=int, default=3, choices=range(1, 21), metavar="1-20")
    parser.add_argument("--dense", action="store_true", help="Also evaluate experimental LSA and hybrid retrieval")
    args = parser.parse_args()
    dataset = json.loads(args.fixture.read_text())
    corpus = [Evidence(**row) for row in dataset["corpus"]]
    cases = dataset["questions"]
    if not corpus or not cases or len({row.id for row in corpus}) != len(corpus):
        raise ValueError("Benchmark requires non-empty data and unique passage IDs")
    engines = {mode: local_engine(corpus, mode) for mode in (
        "bm25", "metadata", "hierarchical", "adaptive", "without_decomposition", "without_hierarchy", "without_metadata"
    )}
    engines["graph_assisted"] = GraphAssisted(corpus, engines["adaptive"])
    if args.dense:
        from evaluation.baselines import DenseLSA, Hybrid
        dense = DenseLSA(corpus)
        engines.update(dense_lsa=dense, hybrid_lsa=Hybrid(engines["adaptive"], dense))
    print(json.dumps({"dataset": dataset["name"], "passages": len(corpus), "questions": len(cases),
                      "modes": {mode: evaluate(corpus, cases, engine, args.cutoff)
                                for mode, engine in engines.items()}}, indent=2))


if __name__ == "__main__":
    main()
