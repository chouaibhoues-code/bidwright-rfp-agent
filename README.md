# Bidwright

Bidwright reads an RFP package and drafts what a bid team needs first: a solution summary of requirements, approach and risks, with every requirement traced to a verified quote from the RFP. Later iterations add a proposal pack, generated from one solution manifest, that a bid team can edit.

> **Status:** Iteration 0a, the walking skeleton, is in progress. Nothing runs end to end yet, and this README grows with each tag.

## The design in one line

A deterministic shell around a probabilistic core: code checks everything code can check, and the LLM does only the judgment and generation that code cannot, inside those checks. Each agent has to earn its place in a measured comparison.

## Setup

1. Install Python 3.12 and [uv](https://docs.astral.sh/uv/).
2. Run `uv sync`.
3. Copy `.env.example` to `.env` and add the keys there. Git ignores `.env`, and `.env.example` holds variable names only.

**Data rule.** The `free` profile runs only on the synthetic corpus listed in `inputs/CORPUS.sha256`, because free-tier prompts may be used by the provider. Other documents go through `--profile local`, which keeps everything on this machine.

## Documents

| File | Holds |
|---|---|
| `DECISIONS.md` | Architecture and product decisions, and the failure modes hit while building |
| `ASSUMPTIONS.md` | What is assumed, what breaks if it is false, and how it is checked |
| `TIMELOG.md` | Rough hours per part |
| `docs/` | Engineering documents, including the verification log and the demo script |
| `context/` | Project management: plan, decisions in progress, backlog, research register (from Iteration 0b) |
