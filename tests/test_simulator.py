"""FI-01 and FI-02 offline: backoff, Retry-After, fallback, malformed output and missing ids,
and the run budget seen from the client: attempts counted, and a stop between attempts."""

import json
from typing import Any

import pytest

from bidwright.config import RunLimits, load_config
from bidwright.harness.budget import BudgetExceeded, RunBudget
from bidwright.llm.client import LLMClient
from bidwright.llm.simulator import ProviderSimulator
from bidwright.llm.types import Message, QuotaExhausted, UnrecoverableFault
from bidwright.schemas import ExtractResult, LedgerEntry, RiskRegister
from tests.llm_fakes import CALL, FakeBackend

MESSAGES = [Message("user", "passages")]


def _client(
    script: list[dict[str, Any]], sleeps: list[float], inner: FakeBackend | None = None
) -> LLMClient:
    backend = ProviderSimulator(inner or FakeBackend(), script)
    return LLMClient(
        load_config(), "free", {"gemini": backend}, sleep=sleeps.append, rng=lambda: 0.5
    )


def test_fi01_backoff_honors_retry_after() -> None:
    sleeps: list[float] = []
    client = _client([{"call": 1, "fault": "http_429", "retry_after_s": 1}], sleeps)
    completion = client.complete("extract", MESSAGES, ExtractResult, **CALL)
    assert completion.retries == 1 and sleeps == [1]
    assert completion.retry_reasons == ("rate_limited",)


def test_fi01_timeouts_back_off_with_full_jitter_under_the_cap() -> None:
    sleeps: list[float] = []
    script = [{"call": 1, "fault": "timeout"}, {"call": 2, "fault": "server_error"}]
    completion = _client(script, sleeps).complete("extract", MESSAGES, ExtractResult, **CALL)
    assert completion.retries == 2 and completion.retry_reasons == ("timeout", "server_error")
    assert sleeps == [0.5 * 2, 0.5 * 4]  # rng 0.5 times a 2 s base, doubled per retry


def test_fi01_exhausted_retries_switch_extract_to_its_fallback_model() -> None:
    inner = FakeBackend()
    script = [{"call": n, "fault": "timeout"} for n in range(1, 5)]
    completion = _client(script, [], inner).complete("extract", MESSAGES, ExtractResult, **CALL)
    assert completion.model == "gemini-3.1-flash-lite"
    assert inner.models == ["gemini-3.1-flash-lite"]
    # Four attempts on the primary and one on the fallback: the ledger sees all five.
    assert completion.retries == 4 and completion.retry_reasons == ("timeout",) * 4


def test_fi01_reason_falls_back_to_its_own_flash_lite_model() -> None:
    inner = FakeBackend()
    script = [{"call": n, "fault": "timeout"} for n in range(1, 5)]
    completion = _client(script, [], inner).complete("reason", MESSAGES, RiskRegister, **CALL)
    assert completion.model == "gemini-3.1-flash-lite"


def test_fi01_a_role_without_a_fallback_fails_unrecoverably() -> None:
    config = load_config()
    reason = config.models.role("free", "reason").model_copy(update={"fallback": None})
    config.models.profiles["free"]["reason"] = reason
    backend = ProviderSimulator(
        FakeBackend(), [{"call": n, "fault": "timeout"} for n in range(1, 5)]
    )
    client = LLMClient(config, "free", {"gemini": backend}, sleep=lambda _: None, rng=lambda: 0.5)
    with pytest.raises(UnrecoverableFault):
        client.complete("reason", MESSAGES, RiskRegister, **CALL)


def test_a_spent_daily_quota_moves_to_the_fallback_without_retrying() -> None:
    sleeps: list[float] = []
    inner = FakeBackend()
    client = _client([{"call": 1, "fault": "quota_exhausted"}], sleeps, inner)
    completion = client.complete("extract", MESSAGES, ExtractResult, **CALL)
    assert completion.model == "gemini-3.1-flash-lite" and sleeps == []
    # No backoff, but the refused attempt on the primary still counts as one.
    assert completion.retries == 1 and inner.models == ["gemini-3.1-flash-lite"]
    assert completion.retry_reasons == ("quota",)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_the_budget_stops_a_call_between_its_attempts() -> None:
    """The budget is checked before every provider attempt, not only before the call."""
    clock = Clock()
    budget = RunBudget(RunLimits(requests=60, tokens=300_000, active_minutes=1), clock=clock)
    budget.start()
    backend = ProviderSimulator(FakeBackend(), [{"call": n, "fault": "timeout"} for n in (1, 2)])

    def backoff(_: float) -> None:
        clock.now += 61  # one backoff takes the run past its active-time limit

    client = LLMClient(
        load_config(),
        "free",
        {"gemini": backend},
        before_attempt=budget.attempt,
        sleep=backoff,
        rng=lambda: 0.5,
    )
    with pytest.raises(BudgetExceeded, match="active-time"):
        client.complete("extract", MESSAGES, ExtractResult, **CALL)
    assert backend.calls == 1  # the second attempt never reached the provider


