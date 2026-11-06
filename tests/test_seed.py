"""Seed runs (Iteration 3, step 16; section 4.11), on replays of the development recording:
a seeded run starts after its seed point with the seed's state and files, a stale or changed
seed is refused before its run folder exists, and `SEED_KEYS` and `SEED_FILES` hold every key
and file the nodes before each seed point write."""

import json
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import pytest

from bidwright import cli
from bidwright.cli import CASSETTES, RECORDING, replay_arguments
from bidwright.graph.build import RunResult, execute
from bidwright.graph.seed import SEED_HASHES, check_seed, checkpoint_values, freeze, write_hashes
from bidwright.graph.state import SEED_FILES, SEED_KEYS
from bidwright.llm.replay import CassetteStore
from bidwright.obs.ledger import read_ledger
from bidwright.preflight import Refused
from bidwright.schemas import RunManifest, RunTotals

pytestmark = pytest.mark.replay

DEMO = CASSETTES / "demo"
# Files every run writes for itself, which a seed never hands on.
RUN_FILES = (
    "run_manifest.json",
    "ledger.jsonl",
    "events.jsonl",
    "spans.jsonl",
    "tool_calls.jsonl",
    "dead_letter.jsonl",
    "checkpoints.sqlite*",
    "control/*",
    "journal/*",
)
# What `risk` and the nodes after it write, which the RK seed point leaves to the run.
LATER_FILES = (
    "risks.jsonl",
    "risk_rejected.jsonl",
    "review/*",
    "bid_signal.json",
    "bid_memo.md",
    "sections/*",
    "proposal.md",
    "solution_summary.*",
    "compliance_matrix.*",
    "clarification_questions.md",
    "submission_checklist.md",
    "context/risk-*",
    "context/draft-*",
)
LATER_KEYS = ("risk", "gate", "bid_signal", "sections")


def _arguments(**changes: Any) -> dict[str, Any]:
    recording = json.loads((DEMO / RECORDING).read_text(encoding="utf-8"))
    return (
        replay_arguments(recording) | {"cassettes": CassetteStore(DEMO), "gate": "auto"} | changes
    )


@dataclass(frozen=True)
class Probe:
    root: Path
    brief: RunResult  # the recording replayed to `brief`
    full: RunResult  # the recording replayed to `render`
    so_seed: Path
    rk_seed: Path


@pytest.fixture(scope="module")
def probe(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Probe]:
    root = tmp_path_factory.mktemp("seeds")
    brief = execute(**_arguments(until="brief"), outputs=root / "runs", run_id="to-brief")
    full = execute(**_arguments(), outputs=root / "runs", run_id="to-render")
    assert brief.status == "COMPLETED" and full.status in ("COMPLETED", "DEGRADED")
    so_seed = freeze(brief.run_dir, "so", root)
    rk_seed = freeze(full.run_dir, "rk", root)
    yield Probe(root, brief, full, so_seed, rk_seed)


def _files(run_dir: Path) -> list[str]:
    return sorted(p.relative_to(run_dir).as_posix() for p in run_dir.rglob("*") if p.is_file())


def _listed(name: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch(name, pattern) for pattern in patterns)


def _keys(run_dir: Path) -> set[str]:
    manifest = RunManifest.model_validate_json((run_dir / "run_manifest.json").read_text("utf-8"))
    return {k for k in checkpoint_values(run_dir, manifest.run_id) if not k.startswith("__")}


def test_the_seed_lists_hold_every_key_and_file_before_each_point(probe: Probe) -> None:
    research_files = SEED_FILES["research"] + RUN_FILES
    assert [f for f in _files(probe.brief.run_dir) if not _listed(f, research_files)] == []
    assert _keys(probe.brief.run_dir) <= set(SEED_KEYS["research"])
    risk_files = SEED_FILES["risk"] + LATER_FILES + RUN_FILES
    assert [f for f in _files(probe.full.run_dir) if not _listed(f, risk_files)] == []
    assert _keys(probe.full.run_dir) <= set(SEED_KEYS["risk"]) | set(LATER_KEYS)
    assert not set(SEED_KEYS["risk"]) & set(LATER_KEYS)
    assert not [
        f
        for f in _files(probe.full.run_dir)
        if _listed(f, SEED_FILES["risk"]) and _listed(f, LATER_FILES)
    ]


def test_a_research_seed_reaches_render_with_the_seeds_requirements_and_no_extract_call(
    probe: Probe,
) -> None:
    result = execute(
        **_arguments(),
        outputs=probe.root / "seeded",
        run_id="so-seeded",
        seed_run=probe.so_seed,
        seed_from="research",
    )
    assert result.status in ("COMPLETED", "DEGRADED"), result.reason
    nodes = {entry.node for entry in read_ledger(result.run_dir / "ledger.jsonl")}
    assert nodes and not nodes & {"triage", "extract", "consolidate", "brief"}
    for name in ("requirements.jsonl", "passages.jsonl", "brief.json"):
        assert (result.run_dir / name).read_bytes() == (probe.so_seed / name).read_bytes(), name
    assert (result.run_dir / "solution_summary.md").exists()
    manifest = RunManifest.model_validate_json(
        (result.run_dir / "run_manifest.json").read_text("utf-8")
    )
    assert manifest.seed is not None and manifest.seed.seed_from == "research"
    assert manifest.seed.sha256.startswith("sha256:")
    assert manifest.seed.extraction["extract_prompt"] == "extract"
    assert manifest.run_args["seed_from"] == "research"


