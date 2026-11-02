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
