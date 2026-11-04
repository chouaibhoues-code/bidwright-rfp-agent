"""`ContextManager`: packs keep every passage once and in order, stay within their budget
unless a passage is too large to share one, keep neighbors out of their members, carry the
first terms by occurrence, and write one manifest per call."""

from collections.abc import Sequence
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bidwright.config import ContextLimits, load_config
from bidwright.harness.context import (
    ContextManager,
    ContextOverflow,
    estimate_tokens,
    prompt_tokens,
)
from bidwright.ingest import display_text
from bidwright.prompts import load_prompt
from bidwright.schemas import (
    ClusterMember,
    ClusterTask,
    ContextManifest,
    ContextPack,
    DefinedTerm,
    LayerTokens,
    Passage,
    SectionView,
)
from tests.node_fakes import dev_ingest

FIXED = LayerTokens(rules=50, examples=20, task=10)
FILLER = ["the", "supplier", "shall", "keep", "records", "notice", "within", "days", "service"]
TERMS = ["Alder", "Birch", "Cedar", "Dogwood", "Elm", "Hazel", "Juniper", "Larch", "Maple"]


def _limits(max_terms: int = 10) -> ContextLimits:
    return ContextLimits(
        budgets={"extract": 12000, "triage": 8000, "consolidate": 8000},
        chars_per_token=4,
        neighbors=1,
        max_terms=max_terms,
    )


def _passage(number: int, text: str, start: int, doc: str = "doc", section: str = "1 A") -> Passage:
    return Passage(
        id=f"SRC-{number:04d}",
        doc_id=doc,
        section_path=section,
        kind="sentence",
        text=text,
        start=start,
        end=start + len(text),
    )


def _total(pack: ContextPack) -> int:
    layers = pack.manifest.tokens_by_layer
    return layers.rules + layers.examples + layers.evidence + layers.task


@st.composite
def runs(draw: st.DrawFn) -> dict:
    count = draw(st.integers(min_value=1, max_value=40))
    documents = draw(st.integers(min_value=1, max_value=3))
    passages, start = [], 0
    for index in range(count):
        tokens = draw(st.lists(st.sampled_from(FILLER + TERMS), min_size=1, max_size=25))
        if draw(st.integers(min_value=0, max_value=9)) == 0:
            tokens += ["padding"] * draw(st.integers(min_value=200, max_value=900))
        text = " ".join(tokens)
        doc = f"doc-{index * documents // count}"
        passages.append(_passage(index + 1, text, start, doc, f"{index // 7} S"))
        start += len(text) + 1
    packed = draw(
        st.one_of(
            st.just(passages),
            st.lists(st.sampled_from(passages), unique_by=lambda p: p.id).map(
                lambda chosen: sorted(chosen, key=lambda p: p.id)
            ),
        )
    )
    registry = draw(st.lists(st.sampled_from(TERMS), unique=True))
    terms = [
        DefinedTerm(term=t, definition=f"{t} means a tree.", src_id="SRC-9999") for t in registry
    ]
    return {
        "passages": passages,
        "packed": packed,
        "terms": terms,
        "batch_size": draw(st.integers(min_value=1, max_value=25)),
        "budget": draw(st.integers(min_value=150, max_value=3000)),
        "neighbors": draw(st.integers(min_value=0, max_value=2)),
        "max_terms": draw(st.integers(min_value=0, max_value=6)),
    }


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("context")


def _first_terms(members: list[Passage], registry: list[DefinedTerm], limit: int) -> list[str]:
    """The oracle: walk the members' words in order and keep each registry term once."""
    names = {term.term for term in registry}
    found: list[str] = []
    for passage in members:
        for word in passage.text.split():
            if word in names and word not in found:
                found.append(word)
    return found[:limit]


