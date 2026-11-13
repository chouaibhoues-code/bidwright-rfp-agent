"""Compose publishes loopback ports only, holds no literal credentials, and keeps gold out."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "compose.yaml").exists():
    pytest.skip("compose.yaml is not in the image", allow_module_level=True)
COMPOSE: dict[str, Any] = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
SECRET_NAMES = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)", re.IGNORECASE)


def test_only_loopback_ports_are_published() -> None:
    for name, service in COMPOSE["services"].items():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), (name, port)


def test_no_literal_credentials() -> None:
    for name, service in COMPOSE["services"].items():
        for key, value in (service.get("environment") or {}).items():
            if SECRET_NAMES.search(key):
                assert str(value).startswith("${"), (name, key)


def test_only_the_eval_service_mounts_gold_or_the_corpus() -> None:
    for name, service in COMPOSE["services"].items():
        mounts = " ".join(str(v) for v in service.get("volumes", []))
        if "evals/gold" in mounts or "evals/corpus" in mounts:
            assert name == "eval", name
            assert all(
                m.endswith(":ro")
                for m in service["volumes"]
                if "evals/gold" in m or "evals/corpus" in m
            )


def test_the_image_never_receives_gold() -> None:
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for path in ("evals/corpus/", "evals/gold/", "evals/results/", "private/", "outputs/", ".env"):
        assert path in ignored, path


def test_offline_services_have_no_network() -> None:
    for name in ("test", "demo"):
        assert COMPOSE["services"][name]["network_mode"] == "none"


def test_docling_is_pinned_by_digest_and_published_on_loopback_only() -> None:
    """The parser service of Iteration 1: a pinned image, loopback only, reached by app alone."""
    docling = COMPOSE["services"]["docling"]
    pinned = r"ghcr\.io/docling-project/docling-serve-cpu:v[\d.]+@sha256:[0-9a-f]{64}"
    assert re.fullmatch(pinned, docling["image"])
    assert docling["ports"] == ["127.0.0.1:5001:5001"]
    assert "docling" in COMPOSE["services"]["app"]["depends_on"]
    assert COMPOSE["services"]["app"]["environment"]["DOCLING_URL"] == "http://docling:5001"
    for name in ("test", "demo"):
        assert "docling" not in COMPOSE["services"][name].get("depends_on", [])


RUNNERS = ("app", "ui")  # the services that run `bidwright run`: `ui`'s Run page starts runs


def test_only_the_services_that_run_bidwright_name_the_host_machine() -> None:
    """host.docker.internal lets a run reach the host's own Ollama and NotebookLM server; only
    the services that start runs map it."""
    for name, service in COMPOSE["services"].items():
        mapped = service.get("extra_hosts", [])
        if name in RUNNERS:
            assert mapped == ["host.docker.internal:host-gateway"], name
        else:
            assert not mapped, name


def test_every_service_that_runs_bidwright_has_the_same_runtime() -> None:
    """The second architecture review (DE-04): a run started from the UI's Run page had no
    Cerebras, Groq or Context7 key, so it assessed on Gemini and ended DEGRADED."""
    app = COMPOSE["services"]["app"]["environment"]
    assert {"CEREBRAS_API_KEY", "GROQ_API_KEY", "CONTEXT7_API_KEY"} <= set(app)
    for name in RUNNERS:
        assert COMPOSE["services"][name]["environment"] == app, name


def test_ui_publishes_8501_on_loopback_only_and_mounts_results_read_only() -> None:
    """ADR-050: only `ui` publishes 8501 and 8001 (on loopback), and only `ui` and `eval` mount
    `evals/results/`."""
    ui = COMPOSE["services"]["ui"]
    assert ui["ports"] == ["127.0.0.1:8501:8501", "127.0.0.1:8001:8001"]
    assert ui["profiles"] == ["ui"]
    # Section 4.14: both servers bind every address inside the container, where loopback is
    # unreachable through a published port; the ports above keep them on the host's loopback.
    assert ui["command"] == ["ui", "--address", "0.0.0.0", "--api"]  # noqa: S104
    for name, service in COMPOSE["services"].items():
        ports = [str(p) for p in service.get("ports", [])]
        if any("8501" in p or "8001" in p for p in ports):
            assert name == "ui", (name, ports)
        mounts = [str(v) for v in service.get("volumes", [])]
        if any("evals/results" in m for m in mounts):
            assert name in ("ui", "eval"), (name, mounts)
            if name == "ui":
                assert all(m.endswith(":ro") for m in mounts if "evals/results" in m), mounts
