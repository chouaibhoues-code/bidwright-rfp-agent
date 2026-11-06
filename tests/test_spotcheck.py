"""The owner's spot-check of 10 assessments (CH-93; Iteration 3, step 16): the same runs and
random seed draw the same 10, a labels file is never overwritten, and `--score` reports the
share labeled right."""

import json
from pathlib import Path

import pytest

from evals import cli
from evals.spotcheck import SpotcheckRefused, draw, score, write


def _run(root: Path, name: str, claims: int) -> Path:
    run = root / name
    run.mkdir(parents=True)
    rows_claims, rows_assessments = [], []
    for n in range(1, claims + 1):
        rows_claims.append(
            {
                "id": f"CL-{n:03d}",
                "need_id": f"RG-{n:03d}",
                "kind": "capability",
                "text": f"The service meets need {n}.",
                "evidence_ids": ["CAP-001"],
                "src_ids": ["SRC-0001"],
            }
        )
        rows_assessments.append(
            {
                "claim_id": f"CL-{n:03d}",
                "disposition": "SUPPORTED" if n % 2 else "UNVERIFIED",
                "reason": "Read against the record.",
                "supporting_ids": ["CAP-001"] if n % 2 else [],
                "called": bool(n % 2),
                "assessor": (
                    {"provider": "cerebras", "model": "gpt-oss-120b", "prompt": "assess@0.1.0"}
                    if n % 2
                    else None
                ),
            }
        )
    for name_, rows in (("claims.jsonl", rows_claims), ("assessments.jsonl", rows_assessments)):
        (run / name_).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return run


def test_the_same_runs_and_seed_draw_the_same_ten(tmp_path: Path) -> None:
    runs = [_run(tmp_path, "a", 8), _run(tmp_path, "b", 7)]
    first = draw(runs, 10, seed=41)
    assert first == draw(list(reversed(runs)), 10, seed=41), "run order does not matter"
    assert first != draw(runs, 10, seed=42)
    assert len({(r["run"], r["claim_id"]) for r in first}) == 10
    row = first[0]
    assert row["owner_label"] is None and row["evidence"][0]["id"] == "CAP-001"
    assert row["evidence"][0]["text"], "the record's text, for the owner to read"
    with pytest.raises(SpotcheckRefused, match="fewer than 20"):
        draw(runs, 20, seed=41)


def test_a_labels_file_is_never_overwritten_and_the_score_counts_labels(tmp_path: Path) -> None:
    runs = [_run(tmp_path, "a", 12)]
    path = write(draw(runs, 10, seed=7), tmp_path / "labels" / "spot.jsonl")
    with pytest.raises(SpotcheckRefused, match="owner's labels"):
        write(draw(runs, 10, seed=7), path)
    rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    for n, row in enumerate(rows):
        row["owner_label"] = "right" if n < 6 else ("wrong" if n < 8 else None)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    result = score(path)
    assert (result["labeled"], result["right"], result["share_right"]) == (8, 6, 0.75)
    rows[0]["owner_label"] = "maybe"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    with pytest.raises(SpotcheckRefused, match="right or wrong"):
        score(path)


def test_the_cli_draws_then_scores(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run = _run(tmp_path, "a", 10)
    labels = tmp_path / "spot.jsonl"
    argv = ["spotcheck", "--runs", str(run), "--n", "10", "--seed", "3", "--labels", str(labels)]
    assert cli.main(argv) == 0 and labels.exists()
    assert cli.main(argv) == 2, "a second draw would overwrite the labels"
    assert cli.main(["spotcheck", "--score", "--labels", str(labels)]) == 0
    assert "0 of 0 labeled assessments right; 10 not labeled yet" in capsys.readouterr().out
