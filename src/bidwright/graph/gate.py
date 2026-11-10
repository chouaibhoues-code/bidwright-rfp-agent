"""`solution_gate` (Iteration 3, step 10; ADR-035, ADR-046): a person approves the manifest
before anything is drafted from it.

`solution_gate` computes the bid signal (`signal.py`) and writes `bid_signal.json` and
`bid_memo.md`, then `review/solution_gate.md` (`write_review`): the chosen option and the
ranking with each score and reason, how each option answers each need and what supports that
(a need answered with no claim says so), each option's assumptions, the capability map, the
manifest's work packages with their evidence class and claims, its assumptions and ground
rules as an edit numbers them, its checks, every technology verdict, the risks, the bid
signal, the research's origin, and how to decide (ADR-060). It then asks for the approval
through LangGraph's `interrupt()`, and the run's part ends `WAITING_HUMAN`; resumed, LangGraph
runs the node again from its start, so it writes the same files again and `interrupt()` returns
the approval (C7-06, checked again 2026-11-05).

The approval is a `GateApproval` in ADR-035's format. It is void, and the gate asks again, when
it does not validate, names another gate or run, carries `reviewed` hashes that no longer match
`manifest.json` and `options.json`, or approves a blocked gate without an override. A gate is
blocked while a technology claim is `INVALIDATED`. Then:
- `reject` writes the approval and raises `PolicyBlocked` with "GATE_REJECTED";
- an `option_id` other than the manifest's sends the run back to `blueprint`;
- `edit` applies the edits with `blueprint.apply_edits`, writes `manifest.json` again through
  `blueprint.write_manifest`, records its hash in `edited_sha256`, and sends the run to
  `techcheck` for the changed work packages; when the gate comes round again and the manifest's
  hash still equals `edited_sha256`, it passes without asking, unless a technology claim
  now blocks it;
- `approve` goes on to `draft`.
Automatic approval (`mode="auto"`, for tests, matrices and recordings) approves the top-ranked
option with `auto_selected`, and never passes a blocked gate: it raises `PolicyBlocked` with
"GATE_BLOCKED". `write_approval` is the one writer of `review/solution_gate.approval.yaml`.
"""

import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from langgraph.types import interrupt
from pydantic import ValidationError

from bidwright.config import BidPolicy
from bidwright.fileio import write_atomic
from bidwright.graph.blueprint import EDITABLE, apply_edits, write_manifest
from bidwright.graph.signal import SignalInputs, compute_signal, memo, write_signal
from bidwright.guard import PolicyBlocked
from bidwright.schemas import (
    BidSignal,
    CapabilityMap,
    ClarificationQuestion,
    GateApproval,
    ReviewedHashes,
    Risk,
    SolutionManifest,
    SolutionOptions,
    TechValidation,
)

GATE = "solution_gate"
REVIEW_FILE = "review/solution_gate.md"
APPROVAL_FILE = "review/solution_gate.approval.yaml"
BLOCKED = "GATE_BLOCKED"
REJECTED = "GATE_REJECTED"
AUTO_ROLE = "automatic approval, for evaluation only"
GateMode = Literal["wait", "auto"]
Next = Literal["draft", "blueprint", "techcheck"]


