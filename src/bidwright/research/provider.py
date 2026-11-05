"""The research provider (Iteration 2, section 4.4 of the design; ADR-033 and ADR-036).

`discover` depends on `ResearchProvider`, never on NotebookLM itself. `create_notebook(title)`
gives a notebook id; `start(notebook_id, query)` a task id; `status(notebook_id, task_id,
wait_s)` a `JobStatus`; `import_sources(notebook_id, task_id)` the number imported;
`sources(notebook_id)` each source's id and title; `bind(notebook_id)` sets the notebook `ask`
uses, with the sources and the excerpt count a run already holds, so a resumed run numbers
on from them; and `ask(question)` gives an `AskResult`, an answer with its excerpts and sources.
`NotebookLMProvider` (`nlm.py`) implements all of it over the MCP client; the research pack
provider (step 10) implements `ask` and refuses the rest with `ResearchRefused`. A licensed
source can replace NotebookLM behind the same interface.

`tier_of` gives a source's authority tier from its host: the lowest tier with a matching entry
in `config/research.yaml`, where an entry that starts with a dot matches any host that ends
with it, and another entry matches that host and its subdomains; a host with no match takes
the default tier, 4.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from bidwright.config import TiersConfig
from bidwright.schemas import AskResult, JobStatus, PackSource


@dataclass(frozen=True)
class NotebookSource:
    """A source in a notebook, as the provider lists it."""

    id: str
    title: str


class ResearchRefused(Exception):
    """The provider cannot do this: a research pack cannot start a job, for one."""


class ResearchProvider(Protocol):
    def create_notebook(self, title: str) -> str: ...

    def start(self, notebook_id: str, query: str) -> str: ...

    def status(self, notebook_id: str, task_id: str, wait_s: float) -> JobStatus: ...

    def import_sources(self, notebook_id: str, task_id: str) -> int: ...

    def sources(self, notebook_id: str) -> list[NotebookSource]: ...

    def bind(
        self, notebook_id: str, *, known: Sequence[PackSource] = (), excerpts: int = 0
    ) -> None: ...

    def ask(self, question: str) -> AskResult: ...


def tier_of(host: str, tiers: TiersConfig) -> int:
    """The authority tier of a host, from 1, the highest, to `tiers.default`."""
    name = host.lower().rstrip(".")
    for tier in sorted(tiers.hosts):
        for entry in tiers.hosts[tier]:
            listed = entry.lower()
            if listed.startswith("."):
                if name.endswith(listed):
                    return tier
            elif name == listed or name.endswith(f".{listed}"):
                return tier
    return tiers.default


__all__ = ["NotebookSource", "ResearchProvider", "ResearchRefused", "tier_of"]
