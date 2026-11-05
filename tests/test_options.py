"""`options` (Iteration 3, step 6; ADR-041): the call, and code's weights, gates, counts and
tie-breaks, each reproducible from `options.json`."""

import json
from pathlib import Path
from typing import Any

import pytest

from bidwright.config import load_config
from bidwright.graph.nodes import CallManifests
from bidwright.graph.options import (
    options_task,
    pass_or_fail,
    propose,
    settle,
    stated_weight,
    write_options,
)
from bidwright.harness.context import ContextManager
from bidwright.schemas import (
    CapabilityClaim,
    CapabilityMap,
    CapabilityRow,
    ClaimView,
    EvaluationFactor,
    EvidenceAssessment,
    FactorView,
    MapRowView,
    NeedDecision,
    OptionsResult,
    OptionsTask,
    SolutionOptions,
)
from tests.node_fakes import RuleBackend, context, dev_ingest

CONFIG = load_config()


def factor(
    n: int, weight: str, status: str = "IN_SCOPE", scoring: str = "Scored 0 to 4"
) -> FactorView:
    return FactorView(
        factor_id=f"EF-0{n}",
        name=f"Factor {n}",
        weight=weight,
        scoring=scoring,
        status=status,  # type: ignore[arg-type]
    )


NEEDS = [
    MapRowView(
        need_id="RG-001",
        origin="RFP",
        text="Electronic signature of forms",
        status="COVERED",
        claims=[ClaimView(claim_id="CL-001", text="Forms are signed.", disposition="SUPPORTED")],
    ),
    MapRowView(
        need_id="RG-002",
        origin="RFP",
        text="Integration with the Halden system",
        status="GAP",
        claims=[ClaimView(claim_id="CL-002", text="Halden is read.", disposition="UNVERIFIED")],
    ),
]
ASSESSMENTS = [
    EvidenceAssessment(claim_id="CL-001", disposition="SUPPORTED", called=False),
    EvidenceAssessment(claim_id="CL-002", disposition="UNVERIFIED", called=False),
]
STATED = [factor(1, "60%"), factor(2, "40 points"), factor(3, "30", status="OUT_OF_SCOPE")]


def task(factors: list[FactorView]) -> OptionsTask:
    return OptionsTask(factors=factors, needs=NEEDS)


def option(
    name: str,
    scores: dict[str, int],
    *,
    gap: str = "EXCLUDED",
    covered: str = "CONFIG",
    baseline: bool = False,
    gap_claims: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "name": name,
        "summary": f"{name}.",
        "baseline": baseline,
        "approach": [
            {"need_id": "RG-001", "delivery_mode": covered, "claim_ids": ["CL-001"]},
            {"need_id": "RG-002", "delivery_mode": gap, "claim_ids": list(gap_claims)},
        ],
        "assumptions": ["The buyer tests with its own staff.", " "],
        "scores": [{"factor_id": f, "score": s, "reason": "Stated."} for f, s in scores.items()],
    }


def result(*options: dict[str, Any]) -> OptionsResult:
    return OptionsResult.model_validate({"options": list(options)})


def by_id(settled: SolutionOptions) -> dict[str, Any]:
    return {o.id: o for o in settled.options}


def reproduce(settled: SolutionOptions, factors: list[FactorView]) -> dict[str, float]:
    """Each option's total from its stored scores and the factors' published weights."""
    weights = {f.factor_id: stated_weight(f) for f in factors if f.status == "IN_SCOPE"}
    totals = {}
    for o in settled.options:
        mass = sum(w for w in weights.values() if w is not None)
        totals[o.id] = round(sum(s.score * (weights[s.factor_id] or 0) for s in o.scores) / mass, 4)
    return totals


def test_options_scores_reproduce_from_the_logged_scores(tmp_path: Path) -> None:
    settled = settle(
        result(
            option("Configured, Halden left out", {"EF-01": 3, "EF-02": 2}, baseline=True),
            option("Configured, Halden through a partner", {"EF-01": 3, "EF-02": 2}, gap="PARTNER"),
            option("Built", {"EF-01": 4, "EF-02": 4}, covered="CUSTOM", gap="ALTERNATIVE"),
        ),
        task(STATED),
        ASSESSMENTS,
    )
    write_options(tmp_path, settled)
    stored = SolutionOptions.model_validate(
        json.loads((tmp_path / "options.json").read_text(encoding="utf-8"))
    )
    assert stored == settled
    assert stored.weighting == "stated" and stored.hypothetical
    assert {o.id: o.total for o in stored.options} == reproduce(stored, STATED)
    assert {o.id: o.total for o in stored.options} == {"OPT-1": 2.6, "OPT-2": 2.6, "OPT-3": 4.0}
    # OPT-1 and OPT-2 tie on 2.6; OPT-2 meets the gap through a partner, so it leaves none open.
    assert {o.id: o.rank for o in stored.options} == {"OPT-3": 1, "OPT-2": 2, "OPT-1": 3}
    assert [s.factor_id for s in stored.options[0].scores] == ["EF-01", "EF-02"]
    assert stored.options[0].assumptions == ["The buyer tests with its own staff."]


