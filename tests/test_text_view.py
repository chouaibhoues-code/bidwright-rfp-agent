"""D-05, the text view: `IdentityView` changes nothing, and a view that swaps a value is what
every packed view and every search result shows, so nothing reaches a model around it. The
end-to-end test joins this file in step 16, once every node uses packs."""

from collections.abc import Iterable, Mapping
from pathlib import Path

from bidwright.config import load_config
from bidwright.harness.context import ContextManager
from bidwright.harness.view import IdentityView
from bidwright.ingest import display_text
from bidwright.retrieval import PassageIndex
from bidwright.schemas import DefinedTerm, LayerTokens, Passage
from bidwright.tools import SearchArgs, search_tool
from tests.node_fakes import dev_ingest

ORIGINAL, SWAPPED = "Kestrel", "Qwertyx"  # the same length, so offsets carry over


class SwapView:
    """A test view that replaces values with strings of the same length."""

    def __init__(self, passages: Iterable[Passage], swaps: Mapping[str, str]) -> None:
        self._identity = IdentityView(passages)
        self.swaps = dict(swaps)
        assert all(len(a) == len(b) for a, b in self.swaps.items())

    def text(self, passage: Passage) -> str:
        text = display_text(passage.text)
        for value, stand_in in self.swaps.items():
            text = text.replace(value, stand_in)
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
