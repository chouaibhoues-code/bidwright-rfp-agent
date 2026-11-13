"""`blueprint` (Iteration 3, step 7; ADR-043): the chosen option expanded into the
`SolutionManifest`, in two calls checked in code, and its view as `approach.json`.

- **P01, the plan** (`blueprint.md`): workstreams, a work breakdown, the current and target
  state, assumptions, ground rules and technology claims. `settle_plan` gives the plan at most
  one format repair, for a schema failure or a failed tree check, and one closure repair
  naming the `BINDING` requirements in no work package whose need the option does not exclude;
  a second format failure is a blueprint failure. A closure repair whose answer fails keeps
  the plan before it. The requirements still in no work package go to `gaps`.
- **P02, the detail** (`blueprint_detail.md`): per work package its scope, exclusions,
  acceptance, effort, verification and predecessors; per workstream its PDCA; the benefits
  and the win themes. One format repair; a second failure is a blueprint failure, and the
  manifest keeps the plan.
- **P03, the revision** (`blueprint.md`'s `revise`), after an `INVALIDATED` technology claim:
  the plan again, settled as P01's, then P02 again as `P02-revision`; the manifest's revision
  becomes 1. A revision that fails keeps the manifest it revised, with a note.

`build_manifest` applies section 4.5's checks, each failure in `checks`, and each change in
`notes`: the tree, the 100% rule, the backward trace, the dictionary, effort (maturity
`CLASS_5`, always provisional), schedule logic (an edge closing a cycle is removed), and
provenance (an unknown id is dropped; a fact's class is its strongest source's, and a fact or
work package citing a claim that is not supported is `ASSUMPTION` with `needs_proof`). A fact
holding a currency amount, or a calendar date that no passage of the run holds, is dropped;
in any other text the amount or date becomes "[removed]". `approach_view` is the manifest's
view for `write_approach`, and `write_manifest` the one writer of `manifest.json`;
`apply_edits` (step 10) applies the edits a person approves at `solution_gate`, on the
fields `EDITABLE` lists, and refuses any other field, a value of the wrong type, an effort
range turned upside down, an unknown predecessor or one that closes a cycle. Context
manifests are `blueprint-P01.json`, `-P01-repair`, `-P01-closure`, `P02`, `P02-repair`, `P03`
and its repairs, and `P02-revision`.
"""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from bidwright.fileio import write_atomic
from bidwright.graph.decide import NeedPlan, cut
from bidwright.graph.nodes import (
    MALFORMED_TWICE,
    ApproachOutcome,
    CallManifests,
    RunContext,
    _short,
)
from bidwright.kb import Role
from bidwright.llm.schema import sha256_of
from bidwright.llm.types import Message
from bidwright.prompts import Prompt
from bidwright.schemas import (
    FACT_TEXT_MAX_CHARS,
    ApproachItem,
    AssessmentDisposition,
    Benefit,
    BlueprintDetail,
    BlueprintDetailTask,
    BlueprintPlan,
    BlueprintPlanTask,
    BriefItem,
    BriefItemView,
    CapabilityClaim,
    CapabilityMap,
    ClaimView,
    CoverageStatus,
    EffortEstimate,
    EvidenceAssessment,
    EvidenceClass,
    Fact,
    FactProposal,
    GateEdit,
    InvalidatedView,
    ManifestCheck,
    ManifestGap,
    NeedApproach,
    OpportunityBrief,
    OptionView,
    Passage,
    Pdca,
    Requirement,
    RevisionTask,
    RoleView,
    SolutionManifest,
    SolutionOption,
    TechClaim,
    Verification,
    WbsNode,
    WbsNodeProposal,
    WinTheme,
    WorkPackage,
    Workstream,
)
from bidwright.verify import dates, values

NODE = "blueprint"
DETAIL = "blueprint_detail"  # P02's prompt; its calls run under the node name `blueprint`
REMOVED = "[removed]"
MAX_STATE_FACTS = 3
MAX_TECH_CLAIMS = 99  # TC-01 to TC-99
SUPPORTING = frozenset({"SUPPORTED", "PARTIALLY_SUPPORTED"})
STRENGTH: tuple[EvidenceClass, ...] = (
    "RFP_SOURCE",
    "CAPABILITY_EVIDENCE",
    "EXTERNAL_RESEARCH",
    "ASSUMPTION",
)  # strongest first
TREE_FAILED = "blueprint: the plan failed its tree check twice"
SCHEMA_FAILED = f"blueprint: {MALFORMED_TWICE}"
_CODE = re.compile(r"^\d+(\.\d+)*$")


# --- what the plan may cite -----------------------------------------------------------------


