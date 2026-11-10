"""The command line: argument handling, refusals and the `.env` reader."""

import argparse
import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from bidwright import cli
from bidwright.config import load_config
from bidwright.graph.build import RunResult, execute
from bidwright.llm.client import Mode
from bidwright.llm.replay import CassetteStore
from bidwright.llm.types import Response
from bidwright.preflight import Refused
from bidwright.schemas import GateApproval
from tests.node_fakes import DEV_RFP, USAGE, RuleBackend


def test_free_refuses_a_non_corpus_file_before_any_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stranger = tmp_path / "tender.pdf"
    stranger.write_bytes(b"%PDF-1.4")
    assert cli.main(["run", str(stranger), "--outputs", str(tmp_path / "out")]) == 2
    assert "--profile local" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("profile", ["free", "local"])
def test_record_refuses_a_non_corpus_file_on_every_profile(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], profile: str
) -> None:
    stranger = tmp_path / "client_tender.pdf"
    stranger.write_bytes(b"%PDF-1.4")
    name = "should-not-exist"
    code = cli.main(["record", str(stranger), "--profile", profile, "--name", name])
    assert code == 2
    assert "Git tracks" in capsys.readouterr().err
    assert not (cli.CASSETTES / name).exists()


def test_a_bad_consent_string_is_refused(tmp_path: Path) -> None:
    stranger = tmp_path / "tender.pdf"
    stranger.write_bytes(b"%PDF-1.4")
    code = cli.main(["run", str(stranger), "--allow-non-corpus=sure", "--outputs", str(tmp_path)])
    assert code == 2


def test_unknown_profiles_are_rejected_by_argparse() -> None:
    with pytest.raises(SystemExit):
        cli.main(["run", "x.pdf", "--profile", "gold"])


