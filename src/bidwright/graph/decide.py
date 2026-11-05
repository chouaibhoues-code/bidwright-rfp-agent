"""`decide` (Iteration 3, step 4; ADR-039, ADR-040): for each need of the RFP, an agent loop
chooses a decision and drafts at most three claims from the supplier's knowledge base.

`plan_needs` lists the needs: one per requirement group holding a `BINDING` or `OPTIONAL`
requirement, in group order, then one per need of the domain brief, at most the need cap a
run, `RFP` needs first; the rest are the plan's overflow, which the capability map lists as
`GAP` and which makes the run `DEGRADED`.

`decide_need` runs one need's loop through the agent's `ToolGateway`, at most 4 turns and 6
tool calls, ending at a turn that adds nothing new, then makes the final structured call.
`decide_fixed` is SO1-F's control: the same need with the evidence code retrieved, in one call
with no loop (`prompts/decide.md`'s `fixed` element). Both apply the same checks in code: an
evidence id is kept only when the need's loop (or code, in the fixed mode) received it from
the knowledge base, a passage id only when it belongs to the need's requirements or the loop
received it from `search_rfp` or `read_section`, a claim left with no passage is dropped, and
`RETRIEVE_EVIDENCE` with no claim becomes `PROCEED_WITH_GAP`. Each drop is named in the
outcome's notes.

`join` numbers the claims `CL-001` onward in need order, so the numbers do not depend on which
worker finished first, and the clarification questions after the brief's last `CQ-` id, with
origin `decide`. `write_decisions` writes `claims.jsonl` and `decisions.jsonl`, their one
writer. Context manifests name the need: `context/decide-<need id>-<turn>.json` and
`-final` (ADR-039's `UNIT_NODES`).
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes

from bidwright.config import AgentLimits, QuestionsConfig
from bidwright.graph.nodes import MALFORMED_TWICE, CallManifests, RunContext
from bidwright.harness.gateway import ToolGateway
from bidwright.kb import KnowledgeIndex
from bidwright.llm.schema import sha256_of
from bidwright.llm.types import Message
from bidwright.obs.tracing import set_attribute
from bidwright.research.pack import Pack, PackProvider, PackRefused, load_pack, packs_root
from bidwright.schemas import (
    CLAIM_TEXT_MAX_CHARS,
    DECIDE_REASON_MAX_CHARS,
    CapabilityClaim,
    ClaimProposal,
    ClarificationQuestion,
    DecideFixedTask,
    DecideResult,
    DecideTask,
    Decision,
    DomainBrief,
    EvidenceView,
    ExcerptView,
    NeedDecision,
    NeedRequirement,
    NeedView,
    PackManifest,
    Passage,
    PassageView,
    Requirement,
    RequirementGroup,
    ResearchRecord,
    ToolRequest,
    ToolResult,
)

NODE = "decide"
NEED_CAP_REASON = "not decided: the run's need cap"
PLANNED = frozenset({"BINDING", "OPTIONAL"})
FIXED_EVIDENCE = 5  # the knowledge-base hits SO1-F retrieves for a need
MAX_CITED = 3  # evidence ids, and passage ids, one claim may cite


@dataclass(frozen=True)
class NeedPlan:
    """The needs `decide` takes, in order; each need's passages, the ones its requirements
    cite; each need's records, for its context manifests; and the needs past the cap."""

    needs: list[NeedView]
    passages: dict[str, list[str]]
    records: dict[str, list[str]]
    overflow: list[NeedView]

    def degraded(self) -> str | None:
        if not self.overflow:
            return None
        return f"decide: {len(self.overflow)} needs past the need cap"


