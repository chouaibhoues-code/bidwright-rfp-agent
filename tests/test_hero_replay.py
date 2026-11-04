"""The hero recording of step 16, replayed through `consolidate`, scored and gated against the
baseline committed at the `v0.1` tag. The gate applies from that tag: before it, no baseline
exists, since none may be scored before gold v2 is hashed, and the gate step is skipped."""

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
        pytest.skip("the hero baseline is written at the v0.1 tag, after gold v2 is hashed")
    outcome = gate(
        scores, json.loads(BASELINE.read_text(encoding="utf-8")), load_config().thresholds
    )
    assert not outcome.blocked, outcome.report()
