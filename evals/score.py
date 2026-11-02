"""Score one frozen run against its gold: the 0a scorecard.

Reads the run folder only and never writes into it. Gold must match the hash recorded in
`evals/gold/MANIFEST.sha256`, so no score is ever taken against gold that changed after it
was frozen. Results go to `evals/results/runs/<run>/`.
"""

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from bidwright.obs.ledger import read_ledger
from bidwright.schemas import ApproachItem, Passage, Requirement, Risk, RunManifest
from evals.matcher import GoldClause, Match, gold_clauses, match

ROOT = Path(__file__).resolve().parents[1]
GOLD_DIR = ROOT / "evals" / "gold"
RESULTS_DIR = ROOT / "evals" / "results" / "runs"


class GoldChanged(Exception):
    """The gold file no longer matches its recorded hash."""


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def gold_for(doc_id: str, gold_dir: Path = GOLD_DIR) -> tuple[str, list[dict[str, Any]]]:
    """The corpus whose gold doc id prefixes the run's doc id, after checking its hash."""
    manifest = gold_dir / "MANIFEST.sha256"
    recorded: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, _, name = line.partition("  ")
        recorded[name.strip()] = digest
    for path in sorted(gold_dir.glob("*/gold.jsonl")):
        lines = _jsonl(path)
        if lines and doc_id.startswith(lines[0]["doc_id"]):
            name = path.relative_to(gold_dir).as_posix()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if recorded.get(name) != digest:
                raise GoldChanged(f"{name} does not match MANIFEST.sha256; version the change")
            return path.parent.name, lines
    raise LookupError(f"no gold for document {doc_id}")


def seed_hits(
    seeds: list[dict[str, Any]],
    risks: list[Risk],
    clauses: list[GoldClause],
    passages: dict[str, Passage],
) -> dict[str, bool]:
    """A risk finds a seed when it cites an anchor passage and has a term from each group."""
    by_id = {c.gold_id: c for c in clauses}
    hits = {}
    for seed in seeds:
        anchors = {
            p.id
            for p in passages.values()
            for gold_id in seed["anchors"]
            if gold_id in by_id
            and p.start < by_id[gold_id].span[1]
            and by_id[gold_id].span[0] < p.end
        }
        found = False
        for risk in risks:
            text = " ".join(
                [risk.condition, risk.event, risk.effect, risk.trigger, *risk.responses]
            ).lower()
            groups = all(
                any(re.search(rf"\b{re.escape(term.lower())}", text) for term in group)
                for group in seed["terms"]
            )
            if groups and anchors & set(risk.evidence_src_ids):
                found = True
                break
        hits[seed["gold_id"]] = found
    return hits


