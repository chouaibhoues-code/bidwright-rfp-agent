"""Human review of a run's records (ADR-053): the queue a person works through, and the one
writer of `review/decisions.jsonl`.

The queue orders the records by consequence, as the Master-Plan's Gold review does: the
submission hazards, the mandatory requirements, the contract flags that need legal review,
the hidden text `guard` quarantined (possible requirements), the technology claims, the
risks, the clarification questions, the optional requirements, and last a negative-space
sample, passages no record cites, drawn with a seed from the run id so that every reviewer of
a run sees the same ones. Each item carries the verbatim source the person checks it
against and the hash of the record as shown.

A record takes `accept`, `correct` (the note holds the correction), `reject` or `flag` (for
another person, such as legal); a sampled passage takes `clear` or `missed`, a missed
obligation the extraction lost. Decisions append; the last one for an item counts, and one
whose hash no longer matches the record is stale. Nothing here changes a run's other files,
and its outputs stay `UNREVIEWED_DRAFT`: the sign-off is Iteration 4's `review` gate.
"""

import json
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from bidwright.fileio import read_lines, repair_lines
from bidwright.harness.supervisor import read_manifest
from bidwright.preflight import Refused
from bidwright.schemas import ReviewDecision, ReviewKind, ReviewVerdict

DECISIONS = Path("review") / "decisions.jsonl"
RECORD_VERDICTS: tuple[ReviewVerdict, ...] = ("accept", "correct", "reject", "flag")
PASSAGE_VERDICTS: tuple[ReviewVerdict, ...] = ("clear", "missed")
SAMPLE_SIZE = 10
MIN_PASSAGE_CHARS = 25
KIND_ORDER: tuple[ReviewKind, ...] = (
    "hazard",
    "requirement",
    "contract_flag",
    "quarantine",
    "tech_claim",
    "risk",
    "question",
    "optional",
    "passage",
)
KIND_TITLES = {
    "hazard": "Submission hazards",
    "requirement": "Mandatory requirements",
    "contract_flag": "Contract flags (legal review)",
    "quarantine": "Quarantined hidden text",
    "tech_claim": "Technology claims",
    "risk": "Risks",
    "question": "Clarification questions",
    "optional": "Optional requirements",
    "passage": "Negative-space sample: passages no record cites",
}


class ReviewRefused(Refused):
    """A decision `bidwright review` will not record."""


@dataclass(frozen=True)
class ReviewItem:
    id: str
    kind: ReviewKind
    title: str
    source: str  # the verbatim text the person checks the record against
    src_ids: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)
    sha256: str = ""

    @property
    def verdicts(self) -> tuple[ReviewVerdict, ...]:
        return PASSAGE_VERDICTS if self.kind == "passage" else RECORD_VERDICTS


def _hash(record: Any) -> str:
    text = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"sha256:{sha256(text.encode('utf-8')).hexdigest()}"


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in read_lines(path) if line.strip()]


def _passages(run_dir: Path) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in _rows(run_dir / "passages.jsonl")}


def _source(passages: dict[str, dict[str, Any]], src_ids: Iterable[str]) -> str:
    return "\n".join(passages[s]["text"] for s in src_ids if s in passages)


def _item(kind: ReviewKind, record: dict[str, Any], **fields: Any) -> ReviewItem:
    return ReviewItem(kind=kind, sha256=_hash(record), **fields)


