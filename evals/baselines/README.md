# Baselines

One file per corpus RFP, `<rfp>.json`, written by `bidwright-eval baseline <run>`: a copy of
the run's `scores.json`, which records the corpus and the hash of the gold it was scored
against. `bidwright-eval gate <run> --baseline evals/baselines/<rfp>.json` compares a later
run with it under `config/thresholds.yaml`, and blocks when the baseline was scored on other
gold.

A baseline is a score, so none exists before its gold is hashed in
`evals/gold/MANIFEST.sha256`. The hero baseline was written on 2026-11-04 from the replayed
hero recording made with packs of 40, after gold v2 was hashed, and the `gold` CI job gates the
hero replay against it (`tests/test_hero_replay.py`). It was written again the same day after
ADR-030 corrected the matcher, since a gate must compare scores from one matcher: 3 of 45
missed, where the first scoring of the same replay counted 8.

It was written once more on 2026-11-05, after gold v3 was hashed (Iteration 2, step 8), since
the gate blocks a baseline scored on other gold. Gold v3 adds the factor seeds and the hero's
domain seeds and changes no requirement, so the scores held: 3 of 45 missed (GR-0030, GR-0042
and GR-0045). The new factor line reads "not run", because the replay stops after
`consolidate`, before `brief`.
