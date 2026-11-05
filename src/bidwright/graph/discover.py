"""`discover` (Iteration 2, step 11; ADR-033, ADR-034 and ADR-036): research on the RFP's domain
from the brief's topics, behind the research provider. The model never sees the RFP.

Five nodes, which step 12 wires as section 4.1 of the design draws them, each a method of
`Discovery`:
- `load`, `discover_load`, code: in research mode `pack`, and after a live node's research
  failure, the research pack the topics select is loaded with no model call, and its
  `DomainBrief` becomes `domain_brief.json`. No matching pack is not a shortfall; a refused
  pack is, and so is a live failure, whether or not a pack then loads.
- `start`, `discover_start`, one agent turn: code creates the run's notebook, titled with the
  run id, and writes its id before the turn, whose only tool is `start_research`. A turn that
  starts no job gets one reminder; if that one starts none either, code calls `start_research`
  with the topics as the question, through the gateway like the model's own call. With no
  topics, no job starts.
- `wait`, `discover_wait`, code: polls the latest unfinished job, the budget paused around each
  poll and each sleep. A stop request raises `ResearchStopped` before a poll; a job still
  running after the wait cap is `timed_out`, and `ResearchPending` leaves the run
  `WAITING_RESEARCH`, while a resume sets it running again with a fresh cap. A finished job's
  cited sources are imported, and the research provider is bound to its notebook.
- `ask`, `discover_ask`, an agent pass of at most `max_turns` turns over the latest finished
  job's report: `ask_research` always, and `start_research` while the run's second job is
  unspent. A pass ends when a second job starts (`second_job`, so the edge goes back to
  `discover_wait`), when the model answers with no tool call, at a turn that returns no excerpt
  the pass has not seen, or at the call cap.
- `extract`, `discover_extract`, one call over every finished job's report, newest first, with
  the answers and their excerpts, which becomes `domain_brief.json`.

`start_research` builds the query from the prompt's `envelope` element with the model's question
and topics, and is idempotent on the query's hash: a call whose query a recorded job holds
returns that job's label and starts nothing. A second job gets a fresh notebook. Every notebook
and job id is written to `research.json` as soon as it exists. `ask_research` answers a question
already recorded from `research.json`, so a resumed node sees the same transcript; every other
question goes to the research provider, and its answer is screened and recorded, an empty one
too, with the job it was asked of, before it returns. The gateway lets both kinds of replay
through its caps (G1, G5). A pass sees the research as it stood when it began, the answers of
earlier passes and the jobs that have ended, so a pass rerun after a crash builds the same
requests although the crashed run had recorded answers or started a job.

A research failure inside a live node is written to `research.json`'s notes and returned as the
node's `failed`, so the edge goes to `discover_load`: a tool error, a refused server, an open
breaker on the server, a failed job, or code's own query refused by the gateway. A failure of
the model's own call is not one: a denial goes back to the model, and an open breaker on the
model propagates as it does in every node. `ResearchPending` and `ResearchStopped` propagate.

Inbound trust (`research/trust.py`): every excerpt and answer is screened as it arrives, and
every report paragraph before a model sees it; a suspect report paragraph is removed, with a
security event and a note. In the extraction, an id that is unknown or quarantined is dropped,
the first 3 of the rest kept, and an item or a need whose excerpts all come from tier-4 sources
is dropped; each drop and cut is noted. Reports stay in memory only, and a resumed node polls
its finished jobs once to get them back.

This module is the only writer of `research.json` and `domain_brief.json`; `research.json` is
rewritten whole through `fileio.write_atomic` after every change. Its `tool_calls` and `calls`
move only when a node ends, so a node rerun after a crash counts its tool calls from the same
base and names its context manifests, `context/discover-D01.json` onward, with the same ids.
"""

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes

from bidwright.candidates import cut
from bidwright.config import AgentConfig, ResearchConfig
from bidwright.fileio import write_atomic
from bidwright.graph.nodes import RunContext
from bidwright.harness.context import ContextManager, estimate_tokens, prompt_tokens
from bidwright.harness.egress import RESEARCH_DESTINATION
from bidwright.harness.gateway import ToolGateway, ToolLog
from bidwright.harness.rules import RuleContext, query_sha256
from bidwright.llm.client import Completion
from bidwright.llm.schema import sha256_of
from bidwright.llm.types import CircuitOpen, Message, ToolCall
from bidwright.obs.events import EventRecorder, utc_now
from bidwright.obs.tracing import set_attribute
from bidwright.research.mcp_client import McpError
from bidwright.research.pack import NO_PACK, Pack, PackRefused, load_pack, select_pack
from bidwright.research.pins import ServerRefused
from bidwright.research.provider import ResearchProvider, ResearchRefused
from bidwright.research.trust import ATTRIBUTION, screen, suspect
from bidwright.schemas import (
    ANSWER_MAX_CHARS,
    DOMAIN_NEED_MAX_CHARS,
    DOMAIN_STATEMENT_MAX_CHARS,
    DOMAIN_SUMMARY_MAX_CHARS,
    OPEN_QUESTIONS_MAX,
    AnswerView,
    AskResult,
    DiscoveryExtract,
    DiscoveryTask,
    DomainBrief,
    DomainItem,
    DomainNeed,
    ExcerptView,
    JobStatus,
    PackAnswer,
    PackExcerpt,
    PackSource,
    Passage,
    ResearchJob,
    ResearchModeName,
    ResearchRecord,
    ToolRequest,
    ToolResult,
)
from bidwright.tools import NO_SOURCED_ANSWER, StartResearchArgs, Tool, ask_tool, start_tool

