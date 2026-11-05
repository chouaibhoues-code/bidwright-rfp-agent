"""The run budget: requests, tokens and active time, per run.

Limits come from `config/limits.yaml` by RFP and profile. Only live calls count: a replayed
call spends nothing. The request limit counts provider attempts, retries and the fallback
model's attempts included, because that is what a provider's quota counts (ADR-022): the
client calls `attempt` before each one, which checks every limit and then counts it, so the
count is exact between retries, and a call that fails on every model still spent its attempts.
Tokens are counted from the ledger entry after the call. The clock runs only while the run is
`RUNNING`, so time waiting for a person or a quota never counts. Going over a limit raises
`BudgetExceeded`, and the run stops in `BUDGET_EXCEEDED`.

A run's limits hold across all its parts (ADR-031). `snapshot` gives the counts and raises that
the supervisor keeps in `control/budget.json`, and `restore` takes them back on a resume.
`raise_by(percent)`, from `bidwright resume --raise-budget PERCENT`, adds
`ceil(limit × percent / 100)` to each configured limit; raises add up across resumes, and each
is computed on the configured value, so the order of resumes never changes the result.
"""

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from bidwright.config import RunLimits
from bidwright.schemas import BudgetSnapshot, LedgerEntry


class BudgetExceeded(Exception):
    """The run must stop in `BUDGET_EXCEEDED`. The message names the limit."""

    status = "BUDGET_EXCEEDED"


@dataclass
class RunBudget:
    limits: RunLimits
    clock: Callable[[], float] = time.monotonic
    requests: int = 0
    tokens: int = 0
    raise_percent: int = 0
    _active: float = 0.0
    _since: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _configured: RunLimits = field(init=False)

    def __post_init__(self) -> None:
        self._configured = self.limits

    @property
    def active_seconds(self) -> float:
        running = self.clock() - self._since if self._since is not None else 0.0
        return self._active + running

    def start(self) -> None:
        """The run enters `RUNNING`."""
        if self._since is None:
            self._since = self.clock()

    def pause(self) -> None:
        """The run leaves `RUNNING`, to wait or to stop."""
        if self._since is not None:
            self._active += self.clock() - self._since
            self._since = None

    def check(self) -> None:
        """Raises if any limit is already reached."""
        if self.requests >= self.limits.requests:
            raise BudgetExceeded(f"request limit of {self.limits.requests} reached")
        if self.tokens >= self.limits.tokens:
            raise BudgetExceeded(f"token limit of {self.limits.tokens} reached")
        if self.active_seconds >= self.limits.active_minutes * 60:
            raise BudgetExceeded(
                f"active-time limit of {self.limits.active_minutes} minutes reached"
            )

    def attempt(self) -> None:
        """Called before each provider attempt: check every limit, then count the attempt."""
        with self._lock:
            self.check()
            self.requests += 1

    def record(self, entry: LedgerEntry) -> None:
        """Count a finished call's tokens from the ledger; its attempts were counted as made."""
        if entry.replayed:
            return
        with self._lock:
            self.tokens += entry.tokens_in + entry.tokens_out + entry.tokens_thinking

    def raise_by(self, percent: int) -> None:
        """Raise every limit by `percent` of its configured value, rounded up."""
        if percent <= 0:
            raise ValueError(f"a budget raise is a positive percentage, not {percent}")
        with self._lock:
            self.raise_percent += percent
            self.limits = _raised(self._configured, self.raise_percent)

    def snapshot(self) -> BudgetSnapshot:
        with self._lock:
            return BudgetSnapshot(
                attempts=self.requests,
                tokens=self.tokens,
                active_seconds=round(self.active_seconds, 3),
                raise_percent=self.raise_percent,
            )

    def restore(self, snapshot: BudgetSnapshot) -> None:
        """Take back a stored snapshot's counts and re-apply its raises, before a resume."""
        with self._lock:
            self.requests = snapshot.attempts
            self.tokens = snapshot.tokens
            self._active = snapshot.active_seconds
            self.raise_percent = snapshot.raise_percent
            self.limits = _raised(self._configured, self.raise_percent)


def _raised(configured: RunLimits, percent: int) -> RunLimits:
    """The configured limits, each raised by `ceil(limit × percent / 100)`."""
    if percent == 0:
        return configured
    return RunLimits(
        requests=configured.requests + math.ceil(configured.requests * percent / 100),
        tokens=configured.tokens + math.ceil(configured.tokens * percent / 100),
        active_minutes=configured.active_minutes
        + math.ceil(configured.active_minutes * percent / 100),
    )
