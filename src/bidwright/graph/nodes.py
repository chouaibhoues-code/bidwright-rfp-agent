"""The Iteration 0a nodes: extract, verify, approach, risk and draft.

Each node is a plain function over typed inputs, so it runs and tests without the graph;
`build.py` wires them into LangGraph. Every LLM call goes through `RunContext.call`, which
checks the run budget before each provider attempt and records the ledger entry. Each node
allows one repair: a targeted one for quotes, missing ids or generic risks, or a format one
for a response that breaks its schema. Whatever still fails is rejected and logged, never
accepted: `extract` rejects the batch, `draft` marks the section `FAILED`, and `approach` and
`risk` return an empty result with the reason, so the run ends `DEGRADED` with its verified
requirements in the summary (ADR-024).
"""

import json
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes
from pydantic import BaseModel

from bidwright.config import AgentLimits
from bidwright.harness.budget import RunBudget
from bidwright.harness.gateway import ToolGateway
from bidwright.ingest import display_text
from bidwright.llm.client import Completion, LLMClient
from bidwright.llm.schema import sha256_of
from bidwright.llm.types import Message
from bidwright.obs.tracing import Tracing, maybe_span, record_llm, set_attribute
from bidwright.prompts import Prompt
from bidwright.schemas import (
    ApproachInput,
    ApproachItem,
    ApproachItemView,
    ApproachResult,
    DraftResult,
    DraftTask,
    ExtractBatch,
    ExtractItem,
    ExtractResult,
    LedgerEntry,
    OpenQuestion,
    Passage,
    PassageView,
    ProposalSection,
    Requirement,
    RequirementView,
    Risk,
    RiskInput,
    RiskProposal,
    RiskRegister,
    ToolRequest,
    ToolResult,
)
from bidwright.verify import QuoteCheck, check_quote

PREDICTIONS = ("BINDING", "OPTIONAL")
RATING_WORDS = frozenset(
    "high medium low moderate minor major critical severe negligible significant".split()
)
# A rating stated in words: an exposure that opens with a scale level ("Low if tested
# early"), or a level attached to risk, exposure or similar ("remains a medium risk"). Words
# such as "lower" or "highly" do not match.
RATING_PHRASE = re.compile(
    r"^(?:very |fairly |relatively |quite )?(?:high|medium|low|moderate|negligible)\b"
    r"|\b(?:high|medium|low|moderate)(?:[- ](?:to[- ])?(?:high|medium|low))?"
    r" (?:risk|exposure|likelihood|impact|probability|severity)\b",
    re.IGNORECASE,
)
PROBABILITY = re.compile(
    r"(probability|likelihood|chance)\W{0,3}(of\W+)?(is\W+)?\d"
    r"|\d+(\.\d+)?\s*%\s*(probability|likelihood|chance)",
    re.IGNORECASE,
)
STOPWORDS = frozenset(
    """that this with from have will shall must should which their there these those would
    could about into than then them they been being were what when where also each only other
    such some more most very over under after before until while within without because upon
    between during against through every""".split()
)


MALFORMED_TWICE = "malformed output twice"


