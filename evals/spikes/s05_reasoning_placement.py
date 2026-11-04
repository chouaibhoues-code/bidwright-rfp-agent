"""S-05: where should `extract` reason? Three variants on the development RFP, 5 repeats each.

- A, schema only: `thinking: minimal`, the current extract setting, with the schema enforced.
- B, thinking plus schema: `thinking: medium`, with the schema enforced.
- C, two-step: a free-text reasoning call at `minimal`, then the schema call with that
  reasoning in the conversation.

Each repeat scores the first structured answer, before any repair, so the variants differ only
in where reasoning happens. The answer is settled with the producer's own rules
(`graph.nodes.settle`, which checks a quote only against its own batch, and
`assign_requirements`), then scored for missed mandatory requirements against gold v1, the
share of quotes `verify` accepts, and the batches whose first answer broke the schema. Pass
mark: the cheapest variant within noise of the best. Run with
`uv run python -m evals.spikes.s05_reasoning_placement`; it needs GEMINI_API_KEY and makes
about 40 Flash-Lite calls. Results are written after every repeat, so a spent quota keeps what
finished. Synthetic text only.
"""

import json
import os
import statistics
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bidwright.config import load_config
from bidwright.graph.nodes import BatchOutcome, assign_requirements, batches, settle
from bidwright.ingest import display_text, ingest_pdf
from bidwright.llm.client import Completion, LLMClient, default_backends
from bidwright.llm.schema import sha256_of
from bidwright.llm.types import LLMError, Message
from bidwright.prompts import Prompt, load_prompt
from bidwright.schemas import ExtractBatch, ExtractResult, Passage, PassageView
from evals.matcher import gold_clauses, match
from evals.score import GOLD_DIR

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "evals" / "results" / "spikes" / "s05.json"
REPEATS = 5
PACE_S = 4.5  # Flash-Lite allows 15 requests a minute on the free tier
REASON = (
    "Before giving the JSON, reason in plain text: for each passage id, say whether it places an"
    " obligation on the supplier, which row of the decision table applies, and the exact words to"
    " quote. Do not return JSON yet."
)
TO_JSON = "Now return the result as JSON that matches the response schema."
VARIANTS = {
    "A schema only": "minimal",
    "B thinking plus schema": "medium",
    "C two-step": "minimal",
}


@dataclass
class BatchScore:
    outcome: BatchOutcome
    items: int = 0
    calls: int = 0
    tokens: int = 0
    latency_ms: int = 0
    schema_failed: bool = False

    def add(self, completion: Completion) -> None:
        usage = completion.usage
        self.calls += 1
        self.tokens += usage.tokens_in + usage.tokens_out + usage.tokens_thinking
        self.latency_ms += completion.latency_ms


