"""The command line: argument handling, refusals and the `.env` reader."""

import json
import os
from pathlib import Path

import pytest

from bidwright import cli
from bidwright.config import load_config
from bidwright.graph.build import RunResult, execute
from bidwright.preflight import Refused
from tests.node_fakes import DEV_RFP, RuleBackend


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
    """A package folder, `--until`, `--baseline b0`, `--cache`, `--no-second-pass`, and `paid`
    with the paid key."""
    seen: dict[str, object] = {}

    def fake_execute(**kwargs: object) -> RunResult:
        seen.update(kwargs)
        return RunResult("run", tmp_path, "COMPLETED", None)

    monkeypatch.setattr("bidwright.graph.build.execute", fake_execute)
    monkeypatch.setenv("GEMINI_PAID_API_KEY", "test-paid-key")
    folder = cli.HOME / "inputs" / "hero"
    arguments = ["run", str(folder), "--profile", "paid", "--baseline", "b0", "--cache"]
    arguments += ["--no-second-pass", "--until", "coverage", "--outputs", str(tmp_path)]
    assert cli.main(arguments) == 0
    assert seen["source"] == folder and seen["profile"] == "paid"
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
    recording = json.loads((tmp_path / "probe" / cli.RECORDING).read_text(encoding="utf-8"))
    assert recording["until"] == "consolidate" and recording["source"] == "inputs/hero"
    limits = load_config().limits
    assert (recording["batch_size"], recording["second_pass"]) == (
        limits.batch_size,
        limits.second_pass,
    )
    assert cli.stale_recording(recording, limits.batch_size, limits.second_pass) is None


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
