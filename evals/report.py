"""`bidwright-eval report <matrix>`: score every run of a matrix and decide each rung.

Writes `evals/results/<matrix>/report.md`, `report.json` and `runs.csv`: per rung, the median,
the minimum and the maximum of each numeric score, and the decision `evals/hypotheses.yaml`
names. With spread(control) the control rung's maximum less its minimum:

- `within_noise` passes when median(rung) - median(control) <= spread(control);
- `superiority` passes when median(control) - median(rung) > spread(control);
- `improvement` passes when median(rung) < median(control) and, on its `secondary` metric,
  median(control) - median(rung) <= `max_drop`;
- `worst_repeat` passes when max(rung) <= max(control): no repeat is worse than the
  control's worst (ADR-055, for a metric a block rule wants at zero in every repeat).

The metrics count down (missed mandatory requirements), and the secondary metric counts up
(precision). A hypothesis may give `within_noise` and `worst_repeat` a `direction: higher`
for a metric that counts up (risk-seed recall), which turns each comparison around. A rung
may also hold `checks`, a list of `{metric, kind, direction}`, instead of one `metric` and
`kind`; each check is decided on its own and reported as its own row (S-12's scorecard check,
ADR-055). Only runs that finished, `COMPLETED` or `DEGRADED`, on their roles' primary
models are scored: a run with a call a fallback model answered is listed apart, and
`bidwright matrix run <file> --resume` runs it again. A repeat the runner recorded `invalid`,
after its third end under section 4.11's re-run rule, is left out with its note. These are the
spikes' pass marks. The ablation ladders of Iteration 3 (step 16, section 4.11) use a fourth
kind, `keep_or_drop`:

- a ladder's main chain is taken in order, its control kept; each later rung is compared
  with the last rung kept, and a side rung, one that names `compare_to`, with that rung only,
  never becoming a comparator itself;
- `d` is the difference of the two medians on the rung's metric, signed so that a positive
  `d` is favorable (comparator minus rung for `direction: lower`, rung minus comparator for
  `higher`), and `[lo, hi]` its 90% bootstrap interval: each rung's repeats resampled with
  replacement, independently, 10,000 times, with `random.Random` seeded from the first 8
  bytes of the SHA-256 of the matrix name, and the 5th and 95th percentiles taken;
- with no `margin`, a rung is kept when `lo > 0`; with a margin `m`, when `lo >= -m` (the
  metric rises by no more than its margin, ADR-054) and the signed difference of the medians
  of its `secondary` metric is above 0;
- the cost per avoided miss, the difference of the median shadow costs over the difference
  of the median missed mandatory requirements, is reported, `n/a` when no miss is avoided,
  and never decides.

The report also gives QS-8 for each rung with two or more scored repeats: the median
pairwise Jaccard over the gold clause ids the repeats capture, a warning below
`config/thresholds.yaml`'s `captured_gold_jaccard_below`. Scoring checks the hash of the
hypotheses with the gold's.
"""

import csv
import hashlib
import itertools
import json
import random
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from bidwright.config import load_config
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
    # `keep_or_drop` only: the signed difference, its interval, the cost per avoided miss
    # (None when no miss is avoided) and whether the rung is a side rung.
    d: float | None = None
    interval: tuple[float, float] | None = None
    cost_per_avoided_miss: float | None = None
    side: bool = False

    def row(self) -> dict[str, Any]:
        """The decision as `report.json` keeps it; the `keep_or_drop` fields only on its
        kind, which the Ops page reads."""
        row: dict[str, Any] = {
            "rung": self.rung,
            "control": self.control,
            "metric": self.metric,
            "kind": self.kind,
            "passed": self.passed,
            "detail": self.detail,
            "hypothesis": self.hypothesis,
        }
        if self.kind == KEEP_OR_DROP:
            row |= {
                "d": self.d,
                "interval": list(self.interval) if self.interval else None,
                "cost_per_avoided_miss": self.cost_per_avoided_miss,
                "side": self.side,
            }
        return row


def decide(
    kind: str,
    control: Sequence[float],
    rung: Sequence[float],
    secondary: tuple[Sequence[float], Sequence[float], float] | None = None,
    direction: str = "lower",
) -> tuple[bool, str]:
    """One rung against its control, by the rule its kind names. `direction: higher` turns
    `within_noise` and `worst_repeat` around, for a metric that counts up."""
    if direction not in ("lower", "higher"):
        raise ValueError(f"direction takes lower or higher, not {direction!r}")
    sign = 1 if direction == "lower" else -1
    spread = max(control) - min(control)
    base, now = statistics.median(control), statistics.median(rung)
    if kind == "within_noise":
        return (
            sign * (now - base) <= spread,
            f"median {now:g} against {base:g}, spread {spread:g}",
        )
    if kind == "worst_repeat":
        worst, then = (max(rung), max(control)) if sign == 1 else (min(rung), min(control))
        return sign * (worst - then) <= 0, f"worst repeat {worst:g} against {then:g}"
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


