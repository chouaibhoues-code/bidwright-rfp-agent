"""The solution path's nodes (Iteration 3, step 12; section 4.1 of the design): from the needs
to the gate, wired by `build.py`.

`decide_plan` plans the needs and builds the knowledge-base index; `decide` is one `Send`
worker per need (a tool loop, or SO1-F's one call under `solution: fixed`); `decide_join`
numbers the claims and questions and writes `claims.jsonl` and `decisions.jsonl`; `assess` is
one `Send` worker per claim that cites evidence, on the `assess` role's route; `assess_join`
adds the claims with none and writes `assessments.jsonl`; `capability_map`, `options`,
`blueprint` (with P03 when `techcheck` found a claim `INVALIDATED`), `techcheck` and `gate`
follow. Each function takes the run's `Runtime` and the state, and returns the keys it writes.
The `solution` switch (section 4.11) decides how far the path goes: `oneshot` never enters it,
`fixed` and `decide` end at `decide_join`, `assess` at the capability map, and `manifest`, the
full path, runs the gate.
"""

import re
from collections.abc import Sequence
from dataclasses import asdict
from typing import Any

from langgraph.types import Send

from bidwright.config import compile_patterns
from bidwright.graph import blueprint as bp
from bidwright.graph.assess import (
    assess_claim,
    assessed_same_family,
    assessor_of,
    same_family_reason,
    write_assessments,
)
from bidwright.graph.capability import build_map, write_map
from bidwright.graph.decide import (
    DecideOutcome,
    NeedPlan,
    decide_fixed,
    decide_need,
    fixed_evidence,
    join,
    need_passages,
    plan_needs,
    question_number,
    research_provider,
    write_decisions,
)
from bidwright.graph.gate import SWITCH_FAILED, GateInputs, solution_gate
from bidwright.graph.nodes import MALFORMED_TWICE, CallManifests, RiskView, write_approach
from bidwright.graph.options import options_task, propose, settle, write_options
from bidwright.graph.signal import SignalInputs
from bidwright.graph.techcheck import Sources, techcheck, write_techcheck
from bidwright.guard import PolicyBlocked
from bidwright.harness.context import ContextManager
from bidwright.harness.gateway import ToolGateway
from bidwright.harness.reflect import reflect_for
from bidwright.harness.rules import RuleContext
from bidwright.kb import INDEX_FILE, KnowledgeIndex
from bidwright.llm.client import route_config
from bidwright.research.context7 import context7_docs
from bidwright.research.pack import PackRefused, library_pack_path, load_library_pack
from bidwright.retrieval import PassageIndex
from bidwright.schemas import (
    BlueprintPlan,
    CapabilityClaim,
    CapabilityMap,
    ClaimProposal,
    ClaimView,
    ClarificationQuestion,
    ContractFlag,
    Discrepancy,
    DomainBrief,
    EvidenceAssessment,
    ExcerptView,
    NeedDecision,
    NeedView,
    OpportunityBrief,
    OptionsResult,
    Requirement,
    RequirementGroup,
    ResearchRecord,
    RfpProfile,
    Risk,
    RiskClaimView,
    RiskDiscrepancyView,
    RiskGapView,
    RiskPackageView,
    SolutionManifest,
    SolutionOption,
    SolutionOptions,
    SubmissionHazard,
    TechValidation,
)
from bidwright.tools import ask_tool, capabilities_tool, search_tool, section_tool

SOLUTIONS = ("oneshot", "fixed", "decide", "assess", "manifest")
RISK_MODES = ("oneshot", "fixed", "agent")
NO_OPTION = "blueprint: no option to plan"
OPTIONS_FAILED = f"options: {MALFORMED_TWICE}"


# --- state forms ------------------------------------------------------------------------------


def plan_dict(plan: NeedPlan) -> dict[str, Any]:
    return {
        "needs": [n.model_dump(mode="json") for n in plan.needs],
        "passages": plan.passages,
        "records": plan.records,
        "overflow": [n.model_dump(mode="json") for n in plan.overflow],
    }


def plan_of(data: dict[str, Any] | None) -> NeedPlan:
    data = data or {}
    return NeedPlan(
        needs=[NeedView.model_validate(n) for n in data.get("needs", [])],
        passages=dict(data.get("passages", {})),
        records=dict(data.get("records", {})),
        overflow=[NeedView.model_validate(n) for n in data.get("overflow", [])],
    )