def plan_needs(
    groups: Sequence[RequirementGroup],
    requirements: Sequence[Requirement],
    domain: DomainBrief | None,
    *,
    cap: int,
    excerpts: Mapping[str, ExcerptView] | None = None,
) -> NeedPlan:
    """The run's needs, `RFP` first, at most `cap` to decide."""
    by_id = {r.id: r for r in requirements}
    excerpts = excerpts or {}
    needs: list[NeedView] = []
    passages: dict[str, list[str]] = {}
    records: dict[str, list[str]] = {}
    for group in groups:
        members = [by_id[m] for m in group.member_ids if m in by_id]
        if not any(r.disposition in PLANNED for r in members):
            continue
        context = [by_id[c] for c in group.context_ids if c in by_id]
        needs.append(
            NeedView(
                need_id=group.id,
                origin="RFP",
                topic=group.topic,
                requirements=[
                    NeedRequirement(
                        id=r.id,
                        statement=r.statement,
                        modality=r.modality,
                        quote=r.quote,
                        src_ids=list(r.src_ids),
                    )
                    for r in members
                ],
                discrepancy_ids=list(group.discrepancy_ids),
                question_ids=list(group.question_ids),
            )
        )
        passages[group.id] = list(dict.fromkeys(s for r in [*members, *context] for s in r.src_ids))
        records[group.id] = [r.id for r in members]
    for need in domain.needs if domain is not None else []:
        needs.append(
            NeedView(
                need_id=need.id,
                origin="DOMAIN",
                text=need.need,
                excerpts=[excerpts[e] for e in need.excerpt_ids if e in excerpts],
            )
        )
        passages[need.id] = []
        records[need.id] = [need.id, *need.excerpt_ids]
    return NeedPlan(needs[:cap], passages, records, needs[cap:])


# --- the checks code applies to an answer -------------------------------------------------


def cut(text: str, limit: int) -> str:
    """The text, cut at the last word boundary within `limit` characters."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    head = text[:limit]
    space = head.rfind(" ")
    return head[:space] if space > 0 else head


@dataclass
class DecideOutcome:
    need_id: str
    origin: str
    decision: Decision
    reason: str
    claims: list[ClaimProposal] = field(default_factory=list)
    gap: str | None = None
    question: str | None = None
    turns: int = 0
    tool_calls: int = 0
    stop_reason: str = ""
    notes: list[str] = field(default_factory=list)
    failure: str | None = None


def check(
    need: NeedView,
    result: DecideResult,
    *,
    evidence: Iterable[str],
    passages: Iterable[str],
    claims_cap: int,
) -> tuple[DecideOutcome, list[str]]:
    """The answer after code's checks (ADR-040), and the notes naming each drop. `evidence`
    holds the knowledge-base ids the loop received; `passages` the passage ids of the need's
    requirements and of the loop's RFP searches."""
    known_evidence, known_passages = set(evidence), set(passages)
    notes: list[str] = []
    claims: list[ClaimProposal] = []
    proposed = result.claims
    if len(proposed) > claims_cap:
        notes.append(f"{len(proposed) - claims_cap} claims past the cap of {claims_cap} dropped")
        proposed = proposed[:claims_cap]
    for n, claim in enumerate(proposed, start=1):
        text = cut(claim.text, CLAIM_TEXT_MAX_CHARS)
        if not text:
            notes.append(f"claim {n} has no text, dropped")
            continue
        kept_evidence = [e for e in dict.fromkeys(claim.evidence_ids) if e in known_evidence]
        for dropped in sorted(set(claim.evidence_ids) - known_evidence):
            notes.append(f"claim {n}: evidence id {dropped} was not returned by a search, dropped")
        kept_passages = [s for s in dict.fromkeys(claim.src_ids) if s in known_passages]
        for dropped in sorted(set(claim.src_ids) - known_passages):
            notes.append(f"claim {n}: passage id {dropped} is outside the need, dropped")
        if not kept_passages:
            notes.append(f"claim {n} cites no passage of the need, dropped")
            continue
        claims.append(
            ClaimProposal(
                kind=claim.kind,
                text=text,
                evidence_ids=kept_evidence[:MAX_CITED],
                src_ids=kept_passages[:MAX_CITED],
            )
        )
    decision: Decision = result.decision
    reason = cut(result.reason, DECIDE_REASON_MAX_CHARS)
    gap = cut(result.gap, CLAIM_TEXT_MAX_CHARS) if result.gap else None
    question = cut(result.question, CLAIM_TEXT_MAX_CHARS) if result.question else None
    if decision == "RETRIEVE_EVIDENCE" and not claims:
        notes.append("RETRIEVE_EVIDENCE with no claim left becomes PROCEED_WITH_GAP")
        decision = "PROCEED_WITH_GAP"
    if decision == "PROCEED_WITH_GAP" and not gap:
        gap = reason or "no claim with evidence for this need"
    if decision == "REQUEST_CLARIFICATION" and not question:
        notes.append("REQUEST_CLARIFICATION with no question becomes ABSTAIN")
        decision = "ABSTAIN"
    if decision == "ABSTAIN" and claims:
        notes.append(f"ABSTAIN drops its {len(claims)} claims")
        claims = []
    outcome = DecideOutcome(
        need_id=need.need_id,
        origin=need.origin,
        decision=decision,
        reason=reason,
        claims=claims,
        gap=gap if decision == "PROCEED_WITH_GAP" else None,
        question=question if decision == "REQUEST_CLARIFICATION" else None,
        notes=notes,
    )
    return outcome, notes