def test_a_risk_seed_makes_no_call_before_risk(probe: Probe) -> None:
    result = execute(
        **_arguments(),
        outputs=probe.root / "seeded",
        run_id="rk-seeded",
        seed_run=probe.rk_seed,
        seed_from="risk",
    )
    assert result.status in ("COMPLETED", "DEGRADED"), result.reason
    nodes = {entry.node for entry in read_ledger(result.run_dir / "ledger.jsonl")}
    assert nodes and nodes <= {"risk", "draft"}, nodes
    for pattern in SEED_FILES["risk"]:
        for source in probe.rk_seed.glob(pattern):
            if source.is_file():
                copied = result.run_dir / source.relative_to(probe.rk_seed)
                assert copied.read_bytes() == source.read_bytes(), copied.name


def _copy(seed: Path, where: Path) -> Path:
    target = where / seed.name
    shutil.copytree(seed, target)
    return target


def test_a_seed_with_another_prompt_is_refused_before_the_run_folder_exists(
    probe: Probe, tmp_path: Path
) -> None:
    seed = _copy(probe.so_seed, tmp_path)
    path = seed / "run_manifest.json"
    manifest = RunManifest.model_validate_json(path.read_text("utf-8"))
    manifest.prompt_hashes["triage"] = "sha256:" + "0" * 64
    path.write_text(manifest.model_dump_json(), encoding="utf-8")
    write_hashes(seed)  # a seed frozen with another triage prompt
    with pytest.raises(Refused, match="triage"):
        execute(
            **_arguments(),
            outputs=tmp_path / "runs",
            run_id="stale",
            seed_run=seed,
            seed_from="research",
        )
    assert not (tmp_path / "runs" / "stale").exists()


def test_a_changed_seed_file_fails_its_hashes(probe: Probe, tmp_path: Path) -> None:
    seed = _copy(probe.so_seed, tmp_path)
    with (seed / "requirements.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("\n")
    with pytest.raises(Refused, match="requirements.jsonl changed"):
        check_seed(seed, "research", {})
    (seed / SEED_HASHES).unlink()
    with pytest.raises(Refused, match="bidwright seed"):
        check_seed(seed, "research", {})


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"seed_from": "risk", "until": "brief"}, "runs to one of"),
        ({"seed_from": None}, "both seed_run and seed_from"),
        ({"extract_context": "bare"}, "keeps its seed's extraction"),
    ],
)
def test_a_seeded_run_is_refused_when_its_settings_do_not_fit(
    probe: Probe, tmp_path: Path, changes: dict[str, Any], message: str
) -> None:
    arguments = _arguments(seed_run=probe.so_seed, seed_from="research") | changes
    with pytest.raises(Refused, match=message):
        execute(**arguments, outputs=tmp_path, run_id="refused")


def _ended(tmp_path: Path, status: str) -> Path:
    run_dir = tmp_path / f"run-{status.lower()}"
    run_dir.mkdir()
    manifest = RunManifest(
        run_id=run_dir.name,
        commit="test",
        profile="free",
        models={},
        started=datetime(2026, 11, 6, tzinfo=UTC),
        status=status,  # type: ignore[arg-type]
        totals=RunTotals(),
    )
    (run_dir / "run_manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    return run_dir


@pytest.mark.parametrize("status", ["POLICY_BLOCKED", "BUDGET_EXCEEDED", "RUNNING", "STOPPED"])
def test_bidwright_seed_refuses_a_run_that_failed_or_has_not_ended(
    tmp_path: Path, status: str
) -> None:
    with pytest.raises(Refused, match=status):
        freeze(_ended(tmp_path, status), "x", tmp_path)


def test_bidwright_seed_freezes_a_finished_run_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = _ended(tmp_path, "COMPLETED")
    (run_dir / "requirements.jsonl").write_text("{}\n", encoding="utf-8")
    argv = ["seed", str(run_dir), "--name", "s1", "--outputs", str(tmp_path / "out")]
    assert cli.main(argv) == 0
    seed = tmp_path / "out" / "seeds" / "s1"
    assert "Seed frozen" in capsys.readouterr().out
    lines = (seed / SEED_HASHES).read_text("utf-8").splitlines()
    assert [line.split("  ")[1] for line in lines] == ["requirements.jsonl", "run_manifest.json"]
    assert cli.main(argv) == 2, "the name is taken"
