"""`discover` (Iteration 2, steps 11 and 12): the five research nodes, called directly, against
the fake NotebookLM server over HTTP through `NotebookLMProvider`, with scripted model turns;
then whole live-research runs through `execute`, with the rule backend as the model: a wait
and its resume, a crash after `discover_start`, a resume at `discover_ask`, and an open breaker
on the server."""

import json
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from bidwright.candidates import cut
from bidwright.config import Config, ResearchConfig, ServerPins, compile_patterns, load_config
from bidwright.graph.build import RunResult, execute
from bidwright.graph.discover import (
    BRIEF_FILE,
    RESEARCH_FILE,
    Discovery,
    ResearchPending,
    ResearchStopped,
)
from bidwright.harness.budget import RunBudget
from bidwright.harness.context import ContextManager
from bidwright.harness.gateway import ToolLog
from bidwright.harness.recovery import CircuitBreaker, server_key
from bidwright.harness.rules import query_sha256
from bidwright.ingest import display_text
from bidwright.llm.types import Request, Response
from bidwright.obs.events import EventRecorder, read_events
from bidwright.research.audit import query_overlaps
from bidwright.research.mcp_client import McpClient
from bidwright.research.nlm import SENT, NotebookLMProvider
from bidwright.research.pins import pinned
from bidwright.research.provider import ResearchProvider
from bidwright.schemas import (
    DomainBrief,
    JobStatus,
    PackAnswer,
    PackExcerpt,
    PackSource,
    ResearchJob,
    ResearchRecord,
    RunManifest,
)
from tests.mcp_fakes import INJECTED, WCAG, WCAG_URL, http_server, serving
from tests.node_fakes import (
    DEV_RFP,
    USAGE,
    Reply,
    RuleBackend,
    ScriptBackend,
    context,
    data_of,
    dev_ingest,
    text,
    tools,
)

CONFIG = load_config()
AGENT = CONFIG.agents.agents["discover"]
PATTERNS = compile_patterns(CONFIG.ingest.suspect_patterns, "config/ingest.yaml")
PACKS = Path(__file__).resolve().parent / "data" / "packs"
# Topics that select no pack of tests/data/packs, and topics that select its fixture.
TOPICS = ["accessible online forms", "council casework services"]
PACK_TOPICS = ["records management in councils", "retention schedules for digital records"]
QUESTION = "What do councils need from a service for casework and online forms?"
FOLLOW_UP = "Which accessibility standard applies to the online forms of public bodies?"
SECOND = "Which pitfalls do councils meet when they move casework online?"
DONE = "The research covers what the brief needs."
EXTRACTION = text(
    {
        "summary": "Public bodies follow WCAG 2.2 for their online forms.",
        "items": [
            {
                "kind": "standard",
                "statement": "Online forms meet WCAG 2.2 at level AA.",
                "excerpt_ids": ["PX-0001"],
            }
        ],
        "needs": [{"need": "Accessible online forms for residents", "excerpt_ids": ["PX-0001"]}],
        "open_questions": [],
    }
)


def _start(question: str = QUESTION, *more: str) -> Response:
    calls = [("start_research", {"question": q, "topics": TOPICS}) for q in (question, *more)]
    return tools(*calls)


def _asking(question: str = FOLLOW_UP) -> Response:
    return tools(("ask_research", {"question": question}))


@pytest.fixture(scope="module")
def fake_url() -> Iterator[str]:
    with serving() as url:
        yield url


def _counts(url: str) -> dict[str, int]:
    payload = McpClient("notebooklm", http_server(url)).call("fake_counts", {})
    return {name: int(count) for name, count in payload.items() if name != "status"}


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class TimedProvider(NotebookLMProvider):
    """Each poll takes its whole wait on the fake clock."""

    clock: FakeClock

    def status(self, notebook_id: str, task_id: str, wait_s: float) -> JobStatus:
        self.clock.now += wait_s
        return super().status(notebook_id, task_id, wait_s)


def _provider[P: NotebookLMProvider](
    url: str, pins: ServerPins | None = None, kind: type[P] = NotebookLMProvider
) -> P:
    client = McpClient("notebooklm", http_server(url))
    if pins is None:
        reported, listed = client.list_tools()
        pins = pinned(client.name, reported, listed, SENT, "notebooklm-mcp-cli==0.15.8")
    return kind(
        client,
        pins,
        CONFIG.research.tiers,
        CONFIG.research.jobs,
        today=lambda: date(2026, 11, 5),
    )