# --- the loop and the fixed control --------------------------------------------------------


def progress_keys(tool: str, result: ToolResult) -> list[str]:
    """What a tool result adds: knowledge-base ids, passage ids and excerpt ids."""
    if result.status != "OK":
        return []
    if tool == "search_capabilities" and isinstance(result.data, list):
        return [f"kb:{hit['id']}" for hit in result.data]
    if tool in ("search_rfp", "read_section") and isinstance(result.data, list):
        return [f"src:{hit['src_id']}" for hit in result.data]
    if tool == "ask_research" and isinstance(result.data, dict):
        return [f"px:{excerpt['id']}" for excerpt in result.data.get("excerpts", [])]
    return []


def _failed(need: NeedView, turns: int, calls: int, stop: str) -> DecideOutcome:
    return DecideOutcome(
        need_id=need.need_id,
        origin=need.origin,
        decision="ABSTAIN",
        reason="",
        turns=turns,
        tool_calls=calls,
        stop_reason=stop,
        notes=[f"decide: {MALFORMED_TWICE}"],
        failure=MALFORMED_TWICE,
    )


def decide_need(
    ctx: RunContext,
    need: NeedView,
    gateway: ToolGateway,
    limits: AgentLimits,
    *,
    passages: Sequence[str],
    records: Sequence[str],
    claims_cap: int,
    manifests: CallManifests | None = None,
) -> DecideOutcome:
    """One need's loop and final call. Its calls are `<need id>-<turn>`, then
    `<need id>-final` and a format repair `<need id>-final-repair`."""
    prompt = ctx.prompts[NODE]
    data = DecideTask(need=need).model_dump_json()
    rendered = prompt.render(data, run_id=ctx.run_id)
    messages = list(rendered.messages)
    specs = [tool.spec for tool in gateway.specs()]
    seen: set[str] = set()
    evidence: list[str] = []
    found: list[str] = list(passages)

    def record(call_id: str, history: Sequence[Message]) -> None:
        if manifests is not None:
            turns = history[len(rendered.messages) :]
            manifests.record(prompt, NODE, call_id, records, data, turns, found)

    transcript: list[Any] = []
    stop_reason, turns = "turn_cap", 0
    for turn in range(1, (limits.max_turns or 4) + 1):
        turns = turn
        record(f"{need.need_id}-{turn}", messages)
        completion = ctx.call(
            prompt,
            messages,
            None,
            node=NODE,
            tools=specs,
            input_hash=sha256_of([rendered.input_hash, transcript]),
        )
        messages.append(completion.as_message())
        if not completion.tool_calls:
            stop_reason = "answered"
            break
        progress = False
        for call in completion.tool_calls:
            request = ToolRequest(tool=call.name, args=call.arguments, agent=NODE, turn=turn)
            attributes = {SpanAttributes.TOOL_NAME: call.name, "bidwright.turn": turn}
            with ctx.span(
                f"tool.{call.name}", OpenInferenceSpanKindValues.TOOL, **attributes
            ) as span:
                result = gateway.call(request)
                set_attribute(span, "bidwright.tool_status", result.status)
            transcript.append([call.name, call.arguments, result.model_dump()])
            for key in progress_keys(call.name, result):
                kind, _, value = key.partition(":")
                if kind == "kb" and value not in evidence:
                    evidence.append(value)
                if kind == "src" and value not in found:
                    found.append(value)
                if key not in seen:
                    seen.add(key)
                    progress = True
            messages.append(
                Message("tool", result.model_dump_json(), tool_call_id=call.id, name=call.name)
            )
        if limits.stop_on_no_progress and not progress:
            stop_reason = "no_progress"
            break
        if limits.max_tool_calls is not None and gateway.executed >= limits.max_tool_calls:
            stop_reason = "tool_cap"
            break
    final = [*messages, Message("user", prompt.task_text("final_task"))]
    record(f"{need.need_id}-final", final)
    parsed, _ = ctx.structured(
        prompt,
        final,
        DecideResult,
        node=NODE,
        input_hash=sha256_of([rendered.input_hash, transcript, "final"]),
        on_repair=lambda sent: record(f"{need.need_id}-final-repair", sent),
    )
    calls = len(gateway.calls)
    if not isinstance(parsed, DecideResult):
        return _failed(need, turns, calls, stop_reason)
    outcome, _ = check(need, parsed, evidence=evidence, passages=found, claims_cap=claims_cap)
    outcome.turns, outcome.tool_calls, outcome.stop_reason = turns, calls, stop_reason
    return outcome


