"""The command line: argument handling, refusals and the `.env` reader."""

import json
import os
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
        return RunResult("run", tmp_path, "COMPLETED", None)

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
    assert cli.stale_recording(recording, limits.batch_size, limits.second_pass) is None


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


def test_a_stale_recording_names_the_setting_to_record_again() -> None:
    recording = {"batch_size": 40, "second_pass": True}
    assert cli.stale_recording(recording, 40, True) is None
    stale = cli.stale_recording(recording, 20, True)
    assert stale is not None and "batch_size 40" in stale and "record again" in stale
    stale = cli.stale_recording({"batch_size": 40}, 40, False)
    assert stale is not None and "second_pass None" in stale


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


def test_a_raise_must_be_a_positive_percentage() -> None:
    with pytest.raises(SystemExit):
        cli.main(["resume", "run", "--raise-budget", "0"])
    with pytest.raises(SystemExit):
        cli.main(["resume", "run", "--profile", "local"])


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