def _research(**jobs: Any) -> ResearchConfig:
    return CONFIG.research.model_copy(
        update={"packs_dir": str(PACKS), "jobs": CONFIG.research.jobs.model_copy(update=jobs)}
    )


def _discovery(
    run_dir: Path,
    replies: Sequence[Reply],
    provider: ResearchProvider | None,
    **extra: Any,
) -> tuple[Discovery, ScriptBackend]:
    backend = ScriptBackend(list(replies))
    passages = dev_ingest().passages
    settings: dict[str, Any] = {
        "config": _research(),
        "events": EventRecorder(run_dir / "events.jsonl"),
        "tool_log": ToolLog(run_dir / "tool_calls.jsonl"),
        "budget_tokens": CONFIG.limits.context.budgets["discover"],
        "sleep": lambda seconds: None,
    } | extra
    discovery = Discovery(
        ctx=context(backend),
        provider=provider,
        agent=AGENT,
        run_dir=run_dir,
        manager=ContextManager(run_dir, CONFIG.limits.context, passages),
        passages=passages,
        patterns=PATTERNS,
        **settings,
    )
    return discovery, backend


def _record(run_dir: Path) -> ResearchRecord:
    return ResearchRecord.model_validate_json((run_dir / RESEARCH_FILE).read_text(encoding="utf-8"))


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _first_ready(
    run_dir: Path, url: str, replies: Sequence[Reply] = ()
) -> tuple[Discovery, ScriptBackend]:
    """A run whose first job has started and finished; its backend's first request is the
    start turn's."""
    discovery, backend = _discovery(run_dir, [_start(), *replies], _provider(url))
    assert discovery.start(TOPICS).failed is None
    assert discovery.wait().failed is None
    return discovery, backend


def test_a_live_discovery_runs_end_to_end_and_writes_both_files(
    tmp_path: Path, fake_url: str
) -> None:
    before = _counts(fake_url)
    discovery, backend = _discovery(
        tmp_path, [_start(), _asking(), DONE, EXTRACTION], _provider(fake_url)
    )
    assert discovery.start(TOPICS).failed is None
    assert discovery.wait().failed is None
    asked = discovery.ask(TOPICS)
    assert asked.failed is None and not asked.second_job
    assert discovery.extract(TOPICS).failed is None
    assert backend.replies == []

    first = data_of(backend.requests[0])
    assert first["topics"] == TOPICS and first["report"] is None, "the model sees only topics"
    record = _record(tmp_path)
    [job] = record.jobs
    assert (job.label, job.state, job.task_id.endswith("-final")) == ("J1", "completed", True)
    assert QUESTION in job.query and job.query.startswith("Research objective")
    assert [(a.question, a.job) for a in record.answers] == [(FOLLOW_UP, "J1")]
    assert [(s.id, s.title, s.url, s.tier) for s in record.sources] == [
        ("PS-001", WCAG, WCAG_URL, 1)
    ], "the reference to a source with no URL never became a source"
    assert [e.id for e in record.excerpts] == ["PX-0001"]
    assert (record.tool_calls, record.calls) == (2, 4)
    brief = DomainBrief.model_validate_json((tmp_path / BRIEF_FILE).read_text(encoding="utf-8"))
    assert brief.mode == "live" and brief.evidence_class == "EXTERNAL_RESEARCH"
    assert [(i.id, i.excerpt_ids) for i in brief.items] == [("DI-001", ["PX-0001"])]
    assert [(n.id, n.need) for n in brief.needs] == [
        ("DN-001", "Accessible online forms for residents")
    ]
    manifests = sorted(p.name for p in (tmp_path / "context").glob("discover-*.json"))
    assert manifests == [f"discover-D0{n}.json" for n in range(1, 5)]
    extract_manifest = json.loads((tmp_path / "context" / "discover-D04.json").read_text("utf-8"))
    assert extract_manifest["included_record_ids"] == ["PX-0001"]
    nodes = [entry.node for entry in discovery.ctx.ledger]
    assert nodes == ["discover_start", "discover_ask", "discover_ask", "discover_extract"]
    after = _counts(fake_url)
    assert after["research_start"] - before["research_start"] == 1
    assert after["notebook_query"] - before["notebook_query"] == 1


