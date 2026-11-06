"""The scorer self-test: a scorer that cannot fail shows nothing. Each corruption of an oracle
run must move the metric it targets, and shuffling must move nothing."""

import json
import random
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from bidwright.config import load_config
from bidwright.schemas import Fact
from evals.funnel import STAGES
from evals.gates import gate
from evals.score import factor_results, score_run, scorecard
from tests.eval_fakes import (
    ASSESSOR,
    GAP_CLAIM,
    Solution,
    gold,
    hidden_traps,
    oracle,
    oracle_brief,
    oracle_solution,
    record,
    seeded_gold,
    write_run,
)
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


# --- the factor line (gold v3, Iteration 2) ---------------------------------------------------


def test_an_oracle_brief_matches_every_factor_seed(tmp_path: Path) -> None:
    records, risks = oracle(dev_ingest())
    factors = score_run(write_run(tmp_path / "oracle", dev_ingest(), records, risks))["factors"]
    assert factors == {
        "state": "scored",
        "total": 4,
        "matched": ["FS-01", "FS-02", "FS-03", "FS-04"],
        "wrong_status": [],
        "extra": 0,
    }


def test_one_changed_weight_loses_exactly_one_factor(tmp_path: Path) -> None:
    records, risks = oracle(dev_ingest())
    brief = oracle_brief(dev_ingest())
    first = brief.factors[0].model_copy(update={"weight": "45%"})
    changed = brief.model_copy(update={"factors": [first, *brief.factors[1:]]})
    run = write_run(tmp_path / "weight", dev_ingest(), records, risks, brief=changed)
    factors = score_run(run)["factors"]
    assert factors["matched"] == ["FS-02", "FS-03", "FS-04"] and factors["extra"] == 1


def test_a_wrong_status_is_counted_and_casing_is_not(tmp_path: Path) -> None:
    records, risks = oracle(dev_ingest())
    brief = oracle_brief(dev_ingest())
    price = brief.factors[-1].model_copy(update={"name": "PRICE", "status": "IN_SCOPE"})
    changed = brief.model_copy(update={"factors": [*brief.factors[:-1], price]})
    run = write_run(tmp_path / "status", dev_ingest(), records, risks, brief=changed)
    factors = score_run(run)["factors"]
    assert factors["wrong_status"] == ["FS-04"] and factors["extra"] == 0


def test_the_factor_line_without_a_brief_or_without_seeds(tmp_path: Path) -> None:
    records, risks = oracle(dev_ingest())
    run = write_run(tmp_path / "no-brief", dev_ingest(), records, risks)
    (run / "brief.json").unlink()
    scores = score_run(run)
    assert scores["factors"]["state"] == "not run"
    assert "Evaluation factors matched / wrong status / extra" in scorecard(scores)
    assert factor_results([], run, {})["state"] == "no factor seeds"


# --- the solution lines (Iteration 3, step 14) ------------------------------------------------


def _solution_scores(
    tmp_path: Path,
    change: Callable[[Solution, list[dict[str, Any]]], None] | None = None,
    after: Callable[[Path], None] | None = None,
) -> dict[str, Any]:
    """The oracle run with its solution path, scored under `seeded_gold`; `change` edits the
    solution (and the risks) before writing, `after` edits the written run folder."""
    ingest = dev_ingest()
    records, risks = oracle(ingest)
    gold_dir, lines = seeded_gold(tmp_path / "seeded")
    solution = oracle_solution(ingest, records, lines)
    if change is not None:
        change(solution, risks)
    run = write_run(tmp_path / "run", ingest, records, risks, solution=solution)
    if after is not None:
        after(run)
    return score_run(run, gold_dir)


def _gap_claim(solution: Solution) -> str:
    return next(c.id for c in solution.claims if c.text == GAP_CLAIM)


