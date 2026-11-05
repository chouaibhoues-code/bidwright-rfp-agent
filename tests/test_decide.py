"""`decide` (Iteration 3, step 4): the needs, the loop, code's checks on each answer, the
join's numbering, the fixed control, and `ask_research` from the run's own research."""

import json
from pathlib import Path

import pytest

from bidwright.config import AgentLimits, compile_patterns, load_config
from bidwright.graph.decide import (
    DecideOutcome,
    check,
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
from bidwright.graph.nodes import CallManifests
from bidwright.harness.context import ContextManager
from bidwright.harness.gateway import ToolGateway
from bidwright.harness.rules import RuleContext
from bidwright.kb import INDEX_FILE, KnowledgeIndex, load_kb
from bidwright.research.pack import load_pack
from bidwright.retrieval import PassageIndex
from bidwright.schemas import (
    ClaimProposal,
    ClarificationQuestion,
    DecideResult,
    DomainBrief,
    DomainNeed,
    ExcerptView,
    RequirementGroup,
    ResearchRecord,
    ToolRequest,
)
from bidwright.tools import ask_tool, capabilities_tool, search_tool, section_tool
from tests.node_fakes import (
    RuleBackend,
    ScriptBackend,
    context,
    dev_ingest,
    requirement,
    text,
    tools,
)

CONFIG = load_config()
LIMITS = CONFIG.agents.agents["decide"].limits
PATTERNS = compile_patterns(CONFIG.ingest.suspect_patterns, "config/ingest.yaml")
FIXTURE_PACK = Path(__file__).parent / "data" / "packs" / "fixture"

SIGNATURE = requirement(1, "SRC-0015", "The Supplier shall provide electronic signature of forms.")
QUILLBECK = requirement(2, "SRC-0020", "The Supplier shall integrate with the Quillbeck system.")
GROUPS = [
    RequirementGroup(
        id="RG-001", member_ids=["REQ-0001"], topic="Electronic signature of forms", llm=False
    ),
    RequirementGroup(id="RG-002", member_ids=["REQ-0002"], topic="Quillbeck", llm=False),
]


@pytest.fixture(scope="module")
def kb_index(tmp_path_factory: pytest.TempPathFactory) -> KnowledgeIndex:
    return KnowledgeIndex.build(load_kb(), tmp_path_factory.mktemp("kb") / INDEX_FILE)


def _gateway(tmp_path: Path, kb_index: KnowledgeIndex, *extra: object) -> ToolGateway:
    passages = dev_ingest().passages
    index = PassageIndex.build(passages, tmp_path / "search.sqlite")
    tools_list = [capabilities_tool(kb_index), search_tool(index), section_tool(passages), *extra]
    return ToolGateway.for_agent(
        "decide",
        allowed=CONFIG.agents.agents["decide"].tools,
        tools=tools_list,  # type: ignore[arg-type]
        max_tool_calls=LIMITS.max_tool_calls or 6,
        context=RuleContext(passages=passages),
    )


def _plan(cap: int = 24):  # type: ignore[no-untyped-def]
    return plan_needs(GROUPS, [SIGNATURE, QUILLBECK], None, cap=cap)


def _run(tmp_path: Path, kb_index: KnowledgeIndex, backend: object, n: int = 0) -> DecideOutcome:
    plan = _plan()
    need = plan.needs[n]
    return decide_need(
        context(backend),  # type: ignore[arg-type]
        need,
        _gateway(tmp_path, kb_index),
        LIMITS,
        passages=plan.passages[need.need_id],
        records=plan.records[need.need_id],
        claims_cap=3,
    )


def test_two_needs_get_different_decisions(tmp_path: Path, kb_index: KnowledgeIndex) -> None:
    supported = _run(tmp_path, kb_index, RuleBackend(), 0)
    gap = _run(tmp_path / "b", kb_index, RuleBackend(), 1)
    assert supported.decision == "RETRIEVE_EVIDENCE" and supported.claims
    assert supported.claims[0].evidence_ids == ["CAP-012"]
    assert gap.decision == "PROCEED_WITH_GAP" and not gap.claims and gap.gap


def test_ids_the_loop_never_received_are_dropped_and_a_claim_left_bare_goes(
    tmp_path: Path, kb_index: KnowledgeIndex
) -> None:
    claims = [
        {
            "kind": "capability",
            "text": "Signs forms.",
            "evidence_ids": ["CAP-012", "CAP-999"],
            "src_ids": ["SRC-0015", "SRC-0999"],
        },
        {
            "kind": "capability",
            "text": "Signs anything.",
            "evidence_ids": ["CAP-012"],
            "src_ids": ["SRC-0999"],
        },
    ]
    backend = ScriptBackend(
        [
            tools(("search_capabilities", {"query": "electronic signature"})),
            "Done.",
            text({"decision": "RETRIEVE_EVIDENCE", "reason": "CAP-012.", "claims": claims}),
        ]
    )
    outcome = _run(tmp_path, kb_index, backend)
    assert [c.text for c in outcome.claims] == ["Signs forms."]
    assert outcome.claims[0].evidence_ids == ["CAP-012"] and outcome.claims[0].src_ids == [
        "SRC-0015"
    ]
    assert any("CAP-999 was not returned" in note for note in outcome.notes)
    assert any("SRC-0999 is outside the need" in note for note in outcome.notes)
    assert any("claim 2 cites no passage" in note for note in outcome.notes)


def test_retrieve_evidence_with_no_claim_left_becomes_a_gap() -> None:
    need = _plan().needs[0]
    result = DecideResult(
        decision="RETRIEVE_EVIDENCE",
        reason="Some record.",
        claims=[ClaimProposal(text="Unproven.", evidence_ids=["CAP-012"], src_ids=["SRC-0015"])],
    )
    outcome, notes = check(need, result, evidence=[], passages=[], claims_cap=3)
    assert outcome.decision == "PROCEED_WITH_GAP" and outcome.gap
    assert "becomes PROCEED_WITH_GAP" in notes[-1]


def test_a_question_becomes_a_decide_question_numbered_after_the_briefs() -> None:
    plan = _plan()
    outcome = DecideOutcome(
        need_id="RG-002",
        origin="RFP",
        decision="REQUEST_CLARIFICATION",
        reason="Unclear.",
        question="Which version of the Quillbeck system is in use?",
    )
    brief = [ClarificationQuestion(id="CQ-004", text="Q", origin="brief")]
    joined = join([outcome], plan, last_question=question_number(brief))
    question = joined.questions[0]
    assert (question.id, question.origin, question.group_id) == ("CQ-005", "decide", "RG-002")
    assert question.src_ids == ["SRC-0020"]
    assert joined.decisions[0].question == question


def test_claim_numbers_do_not_depend_on_which_worker_finished_first(tmp_path: Path) -> None:
    plan = _plan()
    first = DecideOutcome(
        "RG-001",
        "RFP",
        "RETRIEVE_EVIDENCE",
        "r",
        [ClaimProposal(text="A.", evidence_ids=["CAP-012"], src_ids=["SRC-0015"])],
    )
    second = DecideOutcome(
        "RG-002",
        "RFP",
        "RETRIEVE_EVIDENCE",
        "r",
        [ClaimProposal(text="B.", evidence_ids=["CAP-006"], src_ids=["SRC-0020"])],
    )
    one = join([first, second], plan, last_question=0)
    other = join([second, first], plan, last_question=0)
    assert [(c.id, c.text) for c in one.claims] == [(c.id, c.text) for c in other.claims]
    assert [(c.id, c.need_id) for c in one.claims] == [("CL-001", "RG-001"), ("CL-002", "RG-002")]
    write_decisions(tmp_path, one)
    lines = (tmp_path / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["claim_ids"] for line in lines] == [["CL-001"], ["CL-002"]]


def test_past_the_need_cap_the_rest_are_overflow_and_degrade_the_run() -> None:
    domain = DomainBrief(
        mode="pack",
        needs=[DomainNeed(id="DN-001", need="Records retention", excerpt_ids=["PX-0001"])],
    )
    plan = plan_needs(GROUPS, [SIGNATURE, QUILLBECK], domain, cap=2)
    assert [n.need_id for n in plan.needs] == ["RG-001", "RG-002"]
    assert [n.need_id for n in plan.overflow] == ["DN-001"]
    assert plan.degraded() == "decide: 1 needs past the need cap"
    assert plan_needs(GROUPS, [SIGNATURE, QUILLBECK], domain, cap=24).degraded() is None


def test_a_group_with_no_binding_or_optional_member_is_no_need() -> None:
    background = requirement(
        3, "SRC-0021", "The College was founded in 1890.", disposition="BACKGROUND", mandatory=False
    )
    groups = [
        *GROUPS,
        RequirementGroup(id="RG-003", member_ids=["REQ-0003"], topic="History", llm=False),
    ]
    plan = plan_needs(groups, [SIGNATURE, QUILLBECK, background], None, cap=24)
    assert [n.need_id for n in plan.needs] == ["RG-001", "RG-002"]


def test_the_loop_stops_at_a_turn_with_nothing_new(
    tmp_path: Path, kb_index: KnowledgeIndex
) -> None:
    search = ("search_capabilities", {"query": "electronic signature"})
    backend = ScriptBackend(
        [
            tools(search),
            tools(search),
            text({"decision": "PROCEED_WITH_GAP", "reason": "r", "gap": "g"}),
        ]
    )
    outcome = _run(tmp_path, kb_index, backend)
    assert outcome.stop_reason == "no_progress" and outcome.turns == 2


def test_the_loop_stops_at_its_tool_cap(tmp_path: Path, kb_index: KnowledgeIndex) -> None:
    calls = [
        ("search_capabilities", {"query": word})
        for word in ("signature", "portal", "migration", "audit", "hosting", "training", "mapping")
    ]
    backend = ScriptBackend([tools(*calls), text({"decision": "ABSTAIN", "reason": "r"})])
    outcome = _run(tmp_path, kb_index, backend)
    assert outcome.stop_reason == "tool_cap" and outcome.tool_calls == 7


def test_decide_context_holds_no_other_need(tmp_path: Path, kb_index: KnowledgeIndex) -> None:
    backend = RuleBackend()
    _run(tmp_path, kb_index, backend, 0)
    sent = "\n".join(m.content for r in backend.requests for m in r.messages)
    assert "REQ-0001" in sent and "REQ-0002" not in sent and "Quillbeck" not in sent


def test_context_manifests_name_the_need(tmp_path: Path, kb_index: KnowledgeIndex) -> None:
    passages = dev_ingest().passages
    manifests = CallManifests(
        ContextManager(tmp_path, CONFIG.limits.context, passages),
        CONFIG.limits.context.budgets["decide"],
    )
    plan = _plan()
    need = plan.needs[0]
    decide_need(
        context(RuleBackend()),
        need,
        _gateway(tmp_path, kb_index),
        LIMITS,
        passages=plan.passages["RG-001"],
        records=plan.records["RG-001"],
        claims_cap=3,
        manifests=manifests,
    )
    names = sorted(path.name for path in (tmp_path / "context").glob("decide-*.json"))
    assert names == ["decide-RG-001-1.json", "decide-RG-001-2.json", "decide-RG-001-final.json"]


def test_the_fixed_mode_makes_one_call_with_the_retrieved_evidence(
    kb_index: KnowledgeIndex,
) -> None:
    plan = _plan()
    need = plan.needs[0]
    evidence = fixed_evidence(kb_index, need)
    assert evidence and evidence[0].id == "CAP-012"
    passages = need_passages(plan.passages["RG-001"], {p.id: p for p in dev_ingest().passages})
    backend = RuleBackend()
    outcome = decide_fixed(
        context(backend), need, evidence, passages, records=plan.records["RG-001"], claims_cap=3
    )
    assert len(backend.requests) == 1 and backend.requests[0].tools == ()
    assert '"evidence"' in backend.requests[0].messages[1].content
    assert outcome.decision == "RETRIEVE_EVIDENCE" and outcome.stop_reason == "fixed"


def test_ask_research_reads_the_loaded_pack_or_the_runs_own_research(tmp_path: Path) -> None:
    pack = load_pack(FIXTURE_PACK, PATTERNS)
    questions = CONFIG.research.questions
    loaded = ResearchRecord(mode="pack", pack_id="fixture", pack_sha256=pack.sha256)
    provider, note = research_provider(
        "pack",
        loaded,
        packs_dir=FIXTURE_PACK.parent,
        questions=questions,
        patterns=PATTERNS,
        run_dir=tmp_path,
    )
    assert provider is not None and note is None
    assert provider.ask("How long should records be kept by public bodies?").excerpts
    changed = loaded.model_copy(update={"pack_sha256": "sha256:" + "0" * 64})
    provider, note = research_provider(
        "pack",
        changed,
        packs_dir=FIXTURE_PACK.parent,
        questions=questions,
        patterns=PATTERNS,
        run_dir=tmp_path,
    )
    assert provider is None and note is not None and "changed since discover" in note
    live = ResearchRecord(
        mode="live", answers=pack.answers, excerpts=pack.excerpts, sources=pack.sources
    )
    provider, _ = research_provider(
        "live",
        live,
        packs_dir=FIXTURE_PACK.parent,
        questions=questions,
        patterns=PATTERNS,
        run_dir=tmp_path,
    )
    assert provider is not None
    assert provider.ask("How long should records be kept by public bodies?").excerpts
    assert research_provider(
        "off",
        live,
        packs_dir=FIXTURE_PACK.parent,
        questions=questions,
        patterns=PATTERNS,
        run_dir=tmp_path,
    ) == (None, None)


def test_g5_does_not_count_decides_questions(tmp_path: Path, kb_index: KnowledgeIndex) -> None:
    pack = load_pack(FIXTURE_PACK, PATTERNS)
    from bidwright.research.pack import PackProvider

    asked = ask_tool(PackProvider(pack, CONFIG.research.questions), max_excerpts=3)
    full = ResearchRecord(mode="pack", answers=[*pack.answers] * 3)  # past G5's 6 questions
    gateway = ToolGateway.for_agent(
        "decide",
        allowed=["ask_research"],
        tools=[asked],
        max_tool_calls=6,
        context=RuleContext(passages=dev_ingest().passages, research=lambda: full),
    )
    request = ToolRequest(
        tool="ask_research",
        args={"question": "How long should records be kept by public bodies?"},
        agent="decide",
        turn=1,
    )
    assert gateway.call(request).status == "OK"


def test_domain_needs_carry_their_text_and_excerpts() -> None:
    excerpt = ExcerptView(id="PX-0001", source_title="A guide", tier=2, text="Keep records.")
    domain = DomainBrief(
        mode="pack",
        needs=[DomainNeed(id="DN-001", need="Records retention", excerpt_ids=["PX-0001"])],
    )
    plan = plan_needs([], [], domain, cap=24, excerpts={"PX-0001": excerpt})
    need = plan.needs[0]
    assert (need.origin, need.text, need.excerpts) == ("DOMAIN", "Records retention", [excerpt])
    assert plan.passages["DN-001"] == []


def test_the_need_cap_and_claims_cap_come_from_config() -> None:
    assert CONFIG.limits.solution.need_cap == 24 and CONFIG.limits.solution.claims_per_need == 3
    assert isinstance(LIMITS, AgentLimits) and LIMITS.max_turns == 4
