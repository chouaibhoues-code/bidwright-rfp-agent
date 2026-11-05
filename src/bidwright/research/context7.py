"""Context7 (Iteration 3, step 8; ADR-044): current library documentation for `techcheck`.

Code calls Context7's remote MCP server; no model chooses a call or writes an argument. The
server lists the two tools `SENT` names, checked on 2026-11-05 against Context7 4.5.0:
`resolve-library-id` takes `libraryName` and `query` and answers in text, one library per
block with its "Context7-compatible library ID: /org/project" line, best first;
`query-docs` takes `libraryId` and `query` and answers with the documentation in text.

`Context7Docs` checks the server's pins once a run (`connect`), as the NotebookLM provider
does, and makes each call as a `ToolRequest` through a `ToolGateway` for agent `techcheck`,
so the allowlist, the call cap, G4 (the pins) and G3 (a query or library name copying a
passage) apply. It resolves each library once a run, with the first technology claim's
query, and caches each documentation by library id and query. A query is the library, its
version and the claim's content words: the words of 4 or more letters outside the stopword
list, in order, at most 12. The documentation is split into paragraphs of at most 1,200
characters (`paragraphs`), each screened by `trust.screen`'s patterns; a quarantined one is
dropped, with a security event, and the rest are joined by blank lines and cut at the last
paragraph within 4,500 tokens (`joined`).
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from bidwright.config import Config, ServerPins
from bidwright.harness.egress import CONTEXT7_DESTINATION
from bidwright.harness.gateway import ToolGateway, ToolLog
from bidwright.harness.rules import RuleContext
from bidwright.llm.types import Breaker, CircuitOpen
from bidwright.obs.events import EventRecorder
from bidwright.research.mcp_client import McpClient, McpError
from bidwright.research.pins import ServerRefused, check
from bidwright.research.trust import ATTRIBUTION, suspect
from bidwright.schemas import LIBRARY_EXCERPT_MAX_CHARS, ToolRequest, ToolResult
from bidwright.text import STOPWORDS
from bidwright.tools import Tool

SERVER = CONTEXT7_DESTINATION
RESOLVE = "resolve-library-id"
QUERY = "query-docs"
SENT: Mapping[str, frozenset[str]] = {
    RESOLVE: frozenset({"libraryName", "query"}),
    QUERY: frozenset({"libraryId", "query"}),
}
AGENT = "techcheck"
DOCS_MAX_TOKENS = 4500
QUERY_MAX_WORDS = 12
_LIBRARY_ID = re.compile(r"Context7-compatible library ID:\s*(/\S+)")
_BLANK = re.compile(r"\n\s*\n")
_CONTENT_WORD = re.compile(r"[A-Za-z][\w.+/-]*[\w+]")  # such as to_pdfa, PDF/A, C++


class ResolveArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    libraryName: str = Field(min_length=1, max_length=100)  # noqa: N815 (the server's name)
    query: str = Field(min_length=1, max_length=300)


class QueryDocsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    libraryId: str = Field(pattern=r"^/[\w.\-]+(/[\w.\-]+)+$")  # noqa: N815 (the server's name)
    query: str = Field(min_length=1, max_length=300)


def library_ids(text: str) -> list[str]:
    """The library ids a resolve answer lists, best first."""
    return list(dict.fromkeys(_LIBRARY_ID.findall(text)))


def content_words(text: str) -> list[str]:
    """The words of 4 or more letters outside the stopword list, in order, each once."""
    found = _CONTENT_WORD.findall(text)
    words = [w for w in found if len(w) >= 4 and w.lower() not in STOPWORDS]
    return list(dict.fromkeys(words))


def query_for(library: str, version: str | None, claim_text: str) -> str:
    words = [w for w in content_words(claim_text) if w.lower() != library.lower()]
    parts = [library, *([version] if version else []), *words[:QUERY_MAX_WORDS]]
    return " ".join(parts)[:300]


def paragraphs(text: str, limit: int = LIBRARY_EXCERPT_MAX_CHARS) -> list[str]:
    """The text's paragraphs, split at blank lines; one longer than `limit` is cut at its last
    line break, sentence end or space within the limit, and the rest goes on."""
    found: list[str] = []
    for block in _BLANK.split(text):
        block = block.strip()
        while len(block) > limit:
            head = block[:limit]
            at = max(head.rfind("\n"), head.rfind(". ") + 1, head.rfind(" "))
            at = at if at > 0 else limit
            found.append(block[:at].strip())
            block = block[at:].strip()
        if block:
            found.append(block)
    return [p for p in found if p]


def joined(parts: Sequence[str], max_chars: int) -> str:
    """The paragraphs joined by blank lines, stopping at the last one within `max_chars`."""
    kept: list[str] = []
    size = 0
    for part in parts:
        extra = len(part) + (2 if kept else 0)
        if size + extra > max_chars:
            break
        kept.append(part)
        size += extra
    return "\n\n".join(kept)


@dataclass(frozen=True)
class Fetched:
    """The documentation one technology claim is judged on."""

    library_id: str
    query: str
    text: str
    quarantined: int = 0  # paragraphs dropped by the screen


@dataclass(frozen=True)
class NotFetched:
    """Why no documentation came: the claim stays `UNVALIDATED` with this reason."""

    reason: str


@dataclass
class Context7Docs:
    client: McpClient
    pins: ServerPins
    patterns: Sequence[re.Pattern[str]]
    events: EventRecorder | None = None
    chars_per_token: int = 4
    max_tokens: int = DOCS_MAX_TOKENS
    pinned: bool | None = None  # None until the first connection
    refusal: str | None = None
    _resolved: dict[str, str | None] = field(default_factory=dict)  # library to its id
    _docs: dict[tuple[str, str], str] = field(default_factory=dict)  # raw, by id and query
    _fetched: dict[tuple[str, str], Fetched] = field(default_factory=dict)

    def connect(self) -> bool:
        """Check the server's identity and tools against their pins, once a run. Raises
        `McpError` when the server is out of reach."""
        if self.pinned is None:
            reported, tools = self.client.list_tools()
            try:
                check(self.client.name, reported, tools, self.pins)
            except ServerRefused as exc:
                self.pinned, self.refusal = False, str(exc)
            else:
                self.pinned = True
        return self.pinned

    def tools(self) -> list[Tool]:
        return [
            Tool(
                name=RESOLVE,
                description="Context7: a library's name to its Context7 library id.",
                args_model=ResolveArgs,
                run=self._resolve,
            ),
            Tool(
                name=QUERY,
                description="Context7: a library's current documentation for a query.",
                args_model=QueryDocsArgs,
                run=self._query,
            ),
        ]

    def gateway(
        self, context: RuleContext, allowed: Sequence[str], cap: int, log: ToolLog | None = None
    ) -> ToolGateway:
        """The gateway for agent `techcheck`, with this server's pin result in `context`."""
        context.server, context.pinned = SERVER, bool(self.pinned)
        return ToolGateway.for_agent(AGENT, allowed, self.tools(), cap, context=context, log=log)

    def fetch(
        self, gateway: ToolGateway, library: str, version: str | None, claim_text: str, turn: int
    ) -> Fetched | NotFetched:
        """The documentation one technology claim is judged on, screened and cut."""
        query = query_for(library, version, claim_text)
        known = self._fetched.get((library, query))
        if known is not None:
            return known
        found = self.lookup(gateway, library, query, turn)
        if isinstance(found, NotFetched):
            return found
        library_id, raw = found
        text, dropped = self.prepare(raw, library)
        fetched = Fetched(library_id, query, text, dropped)
        self._fetched[(library, query)] = fetched
        return fetched

    def lookup(
        self, gateway: ToolGateway, library: str, query: str, turn: int
    ) -> tuple[str, str] | NotFetched:
        """The library's id and its documentation for `query`, as Context7 sends it: the
        library resolved once, the documentation once per library id and query."""
        if library not in self._resolved:
            request = ToolRequest(
                tool=RESOLVE, args={"libraryName": library, "query": query}, agent=AGENT, turn=turn
            )
            result = gateway.call(request)
            if result.status != "OK":
                return NotFetched(result.reason or f"{RESOLVE} gave {result.status}")
            self._resolved[library] = (result.data or {}).get("library_id")
        library_id = self._resolved[library]
        if library_id is None:
            return NotFetched(f"Context7 lists no library named {library}")
        raw = self._docs.get((library_id, query))
        if raw is None:
            request = ToolRequest(
                tool=QUERY, args={"libraryId": library_id, "query": query}, agent=AGENT, turn=turn
            )
            result = gateway.call(request)
            if result.status != "OK":
                return NotFetched(result.reason or f"{QUERY} gave {result.status}")
            raw = str((result.data or {}).get("text", ""))
            self._docs[(library_id, query)] = raw
        return library_id, raw

    def prepare(self, documentation: str, library: str) -> tuple[str, int]:
        """The documentation split, screened and cut; and how many paragraphs were dropped."""
        kept, dropped = [], 0
        for paragraph in paragraphs(documentation):
            if suspect(paragraph, self.patterns):
                dropped += 1
                if self.events is not None:
                    self.events.record(
                        "security",
                        AGENT,
                        f"a {library} documentation paragraph quarantined: it reads like an"
                        " instruction to a model",
                        ATTRIBUTION,
                    )
                continue
            kept.append(paragraph)
        return joined(kept, self.max_tokens * self.chars_per_token), dropped

    def _resolve(self, args: ResolveArgs) -> ToolResult:
        try:
            payload = self.client.call(RESOLVE, args.model_dump())
        except (McpError, CircuitOpen) as exc:
            return ToolResult(status="FAILED", reason=f"{RESOLVE} failed: {exc}")
        ids = library_ids(_text(payload))
        if not ids:
            return ToolResult(status="EMPTY", data={}, reason="Context7 found no library")
        return ToolResult(status="OK", data={"library_id": ids[0], "listed": ids})

    def _query(self, args: QueryDocsArgs) -> ToolResult:
        try:
            payload = self.client.call(QUERY, args.model_dump())
        except (McpError, CircuitOpen) as exc:
            return ToolResult(status="FAILED", reason=f"{QUERY} failed: {exc}")
        text = _text(payload)
        if not text.strip():
            return ToolResult(status="EMPTY", data={}, reason="Context7 returned no documentation")
        return ToolResult(status="OK", data={"text": text})


def _text(payload: Mapping[str, object]) -> str:
    """A tool's answer as text: Context7 answers in text, which the client keeps as `text`."""
    value = payload.get("text", payload.get("result", ""))
    return value if isinstance(value, str) else str(value)


def context7_docs(
    config: Config,
    patterns: Sequence[re.Pattern[str]],
    events: EventRecorder | None = None,
    breaker: Breaker | None = None,
) -> Context7Docs:
    """`Context7Docs` over the configured server, with its pins."""
    server = config.research.servers[SERVER]
    pins = config.pins.servers.get(SERVER, ServerPins())
    return Context7Docs(
        McpClient(SERVER, server, breaker=breaker),
        pins,
        patterns,
        events,
        chars_per_token=config.limits.context.chars_per_token,
    )


__all__ = [
    "AGENT",
    "QUERY",
    "RESOLVE",
    "SENT",
    "SERVER",
    "Context7Docs",
    "Fetched",
    "NotFetched",
    "content_words",
    "context7_docs",
    "joined",
    "library_ids",
    "paragraphs",
    "query_for",
]
