"""FI-01 and FI-02 offline: backoff, Retry-After, fallback, malformed output and missing ids."""

import json
from typing import Any

import pytest

from bidwright.config import load_config
from bidwright.llm.client import LLMClient
from bidwright.llm.simulator import ProviderSimulator
from bidwright.llm.types import Message, QuotaExhausted, UnrecoverableFault
from bidwright.schemas import ExtractResult, RiskRegister
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


def test_fi01_timeouts_back_off_with_full_jitter_under_the_cap() -> None:
    sleeps: list[float] = []
    script = [{"call": 1, "fault": "timeout"}, {"call": 2, "fault": "server_error"}]
    completion = _client(script, sleeps).complete("extract", MESSAGES, ExtractResult, **CALL)
    assert completion.retries == 2
    assert sleeps == [0.5 * 2, 0.5 * 4]  # rng 0.5 times a 2 s base, doubled per retry


def test_fi01_exhausted_retries_switch_extract_to_its_fallback_model() -> None:
    inner = FakeBackend()
    script = [{"call": n, "fault": "timeout"} for n in range(1, 5)]
    completion = _client(script, [], inner).complete("extract", MESSAGES, ExtractResult, **CALL)
    assert completion.model == "gemini-3.1-flash-lite"
    assert inner.models == ["gemini-3.1-flash-lite"]


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
    assert completion.retries == 0 and inner.models == ["gemini-3.1-flash-lite"]


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
