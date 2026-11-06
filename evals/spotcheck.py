"""`bidwright-eval spotcheck`: the owner's check of 10 assessments (CH-93; Iteration 3, step
16; design section 4.13).

    bidwright-eval spotcheck --runs DIR [DIR ...] --n 10 --seed INT
    bidwright-eval spotcheck --score

The draw pools every assessment of the named runs whose claim the run holds, in run and claim
order, and takes `n` with `random.Random(seed)`, so the same runs and seed give the same draw.
Each row holds the claim, the knowledge-base records it and the assessment cite, the
disposition, the assessor's reason and `owner_label: null`, which the owner sets to `right`
or `wrong`; the rows go to `evals/labels/assess_spotcheck.jsonl`, and a file already there is
never overwritten, since it may hold the owner's labels. `--score` reports the share of the
labeled rows marked `right`, beside each run's joint error of `decide` and `assess` when the
run can be scored.
"""

import json
import random
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from bidwright.kb import KnowledgeBase, load_kb
from bidwright.schemas import CapabilityClaim, EvidenceAssessment
from evals.score import ROOT

LABELS = ROOT / "evals" / "labels" / "assess_spotcheck.jsonl"
LABEL_VALUES = ("right", "wrong")


class SpotcheckRefused(ValueError):
    """The draw or the score cannot be made as asked."""


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _texts(kb: KnowledgeBase) -> dict[str, str]:
    """Each knowledge-base record's text, as the assessor's evidence shows it."""
    found: dict[str, str] = {}
    for c in kb.capabilities:
        found[c.id] = f"{c.name}: {c.summary}"
    for s in kb.case_studies:
        found[s.id] = f"{s.client} ({s.sector}, {s.year}): {s.summary}"
    for cert in kb.certifications:
        found[cert.id] = f"{cert.name}, held by {cert.holder}, valid until {cert.valid_until}"
    for r in kb.roles:
        found[r.id] = f"{r.title}: {r.summary}"
    return found


def draw(
    runs: Sequence[Path], n: int, seed: int, kb: KnowledgeBase | None = None
) -> list[dict[str, Any]]:
    texts = _texts(kb or load_kb())
    pool: list[dict[str, Any]] = []
    for run in sorted(runs, key=lambda p: p.name):
        claims = {
            c.id: c for c in map(CapabilityClaim.model_validate, _jsonl(run / "claims.jsonl"))
        }
        assessments = [
            EvidenceAssessment.model_validate(row) for row in _jsonl(run / "assessments.jsonl")
        ]
        for assessment in sorted(assessments, key=lambda a: a.claim_id):
            claim = claims.get(assessment.claim_id)
            if claim is None:
                continue
            cited = list(dict.fromkeys([*claim.evidence_ids, *assessment.supporting_ids]))
            pool.append(
                {
                    "run": run.as_posix(),
                    "claim_id": claim.id,
                    "need_id": claim.need_id,
                    "claim": claim.text,
                    "evidence": [{"id": i, "text": texts.get(i, "")} for i in cited],
                    "disposition": assessment.disposition,
                    "reason": assessment.reason,
                    "assessor": assessment.assessor.model if assessment.assessor else None,
                    "owner_label": None,
                }
            )
    if len(pool) < n:
        raise SpotcheckRefused(f"the runs hold {len(pool)} assessments, fewer than {n}")
    return random.Random(seed).sample(pool, n)  # noqa: S311 - a reproducible draw


def write(rows: Sequence[dict[str, Any]], path: Path = LABELS) -> Path:
    if path.exists():
        raise SpotcheckRefused(
            f"{path} already exists and may hold the owner's labels; move it before drawing again"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )
    return path


def score(path: Path = LABELS) -> dict[str, Any]:
    rows = _jsonl(path)
    if not rows:
        raise SpotcheckRefused(f"no spot-check rows in {path}; draw them first")
    bad = [r["claim_id"] for r in rows if r.get("owner_label") not in (None, *LABEL_VALUES)]
    if bad:
        raise SpotcheckRefused(f"owner_label takes right or wrong; check {', '.join(bad)}")
    labeled = [r for r in rows if r.get("owner_label") in LABEL_VALUES]
    right = sum(1 for r in labeled if r["owner_label"] == "right")
    return {
        "rows": len(rows),
        "labeled": len(labeled),
        "right": right,
        "share_right": round(right / len(labeled), 4) if labeled else None,
        "runs": sorted({r["run"] for r in rows}),
    }


__all__ = ["LABELS", "SpotcheckRefused", "draw", "score", "write"]