@dataclass
class RunContext:
    run_id: str
    client: LLMClient
    budget: RunBudget
    prompts: dict[str, Prompt]
    passages: dict[str, Passage]
    ledger: list[LedgerEntry] = field(default_factory=list)
    tracing: Tracing | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self.client.on_ledger = self.record
        self.client.before_attempt = self.budget.check

    def record(self, entry: LedgerEntry) -> None:
        with self._lock:
            self.ledger.append(entry)
            self.budget.record(entry)

    def span(self, name: str, kind: OpenInferenceSpanKindValues, **attributes: Any) -> Any:
        return maybe_span(self.tracing, name, kind, **attributes)

    def call(
        self,
        prompt: Prompt,
        messages: Sequence[Message],
        schema: type[BaseModel] | None,
        *,
        node: str,
        input_hash: str,
        tools: Sequence[Any] = (),
        repeat: int = 0,
    ) -> Completion:
        self.budget.check()
        attributes = {
            "bidwright.node": node,
            "bidwright.prompt": prompt.ref,
            "bidwright.prompt_hash": prompt.hash,
            "bidwright.input_hash": input_hash,
        }
        with self.span(f"llm.{node}", OpenInferenceSpanKindValues.LLM, **attributes) as span:
            completion = self.client.complete(
                prompt.meta.role,
                messages,
                schema,
                tools or None,
                node=node,
                agent=prompt.meta.id,
                prompt_hash=prompt.hash,
                input_hash=input_hash,
                repeat=repeat,
                decoding=prompt.decoding,
            )
            with self._lock:
                entry = next((e for e in reversed(self.ledger) if e.input_hash == input_hash), None)
            if entry is not None:
                record_llm(span, entry)
            set_attribute(span, "bidwright.parse_error", completion.parse_error and "yes")
            return completion

    def structured(
        self,
        prompt: Prompt,
        messages: Sequence[Message],
        schema: type[BaseModel],
        *,
        node: str,
        input_hash: str,
    ) -> tuple[BaseModel | None, list[Message]]:
        """One call, and one format repair if the answer breaks the schema."""
        first = self.call(prompt, messages, schema, node=node, input_hash=input_hash)
        history = [*messages, first.as_message()]
        if first.parsed is not None:
            return first.parsed, history
        repair = prompt.task_text("repair_format", error=_short(first.parse_error))
        history.append(Message("user", repair))
        second = self.call(
            prompt, history, schema, node=node, input_hash=sha256_of([input_hash, repair])
        )
        return second.parsed, [*history, second.as_message()]


