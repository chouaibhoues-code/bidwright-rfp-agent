"""The bid signal and the memo (Iteration 3, step 6; ADR-042), computed in code at the gate.

With no approved bid policy, or with an input the policy requires missing, the signal is
`UNDETERMINED`, listing what is missing. Otherwise a fatal trigger gives `NO_GO`; a condition,
or a covered share (binding needs `COVERED` or `PARTNER`) below the policy's minimum, gives
`CONDITIONAL_GO`; else `GO`. A deadline that is `not_stated`, or that names no date
`verify.values` reads, is a missing input, "submission deadline", for `deadline_within_days`;
with no binding need the covered share is `None`, and the minimum does not apply.
`bid_memo.md` is one page: the signal and its triggers with their record ids, the covered
share, the options' ranking, the open clarifications and the technology claims not validated,
and the line that a person decides. It states no chance of winning and no price: a currency
amount in a record's text is replaced by "[removed]". `write_signal` is the one writer of
`bid_signal.json` and `bid_memo.md`.
"""

import json
import re
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from bidwright.config import BidPolicy, BidRule
from bidwright.schemas import (
    BidSignal,
    BidSignalLabel,
    BidTrigger,
    CapabilityMap,
    ClarificationQuestion,
    ContractFlag,
    SolutionManifest,
    SolutionOptions,
    SubmissionHazard,
    TechValidation,
)
from bidwright.verify import values

COVERED = frozenset({"COVERED", "PARTNER"})
VALIDATED = frozenset({"VALIDATED", "NOT_CHECKABLE"})
DEADLINE = "submission deadline"
NO_POLICY = "bid policy"
REMOVED = "[removed]"


@dataclass(frozen=True)
class SignalInputs:
    """What the triggers read. A file the run has not written is None."""

    capability_map: CapabilityMap | None
    options: SolutionOptions | None
    manifest: SolutionManifest | None
    tech_validations: Sequence[TechValidation] | None
    hazards: Sequence[SubmissionHazard]
    flags: Sequence[ContractFlag]
    binding_needs: Collection[str]  # RFP needs whose group holds a BINDING requirement
    need_of: dict[str, str]  # requirement id to need id
    deadline: str  # the RFP profile's submission deadline, in the RFP's words
    started: date  # the UTC date of the run manifest's `started`


def deadline_date(text: str) -> date | None:
    """The first real date the deadline's words state, or None."""
    return next((v for v in values(text) if isinstance(v, date)), None)


def covered_share(inputs: SignalInputs) -> float | None:
    if inputs.capability_map is None or not inputs.binding_needs:
        return None
    rows = [r for r in inputs.capability_map.rows if r.need_id in inputs.binding_needs]
    if not rows:
        return None
    return round(sum(r.status in COVERED for r in rows) / len(rows), 4)


def _fired(rule: BidRule, inputs: SignalInputs, missing: list[str]) -> list[str] | None:
    """The record ids a rule fired on, or None when it did not fire."""
    gaps = (
        {r.need_id for r in inputs.capability_map.rows if r.status == "GAP"}
        if inputs.capability_map is not None
        else set()
    )
    if rule.when == "hazard_on_gap":
        hit = [
            h.id
            for h in inputs.hazards
            if any(inputs.need_of.get(r) in gaps for r in h.requirement_ids)
        ]
        return hit or None
    if rule.when == "gap_on_mandatory":
        hit = sorted(n for n in gaps if n in inputs.binding_needs)
        return hit or None
    if rule.when == "contract_flag":
        hit = [f.id for f in inputs.flags if f.category in rule.categories]
        return hit or None
    if rule.when == "deadline_within_days":
        due = deadline_date(inputs.deadline)
        if due is None:
            if DEADLINE not in missing:
                missing.append(DEADLINE)
            return None
        return [due.isoformat()] if (due - inputs.started).days <= (rule.days or 0) else None
    options = inputs.options.options if inputs.options is not None else []
    if options and all(o.needs_proof for o in options):
        return [o.id for o in options]
    return None