KEEP_OR_DROP = "keep_or_drop"
RESAMPLES = 10_000
COST = "shadow_cost_usd"
MISSES = "missed_mandatory_count"


def _signed(direction: str, comparator: float, rung: float) -> float:
    if direction == "lower":
        return comparator - rung
    if direction == "higher":
        return rung - comparator
    raise ValueError(f"direction takes lower or higher, not {direction!r}")


def bootstrap(
    matrix: str, comparator: Sequence[float], rung: Sequence[float], direction: str
) -> tuple[float, float, float]:
    """`d` and its 90% bootstrap interval `lo` and `hi` (section 4.11)."""
    seed = int.from_bytes(hashlib.sha256(matrix.encode("utf-8")).digest()[:8], "big")
    rng = random.Random(seed)  # noqa: S311 - a reproducible resample, not a secret
    d = _signed(direction, statistics.median(comparator), statistics.median(rung))
    samples = sorted(
        _signed(
            direction,
            statistics.median(rng.choices(comparator, k=len(comparator))),
            statistics.median(rng.choices(rung, k=len(rung))),
        )
        for _ in range(RESAMPLES)
    )
    cuts = statistics.quantiles(samples, n=20, method="inclusive")
    return d, round(cuts[0], 6), round(cuts[-1], 6)


def _median(runs: Sequence[Mapping[str, float]], key: str) -> float | None:
    values = [s[key] for s in runs if key in s]
    return statistics.median(values) if values else None


def cost_per_avoided_miss(
    comparator: Sequence[Mapping[str, float]], rung: Sequence[Mapping[str, float]]
) -> float | None:
    """Dollars per avoided miss, from the medians, None when no miss is avoided; it never
    decides."""
    cost_now, cost_then = _median(rung, COST), _median(comparator, COST)
    misses_then, misses_now = _median(comparator, MISSES), _median(rung, MISSES)
    if None in (cost_now, cost_then, misses_then, misses_now):
        return None
    avoided = float(misses_then or 0) - float(misses_now or 0)
    if avoided <= 0:
        return None
    return round((float(cost_now or 0) - float(cost_then or 0)) / avoided, 6)


def keep_or_drop(
    matrix: str,
    rung: str,
    comparator_name: str,
    comparator: Sequence[Mapping[str, float]],
    runs: Sequence[Mapping[str, float]],
    spec: Mapping[str, Any],
) -> Decision:
    """One rung against its comparator by section 4.11's rule."""
    metric, direction = spec["metric"], spec["direction"]
    before = [s[metric] for s in comparator if metric in s]
    after = [s[metric] for s in runs if metric in s]
    d, lo, hi = bootstrap(matrix, before, after, direction)
    detail = f"d {d:g}, 90% interval [{lo:g}, {hi:g}]"
    margin = spec.get("margin")
    if margin is None:
        kept = lo > 0
    else:
        other = spec["secondary"]
        then, now = _median(comparator, other["metric"]), _median(runs, other["metric"])
        gain = (
            _signed(other["direction"], then, now) if then is not None and now is not None else 0.0
        )
        kept = lo >= -float(margin) and gain > 0
        detail += f"; margin {float(margin):g}, {other['metric']} gain {gain:g}"
    cost = cost_per_avoided_miss(comparator, runs)
    detail += "; cost per avoided miss " + ("n/a" if cost is None else f"${cost:g}")
    side = spec.get("compare_to") is not None
    return Decision(
        rung,
        comparator_name,
        metric,
        KEEP_OR_DROP,
        kept,
        ("side rung; " if side else "") + detail,
        spec.get("hypothesis", ""),
        d=d,
        interval=(lo, hi),
        cost_per_avoided_miss=cost,
        side=side,
    )


def _ladder(
    name: str, plan: Mapping[str, Any], by_rung: Mapping[str, Sequence[dict[str, float]]]
) -> list[Decision]:
    """A `keep_or_drop` ladder: the main chain in order, a side rung against its
    `compare_to`, which it never replaces as the last rung kept."""
    last_kept = str(plan["control"])
    decisions = []
    for key, spec in plan["rungs"].items():
        rung = str(key)
        side = spec.get("compare_to")
        comparator = str(side) if side is not None else last_kept
        metric = spec["metric"]
        before = [s for s in by_rung.get(comparator, []) if metric in s]
        after = [s for s in by_rung.get(rung, []) if metric in s]
        if not before or not after:
            decisions.append(
                Decision(
                    rung,
                    comparator,
                    metric,
                    KEEP_OR_DROP,
                    None,
                    "no finished runs to compare",
                    spec.get("hypothesis", ""),
                    side=side is not None,
                )
            )
            continue
        decision = keep_or_drop(name, rung, comparator, before, after, spec)
        if decision.passed and side is None:
            last_kept = rung
        decisions.append(decision)
    return decisions


def jaccard_median(captured: Sequence[Sequence[str]]) -> float | None:
    """QS-8: the median pairwise Jaccard over the gold clause ids each repeat captures."""
    sets = [set(c) for c in captured]
    pairs = list(itertools.combinations(sets, 2))
    if not pairs:
        return None
    values = [len(a & b) / len(a | b) if a | b else 1.0 for a, b in pairs]
    return round(statistics.median(values), 4)


