"""The MCP client, NotebookLM as the research provider, and the tool pins (Iteration 2, step 7),
against the fake server of `tests/mcp_fakes.py`, over HTTP and over stdio."""

import socket
import subprocess
import sys
import time
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import date
from importlib.metadata import version
from pathlib import Path

import pytest
import yaml

from bidwright import cli
from bidwright.config import HttpServer, PinsConfig, ServerPins, StdioServer, load_config
from bidwright.graph.build import execute
from bidwright.harness.egress import EgressRefused, check_run
from bidwright.harness.recovery import CircuitBreaker, server_key
from bidwright.llm.types import CircuitOpen
from bidwright.preflight import HOME
from bidwright.research.mcp_client import McpClient, McpToolError, McpUnavailable
from bidwright.research.nlm import SENT, NotebookLMProvider
from bidwright.research.pins import ServerRefused, check, pinned
from bidwright.research.provider import ResearchRefused
from tests.mcp_fakes import CITED_TEXT, NAME, WCAG, WCAG_URL
from tests.node_fakes import DEV_RFP, RuleBackend

CONFIG = load_config()
SIX = set(SENT)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextmanager
def _serving(*flags: str) -> Generator[str, None, None]:
    """The fake server over HTTP on a free port, in its own process, for the block."""
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "tests.mcp_fakes", "http", str(port), *flags],
        cwd=HOME,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 60
        while True:
            assert process.poll() is None, "the fake server exited"
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                assert time.monotonic() < deadline, "the fake server never listened"
                time.sleep(0.1)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        process.terminate()
        process.wait(30)


def _http(url: str) -> HttpServer:
    return HttpServer(transport="http", url=url, timeout_s=30, tool_timeout_s=30)


@pytest.fixture(scope="module")
def fake_url() -> Iterator[str]:
    with _serving() as url:
        yield url


def _pins(client: McpClient) -> ServerPins:
    reported, tools = client.list_tools()
    return pinned(client.name, reported, tools, SENT, "notebooklm-mcp-cli==0.15.8")


def _provider(url: str, pins: ServerPins | None = None) -> NotebookLMProvider:
    client = McpClient("notebooklm", _http(url))
    return NotebookLMProvider(
        client,
        pins if pins is not None else _pins(client),
        CONFIG.research.tiers,
        CONFIG.research.jobs,
        today=lambda: date(2026, 11, 5),
    )


# --- the client -------------------------------------------------------------------------------


def test_tools_are_listed_and_called_over_http(fake_url: str) -> None:
    client = McpClient("notebooklm", _http(fake_url))
    reported, tools = client.list_tools()
    assert reported.name == NAME and reported.version == version("mcp")
    names = {tool.name for tool in tools}
    assert SIX <= names and "notebook_delete" in names
    query = next(tool for tool in tools if tool.name == "notebook_query")
    assert {"notebook_id", "query", "new_conversation"} <= set(query.input_schema["properties"])
    created = client.call("notebook_create", {"title": "run-1"})
    assert created["status"] == "success" and created["notebook_id"].startswith("nb-")


def test_an_error_result_raises(fake_url: str) -> None:
    client = McpClient("notebooklm", _http(fake_url))
    with pytest.raises(McpToolError, match="Notebook nb-404 not found"):
        client.call("notebook_get", {"notebook_id": "nb-404"})


def test_tools_are_listed_and_one_is_called_over_stdio() -> None:
    server = StdioServer(
        transport="stdio",
        command=sys.executable,
        args=["-m", "tests.mcp_fakes", "stdio"],
        env={"PYTHONPATH": str(HOME)},
        timeout_s=60,
        tool_timeout_s=60,
    )
    client = McpClient("notebooklm", server)
    reported, tools = client.list_tools()
    assert reported.name == NAME and SIX <= {tool.name for tool in tools}
    assert client.call("notebook_create", {"title": "over stdio"})["notebook_id"] == "nb-1"