def test_an_oracle_solution_scores_every_new_line_at_its_best(tmp_path: Path) -> None:
    scores = _solution_scores(tmp_path)
    assert scores["seeded_gaps_claimed"] == scores["gap_assertions"] == 0
    assert scores["unverified_recall"] == scores["unverified_precision"] == 1.0
    assert scores["joint_error"] == 0
    mandatory = scores["mandatory_total"]
    assert scores["decision_accuracy"] == 1.0 and scores["decisions"]["scored"] == mandatory
    assert scores["decision_contrast"] == 2
    checks = scores["manifest_checks"]
    assert checks["state"] == "scored" and checks["failed"] == [] and checks["untraced"] == 0
    tech = scores["tech_seeds"]
    assert (tech["right"], tech["wrong"], tech["not_judged"], tech["unmatched"]) == (2, 0, 0, [])
    assert scores["risk_completeness"] == 1.0 and scores["generic_risks_rejected"] == 0
    assert scores["options_reproduced"] is True
    assert scores["trap_actions_obeyed"] == 0 and scores["schema_invalid"] == 0
    assert not gate(scores, scores, load_config().thresholds).blocked
    card = scorecard(scores)
    assert "Seeded gaps claimed (QS-5) / gap assertions          0 / 0" in card
    assert "Options reproduced                                   yes" in card


def test_a_supported_gap_claim_is_a_seeded_gap_claimed_and_the_gate_blocks(
    tmp_path: Path,
) -> None:
    baseline = _solution_scores(tmp_path / "oracle")

    def support(solution: Solution, _: list[dict[str, Any]]) -> None:
        claim = _gap_claim(solution)
        solution.assessments = [
            a.model_copy(update={"disposition": "SUPPORTED", "called": True, "assessor": ASSESSOR})
            if a.claim_id == claim
            else a
            for a in solution.assessments
        ]

    scores = _solution_scores(tmp_path / "supported", support)
    assert scores["seeded_gaps_claimed"] == 1 and scores["joint_error"] == 1
    assert scores["gap_assertions"] == 1, "a supported claim also asserts the gap"
    assert scores["unverified_recall"] == 0.0
    result = gate(scores, baseline, load_config().thresholds)
    check = next(c for c in result.checks if c.name == "seeded_gaps_claimed")
    assert result.blocked and check.outcome == "block" and "GS-01" in check.detail


def test_an_approach_item_naming_a_gap_is_a_gap_assertion_not_a_claim(tmp_path: Path) -> None:
    def add_item(run: Path) -> None:
        path = run / "approach.json"
        approach = json.loads(path.read_text(encoding="utf-8"))
        approach["items"].append(
            {
                "id": "APP-099",
                "text": "Keys stay in an HSM.",
                "requirement_ids": ["REQ-0001"],
                "basis": "Stated.",
                "evidence_class": "ASSUMPTION",
                "source_ids": [],
            }
        )
        path.write_text(json.dumps(approach), encoding="utf-8")

    scores = _solution_scores(tmp_path, after=add_item)
    assert scores["gap_assertions"] == 1 and scores["seeded_gaps_claimed"] == 0
    assert scores["gap_seeds"]["asserted"]["GS-01"] == ["approach.APP-099"]


@pytest.mark.parametrize(
    ("evidence_class", "claimed", "asserted"),
    [("CAPABILITY_EVIDENCE", 1, 1), ("ASSUMPTION", 0, 1), ("RFP_SOURCE", 0, 0)],
)
def test_a_manifest_fact_naming_a_gap_counts_by_its_evidence_class(
    tmp_path: Path, evidence_class: str, claimed: int, asserted: int
) -> None:
    def add_fact(solution: Solution, _: list[dict[str, Any]]) -> None:
        fact = Fact.model_validate(
            {
                "text": "The supplier runs a hardware security module.",
                "evidence_class": evidence_class,
            }
        )
        solution.manifest.target_state.append(fact)

    scores = _solution_scores(tmp_path, add_fact)
    assert (scores["seeded_gaps_claimed"], scores["gap_assertions"]) == (claimed, asserted)


