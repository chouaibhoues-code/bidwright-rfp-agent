"""S-01: how much of the hero package's gold text survives parsing, with each PDF parser.

For each PDF parser, Docling and pdfplumber, the hero package runs through `guard` and `ingest`
as a B0 run stopped after `verify`: no model call, and Docling's responses replayed from
`tests/cassettes/docling/`, so the spike needs no key, no network and no Docling service. The
XLSX annex goes through Docling in both runs, as `config/ingest.yaml` sets. Each gold clause is
then searched in the run's frozen text, inside its own document, after whitespace
normalization, as the matcher does. Pass mark: Docling stays the PDF parser when at least 98%
of the clauses are located; otherwise `parsers.pdf: pdfplumber` is set and DR-04, the parser
comparison, is launched.

Run with `uv run python -m evals.spikes.s01_parse_fidelity`. It scores against gold, so it
refuses to run until gold v2's hash is recorded. Results go to
`evals/results/s01-parse-fidelity/`.
"""

import json
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import bidwright.graph.build as build
from bidwright.config import load_config
from bidwright.schemas import Passage
from evals.matcher import gold_clauses
from evals.score import GOLD_DIR, find_gold

ROOT = Path(__file__).resolve().parents[2]
HERO = ROOT / "inputs" / "hero"
RESULTS = ROOT / "evals" / "results" / "s01-parse-fidelity"
PASS_MARK = 0.98
PARSERS = ("docling", "pdfplumber")


def _parse(parser: str, outputs: Path) -> Path:
    """The hero package's frozen text and passages, with this PDF parser."""
    config = load_config()
    config.ingest.parsers.pdf = parser  # type: ignore[assignment]
    original = build.load_config
    build.load_config = lambda: config  # type: ignore[assignment]
    try:
        result = build.execute(
            source=HERO,
            profile="free",
            outputs=outputs,
            mode="live",
            backends={},
            baseline="b0",
            docling_mode="replay",
            run_id=f"s01-{parser}",
        )
    finally:
        build.load_config = original  # type: ignore[assignment]
    if result.status not in ("COMPLETED", "DEGRADED"):
        raise SystemExit(f"{parser}: the run ended {result.status}: {result.reason}")
    return result.run_dir


def _located(run_dir: Path, lines: list[dict[str, Any]]) -> dict[str, Any]:
    frozen = (run_dir / "frozen.txt").read_text(encoding="utf-8")
    passages = [
        Passage.model_validate_json(line)
        for line in (run_dir / "passages.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    clauses = [c for c in gold_clauses(lines, frozen, passages) if not c.hidden]
    found = [c for c in clauses if c.span is not None]
    by_document = Counter(c.doc_id for c in clauses)
    found_by_document = Counter(c.doc_id for c in found)
    return {
        "clauses": len(clauses),
        "located": len(found),
        "share": round(len(found) / len(clauses), 4) if clauses else None,
        "by_document": {
            doc: f"{found_by_document[doc]}/{total}" for doc, total in sorted(by_document.items())
        },
        "not_located": sorted(c.gold_id for c in clauses if c.span is None),
    }


def main() -> int:
    gold = find_gold("hero", GOLD_DIR, "hero")
    results: dict[str, Any] = {"gold": f"hero v{gold.version} {gold.sha256[:12]}"}
    with tempfile.TemporaryDirectory() as tmp:
        for parser in PARSERS:
            results[parser] = _located(_parse(parser, Path(tmp)), gold.lines)
    share = results["docling"]["share"] or 0.0
    results["decision"] = (
        "Docling stays the PDF parser"
        if share >= PASS_MARK
        else "set parsers.pdf: pdfplumber and launch DR-04"
    )
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "report.json").write_text(
        json.dumps(results, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    lines = [
        "# S-01: parse fidelity on the hero package",
        "",
        f"Gold {results['gold']}. The share of visible gold clauses found in the frozen text,"
        " inside their own document, after whitespace normalization.",
        "",
        "| PDF parser | Located | Share | By document | Not located |",
        "|---|---|---|---|---|",
    ]
    for parser in PARSERS:
        r = results[parser]
        documents = ", ".join(f"{doc} {count}" for doc, count in r["by_document"].items())
        missing = " ".join(r["not_located"]) or "none"
        lines.append(
            f"| {parser} | {r['located']} of {r['clauses']} | {r['share']:.1%} | {documents}"
            f" | {missing} |"
        )
    lines += ["", f"Pass mark: {PASS_MARK:.0%} for Docling. Decision: {results['decision']}."]
    (RESULTS / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
