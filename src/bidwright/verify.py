"""Quote verification: is each quote really in the passage it cites?

A quote is checked against its cited passages, in order, in the form the model saw.
- `VERBATIM_VERIFIED`: the quote occurs exactly.
- `NORMALIZED_MATCH`: it occurs once both sides are normalized for whitespace, ligatures,
  hyphenation at line ends and quote style. Accepted, and counted apart.
- `REJECTED`: anything else, including a quote shorter than three words, which would match
  almost anywhere.
The app, never the model, sets the status and the span in the frozen text. The text checked is
the run's text view, and `TextView.to_frozen` maps the span back (D-05); with no view it is the
display text (line breaks as spaces, same offsets as the frozen text), as before.

Number and date fidelity (Iteration 1, step 11): every value a statement states must occur in
its quote, a cited passage, that passage's lead-in or table header, or its section path, so
"section 4.2" needs no source. `values` reads dates (`YYYY-MM-DD`, `D Month YYYY`,
`Month D, YYYY`), times (`HH:MM` with an optional zone word, compared as text), and numbers as
`Decimal`, whatever their unit: amounts, percentages, digits with thousands separators and a
decimal part, and the spelled numbers zero to twenty, thirty to ninety by tens, hundred,
thousand and million. "seven (7)" is one value. Ids such as `REQ-0001` and `SRC-0001` are not
values, and the digits of a date or a time belong to that date or time only.
"""

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from bidwright.ingest import display_text
from bidwright.schemas import Passage, QuoteStatus

if TYPE_CHECKING:
    from bidwright.harness.view import TextView

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
    failure: str | None = None  # "quote", "number" or "long": what a repair must fix
    repaired: bool = False  # passed only after its repair
    second_pass: bool = False  # added by the second extraction pass (S-13)


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


def shown_text(passage: Passage, view: "TextView | None" = None) -> str:
    """The passage as a model saw it: through the view, or as display text."""
    return view.text(passage) if view is not None else display_text(passage.text)


def _frozen(passage: Passage, view: "TextView | None", start: int, end: int) -> tuple[int, int]:
    if view is None:
        return passage.start + start, passage.start + end
    return view.to_frozen(passage.id, start, end)


def check_quote(quote: str, cited: Sequence[Passage], view: "TextView | None" = None) -> QuoteCheck:
    """Find the quote in the cited passages, exactly first and then normalized."""
    if len(quote.split()) < MIN_QUOTE_WORDS:
        return QuoteCheck(
            "REJECTED", reason=f"a quote needs at least {MIN_QUOTE_WORDS} words", failure="quote"
        )
    for passage in cited:
        found = shown_text(passage, view).find(quote)
        if found >= 0:
            span = _frozen(passage, view, found, found + len(quote))
            return QuoteCheck("VERBATIM_VERIFIED", passage.id, span)
    wanted, _ = normalize(quote)
    for passage in cited:
        text, origin = normalize(shown_text(passage, view))
        found = text.find(wanted)
        if found >= 0 and wanted:
            span = _frozen(passage, view, origin[found], origin[found + len(wanted) - 1] + 1)
            return QuoteCheck("NORMALIZED_MATCH", passage.id, span)
    return QuoteCheck("REJECTED", reason="not found in the cited passages", failure="quote")


# --- Number and date fidelity -------------------------------------------------------------