def test_run_passes_its_flags_to_the_run_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A package folder, `--until`, `--baseline b0`, `--cache`, `--no-second-pass`,
    `--research off`, and `paid` with the paid key."""
    seen: dict[str, object] = {}

    def fake_execute(**kwargs: object) -> RunResult:
        seen.update(kwargs)
        return RunResult("run", tmp_path, "COMPLETED", None)

    monkeypatch.setattr("bidwright.graph.build.execute", fake_execute)
    monkeypatch.setenv("GEMINI_PAID_API_KEY", "test-paid-key")
    folder = cli.HOME / "inputs" / "hero"
    arguments = ["run", str(folder), "--profile", "paid", "--baseline", "b0", "--cache"]
    arguments += ["--no-second-pass", "--until", "coverage", "--outputs", str(tmp_path)]
    assert cli.main(arguments + ["--research", "off"]) == 0
    assert seen["source"] == folder and seen["profile"] == "paid"
    assert seen["research"] == "off"
    assert (seen["baseline"], seen["until"], seen["cache"], seen["second_pass"]) == (
        "b0",
        "coverage",
        True,
        False,
    )
    backends = seen["backends"]
    assert isinstance(backends, dict) and backends["gemini"].paid is True


def test_record_passes_until_and_writes_it_to_the_recording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def fake_execute(**kwargs: object) -> RunResult:
        seen.update(kwargs)
        return RunResult("run", tmp_path, "COMPLETED", None, "fallback")

    monkeypatch.setattr("bidwright.graph.build.execute", fake_execute)
    monkeypatch.setattr(cli, "CASSETTES", tmp_path)
    (tmp_path / "probe").mkdir()
    source = cli.HOME / "inputs" / "hero"
    assert cli.main(["record", str(source), "--name", "probe", "--until", "consolidate"]) == 0
    assert seen["until"] == "consolidate" and seen["mode"] == "record"
    assert (seen["research"], seen["fill"], seen["docling_mode"]) == (None, False, None)
    recording = json.loads((tmp_path / "probe" / cli.RECORDING).read_text(encoding="utf-8"))
    assert recording["until"] == "consolidate" and recording["source"] == "inputs/hero"
    assert recording["research"] == load_config().research.mode, "the configured mode"
    limits = load_config().limits
    assert (recording["batch_size"], recording["second_pass"]) == (
        limits.batch_size,
        limits.second_pass,
    )
    assert cli.stale_recording(recording, limits) is None
    assert recording["assess_route"] == "fallback", "the route a replay takes (ADR-045)"
    assert (seen["gate"], recording["gate"]) == ("wait", "wait"), "no --auto-select"
    assert recording["solution"] == limits.switches.solution
    assert recording["risk_mode"] == limits.switches.risk_mode
    assert recording["reflect"] == limits.switches.reflect
    assert recording["need_cap"] == limits.solution.need_cap


def _cassette(store: CassetteStore, name: str) -> str:
    """A stored call under a made-up key, as `record` writes one; its key."""
    key = f"sha256:{sha256(name.encode()).hexdigest()}"
    store.save(key, {"role": "extract"}, Response(text=name, usage=USAGE))
    return key


@pytest.mark.parametrize("fill", [True, False])
def test_record_passes_research_and_a_fill_removes_the_cassettes_the_run_did_not_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fill: bool
) -> None:
    """`--fill` replays Docling and keeps only the cassettes the run used; a plain record
    removes nothing."""
    seen: dict[str, object] = {}
    store = CassetteStore(tmp_path / "probe")
    used, unused = _cassette(store, "used"), _cassette(store, "unused")

    def fake_execute(**kwargs: object) -> RunResult:
        seen.update(kwargs)
        cassettes = kwargs["cassettes"]
        assert isinstance(cassettes, CassetteStore) and cassettes.load(used) is not None
        return RunResult("run", tmp_path, "COMPLETED", None)

    monkeypatch.setattr("bidwright.graph.build.execute", fake_execute)
    monkeypatch.setattr(cli, "CASSETTES", tmp_path)
    arguments = ["record", str(DEV_RFP), "--name", "probe", "--until", "brief"]
    arguments += ["--research", "pack"] + (["--fill"] if fill else [])
    assert cli.main(arguments) == 0
    assert (seen["research"], seen["until"], seen["fill"]) == ("pack", "brief", fill)
    assert seen["docling_mode"] == ("replay" if fill else None)
    assert set(store.keys()) == ({used} if fill else {used, unused})
    recording = json.loads((tmp_path / "probe" / cli.RECORDING).read_text(encoding="utf-8"))
    assert recording["research"] == "pack" and recording["until"] == "brief"


def _limits(batch_size: int = 40, second_pass: bool = True, need_cap: int = 24) -> object:
    limits = load_config().limits
    solution = limits.solution.model_copy(update={"need_cap": need_cap})
    return limits.model_copy(
        update={"batch_size": batch_size, "second_pass": second_pass, "solution": solution}
    )


def test_a_stale_recording_names_the_setting_to_record_again() -> None:
    recording = {"batch_size": 40, "second_pass": True}
    assert cli.stale_recording(recording, _limits()) is None
    stale = cli.stale_recording(recording, _limits(batch_size=20))
    assert stale is not None and "batch_size 40" in stale and "record again" in stale
    stale = cli.stale_recording({"batch_size": 40}, _limits(second_pass=False))
    assert stale is not None and "second_pass None" in stale


def test_a_recording_is_stale_on_a_solution_cap_only_where_its_path_reads_it() -> None:
    """`oneshot`, the path of a recording made before Iteration 3, reads no cap; `decide`
    reads the need cap, and only `manifest` the technology-claim cap."""
    limits = load_config().limits
    base = {
        "batch_size": 40,
        "second_pass": True,
        "need_cap": 24,
        "claims_per_need": limits.solution.claims_per_need,
    }
    assert cli.stale_recording(base, _limits(need_cap=9)) is None, "oneshot reads no cap"
    stale = cli.stale_recording({**base, "solution": "decide"}, _limits(need_cap=9))
    assert stale is not None and "need_cap 24" in stale
    assert cli.stale_recording({**base, "solution": "decide"}, _limits()) is None
    stale = cli.stale_recording({**base, "solution": "manifest"}, _limits())
    assert stale is not None and "tech_claim_cap None" in stale


def test_a_baseline_asked_for_the_second_pass_is_refused_before_a_run_folder_exists(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"
    arguments = ["run", str(DEV_RFP), "--baseline", "ex0", "--second-pass", "--outputs", str(out)]
    assert cli.main(arguments) == 2
    assert "ADR-028" in capsys.readouterr().err
    assert not out.exists()


def test_an_extract_prompt_a_run_does_not_load_is_refused_before_a_run_folder_exists(
    tmp_path: Path,
) -> None:
    with pytest.raises(Refused, match="no extract prompt 'extract_noexamples'"):
        execute(
            docling_mode="replay",
            source=DEV_RFP,
            profile="free",
            outputs=tmp_path / "out",
            backends={"gemini": RuleBackend()},
            extract_prompt="extract_noexamples",
        )
    assert not (tmp_path / "out").exists()
    with pytest.raises(Refused, match="no extract prompt 'approach'"):
        execute(source=DEV_RFP, profile="free", outputs=tmp_path / "out", extract_prompt="approach")


@pytest.mark.parametrize("mode", ["record", "replay"])
def test_live_research_is_refused_when_recording_or_replaying(tmp_path: Path, mode: Mode) -> None:
    """MCP calls have no cassettes, so a recording in research mode live would reach the
    research server when replayed (drift report of 2026-11-05)."""
    with pytest.raises(Refused, match=f"client's {mode} mode"):
        execute(
            docling_mode="replay",
            source=DEV_RFP,
            profile="free",
            outputs=tmp_path / "out",
            mode=mode,
            cassettes=CassetteStore(tmp_path / "cassettes"),
            backends={"gemini": RuleBackend()},
            research="live",
        )
    assert not (tmp_path / "out").exists()


def test_load_env_never_overrides_and_skips_empty_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / ".env"
    env.write_text("# comment\nBW_A=1\nBW_B=\nBW_C='3'\n", encoding="utf-8")
    monkeypatch.setenv("BW_A", "set")
    monkeypatch.delenv("BW_B", raising=False)
    monkeypatch.delenv("BW_C", raising=False)
    cli.load_env(env)
    assert os.environ["BW_A"] == "set"
    assert "BW_B" not in os.environ
    assert os.environ["BW_C"] == "3"


# --- stop and resume (Iteration 2, ADR-031) ---------------------------------------------------


def _manifest_file(run_dir: Path, status: str, run_args: dict[str, object]) -> None:
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": run_dir.name,
        "commit": "abc1234",
        "profile": "free",
        "models": {},
        "started": "2026-11-04T10:00:00Z",
        "status": status,
        "run_args": run_args,
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_stop_writes_the_request_for_a_running_run_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    running, stopped = tmp_path / "running", tmp_path / "stopped"
    _manifest_file(running, "RUNNING", {})
    _manifest_file(stopped, "STOPPED", {})
    assert cli.main(["stop", str(running)]) == 0
    assert (running / "control" / "stop.request").is_file()
    assert cli.main(["stop", str(stopped)]) == 1
    assert "the run is STOPPED, not RUNNING" in capsys.readouterr().err
    assert not (stopped / "control" / "stop.request").exists()
    assert cli.main(["stop", str(tmp_path / "nowhere")]) == 1


def test_resume_calls_the_run_entry_with_the_recorded_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def fake_execute(**kwargs: object) -> RunResult:
        seen.update(kwargs)
        return RunResult("paused", tmp_path, "COMPLETED", None)

    monkeypatch.setattr("bidwright.graph.build.execute", fake_execute)
    monkeypatch.setenv("GEMINI_PAID_API_KEY", "test-paid-key")
    run_args = {
        "source": "inputs/dev/dev_rfp.pdf",
        "profile": "free",
        "outputs": "outputs",
        "limits": "dev",
        "until": "render",
        "batch_size": 40,
        "second_pass": True,
        "extract_prompt": "extract",
        "research": "pack",
        "repeat": 2,
        "cache": False,
        "docling_mode": "live",
        "fallback": False,
        "mode": "live",
        "environment": "host:anywhere",
    }
    run_dir = tmp_path / "runs" / "paused"
    _manifest_file(run_dir, "QUOTA_PAUSED", run_args)
    arguments = ["resume", str(run_dir), "--raise-budget", "50", "--profile", "paid"]
    assert cli.main(arguments) == 0
    assert seen["source"] == cli.HOME / "inputs" / "dev" / "dev_rfp.pdf"
    assert (seen["outputs"], seen["run_id"]) == (tmp_path / "runs", "paused")
    assert (seen["resume"], seen["raise_budget"], seen["profile"]) == (True, 50, "paid")
    assert (seen["repeat"], seen["fallback"], seen["limits"]) == (2, False, "dev")
    assert "environment" not in seen, "the supervisor checks it against the stored manifest"
    backends = seen["backends"]
    assert isinstance(backends, dict) and backends["gemini"].paid is True


def test_run_waits_at_the_gate_unless_auto_select_and_passes_the_switches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def fake_execute(**kwargs: object) -> RunResult:
        seen.update(kwargs)
        return RunResult("run", tmp_path, "COMPLETED", None)

    monkeypatch.setattr("bidwright.graph.build.execute", fake_execute)
    assert cli.main(["run", str(DEV_RFP), "--outputs", str(tmp_path)]) == 0
    assert seen["gate"] == "wait"
    assert (seen["solution"], seen["risk_mode"], seen["reflect"]) == (None, None, None)
    policy = tmp_path / "policy.yaml"
    arguments = ["run", str(DEV_RFP), "--auto-select", "--bid-policy", str(policy)]
    arguments += ["--solution", "manifest", "--risk-mode", "fixed", "--reflect"]
    assert cli.main(arguments) == 0
    assert (seen["gate"], seen["bid_policy"]) == ("auto", policy)
    assert (seen["solution"], seen["risk_mode"], seen["reflect"]) == ("manifest", "fixed", True)
    with pytest.raises(SystemExit):
        cli.main(["run", str(DEV_RFP), "--solution", "everything"])


def test_a_run_waiting_at_its_gate_exits_0_and_names_the_approve_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    review = tmp_path / "review" / "solution_gate.md"
    review.parent.mkdir()
    review.write_text("# Gate\n", encoding="utf-8")
    reason = "solution_gate: waiting for a decision"
    assert cli._report(RunResult("run-9", tmp_path, "WAITING_HUMAN", reason)) == 0
    out = capsys.readouterr().out
    assert str(review) in out and "bidwright approve run-9 --role ROLE" in out
    assert cli._report(RunResult("run-9", tmp_path, "STOPPED", None)) == 1


def test_a_resume_carries_the_gate_the_bid_policy_and_the_switches(tmp_path: Path) -> None:
    run_args = {
        "source": "inputs/dev/dev_rfp.pdf",
        "profile": "free",
        "gate": "wait",
        "bid_policy": "config/bid_policy.example.yaml",
        "solution": "assess",
        "risk_mode": "fixed",
        "reflect": True,
    }
    arguments = cli.resume_arguments(run_args, tmp_path / "run")
    assert (arguments["gate"], arguments["solution"]) == ("wait", "assess")
    assert (arguments["risk_mode"], arguments["reflect"]) == ("fixed", True)
    assert arguments["bid_policy"] == cli.HOME / "config" / "bid_policy.example.yaml"
    assert "bid_policy" not in cli.resume_arguments({**run_args, "bid_policy": None}, tmp_path)


def test_a_raise_must_be_a_positive_percentage() -> None:
    with pytest.raises(SystemExit):
        cli.main(["resume", "run", "--raise-budget", "0"])
    with pytest.raises(SystemExit):
        cli.main(["resume", "run", "--profile", "local"])


def test_a_resume_carries_the_assess_route_its_first_part_recorded(tmp_path: Path) -> None:
    run_args = {"source": "inputs/dev/dev_rfp.pdf", "profile": "free", "assess_route": "fallback"}
    assert cli.resume_arguments(run_args, tmp_path / "run")["assess_route"] == "fallback"


EVERY_ADDRESS = "0.0.0.0"  # noqa: S104 - the address the ui service binds in its container


# --- Iteration 3, step 10: bidwright approve ---------------------------------------------------


def _gate_folder(
    folder: Path, verdict: str = "VALIDATED", run_args: dict[str, object] | None = None
) -> Path:
    from bidwright.graph.blueprint import write_manifest
    from bidwright.graph.options import write_options
    from bidwright.schemas import (
        EffortEstimate,
        RunManifest,
        SolutionManifest,
        SolutionOption,
        SolutionOptions,
        TechValidation,
        WorkPackage,
    )

    folder.mkdir(parents=True)
    effort = EffortEstimate(low_days=5, high_days=10, basis="analogy", basis_text="Similar.")
    write_manifest(
        folder,
        SolutionManifest(
            option_id="OPT-1", work_packages=[WorkPackage(code="1.1", name="W", effort=effort)]
        ),
    )
    write_options(
        folder,
        SolutionOptions(
            options=[
                SolutionOption(id="OPT-1", name="A", rank=1),
                SolutionOption(id="OPT-2", name="B", rank=2),
            ]
        ),
    )
    row = TechValidation(claim_id="TC-01", library="pdfplumber", verdict=verdict)  # type: ignore[arg-type]
    (folder / "tech_validations.jsonl").write_text(row.model_dump_json() + "\n", encoding="utf-8")
    manifest = RunManifest(
        run_id="run-gate",
        commit="0" * 7,
        profile="free",
        models={},
        started=datetime(2026, 11, 5, tzinfo=UTC),
        status="WAITING_HUMAN",
        run_args=run_args or {},
    )
    (folder / "run_manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    return folder


def _approve_args(*flags: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", default="Bid director")
    for name in ("--option", "--edit", "--override", "--reject"):
        parser.add_argument(name)
    return parser.parse_args(list(flags))


@pytest.mark.parametrize(
    ("flags", "decision"),
    [((), "approve"), (("--option", "OPT-2"), "approve"), (("--reject", "No."), "reject")],
)
def test_approval_from_args_gives_the_decision_for_each_flag_set(
    tmp_path: Path, flags: tuple[str, ...], decision: str
) -> None:
    folder = _gate_folder(tmp_path / "run")
    approval = cli.approval_from_args(_approve_args(*flags), folder)
    assert approval.decision == decision and approval.run_id == "run-gate"
    assert approval.reviewed.manifest.startswith("sha256:")


@pytest.mark.parametrize(
    ("flags", "problem"),
    [
        (("--reject", "No.", "--option", "OPT-2"), "--reject takes no other decision flag"),
        (("--option", "OPT-2", "--edit", "edits.yaml"), "do not combine"),
        (("--option", "OPT-9"), "no option OPT-9"),
    ],
)
def test_approval_from_args_refuses_a_forbidden_combination(
    tmp_path: Path, flags: tuple[str, ...], problem: str
) -> None:
    folder = _gate_folder(tmp_path / "run")
    with pytest.raises(cli.ApprovalRefused, match=problem):
        cli.approval_from_args(_approve_args(*flags), folder)


def test_approval_from_args_reads_edits_and_refuses_an_unknown_field(tmp_path: Path) -> None:
    import io

    folder = _gate_folder(tmp_path / "run")
    good = "- {field: 'work_packages[1.1].effort.high_days', value: 12}\n"
    approval = cli.approval_from_args(_approve_args("--edit", "-"), folder, io.StringIO(good))
    assert approval.decision == "edit"
    assert [(e.field, e.value) for e in approval.edits] == [
        ("work_packages[1.1].effort.high_days", 12)
    ]
    bad = tmp_path / "edits.yaml"
    bad.write_text("- {field: 'work_packages[1.1].name', value: New}\n", encoding="utf-8")
    with pytest.raises(cli.ApprovalRefused, match="is not a field an edit may change"):
        cli.approval_from_args(_approve_args("--edit", str(bad)), folder)


def test_approval_from_args_refuses_a_blocked_gate_without_an_override(tmp_path: Path) -> None:
    folder = _gate_folder(tmp_path / "run", verdict="INVALIDATED")
    with pytest.raises(cli.ApprovalRefused, match="blocked by TC-01"):
        cli.approval_from_args(_approve_args(), folder)
    passed = cli.approval_from_args(_approve_args("--override", "Fixed upstream."), folder)
    assert passed.override_reason == "Fixed upstream."
    assert cli.approval_from_args(_approve_args("--reject", "No."), folder).decision == "reject"


def test_approve_refuses_a_run_that_waits_at_no_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _gate_folder(tmp_path / "run")
    data = json.loads((folder / "run_manifest.json").read_text(encoding="utf-8"))
    data["status"] = "STOPPED"
    (folder / "run_manifest.json").write_text(json.dumps(data), encoding="utf-8")
    assert cli.main(["approve", str(folder), "--role", "Bid director"]) == 2
    assert "does not wait at a gate" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("flags", "status"), [((), "COMPLETED"), (("--reject", "No."), "POLICY_BLOCKED")]
)
def test_approve_resumes_the_run_from_its_gate_through_the_run_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flags: tuple[str, ...], status: str
) -> None:
    """The approval and the recorded arguments go to `execute` as a resume; a rejection ends
    the run POLICY_BLOCKED, which is the decision asked for, so the command exits 0."""
    seen: dict[str, object] = {}
    run_args = {
        "source": "inputs/dev/dev_rfp.pdf",
        "profile": "free",
        "gate": "wait",
        "solution": "manifest",
        "risk_mode": "agent",
        "reflect": False,
    }
    folder = _gate_folder(tmp_path / "run", run_args=run_args)

    def fake_execute(**kwargs: object) -> RunResult:
        seen.update(kwargs)
        return RunResult("run-gate", folder, status, "GATE_REJECTED" if flags else None)  # type: ignore[arg-type]

    monkeypatch.setattr("bidwright.graph.build.execute", fake_execute)
    assert cli.main(["approve", str(folder), "--role", "Bid director", *flags]) == 0
    approval = seen["approval"]
    assert isinstance(approval, GateApproval)
    assert approval.decision == ("reject" if flags else "approve")
    assert (seen["resume"], seen["run_id"], seen["outputs"]) == (True, "run", tmp_path)
    assert (seen["gate"], seen["solution"], seen["profile"]) == ("wait", "manifest", "free")


def test_the_command_line_offers_the_values_the_run_entry_takes() -> None:
    """`cli.py` keeps its own lists, so parsing never imports the graph; they match it."""
    from bidwright.graph import build
    from bidwright.graph import solution as sol
    from bidwright.matrix import MatrixFile

    assert cli.UNTIL == list(build.UNTIL)
    assert (cli.SOLUTIONS, cli.RISK_MODES) == (list(sol.SOLUTIONS), list(sol.RISK_MODES))
    until = MatrixFile.model_fields["until"].annotation
    assert set(getattr(until, "__args__", ())) == set(build.UNTIL)


def test_ui_starts_streamlit_with_loopback_and_headless_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    class DummyCompleted:
        returncode = 0

    def fake_run(cmd: list[str], **kwargs: object) -> DummyCompleted:
        seen.extend(cmd)
        return DummyCompleted()

    monkeypatch.setattr("subprocess.run", fake_run)
    assert cli.main(["ui"]) == 0
    assert "streamlit" in seen
    assert "--server.address" in seen and "127.0.0.1" in seen
    assert "--server.port" in seen and "8501" in seen
    assert "--server.headless" in seen and "true" in seen
    assert "--browser.gatherUsageStats" in seen and "false" in seen
    assert EVERY_ADDRESS not in seen, "loopback on the host"


def test_the_container_ui_binds_every_address_and_starts_the_api_beside_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Section 4.14: the `ui` service runs both servers on 0.0.0.0, and the API stops with
    the UI."""
    started: list[list[str]] = []
    stopped: list[bool] = []

    class FakeServer:
        def __init__(self, cmd: list[str], **kwargs: object) -> None:
            started.append(cmd)

        def terminate(self) -> None:
            stopped.append(True)

    class DummyCompleted:
        returncode = 0

    ran: list[list[str]] = []
    monkeypatch.setattr("subprocess.Popen", FakeServer)
    monkeypatch.setattr("subprocess.run", lambda cmd, **kwargs: ran.append(cmd) or DummyCompleted())
    assert cli.main(["ui", "--address", EVERY_ADDRESS, "--api"]) == 0
    assert started and "uvicorn" in started[0] and EVERY_ADDRESS in started[0]
    assert "streamlit" in ran[0] and ran[0][ran[0].index("--server.address") + 1] == EVERY_ADDRESS
    assert stopped == [True]