@settings(deadline=None, max_examples=80)
@given(runs())
def test_packs_keep_every_passage_once_within_budget(run_dir: Path, run: dict) -> None:
    manager = ContextManager(run_dir, _limits(run["max_terms"]), run["passages"])
    packs = manager.pack(
        "extract",
        run["packed"],
        fixed_tokens=FIXED,
        budget_tokens=run["budget"],
        batch_size=run["batch_size"],
        neighbors=run["neighbors"],
        terms=run["terms"],
    )
    by_id = {p.id: p for p in run["passages"]}
    included = [src for pack in packs for src in pack.manifest.included_src_ids]
    assert included == [p.id for p in run["packed"]], "the union is the input, once, in order"
    assert [pack.call_id for pack in packs] == [f"B{n:02d}" for n in range(1, len(packs) + 1)]
    for pack in packs:
        members = pack.manifest.included_src_ids
        assert [view.src_id for view in pack.passages] == members
        assert len(members) <= run["batch_size"]
        if len(members) > 1:
            assert _total(pack) <= run["budget"], "only a lone passage may pass the budget"
        context = pack.manifest.context_src_ids
        assert not set(context) & set(members), "a neighbor is never a member"
        assert [view.src_id for view in pack.context] == context
        for src in context:
            near = [
                m
                for m in members
                if by_id[m].doc_id == by_id[src].doc_id
                and abs(int(m[4:]) - int(src[4:])) <= run["neighbors"]
            ]
            assert near, f"{src} is no member's neighbor"
        expected = _first_terms([by_id[m] for m in members], run["terms"], run["max_terms"])
        assert pack.manifest.terms == expected == [t.term for t in pack.terms]
        assert pack.manifest.dropped_src_ids == []


def test_a_passage_larger_than_the_budget_goes_alone(tmp_path: Path) -> None:
    small, large = "the supplier shall keep records", "padding " * 2000
    passages = [
        _passage(1, small, 0),
        _passage(2, large, 40),
        _passage(3, small, 20000),
    ]
    manager = ContextManager(tmp_path, _limits(), passages)
    packs = manager.pack(
        "extract", passages, fixed_tokens=FIXED, budget_tokens=1000, batch_size=20, neighbors=0
    )
    assert [p.manifest.included_src_ids for p in packs] == [
        ["SRC-0001"],
        ["SRC-0002"],
        ["SRC-0003"],
    ]
    assert _total(packs[1]) > 1000 and packs[1].manifest.utilization > 1
    assert packs[1].passages[0].text == display_text(large), "no passage is cut"


def test_ex0_packs_every_passage_into_one_pack_with_no_budget(tmp_path: Path) -> None:
    passages = dev_ingest().passages
    manager = ContextManager(tmp_path, _limits(), passages)
    [pack] = manager.pack(
        "extract", passages, fixed_tokens=FIXED, budget_tokens=500, batch_size=None, neighbors=1
    )
    assert pack.manifest.included_src_ids == [p.id for p in passages]
    assert pack.context == [] and pack.manifest.utilization > 1


def test_each_call_writes_its_manifest_and_numbering_continues(tmp_path: Path) -> None:
    passages = dev_ingest().passages
    manager = ContextManager(tmp_path, _limits(), passages)
    first = manager.pack(
        "extract",
        passages[:30],
        fixed_tokens=FIXED,
        budget_tokens=12000,
        batch_size=10,
        neighbors=1,
    )
    gaps = manager.pack(
        "extract",
        passages[30:],
        fixed_tokens=FIXED,
        budget_tokens=12000,
        batch_size=5,
        neighbors=1,
        first=len(first) + 1,
    )
    assert [p.call_id for p in first + gaps] == ["B01", "B02", "B03", "B04", "B05"]
    for pack in first + gaps:
        path = tmp_path / "context" / f"extract-{pack.call_id}.json"
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1 and ContextManifest.model_validate_json(lines[0]) == pack.manifest
    assert first[0].manifest.context_src_ids == ["SRC-0011"]
    assert gaps[0].manifest.context_src_ids == ["SRC-0030", "SRC-0036"], "outside the packed set"
    budget = first[0].manifest.budget_tokens
    assert first[0].manifest.utilization == round(_total(first[0]) / budget, 4)


def test_views_carry_lead_ins_and_term_definitions(tmp_path: Path) -> None:
    passages = dev_ingest().passages
    listed = next(p for p in passages if p.lead_in_id)
    college = DefinedTerm(term="College", definition="unused", src_id="SRC-0006")
    manager = ContextManager(tmp_path, _limits(), passages)
    packs = manager.pack(
        "extract",
        passages,
        fixed_tokens=FIXED,
        budget_tokens=12000,
        batch_size=20,
        neighbors=1,
        terms=[college],
    )
    by_id = {p.id: p for p in passages}
    views = {view.src_id: view for pack in packs for view in pack.passages}
    assert views[listed.id].lead_in == display_text(by_id[listed.lead_in_id or ""].text)
    [term] = packs[0].terms
    assert term.definition == display_text(by_id["SRC-0006"].text)[: len(term.definition)]
    assert term.definition.startswith("Kestrel Vale Community College (the College)")