def consistency(captured: Mapping[str, Sequence[Sequence[str]]], below: float) -> dict[str, Any]:
    """QS-8 per rung with two or more scored repeats, warning below the threshold."""
    found: dict[str, Any] = {}
    for rung, runs in captured.items():
        value = jaccard_median(runs)
        if value is not None:
            found[rung] = {"jaccard": value, "repeats": len(runs), "warn": value < below}
    return found


def _decisions(
    name: str, by_rung: Mapping[str, Sequence[dict[str, float]]], hypotheses: Mapping[str, Any]
) -> list[Decision]:
    plan = hypotheses.get(name)
    if not plan:
        return []
    if any(spec.get("kind") == KEEP_OR_DROP for spec in plan["rungs"].values()):
        return _ladder(name, plan, by_rung)
    control = str(plan["control"])
    decisions = []
    for rung, spec in plan["rungs"].items():
        checks = spec.get("checks") or [spec]
        for check in checks:
            decisions.append(_check(str(rung), control, by_rung, check, spec))
    return decisions


def _check(
    rung: str,
    control: str,
    by_rung: Mapping[str, Sequence[dict[str, float]]],
    check: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> Decision:
    """One metric of a rung against the control, by the check's kind."""
    metric, kind = check["metric"], check["kind"]
    hypothesis = spec.get("hypothesis", "")
    before = [s[metric] for s in by_rung.get(control, []) if metric in s]
    after = [s[metric] for s in by_rung.get(rung, []) if metric in s]
    if not before or not after:
        return Decision(
            rung, control, metric, kind, None, "no finished runs to compare", hypothesis
        )
    secondary = None
    if "secondary" in check:
        other = check["secondary"]["metric"]
        secondary = (
            [s[other] for s in by_rung[control] if other in s],
            [s[other] for s in by_rung[rung] if other in s],
            float(check["secondary"]["max_drop"]),
        )
    passed, detail = decide(kind, before, after, secondary, check.get("direction", "lower"))
    return Decision(rung, control, metric, kind, passed, detail, hypothesis)


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
        )
        + (
            f" Left out as invalid under the re-run rule: {', '.join(data['invalid'])}."
            if data.get("invalid")
            else ""
        ),
        "",
        "## Decisions",
        "",
        "| Rung | Control | Metric | Kind | Result | Detail |",
        "|---|---|---|---|---|---|",
    ]
    for d in data["decisions"]:
        verdicts = ("keep", "drop") if d["kind"] == KEEP_OR_DROP else ("pass", "fail")
        result = "n/a" if d["passed"] is None else verdicts[0] if d["passed"] else verdicts[1]
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
    if data.get("consistency"):
        lines += [
            "",
            "## Consistency (QS-8)",
            "",
            "The median pairwise Jaccard over the gold clause ids each repeat captures.",
            "",
            "| Rung | Repeats | Jaccard | Result |",
            "|---|---|---|---|",
        ]
        for rung, row in data["consistency"].items():
            result = "warn" if row["warn"] else "pass"
            lines.append(f"| {rung} | {row['repeats']} | {row['jaccard']:g} | {result} |")
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
    invalid: list[str] = []
    by_rung: dict[str, list[dict[str, float]]] = {}
    captured: dict[str, list[list[str]]] = {}
    gold = "not scored"
    for run in manifest["runs"]:
        row: dict[str, Any] = {k: run[k] for k in ("run_id", "rung", "repeat", "status")}
        if run.get("invalid"):
            invalid.append(f"{run['run_id']} ({run.get('note') or 'invalid'})")
            rows.append(row | {"status": f"{run['status']}, invalid"})
            continue
        if run["status"] in FINISHED:
            manifest_path = root / run["run_id"] / "run_manifest.json"
            if fell_back(RunManifest.model_validate_json(manifest_path.read_text("utf-8"))):
                left_out.append(run["run_id"])
                rows.append(row | {"status": f"{run['status']}, fallback model"})
                continue
            scores = score_run(root / run["run_id"], gold_dir)
            gold = f"{scores['corpus']} v{scores['gold_version']} {scores['gold_sha256'][:12]}"
            values = numeric(scores)
            by_rung.setdefault(run["rung"], []).append(values)
            if "captured" in scores:
                captured.setdefault(run["rung"], []).append(list(scores["captured"]))
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
        "invalid": invalid,
        "rungs": {
            rung: {
                metric: summary([s[metric] for s in values if metric in s])
                for metric in metrics
                if any(metric in s for s in values)
            }
            for rung, values in by_rung.items()
        },
        "decisions": [d.row() for d in decisions],
        "consistency": consistency(
            captured, float(load_config().thresholds.warn["captured_gold_jaccard_below"])
        ),
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


__all__ = [
    "Decision",
    "bootstrap",
    "consistency",
    "cost_per_avoided_miss",
    "decide",
    "jaccard_median",
    "keep_or_drop",
    "numeric",
    "report",
    "summary",
]