def test_a_second_discover_start_starts_no_second_job(tmp_path: Path, fake_url: str) -> None:
    before = _counts(fake_url)
    first, _ = _discovery(tmp_path, [_start()], _provider(fake_url))
    assert first.start(TOPICS).failed is None
    again, backend = _discovery(tmp_path, [], _provider(fake_url))
    assert again.start(TOPICS).failed is None and backend.requests == []
    after = _counts(fake_url)
    assert after["research_start"] - before["research_start"] == 1
    assert after["notebook_create"] - before["notebook_create"] == 1
    assert [j.label for j in _record(tmp_path).jobs] == ["J1"]


def test_a_rerun_discover_ask_gets_j2s_label_and_starts_nothing(
    tmp_path: Path, fake_url: str
) -> None:
    discovery, first = _first_ready(tmp_path, fake_url, [_start(SECOND)])
    assert discovery.ask(TOPICS).second_job, "a second job ends the pass"
    before = _counts(fake_url)
    rerun, backend = _discovery(tmp_path, [_start(SECOND)], _provider(fake_url))
    outcome = rerun.ask(TOPICS)
    assert outcome.second_job and outcome.failed is None
    after = _counts(fake_url)
    assert after["research_start"] == before["research_start"], "no second research_start"
    assert after["notebook_create"] == before["notebook_create"]
    starts = [r for r in _rows(tmp_path / "tool_calls.jsonl") if r["tool"] == "start_research"]
    assert [(r["status"], r["data"]) for r in starts[-2:]] == [
        ("OK", {"job": "J2", "state": "running"}),
        ("OK", {"job": "J2", "state": "running"}),
    ]
    assert [j.label for j in _record(tmp_path).jobs] == ["J1", "J2"]
    [request] = backend.requests
    assert {tool.name for tool in request.tools or ()} == {"ask_research", "start_research"}
    assert data_of(request) == data_of(first.requests[1]), "the pass's request as it first was"
    assert data_of(request)["jobs_left"] == 1


def test_a_second_start_in_one_turn_is_denied(tmp_path: Path, fake_url: str) -> None:
    before = _counts(fake_url)
    discovery, _ = _discovery(tmp_path, [_start(QUESTION, SECOND)], _provider(fake_url))
    assert discovery.start(TOPICS).failed is None
    rows = _rows(tmp_path / "tool_calls.jsonl")
    assert [(r["status"], r["reason"]) for r in rows] == [
        ("OK", None),
        ("DENIED", "one job a turn"),
    ]
    assert [j.label for j in _record(tmp_path).jobs] == ["J1"]
    assert _counts(fake_url)["research_start"] - before["research_start"] == 1


def test_a_copied_passage_is_denied_before_the_server_sees_it(
    tmp_path: Path, fake_url: str
) -> None:
    passage = next(p for p in dev_ingest().passages if p.id == "SRC-0015")
    copied = cut(display_text(passage.text), 250)
    before = _counts(fake_url)
    discovery, _ = _discovery(tmp_path, [_start(copied), _start()], _provider(fake_url))
    assert discovery.start(TOPICS).failed is None
    rows = _rows(tmp_path / "tool_calls.jsonl")
    assert [r["status"] for r in rows] == ["DENIED", "OK"], "the reminder turn starts the job"
    assert "research queries never carry RFP text" in rows[0]["reason"]
    [job] = _record(tmp_path).jobs
    assert copied not in job.query and QUESTION in job.query
    assert _counts(fake_url)["research_start"] - before["research_start"] == 1
    security = [e for e in read_events(tmp_path / "events.jsonl") if e.kind == "security"]
    assert [(e.node, e.attribution) for e in security] == [("discover_start", "indeterminate")]