def outcome_dict(outcome: DecideOutcome) -> dict[str, Any]:
    data = asdict(outcome)
    data["claims"] = [c.model_dump(mode="json") for c in outcome.claims]
    return data


def outcome_of(data: dict[str, Any]) -> DecideOutcome:
    fields = dict(data)
    fields["claims"] = [ClaimProposal.model_validate(c) for c in fields.get("claims", [])]
    return DecideOutcome(**fields)


def _models(model: Any, rows: Sequence[Any] | None) -> list[Any]:
    return [model.model_validate(r) for r in rows or []]


def _brief(state: dict[str, Any]) -> OpportunityBrief | None:
    data = state.get("brief")
    return OpportunityBrief.model_validate(data["record"]) if data else None


def _domain(state: dict[str, Any]) -> DomainBrief | None:
    data = state.get("domain_brief")
    return DomainBrief.model_validate(data["brief"]) if data else None


def _manifests(rt: Any, node: str) -> CallManifests:
    manager = ContextManager(
        rt.run_dir, rt.config.limits.context, list(rt.ctx.passages.values()), cards=rt.cards
    )
    return CallManifests(manager, rt.config.limits.context.budgets[node])


def _kb_index(rt: Any) -> KnowledgeIndex:
    path = rt.run_dir / INDEX_FILE
    return KnowledgeIndex(path) if path.exists() else KnowledgeIndex.build(rt.kb, path)


def _patterns(rt: Any) -> list[re.Pattern[str]]:
    return compile_patterns(rt.config.ingest.suspect_patterns, "config/ingest.yaml")


def _amounts(rt: Any) -> list[re.Pattern[str]]:
    return compile_patterns(rt.config.cues.kinds.get("AMOUNT", []), "config/cues.yaml: AMOUNT")


# --- decide ---------------------------------------------------------------------------------


def decide_plan(rt: Any, state: dict[str, Any]) -> dict[str, Any]:
    plan = plan_needs(
        _models(RequirementGroup, state.get("group_records")),
        _models(Requirement, state.get("requirements")),
        _domain(state),
        cap=rt.config.limits.solution.need_cap,
        excerpts=_excerpt_views(rt),
    )
    KnowledgeIndex.build(rt.kb, rt.run_dir / INDEX_FILE)
    return {"needs": plan_dict(plan)}


def decide_sends(rt: Any, state: dict[str, Any]) -> list[Send] | str:
    plan = plan_of(state.get("needs"))
    if not plan.needs:
        return "decide_join"
    return [
        Send(
            "decide",
            {
                "need": need.model_dump(mode="json"),
                "passages": plan.passages.get(need.need_id, []),
                "records": plan.records.get(need.need_id, []),
            },
        )
        for need in plan.needs
    ]


def _excerpt_views(rt: Any) -> dict[str, ExcerptView]:
    """The run's clean research excerpts by id, with their sources' titles and tiers, for the
    `DOMAIN` needs `decide` answers: the pack `discover_load` loaded, or the run's own research
    in research mode `live`. A pack withheld because it changed is recorded as an event (drift
    report 2026-11-12)."""
    config = rt.config
    provider, note = research_provider(
        rt.research_mode,
        _research_record(rt),
        packs_dir=config.research.packs_dir,
        questions=config.research.questions,
        patterns=_patterns(rt),
        run_dir=rt.run_dir,
    )
    if note and rt.events is not None:
        rt.events.record("research", "decide", note)
    if provider is None:
        return {}
    sources = {s.id: s for s in provider.pack.sources}
    return {
        e.id: ExcerptView(
            id=e.id,
            source_title=sources[e.source_id].title,
            tier=sources[e.source_id].tier,
            text=e.text,
        )
        for e in provider.pack.excerpts
        if not e.quarantined and e.source_id in sources
    }


def _research_record(rt: Any) -> ResearchRecord | None:
    path = rt.run_dir / "research.json"
    if not path.is_file():
        return None
    return ResearchRecord.model_validate_json(path.read_text(encoding="utf-8"))


