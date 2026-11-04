"""D-05, egress: every outbound channel is checked against `config/egress.yaml` and the run's
data class before the run starts. A refused trace endpoint falls back to `spans.jsonl`."""

from pathlib import Path

import pytest

import bidwright.obs.tracing
from bidwright.config import load_config
from bidwright.graph.build import execute
from bidwright.harness.egress import EgressRefused, check, check_run, hostname
from bidwright.llm.genai import GenaiBackend
from bidwright.llm.ollama import OllamaBackend
from bidwright.preflight import CONSENT, Refused
from bidwright.schemas import RunManifest
from tests.llm_fakes import FakeBackend
from tests.node_fakes import DEV_RFP, RuleBackend

GEMINI = "generativelanguage.googleapis.com"
REGISTER = load_config().egress


@pytest.fixture
def client_document(tmp_path: Path) -> Path:
    """The development PDF with one more line, so its hash is not in the corpus."""
    path = tmp_path / "my_tender.pdf"
    path.write_bytes(DEV_RFP.read_bytes() + b"\n% a trailing comment changes the hash only\n")
    return path


def test_hostnames_come_from_urls_and_bare_names() -> None:
    assert hostname("http://LocalHost:11434") == "localhost"
    assert hostname("ollama:11434") == "ollama"
    assert hostname(GEMINI) == GEMINI
    assert hostname("https://collector.example.com/v1") == "collector.example.com"


def test_an_unlisted_host_is_refused() -> None:
    with pytest.raises(EgressRefused, match="evil.example.com"):
        check("gemini", "evil.example.com", "synthetic", register=REGISTER)
    with pytest.raises(EgressRefused, match="not a destination"):
        check("cerebras", "api.cerebras.ai", "synthetic", register=REGISTER)
    with pytest.raises(EgressRefused, match="docling"):
        check_run({}, None, "https://docling.example.com", "synthetic", register=REGISTER)
    remote_ollama = OllamaBackend("http://gpu-box.example.net:11434")
    with pytest.raises(EgressRefused, match="gpu-box"):
        check_run({"ollama": remote_ollama}, None, None, "synthetic", register=REGISTER)
    assert issubclass(EgressRefused, Refused), "a refusal leaves no run folder"


def test_a_client_run_refuses_a_remote_host_and_allows_localhost() -> None:
    check("gemini", GEMINI, "synthetic", register=REGISTER)
    with pytest.raises(EgressRefused, match="local destinations only"):
        check("gemini", GEMINI, "client", register=REGISTER)
    check("gemini", GEMINI, "client", register=REGISTER, consent=True)  # ADR-026's exception
    check("ollama", "http://localhost:11434", "client", register=REGISTER)
    check("docling", "http://127.0.0.1:5001", "client", register=REGISTER, consent=True)
    local = {"ollama": OllamaBackend("http://localhost:11434")}
    assert check_run(local, None, "http://localhost:5001", "client", register=REGISTER) == []
    remote = {"gemini": GenaiBackend(api_key="unused", paid=True)}
    assert remote["gemini"].host == GEMINI
    with pytest.raises(EgressRefused):
        check_run(remote, None, None, "client", register=REGISTER)


def test_a_backend_with_no_host_attribute_passes() -> None:
    assert not hasattr(FakeBackend(), "host")
    assert check_run({"gemini": FakeBackend()}, None, None, "client", register=REGISTER) == []


def test_a_remote_trace_endpoint_is_recorded_and_never_contacted() -> None:
    endpoint = "https://collector.example.com"
    assert check_run({}, endpoint, None, "synthetic", register=REGISTER) == [
        "phoenix at collector.example.com"
    ], "unlisted on any run"
    assert check_run({}, "http://localhost:6006", None, "client", register=REGISTER) == []


def test_a_remote_trace_endpoint_on_a_client_run_falls_back_to_spans_jsonl(
    client_document: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PHOENIX_ENDPOINT", "https://collector.example.com")

    def no_connection(endpoint: str, timeout: float = 1.0) -> bool:
        raise AssertionError(f"the run tried to reach {endpoint}")

    monkeypatch.setattr(bidwright.obs.tracing, "reachable", no_connection)
    result = execute(
        source=client_document,
        profile="free",
        outputs=tmp_path / "out",
        backends={"gemini": RuleBackend()},
        consent=CONSENT,
        run_id="client-trace",
    )
    assert result.status == "COMPLETED", result.reason
    manifest = RunManifest.model_validate_json(
        (result.run_dir / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest.data_class == "client"
    assert manifest.refused_destinations == ["phoenix at collector.example.com"]
    assert (result.run_dir / "spans.jsonl").stat().st_size > 0


def test_a_client_run_on_the_paid_tier_is_refused_before_its_folder_exists(
    client_document: Path, tmp_path: Path
) -> None:
    with pytest.raises(EgressRefused, match="local destinations only"):
        execute(
            source=client_document,
            profile="paid",
            outputs=tmp_path / "out",
            backends={"gemini": GenaiBackend(api_key="unused", paid=True)},
        )
    assert not (tmp_path / "out").exists()


def test_a_backend_the_profile_does_not_use_is_neither_checked_nor_kept(
    client_document: Path, tmp_path: Path
) -> None:
    """A local run with a Gemini key in the environment still runs a client document."""
    result = execute(
        source=client_document,
        profile="local",
        outputs=tmp_path / "out",
        backends={
            "ollama": RuleBackend(),
            "gemini": GenaiBackend(api_key="unused"),
        },
        run_id="client-local",
    )
    assert result.status == "COMPLETED", result.reason