@dataclass(frozen=True)
class Sources:
    """The run's records a fact or work package may cite, and what code checks them against."""

    passages: Mapping[str, Passage]
    requirements: Mapping[str, Requirement]  # BINDING and OPTIONAL, by id
    binding: Sequence[str]  # BINDING requirement ids, in run order
    need_of: Mapping[str, str]  # requirement id to need id
    need_status: Mapping[str, CoverageStatus]
    excluded: frozenset[str]  # the needs the chosen option marks EXCLUDED
    claims: Mapping[str, CapabilityClaim]
    supported: frozenset[str]  # claims assessed SUPPORTED or PARTIALLY_SUPPORTED
    domain_items: frozenset[str]
    roles: Mapping[str, Role]
    amounts: Sequence[re.Pattern[str]] = ()  # the AMOUNT cue's patterns
    known_dates: frozenset[date] = frozenset()  # the dates the run's passages state

    def clean(self, text: str) -> tuple[str, bool]:
        """`text` with each currency amount, and each date no passage holds, as "[removed]"."""
        changed = False
        for pattern in self.amounts:
            text, count = pattern.subn(REMOVED, text)
            changed |= count > 0
        spans = [span for span, value in dates(text) if value not in self.known_dates]
        for start, end in sorted(spans, reverse=True):
            text, changed = text[:start] + REMOVED + text[end:], True
        return text, changed


def sources(
    passages: Mapping[str, Passage],
    requirements: Sequence[Requirement],
    plan: NeedPlan,
    capability_map: CapabilityMap,
    option: SolutionOption,
    claims: Sequence[CapabilityClaim],
    assessments: Sequence[EvidenceAssessment],
    domain_item_ids: Iterable[str],
    roles: Sequence[Role],
    amounts: Sequence[re.Pattern[str]] = (),
) -> Sources:
    chosen = [r for r in requirements if r.disposition in ("BINDING", "OPTIONAL")]
    need_of = {r.id: n.need_id for n in [*plan.needs, *plan.overflow] for r in n.requirements}
    known = {v for p in passages.values() for v in values(p.text) if isinstance(v, date)}
    return Sources(
        passages=passages,
        requirements={r.id: r for r in chosen},
        binding=[r.id for r in chosen if r.disposition == "BINDING"],
        need_of=need_of,
        need_status={row.need_id: row.status for row in capability_map.rows},
        excluded=frozenset(a.need_id for a in option.approach if a.delivery_mode == "EXCLUDED"),
        claims={c.id: c for c in claims},
        supported=frozenset(a.claim_id for a in assessments if a.disposition in SUPPORTING),
        domain_items=frozenset(domain_item_ids),
        roles={r.id: r for r in roles},
        amounts=amounts,
        known_dates=frozenset(known),
    )


def plan_task(
    option: SolutionOption,
    plan: NeedPlan,
    claims: Sequence[CapabilityClaim],
    assessments: Sequence[EvidenceAssessment],
    brief: OpportunityBrief | None,
) -> BlueprintPlanTask:
    by_claim: dict[str, AssessmentDisposition] = {a.claim_id: a.disposition for a in assessments}

    def items(rows: Sequence[BriefItem]) -> list[BriefItemView]:
        return [BriefItemView(id=item.id, text=item.text) for item in rows]

    return BlueprintPlanTask(
        option=OptionView(
            option_id=option.id,
            name=option.name,
            summary=option.summary,
            approach=[
                NeedApproach(
                    need_id=a.need_id, delivery_mode=a.delivery_mode, claim_ids=a.claim_ids
                )
                for a in option.approach
            ],
            assumptions=option.assumptions,
        ),
        needs=plan.needs,
        claims=[
            ClaimView(claim_id=c.id, text=c.text, disposition=by_claim.get(c.id)) for c in claims
        ],
        scope_in=items(brief.scope_in) if brief else [],
        scope_out=items(brief.scope_out) if brief else [],
        constraints=items(brief.constraints) if brief else [],
        never=items(brief.never) if brief else [],
    )


def role_views(roles: Sequence[Role]) -> list[RoleView]:
    return [RoleView(id=r.id, title=r.title, summary=r.summary) for r in roles]


# --- the tree -------------------------------------------------------------------------------


def parent(code: str) -> str | None:
    return code.rsplit(".", 1)[0] if "." in code else None


def leaves(wbs: Sequence[WbsNodeProposal]) -> list[WbsNodeProposal]:
    """The work packages: the nodes no other node names as its parent."""
    parents = {parent(n.code) for n in wbs}
    return [n for n in wbs if n.code not in parents]


