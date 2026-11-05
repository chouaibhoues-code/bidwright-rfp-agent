"""`brief` (Iteration 2, step 9; ADR-036): the opportunity brief, from the RFP's evaluation and
instruction sections.

`ContextManager.pack_brief` packs the `EVALUATION` sections, then the `INSTRUCTION` sections,
each whole and in document order, with the verified requirements their passages hold and the
RFP profile, into calls of the `brief` budget, `F01` onward; a section over the budget goes
alone, with a note. Each call reads one `BriefInput` through the run's text view and goes
through `RunContext.structured`: one call, and one format repair.

Code checks every answer, so the brief holds only what the RFP's own text supports:
- a factor stays only when its name and, unless `not_stated`, its weight each occur as whole
  words in one passage it cites, compared after `verify.normalize` and casefolding; `%` belongs
  to the weight, so "20%" matches the development PDF's row, "40" the hero's, and "1" never
  matches inside "10";
- a scoring quote that `verify.check_quote` does not accept in the factor's passages becomes
  `not_stated`;
- code sets every status: a factor whose name holds the word price, cost, fee or charge, in
  any letter case, singular or plural, is `OUT_OF_SCOPE`, and every other factor is `IN_SCOPE`;
- an id outside the call's sections is dropped, the fourth and later ids too, and a factor or
  item left with no id is dropped;
- a factor name over 80 characters drops the factor, a weight over 20 characters or a scoring
  quote over 200 becomes `not_stated`, and an item over 200 characters is cut at a word
  boundary;
- a topic of more than 7 words, or one sharing 4 or more consecutive normalized words with a
  passage of the run, is dropped.
Each drop and cut is named in `notes`.

The calls' results then merge in call order. One factor with one weight from two calls is one
factor, its passages united up to 3, the first call's first. `not_stated` is no weight: a factor
with none joins the same name's factor that has one. One name with two stated weights keeps
both and adds a `FactorDiscrepancy` and its clarification question, origin `brief`, numbered
after `consolidate`'s last. Items keep their order, de-duplicated by normalized text within each
list; the first scoring method and the first 5 distinct topics are kept. Factors are numbered
`EF-01` onward; items `BI-001` onward across `needs`, `scope_in`, `scope_out`, `constraints`,
`never`, `ask` and `always`, and the scoring method takes the next number.

With no `EVALUATION` or `INSTRUCTION` section, no call is made, the brief is empty, and the run
is not degraded. A call that breaks its schema twice adds nothing: when some calls fail, the run
finishes `DEGRADED` with "brief: N of M calls failed", and when every call fails, the brief is
empty and the reason is "brief: no brief". `brief` writes `brief.json`, an `OpportunityBrief`.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from bidwright.candidates import cut
from bidwright.graph.nodes import RunContext
from bidwright.harness.context import ContextManager, prompt_tokens, requirement_view
from bidwright.harness.view import TextView
from bidwright.schemas import (
    BRIEF_ITEM_MAX_CHARS,
    FACTOR_NAME_MAX_CHARS,
    FACTOR_SCORING_MAX_CHARS,
    FACTOR_WEIGHT_MAX_CHARS,
    NOT_STATED,
    TOPIC_MAX_CHARS,
    TOPICS_MAX,
    BriefInput,
    BriefItem,
    BriefItemProposal,
    BriefResult,
    ClarificationQuestion,
    ContextPack,
    EvaluationFactor,
    EvaluationFactorProposal,
    FactorDiscrepancy,
    FactorStatus,
    OpportunityBrief,
    Passage,
    Requirement,
    RfpProfile,
    ZoneRecord,
)
from bidwright.text import normalized_words
from bidwright.verify import check_quote, normalize, shown_text

NODE = "brief"
NO_BRIEF = "brief: no brief"
PRICE_WORDS = frozenset({"price", "prices", "cost", "costs", "fee", "fees", "charge", "charges"})
TOPIC_MAX_WORDS = 7
TOPIC_SHARED_WORDS = 4  # a topic sharing this many consecutive words with a passage quotes it
MAX_IDS = 3
ITEM_LISTS = ("needs", "scope_in", "scope_out", "constraints", "never", "ask", "always")
ACCEPTED = frozenset({"VERBATIM_VERIFIED", "NORMALIZED_MATCH"})


@dataclass(frozen=True)
class BriefOutcome:
    brief: OpportunityBrief
    degraded: str | None


@dataclass
class _Factor:
    name: str
    weight: str
    scoring: str
    src_ids: list[str]
    status: FactorStatus


@dataclass
class _Item:
    text: str
    src_ids: list[str]


@dataclass
class _Settled:
    """One call's answer after code's checks."""

    factors: list[_Factor] = field(default_factory=list)
    scoring_method: _Item | None = None
    items: dict[str, list[_Item]] = field(default_factory=dict)
    topics: list[str] = field(default_factory=list)


def _norm(text: str) -> str:
    return normalize(text)[0].casefold()


def occurs(term: str, text: str) -> bool:
    """Whether `term` occurs in `text` as whole words, after normalizing and casefolding both;
    `%` counts as part of a word, so "20%" and "20" never match each other."""
    needle = _norm(term)
    if not needle:
        return False
    return re.search(rf"(?<![\w%]){re.escape(needle)}(?![\w%])", _norm(text)) is not None


def status_of(name: str) -> FactorStatus:
    """`OUT_OF_SCOPE` for a factor priced by the commercial team, `IN_SCOPE` otherwise."""
    return "OUT_OF_SCOPE" if PRICE_WORDS & set(normalized_words(name)) else "IN_SCOPE"


@dataclass
class _Checker:
    """Applies code's rules to one call's answer, recording each drop and cut in `notes`."""

    pack: ContextPack
    passages: Mapping[str, Passage]
    view: TextView | None
    runs: frozenset[tuple[str, ...]]
    notes: list[str]

    def ids(self, src_ids: Sequence[str], what: str) -> list[str]:
        allowed = set(self.pack.manifest.included_src_ids)
        unique = list(dict.fromkeys(src_ids))
        outside = [s for s in unique if s not in allowed]
        if outside:
            self.notes.append(
                f"{self.pack.call_id}: {what} cited ids outside its sections: {', '.join(outside)}"
            )
        kept = [s for s in unique if s in allowed]
        if len(kept) > MAX_IDS:
            self.notes.append(f"{self.pack.call_id}: {what} kept its first {MAX_IDS} ids")
        return kept[:MAX_IDS]

    def factor(self, proposal: EvaluationFactorProposal) -> _Factor | None:
        name = " ".join(proposal.name.split())
        label = f"factor {name[:40]!r}"
        if not name:
            self.notes.append(f"{self.pack.call_id}: a factor with no name was dropped")
            return None
        if len(name) > FACTOR_NAME_MAX_CHARS:
            self.notes.append(
                f"{self.pack.call_id}: {label} dropped: its name passes 80 characters"
            )
            return None
        src_ids = self.ids(proposal.src_ids, label)
        if not src_ids:
            self.notes.append(f"{self.pack.call_id}: {label} dropped: it cites no passage")
            return None
        weight = " ".join(proposal.weight.split()) or NOT_STATED
        if weight != NOT_STATED and len(weight) > FACTOR_WEIGHT_MAX_CHARS:
            self.notes.append(
                f"{self.pack.call_id}: the weight of {label} passes 20 characters and is not_stated"
            )
            weight = NOT_STATED
        cited = [self.passages[s] for s in src_ids]
        texts = [shown_text(p, self.view) for p in cited]
        if not any(
            occurs(name, text) and (weight == NOT_STATED or occurs(weight, text)) for text in texts
        ):
            problem = (
                "its name is not in a cited passage"
                if weight == NOT_STATED
                else "its name and weight are not in one cited passage"
            )
            self.notes.append(f"{self.pack.call_id}: {label} dropped: {problem}")
            return None
        scoring = " ".join(proposal.scoring.split()) or NOT_STATED
        if scoring != NOT_STATED:
            if len(scoring) > FACTOR_SCORING_MAX_CHARS:
                self.notes.append(
                    f"{self.pack.call_id}: the scoring of {label} passes 200 characters and is"
                    " not_stated"
                )
                scoring = NOT_STATED
            elif check_quote(scoring, cited, self.view).status not in ACCEPTED:
                self.notes.append(
                    f"{self.pack.call_id}: the scoring of {label} is not a quote of its passages"
                    " and is not_stated"
                )
                scoring = NOT_STATED
        return _Factor(name, weight, scoring, src_ids, status_of(name))

    def item(self, proposal: BriefItemProposal, what: str) -> _Item | None:
        text = " ".join(proposal.text.split())
        if not text:
            return None
        if len(text) > BRIEF_ITEM_MAX_CHARS:
            text = cut(text, BRIEF_ITEM_MAX_CHARS)
            self.notes.append(f"{self.pack.call_id}: a {what} item was cut to 200 characters")
        src_ids = self.ids(proposal.src_ids, f"a {what} item")
        if not src_ids:
            self.notes.append(f"{self.pack.call_id}: a {what} item dropped: it cites no passage")
            return None
        return _Item(text, src_ids)

    def topic(self, topic: str) -> str | None:
        text = " ".join(topic.split())
        if not text:
            return None
        words = normalized_words(text)
        if len(text.split()) > TOPIC_MAX_WORDS or len(text) > TOPIC_MAX_CHARS:
            self.notes.append(f"{self.pack.call_id}: topic {text!r} dropped: over 7 words")
            return None
        size = TOPIC_SHARED_WORDS
        if any(tuple(words[i : i + size]) in self.runs for i in range(len(words) - size + 1)):
            self.notes.append(
                f"{self.pack.call_id}: topic {text!r} dropped: it shares 4 or more consecutive"
                " words with the RFP"
            )
            return None
        return text

    def settle(self, result: BriefResult) -> _Settled:
        settled = _Settled()
        for proposal in result.factors:
            factor = self.factor(proposal)
            if factor is not None:
                settled.factors.append(factor)
        if result.scoring_method is not None:
            settled.scoring_method = self.item(result.scoring_method, "scoring method")
        for name in ITEM_LISTS:
            kept = [self.item(p, name.replace("_", " ")) for p in getattr(result, name)]
            settled.items[name] = [item for item in kept if item is not None]
        topics = [self.topic(t) for t in result.topics]
        settled.topics = [t for t in topics if t is not None]
        return settled


def _runs(passages: Sequence[Passage], view: TextView | None) -> frozenset[tuple[str, ...]]:
    """Every run of `TOPIC_SHARED_WORDS` normalized words in the run's passages."""
    size = TOPIC_SHARED_WORDS
    found: set[tuple[str, ...]] = set()
    for passage in passages:
        words = normalized_words(shown_text(passage, view))
        found.update(tuple(words[i : i + size]) for i in range(len(words) - size + 1))
    return frozenset(found)


