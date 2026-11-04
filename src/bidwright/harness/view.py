"""The text view (ADR-026, D-05): the one seam between the frozen text and what a model reads.

Every model-facing view and every tool result is built from `TextView.text`: the passage views
of a context pack and their lead-ins, its neighbors and term definitions, the section views of
`triage`, the cluster tasks of `consolidate`, and the `search_rfp` index. Stored records keep
the frozen text. `to_frozen` maps a span of a passage's view text back to `frozen.txt`, so a
quote the model copied from the view still gets its frozen offsets.

`IdentityView`, the default, shows each passage's display text: the frozen text with line
breaks as spaces, the form a model has seen since `v0.0`. It has the same length, so a span maps
back by the passage's start offset alone and runs behave as before. Iteration 5's masking is a
drop-in replacement for it.
"""

from collections.abc import Iterable
from typing import Protocol

from bidwright.ingest import display_text
from bidwright.schemas import Passage


class TextView(Protocol):
    def bind(self, passages: Iterable[Passage]) -> None:
        """Learn the run's passages, once `ingest` has made them, for `to_frozen`."""
        ...

    def text(self, passage: Passage) -> str:
        """The text a model sees for this passage."""
        ...

    def to_frozen(self, src_id: str, start: int, end: int) -> tuple[int, int]:
        """The `frozen.txt` span of a half-open span of this passage's view text."""
        ...


class IdentityView:
    """The frozen text as a model has always seen it: line breaks as spaces, offsets kept."""

    def __init__(self, passages: Iterable[Passage] = ()) -> None:
        self._starts: dict[str, int] = {}
        self.bind(passages)

    def bind(self, passages: Iterable[Passage]) -> None:
        self._starts.update({passage.id: passage.start for passage in passages})

    def text(self, passage: Passage) -> str:
        return display_text(passage.text)

    def to_frozen(self, src_id: str, start: int, end: int) -> tuple[int, int]:
        try:
            offset = self._starts[src_id]
        except KeyError as exc:
            raise KeyError(f"the view holds no passage {src_id}") from exc
        return offset + start, offset + end


__all__ = ["IdentityView", "TextView"]