@pytest.mark.parametrize(
    ("weight", "expected"),
    [
        ("40", 40.0),
        ("40%", 40.0),
        ("40 points", 40.0),
        ("12.5%", 12.5),
        ("high", None),
        ("not_stated", None),
    ],
)
def test_a_stated_weight_is_the_number_at_its_start(weight: str, expected: float | None) -> None:
    assert stated_weight(factor(1, weight)) == expected


@pytest.mark.parametrize(
    ("weight", "scoring", "gate"),
    [
        ("Pass/Fail", "Scored 0 to 4", True),
        ("pass or fail", "Scored 0 to 4", True),
        ("PASS-FAIL", "Scored 0 to 4", True),
        ("not_stated", "Bids that fail the form check do not pass", True),
        ("40%", "Scored 0 to 4", False),
    ],
)
def test_a_pass_or_fail_factor_is_read_from_its_weight_or_its_scoring(
    weight: str, scoring: str, gate: bool
) -> None:
    assert pass_or_fail(factor(1, weight, scoring=scoring)) is gate


def test_one_unstated_weight_makes_every_factor_count_equally_and_the_ranking_provisional() -> None:
    factors = [factor(1, "60%"), factor(2, "high")]
    settled = settle(result(option("A", {"EF-01": 3, "EF-02": 2})), task(factors), ASSESSMENTS)
    assert settled.weighting == "equal"
    assert settled.options[0].total == 2.5
    assert any("provisional" in note for note in settled.notes)


def test_a_failed_gate_ranks_its_option_below_every_passing_one() -> None:
    factors = [factor(1, "60%"), factor(2, "Pass/Fail")]
    settled = settle(
        result(
            option("Strong but fails the form", {"EF-01": 4, "EF-02": 1}, baseline=True),
            option("Weak but passes", {"EF-01": 0, "EF-02": 2}),
        ),
        task(factors),
        ASSESSMENTS,
    )
    options = by_id(settled)
    assert options["OPT-1"].failed_gates == ["EF-02"] and options["OPT-2"].failed_gates == []
    assert (options["OPT-1"].total, options["OPT-2"].total) == (4.0, 0.0), "a gate has no weight"
    assert (options["OPT-2"].rank, options["OPT-1"].rank) == (1, 2)
    assert settled.weighting == "stated"


@pytest.mark.parametrize(
    "factors", [[factor(1, "Pass/Fail")], [factor(1, "60%", status="OUT_OF_SCOPE")], []]
)
def test_with_no_weighted_factor_every_total_is_zero(factors: list[FactorView]) -> None:
    settled = settle(
        result(option("A", {"EF-01": 4}), option("B", {"EF-01": 3})), task(factors), ASSESSMENTS
    )
    assert [o.total for o in settled.options] == [0.0, 0.0]


def test_an_out_of_scope_score_is_dropped_a_missing_one_counts_zero_and_a_wild_one_is_clamped() -> (
    None
):
    settled = settle(
        result(option("A", {"EF-01": 7, "EF-03": 4, "EF-09": 2})), task(STATED), ASSESSMENTS
    )
    scores = {s.factor_id: s.score for s in settled.options[0].scores}
    assert scores == {"EF-01": 4, "EF-02": 0}
    notes = " ".join(settled.notes)
    assert "EF-03, not in scope, dropped" in notes and "EF-09, not in scope, dropped" in notes
    assert "no score for EF-02, counted 0" in notes and "clamped to 4" in notes


def test_the_counts_one_kept_a_fourth_dropped_and_one_baseline() -> None:
    one = settle(result(option("Only", {"EF-01": 2})), task(STATED), ASSESSMENTS)
    assert len(one.options) == 1 and "one option only, kept" in one.notes
    assert one.options[0].baseline, "with none marked, code marks the only one"

    four = settle(
        result(*(option(f"O{n}", {"EF-01": 2}, baseline=n == 1) for n in range(4))),
        task(STATED),
        ASSESSMENTS,
    )
    assert [o.id for o in four.options] == ["OPT-1", "OPT-2", "OPT-3"]
    assert "options past the first 3 dropped: 1" in four.notes

    none = settle(
        result(
            option("Built", {"EF-01": 2}, covered="CUSTOM", gap="CUSTOM"),
            option("Configured", {"EF-01": 2}),
        ),
        task(STATED),
        ASSESSMENTS,
    )
    assert [o.baseline for o in none.options] == [False, True], "the fewest CUSTOM needs"

    two = settle(
        result(option("A", {"EF-01": 2}, baseline=True), option("B", {"EF-01": 2}, baseline=True)),
        task(STATED),
        ASSESSMENTS,
    )
    assert [o.baseline for o in two.options] == [True, False]
    assert "OPT-2 lost its baseline mark: OPT-1 keeps it" in two.notes


