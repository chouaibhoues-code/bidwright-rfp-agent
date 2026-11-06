"""The risk agent's tool loop: caps, no-progress stop, typed tool results, generic risks;
and from Iteration 3, step 9, its one-call baselines RK0 (`oneshot`) and RK1-F (`fixed`)."""

from pathlib import Path

import pytest

from bidwright.config import AgentLimits
from bidwright.graph.nodes import MALFORMED_TWICE, risk, risk_baseline
from bidwright.retrieval import PassageIndex
from tests.node_fakes import (
    GENERIC_RISK,
    GOOD_RISK,
    RISK_LIMITS,
    ScriptBackend,
    context,
    dev_ingest,
    dev_requirements,
    gateway,
    text,
    tools,
)

REGISTER = text({"risks": [GOOD_RISK], "open_questions": []})


def _date(day: int) -> tuple[str, dict]:
    return ("date_calc", {"date": f"2027-01-{day:02d}", "op": "weekday"})


def test_loop_caps_stop_at_four_turns(tmp_path: Path) -> None:
    backend = ScriptBackend([*[tools(_date(d)) for d in (4, 5, 6, 7)], REGISTER])
    outcome = risk(context(backend), dev_requirements(), [], gateway(tmp_path), RISK_LIMITS)
    assert outcome.turns == 4 and outcome.stop_reason == "turn_cap"
    assert len(backend.requests) == 5
    assert backend.requests[-1].tools == () and backend.requests[-1].schema is not None


def test_loop_caps_stop_at_six_tool_calls(tmp_path: Path) -> None:
    calls = [_date(d) for d in range(4, 11)]  # seven calls in one turn
    backend = ScriptBackend([tools(*calls), REGISTER])
    guard = gateway(tmp_path)
    outcome = risk(context(backend), dev_requirements(), [], guard, RISK_LIMITS)
    assert outcome.stop_reason == "tool_cap" and guard.executed == 6
    assert guard.calls[-1][1].status == "DENIED"


def test_a_turn_with_nothing_new_ends_the_research(tmp_path: Path) -> None:
    search = ("search_rfp", {"query": "go-live migration"})
    backend = ScriptBackend([tools(search), tools(search), REGISTER])
    outcome = risk(context(backend), dev_requirements(), [], gateway(tmp_path), RISK_LIMITS)
    assert outcome.stop_reason == "no_progress" and outcome.turns == 2


def test_tool_results_go_back_to_the_model_typed(tmp_path: Path) -> None:
    backend = ScriptBackend(
        [
            tools(("delete_rfp", {}), ("search_rfp", {"query": "kangaroo"})),
            "I have what I need.",
            REGISTER,
        ]
    )
    risk(context(backend), dev_requirements(), [], gateway(tmp_path), RISK_LIMITS)
    sent = [m for m in backend.requests[1].messages if m.role == "tool"]
    assert [m.name for m in sent] == ["delete_rfp", "search_rfp"]
    assert '"status":"DENIED"' in sent[0].content and '"status":"EMPTY"' in sent[1].content


def test_risk_generic_is_rejected_then_replaced_on_retry(tmp_path: Path) -> None:
    backend = ScriptBackend(
        [
            "Done.",
            text({"risks": [GOOD_RISK, GENERIC_RISK], "open_questions": []}),
            text(
                {
                    "risks": [GOOD_RISK],
                    "open_questions": [
                        {"text": "Paper forms too?", "src_ids": ["SRC-0026", "SRC-9999"]}
                    ],
                }
            ),
        ]
    )
    outcome = risk(context(backend), dev_requirements(), [], gateway(tmp_path), RISK_LIMITS)
    assert "were rejected" in backend.requests[2].messages[-1].content
    assert [r.id for r in outcome.risks] == ["RSK-001"] and outcome.rejected == []
    assert outcome.risks[0].evidence_src_ids == ["SRC-0032", "SRC-0026"]
    assert outcome.questions[0].src_ids == ["SRC-0026"]


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"evidence_src_ids": []}, "cites no passage"),
        ({"evidence_src_ids": ["SRC-0039"]}, "shares no content word"),
        ({"residual_exposure": "High"}, "rating"),
        ({"residual_exposure": "Low if tested early; an outage could still hit."}, "rating"),
        ({"residual_exposure": "It remains a medium-to-high risk until testing."}, "rating"),
        ({"effect": "There is a 40% chance of delay."}, "probability"),
    ],
)
def test_risk_generic_stays_rejected_when_the_retry_repeats_it(
    tmp_path: Path, change: dict, reason: str
) -> None:
    bad = GOOD_RISK | change
    register = text({"risks": [bad], "open_questions": []})
    backend = ScriptBackend(["Done.", register, register])
    outcome = risk(context(backend), dev_requirements(), [], gateway(tmp_path), RISK_LIMITS)
    assert outcome.risks == []
    assert (
        reason.split()[0] in outcome.rejected[0]["reason"]
        or reason in outcome.rejected[0]["reason"]
    )


