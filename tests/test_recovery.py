"""Recovery (Iteration 2): the circuit breaker (FI-01) and the dead-letter file (FI-02)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from bidwright.config import Config, load_config
from bidwright.graph.build import RunResult, execute
from bidwright.harness.recovery import CircuitBreaker, DeadLetters, read_dead_letters
from bidwright.llm.client import LLMClient
from bidwright.llm.limits import model_key
from bidwright.llm.simulator import ProviderSimulator
from bidwright.llm.types import Backend, CircuitOpen, Message, UnrecoverableFault
from bidwright.obs.events import read_events
from bidwright.schemas import ExtractResult, LedgerEntry, RunManifest
from tests.kill_target import ScriptedRun
from tests.llm_fakes import CALL, FakeBackend
from tests.node_fakes import DEV_RFP, RuleBackend, fake_backends

MESSAGES = [Message("system", "Extract obligations."), Message("user", "passages")]
PRIMARY = model_key("gemini", "free", "gemini-3.5-flash-lite")


def _breaker(root: Path, changes: list[str] | None = None, **kwargs: Any) -> CircuitBreaker:
    on_change = changes.append if changes is not None else None
    return CircuitBreaker(load_config().limits.breaker, root, on_change=on_change, **kwargs)


def _client(backend: Backend, breaker: CircuitBreaker, *, fallback: bool = False) -> LLMClient:
    return LLMClient(
        load_config(),
        "free",
        {"gemini": backend},
        breaker=breaker,
        fallback=fallback,
        sleep=lambda _: None,
    )


def _failures(count: int) -> list[dict[str, Any]]:
    """Timeouts and server errors, alternating, on the first `count` calls."""
    return [
        {"call": n, "fault": "timeout" if n % 2 else "server_error"} for n in range(1, count + 1)
    ]


# --- the circuit breaker ----------------------------------------------------------------------


def test_fi01_breaker_opens_after_five_failures(tmp_path: Path) -> None:
    """Four attempts fail one call; the fifth failure, on the next call, opens the breaker, and
    the retry after it is never made."""
    changes: list[str] = []
    model = ProviderSimulator(FakeBackend(), _failures(6))
    client = _client(model, _breaker(tmp_path, changes))
    with pytest.raises(UnrecoverableFault):
        client.complete("extract", MESSAGES, ExtractResult, **CALL)
    with pytest.raises(CircuitOpen, match="circuit open on gemini-3.5-flash-lite until"):
        client.complete("extract", MESSAGES, ExtractResult, **CALL)
    assert model.calls == 5, "the attempt after the fifth failure is not made"
    failures, until = _breaker(tmp_path).state(PRIMARY)
    assert failures == 5 and until is not None
    assert [c.split(" after ")[0] for c in changes] == [f"breaker opened on {PRIMARY}"]


def test_fi01_clean_control_four_failures_and_a_success_keep_it_closed(tmp_path: Path) -> None:
    model = ProviderSimulator(FakeBackend(), _failures(4))
    client = _client(model, _breaker(tmp_path))
    with pytest.raises(UnrecoverableFault):
        client.complete("extract", MESSAGES, ExtractResult, **CALL)
    assert client.complete("extract", MESSAGES, ExtractResult, **CALL).parsed is not None
    assert _breaker(tmp_path).state(PRIMARY) == (0, None), "an answer resets the count"
    assert client.complete("extract", MESSAGES, ExtractResult, **CALL).parsed is not None


def test_the_breaker_survives_a_new_client(tmp_path: Path) -> None:
    opened = _breaker(tmp_path)
    for _ in range(5):
        opened.failure(PRIMARY)
    backend = FakeBackend()
    with pytest.raises(CircuitOpen):
        _client(backend, _breaker(tmp_path)).complete("extract", MESSAGES, ExtractResult, **CALL)
    assert backend.requests == []


def test_an_open_breaker_moves_the_call_to_the_fallback_model(tmp_path: Path) -> None:
    opened = _breaker(tmp_path)
    for _ in range(5):
        opened.failure(PRIMARY)
    entries: list[LedgerEntry] = []
    client = _client(FakeBackend(), _breaker(tmp_path), fallback=True)
    client.on_ledger = entries.append
    answered = client.complete("extract", MESSAGES, ExtractResult, **CALL)
    assert answered.model == "gemini-3.1-flash-lite"
    assert entries[0].retry_reasons == ["circuit"]


def test_the_breaker_closes_after_its_cooldown(tmp_path: Path) -> None:
    clock = [datetime(2026, 11, 4, 10, 0, tzinfo=UTC)]
    changes: list[str] = []
    breaker = _breaker(tmp_path, changes, now=lambda: clock[0])
    for _ in range(5):
        breaker.failure(PRIMARY)
    with pytest.raises(CircuitOpen, match="until 2026-11-04T10:30:00Z"):
        breaker.check(PRIMARY, "gemini-3.5-flash-lite")
    clock[0] += timedelta(minutes=30)
    breaker.check(PRIMARY, "gemini-3.5-flash-lite")
    assert breaker.state(PRIMARY) == (0, None)
    assert changes[-1] == f"breaker closed on {PRIMARY}: its cooldown ended"


def _no_minute_wait() -> Config:
    """The configuration with the free tier's per-minute limit raised: a run whose repairs and
    coverage rounds pass 15 calls would otherwise wait a minute on the limiter."""
    config = load_config()
    gemini = config.limits.providers["gemini"]
    free = {m: q.model_copy(update={"rpm": 4000}) for m, q in gemini.tiers["free"].items()}
    tiers = {**gemini.tiers, "free": free}
    providers = {**config.limits.providers, "gemini": gemini.model_copy(update={"tiers": tiers})}
    limits = config.limits.model_copy(update={"providers": providers})
    return config.model_copy(update={"limits": limits})


def _run(tmp_path: Path, model: Backend, **kwargs: Any) -> RunResult:
    arguments: dict[str, Any] = {
        "config": _no_minute_wait(),
        "docling_mode": "replay",
        "source": DEV_RFP,
        "profile": "free",
        "outputs": tmp_path / "out",
        "backends": fake_backends(model),
        "run_id": "run",
        **kwargs,
    }
    return execute(**arguments)


def test_an_open_breaker_with_no_fallback_pauses_the_run_and_paid_resumes_it(
    tmp_path: Path,
) -> None:
    opened = CircuitBreaker(load_config().limits.breaker)  # the test's breaker folder
    for _ in range(5):
        opened.failure(PRIMARY)
    paused = _run(tmp_path, RuleBackend(), fallback=False)
    assert paused.status == "QUOTA_PAUSED"
    assert paused.reason is not None
    assert paused.reason.startswith("circuit open on gemini-3.5-flash-lite until ")
    assert "quota resets" not in paused.reason
    resumed = _run(tmp_path, RuleBackend(), fallback=False, profile="paid", resume=True)
    assert resumed.status == "COMPLETED", "the paid tier has a breaker of its own"


# --- dead letters -----------------------------------------------------------------------------


def _letters(run_dir: Path) -> list[tuple[str, str, str, int, str | None]]:
    return [
        (d.id, d.node, d.call_id, d.attempts, d.manifest)
        for d in read_dead_letters(run_dir / "dead_letter.jsonl")
    ]


def test_fi02_a_rejected_context_pack_leaves_one_dead_letter(tmp_path: Path) -> None:
    """B01's first reading and its repair are both malformed, so the pack is rejected; the
    coverage loop then extracts its passages again, and the run completes."""
    broken = [{"call": 2, "fault": "malformed_json"}, {"call": 3, "fault": "malformed_json"}]
    result = _run(tmp_path, ProviderSimulator(RuleBackend(), broken))
    assert result.status == "COMPLETED", result.reason
    letters = _letters(result.run_dir)
    assert letters == [("DL-001", "extract", "B01", 2, "context/extract-B01.json")]
    assert (result.run_dir / "context" / "extract-B01.json").is_file()
    recovery = [e for e in read_events(result.run_dir / "events.jsonl") if e.kind == "recovery"]
    assert [(e.node, e.detail.split(":")[0]) for e in recovery] == [("extract", "DL-001")]


def test_fi02_clean_control_a_well_formed_pack_leaves_none(tmp_path: Path) -> None:
    result = _run(tmp_path, RuleBackend())
    assert result.status == "COMPLETED", result.reason
    assert _letters(result.run_dir) == []


def test_a_cluster_that_fell_back_leaves_one(tmp_path: Path) -> None:
    result = _run(tmp_path, ScriptedRun("consolidate", block=False))
    assert result.status == "DEGRADED", result.reason
    assert _letters(result.run_dir) == [
        ("DL-001", "consolidate", "RG-002", 2, "context/consolidate-RG-002.json")
    ]


def test_a_resumed_run_adds_no_dead_letter(tmp_path: Path) -> None:
    """The pack is rejected again when the resumed run starts from the beginning, since a
    malformed answer is never journaled; its call id already has its letter."""
    broken = [{"call": 2, "fault": "malformed_json"}, {"call": 3, "fault": "malformed_json"}]
    done = _run(tmp_path, ProviderSimulator(RuleBackend(), broken))
    (done.run_dir / "checkpoints.sqlite").unlink()
    manifest = json.loads((done.run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    manifest["status"] = "RUNNING"
    (done.run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    again = [{"call": 1, "fault": "malformed_json"}, {"call": 2, "fault": "malformed_json"}]
    resumed = _run(tmp_path, ProviderSimulator(RuleBackend(), again), resume=True)
    assert resumed.status == "COMPLETED", resumed.reason
    assert _letters(done.run_dir) == [("DL-001", "extract", "B01", 2, "context/extract-B01.json")]
    stored = RunManifest.model_validate_json(
        (done.run_dir / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert [c.status for c in stored.status_history][-2:] == ["RUNNING", "COMPLETED"]


def test_dead_letters_are_written_once_per_call_id(tmp_path: Path) -> None:
    first = DeadLetters(tmp_path)
    assert first.add("extract", "B04", "malformed output after repair", 2, None) is not None
    assert first.add("extract", "B04", "malformed output after repair", 2, None) is None
    again = DeadLetters(tmp_path)
    assert again.add("extract", "B04", "malformed output after repair", 2, None) is None
    letter = again.add("consolidate", "RG-003", "malformed output twice", 2, None)
    assert letter is not None and letter.id == "DL-002"