def _unite(target: list[str], more: Sequence[str]) -> None:
    for src_id in more:
        if src_id not in target and len(target) < MAX_IDS:
            target.append(src_id)


def _merge_factors(all_factors: Sequence[_Factor]) -> list[_Factor]:
    """One factor per name and weight; a factor with no weight joins its name's stated one."""
    merged: list[_Factor] = []
    by_key: dict[tuple[str, str], _Factor] = {}
    for factor in all_factors:
        key = (_norm(factor.name), _norm(factor.weight))
        if key in by_key:
            _unite(by_key[key].src_ids, factor.src_ids)
            continue
        by_key[key] = factor
        merged.append(factor)
    stated = {
        _norm(f.name): f for f in reversed(merged) if f.weight != NOT_STATED
    }  # the first stated factor of each name
    kept = []
    for factor in merged:
        home = stated.get(_norm(factor.name))
        if factor.weight == NOT_STATED and home is not None:
            _unite(home.src_ids, factor.src_ids)
            continue
        kept.append(factor)
    return kept


def _weights_text(weights: Sequence[str]) -> str:
    count = {2: "two", 3: "three", 4: "four"}.get(len(weights), str(len(weights)))
    listed = ", ".join(weights[:-1]) + f" and {weights[-1]}"
    return f"{count} weights, {listed}"


