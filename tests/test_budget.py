"""The run budget: a run over a limit stops in BUDGET_EXCEEDED, and a raise lets it resume."""

import pytest

from bidwright.config import RunLimits
from bidwright.harness.budget import BudgetExceeded, RunBudget
from bidwright.schemas import LedgerEntry


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _entry(tokens_in: int = 1000, tokens_out: int = 200, replayed: bool = False) -> LedgerEntry:
    return LedgerEntry(
        run_id="run-1",
        node="extract",
        agent="extract",
        provider="gemini",
        model="m",
        prompt_hash="sha256:p",
        input_hash="sha256:i",
        repeat=0,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=10,
        cost_usd=0.0,
        shadow_cost_usd=0.0,
        replayed=replayed,
    )


def test_the_request_limit_stops_the_run() -> None:
    budget = RunBudget(RunLimits(requests=2, tokens=10_000, active_minutes=20))
    for _ in range(2):
        budget.check()
        budget.record(_entry())
    with pytest.raises(BudgetExceeded, match="request limit") as stop:
        budget.check()
    assert stop.value.status == "BUDGET_EXCEEDED"


def test_the_token_limit_counts_input_output_and_thinking() -> None:
    budget = RunBudget(RunLimits(requests=60, tokens=2_000, active_minutes=20))
    budget.record(_entry(tokens_in=1500, tokens_out=400))
    budget.check()
    budget.record(_entry(tokens_in=100, tokens_out=0))
    with pytest.raises(BudgetExceeded, match="token limit"):
        budget.check()


def test_replayed_calls_spend_nothing() -> None:
    budget = RunBudget(RunLimits(requests=1, tokens=10, active_minutes=20))
    budget.record(_entry(replayed=True))
    budget.check()
    assert budget.requests == 0 and budget.tokens == 0


def test_only_running_time_counts() -> None:
    clock = Clock()
    budget = RunBudget(RunLimits(requests=60, tokens=300_000, active_minutes=1), clock=clock)
    budget.start()
    clock.now = 50
    budget.pause()  # waiting for a person
    clock.now = 5_000
    budget.start()
    clock.now = 5_005
    assert budget.active_seconds == 55
    budget.check()
    clock.now = 5_011
    with pytest.raises(BudgetExceeded, match="active-time"):
        budget.check()


def test_raising_the_budget_resumes_and_is_logged() -> None:
    budget = RunBudget(RunLimits(requests=1, tokens=10_000, active_minutes=20))
    budget.record(_entry())
    with pytest.raises(BudgetExceeded):
        budget.check()
    note = budget.raise_limits(requests=5)
    budget.check()
    assert note == "raise-budget: requests 1->5, tokens 10000->10000, active_minutes 20.0->20.0"
    assert budget.raises == [note]
