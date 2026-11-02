"""FI-09 basics: the gateway denies what the agent may not do, and allows a clean call."""

from typing import Any

import pytest

from bidwright.harness.gateway import ToolGateway
from bidwright.schemas import ToolRequest
from bidwright.tools import date_tool


def _gateway(max_tool_calls: int = 6) -> ToolGateway:
    return ToolGateway.for_agent(
        "risk",
        allowed=["date_calc", "search_rfp"],
        tools=[date_tool()],
        max_tool_calls=max_tool_calls,
    )


def _request(tool: str = "date_calc", agent: str = "risk", **args: Any) -> ToolRequest:
    return ToolRequest(
        tool=tool, args=args or {"date": "2026-12-01", "op": "weekday"}, agent=agent, turn=1
    )


def test_fi09_clean_control_is_allowed() -> None:
    result = _gateway().call(_request())
    assert result.status == "OK" and result.data["result"] == "Tuesday"


@pytest.mark.parametrize(
    ("request_", "reason"),
    [
        (_request(tool="delete_notebook"), "not allowed"),
        (_request(agent="draft"), "not allowed"),
        (_request(tool="search_rfp"), "not allowed"),  # listed, but no index in this gateway
        (_request(date="2026-12-01", op="explode"), "bad arguments"),
        (_request(date="2026-12-01", op="weekday", owner="me"), "bad arguments"),
    ],
)
def test_fi09_unauthorized_or_malformed_calls_are_denied(
    request_: ToolRequest, reason: str
) -> None:
    gateway = _gateway()
    result = gateway.call(request_)
    assert result.status == "DENIED" and reason in (result.reason or "")
    assert gateway.calls == [(request_, result)]


def test_a_third_identical_call_is_denied() -> None:
    gateway = _gateway()
    statuses = [gateway.call(_request()).status for _ in range(3)]
    assert statuses == ["OK", "OK", "DENIED"]
    assert gateway.call(_request(date="2026-12-02", op="weekday")).status == "OK"


def test_the_tool_call_budget_is_enforced() -> None:
    gateway = _gateway(max_tool_calls=2)
    days = ["2026-12-01", "2026-12-02", "2026-12-03"]
    statuses = [gateway.call(_request(date=d, op="weekday")).status for d in days]
    assert statuses == ["OK", "OK", "DENIED"]
    assert "budget" in (gateway.calls[-1][1].reason or "")


def test_specs_list_only_allowed_and_registered_tools() -> None:
    assert [tool.name for tool in _gateway().specs()] == ["date_calc"]