def _discrepancies(
    factors: Sequence[_Factor], first_discrepancy: int, first_question: int
) -> tuple[list[FactorDiscrepancy], list[ClarificationQuestion]]:
    by_name: dict[str, list[_Factor]] = {}
    for factor in factors:
        if factor.weight != NOT_STATED:
            by_name.setdefault(_norm(factor.name), []).append(factor)
    discrepancies, questions = [], []
    for group in by_name.values():
        if len(group) < 2:
            continue
        weights = [f.weight for f in group]
        src_ids = list(dict.fromkeys(s for f in group for s in f.src_ids))
        name = group[0].name
        discrepancies.append(
            FactorDiscrepancy(
                id=f"DS-{first_discrepancy + len(discrepancies):03d}",
                factor=name,
                weights=weights,
                src_ids=src_ids,
            )
        )
        questions.append(
            ClarificationQuestion(
                id=f"CQ-{first_question + len(questions):03d}",
                text=f"The RFP gives {name} {_weights_text(weights)}; which applies?",
                src_ids=src_ids,
                origin="brief",
            )
        )
    return discrepancies, questions


def _merge(
    settled: Sequence[_Settled], first_discrepancy: int, first_question: int, notes: list[str]
) -> OpportunityBrief:
    factors = _merge_factors([f for s in settled for f in s.factors])
    discrepancies, questions = _discrepancies(factors, first_discrepancy, first_question)
    lists: dict[str, list[BriefItem]] = {}
    number = 0
    for name in ITEM_LISTS:
        seen: set[str] = set()
        lists[name] = []
        for item in (i for s in settled for i in s.items.get(name, [])):
            key = _norm(item.text)
            if key in seen:
                continue
            seen.add(key)
            number += 1
            lists[name].append(
                BriefItem(id=f"BI-{number:03d}", text=item.text, src_ids=item.src_ids)
            )
    method = next((s.scoring_method for s in settled if s.scoring_method is not None), None)
    scoring_method = (
        BriefItem(id=f"BI-{number + 1:03d}", text=method.text, src_ids=method.src_ids)
        if method is not None
        else None
    )
    topics: list[str] = []
    for topic in (t for s in settled for t in s.topics):
        if topic.casefold() not in {t.casefold() for t in topics}:
            topics.append(topic)
    if len(topics) > TOPICS_MAX:
        notes.append(f"topics after the first {TOPICS_MAX} dropped: {'; '.join(topics[5:])}")
    return OpportunityBrief(
        factors=[
            EvaluationFactor(
                id=f"EF-{n:02d}",
                name=f.name,
                weight=f.weight,
                scoring=f.scoring,
                src_ids=f.src_ids,
                status=f.status,
            )
            for n, f in enumerate(factors, start=1)
        ],
        scoring_method=scoring_method,
        topics=topics[:TOPICS_MAX],
        discrepancies=discrepancies,
        questions=questions,
        notes=notes,
        **lists,
    )