def tree_problems(plan: BlueprintPlan) -> list[str]:
    codes = [n.code for n in plan.wbs]
    if not codes:
        return ["the breakdown is empty"]
    problems = [f"{c!r} is not a code such as 1.2" for c in codes if not _CODE.match(c)]
    if problems:
        return problems
    seen: set[str] = set()
    for code in codes:
        if code in seen:
            problems.append(f"code {code} appears twice")
        seen.add(code)
    for code in dict.fromkeys(codes):
        up = parent(code)
        if up is not None and up not in seen:
            problems.append(f"the parent {up} of {code} is missing")
    if all(parent(c) is None for c in codes):
        problems.append("the breakdown is one level deep; it needs at least two")
    tops = {c for c in seen if parent(c) is None}
    wanted = {str(n) for n in range(1, len(plan.workstreams) + 1)}
    problems += [f"top-level node {c} has no workstream" for c in sorted(tops - wanted, key=int)]
    problems += [
        f"workstream {c} has no top-level node {c}" for c in sorted(wanted - tops, key=int)
    ]
    return problems


def unplaced(plan: BlueprintPlan, src: Sources) -> list[str]:
    """The `BINDING` requirements in no work package, in run order."""
    placed = {r for leaf in leaves(plan.wbs) for r in leaf.requirement_ids}
    return [r for r in src.binding if r not in placed]


# --- the calls ------------------------------------------------------------------------------


@dataclass
class PlanOutcome:
    plan: BlueprintPlan | None
    failure: str | None = None
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def settle_plan(
    ctx: RunContext,
    prompt: Prompt,
    messages: Sequence[Message],
    input_hash: str,
    src: Sources,
    record: "Recorder",
    call_id: str,
) -> PlanOutcome:
    """P01's or P03's call, its one format repair and its one closure repair."""
    history = list(messages)
    record(call_id, history)
    answer = ctx.call(prompt, history, BlueprintPlan, node=NODE, input_hash=input_hash)
    format_used = closure_used = False
    settled: BlueprintPlan | None = None  # the last plan that passed the tree check
    notes: list[str] = []
    while True:
        history.append(answer.as_message())
        plan = answer.parsed if isinstance(answer.parsed, BlueprintPlan) else None
        problems = tree_problems(plan) if plan is not None else []
        if plan is None or problems:
            if settled is not None:  # the closure repair's answer failed: keep the plan
                notes.append(
                    f"{call_id}: the closure repair's answer failed; the plan before it kept"
                )
                return PlanOutcome(settled, notes=notes)
            if format_used:
                failure = TREE_FAILED if plan is not None else SCHEMA_FAILED
                return PlanOutcome(None, failure, problems, notes)
            format_used = True
            error = "; ".join(problems) if plan is not None else _short(answer.parse_error)
            message = prompt.task_text("repair_format", error=error)
            suffix = "-repair"
        else:
            settled = plan
            wanted = [r for r in unplaced(plan, src) if src.need_of.get(r) not in src.excluded]
            if not wanted or closure_used:
                return PlanOutcome(plan, notes=notes)
            closure_used = True
            message = prompt.task_text("repair_closure", ids=", ".join(wanted))
            suffix = "-closure"
        history.append(Message("user", message))
        input_hash = sha256_of([input_hash, message])
        record(call_id + suffix, history)
        answer = ctx.call(prompt, history, BlueprintPlan, node=NODE, input_hash=input_hash)


class Recorder:
    """Writes each call's context manifest before the call, naming the task's records."""

    def __init__(
        self,
        manifests: CallManifests | None,
        prompt: Prompt,
        records: Sequence[str],
        data: str,
        rendered: int,
    ) -> None:
        self.manifests, self.prompt, self.records = manifests, prompt, list(records)
        self.data, self.rendered = data, rendered

    def __call__(self, call_id: str, history: Sequence[Message]) -> None:
        if self.manifests is not None:
            turns = list(history[self.rendered :])
            self.manifests.record(self.prompt, NODE, call_id, self.records, self.data, turns)


def _records(task: BlueprintPlanTask) -> list[str]:
    needs = [n.need_id for n in task.needs]
    return [
        *needs,
        *(r.id for n in task.needs for r in n.requirements),
        *(c.claim_id for c in task.claims),
    ]


def detail(
    ctx: RunContext,
    plan: BlueprintPlan,
    claims: Sequence[ClaimView],
    roles: Sequence[RoleView],
    manifests: CallManifests | None,
    call_id: str = "P02",
) -> BlueprintDetail | None:
    prompt = ctx.prompts[DETAIL]
    task = BlueprintDetailTask(plan=plan, claims=list(claims), roles=list(roles))
    data = task.model_dump_json()
    rendered = prompt.render(data, run_id=ctx.run_id)
    records = [leaf.code for leaf in leaves(plan.wbs)] + [c.claim_id for c in claims]
    record = Recorder(manifests, prompt, records, data, len(rendered.messages))
    record(call_id, rendered.messages)
    parsed, _ = ctx.structured(
        prompt,
        list(rendered.messages),
        BlueprintDetail,
        node=NODE,
        input_hash=rendered.input_hash,
        on_repair=lambda sent: record(f"{call_id}-repair", sent),
    )
    return parsed if isinstance(parsed, BlueprintDetail) else None