NODE = "discover"  # the agent, its prompt and its call ids
RESEARCH_FILE = "research.json"
BRIEF_FILE = "domain_brief.json"
POLL_WAIT_S = 30.0  # each poll's wait at the server
QUESTION_MAX_CHARS = 300  # StartResearchArgs.question
NO_TOPICS = "research: the brief gave no topics"
FAILURES = (McpError, ServerRefused, ResearchRefused, CircuitOpen)  # inside a provider call


class ResearchPending(Exception):
    """A job still runs after the wait cap: the run waits in `WAITING_RESEARCH`."""


class ResearchStopped(Exception):
    """A stop was requested while a job ran: the run is `STOPPED`."""


class _Failed(Exception):
    """A research failure inside a live node."""


class Drain(Protocol):
    """What `discover_wait` reads of LangGraph's `RunControl`."""

    @property
    def drain_requested(self) -> bool: ...


@dataclass(frozen=True)
class NodeOutcome:
    """What a live node tells the graph: `failed` routes to `discover_load`, with the reason;
    `second_job` routes `discover_ask` back to `discover_wait`."""

    failed: str | None = None
    second_job: bool = False
    view: dict[str, Any] | None = None  # `discover_extract`'s domain brief, for the summary


@dataclass(frozen=True)
class LoadOutcome:
    domain_brief: DomainBrief | None
    degraded: str | None  # the run's shortfall, or None
    view: dict[str, Any] | None = None  # the domain brief, for the summary


def domain_view(
    brief: DomainBrief,
    origin: str,
    excerpts: Sequence[PackExcerpt],
    sources: Sequence[PackSource],
) -> dict[str, Any]:
    """The domain brief as the summary's appendix reads it: where it came from, and each cited
    excerpt's source title and tier, so `render` needs neither the pack nor `research.json`."""
    titles = {s.id: (s.title, s.tier) for s in sources}
    cited = {i for entry in [*brief.items, *brief.needs] for i in entry.excerpt_ids}
    citations = {
        e.id: {"title": titles[e.source_id][0], "tier": titles[e.source_id][1]}
        for e in excerpts
        if e.id in cited and e.source_id in titles
    }
    return {"brief": brief.model_dump(mode="json"), "origin": origin, "citations": citations}


@dataclass
class ResearchStore:
    """`research.json`, read whole before each change and rewritten whole after it."""

    path: Path
    mode: ResearchModeName

    def load(self) -> ResearchRecord:
        if not self.path.exists():
            return ResearchRecord(mode=self.mode)
        return ResearchRecord.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, record: ResearchRecord) -> ResearchRecord:
        write_atomic(self.path, record.model_dump_json(indent=1) + "\n")
        return record

    def note(self, *notes: str) -> ResearchRecord:
        record = self.load()
        fresh = [n for n in dict.fromkeys(notes) if n not in record.notes]
        if not fresh and self.path.exists():
            return record
        return self.save(record.model_copy(update={"notes": [*record.notes, *fresh]}))


def _excerpt_tiers(
    excerpts: Sequence[PackExcerpt], sources: Sequence[PackSource]
) -> dict[str, int]:
    """Each clean excerpt with a known source, by id, with its source's tier."""
    tiers = {s.id: s.tier for s in sources}
    return {
        e.id: tiers[e.source_id] for e in excerpts if not e.quarantined and e.source_id in tiers
    }


def _supported(
    cited: Sequence[str],
    tiers: dict[str, int],
    what: str,
    notes: list[str],
    tier_rule: bool,
) -> list[str] | None:
    """The first 3 clean ids an item cites, or None when it rests on none, or, under the tier
    rule, on tier 4 only."""
    refused = [i for i in dict.fromkeys(cited) if i not in tiers]
    if refused:
        notes.append(f"{what} cited unknown or quarantined excerpts: {', '.join(refused)}")
    kept = [i for i in dict.fromkeys(cited) if i in tiers][:3]
    if not kept:
        notes.append(f"{what} dropped: it cites no clean excerpt")
        return None
    if tier_rule and all(tiers[i] == 4 for i in kept):
        notes.append(f"{what} dropped: its excerpts all come from tier-4 sources")
        return None
    return kept