def decide_gateway(rt: Any, need: NeedView | None = None) -> ToolGateway:
    """`decide`'s tools; `search_rfp` maps the need's requirement ids to the passages they
    quote, as its description promises (drift report 2026-11-12)."""
    config, ctx = rt.config, rt.ctx
    limits = config.agents.agents["decide"].limits
    passages = list(ctx.passages.values())
    index = rt.index or PassageIndex(rt.run_dir / "search.sqlite")
    listed: list[Any] = [
        capabilities_tool(_kb_index(rt)),
        search_tool(index, {r.id: r.src_ids for r in need.requirements} if need else None),
        section_tool(passages, ctx.view),
    ]
    provider, _ = research_provider(
        rt.research_mode,
        _research_record(rt),
        packs_dir=config.research.packs_dir,
        questions=config.research.questions,
        patterns=_patterns(rt),
        run_dir=rt.run_dir,
    )
    if provider is not None:
        listed.append(ask_tool(provider, max_excerpts=config.research.questions.max_matches))
    if rt.reflect:
        listed.append(reflect_for(config, rt.breaker))
    context = RuleContext(
        passages=passages,
        view=ctx.view,
        events=rt.events,
        node="decide",
        max_shared_words=config.research.outbound.max_shared_words,
    )
    return ToolGateway.for_agent(
        "decide",
        allowed=config.agents.agents["decide"].tools,
        tools=listed,
        max_tool_calls=limits.max_tool_calls or 6,
        context=context,
        log=rt.tool_log,
        reflect=rt.reflect,
    )


def decide_worker(rt: Any, state: dict[str, Any]) -> dict[str, Any]:
    need = NeedView.model_validate(state["need"])
    limits = rt.config.agents.agents["decide"].limits
    if rt.reflect:
        limits = limits.model_copy(update={"reflect": True})
    cap = rt.config.limits.solution.claims_per_need
    recorder = _manifests(rt, "decide")
    if rt.solution == "fixed":
        evidence = fixed_evidence(_kb_index(rt), need)
        given = need_passages(state["passages"], rt.ctx.passages, rt.ctx.view)
        outcome = decide_fixed(
            rt.ctx,
            need,
            evidence,
            given,
            records=state["records"],
            claims_cap=cap,
            manifests=recorder,
        )
    else:
        outcome = decide_need(
            rt.ctx,
            need,
            decide_gateway(rt, need),
            limits,
            passages=state["passages"],
            records=state["records"],
            claims_cap=cap,
            manifests=recorder,
        )
    return {"decide_outcomes": [outcome_dict(outcome)]}


def decide_join(rt: Any, state: dict[str, Any]) -> dict[str, Any]:
    plan = plan_of(state.get("needs"))
    outcomes = [outcome_of(d) for d in state.get("decide_outcomes", [])]
    earlier = _models(ClarificationQuestion, state.get("questions"))
    brief = _brief(state)
    earlier += brief.questions if brief else []
    joined = join(outcomes, plan, last_question=question_number(earlier))
    write_decisions(rt.run_dir, joined)
    return {
        "decisions": [d.model_dump(mode="json") for d in joined.decisions],
        "claims": [c.model_dump(mode="json") for c in joined.claims],
        "decide_questions": [q.model_dump(mode="json") for q in joined.questions],
        "decide_degraded": joined.degraded(),
    }


def after_decide(rt: Any, state: dict[str, Any]) -> list[Send] | str:
    if rt.solution in ("fixed", "decide"):
        return "approach"
    plan = plan_of(state.get("needs"))
    needs = {n.need_id: n for n in plan.needs}
    sends = [
        Send("assess", {"claim": claim, "need": needs[claim["need_id"]].model_dump(mode="json")})
        for claim in state.get("claims", [])
        if claim.get("evidence_ids") and claim["need_id"] in needs
    ]
    return sends or "assess_join"


# --- assess and the map ---------------------------------------------------------------------


def _assess_role(rt: Any) -> tuple[Any, Any]:
    """The role on this run's route, and the profile's routed role, for the family rule."""
    base = rt.config.models.role(rt.profile, "assess")
    route = rt.assess_route or "primary"
    return route_config(rt.config, rt.profile, "assess", route), base