def brief(
    ctx: RunContext,
    passages: Sequence[Passage],
    zones: Sequence[ZoneRecord],
    requirements: Sequence[Requirement],
    profile: RfpProfile,
    *,
    manager: ContextManager,
    budget_tokens: int,
    run_dir: Path,
    first_discrepancy: int = 1,
    first_question: int = 1,
) -> BriefOutcome:
    """Build the brief from the run's evaluation and instruction sections, and write
    `brief.json`. `first_discrepancy` and `first_question` continue `consolidate`'s ids."""
    prompt = ctx.prompts[NODE]
    packs = manager.pack_brief(
        zones,
        requirements,
        profile,
        view=ctx.view,
        fixed_tokens=prompt_tokens(prompt, manager.limits.chars_per_token),
        budget_tokens=budget_tokens,
    )
    notes = [
        f"{pack.call_id} holds a section over the brief budget"
        for pack in packs
        if pack.manifest.utilization > 1
    ]
    by_id = {p.id: p for p in passages}
    runs = _runs(passages, ctx.view) if packs else frozenset()
    settled: list[_Settled] = []
    failed = 0
    for pack in packs:
        held = set(pack.manifest.included_record_ids)
        data = BriefInput(
            sections=manager.brief_sections(pack),
            profile=profile,
            requirements=[requirement_view(r) for r in requirements if r.id in held],
        ).model_dump_json()
        rendered = prompt.render(data, run_id=ctx.run_id, call_id=pack.call_id)
        result, _ = ctx.structured(
            prompt, rendered.messages, BriefResult, node=NODE, input_hash=rendered.input_hash
        )
        if not isinstance(result, BriefResult):
            failed += 1
            notes.append(f"{pack.call_id} broke its schema twice and adds nothing")
            continue
        checker = _Checker(pack, by_id, ctx.view, runs, notes)
        settled.append(checker.settle(result))
    record = _merge(settled, first_discrepancy, first_question, notes)
    if packs and failed == len(packs):
        record, degraded = OpportunityBrief(notes=notes), NO_BRIEF
    elif failed:
        degraded = f"brief: {failed} of {len(packs)} calls failed"
    else:
        degraded = None
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "brief.json").write_text(
        record.model_dump_json(indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    return BriefOutcome(brief=record, degraded=degraded)


__all__ = ["NO_BRIEF", "NODE", "BriefOutcome", "brief", "occurs", "status_of"]
