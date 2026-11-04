# Baselines

One file per corpus RFP, `<rfp>.json`, written by `bidwright-eval baseline <run>`: a copy of
the run's `scores.json`, which records the corpus and the hash of the gold it was scored
against. `bidwright-eval gate <run> --baseline evals/baselines/<rfp>.json` compares a later
run with it under `config/thresholds.yaml`, and blocks when the baseline was scored on other
gold.

A baseline is a score, so none exists before its gold is hashed in
`evals/gold/MANIFEST.sha256`. The hero baseline was written on 2026-11-04 from the replayed
hero recording made with packs of 40, after gold v2 was hashed, and the `gold` CI job gates the
hero replay against it (`tests/test_hero_replay.py`).
