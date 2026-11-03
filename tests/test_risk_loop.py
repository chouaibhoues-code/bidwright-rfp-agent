"""The risk agent's tool loop: caps, no-progress stop, typed tool results, generic risks."""

from pathlib import Path

import pytest

from bidwright.config import AgentLimits
from bidwright.graph.nodes import risk
from tests.node_fakes import (
    GENERIC_RISK,
    GOOD_RISK,
    RISK_LIMITS,
    ScriptBackend,
    context,
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
                        {"text": "Paper forms too?", "src_ids": ["SRC-0024", "SRC-9999"]}
                    ],
                }
            ),
        ]
    )
    outcome = risk(context(backend), dev_requirements(), [], gateway(tmp_path), RISK_LIMITS)
    assert "were rejected" in backend.requests[2].messages[-1].content
    assert [r.id for r in outcome.risks] == ["RSK-001"] and outcome.rejected == []
    assert outcome.risks[0].evidence_src_ids == ["SRC-0030", "SRC-0024"]
    assert outcome.questions[0].src_ids == ["SRC-0024"]


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"evidence_src_ids": []}, "cites no passage"),
        ({"evidence_src_ids": ["SRC-0037"]}, "shares no content word"),
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


def test_without_a_no_progress_stop_the_loop_runs_to_its_cap(tmp_path: Path) -> None:
    search = ("search_rfp", {"query": "go-live"})
    limits = AgentLimits(max_turns=3, max_tool_calls=6, stop_on_no_progress=False)
    backend = ScriptBackend([tools(search), tools(search), tools(search), REGISTER])
    outcome = risk(context(backend), dev_requirements(), [], gateway(tmp_path, limits), limits)
    assert outcome.turns == 3 and outcome.stop_reason == "turn_cap"
