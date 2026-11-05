"""The MCP client (Iteration 2): sync calls to one MCP server, for the graph's sync nodes.

`McpClient` opens one `ClientSession` per call: over streamable HTTP, through an
`httpx.AsyncClient` carrying the server entry's timeout, or over stdio, which starts the
server as a subprocess; and it runs the session with `anyio.run`, so a node gets plain
`list_tools()` and `call(name, arguments)`. Each session initializes, so `list_tools` also
returns the server's name and version as `initialize` reports them. A tool's result is read
from its JSON text, which FastMCP servers always send, or from its structured content. A result
whose `isError` is set, or whose `status` is `"error"`, raises `McpToolError` with the server's
message; a connection or protocol failure raises `McpUnavailable`.

With a circuit breaker (`harness/recovery.py`), the server's key is checked before each
connection, a tool error or a failed connection counts as a failure, and an answer resets it.

The process builds httpx's TLS context once and every session reuses it: building it loads the
certificate bundle, about half a second, which would otherwise be paid on every call.
"""

import json
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from functools import cache
from typing import Any

import anyio
import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent

from bidwright.config import HttpServer, StdioServer
from bidwright.harness.egress import server_url
from bidwright.harness.recovery import server_key
from bidwright.llm.types import Breaker


@dataclass(frozen=True)
class ServerInfo:
    """What a server's `initialize` reports."""

    name: str
    version: str


@dataclass(frozen=True)
class ToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any]


class McpError(Exception):
    """A call to an MCP server failed."""


class McpToolError(McpError):
    """The server answered with an error result."""


class McpUnavailable(McpError):
    """The server could not be reached, or broke the protocol."""


class McpClient:
    def __init__(
        self, name: str, server: HttpServer | StdioServer, *, breaker: Breaker | None = None
    ) -> None:
        self.name = name
        self.server = server
        self.breaker = breaker
        self.key = server_key(name)

    def list_tools(self) -> tuple[ServerInfo, list[ToolInfo]]:
        """The server's identity and its tools, with each tool's input schema."""
        listed = self._run(self._list)
        self._answered()
        return listed

    def call(self, tool: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Call one tool and return its result as a dict."""
        result: CallToolResult = self._run(lambda session: self._call(session, tool, arguments))
        try:
            payload = _payload(tool, result)
        except McpToolError:
            self._failed()
            raise
        self._answered()
        return payload

    def _run(self, work: Any) -> Any:
        if self.breaker is not None:
            self.breaker.check(self.key, self.name)
        try:
            return anyio.run(self._session, work)
        except Exception as exc:
            self._failed()
            raise McpUnavailable(f"{self.name}: {_message(exc)}") from exc

    def _failed(self) -> None:
        if self.breaker is not None:
            self.breaker.failure(self.key)

    def _answered(self) -> None:
        """An answer that is not an error resets the breaker, a tool error never does."""
        if self.breaker is not None:
            self.breaker.success(self.key)

    async def _session(self, work: Any) -> Any:
        timeout = timedelta(seconds=self.server.timeout_s)
        if isinstance(self.server, HttpServer):
            async with (
                httpx.AsyncClient(
                    timeout=httpx.Timeout(self.server.timeout_s), verify=_tls()
                ) as http,
                streamable_http_client(server_url(self.name, self.server), http_client=http) as (
                    read,
                    write,
                    _,
                ),
                ClientSession(read, write, read_timeout_seconds=timeout) as session,
            ):
                return await work(session)
        parameters = StdioServerParameters(
            command=self.server.command, args=list(self.server.args), env=self.server.env or None
        )
        async with (
            stdio_client(parameters) as (read, write),
            ClientSession(read, write, read_timeout_seconds=timeout) as session,
        ):
            return await work(session)

    async def _list(self, session: ClientSession) -> tuple[ServerInfo, list[ToolInfo]]:
        initialized = await session.initialize()
        listed = await session.list_tools()
        info = ServerInfo(initialized.serverInfo.name, initialized.serverInfo.version)
        tools = [ToolInfo(t.name, t.description or "", dict(t.inputSchema)) for t in listed.tools]
        return info, tools

    async def _call(
        self, session: ClientSession, tool: str, arguments: Mapping[str, Any]
    ) -> CallToolResult:
        await session.initialize()
        return await session.call_tool(
            tool,
            dict(arguments),
            read_timeout_seconds=timedelta(seconds=self.server.tool_timeout_s),
        )


@cache
def _tls() -> ssl.SSLContext:
    """httpx's default TLS context, built once per process."""
    return httpx.create_ssl_context()


def _payload(tool: str, result: CallToolResult) -> dict[str, Any]:
    """The result as a dict: its JSON text, or its structured content."""
    text = next((c.text for c in result.content if isinstance(c, TextContent)), None)
    if result.isError:
        raise McpToolError(f"{tool}: {text or 'the server reported an error'}")
    payload: Any = None
    if text is not None:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = {"text": text}
    elif result.structuredContent is not None:
        payload = result.structuredContent
    if not isinstance(payload, dict):
        payload = {"result": payload}
    if payload.get("status") == "error":
        raise McpToolError(f"{tool}: {payload.get('error') or 'the server reported an error'}")
    return payload


def _message(exc: BaseException) -> str:
    """The first leaf of an exception group, which anyio's task groups wrap failures in."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return f"{type(exc).__name__}: {exc}"


__all__ = ["McpClient", "McpError", "McpToolError", "McpUnavailable", "ServerInfo", "ToolInfo"]
