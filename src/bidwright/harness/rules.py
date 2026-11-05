"""The gateway's rules (Iteration 2, ADR-032): the four checks of `v0.0` and G1 to G5.

`ToolGateway` evaluates every rule a call triggers, in `RULES` order: the allowlist, G2, the
argument schema, repeats, the call cap, G4, G1, G5 and G3. G2 runs before the schema check so
that an attempt to name a notebook leaves a security event; G3 runs last because it needs the
text code would send. The first rule a call breaks decides its outcome: `deny` returns
`DENIED` with the rule's reason, `return` returns `EMPTY` with it, so the model can finish, and
`pause`, for Iteration 3's gate, is defined but unused. A call counts against the call cap only
when it passes every rule. The four checks of `v0.0` keep their reason strings byte for byte,
since recorded transcripts hold them and later cassette keys depend on them.

A rule is a small class with `name`, `trigger`, `description` (its check, in words), `outcome`
and `check`; `scripts/gen_docs.py` writes the rules table in `docs/agents.md` from these
classes. The research rules read a `RuleContext`: the run's passages as the text view shows
them, the research record's counts read live at each check, whether the research server's pins
matched when the run first connected, the events log for security events, and `query_for`,
the text a research tool would send.

From Iteration 3 (section 6.2 of its design), G3 and G4 also trigger on Context7's two tools,
`CONTEXT7_TOOLS`, which code calls for `techcheck`: G3 checks their `query` and `libraryName`,
each on its own, and G4 the `context7` server's pins. G2 does not trigger on them, since code
builds their arguments.

A replay consumes nothing (Iteration 2, step 11): a resumed node's model asks again what it asked
before the stop, so G1 lets through a `start_research` whose query is a recorded job's, which
returns that job's label and starts nothing, and G5 an `ask_research` whose question is
recorded, which is answered from `research.json`. Every other rule still applies to them.
"""

import hashlib
import json
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from pydantic import BaseModel, ValidationError

from bidwright.obs.events import EventRecorder
from bidwright.schemas import Attribution, Passage, ResearchRecord, ToolRequest
from bidwright.text import normalized_words, shared_run
from bidwright.verify import shown_text

if TYPE_CHECKING:
    from bidwright.harness.gateway import ToolGateway
    from bidwright.harness.view import TextView

Outcome = Literal["deny", "return", "pause"]
RESEARCH_TOOLS = frozenset({"start_research", "ask_research"})
# Context7's tools, which code calls for `techcheck` (Iteration 3, ADR-044).
CONTEXT7_TOOLS = frozenset({"resolve-library-id", "query-docs"})
OUTBOUND_TOOLS = RESEARCH_TOOLS | CONTEXT7_TOOLS  # the tools whose text leaves the run
_CONTEXT7_TEXTS = ("query", "libraryName")  # what G3 reads of a Context7 call
MAX_IDENTICAL_CALLS = 2
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_LONG_RUN = re.compile(r"[A-Za-z0-9_-]{30,}")
_ID_NAMES = ("notebook", "task", "source")


@dataclass
class Call:
    """One call on its way through the rules: the arguments are set by the schema check."""

    request: ToolRequest
    args: BaseModel | None = None


@dataclass(frozen=True)
class Finding:
    """Why a call broke a rule. `attribution` makes it a security event too."""

    reason: str
    event: str | None = None
    attribution: Attribution | None = None