def review_queue(run_dir: Path) -> list[ReviewItem]:
    """Every item of the run a person can review, in the order of consequence."""
    passages = _passages(run_dir)
    items: list[ReviewItem] = []
    requirements = [
        r
        for r in _rows(run_dir / "requirements.jsonl")
        if r.get("disposition") in ("BINDING", "OPTIONAL")
        and r.get("quote_status") in ("VERBATIM_VERIFIED", "NORMALIZED_MATCH")
    ]
    for r in requirements:
        kind: ReviewKind = (
            "hazard" if r.get("hazard") else "requirement" if r["mandatory"] else "optional"
        )
        items.append(
            _item(
                kind,
                r,
                id=r["id"],
                title=r["statement"],
                source=_source(passages, r["src_ids"]) or r["quote"],
                src_ids=list(r["src_ids"]),
                detail={
                    "quote": r["quote"],
                    "modality": r["modality"],
                    "disposition": r["disposition"],
                },
            )
        )
    for flag in _rows(run_dir / "contract_flags.jsonl"):
        items.append(
            _item(
                "contract_flag",
                flag,
                id=flag["id"],
                title=f"{flag.get('category', '')}: {flag.get('why', '')}".strip(": "),
                source=flag.get("quote", ""),
                src_ids=[flag["src_id"]] if flag.get("src_id") else [],
                detail={"status": flag.get("status", "")},
            )
        )
    for hidden in _rows(run_dir / "quarantine.jsonl"):
        items.append(
            _item(
                "quarantine",
                hidden,
                id=hidden["id"],
                title=(
                    f"{hidden.get('kind', '')} in {hidden.get('file', '')},"
                    f" {hidden.get('location', '')}"
                ),
                source=hidden.get("text", ""),
                detail={"chars": hidden.get("chars")},
            )
        )
    items += _tech_items(run_dir)
    for risk in _rows(run_dir / "risks.jsonl"):
        items.append(
            _item(
                "risk",
                risk,
                id=risk["id"],
                title=risk["event"],
                source=_source(passages, risk.get("evidence_src_ids", [])),
                src_ids=list(risk.get("evidence_src_ids", [])),
                detail={
                    "condition": risk["condition"],
                    "effect": risk["effect"],
                    "owner_role": risk["owner_role"],
                    "trigger": risk["trigger"],
                    "responses": risk.get("responses", []),
                },
            )
        )
    for question in _rows(run_dir / "questions.jsonl"):
        items.append(
            _item(
                "question",
                question,
                id=question["id"],
                title=question["text"],
                source=_source(passages, question.get("src_ids", [])),
                src_ids=list(question.get("src_ids", [])),
                detail={
                    "origin": question.get("origin", ""),
                    "requirements": question.get("requirement_ids", []),
                },
            )
        )
    items += _negative_space(run_dir, passages, cited=_cited(run_dir))
    order = {kind: n for n, kind in enumerate(KIND_ORDER)}
    return sorted(items, key=lambda item: order[item.kind])


def _tech_items(run_dir: Path) -> list[ReviewItem]:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        return []
    claims = {
        c["id"]: c for c in json.loads(manifest_path.read_text("utf-8")).get("tech_claims", [])
    }
    verdicts = {v["claim_id"]: v for v in _rows(run_dir / "tech_validations.jsonl")}
    items = []
    for claim_id, claim in claims.items():
        verdict = verdicts.get(claim_id, {})
        record = {"claim": claim, "validation": verdict}
        items.append(
            _item(
                "tech_claim",
                record,
                id=claim_id,
                title=claim["text"],
                source=verdict.get("quote", ""),
                detail={
                    "library": claim.get("library"),
                    "verdict": verdict.get("verdict", "NOT_CHECKED"),
                    "reason": verdict.get("reason", ""),
                },
            )
        )
    return items


def _cited(run_dir: Path) -> set[str]:
    """Every passage a requirement record of any disposition cites, or a rejected one."""
    cited = {s for r in _rows(run_dir / "requirements.jsonl") for s in r.get("src_ids", [])}
    cited |= {s for r in _rows(run_dir / "rejected.jsonl") for s in r.get("src_ids", [])}
    return cited


def _negative_space(
    run_dir: Path, passages: dict[str, dict[str, Any]], cited: set[str]
) -> list[ReviewItem]:
    """A sample of passages no record cites, seeded from the run id (the Master-Plan's rule)."""
    pool = sorted(
        pid
        for pid, p in passages.items()
        if pid not in cited
        and p.get("kind") in ("sentence", "list_item", "table_row")
        and len(p.get("text", "")) >= MIN_PASSAGE_CHARS
    )
    if not pool:
        return []
    run_id = read_manifest(run_dir).run_id if (run_dir / "run_manifest.json").is_file() else ""
    seed = int.from_bytes(sha256(run_id.encode("utf-8")).digest()[:8], "big")
    sampler = random.Random(seed)  # noqa: S311 - a reproducible sample, not a secret
    chosen = sorted(sampler.sample(pool, min(SAMPLE_SIZE, len(pool))))
    return [
        _item(
            "passage",
            passages[pid],
            id=pid,
            title=passages[pid].get("section_path", ""),
            source=passages[pid]["text"],
            src_ids=[pid],
        )
        for pid in chosen
    ]