@dataclass
class BlueprintOutcome:
    manifest: SolutionManifest
    plan: BlueprintPlan | None  # the settled plan, which P03 revises
    failure: str | None = None  # set when the run ends DEGRADED

    def degraded(self) -> str | None:
        return self.failure


def blueprint(
    ctx: RunContext,
    task: BlueprintPlanTask,
    src: Sources,
    manifests: CallManifests | None = None,
) -> BlueprintOutcome:
    """P01, then P02, then code's checks."""
    prompt = ctx.prompts[NODE]
    data = task.model_dump_json()
    rendered = prompt.render(data, run_id=ctx.run_id)
    record = Recorder(manifests, prompt, _records(task), data, len(rendered.messages))
    settled = settle_plan(ctx, prompt, rendered.messages, rendered.input_hash, src, record, "P01")
    return _finish(ctx, settled, task.claims, src, manifests, task.option.option_id, 0, "P02")


def revise(
    ctx: RunContext,
    plan: BlueprintPlan,
    invalidated: Sequence[InvalidatedView],
    previous: SolutionManifest,
    claims: Sequence[ClaimView],
    src: Sources,
    manifests: CallManifests | None = None,
) -> BlueprintOutcome:
    """P03 over the settled plan and the `INVALIDATED` technology claims, then P02 again."""
    prompt = ctx.prompts[NODE]
    data = RevisionTask(plan=plan, invalidated=list(invalidated)).model_dump_json()
    rendered = prompt.render(data, run_id=ctx.run_id, task="revise")
    records = [leaf.code for leaf in leaves(plan.wbs)]
    record = Recorder(manifests, prompt, records, data, len(rendered.messages))
    settled = settle_plan(ctx, prompt, rendered.messages, rendered.input_hash, src, record, "P03")
    outcome = _finish(ctx, settled, claims, src, manifests, previous.option_id, 1, "P02-revision")
    if outcome.failure is None:
        return outcome
    # The kept manifest counts as revised, so `techcheck` judges it once more and the gate
    # blocks on a claim still INVALIDATED, instead of sending it back here again (drift
    # report 2026-11-12).
    kept = previous.model_copy(deep=True, update={"revision": 1})
    kept.notes.append(
        f"the revision failed ({outcome.failure}); revision 0 kept, counted as revised"
    )
    return BlueprintOutcome(kept, plan)


def _finish(
    ctx: RunContext,
    settled: PlanOutcome,
    claims: Sequence[ClaimView],
    src: Sources,
    manifests: CallManifests | None,
    option_id: str | None,
    revision: int,
    detail_id: str,
) -> BlueprintOutcome:
    if settled.plan is None:
        manifest = failed_manifest(settled, src, option_id, revision)
        return BlueprintOutcome(manifest, None, settled.failure)
    roles = role_views(list(src.roles.values()))
    answer = detail(ctx, settled.plan, claims, roles, manifests, detail_id)
    failure = None if answer is not None else SCHEMA_FAILED
    manifest = build_manifest(
        settled.plan, answer, src, option_id=option_id, revision=revision, notes=settled.notes
    )
    if failure is not None:
        manifest.failed = True
        manifest.notes.append(f"{detail_id}: {failure}; the plan is kept without its detail")
    return BlueprintOutcome(manifest, settled.plan, failure)


def failed_manifest(
    settled: PlanOutcome, src: Sources, option_id: str | None, revision: int
) -> SolutionManifest:
    """No plan settled: every `BINDING` requirement is a gap, and the tree check fails."""
    return SolutionManifest(
        option_id=option_id,
        revision=revision,
        gaps=[_gap(r, src) for r in src.binding],
        checks=[ManifestCheck(name="tree", passed=False, detail="; ".join(settled.problems))],
        failed=True,
        notes=[*settled.notes, *([settled.failure] if settled.failure else [])],
    )


# --- the manifest ---------------------------------------------------------------------------


def _gap(requirement_id: str, src: Sources) -> ManifestGap:
    need = src.need_of.get(requirement_id)
    return ManifestGap(
        requirement_id=requirement_id,
        need_id=need,
        status=src.need_status.get(need) if need is not None else None,
    )


