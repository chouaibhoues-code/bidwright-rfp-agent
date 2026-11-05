"""The response cache: an identical live call is answered from disk, a different repeat index
is not, and `record` neither reads nor writes it. The run's journal: every answer a live run
receives is kept, and only a resume reads it. Entries are written whole."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

import bidwright.fileio
import bidwright.llm.cache
from bidwright.config import load_config
from bidwright.fileio import write_atomic
from bidwright.harness.budget import RunBudget
from bidwright.llm.cache import response_cache, run_journal
from bidwright.llm.client import LLMClient
from bidwright.llm.limits import Limiter
from bidwright.llm.replay import CassetteStore
from bidwright.llm.types import Message, Response
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


# --- The run's journal (Iteration 2, ADR-031) ------------------------------------------------


def _journaled(
    backend: FakeBackend,
    journal: CassetteStore,
    *,
    journal_read: bool = False,
    on_ledger: Callable[[LedgerEntry], None] | None = None,
    before_attempt: Callable[[], None] | None = None,
) -> LLMClient:
    return LLMClient(
        load_config(),
        "free",
        {"gemini": backend},
        run_id="run-a",
        journal=journal,
        journal_read=journal_read,
        on_ledger=on_ledger,
        before_attempt=before_attempt,
    )


def test_a_live_call_lands_in_the_journal_with_the_cache_off(tmp_path: Path) -> None:
    journal = run_journal(tmp_path / "run-a")
    assert journal.root == tmp_path / "run-a" / "journal"
    _journaled(FakeBackend(), journal).complete("extract", MESSAGES, ExtractResult, **CALL)
    [entry] = list(journal.root.glob("*.json"))
    assert json.loads(entry.read_text(encoding="utf-8"))["run_id"] == "run-a"


def test_the_journal_answers_only_a_resume(tmp_path: Path) -> None:
    """Off, a second identical call reaches the backend; on, the journal answers it at no cost
    and the budget counts no attempt."""
    journal = run_journal(tmp_path / "run-a")
    backend = FakeBackend()
    first = _journaled(backend, journal)
    first.complete("extract", MESSAGES, ExtractResult, **CALL)
    first.complete("extract", MESSAGES, ExtractResult, **CALL)
    assert len(backend.requests) == 2, "a run that is not resuming never reads its journal"
    budget = RunBudget(load_config().limits.run("dev", "free"))
    entries: list[LedgerEntry] = []
    resumed = _journaled(
        backend,
        journal,
        journal_read=True,
        on_ledger=entries.append,
        before_attempt=budget.attempt,
    )
    hit = resumed.complete("extract", MESSAGES, ExtractResult, **CALL)
    assert len(backend.requests) == 2 and budget.requests == 0
    assert hit.replayed and isinstance(hit.parsed, ExtractResult)
    [entry] = entries
    assert entry.replayed and entry.cost_usd == 0.0 and entry.retries == 0


def test_a_cache_hit_is_journaled_too(tmp_path: Path) -> None:
    """The journal holds every answer the run had, so a resume never depends on the cache."""
    cache = response_cache(tmp_path / "cache")
    _client(FakeBackend(), cache).complete("extract", MESSAGES, ExtractResult, **CALL)
    journal = run_journal(tmp_path / "run-b")
    backend = FakeBackend()
    client = LLMClient(
        load_config(), "free", {"gemini": backend}, cache=cache, journal=journal, run_id="run-b"
    )
    assert client.complete("extract", MESSAGES, ExtractResult, **CALL).replayed
    assert backend.requests == [] and len(list(journal.root.glob("*.json"))) == 1


def test_a_staging_file_left_by_a_kill_is_ignored(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path)
    store.save("sha256:aa", {"run_id": "run-a"}, Response(text="kept"))
    (tmp_path / "aa.json.0123456789ab.tmp").write_text('{"key": "sha256:aa", "resp', "utf-8")
    (tmp_path / "bb.json.0123456789ab.tmp").write_text('{"key": "sha256:bb"', "utf-8")
    kept = store.load("sha256:aa")
    assert kept is not None and kept.text == "kept"
    assert store.load("sha256:bb") is None, "a write that never finished is no entry"
    assert [p.name for p in tmp_path.glob("*.json")] == ["aa.json"]


def test_a_whole_file_write_leaves_no_staging_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "count.json"
    write_atomic(target, "one\n")
    write_atomic(target, "two\n")
    assert target.read_text(encoding="utf-8") == "two\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["count.json"]

    def refuse(source: object, destination: object) -> None:
        raise OSError("disk gone")

    monkeypatch.setattr(bidwright.fileio.os, "replace", refuse)
    with pytest.raises(OSError, match="disk gone"):
        write_atomic(target, "three\n")
    assert target.read_text(encoding="utf-8") == "two\n", "the old file stands"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["count.json"]