def _cut(text: str, limit: int, what: str, notes: list[str]) -> str:
    joined = " ".join(text.split())
    if len(joined) > limit:
        notes.append(f"{what} was cut to {limit} characters")
        return cut(joined, limit)
    return joined


def settle_brief(
    proposal: DiscoveryExtract,
    excerpts: Sequence[PackExcerpt],
    sources: Sequence[PackSource],
    *,
    mode: ResearchModeName,
    domain_id: str | None = None,
    tier_rule: bool = True,
) -> tuple[DomainBrief, list[str]]:
    """The extraction as a `DomainBrief`, by the rules above, and the notes that name each
    drop and cut. A research pack's recorded brief goes through them again each time it loads,
    without the tier rule, which its live extraction applied: a pack loses only what now cites a
    quarantined or unknown excerpt."""
    tiers = _excerpt_tiers(excerpts, sources)
    notes: list[str] = []
    items: list[DomainItem] = []
    for item in proposal.items:
        what = f"{item.kind} {' '.join(item.statement.split())[:40]!r}"
        statement = _cut(item.statement, DOMAIN_STATEMENT_MAX_CHARS, what, notes)
        kept = _supported(item.excerpt_ids, tiers, what, notes, tier_rule) if statement else None
        if kept:
            items.append(
                DomainItem(
                    id=f"DI-{len(items) + 1:03d}",
                    kind=item.kind,
                    statement=statement,
                    excerpt_ids=kept,
                )
            )
    needs: list[DomainNeed] = []
    for need in proposal.needs:
        what = f"need {' '.join(need.need.split())[:40]!r}"
        text = _cut(need.need, DOMAIN_NEED_MAX_CHARS, what, notes)
        kept = _supported(need.excerpt_ids, tiers, what, notes, tier_rule) if text else None
        if kept:
            needs.append(DomainNeed(id=f"DN-{len(needs) + 1:03d}", need=text, excerpt_ids=kept))
    questions = [" ".join(q.split()) for q in proposal.open_questions if q.strip()]
    if len(questions) > OPEN_QUESTIONS_MAX:
        notes.append(f"open questions after the first {OPEN_QUESTIONS_MAX} dropped")
    brief = DomainBrief(
        domain_id=domain_id,
        mode="pack" if mode == "pack" else "live",
        summary=_cut(proposal.summary, DOMAIN_SUMMARY_MAX_CHARS, "the summary", notes),
        items=items,
        needs=needs,
        open_questions=questions[:OPEN_QUESTIONS_MAX],
    )
    return brief, notes


def _settled(record: ResearchRecord) -> int:
    """The jobs that have ended. `discover_ask` runs only once `discover_wait` has ended
    every job, so a job still running at a pass's start is one a crashed run of that pass
    started."""
    return sum(1 for j in record.jobs if j.state not in ("running", "timed_out"))


def _recorded_proposal(brief: DomainBrief) -> DiscoveryExtract:
    """A recorded brief as the proposal `settle_brief` checks, so a pack's brief meets the same
    rules as a live extraction each time it loads."""
    return DiscoveryExtract.model_validate(
        {
            "summary": brief.summary,
            "items": [i.model_dump(exclude={"id"}) for i in brief.items],
            "needs": [n.model_dump(exclude={"id"}) for n in brief.needs],
            "open_questions": brief.open_questions,
        }
    )


