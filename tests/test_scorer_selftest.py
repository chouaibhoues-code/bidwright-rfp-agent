"""The 0a scorer self-test: a scorer that cannot fail shows nothing."""

import random
from pathlib import Path

import pytest

from evals.score import score_run
from tests.eval_fakes import oracle, write_run
from tests.node_fakes import dev_ingest

pytestmark = pytest.mark.gold


def test_an_oracle_scores_full_marks(tmp_path: Path) -> None:
    records, risks = oracle(dev_ingest())
    scores = score_run(write_run(tmp_path / "oracle", dev_ingest(), records, risks))
    assert scores["missed_mandatory"] == [] and scores["missed_mandatory_strict"] == []
    assert scores["missed_hazards"] == []
    assert scores["recall"] == 1.0
    assert scores["precision_low"] == scores["precision_high"] == 1.0
    assert scores["verbatim_rate"] == 1.0
    assert scores["approach_mapping"] == 1.0
    assert scores["risk_seed_recall"] == 1.0


def test_removing_one_mandatory_record_adds_exactly_one_miss(tmp_path: Path) -> None:
    records, risks = oracle(dev_ingest())
    dropped = next(r for r in records if r.mandatory and not r.hazard)
    kept = [r for r in records if r.id != dropped.id]
    scores = score_run(write_run(tmp_path / "minus-one", dev_ingest(), kept, risks))
    assert len(scores["missed_mandatory"]) == 1


def test_shuffling_the_records_changes_nothing(tmp_path: Path) -> None:
    records, risks = oracle(dev_ingest())
    shuffled = records[:]
    random.Random(7).shuffle(shuffled)
    first = score_run(write_run(tmp_path / "a", dev_ingest(), records, risks))
    second = score_run(write_run(tmp_path / "b", dev_ingest(), shuffled, risks))
    for key in (
        "missed_mandatory",
        "recall",
        "precision_low",
        "precision_high",
        "risk_seed_recall",
    ):
        assert first[key] == second[key], key


def test_no_approach_mapping_and_no_risks_score_zero(tmp_path: Path) -> None:
    records, _ = oracle(dev_ingest())
    scores = score_run(write_run(tmp_path / "bare", dev_ingest(), records, [], mapped=False))
    assert scores["approach_mapping"] == 0.0 and scores["risk_seed_recall"] == 0.0
