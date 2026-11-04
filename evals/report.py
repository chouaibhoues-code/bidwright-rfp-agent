"""`bidwright-eval report <matrix>`: score every run of a matrix and decide each rung.

Writes `evals/results/<matrix>/report.md`, `report.json` and `runs.csv`: per rung, the median,
the minimum and the maximum of each numeric score, and the decision `evals/hypotheses.yaml`
names. With spread(control) the control rung's maximum less its minimum:

- `within_noise` passes when median(rung) - median(control) <= spread(control);
- `superiority` passes when median(control) - median(rung) > spread(control);
- `improvement` passes when median(rung) < median(control) and, on its `secondary` metric,
  median(control) - median(rung) <= `max_drop`.

The metrics count down (missed mandatory requirements), and the secondary metric counts up
(precision). Only runs that finished, `COMPLETED` or `DEGRADED`, on their roles' primary
models are scored: a run with a call a fallback model answered is listed apart, and
`bidwright matrix run <file> --resume` runs it again. These are the
spikes' pass marks; the Master-Plan's bootstrap keep-or-drop rule applies to the ablation
ladders from Iteration 3. Scoring checks the hash of the hypotheses with the gold's.
"""

import csv
import json
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from bidwright.matrix import fell_back
from bidwright.schemas import RunManifest
from evals.score import GOLD_DIR, ROOT, score_run

HYPOTHESES = ROOT / "evals" / "hypotheses.yaml"
RESULTS = ROOT / "evals" / "results"
FINISHED = ("COMPLETED", "DEGRADED")
SHOWN = (
    "missed_mandatory_count",
    "missed_mandatory_strict_count",
    "recall",
    "precision_low",
    "precision_high",
    "f1",
    "first_pass_citation_error",
    "requests",
    "tokens",
    "cost_usd",
    "shadow_cost_usd",
)


def numeric(scores: Mapping[str, Any]) -> dict[str, float]:
    """The scorer's numeric keys: counts, rates and costs, never flags or lists."""
    return {
        key: float(value)
        for key, value in scores.items()
        if isinstance(value, int | float) and not isinstance(value, bool)
    }


def summary(values: Sequence[float]) -> dict[str, float]:
    return {
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "n": len(values),
    }


@dataclass(frozen=True)
class Decision:
    rung: str
    control: str
    metric: str
    kind: str
    passed: bool | None  # None when a rung has no finished run to decide on
    detail: str
    hypothesis: str = ""


def decide(
    kind: str,
    control: Sequence[float],
    rung: Sequence[float],
    secondary: tuple[Sequence[float], Sequence[float], float] | None = None,
) -> tuple[bool, str]:
    """One rung against its control, by the rule its kind names."""
    spread = max(control) - min(control)
    base, now = statistics.median(control), statistics.median(rung)
    if kind == "within_noise":
        return now - base <= spread, f"median {now:g} against {base:g}, spread {spread:g}"
    if kind == "superiority":
        return base - now > spread, f"median {now:g} against {base:g}, spread {spread:g}"
    if kind == "improvement":
        if secondary is None:
            raise ValueError("improvement needs a secondary metric")
        before, after, max_drop = secondary
        drop = statistics.median(before) - statistics.median(after)
        passed = now < base and drop <= max_drop
        return (
            passed,
            f"median {now:g} against {base:g}; secondary drop {drop:g} (max {max_drop:g})",
        )
    raise ValueError(f"unknown decision kind {kind!r}")


def _decisions(
    name: str, by_rung: Mapping[str, Sequence[dict[str, float]]], hypotheses: Mapping[str, Any]
) -> list[Decision]:
    plan = hypotheses.get(name)
    if not plan:
        return []
    control = str(plan["control"])
    decisions = []
    for rung, spec in plan["rungs"].items():
        metric, kind = spec["metric"], spec["kind"]
        before = [s[metric] for s in by_rung.get(control, []) if metric in s]
        after = [s[metric] for s in by_rung.get(str(rung), []) if metric in s]
        if not before or not after:
            decisions.append(
                Decision(str(rung), control, metric, kind, None, "no finished runs to compare")
            )
            continue
        secondary = None
        if "secondary" in spec:
            other = spec["secondary"]["metric"]
            secondary = (
                [s[other] for s in by_rung[control] if other in s],
                [s[other] for s in by_rung[str(rung)] if other in s],
                float(spec["secondary"]["max_drop"]),
            )
        passed, detail = decide(kind, before, after, secondary)
        decisions.append(
            Decision(str(rung), control, metric, kind, passed, detail, spec.get("hypothesis", ""))
        )
    return decisions