def _assess_one(rt: Any, claim: CapabilityClaim, need: NeedView) -> EvidenceAssessment:
    role, base = _assess_role(rt)
    prompt = rt.ctx.prompts["assess"].ref
    outcome = assess_claim(
        rt.ctx,
        claim,
        need,
        rt.kb,
        assessor=assessor_of(role, prompt),
        same_family=assessed_same_family(rt.assess_route, base),
        manifests=_manifests(rt, "assess"),
    )
    return outcome.assessment


def assess_worker(rt: Any, state: dict[str, Any]) -> dict[str, Any]:
    claim = CapabilityClaim.model_validate(state["claim"])
    need = NeedView.model_validate(state["need"])
    return {"assessed": [_assess_one(rt, claim, need).model_dump(mode="json")]}


def assess_join(rt: Any, state: dict[str, Any]) -> dict[str, Any]:
    plan = plan_of(state.get("needs"))
    needs = {n.need_id: n for n in [*plan.needs, *plan.overflow]}
    done = {a["claim_id"]: a for a in state.get("assessed", [])}
    rows: list[EvidenceAssessment] = []
    for claim in _models(CapabilityClaim, state.get("claims")):
        if claim.id in done:
            rows.append(EvidenceAssessment.model_validate(done[claim.id]))
        elif claim.need_id in needs:  # no evidence: UNVERIFIED in code, with no call
            rows.append(_assess_one(rt, claim, needs[claim.need_id]))
    write_assessments(rt.run_dir, rows)
    _, base = _assess_role(rt)
    called = any(a.called for a in rows)
    family = same_family_reason(rt.assess_route, base) if called else None
    return {"assessments": [a.model_dump(mode="json") for a in rows], "assess_degraded": family}


def capability_map(rt: Any, state: dict[str, Any]) -> dict[str, Any]:
    cmap = build_map(
        plan_of(state.get("needs")),
        _models(NeedDecision, state.get("decisions")),
        _models(CapabilityClaim, state.get("claims")),
        _models(EvidenceAssessment, state.get("assessments")),
    )
    write_map(rt.run_dir, cmap)
    return {"capability_map": cmap.model_dump(mode="json")}


def after_map(rt: Any, state: dict[str, Any]) -> str:
    if rt.until == "capability_map":
        return "__end__"
    return "approach" if rt.solution == "assess" else "options"


# --- options, blueprint and techcheck -------------------------------------------------------


def options(rt: Any, state: dict[str, Any]) -> dict[str, Any]:
    brief = _brief(state)
    assessments = _models(EvidenceAssessment, state.get("assessments"))
    task = options_task(
        brief.factors if brief else [],
        CapabilityMap.model_validate(state["capability_map"]),
        _models(CapabilityClaim, state.get("claims")),
        assessments,
        _models(NeedDecision, state.get("decisions")),
        _domain(state),
    )
    result = propose(rt.ctx, task, _manifests(rt, "options"))
    settled = settle(
        result or OptionsResult(), task, assessments, policy_loaded=rt.bid_policy is not None
    )
    write_options(rt.run_dir, settled)
    return {
        "options": settled.model_dump(mode="json"),
        "options_degraded": OPTIONS_FAILED if result is None else None,
    }


def _blueprint_sources(rt: Any, state: dict[str, Any], option: Any) -> bp.Sources:
    domain = _domain(state)
    return bp.sources(
        rt.ctx.passages,
        _models(Requirement, state.get("requirements")),
        plan_of(state.get("needs")),
        CapabilityMap.model_validate(state["capability_map"]),
        option,
        _models(CapabilityClaim, state.get("claims")),
        _models(EvidenceAssessment, state.get("assessments")),
        [i.id for i in domain.items] if domain else [],
        rt.kb.roles,
        _amounts(rt),
    )


def blueprint_option(options: SolutionOptions, state: dict[str, Any]) -> SolutionOption | None:
    """The option `blueprint` builds for: the one a switch at the gate names; else, for a
    revision after `techcheck`, the one the manifest was built for, which after a switch is not
    the top-ranked one (step 22's code review); else the top-ranked one."""
    wanted = (state.get("gate") or {}).get("option_id")
    built_for = (state.get("manifest") or {}).get("option_id")
    ranked = sorted(options.options, key=lambda o: o.rank)
    pick = wanted or built_for
    return next((o for o in ranked if o.id == pick), ranked[0] if ranked else None)


