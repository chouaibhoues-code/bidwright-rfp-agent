"""Render corpus specs to RFP packages and generate gold from the same specs.

`python -m evals.render dev` writes the documents of the `dev` package under `inputs/dev/`,
records their hashes in `inputs/CORPUS.sha256`, and writes `evals/gold/dev/gold.jsonl`.
"""
