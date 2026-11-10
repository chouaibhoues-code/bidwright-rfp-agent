"""The `bidwright` command line.

    bidwright run <file or folder> [--profile free|local|paid] [--baseline ex0|b0]
                  [--allow-non-corpus=i-accept-free-tier-terms] [--cache]
                  [--second-pass | --no-second-pass] [--until NODE]
                  [--research off|pack|live] [--auto-select] [--bid-policy FILE]
                  [--solution PATH] [--risk-mode MODE] [--reflect | --no-reflect]
                  [--outputs DIR]
                         without --auto-select, a run that reaches the solution gate waits
                         there in WAITING_HUMAN until bidwright approve decides it
    bidwright demo       replays a recorded development run; needs no keys
    bidwright record <file or folder> [--name demo] [--profile free|local|paid] [--until NODE]
                         [--research off|pack|live] [--fill] [--auto-select]
                         [--bid-policy FILE] [--solution PATH] [--risk-mode MODE]
                         [--reflect | --no-reflect]
                         runs live and writes LLM and Docling cassettes, on the host; --fill
                         keeps the recording's cassettes, records only the calls it lacks,
                         and removes the ones the run did not use
    bidwright approve <run> --role TEXT [--option OPT-n] [--edit FILE|-] [--override REASON]
                      [--reject REASON]
                         decides the run's solution gate; the run resumes from it
    bidwright stop <run>  asks a running run to stop when its current step ends
    bidwright resume <run> [--raise-budget PERCENT] [--profile paid]
                         continues a stopped, paused or killed run from its last checkpoint
    bidwright purge <run> | --expired
                         deletes a run's folder and its cache entries, or every client run
                         past the retention period
    bidwright matrix run <file> [--resume]
                         runs a matrix file's rungs and repeats in order, under
                         outputs/matrices/<name>/
    bidwright research pin [--server notebooklm|context7|reflect]
                         pins a server's tools in config/mcp_pins.yaml, on the host
    bidwright research libraries --library NAME --topic WORDS ... [--run RUN]
                         builds or extends research_packs/libraries/ from Context7, on the host
    bidwright research pack --domain ID --title TEXT --keyword WORDS ... --select-for RUN
                            (--run RUN | --notebook ID --job TASK --topic WORDS ...)
                            [--leave-out SOURCE ...] [--profile free|paid]
                         builds research_packs/<domain>/ from a finished live run, or
                         from an existing NotebookLM job in a run of its own, on the host
    bidwright ui         starts the local Streamlit UI on 127.0.0.1:8501
    bidwright api        starts the local FastAPI wrapper on 127.0.0.1:8001
    bidwright spans replay <run> [--endpoint URL]
                         replays a run's spans.jsonl into Phoenix over OTLP HTTP
    bidwright review <run> --role TEXT (--item ID --verdict V [--note TEXT] | --from -)
                         records a person's verdicts on a run's records in
                         review/decisions.jsonl; with no verdict, prints the queue
    bidwright phoenix sync <run>
                         sends a run's checks, gate decision and review verdicts to its
                         Phoenix trace as annotations, replaying the trace first if needed

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
    from bidwright.schemas import GateApproval

DEMO_SOURCE = HOME / "inputs" / "dev" / "dev_rfp.pdf"
CONFIG_DIR = HOME / "config"  # where `research pin` writes the pins
CASSETTES = HOME / "tests" / "cassettes"
# Which profile, input, stop and run settings a cassette folder was recorded with.
RECORDING = "recording.json"
DEMO_RECORD = "inputs/dev/dev_rfp.pdf"
PROFILES = ["free", "local", "paid"]
UNTIL = ["verify", "coverage", "consolidate", "brief", "capability_map", "solution_gate", "render"]
RESEARCH = ["off", "pack", "live"]  # config/research.yaml sets the default
# The solution path's switches (section 4.11); config/limits.yaml's `switches` sets the default.
SOLUTIONS = ["oneshot", "fixed", "decide", "assess", "manifest"]
RISK_MODES = ["oneshot", "fixed", "agent"]
# The recorded settings that change which calls a run makes without changing a cassette key,
# and the solution paths that read each.
SOLUTION_CAPS = {
    "need_cap": ("fixed", "decide", "assess", "manifest"),
    "claims_per_need": ("fixed", "decide", "assess", "manifest"),
    "tech_claim_cap": ("manifest",),
}


def load_env(path: Path) -> None:
    """Read KEY=VALUE lines from `.env` into the environment, never overriding a set variable."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#") and value.strip():
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _report(result: "RunResult") -> int:
    """Print a run's outcome. A run waiting at its gate did what was asked, so it exits 0 and
    names the review file and the command that decides it."""
    print(f"{result.status}: {result.run_dir}")
    if result.reason:
        print(f"  {result.reason}")
    review = result.run_dir / "review" / "solution_gate.md"
    if result.status == "WAITING_HUMAN" and review.exists():
        print(f"  review: {review}")
        print(f"  decide it with: bidwright approve {result.run_id} --role ROLE")
    summary = result.run_dir / "solution_summary.md"
    if summary.exists():
        print(f"  summary: {summary}")
    return 0 if result.status in ("COMPLETED", "DEGRADED", "WAITING_HUMAN") else 1


