"""D-05, the text view: `IdentityView` changes nothing, and a view that swaps a value is what
every packed view, every search result and every model request shows, so nothing reaches a
model around it.

The end-to-end tests run the development PDF through a scripted model that keeps every
request. They read the planted personal data from the `personal_data` lines of the
development gold and never write it here, so they carry the `gold` marker."""

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import pytest

from bidwright.config import load_config
from bidwright.graph.build import RunResult, execute
from bidwright.harness.context import ContextManager
from bidwright.harness.view import IdentityView, TextView
from bidwright.ingest import display_text
from bidwright.llm.replay import CassetteStore
from bidwright.retrieval import PassageIndex
from bidwright.schemas import DefinedTerm, LayerTokens, Passage
from bidwright.tools import SearchArgs, search_tool
from tests.node_fakes import DEV_RFP, dev_ingest
from tests.privacy_fakes import ScriptedModel, body, planted_values, stand_in

ORIGINAL, SWAPPED = "Kestrel", "Qwertyx"  # the same length, so offsets carry over


class SwapView:
    """A test view that replaces values with strings of the same length."""

    def __init__(self, passages: Iterable[Passage], swaps: Mapping[str, str]) -> None:
        self._identity = IdentityView(passages)
        self.swaps = dict(swaps)
        assert all(len(a) == len(b) for a, b in self.swaps.items())

    def bind(self, passages: Iterable[Passage]) -> None:
        self._identity.bind(passages)

    def text(self, passage: Passage) -> str:
        text = display_text(passage.text)
        for value, replacement in self.swaps.items():
            text = text.replace(value, replacement)
        return text

    def to_frozen(self, src_id: str, start: int, end: int) -> tuple[int, int]:
        return self._identity.to_frozen(src_id, start, end)


def test_identity_view_returns_text_and_spans_unchanged() -> None:
    result = dev_ingest()
    view = IdentityView(result.passages)
    for passage in result.passages:
        shown = view.text(passage)
        assert shown == display_text(passage.text) and len(shown) == len(passage.text)
        assert view.to_frozen(passage.id, 0, len(shown)) == (passage.start, passage.end)
        middle = (len(shown) // 3, len(shown) // 2)
        start, end = view.to_frozen(passage.id, *middle)
        assert result.frozen_text[start:end] == passage.text[middle[0] : middle[1]]


def test_pack_shows_the_swapped_text_everywhere(tmp_path: Path) -> None:
    passages = dev_ingest().passages
    assert any(ORIGINAL in p.text for p in passages)
    view = SwapView(passages, {ORIGINAL: SWAPPED})
    term = DefinedTerm(term="College", definition="unused", src_id="SRC-0006")
    manager = ContextManager(tmp_path, load_config().limits.context, passages)
    packs = manager.pack(
        "extract",
        passages,
        view=view,
        fixed_tokens=LayerTokens(rules=100),
        budget_tokens=2000,
        batch_size=10,
        neighbors=1,
        terms=[term],
    )
    shown = [
        text
        for pack in packs
        for text in [
            *(v.text for v in pack.passages),
            *(v.lead_in or "" for v in pack.passages),
            *(c.text for c in pack.context),
            *(t.definition for t in pack.terms),
        ]
    ]
    assert not any(ORIGINAL in text for text in shown)
    assert any(SWAPPED in text for text in shown)
    assert SWAPPED in packs[0].terms[0].definition, "a term's definition comes from the view"
    assert ORIGINAL in passages[0].text, "stored records keep the frozen text"


def test_search_rfp_returns_the_swapped_text(tmp_path: Path) -> None:
    passages = dev_ingest().passages
    view = SwapView(passages, {ORIGINAL: SWAPPED})
    index = PassageIndex.build(passages, tmp_path / "search.sqlite", view=view)
    tool = search_tool(index)
    found = tool.run(SearchArgs(query=SWAPPED, k=8))
    assert found.status == "OK" and found.data
    assert all(ORIGINAL not in hit["text"] for hit in found.data)
    assert any(SWAPPED in hit["text"] for hit in found.data)
    assert tool.run(SearchArgs(query=ORIGINAL)).status == "EMPTY"
    plain = PassageIndex.build(passages, tmp_path / "plain.sqlite")
    assert search_tool(plain).run(SearchArgs(query=ORIGINAL)).status == "OK"


# --- end to end (D-05) ------------------------------------------------------------------------


def _run(tmp_path: Path, view: TextView, markers: Sequence[str]) -> tuple[RunResult, ScriptedModel]:
    model = ScriptedModel(markers)
    result = execute(
        docling_mode="replay",
        source=DEV_RFP,
        profile="free",
        outputs=tmp_path / "out",
        mode="record",
        cassettes=CassetteStore(tmp_path / "cassettes"),
        backends={"gemini": model},
        run_id="view",
        view=view,
    )
    assert result.status == "COMPLETED", result.reason
    return result, model


def _bodies(model: ScriptedModel, schema: str | None) -> list[str]:
    return [body(r) for r in model.requests if r.schema_name == schema]


def _tool_results(result: RunResult) -> str:
    return (result.run_dir / "tool_calls.jsonl").read_text(encoding="utf-8")


@pytest.mark.gold
def test_no_planted_value_reaches_a_model_or_a_tool_result_through_a_swap_view(
    tmp_path: Path,
) -> None:
    planted = planted_values()
    swaps = {value: stand_in(value) for value in planted}
    result, model = _run(tmp_path, SwapView((), swaps), [*planted, *swaps.values()])
    every = [body(r) for r in model.requests]
    for schema in ("TriageResult", "ExtractResult", "ConsolidationResult"):
        assert _bodies(model, schema), f"the run made a {schema} request"
    assert any(r.tools for r in model.requests), "risk ran its tool loop"
    for value in planted:
        assert not any(value in text for text in every), "a request carried a planted value"
        assert value not in _tool_results(result), "a tool result carried a planted value"
    for schema in ("ExtractResult", "ConsolidationResult"):
        texts = _bodies(model, schema)
        assert all(any(s in t for t in texts) for s in swaps.values()), f"{schema} shows the view"
    assert any(stand in _tool_results(result) for stand in swaps.values())
    frozen = display_text((result.run_dir / "frozen.txt").read_text(encoding="utf-8"))
    assert all(value in frozen for value in planted), "the frozen text keeps the values"


@pytest.mark.gold
def test_the_identity_view_lets_the_same_values_through(tmp_path: Path) -> None:
    """The control: with `IdentityView` the same requests carry the values, so the test
    above can fail."""
    planted = planted_values()
    result, model = _run(tmp_path, IdentityView(), planted)
    for schema in ("ExtractResult", "ConsolidationResult"):
        texts = _bodies(model, schema)
        assert all(any(value in text for text in texts) for value in planted), schema
    assert any(value in _tool_results(result) for value in planted)
