"""Wire the nodes into a LangGraph graph, and run one RFP file or package through it.

guard -> ingest -> candidates -> triage -> pack -> extract (one `Send` per context pack, at most
`concurrency` at once) -> verify -> coverage -> lint -> consolidate (one `Send` per cluster the
model step takes) -> brief -> research -> approach -> risk -> draft -> render (Iteration 1,
section 4.1 of its design; `brief` and the research nodes from Iteration 2, section 4.1 of
its design). Research mode `off` goes from `brief` to `approach`; `pack` goes through
`discover_load`; `live` goes through `discover_start`, `discover_wait`, `discover_ask` and
`discover_extract`, and a research failure in any of them goes to `discover_load`.

`guard` checks and scans the files before any parser reads them, and a refusal ends the run
`POLICY_BLOCKED`. `ingest` parses each accepted file with its parser, Docling or pdfplumber,
through the control register. `--baseline b0` routes `candidates` to `b0`, which makes no model
call, and stops after `verify`; `until` stops a run after `verify`, `coverage`, `consolidate`
or `brief`. `coverage` either stops, or sends the passages still without a disposition back to
`extract` as gap packs, and `verify` runs again over every outcome.

The SQLite checkpointer keeps each step's state in the run folder. The LLM client, budget,
prompts and search index stay outside the state, in `Runtime`, so a checkpoint holds plain data
only. Each node writes its own files; `render` writes the summary, the proposal pack files and
the manifest. The run's `ledger.jsonl` gains each entry as its call finishes, and a live run's
answers go to its journal (ADR-031), so a killed run keeps both.

Before the run folder exists, `execute` checks the run's outbound channels against the egress
register (D-05): the backends of the profile's providers, which are the only backends the client
gets, the trace endpoint, whose refusal sends spans to `spans.jsonl` and is recorded in the
manifest, and the Docling service when the run parses with it. Live and recorded runs get the
limiter for the profile's tier, and live runs the response cache when asked.
"""

import hashlib
import json
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.errors import EmptyInputError, GraphDrained
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import RunControl
from langgraph.types import Command, Send
from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes
from opentelemetry import trace as otel_trace

from bidwright.baselines import BASELINES, b0_outcome
from bidwright.candidates import CompiledCues, cue_hits, defined_terms, write_candidates
from bidwright.clusters import Cluster, build_clusters, precedence_passages
from bidwright.config import (
    Config,
    ResearchConfig,
    compile_patterns,
    load_bid_policy,
    load_config,
)
from bidwright.coverage import degraded_reason, next_step, write_report
from bidwright.fileio import repair_lines
from bidwright.graph import solution as sol
from bidwright.graph.brief import brief as write_brief
from bidwright.graph.consolidate import (
    GroupDraft,
    QuestionDraft,
    assemble,
    cluster_task,
    code_group,
    consolidate_cluster,
    write_consolidation,
)
from bidwright.graph.discover import Discovery, ResearchPending, ResearchStopped
from bidwright.graph.nodes import (
    MALFORMED_AFTER_REPAIR,
    BatchOutcome,
    CallManifests,
    RunContext,
    approach,
    assign_requirements,
    candidate_rows,
    draft,
    extract_batch,
    link_hazards,
    risk,
    risk_baseline,
    section_records,
    write_approach,
)
from bidwright.graph.seed import Seed, check_seed, copy_seed_files, seed_values
from bidwright.graph.state import (
    SEED_UNTIL,
    BatchState,
    ClaimState,
    ClusterState,
    NeedState,
    RunState,
)
from bidwright.graph.triage import forced_zones, triage
from bidwright.guard import GuardResult, PolicyBlocked, run_guard
from bidwright.harness.budget import BudgetExceeded, RunBudget
from bidwright.harness.context import CONTEXT_DIR, ContextManager, prompt_tokens
from bidwright.harness.egress import CONTEXT7_DESTINATION, RESEARCH_DESTINATION, check_run
from bidwright.harness.gateway import ToolGateway, ToolLog
from bidwright.harness.recovery import DEAD_LETTERS, CircuitBreaker, DeadLetters
from bidwright.harness.reflect import reflect_for
from bidwright.harness.supervisor import STOP_REASON, RunSupervisor, environment, read_manifest
from bidwright.harness.view import TextView
from bidwright.ingest import doc_id_for, ingest_package
from bidwright.kb import cards_by_node, load_cards, load_kb, normalize_families
from bidwright.lint import run_lint, write_lint
from bidwright.llm.cache import response_cache, run_journal
from bidwright.llm.client import ROUTES, LLMClient, Mode, Route, choose_route, route_config
from bidwright.llm.limits import Limiter, tier_for
from bidwright.llm.replay import CassetteStore
from bidwright.llm.types import Backend, CircuitOpen, LLMError, QuotaExhausted
from bidwright.obs.events import EventRecorder
from bidwright.obs.ledger import LedgerFile, models_used, totals_of
from bidwright.obs.tracing import Tracing, maybe_span, run_metadata, set_attribute, trace_endpoint
from bidwright.parsers.docling_client import CASSETTES as DOCLING_CASSETTES
from bidwright.parsers.docling_client import DoclingClient, DoclingError
from bidwright.parsers.docling_parser import DoclingParser
from bidwright.parsers.pdfplumber_parser import PdfplumberParser
from bidwright.preflight import (
    CONSENT,
    HOME,
    Preflight,
    Refused,
    check_preconditions,
    needs_docling,
    package_documents,
)
from bidwright.prompts import Prompt, load_prompt, load_prompt_ref, with_cards
from bidwright.register import RegisterInput, build_register
from bidwright.render import DomainResearch, RenderBlocked, RunRecords, render
from bidwright.research.nlm import notebooklm_provider
from bidwright.research.provider import ResearchProvider
from bidwright.retrieval import PassageIndex
from bidwright.schemas import (
    ApproachItem,
    CandidateRow,
    ClarificationQuestion,
    ClusterTask,
    ContextPack,
    ContractFlag,
    ControlRegister,
    CoverageReport,
    CoverageRound,
    CueHit,
    DefinedTerm,
    Discrepancy,
    DiscrepancyProposal,
    DocumentHash,
    DomainBrief,
    DuplicatePair,
    ExtractItem,
    LedgerEntry,
    LintFinding,
    OpenQuestion,
    OpportunityBrief,
    Passage,
    ProposalSection,
    QuarantineRecord,
    ReferenceLink,
    Requirement,
    RequirementGroup,
    ResearchModeName,
    RfpProfile,
    Risk,
    RunManifest,
    RunStatus,
    SubmissionHazard,
    ZoneRecord,
)
from bidwright.tools import date_tool, search_tool, sla_tool
from bidwright.verify import QuoteCheck

SECTIONS = ("understanding", "approach", "risks_and_assumptions")
UNTIL = (
    "verify",
    "coverage",
    "consolidate",
    "brief",
    "capability_map",
    "solution_gate",
    "render",
)
# The research nodes after `brief`, by research mode.
AFTER_BRIEF = {"off": "approach", "pack": "discover_load", "live": "discover_start"}
# A spent daily quota pauses a run; `bidwright resume` continues it (ADR-031).
QUOTA_ADVICE = "resume it with bidwright resume after the quota resets, or with --profile paid"
# MCP calls have no cassettes, so a recording in research mode live would reach the research
# server when replayed; the client's record and replay modes refuse it.
LIVE_RESEARCH_UNRECORDED = (
    "research mode live cannot run in the client's {mode} mode: MCP calls have no cassettes,"
    " so a replay would reach the research server; use --research pack or off"
)


class NodeFunction(Protocol):
    """A graph node: takes the state it reads, returns the keys it writes."""

    def __call__(self, state: Any) -> dict[str, Any]: ...


# The `extract_context` switch's values (section 4.11).
EXTRACT_CONTEXTS = ("full", "bare")
# The servers research mode `live` reaches (Iteration 3: Context7 for techcheck).
LIVE_SERVERS = (RESEARCH_DESTINATION, CONTEXT7_DESTINATION)