@dataclass
class RuleContext:
    """What the research rules read, for one agent invocation. Built from the run's passages,
    and refused with none, since G3 would then let every query through; only a run that holds
    no RFP, as a research pack build's, says so with `rfp=False` and has no passages, so G3
    has nothing a query could copy."""

    passages: Sequence[Passage]
    view: "TextView | None" = None
    research: Callable[[], ResearchRecord] | None = None
    server: str | None = None  # the MCP server, NotebookLM's or Context7's, when there is one
    pinned: bool = False  # whether that server matched its pins when the run first connected
    events: EventRecorder | None = None
    node: str | None = None  # the node the events name
    query_for: Callable[[ToolRequest], str] | None = None
    max_shared_words: int = 7
    max_jobs: int = 2
    max_questions: int = 6
    rfp: bool = True  # False only for a run that holds no RFP
    suspect: frozenset[str] = field(init=False, default=frozenset())

    def __post_init__(self) -> None:
        if self.rfp and not self.passages:
            raise ValueError("a rule context needs the run's passages")
        if not self.rfp and self.passages:
            raise ValueError("a run that holds no RFP has no passages")
        self.suspect = frozenset(p.id for p in self.passages if p.suspect)

    @cached_property
    def runs(self) -> Mapping[tuple[str, ...], str]:
        """Each run of `max_shared_words + 1` normalized words in the run's passages, mapped
        to the first passage that holds it; built once."""
        size = self.max_shared_words + 1
        found: dict[tuple[str, ...], str] = {}
        for passage in self.passages:
            words = normalized_words(shown_text(passage, self.view))
            for start in range(len(words) - size + 1):
                found.setdefault(tuple(words[start : start + size]), passage.id)
        return found

    @cached_property
    def words(self) -> Mapping[str, list[str]]:
        return {p.id: normalized_words(shown_text(p, self.view)) for p in self.passages}

    def record(self) -> ResearchRecord | None:
        return self.research() if self.research is not None else None

    def sent(self, request: ToolRequest) -> str:
        """The text the tool would send: code's rendering, or the model's question."""
        if self.query_for is not None:
            return self.query_for(request)
        return str(request.args.get("question", ""))

    def sent_texts(self, request: ToolRequest) -> list[str]:
        """Each text a call would send, which G3 checks on its own: a Context7 call's query
        and library name, or `sent` for a research tool."""
        if request.tool in CONTEXT7_TOOLS:
            return [str(request.args.get(name, "")) for name in _CONTEXT7_TEXTS]
        return [self.sent(request)]

    def overlap(self, text: str) -> tuple[int, str] | None:
        """The longest run of normalized words `text` shares with one passage, and that
        passage's id, when it reaches `max_shared_words + 1` words; else None."""
        words = normalized_words(text)
        size = self.max_shared_words + 1
        found = {
            self.runs[run]
            for run in (tuple(words[s : s + size]) for s in range(len(words) - size + 1))
            if run in self.runs
        }
        if not found:
            return None
        shared = {src_id: shared_run(words, self.words[src_id]) for src_id in sorted(found)}
        src_id = max(shared, key=lambda s: shared[s])
        return shared[src_id], src_id


class Rule:
    name: ClassVar[str]
    trigger: ClassVar[str]
    description: ClassVar[str]
    outcome: ClassVar[Outcome] = "deny"
    note: ClassVar[str] = ""  # what the outcome adds, for the rules table
    tools: ClassVar[frozenset[str] | None] = None  # None: every call

    def triggered(self, call: Call, gateway: "ToolGateway") -> bool:
        return self.tools is None or call.request.tool in self.tools

    def check(self, call: Call, gateway: "ToolGateway") -> Finding | None:
        raise NotImplementedError


class Allowlist(Rule):
    name = "allowlist"
    trigger = "Every call"
    description = "The tool is registered and listed for the agent in `config/agents.yaml`"

    def check(self, call: Call, gateway: "ToolGateway") -> Finding | None:
        request = call.request
        if (
            request.agent != gateway.agent
            or request.tool not in gateway.allowed
            or request.tool not in gateway.tools
        ):
            return Finding(f"{request.tool!r} is not allowed for agent {request.agent!r}")
        return None


