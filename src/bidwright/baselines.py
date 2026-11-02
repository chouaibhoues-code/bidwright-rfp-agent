"""Baselines: the simple configurations each agentic rung is judged against.

EX0 sends every passage of the RFP in one call to `extract_oneshot.md`, a plain instruction,
and expects the same `ExtractResult`. `verify` still checks its quotes, so the step from EX0
to EX1 measures batching and the prompt contract only. Run it with
`bidwright run <file> --baseline ex0`, and score it with the same scorer as any run.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Baseline:
    name: str
    extract_prompt: str
    one_batch: bool


BASELINES = {"ex0": Baseline(name="ex0", extract_prompt="extract_oneshot", one_batch=True)}