def file_hash(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def reviewed_hashes(run_dir: Path) -> ReviewedHashes:
    """The hashes of the two files the approver reviews."""
    return ReviewedHashes(
        manifest=file_hash(run_dir / "manifest.json"), options=file_hash(run_dir / "options.json")
    )


def blocking(validations: Sequence[TechValidation]) -> list[str]:
    """The technology claims that block the gate: those still `INVALIDATED`."""
    return [v.claim_id for v in validations if v.verdict == "INVALIDATED"]


@dataclass(frozen=True)
class GateInputs:
    """What the review shows and the signal reads."""

    options: SolutionOptions
    capability_map: CapabilityMap
    manifest: SolutionManifest
    tech_validations: Sequence[TechValidation]
    risks: Sequence[Risk]
    questions: Sequence[ClarificationQuestion]
    signal_inputs: SignalInputs
    policy: BidPolicy | None = None
    policy_sha256: str | None = None
    research_origin: str = "research off"
    amounts: Sequence[re.Pattern[str]] = ()


@dataclass
class GateOutcome:
    next: Next
    approval: GateApproval
    manifest: SolutionManifest
    signal: BidSignal
    changed: list[str] = field(default_factory=list)  # work packages an edit changed


def read_approval(run_dir: Path) -> GateApproval | None:
    path = run_dir / APPROVAL_FILE
    if not path.is_file():
        return None
    try:
        return GateApproval.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (yaml.YAMLError, ValidationError):
        return None


def write_approval(run_dir: Path, approval: GateApproval) -> None:
    """`review/solution_gate.approval.yaml`, written by this function only."""
    body = yaml.safe_dump(
        approval.model_dump(mode="json"), sort_keys=False, allow_unicode=True, width=100
    )
    write_atomic(run_dir / APPROVAL_FILE, body)


def void(
    approval: GateApproval, run_id: str, hashes: ReviewedHashes, blocked: Sequence[str]
) -> str | None:
    """Why an approval cannot be acted on, or None."""
    if approval.gate != GATE or approval.run_id != run_id:
        return f"the approval is for {approval.gate} of {approval.run_id}, not this gate"
    if approval.reviewed != hashes:
        return "manifest.json or options.json changed after it was reviewed"
    if blocked and approval.decision != "reject" and not approval.override_reason:
        return f"the gate is blocked by {', '.join(blocked)}; approving it needs --override"
    return None


def auto_approval(
    run_id: str, hashes: ReviewedHashes, options: SolutionOptions, now: datetime
) -> GateApproval:
    top = min(options.options, key=lambda o: o.rank) if options.options else None
    return GateApproval(
        run_id=run_id,
        reviewed=hashes,
        decision="approve",
        option_id=top.id if top is not None else None,
        approver_role=AUTO_ROLE,
        decided=now,
        auto_selected=True,
    )


def solution_gate(
    run_dir: Path,
    run_id: str,
    inputs: GateInputs,
    *,
    mode: GateMode,
    ask: Callable[[Any], Any] = interrupt,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> GateOutcome:
    """The node's work: the signal, the review, the approval and where the run goes next."""
    signal = compute_signal(inputs.policy, inputs.policy_sha256, inputs.signal_inputs)
    text = memo(
        signal, inputs.options, inputs.questions, inputs.tech_validations, amounts=inputs.amounts
    )
    write_signal(run_dir, signal, text)
    hashes = reviewed_hashes(run_dir)
    manifest = inputs.manifest
    blocked = blocking(inputs.tech_validations)
    stored = read_approval(run_dir)
    if (
        stored is not None
        and stored.edited_sha256 == hashes.manifest
        and (not blocked or stored.override_reason)
    ):
        return GateOutcome("draft", stored, manifest, signal)  # the edited manifest, unchanged
    write_review(run_dir, run_id, inputs, signal, hashes, blocked)
    if mode == "auto":
        if blocked:
            raise PolicyBlocked(f"{BLOCKED}: technology claims INVALIDATED: {', '.join(blocked)}")
        approval = auto_approval(run_id, hashes, inputs.options, now())
    else:
        approval = _asked(ask, run_id, hashes, blocked)
    if approval.decision == "reject":
        write_approval(run_dir, approval)
        raise PolicyBlocked(f"{REJECTED}: {approval.reject_reason}")
    if approval.option_id is not None and approval.option_id != manifest.option_id:
        write_approval(run_dir, approval)
        return GateOutcome("blueprint", approval, manifest, signal)
    if approval.decision == "edit":
        edited, changed = apply_edits(manifest, approval.edits)
        write_manifest(run_dir, edited)
        approval = approval.model_copy(
            update={"edited_sha256": file_hash(run_dir / "manifest.json")}
        )
        write_approval(run_dir, approval)
        return GateOutcome("techcheck", approval, edited, signal, changed)
    write_approval(run_dir, approval)
    return GateOutcome("draft", approval, manifest, signal)


def _asked(
    ask: Callable[[Any], Any], run_id: str, hashes: ReviewedHashes, blocked: Sequence[str]
) -> GateApproval:
    """Ask until an approval can be acted on: each void one asks again."""
    note: str | None = None
    while True:
        value = ask(
            {
                "gate": GATE,
                "review": REVIEW_FILE,
                "command": f"bidwright approve {run_id} --role ROLE",
                "blocked_by": list(blocked),
                "note": note,
            }
        )
        try:
            approval = GateApproval.model_validate(value)
        except ValidationError as exc:
            note = f"the approval does not validate: {exc.errors()[0]['msg']}"
            continue
        note = void(approval, run_id, hashes, blocked)
        if note is None:
            return approval


# --- the review file ------------------------------------------------------------------------


def _cell(text: object) -> str:
    return " ".join(str(text).split()).replace("|", "/")


def write_review(
    run_dir: Path,
    run_id: str,
    inputs: GateInputs,
    signal: BidSignal,
    hashes: ReviewedHashes,
    blocked: Sequence[str],
) -> Path:
    manifest, options = inputs.manifest, inputs.options
    ranked = sorted(options.options, key=lambda o: o.rank)
    chosen = next((o for o in options.options if o.id == manifest.option_id), None)
    lines = [
        "# Solution gate",
        "",
        f"Status: UNREVIEWED_DRAFT. Run `{run_id}`. Reviewed `manifest.json` {hashes.manifest}"
        f" and `options.json` {hashes.options}.",
        "",
        "## The chosen option",
        "",
    ]
    if chosen is not None:
        lines.append(
            f"{chosen.id}, {chosen.name}: rank {chosen.rank}, total {chosen.total:g} of 4."
        )
        lines.append(f"{chosen.summary}")
    else:
        lines.append("No option is chosen.")
    lines.append("")
    if options.hypothetical:
        lines.append("The ranking is hypothetical: no approved bid policy is loaded.")
    if options.weighting == "equal":
        lines.append("Every factor counts equally, so the ranking is provisional.")
    lines += [
        "",
        "## The ranking",
        "",
        "| Rank | Option | Total | Failed gates | Cites unsupported claims |",
    ]
    lines.append("|---|---|---|---|---|")
    for o in ranked:
        gates = ", ".join(o.failed_gates) or "none"
        proof = ", ".join(o.needs_proof) or "none"
        lines.append(f"| {o.rank} | {o.id} {_cell(o.name)} | {o.total:g} | {gates} | {proof} |")
    for o in ranked:
        for s in o.scores:
            lines.append(f"- {o.id} {s.factor_id}: {s.score} of 4. {_cell(s.reason)}")
    # How each option answers each need, and what supports that: a need answered with no
    # claim rests on the option's assumptions, which `needs_proof` cannot show (ADR-060).
    for o in ranked:
        for a in o.approach:
            if a.delivery_mode == "EXCLUDED":
                support = "left out"
            elif a.claim_ids:
                support = "claims " + ", ".join(a.claim_ids)
            else:
                support = "no claim: rests on the option's assumptions"
            lines.append(f"- {o.id} answers {a.need_id} as {a.delivery_mode}; {support}.")
        lines += [f"- {o.id} assumes: {_cell(text)}" for text in o.assumptions]
    lines += ["", "## The capability map", "", "| Need | Origin | Status | Claims | Note |"]
    lines.append("|---|---|---|---|---|")
    for row in inputs.capability_map.rows:
        lines.append(
            f"| {row.need_id} {_cell(row.text)} | {row.origin} | {row.status}"
            f" | {', '.join(row.claim_ids) or 'none'} | {_cell(row.reason)} |"
        )
    lines += [
        "",
        "## The work packages",
        "",
        "| Code | Name | Effort (days) | Predecessors | Evidence | Claims |",
    ]
    lines.append("|---|---|---|---|---|---|")
    for p in manifest.work_packages:
        effort = f"{p.effort.low_days:g} to {p.effort.high_days:g}" if p.effort else "none"
        evidence = p.evidence_class + (", needs proof" if p.needs_proof else "")
        lines.append(
            f"| {p.code} | {_cell(p.name)} | {effort} | {', '.join(p.predecessors) or 'none'}"
            f" | {evidence} | {', '.join(p.claim_ids) or 'none'} |"
        )
    lines += ["", "## Assumptions and ground rules", ""]
    facts = [("Assumption", f) for f in manifest.assumptions] + [
        ("Ground rule", f) for f in manifest.ground_rules
    ]
    counts: dict[str, int] = {}
    for kind, fact in facts:
        counts[kind] = counts.get(kind, 0) + 1
        lines.append(f"- {kind} {counts[kind]} ({fact.evidence_class}): {_cell(fact.text)}")
    if not facts:
        lines.append("None.")
    lines += ["", "## The manifest's checks", "", "| Check | Passed | Detail |", "|---|---|---|"]
    for check in manifest.checks:
        lines.append(
            f"| {check.name} | {'yes' if check.passed else 'no'} | {_cell(check.detail)} |"
        )
    lines += ["", "## Technology claims", "", "| Claim | Library | Verdict | Reason |"]
    lines.append("|---|---|---|---|")
    for v in inputs.tech_validations:
        lines.append(f"| {v.claim_id} | {v.library or 'none'} | {v.verdict} | {_cell(v.reason)} |")
    if blocked:
        lines += ["", f"**Blocked** by {', '.join(blocked)}: approving needs `--override REASON`."]
    lines += ["", "## Risks", ""]
    lines += [f"- {r.id}: {_cell(r.event)} ({r.owner_role})" for r in inputs.risks] or ["None."]
    lines += ["", "## The bid signal", "", f"{signal.signal}."]
    lines += [f"- {t.id} ({t.when}): {', '.join(t.record_ids)}" for t in signal.triggers]
    if signal.missing_inputs:
        lines.append(f"Missing for a signal: {', '.join(signal.missing_inputs)}.")
    lines += ["", "## Research", "", inputs.research_origin, ""]
    lines += [
        "## How to decide",
        "",
        f"    bidwright approve {run_id} --role ROLE [--option OPT-n] [--edit FILE]"
        " [--override REASON] [--reject REASON]",
        "",
        "An edit file is a YAML list of `{field, value}`. The fields an edit may change are "
        + ", ".join(f"`{p}`" for p in EDITABLE)
        + "; `<n>` counts from 1, as the manifest lists them.",
        "",
    ]
    path = run_dir / REVIEW_FILE
    write_atomic(path, "\n".join(lines))
    return path


__all__ = [
    "APPROVAL_FILE",
    "BLOCKED",
    "GATE",
    "REJECTED",
    "REVIEW_FILE",
    "GateInputs",
    "GateOutcome",
    "auto_approval",
    "blocking",
    "file_hash",
    "read_approval",
    "reviewed_hashes",
    "solution_gate",
    "void",
    "write_approval",
    "write_review",
]
