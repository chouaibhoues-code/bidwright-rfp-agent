"""Quote verification: is each quote really in the passage it cites?

A quote is checked against its cited passages, in order, in the form the model saw
(`display_text`: line breaks as spaces, same offsets as the frozen text).
- `VERBATIM_VERIFIED`: the quote occurs exactly.
- `NORMALIZED_MATCH`: it occurs once both sides are normalized for whitespace, ligatures,
  hyphenation at line ends and quote style. Accepted, and counted apart.
- `REJECTED`: anything else, including a quote shorter than three words, which would match
  almost anywhere.
The app, never the model, sets the status and the span in the frozen text.
"""

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from bidwright.ingest import display_text
from bidwright.schemas import Passage, QuoteStatus

MIN_QUOTE_WORDS = 3
_QUOTE_STYLE = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "′": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "″": '"',
    }
)


@dataclass(frozen=True)
class QuoteCheck:
    status: QuoteStatus
    src_id: str | None = None
    span: tuple[int, int] | None = None
    reason: str | None = None


def normalize(text: str) -> tuple[str, list[int]]:
    """The normalized text, and for each of its characters the index it came from."""
    chars: list[tuple[str, int]] = []
    for index, char in enumerate(text):
        for piece in unicodedata.normalize("NFKC", char.translate(_QUOTE_STYLE)):
            chars.append((piece, index))
    spaced: list[tuple[str, int]] = []
    for char, index in chars:
        if char.isspace():
            if spaced and spaced[-1][0] != " ":
                spaced.append((" ", index))
        else:
            spaced.append((char, index))
    joined: list[tuple[str, int]] = []
    position = 0
    while position < len(spaced):
        char, index = spaced[position]
        if char == "-" and joined and joined[-1][0].isalpha():
            after = position + 1
            if after < len(spaced) and spaced[after][0] == " ":
                after += 1
            if after < len(spaced) and spaced[after][0].isalpha():
                position = after  # "signa- ture" and "on-premises" both lose the hyphen
                continue
        joined.append((char, index))
        position += 1
    while joined and joined[-1][0] == " ":
        joined.pop()
    return "".join(c for c, _ in joined), [i for _, i in joined]


def check_quote(quote: str, cited: Sequence[Passage]) -> QuoteCheck:
    if len(quote.split()) < MIN_QUOTE_WORDS:
        return QuoteCheck("REJECTED", reason=f"a quote needs at least {MIN_QUOTE_WORDS} words")
    for passage in cited:
        shown = display_text(passage.text)
        found = shown.find(quote)
        if found >= 0:
            span = (passage.start + found, passage.start + found + len(quote))
            return QuoteCheck("VERBATIM_VERIFIED", passage.id, span)
    wanted, _ = normalize(quote)
    for passage in cited:
        text, origin = normalize(display_text(passage.text))
        found = text.find(wanted)
        if found >= 0 and wanted:
            start = passage.start + origin[found]
            end = passage.start + origin[found + len(wanted) - 1] + 1
            return QuoteCheck("NORMALIZED_MATCH", passage.id, (start, end))
    return QuoteCheck("REJECTED", reason="not found in the cited passages")
