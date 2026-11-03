"""The command line: argument handling, refusals and the `.env` reader."""

import os
from pathlib import Path

import pytest

from bidwright import cli


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
    assert "Git tracks" in capsys.readouterr().err or profile == "free"
    assert not (cli.CASSETTES / name).exists()


def test_a_bad_consent_string_is_refused(tmp_path: Path) -> None:
    stranger = tmp_path / "tender.pdf"
    stranger.write_bytes(b"%PDF-1.4")
    code = cli.main(["run", str(stranger), "--allow-non-corpus=sure", "--outputs", str(tmp_path)])
    assert code == 2


def test_unknown_profiles_are_rejected_by_argparse() -> None:
    with pytest.raises(SystemExit):
        cli.main(["run", "x.pdf", "--profile", "paid"])


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
