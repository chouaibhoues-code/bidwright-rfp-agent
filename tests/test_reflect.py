"""The gated `reflect` tool (Iteration 3, step 11; ADR-047): G6, the counters, the loops'
rules, and the pinned server. The fake sequential-thinking server of `tests/mcp_fakes.py`
stands in for the gating tests, so they need no Node; the pinned server's own test skips when
Node or its installed package is absent."""

import shutil
import sys
from pathlib import Path

import pytest

from bidwright.config import AgentLimits, StdioServer, load_config
from bidwright.graph.nodes import risk
from bidwright.harness.egress import EgressRefused, check_run
from bidwright.harness.gateway import ToolGateway
from bidwright.harness.reflect import SENT, reflect_for, reflect_tool, thought_attributes
from bidwright.harness.rules import REFLECT_DENIED
from bidwright.preflight import HOME
from bidwright.research.mcp_client import McpClient
from bidwright.research.pins import pinned
from bidwright.retrieval import PassageIndex
from bidwright.schemas import ToolRequest
from bidwright.tools import Tool, date_tool, search_tool
from tests.node_fakes import ScriptBackend, context, dev_ingest, dev_requirements, text, tools

CONFIG = load_config()
FAKE = StdioServer(
    transport="stdio",
    command=sys.executable,
    args=["-m", "tests.mcp_fakes", "stdio", "--reflect"],
    timeout_s=30,
    tool_timeout_s=30,
)
ON = AgentLimits(max_turns=4, max_tool_calls=6, stop_on_no_progress=True, reflect=True)
OFF = AgentLimits(max_turns=4, max_tool_calls=6, stop_on_no_progress=True)
REGISTER = text({"risks": [], "open_questions": []})


@pytest.fixture(scope="module")
def fake_pins() -> object:
    reported, listed = McpClient("reflect", FAKE).list_tools()
    return pinned("reflect", reported, listed, SENT, None)


def fake_reflect(pins: object) -> Tool:
    return reflect_tool(McpClient("reflect", FAKE), pins)  # type: ignore[arg-type]


def gateway(
    pins: object, *, reflect: bool, cap: int = 6, index: PassageIndex | None = None
) -> ToolGateway:
    listed = [date_tool(), fake_reflect(pins)]
    if index is not None:
        listed.append(search_tool(index))
    return ToolGateway.for_agent(
        "risk",
        ["search_rfp", "date_calc", "reflect"],
        listed,
        cap,
        reflect=reflect,
    )


def request(tool: str, turn: int = 1, **args: object) -> ToolRequest:
    return ToolRequest(tool=tool, args=dict(args), agent="risk", turn=turn)


def thought(text_: str = "The date call failed; give it the second date.") -> ToolRequest:
    return request("reflect", thought=text_)


def test_reflect_gating(fake_pins: object) -> None:
    gw = gateway(fake_pins, reflect=True)
    first = gw.call(thought())
    assert (first.status, first.reason) == ("DENIED", REFLECT_DENIED), "no failure signal yet"
    assert gw.call(request("date_calc", date="2027-01-04", op="diff")).status == "FAILED"
    one = gw.call(thought())
    assert one.status == "OK" and one.data == {
        "thought_number": 1,
        "total_thoughts": 2,
        "next_thought_needed": True,
    }
    two = gw.call(thought("Then check the go-live date."))
    assert two.status == "OK" and two.data["thought_number"] == 2
    assert two.data["next_thought_needed"] is False, "code fills the counters"
    third = gw.call(thought("One more."))
    assert (third.status, third.reason) == ("DENIED", REFLECT_DENIED)
    assert gw.thoughts == 2 and gw.executed == 1, "a passing thought counts against no cap"

    off = gateway(fake_pins, reflect=False)
    off.call(request("date_calc", date="2027-01-04", op="diff"))
    assert off.call(thought()).reason == REFLECT_DENIED


