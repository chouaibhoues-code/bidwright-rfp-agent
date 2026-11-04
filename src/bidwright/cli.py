"""The `bidwright` command line.

    bidwright run <file or folder> [--profile free|local|paid] [--baseline ex0|b0]
                  [--allow-non-corpus=i-accept-free-tier-terms] [--cache] [--second-pass]
                  [--until NODE] [--outputs DIR]
    bidwright demo       replays a recorded development run; needs no keys
    bidwright record <file or folder> [--name demo] [--until NODE]
                         runs live and writes LLM and Docling cassettes, on the host
    bidwright purge <run> | --expired
                         deletes a run's folder and its cache entries, or every client run
                         past the retention period
    bidwright matrix run <file> [--resume]
                         runs a matrix file's rungs and repeats in order, under
                         outputs/matrices/<name>/

The command line parses arguments and prints what the run entry refuses. The rules themselves
sit at the run entry, in `preflight.py`: on `free`, a file is refused unless its hash is
listed in `inputs/CORPUS.sha256`, because the free tier's terms let the provider use prompt
content. Your own files belong on `--profile local`; the override exists for informed use,
and the run manifest logs it. `paid` runs the same models under `GEMINI_PAID_API_KEY`.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from bidwright.baselines import BASELINES
from bidwright.preflight import HOME, Refused

if TYPE_CHECKING:
    from bidwright.graph.build import RunResult

DEMO_SOURCE = HOME / "inputs" / "dev" / "dev_rfp.pdf"
CASSETTES = HOME / "tests" / "cassettes"
RECORDING = "recording.json"  # which profile, input and stop a cassette folder was recorded from
PROFILES = ["free", "local", "paid"]
UNTIL = ["verify", "coverage", "consolidate", "render"]


def load_env(path: Path) -> None:
    """Read KEY=VALUE lines from `.env` into the environment, never overriding a set variable."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#") and value.strip():
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _report(result: "RunResult") -> int:
    print(f"{result.status}: {result.run_dir}")
    if result.reason:
        print(f"  {result.reason}")
    summary = result.run_dir / "solution_summary.md"
    if summary.exists():
        print(f"  summary: {summary}")
    return 0 if result.status in ("COMPLETED", "DEGRADED") else 1


def _purge(args: argparse.Namespace) -> int:
    from bidwright.config import load_config
    from bidwright.purge import NotARun, outputs_root, purge_expired, purge_run

    if args.expired:
        deleted = purge_expired(load_config().limits.retention.client_days)
    elif args.run:
        candidate = Path(args.run)
        run_dir = candidate if candidate.is_dir() else outputs_root() / args.run
        if not run_dir.is_dir():
            print(f"No run folder {run_dir}", file=sys.stderr)
            return 1
        try:
            deleted = purge_run(run_dir)
        except NotARun as exc:
            print(f"Refused: {exc}", file=sys.stderr)
            return 1
    else:
        print("Name a run, or pass --expired.", file=sys.stderr)
        return 2
    for path in deleted:
        print(f"deleted {path}")
    if not deleted:
        print("Nothing to delete.")
    return 0