def score_run(run_dir: Path, gold_dir: Path = GOLD_DIR) -> dict[str, Any]:
    frozen = (run_dir / "frozen.txt").read_text(encoding="utf-8")
    passages = {p["id"]: Passage.model_validate(p) for p in _jsonl(run_dir / "passages.jsonl")}
    records = [Requirement.model_validate(r) for r in _jsonl(run_dir / "requirements.jsonl")]
    doc_id = next(iter(passages.values())).doc_id
    corpus, lines = gold_for(doc_id, gold_dir)
    clauses = gold_clauses(lines, frozen)
    result: Match = match(records, clauses, passages)
    requirements = [c for c in clauses if c.kind == "requirement"]
    mandatory = [c for c in requirements if c.mandatory]
    hazards = [c for c in requirements if c.hazard]
    predictions = [r for r in records if r.disposition in ("BINDING", "OPTIONAL")]
    verified = [
        r for r in predictions if r.quote_status in ("VERBATIM_VERIFIED", "NORMALIZED_MATCH")
    ]
    true_positive = len(verified) - len(result.unmatched) - len(result.false_positive)
    approach_file = run_dir / "approach.json"
    approach = (
        [
            ApproachItem.model_validate(a)
            for a in json.loads(approach_file.read_text(encoding="utf-8"))["items"]
        ]
        if approach_file.exists()
        else []
    )
    mapped = {i for item in approach for i in item.requirement_ids}
    binding = [r for r in records if r.disposition == "BINDING"]
    risks = [Risk.model_validate(r) for r in _jsonl(run_dir / "risks.jsonl")]
    seeds = seed_hits(
        [line for line in lines if line["kind"] == "risk_seed"], risks, clauses, passages
    )
    manifest = RunManifest.model_validate_json(
        (run_dir / "run_manifest.json").read_text(encoding="utf-8")
    )
    ledger = read_ledger(run_dir / "ledger.jsonl")
    statuses = [r.quote_status for r in predictions]
    return {
        "run_id": manifest.run_id,
        "corpus": corpus,
        "gold_version": lines[0]["gold_version"],
        "status": manifest.status,
        "missed_mandatory": sorted(
            c.gold_id for c in mandatory if c.gold_id not in result.captured
        ),
        "missed_mandatory_strict": sorted(
            c.gold_id for c in mandatory if c.gold_id not in result.strict
        ),
        "missed_hazards": sorted(c.gold_id for c in hazards if c.gold_id not in result.captured),
        "mandatory_total": len(mandatory),
        "hazards_total": len(hazards),
        "recall": round(len(result.captured) / len(requirements), 4) if requirements else None,
        "precision_low": round(true_positive / len(verified), 4) if verified else None,
        "precision_high": round((true_positive + len(result.unmatched)) / len(verified), 4)
        if verified
        else None,
        "verbatim_rate": round(statuses.count("VERBATIM_VERIFIED") / len(statuses), 4)
        if statuses
        else None,
        "normalized_rate": round(statuses.count("NORMALIZED_MATCH") / len(statuses), 4)
        if statuses
        else None,
        "merged": sorted(result.merged),
        "duplicate": sorted(result.duplicate),
        "false_positive_on_background": sorted(result.false_positive),
        "unmatched": result.unmatched,
        "approach_mapping": round(len([r for r in binding if r.id in mapped]) / len(binding), 4)
        if binding
        else None,
        "risk_seed_recall": round(sum(seeds.values()) / len(seeds), 4) if seeds else None,
        "risk_seeds": seeds,
        "requests": manifest.totals.requests,
        "tokens": manifest.totals.tokens_in
        + manifest.totals.tokens_out
        + manifest.totals.tokens_thinking,
        "cost_usd": manifest.totals.cost_usd,
        "shadow_cost_usd": manifest.totals.shadow_cost_usd,
        "models": sorted({entry.model for entry in ledger}),
    }


def scorecard(scores: dict[str, Any]) -> str:
    def rate(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.0%}"

    def row(label: str, value: object) -> str:
        return f"  {label:<50} {value}"

    s = scores
    total = s["mandatory_total"]
    missed = f"{len(s['missed_mandatory'])}/{total}, {len(s['missed_mandatory_strict'])}/{total}"
    found = [seed for seed, hit in s["risk_seeds"].items() if hit]
    lines = [
        f"BIDWRIGHT SCORECARD  run {s['run_id']} | gold {s['corpus']} v{s['gold_version']}"
        f" | {s['status']}",
        "HEADLINE",
        row(
            "Missed mandatory requirements (relaxed / strict)",
            f"{missed}  {' '.join(s['missed_mandatory'])}",
        ),
        row("Missed submission hazards", f"{len(s['missed_hazards'])}/{s['hazards_total']}"),
        "REQUIREMENTS",
        row(
            "Recall / precision range",
            f"{rate(s['recall'])} / {rate(s['precision_low'])}-{rate(s['precision_high'])}",
        ),
        row(
            "Merged / duplicate / on background / unmatched",
            f"{len(s['merged'])} / {len(s['duplicate'])}"
            f" / {len(s['false_positive_on_background'])} / {len(s['unmatched'])}",
        ),
        "GROUNDING",
        row(
            "VERBATIM_VERIFIED / NORMALIZED_MATCH rate",
            f"{rate(s['verbatim_rate'])} / {rate(s['normalized_rate'])}",
        ),
        "SOLUTION",
        row("Binding requirements mapped to approach", rate(s["approach_mapping"])),
        row("Risk seeds found", f"{rate(s['risk_seed_recall'])}  {' '.join(found)}"),
        "COST",
        row(
            "Requests / tokens / cost / shadow cost",
            f"{s['requests']} / {s['tokens']} / ${s['cost_usd']} / ${s['shadow_cost_usd']}",
        ),
        row("Models", ", ".join(s["models"])),
    ]
    return "\n".join(lines) + "\n"


def write_results(scores: dict[str, Any], results_dir: Path = RESULTS_DIR) -> Path:
    out = results_dir / scores["run_id"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "scores.json").write_text(
        json.dumps(scores, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    (out / "scorecard.md").write_text(
        "```text\n" + scorecard(scores) + "```\n", encoding="utf-8", newline="\n"
    )
    with (out / "adjudication.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["record_id", "verdict", "note"])
        for record_id in scores["unmatched"]:
            writer.writerow([record_id, "", ""])
    return out
