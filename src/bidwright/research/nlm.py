"""NotebookLM as the research provider (Iteration 2), over the MCP client.

Six tools carry the workflow, each sent the parameters `SENT` lists, with the result shapes the
verification log records (2026-11-04): `notebook_create` gives `notebook_id`; `research_start`,
in the configured mode and on the web, gives `task_id`; `research_status`, polled once with
`max_wait` set to the wait and the full listing (`compact: false`), gives the job's state, its
task id, which can differ from the one asked for, its report, and its listing of sources, the
job's own report among them as the `deep_report` entry; `research_import` gives
`imported_count`; `notebook_get` gives each source's id and title; and `notebook_query`, in a
fresh conversation, gives the answer and its references. `in_progress` reads as running,
`completed` as completed, and `no_research`, any other status or an error result as failed.

The provider checks the server's pins at its first connection in a run: a mismatch refuses
that call and every later one with `ServerRefused`, and `pinned` tells the gateway's rule G4.

An answer's references become its sources and excerpts. A source takes its title from
`notebook_get` and its URL from the bound notebook's last `research_status` listing, matched by
exact title; a source with no URL, the job's report included, is dropped with its references,
so a resumed run polls its job once before it asks. Each remaining reference's cited text,
cut at the last word boundary within 300 characters, becomes an excerpt. A source keeps one id
across the run's answers, `PS-001` onward, and excerpts are numbered `PX-0001` onward; `bind`
takes the sources and the excerpt count already recorded, so a resumed run numbers on from them.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any, Literal

from bidwright.candidates import cut
from bidwright.config import Config, JobsConfig, ServerPins, TiersConfig
from bidwright.harness.egress import RESEARCH_DESTINATION, hostname
from bidwright.llm.types import Breaker
from bidwright.research.mcp_client import McpClient, McpToolError
from bidwright.research.pins import ServerRefused, check
from bidwright.research.provider import NotebookSource, ResearchRefused, tier_of
from bidwright.research.trust import solicitation
from bidwright.schemas import (
    EXCERPT_MAX_CHARS,
    AskResult,
    JobStatus,
    ListedSource,
    PackExcerpt,
    PackSource,
    Reference,
)

SERVER = RESEARCH_DESTINATION
POLL_INTERVAL_S = 30
IMPORT_TIMEOUT_S = 300
QUERY_TIMEOUT_S = 300
SENT: Mapping[str, frozenset[str]] = {
    "notebook_create": frozenset({"title"}),
    "research_start": frozenset({"query", "mode", "source", "notebook_id"}),
    "research_status": frozenset(
        {"notebook_id", "task_id", "max_wait", "poll_interval", "compact", "auto_import"}
    ),
    "research_import": frozenset({"notebook_id", "task_id", "cited_only", "timeout"}),
    "notebook_get": frozenset({"notebook_id"}),
    "notebook_query": frozenset({"notebook_id", "query", "new_conversation", "timeout"}),
}
PollState = Literal["running", "completed", "failed"]
STATES: Mapping[str, PollState] = {"in_progress": "running", "completed": "completed"}
REPORT = "deep_report"


class NotebookLMProvider:
    def __init__(
        self,
        client: McpClient,
        pins: ServerPins,
        tiers: TiersConfig,
        jobs: JobsConfig,
        *,
        today: Callable[[], date] = date.today,
    ) -> None:
        self.client = client
        self.pins = pins
        self.tiers = tiers
        self.jobs = jobs
        self.pinned: bool | None = None  # None until the first connection
        self.refusal: str | None = None
        self._today = today
        self._listings: dict[str, list[ListedSource]] = {}
        self._notebook: str | None = None
        self._sources: dict[str, PackSource] = {}  # by NotebookLM's source id
        self._excerpts = 0

    def connect(self) -> bool:
        """Check the server's identity and tools against their pins, once per run."""
        if self.pinned is None:
            reported, tools = self.client.list_tools()
            try:
                check(self.client.name, reported, tools, self.pins)
            except ServerRefused as exc:
                self.pinned, self.refusal = False, str(exc)
            else:
                self.pinned = True
        return self.pinned

    def create_notebook(self, title: str) -> str:
        return str(self._call("notebook_create", {"title": title})["notebook_id"])

    def start(self, notebook_id: str, query: str) -> str:
        arguments = {"query": query, "mode": self.jobs.mode, "source": "web"}
        payload = self._call("research_start", {**arguments, "notebook_id": notebook_id})
        return str(payload["task_id"])

    def status(self, notebook_id: str, task_id: str, wait_s: float) -> JobStatus:
        arguments = {
            "notebook_id": notebook_id,
            "task_id": task_id,
            "max_wait": int(wait_s),
            "poll_interval": POLL_INTERVAL_S,
            "compact": False,
            "auto_import": False,
        }
        try:
            payload = self._call("research_status", arguments)
        except McpToolError:
            return JobStatus(state="failed", task_id=task_id)
        listing = [_listed(entry) for entry in payload.get("sources") or []]
        if listing:
            self._listings[notebook_id] = listing
        state: PollState = STATES.get(str(payload.get("status")), "failed")
        return JobStatus(
            state=state,
            task_id=str(payload.get("task_id") or task_id),
            report=payload.get("report") or None,
            listing=listing,
        )

    def import_sources(self, notebook_id: str, task_id: str) -> int:
        arguments = {
            "notebook_id": notebook_id,
            "task_id": task_id,
            "cited_only": self.jobs.import_sources == "cited",
            "timeout": IMPORT_TIMEOUT_S,
        }
        return int(self._call("research_import", arguments).get("imported_count") or 0)

    def sources(self, notebook_id: str) -> list[NotebookSource]:
        payload = self._call("notebook_get", {"notebook_id": notebook_id})
        return [
            NotebookSource(str(entry["id"]), str(entry.get("title") or ""))
            for entry in payload.get("sources") or []
            if entry.get("id")
        ]

    def bind(
        self, notebook_id: str, *, known: Sequence[PackSource] = (), excerpts: int = 0
    ) -> None:
        """The notebook `ask` uses, with the sources and excerpt count a run already holds."""
        self._notebook = notebook_id
        for source in known:
            self._sources.setdefault(source.provider_source_id, source)
        self._excerpts = max(self._excerpts, excerpts)

    def ask(self, question: str) -> AskResult:
        notebook = self._notebook
        if notebook is None:
            raise ResearchRefused("no notebook is bound yet; a research job must finish first")
        arguments = {
            "notebook_id": notebook,
            "query": question,
            "new_conversation": True,
            "timeout": QUERY_TIMEOUT_S,
        }
        payload = self._call("notebook_query", arguments)
        references = [
            Reference(
                source_id=str(entry["source_id"]),
                citation_number=int(entry.get("citation_number") or 0),
                cited_text=str(entry.get("cited_text") or ""),
            )
            for entry in payload.get("references") or []
            if entry.get("source_id")
        ]
        titles = {s.id: s.title for s in self.sources(notebook)} if references else {}
        urls: dict[str, str] = {}
        for entry in self._listings.get(notebook, []):
            if entry.url and entry.type_name != REPORT:
                urls.setdefault(entry.title, entry.url)
        excerpts: list[PackExcerpt] = []
        used: dict[str, PackSource] = {}
        seen: set[tuple[str, str]] = set()
        dropped: set[str] = set()  # sources that read like a published solicitation (ADR-038)
        for reference in references:
            if reference.source_id not in self._sources:
                title = titles.get(reference.source_id, "")
                if solicitation(title, urls.get(title, "")):
                    dropped.add(reference.source_id)
                    continue
            source = self._source(reference.source_id, titles, urls)
            text = cut(reference.cited_text.strip(), EXCERPT_MAX_CHARS)
            if source is None or not text or (source.id, text) in seen:
                continue
            seen.add((source.id, text))
            used[source.id] = source
            self._excerpts += 1
            excerpts.append(
                PackExcerpt(id=f"PX-{self._excerpts:04d}", source_id=source.id, text=text)
            )
        # The answer is a synthesis that can carry a left-out source's content, so it is
        # withheld when it cited one; its clean excerpts still return.
        answer = None if dropped else payload.get("answer") or None
        return AskResult(
            answer=answer, excerpts=excerpts, sources=list(used.values()), dropped=len(dropped)
        )

    def _source(
        self, provider_id: str, titles: Mapping[str, str], urls: Mapping[str, str]
    ) -> PackSource | None:
        known = self._sources.get(provider_id)
        if known is not None:
            return known
        title = titles.get(provider_id)
        url = urls.get(title) if title else None
        if not title or not url:
            return None
        host = hostname(url)
        source = PackSource(
            id=f"PS-{len(self._sources) + 1:03d}",
            provider_source_id=provider_id,
            url=url,
            title=title,
            host=host,
            tier=tier_of(host, self.tiers),
            retrieved=self._today(),
        )
        self._sources[provider_id] = source
        return source

    def _call(self, tool: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if not self.connect():
            raise ServerRefused(self.refusal or f"{self.client.name} does not match its pins")
        return self.client.call(tool, arguments)


def _listed(entry: Mapping[str, Any]) -> ListedSource:
    return ListedSource(
        index=int(entry.get("index") or 0),
        title=str(entry.get("title") or ""),
        url=entry.get("url") or None,
        type_name=str(entry.get("result_type_name") or "web"),
        cited=bool(entry.get("cited")),
    )


def notebooklm_provider(config: Config, breaker: Breaker | None = None) -> NotebookLMProvider:
    """The provider over the configured NotebookLM server, with its pins."""
    server = config.research.servers[SERVER]
    pins = config.pins.servers.get(SERVER, ServerPins())
    client = McpClient(SERVER, server, breaker=breaker)
    return NotebookLMProvider(client, pins, config.research.tiers, config.research.jobs)


__all__ = ["SENT", "SERVER", "NotebookLMProvider", "notebooklm_provider"]