def compute_signal(
    policy: BidPolicy | None, policy_sha256: str | None, inputs: SignalInputs
) -> BidSignal:
    share = covered_share(inputs)
    if policy is None:
        return BidSignal(signal="UNDETERMINED", covered_share=share, missing_inputs=[NO_POLICY])
    present = {
        "capability_map": inputs.capability_map is not None,
        "options": inputs.options is not None,
        "manifest": inputs.manifest is not None,
        "tech_validations": inputs.tech_validations is not None,
    }
    missing: list[str] = [name for name in policy.required_inputs if not present[name]]
    fatal: list[BidTrigger] = []
    conditions: list[BidTrigger] = []
    for rules, found in ((policy.fatal, fatal), (policy.conditions, conditions)):
        for rule in rules:
            hit = _fired(rule, inputs, missing)
            if hit is not None:
                found.append(BidTrigger(id=rule.id, when=rule.when, record_ids=hit))
    low = (
        policy.min_covered_share is not None
        and share is not None
        and share < policy.min_covered_share
    )
    signal: BidSignalLabel
    if missing:
        signal = "UNDETERMINED"
    elif fatal:
        signal = "NO_GO"
    elif conditions or low:
        signal = "CONDITIONAL_GO"
    else:
        signal = "GO"
    return BidSignal(
        signal=signal,
        triggers=[*fatal, *conditions],
        covered_share=share,
        policy_sha256=policy_sha256,
        missing_inputs=missing,
    )


def scrub(text: str, amounts: Iterable[re.Pattern[str]]) -> str:
    for pattern in amounts:
        text = pattern.sub(REMOVED, text)
    return text


def memo(
    signal: BidSignal,
    options: SolutionOptions | None,
    questions: Sequence[ClarificationQuestion],
    tech_validations: Sequence[TechValidation] | None,
    *,
    amounts: Sequence[re.Pattern[str]] = (),
) -> str:
    """The one-page bid memo, in Markdown, from the records only. `amounts` are the AMOUNT
    cue's patterns, which remove a currency amount from any text a record carries."""
    lines = ["# Bid memo", "", "Status: UNREVIEWED_DRAFT", "", f"**Signal:** {signal.signal}"]
    if signal.missing_inputs:
        lines.append(f"Missing for a signal: {', '.join(signal.missing_inputs)}.")
    for trigger in signal.triggers:
        lines.append(f"- {trigger.id} ({trigger.when}): {', '.join(trigger.record_ids)}")
    share = "none" if signal.covered_share is None else f"{signal.covered_share:.2f}"
    lines += ["", f"**Share of binding needs covered or partnered:** {share}", ""]
    lines.append("**Options, ranked:**")
    ranked = sorted(options.options, key=lambda o: o.rank) if options is not None else []
    for option in ranked:
        name = scrub(option.name, amounts)
        gates = f", failed gates {', '.join(option.failed_gates)}" if option.failed_gates else ""
        lines.append(f"{option.rank}. {option.id}, {name}: total {option.total:g} of 4{gates}")
    if not ranked:
        lines.append("None.")
    if options is not None and options.hypothetical:
        lines.append("The ranking is hypothetical: no approved bid policy is loaded.")
    lines += ["", f"**Open clarifications:** {len(questions)}"]
    lines += [f"- {q.id}: {scrub(q.text, amounts)}" for q in questions]
    unchecked = [t.claim_id for t in tech_validations or [] if t.verdict not in VALIDATED]
    lines += ["", f"**Technology claims not validated:** {', '.join(unchecked) or 'none'}"]
    lines += ["", "A person decides whether to bid. The signal applies the policy's rules only."]
    return "\n".join(lines) + "\n"


def write_signal(run_dir: Path, signal: BidSignal, memo_text: str) -> None:
    """`bid_signal.json` and `bid_memo.md`, written by this function only."""
    body = json.dumps(signal.model_dump(mode="json"), indent=1, ensure_ascii=False) + "\n"
    (run_dir / "bid_signal.json").write_text(body, encoding="utf-8", newline="\n")
    (run_dir / "bid_memo.md").write_text(memo_text, encoding="utf-8", newline="\n")