def _matrix(args: argparse.Namespace) -> int:
    from bidwright.llm.client import default_backends
    from bidwright.matrix import MatrixRefused, load_matrix, run_matrix

    try:
        paid = load_matrix(args.file).profile == "paid"
        outcome = run_matrix(args.file, resume=args.resume, backends=default_backends(paid=paid))
    except (MatrixRefused, Refused, ValueError, OSError) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    print(f"{outcome.status}: {len(outcome.runs)} runs, ${outcome.spent_usd:g} spent")
    return 0 if outcome.status == "COMPLETED" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bidwright", description="Bidwright: RFP to proposal.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run one RFP file or package folder live")
    run.add_argument("file", type=Path, help="an RFP file, or a folder holding a package")
    run.add_argument("--profile", choices=PROFILES, default="free")
    run.add_argument("--baseline", choices=sorted(BASELINES))
    run.add_argument("--allow-non-corpus", dest="consent", metavar="CONSENT")
    run.add_argument("--cache", action="store_true", help="answer repeated calls from the cache")
    run.add_argument("--second-pass", action="store_true", help="re-read OBLIGATION zones (S-13)")
    run.add_argument("--until", choices=UNTIL, default="render", help="the last node to run")
    run.add_argument("--outputs", type=Path, default=HOME / "outputs")
    demo = sub.add_parser("demo", help="replay the recorded development run, with no keys")
    demo.add_argument("--outputs", type=Path, default=HOME / "outputs")
    record = sub.add_parser("record", help="run live and record cassettes, on the host")
    record.add_argument("file", type=Path, help="an RFP file, or a folder holding a package")
    record.add_argument("--name", default="demo")
    record.add_argument("--profile", choices=PROFILES, default="free")
    record.add_argument("--until", choices=UNTIL, default="render", help="the last node to run")
    record.add_argument("--outputs", type=Path, default=HOME / "outputs")
    purge = sub.add_parser("purge", help="delete a run and its cache entries, or expired runs")
    purge.add_argument("run", nargs="?", help="a run id under outputs/, or a run folder")
    purge.add_argument(
        "--expired", action="store_true", help="every client run past the retention period"
    )
    matrix = sub.add_parser("matrix", help="run a matrix of rungs and repeats")
    matrix_sub = matrix.add_subparsers(dest="matrix_command", required=True)
    matrix_run = matrix_sub.add_parser("run", help="run a matrix file's rungs and repeats")
    matrix_run.add_argument("file", type=Path, help="a matrix file, as in config/matrices/")
    matrix_run.add_argument(
        "--resume", action="store_true", help="skip the runs that finished and go on"
    )
    args = parser.parse_args(argv)

    os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
    load_env(HOME / ".env")
    if args.command == "purge":
        return _purge(args)
    if args.command == "matrix":
        return _matrix(args)
    from bidwright.graph.build import execute
    from bidwright.llm.client import default_backends
    from bidwright.llm.replay import CassetteStore

    if args.command == "demo":
        store = CASSETTES / "demo"
        if not (store / RECORDING).exists():
            print("No demo cassettes. Record them with: bidwright record inputs/dev/dev_rfp.pdf")
            return 1
        recording = json.loads((store / RECORDING).read_text(encoding="utf-8"))
        result = execute(
            source=HOME / recording["source"],
            profile=recording["profile"],
            outputs=args.outputs,
            mode="replay",
            cassettes=CassetteStore(store),
            until=recording.get("until", "render"),
        )
        return _report(result)
    try:
        if args.command == "record":
            store = CASSETTES / args.name
            result = execute(
                source=args.file,
                profile=args.profile,
                outputs=args.outputs,
                mode="record",
                cassettes=CassetteStore(store),
                backends=default_backends(paid=args.profile == "paid"),
                until=args.until,
            )
        else:
            result = execute(
                source=args.file,
                profile=args.profile,
                outputs=args.outputs,
                backends=default_backends(paid=args.profile == "paid"),
                baseline=args.baseline,
                consent=args.consent,
                until=args.until,
                second_pass=args.second_pass,
                cache=args.cache,
            )
    except Refused as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    if args.command == "record" and result.status in ("COMPLETED", "DEGRADED"):
        source = args.file.resolve()
        recording = {
            "profile": args.profile,
            "source": source.relative_to(HOME).as_posix()
            if source.is_relative_to(HOME)
            else str(source),
            "until": args.until,
            "run_id": result.run_id,
            "status": result.status,
        }
        (CASSETTES / args.name / RECORDING).write_text(
            json.dumps(recording, indent=1) + "\n", encoding="utf-8", newline="\n"
        )
    return _report(result)


if __name__ == "__main__":
    raise SystemExit(main())
