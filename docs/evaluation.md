# Retrieval evaluation

Run from backend with the project dependencies installed.

```sh
python -m evaluation.retrieval_benchmark
pip install -r requirements-eval.txt
python -m evaluation.retrieval_benchmark --dense
```

The default corpus contains 18 synthetic passages and 12 hand-labeled queries. The JSON fixture records passage IDs and relevance labels. Use `--fixture PATH` for a permitted external dataset of the same shape and `--cutoff N` to change k. Every mode uses the same labels and cutoff. The graph mode follows same-section and shared rare-term links. The optional dense model is eight-component LSA trained on the fixture's TF-IDF matrix. It is isolated from the application and has no external model dependency.

## Measured fixture results

| Variant | Precision@3 | Recall@3 | MRR | nDCG@3 | Median query ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| BM25 | 0.4444 | 0.8472 | 0.8750 | 0.8341 | 0.034 |
| BM25 and metadata | 0.5278 | 0.9583 | 0.9583 | 0.9303 | 0.068 |
| BM25 and hierarchy | 0.4444 | 0.8472 | 0.8750 | 0.8341 | 0.041 |
| Adaptive vectorless | 0.5000 | 0.9306 | 1.0000 | 0.9482 | 0.090 |
| Adaptive without decomposition | 0.5000 | 0.9306 | 1.0000 | 0.9482 | 0.070 |
| Adaptive without hierarchy | 0.5000 | 0.9306 | 1.0000 | 0.9482 | 0.079 |
| Adaptive without metadata | 0.4444 | 0.8472 | 0.9167 | 0.8649 | 0.040 |
| Graph assisted | 0.5000 | 0.9306 | 0.9583 | 0.9175 | 0.091 |
| Dense LSA | 0.4722 | 0.8750 | 0.7917 | 0.7922 | 0.015 |
| Hybrid LSA | 0.5278 | 0.9583 | 1.0000 | 0.9678 | 0.097 |

The hybrid run had the highest nDCG on this fixture. Adaptive vectorless and hybrid LSA returned a relevant passage first for every case. Metadata-only augmentation had higher recall than adaptive on this dataset. Decomposition and hierarchy changed latency but did not change aggregate ranking metrics here. In-process timings exclude SQL, network, parsing and report generation.

A synthetic provider fixture exercises opt-in synthesis, rejects fabricated quotes and unsupported model proposals, and checks usage accounting. The application tests also assert that output excerpts match stored source text, that numerical results preserve raw strings and unit case, and that cross-tenant evidence IDs are rejected. The HTTP release smoke checks the same provenance over the deployed service boundary. The fixture is too small and constructed to estimate real scientific retrieval quality. Live model reranking, human-rated faithfulness, scholarly DOI accuracy, extraction accuracy at scale, and representative storage and cost measurements remain unmeasured.


## SciFact scholarly benchmark

The GitHub Actions benchmark downloads AI2 SciFact's original development archive, ranks the same full abstract corpus for each mode, and publishes metrics and the archive SHA-256 in the run summary. Use the same archive to reproduce the run.

```sh
pip install -r requirements-eval.txt
python -m evaluation.scifact /path/to/data.tar.gz --dense
```

The corpus contains real scientific abstracts. Development claims with SUPPORT or CONTRADICT document labels are treated as retrieval queries. Claims without evidence labels are counted and excluded from ranking metrics. Results measure abstract-level evidence retrieval on this scientific fact-checking corpus. Additional domain-specific corpora, passage-level faithfulness, numerical extraction accuracy, and a live model evaluation remain separate checks.

Source [AI2 SciFact](https://github.com/allenai/scifact).