def test_options_needs_proof() -> None:
    settled = settle(
        result(
            option("Halden built anyway", {"EF-01": 3}, gap="CUSTOM", gap_claims=("CL-002",)),
            option("Halden left out", {"EF-01": 3}, baseline=True),
        ),
        task(STATED),
        ASSESSMENTS,
    )
    options = by_id(settled)
    assert options["OPT-1"].needs_proof == ["CL-002"] and options["OPT-2"].needs_proof == []
    # Equal totals and one open gap each: the option needing no proof ranks first.
    assert (options["OPT-2"].rank, options["OPT-1"].rank) == (1, 2)


def test_ties_break_on_custom_needs_then_option_order() -> None:
    settled = settle(
        result(
            option("Built", {"EF-01": 3}, covered="CUSTOM"),
            option("Configured", {"EF-01": 3}, baseline=True),
            option("Configured again", {"EF-01": 3}),
        ),
        task(STATED),
        ASSESSMENTS,
    )
    assert {o.id: o.rank for o in settled.options} == {"OPT-2": 1, "OPT-3": 2, "OPT-1": 3}


def test_an_unknown_need_a_second_approach_and_another_needs_claim_are_dropped() -> None:
    proposal = option("A", {"EF-01": 3}, gap_claims=("CL-001", "CL-404"))
    proposal["approach"] += [
        {"need_id": "RG-404", "delivery_mode": "OOTB", "claim_ids": []},
        {"need_id": "RG-001", "delivery_mode": "CUSTOM", "claim_ids": []},
    ]
    settled = settle(result(proposal), task(STATED), ASSESSMENTS)
    approach = settled.options[0].approach
    assert [(a.need_id, a.delivery_mode, a.claim_ids) for a in approach] == [
        ("RG-001", "CONFIG", ["CL-001"]),
        ("RG-002", "EXCLUDED", []),
    ]
    notes = " ".join(settled.notes)
    assert "CL-001 is not a claim of RG-002" in notes and "CL-404 is not a claim of RG-002" in notes
    assert "RG-404 is not on the map" in notes and "a second approach for RG-001" in notes


def test_a_policy_makes_the_ranking_not_hypothetical_and_no_option_is_noted() -> None:
    settled = settle(
        result(option("A", {"EF-01": 3})), task(STATED), ASSESSMENTS, policy_loaded=True
    )
    assert not settled.hypothetical
    empty = settle(OptionsResult(), task(STATED), ASSESSMENTS)
    assert empty.options == [] and empty.notes == ["options: no option"]


def test_the_task_carries_the_map_the_dispositions_and_the_gap_text() -> None:
    factors = [
        EvaluationFactor(
            id="EF-01",
            name="Quality",
            weight="60%",
            scoring="0 to 4",
            src_ids=["SRC-0001"],
            status="IN_SCOPE",
        )
    ]
    cmap = CapabilityMap(
        rows=[
            CapabilityRow(
                need_id="RG-001",
                origin="RFP",
                text="Signature",
                decision="RETRIEVE_EVIDENCE",
                status="COVERED",
                claim_ids=["CL-001"],
            ),
            CapabilityRow(
                need_id="RG-002",
                origin="RFP",
                text="Halden",
                decision="PROCEED_WITH_GAP",
                status="GAP",
                reason="no claim is supported",
            ),
        ]
    )
    claims = [
        CapabilityClaim(
            id="CL-001",
            need_id="RG-001",
            kind="capability",
            text="Forms are signed.",
            evidence_ids=["CAP-012"],
            src_ids=["SRC-0015"],
        )
    ]
    decisions = [
        NeedDecision(need_id="RG-002", origin="RFP", decision="PROCEED_WITH_GAP", gap="No Halden.")
    ]
    built = options_task(factors, cmap, claims, ASSESSMENTS, decisions, None)
    assert [f.factor_id for f in built.factors] == ["EF-01"]
    assert built.needs[0].claims == [
        ClaimView(claim_id="CL-001", text="Forms are signed.", disposition="SUPPORTED")
    ]
    assert [(g.need_id, g.gap) for g in built.gaps] == [("RG-002", "No Halden.")]
    assert built.domain_items == []


def test_the_call_proposes_two_options_and_names_its_manifest(tmp_path: Path) -> None:
    manifests = CallManifests(
        ContextManager(tmp_path, CONFIG.limits.context, dev_ingest().passages),
        CONFIG.limits.context.budgets["options"],
    )
    backend = RuleBackend()
    proposed = propose(context(backend), task(STATED), manifests)
    assert proposed is not None and len(proposed.options) == 2
    settled = settle(proposed, task(STATED), ASSESSMENTS)
    first = by_id(settled)["OPT-1"]
    assert first.baseline and first.rank == 1 and first.needs_proof == []
    assert [p.name for p in (tmp_path / "context").glob("options-*.json")] == ["options-O01.json"]
    assert len(backend.requests) == 1 and backend.requests[0].schema_name == "OptionsResult"
