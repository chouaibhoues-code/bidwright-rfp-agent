"""The limiter: a provider's published rate limits, applied before every live attempt
(Iteration 1, step 9).

`LLMClient` calls `Limiter.acquire` in `_obtain`, after the run budget's `before_attempt`, with
the model and the request's estimated input tokens, so the budget and the limiter both apply
and every provider attempt counts, as ADR-022 counts it. Replayed and cached calls skip it.

A limit is keyed by provider, tier (`free` or `paid`, from the profile) and model, from the
`providers` block of `config/limits.yaml`; a provider or model with no row there, such as
Ollama, is not limited. The limiter keeps the request times and input tokens of the last 60
seconds in memory and waits until the per-minute limits allow an attempt. It keeps the day's
request count in `outputs/.quota/<provider>-<tier>-<model>-<YYYY-MM-DD>.json` under
`HOME / "outputs"`, whatever `--outputs` says, because a quota belongs to the account rather
than to an output folder. The date is the provider's quota day, in its `quota_day_tz`. With
`daily: enforce`, once the day's count reaches the daily limit less the reserve, `acquire`
raises `QuotaExhausted`, which moves the call to its fallback model, whose limit is counted
separately; when both are spent, the run ends `QUOTA_PAUSED`. With `daily: observe`, the count
is kept but never stops a call: the provider's own daily 429, which the adapter turns into the
same `QuotaExhausted`, decides (ADR-029). The per-minute limits always apply.

Iteration 3 (ADR-045) adds two things. A row may set `tpd`, the tokens a day: `record_usage`,
which the client calls after each answer, adds the input, output and thinking tokens the
provider reported to the day's count file, and `acquire` stops a call once the day's tokens
reach `tpd` less the reserve, with `daily: enforce`. And a provider whose limits have one tier
only, such as Cerebras's trial, is counted under that tier on every profile, since one account
holds one quota whatever the profile.

Step 19 adds a row's `max_completion_tokens`: a provider that charges the output ceiling to its
per-minute token limit before a call runs, as Cerebras does, gets that ceiling on every live
request, and the client asks `acquire` for the estimated input tokens plus the ceiling, so the
per-minute pacing counts what the provider counts.
"""

import json
import math
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bidwright.config import LimitsConfig, ModelQuota
from bidwright.fileio import write_atomic
from bidwright.llm.types import QuotaExhausted
from bidwright.preflight import HOME

QUOTA_DIR = HOME / "outputs" / ".quota"
WINDOW_S = 60.0
_EXPIRED = 1e-9  # slack when comparing clock readings, so an entry due now has left


def tier_for(profile: str) -> str:
    """The limits tier of a profile: `paid` runs under the paid key, everything else free."""
    return "paid" if profile == "paid" else "free"


def model_key(provider: str, tier: str, model: str) -> str:
    """A model on a provider and tier, as its quota counts and its circuit breaker name it."""
    return f"{provider}-{tier}-{model}"


def daily_allowance(quota: ModelQuota) -> int:
    """The requests a day may spend: the daily limit less the reserve kept free."""
    return math.floor(quota.rpd * (1 - quota.reserve) + _EXPIRED)


def daily_token_allowance(quota: ModelQuota) -> int | None:
    """The tokens a day may spend, when the row sets `tpd`: the cap less the reserve."""
    if quota.tpd is None:
        return None
    return math.floor(quota.tpd * (1 - quota.reserve) + _EXPIRED)


def _wait(window: deque[tuple[float, int]], now: float, quota: ModelQuota, tokens: int) -> float:
    """Seconds until one more attempt of `tokens` fits both per-minute limits."""
    while window and window[0][0] + WINDOW_S <= now + _EXPIRED:
        window.popleft()
    wait = 0.0
    if len(window) >= quota.rpm:
        wait = window[len(window) - quota.rpm][0] + WINDOW_S - now
    used = sum(count for _, count in window)
    if window and used + tokens > quota.tpm:
        # Wait for the oldest entries to leave until the attempt fits, or for all of them,
        # since an attempt larger than the whole limit can only go alone.
        due = window[-1][0]
        for moment, count in window:
            used -= count
            if used + tokens <= quota.tpm:
                due = moment
                break
        wait = max(wait, due + WINDOW_S - now)
    return max(wait, 0.0)