@dataclass
class _Build:
    """The notes, dropped ids and cleaned texts of one manifest build."""

    src: Sources
    notes: list[str]
    dropped: list[str] = field(default_factory=list)  # provenance: unknown ids
    removed: list[str] = field(default_factory=list)  # amounts and dates

    def keep(self, ids: Iterable[str], known: Iterable[str], where: str) -> list[str]:
        known = set(known)
        kept = []
        for one in dict.fromkeys(ids):
            if one in known:
                kept.append(one)
            else:
                self.dropped.append(f"{where}: {one or 'an empty id'}")
        return kept

    def text(self, value: str, where: str) -> str:
        cleaned, changed = self.src.clean(value.strip())
        if changed:
            self.removed.append(where)
        return cleaned

    def fact(self, proposal: FactProposal, where: str) -> Fact | None:
        text = " ".join(proposal.text.split())
        if not text:
            self.notes.append(f"{where}: a fact with no text dropped")
            return None
        if self.src.clean(text)[1]:
            self.removed.append(where)
            self.notes.append(
                f"{where}: a fact holding an amount or a date no passage holds dropped"
            )
            return None
        src_ids = self.keep(proposal.src_ids, self.src.passages, where)
        requirement_ids = self.keep(proposal.requirement_ids, self.src.requirements, where)
        claim_ids = self.keep(proposal.claim_ids, self.src.claims, where)
        items = self.keep(proposal.domain_item_ids, self.src.domain_items, where)
        unsupported = [c for c in claim_ids if c not in self.src.supported]
        if unsupported:
            cls: EvidenceClass = "ASSUMPTION"
        elif src_ids or requirement_ids:
            cls = "RFP_SOURCE"
        elif claim_ids:
            cls = "CAPABILITY_EVIDENCE"
        elif items:
            cls = "EXTERNAL_RESEARCH"
        else:
            cls = "ASSUMPTION"
        return Fact(
            text=cut(text, FACT_TEXT_MAX_CHARS),
            evidence_class=cls,
            source_ids=[*src_ids, *requirement_ids, *claim_ids, *items],
            needs_proof=bool(unsupported),
        )

    def facts(
        self, proposals: Sequence[FactProposal], where: str, cap: int | None = None
    ) -> list[Fact]:
        if cap is not None and len(proposals) > cap:
            self.notes.append(
                f"{where}: facts past the first {cap} dropped: {len(proposals) - cap}"
            )
            proposals = proposals[:cap]
        kept = [self.fact(p, f"{where} {n}") for n, p in enumerate(proposals, start=1)]
        return [f for f in kept if f is not None]


def build_manifest(
    plan: BlueprintPlan,
    answer: BlueprintDetail | None,
    src: Sources,
    *,
    option_id: str | None,
    revision: int = 0,
    notes: Sequence[str] = (),
) -> SolutionManifest:
    """Section 4.5's checks over a settled plan and its detail, or the plan alone."""
    b = _Build(src, list(notes))
    workstreams = [
        Workstream(
            code=str(n),
            name=b.text(w.name, f"workstream {n}") or f"Workstream {n}",
            objective=b.text(w.objective, f"workstream {n}"),
        )
        for n, w in enumerate(plan.workstreams, start=1)
    ]
    work = {leaf.code for leaf in leaves(plan.wbs)}
    nodes, packages = [], []
    for node in plan.wbs:
        name = b.text(node.name, node.code) or f"Node {node.code}"
        deliverable = b.text(node.deliverable, node.code)
        if node.code not in work:
            if node.requirement_ids or node.need_ids or node.claim_ids:
                b.notes.append(f"{node.code} is not a work package; the ids it names dropped")
            nodes.append(WbsNode(code=node.code, name=name, deliverable=deliverable))
            continue
        packages.append(_package(b, node, name, deliverable))
    by_code = {p.code: p for p in packages}
    if answer is not None:
        _apply_detail(b, answer, by_code)
    schedule = _schedule(b, packages)
    pdca = _pdca(b, answer, workstreams) if answer is not None else []
    benefits, themes = _benefits_and_themes(b, answer) if answer is not None else ([], [])
    tech = _tech_claims(b, plan, set(by_code))
    current = b.facts(plan.current_state, "current state", MAX_STATE_FACTS)
    target = b.facts(plan.target_state, "target state", MAX_STATE_FACTS)
    assumptions = b.facts(plan.assumptions, "assumption")
    ground_rules = b.facts(plan.ground_rules, "ground rule")
    gaps = [_gap(r, src) for r in src.binding if all(r not in p.requirement_ids for p in packages)]
    checks = _checks(b, packages, gaps, themes, schedule, detailed=answer is not None)
    return SolutionManifest(
        option_id=option_id,
        revision=revision,
        current_state=current,
        target_state=target,
        workstreams=workstreams,
        wbs=nodes,
        work_packages=packages,
        assumptions=assumptions,
        ground_rules=ground_rules,
        tech_claims=tech,
        benefits=benefits,
        win_themes=themes,
        pdca=pdca,
        gaps=gaps,
        checks=checks,
        notes=b.notes,
    )


