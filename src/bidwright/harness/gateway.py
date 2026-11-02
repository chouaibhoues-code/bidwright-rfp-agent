"""The minimal `ToolGateway`: every tool call an agent asks for passes through it.

Checks, in order, outside the model:
1. allowlist: the tool is registered and listed for the agent in `config/agents.yaml`;
2. argument schema: the arguments validate against the tool's Pydantic model;
3. repeats: a third identical call (same tool, same arguments) is denied;
4. budget: the agent's tool-call cap for this invocation is not yet spent.
A failed check returns a `DENIED` result with the reason, which goes back to the model; the
tool never runs. Every request and result is kept in `calls` for the trace.
"""

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from pydantic import ValidationError

from bidwright.schemas import ToolRequest, ToolResult
from bidwright.tools import Tool

MAX_IDENTICAL_CALLS = 2


@dataclass
class ToolGateway:
    agent: str
    allowed: frozenset[str]
    tools: Mapping[str, Tool]
    max_tool_calls: int
    calls: list[tuple[ToolRequest, ToolResult]] = field(default_factory=list)
    _seen: Counter[str] = field(default_factory=Counter)
    _executed: int = 0

    @classmethod
    def for_agent(
        cls, agent: str, allowed: Iterable[str], tools: Iterable[Tool], max_tool_calls: int
    ) -> "ToolGateway":
        return cls(agent, frozenset(allowed), {t.name: t for t in tools}, max_tool_calls)

    def specs(self) -> list[Tool]:
        """The tools this agent may see, in a stable order."""
        return [self.tools[name] for name in sorted(self.allowed) if name in self.tools]

    def call(self, request: ToolRequest) -> ToolResult:
        result = self._decide(request)
        self.calls.append((request, result))
        return result

    def _decide(self, request: ToolRequest) -> ToolResult:
        tool = self.tools.get(request.tool)
        if request.agent != self.agent or request.tool not in self.allowed or tool is None:
            return _denied(f"{request.tool!r} is not allowed for agent {request.agent!r}")
        try:
            args = tool.args_model.model_validate(request.args)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}"
                for e in exc.errors()
            )
            return _denied(f"bad arguments for {request.tool}: {problems}")
        key = request.tool + json.dumps(args.model_dump(), sort_keys=True, default=str)
        self._seen[key] += 1
        if self._seen[key] > MAX_IDENTICAL_CALLS:
            return _denied(f"{request.tool} was already called twice with these arguments")
        if self._executed >= self.max_tool_calls:
            return _denied(f"the tool-call budget of {self.max_tool_calls} is spent")
        self._executed += 1
        try:
            return tool.run(args)
        except Exception as exc:  # a tool bug must not crash the run
            return ToolResult(status="FAILED", reason=f"{request.tool} failed: {exc}")


def _denied(reason: str) -> ToolResult:
    return ToolResult(status="DENIED", reason=reason)
