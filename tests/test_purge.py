"""Purge (D-05, C4): a run's folder and its cache entries go, another run's entries stay, and
`--expired` takes only client runs past the retention period, matrix runs included."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import bidwright.purge
from bidwright import cli
from bidwright.purge import expired_runs, purge_expired, purge_run
from bidwright.schemas import RunManifest

NOW = datetime(2026, 12, 31, 12, 0, tzinfo=UTC)


def _run(root: Path, run_id: str, data_class: str, ended: datetime) -> Path:
    folder = root / run_id
    folder.mkdir(parents=True)
    manifest = RunManifest(
        run_id=run_id,
        commit="x",
        profile="local",
        models={},
        started=ended - timedelta(minutes=5),
        ended=ended,
        status="COMPLETED",
        data_class=data_class,  # type: ignore[arg-type]
    )
    (folder / "run_manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    (folder / "checkpoints.sqlite").write_bytes(b"state")
    return folder


def _entry(cache: Path, name: str, run_id: str) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{name}.json"
    path.write_text(json.dumps({"key": name, "run_id": run_id, "response": {}}), encoding="utf-8")
    return path


def test_a_run_and_its_cache_entries_are_deleted_and_others_stay(tmp_path: Path) -> None:
    cache = tmp_path / ".cache"
    target = _run(tmp_path, "client-run", "client", NOW)
    other = _run(tmp_path, "other-run", "client", NOW)
    mine = [_entry(cache, "a", "client-run"), _entry(cache, "b", "client-run")]
    theirs = _entry(cache, "c", "other-run")
    deleted = purge_run(target, cache)
    assert set(deleted) == {*mine, target}
    assert not target.exists() and other.exists() and theirs.exists()


def test_expired_skips_synthetic_and_recent_runs_and_walks_matrices(tmp_path: Path) -> None:
    old = NOW - timedelta(days=31)
    stale = _run(tmp_path, "stale-client", "client", old)
    _run(tmp_path, "stale-synthetic", "synthetic", old)
    _run(tmp_path, "fresh-client", "client", NOW - timedelta(days=2))
    matrix = _run(tmp_path / "matrices" / "s03", "s03-b20-r0", "client", old)
    assert expired_runs(tmp_path, 30, NOW) == [stale, matrix]
    deleted = purge_expired(30, tmp_path, tmp_path / ".cache", NOW)
    assert deleted == [stale, matrix]
    remaining = sorted(p.name for p in tmp_path.iterdir() if p.name != "matrices")
    assert remaining == ["fresh-client", "stale-synthetic"]


def test_the_cli_prints_what_it_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(bidwright.purge, "outputs_root", lambda: tmp_path)
    folder = _run(tmp_path, "client-run", "client", NOW)
    assert cli.main(["purge", "client-run"]) == 0
    assert f"deleted {folder}" in capsys.readouterr().out and not folder.exists()
    assert cli.main(["purge", "no-such-run"]) == 1
    assert cli.main(["purge"]) == 2


def test_a_folder_without_a_run_manifest_is_never_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A mistyped path, such as the repository or the outputs folder, is refused whole."""
    monkeypatch.setattr(bidwright.purge, "outputs_root", lambda: tmp_path / "outputs")
    precious = tmp_path / "src"
    precious.mkdir()
    (precious / "code.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(bidwright.purge.NotARun):
        purge_run(precious)
    assert cli.main(["purge", str(precious)]) == 1
    assert "not a run folder" in capsys.readouterr().err
    assert (precious / "code.py").exists()