def test_discover_wait_pauses_the_budget_around_each_poll(tmp_path: Path, fake_url: str) -> None:
    clock = FakeClock()
    provider = _provider(fake_url, kind=TimedProvider)
    provider.clock = clock
    discovery, _ = _discovery(tmp_path, [_start()], provider, clock=clock, sleep=clock.sleep)
    assert discovery.start(TOPICS).failed is None
    budget = RunBudget(CONFIG.limits.run("dev", "free"), clock=clock)
    discovery.ctx.budget = budget
    budget.start()
    assert discovery.wait().failed is None
    [job] = _record(tmp_path).jobs
    assert (job.state, job.waited_seconds, clock.now) == ("completed", 60.0, 60.0)
    assert budget.active_seconds == 0.0, "two polls of 30 seconds, none of it active time"


def test_discover_wait_times_out_and_a_resume_finishes_the_job(
    tmp_path: Path, fake_url: str
) -> None:
    clock = FakeClock()
    capped = _research(wait_minutes=0.5)
    provider = _provider(fake_url, kind=TimedProvider)
    provider.clock = clock
    discovery, _ = _discovery(
        tmp_path, [_start()], provider, config=capped, clock=clock, sleep=clock.sleep
    )
    assert discovery.start(TOPICS).failed is None
    with pytest.raises(ResearchPending, match="J1 still runs after 0.5 minutes"):
        discovery.wait()
    assert _record(tmp_path).jobs[0].state == "timed_out"
    again = _provider(fake_url, kind=TimedProvider)
    again.clock = clock
    resumed, _ = _discovery(tmp_path, [], again, config=capped, clock=clock, sleep=clock.sleep)
    assert resumed.wait().failed is None
    assert _record(tmp_path).jobs[0].state == "completed", "a fresh wait cap on the resume"


class Drained:
    drain_requested = True


def test_discover_wait_stops_once_a_drain_is_requested(tmp_path: Path, fake_url: str) -> None:
    discovery, _ = _discovery(tmp_path, [_start()], _provider(fake_url), control=Drained())
    assert discovery.start(TOPICS).failed is None
    with pytest.raises(ResearchStopped, match="while research job J1 ran"):
        discovery.wait()
    assert _record(tmp_path).jobs[0].state == "running"


def test_discover_fallback(tmp_path: Path, fake_url: str) -> None:
    """A refused server falls back to the matching research pack, and the run is degraded; a
    failed job (`no_research`) with no matching pack continues without research."""
    refused, backend = _discovery(tmp_path / "refused", [], _provider(fake_url, ServerPins()))
    failed = refused.start(PACK_TOPICS).failed
    assert failed is not None and failed.startswith("research: ") and backend.requests == []
    loaded = refused.load(PACK_TOPICS, failed)
    assert loaded.degraded == failed and loaded.domain_brief is not None
    brief = DomainBrief.model_validate_json(
        (tmp_path / "refused" / BRIEF_FILE).read_text(encoding="utf-8")
    )
    assert (brief.domain_id, brief.mode, len(brief.items), len(brief.needs)) == (
        "fixture-records-management",
        "pack",
        2,
        1,
    )
    record = _record(tmp_path / "refused")
    assert record.pack_id == "fixture-records-management" and failed in record.notes

    nothing = "What does nothing in council casework services cost residents?"
    empty, _ = _discovery(tmp_path / "empty", [_start(nothing)], _provider(fake_url))
    assert empty.start(TOPICS).failed is None
    reason = empty.wait().failed
    assert reason == "research: job J1 failed"
    assert _record(tmp_path / "empty").jobs[0].state == "failed"
    alone = empty.load(TOPICS, reason)
    assert (alone.domain_brief, alone.degraded) == (None, reason)
    assert not (tmp_path / "empty" / BRIEF_FILE).exists()
    assert "no pack for this domain" in _record(tmp_path / "empty").notes


def test_a_resumed_discover_ask_answers_a_recorded_question_from_the_file(
    tmp_path: Path, fake_url: str
) -> None:
    discovery, first = _first_ready(tmp_path, fake_url, [_asking(), DONE])
    assert discovery.ask(TOPICS).failed is None
    first_request = data_of(first.requests[1])
    before = _counts(fake_url)
    rerun, backend = _discovery(tmp_path, [_asking(), DONE], _provider(fake_url))
    assert rerun.ask(TOPICS).failed is None
    assert _counts(fake_url)["notebook_query"] == before["notebook_query"], "sent to no server"
    asks = [r for r in _rows(tmp_path / "tool_calls.jsonl") if r["tool"] == "ask_research"]
    assert len(asks) == 2 and asks[0]["data"] == asks[1]["data"]
    assert data_of(backend.requests[0]) == first_request, "the same request as before the stop"
    assert [a.question for a in _record(tmp_path).answers] == [FOLLOW_UP]