@dataclass
class Runtime:
    ctx: RunContext
    config: Config
    source: Path
    run_dir: Path
    extract_prompt: str = "extract"
    one_batch: bool = False
    second_pass: bool = False  # S-13
    until: str = "render"  # the last node to run
    batch_size: int | None = None  # None: `limits.yaml`
    baseline: str | None = None
    docling_mode: Mode = "live"
    docling_cassettes: Path = DOCLING_CASSETTES
    index: PassageIndex | None = None
    guard: GuardResult | None = None
    paths: list[Path] | None = None  # the input documents, in name order
    data_class: str | None = None  # the run entry's; None in replay, where each file is classed
    dead_letters: DeadLetters | None = None  # the run's dead_letter.jsonl (Iteration 2)
    tool_log: ToolLog | None = None  # the run's tool_calls.jsonl, every gateway's calls
    control: RunControl | None = None  # the stop control `discover_wait` reads
    events: EventRecorder | None = None  # the run's events.jsonl
    provider: ResearchProvider | None = None  # the research provider, or None
    research: ResearchConfig | None = None  # the research configuration
    research_mode: ResearchModeName = "off"
    discovery: Discovery | None = None  # built once the passages are known
    # The `assess` role's route, set once a run (ADR-045): primary, fallback or same; None on a
    # profile with no routed `assess`.
    assess_route: str | None = None
    # The run's circuit breaker, for the MCP servers code calls: Context7 and reflect's.
    breaker: Any = None
    # Iteration 3 (step 12): the profile, the knowledge base, the switches of section 4.11, the
    # gate's mode and the loaded bid policy with its hash.
    profile: str = "free"
    kb: Any = None
    solution: str = "manifest"
    risk_mode: str = "agent"
    reflect: bool = False
    gate: str = "auto"
    bid_policy: tuple[Any, str] | None = None
    # The extraction switches (step 16): `bare` packs each passage's id and text only;
    # triage off zones every section OBLIGATION with no call; coverage off runs no round.
    extract_context: str = "full"
    triage_on: bool = True
    coverage_on: bool = True
    # A seeded run's seed and the state its checkpoint holds (step 16), or None.
    seed: Seed | None = None
    seed_state: dict[str, Any] | None = None
    # Each node's method-card ids (step 18), which its context manifests record.
    cards: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class RunResult:
    run_id: str
    run_dir: Path
    status: RunStatus
    reason: str | None
    assess_route: str | None = None  # the route `bidwright record` writes to the recording


def _jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(body, encoding="utf-8", newline="\n")


def _outcome_dict(outcome: BatchOutcome) -> dict[str, Any]:
    return {
        "batch_id": outcome.batch_id,
        "round": outcome.round,
        "accepted": [
            {"item": item.model_dump(), "check": asdict(check)} for item, check in outcome.accepted
        ],
        "rejected": outcome.rejected,
        "no_obligation": outcome.no_obligation,
    }


def _outcome(data: dict[str, Any]) -> BatchOutcome:
    accepted = []
    for entry in data["accepted"]:
        check = dict(entry["check"])
        check["span"] = tuple(check["span"]) if check["span"] else None
        accepted.append((ExtractItem.model_validate(entry["item"]), QuoteCheck(**check)))
    return BatchOutcome(
        data["batch_id"], accepted, data["rejected"], data["no_obligation"], data["round"]
    )


def _zones(state: RunState) -> dict[tuple[str, str], str]:
    """The zone of each section, by document and section path."""
    records = [ZoneRecord.model_validate(z) for z in state.get("zones", [])]
    return {(z.doc_id, z.section_path): z.zone for z in records}


def _cues(state: RunState) -> list[CueHit]:
    return [CueHit.model_validate(c) for c in state.get("cues", [])]


def _draft_dict(draft: GroupDraft) -> dict[str, Any]:
    return {
        "cluster": asdict(draft.cluster),
        "topic": draft.topic,
        "llm": draft.llm,
        "duplicates": [d.model_dump(mode="json") for d in draft.duplicates],
        "references": [r.model_dump(mode="json") for r in draft.references],
        "discrepancies": [d.model_dump(mode="json") for d in draft.discrepancies],
        "questions": [asdict(q) for q in draft.questions],
        "fell_back": draft.fell_back,
    }


def _draft(data: dict[str, Any]) -> GroupDraft:
    return GroupDraft(
        cluster=Cluster(**data["cluster"]),
        topic=data["topic"],
        llm=data["llm"],
        duplicates=[DuplicatePair.model_validate(d) for d in data["duplicates"]],
        references=[ReferenceLink.model_validate(r) for r in data["references"]],
        discrepancies=[DiscrepancyProposal.model_validate(d) for d in data["discrepancies"]],
        questions=[QuestionDraft(**q) for q in data["questions"]],
        fell_back=data["fell_back"],
    )


