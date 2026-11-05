"""Word-level text helpers shared by the nodes and the gateway's rules (Iteration 2).

`content_stems` and `STOPWORDS` come from `graph/nodes.py` unchanged, which re-exports them:
the `risk` loop's generic-risk check and the cluster rule use them. `normalized_words` is the
gateway's normalization (ADR-032): the text as `verify.normalize` gives it, so ligatures, quote
styles, whitespace and line-end hyphens do not matter, then casefolded with `str.casefold` and
split on every character that is not a letter or a digit. The outbound rule G3, the brief's
topic rule, the overlap check on queries and ADR-034's matching all use it. `shared_run` is
the length of the longest run of words two such word lists share, which G3 and the query
audit report.
"""

import re
from collections.abc import Sequence

from bidwright.verify import normalize

STOPWORDS = frozenset(
    """that this with from have will shall must should which their there these those would
    could about into than then them they been being were what when where also each only other
    such some more most very over under after before until while within without because upon
    between during against through every""".split()
)
_WORD = re.compile(r"[^\W_]+")


def content_stems(text: str) -> set[str]:
    """Words of 4 or more letters outside the stopword list, cut to their first 6 letters."""
    words = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", text)} - STOPWORDS
    return {w[:6] for w in words}


def normalized_words(text: str) -> list[str]:
    """The text's words, normalized as `verify.normalize` does and casefolded."""
    return _WORD.findall(normalize(text)[0].casefold())


def shared_run(left: Sequence[str], right: Sequence[str]) -> int:
    """The length of the longest run of words the two sequences share."""
    best, previous = 0, [0] * (len(right) + 1)
    for word in left:
        current = [0] * (len(right) + 1)
        for j, other in enumerate(right, start=1):
            if word == other:
                current[j] = previous[j - 1] + 1
                best = max(best, current[j])
        previous = current
    return best


__all__ = ["STOPWORDS", "content_stems", "normalized_words", "shared_run"]
