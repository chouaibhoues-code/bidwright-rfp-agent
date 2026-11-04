"""The `bidwright` command line.

    bidwright run <file> [--profile free|local] [--baseline ex0]
                         [--allow-non-corpus=i-accept-free-tier-terms]
    bidwright demo       replays a recorded development run; needs no keys
    bidwright record <file> [--name demo]   runs live and writes cassettes, on the host

The command line parses arguments and prints what the run entry refuses. The rules themselves
sit at the run entry, in `preflight.py`: on `free`, a file is refused unless its hash is
listed in `inputs/CORPUS.sha256`, because the free tier's terms let the provider use prompt
content. Your own files belong on `--profile local`; the override exists for informed use,
and the run manifest logs it.
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
RECORDING = "recording.json"  # which profile and input a cassette folder was recorded from


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bidwright", description="Bidwright: RFP to proposal.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run one RFP live")
    run.add_argument("file", type=Path)
    run.add_argument("--profile", choices=["free", "local"], default="free")
    run.add_argument("--baseline", choices=sorted(BASELINES))
    run.add_argument("--allow-non-corpus", dest="consent", metavar="CONSENT")
    run.add_argument("--outputs", type=Path, default=HOME / "outputs")
    demo = sub.add_parser("demo", help="replay the recorded development run, with no keys")
    demo.add_argument("--outputs", type=Path, default=HOME / "outputs")
    record = sub.add_parser("record", help="run live and record cassettes, on the host")
    record.add_argument("file", type=Path)
    record.add_argument("--name", default="demo")
    record.add_argument("--profile", choices=["free", "local"], default="free")
    record.add_argument("--outputs", type=Path, default=HOME / "outputs")
    args = parser.parse_args(argv)

    os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
    load_env(HOME / ".env")
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
            )
        else:
            result = execute(
                source=args.file,
                profile=args.profile,
                outputs=args.outputs,
                backends=default_backends(paid=args.profile == "paid"),
                baseline=args.baseline,
                consent=args.consent,
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
            "run_id": result.run_id,
            "status": result.status,
        }
        (CASSETTES / args.name / RECORDING).write_text(
            json.dumps(recording, indent=1) + "\n", encoding="utf-8", newline="\n"
        )
    return _report(result)


if __name__ == "__main__":
    raise SystemExit(main())
