"""The `bidwright` command line.

    bidwright run <file or folder> [--profile free|local|paid] [--baseline ex0|b0]
                  [--allow-non-corpus=i-accept-free-tier-terms] [--cache]
                  [--second-pass | --no-second-pass] [--until NODE]
                  [--research off|pack|live] [--outputs DIR]
    bidwright demo       replays a recorded development run; needs no keys
    bidwright record <file or folder> [--name demo] [--profile free|local|paid] [--until NODE]
                         [--research off|pack|live] [--fill]
                         runs live and writes LLM and Docling cassettes, on the host; --fill
                         keeps the recording's cassettes, records only the calls it lacks,
                         and removes the ones the run did not use
    bidwright stop <run>  asks a running run to stop when its current step ends
    bidwright resume <run> [--raise-budget PERCENT] [--profile paid]
                         continues a stopped, paused or killed run from its last checkpoint
    bidwright purge <run> | --expired
                         deletes a run's folder and its cache entries, or every client run
                         past the retention period
    bidwright matrix run <file> [--resume]
                         runs a matrix file's rungs and repeats in order, under
                         outputs/matrices/<name>/
    bidwright research pin [--server notebooklm]
                         pins the research server's tools in config/mcp_pins.yaml, on the host
    bidwright research pack --domain ID --title TEXT --keyword WORDS ... --select-for RUN
                            (--run RUN | --notebook ID --job TASK --topic WORDS ...)
                            [--leave-out SOURCE ...] [--profile free|paid]
                         builds research_packs/<domain>/ from a finished live run, or
                         from an existing NotebookLM job in a run of its own, on the host

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
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bidwright.baselines import BASELINES
from bidwright.preflight import HOME, Refused

if TYPE_CHECKING:
    from bidwright.graph.build import RunResult

DEMO_SOURCE = HOME / "inputs" / "dev" / "dev_rfp.pdf"
CONFIG_DIR = HOME / "config"  # where `research pin` writes the pins
CASSETTES = HOME / "tests" / "cassettes"
# Which profile, input, stop and run settings a cassette folder was recorded with.
RECORDING = "recording.json"
DEMO_RECORD = "inputs/dev/dev_rfp.pdf"
PROFILES = ["free", "local", "paid"]
UNTIL = ["verify", "coverage", "consolidate", "brief", "render"]
RESEARCH = ["off", "pack", "live"]  # config/research.yaml sets the default


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


def stale_recording(
    recording: Mapping[str, object], batch_size: int, second_pass: bool
) -> str | None:
    """Why a recording cannot replay under the current settings, or None. The pack size and
    the second pass change which calls a run makes without changing any cassette key, so a
    replay under other values would miss its cassettes."""
    for key, now in (("batch_size", batch_size), ("second_pass", second_pass)):
        if recording.get(key) != now:
            return (
                f"recorded with {key} {recording.get(key)!r}, and config/limits.yaml sets"
                f" {now!r}; record again"
            )
    return None


def _run_folder(name: str) -> Path:
    """A run as `stop`, `resume` and `purge` name it: a run folder, or a run id under
    outputs/."""
    from bidwright.purge import outputs_root

    candidate = Path(name)
    return candidate if candidate.is_dir() else outputs_root() / name


def _purge(args: argparse.Namespace) -> int:
    from bidwright.config import load_config
    from bidwright.purge import NotARun, RunInUse, purge_expired, purge_run

    if args.expired:
        deleted = purge_expired(load_config().limits.retention.client_days)
    elif args.run:
        run_dir = _run_folder(args.run)
        if not run_dir.is_dir():
            print(f"No run folder {run_dir}", file=sys.stderr)
            return 1
        try:
            deleted = purge_run(run_dir)
        except (NotARun, RunInUse) as exc:
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


def _stop(args: argparse.Namespace) -> int:
    """Write the run's stop request, which its supervisor's watcher reads within a second."""
    from bidwright.harness.supervisor import CONTROL, STOP_REQUEST, read_manifest

    run_dir = _run_folder(args.run)
    try:
        manifest = read_manifest(run_dir)
    except Refused as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 1
    if manifest.status != "RUNNING":
        print(f"Refused: the run is {manifest.status}, not RUNNING", file=sys.stderr)
        return 1
    request = run_dir / CONTROL / STOP_REQUEST
    request.parent.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ}"
    request.write_text(stamp + "\n", encoding="utf-8", newline="\n")
    print(f"Stop requested: {run_dir}")
    print("  the run stops when its current step ends; resume it with bidwright resume")
    return 0


def resume_arguments(run_args: Mapping[str, Any], run_dir: Path) -> dict[str, Any]:
    """The arguments of `execute` that a manifest's `run_args` recorded, for a resume of the
    run in `run_dir`. The run's own folder names where it is, whatever `outputs` said."""
    source = Path(str(run_args["source"]))
    keys = (
        "baseline",
        "consent",
        "until",
        "batch_size",
        "second_pass",
        "extract_prompt",
        "research",
        "repeat",
        "cache",
        "docling_mode",
        "fallback",
        "mode",
    )
    return {
        "source": source if source.is_absolute() else HOME / source,
        "outputs": run_dir.parent,
        "run_id": run_dir.name,
        "limits": run_args.get("limits"),
        **{key: run_args[key] for key in keys if key in run_args},
    }