MONTHS: tuple[str, ...] = tuple(
    "january february march april may june july august september october november december".split()
)
_MONTH = "(" + "|".join(month.capitalize() for month in MONTHS) + ")"
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DAY_MONTH = re.compile(r"\b(\d{1,2}) " + _MONTH + r" (\d{4})\b")
_MONTH_DAY = re.compile(r"\b" + _MONTH + r" (\d{1,2}),? (\d{4})\b")
_TIME = re.compile(r"\b(\d{1,2}):(\d{2})\b(?:\s?(UTC|GMT|CET|CEST|BST|[A-Z]{2,4})\b)?")
_ID = re.compile(r"\b[A-Z]{2,}-\d+\b")
# Digits with optional thousands separators and decimals, standing alone: never inside a word,
# an id or a version string such as 1.2.3.
_NUMBER = re.compile(
    r"(?<![\w.,])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?!\w|\.\d)"
    r"|(?<![\w.,])\d+(?:\.\d+)?(?!\w|\.\d)"
)
_TENS = ("thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
SPELLED: dict[str, Decimal] = {
    **{
        word: Decimal(number)
        for number, word in enumerate(
            "zero one two three four five six seven eight nine ten eleven twelve thirteen"
            " fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()
        )
    },
    **{word: Decimal(30 + 10 * n) for n, word in enumerate(_TENS)},
    "hundred": Decimal(100),
    "thousand": Decimal(1000),
    "million": Decimal(1_000_000),
}
_SPELLED = re.compile(
    r"\b(" + "|".join(sorted(SPELLED, key=len, reverse=True)) + r")\b(?:\s*\((\d+)\))?",
    re.IGNORECASE,
)

Value = date | Decimal | str  # a date, a number, or a time as text, such as "12:00 UTC"


def _mask(text: str, spans: Iterable[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    return "".join(chars)


def _date(year: str, month: int, day: str) -> date | str:
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return f"{year}-{month:02d}-{day}"  # an impossible date still has to match as written


def values(text: str) -> list[Value]:
    """The dates, times and numbers a text states, each once, in the order found."""
    found: list[Value] = []
    taken: list[tuple[int, int]] = [m.span() for m in _ID.finditer(text)]
    for match in _ISO_DATE.finditer(text):
        found.append(_date(match.group(1), int(match.group(2)), match.group(3)))
        taken.append(match.span())
    for match in _DAY_MONTH.finditer(text):
        month = MONTHS.index(match.group(2).lower()) + 1
        found.append(_date(match.group(3), month, match.group(1)))
        taken.append(match.span())
    for match in _MONTH_DAY.finditer(text):
        month = MONTHS.index(match.group(1).lower()) + 1
        found.append(_date(match.group(3), month, match.group(2)))
        taken.append(match.span())
    rest = _mask(text, taken)
    times = list(_TIME.finditer(rest))
    for match in times:
        zone = f" {match.group(3)}" if match.group(3) else ""
        found.append(f"{int(match.group(1)):02d}:{match.group(2)}{zone}")
    rest = _mask(rest, [m.span() for m in times])
    spelled = list(_SPELLED.finditer(rest))
    for match in spelled:
        found.append(SPELLED[match.group(1).lower()])
    rest = _mask(rest, [m.span() for m in spelled])
    for match in _NUMBER.finditer(rest):
        try:
            found.append(Decimal(match.group(0).replace(",", "")))
        except InvalidOperation:
            continue
    return list(dict.fromkeys(found))


def dates(text: str) -> list[tuple[tuple[int, int], date | str]]:
    """Each calendar date the text states, with its span, as `values` reads them: an
    impossible date stays text (Iteration 3, step 7, for `blueprint`'s "[removed]")."""
    found: list[tuple[tuple[int, int], date | str]] = []
    for match in _ISO_DATE.finditer(text):
        found.append((match.span(), _date(match.group(1), int(match.group(2)), match.group(3))))
    for match in _DAY_MONTH.finditer(text):
        month = MONTHS.index(match.group(2).lower()) + 1
        found.append((match.span(), _date(match.group(3), month, match.group(1))))
    for match in _MONTH_DAY.finditer(text):
        month = MONTHS.index(match.group(1).lower()) + 1
        found.append((match.span(), _date(match.group(3), month, match.group(2))))
    return found


def _same(wanted: Value, offered: Value) -> bool:
    if isinstance(wanted, str) and isinstance(offered, str):
        # A time with no zone word matches the same time with any zone word.
        return offered == wanted or (" " not in wanted and offered.split(" ")[0] == wanted)
    return type(wanted) is type(offered) and wanted == offered


def missing_values(statement: str, sources: Iterable[str]) -> list[Value]:
    """The values the statement states that no source text states."""
    offered = [value for text in sources for value in values(text)]
    return [v for v in values(statement) if not any(_same(v, o) for o in offered)]