def build_graph(rt: Runtime, checkpointer: Any | None = None) -> Any:
    ctx = rt.ctx
    config = rt.config

    def passages(state: RunState) -> list[Passage]:
        found = [Passage.model_validate(p) for p in state.get("passages", [])]
        if not ctx.passages:
            ctx.passages = {p.id: p for p in found}
        return found

    def register_of(state: RunState) -> ControlRegister | None:
        data = state.get("register")
        return ControlRegister.model_validate(data) if data else None

    def requirements_of(state: RunState) -> list[Requirement]:
        return [Requirement.model_validate(r) for r in state.get("requirements", [])]

    def findings_of(state: RunState) -> list[LintFinding]:
        return [LintFinding.model_validate(f) for f in state.get("lint", [])]

    # --- guard and ingest ---------------------------------------------------------------------

    def guard_node(state: RunState) -> dict[str, Any]:
        paths = package_documents(rt.source) if rt.source.is_dir() else [rt.source]
        for path in paths:
            if not path.is_file():
                raise PolicyBlocked(f"{path.name} is not a readable file")
        rt.guard = run_guard(paths, rt.run_dir, config, data_class=rt.data_class)
        rt.paths = paths
        return {"guard": rt.guard.report.model_dump(mode="json")}

    def ingest_node(state: RunState) -> dict[str, Any]:
        guard = rt.guard
        if guard is None:  # a resumed run: the guard's files are already in the run folder
            rt.guard = guard = run_guard(
                rt.paths or [rt.source], rt.run_dir, config, data_class=rt.data_class
            )
        paths = rt.paths or [rt.source]
        items = [
            RegisterInput(
                path, entry.doc_id, entry.sha256, entry.format, entry.doc_id in guard.sanitized
            )
            for path, entry in zip(paths, guard.report.files, strict=True)
            if entry.format is not None and entry.accepted
        ]
        register = build_register(rt.source, items, config.ingest.parsers)
        docling = DoclingParser(
            DoclingClient.from_config(config, rt.docling_mode, store=rt.docling_cassettes)
        )
        plumber = PdfplumberParser()
        chosen = {entry.doc_id: entry.parser for entry in register.documents}
        parsed = [
            (docling if chosen[item.doc_id] == "docling" else plumber).parse(
                guard.sanitized.get(item.doc_id, item.path),
                item.doc_id,
                guard.guards.get(item.doc_id),
            )
            for item in items
        ]
        suspect = compile_patterns(config.ingest.suspect_patterns, "config/ingest.yaml")
        result = ingest_package(register, parsed, rt.run_dir, suspect)
        ctx.passages = {p.id: p for p in result.passages}
        if ctx.view is not None:
            ctx.view.bind(result.passages)
        rt.index = PassageIndex.build(result.passages, rt.run_dir / "search.sqlite", view=ctx.view)
        final = result.register or register
        main = next((e for e in final.documents if e.role == "main"), None)
        return {
            "doc_id": result.doc_id,
            "title": (main.title if main and main.title else result.doc_id),
            "passages": [p.model_dump() for p in result.passages],
            "register": final.model_dump(mode="json"),
            "ingest_degraded": [*guard.degraded, *result.degraded],
        }

    # --- candidates, triage, b0 and packs -----------------------------------------------------

    def candidates_node(state: RunState) -> dict[str, Any]:
        found = passages(state)
        hits = cue_hits(found, CompiledCues.load(config.cues))
        terms = defined_terms(found)
        write_candidates(rt.run_dir, hits, terms)
        return {
            "cues": [h.model_dump(mode="json") for h in hits],
            "terms": [t.model_dump(mode="json") for t in terms],
        }

    def after_candidates(state: RunState) -> str:
        return "b0" if rt.baseline == "b0" else "triage"

    def b0_node(state: RunState) -> dict[str, Any]:
        outcome = b0_outcome(passages(state), CompiledCues.load(config.cues))
        return {"outcomes": [_outcome_dict(outcome)], "round": 0}

    def triage_node(state: RunState) -> dict[str, Any]:
        found = passages(state)
        if not rt.triage_on:
            outcome = forced_zones(
                found, run_dir=rt.run_dir, register=register_of(state), view=ctx.view
            )
        else:
            outcome = triage(
                ctx,
                found,
                manager=ContextManager(rt.run_dir, config.limits.context, found, cards=rt.cards),
                zones=config.zones,
                budget_tokens=config.limits.context.budgets["triage"],
                run_dir=rt.run_dir,
                register=register_of(state),
                cues=_cues(state),
                view=ctx.view,
            )
        return {
            "zones": [z.model_dump(mode="json") for z in outcome.record.zones],
            "profile": outcome.record.profile.model_dump(mode="json"),
            "hazards": [h.model_dump(mode="json") for h in outcome.hazards],
            "triage_fallback": outcome.degraded,
        }

    def packs_for(
        state: RunState, members: list[Passage], size: int | None, first: int
    ) -> list[dict[str, Any]]:
        limits = config.limits
        manager = ContextManager(rt.run_dir, limits.context, passages(state), cards=rt.cards)
        bare = rt.extract_context == "bare"
        packs = manager.pack(
            "extract",
            members,
            view=ctx.view,
            fixed_tokens=prompt_tokens(
                ctx.prompts[rt.extract_prompt], limits.context.chars_per_token
            ),
            budget_tokens=limits.context.budgets["extract"],
            batch_size=size,
            neighbors=0 if bare else limits.context.neighbors,
            terms=[] if bare else [DefinedTerm.model_validate(t) for t in state.get("terms", [])],
            bare=bare,
            zones=[ZoneRecord.model_validate(z) for z in state.get("zones", [])],
            cues=_cues(state),
            first=first,
        )
        return [p.model_dump(mode="json") for p in packs]

    def pack_node(state: RunState) -> dict[str, Any]:
        size = None if rt.one_batch else (rt.batch_size or config.limits.batch_size)
        return {"packs": packs_for(state, passages(state), size, 1), "round": 0}

    def fan_out(state: RunState) -> list[Send]:
        return [
            Send("extract", {"call_id": p["call_id"], "round": 0, "pack": p})
            for p in state["packs"]
        ]

    def extract_node(state: BatchState) -> dict[str, Any]:
        pack = ContextPack.model_validate(state["pack"])
        outcome = extract_batch(
            ctx, pack, rt.extract_prompt, second_pass=rt.second_pass, round=state["round"]
        )
        if rt.dead_letters is not None and any(
            r["reason"] == MALFORMED_AFTER_REPAIR for r in outcome.rejected
        ):
            rt.dead_letters.add(
                "extract",
                pack.call_id,
                MALFORMED_AFTER_REPAIR,
                attempts=2,
                manifest=f"{CONTEXT_DIR}/extract-{pack.call_id}.json",
            )
        return {"outcomes": [_outcome_dict(outcome)]}

    # --- verify and coverage --------------------------------------------------------------------

    def verify_node(state: RunState) -> dict[str, Any]:
        found = passages(state)
        outcomes = sorted(
            (_outcome(o) for o in state["outcomes"]), key=lambda o: (o.round, o.batch_id)
        )
        zones = _zones(state)
        requirements, rejected = assign_requirements(outcomes, found, zones)
        hazards = [SubmissionHazard.model_validate(h) for h in state.get("hazards", [])]
        requirements, hazards = link_hazards(requirements, hazards)
        ledger = candidate_rows(outcomes, found, requirements, zones, _cues(state))
        rows = [r.model_dump(mode="json") for r in requirements]
        rows_out = [c.model_dump(mode="json") for c in ledger]
        _jsonl(rt.run_dir / "requirements.jsonl", rows)
        _jsonl(rt.run_dir / "rejected.jsonl", rejected)
        _jsonl(rt.run_dir / "candidates.jsonl", rows_out)
        linked = [h.model_dump(mode="json") for h in hazards]
        (rt.run_dir / "hazards.json").write_text(
            json.dumps(linked, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return {
            "requirements": rows,
            "rejected": rejected,
            "hazards": linked,
            "candidates": rows_out,
        }

    def after_verify(state: RunState) -> str:
        return END if rt.until == "verify" else "coverage"

    def coverage_node(state: RunState) -> dict[str, Any]:
        """Stop, or pack the gaps for the next round. EX0 is one call, so it never loops."""
        rows = [CandidateRow.model_validate(r) for r in state["candidates"]]
        so_far = [
            CoverageRound.model_validate(r) for r in state.get("coverage", {}).get("rounds", [])
        ]
        limits = config.limits.coverage
        current = state.get("round", 0)
        rounds = 0 if rt.one_batch or not rt.coverage_on else limits.max_rounds
        step = next_step(rows, so_far, current, rounds)
        if step.report is not None:
            write_report(rt.run_dir, step.report)
            return {"coverage": step.report.model_dump(mode="json")}
        gaps = [ctx.passages[s] for s in step.gaps]
        packs = list(state["packs"])
        new = packs_for(state, gaps, limits.gap_pack_size, len(packs) + 1)
        return {
            "round": current + 1,
            "packs": packs + new,
            "coverage": {
                "rounds": [r.model_dump(mode="json") for r in step.rounds],
                "pending": [p["call_id"] for p in new],
            },
        }

    def after_coverage(state: RunState) -> list[Send] | str:
        coverage = state["coverage"]
        if "stop_reason" in coverage:
            return END if rt.until == "coverage" else "lint"
        pending = set(coverage["pending"])
        return [
            Send("extract", {"call_id": p["call_id"], "round": state["round"], "pack": p})
            for p in state["packs"]
            if p["call_id"] in pending
        ]

    # --- lint and consolidate -------------------------------------------------------------------

    def lint_node(state: RunState) -> dict[str, Any]:
        found = passages(state)
        skipped: list[str] = []
        frozen = rt.run_dir / "frozen.txt"
        findings, flags = run_lint(
            requirements_of(state),
            found,
            [DefinedTerm.model_validate(t) for t in state.get("terms", [])],
            register_of(state),
            config,
            frozen_text=frozen.read_text(encoding="utf-8") if frozen.exists() else None,
            skipped=skipped,
        )
        write_lint(rt.run_dir, findings, flags)
        return {
            "lint": [f.model_dump(mode="json") for f in findings],
            "flags": [f.model_dump(mode="json") for f in flags],
            "lint_skipped": skipped,
        }

    def plan_clusters(state: RunState) -> tuple[list[Cluster], list[Requirement]]:
        requirements = requirements_of(state)
        clusters = build_clusters(
            requirements, ctx.passages, register_of(state), config.limits.clusters
        )
        return clusters, requirements

    def consolidate_plan(state: RunState) -> dict[str, Any]:
        """Code groups for the clusters that need no model; the rest go out as tasks."""
        passages(state)
        clusters, requirements = plan_clusters(state)
        by_id = {r.id: r for r in requirements}
        drafts = [
            _draft_dict(code_group(c, by_id, ctx.passages, findings_of(state), config))
            for c in clusters
            if not c.to_model
        ]
        return {"groups": drafts}

    def to_consolidate(state: RunState) -> list[Send] | str:
        passages(state)
        clusters, requirements = plan_clusters(state)
        by_id = {r.id: r for r in requirements}
        precedence = precedence_passages(list(ctx.passages.values()))
        sends = [
            Send(
                "consolidate",
                {
                    "cluster": asdict(cluster),
                    "task": cluster_task(
                        cluster,
                        by_id,
                        ctx.passages,
                        register=register_of(state),
                        lint=findings_of(state),
                        precedence=precedence,
                        view=ctx.view,
                    ).model_dump(mode="json"),
                    "requirements": state["requirements"],
                    "lint": state.get("lint", []),
                },
            )
            for cluster in clusters
            if cluster.to_model
        ]
        return sends or "consolidate_join"

    def consolidate_node(state: ClusterState) -> dict[str, Any]:
        requirements = [Requirement.model_validate(r) for r in state["requirements"]]
        by_id = {r.id: r for r in requirements}
        manager = ContextManager(
            rt.run_dir,
            config.limits.context,
            list(ctx.passages.values()),
            requirement_sources={r.id: r.src_ids for r in requirements},
            cards=rt.cards,
        )
        task = ClusterTask.model_validate(state["task"])
        draft = consolidate_cluster(
            ctx,
            task,
            Cluster(**state["cluster"]),
            manager,
            by_id,
            ctx.passages,
            [LintFinding.model_validate(f) for f in state["lint"]],
            config,
        )
        if draft.fell_back and rt.dead_letters is not None:
            rt.dead_letters.add(
                "consolidate",
                task.cluster_id,
                "malformed output twice; a code group stands in",
                attempts=2,
                manifest=f"{CONTEXT_DIR}/consolidate-{task.cluster_id}.json",
            )
        return {"groups": [_draft_dict(draft)]}

    def consolidate_join(state: RunState) -> dict[str, Any]:
        by_id = {r.id: r for r in requirements_of(state)}
        outcome = assemble([_draft(d) for d in state.get("groups", [])], by_id)
        write_consolidation(rt.run_dir, outcome)
        return {
            "group_records": [g.model_dump(mode="json") for g in outcome.groups],
            "discrepancies": [d.model_dump(mode="json") for d in outcome.discrepancies],
            "questions": [q.model_dump(mode="json") for q in outcome.questions],
            "consolidate_fallback": outcome.degraded,
        }

    def after_consolidate(state: RunState) -> str:
        return END if rt.until == "consolidate" else "brief"

    # --- brief and research ------------------------------------------------------------------

    def brief_node(state: RunState) -> dict[str, Any]:
        found = passages(state)
        profile = state.get("profile")
        outcome = write_brief(
            ctx,
            found,
            [ZoneRecord.model_validate(z) for z in state.get("zones", [])],
            requirements_of(state),
            RfpProfile.model_validate(profile) if profile else RfpProfile(),
            manager=ContextManager(rt.run_dir, config.limits.context, found, cards=rt.cards),
            budget_tokens=config.limits.context.budgets["brief"],
            run_dir=rt.run_dir,
            first_discrepancy=len(state.get("discrepancies", [])) + 1,
            first_question=len(state.get("questions", [])) + 1,
        )
        record = outcome.brief.model_dump(mode="json")
        return {"brief": {"record": record, "degraded": outcome.degraded}}

    def research_next(state: RunState) -> str:
        """Where research leads: `v0.2`'s `approach` under `solution: oneshot`, else the
        solution path (Iteration 3)."""
        return "approach" if rt.solution == "oneshot" else "decide_plan"

    def after_brief(state: RunState) -> str:
        if rt.until == "brief":
            return END
        return research_next(state) if rt.research_mode == "off" else AFTER_BRIEF[rt.research_mode]

    def topics_of(state: RunState) -> list[str]:
        return list(((state.get("brief") or {}).get("record") or {}).get("topics", []))

    def discovery(state: RunState) -> Discovery:
        """The run's research nodes, built once the passages are known."""
        if rt.discovery is None:
            found = passages(state)
            rt.discovery = Discovery(
                ctx=ctx,
                provider=rt.provider,
                config=config.research,
                agent=config.agents.agents["discover"],
                run_dir=rt.run_dir,
                manager=ContextManager(rt.run_dir, config.limits.context, found, cards=rt.cards),
                passages=found,
                patterns=compile_patterns(config.ingest.suspect_patterns, "config/ingest.yaml"),
                mode=rt.research_mode,
                events=rt.events,
                tool_log=rt.tool_log,
                control=rt.control,
                budget_tokens=config.limits.context.budgets["discover"],
            )
        return rt.discovery

    def discover_load_node(state: RunState) -> dict[str, Any]:
        outcome = discovery(state).load(topics_of(state), state.get("research_failed"))
        research = {"second_job": False, "degraded": outcome.degraded}
        return {"research": research, "domain_brief": outcome.view}

    def discover_start_node(state: RunState) -> dict[str, Any]:
        return {"research_failed": discovery(state).start(topics_of(state)).failed}

    def discover_wait_node(state: RunState) -> dict[str, Any]:
        return {"research_failed": discovery(state).wait().failed}

    def discover_ask_node(state: RunState) -> dict[str, Any]:
        outcome = discovery(state).ask(topics_of(state))
        research = {"second_job": outcome.second_job, "degraded": None}
        return {"research_failed": outcome.failed, "research": research}

    def discover_extract_node(state: RunState) -> dict[str, Any]:
        outcome = discovery(state).extract(topics_of(state))
        return {"research_failed": outcome.failed, "domain_brief": outcome.view}

    def failed_or(following: str) -> Callable[[RunState], str]:
        def route(state: RunState) -> str:
            if state.get("research_failed"):
                return "discover_load"
            return research_next(state) if following == "approach" else following

        return route

    def after_ask(state: RunState) -> str:
        if state.get("research_failed"):
            return "discover_load"
        second = (state.get("research") or {}).get("second_job")
        return "discover_wait" if second else "discover_extract"

    # --- approach, risk, draft and render -------------------------------------------------------

    def manifests(state: RunState, node: str) -> CallManifests:
        """Where `approach`, `risk` and `draft` record a manifest for each model call."""
        manager = ContextManager(rt.run_dir, config.limits.context, passages(state), cards=rt.cards)
        return CallManifests(manager, config.limits.context.budgets[node])

    def approach_node(state: RunState) -> dict[str, Any]:
        outcome = approach(ctx, requirements_of(state), manifests(state, "approach"))
        return {"approach": write_approach(rt.run_dir, outcome)}

    def risk_node(state: RunState) -> dict[str, Any]:
        passages(state)
        index = rt.index or PassageIndex(rt.run_dir / "search.sqlite")
        limits = config.agents.agents["risk"].limits
        requirements = requirements_of(state)
        sources = {r.id: r.src_ids for r in requirements}
        if rt.reflect:
            limits = limits.model_copy(update={"reflect": True})
        listed: list[Any] = [search_tool(index, sources), date_tool(), sla_tool()]
        if rt.reflect:
            listed.append(reflect_for(config, rt.breaker))
        gateway = ToolGateway.for_agent(
            "risk",
            allowed=config.agents.agents["risk"].tools,
            tools=listed,
            max_tool_calls=limits.max_tool_calls or 6,
            log=rt.tool_log,
            reflect=rt.reflect,
        )
        items = [ApproachItem.model_validate(a) for a in state["approach"]["items"]]
        view = sol.risk_view(dict(state))
        if rt.risk_mode in ("oneshot", "fixed"):
            outcome = risk_baseline(
                ctx,
                requirements,
                items,
                rt.risk_mode,
                index=index,
                manifests=manifests(state, "risk"),
                solution=view,
            )
        else:
            outcome = risk(
                ctx, requirements, items, gateway, limits, manifests(state, "risk"), view
            )
        rows = [r.model_dump(mode="json") for r in outcome.risks]
        _jsonl(rt.run_dir / "risks.jsonl", rows)
        # risk_rejected.jsonl, written here only: each risk the checks dropped, with its reason.
        _jsonl(rt.run_dir / "risk_rejected.jsonl", outcome.rejected)
        span = otel_trace.get_current_span()
        set_attribute(span, "bidwright.stop_reason", outcome.stop_reason)
        set_attribute(span, "bidwright.turns", outcome.turns)
        set_attribute(span, "bidwright.tool_calls", len(gateway.calls))
        calls = [
            {
                "agent": request.agent,
                "tool": request.tool,
                "args": request.args,
                "turn": request.turn,
                "status": result.status,
            }
            for request, result in gateway.calls
        ]
        data = {
            "risks": rows,
            "questions": [q.model_dump(mode="json") for q in outcome.questions],
            "rejected": outcome.rejected,
            "stop_reason": outcome.stop_reason,
            "turns": outcome.turns,
            "tool_calls": calls,
            "failure": outcome.failure,
        }
        return {"risk": data}

    def draft_node(state: RunState) -> dict[str, Any]:
        requirements = requirements_of(state)
        items = [ApproachItem.model_validate(a) for a in state["approach"]["items"]]
        risks = [Risk.model_validate(r) for r in state["risk"]["risks"]]
        questions = [
            OpenQuestion.model_validate(q)
            for q in state["approach"]["questions"] + state["risk"]["questions"]
        ]
        sections = []
        recorder = manifests(state, "draft")
        for number, section_id in enumerate(SECTIONS, start=1):
            records = section_records(section_id, requirements, items, risks, questions)
            section = draft(ctx, section_id, records, recorder, call_id=f"S{number:02d}")
            path = rt.run_dir / "sections" / f"{section_id}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"# {section.title}\n\n{section.text}\n", encoding="utf-8", newline="\n"
            )
            sections.append(section.model_dump(mode="json"))
        return {"sections": sections}

    def render_node(state: RunState) -> dict[str, Any]:
        profile = state.get("profile")
        brief = state.get("brief")
        coverage = state.get("coverage") or {}
        guard_dir = rt.run_dir / "quarantine.jsonl"
        quarantine = (
            [
                QuarantineRecord.model_validate_json(line)
                for line in guard_dir.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if guard_dir.exists()
            else []
        )
        records = RunRecords(
            run_id=ctx.run_id,
            title=state["title"],
            requirements=requirements_of(state),
            rejected=state["rejected"],
            approach=[ApproachItem.model_validate(a) for a in state["approach"]["items"]],
            unmapped=state["approach"]["unmapped"],
            risks=[Risk.model_validate(r) for r in state["risk"]["risks"]],
            questions=[
                OpenQuestion.model_validate(q)
                for q in state["approach"]["questions"] + state["risk"]["questions"]
            ],
            sections=[ProposalSection.model_validate(s) for s in state["sections"]],
            passages=dict(ctx.passages),
            register=register_of(state),
            profile=RfpProfile.model_validate(profile) if profile else None,
            hazards=[SubmissionHazard.model_validate(h) for h in state.get("hazards", [])],
            candidates=[CandidateRow.model_validate(c) for c in state.get("candidates", [])],
            coverage=(
                CoverageReport.model_validate(coverage) if "stop_reason" in coverage else None
            ),
            groups=[RequirementGroup.model_validate(g) for g in state.get("group_records", [])],
            discrepancies=[Discrepancy.model_validate(d) for d in state.get("discrepancies", [])],
            clarifications=[
                ClarificationQuestion.model_validate(q) for q in state.get("questions", [])
            ],
            lint_findings=findings_of(state),
            contract_flags=[ContractFlag.model_validate(f) for f in state.get("flags", [])],
            quarantine=quarantine,
            brief=OpportunityBrief.model_validate(brief["record"]) if brief else None,
            domain=_domain_research(state.get("domain_brief")),
            solution=sol.solution_block(dict(state)),
            decide_questions=[
                ClarificationQuestion.model_validate(q) for q in state.get("decide_questions", [])
            ],
        )
        render(rt.run_dir, records)
        return {}

    # --- the solution path (Iteration 3, step 12; graph/solution.py) ------------------------

    def on(function: Callable[[Any, dict[str, Any]], dict[str, Any]]) -> NodeFunction:
        def node(state: Any) -> dict[str, Any]:
            if "need" not in state and "claim" not in state:  # a worker's state is its unit's
                passages(state)
            return function(rt, dict(state))

        return node

    def traced(name: str, node: NodeFunction) -> NodeFunction:
        kind = (
            OpenInferenceSpanKindValues.AGENT
            if name in ("risk", "decide", "discover_start", "discover_ask")
            else OpenInferenceSpanKindValues.CHAIN
        )

        def run(state: Any) -> dict[str, Any]:
            # A fan-out worker's span names its call, as its context manifest
            # `context/<node>-<call id>.json` does, so a passage leads to its span: a pack's
            # call id, a cluster's id, a need's id for `decide`, a claim's for `assess`.
            call_id = (
                state.get("call_id")
                or (state.get("task") or {}).get("cluster_id")
                or (state.get("claim") or {}).get("id")
                or (state.get("need") or {}).get("need_id")
            )
            attributes = {"bidwright.node": name, "bidwright.call_id": call_id}
            with maybe_span(ctx.tracing, f"node.{name}", kind, **attributes):
                return node(state)

        return run

    builder = StateGraph(RunState)
    nodes: list[tuple[str, NodeFunction]] = [
        ("guard", guard_node),
        ("ingest", ingest_node),
        ("candidates", candidates_node),
        ("b0", b0_node),
        ("triage", triage_node),
        ("pack", pack_node),
        ("verify", verify_node),
        ("coverage", coverage_node),
        ("lint", lint_node),
        ("consolidate_plan", consolidate_plan),
        ("consolidate_join", consolidate_join),
        ("brief", brief_node),
        ("discover_load", discover_load_node),
        ("discover_start", discover_start_node),
        ("discover_wait", discover_wait_node),
        ("discover_ask", discover_ask_node),
        ("discover_extract", discover_extract_node),
        ("approach", approach_node),
        ("risk", risk_node),
        ("draft", draft_node),
        ("render", render_node),
        ("decide_plan", on(sol.decide_plan)),
        ("decide_join", on(sol.decide_join)),
        ("assess_join", on(sol.assess_join)),
        ("capability_map", on(sol.capability_map)),
        ("options", on(sol.options)),
        ("blueprint", on(sol.blueprint)),
        ("techcheck", on(sol.run_techcheck)),
        ("solution_gate", on(sol.gate)),
    ]
    for name, node in nodes:
        builder.add_node(name, traced(name, node))
    builder.add_node("extract", traced("extract", extract_node), input_schema=BatchState)
    builder.add_node(
        "consolidate", traced("consolidate", consolidate_node), input_schema=ClusterState
    )
    builder.add_node("decide", traced("decide", on(sol.decide_worker)), input_schema=NeedState)
    builder.add_node("assess", traced("assess", on(sol.assess_worker)), input_schema=ClaimState)
    if rt.seed is not None:
        seed = rt.seed

        def seed_load(state: RunState) -> dict[str, Any]:
            """A seeded run's first node: the seed's files and state (section 4.11)."""
            copy_seed_files(seed, rt.run_dir)
            values = dict(rt.seed_state or {})
            found = [Passage.model_validate(p) for p in values.get("passages", [])]
            ctx.passages = {p.id: p for p in found}
            if ctx.view is not None:
                ctx.view.bind(found)
            rt.index = PassageIndex(rt.run_dir / "search.sqlite")
            return values

        def after_seed(state: RunState) -> str:
            return after_brief(state) if seed.seed_from == "research" else "risk"

        builder.add_node("seed_load", traced("seed_load", seed_load))
        builder.add_edge(START, "seed_load")
        builder.add_conditional_edges(
            "seed_load", after_seed, [*AFTER_BRIEF.values(), "decide_plan", "risk", END]
        )
    else:
        builder.add_edge(START, "guard")
    builder.add_edge("guard", "ingest")
    builder.add_edge("ingest", "candidates")
    builder.add_conditional_edges("candidates", after_candidates, ["b0", "triage"])
    builder.add_edge("b0", "verify")
    builder.add_edge("triage", "pack")
    builder.add_conditional_edges("pack", fan_out, ["extract"])
    builder.add_edge("extract", "verify")
    builder.add_conditional_edges("verify", after_verify, ["coverage", END])
    builder.add_conditional_edges("coverage", after_coverage, ["extract", "lint", END])
    builder.add_edge("lint", "consolidate_plan")
    builder.add_conditional_edges(
        "consolidate_plan", to_consolidate, ["consolidate", "consolidate_join"]
    )
    builder.add_edge("consolidate", "consolidate_join")
    builder.add_conditional_edges("consolidate_join", after_consolidate, ["brief", END])
    builder.add_conditional_edges("brief", after_brief, [*AFTER_BRIEF.values(), "decide_plan", END])
    builder.add_conditional_edges(
        "discover_start", failed_or("discover_wait"), ["discover_load", "discover_wait"]
    )
    builder.add_conditional_edges(
        "discover_wait", failed_or("discover_ask"), ["discover_load", "discover_ask"]
    )
    builder.add_conditional_edges(
        "discover_ask", after_ask, ["discover_load", "discover_wait", "discover_extract"]
    )
    builder.add_conditional_edges(
        "discover_extract", failed_or("approach"), ["discover_load", "approach", "decide_plan"]
    )
    builder.add_conditional_edges("discover_load", research_next, ["approach", "decide_plan"])

    def route(function: Callable[[Any, dict[str, Any]], Any]) -> Callable[[Any], Any]:
        return lambda state: function(rt, dict(state))

    builder.add_conditional_edges("decide_plan", route(sol.decide_sends), ["decide", "decide_join"])
    builder.add_edge("decide", "decide_join")
    builder.add_conditional_edges(
        "decide_join", route(sol.after_decide), ["assess", "assess_join", "approach"]
    )
    builder.add_edge("assess", "assess_join")
    builder.add_edge("assess_join", "capability_map")
    builder.add_conditional_edges(
        "capability_map", route(sol.after_map), ["options", "approach", END]
    )
    builder.add_edge("options", "blueprint")
    builder.add_conditional_edges(
        "blueprint", route(sol.after_blueprint), ["techcheck", "approach"]
    )
    builder.add_conditional_edges("techcheck", route(sol.after_techcheck), ["blueprint", "risk"])
    builder.add_edge("approach", "risk")
    builder.add_conditional_edges("risk", route(sol.after_risk), ["solution_gate", "draft"])
    builder.add_conditional_edges(
        "solution_gate",
        route(sol.after_gate),
        ["draft", "blueprint", "techcheck", END],
    )
    builder.add_edge("draft", "render")
    builder.add_edge("render", END)
    return builder.compile(checkpointer=checkpointer)


def current_commit() -> str:
    """The commit a run records: `BIDWRIGHT_COMMIT` when set, as the image sets it, or Git's
    short HEAD; the research pack builder's runs record it too."""
    if os.environ.get("BIDWRIGHT_COMMIT"):
        return os.environ["BIDWRIGHT_COMMIT"]
    try:
        out = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _file_hash(path: Path) -> str:
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        return f"unreadable: {type(exc).__name__}"


def _degraded(state: dict[str, Any]) -> str | None:
    """The shortfalls a finished run carries, in the order of section 4.3 of the design;
    each one makes the status `DEGRADED`."""
    reasons = list(state.get("ingest_degraded", []))
    coverage = state.get("coverage") or {}
    if "stop_reason" in coverage:
        left = degraded_reason(CoverageReport.model_validate(coverage))
        if left:
            reasons.append(left)
    else:
        failed = [r for r in state.get("rejected", []) if r.get("reason") == MALFORMED_AFTER_REPAIR]
        if failed:
            reasons.append(f"{len(failed)} extraction batch(es) failed")
    if state.get("triage_fallback"):
        reasons.append(state["triage_fallback"])
    reasons += state.get("lint_skipped", [])
    if state.get("consolidate_fallback"):
        reasons.append(state["consolidate_fallback"])
    for step in ("brief", "research"):
        shortfall = (state.get(step) or {}).get("degraded")
        if shortfall:
            reasons.append(shortfall)
    reasons += sol.degraded_reasons(state)
    for node in ("approach", "risk"):
        failure = (state.get(node) or {}).get("failure")
        if failure:
            reasons.append(f"{node}: {failure}")
    sections = [s["id"] for s in state.get("sections", []) if s.get("status") == "FAILED"]
    if sections:
        reasons.append(f"sections failed: {', '.join(sections)}")
    return "; ".join(reasons) or None


def _domain_research(view: dict[str, Any] | None) -> DomainResearch | None:
    """The state's domain brief as `render` reads it."""
    if not view:
        return None
    citations = {k: (str(v["title"]), int(v["tier"])) for k, v in view["citations"].items()}
    return DomainResearch(DomainBrief.model_validate(view["brief"]), view["origin"], citations)


def _second_pass(asked: bool | None, baseline: bool, config: Config) -> bool:
    """Off for a baseline, whose one call is its definition, and refused when a caller asks
    for it there (ADR-028); for any other run, the caller's flag, or `limits.yaml`'s value
    (S-13)."""
    if baseline:
        if asked:
            raise Refused(
                "a baseline runs without the second pass, since its one call is its definition"
                " (ADR-028): drop --second-pass"
            )
        return False
    return config.limits.second_pass if asked is None else asked


def extract_prompt_ids(prompts: dict[str, Prompt]) -> list[str]:
    """The loaded prompts the `extract` step may use: those that answer with `ExtractResult`."""
    return sorted(
        name for name, prompt in prompts.items() if prompt.meta.output_schema == "ExtractResult"
    )


def check_extract_prompt(name: str, prompts: dict[str, Prompt]) -> None:
    """Refuse an extract prompt the run does not load, before anything starts."""
    known = extract_prompt_ids(prompts)
    if name not in known:
        raise Refused(f"no extract prompt {name!r}: a run loads {', '.join(known)}")


def run_prompts(config: Config, methods: Sequence[str] | None = None) -> dict[str, Prompt]:
    """Each agent's pinned prompt, plus the extraction baselines' prompts. The cards of the
    enabled families, `methods` or `limits.yaml`'s by default, are appended to their
    consumers' prompts (step 18)."""
    prompts = {name: load_prompt_ref(agent.prompt) for name, agent in config.agents.agents.items()}
    prompts["extract_oneshot"] = load_prompt("extract_oneshot")
    families = list(config.limits.methods.enabled if methods is None else methods)
    if families:
        for node, cards in cards_by_node(load_cards(), families).items():
            if node in prompts:
                prompts[node] = with_cards(prompts[node], [(c.id, c.text) for c in cards])
    return prompts


def _package_id(source: Path, preflight_id: str | None) -> str:
    """The run id's package part: from preflight, or, on replay, from the source itself."""
    if preflight_id:
        return preflight_id
    return source.name if source.is_dir() else doc_id_for(source)


def _documents(preflight: Preflight, data_class: str) -> list[DocumentHash]:
    return [
        DocumentHash(
            doc_id=doc_id_for(document.path, data_class, document.sha256),
            file=document.path.name,
            sha256=document.sha256,
        )
        for document in preflight.documents
    ]


def execute(
    *,
    source: Path,
    profile: str,
    outputs: Path,
    mode: Mode = "live",
    cassettes: CassetteStore | None = None,
    backends: dict[str, Backend] | None = None,
    baseline: str | None = None,
    consent: str | None = None,
    limits: str | None = None,
    run_id: str | None = None,
    until: str = "render",
    batch_size: int | None = None,
    extract_prompt: str | None = None,
    second_pass: bool | None = None,
    repeat: int = 0,
    cache: bool = False,
    docling_mode: Mode | None = None,
    docling_cassettes: Path | None = None,
    view: TextView | None = None,
    fallback: bool = True,
    research: ResearchModeName | None = None,
    provider: ResearchProvider | None = None,
    fill: bool = False,
    resume: bool = False,
    raise_budget: int | None = None,
    control: RunControl | None = None,
    config: Config | None = None,
    watch_interval_s: float = 1.0,
    assess_route: str | None = None,
    gate: str = "auto",
    approval: Any = None,
    solution: str | None = None,
    risk_mode: str | None = None,
    reflect: bool | None = None,
    bid_policy: Path | str | None = None,
    extract_context: str | None = None,
    triage: bool | None = None,
    coverage: bool | None = None,
    seed_run: Path | str | None = None,
    seed_from: str | None = None,
    methods: Sequence[str] | None = None,
) -> RunResult:
    """Run one RFP file or package end to end, or resume a run. A failed run still leaves its
    manifest and ledger.

    The profile's preconditions are checked first (`preflight.py`): a run that is refused
    leaves no folder, and `Refused` carries what to do instead. `limits` names the tier in
    `config/limits.yaml`; by default a corpus file gets its own tier, and any other file `dev`.
    `until` stops the run after `verify`, `coverage` or `consolidate`; `--baseline b0` makes no
    model call and stops after `verify`. Docling runs in `docling_mode`, the run's mode unless
    set, so a test can record its LLM cassettes while Docling replays. `view` is the run's text
    view (D-05), the frozen text when None; Iteration 5's masking passes one. `fallback=False`
    keeps every call on its role's primary model: a spent quota then pauses the run, and a
    call that exhausts its retries faults it, as matrix runs need. `research` is the research
    mode, `config/research.yaml`'s when None; `provider`, for tests, is the research provider
    used instead of the configured NotebookLM server. `fill` keeps a recording's cassettes in
    the client's `record` mode and records only the calls they lack.

    The run executes under a `RunSupervisor` (ADR-031), which takes the run lock, writes the
    manifest and records each status. `resume=True` continues the run named by `run_id` under
    `outputs` from its last checkpoint, with its journal answering the calls it had made and
    `raise_budget` added to its limits; `bidwright resume` passes the arguments the manifest's
    `run_args` recorded. `control` drains the run between super-steps, which is how
    `bidwright stop` stops it; each part gets a fresh one. `config`, used instead of
    `load_config()`, and `watch_interval_s`, the stop watcher's interval, are for tests.

    `assess_route` is the `assess` role's route (ADR-045). A live or recording run sets it from
    the backends present when it is None; a replay takes the recording's, `primary` when the
    recording names none; a resume takes the first part's, refused when that route's provider
    has no backend; and a client run takes `same` before its egress check."""
    if until not in UNTIL:
        raise Refused(f"--until takes one of {', '.join(UNTIL)}")
    if raise_budget is not None and not resume:
        raise Refused("--raise-budget applies to a resume")
    if resume and run_id is None:
        raise Refused("a resume names its run")
    chosen = BASELINES[baseline] if baseline is not None else None
    if chosen is not None and chosen.until is not None:
        until = chosen.until
    docling_mode = docling_mode or mode
    config = config or load_config()
    if (research or config.research.mode) == "live" and mode != "live":
        raise Refused(LIVE_RESEARCH_UNRECORDED.format(mode=mode))
    try:
        families = normalize_families(
            list(config.limits.methods.enabled if methods is None else methods)
        )
    except ValueError as exc:
        raise Refused(str(exc)) from exc
    prompts = run_prompts(config, families)
    seed = _seed(
        seed_run,
        seed_from,
        prompts,
        until=until,
        baseline=baseline,
        given={
            "batch_size": batch_size,
            "second_pass": second_pass,
            "extract_prompt": extract_prompt,
            "extract_context": extract_context,
            "triage": triage,
            "coverage": coverage,
        },
    )
    if seed is not None:  # a seeded run keeps its seed's extraction settings
        fixed = seed.record.extraction
        extract_prompt = fixed.get("extract_prompt") or extract_prompt
        batch_size = fixed.get("batch_size") or batch_size
        second_pass = fixed.get("second_pass")
        extract_context = fixed.get("extract_context") or extract_context
        triage = fixed.get("triage")
        coverage = fixed.get("coverage")
    extract_id = extract_prompt or (chosen.extract_prompt if chosen else "extract")
    check_extract_prompt(extract_id, prompts)
    second = _second_pass(second_pass, chosen is not None, config)
    docling = DoclingClient.from_config(
        config, docling_mode, store=docling_cassettes or DOCLING_CASSETTES
    )
    preflight = check_preconditions(
        source=source,
        profile=profile,
        mode=mode,
        consent=consent,
        backends=backends or {},
        config=config,
        docling=docling if docling_mode in ("live", "record") else None,
        models=chosen is None or chosen.llm,
    )
    llm = chosen is None or chosen.llm
    route = _assess_route(
        config,
        profile,
        backends or {},
        given=assess_route,
        mode=mode,
        client=preflight.data_class == "client",
        resume=resume,
        llm=llm,
    )
    overrides = {"assess": route_config(config, profile, "assess", route)} if route else {}
    same = route == "same"
    shadow_roles = (
        {"assess": str(config.models.role(profile, "assess").same_family_role)} if same else None
    )
    roles = {
        name: overrides.get(name, role) for name, role in config.models.profiles[profile].items()
    }
    used = {role.provider for role in roles.values()}
    run_backends = (
        {p: b for p, b in (backends or {}).items() if p in used} if mode != "replay" and llm else {}
    )
    endpoint = trace_endpoint()
    parses = docling_mode in ("live", "record") and needs_docling(preflight.documents, config)
    research_mode = research or config.research.mode
    research_servers = (
        [(name, config.research.servers[name]) for name in LIVE_SERVERS]
        if research_mode == "live"
        else []
    )
    switches = _switches(
        config,
        solution,
        risk_mode,
        reflect,
        extract_context=extract_context,
        triage=triage,
        coverage=coverage,
    )
    if switches["reflect"]:
        # The reflect server, over stdio, is checked against the register like the research
        # servers (step 11's design; drift report 2026-11-12).
        research_servers.append(("reflect", config.research.servers["reflect"]))
    refused = check_run(
        run_backends,
        endpoint,
        docling.host if parses else None,
        preflight.data_class,
        register=config.egress,
        consent=profile == "free" and consent == CONSENT,
        research=research_servers,
    )
    if gate not in ("wait", "auto"):
        raise Refused(f"the gate takes wait or auto, not {gate!r}")
    policy = load_bid_policy(Path(bid_policy)) if bid_policy else None
    started = datetime.now(UTC)
    suffix = f"-{baseline}" if baseline else ""
    if run_id is None:
        package_id = _package_id(source, preflight.package_id)
        run_id = f"{started:%Y%m%dT%H%M%SZ}-{package_id}-{profile}{suffix}"
    run_dir = outputs / run_id
    if resume:
        read_manifest(run_dir)  # refuses a folder that holds no run
    run_dir.mkdir(parents=True, exist_ok=True)
    tier = limits or preflight.tier
    run_args = {
        "source": _relative(source),
        "profile": profile,
        "outputs": _relative(outputs),
        "baseline": baseline,
        "consent": consent,
        "limits": tier,
        "until": until,
        "batch_size": batch_size or config.limits.batch_size,
        "second_pass": second,
        "extract_prompt": extract_id,
        "research": research_mode,
        "repeat": repeat,
        "cache": cache,
        "docling_mode": docling_mode,
        "fallback": fallback,
        "mode": mode,
        "assess_route": route,
        "environment": environment(),
        "gate": gate,
        "bid_policy": _relative(Path(bid_policy)) if bid_policy else None,
        "solution": switches["solution"],
        "risk_mode": switches["risk_mode"],
        "reflect": switches["reflect"],
        "extract_context": switches["extract_context"],
        "triage": switches["triage"],
        "coverage": switches["coverage"],
        "seed_run": _relative(seed.folder) if seed is not None else None,
        "seed_from": seed.seed_from if seed is not None else None,
        "methods": families,
    }
    hashes = {
        document.path.name: f"sha256:{document.sha256}" for document in preflight.documents
    } or {source.name: _file_hash(source)}
    manifest = RunManifest(
        run_id=run_id,
        commit=current_commit(),
        profile=profile,
        models={role: rc.model for role, rc in roles.items()},
        prompt_hashes={name: prompt.hash for name, prompt in prompts.items()},
        input_hashes=hashes,
        started=started,
        status="RUNNING",
        overrides=preflight.overrides,
        documents=_documents(preflight, preflight.data_class),
        data_class=preflight.data_class,
        refused_destinations=refused,
        run_args=run_args,
        assess_route=route,
        bid_policy_sha256=policy[1] if policy else None,
        switches=switches,
        seed=seed.record if seed is not None else None,
    )
    budget = RunBudget(config.limits.run(tier, profile))
    control = control or RunControl()
    supervisor = RunSupervisor(
        run_dir,
        manifest,
        control=control,
        budget=budget,
        resume=resume,
        raise_budget=raise_budget,
        watch_interval_s=watch_interval_s,
        approving=approval is not None,
    )
    with supervisor:
        ledger_file = LedgerFile(run_dir / "ledger.jsonl")
        if resume and ledger_file.path.exists():
            # Each line file a kill can cut, before anything appends to it again.
            for name, path in (
                ("ledger", ledger_file.path),
                ("tool_calls", run_dir / "tool_calls.jsonl"),
                ("dead_letter", run_dir / DEAD_LETTERS),
            ):
                cut = repair_lines(path)
                if cut:
                    detail = f"{name}_cut: {len(cut)} characters of an unfinished last line removed"
                    supervisor.events.record("recovery", None, detail)
        else:
            ledger_file.create()
        events = supervisor.events
        breaker = CircuitBreaker(
            config.limits.breaker, on_change=lambda detail: events.record("recovery", None, detail)
        )
        if not resume:
            (run_dir / DEAD_LETTERS).unlink(missing_ok=True)
        # Every tool request with its full result, so a trace can be checked from the folder.
        tool_log = ToolLog(run_dir / "tool_calls.jsonl", part=supervisor.part)
        if not resume:
            tool_log.create()
        dead_letters = DeadLetters(
            run_dir,
            on_add=lambda letter: events.record(
                "recovery", letter.node, f"{letter.id}: {letter.call_id}, {letter.reason}"
            ),
        )
        client = LLMClient(
            config,
            profile,
            run_backends,
            mode=mode,
            cassettes=cassettes,
            run_id=run_id,
            # Quotas pace real providers only: a backend with no host, as every test double, is
            # local, as the egress check reads it, and waits for no quota window.
            limiter=(
                Limiter(config.limits, tier_for(profile))
                if mode != "replay" and any(getattr(b, "host", None) for b in run_backends.values())
                else None
            ),
            cache=response_cache() if cache and mode == "live" else None,
            journal=run_journal(run_dir) if mode == "live" else None,
            journal_read=resume,
            breaker=breaker,
            fallback=fallback,
            fill=fill,
            role_overrides=overrides,
            shadow_roles=shadow_roles,
        )
        if provider is None and research_mode == "live":
            provider = notebooklm_provider(config, breaker)
        tracing = Tracing(
            run_id,
            run_dir,
            None if refused else endpoint,
            os.environ.get("PHOENIX_API_KEY") or None,
            tags=[profile, mode, f"solution:{switches['solution']}", f"research:{research_mode}"],
        )
        ctx = RunContext(
            run_id,
            client,
            budget,
            prompts,
            {},
            tracing=tracing,
            view=view,
            repeat=repeat,
            ledger_file=ledger_file,
            started=supervisor.manifest.started.astimezone(UTC).date(),
        )
        rt = Runtime(
            ctx=ctx,
            config=config,
            source=source,
            run_dir=run_dir,
            extract_prompt=extract_id,
            one_batch=chosen.one_batch if chosen else False,
            second_pass=second,
            until=until,
            batch_size=batch_size,
            baseline=baseline,
            docling_mode=docling_mode,
            docling_cassettes=docling_cassettes or DOCLING_CASSETTES,
            data_class=preflight.data_class if mode != "replay" else None,
            dead_letters=dead_letters,
            tool_log=tool_log,
            control=control,
            events=events,
            provider=provider,
            research=config.research,
            research_mode=research_mode,
            assess_route=route,
            breaker=breaker,
            profile=profile,
            kb=load_kb(),
            solution=switches["solution"],
            risk_mode=switches["risk_mode"],
            reflect=switches["reflect"],
            gate=gate,
            bid_policy=policy,
            extract_context=switches["extract_context"],
            triage_on=switches["triage"],
            coverage_on=switches["coverage"],
            seed=seed,
            seed_state=seed_values(seed) if seed is not None else None,
            cards={node: list(p.cards) for node, p in prompts.items() if p.cards},
        )
        # Until the graph returns, the run has not finished: any exit this function does not
        # name below is recorded as a fault, never as COMPLETED.
        status: RunStatus = "UNRECOVERABLE_FAULT"
        reason: str | None = "the run ended before it finished"
        budget.start()
        run_attributes = {
            "bidwright.run_id": run_id,
            "bidwright.profile": profile,
            "bidwright.part": supervisor.part,
            SpanAttributes.METADATA: run_metadata(
                {
                    "profile": profile,
                    "mode": mode,
                    "source": run_args.get("source"),
                    "research": research_mode,
                    "until": until,
                    "gate": gate,
                    "assess_route": route,
                    "commit": supervisor.manifest.commit,
                    **switches,
                }
            ),
        }
        try:
            with (
                tracing.span("run", OpenInferenceSpanKindValues.CHAIN, **run_attributes),
                SqliteSaver.from_conn_string(str(run_dir / "checkpoints.sqlite")) as saver,
            ):
                supervisor.record_trace(tracing.trace_id)
                graph = build_graph(rt, saver)
                thread: dict[str, Any] = {
                    "configurable": {"thread_id": run_id},
                    "max_concurrency": config.limits.concurrency_for(profile),
                }
                if resume:
                    _rebuild(graph, thread, rt)
                final = _invoke(graph, thread, control, resume, approval)
            if "__interrupt__" in final:  # the solution gate asks for a decision (ADR-046)
                status = "WAITING_HUMAN"
                review = run_dir / "review" / "solution_gate.md"
                reason = (
                    f"waiting at the solution gate: review {review}, then run"
                    f" bidwright approve {run_id} --role ROLE"
                )
            else:
                reason = _degraded(final)
                status = "DEGRADED" if reason else "COMPLETED"
            if status != "WAITING_HUMAN" and until != "render":
                stopped = f"stopped after {until} by request"
                reason = f"{reason}; {stopped}" if reason else stopped
        except GraphDrained:
            status, reason = "STOPPED", STOP_REASON
        except PolicyBlocked as exc:
            status, reason = "POLICY_BLOCKED", str(exc)
        except BudgetExceeded as exc:
            status, reason = "BUDGET_EXCEEDED", str(exc)
        except QuotaExhausted as exc:
            status, reason = "QUOTA_PAUSED", f"{exc}; {QUOTA_ADVICE}"
        except CircuitOpen as exc:
            status, reason = "QUOTA_PAUSED", str(exc)
        except ResearchPending as exc:
            status, reason = "WAITING_RESEARCH", str(exc)
        except ResearchStopped as exc:
            status, reason = "STOPPED", str(exc)
        except (LLMError, RenderBlocked, DoclingError) as exc:
            status, reason = "UNRECOVERABLE_FAULT", f"{type(exc).__name__}: {exc}"
        except KeyboardInterrupt:
            status, reason = "STOPPED", "interrupted by the operator"
            raise
        except Exception as exc:
            # Recorded before it propagates, so the manifest tells what happened.
            status, reason = "UNRECOVERABLE_FAULT", f"unexpected {type(exc).__name__}: {exc}"
            raise
        finally:
            budget.pause()
            try:
                tracing.close()
            finally:
                # Nothing here may raise again and hide the run's own error: the manifest is
                # the record of the run, whatever happened.
                entries = _ledger_entries(ledger_file, ctx.ledger)
                supervisor.finish(
                    status,
                    reason,
                    totals_of(entries, budget.active_seconds),
                    models_used(entries),
                )
    return RunResult(run_id, run_dir, status, reason, route)


def _seed(
    seed_run: Path | str | None,
    seed_from: str | None,
    prompts: Mapping[str, Any],
    *,
    until: str,
    baseline: str | None,
    given: Mapping[str, Any],
) -> Seed | None:
    """The run's seed, checked before its folder exists (section 4.11), or None."""
    if seed_run is None and seed_from is None:
        return None
    if seed_run is None or seed_from is None:
        raise Refused("a seeded run names both seed_run and seed_from")
    if seed_from not in SEED_UNTIL:
        raise Refused(f"seed_from takes one of {', '.join(SEED_UNTIL)}, not {seed_from!r}")
    if until not in SEED_UNTIL[seed_from]:
        raise Refused(
            f"a run seeded from {seed_from} runs to one of {', '.join(SEED_UNTIL[seed_from])}"
        )
    if baseline is not None:
        raise Refused("a baseline extracts, so it does not start from a seed")
    folder = Path(seed_run)
    if not folder.is_absolute():
        folder = HOME / folder
    if not folder.is_dir():
        raise Refused(f"no seed at {folder}; freeze a run with bidwright seed")
    seed = check_seed(folder, seed_from, prompts)
    # A resume passes the settings its first part recorded, which are the seed's.
    changed = sorted(
        name
        for name, value in given.items()
        if value is not None and value != seed.record.extraction.get(name)
    )
    if changed:
        raise Refused(
            f"a seeded run keeps its seed's extraction settings; drop {', '.join(changed)}"
        )
    return seed


def _switches(
    config: Config,
    solution: str | None,
    risk_mode: str | None,
    reflect: bool | None,
    *,
    extract_context: str | None = None,
    triage: bool | None = None,
    coverage: bool | None = None,
) -> dict[str, Any]:
    """The run's switches (section 4.11): each argument, or `limits.yaml`'s default."""
    defaults = config.limits.switches
    chosen = {
        "solution": solution or defaults.solution,
        "risk_mode": risk_mode or defaults.risk_mode,
        "reflect": defaults.reflect if reflect is None else reflect,
        "extract_context": extract_context or defaults.extract_context,
        "triage": defaults.triage if triage is None else triage,
        "coverage": defaults.coverage if coverage is None else coverage,
    }
    if chosen["extract_context"] not in EXTRACT_CONTEXTS:
        raise Refused(f"extract_context takes one of {', '.join(EXTRACT_CONTEXTS)}")
    if chosen["solution"] not in sol.SOLUTIONS:
        raise Refused(f"solution takes one of {', '.join(sol.SOLUTIONS)}")
    if chosen["risk_mode"] not in sol.RISK_MODES:
        raise Refused(f"risk_mode takes one of {', '.join(sol.RISK_MODES)}")
    return chosen


def _relative(path: Path) -> str:
    """A path as `run_args` records it: relative to HOME when under it, so a resume finds it
    from any working directory."""
    resolved = path.resolve()
    if resolved.is_relative_to(HOME):
        return resolved.relative_to(HOME).as_posix()
    return str(resolved)


def _rebuild(graph: Any, thread: dict[str, Any], rt: Runtime) -> None:
    """Before a resume, what the nodes keep outside the checkpointed state: the passages, which
    the `Send` workers do not carry, the text view's binding, the search index and the input
    documents. A run killed before its first checkpoint has no passages to rebuild."""
    ctx = rt.ctx
    values = graph.get_state(thread).values or {}
    found = [Passage.model_validate(p) for p in values.get("passages", [])]
    if found:
        ctx.passages = {p.id: p for p in found}
        if ctx.view is not None:
            ctx.view.bind(found)
        index = rt.run_dir / "search.sqlite"
        if index.exists():
            rt.index = PassageIndex(index)
    rt.paths = package_documents(rt.source) if rt.source.is_dir() else [rt.source]


def _assess_route(
    config: Config,
    profile: str,
    backends: dict[str, Backend],
    *,
    given: str | None,
    mode: Mode,
    client: bool,
    resume: bool,
    llm: bool,
) -> Route | None:
    """The `assess` role's route for this run (ADR-045), or None when the profile does not
    route it. The route never changes within a run: a resume keeps its first part's."""
    role = config.models.profiles[profile].get("assess")
    if role is None or role.same_family_role is None:
        return None
    if given is not None:
        if given not in ROUTES:
            raise Refused(f"assess_route takes one of {', '.join(ROUTES)}, not {given!r}")
        route = cast(Route, given)
        target = route_config(config, profile, "assess", route)
        if resume and mode == "live" and llm and target.provider not in backends:
            raise Refused(
                f"this run's assess role is on route {given}, served by {target.provider},"
                f" which has no backend; set its key in .env, as the run's first part had"
            )
        return route
    if mode == "replay":
        return "primary"
    if client:
        return "same"
    return choose_route(role, backends)


def _invoke(
    graph: Any, thread: dict[str, Any], control: RunControl, resume: bool, approval: Any = None
) -> Any:
    """Run the graph, each checkpoint written before the next super-step starts. A resume
    continues from the last checkpoint; one killed before its first starts from the beginning.
    An approval resumes the gate that asked for it (`Command(resume=...)`, ADR-046)."""
    if approval is not None:
        value = approval.model_dump(mode="json") if hasattr(approval, "model_dump") else approval
        return graph.invoke(Command(resume=value), thread, control=control, durability="sync")
    if resume:
        try:
            return graph.invoke(None, thread, control=control, durability="sync")
        except EmptyInputError:
            pass
    return graph.invoke({}, thread, control=control, durability="sync")


def _ledger_entries(ledger_file: LedgerFile, kept: list[LedgerEntry]) -> list[LedgerEntry]:
    """The entries `ledger.jsonl` holds, which the manifest's totals come from. If the file
    cannot be read, the entries this process kept in memory stand in: the manifest is written
    whatever happened."""
    try:
        return ledger_file.load()
    except (OSError, ValueError):
        return list(kept)
