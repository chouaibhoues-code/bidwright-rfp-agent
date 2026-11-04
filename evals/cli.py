"""`bidwright-eval`: score frozen runs against gold. It never changes a run.

bidwright-eval score <run_dir>       prints the scorecard and writes evals/results/runs/<run>/
bidwright-eval gate <run_dir> --baseline evals/baselines/<rfp>.json
                                     applies config/thresholds.yaml; exits 1 on a block
bidwright-eval baseline <run_dir>    writes the run's scores, with the gold hash they were
                                     scored against, to evals/baselines/<rfp>.json
bidwright-eval explain <run_dir> <gold_id>
                                     shows what happened to one gold item in the run
bidwright-eval hash-gold             records the hashes of the gold files and of
                                     evals/hypotheses.yaml in evals/gold/MANIFEST.sha256
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

from bidwright.config import load_config
from evals.explain import explain
from evals.gates import gate
from evals.score import GOLD_DIR, HYPOTHESES_ENTRY, ROOT, score_run, scorecard, write_results

BASELINES = ROOT / "evals" / "baselines"


def hash_gold(gold_dir: Path = GOLD_DIR) -> Path:
    """Freeze the gold and the hypotheses: one `sha256sum` line each, the hypotheses last."""
    manifest = gold_dir / "MANIFEST.sha256"
    lines = []
    for path in sorted(gold_dir.glob("*/gold.jsonl")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(gold_dir).as_posix()}\n")
    hypotheses = gold_dir / HYPOTHESES_ENTRY
    if hypotheses.exists():
        digest = hashlib.sha256(hypotheses.read_bytes()).hexdigest()
        lines.append(f"{digest}  {HYPOTHESES_ENTRY}\n")
    manifest.write_text("".join(lines), encoding="utf-8", newline="\n")
    return manifest


def write_baseline(scores: dict[str, object], out: Path | None = None) -> Path:
    """A copy of the scores, which carry the corpus and the gold hash they were scored
    against, as the baseline the gate compares later runs with."""
    path = out or BASELINES / f"{scores['corpus']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(scores, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bidwright-eval",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    score = sub.add_parser("score", help="score one run folder")
    score.add_argument("run_dir", type=Path)
    check = sub.add_parser("gate", help="gate one run folder against a committed baseline")
    check.add_argument("run_dir", type=Path)
    check.add_argument("--baseline", type=Path, required=True, help="a baseline file")
    baseline = sub.add_parser("baseline", help="write a run's scores as the baseline")
    baseline.add_argument("run_dir", type=Path)
    baseline.add_argument("--out", type=Path, help="default: evals/baselines/<rfp>.json")
    why = sub.add_parser("explain", help="what happened to one gold item in a run")
    why.add_argument("run_dir", type=Path)
    why.add_argument("gold_id")
    sub.add_parser("hash-gold", help="freeze the current gold files' hashes")
    args = parser.parse_args(argv)
    if args.command == "hash-gold":
        print(f"wrote {hash_gold()}")
        return 0
    if args.command == "explain":
        try:
            print(explain(args.run_dir, args.gold_id), end="")
        except LookupError as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0
    scores = score_run(args.run_dir)
    if args.command == "baseline":
        print(f"wrote {write_baseline(scores, args.out)}")
        return 0
    if args.command == "gate":
        reference = json.loads(args.baseline.read_text(encoding="utf-8"))
        result = gate(scores, reference, load_config().thresholds)
        print(result.report(), end="")
        return 1 if result.blocked else 0
    print(scorecard(scores), end="")
    print(f"results: {write_results(scores)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
