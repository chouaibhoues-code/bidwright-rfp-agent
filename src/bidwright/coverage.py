"""`coverage`: the closure check after `verify`, and the rounds that re-extract its gaps
(Iteration 1, step 12).

A gap is a passage whose candidate-ledger row holds no accepted item and is `UNACCOUNTED`, or
`REJECTED`: the model never accounted for it, or every item citing it failed its checks. After
each `verify`:
- with no gaps, the stop reason is `closed`;
- otherwise, once `max_rounds` rounds have run, it is `max_rounds`;
- otherwise, if the gaps did not shrink since the last round, it is `no_shrink`;
- otherwise the gaps go back to `extract` as packs of `gap_pack_size` passages with their
  neighbors, whose call ids continue the `B` numbering, and `verify` runs again over every
  outcome, each passage taking its entries from the latest round that answered for it.
The report goes to `coverage.json`, and any gap left at the end marks the run `DEGRADED` with
"coverage: N passages without a disposition". Code only: the rounds call `extract` again,
never a model of their own.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from bidwright.schemas import CandidateRow, CoverageReport, CoverageRound, StopReason

ACCEPTED = frozenset({"BINDING", "OPTIONAL", "BACKGROUND", "NOT_BINDING", "OUT_OF_SCOPE"})


def _unaccounted(row: CandidateRow) -> bool:
    return set(row.dispositions) == {"UNACCOUNTED"}


def _rejected_only(row: CandidateRow) -> bool:
    kinds = set(row.dispositions)
    return "REJECTED" in kinds and not kinds & ACCEPTED


def gap_ids(rows: Sequence[CandidateRow]) -> list[str]:
    """The passages with no disposition yet, in reading order."""
    return [row.src_id for row in rows if _unaccounted(row) or _rejected_only(row)]


@dataclass
class CoverageStep:
    """What one `coverage` pass decided: re-extract `gaps`, or stop with `report`."""

    rounds: list[CoverageRound]
    gaps: list[str] = field(default_factory=list)
    report: CoverageReport | None = None  # set when the loop stops


def next_step(
    rows: Sequence[CandidateRow],
    rounds: Sequence[CoverageRound],
    current: int,
    max_rounds: int,
) -> CoverageStep:
    """Decide after the `verify` of round `current` (0 for the first pass). `rounds` holds the
    re-extraction rounds so far, the last one being `current` when it is 1 or more."""
    gaps = gap_ids(rows)
    done = [round_.model_copy() for round_ in rounds]
    if current >= 1 and done:
        sent = done[-1].gaps
        done[-1] = done[-1].model_copy(update={"resolved": [s for s in sent if s not in gaps]})
    stop: StopReason | None = None
    if not gaps:
        stop = "closed"
    elif current >= max_rounds:
        stop = "max_rounds"
    elif current >= 1 and len(gaps) >= len(done[-1].gaps):
        stop = "no_shrink"
    if stop is None:
        done.append(CoverageRound(round=current + 1, gaps=gaps))
        return CoverageStep(rounds=done, gaps=gaps)
    report = CoverageReport(
        rounds=done,
        stop_reason=stop,
        passages=len(rows),
        with_disposition=len(rows) - len(gaps),
        unaccounted=sum(1 for row in rows if _unaccounted(row)),
        rejected_only=sum(1 for row in rows if _rejected_only(row)),
    )
    return CoverageStep(rounds=done, report=report)


def degraded_reason(report: CoverageReport) -> str | None:
    """The run's shortfall when gaps remain at the end."""
    left = report.passages - report.with_disposition
    return f"coverage: {left} passages without a disposition" if left else None


def write_report(run_dir: Path, report: CoverageReport) -> None:
    """`coverage.json`; `coverage` is its only writer."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "coverage.json").write_text(
        report.model_dump_json(indent=1) + "\n", encoding="utf-8", newline="\n"
    )


__all__ = ["CoverageStep", "degraded_reason", "gap_ids", "next_step", "write_report"]
