"""Word-level text helpers shared by the nodes and the gateway's rules (Iteration 2).

`content_stems` and `STOPWORDS` come from `graph/nodes.py` unchanged, which re-exports them:
the `risk` loop's generic-risk check and the cluster rule use them. `normalized_words` is the
gateway's normalization (ADR-032): the text as `verify.normalize` gives it, so ligatures, quote
styles, whitespace and line-end hyphens do not matter, then casefolded with `str.casefold` and
split on every character that is not a letter or a digit. The outbound rule G3, the brief's
topic rule, the overlap check on queries and ADR-034's matching all use it.
"""

import re

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


__all__ = ["STOPWORDS", "content_stems", "normalized_words"]
