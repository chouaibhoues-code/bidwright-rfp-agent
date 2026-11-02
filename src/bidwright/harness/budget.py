"""The minimal run budget: requests, tokens and active time, per run.

Limits come from `config/limits.yaml` by RFP and profile. Only live calls count: a replayed
call spends nothing. The clock runs only while the run is `RUNNING`, so time waiting for a
person or a quota never counts. Going over a limit raises `BudgetExceeded`, and the run stops
in `BUDGET_EXCEEDED`, a resumable status: `raise_limits` records the raise for the manifest.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from bidwright.config import RunLimits
from bidwright.schemas import LedgerEntry


class BudgetExceeded(Exception):
    """The run must stop in `BUDGET_EXCEEDED`. The message names the limit."""

    status = "BUDGET_EXCEEDED"


@dataclass
class RunBudget:
    limits: RunLimits
    clock: Callable[[], float] = time.monotonic
    requests: int = 0
    tokens: int = 0
    raises: list[str] = field(default_factory=list)
    _active: float = 0.0
    _since: float | None = None

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
        """Called before each LLM call. Raises if any limit is already reached."""
        if self.requests >= self.limits.requests:
            raise BudgetExceeded(f"request limit of {self.limits.requests} reached")
        if self.tokens >= self.limits.tokens:
            raise BudgetExceeded(f"token limit of {self.limits.tokens} reached")
        if self.active_seconds >= self.limits.active_minutes * 60:
            raise BudgetExceeded(
                f"active-time limit of {self.limits.active_minutes} minutes reached"
            )

    def record(self, entry: LedgerEntry) -> None:
        """Count one finished call from the ledger."""
        if entry.replayed:
            return
        self.requests += 1
        self.tokens += entry.tokens_in + entry.tokens_out + entry.tokens_thinking

    def raise_limits(
        self,
        *,
        requests: int | None = None,
        tokens: int | None = None,
        active_minutes: float | None = None,
    ) -> str:
        """Resume with higher limits. Returns the line the run manifest logs."""
        new = self.limits.model_copy(
            update={
                key: value
                for key, value in {
                    "requests": requests,
                    "tokens": tokens,
                    "active_minutes": active_minutes,
                }.items()
                if value is not None
            }
        )
        note = (
            f"raise-budget: requests {self.limits.requests}->{new.requests},"
            f" tokens {self.limits.tokens}->{new.tokens},"
            f" active_minutes {self.limits.active_minutes}->{new.active_minutes}"
        )
        self.limits = RunLimits.model_validate(new.model_dump())
        self.raises.append(note)
        return note
