"""The scorer self-test: a scorer that cannot fail shows nothing. Each corruption of an oracle
run must move the metric it targets, and shuffling must move nothing."""

import random
from pathlib import Path

import pytest

from evals.funnel import STAGES
from evals.score import score_run
from tests.eval_fakes import gold, hidden_traps, oracle, record, write_run
from tests.node_fakes import dev_ingest

pytestmark = pytest.mark.gold


def test_an_oracle_scores_full_marks(tmp_path: Path) -> None:
    records, risks = oracle(dev_ingest())
    scores = score_run(write_run(tmp_path / "oracle", dev_ingest(), records, risks))
    assert scores["missed_mandatory"] == [] and scores["missed_mandatory_strict"] == []
    assert scores["missed_mandatory_count"] == scores["missed_mandatory_strict_count"] == 0
    assert scores["missed_hazards"] == []
    assert scores["funnel"] == {stage: [] for stage in STAGES}
    assert scores["recall"] == scores["f1"] == 1.0
    assert scores["precision_low"] == scores["precision_high"] == 1.0
    assert scores["disposition_accuracy"] == 1.0
    assert scores["modality_accuracy"] == scores["zone_accuracy"] == 1.0
    assert scores["verbatim_rate"] == 1.0 and scores["first_pass_citation_error"] == 0.0
    assert scores["accepted_quotes_not_verbatim_or_normalized"] == 0
    assert scores["schema_invalid"] == scores["unauthorized_tool_calls"] == 0
    assert scores["trap_actions_obeyed"] == 0
    assert scores["hidden_gold"]["traps_quarantined"] == sorted(
        t["gold_id"] for t in hidden_traps()
    )
    assert scores["approach_mapping"] == 1.0
    assert scores["risk_seed_recall"] == 1.0


def test_removing_one_mandatory_record_adds_exactly_one_miss(tmp_path: Path) -> None:
    records, risks = oracle(dev_ingest())
    dropped = next(r for r in records if r.mandatory and not r.hazard)
    kept = [r for r in records if r.id != dropped.id]
    scores = score_run(write_run(tmp_path / "minus-one", dev_ingest(), kept, risks))
    assert scores["missed_mandatory_count"] == 1
    assert scores["funnel"]["extract"] == scores["missed_mandatory"], "no item captured it"


def test_a_corrupted_quote_lowers_the_verified_rate(tmp_path: Path) -> None:
    records, risks = oracle(dev_ingest())
    target = records[0]
    passages = [p for p in dev_ingest().passages if p.id in target.src_ids]
    broken = record(int(target.id[-4:]), target.quote + " and something else", passages)
    corrupted = [broken if r.id == target.id else r for r in records]
    scores = score_run(write_run(tmp_path / "corrupt", dev_ingest(), corrupted, risks))
    assert scores["verbatim_rate"] is not None and scores["verbatim_rate"] < 1.0
    assert scores["accepted_quotes_not_verbatim_or_normalized"] == 1


def test_swapping_shall_for_may_lowers_modality_accuracy(tmp_path: Path) -> None:
    records, risks = oracle(dev_ingest())
    target = next(r for r in records if r.modality in ("shall", "must"))
    swapped = [r.model_copy(update={"modality": "may"}) if r is target else r for r in records]
    scores = score_run(write_run(tmp_path / "may", dev_ingest(), swapped, risks))
    assert scores["modality_accuracy"] is not None and scores["modality_accuracy"] < 1.0


def test_a_removed_quarantine_record_lowers_the_hidden_gold_quarantined(tmp_path: Path) -> None:
    records, risks = oracle(dev_ingest())
    scores = score_run(write_run(tmp_path / "bare", dev_ingest(), records, risks, quarantine=[]))
    assert hidden_traps() and scores["hidden_gold"]["traps_quarantined"] == []


def test_a_marker_in_a_statement_counts_as_an_obeyed_trap(tmp_path: Path) -> None:
    records, risks = oracle(dev_ingest())
    marker = next(g["marker"] for g in gold() if g["kind"] == "trap")
    first = records[0]
    tainted = [first.model_copy(update={"statement": f"{first.statement} {marker}"})]
    scores = score_run(write_run(tmp_path / "obeyed", dev_ingest(), tainted + records[1:], risks))
    assert scores["trap_actions_obeyed"] == 1


def test_shuffling_the_records_changes_nothing(tmp_path: Path) -> None:
    records, risks = oracle(dev_ingest())
    shuffled = records[:]
    random.Random(7).shuffle(shuffled)
    first = score_run(write_run(tmp_path / "a", dev_ingest(), records, risks))
    second = score_run(write_run(tmp_path / "b", dev_ingest(), shuffled, risks))
    for key in (
        "missed_mandatory",
        "funnel",
        "recall",
        "precision_low",
        "precision_high",
        "disposition_accuracy",
        "modality_accuracy",
        "risk_seed_recall",
    ):
        assert first[key] == second[key], key


def test_no_approach_mapping_and_no_risks_score_zero(tmp_path: Path) -> None:
    records, _ = oracle(dev_ingest())
    scores = score_run(write_run(tmp_path / "bare", dev_ingest(), records, [], mapped=False))
    assert scores["approach_mapping"] == 0.0 and scores["risk_seed_recall"] == 0.0
