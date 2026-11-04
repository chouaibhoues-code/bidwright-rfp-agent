"""The Iteration 0a nodes: extract, verify, approach, risk and draft.

Each node is a plain function over typed inputs, so it runs and tests without the graph;
`build.py` wires them into LangGraph. Every LLM call goes through `RunContext.call`, which
records the ledger entry; the client counts and checks the run budget before each provider
attempt (ADR-022). Each node allows one repair: a targeted one for quotes, missing ids or
generic risks, or a format one for a response that breaks its schema. Whatever still fails is
rejected and logged, never accepted: `extract` rejects the batch, `draft` marks the section
`FAILED`, and `approach` and `risk` return an empty result with the reason, so the run ends
`DEGRADED` with its verified requirements in the summary (ADR-024).
"""

import dataclasses
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
from bidwright.harness.view import TextView
from bidwright.ingest import display_text
from bidwright.llm.client import Completion, LLMClient
from bidwright.llm.schema import sha256_of
from bidwright.llm.types import Message
from bidwright.obs.tracing import Tracing, maybe_span, record_llm, set_attribute
from bidwright.prompts import Prompt
from bidwright.schemas import (
    QUOTE_MAX_CHARS,
    ApproachInput,
    ApproachItem,
    ApproachItemView,
    ApproachResult,
    CandidateRow,
    ContextPack,
    CueHit,
    DraftResult,
    DraftTask,
    ExtractBatch,
    ExtractItem,
    ExtractResult,
    LedgerEntry,
    OpenQuestion,
    Passage,
    ProposalSection,
    Requirement,
    RequirementView,
    Risk,
    RiskInput,
    RiskProposal,
    RiskRegister,
    SubmissionHazard,
    ToolRequest,
    ToolResult,
)
from bidwright.verify import QuoteCheck, check_quote, missing_values, shown_text

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
    view: TextView | None = None  # the run's text view (D-05); None is the frozen text
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self.client.on_ledger = self.record
        self.client.before_attempt = self.budget.attempt

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

MAX_CITED = 3  # passages one requirement may cite
SECOND_PASS_FROM = frozenset({"NO_OBLIGATION", "BACKGROUND", "NOT_BINDING"})


