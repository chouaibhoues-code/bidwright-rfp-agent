"""The hero recording, replayed through `consolidate`, scored and gated against the baseline
written from it on 2026-11-04. Without a baseline, as before gold v2 was hashed, the gate step is
skipped."""

import json
from pathlib import Path

import pytest

from bidwright.config import load_config
from bidwright.preflight import HOME
from evals.gates import gate
from evals.score import score_run, scorecard
from tests.recordings import replay

pytestmark = pytest.mark.gold

BASELINE = HOME / "evals" / "baselines" / "hero.json"


def test_the_hero_replay_scores_and_passes_its_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PHOENIX_ENDPOINT", raising=False)
    result, _ = replay("hero", tmp_path)
    assert (result.reason or "").endswith("stopped after consolidate by request")
    scores = score_run(result.run_dir)
    assert scores["corpus"] == "hero" and scores["mandatory_total"] > 0
    assert set(scores["funnel"]) == {"guard", "parse", "extract", "verify", "consolidate"}
    assert scores["funnel"]["consolidate"] == []
    card = scorecard(scores)
    for heading in ("HEADLINE", "WHERE MANDATORY REQUIREMENTS WERE LOST", "SAFETY"):
        assert heading in card
    if not BASELINE.exists():
        pytest.skip("no hero baseline: none is scored before its gold is hashed")
    outcome = gate(
        scores, json.loads(BASELINE.read_text(encoding="utf-8")), load_config().thresholds
    )
    assert not outcome.blocked, outcome.report()