class Limiter:
    def __init__(
        self,
        limits: LimitsConfig,
        tier: str,
        root: Path | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.limits = limits
        self.tier = tier
        self.root = root if root is not None else QUOTA_DIR
        self._clock = clock
        self._sleep = sleep
        self._now = now
        self._windows: dict[tuple[str, str], deque[tuple[float, int]]] = {}
        self._lock = threading.Lock()

    def quota_day(self, provider: str) -> date:
        """Today, in the provider's quota time zone."""
        zone = ZoneInfo(self.limits.providers[provider].quota_day_tz)
        return self._now().astimezone(zone).date()

    def path(self, provider: str, model: str, day: date | None = None) -> Path:
        """The count file of one model on this tier, for `day` or today."""
        day = day or self.quota_day(provider)
        tier = self.limits.quota_tier(provider, self.tier)
        name = f"{model_key(provider, tier, model)}-{day.isoformat()}.json"
        return self.root / name.replace("/", "_").replace(":", "_")

    def count(self, provider: str, model: str) -> int:
        """The attempts counted today for one model on this tier."""
        return int(_read(self.path(provider, model))["requests"])

    def tokens(self, provider: str, model: str) -> int:
        """The tokens counted today for one model on this tier."""
        return int(_read(self.path(provider, model))["tokens"])

    def record_usage(self, provider: str, model: str, tokens: int) -> None:
        """Add an answer's reported tokens to today's count, for a row that sets `tpd`."""
        quota = self.limits.quota_for(provider, self.tier, model)
        if quota is None or quota.tpd is None or tokens <= 0:
            return
        with self._lock:
            day = self.quota_day(provider)
            path = self.path(provider, model, day)
            body = _read(path)
            total = body["tokens"] + tokens
            _write(path, self._body(provider, model, day, body["requests"], total))

    def _body(
        self, provider: str, model: str, day: date, requests: int, tokens: int
    ) -> dict[str, object]:
        return {
            "provider": provider,
            "tier": self.limits.quota_tier(provider, self.tier),
            "model": model,
            "day": day.isoformat(),
            "requests": requests,
            "tokens": tokens,
        }

    def acquire(self, provider: str, model: str, tokens: int) -> None:
        """Return once an attempt may go, counting it; on a row with `daily: enforce`, raise
        `QuotaExhausted` when the day's allowance is spent. A row with `daily: observe` only
        counts, and the provider's own daily 429 stops the calls (ADR-029)."""
        quota = self.limits.quota_for(provider, self.tier, model)
        if quota is None:
            return
        allowed = daily_allowance(quota)
        while True:
            with self._lock:
                day = self.quota_day(provider)
                path = self.path(provider, model, day)
                body = _read(path)
                spent = int(body["requests"])
                if quota.daily == "enforce" and spent >= allowed:
                    raise QuotaExhausted(
                        f"{provider} {self.tier} quota for {model} spent today: {spent} of"
                        f" {allowed} requests, with {quota.reserve:.0%} of {quota.rpd} in reserve"
                    )
                used = int(body["tokens"])
                token_allowance = daily_token_allowance(quota)
                if quota.daily == "enforce" and token_allowance is not None:
                    if used >= token_allowance:
                        raise QuotaExhausted(
                            f"{provider} {self.tier} quota for {model} spent today: {used} of"
                            f" {token_allowance} tokens, with {quota.reserve:.0%} of"
                            f" {quota.tpd} in reserve"
                        )
                window = self._windows.setdefault((provider, model), deque())
                now = self._clock()
                wait = _wait(window, now, quota, tokens)
                if wait <= 0:
                    window.append((now, tokens))
                    _write(path, self._body(provider, model, day, spent + 1, used))
                    return
            self._sleep(wait)


def _read(path: Path) -> dict[str, int]:
    """A day's counts; a file written before Iteration 3 holds no `tokens`, which reads 0."""
    if not path.exists():
        return {"requests": 0, "tokens": 0}
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        return {"requests": int(body["requests"]), "tokens": int(body.get("tokens", 0))}
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"{path} is not a quota count file: {exc}") from exc


def _write(path: Path, body: dict[str, object]) -> None:
    """The count, written whole, so a reader never sees half a file."""
    write_atomic(path, json.dumps(body) + "\n")


__all__ = [
    "QUOTA_DIR",
    "Limiter",
    "daily_allowance",
    "daily_token_allowance",
    "model_key",
    "tier_for",
]
