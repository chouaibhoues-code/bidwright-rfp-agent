"""`bidwright-eval`: score frozen runs against gold. It never changes a run.

bidwright-eval score <run_dir>   prints the 0a scorecard and writes evals/results/runs/<run>/
bidwright-eval hash-gold         records the gold files' hashes in evals/gold/MANIFEST.sha256
"""

import argparse
import hashlib
from pathlib import Path

from evals.score import GOLD_DIR, score_run, scorecard, write_results


def hash_gold(gold_dir: Path = GOLD_DIR) -> Path:
    manifest = gold_dir / "MANIFEST.sha256"
    lines = []
    for path in sorted(gold_dir.glob("*/gold.jsonl")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(gold_dir).as_posix()}\n")
    manifest.write_text("".join(lines), encoding="utf-8", newline="\n")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bidwright-eval", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    score = sub.add_parser("score", help="score one run folder")
    score.add_argument("run_dir", type=Path)
    sub.add_parser("hash-gold", help="freeze the current gold files' hashes")
    args = parser.parse_args(argv)
    if args.command == "hash-gold":
        print(f"wrote {hash_gold()}")
        return 0
    scores = score_run(args.run_dir)
    print(scorecard(scores), end="")
    print(f"results: {write_results(scores)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
