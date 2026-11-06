"""Human review (ADR-053): the queue's order and sources, the negative-space sample, and the one
writer of `review/decisions.jsonl` with its refusals; and `bidwright review` on the CLI."""

import io
import json
import shutil
from pathlib import Path

import pytest

from bidwright import cli
from bidwright.preflight import HOME
from bidwright.review import (
    DECISIONS,
    KIND_ORDER,
    ReviewRefused,
    latest,
    progress,
    record,
    review_queue,
)

DEV_SAMPLE = HOME / "samples" / "dev"


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "dev"
    shutil.copytree(DEV_SAMPLE, folder)
    return folder


def test_the_queue_puts_hazards_first_and_shows_each_record_beside_its_source(
    run_dir: Path,
) -> None:
    queue = review_queue(run_dir)
    kinds = [item.kind for item in queue]
    assert kinds == sorted(kinds, key=KIND_ORDER.index), "the order of consequence"
    assert kinds[0] == "hazard" and kinds[-1] == "passage"
    first = queue[0]
    passages = {
        json.loads(line)["id"]: json.loads(line)["text"]
        for line in (run_dir / "passages.jsonl").read_text("utf-8").splitlines()
    }
    assert first.source == "\n".join(passages[s] for s in first.src_ids)
    assert any(item.kind == "quarantine" for item in queue), "the hidden text guard removed"
    assert all(item.sha256.startswith("sha256:") for item in queue)


def test_the_negative_space_sample_is_the_same_for_every_reviewer_and_cites_nothing(
    run_dir: Path,
) -> None:
    sample = [i.id for i in review_queue(run_dir) if i.kind == "passage"]
    assert sample == [i.id for i in review_queue(run_dir) if i.kind == "passage"]
    cited = {
        s
        for line in (run_dir / "requirements.jsonl").read_text("utf-8").splitlines()
        for s in json.loads(line)["src_ids"]
    }
    assert sample and not set(sample) & cited


def test_record_appends_and_the_last_verdict_counts(run_dir: Path) -> None:
    record(run_dir, [{"item": "REQ-0001", "verdict": "flag", "note": "Ask legal."}], "Bid manager")
    record(run_dir, [{"item": "REQ-0001", "verdict": "accept"}], "Bid director")
    assert len((run_dir / DECISIONS).read_text("utf-8").splitlines()) == 2
    decision = latest(run_dir)["REQ-0001"]
    assert (decision.verdict, decision.role) == ("accept", "Bid director")
    done = progress(review_queue(run_dir), latest(run_dir))
    assert (done.reviewed, done.stale) == (1, 0)


def test_a_rewritten_record_makes_its_verdict_stale(run_dir: Path) -> None:
    record(run_dir, [{"item": "REQ-0001", "verdict": "accept"}], "Bid manager")
    path = run_dir / "requirements.jsonl"
    rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    rows[0]["statement"] = rows[0]["statement"] + " Changed by a resume."
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    done = progress(review_queue(run_dir), latest(run_dir))
    assert (done.reviewed, done.stale) == (0, 1)


@pytest.mark.parametrize(
    ("entry", "role", "problem"),
    [
        ({"item": "REQ-9999", "verdict": "accept"}, "Bid manager", "no item"),
        ({"item": "REQ-0001", "verdict": "missed"}, "Bid manager", "takes accept"),
        ({"item": "REQ-0001", "verdict": "correct"}, "Bid manager", "corrected text"),
        ({"item": "REQ-0001", "verdict": "accept"}, " ", "role"),
    ],
)
def test_record_refuses_and_writes_nothing(
    run_dir: Path, entry: dict[str, str], role: str, problem: str
) -> None:
    with pytest.raises(ReviewRefused, match=problem):
        record(run_dir, [entry], role)
    assert not (run_dir / DECISIONS).exists()


def test_a_running_run_is_not_reviewed(run_dir: Path) -> None:
    path = run_dir / "run_manifest.json"
    data = json.loads(path.read_text("utf-8"))
    data["status"] = "RUNNING"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ReviewRefused, match="RUNNING"):
        record(run_dir, [{"item": "REQ-0001", "verdict": "accept"}], "Bid manager")


def test_bidwright_review_records_from_standard_input_and_prints_progress(
    run_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    stdin = io.StringIO("- {item: REQ-0001, verdict: accept}\n")
    monkeypatch.setattr("sys.stdin", stdin)
    assert cli.main(["review", str(run_dir), "--role", "Bid manager", "--from", "-"]) == 0
    out = capsys.readouterr().out
    assert "Recorded 1 verdicts" in out and "Reviewed 1 of" in out
    assert cli.main(["review", str(run_dir)]) == 0, "with no verdict it prints the queue"
    assert "REQ-0001   accept" in capsys.readouterr().out
    assert cli.main(["review", str(run_dir), "--role", "X", "--item", "REQ-0001"]) == 2


def test_run_takes_a_run_id_and_refuses_one_that_names_a_path() -> None:
    with pytest.raises(SystemExit):
        cli.main(["run", "inputs/dev/dev_rfp.pdf", "--run-id", "../escape"])