def blueprint(rt: Any, state: dict[str, Any]) -> dict[str, Any]:
    settled = SolutionOptions.model_validate(state["options"])
    wanted = (state.get("gate") or {}).get("option_id")
    option = blueprint_option(settled, state)
    if option is None:
        return {"blueprint_failed": NO_OPTION}
    src = _blueprint_sources(rt, state, option)
    claims = _models(CapabilityClaim, state.get("claims"))
    assessments = _models(EvidenceAssessment, state.get("assessments"))
    stored_plan = state.get("blueprint_plan")
    due = (state.get("techcheck") or {}).get("revision_due")
    if due and stored_plan and not wanted:
        previous = SolutionManifest.model_validate(state["manifest"])
        by_claim = {a.claim_id: a.disposition for a in assessments}
        views = [
            ClaimView(claim_id=c.id, text=c.text, disposition=by_claim.get(c.id)) for c in claims
        ]
        validations = _models(TechValidation, state.get("tech_validations"))
        from bidwright.graph.techcheck import TechcheckOutcome

        invalid = TechcheckOutcome(validations=validations, revision=0).revision_task(previous)
        outcome = bp.revise(
            rt.ctx,
            BlueprintPlan.model_validate(stored_plan),
            invalid,
            previous,
            views,
            src,
            _manifests(rt, "blueprint"),
        )
    else:
        task = bp.plan_task(option, plan_of(state.get("needs")), claims, assessments, _brief(state))
        outcome = bp.blueprint(rt.ctx, task, src, _manifests(rt, "blueprint"))
    updates: dict[str, Any] = {"techcheck": {}, "gate": {}}
    if outcome.failure is not None:
        bp.write_manifest(rt.run_dir, outcome.manifest)
        refused = failed_switch(state, outcome.failure)
        if refused is not None:
            raise PolicyBlocked(refused)
        updates |= {"manifest": outcome.manifest.model_dump(mode="json")}
        return updates | {"blueprint_failed": outcome.failure}
    view = bp.approach_view(outcome.manifest, src)
    bp.write_manifest(rt.run_dir, outcome.manifest)
    return updates | {
        "manifest": outcome.manifest.model_dump(mode="json"),
        "blueprint_plan": outcome.plan.model_dump(mode="json") if outcome.plan else stored_plan,
        "blueprint_failed": None,
        "approach": write_approach(rt.run_dir, view),
    }


def failed_switch(state: dict[str, Any], failure: str | None) -> str | None:
    """The run's `POLICY_BLOCKED` reason when the blueprint for the option a person switched
    to at the gate failed: the one-call `approach` fallback would draft from something no
    person approved, so nothing is drafted (the second architecture review, DE-01). Only a
    switch sets the gate's `option_id`."""
    wanted = (state.get("gate") or {}).get("option_id")
    if failure is None or not wanted:
        return None
    return (
        f"{SWITCH_FAILED}: the blueprint for {wanted}, the option chosen at the gate, failed"
        f" ({failure}); nothing is drafted"
    )


def after_blueprint(rt: Any, state: dict[str, Any]) -> str:
    return "approach" if state.get("blueprint_failed") else "techcheck"


def _tech_sources(rt: Any) -> Sources:
    config = rt.config
    if rt.research_mode == "live":
        docs = context7_docs(config, _patterns(rt), rt.events, rt.breaker)
        context = RuleContext(
            passages=list(rt.ctx.passages.values()),
            view=rt.ctx.view,
            events=rt.events,
            node="techcheck",
            max_shared_words=config.research.outbound.max_shared_words,
        )
        cap = 2 * config.limits.solution.tech_claim_cap
        allowed = config.agents.agents["techcheck"].tools
        return Sources("live", docs=docs, gateway=docs.gateway(context, allowed, cap, rt.tool_log))
    if rt.research_mode == "pack":
        path = library_pack_path(config.research.packs_dir)
        try:
            pack = load_library_pack(path, _patterns(rt), rt.events) if path.is_dir() else None
        except PackRefused as exc:
            pack = None
            if rt.events is not None:
                rt.events.record("research", "techcheck", f"the library pack was refused: {exc}")
        return Sources("pack", library_pack=pack, questions=config.research.questions)
    return Sources("off")