def stale_recording(recording: Mapping[str, object], limits: Any) -> str | None:
    """Why a recording cannot replay under `config/limits.yaml`'s current settings, or None.
    The pack size, the second pass and the solution path's caps change which calls a run makes
    without changing any cassette key, so a replay under other values would miss its cassettes.
    A cap is checked only when the recording's solution path reads it; a recording made before
    Iteration 3 ran no solution path, `oneshot`."""
    checks: list[tuple[str, object]] = [
        ("batch_size", limits.batch_size),
        ("second_pass", limits.second_pass),
    ]
    solution = recording.get("solution", "oneshot")
    checks += [
        (key, getattr(limits.solution, key))
        for key, paths in SOLUTION_CAPS.items()
        if solution in paths
    ]
    for key, now in checks:
        if recording.get(key) != now:
            return (
                f"recorded with {key} {recording.get(key)!r}, and config/limits.yaml sets"
                f" {now!r}; record again"
            )
    return None


def _home_relative(path: Path) -> str:
    """A resolved path as a recording stores it: relative to the repository when inside it."""
    return path.relative_to(HOME).as_posix() if path.is_relative_to(HOME) else str(path)


def _home_path(value: object) -> Path | None:
    """A path a manifest or recording stored relative to the repository, made absolute."""
    if value is None:
        return None
    path = Path(str(value))
    return path if path.is_absolute() else HOME / path


def _run_folder(name: str) -> Path:
    """A run as `stop`, `resume` and `purge` name it: a run folder, or a run id under
    outputs/."""
    from bidwright.purge import outputs_root

    candidate = Path(name)
    return candidate if candidate.is_dir() else outputs_root() / name


