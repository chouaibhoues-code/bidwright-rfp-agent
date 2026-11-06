"""`bidwright-eval`: score frozen runs against gold. It never changes a run.

bidwright-eval score <run_dir>       prints the scorecard and writes evals/results/runs/<run>/
bidwright-eval gate <run_dir> --baseline evals/baselines/<rfp>.json
                                     applies config/thresholds.yaml; exits 1 on a block
bidwright-eval baseline <run_dir>    writes the run's scores, with the gold hash they were
                                     scored against, to evals/baselines/<rfp>.json
bidwright-eval explain <run_dir> <gold_id>
                                     shows what happened to one gold item in the run
bidwright-eval report <matrix>       scores every run of outputs/matrices/<matrix>/ and
                                     writes evals/results/<matrix>/ with each rung's decision
bidwright-eval phoenix <run_dir>     scores the run and sends the scorecard's headline lines to
                                     its Phoenix trace as annotations (ADR-053)
bidwright-eval techcheck [--repeats 5] [--profile free|paid]
                                     judges each technology seed of the hero gold in research
                                     mode pack, and writes evals/results/techcheck/ (step 16)
bidwright-eval spotcheck --runs DIR [DIR ...] --n 10 --seed INT
                                     draws assessments for the owner to label, into
                                     evals/labels/assess_spotcheck.jsonl; with --score, reports
                                     the share labeled right (CH-93)
bidwright-eval hash-gold             records the hashes of the gold files and of
                                     evals/hypotheses.yaml in evals/gold/MANIFEST.sha256
bidwright-eval external crackedpdfs --data <folder>
                                     runs guard's PDF scan on the CrackedPDFs test split,
                                     kept outside the repository, and writes only the scores
                                     to evals/results/external/crackedpdfs.md
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

from bidwright.config import load_config
from evals.explain import explain
from evals.gates import gate
from evals.report import report
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


def _techcheck(args: argparse.Namespace) -> int:
    from bidwright.cli import load_env
    from bidwright.llm.client import default_backends
    from evals.techcheck import judge_seeds, tech_seeds
    from evals.techcheck import report as tech_report

    seeds = tech_seeds()
    if not seeds:
        print("The hero gold holds no technology seeds; they arrive with gold v4 (step 15).")
        return 1
    load_env(ROOT / ".env")
    results = judge_seeds(
        seeds,
        repeats=args.repeats,
        profile=args.profile,
        mode="live",
        backends=default_backends(paid=args.profile == "paid"),
    )
    out = tech_report(results, args.repeats)
    print((out / "report.md").read_text(encoding="utf-8"), end="")
    return 0 if json.loads((out / "report.json").read_text(encoding="utf-8"))["passed"] else 1


def _spotcheck(args: argparse.Namespace) -> int:
    from evals import spotcheck

    labels = args.labels or spotcheck.LABELS
    try:
        if args.score:
            result = spotcheck.score(labels)
            share = result["share_right"]
            print(
                f"{result['right']} of {result['labeled']} labeled assessments right"
                + (f" ({share:.0%})" if share is not None else "")
                + f"; {result['rows'] - result['labeled']} not labeled yet"
            )
            for run in result["runs"]:
                try:
                    joint = score_run(Path(run)).get("joint_error")
                except (LookupError, OSError, ValueError) as exc:
                    print(f"  {run}: joint error not scored ({exc})")
                    continue
                print(f"  {run}: joint error {'not run' if joint is None else joint}")
            return 0
        if not args.runs or args.seed is None:
            print("A draw names --runs and --seed.", file=sys.stderr)
            return 2
        path = spotcheck.write(spotcheck.draw(args.runs, args.n, args.seed), labels)
    except spotcheck.SpotcheckRefused as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {path}: set each owner_label to right or wrong, then run --score")
    return 0


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
    matrix = sub.add_parser("report", help="score a matrix's runs and decide each rung")
    matrix.add_argument("matrix", help="the matrix name, as in outputs/matrices/<matrix>/")
    sub.add_parser("hash-gold", help="freeze the current gold files' hashes")
    tech = sub.add_parser("techcheck", help="judge each technology seed in research mode pack")
    tech.add_argument("--repeats", type=int, default=5)
    tech.add_argument("--profile", choices=["free", "paid"], default="free")
    spot = sub.add_parser("spotcheck", help="draw assessments to label, or score the labels")
    spot.add_argument("--runs", type=Path, nargs="+", default=[], help="run folders")
    spot.add_argument("--n", type=int, default=10)
    spot.add_argument("--seed", type=int, help="the random seed of the draw")
    spot.add_argument("--score", action="store_true", help="report the owner's labels")
    spot.add_argument("--labels", type=Path, default=None, help=argparse.SUPPRESS)
    phoenix = sub.add_parser("phoenix", help="score a run and send its scores to its trace")
    phoenix.add_argument("run_dir", type=Path)
    external = sub.add_parser("external", help="run one stage against a public benchmark")
    external.add_argument("benchmark", choices=["crackedpdfs"])
    external.add_argument(
        "--data", type=Path, required=True, help="the benchmark's folder, outside the repository"
    )
    args = parser.parse_args(argv)
    if args.command == "hash-gold":
        print(f"wrote {hash_gold()}")
        return 0
    if args.command == "external":
        from evals.external import crackedpdfs  # the PDF stack, for this command only

        try:
            out, failed = crackedpdfs.run(args.data)
        except crackedpdfs.BenchmarkRefused as exc:
            print(exc, file=sys.stderr)
            return 1
        print(out.read_text(encoding="utf-8"), end="")
        return 1 if failed else 0
    if args.command == "techcheck":
        return _techcheck(args)
    if args.command == "spotcheck":
        return _spotcheck(args)
    if args.command == "report":
        out = report(args.matrix)
        print((out / "report.md").read_text(encoding="utf-8"), end="")
        print(f"results: {out}")
        return 0
    if args.command == "explain":
        try:
            print(explain(args.run_dir, args.gold_id), end="")
        except LookupError as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0
    scores = score_run(args.run_dir)
    if args.command == "phoenix":
        from bidwright.preflight import Refused
        from evals.phoenix import push_scores

        try:
            count, url = push_scores(args.run_dir, scores)
        except Refused as exc:
            print(f"Refused: {exc}", file=sys.stderr)
            return 2
        print(f"Sent {count} score annotations to Phoenix" + (f": {url}" if url else ""))
        return 0
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