def test_a_suspect_report_paragraph_is_removed_from_what_the_model_sees(
    tmp_path: Path, fake_url: str
) -> None:
    question = "How do councils keep injected content out of their online forms?"
    discovery, backend = _discovery(tmp_path, [_start(question), DONE], _provider(fake_url))
    assert discovery.start(TOPICS).failed is None
    assert discovery.wait().failed is None
    assert discovery.ask(TOPICS).failed is None
    report = data_of(backend.requests[-1])["report"]
    assert "Accessible forms matter" in report and INJECTED not in report
    security = [e for e in read_events(tmp_path / "events.jsonl") if e.kind == "security"]
    assert [(e.detail, e.attribution) for e in security] == [
        (
            "J1's report: paragraph 3 removed: it reads like an instruction to a model",
            "injection-dominant",
        )
    ]
    assert any(
        note.startswith("J1's report: paragraphs 3 removed") for note in _record(tmp_path).notes
    )


def test_research_mode_pack_makes_no_model_call(tmp_path: Path) -> None:
    discovery, backend = _discovery(tmp_path, [], None, mode="pack")
    loaded = discovery.load(PACK_TOPICS)
    assert backend.requests == [] and loaded.degraded is None
    assert loaded.domain_brief is not None and loaded.domain_brief.mode == "pack"
    record = _record(tmp_path)
    assert (record.mode, record.pack_id) == ("pack", "fixture-records-management")
    assert record.pack_sha256 is not None and record.pack_sha256.startswith("sha256:")
    unmatched, _ = _discovery(tmp_path / "unmatched", [], None, mode="pack")
    assert unmatched.load(TOPICS) == type(loaded)(None, None), "no pack is not a shortfall"
    assert _record(tmp_path / "unmatched").notes == ["no pack for this domain"]


def test_an_item_on_tier_4_excerpts_only_is_dropped(tmp_path: Path) -> None:
    sources = [
        PackSource(
            id="PS-001",
            provider_source_id="a",
            url=WCAG_URL,
            title=WCAG,
            host="www.w3.org",
            tier=1,
            retrieved=date(2026, 11, 5),
        ),
        PackSource(
            id="PS-002",
            provider_source_id="b",
            url="https://notes.example.net/forms",
            title="Notes on forms",
            host="notes.example.net",
            tier=4,
            retrieved=date(2026, 11, 5),
        ),
    ]
    excerpts = [
        PackExcerpt(id="PX-0001", source_id="PS-001", text="Success criteria are testable."),
        PackExcerpt(id="PX-0002", source_id="PS-002", text="Forms break on old phones."),
    ]
    query = "Research objective: forms"
    job = ResearchJob(
        label="J1",
        notebook_id="nb",
        task_id="t",
        query=query,
        query_sha256=query_sha256(query),
        state="completed",
        started=datetime(2026, 11, 5, tzinfo=UTC),
    )
    record = ResearchRecord(mode="live", jobs=[job], sources=sources, excerpts=excerpts)
    (tmp_path / RESEARCH_FILE).write_text(record.model_dump_json(), encoding="utf-8")
    reply = text(
        {
            "summary": "Forms meet WCAG.",
            "items": [
                {
                    "kind": "standard",
                    "statement": "Forms meet WCAG 2.2.",
                    "excerpt_ids": ["PX-0001"],
                },
                {
                    "kind": "pitfall",
                    "statement": "Forms break on old phones.",
                    "excerpt_ids": ["PX-0002"],
                },
                {
                    "kind": "pattern",
                    "statement": "Test with residents.",
                    "excerpt_ids": ["PX-0009"],
                },
            ],
            "needs": [{"need": "Forms that work on old phones", "excerpt_ids": ["PX-0002"]}],
            "open_questions": [],
        }
    )
    discovery, _ = _discovery(tmp_path, [reply], None, reports={"J1": "# Forms"})
    assert discovery.extract(TOPICS).failed is None
    brief = DomainBrief.model_validate_json((tmp_path / BRIEF_FILE).read_text(encoding="utf-8"))
    assert [(i.id, i.kind, i.excerpt_ids) for i in brief.items] == [
        ("DI-001", "standard", ["PX-0001"])
    ]
    assert brief.needs == []
    notes = _record(tmp_path).notes
    assert (
        "pitfall 'Forms break on old phones.' dropped: its excerpts all come from tier-4 sources"
        in notes
    )
    assert "pattern 'Test with residents.' cited unknown or quarantined excerpts: PX-0009" in notes
    assert (
        "need 'Forms that work on old phones' dropped: its excerpts all come from tier-4 sources"
        in notes
    )