def fixed_evidence(
    index: KnowledgeIndex, need: NeedView, k: int = FIXED_EVIDENCE
) -> list[EvidenceView]:
    """SO1-F's retrieval: the top hits for the need's topic and statements, or a domain need's
    text."""
    words = (
        [need.topic, *(r.statement for r in need.requirements)]
        if need.origin == "RFP"
        else [need.text]
    )
    return [
        EvidenceView(id=hit.id, kind=hit.kind, name=hit.name, text=hit.text)
        for hit in index.search(" ".join(words), k)
    ]


def need_passages(
    ids: Sequence[str], passages: Mapping[str, Passage], view: Any = None
) -> list[PassageView]:
    """The need's own passages, as the run's text view shows them."""
    from bidwright.ingest import display_text

    out = []
    for src_id in ids:
        passage = passages.get(src_id)
        if passage is None:
            continue
        text = view.text(passage) if view is not None else display_text(passage.text)
        out.append(PassageView(src_id=src_id, section_path=passage.section_path, text=text))
    return out


def decide_fixed(
    ctx: RunContext,
    need: NeedView,
    evidence: Sequence[EvidenceView],
    passages: Sequence[PassageView],
    *,
    records: Sequence[str],
    claims_cap: int,
    manifests: CallManifests | None = None,
) -> DecideOutcome:
    """SO1-F: one call with the evidence code retrieved, `<need id>-fixed`, and a format
    repair `<need id>-fixed-repair`."""
    prompt = ctx.prompts[NODE]
    task = DecideFixedTask(need=need, evidence=list(evidence), passages=list(passages))
    data = task.model_dump_json()
    rendered = prompt.render(data, run_id=ctx.run_id, task="fixed")
    src_ids = [p.src_id for p in passages]

    def record(call_id: str, history: Sequence[Message]) -> None:
        if manifests is not None:
            turns = history[len(rendered.messages) :]
            manifests.record(prompt, NODE, call_id, records, data, turns, src_ids)

    record(f"{need.need_id}-fixed", rendered.messages)
    parsed, _ = ctx.structured(
        prompt,
        list(rendered.messages),
        DecideResult,
        node=NODE,
        input_hash=rendered.input_hash,
        on_repair=lambda sent: record(f"{need.need_id}-fixed-repair", sent),
    )
    if not isinstance(parsed, DecideResult):
        return _failed(need, 0, 0, "fixed")
    known = [s for r in need.requirements for s in r.src_ids] + src_ids
    outcome, _ = check(
        need, parsed, evidence=[e.id for e in evidence], passages=known, claims_cap=claims_cap
    )
    outcome.stop_reason = "fixed"
    return outcome


# --- the join ------------------------------------------------------------------------------


@dataclass(frozen=True)
class DecideJoin:
    claims: list[CapabilityClaim]
    decisions: list[NeedDecision]
    questions: list[ClarificationQuestion]

    def degraded(self) -> str | None:
        failed = [d.need_id for d in self.decisions if f"decide: {MALFORMED_TWICE}" in d.notes]
        return f"decide: {len(failed)} needs failed" if failed else None


def question_number(questions: Iterable[ClarificationQuestion]) -> int:
    """The number of the run's last `CQ-` question, 0 with none."""
    numbers = [int(q.id.split("-")[1]) for q in questions]
    return max(numbers, default=0)


