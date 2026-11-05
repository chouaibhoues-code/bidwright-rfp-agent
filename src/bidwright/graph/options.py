"""`options` (Iteration 3, step 6; ADR-041): one call proposes two or three solution options,
each scored 0 to 4 on the RFP's in-scope factors, and code weights, gates and ranks them.

`options_task` builds the call's input from the brief's factors, the capability map with each
claim's disposition, the domain brief's items and the gaps. `settle` applies code's rules:
- one option is kept, with a note, and beyond 3 the first 3; with no baseline, code marks the
  option with the fewest `CUSTOM` needs, and with two or more, the first keeps the mark;
- a score for an `OUT_OF_SCOPE` or unknown factor is dropped, a missing in-scope score counts
  0, and a score outside 0 to 4 is clamped, each with a note;
- a factor is pass-or-fail when its weight reads "pass/fail", "pass or fail" or "pass-fail",
  or its scoring quote holds both "pass" and "fail"; it carries no weight, and an option
  scored below 2 on it fails that gate;
- a stated weight is the number at the start of the weight text; with every other in-scope
  factor stated, the total is the weighted mean of the scores, else every factor counts
  equally and the ranking is provisional; with no weighted factor, every total is 0;
- a need not on the map, a second approach for one need, and a claim that is not one of its
  need's claims are dropped, each with a note;
- an option citing a claim not assessed `SUPPORTED` or `PARTIALLY_SUPPORTED` needs proof;
- options that pass their gates rank above any that fail one; ties break on fewer open gaps
  (`GAP` needs the option marks neither `PARTNER` nor `ALTERNATIVE`), then fewer claims
  needing proof, then fewer `CUSTOM` needs, then option order.
The ranking is hypothetical unless an approved bid policy is loaded. `write_options` is the one
writer of `options.json`.
"""

import json
import re
from collections.abc import Sequence
from pathlib import Path

from bidwright.graph.decide import cut
from bidwright.graph.nodes import CallManifests, RunContext
from bidwright.schemas import (
    NOT_STATED,
    OPTION_NAME_MAX_CHARS,
    OPTION_SUMMARY_MAX_CHARS,
    SCORE_REASON_MAX_CHARS,
    CapabilityClaim,
    CapabilityMap,
    ClaimView,
    DomainBrief,
    DomainItemView,
    EvaluationFactor,
    EvidenceAssessment,
    FactorView,
    GapView,
    MapRowView,
    NeedDecision,
    OptionProposal,
    OptionsResult,
    OptionsTask,
    SolutionOption,
    SolutionOptions,
    StoredApproach,
    StoredScore,
)

NODE = "options"
MAX_OPTIONS = 3
GATE_SCORE = 2  # an option scored below this on a pass-or-fail factor fails its gate
SUPPORTING = frozenset({"SUPPORTED", "PARTIALLY_SUPPORTED"})
OPEN_MODES = frozenset({"PARTNER", "ALTERNATIVE"})
_PASS_FAIL = re.compile(r"\bpass\s*(?:/|or|-)\s*fail\b", re.IGNORECASE)
_NUMBER = re.compile(r"^\s*(\d+(?:\.\d+)?)")


def options_task(
    factors: Sequence[EvaluationFactor],
    capability_map: CapabilityMap,
    claims: Sequence[CapabilityClaim],
    assessments: Sequence[EvidenceAssessment],
    decisions: Sequence[NeedDecision],
    domain: DomainBrief | None,
) -> OptionsTask:
    by_claim = {a.claim_id: a for a in assessments}
    texts = {c.id: c.text for c in claims}
    gaps = {d.need_id: d.gap for d in decisions}
    return OptionsTask(
        factors=[
            FactorView(
                factor_id=f.id, name=f.name, weight=f.weight, scoring=f.scoring, status=f.status
            )
            for f in factors
        ],
        needs=[
            MapRowView(
                need_id=row.need_id,
                origin=row.origin,
                text=row.text,
                status=row.status,
                claims=[
                    ClaimView(
                        claim_id=c,
                        text=texts.get(c, ""),
                        disposition=by_claim[c].disposition if c in by_claim else None,
                    )
                    for c in row.claim_ids
                ],
            )
            for row in capability_map.rows
        ],
        domain_items=[
            DomainItemView(id=item.id, kind=item.kind, statement=item.statement)
            for item in (domain.items if domain is not None else [])
        ],
        gaps=[
            GapView(need_id=row.need_id, gap=gaps.get(row.need_id) or row.reason)
            for row in capability_map.rows
            if row.status == "GAP"
        ],
    )


