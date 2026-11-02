"""The ledger: one `LedgerEntry` per LLM call, and the run totals derived from it.

The run manifest's `totals` are computed here from the same entries that `ledger.jsonl`
holds, so the two always agree. Cost is real spend on paid calls only; the shadow cost
prices every call at the paid list rate of the role's shadow model.
"""

from collections.abc import Sequence
from pathlib import Path

from bidwright.schemas import LedgerEntry, RunTotals


def totals_of(ledger: Sequence[LedgerEntry], active_seconds: float) -> RunTotals:
    return RunTotals(
        requests=len(ledger),
        tokens_in=sum(e.tokens_in for e in ledger),
        tokens_out=sum(e.tokens_out for e in ledger),
        tokens_cached=sum(e.tokens_cached for e in ledger),
        tokens_thinking=sum(e.tokens_thinking for e in ledger),
        cost_usd=round(sum(e.cost_usd for e in ledger), 8),
        shadow_cost_usd=round(sum(e.shadow_cost_usd for e in ledger), 8),
        active_seconds=round(active_seconds, 3),
    )


def read_ledger(path: Path) -> list[LedgerEntry]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [LedgerEntry.model_validate_json(line) for line in lines if line.strip()]