def _seed(args: argparse.Namespace) -> int:
    """`bidwright seed`: freeze a finished run into `outputs/seeds/<name>/` (step 16)."""
    from bidwright.graph.seed import freeze
    from bidwright.purge import outputs_root

    try:
        target = freeze(_run_folder(args.run), args.name, args.outputs or outputs_root())
    except Refused as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    print(f"Seed frozen: {target}")
    print(f"  a matrix names it as seed_run: {_home_relative(target)}")
    return 0


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
    run in `run_dir`. The run's own folder names where it is, whatever `outputs` said. The
    gate's mode, the bid policy and the solution switches carry over, so a resumed run takes
    the route its first part took."""
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
        "assess_route",
        "gate",
        "solution",
        "risk_mode",
        "reflect",
        "extract_context",
        "triage",
        "coverage",
        "seed_from",
        "methods",
    )
    arguments = {
        "source": _home_path(run_args["source"]),
        "outputs": run_dir.parent,
        "run_id": run_dir.name,
        "limits": run_args.get("limits"),
        **{key: run_args[key] for key in keys if key in run_args},
    }
    if run_args.get("bid_policy"):
        arguments["bid_policy"] = _home_path(run_args["bid_policy"])
    if run_args.get("seed_run"):
        arguments["seed_run"] = _home_path(run_args["seed_run"])
    return arguments


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


class ApprovalRefused(Refused):
    """`bidwright approve` flags that cannot make an approval."""


def approval_from_args(
    args: argparse.Namespace, run_dir: Path, stdin: Any = None
) -> "GateApproval":
    """The `GateApproval` the flags make (section 4.8): `reject` with `--reject`, which takes
    no other flag; `edit` with `--edit`; else `approve`. `--option` does not combine with
    `--edit`. Refused: an unknown field path, an edit file that is not a list of
    `{field, value}`, edits the reviewed manifest cannot take (a low estimate above the high
    one, a fact that does not exist, a cycle), an option `options.json` does not hold, and a
    blocked gate approved without `--override`; a rejection or a switch to another option
    needs none."""
    import yaml

    from bidwright.graph.blueprint import EditRefused, apply_edits, edit_path_problem
    from bidwright.graph.gate import blocking, reviewed_hashes
    from bidwright.harness.supervisor import read_manifest
    from bidwright.schemas import (
        GateApproval,
        GateEdit,
        SolutionManifest,
        SolutionOptions,
        TechValidation,
    )

    if args.reject is not None and (args.option or args.edit or args.override):
        raise ApprovalRefused("--reject takes no other decision flag")
    if args.option and args.edit:
        raise ApprovalRefused(
            "--option and --edit do not combine: edits apply to the reviewed manifest"
        )
    for name in ("manifest.json", "options.json"):
        if not (run_dir / name).is_file():
            raise ApprovalRefused(f"{run_dir.name} holds no {name}, so there is no gate to decide")
    edits: list[GateEdit] = []
    if args.edit:
        if args.edit == "-":
            text = (stdin or sys.stdin).read()
        else:
            text = Path(args.edit).read_text(encoding="utf-8")
        loaded = yaml.safe_load(text)
        if not isinstance(loaded, list) or not loaded:
            raise ApprovalRefused("an edit file is a YAML list of {field, value}")
        for entry in loaded:
            if not isinstance(entry, dict) or set(entry) != {"field", "value"}:
                raise ApprovalRefused("each edit is one {field, value}")
            problem = edit_path_problem(str(entry["field"]))
            if problem is not None:
                raise ApprovalRefused(problem)
            edits.append(GateEdit(field=str(entry["field"]), value=entry["value"]))
    manifest = SolutionManifest.model_validate_json(
        (run_dir / "manifest.json").read_text(encoding="utf-8")
    )
    if edits:
        try:
            apply_edits(manifest, edits)
        except EditRefused as exc:
            raise ApprovalRefused(f"the edits cannot be applied: {exc}") from exc
    options = SolutionOptions.model_validate_json(
        (run_dir / "options.json").read_text(encoding="utf-8")
    )
    if args.option and args.option not in {o.id for o in options.options}:
        raise ApprovalRefused(f"options.json holds no option {args.option}")
    validations = run_dir / "tech_validations.jsonl"
    rows = validations.read_text(encoding="utf-8").splitlines() if validations.is_file() else []
    blocked = blocking([TechValidation.model_validate_json(r) for r in rows if r.strip()])
    decision = "reject" if args.reject is not None else "edit" if edits else "approve"
    switching = bool(args.option) and args.option != manifest.option_id
    if blocked and decision != "reject" and not switching and not args.override:
        raise ApprovalRefused(
            f"the gate is blocked by {', '.join(blocked)}, still INVALIDATED; approve it with"
            " --override REASON, or reject it"
        )
    return GateApproval(
        run_id=read_manifest(run_dir).run_id,
        reviewed=reviewed_hashes(run_dir),
        decision=decision,
        option_id=args.option,
        approver_role=args.role,
        decided=datetime.now(UTC),
        edits=edits,
        override_reason=args.override,
        reject_reason=args.reject,
    )


def _approve(args: argparse.Namespace) -> int:
    """Decide the run's gate, then resume the run from it through `execute`. A rejection ends
    the run `POLICY_BLOCKED` with "GATE_REJECTED", which is the decision asked for, so it
    exits 0."""
    from bidwright.graph.build import execute
    from bidwright.harness.supervisor import read_manifest
    from bidwright.llm.client import default_backends

    run_dir = _run_folder(args.run)
    try:
        manifest = read_manifest(run_dir)
        if manifest.status != "WAITING_HUMAN":
            raise ApprovalRefused(
                f"the run {run_dir.name} does not wait at a gate; bidwright approve continues"
                " only a run in WAITING_HUMAN"
            )
        approval = approval_from_args(args, run_dir)
        profile = str(manifest.run_args["profile"])
        result = execute(
            **resume_arguments(manifest.run_args, run_dir),
            profile=profile,
            backends=default_backends(paid=profile == "paid"),
            resume=True,
            approval=approval,
        )
    except Refused as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    code = _report(result)
    rejected = approval.decision == "reject" and result.status == "POLICY_BLOCKED"
    return 0 if rejected else code


def _percent(value: str) -> int:
    percent = int(value)
    if percent <= 0:
        raise argparse.ArgumentTypeError(f"a budget raise is a positive percentage, not {value}")
    return percent


def _pin(args: argparse.Namespace) -> int:
    """List the research server's tools and pin the ones research uses. Run on the host,
    with the server started, after its version changes."""
    from bidwright.config import StdioServer, load_config
    from bidwright.harness import reflect
    from bidwright.research import context7, nlm
    from bidwright.research.mcp_client import McpClient, McpError
    from bidwright.research.pins import ServerRefused, pinned, write_pins

    servers = load_config().research.servers
    server = servers.get(args.server)
    sent = {
        nlm.SERVER: nlm.SENT,
        context7.SERVER: context7.SENT,
        reflect.SERVER: reflect.SENT,
    }.get(args.server)
    if isinstance(server, StdioServer):
        server = reflect.reflect_server(server)
    if server is None or sent is None:
        print(f"Refused: no server {args.server!r} research can pin", file=sys.stderr)
        return 2
    package = f"{server.package}=={server.version}" if server.package and server.version else None
    try:
        reported, tools = McpClient(args.server, server).list_tools()
        pins = pinned(args.server, reported, tools, sent, package)
    except (McpError, ServerRefused) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    write_pins(CONFIG_DIR, args.server, pins, servers)
    print(f"Pinned {len(pins.tools)} tools of {reported.name} {reported.version}")
    print(f"  wrote {CONFIG_DIR / 'mcp_pins.yaml'} and {CONFIG_DIR / 'mcp_servers.txt'}")
    return 0


def _libraries(args: argparse.Namespace) -> int:
    """Build or extend `research_packs/libraries/` from Context7, and a live run's documents."""
    from bidwright.research.builder import BuildRefused, build_library_pack

    try:
        built = build_library_pack(
            args.libraries, args.topics, run=_run_folder(args.run) if args.run else None
        )
    except BuildRefused as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    counts = ", ".join(f"{count} {name}" for name, count in built.manifest.counts.items())
    print(f"Wrote {built.path} version {built.manifest.version}: {counts}")
    for note in built.notes:
        print(f"  {note}")
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