def test_a_server_out_of_reach_counts_against_its_breaker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One real refused connection, then refusals without the network: on Windows each real
    one takes two seconds."""
    breaker = CircuitBreaker(CONFIG.limits.breaker, tmp_path)
    client = McpClient("notebooklm", _http(f"http://127.0.0.1:{_free_port()}/mcp"), breaker=breaker)
    with pytest.raises(McpUnavailable, match="notebooklm"):
        client.call("notebook_create", {"title": "t"})

    async def refused(self: McpClient, work: object) -> object:
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(McpClient, "_session", refused)
    for _ in range(CONFIG.limits.breaker.failures - 1):
        with pytest.raises(McpUnavailable, match="ConnectionRefusedError"):
            client.call("notebook_create", {"title": "t"})
    assert breaker.state(server_key("notebooklm"))[1] is not None, "open"
    with pytest.raises(CircuitOpen, match="circuit open on notebooklm"):
        client.call("notebook_create", {"title": "t"})


# --- NotebookLM as the research provider ------------------------------------------------------


def test_a_job_runs_and_a_poll_that_returns_a_new_task_id_updates_it(fake_url: str) -> None:
    provider = _provider(fake_url)
    assert provider.connect() is True
    notebook = provider.create_notebook("run-2")
    task = provider.start(notebook, "Case management services in local government")
    first = provider.status(notebook, task, 0)
    assert (first.state, first.task_id) == ("running", task)
    done = provider.status(notebook, task, 0)
    assert done.state == "completed" and done.task_id == f"{task}-final", "the new id replaces it"
    assert done.report and [s.type_name for s in done.listing] == ["deep_report", "web", "web"]
    assert done.listing[0].url is None and done.listing[1].url == WCAG_URL
    assert provider.import_sources(notebook, done.task_id) == 1, "cited sources only"
    assert [(s.id, s.title) for s in provider.sources(notebook)] == [("src-wcag", WCAG)]
    with pytest.raises(ResearchRefused):
        provider.ask("Which standard applies to online forms?")
    provider.bind(notebook)
    result = provider.ask("Which standard applies to online forms?")
    assert result.answer and "WCAG 2.2" in result.answer
    [source] = result.sources
    assert (source.id, source.url, source.host, source.tier) == (
        "PS-001",
        WCAG_URL,
        "www.w3.org",
        1,
    )
    assert source.retrieved == date(2026, 11, 5)
    [excerpt] = result.excerpts  # a reference to a source the notebook does not list is dropped
    assert excerpt.id == "PX-0001" and excerpt.source_id == "PS-001"
    assert len(excerpt.text) <= 300 and CITED_TEXT.startswith(excerpt.text)
    again = provider.ask("And for documents?")
    assert again.sources[0].id == "PS-001" and again.excerpts[0].id == "PX-0002"


def test_a_resumed_provider_numbers_on_from_the_record(fake_url: str) -> None:
    first = _provider(fake_url)
    notebook = first.create_notebook("run-3")
    task = first.start(notebook, "Online forms")
    first.status(notebook, task, 0)
    first.status(notebook, task, 0)
    first.import_sources(notebook, f"{task}-final")
    first.bind(notebook)
    answered = first.ask("Which standard applies?")
    resumed = _provider(fake_url)
    resumed.status(notebook, f"{task}-final", 0)  # a resumed run polls its job before it asks
    resumed.bind(notebook, known=answered.sources, excerpts=len(answered.excerpts))
    again = resumed.ask("Which standard applies?")
    assert again.sources == answered.sources and again.excerpts[0].id == "PX-0002"


def test_no_research_reads_as_failed(fake_url: str) -> None:
    provider = _provider(fake_url)
    notebook = provider.create_notebook("run-4")
    task = provider.start(notebook, "nothing to find")
    assert provider.status(notebook, task, 0).state == "failed"


# --- the pins ---------------------------------------------------------------------------------


def test_fi11_changed_description_refuses_the_server(fake_url: str) -> None:
    pins = _pins(McpClient("notebooklm", _http(fake_url)))
    assert _provider(fake_url, pins).connect() is True, "the clean control: unchanged tools"
    with _serving("--changed-description") as changed:
        provider = _provider(changed, pins)
        assert provider.connect() is False
        assert provider.refusal == "notebooklm's tool notebook_query changed since it was pinned"
        with pytest.raises(ServerRefused, match="changed since it was pinned"):
            provider.create_notebook("never made")


def test_a_changed_reported_version_refuses_the_server(fake_url: str) -> None:
    pins = _pins(McpClient("notebooklm", _http(fake_url)))
    with _serving("--version", "9.9.9") as newer:
        reported, tools = McpClient("notebooklm", _http(newer)).list_tools()
        with pytest.raises(ServerRefused, match="reports gemini-notebook-mcp 9.9.9"):
            check("notebooklm", reported, tools, pins)


def test_a_server_with_no_pins_is_refused(fake_url: str) -> None:
    provider = _provider(fake_url, ServerPins())
    assert provider.connect() is False and "run bidwright research pin" in (provider.refusal or "")


def test_research_pin_refuses_a_tool_without_a_parameter_research_sends() -> None:
    with _serving("--no-new-conversation") as older:
        reported, tools = McpClient("notebooklm", _http(older)).list_tools()
        with pytest.raises(ServerRefused, match="notebook_query takes no new_conversation"):
            pinned("notebooklm", reported, tools, SENT, None)


def test_research_pin_writes_the_pins_and_the_server_list(
    fake_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "CONFIG_DIR", tmp_path)
    monkeypatch.setenv("NOTEBOOKLM_MCP_URL", fake_url)
    assert cli.main(["research", "pin"]) == 0
    written = yaml.safe_load((tmp_path / "mcp_pins.yaml").read_text(encoding="utf-8"))
    pins = PinsConfig.model_validate({"servers": written}).servers["notebooklm"]
    assert pins.server is not None and pins.server.name == NAME
    assert set(pins.tools) == SIX and pins.package == "notebooklm-mcp-cli==0.15.8"
    servers = (tmp_path / "mcp_servers.txt").read_text(encoding="utf-8").splitlines()
    assert servers[-1] == "notebooklm-mcp-cli==0.15.8"


# --- egress -----------------------------------------------------------------------------------


def test_a_client_run_with_live_research_is_refused_before_its_folder_exists(
    tmp_path: Path, client_root: Path
) -> None:
    document = tmp_path / "my_tender.pdf"
    document.write_bytes(DEV_RFP.read_bytes() + b"\n% a trailing comment changes the hash only\n")
    with pytest.raises(EgressRefused, match="--research pack"):
        execute(
            docling_mode="replay",
            source=document,
            profile="local",
            outputs=tmp_path / "out",
            backends={"ollama": RuleBackend()},
            research="live",
        )
    assert not (tmp_path / "out").exists()


def test_a_stdio_research_server_is_refused() -> None:
    server = StdioServer(
        transport="stdio", command="notebooklm-mcp", timeout_s=60, tool_timeout_s=60
    )
    with pytest.raises(EgressRefused, match="runs over stdio"):
        check_run(
            {}, None, None, "synthetic", register=CONFIG.egress, research=("notebooklm", server)
        )
