"""`ToolGateway`: every tool call an agent asks for passes through it, outside the model.

The gateway evaluates the rules of `harness/rules.py` that a call triggers, in their order
(ADR-032): the allowlist, G2 bound ids, the argument schema, repeats, G6 reflection gate (from
Iteration 3), the call cap, G4 pinned server, G1 job limit, G5 question cap and G3 outbound
overlap. A call that breaks a rule gets that rule's outcome, `DENIED` or `EMPTY` with the rule's
reason, which goes back to the model, and the tool never runs; a rule that finds a security
breach also records a security event with its attribution class. A call that passes every rule
runs and counts against the agent's cap, which can start from the run's own count, so a cap
holds across nodes and resumes; a `reflect` thought that passes counts as a thought instead,
outside the cap (ADR-047). The research rules need a `RuleContext`; an agent that may call a
research or Context7 tool is refused one without it. Every request and result is kept in `calls`
for the trace.

`ToolLog` is the only writer of the run's `tool_calls.jsonl`: every gateway's calls, one row
each, with `part`, the run's resume count, so a call made again after a resume is told apart.
"""

import json
import threading
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from bidwright.harness.rules import OUTBOUND_TOOLS, REFLECT, RULES, Call, RuleContext
from bidwright.schemas import ToolRequest, ToolResult
from bidwright.tools import Tool


class ToolLog:
    def __init__(self, path: Path, part: int = 0) -> None:
        self.path = path
        self.part = part
        self._lock = threading.Lock()

    def create(self) -> None:
        """An empty log, written when a fresh run starts in its folder."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8", newline="\n")

    def append(self, request: ToolRequest, result: ToolResult) -> None:
        row = {
            "agent": request.agent,
            "tool": request.tool,
            "args": request.args,
            "turn": request.turn,
            "status": result.status,
            "reason": result.reason,
            "data": result.data,
            "part": self.part,
        }
        with self._lock, self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


@dataclass
class ToolGateway:
    agent: str
    allowed: frozenset[str]
    tools: Mapping[str, Tool]
    max_tool_calls: int
    context: RuleContext | None = None
    log: ToolLog | None = None
    calls: list[tuple[ToolRequest, ToolResult]] = field(default_factory=list)
    ran: list[ToolRequest] = field(default_factory=list)  # the calls that passed every rule
    seen: Counter[str] = field(default_factory=Counter)
    # Iteration 3 (ADR-047): whether the agent's limits allow reflect, the thoughts taken this
    # invocation, and whether its loop's last turn of other tools made progress.
    reflect: bool = False
    thoughts: int = 0
    last_progress: bool | None = None
    _executed: int = 0

    @classmethod
    def for_agent(
        cls,
        agent: str,
        allowed: Iterable[str],
        tools: Iterable[Tool],
        max_tool_calls: int,
        *,
        executed: int = 0,
        context: RuleContext | None = None,
        log: ToolLog | None = None,
        reflect: bool = False,
    ) -> "ToolGateway":
        """`executed` is the run's count so far against `max_tool_calls`; `reflect` is the
        agent's `reflect` limit."""
        listed = frozenset(allowed)
        if listed & OUTBOUND_TOOLS and context is None:
            raise ValueError(
                f"agent {agent!r} may call research or Context7 tools, which need a RuleContext"
            )
        return cls(
            agent,
            listed,
            {t.name: t for t in tools},
            max_tool_calls,
            context=context,
            log=log,
            reflect=reflect,
            _executed=executed,
        )

    @property
    def executed(self) -> int:
        """Tool calls that passed every rule and ran, counting from the run's start."""
        return self._executed

    def specs(self) -> list[Tool]:
        """The tools this agent may see, in a stable order."""
        return [self.tools[name] for name in sorted(self.allowed) if name in self.tools]

    def turn_done(self, progress: bool) -> None:
        """The loop's report on its last turn of tools other than `reflect`, which G6 reads."""
        self.last_progress = progress

    def call(self, request: ToolRequest) -> ToolResult:
        result = self._decide(request)
        self.calls.append((request, result))
        if self.log is not None:
            self.log.append(request, result)
        return result

    def _decide(self, request: ToolRequest) -> ToolResult:
        call = Call(request)
        for rule in RULES:
            if not rule.triggered(call, self):
                continue
            finding = rule.check(call, self)
            if finding is None:
                continue
            context = self.context
            if finding.attribution is not None and context is not None and context.events:
                context.events.record(
                    "security",
                    context.node or self.agent,
                    finding.event or finding.reason,
                    finding.attribution,
                )
            if rule.outcome == "pause":
                raise NotImplementedError("pausing for a human arrives with Iteration 3's gate")
            status = "EMPTY" if rule.outcome == "return" else "DENIED"
            return ToolResult(status=status, reason=finding.reason)
        if request.tool == REFLECT:
            self.thoughts += 1  # outside the call cap (ADR-047)
        else:
            self._executed += 1
        self.ran.append(request)
        try:
            return self.tools[request.tool].run(call.args)
        except Exception as exc:  # a tool bug must not crash the run
            return ToolResult(status="FAILED", reason=f"{request.tool} failed: {exc}")


__all__ = ["ToolGateway", "ToolLog"]
