"""G3's pass rates on the outbound test set (Iteration 2, step 6; ADR-032).

    uv run python scripts/outbound_rates.py

Runs the outbound overlap rule over `tests/data/outbound_cases.yaml`, with the set's own
passages as the run's passages, and prints the share of verbatim copies, edited copies and
paraphrases it lets through. Every verbatim copy must be denied, which `tests/test_gateway.py`
checks; the other two shares are reported at the tag (step 15), since a rule on consecutive
words reduces the chance that RFP text leaks out through a query but cannot stop a paraphrase.
"""

import sys
from pathlib import Path
from typing import Any

import yaml

from bidwright.harness.rules import RuleContext
from bidwright.schemas import Passage

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "data" / "outbound_cases.yaml"
VARIANTS = ("passage", "edited", "paraphrase")


def load_cases(path: Path = CASES) -> list[dict[str, Any]]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["cases"]


def context_for(cases: list[dict[str, Any]]) -> RuleContext:
    """A rule context whose passages are the set's verbatim passages."""
    passages = [
        Passage(
            id=f"SRC-{number:04d}",
            doc_id=str(case["id"]).split("-")[0],
            section_path="",
            kind="sentence",
            text=case["passage"],
            start=0,
            end=len(case["passage"]),
        )
        for number, case in enumerate(cases, start=1)
    ]
    return RuleContext(passages)


def pass_rates(cases: list[dict[str, Any]]) -> dict[str, float]:
    """The share of each variant that G3 lets through."""
    context = context_for(cases)
    return {
        variant: sum(context.overlap(case[variant]) is None for case in cases) / len(cases)
        for variant in VARIANTS
    }


def main() -> int:
    cases = load_cases()
    rates = pass_rates(cases)
    print(f"G3 on {len(cases)} passages of the synthetic corpus, the share let through:")
    print(f"  verbatim copies: {rates['passage']:.0%} (must be 0%)")
    print(f"  edited copies, about one word in ten replaced: {rates['edited']:.0%}")
    print(f"  paraphrases written by hand: {rates['paraphrase']:.0%}")
    return 0 if rates["passage"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