def run_techcheck(rt: Any, state: dict[str, Any]) -> dict[str, Any]:
    manifest = SolutionManifest.model_validate(state["manifest"])
    changed = set((state.get("gate") or {}).get("changed") or [])
    checked = manifest
    if changed:  # after edits at the gate: only the changed work packages' claims again
        claims = [c for c in manifest.tech_claims if c.wbs_code in changed]
        checked = manifest.model_copy(update={"tech_claims": claims})
    chars = rt.config.limits.context.chars_per_token * 4500
    outcome = techcheck(
        rt.ctx,
        checked,
        _tech_sources(rt),
        cap=rt.config.limits.solution.tech_claim_cap,
        max_chars=chars,
        manifests=_manifests(rt, "techcheck"),
    )
    if changed:
        fresh = {v.claim_id: v for v in outcome.validations}
        earlier: list[TechValidation] = _models(TechValidation, state.get("tech_validations"))
        kept: list[TechValidation] = [fresh.get(v.claim_id) or v for v in earlier]
        outcome.validations = kept + [v for v in fresh.values() if v not in kept]
    write_techcheck(rt.run_dir, outcome)
    due = outcome.revision_due() and not changed
    # A verdict call runs for each claim with documentation, on the `assess` route.
    _, base = _assess_role(rt)
    family = same_family_reason(rt.assess_route, base) if outcome.docs else None
    return {
        "tech_validations": [v.model_dump(mode="json") for v in outcome.validations],
        "techcheck": {"revision_due": due, "degraded": family},
    }


def after_techcheck(rt: Any, state: dict[str, Any]) -> str:
    return "blueprint" if (state.get("techcheck") or {}).get("revision_due") else "risk"


# --- the gate -------------------------------------------------------------------------------


def _signal_inputs(rt: Any, state: dict[str, Any]) -> SignalInputs:
    plan = plan_of(state.get("needs"))
    requirements = {r.id: r for r in _models(Requirement, state.get("requirements"))}
    binding = {
        n.need_id
        for n in plan.needs
        if any(
            requirements.get(r.id) and requirements[r.id].disposition == "BINDING"
            for r in n.requirements
        )
    }
    profile = state.get("profile")
    deadline = RfpProfile.model_validate(profile).submission_deadline if profile else "not_stated"
    started = rt.ctx.started
    if started is None:
        raise ValueError("the gate needs the run's start date")
    return SignalInputs(
        capability_map=CapabilityMap.model_validate(state["capability_map"]),
        options=SolutionOptions.model_validate(state["options"]),
        manifest=SolutionManifest.model_validate(state["manifest"]),
        tech_validations=_models(TechValidation, state.get("tech_validations")),
        hazards=_models(SubmissionHazard, state.get("hazards")),
        flags=_models(ContractFlag, state.get("flags")),
        binding_needs=binding,
        need_of={r.id: n.need_id for n in plan.needs for r in n.requirements},
        deadline=deadline,
        started=started,
    )


def gate(rt: Any, state: dict[str, Any]) -> dict[str, Any]:
    policy, sha = rt.bid_policy if rt.bid_policy is not None else (None, None)
    domain = state.get("domain_brief")
    questions = _models(ClarificationQuestion, state.get("questions"))
    questions += _models(ClarificationQuestion, state.get("decide_questions"))
    inputs = GateInputs(
        options=SolutionOptions.model_validate(state["options"]),
        capability_map=CapabilityMap.model_validate(state["capability_map"]),
        manifest=SolutionManifest.model_validate(state["manifest"]),
        tech_validations=_models(TechValidation, state.get("tech_validations")),
        risks=_models(Risk, (state.get("risk") or {}).get("risks")),
        questions=questions,
        signal_inputs=_signal_inputs(rt, state),
        policy=policy,
        policy_sha256=sha,
        research_origin=domain["origin"] if domain else f"research {rt.research_mode}",
        amounts=_amounts(rt),
    )
    outcome = solution_gate(rt.run_dir, rt.ctx.run_id, inputs, mode=rt.gate)
    switched = outcome.approval.option_id if outcome.next == "blueprint" else None
    return {
        "gate": {"next": outcome.next, "option_id": switched, "changed": outcome.changed},
        "manifest": outcome.manifest.model_dump(mode="json"),
        "bid_signal": outcome.signal.model_dump(mode="json"),
    }


def after_gate(rt: Any, state: dict[str, Any]) -> str:
    if rt.until == "solution_gate":
        return "__end__"
    return str((state.get("gate") or {}).get("next") or "draft")


