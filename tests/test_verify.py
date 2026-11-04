"""S-07: quote verification under PDF noise. Every real quote is accepted, and none are invented."""

from datetime import date
from decimal import Decimal

import pytest

from bidwright.harness.view import IdentityView
from bidwright.schemas import Passage
from bidwright.verify import check_quote, missing_values, normalize, values
from tests.test_text_view import SwapView

FROZEN = (
    "The Supplier shall store signed documents for ten  (10) years.\n\n"
    "The ﬁrm shall keep signa-\nture logs for every College’s form.\n\n"
    "Bidders may propose an on-\npremises option.\n\n"
    "The Supplier shall keep an audit record of every signature event, including\n"
    "the signer's identity."
)


def _passages() -> list[Passage]:
    out = []
    start = 0
    for number, text in enumerate(FROZEN.split("\n\n"), start=1):
        start = FROZEN.index(text, start)
        out.append(
            Passage(
                id=f"SRC-{number:04d}",
                doc_id="d",
                section_path="",
                kind="sentence",
                text=text,
                start=start,
                end=start + len(text),
            )
        )
        start += len(text)
    return out


P = _passages()


@pytest.mark.parametrize(
    ("quote", "cited", "status"),
    [
        # Real quotes: accepted as verbatim or normalized.
        (
            "The Supplier shall keep an audit record of every signature event, including"
            " the signer's identity.",
            [3],
            "VERBATIM_VERIFIED",
        ),
        ("store signed documents for ten  (10) years", [0], "VERBATIM_VERIFIED"),
        ("store signed documents for ten (10) years", [0], "NORMALIZED_MATCH"),
        ("The firm shall keep signa- ture logs", [1], "NORMALIZED_MATCH"),
        ("The firm shall keep signature logs", [1], "NORMALIZED_MATCH"),
        ("logs for every College's form.", [1], "NORMALIZED_MATCH"),
        ("Bidders may propose an on-premises option.", [2], "NORMALIZED_MATCH"),
        ("Bidders may propose an on- premises option.", [2], "VERBATIM_VERIFIED"),
        ("store signed documents for ten  (10) years", [2, 0], "VERBATIM_VERIFIED"),
        # Not in the source: rejected.
        ("store signed documents for twelve (12) years", [0], "REJECTED"),
        ("The Supplier keeps signed documents for a decade.", [0], "REJECTED"),
        ("the supplier shall store signed documents", [0], "REJECTED"),
        ("ten (10) years. The firm shall keep", [0, 1], "REJECTED"),
        ("Bidders may propose an on-premises option.", [0], "REJECTED"),
        ("shall store", [0], "REJECTED"),
        ("", [0], "REJECTED"),
    ],
)
def test_s07_quote_cases(quote: str, cited: list[int], status: str) -> None:
    check = check_quote(quote, [P[i] for i in cited])
    assert check.status == status, check.reason
    if status != "REJECTED":
        assert check.span is not None and check.src_id is not None
        start, end = check.span
        assert normalize(FROZEN[start:end].replace("\n", " "))[0] == normalize(quote)[0]


def test_normalize_keeps_an_index_map_to_the_original() -> None:
    text, origin = normalize("aﬁ  b’s")
    assert text == "afi b's"
    assert origin == [0, 1, 1, 2, 4, 5, 6]


# --- Number and date fidelity (Iteration 1, step 11) --------------------------------------


def test_values_read_dates_times_and_numbers() -> None:
    assert values("Bids close at 12:00 UTC on 2027-01-15.") == [date(2027, 1, 15), "12:00 UTC"]
    assert values("Keep records for seven (7) years.") == [Decimal(7)], "one value, not two"
    assert values("15 January 2027, or January 15, 2027") == [date(2027, 1, 15)]
    assert values("£4,000,000 a year, 99.9% or 99.9 percent") == [
        Decimal(4_000_000),
        Decimal("99.9"),
    ]
    assert values("REQ-0001 quotes SRC-0042 and HZ-003.") == [], "ids are not values"
    assert values("Use PDF 1.7.2 or later.") == [], "a version string is not a number"


@pytest.mark.parametrize(
    ("statement", "sources", "missing"),
    [
        ("Keep records for 7 years.", ["Keep records for seven (7) years."], []),
        ("Keep records for ten years.", ["Keep records for 10 years."], []),
        ("Keep records for twelve years.", ["Keep records for ten (10) years."], [Decimal(12)]),
        (
            "The Supplier sends a reminder within 48 hours.",
            ["send a reminder;", "Within 48 hours of each request, the Supplier shall:"],
            [],
        ),
        (
            "Comply with section 4.2.",
            ["Comply with the rules.", "4 Requirements > 4.2 Signing"],
            [],
        ),
        ("Bids close on 2027-01-15.", ["Bids close on 15 January 2027."], []),
        ("Bids close on January 15, 2027.", ["Bids close on 2027-01-15."], []),
        ("Bids close on 2027-01-16.", ["Bids close on 15 January 2027."], [date(2027, 1, 16)]),
        ("Bids close at 12:00.", ["Bids close at 12:00 UTC."], []),
        ("Bids close at 12:00 CET.", ["Bids close at 12:00 UTC."], ["12:00 CET"]),
    ],
)
def test_every_value_of_a_statement_needs_a_source(
    statement: str, sources: list[str], missing: list[object]
) -> None:
    """A correct number, a changed one, spelled and digit forms, a value from the lead-in, a
    section number from the section path, and dates in three forms."""
    assert missing_values(statement, sources) == missing


def test_a_quote_is_found_in_the_view_and_mapped_to_the_frozen_text() -> None:
    passages = _passages()
    identity = IdentityView(passages)
    quote = "keep an audit record of every signature event"
    assert check_quote(quote, [passages[3]], identity) == check_quote(quote, [passages[3]])
    swapped = SwapView(passages, {"audit": "check"})
    check = check_quote("keep an check record", [passages[3]], swapped)
    assert check.status == "VERBATIM_VERIFIED" and check.span is not None
    assert FROZEN[check.span[0] : check.span[1]] == "keep an audit record"
