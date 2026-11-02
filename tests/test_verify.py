"""S-07: quote verification under PDF noise. Every real quote is accepted, and none are invented."""

import pytest

from bidwright.schemas import Passage
from bidwright.verify import check_quote, normalize

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
