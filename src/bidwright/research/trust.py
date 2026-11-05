"""Inbound trust for research (Iteration 2, step 10; section 4.4 of the design).

Research results are untrusted web content. `screen` checks each excerpt and each recorded
answer against the suspect patterns of `config/ingest.yaml`, as `ingest` checks passages, and
quarantines a match: the item stays, with `quarantined` set, so the run can show what it held
back, and each match records a security event attributed `injection-dominant`. A quarantined
excerpt is never returned and no item may cite it; a quarantined answer's text is withheld
while its clean excerpts still return. A research pack, and from Iteration 3 the library pack's
excerpts, are screened again each time they load.

`solicitation` tells whether a source's title or URL reads like a published solicitation, such
as a request for proposal: the data rule keeps real tenders out of prompts and out of the
repository, so the NotebookLM provider leaves such a source out before any excerpt is made
(ADR-038), and the pack builder lists any that remain for review.

`tier` gives a source URL's authority tier from its host, read with `egress.hostname`, by the
tier rule of `research.provider.tier_of`. Everything research yields carries the evidence class
`EXTERNAL_RESEARCH` and is never promoted to capability evidence.
"""

import re
from collections.abc import Sequence

from bidwright.config import TiersConfig
from bidwright.harness.egress import hostname
from bidwright.obs.events import EventRecorder
from bidwright.research.provider import tier_of
from bidwright.schemas import Attribution, LibraryExcerpt, PackAnswer, PackExcerpt

ATTRIBUTION: Attribution = "injection-dominant"
# A title or URL that reads like a published solicitation, which the data rule keeps out.
SOLICITATION = re.compile(
    r"(?i)\b(rfp|rfq|itt|request\W+for\W+(proposals?|quotations?|tenders?)|invitation\W+to"
    r"\W+tender|tender\W+documents?|solicitation|bid\W+opportunit\w*)\b"
)


def solicitation(title: str, url: str) -> bool:
    """Whether a source's title or URL reads like a published solicitation (ADR-038)."""
    return SOLICITATION.search(f"{title} {url}") is not None


def suspect(text: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    """Whether the text matches one of the suspect patterns."""
    return any(pattern.search(text) for pattern in patterns)


def _label(item: PackExcerpt | PackAnswer | LibraryExcerpt) -> tuple[str, str]:
    if isinstance(item, PackExcerpt | LibraryExcerpt):
        return item.id, item.text
    question = item.question if len(item.question) <= 60 else item.question[:57] + "..."
    return f"the recorded answer to {question!r}", item.answer


def screen[T: (PackExcerpt, PackAnswer, LibraryExcerpt)](
    items: Sequence[T],
    patterns: Sequence[re.Pattern[str]],
    events: EventRecorder | None = None,
    *,
    node: str = "research",
) -> list[T]:
    """The items in order, each one that matches a suspect pattern quarantined, with a security
    event for every match."""
    screened: list[T] = []
    for item in items:
        label, text = _label(item)
        if suspect(text, patterns):
            if events is not None:
                events.record(
                    "security",
                    node,
                    f"{label} quarantined: it reads like an instruction to a model",
                    ATTRIBUTION,
                )
            item = item.model_copy(update={"quarantined": True})
        screened.append(item)
    return screened


def tier(url: str, tiers: TiersConfig) -> int:
    """The authority tier of a source URL, from 1, the highest, to `tiers.default`."""
    return tier_of(hostname(url), tiers)


__all__ = ["ATTRIBUTION", "SOLICITATION", "screen", "solicitation", "suspect", "tier"]