def propose(
    ctx: RunContext, task: OptionsTask, manifests: CallManifests | None = None
) -> OptionsResult | None:
    """The one call, `O01`, and its format repair, `O01-repair`."""
    prompt = ctx.prompts[NODE]
    data = task.model_dump_json()
    rendered = prompt.render(data, run_id=ctx.run_id)
    records = [row.need_id for row in task.needs] + [f.factor_id for f in task.factors]

    def record(call_id: str, history: Sequence[object]) -> None:
        if manifests is not None:
            turns = list(history[len(rendered.messages) :])
            manifests.record(prompt, NODE, call_id, records, data, turns)  # type: ignore[arg-type]

    record("O01", rendered.messages)
    parsed, _ = ctx.structured(
        prompt,
        list(rendered.messages),
        OptionsResult,
        node=NODE,
        input_hash=rendered.input_hash,
        on_repair=lambda sent: record("O01-repair", sent),
    )
    return parsed if isinstance(parsed, OptionsResult) else None


def pass_or_fail(factor: FactorView) -> bool:
    scoring = factor.scoring.lower()
    return bool(_PASS_FAIL.search(factor.weight)) or ("pass" in scoring and "fail" in scoring)


def stated_weight(factor: FactorView) -> float | None:
    """The number at the start of the weight text, or None for `not_stated` and any words."""
    if factor.weight == NOT_STATED:
        return None
    found = _NUMBER.match(factor.weight)
    return float(found.group(1)) if found else None


def _scores(
    proposal: OptionProposal, in_scope: dict[str, FactorView], notes: list[str], name: str
) -> list[StoredScore]:
    given: dict[str, StoredScore] = {}
    for score in proposal.scores:
        if score.factor_id not in in_scope:
            notes.append(
                f"{name}: a score for {score.factor_id or 'no factor'}, not in scope, dropped"
            )
            continue
        if score.factor_id in given:
            notes.append(f"{name}: a second score for {score.factor_id} dropped")
            continue
        value = min(max(score.score, 0), 4)
        if value != score.score:
            notes.append(
                f"{name}: the score {score.score} for {score.factor_id} clamped to {value}"
            )
        given[score.factor_id] = StoredScore(
            factor_id=score.factor_id, score=value, reason=cut(score.reason, SCORE_REASON_MAX_CHARS)
        )
    for factor_id in in_scope:
        if factor_id not in given:
            notes.append(f"{name}: no score for {factor_id}, counted 0")
            given[factor_id] = StoredScore(factor_id=factor_id, score=0, reason="")
    return [given[f] for f in in_scope]


