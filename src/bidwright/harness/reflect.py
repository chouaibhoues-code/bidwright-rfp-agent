"""The gated `reflect` tool (Iteration 3, step 11; ADR-047, CH-68).

The tool the model sees is `reflect(thought)`. Behind it is the reference sequential-thinking
server, `@modelcontextprotocol/server-sequential-thinking` 1.0.0, pinned in `package.json` and
`package-lock.json`, installed by `npm ci` and run over stdio through `McpClient` with
`DISABLE_THOUGHT_LOGGING=true`, one process a thought. The server lists one tool,
`sequentialthinking`, which requires `thought`, `nextThoughtNeeded`, `thoughtNumber` and
`totalThoughts` (`SENT`; checked on 1.0.0, 2026-11-05). Code fills the counters: the thought's
number, 1 or 2, `totalThoughts` 2, and `nextThoughtNeeded` true on the first thought only, so
nothing relies on the server's own history. The server's pins are checked at the first thought
of each tool; a mismatch, or a server out of reach, returns `FAILED` with the reason.

The gateway's rule G6 decides whether a call reaches the tool (`harness/rules.py`); the tool
only makes the call. `thought_attributes` gives a thought's span its counts and hash, never its
text. The 1.0.0 pin keeps Node 22: the server's 2.x releases need Node 24, and 2.0.0 is a
rewrite onto a new SDK package.
"""

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from bidwright.config import Config, ServerPins, StdioServer
from bidwright.harness.rules import MAX_THOUGHTS, REFLECT
from bidwright.llm.types import Breaker, CircuitOpen
from bidwright.preflight import HOME
from bidwright.research.mcp_client import McpClient, McpError
from bidwright.research.pins import ServerRefused, check
from bidwright.schemas import ToolResult
from bidwright.tools import Tool

SERVER = "reflect"
TOOL = "sequentialthinking"
SENT: Mapping[str, frozenset[str]] = {
    TOOL: frozenset({"thought", "nextThoughtNeeded", "thoughtNumber", "totalThoughts"}),
}
THOUGHT_MAX_CHARS = 2000


class ReflectArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thought: str = Field(
        min_length=1,
        max_length=THOUGHT_MAX_CHARS,
        description="One step of reasoning about what went wrong and what to try next.",
    )


def thought_attributes(thought: str) -> dict[str, Any]:
    """A thought's span attributes: its length and hash, never its text."""
    digest = hashlib.sha256(thought.encode("utf-8")).hexdigest()
    return {"bidwright.thought_chars": len(thought), "bidwright.thought_sha256": f"sha256:{digest}"}


def reflect_tool(client: McpClient, pins: ServerPins) -> Tool:
    """A `reflect` tool for one agent invocation: it counts its own thoughts."""
    state: dict[str, Any] = {"thoughts": 0, "pinned": None, "refusal": None}

    def connect() -> bool:
        if state["pinned"] is None:
            reported, tools = client.list_tools()
            try:
                check(client.name, reported, tools, pins)
            except ServerRefused as exc:
                state["pinned"], state["refusal"] = False, str(exc)
            else:
                state["pinned"] = True
        return bool(state["pinned"])

    def run(args: ReflectArgs) -> ToolResult:
        try:
            if not connect():
                return ToolResult(status="FAILED", reason=f"reflect refused: {state['refusal']}")
            number = state["thoughts"] + 1
            answer = client.call(
                TOOL,
                {
                    "thought": args.thought,
                    "thoughtNumber": number,
                    "totalThoughts": MAX_THOUGHTS,
                    "nextThoughtNeeded": number < MAX_THOUGHTS,
                },
            )
        except (McpError, CircuitOpen) as exc:
            return ToolResult(status="FAILED", reason=f"reflect failed: {exc}")
        state["thoughts"] = number
        data = {
            "thought_number": answer.get("thoughtNumber", number),
            "total_thoughts": answer.get("totalThoughts", MAX_THOUGHTS),
            "next_thought_needed": answer.get("nextThoughtNeeded", number < MAX_THOUGHTS),
        }
        return ToolResult(status="OK", data=data)

    return Tool(
        name=REFLECT,
        description=(
            "Think one step through after a tool call failed or a turn found nothing new: what"
            " went wrong, and what to try next. At most two thoughts; then act."
        ),
        args_model=ReflectArgs,
        run=run,
    )


def reflect_server(server: StdioServer, home: Path = HOME) -> StdioServer:
    """The server entry with each relative argument that names a file under `home` resolved,
    so the server starts from any working directory."""
    args = [
        str(home / a) if not Path(a).is_absolute() and (home / a).exists() else a
        for a in server.args
    ]
    return server.model_copy(update={"args": args})


def reflect_for(config: Config, breaker: Breaker | None = None) -> Tool:
    """The `reflect` tool over the configured server, with its pins."""
    entry = config.research.servers[SERVER]
    if not isinstance(entry, StdioServer):
        raise ValueError("config/research.yaml's reflect server runs over stdio")
    client = McpClient(SERVER, reflect_server(entry), breaker=breaker)
    return reflect_tool(client, config.pins.servers.get(SERVER, ServerPins()))


__all__ = [
    "SENT",
    "SERVER",
    "TOOL",
    "ReflectArgs",
    "reflect_for",
    "reflect_server",
    "reflect_tool",
    "thought_attributes",
]
