"""The cache key changes with everything that should change a response, and nothing else."""

from pathlib import Path
from typing import Any

import pytest

from bidwright.config import load_config
from bidwright.llm.client import LLMClient
from bidwright.llm.replay import CassetteStore, cache_key
from bidwright.llm.types import Message
from bidwright.schemas import ExtractResult
from tests.llm_fakes import CALL, FakeBackend

BASE: dict[str, Any] = {
    "prompt_hash": "sha256:p",
    "schema_hash": "sha256:s",
    "tools_hash": None,
    "model": "gemini-3.5-flash-lite",
    "settings": {"thinking": "minimal"},
    "input_hash": "sha256:i",
    "repeat": 0,
}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prompt_hash", "sha256:p2"),
        ("schema_hash", "sha256:s2"),
        ("tools_hash", "sha256:t"),
        ("model", "gemini-3.1-flash-lite"),
        ("settings", {"thinking": "low"}),
        ("input_hash", "sha256:i2"),
        ("repeat", 1),
    ],
)
def test_key_changes_with_each_part(field: str, value: Any) -> None:
    assert cache_key(**BASE) != cache_key(**{**BASE, field: value})


def test_key_is_stable() -> None:
    assert cache_key(**BASE) == cache_key(**dict(BASE))


def test_delimiter_tags_do_not_change_the_key(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path)
    config = load_config()
    recorder = LLMClient(config, "free", {"gemini": FakeBackend()}, mode="record", cassettes=store)
    replayer = LLMClient(config, "free", mode="replay", cassettes=store)
    recorder.complete(
        "extract", [Message("user", "<data-7f3a>passages</data-7f3a>")], ExtractResult, **CALL
    )
    replayed = replayer.complete(
        "extract", [Message("user", "<data-91bc>passages</data-91bc>")], ExtractResult, **CALL
    )
    assert replayed.replayed and replayed.parsed is not None
