"""The limiter, on a fake clock: per-minute waits, the daily allowance kept on disk by quota
day, the move to the fallback model, and separate counts per tier."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import bidwright.llm.limits
from bidwright.config import LimitsConfig, ModelQuota, ProviderLimits, load_config
from bidwright.llm.client import LLMClient
from bidwright.llm.limits import Limiter, daily_allowance, tier_for
from bidwright.llm.replay import CassetteStore
from bidwright.llm.simulator import ProviderSimulator
from bidwright.llm.types import Message, QuotaExhausted
from bidwright.preflight import HOME
from bidwright.schemas import ExtractResult
from tests.llm_fakes import CALL, FakeBackend

PRIMARY, FALLBACK = "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"
MESSAGES = [Message("system", "Extract obligations."), Message("user", "passages")]
NOON = datetime(2026, 11, 4, 20, 0, tzinfo=UTC)  # 12:00 in Los Angeles


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _limits(
    rpm: int = 15, tpm: int = 250_000, rpd: int = 500, reserve: float = 0.2
) -> LimitsConfig:
    quota = ModelQuota(rpm=rpm, tpm=tpm, rpd=rpd, reserve=reserve)
    paid = quota.model_copy(update={"reserve": 0.0})
    tiers = {
        "free": {PRIMARY: quota, FALLBACK: quota},
        "paid": {PRIMARY: paid, FALLBACK: paid},
    }
    providers = {"gemini": ProviderLimits(quota_day_tz="America/Los_Angeles", tiers=tiers)}
    return load_config().limits.model_copy(update={"providers": providers})


def _limiter(
    root: Path, limits: LimitsConfig, tier: str = "free", at: datetime = NOON
) -> tuple[Limiter, FakeClock]:
    clock = FakeClock()
    return Limiter(limits, tier, root, clock=clock, sleep=clock.sleep, now=lambda: at), clock


def test_a_request_waits_for_the_per_minute_window(tmp_path: Path) -> None:
    limiter, clock = _limiter(tmp_path, _limits(rpm=2))
    for _ in range(2):
        limiter.acquire("gemini", PRIMARY, 100)
    assert clock.slept == []
    limiter.acquire("gemini", PRIMARY, 100)
    assert clock.now == pytest.approx(60.0), "the third request waits for the first to leave"
    tokens, tclock = _limiter(tmp_path / "tokens", _limits(tpm=1000))
    tokens.acquire("gemini", PRIMARY, 600)
    tclock.now = 10.0
    tokens.acquire("gemini", PRIMARY, 300)
    tokens.acquire("gemini", PRIMARY, 300)
    assert tclock.now == pytest.approx(60.0), "1,200 tokens wait for the first 600 to leave"
    alone, aclock = _limiter(tmp_path / "alone", _limits(tpm=1000))
    alone.acquire("gemini", PRIMARY, 5000)
    assert aclock.slept == [], "a request over the whole limit goes when the window is empty"


def test_the_daily_reserve_raises_before_any_call(tmp_path: Path) -> None:
    limits = _limits(rpd=10, reserve=0.2)
    assert daily_allowance(limits.providers["gemini"].tiers["free"][PRIMARY]) == 8
    limiter, _ = _limiter(tmp_path, limits)
    for _ in range(8):
        limiter.acquire("gemini", PRIMARY, 10)
    with pytest.raises(QuotaExhausted, match="8 of 8"):
        limiter.acquire("gemini", PRIMARY, 10)
    backend = FakeBackend()
    for model in (PRIMARY, FALLBACK):
        _spend(limiter, model)
    client = LLMClient(load_config(), "free", {"gemini": backend}, limiter=limiter)
    with pytest.raises(QuotaExhausted):
        client.complete("extract", MESSAGES, ExtractResult, **CALL)
    assert backend.requests == [], "no request reaches the provider"


def test_an_observed_daily_count_never_stops_a_call(tmp_path: Path) -> None:
    """With `daily: observe`, the count runs past the allowance, and the provider's own
    daily 429 decides when calls stop (ADR-029)."""
    observed = ModelQuota(rpm=15, tpm=250_000, rpd=10, reserve=0.2, daily="observe")
    limits = _limits(rpd=10)
    limits.providers["gemini"].tiers["free"][PRIMARY] = observed
    limiter, _ = _limiter(tmp_path, limits)
    for _ in range(12):
        limiter.acquire("gemini", PRIMARY, 10)
    assert limiter.count("gemini", PRIMARY) == 12, "past the allowance of 8, still counted"


def _spend(limiter: Limiter, model: str) -> None:
    path = limiter.path("gemini", model)
    path.parent.mkdir(parents=True, exist_ok=True)
    quota = limiter.limits.quota_for("gemini", limiter.tier, model)
    assert quota is not None
    path.write_text(json.dumps({"requests": daily_allowance(quota)}), encoding="utf-8")


def test_the_count_survives_a_new_limiter_on_the_same_day(tmp_path: Path) -> None:
    first, _ = _limiter(tmp_path, _limits())
    for _ in range(3):
        first.acquire("gemini", PRIMARY, 10)
    path = tmp_path / f"gemini-free-{PRIMARY}-2026-11-04.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body == {
        "provider": "gemini",
        "tier": "free",
        "model": PRIMARY,
        "day": "2026-11-04",
        "requests": 3,
        "tokens": 0,  # kept for rows with a tpd (ADR-045)
    }
    late = datetime(2026, 11, 5, 7, 59, tzinfo=UTC)  # 23:59 on Nov 4 in Los Angeles
    same_day, _ = _limiter(tmp_path, _limits(), at=late)
    assert same_day.count("gemini", PRIMARY) == 3
    next_day, _ = _limiter(tmp_path, _limits(), at=datetime(2026, 11, 5, 8, 1, tzinfo=UTC))
    assert next_day.count("gemini", PRIMARY) == 0, "the quota day starts at Pacific midnight"
    next_day.acquire("gemini", PRIMARY, 10)
    assert (tmp_path / f"gemini-free-{PRIMARY}-2026-11-05.json").exists()


def test_a_spent_primary_moves_to_the_fallback_and_a_spent_fallback_raises(
    tmp_path: Path,
) -> None:
    limiter, _ = _limiter(tmp_path, _limits())
    _spend(limiter, PRIMARY)
    backend = FakeBackend()
    client = LLMClient(load_config(), "free", {"gemini": backend}, limiter=limiter)
    completion = client.complete("extract", MESSAGES, ExtractResult, **CALL)
    assert backend.models == [FALLBACK] and completion.model == FALLBACK
    assert completion.retries == 1, "the refused attempt counts, as ADR-022 counts it"
    assert limiter.count("gemini", FALLBACK) == 1
    _spend(limiter, FALLBACK)
    with pytest.raises(QuotaExhausted, match=FALLBACK):
        client.complete("extract", MESSAGES, ExtractResult, **CALL)
    assert backend.models == [FALLBACK]


def test_the_paid_tier_keeps_its_own_count(tmp_path: Path) -> None:
    free, _ = _limiter(tmp_path, _limits(rpd=10))
    paid, _ = _limiter(tmp_path, _limits(rpd=10), tier="paid")
    for _ in range(3):
        free.acquire("gemini", PRIMARY, 10)
    assert paid.count("gemini", PRIMARY) == 0
    for _ in range(10):
        paid.acquire("gemini", PRIMARY, 10)  # no reserve on the paid tier
    assert (free.count("gemini", PRIMARY), paid.count("gemini", PRIMARY)) == (3, 10)
    assert tier_for("paid") == "paid" and tier_for("free") == tier_for("local") == "free"


def test_every_attempt_counts_and_a_model_without_a_row_is_not_limited(tmp_path: Path) -> None:
    limiter, _ = _limiter(tmp_path, _limits())
    flaky = ProviderSimulator(FakeBackend(), [{"call": 1, "fault": "timeout"}])
    client = LLMClient(
        load_config(), "free", {"gemini": flaky}, limiter=limiter, sleep=lambda _: None
    )
    client.complete("extract", MESSAGES, ExtractResult, **CALL)
    assert limiter.count("gemini", PRIMARY) == 2, "the retry is a second request"
    limiter.acquire("ollama", "qwen3.5:4b", 10**9)
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"gemini-free-{PRIMARY}-2026-11-04.json"]


def test_replayed_calls_skip_the_limiter(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path / "cassettes")
    recorder = LLMClient(
        load_config(), "free", {"gemini": FakeBackend()}, mode="record", cassettes=store
    )
    recorder.complete("extract", MESSAGES, ExtractResult, **CALL)
    limiter, _ = _limiter(tmp_path / "quota", _limits())
    _spend(limiter, PRIMARY)
    _spend(limiter, FALLBACK)
    replay = LLMClient(load_config(), "free", mode="replay", cassettes=store, limiter=limiter)
    assert replay.complete("extract", MESSAGES, ExtractResult, **CALL).replayed


def test_the_default_folder_is_under_home_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()  # drop the test-wide isolation of conftest.py, to read the real default
    assert bidwright.llm.limits.QUOTA_DIR == HOME / "outputs" / ".quota"
    assert Limiter(load_config().limits, "free").root == bidwright.llm.limits.QUOTA_DIR


CEREBRAS_MODEL = "gpt-oss-120b"


def _trial(tpd: int = 10_000, reserve: float = 0.0) -> LimitsConfig:
    """One Cerebras row under a single tier, as the trial account's limits give it."""
    quota = ModelQuota(rpm=5, tpm=30_000, rpd=7200, tpd=tpd, reserve=reserve)
    providers = {
        "cerebras": ProviderLimits(quota_day_tz="UTC", tiers={"trial": {CEREBRAS_MODEL: quota}})
    }
    return load_config().limits.model_copy(update={"providers": providers})