def settle(
    result: OptionsResult,
    task: OptionsTask,
    assessments: Sequence[EvidenceAssessment],
    *,
    policy_loaded: bool = False,
) -> SolutionOptions:
    """Code's rules over the model's options (ADR-041)."""
    notes: list[str] = []
    proposals = list(result.options)
    if len(proposals) > MAX_OPTIONS:
        notes.append(
            f"options past the first {MAX_OPTIONS} dropped: {len(proposals) - MAX_OPTIONS}"
        )
        proposals = proposals[:MAX_OPTIONS]
    if len(proposals) == 1:
        notes.append("one option only, kept")
    if not proposals:
        notes.append("options: no option")
        return SolutionOptions(notes=notes, hypothetical=not policy_loaded)
    in_scope = {f.factor_id: f for f in task.factors if f.status == "IN_SCOPE"}
    gates = {f for f, factor in in_scope.items() if pass_or_fail(factor)}
    weighted = {f: stated_weight(factor) for f, factor in in_scope.items() if f not in gates}
    stated = bool(weighted) and all(w is not None for w in weighted.values())
    weighting = "stated" if stated else "equal"
    if weighted and not stated:
        notes.append(
            "a weight is not stated, so every factor counts equally: the ranking is provisional"
        )
    row_claims = {row.need_id: {c.claim_id for c in row.claims} for row in task.needs}
    gap_needs = {row.need_id for row in task.needs if row.status == "GAP"}
    supported = {a.claim_id for a in assessments if a.disposition in SUPPORTING}
    options: list[SolutionOption] = []
    for n, proposal in enumerate(proposals, start=1):
        name = f"OPT-{n}"
        approach: list[StoredApproach] = []
        for need in proposal.approach:
            if need.need_id not in row_claims:
                notes.append(f"{name}: need {need.need_id or 'none'} is not on the map, dropped")
                continue
            if any(a.need_id == need.need_id for a in approach):
                notes.append(f"{name}: a second approach for {need.need_id} dropped")
                continue
            own = row_claims[need.need_id]
            claim_ids = [c for c in dict.fromkeys(need.claim_ids) if c in own]
            for other in dict.fromkeys(c for c in need.claim_ids if c not in own):
                notes.append(
                    f"{name}: {other or 'no claim'} is not a claim of {need.need_id}, dropped"
                )
            approach.append(
                StoredApproach(
                    need_id=need.need_id, delivery_mode=need.delivery_mode, claim_ids=claim_ids
                )
            )
        scores = _scores(proposal, in_scope, notes, name)
        by_factor = {s.factor_id: s.score for s in scores}
        total = 0.0
        if weighted:
            if stated:
                weights = {f: float(w) for f, w in weighted.items() if w is not None}
                mass = sum(weights.values())
                total = sum(by_factor[f] * w for f, w in weights.items()) / mass if mass else 0.0
            else:
                total = sum(by_factor[f] for f in weighted) / len(weighted)
        options.append(
            SolutionOption(
                id=name,
                name=cut(proposal.name, OPTION_NAME_MAX_CHARS) or name,
                summary=cut(proposal.summary, OPTION_SUMMARY_MAX_CHARS),
                baseline=proposal.baseline,
                approach=approach,
                assumptions=[a for a in proposal.assumptions if a.strip()],
                scores=scores,
                needs_proof=sorted(
                    {c for a in approach for c in a.claim_ids if c not in supported}
                ),
                failed_gates=sorted(f for f in gates if by_factor[f] < GATE_SCORE),
                total=round(total, 4),
            )
        )
    _baseline(options, notes)
    ranked = sorted(
        options,
        key=lambda o: (
            bool(o.failed_gates),
            -o.total,
            _open_gaps(o, gap_needs),
            len(o.needs_proof),
            sum(a.delivery_mode == "CUSTOM" for a in o.approach),
            int(o.id.split("-")[1]),
        ),
    )
    for rank, option in enumerate(ranked, start=1):
        option.rank = rank
    return SolutionOptions(
        options=options, weighting=weighting, hypothetical=not policy_loaded, notes=notes
    )


def _open_gaps(option: SolutionOption, gap_needs: set[str]) -> int:
    modes = {a.need_id: a.delivery_mode for a in option.approach}
    return sum(modes.get(need) not in OPEN_MODES for need in gap_needs)


def _baseline(options: list[SolutionOption], notes: list[str]) -> None:
    marked = [o for o in options if o.baseline]
    if not marked:
        fewest = min(options, key=lambda o: sum(a.delivery_mode == "CUSTOM" for a in o.approach))
        fewest.baseline = True
        notes.append(
            f"no option was marked the baseline: {fewest.id}, with the fewest CUSTOM needs"
        )
    for extra in marked[1:]:
        extra.baseline = False
        notes.append(f"{extra.id} lost its baseline mark: {marked[0].id} keeps it")


def write_options(run_dir: Path, options: SolutionOptions) -> None:
    """`options.json`, written by this function only."""
    body = json.dumps(options.model_dump(mode="json"), indent=1, ensure_ascii=False) + "\n"
    (run_dir / "options.json").write_text(body, encoding="utf-8", newline="\n")