def _solution_flags(command: argparse.ArgumentParser) -> None:
    """The gate and solution flags that `run` and `record` share (sections 4.8 and 4.11)."""
    command.add_argument(
        "--auto-select",
        action="store_true",
        help="approve the top-ranked option at the gate, for evaluation; never a blocked gate",
    )
    command.add_argument(
        "--bid-policy", type=Path, metavar="FILE", help="a bid policy, for the bid signal"
    )
    command.add_argument(
        "--solution", choices=SOLUTIONS, help="config/limits.yaml's switches set the default"
    )
    command.add_argument(
        "--risk-mode", choices=RISK_MODES, help="config/limits.yaml's switches set the default"
    )
    command.add_argument(
        "--reflect",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="offer the gated reflect tool; config/limits.yaml's switches set the default",
    )


def _solution_arguments(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "gate": "auto" if args.auto_select else "wait",
        "bid_policy": args.bid_policy,
        "solution": args.solution,
        "risk_mode": args.risk_mode,
        "reflect": args.reflect,
    }


def _ui(address: str = "127.0.0.1", api: bool = False) -> int:
    """Start the Streamlit UI over `app/main.py` on port 8501. The `ui` service passes
    `--address 0.0.0.0`, since a container's loopback is not reachable through a published
    port, and `--api`, which also starts the API on port 8001 and stops it with the UI."""
    import subprocess

    server = subprocess.Popen(_api_command(address), cwd=HOME) if api else None  # noqa: S603
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(HOME / "app" / "main.py"),
        "--server.address",
        address,
        "--server.port",
        "8501",
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]
    try:
        return subprocess.run(cmd, cwd=HOME, check=False).returncode  # noqa: S603
    finally:
        if server is not None:
            server.terminate()