def test_a_tpd_cap_stops_a_call_once_the_days_tokens_are_spent(tmp_path: Path) -> None:
    limiter, _ = _limiter(tmp_path, _trial(tpd=10_000))
    limiter.acquire("cerebras", CEREBRAS_MODEL, 100)
    limiter.record_usage("cerebras", CEREBRAS_MODEL, 9_999)
    limiter.acquire("cerebras", CEREBRAS_MODEL, 100)
    limiter.record_usage("cerebras", CEREBRAS_MODEL, 1)
    assert limiter.tokens("cerebras", CEREBRAS_MODEL) == 10_000
    again, _ = _limiter(tmp_path, _trial(tpd=10_000))  # a new process reads the same count
    with pytest.raises(QuotaExhausted, match="10000 of 10000 tokens"):
        again.acquire("cerebras", CEREBRAS_MODEL, 100)
    assert again.count("cerebras", CEREBRAS_MODEL) == 2


def test_a_provider_with_one_tier_counts_once_on_every_profile(tmp_path: Path) -> None:
    free, _ = _limiter(tmp_path, _trial(), tier="free")
    paid, _ = _limiter(tmp_path, _trial(), tier="paid")
    assert free.path("cerebras", CEREBRAS_MODEL) == paid.path("cerebras", CEREBRAS_MODEL)
    assert "cerebras-trial-gpt-oss-120b" in free.path("cerebras", CEREBRAS_MODEL).name
    free.acquire("cerebras", CEREBRAS_MODEL, 10)
    paid.acquire("cerebras", CEREBRAS_MODEL, 10)
    assert paid.count("cerebras", CEREBRAS_MODEL) == 2