def test_api_starts_uvicorn_on_loopback_8001(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    class DummyCompleted:
        returncode = 0

    def fake_run(cmd: list[str], **kwargs: object) -> DummyCompleted:
        seen.extend(cmd)
        return DummyCompleted()

    monkeypatch.setattr("subprocess.run", fake_run)
    assert cli.main(["api"]) == 0
    assert "uvicorn" in seen and "app.api:app" in seen
    assert "--host" in seen and "127.0.0.1" in seen
    assert "--port" in seen and "8001" in seen


def test_spans_replay_calls_replay_spans_and_refuses_bad_endpoint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = cli.main(
        [
            "spans",
            "replay",
            str(cli.HOME / "samples" / "dev"),
            "--endpoint",
            "https://collector.example.com:6006",
        ]
    )
    assert code == 2
    assert "Refused:" in capsys.readouterr().err


def test_approval_from_args_refuses_edits_the_manifest_cannot_take(tmp_path: Path) -> None:
    import io

    folder = _gate_folder(tmp_path / "run")
    for edit, problem in (
        ("- {field: 'work_packages[1.1].effort.low_days', value: 12}\n", "above high_days"),
        ("- {field: 'assumptions[3].text', value: More}\n", "no such fact"),
    ):
        with pytest.raises(cli.ApprovalRefused, match=problem):
            cli.approval_from_args(_approve_args("--edit", "-"), folder, io.StringIO(edit))


def test_approval_from_args_lets_a_switch_leave_a_blocked_gate_without_an_override(
    tmp_path: Path,
) -> None:
    folder = _gate_folder(tmp_path / "run", verdict="INVALIDATED")
    switched = cli.approval_from_args(_approve_args("--option", "OPT-2"), folder)
    assert switched.option_id == "OPT-2" and switched.override_reason is None
    with pytest.raises(cli.ApprovalRefused, match="blocked by TC-01"):
        cli.approval_from_args(_approve_args("--option", "OPT-1"), folder)  # the same option
