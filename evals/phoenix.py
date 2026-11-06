"""A run's scores on its Phoenix trace (ADR-053): `bidwright-eval phoenix <run>`.

The scorecard's headline lines become trace annotations, so Phoenix shows each run's misses,
precision, recall, grounding and safety beside its trace, and its filters can find the runs
that missed a hazard. Like the results files, an annotation holds scores, counts and gold ids,
never a clause's text. Each one carries an identifier, so scoring a run again updates them.
"""

from pathlib import Path
from typing import Any

from bidwright.obs.phoenix import PhoenixClient, run_spans
from bidwright.preflight import Refused

# The scores pushed: (annotation name, the scores key, how its label reads).
HEADLINE = (
    ("eval: missed mandatory", "missed_mandatory_count", "{value} of {mandatory_total} missed"),
    ("eval: missed hazards", "missed_hazards", "{count} of {hazards_total} missed"),
    ("eval: recall", "recall", "{value:.0%}"),
    ("eval: precision (low)", "precision_low", "{value:.0%}"),
    ("eval: F1", "f1", "{value:.2f}"),
    ("eval: verbatim quotes", "verbatim_rate", "{value:.0%}"),
    ("eval: trap actions obeyed", "trap_actions_obeyed", "{value}"),
    ("eval: unauthorized tool calls", "unauthorized_tool_calls", "{value}"),
    ("eval: approach mapping", "approach_mapping", "{value:.0%}"),
    ("eval: risk seed recall", "risk_seed_recall", "{value:.0%}"),
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, list):
        return float(len(value))
    return None


def score_annotations(scores: dict[str, Any], trace_ids: list[str]) -> list[dict[str, Any]]:
    rows = []
    run_id = str(scores.get("run_id", ""))
    for name, key, label in HEADLINE:
        value = scores.get(key)
        number = _number(value)
        if number is None:
            continue
        explanation = None
        if key == "missed_mandatory_count":
            explanation = ", ".join(scores.get("missed_mandatory", [])) or None
        if key == "missed_hazards":
            explanation = ", ".join(value) if isinstance(value, list) and value else None
        text = label.format(
            value=value if not isinstance(value, list) else len(value),
            count=len(value) if isinstance(value, list) else value,
            mandatory_total=scores.get("mandatory_total", "?"),
            hazards_total=scores.get("hazards_total", "?"),
        )
        for trace in trace_ids:
            rows.append(
                {
                    "trace_id": trace,
                    "name": name,
                    "annotator_kind": "CODE",
                    "result": {
                        "label": text,
                        "score": number,
                        **({"explanation": explanation} if explanation else {}),
                    },
                    "identifier": f"bidwright-eval:{run_id}:{name}",
                    "metadata": {
                        "run_id": run_id,
                        "gold_version": scores.get("gold_version"),
                        "gold_sha256": scores.get("gold_sha256"),
                    },
                }
            )
    return rows


def push_scores(
    run_dir: Path, scores: dict[str, Any], client: PhoenixClient | None = None
) -> tuple[int, str | None]:
    """Send the scores to every trace of the run Phoenix holds; the count and the last link."""
    spans = run_spans(run_dir)
    if not spans.roots:
        raise Refused(f"{run_dir.name} holds no spans.jsonl with a run span")
    client = client or PhoenixClient.from_env()
    held = [t for t in spans.roots if client.find_project(t) is not None]
    if not held:
        raise Refused(
            f"Phoenix holds no trace of {run_dir.name}; send it with bidwright phoenix sync first"
        )
    count = client.annotate_traces(score_annotations(scores, held))
    return count, client.trace_url(held[-1])


__all__ = ["HEADLINE", "push_scores", "score_annotations"]
