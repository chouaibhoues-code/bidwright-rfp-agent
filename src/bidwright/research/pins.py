"""Tool pins (Iteration 2, M10's description-drift check; FI-11).

`check` hashes each allowed tool's name, description and input schema with
`llm.schema.sha256_of`, and compares the hashes, and the server's name and version as
`initialize` reports them, with the pins it is given from `config/mcp_pins.yaml`. Any mismatch,
a pinned tool the server no longer lists, or a server with no pins raises `ServerRefused`, and
the run uses no tool of that server. A changed description can carry an instruction to the
model, so a new version of the server is pinned again, on the host, by a person.

`pinned` builds the pins that `bidwright research pin` writes: it refuses a server whose
pinned tools lack a parameter `NotebookLMProvider` sends, since such a call would fail or be
read differently. NotebookLM's FastMCP server declares no version of its own, so the version
`initialize` reports is the MCP SDK's; the package and its version come from
`config/research.yaml`.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path

import yaml

from bidwright.config import ServerIdentity, ServerPins
from bidwright.fileio import write_atomic
from bidwright.llm.schema import sha256_of
from bidwright.research.mcp_client import ServerInfo, ToolInfo

PINS_FILE = "mcp_pins.yaml"
SERVERS_FILE = "mcp_servers.txt"
_PINS_HEADER = (
    "# Tool pins for MCP servers (ADR-032), written by `bidwright research pin` on the host.\n"
    "# A server with no pinned tools is refused. The server's name and version are what\n"
    "# `initialize` reports; the package is the one config/research.yaml declares.\n"
)
_SERVERS_HEADER = (
    "# The MCP servers' packages, written by `bidwright research pin` from\n"
    "# config/research.yaml, for the dependency audit:\n"
    "# uv run pip-audit -r config/mcp_servers.txt\n"
)


class ServerRefused(Exception):
    """The server's identity or tools do not match their pins."""


def tool_hash(tool: ToolInfo) -> str:
    return sha256_of([tool.name, tool.description, tool.input_schema])


def check(server: str, reported: ServerInfo, tools: Sequence[ToolInfo], pins: ServerPins) -> None:
    """Raise `ServerRefused` unless the server and its pinned tools match `pins`."""
    if pins.server is None or not pins.tools:
        raise ServerRefused(
            f"{server} has no pins in config/mcp_pins.yaml; run bidwright research pin on the host"
        )
    if (reported.name, reported.version) != (pins.server.name, pins.server.version):
        raise ServerRefused(
            f"{server} reports {reported.name} {reported.version}, and its pins name"
            f" {pins.server.name} {pins.server.version}"
        )
    listed = {tool.name: tool for tool in tools}
    for name, pinned in sorted(pins.tools.items()):
        tool = listed.get(name)
        if tool is None:
            raise ServerRefused(f"{server} no longer lists its pinned tool {name}")
        if tool_hash(tool) != pinned:
            raise ServerRefused(f"{server}'s tool {name} changed since it was pinned")


def pinned(
    server: str,
    reported: ServerInfo,
    tools: Sequence[ToolInfo],
    sent: Mapping[str, frozenset[str]],
    package: str | None,
) -> ServerPins:
    """The pins of the tools in `sent`, each of which must take every parameter sent to it."""
    listed = {tool.name: tool for tool in tools}
    for name, parameters in sorted(sent.items()):
        tool = listed.get(name)
        if tool is None:
            raise ServerRefused(f"{server} lists no tool {name}, which research needs")
        offered = set(tool.input_schema.get("properties", {}))
        missing = sorted(parameters - offered)
        if missing:
            raise ServerRefused(
                f"{server}'s tool {name} takes no {', '.join(missing)}, which research sends"
            )
    return ServerPins(
        server=ServerIdentity(name=reported.name, version=reported.version),
        package=package,
        tools={name: tool_hash(listed[name]) for name in sorted(sent)},
    )


def write_pins(folder: Path, server: str, pins: ServerPins) -> None:
    """Write `server`'s pins into `mcp_pins.yaml`, keeping the other servers' pins, and the
    pinned packages into `mcp_servers.txt`."""
    path = folder / PINS_FILE
    stored = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}
    stored[server] = pins.model_dump(mode="json")
    body = yaml.safe_dump(stored, sort_keys=True, default_flow_style=False, allow_unicode=True)
    write_atomic(path, _PINS_HEADER + body)
    packages = sorted(
        str(entry["package"]) for entry in stored.values() if entry and entry.get("package")
    )
    listing = "".join(f"{package}\n" for package in packages)
    write_atomic(folder / SERVERS_FILE, _SERVERS_HEADER + listing)


__all__ = [
    "PINS_FILE",
    "SERVERS_FILE",
    "ServerRefused",
    "check",
    "pinned",
    "tool_hash",
    "write_pins",
]