def test_a_thought_passes_when_the_call_cap_is_spent(fake_pins: object) -> None:
    gw = gateway(fake_pins, reflect=True, cap=1)
    assert gw.call(request("date_calc", date="2027-01-04", op="diff")).status == "FAILED"
    assert gw.call(thought()).status == "OK" and gw.executed == 1
    spent = gw.call(request("date_calc", date="2027-01-04", op="weekday"))
    assert spent.status == "DENIED" and "budget" in (spent.reason or "")


def test_the_loop_reflects_after_a_failure_and_ends_once_both_thoughts_are_spent(
    fake_pins: object, tmp_path: Path
) -> None:
    index = PassageIndex.build(dev_ingest().passages, tmp_path / "search.sqlite")
    gw = gateway(fake_pins, reflect=True, index=index)
    search = ("search_rfp", {"query": "go-live migration"})
    backend = ScriptBackend(
        [
            tools(("date_calc", {"date": "2027-01-04", "op": "diff"})),  # fails: no progress
            tools(("reflect", {"thought": "The diff needs a second date."})),  # outside the cap
            tools(search),  # progress
            tools(search),  # evidence already seen: no progress, a thought is left
            tools(("reflect", {"thought": "Search for the migration deadline instead."})),
            tools(search),  # no progress, both thoughts spent: the loop ends
            REGISTER,
        ]
    )
    outcome = risk(context(backend), dev_requirements(), [], gw, ON)
    assert outcome.stop_reason == "no_progress" and outcome.turns == 4
    assert len(backend.requests) == 7 and gw.thoughts == 2
    assert "reflect" in {spec.name for spec in backend.requests[0].tools}


def test_without_reflect_the_definition_is_absent_and_the_loop_is_v0_2s(
    fake_pins: object,
) -> None:
    gw = gateway(fake_pins, reflect=False)
    backend = ScriptBackend([tools(("date_calc", {"date": "2027-01-04", "op": "diff"})), REGISTER])
    outcome = risk(context(backend), dev_requirements(), [], gw, OFF)
    assert outcome.stop_reason == "no_progress" and outcome.turns == 1
    assert "reflect" not in {spec.name for spec in backend.requests[0].tools}


def test_a_thoughts_span_holds_its_counts_and_hash_only() -> None:
    attributes = thought_attributes("Search for the migration deadline instead.")
    assert set(attributes) == {"bidwright.thought_chars", "bidwright.thought_sha256"}
    assert attributes["bidwright.thought_chars"] == 42
    assert str(attributes["bidwright.thought_sha256"]).startswith("sha256:")
    assert "migration" not in " ".join(str(v) for v in attributes.values())


def test_the_egress_check_allows_reflect_and_refuses_another_stdio_server() -> None:
    entry = CONFIG.research.servers["reflect"]
    assert (
        check_run({}, None, None, "client", register=CONFIG.egress, research=[("reflect", entry)])
        == []
    )
    with pytest.raises(EgressRefused, match="runs over stdio"):
        check_run({}, None, None, "synthetic", register=CONFIG.egress, research=[("other", FAKE)])


NODE_PACKAGE = HOME / "node_modules" / "@modelcontextprotocol" / "server-sequential-thinking"


@pytest.mark.skipif(
    shutil.which("node") is None or not NODE_PACKAGE.is_dir(),
    reason="Node or the pinned sequential-thinking package is absent; run npm ci",
)
def test_the_pinned_server_answers_through_its_pins() -> None:
    tool = reflect_for(CONFIG)
    gw = ToolGateway.for_agent(
        "risk", ["date_calc", "reflect"], [date_tool(), tool], 6, reflect=True
    )
    gw.call(request("date_calc", date="2027-01-04", op="diff"))
    result = gw.call(thought())
    assert result.status == "OK", result.reason
    assert result.data == {"thought_number": 1, "total_thoughts": 2, "next_thought_needed": True}