def _resume(args: argparse.Namespace) -> int:
    from bidwright.graph.build import execute
    from bidwright.harness.supervisor import read_manifest
    from bidwright.llm.client import default_backends

    run_dir = _run_folder(args.run)
    try:
        manifest = read_manifest(run_dir)
        if not manifest.run_args:
            raise Refused("this run predates v0.2; start it again")
        if manifest.run_args.get("command") == "research pack":
            raise Refused("a research pack build is not resumed; run bidwright research pack again")
        profile = args.profile or str(manifest.run_args["profile"])
        result = execute(
            **resume_arguments(manifest.run_args, run_dir),
            profile=profile,
            backends=default_backends(paid=profile == "paid"),
            resume=True,
            raise_budget=args.raise_budget,
        )
    except Refused as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    return _report(result)


def _percent(value: str) -> int:
    percent = int(value)
    if percent <= 0:
        raise argparse.ArgumentTypeError(f"a budget raise is a positive percentage, not {value}")
    return percent


def _pin(args: argparse.Namespace) -> int:
    """List the research server's tools and pin the ones research uses. Run on the host,
    with the server started, after its version changes."""
    from bidwright.config import load_config
    from bidwright.research.mcp_client import McpClient, McpError
    from bidwright.research.nlm import SENT
    from bidwright.research.pins import ServerRefused, pinned, write_pins

    server = load_config().research.servers.get(args.server)
    if server is None:
        print(f"Refused: config/research.yaml lists no server {args.server!r}", file=sys.stderr)
        return 2
    package = f"{server.package}=={server.version}" if server.package and server.version else None
    try:
        reported, tools = McpClient(args.server, server).list_tools()
        pins = pinned(args.server, reported, tools, SENT, package)
    except (McpError, ServerRefused) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    write_pins(CONFIG_DIR, args.server, pins)
    print(f"Pinned {len(pins.tools)} tools of {reported.name} {reported.version}")
    print(f"  wrote {CONFIG_DIR / 'mcp_pins.yaml'} and {CONFIG_DIR / 'mcp_servers.txt'}")
    return 0