def _api_command(host: str) -> list[str]:
    return [sys.executable, "-m", "uvicorn", "app.api:app", "--host", host, "--port", "8001"]


def _api(host: str = "127.0.0.1") -> int:
    """Start the FastAPI wrapper (`app/api.py`) on port 8001, on loopback by default."""
    import subprocess

    return subprocess.run(_api_command(host), cwd=HOME, check=False).returncode  # noqa: S603


def _spans_replay(args: argparse.Namespace) -> int:
    """Replay `<run>/spans.jsonl` into Phoenix over OTLP HTTP."""
    from bidwright.obs.replay import replay_spans

    run_dir = _run_folder(args.run)
    try:
        count, url = replay_spans(run_dir, endpoint=args.endpoint)
    except Refused as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    print(f"Replayed {count} spans from {run_dir} to {url}")
    return 0


RUN_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")


def _run_id(value: str) -> str:
    """A run id a caller names, such as the UI: a folder name, never a path."""
    if not value or not set(value) <= RUN_ID_CHARS or value.startswith("."):
        raise argparse.ArgumentTypeError(
            f"a run id holds letters, digits, '-', '_' and '.' only, not {value!r}"
        )
    return value


def _review(args: argparse.Namespace, stdin: Any = None) -> int:
    """Print the run's review queue and progress, or record verdicts (ADR-053)."""
    import yaml

    from bidwright.review import ReviewRefused, latest, progress, record, review_queue

    run_dir = _run_folder(args.run)
    if not (run_dir / "run_manifest.json").is_file():
        print(f"Refused: no run folder {run_dir}", file=sys.stderr)
        return 2
    entries: list[dict[str, Any]] = []
    if args.source == "-":
        loaded = yaml.safe_load((stdin or sys.stdin).read())
        if not isinstance(loaded, list) or not all(isinstance(e, dict) for e in loaded):
            print("Refused: --from - takes a YAML list of {item, verdict, note}", file=sys.stderr)
            return 2
        entries = loaded
    elif args.item:
        entries = [{"item": args.item, "verdict": args.verdict, "note": args.note}]
    if entries:
        try:
            recorded = record(run_dir, entries, args.role or "")
        except ReviewRefused as exc:
            print(f"Refused: {exc}", file=sys.stderr)
            return 2
        print(f"Recorded {len(recorded)} verdicts in {run_dir / 'review' / 'decisions.jsonl'}")
    queue = review_queue(run_dir)
    done = progress(queue, latest(run_dir))
    print(f"Reviewed {done.reviewed} of {done.total} items; {done.stale} stale")
    if not entries:
        decisions = latest(run_dir)
        for item in queue:
            mark = decisions[item.id].verdict if item.id in decisions else "-"
            print(f"  {item.kind:<13} {item.id:<10} {mark:<8} {item.title[:70]}")
    return 0