def test_query_overlaps_finds_a_planted_copy(tmp_path: Path) -> None:
    passages = dev_ingest().passages
    (tmp_path / "passages.jsonl").write_text(
        "".join(p.model_dump_json() + "\n" for p in passages), encoding="utf-8"
    )
    planted = next(p for p in passages if p.id == "SRC-0015")
    copied = cut(display_text(planted.text), 120)
    query = f"Research objective: {copied}"
    job = ResearchJob(
        label="J1",
        notebook_id="nb",
        task_id="t",
        query=query,
        query_sha256=query_sha256(query),
        state="completed",
        started=datetime(2026, 11, 5, tzinfo=UTC),
    )
    answers = [PackAnswer(question=FOLLOW_UP, answer="", job="J1")]
    record = ResearchRecord(mode="live", jobs=[job], answers=answers)
    (tmp_path / RESEARCH_FILE).write_text(record.model_dump_json(), encoding="utf-8")
    planted_query, question = query_overlaps(tmp_path)
    assert (planted_query.kind, planted_query.label, planted_query.src_id) == (
        "query",
        "J1",
        "SRC-0015",
    )
    assert planted_query.shared >= 8, planted_query
    assert (question.kind, question.label) == ("question", "Q1") and question.shared < 8


# --- whole runs through execute (step 12) -----------------------------------------------------


def _config(**jobs: Any) -> Config:
    """The configuration with research packs from tests/data/packs and the jobs changed."""
    config = load_config()
    research = config.research.model_copy(
        update={"packs_dir": str(PACKS), "jobs": config.research.jobs.model_copy(update=jobs)}
    )
    return config.model_copy(update={"research": research})


def _live(
    outputs: Path,
    provider: ResearchProvider,
    run_id: str,
    model: Any = None,
    *,
    config: Config | None = None,
    resume: bool = False,
) -> RunResult:
    """The development PDF in research mode live, with the rule backend as the model."""
    return execute(
        docling_mode="replay",
        source=DEV_RFP,
        profile="free",
        outputs=outputs,
        backends={"gemini": model or RuleBackend()},
        run_id=run_id,
        research="live",
        provider=provider,
        config=config or _config(poll_seconds=0.01),
        resume=resume,
    )


def _manifest(run_dir: Path) -> RunManifest:
    return RunManifest.model_validate_json((run_dir / "run_manifest.json").read_text("utf-8"))


def test_a_live_run_waits_for_research_and_a_resume_completes_it(
    tmp_path: Path, fake_url: str
) -> None:
    capped = _config(wait_minutes=0.0005, poll_seconds=0.01)  # a cap of 30 milliseconds
    waiting = _live(tmp_path, _provider(fake_url), "waiting", config=capped)
    assert waiting.status == "WAITING_RESEARCH", waiting.reason
    assert "J1 still runs after" in (waiting.reason or "")
    assert _record(waiting.run_dir).jobs[0].state == "timed_out"
    resumed = _live(tmp_path, _provider(fake_url), "waiting", config=capped, resume=True)
    assert resumed.status == "COMPLETED", resumed.reason
    record = _record(resumed.run_dir)
    assert record.jobs[0].state == "completed" and len(record.answers) == 1
    summary = (resumed.run_dir / "solution_summary.md").read_text(encoding="utf-8")
    assert "## Appendix: domain research (external, unverified)" in summary
    assert "From this run's live research, job J1." in summary
    assert f"Sources: {WCAG} (tier 1)." in summary
    manifest = _manifest(resumed.run_dir)
    assert manifest.research is not None
    assert (manifest.research.mode, manifest.research.jobs) == ("live", 1)
    assert [change.status for change in manifest.status_history] == [
        "RUNNING",
        "WAITING_RESEARCH",
        "RUNNING",
        "COMPLETED",
    ]