def _short(error: str | None, limit: int = 400) -> str:
    text = " ".join((error or "unknown error").split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


# --- extract and verify -------------------------------------------------------------------


@dataclass
class BatchOutcome:
    batch_id: str
    accepted: list[tuple[ExtractItem, QuoteCheck]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    no_obligation: list[str] = field(default_factory=list)


def batches(passages: Sequence[Passage], size: int) -> list[list[Passage]]:
    return [list(passages[i : i + size]) for i in range(0, len(passages), size)]


def extract_batch(
    ctx: RunContext, batch: Sequence[Passage], batch_id: str, prompt_id: str = "extract"
) -> BatchOutcome:
    """Extract one batch, verify every quote, and repair once what failed or is missing."""
    prompt = ctx.prompts[prompt_id]
    view = ExtractBatch(
        batch_id=batch_id,
        passages=[
            PassageView(
                src_id=p.id,
                section_path=p.section_path,
                text=display_text(p.text),
                lead_in=display_text(ctx.passages[p.lead_in_id].text) if p.lead_in_id else None,
            )
            for p in batch
        ],
    )
    rendered = prompt.render(view.model_dump_json(), run_id=ctx.run_id, batch_id=batch_id)
    first = ctx.call(
        prompt, rendered.messages, ExtractResult, node="extract", input_hash=rendered.input_hash
    )
    history = [*rendered.messages, first.as_message()]
    ids = [p.id for p in batch]
    outcome = BatchOutcome(batch_id)
    result = first.parsed
    if not isinstance(result, ExtractResult):
        repair = prompt.task_text("repair_format", error=_short(first.parse_error))
        second = ctx.call(
            prompt,
            [*history, Message("user", repair)],
            ExtractResult,
            node="extract",
            input_hash=sha256_of([rendered.input_hash, repair]),
        )
        if not isinstance(second.parsed, ExtractResult):
            outcome.rejected.append(_rejection(batch_id, ids, "", "malformed output after repair"))
            return outcome
        settle(outcome, second.parsed.items, ctx.passages, ids, final=True)
        _account(outcome, second.parsed.no_obligation_src_ids, ids)
        return outcome
    failed = settle(outcome, result.items, ctx.passages, ids, final=False)
    outcome.no_obligation += [s for s in result.no_obligation_src_ids if s in ids]
    missing = [s for s in ids if s not in _accounted(outcome, failed)]
    if not failed and not missing:
        return outcome
    parts = []
    if failed:
        pairs = [[item.src_ids[0] if item.src_ids else "", item.quote] for item in failed]
        parts.append(prompt.task_text("repair_quotes", failures=json.dumps(pairs)))
    if missing:
        parts.append(prompt.task_text("repair_missing", missing=json.dumps(missing)))
    parts.append(prompt.task_text("repair_close"))
    repair = " ".join(parts)
    second = ctx.call(
        prompt,
        [*history, Message("user", repair)],
        ExtractResult,
        node="extract",
        input_hash=sha256_of([rendered.input_hash, repair]),
    )
    repaired = (
        second.parsed if isinstance(second.parsed, ExtractResult) else ExtractResult(items=[])
    )
    _merge_repair(outcome, failed, missing, repaired, ctx.passages, ids)
    return outcome


def _rejection(batch_id: str, src_ids: list[str], quote: str, reason: str) -> dict[str, Any]:
    return {"batch_id": batch_id, "src_ids": src_ids, "quote": quote, "reason": reason}


def _check(item: ExtractItem, passages: Mapping[str, Passage], ids: list[str]) -> QuoteCheck:
    cited = [passages[s] for s in item.src_ids if s in ids]
    if not cited:
        return QuoteCheck("REJECTED", reason="cites no passage of the batch")
    return check_quote(item.quote, cited)


def settle(
    outcome: BatchOutcome,
    items: Sequence[ExtractItem],
    passages: Mapping[str, Passage],
    ids: list[str],
    *,
    final: bool,
) -> list[ExtractItem]:
    """Accept verified items. Failures are returned for repair, or rejected when final.

    A quote counts only against the passages of its own batch (`ids`), and an id from outside
    the batch is dropped from the item, so a requirement never cites a passage its batch did
    not show the model."""
    failed = []
    for item in items:
        if not item.quote.strip():
            outcome.rejected.append(_rejection(outcome.batch_id, item.src_ids, "", "withdrawn"))
            continue
        kept = [s for s in item.src_ids if s in ids]
        if kept and kept != item.src_ids:
            item = item.model_copy(update={"src_ids": kept})
        check = _check(item, passages, ids)
        if check.status != "REJECTED":
            outcome.accepted.append((item, check))
        elif final:
            reason = check.reason or "not found"
            outcome.rejected.append(_rejection(outcome.batch_id, item.src_ids, item.quote, reason))
        else:
            failed.append(item)
    return failed


def _accounted(outcome: BatchOutcome, pending: Sequence[ExtractItem] = ()) -> set[str]:
    cited = {s for item, _ in outcome.accepted for s in item.src_ids}
    cited |= {s for entry in outcome.rejected for s in entry["src_ids"]}
    cited |= {s for item in pending for s in item.src_ids}
    return cited | set(outcome.no_obligation)


def _account(outcome: BatchOutcome, no_obligation: Sequence[str], ids: list[str]) -> None:
    outcome.no_obligation += [s for s in no_obligation if s in ids]
    for missing in [s for s in ids if s not in _accounted(outcome)]:
        outcome.rejected.append(_rejection(outcome.batch_id, [missing], "", "unaccounted"))


def _merge_repair(
    outcome: BatchOutcome,
    failed: list[ExtractItem],
    missing: list[str],
    repaired: ExtractResult,
    passages: Mapping[str, Passage],
    ids: list[str],
) -> None:
    pool = list(repaired.items)
    for item in failed:
        first_id = item.src_ids[0] if item.src_ids else None
        match = next((r for r in pool if r.src_ids and r.src_ids[0] == first_id), None)
        if match is None:
            outcome.rejected.append(
                _rejection(outcome.batch_id, item.src_ids, item.quote, "not repaired")
            )
            continue
        pool.remove(match)
        settle(outcome, [match], passages, ids, final=True)
    added = [r for r in pool if set(r.src_ids) & set(missing)]
    settle(outcome, added, passages, ids, final=True)
    _account(outcome, [s for s in repaired.no_obligation_src_ids if s in missing], ids)


def assign_requirements(
    outcomes: Sequence[BatchOutcome], passages: Sequence[Passage], doc_id: str
) -> tuple[list[Requirement], list[dict[str, Any]]]:
    """The fan-in after extract: number verified items in reading order as requirements."""
    order = {p.id: n for n, p in enumerate(passages)}
    accepted = [entry for outcome in outcomes for entry in outcome.accepted]
    accepted.sort(key=lambda e: (order[e[1].src_id or ""], (e[1].span or (0, 0))[0]))
    requirements = []
    for number, (item, check) in enumerate(accepted, start=1):
        cited = [check.src_id] + [s for s in item.src_ids if s != check.src_id and s in order]
        requirements.append(
            Requirement(
                id=f"REQ-{number:04d}",
                doc_id=doc_id,
                statement=item.statement,
                modality=item.modality,
                mandatory=item.disposition == "BINDING",
                hazard=item.hazard,
                disposition=item.disposition,
                src_ids=[s for s in cited if s][:3],
                quote=item.quote,
                quote_status=check.status,
                quote_span=check.span,
            )
        )
    rejected = [entry for outcome in outcomes for entry in outcome.rejected]
    return requirements, rejected


def predictions(requirements: Sequence[Requirement]) -> list[Requirement]:
    """The records the later nodes and the summary use: BINDING and OPTIONAL ones."""
    return [r for r in requirements if r.disposition in PREDICTIONS]


def requirement_views(requirements: Sequence[Requirement]) -> list[RequirementView]:
    return [
        RequirementView(
            id=r.id,
            statement=r.statement,
            modality=r.modality,
            mandatory=r.mandatory,
            hazard=r.hazard,
        )
        for r in requirements
    ]


# --- approach -------------------------------------------------------------------------------


@dataclass
class ApproachOutcome:
    items: list[ApproachItem]
    unmapped: list[str]
    questions: list[OpenQuestion]
    failure: str | None = None  # set when the node gave up, and the run ends DEGRADED


def approach(ctx: RunContext, requirements: Sequence[Requirement]) -> ApproachOutcome:
    """The first `blueprint`: approach items mapped to requirement ids."""
    prompt = ctx.prompts["approach"]
    chosen = predictions(requirements)
    by_id = {r.id: r for r in chosen}
    view = ApproachInput(requirements=requirement_views(chosen))
    rendered = prompt.render(view.model_dump_json(), run_id=ctx.run_id)
    parsed, _ = ctx.structured(
        prompt, rendered.messages, ApproachResult, node="approach", input_hash=rendered.input_hash
    )
    if not isinstance(parsed, ApproachResult):
        # The requirements are complete and verified by now: keep them, and let the summary
        # show every requirement as unmapped rather than lose the run.
        return ApproachOutcome([], [r.id for r in chosen], [], failure=MALFORMED_TWICE)
    items = []
    for proposal in parsed.items:
        kept = [i for i in proposal.requirement_ids if i in by_id]
        if not kept:
            continue
        items.append(
            ApproachItem(
                id=f"APP-{len(items) + 1:03d}",
                text=proposal.text,
                requirement_ids=kept,
                basis=proposal.basis,
                evidence_class="ASSUMPTION",
                source_ids=sorted({s for i in kept for s in by_id[i].src_ids}),
            )
        )
    mapped = {i for item in items for i in item.requirement_ids}
    unmapped = [r.id for r in chosen if r.id not in mapped]
    questions = []
    for question in parsed.open_questions:
        src_ids = sorted(
            {s for i in question.requirement_ids if i in by_id for s in by_id[i].src_ids}
        )
        questions.append(OpenQuestion(text=question.text, src_ids=src_ids))
    return ApproachOutcome(items, unmapped, questions)


# --- risk -----------------------------------------------------------------------------------


@dataclass
class RiskOutcome:
    risks: list[Risk]
    questions: list[OpenQuestion]
    rejected: list[dict[str, Any]]
    stop_reason: str
    turns: int
    failure: str | None = None  # set when the node gave up, and the run ends DEGRADED


def risk(
    ctx: RunContext,
    requirements: Sequence[Requirement],
    approach_items: Sequence[ApproachItem],
    gateway: ToolGateway,
    limits: AgentLimits,
) -> RiskOutcome:
    """A tool loop of at most `max_turns` turns, then a final structured call with no tools."""
    prompt = ctx.prompts["risk"]
    chosen = predictions(requirements)
    view = RiskInput(
        requirements=requirement_views(chosen),
        approach=[
            ApproachItemView(id=a.id, text=a.text, requirement_ids=a.requirement_ids)
            for a in approach_items
        ],
        hazards=[r.id for r in chosen if r.hazard],
    )
    rendered = prompt.render(view.model_dump_json(), run_id=ctx.run_id)
    messages = list(rendered.messages)
    specs = [tool.spec for tool in gateway.specs()]
    seen: set[str] = set()
    transcript: list[Any] = []
    stop_reason, turns = "turn_cap", 0
    max_turns = limits.max_turns or 4
    for turn in range(1, max_turns + 1):
        turns = turn
        completion = ctx.call(
            prompt,
            messages,
            None,
            node="risk",
            tools=specs,
            input_hash=sha256_of([rendered.input_hash, transcript]),
        )
        messages.append(completion.as_message())
        if not completion.tool_calls:
            stop_reason = "answered"
            break
        progress = False
        for call in completion.tool_calls:
            request = ToolRequest(tool=call.name, args=call.arguments, agent="risk", turn=turn)
            tool_attributes = {SpanAttributes.TOOL_NAME: call.name, "bidwright.turn": turn}
            with ctx.span(
                f"tool.{call.name}", OpenInferenceSpanKindValues.TOOL, **tool_attributes
            ) as span:
                result = gateway.call(request)
                set_attribute(span, "bidwright.tool_status", result.status)
            transcript.append([call.name, call.arguments, result.model_dump()])
            for key in _progress_keys(call.name, result):
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
    base = sha256_of([rendered.input_hash, transcript, "final"])
    parsed, history = ctx.structured(prompt, final, RiskRegister, node="risk", input_hash=base)
    if not isinstance(parsed, RiskRegister):
        return RiskOutcome([], [], [], stop_reason, turns, failure=MALFORMED_TWICE)
    accepted, rejected = _screen(parsed.risks, ctx.passages)
    if rejected:
        reasons = json.dumps([[entry["event"], entry["reason"]] for entry in rejected])
        retry = [*history, Message("user", prompt.task_text("repair_generic", rejected=reasons))]
        second = ctx.call(
            prompt, retry, RiskRegister, node="risk", input_hash=sha256_of([base, reasons])
        )
        if isinstance(second.parsed, RiskRegister):
            parsed = second.parsed
            accepted, rejected = _screen(parsed.risks, ctx.passages)
    risks = [
        Risk(
            id=f"RSK-{n:03d}",
            **proposal.model_dump(exclude={"evidence_src_ids"}),
            evidence_src_ids=ids,
        )
        for n, (proposal, ids) in enumerate(accepted, start=1)
    ]
    questions = [
        OpenQuestion(text=q.text, src_ids=[s for s in q.src_ids if s in ctx.passages])
        for q in parsed.open_questions
    ]
    return RiskOutcome(risks, questions, rejected, stop_reason, turns)


def _progress_keys(tool: str, result: ToolResult) -> list[str]:
    if result.status != "OK":
        return []
    if tool == "search_rfp" and isinstance(result.data, list):
        return [hit["src_id"] for hit in result.data]
    if tool == "date_calc" and isinstance(result.data, dict):
        return [f"date:{json.dumps(result.data.get('result'))}"]
    return []


def _content_stems(text: str) -> set[str]:
    words = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", text)} - STOPWORDS
    return {w[:6] for w in words}


def _screen(
    proposals: Sequence[RiskProposal], passages: dict[str, Passage]
) -> tuple[list[tuple[RiskProposal, list[str]]], list[dict[str, Any]]]:
    """Reject generic risks, and risks that carry a rating or a probability."""
    accepted, rejected = [], []
    for proposal in proposals:
        evidence = [s for s in proposal.evidence_src_ids if s in passages]
        cited = " ".join(display_text(passages[s].text) for s in evidence)
        shared = _content_stems(f"{proposal.condition} {proposal.event}") & _content_stems(cited)
        exposure = proposal.residual_exposure.strip().lower().rstrip(".")
        everything = " ".join([proposal.condition, proposal.event, proposal.effect, exposure])
        if not evidence:
            reason = "generic: cites no passage"
        elif not shared:
            reason = "generic: shares no content word with the passages it cites"
        elif (
            exposure in RATING_WORDS
            or RATING_PHRASE.search(exposure)
            or PROBABILITY.search(everything)
        ):
            reason = "carries a rating or a probability"
        else:
            accepted.append((proposal, evidence))
            continue
        rejected.append({"event": proposal.event, "evidence_src_ids": evidence, "reason": reason})
    return accepted, rejected


# --- draft ----------------------------------------------------------------------------------

SECTION_TITLES = {
    "understanding": "Our understanding",
    "approach": "Our approach",
    "risks_and_assumptions": "Risks and assumptions",
}


def draft(ctx: RunContext, section_id: str, records: list[dict[str, Any]]) -> ProposalSection:
    """One short section from its records only. A failure marks the section FAILED."""
    prompt = ctx.prompts["draft"]
    task = DraftTask.model_validate({"section_id": section_id, "records": records})
    rendered = prompt.render(task.model_dump_json(), run_id=ctx.run_id, section_id=section_id)
    parsed, _ = ctx.structured(
        prompt, rendered.messages, DraftResult, node="draft", input_hash=rendered.input_hash
    )
    if not isinstance(parsed, DraftResult):
        return ProposalSection(
            id=section_id,
            title=SECTION_TITLES[section_id],
            text="",
            input_hash=rendered.input_hash,
            status="FAILED",
        )
    known = {str(r["id"]) for r in records if "id" in r}
    return ProposalSection(
        id=section_id,
        title=parsed.title,
        text=parsed.text,
        cited_ids=[c for c in parsed.cited_ids if c in known],
        input_hash=rendered.input_hash,
        status="CURRENT",
    )


def section_records(
    section_id: str,
    requirements: Sequence[Requirement],
    approach_items: Sequence[ApproachItem],
    risks: Sequence[Risk],
    questions: Sequence[OpenQuestion],
) -> list[dict[str, Any]]:
    if section_id == "understanding":
        ordered = sorted(predictions(requirements), key=lambda r: (not r.hazard, not r.mandatory))
        return [
            r.model_dump(include={"id", "statement", "modality", "mandatory", "hazard"})
            for r in ordered
        ]
    if section_id == "approach":
        return [
            a.model_dump(include={"id", "text", "requirement_ids", "basis"}) for a in approach_items
        ]
    found = [
        r.model_dump(include={"id", "event", "effect", "responses", "owner_role"}) for r in risks
    ]
    asked = [{"id": f"Q-{n:02d}", "question": q.text} for n, q in enumerate(questions, start=1)]
    return found + asked
