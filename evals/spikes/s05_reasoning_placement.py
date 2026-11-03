"""S-05: where should `extract` reason? Three variants on the development RFP, 5 repeats each.

- A, schema only: `thinking: minimal`, the current extract setting, with the schema enforced.
- B, thinking plus schema: `thinking: medium`, with the schema enforced.
- C, two-step: a free-text reasoning call at `minimal`, then the schema call with that
  reasoning in the conversation.

Each repeat scores the first structured answer, before any repair, so the variants differ only
in where reasoning happens: missed mandatory requirements against gold v1, and the share of
quotes `verify` accepts. Pass mark: the cheapest variant within noise of the best. Run with
`uv run python -m evals.spikes.s05_reasoning_placement`; it needs GEMINI_API_KEY and makes about
40 Flash-Lite calls. Synthetic text only.
"""

import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from bidwright.config import load_config
from bidwright.graph.nodes import batches
from bidwright.ingest import display_text, ingest_pdf
from bidwright.llm.client import LLMClient, default_backends
from bidwright.llm.schema import sha256_of
from bidwright.llm.types import Message
from bidwright.prompts import load_prompt
from bidwright.schemas import ExtractBatch, ExtractResult, PassageView, Requirement
from bidwright.verify import check_quote
from evals.matcher import gold_clauses, match
from evals.score import GOLD_DIR

ROOT = Path(__file__).resolve().parents[2]
REPEATS = 5
PACE_S = 4.5  # Flash-Lite allows 15 requests a minute on the free tier
REASON = (
    "Before giving the JSON, reason in plain text: for each passage id, say whether it places an"
    " obligation on the supplier, which row of the decision table applies, and the exact words to"
    " quote. Do not return JSON yet."
)
TO_JSON = "Now return the result as JSON that matches the response schema."


def _records(
    result: ExtractResult, passages: dict[str, Any], start: int
) -> tuple[list[Requirement], int]:
    records, verified = [], 0
    for item in result.items:
        cited = [passages[s] for s in item.src_ids if s in passages]
        check = check_quote(item.quote, cited) if cited else None
        if check is None or check.status == "REJECTED" or check.src_id is None:
            continue
        verified += 1
        records.append(
            Requirement(
                id=f"REQ-{start + len(records):04d}",
                doc_id="dev",
                statement=item.statement,
                modality=item.modality,
                mandatory=item.disposition == "BINDING",
                hazard=item.hazard,
                disposition=item.disposition,
                src_ids=[check.src_id],
                quote=item.quote,
                quote_status=check.status,
                quote_span=check.span,
            )
        )
    return records, verified


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    from bidwright.cli import load_env

    load_env(ROOT / ".env")
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY is not set")
        return 1
    client = LLMClient(load_config(), "free", default_backends(), run_id="s05")
    prompt = load_prompt("extract")
    ingest = ingest_pdf(ROOT / "inputs" / "dev" / "dev_rfp.pdf")
    passages = {p.id: p for p in ingest.passages}
    gold = [
        json.loads(line)
        for line in (GOLD_DIR / "dev" / "gold.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    clauses = gold_clauses(gold, ingest.frozen_text)
    mandatory = {c.gold_id for c in clauses if c.kind == "requirement" and c.mandatory}
    variants = {
        "A schema only": "minimal",
        "B thinking plus schema": "medium",
        "C two-step": "minimal",
    }
    rows: list[dict[str, Any]] = []
    for name, level in variants.items():
        for repeat in range(1, REPEATS + 1):
            records: list[Requirement] = []
            items = verified = calls = tokens = 0
            latency = 0
            for number, batch in enumerate(batches(ingest.passages, 20), start=1):
                view = ExtractBatch(
                    batch_id=f"B{number:02d}",
                    passages=[
                        PassageView(
                            src_id=p.id,
                            section_path=p.section_path,
                            text=display_text(p.text),
                            lead_in=display_text(passages[p.lead_in_id].text)
                            if p.lead_in_id
                            else None,
                        )
                        for p in batch
                    ],
                )
                rendered = prompt.render(
                    view.model_dump_json(), run_id=f"s05-{name}-{repeat}", batch_id=view.batch_id
                )
                messages = list(rendered.messages)
                ids = {"node": "s05", "agent": name, "prompt_hash": prompt.hash, "repeat": repeat}
                decoding = {"gemini": {"thinking": level}}
                if name.startswith("C"):
                    thought = client.complete(
                        "extract",
                        [*messages, Message("user", REASON)],
                        None,
                        input_hash=sha256_of([rendered.input_hash, "reason"]),
                        decoding=decoding,
                        **ids,
                    )
                    calls += 1
                    tokens += (
                        thought.usage.tokens_in
                        + thought.usage.tokens_out
                        + thought.usage.tokens_thinking
                    )
                    latency += thought.latency_ms
                    messages += [
                        Message("user", REASON),
                        thought.as_message(),
                        Message("user", TO_JSON),
                    ]
                    time.sleep(PACE_S)
                answer = client.complete(
                    "extract",
                    messages,
                    ExtractResult,
                    input_hash=rendered.input_hash,
                    decoding=decoding,
                    **ids,
                )
                calls += 1
                tokens += (
                    answer.usage.tokens_in + answer.usage.tokens_out + answer.usage.tokens_thinking
                )
                latency += answer.latency_ms
                if isinstance(answer.parsed, ExtractResult):
                    items += len(answer.parsed.items)
                    found, ok = _records(answer.parsed, passages, len(records) + 1)
                    records += found
                    verified += ok
                time.sleep(PACE_S)
            result = match(records, clauses, passages)
            missed = sorted(mandatory - set(result.captured))
            rows.append(
                {
                    "variant": name,
                    "repeat": repeat,
                    "missed_mandatory": missed,
                    "verified_rate": round(verified / items, 4) if items else 0.0,
                    "calls": calls,
                    "tokens": tokens,
                    "latency_ms": latency,
                }
            )
            rate = rows[-1]["verified_rate"]
            print(
                f"{name} #{repeat}: missed {len(missed)}/8 {missed}"
                f" verified {rate:.0%} tokens {tokens} {latency} ms",
                flush=True,
            )
    summary = {}
    for name in variants:
        mine = [r for r in rows if r["variant"] == name]
        summary[name] = {
            "missed_median": statistics.median(len(r["missed_mandatory"]) for r in mine),
            "missed_range": [
                min(len(r["missed_mandatory"]) for r in mine),
                max(len(r["missed_mandatory"]) for r in mine),
            ],
            "verified_mean": round(statistics.mean(r["verified_rate"] for r in mine), 4),
            "tokens_mean": round(statistics.mean(r["tokens"] for r in mine)),
            "latency_ms_median": statistics.median(r["latency_ms"] for r in mine),
        }
    out = ROOT / "evals" / "results" / "spikes" / "s05.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"summary": summary, "repeats": rows}, indent=1) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
