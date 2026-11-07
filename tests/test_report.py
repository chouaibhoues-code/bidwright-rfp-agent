"""The report's `keep_or_drop` rule and QS-8 (Iteration 3, step 16; section 4.11), on fixture
scores: each direction, the non-inferiority margin, side rungs, the same verdict for the same
input, the cost per avoided miss, and the consistency warning; and the Ops page reading the
written report."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import evals.report
from app.data import load_ladder_reports
from bidwright.schemas import RunManifest, RunTotals
from evals.report import _decisions, consistency, cost_per_avoided_miss, jaccard_median, report

LOWER = {"metric": "missed_mandatory_count", "kind": "keep_or_drop", "direction": "lower"}


def _runs(metric: str, values: list[float], **others: list[float]) -> list[dict[str, float]]:
    rows = [{metric: v} for v in values]
    for name, column in others.items():
        for row, value in zip(rows, column, strict=True):
            row[name] = value
    return rows


def _plan(rungs: dict[str, dict[str, Any]], control: str = "c0") -> dict[str, Any]:
    return {"m": {"control": control, "rungs": rungs}}


def test_a_clear_gain_is_kept_in_either_direction() -> None:
    misses = {
        "c0": _runs("missed_mandatory_count", [6, 7, 6, 7, 6]),
        "r1": _runs("missed_mandatory_count", [2, 3, 2, 2, 3]),
    }
    [kept] = _decisions("m", misses, _plan({"r1": LOWER}))
    assert kept.passed is True and kept.interval is not None and kept.interval[0] > 0
    assert kept.d == 4.0, "comparator minus rung, so fewer misses is positive"
    recall = {
        "c0": _runs("risk_seed_recall", [0.2, 0.3, 0.2, 0.3, 0.2]),
        "r1": _runs("risk_seed_recall", [0.8, 0.7, 0.8, 0.9, 0.8]),
    }
    higher = {"metric": "risk_seed_recall", "kind": "keep_or_drop", "direction": "higher"}
    [up] = _decisions("m", recall, _plan({"r1": higher}))
    assert up.passed is True and up.d == pytest.approx(0.6)


def test_an_interval_that_holds_zero_drops_the_rung() -> None:
    by_rung = {
        "c0": _runs("missed_mandatory_count", [3, 5, 4, 6, 2]),
        "r1": _runs("missed_mandatory_count", [4, 2, 6, 3, 5]),
    }
    [dropped] = _decisions("m", by_rung, _plan({"r1": LOWER}))
    assert dropped.passed is False
    assert dropped.interval is not None and dropped.interval[0] <= 0 <= dropped.interval[1]


def test_non_inferiority_keeps_a_rung_only_when_its_secondary_improves() -> None:
    spec = LOWER | {"margin": 1, "secondary": {"metric": "precision_low", "direction": "higher"}}
    control = _runs("missed_mandatory_count", [3, 3, 3, 3, 3], precision_low=[0.7] * 5)
    better = _runs("missed_mandatory_count", [3, 3, 3, 3, 3], precision_low=[0.8] * 5)
    worse = _runs("missed_mandatory_count", [3, 3, 3, 3, 3], precision_low=[0.6] * 5)
    plan = _plan({"r1": spec})
    [kept] = _decisions("m", {"c0": control, "r1": better}, plan)
    [dropped] = _decisions("m", {"c0": control, "r1": worse}, plan)
    assert kept.passed is True and "precision_low gain 0.1" in kept.detail
    assert dropped.passed is False, "no worse on misses, but precision fell"


def test_a_side_rung_meets_its_compare_to_and_never_becomes_the_comparator() -> None:
    by_rung = {
        "c0": _runs("missed_mandatory_count", [6, 6, 7, 6, 6]),
        "r1": _runs("missed_mandatory_count", [3, 3, 2, 3, 3]),
        "r1-t": _runs("missed_mandatory_count", [0, 0, 1, 0, 0]),
        "r2": _runs("missed_mandatory_count", [1, 1, 1, 1, 1]),
    }
    plan = _plan({"r1": LOWER, "r1-t": LOWER | {"compare_to": "r1"}, "r2": LOWER})
    r1, side, r2 = _decisions("m", by_rung, plan)
    assert (r1.control, side.control, r2.control) == ("c0", "r1", "r1")
    assert side.passed is True and side.side and side.detail.startswith("side rung")
    assert r2.passed is True, "compared with r1, the last main rung kept, not with r1-t"


def test_the_same_input_gives_the_same_verdict() -> None:
    by_rung = {
        "c0": _runs("missed_mandatory_count", [4, 5, 3, 6, 4]),
        "r1": _runs("missed_mandatory_count", [3, 4, 3, 5, 2]),
    }
    first = _decisions("m", by_rung, _plan({"r1": LOWER}))
    again = _decisions("m", by_rung, _plan({"r1": LOWER}))
    assert first == again


def test_the_cost_per_avoided_miss_reads_n_a_when_no_miss_is_avoided() -> None:
    then = _runs("missed_mandatory_count", [4, 4, 4], shadow_cost_usd=[1.0, 1.0, 1.0])
    fewer = _runs("missed_mandatory_count", [2, 2, 2], shadow_cost_usd=[2.0, 2.0, 2.0])
    same = _runs("missed_mandatory_count", [4, 4, 5], shadow_cost_usd=[2.0, 2.0, 2.0])
    assert cost_per_avoided_miss(then, fewer) == 0.5
    assert cost_per_avoided_miss(then, same) is None


def test_qs8_warns_below_the_threshold() -> None:
    steady = [["GR-1", "GR-2", "GR-3"]] * 3
    one_short = [["GR-1", "GR-2", "GR-3"], ["GR-1", "GR-2", "GR-3"], ["GR-1", "GR-2"]]
    shaky = [["GR-1", "GR-2"], ["GR-3", "GR-4"], ["GR-1", "GR-4"]]
    assert jaccard_median(steady) == 1.0 and jaccard_median([["GR-1"]]) is None
    assert jaccard_median(one_short) == 0.6667, "pairs 1, 2/3 and 2/3"
    found = consistency({"steady": steady, "shaky": shaky}, 0.85)
    assert found["steady"] == {"jaccard": 1.0, "repeats": 3, "warn": False}
    assert found["shaky"]["warn"] is True


def _matrix(root: Path, misses: dict[str, list[int]]) -> None:
    folder = root / "matrices" / "lad"
    runs = []
    for rung, values in misses.items():
        for repeat, _ in enumerate(values):
            run_id = f"lad-{rung}-r{repeat}"
            (folder / run_id).mkdir(parents=True)
            manifest = RunManifest(
                run_id=run_id,
                commit="test",
                profile="paid",
                models={},
                started=datetime(2026, 11, 6, tzinfo=UTC),
                status="COMPLETED",
                totals=RunTotals(),
            )
            (folder / run_id / "run_manifest.json").write_text(manifest.model_dump_json())
            runs.append({"run_id": run_id, "rung": rung, "repeat": repeat, "status": "COMPLETED"})
    (folder / "matrix_manifest.json").write_text(json.dumps({"runs": runs}), encoding="utf-8")


def test_the_report_writes_a_ladder_the_ops_page_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    misses = {"c0": [6, 7, 6, 7, 6], "r1": [2, 3, 2, 2, 3], "r2": [3, 2, 4, 2, 3]}
    _matrix(tmp_path / "out", misses)

    def fake_score(run_dir: Path, gold_dir: Path) -> dict[str, Any]:
        _, rung, repeat = run_dir.name.split("-")
        count = misses[rung][int(repeat[1:])]
        return {
            "corpus": "hero",
            "gold_version": 4,
            "gold_sha256": "a" * 64,
            "missed_mandatory_count": count,
            "shadow_cost_usd": 0.5 if rung == "c0" else 1.0,
            "captured": [f"GR-{n}" for n in range(10 - count)],
        }

    monkeypatch.setattr(evals.report, "score_run", fake_score)
    hypotheses = tmp_path / "hypotheses.yaml"
    hypotheses.write_text(
        'lad:\n  control: "c0"\n  rungs:\n'
        '    "r1": {metric: missed_mandatory_count, kind: keep_or_drop, direction: lower}\n'
        '    "r2": {metric: missed_mandatory_count, kind: keep_or_drop, direction: lower}\n',
        encoding="utf-8",
    )
    results = tmp_path / "evals" / "results"
    out = report("lad", outputs=tmp_path / "out", results=results, hypotheses=hypotheses)
    data = json.loads((out / "report.json").read_text(encoding="utf-8"))
    r1, r2 = data["decisions"]
    assert (r1["passed"], r2["passed"], r2["control"]) == (True, False, "r1")
    assert len(r1["interval"]) == 2 and r1["cost_per_avoided_miss"] == 0.125
    assert data["consistency"]["c0"]["repeats"] == 5
    markdown = (out / "report.md").read_text(encoding="utf-8")
    assert "| r1 | c0 | missed_mandatory_count | keep_or_drop | keep |" in markdown
    assert "## Consistency (QS-8)" in markdown
    [ladder] = load_ladder_reports(results)
    rows = {row.rung: row for row in ladder.rows}
    assert rows["r1"].verdict == "keep" and rows["r2"].verdict == "drop"
    assert rows["r1"].interval.startswith("[") and rows["r1"].cost_per_avoided_miss == "$0.125"


def test_a_tie_at_the_margin_is_kept_as_adr_054_states() -> None:
    """ADR-054: a non-inferiority rung is kept when `lo >= -m`, the Master-Plan's "rise by no
    more than its margin". A rung that ties its comparator at zero gap assertions, margin 0,
    is kept when its secondary improves, and dropped when it does not; one whose interval
    falls below the margin is dropped."""
    spec = {
        "metric": "gap_assertions",
        "kind": "keep_or_drop",
        "direction": "lower",
        "margin": 0,
        "secondary": {"metric": "approach_mapping", "direction": "higher"},
    }
    plan = _plan({"r1": spec})
    control = _runs("gap_assertions", [0] * 5, approach_mapping=[0.6] * 5)
    rung = _runs("gap_assertions", [0] * 5, approach_mapping=[0.9] * 5)
    [tie] = _decisions("m", {"c0": control, "r1": rung}, plan)
    assert tie.interval == (0.0, 0.0) and tie.passed is True
    flat = _runs("gap_assertions", [0] * 5, approach_mapping=[0.6] * 5)
    [same] = _decisions("m", {"c0": control, "r1": flat}, plan)
    assert same.passed is False, "a tie with no secondary gain is dropped"
    worse = _runs("gap_assertions", [1] * 5, approach_mapping=[0.9] * 5)
    [above] = _decisions("m", {"c0": control, "r1": worse}, plan)
    assert above.interval == (-1.0, -1.0) and above.passed is False


def test_within_noise_and_worst_repeat_take_a_direction() -> None:
    """ADR-055: `within_noise` and `worst_repeat` read `direction: higher` for a metric that
    counts up, and `worst_repeat` fails on one repeat worse than the control's worst."""
    control = _runs("risk_seed_recall", [0.5, 0.67, 0.5, 0.67, 0.5])
    held = _runs("risk_seed_recall", [0.5, 0.5, 0.67, 0.5, 0.5])
    fell = _runs("risk_seed_recall", [0.17, 0.33, 0.17, 0.33, 0.17])
    spec = {"metric": "risk_seed_recall", "kind": "within_noise", "direction": "higher"}
    [ok] = _decisions("m", {"c0": control, "r1": held}, _plan({"r1": spec}))
    [low] = _decisions("m", {"c0": control, "r1": fell}, _plan({"r1": spec}))
    assert (ok.passed, low.passed) == (True, False)
    zero = _runs("seeded_gaps_claimed", [0] * 5)
    one = _runs("seeded_gaps_claimed", [0, 0, 1, 0, 0])
    worst = {"metric": "seeded_gaps_claimed", "kind": "worst_repeat"}
    median = {"metric": "seeded_gaps_claimed", "kind": "within_noise"}
    [strict] = _decisions("m", {"c0": zero, "r1": one}, _plan({"r1": worst}))
    [loose] = _decisions("m", {"c0": zero, "r1": one}, _plan({"r1": median}))
    assert strict.passed is False and "worst repeat 1 against 0" in strict.detail
    assert loose.passed is True, "the median rule lets one repeat claim a gap"
    [floor] = _decisions(
        "m",
        {"c0": control, "r1": _runs("risk_seed_recall", [0.5, 0.5, 0.33, 0.5, 0.5])},
        _plan({"r1": worst | {"metric": "risk_seed_recall", "direction": "higher"}}),
    )
    assert floor.passed is False, "a repeat below the control's lowest recall"


def test_a_rung_with_checks_gets_a_decision_for_each() -> None:
    """S-12's scorecard check (ADR-055): one rung, three metrics, each its own row; a metric
    the runs lack reads as not decided."""
    spec = {
        "checks": [
            {"metric": "missed_mandatory_count", "kind": "within_noise"},
            {"metric": "seeded_gaps_claimed", "kind": "worst_repeat"},
            {"metric": "risk_seed_recall", "kind": "within_noise", "direction": "higher"},
        ],
        "hypothesis": "cards keep the scorecard",
    }
    control = _runs("missed_mandatory_count", [3, 4, 3, 3, 4], seeded_gaps_claimed=[0] * 5)
    rung = _runs("missed_mandatory_count", [3, 3, 4, 3, 3], seeded_gaps_claimed=[0] * 5)
    misses, gaps, recall = _decisions("m", {"off": control, "on": rung}, _plan({"on": spec}, "off"))
    assert [d.metric for d in (misses, gaps, recall)] == [
        "missed_mandatory_count",
        "seeded_gaps_claimed",
        "risk_seed_recall",
    ]
    assert (misses.passed, gaps.passed, recall.passed) == (True, True, None)
    assert misses.hypothesis == "cards keep the scorecard"