def read_decisions(run_dir: Path) -> list[ReviewDecision]:
    return [ReviewDecision.model_validate_json(line) for line in read_lines(run_dir / DECISIONS)]


def latest(run_dir: Path) -> dict[str, ReviewDecision]:
    """The decision that counts for each item: its last."""
    return {d.item_id: d for d in read_decisions(run_dir)}


@dataclass
class Progress:
    total: int
    reviewed: int
    stale: int
    by_kind: dict[str, tuple[int, int]]  # kind -> (reviewed, total)
    by_verdict: dict[str, int]


def progress(queue: Sequence[ReviewItem], decisions: dict[str, ReviewDecision]) -> Progress:
    by_kind: dict[str, tuple[int, int]] = {}
    by_verdict: dict[str, int] = {}
    reviewed = stale = 0
    for item in queue:
        done, total = by_kind.get(item.kind, (0, 0))
        decision = decisions.get(item.id)
        current = decision is not None and decision.item_sha256 == item.sha256
        if decision is not None and not current:
            stale += 1
        if decision is not None and current:
            reviewed += 1
            by_verdict[decision.verdict] = by_verdict.get(decision.verdict, 0) + 1
        by_kind[item.kind] = (done + int(current), total + 1)
    return Progress(len(queue), reviewed, stale, by_kind, by_verdict)


def record(
    run_dir: Path,
    entries: Sequence[dict[str, Any]],
    role: str,
    *,
    now: datetime | None = None,
) -> list[ReviewDecision]:
    """Check each `{item, verdict, note}` against the run's queue and append the decisions.
    Refused, with nothing written: a running run, an unknown item, a verdict the item's kind
    does not take, a `correct` with no correction in its note, and an empty role."""
    if not role.strip():
        raise ReviewRefused("a decision names the reviewer's role, never a name")
    if (run_dir / "run_manifest.json").is_file() and read_manifest(run_dir).status == "RUNNING":
        raise ReviewRefused("the run is RUNNING; review it once it has stopped or finished")
    queue = {item.id: item for item in review_queue(run_dir)}
    stamp = now or datetime.now(UTC)
    decisions = []
    for entry in entries:
        item = queue.get(str(entry.get("item", "")))
        if item is None:
            raise ReviewRefused(f"{entry.get('item')!r} is no item of this run's review queue")
        verdict = cast(ReviewVerdict, str(entry.get("verdict", "")))
        if verdict not in item.verdicts:
            raise ReviewRefused(
                f"{item.id} is a {item.kind}, which takes {', '.join(item.verdicts)},"
                f" not {verdict!r}"
            )
        note = str(entry.get("note") or "").strip()
        if verdict == "correct" and not note:
            raise ReviewRefused(f"{item.id}: a correction holds the corrected text in its note")
        decisions.append(
            ReviewDecision(
                item_id=item.id,
                kind=item.kind,
                verdict=verdict,
                role=role.strip(),
                note=note,
                decided=stamp,
                item_sha256=item.sha256,
            )
        )
    path = run_dir / DECISIONS
    path.parent.mkdir(parents=True, exist_ok=True)
    repair_lines(path)
    with path.open("a", encoding="utf-8", newline="\n") as out:
        for decision in decisions:
            out.write(decision.model_dump_json() + "\n")
    return decisions


__all__ = [
    "DECISIONS",
    "KIND_ORDER",
    "KIND_TITLES",
    "PASSAGE_VERDICTS",
    "RECORD_VERDICTS",
    "Progress",
    "ReviewItem",
    "ReviewRefused",
    "latest",
    "progress",
    "read_decisions",
    "record",
    "review_queue",
]
