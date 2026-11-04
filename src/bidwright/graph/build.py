"""Wire the 0a nodes into a LangGraph graph, and run one RFP through it.

ingest -> extract (one `Send` per batch, at most `concurrency` at once) -> verify -> approach
-> risk -> draft -> render, with no branches. The SQLite checkpointer keeps each step's state
in the run folder. The LLM client, budget, prompts and search index stay outside the state, in
`Runtime`, so a checkpoint holds plain data only. Each node writes its own files; `render`
writes the summary, the proposal, the manifest and the ledger.
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
from bidwright.config import Config, load_config
from bidwright.graph.nodes import (
    BatchOutcome,
    RunContext,
    approach,
    assign_requirements,
    batches,
    draft,
    extract_batch,
    risk,
    section_records,
)
from bidwright.graph.state import BatchState, RunState
from bidwright.harness.budget import BudgetExceeded, RunBudget
from bidwright.harness.gateway import ToolGateway
from bidwright.ingest import doc_id_for, ingest_pdf
from bidwright.llm.client import LLMClient, Mode
from bidwright.llm.replay import CassetteStore
from bidwright.llm.types import Backend, LLMError, QuotaExhausted
from bidwright.obs.ledger import models_used, totals_of
from bidwright.obs.tracing import Tracing, maybe_span, set_attribute
from bidwright.preflight import Refused, check_preconditions
from bidwright.prompts import Prompt, load_prompt, load_prompt_ref
from bidwright.render import RenderBlocked, RunRecords, render, write_manifest
from bidwright.retrieval import PassageIndex
from bidwright.schemas import (
    ApproachItem,
    ExtractItem,
    OpenQuestion,
    Passage,
    ProposalSection,
    Requirement,
    Risk,
    RunManifest,
    RunStatus,
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
    return BatchOutcome(data["batch_id"], accepted, data["rejected"], data["no_obligation"])


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
        rt.index = PassageIndex.build(result.passages, rt.run_dir / "search.sqlite")
        size = len(result.passages) if rt.one_batch else rt.config.limits.batch_size
        groups = batches(result.passages, max(size, 1))
        title = next((p.section_path for p in result.passages if p.section_path), result.doc_id)
        return {
            "doc_id": result.doc_id,
            "title": title.split(" > ")[0],
            "passages": [p.model_dump() for p in result.passages],
            "batches": [
                {"batch_id": f"B{n:02d}", "ids": [p.id for p in group]}
                for n, group in enumerate(groups, start=1)
            ],
        }

    def fan_out(state: RunState) -> list[Send]:
        return [
            Send("extract", {"batch_id": b["batch_id"], "ids": b["ids"]}) for b in state["batches"]
        ]

    def extract_node(state: BatchState) -> dict[str, Any]:
        chosen = [ctx.passages[i] for i in state["ids"]]
        outcome = extract_batch(ctx, chosen, state["batch_id"], rt.extract_prompt)
        return {"outcomes": [_outcome_dict(outcome)]}

    def verify_node(state: RunState) -> dict[str, Any]:
        outcomes = sorted((_outcome(o) for o in state["outcomes"]), key=lambda o: o.batch_id)
        requirements, rejected = assign_requirements(outcomes, passages(state), state["doc_id"])
        rows = [r.model_dump(mode="json") for r in requirements]
        _jsonl(rt.run_dir / "requirements.jsonl", rows)
        _jsonl(rt.run_dir / "rejected.jsonl", rejected)
        return {"requirements": rows, "rejected": rejected}

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
    builder.add_node("extract", traced("extract", extract_node), input_schema=BatchState)
    builder.add_node("verify", traced("verify", verify_node))
    builder.add_node("approach", traced("approach", approach_node))
    builder.add_node("risk", traced("risk", risk_node))
    builder.add_node("draft", traced("draft", draft_node))
    builder.add_node("render", traced("render", render_node))
    builder.add_edge(START, "ingest")
    builder.add_conditional_edges("ingest", fan_out, ["extract"])
    builder.add_edge("extract", "verify")
    for first, second in (("verify", "approach"), ("approach", "risk"), ("risk", "draft")):
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
    started = datetime.now(UTC)
    suffix = f"-{baseline}" if baseline else ""
    run_id = run_id or f"{started:%Y%m%dT%H%M%SZ}-{doc_id_for(source)}-{profile}{suffix}"
    run_dir = outputs / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    client = LLMClient(
        config,
        profile,
        backends if mode != "replay" else {},
        mode=mode,
        cassettes=cassettes,
        run_id=run_id,
    )
    budget = RunBudget(config.limits.run(limits or preflight.tier, profile))
    prompts = run_prompts(config)
    tracing = Tracing(
        run_id,
        run_dir,
        os.environ.get("PHOENIX_ENDPOINT") or None,
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
            )
            write_manifest(run_dir, manifest, ctx.ledger)
    return RunResult(run_id, run_dir, status, reason)