def _markdown(name: str, data: Mapping[str, Any]) -> str:
    rungs = list(data["rungs"])
    lines = [
        f"# Matrix `{name}`",
        "",
        f"Gold {data['gold']}. {data['finished']} of {data['runs']} runs finished and were scored."
        + (
            f" Left out, because a fallback model answered a call: {', '.join(data['fell_back'])};"
            " `bidwright matrix run <file> --resume` runs them again."
            if data["fell_back"]
            else ""
        ),
        "",
        "## Decisions",
        "",
        "| Rung | Control | Metric | Kind | Result | Detail |",
        "|---|---|---|---|---|---|",
    ]
    for d in data["decisions"]:
        result = "n/a" if d["passed"] is None else "pass" if d["passed"] else "fail"
        lines.append(
            f"| {d['rung']} | {d['control']} | {d['metric']} | {d['kind']} | {result}"
            f" | {d['detail']} |"
        )
    lines += [
        "",
        "## Scores by rung",
        "",
        "Median, with the minimum and the maximum in brackets.",
        "",
        "| Metric | " + " | ".join(rungs) + " |",
        "|---|" + "---|" * len(rungs),
    ]
    for metric in SHOWN:
        cells = []
        for rung in rungs:
            stats = data["rungs"][rung].get(metric)
            cells.append(
                "n/a"
                if stats is None
                else f"{stats['median']:g} ({stats['min']:g}-{stats['max']:g})"
            )
        lines.append(f"| {metric} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def report(
    name: str,
    *,
    outputs: Path | None = None,
    results: Path = RESULTS,
    gold_dir: Path = GOLD_DIR,
    hypotheses: Path = HYPOTHESES,
) -> Path:
    """Score every finished run of the matrix and write its report folder."""
    root = (outputs or ROOT / "outputs") / "matrices" / name
    manifest = json.loads((root / "matrix_manifest.json").read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    left_out: list[str] = []
    by_rung: dict[str, list[dict[str, float]]] = {}
    gold = "not scored"
    for run in manifest["runs"]:
        row: dict[str, Any] = {k: run[k] for k in ("run_id", "rung", "repeat", "status")}
        manifest_path = root / run["run_id"] / "run_manifest.json"
        if run["status"] in FINISHED and manifest_path.exists():
            if fell_back(RunManifest.model_validate_json(manifest_path.read_text("utf-8"))):
                left_out.append(run["run_id"])
                rows.append(row | {"status": f"{run['status']}, fallback model"})
                continue
            scores = score_run(root / run["run_id"], gold_dir)
            gold = f"{scores['corpus']} v{scores['gold_version']} {scores['gold_sha256'][:12]}"
            values = numeric(scores)
            by_rung.setdefault(run["rung"], []).append(values)
            row |= values
        rows.append(row)
    plan = yaml.safe_load(hypotheses.read_text(encoding="utf-8")) if hypotheses.exists() else {}
    decisions = _decisions(name, by_rung, plan or {})
    metrics = sorted({key for values in by_rung.values() for s in values for key in s})
    data = {
        "matrix": name,
        "gold": gold,
        "runs": len(rows),
        "finished": sum(len(v) for v in by_rung.values()),
        "fell_back": left_out,
        "rungs": {
            rung: {
                metric: summary([s[metric] for s in values if metric in s])
                for metric in metrics
                if any(metric in s for s in values)
            }
            for rung, values in by_rung.items()
        },
        "decisions": [d.__dict__ for d in decisions],
    }
    out = results / name
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(
        json.dumps(data, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    (out / "report.md").write_text(_markdown(name, data), encoding="utf-8", newline="\n")
    with (out / "runs.csv").open("w", encoding="utf-8", newline="") as handle:
        columns = ["run_id", "rung", "repeat", "status", *metrics]
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return out


__all__ = ["Decision", "decide", "numeric", "report", "summary"]
