"""The response cache: an identical live call is answered from disk, a different repeat index
is not, and `record` neither reads nor writes it."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

import bidwright.llm.cache
from bidwright.config import load_config
from bidwright.llm.cache import response_cache
from bidwright.llm.client import LLMClient
from bidwright.llm.limits import Limiter
from bidwright.llm.replay import CassetteStore
from bidwright.llm.types import Message
from bidwright.preflight import HOME
from bidwright.schemas import ExtractResult, LedgerEntry
from tests.llm_fakes import CALL, FakeBackend

MESSAGES = [Message("system", "Extract obligations."), Message("user", "passages")]


def _client(
    backend: FakeBackend,
    cache: CassetteStore,
    *,
    on_ledger: Callable[[LedgerEntry], None] | None = None,
    before_attempt: Callable[[], None] | None = None,
    limiter: Limiter | None = None,
) -> LLMClient:
    return LLMClient(
        load_config(),
        "free",
        {"gemini": backend},
        cache=cache,
        run_id="run-a",
        on_ledger=on_ledger,
        before_attempt=before_attempt,
        limiter=limiter,
    )


def test_a_second_identical_call_is_served_from_the_cache(tmp_path: Path) -> None:
    backend = FakeBackend()
    entries: list[LedgerEntry] = []
    attempts: list[int] = []
    client = _client(
        backend,
        response_cache(tmp_path),
        on_ledger=entries.append,
        before_attempt=lambda: attempts.append(1),
    )
    first = client.complete("extract", MESSAGES, ExtractResult, **CALL)
    second = client.complete("extract", MESSAGES, ExtractResult, **CALL)
    assert len(backend.requests) == 1 and len(attempts) == 1, "a hit makes no attempt"
    assert not first.replayed and second.replayed and second.text == first.text
    assert isinstance(second.parsed, ExtractResult)
    hit = entries[1]
    assert hit.replayed and hit.cost_usd == 0.0 and hit.retries == 0
    [stored] = list(tmp_path.glob("*.json"))
    assert json.loads(stored.read_text(encoding="utf-8"))["run_id"] == "run-a", "for purge"


def test_a_different_repeat_index_misses_it(tmp_path: Path) -> None:
    backend = FakeBackend()
    client = _client(backend, response_cache(tmp_path))
    client.complete("extract", MESSAGES, ExtractResult, **CALL)
    again = client.complete("extract", MESSAGES, ExtractResult, **CALL, repeat=1)
    assert not again.replayed and len(backend.requests) == 2
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_a_record_run_ignores_the_cache(tmp_path: Path) -> None:
    cache = response_cache(tmp_path / "cache")
    _client(FakeBackend(), cache).complete("extract", MESSAGES, ExtractResult, **CALL)
    assert len(list(cache.root.glob("*.json"))) == 1
    backend, store = FakeBackend(), CassetteStore(tmp_path / "cassettes")
    recorder = LLMClient(
        load_config(),
        "free",
        {"gemini": backend},
        mode="record",
        cassettes=store,
        cache=cache,
        run_id="run-b",
    )
    completion = recorder.complete("extract", MESSAGES, ExtractResult, **CALL)
    assert not completion.replayed and len(backend.requests) == 1, "the cached entry is not read"
    entries = [json.loads(p.read_text(encoding="utf-8")) for p in cache.root.glob("*.json")]
    assert [e["run_id"] for e in entries] == ["run-a"], "and nothing is written to the cache"
    assert len(list(store.root.glob("*.json"))) == 1


def test_a_cache_hit_skips_the_limiter(tmp_path: Path) -> None:
    cache = response_cache(tmp_path / "cache")
    _client(FakeBackend(), cache).complete("extract", MESSAGES, ExtractResult, **CALL)
    limiter = Limiter(load_config().limits, "free", tmp_path / "quota")
    backend = FakeBackend()
    hit = _client(backend, cache, limiter=limiter).complete(
        "extract", MESSAGES, ExtractResult, **CALL
    )
    assert hit.replayed and backend.requests == []
    assert limiter.count("gemini", "gemini-3.5-flash-lite") == 0


def test_the_default_folder_is_under_home_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()  # drop the test-wide isolation of conftest.py, to read the real default
    assert bidwright.llm.cache.CACHE_DIR == HOME / "outputs" / ".cache"
    assert response_cache().root == bidwright.llm.cache.CACHE_DIR


def test_an_answer_that_does_not_parse_is_never_cached(tmp_path: Path) -> None:
    """A malformed answer is a fault to retry, so a later identical call asks the model again."""
    backend = FakeBackend(text="{not json")
    client = _client(backend, response_cache(tmp_path))
    first = client.complete("extract", MESSAGES, ExtractResult, **CALL)
    second = client.complete("extract", MESSAGES, ExtractResult, **CALL)
    assert first.parse_error and second.parse_error and not second.replayed
    assert len(backend.requests) == 2 and not list(tmp_path.glob("*.json"))