def after_risk(rt: Any, state: dict[str, Any]) -> str:
    full = rt.solution == "manifest" and state.get("manifest") and not state.get("blueprint_failed")
    return "solution_gate" if full else "draft"


def risk_view(state: dict[str, Any]) -> RiskView:
    """What `risk` sees of the solution path (section 4.7). The discrepancies come from
    `consolidate` on every path; the rest is empty until a manifest or a map exists. A
    technology claim no verdict covers reads `NOT_CHECKED`."""
    discrepancies = [
        RiskDiscrepancyView(
            kind=d.kind, requirement_ids=d.requirement_ids, description=d.description
        )
        for d in _models(Discrepancy, state.get("discrepancies"))
    ]
    needs = [n.need_id for n in plan_of(state.get("needs")).needs] if state.get("needs") else []
    cmap = state.get("capability_map")
    rows = CapabilityMap.model_validate(cmap).rows if cmap else []
    gaps = [
        RiskGapView(need_id=r.need_id, text=r.text, status=r.status)
        for r in rows
        if r.status == "GAP"
    ]
    known = set(needs) | {r.need_id for r in rows}
    if not state.get("manifest"):
        return RiskView(gaps=gaps, discrepancies=discrepancies, affectable=frozenset(known))
    manifest = SolutionManifest.model_validate(state["manifest"])
    verdicts = {
        v.claim_id: v.verdict for v in _models(TechValidation, state.get("tech_validations"))
    }
    packages = [
        RiskPackageView(
            code=p.code,
            name=p.name,
            predecessors=p.predecessors,
            low_days=p.effort.low_days if p.effort else None,
            high_days=p.effort.high_days if p.effort else None,
        )
        for p in manifest.work_packages
    ]
    claims = [
        RiskClaimView(
            text=c.text,
            verdict=verdicts.get(
                c.id, "NOT_CHECKABLE" if c.kind == "NOT_CHECKABLE" else "NOT_CHECKED"
            ),
        )
        for c in manifest.tech_claims
    ]
    return RiskView(
        work_packages=packages,
        assumptions=[a.text for a in manifest.assumptions],
        tech_claims=claims,
        gaps=gaps,
        discrepancies=discrepancies,
        affectable=frozenset(known | {p.code for p in manifest.work_packages}),
    )


# --- what render and the status read ---------------------------------------------------------


def degraded_reasons(state: dict[str, Any]) -> list[str]:
    """The solution path's shortfalls, in graph order."""
    reasons = []
    plan = plan_of(state.get("needs")) if state.get("needs") else None
    if plan is not None and plan.degraded():
        reasons.append(plan.degraded())
    for key in ("decide_degraded", "assess_degraded", "options_degraded", "blueprint_failed"):
        if state.get(key):
            reasons.append(str(state[key]))
    reasons.append((state.get("techcheck") or {}).get("degraded") or "")
    return list(dict.fromkeys(r for r in reasons if r))


def solution_block(state: dict[str, Any]) -> dict[str, Any] | None:
    """The summary's solution block, or None when the run took no solution path."""
    if not state.get("capability_map"):
        return None
    cmap = CapabilityMap.model_validate(state["capability_map"])
    manifest = state.get("manifest") or {}
    tech: dict[str, int] = {}
    for v in state.get("tech_validations") or []:
        tech[v["verdict"]] = tech.get(v["verdict"], 0) + 1
    signal = state.get("bid_signal") or {}
    return {
        "option_id": manifest.get("option_id"),
        "capability_counts": dict(cmap.counts),
        "gaps": [r.need_id for r in cmap.rows if r.status == "GAP"],
        "tech_counts": tech,
        "bid_signal": signal.get("signal"),
    }


__all__ = [
    "RISK_MODES",
    "SOLUTIONS",
    "after_blueprint",
    "after_decide",
    "after_gate",
    "after_map",
    "after_risk",
    "after_techcheck",
    "assess_join",
    "assess_worker",
    "blueprint",
    "capability_map",
    "decide_join",
    "decide_plan",
    "decide_sends",
    "decide_worker",
    "degraded_reasons",
    "failed_switch",
    "gate",
    "options",
    "plan_of",
    "run_techcheck",
    "solution_block",
]