def join(
    outcomes: Sequence[DecideOutcome],
    plan: NeedPlan,
    *,
    last_question: int,
) -> DecideJoin:
    """Claims and questions numbered in need order, whatever order the workers ended in."""
    order = {need.need_id: n for n, need in enumerate(plan.needs)}
    needs = {need.need_id: need for need in plan.needs}
    claims: list[CapabilityClaim] = []
    decisions: list[NeedDecision] = []
    questions: list[ClarificationQuestion] = []
    for outcome in sorted(outcomes, key=lambda o: order.get(o.need_id, len(order))):
        need = needs[outcome.need_id]
        ids = []
        for claim in outcome.claims:
            claim_id = f"CL-{len(claims) + 1:03d}"
            claims.append(
                CapabilityClaim(
                    id=claim_id,
                    need_id=outcome.need_id,
                    kind=claim.kind,
                    text=claim.text,
                    evidence_ids=claim.evidence_ids,
                    src_ids=claim.src_ids,
                )
            )
            ids.append(claim_id)
        question = None
        if outcome.question:
            question = ClarificationQuestion(
                id=f"CQ-{last_question + len(questions) + 1:03d}",
                group_id=outcome.need_id if outcome.origin == "RFP" else None,
                text=outcome.question,
                requirement_ids=[r.id for r in need.requirements],
                src_ids=list(dict.fromkeys(s for r in need.requirements for s in r.src_ids)),
                origin="decide",
            )
            questions.append(question)
        decisions.append(
            NeedDecision(
                need_id=outcome.need_id,
                origin=need.origin,
                decision=outcome.decision,
                reason=outcome.reason,
                claim_ids=ids,
                gap=outcome.gap,
                question=question,
                turns=outcome.turns,
                tool_calls=outcome.tool_calls,
                stop_reason=outcome.stop_reason,
                notes=outcome.notes,
            )
        )
    return DecideJoin(claims, decisions, questions)


def write_decisions(run_dir: Path, joined: DecideJoin) -> None:
    """`claims.jsonl` and `decisions.jsonl`, written by this function only."""
    for name, rows in (("claims.jsonl", joined.claims), ("decisions.jsonl", joined.decisions)):
        body = "".join(
            json.dumps(r.model_dump(mode="json"), ensure_ascii=False) + "\n" for r in rows
        )
        (run_dir / name).write_text(body, encoding="utf-8", newline="\n")


# --- ask_research from the run's own research (section 4.2) --------------------------------


def record_pack(record: ResearchRecord, run_dir: Path) -> Pack:
    """A pack over the answers, excerpts and sources a live run's `research.json` holds, so
    `decide` asks a `PackProvider` with ADR-034's rule and never a research server."""
    manifest = PackManifest(
        domain_id="live-research",
        title="The research this run gathered",
        version=1,
        created=date(2026, 11, 5),  # fixed, so the pack never depends on the day
        keywords=["live", "research"],
        files={},
    )
    return Pack(
        path=run_dir,
        manifest=manifest,
        sha256="",
        summary="",
        sources=list(record.sources),
        excerpts=list(record.excerpts),
        answers=list(record.answers),
        domain_brief=DomainBrief(mode="live"),
    )


def research_provider(
    mode: str,
    record: ResearchRecord | None,
    *,
    packs_dir: str | Path,
    questions: QuestionsConfig,
    patterns: Sequence[Any],
    run_dir: Path,
) -> tuple[PackProvider | None, str | None]:
    """The provider behind `decide`'s `ask_research`, and a note when it is not offered: the
    pack `discover_load` loaded in research mode `pack`, the run's own research in `live`, and
    none in `off`, or when the pack changed since it was loaded."""
    if mode == "off" or record is None:
        return None, None
    if mode == "live":
        return PackProvider(record_pack(record, run_dir), questions), None
    if record.pack_id is None:
        return None, None
    try:
        pack = load_pack(packs_root(packs_dir) / record.pack_id, patterns)
    except PackRefused as exc:
        return None, f"decide: ask_research is not offered: {exc}"
    if pack.sha256 != record.pack_sha256:
        return None, (
            f"decide: the research pack {record.pack_id} changed since discover loaded it, so"
            " ask_research is not offered"
        )
    return PackProvider(pack, questions), None
