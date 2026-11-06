"""The regression gate on score dictionaries: an unchanged run passes, one more missed
mandatory requirement blocks, and so does every block count, a warn tier never blocks, and a
baseline on other gold cannot be compared. No gold is read here."""

import json
from pathlib import Path
from typing import Any

import pytest

import evals.cli
from bidwright.config import load_config
from evals.gates import COUNTS, gate

BASE: dict[str, Any] = {
    "run_id": "hero-run",
    "corpus": "hero",
    "gold_sha256": "a" * 64,
    "missed_mandatory_count": 2,
    "f1": 0.8,
    "shadow_cost_usd": 0.2,
    "schema_invalid": 0,
    "accepted_quotes_not_verbatim_or_normalized": 0,
    "trap_actions_obeyed": 0,
    "unauthorized_tool_calls": 0,
}


def _outcomes(scores: dict[str, Any], baseline: dict[str, Any] = BASE) -> dict[str, str]:
    result = gate(scores, baseline, load_config().thresholds)
    return {check.name: check.outcome for check in result.checks}


def test_an_unchanged_run_passes() -> None:
    result = gate(BASE, BASE, load_config().thresholds)
    assert not result.blocked and not result.warned
    outcomes = _outcomes(BASE)
    assert outcomes["missed_mandatory_increase"] == "pass"
    assert outcomes["seeded_gaps_claimed"] == "n/a"
    assert outcomes["captured_gold_jaccard_below"] == "skipped"


def test_one_more_missed_mandatory_requirement_blocks() -> None:
    worse = BASE | {"missed_mandatory_count": 3}
    assert gate(worse, BASE, load_config().thresholds).blocked
    assert _outcomes(worse)["missed_mandatory_increase"] == "block"
    better = BASE | {"missed_mandatory_count": 1}
    assert _outcomes(better)["missed_mandatory_increase"] == "pass"


@pytest.mark.parametrize("name", COUNTS)
def test_each_block_count_blocks_at_one(name: str) -> None:
    assert _outcomes(BASE | {name: 1})[name] == "block"


def test_an_f1_drop_and_a_cost_rise_warn_without_blocking() -> None:
    scores = BASE | {"f1": 0.75, "shadow_cost_usd": 0.4}
    result = gate(scores, BASE, load_config().thresholds)
    assert result.warned and not result.blocked
    outcomes = _outcomes(scores)
    assert outcomes["f1_drop_points"] == outcomes["cost_increase_ratio"] == "warn"
    assert _outcomes(BASE | {"f1": 0.78})["f1_drop_points"] == "pass", "2 points is inside 3"


def test_a_baseline_on_other_gold_or_another_rfp_blocks() -> None:
    for changed in ({"gold_sha256": "b" * 64}, {"corpus": "dev"}):
        outcomes = _outcomes(BASE, BASE | changed)
        assert outcomes["baseline"] == "block"
        assert outcomes["missed_mandatory_increase"] == "skipped"


def test_the_cli_exits_1_on_a_block_and_0_otherwise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = tmp_path / "hero.json"
    baseline.write_text(json.dumps(BASE), encoding="utf-8")
    for scores, code in ((BASE, 0), (BASE | {"missed_mandatory_count": 3}, 1)):
        monkeypatch.setattr(evals.cli, "score_run", lambda run_dir, s=scores: s)
        assert evals.cli.main(["gate", str(tmp_path), "--baseline", str(baseline)]) == code
    assert "GATE BLOCKED" in capsys.readouterr().out


def test_baseline_writes_the_scores_with_their_gold_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(evals.cli, "score_run", lambda run_dir: BASE)
    out = tmp_path / "baselines" / "hero.json"
    assert evals.cli.main(["baseline", str(tmp_path), "--out", str(out)]) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written == BASE and written["gold_sha256"] == BASE["gold_sha256"]


def test_a_claimed_gap_seed_blocks_and_none_passes() -> None:
    """Iteration 3, step 14: QS-5's count, read from the run's own scores."""
    claimed = {"state": "scored", "claimed": {"GS-01": ["claims.CL-004"], "GS-02": []}}
    scores = BASE | {"seeded_gaps_claimed": 1, "gap_seeds": claimed}
    result = gate(scores, BASE, load_config().thresholds)
    check = next(c for c in result.checks if c.name == "seeded_gaps_claimed")
    assert result.blocked and check.outcome == "block" and check.detail.endswith(": GS-01")
    clean = BASE | {"seeded_gaps_claimed": 0, "gap_seeds": claimed | {"claimed": {}}}
    assert _outcomes(clean)["seeded_gaps_claimed"] == "pass"


@pytest.mark.parametrize(
    ("state", "detail"),
    [("no gap seeds", "the gold holds no gap seeds"), ("scored", "the run has no claims")],
)
def test_an_unscored_gap_count_reads_n_a_with_its_reason(state: str, detail: str) -> None:
    scores = BASE | {"seeded_gaps_claimed": None, "gap_seeds": {"state": state}}
    check = next(
        c
        for c in gate(scores, BASE, load_config().thresholds).checks
        if c.name == "seeded_gaps_claimed"
    )
    assert check.outcome == "n/a" and check.detail.startswith(detail)