def _package(b: _Build, node: WbsNodeProposal, name: str, deliverable: str) -> WorkPackage:
    src = b.src
    requirement_ids = b.keep(node.requirement_ids, src.requirements, node.code)
    need_ids = b.keep(node.need_ids, src.need_status, node.code)
    claim_ids = b.keep(node.claim_ids, src.claims, node.code)
    unsupported = [c for c in claim_ids if c not in src.supported]
    supported = bool(claim_ids) and not unsupported
    return WorkPackage(
        code=node.code,
        name=name,
        deliverable=deliverable,
        requirement_ids=requirement_ids,
        need_ids=need_ids,
        claim_ids=claim_ids,
        evidence_class="CAPABILITY_EVIDENCE" if supported else "ASSUMPTION",
        needs_proof=bool(unsupported),
        untraced=not requirement_ids and not need_ids,
    )


def _apply_detail(b: _Build, answer: BlueprintDetail, by_code: dict[str, WorkPackage]) -> None:
    done: set[str] = set()
    for item in answer.packages:
        package = by_code.get(item.code)
        if package is None or item.code in done:
            b.notes.append(f"a detail for {item.code or 'no code'}, not a work package, dropped")
            continue
        done.add(item.code)
        package.scope = b.text(item.scope, item.code)
        package.exclusions = b.text(item.exclusions, item.code)
        package.acceptance = b.text(item.acceptance, item.code)
        effort = item.effort
        low, high = max(effort.low_days, 0), max(effort.high_days, 0)
        if (low, high) != (effort.low_days, effort.high_days):
            b.notes.append(f"{item.code}: a negative effort raised to 0")
        package.effort = EffortEstimate(
            low_days=low,
            high_days=high,
            basis=effort.basis,
            basis_text=b.text(effort.basis_text, item.code),
            role_ids=b.keep(effort.role_ids, b.src.roles, f"{item.code} roles"),
            uncertainty=b.text(effort.uncertainty, item.code),
        )
        methods: dict[str, Verification] = {}
        for v in item.verification:
            if v.requirement_id in package.requirement_ids and v.requirement_id not in methods:
                methods[v.requirement_id] = Verification(
                    requirement_id=v.requirement_id, method=v.method
                )
            else:
                b.notes.append(
                    f"{item.code}: a verification for {v.requirement_id or 'none'} dropped"
                )
        package.verification = list(methods.values())
        others = [c for c in by_code if c != item.code]
        package.predecessors = b.keep(item.predecessors, others, f"{item.code} predecessors")


def _schedule(b: _Build, packages: Sequence[WorkPackage]) -> list[str]:
    """Remove each edge that closes a cycle, visiting packages and predecessors in order."""
    by_code = {p.code: p for p in packages}
    state: dict[str, str] = {}  # "open" while on the path, "done" after
    cut_edges: list[str] = []

    def visit(code: str) -> None:
        state[code] = "open"
        package = by_code[code]
        for before in list(package.predecessors):
            if state.get(before) == "open":
                package.predecessors.remove(before)
                cut_edges.append(f"{code} after {before}")
            elif before not in state:
                visit(before)
        state[code] = "done"

    for code in by_code:
        if code not in state:
            visit(code)
    for edge in cut_edges:
        b.notes.append(f"the predecessor edge {edge} closed a cycle and was removed")
    return cut_edges


def _pdca(b: _Build, answer: BlueprintDetail, workstreams: Sequence[Workstream]) -> list[Pdca]:
    names = {w.name.casefold(): w.name for w in workstreams} | {w.code: w.name for w in workstreams}
    kept: dict[str, Pdca] = {}
    for item in answer.pdca:
        name = names.get(item.workstream.strip().casefold())
        if name is None or name in kept:
            b.notes.append(f"a PDCA for {item.workstream or 'no workstream'} dropped")
            continue
        where = f"PDCA {name}"
        kept[name] = Pdca(
            workstream=name,
            plan=b.text(item.plan, where),
            do=b.text(item.do, where),
            check=b.text(item.check, where),
            act=b.text(item.act, where),
        )
    return list(kept.values())