def _sections(passages: Sequence[Passage]) -> list[SectionView]:
    order: dict[tuple[str, str], list[Passage]] = {}
    for passage in passages:
        order.setdefault((passage.doc_id, passage.section_path), []).append(passage)
    return [
        SectionView(
            section_path=section,
            doc_id=doc,
            role="main",
            first_text=" ".join(p.text for p in members[:2])[:400],
            passages=len(members),
        )
        for (doc, section), members in order.items()
    ]


def test_triage_packs_whole_sections_with_every_passage(tmp_path: Path) -> None:
    passages = dev_ingest().passages
    sections = _sections(passages)
    manager = ContextManager(tmp_path, _limits(), passages)
    packs = manager.pack_sections(sections, fixed_tokens=FIXED, budget_tokens=400)
    assert len(packs) > 1
    assert [p.call_id for p in packs] == [f"T{n:02d}" for n in range(1, len(packs) + 1)]
    regrouped = [s for pack in packs for s in manager.sections_in(pack, sections)]
    assert regrouped == sections
    assert [s for pack in packs for s in pack.manifest.included_src_ids] == [p.id for p in passages]
    for pack in packs:
        assert pack.passages == [] and pack.context == [] and pack.terms == []
        if len(manager.sections_in(pack, sections)) > 1:
            assert _total(pack) <= 400
        assert (tmp_path / "context" / f"triage-{pack.call_id}.json").exists()


def _member(requirement_id: str) -> ClusterMember:
    return ClusterMember(
        id=requirement_id,
        statement="Keep records.",
        modality="shall",
        disposition="BINDING",
        quote="The Supplier shall keep records.",
        doc_id="doc",
        section_path="4 Requirements",
    )


def test_a_cluster_call_is_named_by_its_group_and_lists_its_passages(tmp_path: Path) -> None:
    passages = dev_ingest().passages
    sources = {
        "REQ-0001": ["SRC-0020"],
        "REQ-0002": ["SRC-0021", "SRC-0022"],
        "REQ-0003": ["SRC-0022", "SRC-0030"],
    }
    manager = ContextManager(tmp_path, _limits(), passages, requirement_sources=sources)
    task = ClusterTask(
        cluster_id="RG-004",
        members=[_member("REQ-0001"), _member("REQ-0002")],
        context=[_member("REQ-0003")],
    )
    pack = manager.pack_cluster(task, fixed_tokens=FIXED, budget_tokens=8000)
    assert pack.call_id == "RG-004" and pack.manifest.node == "consolidate"
    assert pack.manifest.included_src_ids == ["SRC-0020", "SRC-0021", "SRC-0022"]
    assert pack.manifest.context_src_ids == ["SRC-0030"]
    written = tmp_path / "context" / "consolidate-RG-004.json"
    assert ContextManifest.model_validate_json(written.read_text(encoding="utf-8")) == pack.manifest
    with pytest.raises(ContextOverflow, match="RG-004"):
        manager.pack_cluster(task, fixed_tokens=FIXED, budget_tokens=100)
    with pytest.raises(ValueError, match="REQ-0009"):
        manager.pack_cluster(
            task.model_copy(update={"members": [_member("REQ-0009")]}),
            fixed_tokens=FIXED,
            budget_tokens=8000,
        )


def test_the_prompt_layers_are_rules_examples_and_task() -> None:
    prompt = load_prompt("extract")
    assert prompt.examples and prompt.examples in prompt.system
    layers = prompt_tokens(prompt, 4)
    assert layers.rules == estimate_tokens(len(prompt.system) - len(prompt.examples), 4)
    assert layers.examples == estimate_tokens(len(prompt.examples), 4)
    assert layers.task == estimate_tokens(len(prompt.tasks["task"].template), 4)
    assert layers.evidence == 0
    budgets = load_config().limits.context.budgets
    assert layers.rules + layers.examples + layers.task < budgets["extract"]
    with pytest.raises(KeyError, match="no_such_task"):
        prompt_tokens(prompt, 4, task="no_such_task")


def test_bad_inputs_are_refused(tmp_path: Path) -> None:
    passages = dev_ingest().passages[:3]
    manager = ContextManager(tmp_path, _limits(), passages)
    common = {"fixed_tokens": FIXED, "budget_tokens": 1000, "batch_size": 5, "neighbors": 1}
    with pytest.raises(ValueError, match="no call ids"):
        manager.pack("draft", passages, **common)
    with pytest.raises(ValueError, match="twice"):
        manager.pack("extract", [passages[0], passages[0]], **common)
    stranger = _passage(99, "not in this run", 0)
    with pytest.raises(ValueError, match="not in this run"):
        manager.pack("extract", [stranger], **common)