@dataclass
class BatchOutcome:
    batch_id: str
    accepted: list[tuple[ExtractItem, QuoteCheck]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    no_obligation: list[str] = field(default_factory=list)
    round: int = 0  # the coverage round, 0 for the first pass


def batches(passages: Sequence[Passage], size: int) -> list[list[Passage]]:
    return [list(passages[i : i + size]) for i in range(0, len(passages), size)]


def extract_batch(
    ctx: RunContext,
    pack: ContextPack,
    prompt_id: str = "extract",
    *,
    second_pass: bool = False,
    round: int = 0,
) -> BatchOutcome:
    """Extract one pack, verify every item, and repair once what failed or is missing.

    Each item is checked on its own: an id outside the pack is dropped and a fourth one cut,
    a quote over 300 characters, a quote not found in its passages and a value the sources
    do not state each fail that item only. One repair message names every failure, grouped
    by kind, and every missing id; what still fails is rejected with its reason."""
    prompt = ctx.prompts[prompt_id]
    batch = ExtractBatch(
        batch_id=pack.call_id, passages=pack.passages, context=pack.context, terms=pack.terms
    )
    data = batch.model_dump_json()
    rendered = prompt.render(data, run_id=ctx.run_id, batch_id=pack.call_id)
    ids = [view.src_id for view in pack.passages]
    outcome = BatchOutcome(pack.call_id, round=round)
    first = ctx.call(
        prompt, rendered.messages, ExtractResult, node="extract", input_hash=rendered.input_hash
    )
    history = [*rendered.messages, first.as_message()]
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
            outcome.rejected.append(
                _rejection(pack.call_id, ids, "", "malformed output after repair")
            )
            return outcome
        settle(outcome, second.parsed.items, ctx.passages, ids, final=True, view=ctx.view)
        _account(outcome, second.parsed.no_obligation_src_ids, ids)
    else:
        failed = settle(outcome, result.items, ctx.passages, ids, final=False, view=ctx.view)
        outcome.no_obligation += [s for s in result.no_obligation_src_ids if s in ids]
        pending = [item for item, _ in failed]
        missing = [s for s in ids if s not in _accounted(outcome, pending)]
        if failed or missing:
            repair = _repair_message(prompt, failed, missing)
            second = ctx.call(
                prompt,
                [*history, Message("user", repair)],
                ExtractResult,
                node="extract",
                input_hash=sha256_of([rendered.input_hash, repair]),
            )
            repaired = (
                second.parsed
                if isinstance(second.parsed, ExtractResult)
                else ExtractResult(items=[])
            )
            _merge_repair(outcome, failed, missing, repaired, ctx.passages, ids, view=ctx.view)
    if second_pass:
        _second_pass(ctx, prompt, pack, data, outcome)
    return outcome


def _repair_message(
    prompt: Prompt, failed: Sequence[tuple[ExtractItem, QuoteCheck]], missing: Sequence[str]
) -> str:
    """One message for every failure, grouped by kind, then the missing ids."""
    groups: dict[str, list[list[str]]] = {"quote": [], "number": [], "long": []}
    for item, check in failed:
        first_id = item.src_ids[0] if item.src_ids else ""
        text = item.statement if check.failure == "number" else item.quote
        groups[check.failure or "quote"].append([first_id, text])
    parts = []
    for kind, element in (
        ("quote", "repair_quotes"),
        ("number", "repair_numbers"),
        ("long", "repair_long"),
    ):
        if groups[kind]:
            parts.append(prompt.task_text(element, failures=json.dumps(groups[kind])))
    if missing:
        parts.append(prompt.task_text("repair_missing", missing=json.dumps(list(missing))))
    parts.append(prompt.task_text("repair_close"))
    return " ".join(parts)


def _first_pass_dispositions(outcome: BatchOutcome) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for item, check in outcome.accepted:
        if not check.second_pass:
            for src_id in item.src_ids:
                found.setdefault(src_id, set()).add(item.disposition)
    for src_id in outcome.no_obligation:
        found.setdefault(src_id, set()).add("NO_OBLIGATION")
    for entry in outcome.rejected:
        if not entry.get("second_pass"):
            for src_id in entry["src_ids"]:
                found.setdefault(src_id, set()).add("REJECTED")
    return found


def second_pass_ids(pack: ContextPack, outcome: BatchOutcome) -> list[str]:
    """The pack's passages in an `OBLIGATION` zone that the first pass found no binding,
    optional or out-of-scope obligation in: the second pass's candidates (S-13)."""
    found = _first_pass_dispositions(outcome)
    return [
        view.src_id
        for view in pack.passages
        if view.zone == "OBLIGATION"
        and found.get(view.src_id)
        and found[view.src_id] <= SECOND_PASS_FROM
    ]


def _second_pass(
    ctx: RunContext, prompt: Prompt, pack: ContextPack, data: str, outcome: BatchOutcome
) -> None:
    """One more reading of the candidates, on the same data tag. Its items settle like any
    other; a passage it adds nothing to keeps its first-pass row."""
    ids = second_pass_ids(pack, outcome)
    if not ids:
        return
    rendered = prompt.render(data, run_id=ctx.run_id, task="second_pass", ids=json.dumps(ids))
    pack_hash = sha256_of(pack.model_dump(mode="json"))
    result, _ = ctx.structured(
        prompt,
        rendered.messages,
        ExtractResult,
        node="extract",
        input_hash=sha256_of([pack_hash, "second_pass", ids]),
    )
    if isinstance(result, ExtractResult):
        settle(
            outcome, result.items, ctx.passages, ids, final=True, view=ctx.view, second_pass=True
        )


def _rejection(
    batch_id: str, src_ids: list[str], quote: str, reason: str, second_pass: bool = False
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "batch_id": batch_id,
        "src_ids": src_ids,
        "quote": quote,
        "reason": reason,
    }
    if second_pass:
        entry["second_pass"] = True
    return entry


def _sources(
    item: ExtractItem, cited: Sequence[Passage], passages: Mapping[str, Passage], view: Any
) -> list[str]:
    """The texts a statement's values may come from: the quote, the cited passages, their
    lead-ins and table headers, and their section paths."""
    texts = [item.quote]
    for passage in cited:
        texts.append(shown_text(passage, view))
        for linked in (passage.lead_in_id, passage.header_id):
            if linked and linked in passages:
                texts.append(shown_text(passages[linked], view))
        texts.append(passage.section_path)
    return texts


def _check(
    item: ExtractItem, passages: Mapping[str, Passage], ids: list[str], view: Any = None
) -> QuoteCheck:
    cited = [passages[s] for s in item.src_ids if s in ids]
    if not cited:
        return QuoteCheck("REJECTED", reason="cites no passage of the batch", failure="quote")
    if len(item.quote) > QUOTE_MAX_CHARS:
        return QuoteCheck(
            "REJECTED", reason=f"quote over {QUOTE_MAX_CHARS} characters", failure="long"
        )
    check = check_quote(item.quote, cited, view)
    if check.status == "REJECTED":
        return check
    if missing_values(item.statement, _sources(item, cited, passages, view)):
        return QuoteCheck("REJECTED", reason="number not in source", failure="number")
    return check


def settle(
    outcome: BatchOutcome,
    items: Sequence[ExtractItem],
    passages: Mapping[str, Passage],
    ids: list[str],
    *,
    final: bool,
    view: Any = None,
    repaired: bool = False,
    second_pass: bool = False,
) -> list[tuple[ExtractItem, QuoteCheck]]:
    """Accept verified items. Failures are returned with their check for repair, or rejected
    with their reason when final.

    A quote counts only against the passages of its own batch (`ids`): an id from outside the
    batch is dropped from the item, so a requirement never cites a passage its batch did not
    show the model, and an item keeps at most 3 ids. On the second pass, an item that withdraws
    its quote or cites none of the passages asked about adds nothing and is left out."""
    failed = []
    for item in items:
        kept = [s for s in dict.fromkeys(item.src_ids) if s in ids][:MAX_CITED]
        if not item.quote.strip():
            if not second_pass:
                outcome.rejected.append(_rejection(outcome.batch_id, kept, "", "withdrawn"))
            continue
        if not kept and second_pass:
            continue
        if kept and kept != item.src_ids:
            item = item.model_copy(update={"src_ids": kept})
        check = _check(item, passages, ids, view)
        if check.status != "REJECTED":
            check = dataclasses.replace(check, repaired=repaired, second_pass=second_pass)
            outcome.accepted.append((item, check))
        elif final:
            reason = check.reason or "not found in the cited passages"
            outcome.rejected.append(
                _rejection(outcome.batch_id, kept, item.quote, reason, second_pass)
            )
        else:
            failed.append((item, check))
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
    failed: list[tuple[ExtractItem, QuoteCheck]],
    missing: list[str],
    repaired: ExtractResult,
    passages: Mapping[str, Passage],
    ids: list[str],
    *,
    view: Any = None,
) -> None:
    pool = list(repaired.items)
    for item, _ in failed:
        first_id = item.src_ids[0] if item.src_ids else None
        match = next((r for r in pool if r.src_ids and r.src_ids[0] == first_id), None)
        if match is None:
            kept = [s for s in item.src_ids if s in ids]
            outcome.rejected.append(_rejection(outcome.batch_id, kept, item.quote, "not repaired"))
            continue
        pool.remove(match)
        settle(outcome, [match], passages, ids, final=True, view=view, repaired=True)
    added = [r for r in pool if set(r.src_ids) & set(missing)]
    settle(outcome, added, passages, ids, final=True, view=view)
    _account(outcome, [s for s in repaired.no_obligation_src_ids if s in missing], ids)