def _benefits_and_themes(
    b: _Build, answer: BlueprintDetail
) -> tuple[list[Benefit], list[WinTheme]]:
    benefits = []
    for n, item in enumerate(answer.benefits, start=1):
        hypothesis = b.text(item.hypothesis, f"benefit {n}")
        if not hypothesis:
            b.notes.append(f"benefit {n}: no hypothesis, dropped")
            continue
        need = b.keep([item.need_id], b.src.need_status, f"benefit {n}") if item.need_id else []
        benefits.append(
            Benefit(
                hypothesis=hypothesis,
                measure=b.text(item.measure, f"benefit {n}"),
                need_id=need[0] if need else None,
            )
        )
    themes = []
    for n, item in enumerate(answer.win_themes, start=1):
        feature = b.text(item.feature, f"win theme {n}")
        if not feature:
            b.notes.append(f"win theme {n}: no feature, dropped")
            continue
        given = item.proof_claim_id
        proof = b.keep([given], b.src.claims, f"win theme {n}") if given else []
        claim = proof[0] if proof else None
        themes.append(
            WinTheme(
                feature=feature,
                metric=b.text(item.metric, f"win theme {n}"),
                benefit=b.text(item.benefit, f"win theme {n}"),
                proof_claim_id=claim,
                proof=claim if claim is not None and claim in b.src.supported else "NO_PROOF",
            )
        )
    return benefits, themes


def _tech_claims(b: _Build, plan: BlueprintPlan, work: set[str]) -> list[TechClaim]:
    claims: list[TechClaim] = []
    for n, item in enumerate(plan.tech_claims, start=1):
        text = b.text(item.text, f"technology claim {n}")
        if not text:
            b.notes.append(f"technology claim {n}: no text, dropped")
            continue
        if len(claims) == MAX_TECH_CLAIMS:
            b.notes.append(f"technology claims past the first {MAX_TECH_CLAIMS} dropped")
            break
        code = item.wbs_code if item.wbs_code in work else None
        if item.wbs_code and code is None:
            b.notes.append(f"technology claim {n}: {item.wbs_code} is not a work package")
        library = (item.library or "").strip() or None
        claims.append(
            TechClaim(
                id=f"TC-{len(claims) + 1:02d}",
                text=text,
                library=library,
                version=((item.version or "").strip() or None) if library else None,
                wbs_code=code,
                kind="LIBRARY" if library else "NOT_CHECKABLE",
            )
        )
    return claims


def _checks(
    b: _Build,
    packages: Sequence[WorkPackage],
    gaps: Sequence[ManifestGap],
    themes: Sequence[WinTheme],
    cycles: Sequence[str],
    *,
    detailed: bool,
) -> list[ManifestCheck]:
    def check(name: str, failed: Sequence[str]) -> ManifestCheck:
        return ManifestCheck(name=name, passed=not failed, detail="; ".join(failed))

    no_detail = ["no detail: P02 failed"] if not detailed else []
    dictionary = [p.code for p in packages if not (p.scope and p.exclusions and p.acceptance)]
    effort = []
    for p in packages:
        e = p.effort
        if e is None:
            effort.append(f"{p.code}: no effort")
        elif e.low_days > e.high_days:
            effort.append(f"{p.code}: low_days above high_days")
        elif not e.basis_text:
            effort.append(f"{p.code}: no basis stated")
        elif not e.role_ids:
            effort.append(f"{p.code}: no role the knowledge base holds")
    predecessors = [d for d in b.dropped if " predecessors: " in d]
    return [
        check("tree", []),
        check("hundred_percent", [g.requirement_id for g in gaps]),
        check("backward_trace", [p.code for p in packages if p.untraced]),
        check("dictionary", no_detail or dictionary),
        check("effort", no_detail or effort),
        check("schedule", [*predecessors, *(f"cycle: {c}" for c in cycles)]),
        check("provenance", b.dropped),
        check("win_theme_proof", [t.feature for t in themes if t.proof == "NO_PROOF"]),
        check("no_prices_or_dates", b.removed),
    ]


# --- edits at the gate (step 10) -------------------------------------------------------------

EDITABLE = (
    "work_packages[<code>].effort.low_days",
    "work_packages[<code>].effort.high_days",
    "work_packages[<code>].predecessors",
    "work_packages[<code>].scope",
    "work_packages[<code>].exclusions",
    "work_packages[<code>].acceptance",
    "assumptions[<n>].text",
    "ground_rules[<n>].text",
)
_EDIT_PATH = re.compile(
    r"^(?:work_packages\[(?P<code>\d+(?:\.\d+)*)\]\."
    r"(?P<part>effort\.low_days|effort\.high_days|predecessors|scope|exclusions|acceptance)"
    r"|(?P<facts>assumptions|ground_rules)\[(?P<n>[1-9]\d*)\]\.text)$"
)


class EditRefused(ValueError):
    """An edit the gate cannot apply."""