def test_the_request_limit_counts_each_attempt_as_it_is_made() -> None:
    """Retries spend requests before any ledger entry exists, so the limit stops them."""
    budget = RunBudget(RunLimits(requests=2, tokens=300_000, active_minutes=20))
    budget.start()
    backend = ProviderSimulator(FakeBackend(), [{"call": n, "fault": "timeout"} for n in (1, 2, 3)])
    client = LLMClient(
        load_config(),
        "free",
        {"gemini": backend},
        before_attempt=budget.attempt,
        sleep=lambda _: None,
        rng=lambda: 0.5,
    )
    with pytest.raises(BudgetExceeded, match="request limit"):
        client.complete("extract", MESSAGES, ExtractResult, **CALL)
    assert backend.calls == 2 and budget.requests == 2


def test_a_spent_quota_with_no_fallback_left_stops_with_quota_exhausted() -> None:
    script = [{"call": 1, "fault": "quota_exhausted"}, {"call": 2, "fault": "quota_exhausted"}]
    with pytest.raises(QuotaExhausted):
        _client(script, []).complete("extract", MESSAGES, ExtractResult, **CALL)


def test_fi02_malformed_output_is_reported_for_repair() -> None:
    client = _client([{"call": 1, "fault": "malformed_json"}], [])
    completion = client.complete("extract", MESSAGES, ExtractResult, **CALL)
    assert completion.parsed is None and completion.parse_error


def test_fi02_missing_ids_drop_the_items_that_cite_them() -> None:
    client = _client([{"call": 1, "fault": "missing_ids", "drop": ["SRC-0003"]}], [])
    completion = client.complete("extract", MESSAGES, ExtractResult, **CALL)
    assert isinstance(completion.parsed, ExtractResult)
    cited = {src for item in completion.parsed.items for src in item.src_ids}
    assert "SRC-0003" not in cited and "SRC-0001" in cited
    assert json.loads(completion.text)["no_obligation_src_ids"] == ["SRC-0002"]


def test_unknown_faults_are_rejected() -> None:
    with pytest.raises(ValueError, match="unknown faults"):
        ProviderSimulator(FakeBackend(), [{"call": 1, "fault": "gremlins"}])


def test_the_ledger_says_why_each_attempt_was_retried() -> None:
    entries: list[LedgerEntry] = []
    script = [{"call": 1, "fault": "http_429"}, {"call": 2, "fault": "timeout"}]
    client = LLMClient(
        load_config(),
        "free",
        {"gemini": ProviderSimulator(FakeBackend(), script)},
        on_ledger=entries.append,
        sleep=lambda _: None,
        rng=lambda: 0.5,
    )
    client.complete("extract", MESSAGES, ExtractResult, **CALL)
    assert [(e.retries, e.retry_reasons) for e in entries] == [(2, ["rate_limited", "timeout"])]
    earlier = entries[0].model_dump(exclude={"retry_reasons"})
    assert LedgerEntry.model_validate(earlier).retry_reasons == [], "older ledgers still load"


def test_without_fallback_a_spent_quota_or_exhausted_retries_stay_on_the_primary() -> None:
    """Matrix runs pass fallback=False, so no call is answered by a second model."""
    quota = ProviderSimulator(FakeBackend(), [{"call": 1, "fault": "quota_exhausted"}])
    client = LLMClient(load_config(), "free", {"gemini": quota}, fallback=False)
    with pytest.raises(QuotaExhausted):
        client.complete("extract", MESSAGES, ExtractResult, **CALL)
    inner = FakeBackend()
    timeouts = ProviderSimulator(inner, [{"call": n, "fault": "timeout"} for n in range(1, 5)])
    client = LLMClient(
        load_config(), "free", {"gemini": timeouts}, fallback=False, sleep=lambda _: None
    )
    with pytest.raises(UnrecoverableFault):
        client.complete("extract", MESSAGES, ExtractResult, **CALL)
    assert inner.models == [], "the fallback model was never called"