def assign_requirements(
    outcomes: Sequence[BatchOutcome],
    passages: Sequence[Passage],
    zones: Mapping[tuple[str, str], str] | None = None,
) -> tuple[list[Requirement], list[dict[str, Any]]]:
    """The fan-in after extract: number verified items in reading order as requirements.

    A requirement takes its document, page and small-print flag from its first cited
    passage, and its zone from that passage's section."""
    by_id = {p.id: p for p in passages}
    order = {p.id: n for n, p in enumerate(passages)}
    accepted = [entry for outcome in outcomes for entry in outcome.accepted]
    accepted.sort(key=lambda e: (order[e[1].src_id or ""], (e[1].span or (0, 0))[0]))
    requirements = []
    for number, (item, check) in enumerate(accepted, start=1):
        first = by_id[check.src_id or ""]
        cited = [first.id] + [s for s in item.src_ids if s != first.id and s in order]
        requirements.append(
            Requirement.model_validate(
                {
                    "id": f"REQ-{number:04d}",
                    "doc_id": first.doc_id,
                    "statement": item.statement,
                    "modality": item.modality,
                    "mandatory": item.disposition == "BINDING",
                    "hazard": item.hazard,
                    "disposition": item.disposition,
                    "src_ids": cited[:MAX_CITED],
                    "quote": item.quote,
                    "quote_status": check.status,
                    "quote_span": check.span,
                    "zone": (zones or {}).get((first.doc_id, first.section_path)),
                    "page": first.page,
                    "small_print": first.small_print,
                    "repaired": check.repaired,
                }
            )
        )
    rejected = [entry for outcome in outcomes for entry in outcome.rejected]
    return requirements, rejected