class CrashOnPoll(NotebookLMProvider):
    """The crash the design names: a KeyboardInterrupt from the next server call, the poll."""

    def status(self, notebook_id: str, task_id: str, wait_s: float) -> JobStatus:
        raise KeyboardInterrupt


def test_a_crash_after_discover_start_resumes_without_a_second_job(
    tmp_path: Path, fake_url: str
) -> None:
    before = _counts(fake_url)
    with pytest.raises(KeyboardInterrupt):
        _live(tmp_path, _provider(fake_url, kind=CrashOnPoll), "crashed")
    assert _manifest(tmp_path / "crashed").status == "STOPPED"
    resumed = _live(tmp_path, _provider(fake_url), "crashed", resume=True)
    assert resumed.status == "COMPLETED", resumed.reason
    after = _counts(fake_url)
    assert after["research_start"] - before["research_start"] == 1, "no second job"
    assert after["notebook_create"] - before["notebook_create"] == 1
    assert [j.label for j in _record(resumed.run_dir).jobs] == ["J1"]


class CopiesThenAsks(RuleBackend):
    """In `discover_ask`, one turn with a question that copies an RFP passage and a clean one,
    then done: a turn of the copied question alone would add no excerpt and end the pass."""

    def __init__(self, copied: str) -> None:
        super().__init__()
        self.copied = copied

    def call(self, request: Request) -> Response:
        names = {tool.name for tool in request.tools or ()}
        if "ask_research" not in names:
            return super().call(request)
        self.requests.append(request)
        if not any(message.role == "tool" for message in request.messages):
            return tools(
                ("ask_research", {"question": self.copied}),
                ("ask_research", {"question": FOLLOW_UP}),
            )
        return Response(text=DONE, usage=USAGE)


class CrashOnAsk(NotebookLMProvider):
    def ask(self, question: str) -> Any:
        raise KeyboardInterrupt


def test_a_resume_at_discover_ask_still_denies_a_copied_passage(
    tmp_path: Path, fake_url: str
) -> None:
    passage = next(p for p in dev_ingest().passages if p.id == "SRC-0015")
    copied = cut(display_text(passage.text), 250)
    with pytest.raises(KeyboardInterrupt):
        _live(tmp_path, _provider(fake_url, kind=CrashOnAsk), "asking", CopiesThenAsks(copied))
    resumed = _live(tmp_path, _provider(fake_url), "asking", CopiesThenAsks(copied), resume=True)
    assert resumed.status == "COMPLETED", resumed.reason
    asks = [r for r in _rows(resumed.run_dir / "tool_calls.jsonl") if r["tool"] == "ask_research"]
    copies = [r for r in asks if r["args"]["question"] == copied]
    assert [(r["status"], r["part"]) for r in copies] == [("DENIED", 0), ("DENIED", 1)]
    assert all("never carry RFP text" in r["reason"] for r in copies)
    assert [a.question for a in _record(resumed.run_dir).answers] == [FOLLOW_UP]


def test_an_open_breaker_on_the_server_sends_the_run_to_discover_load(
    tmp_path: Path, fake_url: str
) -> None:
    breaker = CircuitBreaker(CONFIG.limits.breaker, root=tmp_path / "breaker")
    for _ in range(CONFIG.limits.breaker.failures):
        breaker.failure(server_key("notebooklm"))
    pins = _provider(fake_url).pins
    client = McpClient("notebooklm", http_server(fake_url), breaker=breaker)
    provider = NotebookLMProvider(client, pins, CONFIG.research.tiers, CONFIG.research.jobs)
    result = _live(tmp_path, provider, "broken")
    assert result.status == "DEGRADED"
    assert (result.reason or "").startswith("research: "), result.reason
    record = _record(result.run_dir)
    assert record.jobs == [] and "no pack for this domain" in record.notes
    assert not (result.run_dir / BRIEF_FILE).exists(), "no research, so no domain brief"