def edit_path_problem(path: str) -> str | None:
    """Why a field path is not one an edit may change, or None."""
    if _EDIT_PATH.match(path):
        return None
    return f"{path!r} is not a field an edit may change; the fields are {', '.join(EDITABLE)}"


def apply_edits(
    manifest: SolutionManifest, edits: Sequence["GateEdit"]
) -> tuple[SolutionManifest, list[str]]:
    """The manifest with the edits applied, and the work packages they changed, in order."""
    edited = manifest.model_copy(deep=True)
    packages = {p.code: p for p in edited.work_packages}
    changed: list[str] = []
    for edit in edits:
        match = _EDIT_PATH.match(edit.field)
        if match is None:
            raise EditRefused(edit_path_problem(edit.field) or edit.field)
        if match["facts"]:
            facts = edited.assumptions if match["facts"] == "assumptions" else edited.ground_rules
            n = int(match["n"])
            if n > len(facts) or not isinstance(edit.value, str) or not edit.value.strip():
                raise EditRefused(f"{edit.field}: no such fact, or an empty text")
            facts[n - 1].text = cut(" ".join(edit.value.split()), FACT_TEXT_MAX_CHARS)
        else:
            package = packages.get(match["code"])
            if package is None:
                raise EditRefused(f"{edit.field}: no work package {match['code']}")
            _edit_package(package, match["part"], edit.value, set(packages), edit.field)
            if package.code not in changed:
                changed.append(package.code)
        edited.notes.append(f"edited at the gate: {edit.field}")
    for package in edited.work_packages:
        effort = package.effort
        if effort is not None and effort.low_days > effort.high_days:
            raise EditRefused(f"{package.code}: low_days would be above high_days")
    if _cycle(edited.work_packages):
        raise EditRefused("the edited predecessors close a cycle")
    return edited, changed


def _edit_package(
    package: WorkPackage, part: str, value: object, codes: set[str], path: str
) -> None:
    if part.startswith("effort."):
        if package.effort is None:
            raise EditRefused(f"{path}: {package.code} has no effort to edit")
        if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
            raise EditRefused(f"{path}: a number of days, 0 or more")
        setattr(package.effort, part.split(".", 1)[1], float(value))
    elif part == "predecessors":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise EditRefused(f"{path}: a list of work package codes")
        unknown = [v for v in value if v not in codes or v == package.code]
        if unknown:
            raise EditRefused(f"{path}: not other work packages: {', '.join(unknown)}")
        package.predecessors = list(dict.fromkeys(value))
    else:
        if not isinstance(value, str):
            raise EditRefused(f"{path}: a text")
        setattr(package, part, " ".join(value.split()))


def _cycle(packages: Sequence[WorkPackage]) -> bool:
    graph = {p.code: p.predecessors for p in packages}
    state: dict[str, str] = {}

    def visit(code: str) -> bool:
        state[code] = "open"
        for before in graph.get(code, []):
            if state.get(before) == "open" or (before not in state and visit(before)):
                return True
        state[code] = "done"
        return False

    return any(code not in state and visit(code) for code in graph)


# --- the view and the file ------------------------------------------------------------------


def approach_view(
    manifest: SolutionManifest, src: Sources, failure: str | None = None
) -> ApproachOutcome:
    """One approach item per workstream that names a requirement, for `write_approach`."""
    items: list[ApproachItem] = []
    for stream in manifest.workstreams:
        own = [p for p in manifest.work_packages if p.code.split(".")[0] == stream.code]
        requirement_ids = list(dict.fromkeys(r for p in own for r in p.requirement_ids))
        if not requirement_ids:
            manifest.notes.append(f"workstream {stream.code} names no requirement; not in the view")
            continue
        classes: set[EvidenceClass] = {p.evidence_class for p in own}
        weakest: EvidenceClass = max(classes, key=STRENGTH.index) if classes else "ASSUMPTION"
        items.append(
            ApproachItem(
                id=f"APP-{len(items) + 1:03d}",
                text=f"{stream.name}: {stream.objective}" if stream.objective else stream.name,
                requirement_ids=requirement_ids,
                basis=stream.objective,
                evidence_class=weakest,
                source_ids=sorted(
                    {s for r in requirement_ids for s in src.requirements[r].src_ids}
                ),
            )
        )
    gaps = {g.requirement_id for g in manifest.gaps}
    unmapped = [r for r in src.binding if r in gaps]
    return ApproachOutcome(items, unmapped, [], failure=failure)


def write_manifest(run_dir: Path, manifest: SolutionManifest) -> None:
    """`manifest.json`, written by this function only."""
    body = json.dumps(manifest.model_dump(mode="json"), indent=1, ensure_ascii=False) + "\n"
    # Whole or not at all: the gate records this file's hash in its approval.
    write_atomic(run_dir / "manifest.json", body)
