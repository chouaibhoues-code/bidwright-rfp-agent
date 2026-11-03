# Evaluation

What the evaluation harness measures at `v0.0`, and where its full design lives. Iteration 5 completes this document; until then the planned design is in section 10.9 of [`context/Master-Plan.md`](../context/Master-Plan.md).

## The harness at `v0.0`

`bidwright-eval` is a separate package in `evals/`. It reads a finished run folder, scores it against gold, and writes `evals/results/runs/<run>/`. It never writes into a run, and `src/bidwright` never imports it (`tests/test_isolation.py`). In Docker, only the `eval` service mounts the gold.

```bash
uv run bidwright-eval score outputs/<run>
```

### Gold

The development RFP is rendered from `evals/corpus/dev/spec.yaml`, so every clause's text and label are known by construction. `evals/render/gold.py` generates `evals/gold/dev/gold.jsonl` from the spec. This is gold v1: 12 requirements, 8 of them mandatory and one a submission hazard; 3 background clauses, one written to read like a requirement; and 3 planted risks. Its sha256 is recorded in `evals/gold/MANIFEST.sha256`, and the scorer refuses gold that no longer matches that hash.

### Matching

The question is whether each gold obligation was captured. The rules, in `evals/matcher.py`:
- Each gold clause maps to a span of the run's frozen text. A list item's span may extend back over its lead-in.
- Predictions are records with disposition `BINDING` or `OPTIONAL` and a verified quote.
- **Relaxed capture**, the headline: the verified quote lies inside the clause's span. **Strict capture** also needs the cited passages to cover the whole clause.
- A record whose passages reach a second clause is flagged `merged`, and extra records on a captured clause `duplicate`.
- A prediction that captures no gold clause goes to `adjudication.csv`. Precision is therefore a range: the low end counts every such record as wrong, the high end as right.

### The 0a scorecard

| Line | Measures |
|---|---|
| Missed mandatory requirements | The headline, relaxed and strict, per RFP |
| Missed submission hazards | Hazards are reported apart, because one can disqualify a bid |
| Recall and precision range | Over all gold requirements |
| Merged, duplicate, on background, unmatched | Records that need a closer look |
| Verbatim and normalized rates | Grounding, a separate axis from correctness |
| Binding requirements mapped to approach | Whether every binding requirement has an approach item |
| Risk seeds found | A planted risk counts when a risk cites one of its anchor passages and uses a term from each of its term groups |
| Requests, tokens, cost, shadow cost, models | From the run's ledger |

### The scorer is tested too

A scorer that cannot fail shows nothing. `tests/test_scorer_selftest.py` checks that an oracle output scores full marks, that removing one mandatory record adds exactly one miss, and that shuffling the records changes nothing. `tests/test_matcher.py` holds worked examples of each matching rule. Both run in the `gold` CI job.

## Results at `v0.0`

One live run each on the development RFP, committed under `evals/results/runs/`:

| Run | Missed mandatory | Missed hazards | Precision range | Verbatim quotes | Risk seeds | Requests | Shadow cost |
|---|---|---|---|---|---|---|---|
| `free`, the full thread (`20261103T030541Z-dev-rfp-3c582e4c-free`) | 0 of 8 | 0 of 1 | 92% to 100% | 100% | 1 of 3 | 11 | $0.0317 |
| `free`, EX0 baseline (`20261103T030640Z-dev-rfp-3c582e4c-free-ex0`) | 0 of 8 | 0 of 1 | 100% | 100% | 1 of 3 | 11 | $0.0352 |
| `local`, `qwen3.5:4b` on CPU (`20261103T030503Z-dev-rfp-3c582e4c-local`) | 0 of 8 | 0 of 1 | 100% | 100% | 0 of 3 | 11 | $0.0202 |

**What these show, and what they do not.** On a four-page RFP, the batched thread and the one-call baseline capture the same obligations, so the extraction comparison waits for the 20-25-page hero RFP in Iteration 1. Each line is one run, not the median of repeats, so no difference here is claimed as real. Risk recall is the weak point: 1 of 3 planted risks on `free` and none on `local`.

## What CI gates

CI blocks a merge on the unit tests (schemas, quote checks, gateway rules), the gold tests (the matcher and the scorer self-test) and the replayed run. `config/thresholds.yaml` holds the block and warn thresholds of the regression gate, which applies from tag `v0.1`, once the hero RFP gives a baseline worth guarding. Only live runs show model quality; CI shows that the code path and the scorer are unchanged.

## Still to come

Gold v2 with the hero, held-out and DOCX RFPs; the funnel that names the stage which lost each miss; ablations with repeats under a keep-or-drop rule fixed in advance; advisory judges calibrated on the owner's labels; and stage benchmarks against public datasets. The quality scenarios these feed are in section 10 of [`architecture.md`](architecture.md).
