"""`bidwright-eval explain <run> <gold_id>`: what happened to one gold item in one run.

For a clause it prints its status (captured, missed, kept out, a false positive, or for a
hidden clause whether `guard` quarantined it), the records that captured it, the stage that
lost it and why, its passages, and the span of the `extract` call that read them when
`spans.jsonl` has one: the call comes from the context manifests, `context/extract-*.json`,
and the span from its `bidwright.call_id`. For a trap it prints where its marker appears.
"""

import json
from pathlib import Path
from typing import Any

from bidwright.ingest import display_text
from evals.matcher import PREDICTIONS, GoldClause, in_quarantine, overlapping
from evals.score import GOLD_DIR, Analysis, analyze
from evals.seeds import model_texts, trap_results

PASSAGE_CHARS = 160


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def extract_span(run_dir: Path, src_id: str) -> str | None:
    """The span of the `extract` call whose pack included the passage, as `spans.jsonl` and
    the context manifests record them."""
    calls = []
    for path in sorted((run_dir / "context").glob("extract-*.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if src_id in manifest.get("included_src_ids", []):
            calls.append(manifest["call_id"])
    if not calls:
        return None
    for span in _jsonl(run_dir / "spans.jsonl"):
        attributes = span.get("attributes", {})
        if span.get("name") == "node.extract" and attributes.get("bidwright.call_id") in calls:
            context = span.get("context", {})
            return (
                f"node.extract {context.get('span_id')} in trace {context.get('trace_id')}"
                f" (call {attributes['bidwright.call_id']})"
            )
    return f"no span in spans.jsonl for call {calls[0]}"


def _label(clause: GoldClause) -> str:
    if clause.kind != "requirement":
        return clause.kind.replace("_", " ")
    return "mandatory" if clause.mandatory else "optional"


def _clause(a: Analysis, clause: GoldClause) -> list[str]:
    def head(status: str) -> str:
        return f'{status}  {clause.gold_id}  {_label(clause)}  "{clause.text}"'

    records = {r.id: r for r in a.records}
    if clause.hidden:
        found = in_quarantine(clause.text, a.trail.quarantined)
        status = "QUARANTINED" if found else "NOT QUARANTINED"
        return [head(status), f"Layer: {clause.layer}, expected in quarantine"]
    lines = []
    if clause.kind == "requirement":
        owners = a.result.captured.get(clause.gold_id, [])
        if owners:
            marks = [
                f"{i} ({'strict' if clause.gold_id in a.result.strict else 'relaxed'}"
                f"{', duplicate' if i in a.result.duplicate else ''})"
                for i in owners
            ]
            lines = [head("CAPTURED"), f"Records: {', '.join(marks)}"]
        else:
            loss = a.loss(clause)
            lines = [
                head("MISSED"),
                f"Lost at: {loss.stage}    Reason: {loss.reason}",
            ]
    else:
        wrong = [
            i
            for i in a.result.covering.get(clause.gold_id, [])
            if records[i].disposition in PREDICTIONS
        ]
        status = "FALSE POSITIVE" if wrong else "KEPT OUT"
        lines = [head(status)]
        if wrong:
            lines.append(f"Records: {', '.join(wrong)}")
    if clause.span is None:
        lines.append("Passage: none; the clause is not in frozen.txt")
        return lines
    for passage in overlapping(clause.span, a.passages):
        text = display_text(passage.text)
        cut = text if len(text) <= PASSAGE_CHARS else text[: PASSAGE_CHARS - 3] + "..."
        lines.append(f'Passage: {passage.id}  "{cut}"')
        lines.append(f"Span: {extract_span(a.run_dir, passage.id) or 'no extract call read it'}")
    return lines


def explain(run_dir: Path, gold_id: str, gold_dir: Path = GOLD_DIR) -> str:
    a = analyze(run_dir, gold_dir)
    line = next((g for g in a.gold.lines if g["gold_id"] == gold_id), None)
    if line is None:
        raise LookupError(f"{gold_id} is not in the {a.gold.corpus} gold")
    clause = a.by_clause.get(gold_id)
    if clause is not None:
        return "\n".join(_clause(a, clause)) + "\n"
    if line["kind"] == "trap":
        result = trap_results([line], model_texts(run_dir), a.trail.quarantined)[gold_id]
        status = "OBEYED" if result["obeyed"] else "NOT OBEYED"
        where = ", ".join(result["where"]) or "no model-written field"
        quarantine = "quarantined" if result["quarantined"] else "not quarantined"
        expected = "expected" if result["expect_quarantined"] else "not expected"
        return (
            f"{status}  {gold_id}  trap in layer {result['layer']}\n"
            f"Marker found in: {where}\n"
            f"Quarantine: {quarantine} ({expected})\n"
        )
    return f"{gold_id} is a {line['kind'].replace('_', ' ')}; the scorecard reports it\n"


__all__ = ["explain", "extract_span"]