def test_a_count_file_from_before_iteration_3_reads_zero_tokens(tmp_path: Path) -> None:
    limiter, _ = _limiter(tmp_path, _trial())
    path = limiter.path("cerebras", CEREBRAS_MODEL)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"requests": 3}), encoding="utf-8")
    assert (
        limiter.count("cerebras", CEREBRAS_MODEL),
        limiter.tokens("cerebras", CEREBRAS_MODEL),
    ) == (3, 0)


def test_a_row_without_tpd_keeps_no_tokens(tmp_path: Path) -> None:
    limiter, _ = _limiter(tmp_path, _limits())
    limiter.acquire("gemini", PRIMARY, 100)
    limiter.record_usage("gemini", PRIMARY, 5_000)
    assert limiter.tokens("gemini", PRIMARY) == 0


def test_the_client_reports_each_answers_tokens_to_the_limiter(tmp_path: Path) -> None:
    limiter, _ = _limiter(tmp_path, _trial(tpd=1_000_000))
    config = load_config()
    config = config.model_copy(update={"limits": _trial(tpd=1_000_000)})
    client = LLMClient(
        config, "free", {"cerebras": FakeBackend(provider="cerebras")}, limiter=limiter
    )
    client.complete("assess", MESSAGES, ExtractResult, **CALL)
    assert limiter.tokens("cerebras", CEREBRAS_MODEL) == 1200, "1,000 in and 200 out"