@pytest.mark.parametrize(
    "exposure",
    [
        "Lower once a dry-run upload passes, though a portal outage could still delay it.",
        "Highly dependent on the College's test accounts arriving on time.",
        "Staff work in two systems until late February 2027.",
    ],
)
def test_an_exposure_in_plain_words_is_not_a_rating(tmp_path: Path, exposure: str) -> None:
    plain = GOOD_RISK | {"residual_exposure": exposure}
    backend = ScriptBackend(["Done.", text({"risks": [plain], "open_questions": []})])
    outcome = risk(context(backend), dev_requirements(), [], gateway(tmp_path), RISK_LIMITS)
    assert len(outcome.risks) == 1, outcome.rejected


def test_an_availability_percentage_is_not_a_probability(tmp_path: Path) -> None:
    sla = GOOD_RISK | {
        "condition": "The service must be available 99.5% of the time from 2027-01-11,"
        " while records still migrate."
    }
    backend = ScriptBackend(["Done.", text({"risks": [sla], "open_questions": []})])
    outcome = risk(context(backend), dev_requirements(), [], gateway(tmp_path), RISK_LIMITS)
    assert len(outcome.risks) == 1


def test_risk_degrades_after_two_schema_failures(tmp_path: Path) -> None:
    backend = ScriptBackend(["Done.", "{}", "[]"])
    outcome = risk(context(backend), dev_requirements(), [], gateway(tmp_path), RISK_LIMITS)
    assert outcome.risks == [] and outcome.questions == [] and outcome.rejected == []
    assert outcome.failure == MALFORMED_TWICE and outcome.stop_reason == "answered"


def test_without_a_no_progress_stop_the_loop_runs_to_its_cap(tmp_path: Path) -> None:
    search = ("search_rfp", {"query": "go-live"})
    limits = AgentLimits(max_turns=3, max_tool_calls=6, stop_on_no_progress=False)
    backend = ScriptBackend([tools(search), tools(search), tools(search), REGISTER])
    outcome = risk(context(backend), dev_requirements(), [], gateway(tmp_path, limits), limits)
    assert outcome.turns == 3 and outcome.stop_reason == "turn_cap"


# --- Iteration 3, step 9: the risk baselines -------------------------------------------------

STARTED = "2026-11-05"
BY_REQUIREMENT = GOOD_RISK | {"evidence_src_ids": ["REQ-0003", "REQ-0004"]}


def _index(tmp_path: Path) -> PassageIndex:
    return PassageIndex.build(dev_ingest().passages, tmp_path / "search.sqlite")


def _dated_hazard() -> list:
    """The development requirements with the go-live date as a hazard."""
    requirements = dev_requirements()
    requirements[2] = requirements[2].model_copy(update={"hazard": True})
    return requirements


def test_the_oneshot_mode_makes_one_call_with_no_tools_and_no_dates_or_passages() -> None:
    backend = ScriptBackend([text({"risks": [BY_REQUIREMENT], "open_questions": []})])
    ctx = context(backend)
    outcome = risk_baseline(ctx, dev_requirements(), [], "oneshot")
    [request] = backend.requests
    assert request.tools == () and request.schema_name == "RiskRegister"
    sent = request.messages[-1].content
    assert '"dates":[]' in sent and '"passages":[]' in sent
    assert [r.id for r in outcome.risks] == ["RSK-001"] and outcome.rejected == []
    assert outcome.risks[0].evidence_src_ids == ["SRC-0032", "SRC-0026"], "requirement ids resolve"
    assert (outcome.stop_reason, outcome.turns) == ("oneshot", 1)


def test_the_fixed_mode_computes_its_dates_in_code_before_its_one_call(tmp_path: Path) -> None:
    from datetime import date

    backend = ScriptBackend([text({"risks": [GOOD_RISK], "open_questions": []})])
    ctx = context(backend)
    ctx.started = date.fromisoformat(STARTED)
    outcome = risk_baseline(ctx, _dated_hazard(), [], "fixed", index=_index(tmp_path))
    [request] = backend.requests
    sent = request.messages[-1].content
    days = (date(2027, 1, 11) - date.fromisoformat(STARTED)).days
    assert f'"date":"2027-01-11","days_from_start":{days},"weekday":"Monday"' in sent
    assert '"src_id":"SRC-0032"' in sent, "search_rfp's top passages for the hazard"
    assert request.tools == () and len(outcome.risks) == 1


def test_the_fixed_mode_needs_the_runs_start_date(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="start date"):
        risk_baseline(
            context(ScriptBackend([])), _dated_hazard(), [], "fixed", index=_index(tmp_path)
        )