class BoundIds(Rule):
    name = "G2 bound ids"
    trigger = "`start_research`, `ask_research`"
    description = (
        "No argument key outside the tool's schema has a name containing notebook, task or"
        " source, in any letter case, and no string value, at any depth, contains a UUID or a"
        " run of 30 or more letters, digits, hyphens and underscores"
    )
    note = ", with a security event attributed `authorization-dominant`"
    tools = RESEARCH_TOOLS

    def check(self, call: Call, gateway: "ToolGateway") -> Finding | None:
        request = call.request
        known = set(gateway.tools[request.tool].args_model.model_fields)
        for key, value, depth in _walk(request.args):
            if key is not None and (depth > 0 or key not in known) and _names_an_id(key):
                return self._found(request.tool, f"the argument {key!r} names an id")
            if isinstance(value, str) and (_UUID.search(value) or _LONG_RUN.search(value)):
                return self._found(request.tool, "an argument holds an id")
        return None

    def _found(self, tool: str, what: str) -> Finding:
        return Finding(
            f"{tool} denied: code binds the notebook, task and source ids, and {what}",
            event=f"G2 denied {tool}: {what}",
            attribution="authorization-dominant",
        )


def _names_an_id(key: str) -> bool:
    lowered = key.casefold()
    return any(name in lowered for name in _ID_NAMES)


def _walk(value: Any, depth: int = 0) -> Iterator[tuple[str | None, Any, int]]:
    """Every key and value at any depth, with the depth: only a top-level key can be one of
    the schema's fields."""
    if isinstance(value, Mapping):
        for key, inner in value.items():
            yield str(key), inner, depth
            yield from _walk(inner, depth + 1)
    elif isinstance(value, list | tuple):
        for inner in value:
            yield None, inner, depth
            yield from _walk(inner, depth + 1)


class Schema(Rule):
    name = "argument schema"
    trigger = "Every call"
    description = "The arguments validate against the tool's Pydantic model"

    def check(self, call: Call, gateway: "ToolGateway") -> Finding | None:
        request = call.request
        try:
            call.args = gateway.tools[request.tool].args_model.model_validate(request.args)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}"
                for e in exc.errors()
            )
            return Finding(f"bad arguments for {request.tool}: {problems}")
        return None


class Repeats(Rule):
    name = "repeats"
    trigger = "Every call"
    description = "No third identical call: the same tool with the same arguments"

    def check(self, call: Call, gateway: "ToolGateway") -> Finding | None:
        if call.args is None:  # the schema check runs first and sets them
            raise RuntimeError("the repeats rule ran before the argument schema")
        key = call.request.tool + json.dumps(call.args.model_dump(), sort_keys=True, default=str)
        gateway.seen[key] += 1
        if gateway.seen[key] > MAX_IDENTICAL_CALLS:
            return Finding(f"{call.request.tool} was already called twice with these arguments")
        return None


class CallCap(Rule):
    name = "call cap"
    trigger = "Every call"
    description = "The agent's tool-call cap is not yet spent, counting from the run's start"

    def check(self, call: Call, gateway: "ToolGateway") -> Finding | None:
        if gateway.executed >= gateway.max_tool_calls:
            return Finding(f"the tool-call budget of {gateway.max_tool_calls} is spent")
        return None


class PinnedServer(Rule):
    name = "G4 pinned server"
    trigger = (
        "`start_research`, `ask_research`, when the research provider is NotebookLM;"
        " `resolve-library-id`, `query-docs`"
    )
    description = (
        "The server's reported name and version, and its tools, matched their pins when the"
        " run first connected"
    )
    note = ': "server refused: its tools do not match their pins"'
    tools = OUTBOUND_TOOLS

    def triggered(self, call: Call, gateway: "ToolGateway") -> bool:
        context = gateway.context
        return super().triggered(call, gateway) and context is not None and bool(context.server)

    def check(self, call: Call, gateway: "ToolGateway") -> Finding | None:
        if gateway.context is not None and not gateway.context.pinned:
            return Finding("server refused: its tools do not match their pins")
        return None


def query_sha256(text: str) -> str:
    """The hash `research.json` records for a research job's query."""
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


