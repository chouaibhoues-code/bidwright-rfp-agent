"""`bidwright-eval techcheck --repeats 5 --profile P`: `techcheck`'s verdict accuracy on the
technology seeds (Iteration 3, step 16; design section 4.13).

Each technology seed of the hero gold becomes one `LIBRARY` claim, judged by `techcheck`'s own
code in research mode `pack`: the library pack's excerpts for the claim, one `assess`-role
call through `graph/single.py`, and code's check of the verdict's quote. The calls go to
`outputs/single/techcheck-<profile>/`, each repeat with its own index, so repeats never share a
cassette. The Master-Plan's rule: each false seed `INVALIDATED` in at least 4 of 5 repeats
(80%, rounded up), and no true seed ever `INVALIDATED`. The report goes to
`evals/results/techcheck/`.
"""

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bidwright.config import Config, compile_patterns, load_config
from bidwright.graph.single import single_context
from bidwright.graph.techcheck import Sources, techcheck
from bidwright.llm.client import Backend, Mode
from bidwright.llm.replay import CassetteStore
from bidwright.research.pack import library_pack_path, load_library_pack
from bidwright.schemas import SolutionManifest, TechClaim
from evals.score import GOLD_DIR, ROOT, find_gold

RESULTS = ROOT / "evals" / "results" / "techcheck"
FALSE_SHARE = 0.8  # a false seed is INVALIDATED in at least this share of its repeats


@dataclass
class SeedVerdicts:
    seed: str
    library: str
    holds: bool
    verdicts: list[str] = field(default_factory=list)

    @property
    def invalidated(self) -> int:
        return self.verdicts.count("INVALIDATED")

    def passed(self, repeats: int) -> bool:
        if self.holds:
            return self.invalidated == 0
        return self.invalidated >= math.ceil(FALSE_SHARE * repeats)


def tech_seeds(gold_dir: Path = GOLD_DIR) -> list[dict[str, Any]]:
    gold = find_gold("hero-rfp", gold_dir, "hero")
    return [line for line in gold.lines if line["kind"] == "tech_seed"]


def judge_seeds(
    seeds: Sequence[Mapping[str, Any]],
    *,
    repeats: int,
    profile: str,
    mode: Mode,
    backends: dict[str, Backend] | None = None,
    cassettes: CassetteStore | None = None,
    outputs: Path | None = None,
    config: Config | None = None,
) -> list[SeedVerdicts]:
    config = config or load_config()
    path = library_pack_path(config.research.packs_dir)
    patterns = compile_patterns(config.ingest.suspect_patterns, "config/ingest.yaml")
    pack = load_library_pack(path, patterns) if path.is_dir() else None
    sources = Sources("pack", library_pack=pack, questions=config.research.questions)
    chars = config.limits.context.chars_per_token * 4500
    results = [SeedVerdicts(s["gold_id"], s["library"], bool(s["holds"])) for s in seeds]
    for repeat in range(repeats):
        ctx = single_context(
            f"techcheck-{profile}",
            profile=profile,
            mode=mode,
            backends=backends,
            cassettes=cassettes,
            repeat=repeat,
            outputs=outputs,
            config=config,
        )
        for seed, result in zip(seeds, results, strict=True):
            claim = TechClaim(
                id="TC-01", text=seed["text"], library=seed["library"], kind="LIBRARY"
            )
            outcome = techcheck(
                ctx,
                SolutionManifest(tech_claims=[claim]),
                sources,
                cap=1,
                max_chars=chars,
            )
            result.verdicts.append(outcome.validations[0].verdict)
    return results


def report(results: Sequence[SeedVerdicts], repeats: int, out: Path = RESULTS) -> Path:
    rows = [
        {
            "seed": r.seed,
            "library": r.library,
            "holds": r.holds,
            "verdicts": r.verdicts,
            "invalidated": r.invalidated,
            "passed": r.passed(repeats),
        }
        for r in results
    ]
    data = {
        "repeats": repeats,
        "rule": f"a false seed INVALIDATED in at least {math.ceil(FALSE_SHARE * repeats)} of"
        f" {repeats} repeats, and no true seed ever INVALIDATED",
        "passed": bool(rows) and all(row["passed"] for row in rows),
        "seeds": rows,
    }
    out.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=1) + "\n"
    (out / "report.json").write_text(text, encoding="utf-8", newline="\n")
    lines = [
        "# techcheck on the technology seeds",
        "",
        f"Rule: {data['rule']}. Result: {'pass' if data['passed'] else 'fail'}.",
        "",
        "| Seed | Library | Holds | INVALIDATED | Verdicts | Result |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['seed']} | {row['library']} | {row['holds']} | {row['invalidated']}"
            f" | {', '.join(row['verdicts'])} | {'pass' if row['passed'] else 'fail'} |"
        )
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return out


__all__ = ["SeedVerdicts", "judge_seeds", "report", "tech_seeds"]
