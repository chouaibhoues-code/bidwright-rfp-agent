"""Wire the nodes into a LangGraph graph, and run one RFP through it.

ingest -> candidates -> triage -> pack -> extract (one `Send` per context pack, at most
`concurrency` at once) -> verify -> coverage -> approach -> risk -> draft -> render
(Iteration 1, steps 11 and 12). `pack` builds the extraction packs through
`ContextManager.pack`, with the cues, terms and zones of the nodes before it, and writes their
manifests; `verify` settles the outcomes into `requirements.jsonl`, `rejected.jsonl`,
`candidates.jsonl` and `hazards.json`. `coverage` either stops, or sends the passages still
without a disposition back to `extract` as gap packs, and `verify` runs again over every
outcome. The SQLite checkpointer keeps each step's state in the run folder. The LLM client,
budget, prompts and search index stay outside the state, in `Runtime`, so a checkpoint holds
plain data only. Each node writes its own files; `render` writes the summary, the proposal, the
manifest and the ledger.

Before the run folder exists, `execute` checks the run's outbound channels against the egress
register (D-05): the backends of the profile's providers, which are the only backends the client
gets, and the trace endpoint, whose refusal sends spans to `spans.jsonl` and is recorded in the
manifest. Live and recorded runs also get the limiter for the profile's tier (step 9).
"""

import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from openinference.semconv.trace import OpenInferenceSpanKindValues
from opentelemetry import trace as otel_trace

from bidwright.baselines import BASELINES
from bidwright.candidates import CompiledCues, cue_hits, defined_terms, write_candidates
from bidwright.config import Config, load_config
from bidwright.coverage import degraded_reason, next_step, write_report
from bidwright.graph.nodes import (
    BatchOutcome,
    RunContext,
    approach,
    assign_requirements,
    candidate_rows,
    draft,
    extract_batch,
    link_hazards,
    risk,
    section_records,
)
from bidwright.graph.state import BatchState, RunState
from bidwright.graph.triage import triage
from bidwright.harness.budget import BudgetExceeded, RunBudget
from bidwright.harness.context import ContextManager, prompt_tokens
from bidwright.harness.egress import check_run
from bidwright.harness.gateway import ToolGateway
from bidwright.ingest import doc_id_for, ingest_pdf
from bidwright.llm.client import LLMClient, Mode
from bidwright.llm.limits import Limiter, tier_for
from bidwright.llm.replay import CassetteStore
from bidwright.llm.types import Backend, LLMError, QuotaExhausted
from bidwright.obs.ledger import models_used, totals_of
from bidwright.obs.tracing import Tracing, maybe_span, set_attribute, trace_endpoint
from bidwright.preflight import CONSENT, Refused, check_preconditions
from bidwright.prompts import Prompt, load_prompt, load_prompt_ref
from bidwright.render import RenderBlocked, RunRecords, render, write_manifest
from bidwright.retrieval import PassageIndex
from bidwright.schemas import (
    ApproachItem,
    CandidateRow,
    ContextPack,
    CoverageReport,
    CoverageRound,
    CueHit,
    DefinedTerm,
    ExtractItem,
    OpenQuestion,
    Passage,
    ProposalSection,
    Requirement,
    Risk,
    RunManifest,
    RunStatus,
    SubmissionHazard,
    ZoneRecord,
)
from bidwright.tools import date_tool, search_tool
from bidwright.verify import QuoteCheck

SECTIONS = ("understanding", "approach", "risks_and_assumptions")


class NodeFunction(Protocol):
    """A graph node: takes the state it reads, returns the keys it writes."""

    def __call__(self, state: Any) -> dict[str, Any]: ...


@dataclass
class Runtime:
    ctx: RunContext
    config: Config
    source: Path
    run_dir: Path
    extract_prompt: str = "extract"
    one_batch: bool = False
    second_pass: bool = False  # S-13; `execute` sets it from step 16
    index: PassageIndex | None = None


@dataclass(frozen=True)
class RunResult:
    run_id: str
    run_dir: Path
    status: RunStatus
    reason: str | None


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


