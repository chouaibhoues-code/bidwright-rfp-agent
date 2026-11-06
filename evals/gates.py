"""The regression gate: a run's scores against a committed baseline, under the block and warn
tiers of `config/thresholds.yaml`.

At `v0.1` the block tier applies `schema_invalid`, `accepted_quotes_not_verbatim_or_normalized`,
`trap_actions_obeyed`, `unauthorized_tool_calls` and `missed_mandatory_increase` (on
`missed_mandatory_count`). From Iteration 3 (step 14) it also blocks on `seeded_gaps_claimed`,
QS-5's count, which reads `n/a` when the gold holds no gap seed or the run has no claims and
no manifest. The warn
tier applies `f1_drop_points` (F1 from `precision_low`, in percentage points) and
`cost_increase_ratio` (over `shadow_cost_usd`, since `cost_usd` is 0 on `free`);
`captured_gold_jaccard_below` needs repeats and is skipped on one run. A baseline scored on
another corpus or against other gold blocks the comparison, since its counts mean something
else: the baseline is written again on the current gold.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from bidwright.config import ThresholdsConfig

# The block rules that read the run's own count, with no baseline.
COUNTS = (
    "schema_invalid",
    "accepted_quotes_not_verbatim_or_normalized",
    "trap_actions_obeyed",
    "unauthorized_tool_calls",
)


@dataclass(frozen=True)
class Check:
    name: str
    tier: str  # block or warn
    outcome: str  # pass, block, warn, n/a or skipped
    detail: str


@dataclass
class GateResult:
    checks: list[Check] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(c.outcome == "block" for c in self.checks)

    @property
    def warned(self) -> bool:
        return any(c.outcome == "warn" for c in self.checks)

    def report(self) -> str:
        width = max((len(c.name) for c in self.checks), default=0)
        lines = [f"  {c.outcome:<7} {c.name:<{width}}  {c.detail}" for c in self.checks]
        verdict = "BLOCKED" if self.blocked else "PASSED with warnings" if self.warned else "PASSED"
        return "\n".join([f"GATE {verdict}", *lines]) + "\n"


def gate(
    scores: Mapping[str, Any], baseline: Mapping[str, Any], thresholds: ThresholdsConfig
) -> GateResult:
    result = GateResult()
    block, warn = thresholds.block, thresholds.warn
    same_corpus = scores.get("corpus") == baseline.get("corpus")
    same_gold = scores.get("gold_sha256") == baseline.get("gold_sha256")
    if not same_corpus:
        result.checks.append(
            Check(
                "baseline",
                "block",
                "block",
                f"the baseline is for {baseline.get('corpus')}, the run for {scores.get('corpus')}",
            )
        )
    elif not same_gold:
        result.checks.append(
            Check(
                "baseline",
                "block",
                "block",
                "the baseline was scored against other gold; write it again on the current gold",
            )
        )
    comparable = same_corpus and same_gold
    for name in COUNTS:
        limit = block.get(name)
        if limit is None:
            continue
        value = scores.get(name, 0)
        outcome = "block" if value > limit else "pass"
        result.checks.append(Check(name, "block", outcome, f"{value} (limit {limit:g})"))
    limit = block.get("seeded_gaps_claimed")
    if limit is not None:
        value = scores.get("seeded_gaps_claimed")
        gaps = scores.get("gap_seeds") or {}
        if value is None:
            state = gaps.get("state")
            detail = (
                "the gold holds no gap seeds"
                if state == "no gap seeds"
                else "the run has no claims and no manifest"
                if state == "scored"
                else "not scored"
            )
            result.checks.append(Check("seeded_gaps_claimed", "block", "n/a", detail))
        else:
            claimed = sorted(g for g, where in (gaps.get("claimed") or {}).items() if where)
            detail = f"{value} (limit {limit:g})" + (f": {' '.join(claimed)}" if claimed else "")
            outcome = "block" if value > limit else "pass"
            result.checks.append(Check("seeded_gaps_claimed", "block", outcome, detail))
    limit = block.get("missed_mandatory_increase")
    if limit is not None:
        if comparable:
            now, then = scores["missed_mandatory_count"], baseline["missed_mandatory_count"]
            outcome = "block" if now - then > limit else "pass"
            detail = f"{now} missed against {then} in the baseline (limit +{limit:g})"
        else:
            outcome, detail = "skipped", "no comparable baseline"
        result.checks.append(Check("missed_mandatory_increase", "block", outcome, detail))
    limit = warn.get("f1_drop_points")
    if limit is not None:
        now, then = scores.get("f1"), baseline.get("f1")
        if comparable and now is not None and then is not None:
            drop = round((then - now) * 100, 2)
            outcome = "warn" if drop > limit else "pass"
            detail = f"F1 {now:.4f} against {then:.4f}: {drop:g} points (limit {limit:g})"
        else:
            outcome, detail = "skipped", "no comparable F1"
        result.checks.append(Check("f1_drop_points", "warn", outcome, detail))
    limit = warn.get("cost_increase_ratio")
    if limit is not None:
        now, then = scores.get("shadow_cost_usd") or 0.0, baseline.get("shadow_cost_usd") or 0.0
        if comparable and then > 0:
            ratio = round(now / then, 3)
            outcome = "warn" if ratio > limit else "pass"
            detail = f"shadow cost ${now} against ${then}: x{ratio:g} (limit x{limit:g})"
        else:
            outcome, detail = "skipped", "no baseline shadow cost to compare"
        result.checks.append(Check("cost_increase_ratio", "warn", outcome, detail))
    if warn.get("captured_gold_jaccard_below") is not None:
        result.checks.append(
            Check(
                "captured_gold_jaccard_below",
                "warn",
                "skipped",
                "needs repeats; the matrix report applies it",
            )
        )
    return result


__all__ = ["COUNTS", "Check", "GateResult", "gate"]