def link_hazards(
    requirements: Sequence[Requirement], hazards: Sequence[SubmissionHazard]
) -> tuple[list[Requirement], list[SubmissionHazard]]:
    """A requirement is a hazard when `extract` flagged it or a `triage` hazard cites one of
    its passages; each hazard lists the requirements that quote its passages."""
    linked = []
    flagged: set[str] = set()
    for hazard in hazards:
        ids = [r.id for r in requirements if set(r.src_ids) & set(hazard.src_ids)]
        flagged.update(ids)
        linked.append(hazard.model_copy(update={"requirement_ids": ids}))
    marked = [
        r.model_copy(update={"hazard": True}) if r.id in flagged and not r.hazard else r
        for r in requirements
    ]
    return marked, linked


def candidate_rows(
    outcomes: Sequence[BatchOutcome],
    passages: Sequence[Passage],
    requirements: Sequence[Requirement],
    zones: Mapping[tuple[str, str], str] | None = None,
    cues: Sequence[CueHit] = (),
) -> list[CandidateRow]:
    """The candidate ledger: one row per passage, with every disposition it received.

    First-pass entries come first: each item's disposition for every passage it cites, a
    no-obligation mark, or a rejection with its reason (`UNACCOUNTED` for a passage no answer
    covered). The second pass's accepted items follow, with the reason "second pass"."""
    first: dict[str, list[tuple[str, str]]] = {p.id: [] for p in passages}
    later: dict[str, list[tuple[str, str]]] = {p.id: [] for p in passages}
    rounds: dict[str, int] = {}
    for outcome in outcomes:
        touched: list[str] = []
        for item, check in outcome.accepted:
            target = later if check.second_pass else first
            reason = "second pass" if check.second_pass else ""
            for src_id in item.src_ids:
                if src_id in target:
                    target[src_id].append((item.disposition, reason))
                    touched.append(src_id)
        for src_id in outcome.no_obligation:
            if src_id in first:
                first[src_id].append(("NO_OBLIGATION", ""))
                touched.append(src_id)
        for entry in outcome.rejected:
            if entry.get("second_pass"):
                continue
            kind = "UNACCOUNTED" if entry["reason"] == "unaccounted" else "REJECTED"
            for src_id in entry["src_ids"]:
                if src_id in first:
                    first[src_id].append((kind, entry["reason"]))
                    touched.append(src_id)
        for src_id in touched:
            rounds[src_id] = max(rounds.get(src_id, 0), outcome.round)
    quoted: dict[str, list[str]] = {}
    for requirement in requirements:
        for src_id in requirement.src_ids:
            quoted.setdefault(src_id, []).append(requirement.id)
    kinds = {hit.src_id: hit.kinds for hit in cues}
    rows = []
    for passage in passages:
        entries = first[passage.id] + later[passage.id] or [("UNACCOUNTED", "unaccounted")]
        rows.append(
            CandidateRow.model_validate(
                {
                    "src_id": passage.id,
                    "doc_id": passage.doc_id,
                    "zone": (zones or {}).get((passage.doc_id, passage.section_path)),
                    "cues": kinds.get(passage.id, []),
                    "dispositions": [d for d, _ in entries],
                    "requirement_ids": quoted.get(passage.id, []),
                    "reasons": [r for _, r in entries],
                    "round": rounds.get(passage.id, 0),
                }
            )
        )
    return rows


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