class JobLimit(Rule):
    name = "G1 job limit"
    trigger = "`start_research`"
    description = (
        "Fewer than 2 jobs this run, or the query of a recorded job, which starts nothing; and"
        " no other `start_research` in the same turn"
    )
    note = """: "the run's research jobs are spent", or "one job a turn\""""
    tools = frozenset({"start_research"})

    def check(self, call: Call, gateway: "ToolGateway") -> Finding | None:
        context = gateway.context
        record = context.record() if context is not None else None
        if context is None or record is None:
            return Finding("the run's research jobs are spent")
        replay = query_sha256(context.sent(call.request)) in {j.query_sha256 for j in record.jobs}
        if not replay and len(record.jobs) >= context.max_jobs:
            return Finding("the run's research jobs are spent")
        if any(
            ran.tool == "start_research" and ran.turn == call.request.turn for ran in gateway.ran
        ):
            return Finding("one job a turn")
        return None


class QuestionCap(Rule):
    name = "G5 question cap"
    trigger = "`ask_research` from `discover`"
    description = (
        "Fewer than 6 questions this run, or a recorded question, which is answered from"
        " `research.json`"
    )
    outcome = "return"
    note = ': "no questions left; finish"'
    tools = frozenset({"ask_research"})

    def triggered(self, call: Call, gateway: "ToolGateway") -> bool:
        """Only `discover`'s questions reach a research provider; `decide`'s ask the run's own
        research and count against its call cap (Iteration 3, section 6.2)."""
        return super().triggered(call, gateway) and call.request.agent == "discover"

    def check(self, call: Call, gateway: "ToolGateway") -> Finding | None:
        context = gateway.context
        record = context.record() if context is not None else None
        if context is None or record is None:
            return Finding("no questions left; finish")
        question = str(call.request.args.get("question", ""))
        replay = question in {answer.question for answer in record.answers}
        if not replay and len(record.answers) >= context.max_questions:
            return Finding("no questions left; finish")
        return None


class OutboundOverlap(Rule):
    name = "G3 outbound overlap"
    trigger = "`start_research`, `ask_research`, `resolve-library-id`, `query-docs`"
    description = (
        "Each text the tool would send (a Context7 call's query and library name each on its"
        " own) shares fewer than 8 consecutive normalized words with every passage of the run"
    )
    note = (
        ", with a security event attributed `injection-dominant` when the passage is marked"
        " `suspect` and `indeterminate` otherwise"
    )
    tools = OUTBOUND_TOOLS

    def check(self, call: Call, gateway: "ToolGateway") -> Finding | None:
        context = gateway.context
        if context is None:
            return Finding("research needs the run's passages to check what it sends")
        tool = call.request.tool
        found = [context.overlap(text) for text in context.sent_texts(call.request)]
        shared = max((f for f in found if f is not None), default=None)
        if shared is None:
            return None
        count, src_id = shared
        return Finding(
            f"{tool} denied: it shares {count} consecutive words with {src_id}; research"
            " queries never carry RFP text",
            event=f"G3 denied {tool}: {count} words shared with {src_id}",
            attribution="injection-dominant" if src_id in context.suspect else "indeterminate",
        )


RULES: tuple[Rule, ...] = (
    Allowlist(),
    BoundIds(),
    Schema(),
    Repeats(),
    CallCap(),
    PinnedServer(),
    JobLimit(),
    QuestionCap(),
    OutboundOverlap(),
)
OUTCOMES: Mapping[Outcome, str] = {
    "deny": "Deny",
    "return": "Return to the model",
    "pause": "Pause for a human",
}

__all__ = [
    "CONTEXT7_TOOLS",
    "MAX_IDENTICAL_CALLS",
    "OUTBOUND_TOOLS",
    "OUTCOMES",
    "RESEARCH_TOOLS",
    "RULES",
    "Call",
    "Finding",
    "Rule",
    "RuleContext",
    "query_sha256",
]