def _phoenix_sync(args: argparse.Namespace) -> int:
    from bidwright.obs.phoenix import sync_run

    try:
        report = sync_run(_run_folder(args.run))
    except Refused as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    replayed = f", {len(report.replayed)} replayed first" if report.replayed else ""
    print(
        f"Synced {len(report.traces)} traces{replayed}: {report.span_annotations} span"
        f" annotations, {report.trace_annotations} trace annotations"
    )
    if report.url:
        print(f"  {report.url}")
    return 0


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
    _solution_flags(run)
    run.add_argument("--outputs", type=Path, default=HOME / "outputs")
    run.add_argument(
        "--run-id", type=_run_id, help="the run folder's name; the UI names the runs it starts"
    )
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
    _solution_flags(record)
    record.add_argument("--outputs", type=Path, default=HOME / "outputs")
    stop = sub.add_parser("stop", help="ask a running run to stop when its current step ends")
    stop.add_argument("run", help="a run id under outputs/, or a run folder")
    approve = sub.add_parser("approve", help="decide a run's solution gate")
    approve.add_argument("run", help="a run id under outputs/, or a run folder")
    approve.add_argument("--role", required=True, help="the approver's role, never a name")
    approve.add_argument("--option", help="switch to another option, such as OPT-2")
    approve.add_argument("--edit", help="a YAML list of {field, value}, or - for standard input")
    approve.add_argument(
        "--override", metavar="REASON", help="pass a blocked gate, with the reason"
    )
    approve.add_argument("--reject", metavar="REASON", help="reject the solution; the run ends")
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
    pin.add_argument(
        "--server",
        default="notebooklm",
        choices=["notebooklm", "context7", "reflect"],
        help="the server",
    )
    libraries = research_sub.add_parser(
        "libraries", help="build or extend the library pack from Context7, on the host"
    )
    libraries.add_argument(
        "--library", dest="libraries", action="append", required=True, help="a library's name"
    )
    libraries.add_argument(
        "--topic",
        dest="topics",
        action="append",
        required=True,
        help="general words to look up for each library, such as 'PDF/A export'; never RFP text",
    )
    libraries.add_argument("--run", help="a live run whose tech_docs.jsonl the pack adds")
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
    ui = sub.add_parser("ui", help="start the local Streamlit UI on 127.0.0.1:8501")
    ui.add_argument("--address", default="127.0.0.1", help="0.0.0.0 inside the container")
    ui.add_argument("--api", action="store_true", help="also start the API on port 8001")
    api = sub.add_parser("api", help="start the local FastAPI wrapper on 127.0.0.1:8001")
    api.add_argument("--host", default="127.0.0.1", help="0.0.0.0 inside the container")
    spans = sub.add_parser("spans", help="manage recorded OpenTelemetry spans")
    spans_sub = spans.add_subparsers(dest="spans_command", required=True)
    spans_replay = spans_sub.add_parser(
        "replay", help="replay a run's spans.jsonl into Phoenix over OTLP HTTP"
    )
    spans_replay.add_argument("run", help="a run id under outputs/, or a run folder")
    spans_replay.add_argument(
        "--endpoint",
        help="collector URL; PHOENIX_ENDPOINT or http://127.0.0.1:6006 when unset",
    )
    seed = sub.add_parser("seed", help="freeze a finished run as a ladder's seed")
    seed.add_argument("run", help="a run id under outputs/, or a run folder")
    seed.add_argument("--name", required=True, type=_run_id, help="the seed's name")
    seed.add_argument(
        "--outputs", type=Path, default=None, help="where seeds/ goes; outputs/ by default"
    )
    review = sub.add_parser("review", help="record verdicts on a run's records")
    review.add_argument("run", help="a run id under outputs/, or a run folder")
    review.add_argument("--role", help="the reviewer's role, never a name")
    review.add_argument("--item", help="a record id, such as REQ-0003")
    review.add_argument(
        "--verdict", choices=["accept", "correct", "reject", "flag", "clear", "missed"]
    )
    review.add_argument("--note", help="the correction, or the reason")
    review.add_argument(
        "--from", dest="source", choices=["-"], help="a YAML list of {item, verdict, note}"
    )
    phoenix = sub.add_parser("phoenix", help="annotate a run's Phoenix trace")
    phoenix_sub = phoenix.add_subparsers(dest="phoenix_command", required=True)
    sync = phoenix_sub.add_parser("sync", help="send a run's annotations to Phoenix")
    sync.add_argument("run", help="a run id under outputs/, or a run folder")
    args = parser.parse_args(argv)

    os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
    load_env(HOME / ".env")
    if args.command == "purge":
        return _purge(args)
    if args.command == "seed":
        return _seed(args)
    if args.command == "stop":
        return _stop(args)
    if args.command == "resume":
        return _resume(args)
    if args.command == "approve":
        return _approve(args)
    if args.command == "research":
        if args.research_command == "pin":
            return _pin(args)
        return _libraries(args) if args.research_command == "libraries" else _pack(args)
    if args.command == "matrix":
        return _matrix(args)
    if args.command == "ui":
        return _ui(args.address, args.api)
    if args.command == "api":
        return _api(args.host)
    if args.command == "spans":
        return _spans_replay(args)
    if args.command == "review":
        if args.item and not args.verdict:
            print("Refused: --item takes a --verdict", file=sys.stderr)
            return 2
        return _review(args)
    if args.command == "phoenix":
        return _phoenix_sync(args)
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

        stale = stale_recording(recording, load_config().limits)
        if stale:
            print(f"The demo cassettes are stale: {stale}, with: bidwright record {DEMO_RECORD}")
            return 1
        result = execute(
            **replay_arguments(recording), outputs=args.outputs, cassettes=CassetteStore(store)
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
                **_solution_arguments(args),
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
                run_id=args.run_id,
                **_solution_arguments(args),
            )
    except Refused as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    if cassettes is not None and result.status in ("COMPLETED", "DEGRADED"):
        _write_recording(args, cassettes, result)
    return _report(result)