def build_graph(rt: Runtime, checkpointer: Any | None = None) -> Any:
    ctx = rt.ctx

    def passages(state: RunState) -> list[Passage]:
        found = [Passage.model_validate(p) for p in state.get("passages", [])]
        if not ctx.passages:
            ctx.passages = {p.id: p for p in found}
        return found

    def ingest_node(state: RunState) -> dict[str, Any]:
        result = ingest_pdf(rt.source, rt.run_dir)
        ctx.passages = {p.id: p for p in result.passages}
        rt.index = PassageIndex.build(result.passages, rt.run_dir / "search.sqlite", view=ctx.view)
        title = next((p.section_path for p in result.passages if p.section_path), result.doc_id)
        return {
            "doc_id": result.doc_id,
            "title": title.split(" > ")[0],
            "passages": [p.model_dump() for p in result.passages],
        }

    def candidates_node(state: RunState) -> dict[str, Any]:
        found = passages(state)
        hits = cue_hits(found, CompiledCues.load(rt.config.cues))
        terms = defined_terms(found)
        write_candidates(rt.run_dir, hits, terms)
        return {
            "cues": [h.model_dump(mode="json") for h in hits],
            "terms": [t.model_dump(mode="json") for t in terms],
        }

    def triage_node(state: RunState) -> dict[str, Any]:
        found = passages(state)
        outcome = triage(
            ctx,
            found,
            manager=ContextManager(rt.run_dir, rt.config.limits.context, found),
            zones=rt.config.zones,
            budget_tokens=rt.config.limits.context.budgets["triage"],
            run_dir=rt.run_dir,
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
        found = passages(state)
        limits = rt.config.limits
        manager = ContextManager(rt.run_dir, limits.context, found)
        packs = manager.pack(
            "extract",
            members,
            view=ctx.view,
            fixed_tokens=prompt_tokens(
                ctx.prompts[rt.extract_prompt], limits.context.chars_per_token
            ),
            budget_tokens=limits.context.budgets["extract"],
            batch_size=size,
            neighbors=limits.context.neighbors,
            terms=[DefinedTerm.model_validate(t) for t in state.get("terms", [])],
            zones=[ZoneRecord.model_validate(z) for z in state.get("zones", [])],
            cues=_cues(state),
            first=first,
        )
        return [p.model_dump(mode="json") for p in packs]

    def pack_node(state: RunState) -> dict[str, Any]:
        size = None if rt.one_batch else rt.config.limits.batch_size
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
        return {"outcomes": [_outcome_dict(outcome)]}

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
        rows_out = [c.model_dump(mode="json") for c in ledger]
        rows = [r.model_dump(mode="json") for r in requirements]
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

    def coverage_node(state: RunState) -> dict[str, Any]:
        """Stop, or pack the gaps for the next round. EX0 is one call, so it never loops."""
        rows = [CandidateRow.model_validate(r) for r in state["candidates"]]
        so_far = [
            CoverageRound.model_validate(r) for r in state.get("coverage", {}).get("rounds", [])
        ]
        limits = rt.config.limits.coverage
        current = state.get("round", 0)
        step = next_step(rows, so_far, current, 0 if rt.one_batch else limits.max_rounds)
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
            return "approach"
        pending = set(coverage["pending"])
        return [
            Send("extract", {"call_id": p["call_id"], "round": state["round"], "pack": p})
            for p in state["packs"]
            if p["call_id"] in pending
        ]

    def approach_node(state: RunState) -> dict[str, Any]:
        outcome = approach(ctx, [Requirement.model_validate(r) for r in state["requirements"]])
        data = {
            "items": [a.model_dump(mode="json") for a in outcome.items],
            "unmapped": outcome.unmapped,
            "questions": [q.model_dump(mode="json") for q in outcome.questions],
            "failure": outcome.failure,
        }
        (rt.run_dir / "approach.json").write_text(
            json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
        return {"approach": data}

    def risk_node(state: RunState) -> dict[str, Any]:
        passages(state)
        index = rt.index or PassageIndex(rt.run_dir / "search.sqlite")
        limits = rt.config.agents.agents["risk"].limits
        requirements = [Requirement.model_validate(r) for r in state["requirements"]]
        sources = {r.id: r.src_ids for r in requirements}
        gateway = ToolGateway.for_agent(
            "risk",
            allowed=rt.config.agents.agents["risk"].tools,
            tools=[search_tool(index, sources), date_tool()],
            max_tool_calls=limits.max_tool_calls or 6,
        )
        outcome = risk(
            ctx,
            requirements,
            [ApproachItem.model_validate(a) for a in state["approach"]["items"]],
            gateway,
            limits,
        )
        rows = [r.model_dump(mode="json") for r in outcome.risks]
        _jsonl(rt.run_dir / "risks.jsonl", rows)
        span = otel_trace.get_current_span()
        set_attribute(span, "bidwright.stop_reason", outcome.stop_reason)
        set_attribute(span, "bidwright.turns", outcome.turns)
        set_attribute(span, "bidwright.tool_calls", len(gateway.calls))
        calls = [
            {
                "tool": request.tool,
                "args": request.args,
                "turn": request.turn,
                "status": result.status,
            }
            for request, result in gateway.calls
        ]
        # Every tool request with its full result, so a trace can be checked from the folder.
        _jsonl(
            rt.run_dir / "tool_calls.jsonl",
            [
                {**call, "reason": result.reason, "data": result.data}
                for call, (_, result) in zip(calls, gateway.calls, strict=True)
            ],
        )
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
        requirements = [Requirement.model_validate(r) for r in state["requirements"]]
        items = [ApproachItem.model_validate(a) for a in state["approach"]["items"]]
        risks = [Risk.model_validate(r) for r in state["risk"]["risks"]]
        questions = [
            OpenQuestion.model_validate(q)
            for q in state["approach"]["questions"] + state["risk"]["questions"]
        ]
        sections = []
        for section_id in SECTIONS:
            records = section_records(section_id, requirements, items, risks, questions)
            section = draft(ctx, section_id, records)
            path = rt.run_dir / "sections" / f"{section_id}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"# {section.title}\n\n{section.text}\n", encoding="utf-8", newline="\n"
            )
            sections.append(section.model_dump(mode="json"))
        return {"sections": sections}

    def render_node(state: RunState) -> dict[str, Any]:
        records = RunRecords(
            run_id=ctx.run_id,
            title=state["title"],
            requirements=[Requirement.model_validate(r) for r in state["requirements"]],
            rejected=state["rejected"],
            approach=[ApproachItem.model_validate(a) for a in state["approach"]["items"]],
            unmapped=state["approach"]["unmapped"],
            risks=[Risk.model_validate(r) for r in state["risk"]["risks"]],
            questions=[
                OpenQuestion.model_validate(q)
                for q in state["approach"]["questions"] + state["risk"]["questions"]
            ],
            sections=[ProposalSection.model_validate(s) for s in state["sections"]],
        )
        render(rt.run_dir, records)
        return {}

    def traced(name: str, node: NodeFunction) -> NodeFunction:
        kind = (
            OpenInferenceSpanKindValues.AGENT
            if name == "risk"
            else OpenInferenceSpanKindValues.CHAIN
        )

        def run(state: Any) -> dict[str, Any]:
            with maybe_span(ctx.tracing, f"node.{name}", kind, **{"bidwright.node": name}):
                return node(state)

        return run

    builder = StateGraph(RunState)
    builder.add_node("ingest", traced("ingest", ingest_node))
    builder.add_node("candidates", traced("candidates", candidates_node))
    builder.add_node("triage", traced("triage", triage_node))
    builder.add_node("pack", traced("pack", pack_node))
    builder.add_node("extract", traced("extract", extract_node), input_schema=BatchState)
    builder.add_node("verify", traced("verify", verify_node))
    builder.add_node("coverage", traced("coverage", coverage_node))
    builder.add_node("approach", traced("approach", approach_node))
    builder.add_node("risk", traced("risk", risk_node))
    builder.add_node("draft", traced("draft", draft_node))
    builder.add_node("render", traced("render", render_node))
    builder.add_edge(START, "ingest")
    for first, second in (("ingest", "candidates"), ("candidates", "triage"), ("triage", "pack")):
        builder.add_edge(first, second)
    builder.add_conditional_edges("pack", fan_out, ["extract"])
    builder.add_edge("extract", "verify")
    builder.add_edge("verify", "coverage")
    builder.add_conditional_edges("coverage", after_coverage, ["extract", "approach"])
    for first, second in (("approach", "risk"), ("risk", "draft")):
        builder.add_edge(first, second)
    builder.add_edge("draft", "render")
    builder.add_edge("render", END)
    return builder.compile(checkpointer=checkpointer)


def _commit() -> str:
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
    """The shortfalls a finished run carries: each one makes the status `DEGRADED`."""
    failed = [
        r for r in state.get("rejected", []) if r.get("reason") == "malformed output after repair"
    ]
    sections = [s["id"] for s in state.get("sections", []) if s.get("status") == "FAILED"]
    reasons = []
    if state.get("triage_fallback"):
        reasons.append(state["triage_fallback"])
    coverage = state.get("coverage") or {}
    if "stop_reason" in coverage:
        # The coverage loop accounts for every passage, a failed batch's included.
        failed = []
        left = degraded_reason(CoverageReport.model_validate(coverage))
        if left:
            reasons.append(left)
    if failed:
        reasons.append(f"{len(failed)} extraction batch(es) failed")
    for node in ("approach", "risk"):
        failure = (state.get(node) or {}).get("failure")
        if failure:
            reasons.append(f"{node}: {failure}")
    if sections:
        reasons.append(f"sections failed: {', '.join(sections)}")
    return "; ".join(reasons) or None


def run_prompts(config: Config) -> dict[str, Prompt]:
    """Each agent's pinned prompt, plus the EX0 baseline prompt."""
    prompts = {name: load_prompt_ref(agent.prompt) for name, agent in config.agents.agents.items()}
    prompts["extract_oneshot"] = load_prompt("extract_oneshot")
    prompts["extract_noexamples"] = load_prompt("extract_noexamples")
    return prompts


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
) -> RunResult:
    """Run one RFP end to end. A failed run still leaves its manifest and ledger.

    The profile's preconditions are checked first (`preflight.py`): a run that is refused
    leaves no folder, and `Refused` carries what to do instead. `limits` names the tier in
    `config/limits.yaml`; by default a corpus file gets its own tier, and any other file `dev`."""
    if baseline is not None and not BASELINES[baseline].llm:
        raise Refused(f"the {baseline} baseline needs the Iteration 1 graph, which step 16 builds")
    config = load_config()
    preflight = check_preconditions(
        source=source,
        profile=profile,
        mode=mode,
        consent=consent,
        backends=backends or {},
        config=config,
    )
    overrides = preflight.overrides
    used = {role.provider for role in config.models.profiles[profile].values()}
    run_backends = (
        {p: b for p, b in (backends or {}).items() if p in used} if mode != "replay" else {}
    )
    endpoint = trace_endpoint()
    refused = check_run(
        run_backends,
        endpoint,
        None,  # the v0.0 graph parses with pdfplumber; step 16 passes the Docling URL
        preflight.data_class,
        register=config.egress,
        consent=profile == "free" and consent == CONSENT,
    )
    started = datetime.now(UTC)
    suffix = f"-{baseline}" if baseline else ""
    run_id = run_id or f"{started:%Y%m%dT%H%M%SZ}-{doc_id_for(source)}-{profile}{suffix}"
    run_dir = outputs / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    client = LLMClient(
        config,
        profile,
        run_backends,
        mode=mode,
        cassettes=cassettes,
        run_id=run_id,
        limiter=Limiter(config.limits, tier_for(profile)) if mode != "replay" else None,
    )
    budget = RunBudget(config.limits.run(limits or preflight.tier, profile))
    prompts = run_prompts(config)
    tracing = Tracing(
        run_id,
        run_dir,
        None if refused else endpoint,
        os.environ.get("PHOENIX_API_KEY") or None,
    )
    ctx = RunContext(run_id, client, budget, prompts, {}, tracing=tracing)
    rt = Runtime(ctx, config, source, run_dir)
    if baseline is not None:
        chosen = BASELINES[baseline]
        rt.extract_prompt, rt.one_batch = chosen.extract_prompt, chosen.one_batch
    # Until the graph returns, the run has not finished: any exit this function does not name
    # below is recorded as a fault, never as COMPLETED.
    status: RunStatus = "UNRECOVERABLE_FAULT"
    reason: str | None = "the run ended before it finished"
    budget.start()
    run_attributes = {"bidwright.run_id": run_id, "bidwright.profile": profile}
    try:
        with (
            tracing.span("run", OpenInferenceSpanKindValues.CHAIN, **run_attributes),
            SqliteSaver.from_conn_string(str(run_dir / "checkpoints.sqlite")) as saver,
        ):
            graph = build_graph(rt, saver)
            final = graph.invoke(
                {},
                {
                    "configurable": {"thread_id": run_id},
                    "max_concurrency": config.limits.concurrency_for(profile),
                },
            )
        reason = _degraded(final)
        status = "DEGRADED" if reason else "COMPLETED"
    except BudgetExceeded as exc:
        status, reason = "BUDGET_EXCEEDED", str(exc)
    except QuotaExhausted as exc:
        status, reason = "QUOTA_PAUSED", f"{exc}; rerun after the quota resets"
    except (LLMError, RenderBlocked) as exc:
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
            # Nothing here may raise again and hide the run's own error: the manifest is the
            # record of the run, whatever happened.
            manifest = RunManifest(
                run_id=run_id,
                commit=_commit(),
                profile=profile,
                models={role: rc.model for role, rc in config.models.profiles[profile].items()},
                models_used=models_used(ctx.ledger),
                prompt_hashes={name: prompt.hash for name, prompt in prompts.items()},
                input_hashes={
                    source.name: f"sha256:{preflight.digest}"
                    if preflight.digest
                    else _file_hash(source)
                },
                started=started,
                ended=datetime.now(UTC),
                status=status,
                status_reason=reason,
                overrides=overrides,
                totals=totals_of(ctx.ledger, budget.active_seconds),
                data_class=preflight.data_class,
                refused_destinations=refused,
            )
            write_manifest(run_dir, manifest, ctx.ledger)
    return RunResult(run_id, run_dir, status, reason)