def _pack(args: argparse.Namespace) -> int:
    """Build a research pack from a finished live run, or from an existing NotebookLM job."""
    from bidwright.llm.client import default_backends
    from bidwright.research.builder import BuildRefused, PackRequest, build_pack
    from bidwright.restricted import VARIABLE, RestrictedNames

    restricted = RestrictedNames.from_environment()
    if restricted is None:
        print(f"Note: {VARIABLE} is not set, so the restricted-name check did not run here;")
        print("  CI runs it on the committed pack")
    request = PackRequest(
        domain_id=args.domain,
        title=args.title,
        keywords=args.keywords,
        select_for=_run_folder(args.select_for),
        run=_run_folder(args.run) if args.run else None,
        notebook_id=args.notebook,
        job=args.job,
        topics=args.topics,
        leave_out=args.leave_out,
        profile=args.profile,
    )
    backends = default_backends(paid=args.profile == "paid") if args.notebook else None
    try:
        built = build_pack(request, backends=backends, restricted=restricted)
    except (BuildRefused, Refused) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    counts = ", ".join(f"{count} {name}" for name, count in built.manifest.counts.items())
    print(f"Wrote {built.path} version {built.manifest.version}: {counts}")
    print(f"  from the run {built.run_dir.name}")
    for note in built.left_out:
        print(f"  left out: {note}")
    for source in built.review:
        print(f"  review: {source} reads like a published tender; if it is one, build")
        print("    again with --leave-out, since the data rule keeps tenders out")
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
    run.add_argument(
        "--second-pass",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="re-read OBLIGATION zones (S-13); config/limits.yaml sets the default",
    )
    run.add_argument("--until", choices=UNTIL, default="render", help="the last node to run")
    run.add_argument("--research", choices=RESEARCH, help="config/research.yaml sets the default")
    run.add_argument("--outputs", type=Path, default=HOME / "outputs")
    demo = sub.add_parser("demo", help="replay the recorded development run, with no keys")
    demo.add_argument("--outputs", type=Path, default=HOME / "outputs")
    record = sub.add_parser("record", help="run live and record cassettes, on the host")
    record.add_argument("file", type=Path, help="an RFP file, or a folder holding a package")
    record.add_argument("--name", default="demo")
    record.add_argument("--profile", choices=PROFILES, default="free")
    record.add_argument("--until", choices=UNTIL, default="render", help="the last node to run")
    record.add_argument(
        "--research", choices=RESEARCH, help="config/research.yaml sets the default"
    )
    record.add_argument(
        "--fill",
        action="store_true",
        help="keep the recording, record only the calls it lacks, and drop the unused ones",
    )
    record.add_argument("--outputs", type=Path, default=HOME / "outputs")
    stop = sub.add_parser("stop", help="ask a running run to stop when its current step ends")
    stop.add_argument("run", help="a run id under outputs/, or a run folder")
    resume = sub.add_parser("resume", help="continue a run from its last checkpoint")
    resume.add_argument("run", help="a run id under outputs/, or a run folder")
    resume.add_argument(
        "--raise-budget",
        type=_percent,
        metavar="PERCENT",
        help="raise each run limit by PERCENT of its configured value",
    )
    resume.add_argument(
        "--profile",
        choices=["paid"],
        help="continue a free run that paused on its quota under the paid key",
    )
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
    research = sub.add_parser("research", help="manage the research server")
    research_sub = research.add_subparsers(dest="research_command", required=True)
    pin = research_sub.add_parser("pin", help="pin the research server's tools, on the host")
    pin.add_argument("--server", default="notebooklm", help="a server in config/research.yaml")
    pack = research_sub.add_parser(
        "pack", help="build a research pack from a finished live run or a NotebookLM job"
    )
    pack.add_argument("--domain", required=True, help="the pack's id, such as local-government")
    pack.add_argument("--title", required=True, help="the pack's title, for people")
    pack.add_argument(
        "--keyword",
        dest="keywords",
        action="append",
        required=True,
        help="words a brief's topics must hold for the pack to be selected; at least 2",
    )
    pack.add_argument(
        "--select-for",
        required=True,
        help="a run, id or folder, whose brief topics must select the pack",
    )
    source = pack.add_mutually_exclusive_group(required=True)
    source.add_argument("--run", help="a finished run in research mode live, id or folder")
    source.add_argument("--notebook", help="the NotebookLM notebook that holds the job")
    pack.add_argument("--job", help="with --notebook: the research job's task id")
    pack.add_argument(
        "--topic",
        dest="topics",
        action="append",
        default=[],
        help="with --notebook: a subject the job researched; at most 5",
    )
    pack.add_argument(
        "--leave-out",
        dest="leave_out",
        action="append",
        default=[],
        help="a source id, such as PS-005, to leave out with its excerpts, such as a tender",
    )
    pack.add_argument("--profile", choices=["free", "paid"], default="free")
    args = parser.parse_args(argv)

    os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
    load_env(HOME / ".env")
    if args.command == "purge":
        return _purge(args)
    if args.command == "stop":
        return _stop(args)
    if args.command == "resume":
        return _resume(args)
    if args.command == "research":
        return _pin(args) if args.research_command == "pin" else _pack(args)
    if args.command == "matrix":
        return _matrix(args)
    from bidwright.graph.build import execute
    from bidwright.llm.client import default_backends
    from bidwright.llm.replay import CassetteStore

    if args.command == "demo":
        store = CASSETTES / "demo"
        if not (store / RECORDING).exists():
            print(f"No demo cassettes. Record them with: bidwright record {DEMO_RECORD}")
            return 1
        recording = json.loads((store / RECORDING).read_text(encoding="utf-8"))
        from bidwright.config import load_config

        limits = load_config().limits
        stale = stale_recording(recording, limits.batch_size, limits.second_pass)
        if stale:
            print(f"The demo cassettes are stale: {stale}, with: bidwright record {DEMO_RECORD}")
            return 1
        result = execute(
            source=HOME / recording["source"],
            profile=recording["profile"],
            outputs=args.outputs,
            mode="replay",
            cassettes=CassetteStore(store),
            until=recording.get("until", "render"),
            research=recording.get("research", "off"),
        )
        return _report(result)
    cassettes = CassetteStore(CASSETTES / args.name) if args.command == "record" else None
    try:
        if cassettes is not None:
            result = execute(
                source=args.file,
                profile=args.profile,
                outputs=args.outputs,
                mode="record",
                cassettes=cassettes,
                backends=default_backends(paid=args.profile == "paid"),
                until=args.until,
                research=args.research,
                fill=args.fill,
                docling_mode="replay" if args.fill else None,
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
                research=args.research,
            )
    except Refused as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    if cassettes is not None and result.status in ("COMPLETED", "DEGRADED"):
        from bidwright.config import load_config

        # `record` passes neither setting, so the run used the configured values; a replay
        # checks them, since neither is part of a cassette key.
        config = load_config()
        limits = config.limits
        source = args.file.resolve()
        if args.fill:
            gone = cassettes.prune(cassettes.used)
            print(f"  filled: {len(cassettes.used)} cassettes kept, {len(gone)} unused removed")
        recording = {
            "profile": args.profile,
            "source": source.relative_to(HOME).as_posix()
            if source.is_relative_to(HOME)
            else str(source),
            "until": args.until,
            "research": args.research or config.research.mode,
            "batch_size": limits.batch_size,
            "second_pass": limits.second_pass,
            "run_id": result.run_id,
            "status": result.status,
        }
        (cassettes.root / RECORDING).write_text(
            json.dumps(recording, indent=1) + "\n", encoding="utf-8", newline="\n"
        )
    return _report(result)


if __name__ == "__main__":
    raise SystemExit(main())