def replay_arguments(recording: Mapping[str, Any]) -> dict[str, Any]:
    """The arguments of `execute` that replay a recording as `record` ran it. A recording made
    before Iteration 3 names no switch: it ran no solution path (`oneshot`), the risk agent
    (`agent`) and no reflection, and it had no gate."""
    return {
        "source": _home_path(recording["source"]),
        "profile": recording["profile"],
        "mode": "replay",
        "until": recording.get("until", "render"),
        "research": recording.get("research", "off"),
        "assess_route": recording.get("assess_route"),
        "gate": recording.get("gate", "auto"),
        "bid_policy": _home_path(recording.get("bid_policy")),
        "solution": recording.get("solution", "oneshot"),
        "risk_mode": recording.get("risk_mode", "agent"),
        "reflect": recording.get("reflect", False),
        "extract_context": recording.get("extract_context", "full"),
        "triage": recording.get("triage", True),
        "coverage": recording.get("coverage", True),
        "methods": recording.get("methods", []),
    }


def _write_recording(args: argparse.Namespace, cassettes: Any, result: "RunResult") -> None:
    """Write `recording.json`: what a replay must run with. A setting `record` does not pass
    is `config/limits.yaml`'s, which the run used, as `execute` resolves it."""
    from bidwright.config import load_config

    config = load_config()
    limits = config.limits
    source = args.file.resolve()
    if args.fill:
        gone = cassettes.prune(cassettes.used)
        print(f"  filled: {len(cassettes.used)} cassettes kept, {len(gone)} unused removed")
    policy = args.bid_policy.resolve() if args.bid_policy else None
    recording = {
        "profile": args.profile,
        "source": _home_relative(source),
        "until": args.until,
        "research": args.research or config.research.mode,
        "batch_size": limits.batch_size,
        "second_pass": limits.second_pass,
        "need_cap": limits.solution.need_cap,
        "claims_per_need": limits.solution.claims_per_need,
        "tech_claim_cap": limits.solution.tech_claim_cap,
        "gate": "auto" if args.auto_select else "wait",
        "bid_policy": _home_relative(policy) if policy else None,
        "solution": args.solution or limits.switches.solution,
        "risk_mode": args.risk_mode or limits.switches.risk_mode,
        "reflect": limits.switches.reflect if args.reflect is None else args.reflect,
        "extract_context": limits.switches.extract_context,
        "triage": limits.switches.triage,
        "coverage": limits.switches.coverage,
        "methods": list(limits.methods.enabled),
        "run_id": result.run_id,
        "status": result.status,
        # The assess role's route (ADR-045), which a replay takes from here.
        "assess_route": result.assess_route,
    }
    (cassettes.root / RECORDING).write_text(
        json.dumps(recording, indent=1) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