@dataclass
class Discovery:
    """The research nodes of one run, over its research provider (`None` in research mode
    `pack`, where only `load` runs)."""

    ctx: RunContext
    provider: ResearchProvider | None
    config: ResearchConfig
    agent: AgentConfig
    run_dir: Path
    manager: ContextManager
    passages: Sequence[Passage]
    patterns: Sequence[re.Pattern[str]]
    mode: ResearchModeName = "live"
    events: EventRecorder | None = None
    tool_log: ToolLog | None = None
    control: Drain | None = None
    budget_tokens: int = 16000
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], datetime] = utc_now
    reports: dict[str, str] = field(default_factory=dict)  # by job label, in memory only
    store: ResearchStore = field(init=False)
    _failure: str | None = field(default=None, init=False)
    _base: int = field(default=0, init=False)  # research.json's model-call count at node entry
    _made: int = field(default=0, init=False)  # this node's model calls
    _pass_job: str | None = field(default=None, init=False)  # the job a pass asks of

    def __post_init__(self) -> None:
        self.store = ResearchStore(self.run_dir / RESEARCH_FILE, self.mode)

    # --- discover_load --------------------------------------------------------------------------

    def load(self, topics: Sequence[str], failure: str | None = None) -> LoadOutcome:
        """The research pack the topics select, with no model call. `failure` is a live node's
        research failure, which makes the run `DEGRADED` whether or not a pack loads."""
        try:
            selection = select_pack(
                topics,
                self.config.packs_dir,
                min_matches=self.config.selection.min_keyword_matches,
            )
            if selection.path is None:
                self.store.note(selection.note or NO_PACK)
                return LoadOutcome(None, failure)
            pack = load_pack(selection.path, self.patterns, self.events, node="discover_load")
        except PackRefused as exc:
            reason = f"research: the research pack was refused: {exc}"
            self.store.note(reason)
            return LoadOutcome(None, f"{failure}; {reason}" if failure else reason)
        brief = self._pack_brief(pack)
        record = self.store.load()
        self.store.save(
            record.model_copy(update={"pack_id": pack.domain_id, "pack_sha256": pack.sha256})
        )
        write_atomic(self.run_dir / BRIEF_FILE, brief.model_dump_json(indent=1) + "\n")
        self._event(f"research pack {pack.domain_id} loaded", "discover_load")
        origin = f"the research pack `{pack.domain_id}`, version {pack.manifest.version}"
        view = domain_view(brief, origin, pack.excerpts, pack.sources)
        return LoadOutcome(brief, failure, view)

    def _pack_brief(self, pack: Pack) -> DomainBrief:
        brief, notes = settle_brief(
            _recorded_proposal(pack.domain_brief),
            pack.excerpts,
            pack.sources,
            mode="pack",
            domain_id=pack.domain_id,
            tier_rule=False,
        )
        if notes:
            self.store.note(*(f"pack {pack.domain_id}: {note}" for note in notes))
        return brief

    # --- discover_start -------------------------------------------------------------------------

    def start(self, topics: Sequence[str]) -> NodeOutcome:
        """One agent turn that starts the run's first job, or code's own start after one
        reminder."""
        record = self.store.load()
        if record.jobs:
            return NodeOutcome()  # a rerun after the job was written
        if not topics:
            return self._failed(NO_TOPICS)
        try:
            if not record.notebooks:
                notebook = self._research(lambda p: p.create_notebook(self.ctx.run_id))
                record = self.store.save(record.model_copy(update={"notebooks": [notebook]}))
            self._enter(record)
            gateway = self._gateway(record, [self._start_tool()], "discover_start")
            task = self._task(record, topics, None, "task")
            rendered = self.prompt.render(task.model_dump_json(), run_id=self.ctx.run_id)
            messages = list(rendered.messages)
            specs = [tool.spec for tool in gateway.specs()]
            transcript: list[Any] = []
            for turn, element in ((1, "task"), (2, "reminder")):
                if element == "reminder":
                    messages.append(Message("user", self.prompt.task_text("reminder")))
                completion = self._call(
                    task,
                    element,
                    messages,
                    specs,
                    "discover_start",
                    sha256_of([rendered.input_hash, transcript, turn]),
                )
                for call in completion.tool_calls:
                    self._tool(gateway, call, turn, transcript, messages)
                if self.store.load().jobs:
                    break
            else:
                question = cut(", ".join(topics), QUESTION_MAX_CHARS)
                own = ToolRequest(
                    tool="start_research",
                    args={"question": question, "topics": list(topics)},
                    agent=NODE,
                    turn=3,
                )
                result = gateway.call(own)
                self._raise_failure()
                if result.status != "OK":
                    raise _Failed(
                        f"research: code's own start_research was refused: {result.reason}"
                    )
            self._finish(gateway)
            return NodeOutcome()
        except _Failed as exc:
            return self._failed(str(exc))

    # --- discover_wait --------------------------------------------------------------------------

    def wait(self) -> NodeOutcome:
        """Poll the latest unfinished job until it ends, the wait cap passes, or a stop."""
        record = self.store.load()
        pending = [j for j in record.jobs if j.state in ("running", "timed_out")]
        if not pending:
            return NodeOutcome()
        try:
            self._wait_for(pending[-1])
            return NodeOutcome()
        except _Failed as exc:
            return self._failed(str(exc))

    def _wait_for(self, job: ResearchJob) -> None:
        if job.state == "timed_out":
            job = self._update(job.model_copy(update={"state": "running"}))
        cap = self.config.jobs.wait_minutes * 60
        budget = self.ctx.budget
        waited = 0.0
        while True:
            if self.control is not None and self.control.drain_requested:
                raise ResearchStopped(f"stopped by request while research job {job.label} ran")
            wait_s = min(POLL_WAIT_S, max(cap - waited, 0.0))
            budget.pause()
            began = self.clock()
            try:
                status = self._poll(job, wait_s)
            finally:
                elapsed = self.clock() - began
                budget.start()
            waited += elapsed
            job = job.model_copy(
                update={
                    "waited_seconds": job.waited_seconds + elapsed,
                    "task_id": status.task_id or job.task_id,
                }
            )
            if status.state == "completed":
                job = self._update(job.model_copy(update={"state": "completed"}))
                self.reports[job.label] = self._screen_report(job.label, status.report or "")
                self._import(job)
                self._bind(job)
                self._event(
                    f"research job {job.label} finished after {job.waited_seconds:.0f} s",
                    "discover_wait",
                )
                return
            if status.state == "failed":
                self._update(job.model_copy(update={"state": "failed"}))
                raise _Failed(f"research: job {job.label} failed")
            if waited >= cap:
                self._update(job.model_copy(update={"state": "timed_out"}))
                raise ResearchPending(
                    f"research job {job.label} still runs after {cap / 60:g} minutes of waiting"
                )
            job = self._update(job)
            rest = min(self.config.jobs.poll_seconds - elapsed, cap - waited)
            if rest > 0:
                budget.pause()
                try:
                    self.sleep(rest)
                finally:
                    budget.start()
                waited += rest
                job = self._update(
                    job.model_copy(update={"waited_seconds": job.waited_seconds + rest})
                )

    # --- discover_ask ---------------------------------------------------------------------------

    def ask(self, topics: Sequence[str]) -> NodeOutcome:
        """One pass of follow-up questions over the latest finished job's report."""
        try:
            return self._ask_pass(topics)
        except _Failed as exc:
            return self._failed(str(exc))

    def _ask_pass(self, topics: Sequence[str]) -> NodeOutcome:
        record = self.store.load()
        finished = [j for j in record.jobs if j.state == "completed"]
        if not finished:
            raise _Failed("research: no research job finished")
        latest = finished[-1]
        report = self._report(latest)
        self._bind(latest)
        record = self.store.load()
        self._enter(record)
        self._pass_job = latest.label
        tools = [self._ask_tool()]
        if _settled(record) < self.config.jobs.max_per_run:
            tools.append(self._start_tool())
        gateway = self._gateway(record, tools, "discover_ask")
        task = self._task(record, topics, report, "ask", pass_job=latest.label)
        rendered = self.prompt.render(task.model_dump_json(), run_id=self.ctx.run_id, task="ask")
        messages = list(rendered.messages)
        specs = [tool.spec for tool in gateway.specs()]
        transcript: list[Any] = []
        seen: set[str] = set()  # the excerpts this pass's answers returned
        limits = self.agent.limits
        second_job = False
        for turn in range(1, (limits.max_turns or 4) + 1):
            completion = self._call(
                task,
                "ask",
                messages,
                specs,
                "discover_ask",
                sha256_of([rendered.input_hash, transcript]),
            )
            if not completion.tool_calls:
                break
            progress = False
            for call in completion.tool_calls:
                result = self._tool(gateway, call, turn, transcript, messages)
                if call.name == "ask_research" and result.status == "OK":
                    returned = {e["id"] for e in result.data["excerpts"]}
                    progress = progress or bool(returned - seen)
                    seen |= returned
                # A start that leaves a job running, its own or, replayed, the one a crashed
                # run of this pass started, ends the pass at the turn the original ended it.
                started = call.name == "start_research" and result.status == "OK"
                if started and result.data.get("state") in ("running", "timed_out"):
                    second_job = True
            if second_job:
                break
            if limits.stop_on_no_progress and not progress:
                break
            if limits.max_tool_calls is not None and gateway.executed >= limits.max_tool_calls:
                break
        self._finish(gateway)
        return NodeOutcome(second_job=second_job)

    # --- discover_extract -----------------------------------------------------------------------

    def extract(self, topics: Sequence[str]) -> NodeOutcome:
        """One call over every finished job's report and the answers, as `domain_brief.json`."""
        try:
            record = self.store.load()
            finished = [j for j in reversed(record.jobs) if j.state == "completed"]
            if not finished:
                raise _Failed("research: no research job finished")
            reports = [self._report(job) for job in finished]
            record = self.store.load()
            self._enter(record)
            joined = "\n\n".join(report for report in reports if report)
            task = self._task(record, topics, joined or None, "extract")
            data = task.model_dump_json()
            rendered = self.prompt.render(data, run_id=self.ctx.run_id, task="extract")
            self._manifest(task, "extract")
            parsed, _ = self.ctx.structured(
                self.prompt,
                rendered.messages,
                DiscoveryExtract,
                node="discover_extract",
                input_hash=rendered.input_hash,
            )
            if not isinstance(parsed, DiscoveryExtract):
                raise _Failed("research: the extraction broke its schema twice")
            brief, notes = settle_brief(parsed, record.excerpts, record.sources, mode="live")
            if notes:
                self.store.note(*notes)
            write_atomic(self.run_dir / BRIEF_FILE, brief.model_dump_json(indent=1) + "\n")
            self._finish(None)
            done = sorted(job.label for job in finished)
            jobs = f"job {done[0]}" if len(done) == 1 else f"jobs {' and '.join(done)}"
            origin = f"this run's live research, {jobs}"
            view = domain_view(brief, origin, record.excerpts, record.sources)
            return NodeOutcome(view=view)
        except _Failed as exc:
            return self._failed(str(exc))

    # --- the two tools --------------------------------------------------------------------------

    @property
    def prompt(self) -> Any:
        return self.ctx.prompts[NODE]

    def query(self, question: str, topics: Sequence[str]) -> str:
        """The text `start_research` sends: the research envelope around the question."""
        return self.prompt.task_text("envelope", question=question, topics=", ".join(topics))

    def _sent(self, request: ToolRequest) -> str:
        """For the gateway's rules: the text a research tool would send."""
        if request.tool == "start_research":
            topics = request.args.get("topics") or []
            return self.query(str(request.args.get("question", "")), [str(t) for t in topics])
        return str(request.args.get("question", ""))

    def _start_tool(self) -> Tool:
        def run(args: StartResearchArgs) -> ToolResult:
            try:
                return self._start_job(args.question, list(args.topics))
            except _Failed as exc:
                self._failure = str(exc)
                raise

        return start_tool(run)

    def _start_job(self, question: str, topics: Sequence[str]) -> ToolResult:
        query = self.query(question, topics)
        digest = query_sha256(query)
        record = self.store.load()
        for job in record.jobs:
            if job.query_sha256 == digest:
                return ToolResult(status="OK", data={"job": job.label, "state": job.state})
        label = f"J{len(record.jobs) + 1}"
        if len(record.notebooks) > len(record.jobs):
            notebook = record.notebooks[len(record.jobs)]
        else:
            notebook = self._research(lambda p: p.create_notebook(f"{self.ctx.run_id} {label}"))
            record = self.store.save(
                record.model_copy(update={"notebooks": [*record.notebooks, notebook]})
            )
        task_id = self._research(lambda p: p.start(notebook, query))
        job = ResearchJob(
            label=label,
            notebook_id=notebook,
            task_id=task_id,
            query=query,
            query_sha256=digest,
            state="running",
            started=self.now(),
        )
        self.store.save(record.model_copy(update={"jobs": [*record.jobs, job]}))
        self._event(f"research job {label} started", "discover")
        return ToolResult(status="OK", data={"job": label, "state": "running"})

    def _ask_tool(self) -> Tool:
        discovery = self

        class Recorded:
            def ask(self, question: str) -> AskResult:
                try:
                    return discovery._answer(question)
                except _Failed as exc:
                    discovery._failure = str(exc)
                    raise

        return ask_tool(
            Recorded(),
            max_excerpts=self.config.questions.max_matches,
            empty_reason=NO_SOURCED_ANSWER,
        )

    def _answer(self, question: str) -> AskResult:
        """A recorded question from `research.json`, any other from the research provider,
        screened and recorded before it returns."""
        record = self.store.load()
        recorded = next((a for a in record.answers if a.question == question), None)
        if recorded is None:
            result = self._research(lambda p: p.ask(question))
            known = {e.id for e in record.excerpts}
            screened = screen(result.excerpts, self.patterns, self.events, node="discover_ask")
            fresh = [e for e in screened if e.id not in known]
            notes: list[str] = []
            text = _cut(result.answer or "", ANSWER_MAX_CHARS, f"the answer to {question!r}", notes)
            answer = PackAnswer(
                question=question,
                answer=text,
                excerpt_ids=[e.id for e in result.excerpts],
                job=self._pass_job,
            )
            [recorded] = screen([answer], self.patterns, self.events, node="discover_ask")
            sources = {s.id: s for s in record.sources}
            for source in result.sources:
                sources.setdefault(source.id, source)
            record = self.store.save(
                record.model_copy(
                    update={
                        "answers": [*record.answers, recorded],
                        "excerpts": [*record.excerpts, *fresh],
                        "sources": list(sources.values()),
                        "notes": [*record.notes, *(n for n in notes if n not in record.notes)],
                    }
                )
            )
        by_id = {e.id: e for e in record.excerpts}
        sources = {s.id: s for s in record.sources}
        excerpts = [
            by_id[i] for i in recorded.excerpt_ids if i in by_id and not by_id[i].quarantined
        ]
        used = dict.fromkeys(e.source_id for e in excerpts)
        return AskResult(
            answer=recorded.answer if recorded.answer and not recorded.quarantined else None,
            excerpts=excerpts,
            sources=[sources[s] for s in used if s in sources],
        )

    # --- shared ---------------------------------------------------------------------------------

    def _research[T](self, work: Callable[[ResearchProvider], T]) -> T:
        """One call on the research provider; its failure is a research failure."""
        if self.provider is None:
            raise _Failed("research: no research provider is configured")
        try:
            return work(self.provider)
        except FAILURES as exc:
            raise _Failed(f"research: {exc}") from exc

    def _raise_failure(self) -> None:
        if self._failure is not None:
            failure, self._failure = self._failure, None
            raise _Failed(failure)

    def _failed(self, reason: str) -> NodeOutcome:
        self.store.note(reason)
        self._event(reason, "discover")
        return NodeOutcome(failed=reason)

    def _event(self, detail: str, node: str) -> None:
        if self.events is not None:
            self.events.record("research", node, detail)

    def _update(self, job: ResearchJob) -> ResearchJob:
        record = self.store.load()
        jobs = [job if j.label == job.label else j for j in record.jobs]
        self.store.save(record.model_copy(update={"jobs": jobs}))
        return job

    def _poll(self, job: ResearchJob, wait_s: float) -> JobStatus:
        return self._research(lambda p: p.status(job.notebook_id, job.task_id, wait_s))

    def _import(self, job: ResearchJob) -> int:
        return self._research(lambda p: p.import_sources(job.notebook_id, job.task_id))

    def _bind(self, job: ResearchJob) -> None:
        record = self.store.load()
        sources, count = record.sources, len(record.excerpts)
        self._research(lambda p: p.bind(job.notebook_id, known=sources, excerpts=count))

    def _report(self, job: ResearchJob) -> str:
        """A finished job's report, screened: from memory, or from one poll on a resume, which
        also brings back the listing the research provider reads source URLs from."""
        if job.label not in self.reports:
            status = self._poll(job, 0)
            if status.state != "completed":
                raise _Failed(f"research: job {job.label}'s report could not be read again")
            if status.task_id and status.task_id != job.task_id:
                self._update(job.model_copy(update={"task_id": status.task_id}))
            self.reports[job.label] = self._screen_report(job.label, status.report or "")
        return self.reports[job.label]

    def _screen_report(self, label: str, report: str) -> str:
        """The report less each paragraph that reads like an instruction to a model."""
        kept: list[str] = []
        removed: list[str] = []
        for number, paragraph in enumerate(report.split("\n\n"), start=1):
            if suspect(paragraph, self.patterns):
                removed.append(str(number))
                if self.events is not None:
                    self.events.record(
                        "security",
                        NODE,
                        f"{label}'s report: paragraph {number} removed: it reads like an"
                        " instruction to a model",
                        ATTRIBUTION,
                    )
            else:
                kept.append(paragraph)
        if removed:
            self.store.note(
                f"{label}'s report: paragraphs {', '.join(removed)} removed: they read like"
                " instructions to a model"
            )
        return "\n\n".join(kept)

    def _task(
        self,
        record: ResearchRecord,
        topics: Sequence[str],
        report: str | None,
        element: str,
        *,
        pass_job: str | None = None,
    ) -> DiscoveryTask:
        """What the model sees: never a quarantined excerpt or answer, and the report cut at
        the last paragraph that fits the budget. A pass of `discover_ask` (`pass_job`) sees the
        research as it stood when the pass began: the answers of earlier passes and their
        excerpts, and the jobs that have ended. A rerun of a pass after a crash then builds the
        same request, though the crashed pass had already recorded answers or started a job."""
        sources = {s.id: s for s in record.sources}
        answers = [a for a in record.answers if pass_job is None or a.job != pass_job]
        cited = {i for a in answers for i in a.excerpt_ids}
        clean = [
            e
            for e in record.excerpts
            if not e.quarantined and e.source_id in sources and (pass_job is None or e.id in cited)
        ]
        ids = {e.id for e in clean}
        jobs = _settled(record) if pass_job is not None else len(record.jobs)
        task = DiscoveryTask(
            topics=list(topics),
            answers=[
                AnswerView(
                    question=a.question,
                    answer=a.answer,
                    excerpt_ids=[i for i in a.excerpt_ids if i in ids],
                )
                for a in answers
                if a.answer and not a.quarantined
            ],
            excerpts=[
                ExcerptView(
                    id=e.id,
                    source_title=sources[e.source_id].title,
                    tier=sources[e.source_id].tier,
                    text=e.text,
                )
                for e in clean
            ],
            questions_left=max(0, self.config.questions.max_per_run - len(answers)),
            jobs_left=max(0, self.config.jobs.max_per_run - jobs),
        )
        if not report:
            return task
        per_token = self.manager.limits.chars_per_token
        fixed = prompt_tokens(self.prompt, per_token, task=element)
        used = fixed.rules + fixed.examples + fixed.task
        used += estimate_tokens(len(task.model_dump_json()), per_token)
        return task.model_copy(
            update={"report": self._fit(report, (self.budget_tokens - used) * per_token)}
        )

    def _fit(self, report: str, room: int) -> str:
        paragraphs = report.split("\n\n")
        kept: list[str] = []
        size = 0
        for paragraph in paragraphs:
            added = len(paragraph) + (2 if kept else 0)
            if size + added > room:
                break
            kept.append(paragraph)
            size += added
        if len(kept) < len(paragraphs):
            self.store.note(
                f"the reports were cut to {len(kept)} of {len(paragraphs)} paragraphs to fit"
                " the budget"
            )
        return "\n\n".join(kept)

    def _enter(self, record: ResearchRecord) -> None:
        self._base, self._made, self._failure = record.calls, 0, None

    def _manifest(self, task: DiscoveryTask, element: str) -> None:
        """The context manifest of the node's next model call, `D` ids across the nodes."""
        per_token = self.manager.limits.chars_per_token
        self.manager.record_manifest(
            NODE,
            f"D{self._base + self._made + 1:02d}",
            [e.id for e in task.excerpts],
            [],
            prompt_tokens(self.prompt, per_token, task=element),
            estimate_tokens(len(task.model_dump_json()), per_token),
            self.budget_tokens,
        )
        self._made += 1

    def _call(
        self,
        task: DiscoveryTask,
        element: str,
        messages: list[Message],
        specs: Sequence[Any],
        node: str,
        input_hash: str,
    ) -> Completion:
        self._manifest(task, element)
        completion = self.ctx.call(
            self.prompt, messages, None, node=node, tools=specs, input_hash=input_hash
        )
        messages.append(completion.as_message())
        return completion

    def _tool(
        self,
        gateway: ToolGateway,
        call: ToolCall,
        turn: int,
        transcript: list[Any],
        messages: list[Message],
    ) -> ToolResult:
        request = ToolRequest(tool=call.name, args=call.arguments, agent=NODE, turn=turn)
        attributes = {SpanAttributes.TOOL_NAME: call.name, "bidwright.turn": turn}
        with self.ctx.span(
            f"tool.{call.name}", OpenInferenceSpanKindValues.TOOL, **attributes
        ) as span:
            result = gateway.call(request)
            set_attribute(span, "bidwright.tool_status", result.status)
        transcript.append([call.name, call.arguments, result.model_dump()])
        messages.append(
            Message("tool", result.model_dump_json(), tool_call_id=call.id, name=call.name)
        )
        self._raise_failure()
        return result

    def _gateway(self, record: ResearchRecord, tools: Sequence[Tool], node: str) -> ToolGateway:
        connect = getattr(self.provider, "connect", None)
        pinned = bool(self._research(lambda _: connect())) if callable(connect) else True
        context = RuleContext(
            self.passages,
            view=self.ctx.view,
            research=self.store.load,
            server=RESEARCH_DESTINATION if callable(connect) else None,
            pinned=pinned,
            events=self.events,
            node=node,
            query_for=self._sent,
            max_shared_words=self.config.outbound.max_shared_words,
            max_jobs=self.config.jobs.max_per_run,
            max_questions=self.config.questions.max_per_run,
        )
        return ToolGateway.for_agent(
            NODE,
            allowed=self.agent.tools,
            tools=tools,
            max_tool_calls=self.agent.limits.max_tool_calls or 8,
            executed=record.tool_calls,
            context=context,
            log=self.tool_log,
        )

    def _finish(self, gateway: ToolGateway | None) -> None:
        """The node's counts, written once it ends."""
        record = self.store.load()
        update: dict[str, int] = {"calls": self._base + self._made}
        if gateway is not None:
            update["tool_calls"] = gateway.executed
        self.store.save(record.model_copy(update=update))
        self._made = 0


__all__ = [
    "BRIEF_FILE",
    "domain_view",
    "NO_TOPICS",
    "RESEARCH_FILE",
    "Discovery",
    "LoadOutcome",
    "NodeOutcome",
    "ResearchPending",
    "ResearchStopped",
    "ResearchStore",
    "settle_brief",
]