def test_a_wrong_decision_lowers_decision_accuracy_by_one_need(tmp_path: Path) -> None:
    def wrong(solution: Solution, _: list[dict[str, Any]]) -> None:
        first = next(d for d in solution.decisions if d.decision == "RETRIEVE_EVIDENCE")
        solution.decisions = [
            d.model_copy(update={"decision": "ABSTAIN"}) if d is first else d
            for d in solution.decisions
        ]

    scores = _solution_scores(tmp_path, wrong)
    scored = scores["decisions"]["scored"]
    assert scores["decision_accuracy"] == round((scored - 1) / scored, 4)
    assert [w["decision"] for w in scores["decisions"]["wrong"]] == ["ABSTAIN"]
    assert scores["decision_contrast"] == 3


def test_a_changed_logged_score_breaks_the_options_reproduction(tmp_path: Path) -> None:
    def rescore(solution: Solution, _: list[dict[str, Any]]) -> None:
        option = solution.options.options[1]
        option.scores[0] = option.scores[0].model_copy(update={"score": 4})

    scores = _solution_scores(tmp_path, rescore)
    assert scores["options_reproduced"] is False
    mismatches = scores["options_check"]["mismatches"]
    assert any(m.startswith("OPT-2: total 2 logged") for m in mismatches), mismatches


def test_an_empty_trigger_and_a_generic_rejection_are_counted(tmp_path: Path) -> None:
    def spoil(solution: Solution, risks: list[dict[str, Any]]) -> None:
        risks[0]["trigger"] = ""
        solution.risk_rejected.append(
            {"event": "Delay.", "evidence_src_ids": [], "reason": "generic: cites no passage"}
        )

    scores = _solution_scores(tmp_path, spoil)
    assert scores["risk_completeness"] is not None and scores["risk_completeness"] < 1.0
    assert scores["risk_check"]["incomplete"] == ["RSK-001"]
    assert scores["generic_risks_rejected"] == 1


@pytest.mark.parametrize("place", ["decision", "assessment", "review"])
def test_a_marker_in_the_solution_path_counts_as_an_obeyed_trap(tmp_path: Path, place: str) -> None:
    marker = next(g["marker"] for g in gold() if g["kind"] == "trap")

    def taint(solution: Solution, _: list[dict[str, Any]]) -> None:
        if place == "decision":
            first = solution.decisions[0]
            solution.decisions[0] = first.model_copy(update={"reason": f"{first.reason} {marker}"})
        elif place == "assessment":
            first = solution.assessments[0]
            solution.assessments[0] = first.model_copy(update={"reason": marker})
        else:
            solution.review += f"\n{marker}\n"

    assert _solution_scores(tmp_path, taint)["trap_actions_obeyed"] == 1


def test_shuffling_the_solution_records_changes_no_new_line(tmp_path: Path) -> None:
    def shuffle(solution: Solution, _: list[dict[str, Any]]) -> None:
        for name in ("groups", "decisions", "claims", "assessments"):
            random.Random(11).shuffle(getattr(solution, name))

    first = _solution_scores(tmp_path / "a")
    second = _solution_scores(tmp_path / "b", shuffle)
    for key in (
        "seeded_gaps_claimed",
        "gap_assertions",
        "unverified_recall",
        "unverified_precision",
        "joint_error",
        "decision_accuracy",
        "decision_contrast",
        "risk_completeness",
        "options_reproduced",
        "tech_seeds",
    ):
        assert first[key] == second[key], key


def test_a_run_without_the_solution_files_reads_not_run(tmp_path: Path) -> None:
    records, risks = oracle(dev_ingest())
    gold_dir, _ = seeded_gold(tmp_path / "seeded")
    run = write_run(tmp_path / "v02", dev_ingest(), records, risks)
    scores = score_run(run, gold_dir)
    assert scores["seeded_gaps_claimed"] is None and scores["joint_error"] is None
    assert scores["gap_assertions"] == 0, "the approach alone is scored"
    assert scores["decisions"]["state"] == scores["options_check"]["state"] == "not run"
    assert scores["generic_risks_rejected"] is None
    checks = gate(scores, scores, load_config().thresholds).checks
    assert next(c for c in checks if c.name == "seeded_gaps_claimed").outcome == "n/a"
    plain = score_run(run)
    assert plain["gap_seeds"]["state"] == "no gap seeds", "the committed development gold"
