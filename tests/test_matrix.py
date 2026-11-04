"""The matrix runner and the report's decisions (Iteration 1, step 18). A stand-in for
`execute` writes each run's manifest with the status and cost a script gives, so no model,
key or gold is needed."""

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import evals.report
from bidwright import cli
from bidwright.graph.build import RunResult
from bidwright.matrix import MatrixRefused, load_matrix, run_matrix
from bidwright.schemas import RunManifest, RunTotals
from evals.report import decide, report

TWO_RUNGS = "  - {name: b10, flags: {batch_size: 10}}\n  - {name: b20, flags: {batch_size: 20}}\n"


def _matrix(
    tmp_path: Path,
    rungs: str = TWO_RUNGS,
    repeats: int = 2,
    max_cost_usd: float = 10,
) -> Path:
    path = tmp_path / "m.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"name: m\nrfp: inputs/hero\nprofile: free\nrepeats: {repeats}\nuntil: coverage\n"
        f"max_cost_usd: {max_cost_usd}\nrungs:\n{rungs}",
        encoding="utf-8",
    )
    return path


class FakeEntry:
    """Stands in for `execute`: keeps its arguments and writes a manifest with the next
    scripted status and cost, `COMPLETED` at no cost once the script runs out."""

    def __init__(self, script: list[tuple[str, float]] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.script = list(script or [])

    def __call__(self, **kwargs: Any) -> RunResult:
        self.calls.append(kwargs)
        status, cost = self.script.pop(0) if self.script else ("COMPLETED", 0.0)
        run_dir = kwargs["outputs"] / kwargs["run_id"]
        run_dir.mkdir(parents=True, exist_ok=True)
        manifest = RunManifest(
            run_id=kwargs["run_id"],
            commit="test",
            profile=kwargs["profile"],
            models={},
            started=datetime(2026, 11, 4, tzinfo=UTC),
            status=status,  # type: ignore[arg-type]
            totals=RunTotals(cost_usd=cost),
        )
        (run_dir / "run_manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
        return RunResult(kwargs["run_id"], run_dir, status, None)  # type: ignore[arg-type]


def _run(path: Path, entry: FakeEntry, tmp_path: Path, resume: bool = False) -> Any:
    lines: list[str] = []
    outcome = run_matrix(
        path, resume=resume, execute=entry, outputs=tmp_path / "out", say=lines.append
    )
    return outcome, lines


def test_rungs_and_repeats_run_in_order_with_their_flags(tmp_path: Path) -> None:
    entry = FakeEntry()
    outcome, _ = _run(_matrix(tmp_path), entry, tmp_path)
    assert outcome.status == "COMPLETED"
    assert [c["run_id"] for c in entry.calls] == ["m-b10-r0", "m-b10-r1", "m-b20-r0", "m-b20-r1"]
    assert [(c["batch_size"], c["repeat"]) for c in entry.calls] == [
        (10, 0),
        (10, 1),
        (20, 0),
        (20, 1),
    ]
    assert all(c["cache"] and c["until"] == "coverage" for c in entry.calls)
    manifest = json.loads(
        (tmp_path / "out" / "matrices" / "m" / "matrix_manifest.json").read_text(encoding="utf-8")
    )
    assert [r["status"] for r in manifest["runs"]] == ["COMPLETED"] * 4


def test_a_quota_stop_leaves_a_state_that_resume_finishes(tmp_path: Path) -> None:
    path = _matrix(tmp_path)
    entry = FakeEntry([("COMPLETED", 0.0), ("QUOTA_PAUSED", 0.0)])
    outcome, lines = _run(path, entry, tmp_path)
    assert outcome.status == "QUOTA_PAUSED" and len(entry.calls) == 2
    assert any(f"bidwright matrix run {path.as_posix()} --resume" in line for line in lines)
    with pytest.raises(MatrixRefused, match="--resume"):
        _run(path, FakeEntry(), tmp_path)
    again = FakeEntry()
    outcome, _ = _run(path, again, tmp_path, resume=True)
    assert outcome.status == "COMPLETED"
    assert [c["run_id"] for c in again.calls] == ["m-b10-r1", "m-b20-r0", "m-b20-r1"]
    assert [r.skipped for r in outcome.runs] == [True, False, False, False]


def test_the_cost_cap_stops_before_the_run_that_would_pass_it(tmp_path: Path) -> None:
    entry = FakeEntry([("COMPLETED", 4.0)] * 4)
    outcome, lines = _run(_matrix(tmp_path, max_cost_usd=10), entry, tmp_path)
    assert outcome.status == "COST_CAP"
    assert len(entry.calls) == 2 and outcome.spent_usd == 8.0, "a third $4 run would pass $10"
    assert "Stopped before m-b20-r0" in lines[-1]


def test_unknown_flags_are_refused(tmp_path: Path) -> None:
    path = _matrix(tmp_path, rungs="  - {name: hot, flags: {temperature: 0.5}}\n")
    with pytest.raises(ValueError, match="unknown flags"):
        load_matrix(path)
    assert cli.main(["matrix", "run", str(path)]) == 2


def test_the_committed_matrix_files_load() -> None:
    names = {
        load_matrix(path).name for path in sorted((cli.HOME / "config" / "matrices").glob("*.yaml"))
    }
    assert names == {"s03-batch", "s10-examples", "s13-second-pass"}


@pytest.mark.parametrize(
    ("kind", "control", "rung", "secondary", "passed"),
    [
        ("within_noise", [2, 3, 4], [4, 4, 5], None, True),
        ("within_noise", [2, 3, 4], [6, 6, 6], None, False),
        ("superiority", [5, 6, 7], [3, 3, 3], None, True),
        ("superiority", [5, 6, 7], [5, 5, 5], None, False),
        ("improvement", [5, 6, 7], [4, 4, 5], ([0.9, 0.9], [0.88, 0.88], 0.03), True),
        ("improvement", [5, 6, 7], [4, 4, 5], ([0.9, 0.9], [0.8, 0.8], 0.03), False),
        ("improvement", [5, 6, 7], [6, 6, 6], ([0.9, 0.9], [0.9, 0.9], 0.03), False),
    ],
)
def test_one_decision_per_kind(
    kind: str,
    control: list[float],
    rung: list[float],
    secondary: tuple[list[float], list[float], float] | None,
    passed: bool,
) -> None:
    assert decide(kind, control, rung, secondary)[0] is passed


def test_the_report_scores_finished_runs_and_decides_each_rung(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = FakeEntry([("COMPLETED", 0.0)] * 3 + [("UNRECOVERABLE_FAULT", 0.0)])
    _run(_matrix(tmp_path), entry, tmp_path)
    missed = {"m-b10-r0": 2, "m-b10-r1": 3, "m-b20-r0": 3}

    def fake_score(run_dir: Path, gold_dir: Path) -> dict[str, Any]:
        return {
            "corpus": "hero",
            "gold_version": 2,
            "gold_sha256": "a" * 64,
            "missed_mandatory_count": missed[run_dir.name],
            "precision_low": 0.9,
            "missed_mandatory": [],
        }

    monkeypatch.setattr(evals.report, "score_run", fake_score)
    hypotheses = tmp_path / "hypotheses.yaml"
    hypotheses.write_text(
        'm:\n  control: "b10"\n  rungs:\n    "b20": {metric: missed_mandatory_count,'
        " kind: within_noise}\n",
        encoding="utf-8",
    )
    out = report("m", outputs=tmp_path / "out", results=tmp_path / "res", hypotheses=hypotheses)
    data = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert data["finished"] == 3 and data["runs"] == 4
    assert data["rungs"]["b10"]["missed_mandatory_count"] == {
        "median": 2.5,
        "min": 2.0,
        "max": 3.0,
        "n": 2,
    }
    [decision] = data["decisions"]
    assert (decision["rung"], decision["passed"]) == ("b20", True), "3 - 2.5 is within 1"
    with (out / "runs.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [r["status"] for r in rows][-1] == "UNRECOVERABLE_FAULT"
    assert "| b20 | b10 | missed_mandatory_count | within_noise | pass |" in (
        out / "report.md"
    ).read_text(encoding="utf-8")


def test_failed_and_cleared_runs_count_toward_the_cap(tmp_path: Path) -> None:
    """A run that faults still spent its money, and clearing it on resume keeps that spend."""
    script = [("UNRECOVERABLE_FAULT", 4.0), ("QUOTA_PAUSED", 4.0)]
    tight = _matrix(tmp_path / "tight", max_cost_usd=10)
    outcome, _ = _run(tight, FakeEntry(script), tmp_path / "tight")
    assert outcome.status == "QUOTA_PAUSED" and outcome.spent_usd == 8.0
    again = FakeEntry()
    outcome, lines = _run(tight, again, tmp_path / "tight", resume=True)
    assert outcome.status == "COST_CAP" and again.calls == [], "$8 spent; a $4 run would pass $10"
    assert "Stopped before m-b10-r0" in lines[-1]
    roomy = _matrix(tmp_path / "roomy", max_cost_usd=20)
    _run(roomy, FakeEntry(script), tmp_path / "roomy")
    outcome, _ = _run(roomy, FakeEntry(), tmp_path / "roomy", resume=True)
    assert outcome.status == "COMPLETED" and outcome.cleared_usd == 8.0
    assert outcome.spent_usd == 8.0, "the cleared runs' spend stays on the matrix's account"
