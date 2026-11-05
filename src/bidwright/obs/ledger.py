"""The ledger: one `LedgerEntry` per LLM call, and the run totals derived from it.

The run manifest's `totals` are computed here from the same entries that `ledger.jsonl`
holds, so the two always agree. Cost is real spend on paid calls only; the shadow cost
prices every call at the paid list rate of the role's shadow model.

From Iteration 2 (ADR-031), `LedgerFile` appends each entry to `ledger.jsonl` as its call
finishes, so a killed run keeps its ledger. A kill can cut the last line short of its newline;
`read_ledger` and `LedgerFile.load` skip such a line, and `repair` cuts it off before a resumed
run appends.
"""

from collections.abc import Sequence
from pathlib import Path

from bidwright.fileio import read_lines, repair_lines
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


def models_used(ledger: Sequence[LedgerEntry]) -> dict[str, list[str]]:
    """The models that answered, by node: a run that fell back lists both models."""
    found: dict[str, set[str]] = {}
    for entry in ledger:
        found.setdefault(entry.node, set()).add(entry.model)
    return {node: sorted(models) for node, models in sorted(found.items())}


def read_ledger(path: Path) -> list[LedgerEntry]:
    """The entries of a ledger file, without a last line that a kill cut short."""
    if not path.exists():
        raise FileNotFoundError(path)
    return [LedgerEntry.model_validate_json(line) for line in read_lines(path)]


class LedgerFile:
    """A run's `ledger.jsonl`, written one line per finished call. `RunContext` appends under
    its thread lock, so the `Send` workers' lines never interleave."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def create(self) -> None:
        """An empty ledger, written when a run starts."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8", newline="\n")

    def repair(self) -> str:
        """Cut a last line that a kill left without its newline, and return the text cut."""
        return repair_lines(self.path)

    def append(self, entry: LedgerEntry) -> None:
        """Write one entry as one line, flushed before the call that made it returns."""
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(entry.model_dump_json() + "\n")
            stream.flush()

    def load(self) -> list[LedgerEntry]:
        return read_ledger(self.path)


__all__ = ["LedgerFile", "models_used", "read_ledger", "totals_of"]