@pytest.mark.parametrize("mode", ["oneshot", "fixed"])
def test_the_generic_risk_check_applies_to_both_baselines(tmp_path: Path, mode: str) -> None:
    from datetime import date

    first = text({"risks": [GOOD_RISK, GENERIC_RISK], "open_questions": []})
    backend = ScriptBackend([first, text({"risks": [GOOD_RISK], "open_questions": []})])
    ctx = context(backend)
    ctx.started = date.fromisoformat(STARTED)
    outcome = risk_baseline(ctx, _dated_hazard(), [], mode, index=_index(tmp_path))  # type: ignore[arg-type]
    assert "were rejected" in backend.requests[1].messages[-1].content
    assert [r.id for r in outcome.risks] == ["RSK-001"] and outcome.rejected == []


@pytest.mark.parametrize("mode", ["loop", "oneshot", "fixed"])
def test_risk_no_invented_rating(tmp_path: Path, mode: str) -> None:
    """A register with a probability is rejected in all three modes (RISK-002)."""
    from datetime import date

    rated = GOOD_RISK | {"effect": "There is a 40% chance that lookups miss documents."}
    register = text({"risks": [rated], "open_questions": []})
    if mode == "loop":
        backend = ScriptBackend(["Done.", register, register])
        outcome = risk(context(backend), dev_requirements(), [], gateway(tmp_path), RISK_LIMITS)
    else:
        backend = ScriptBackend([register, register])
        ctx = context(backend)
        ctx.started = date.fromisoformat(STARTED)
        outcome = risk_baseline(ctx, _dated_hazard(), [], mode, index=_index(tmp_path))  # type: ignore[arg-type]
    assert outcome.risks == []
    assert outcome.rejected[0]["reason"] == "carries a rating or a probability"


def test_a_baseline_degrades_after_two_schema_failures() -> None:
    outcome = risk_baseline(context(ScriptBackend(["{}", "[]"])), dev_requirements(), [], "oneshot")
    assert outcome.risks == [] and outcome.failure == MALFORMED_TWICE


# --- Iteration 3, step 12: the full risk (section 4.7) ----------------------------------------


@pytest.mark.parametrize(
    ("change", "missing"),
    [
        ({"trigger": " "}, "trigger"),
        ({"owner_role": ""}, "owner role"),
        ({"responses": []}, "response"),
        ({"effect": "", "responses": ["  "]}, "effect, response"),
    ],
)
def test_a_risk_with_an_empty_field_is_rejected_once_then_dropped_with_its_reason(
    tmp_path: Path, change: dict, missing: str
) -> None:
    """The six-field check: the register still parses with no response, and the risk fails its
    own check, with the generic risks' one retry."""
    bad = GOOD_RISK | change
    register = text({"risks": [bad], "open_questions": []})
    backend = ScriptBackend(["Done.", register, register])
    outcome = risk(context(backend), dev_requirements(), [], gateway(tmp_path), RISK_LIMITS)
    assert outcome.risks == []
    assert "were rejected" in backend.requests[2].messages[-1].content
    assert outcome.rejected[0]["reason"] == f"incomplete: no {missing}"
    assert outcome.rejected[0]["risk"]["condition"] == bad["condition"], "the whole proposal"


def test_a_new_sla_calc_result_counts_as_progress(tmp_path: Path) -> None:
    sla = ("sla_calc", {"target_percent": 99.5, "period": "month"})
    other = ("sla_calc", {"target_percent": 99.9, "period": "month"})
    backend = ScriptBackend([tools(sla), tools(other), tools(other), REGISTER])
    outcome = risk(context(backend), dev_requirements(), [], gateway(tmp_path), RISK_LIMITS)
    assert outcome.stop_reason == "no_progress" and outcome.turns == 3


def test_affects_keeps_only_the_codes_and_ids_that_exist(tmp_path: Path) -> None:
    from bidwright.graph.nodes import RiskView

    named = GOOD_RISK | {"affects": ["1.2", "NEED-001", "9.9", "1.2"]}
    backend = ScriptBackend(["Done.", text({"risks": [named], "open_questions": []})])
    view = RiskView(affectable=frozenset({"1.2", "NEED-001"}))
    outcome = risk(
        context(backend), dev_requirements(), [], gateway(tmp_path), RISK_LIMITS, None, view
    )
    assert outcome.risks[0].affects == ["1.2", "NEED-001"]


def test_the_risk_input_carries_the_manifests_view(tmp_path: Path) -> None:
    from bidwright.graph.nodes import RiskView
    from bidwright.schemas import RiskClaimView, RiskGapView, RiskPackageView

    view = RiskView(
        work_packages=[RiskPackageView(code="1.1", name="Migration", predecessors=[])],
        assumptions=["The buyer provides test accounts."],
        tech_claims=[RiskClaimView(text="PDF/A export through pdfplumber", verdict="INVALIDATED")],
        gaps=[RiskGapView(need_id="NEED-002", text="Offline signing", status="GAP")],
    )
    backend = ScriptBackend(["Done.", REGISTER])
    risk(context(backend), dev_requirements(), [], gateway(tmp_path), RISK_LIMITS, None, view)
    sent = backend.requests[0].messages[-1].content
    for value in ("Migration", "test accounts", "INVALIDATED", "Offline signing"):
        assert value in sent, value