def run_batch(
    client: LLMClient,
    prompt: Prompt,
    variant: str,
    repeat: int,
    number: int,
    batch: Sequence[Passage],
    passages: Mapping[str, Passage],
) -> BatchScore:
    """One batch's first structured answer under one variant, settled by the producer's rules."""
    view = ExtractBatch(
        batch_id=f"B{number:02d}",
        passages=[
            PassageView(
                src_id=p.id,
                section_path=p.section_path,
                text=display_text(p.text),
                lead_in=display_text(passages[p.lead_in_id].text) if p.lead_in_id else None,
            )
            for p in batch
        ],
    )
    run_id = f"s05-{variant}-{repeat}"
    rendered = prompt.render(view.model_dump_json(), run_id=run_id, batch_id=view.batch_id)
    messages = list(rendered.messages)
    ids = {"node": "s05", "agent": variant, "prompt_hash": prompt.hash, "repeat": repeat}
    decoding = {"gemini": {"thinking": VARIANTS[variant]}}
    score = BatchScore(BatchOutcome(view.batch_id))
    answer_hash = rendered.input_hash
    if variant.startswith("C"):
        reasoning = [*messages, Message("user", REASON)]
        reason_hash = sha256_of([rendered.input_hash, "reason"])
        thought = client.complete(
            "extract", reasoning, None, input_hash=reason_hash, decoding=decoding, **ids
        )
        score.add(thought)
        messages = [*reasoning, thought.as_message(), Message("user", TO_JSON)]
        # The answer follows a different conversation from variant A's, so it gets its own key.
        answer_hash = sha256_of([rendered.input_hash, "reason", "json"])
        time.sleep(PACE_S)
    answer = client.complete(
        "extract", messages, ExtractResult, input_hash=answer_hash, decoding=decoding, **ids
    )
    score.add(answer)
    if isinstance(answer.parsed, ExtractResult):
        settle(score.outcome, answer.parsed.items, passages, [p.id for p in batch], final=True)
        score.items = len(answer.parsed.items)
    else:
        score.schema_failed = True
    time.sleep(PACE_S)
    return score


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {}
    for name in VARIANTS:
        mine = [r for r in rows if r["variant"] == name]
        if not mine:
            continue
        missed = [len(r["missed_mandatory"]) for r in mine]
        summary[name] = {
            "repeats": len(mine),
            "missed_median": statistics.median(missed),
            "missed_range": [min(missed), max(missed)],
            "verified_mean": round(statistics.mean(r["verified_rate"] for r in mine), 4),
            "schema_failures": sum(r["schema_failures"] for r in mine),
            "tokens_mean": round(statistics.mean(r["tokens"] for r in mine)),
            "latency_ms_median": statistics.median(r["latency_ms"] for r in mine),
        }
    return summary


def write(rows: list[dict[str, Any]], stopped: str | None = None) -> dict[str, Any]:
    summary = summarize(rows)
    payload: dict[str, Any] = {"summary": summary, "repeats": rows}
    if stopped:
        payload["stopped"] = stopped
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8", newline="\n")
    return summary


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    from bidwright.cli import load_env

    load_env(ROOT / ".env")
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY is not set")
        return 1
    config = load_config()
    client = LLMClient(config, "free", default_backends(), run_id="s05")
    prompt = load_prompt("extract")
    ingest = ingest_pdf(ROOT / "inputs" / "dev" / "dev_rfp.pdf")
    passages = {p.id: p for p in ingest.passages}
    gold = [
        json.loads(line)
        for line in (GOLD_DIR / "dev" / "gold.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    clauses = gold_clauses(gold, ingest.frozen_text, ingest.passages)
    mandatory = {c.gold_id for c in clauses if c.kind == "requirement" and c.mandatory}
    rows: list[dict[str, Any]] = []
    for variant in VARIANTS:
        for repeat in range(1, REPEATS + 1):
            try:
                scores = [
                    run_batch(client, prompt, variant, repeat, number, batch, passages)
                    for number, batch in enumerate(
                        batches(ingest.passages, config.limits.batch_size), start=1
                    )
                ]
            except LLMError as exc:
                reason = f"{variant} #{repeat}: {type(exc).__name__}: {exc}"
                print(f"stopped at {reason}")
                print(json.dumps(write(rows, stopped=reason), indent=1))
                return 1
            outcomes = [s.outcome for s in scores]
            records, _ = assign_requirements(outcomes, ingest.passages)
            missed = sorted(mandatory - set(match(records, clauses, passages).captured))
            items = sum(s.items for s in scores)
            verified = sum(len(s.outcome.accepted) for s in scores)
            rows.append(
                {
                    "variant": variant,
                    "repeat": repeat,
                    "missed_mandatory": missed,
                    "verified_rate": round(verified / items, 4) if items else 0.0,
                    "schema_failures": sum(s.schema_failed for s in scores),
                    "calls": sum(s.calls for s in scores),
                    "tokens": sum(s.tokens for s in scores),
                    "latency_ms": sum(s.latency_ms for s in scores),
                }
            )
            write(rows)
            row = rows[-1]
            print(
                f"{variant} #{repeat}: missed {len(missed)}/{len(mandatory)} {missed}"
                f" verified {row['verified_rate']:.0%} schema failures {row['schema_failures']}"
                f" tokens {row['tokens']} {row['latency_ms']} ms",
                flush=True,
            )
    print(json.dumps(write(rows), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
