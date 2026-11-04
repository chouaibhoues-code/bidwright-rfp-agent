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
"""

import json
import math
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bidwright.config import LimitsConfig, ModelQuota
from bidwright.llm.types import QuotaExhausted
from bidwright.preflight import HOME

QUOTA_DIR = HOME / "outputs" / ".quota"
WINDOW_S = 60.0
_EXPIRED = 1e-9  # slack when comparing clock readings, so an entry due now has left


def tier_for(profile: str) -> str:
    """The limits tier of a profile: `paid` runs under the paid key, everything else free."""
    return "paid" if profile == "paid" else "free"


def daily_allowance(quota: ModelQuota) -> int:
    """The requests a day may spend: the daily limit less the reserve kept free."""
    return math.floor(quota.rpd * (1 - quota.reserve) + _EXPIRED)


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
        name = f"{provider}-{self.tier}-{model}-{day.isoformat()}.json"
        return self.root / name.replace("/", "_").replace(":", "_")

    def count(self, provider: str, model: str) -> int:
        """The attempts counted today for one model on this tier."""
        return _read(self.path(provider, model))

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
                spent = _read(path)
                if quota.daily == "enforce" and spent >= allowed:
                    raise QuotaExhausted(
                        f"{provider} {self.tier} quota for {model} spent today: {spent} of"
                        f" {allowed} requests, with {quota.reserve:.0%} of {quota.rpd} in reserve"
                    )
                window = self._windows.setdefault((provider, model), deque())
                now = self._clock()
                wait = _wait(window, now, quota, tokens)
                if wait <= 0:
                    window.append((now, tokens))
                    body = {
                        "provider": provider,
                        "tier": self.tier,
                        "model": model,
                        "day": day.isoformat(),
                        "requests": spent + 1,
                    }
                    _write(path, body)
                    return
            self._sleep(wait)


def _read(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return int(json.loads(path.read_text(encoding="utf-8"))["requests"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"{path} is not a quota count file: {exc}") from exc


def _write(path: Path, body: dict[str, object]) -> None:
    """The count, written whole, so a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_suffix(".tmp")
    staged.write_text(json.dumps(body) + "\n", encoding="utf-8", newline="\n")
    os.replace(staged, path)


__all__ = ["QUOTA_DIR", "Limiter", "daily_allowance", "tier_for"]
