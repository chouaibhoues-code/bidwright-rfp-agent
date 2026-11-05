"""Read-only data loader for the Streamlit Run, Review and Ops pages (`WP-3.6`, `CH-94`).

Reads a run's files under `outputs/` into `bidwright.schemas` models and reads scores from
`evals/results/runs/<run>/` when they exist. Writes no files.
"""

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from bidwright.obs.ledger import read_ledger, totals_of
from bidwright.preflight import HOME
from bidwright.schemas import (
    ApproachItem,
    ClarificationQuestion,
    DomainBrief,
    LedgerEntry,
    OpenQuestion,
    OpportunityBrief,
    Requirement,
    Risk,
    RunManifest,
    SolutionSummary,
)


@dataclass(frozen=True)
class SummaryBundle:
    """The parsed records of `solution_summary.json`."""

    summary: SolutionSummary
    requirements: list[Requirement]
    hazards: list[Requirement]
    binding: list[Requirement]
    optional: list[Requirement]
    approach: list[ApproachItem]
    unmapped_requirement_ids: list[str]
    risks: list[Risk]
    open_questions: list[OpenQuestion]
    brief_questions: list[ClarificationQuestion]
    brief: OpportunityBrief | None
    domain_brief: DomainBrief | None


@dataclass(frozen=True)
class LedgerRow:
    """Aggregated ledger metrics for a single group (`node` or `model`) or the whole run."""

    group: str
    requests: int
    tokens_in: int
    tokens_out: int
    tokens_cached: int
    tokens_thinking: int
    cost_usd: float
    shadow_cost_usd: float
    latency_ms: int

    def as_dict(self, label: str = "Group") -> dict[str, str | int | float]:
        return {
            label: self.group,
            "requests": self.requests,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "tokens_cached": self.tokens_cached,
            "tokens_thinking": self.tokens_thinking,
            "cost_usd": self.cost_usd,
            "shadow_cost_usd": self.shadow_cost_usd,
            "latency_ms": self.latency_ms,
        }


@dataclass(frozen=True)
class RunScores:
    """Scores and scorecard text from `evals/results/runs/<run>/`, when present."""

    scores: dict[str, Any] | None
    scorecard_text: str | None


@dataclass(frozen=True)
class RunData:
    """Everything the three UI pages read for one run folder."""

    run_dir: Path
    manifest: RunManifest
    summary_bundle: SummaryBundle | None
    compliance_rows: list[dict[str, str | int]]
    quarantine_text: str | None
    ledger: list[LedgerEntry]
    ledger_totals: LedgerRow
    by_node: list[LedgerRow]
    by_model: list[LedgerRow]
    scores: RunScores
    has_spans: bool


def outputs_dir(override: Path | None = None) -> Path:
    """Return the root folder searched for runs (`BIDWRIGHT_OUTPUTS` or `HOME / 'outputs'`)."""
    if override is not None:
        return override
    env = os.environ.get("BIDWRIGHT_OUTPUTS", "").strip()
    return Path(env) if env else HOME / "outputs"


def results_dir(override: Path | None = None) -> Path:
    """Return the root folder searched for evaluation results (`BIDWRIGHT_RESULTS` or default)."""
    if override is not None:
        return override
    env = os.environ.get("BIDWRIGHT_RESULTS", "").strip()
    return Path(env) if env else HOME / "evals" / "results"


def list_runs(root: Path | None = None) -> list[Path]:
    """List run folders under `root` that hold a `run_manifest.json`, newest first."""
    base = outputs_dir(root)
    if not base.is_dir():
        return []
    if (base / "run_manifest.json").is_file():
        return [base]
    found: list[Path] = []
    for child in base.iterdir():
        if child.is_dir() and (child / "run_manifest.json").is_file():
            found.append(child)
        elif child.is_dir() and child.name == "matrices":
            for matrix_dir in child.iterdir():
                if not matrix_dir.is_dir():
                    continue
                for sub in matrix_dir.iterdir():
                    if sub.is_dir() and (sub / "run_manifest.json").is_file():
                        found.append(sub)
    return sorted(found, key=lambda p: p.name, reverse=True)


def load_manifest(run_dir: Path) -> RunManifest:
    """Validate `<run_dir>/run_manifest.json` into `RunManifest`."""
    raw = (run_dir / "run_manifest.json").read_text(encoding="utf-8")
    return RunManifest.model_validate_json(raw)


def load_summary_bundle(run_dir: Path) -> SummaryBundle | None:
    """Validate `<run_dir>/solution_summary.json` into `schemas.py` models, or None if absent."""
    path = run_dir / "solution_summary.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    summary = SolutionSummary.model_validate(data["summary"])
    requirements = [Requirement.model_validate(r) for r in data.get("requirements", [])]
    by_id = {r.id: r for r in requirements}
    hazards = [by_id[rid] for rid in summary.hazards if rid in by_id]
    binding = [
        by_id[rid]
        for rid in summary.requirements
        if rid in by_id and by_id[rid].disposition == "BINDING"
    ]
    optional = [
        by_id[rid]
        for rid in summary.requirements
        if rid in by_id and by_id[rid].disposition == "OPTIONAL"
    ]
    approach = [ApproachItem.model_validate(a) for a in data.get("approach", [])]
    unmapped = [str(rid) for rid in data.get("unmapped_requirement_ids", [])]
    risks = [Risk.model_validate(r) for r in data.get("risks", [])]
    brief_raw = data.get("brief")
    brief = OpportunityBrief.model_validate(brief_raw) if brief_raw is not None else None
    domain_raw = data.get("domain_brief")
    domain_brief = DomainBrief.model_validate(domain_raw) if domain_raw is not None else None
    brief_questions = list(brief.questions) if brief is not None else []
    return SummaryBundle(
        summary=summary,
        requirements=requirements,
        hazards=hazards,
        binding=binding,
        optional=optional,
        approach=approach,
        unmapped_requirement_ids=unmapped,
        risks=risks,
        open_questions=list(summary.open_questions),
        brief_questions=brief_questions,
        brief=brief,
        domain_brief=domain_brief,
    )


def load_compliance_matrix(run_dir: Path) -> list[dict[str, str | int]]:
    """Read the `Compliance matrix` sheet of `<run_dir>/compliance_matrix.xlsx` as plain rows."""
    path = run_dir / "compliance_matrix.xlsx"
    if not path.is_file():
        return []
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = (
            wb["Compliance matrix"] if "Compliance matrix" in wb.sheetnames else wb.worksheets[0]
        )
        rows_iter = sheet.iter_rows(values_only=True)
        header_row = next(rows_iter, None)
        if not header_row:
            return []
        headers = [
            str(cell) if cell is not None else f"col_{i}" for i, cell in enumerate(header_row)
        ]
        out: list[dict[str, str | int]] = []
        for row in rows_iter:
            if row is None or all(cell is None or cell == "" for cell in row):
                continue
            record: dict[str, str | int] = {}
            for key, value in zip(headers, row, strict=False):
                if isinstance(value, int) and not isinstance(value, bool):
                    record[key] = value
                elif value is None:
                    record[key] = ""
                else:
                    record[key] = str(value)
            out.append(record)
        return out
    finally:
        wb.close()


def load_quarantine_text(run_dir: Path) -> str | None:
    """Read `<run_dir>/review/quarantine.md` as plain text, or None if absent."""
    path = run_dir / "review" / "quarantine.md"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _summarize_entries(group: str, entries: Sequence[LedgerEntry]) -> LedgerRow:
    summed = totals_of(entries, active_seconds=0.0)
    return LedgerRow(
        group=group,
        requests=summed.requests,
        tokens_in=summed.tokens_in,
        tokens_out=summed.tokens_out,
        tokens_cached=summed.tokens_cached,
        tokens_thinking=summed.tokens_thinking,
        cost_usd=summed.cost_usd,
        shadow_cost_usd=summed.shadow_cost_usd,
        latency_ms=sum(e.latency_ms for e in entries),
    )


def aggregate_ledger(entries: Sequence[LedgerEntry], by: str) -> list[LedgerRow]:
    """Group `entries` by `'node'` or `'model'` in first-seen order and sum their metrics."""
    buckets: dict[str, list[LedgerEntry]] = {}
    for entry in entries:
        key = str(getattr(entry, by))
        buckets.setdefault(key, []).append(entry)
    return [_summarize_entries(group, group_entries) for group, group_entries in buckets.items()]


def load_scores(run_dir: Path, manifest: RunManifest, root: Path | None = None) -> RunScores:
    """Load `scores.json` and `scorecard.md` from `evals/results/runs/<run>/` when they exist."""
    base = results_dir(root) / "runs"
    candidates = [base / run_dir.name]
    if manifest.run_id != run_dir.name:
        candidates.append(base / manifest.run_id)
    for folder in candidates:
        scores_path = folder / "scores.json"
        card_path = folder / "scorecard.md"
        if scores_path.is_file() or card_path.is_file():
            scores = (
                json.loads(scores_path.read_text(encoding="utf-8"))
                if scores_path.is_file()
                else None
            )
            scorecard = card_path.read_text(encoding="utf-8") if card_path.is_file() else None
            return RunScores(scores=scores, scorecard_text=scorecard)
    return RunScores(scores=None, scorecard_text=None)


def load_run_data(
    run_dir: Path,
    *,
    results_root: Path | None = None,
) -> RunData:
    """Load all artifacts for `run_dir` without writing any file."""
    manifest = load_manifest(run_dir)
    summary_bundle = load_summary_bundle(run_dir)
    compliance_rows = load_compliance_matrix(run_dir)
    quarantine_text = load_quarantine_text(run_dir)
    ledger = read_ledger(run_dir / "ledger.jsonl")
    ledger_totals = _summarize_entries("total", ledger)
    by_node = aggregate_ledger(ledger, "node")
    by_model = aggregate_ledger(ledger, "model")
    scores = load_scores(run_dir, manifest, root=results_root)
    has_spans = (run_dir / "spans.jsonl").is_file()
    return RunData(
        run_dir=run_dir,
        manifest=manifest,
        summary_bundle=summary_bundle,
        compliance_rows=compliance_rows,
        quarantine_text=quarantine_text,
        ledger=ledger,
        ledger_totals=ledger_totals,
        by_node=by_node,
        by_model=by_model,
        scores=scores,
        has_spans=has_spans,
    )


def select_run_data() -> RunData | None:
    """Render the sidebar run selector in Streamlit and return the selected `RunData`."""
    import streamlit as st

    runs = list_runs()
    if not runs:
        st.text("No run folders with run_manifest.json found under outputs/.")
        return None
    by_name = {run.name: run for run in runs}
    chosen_name = st.sidebar.selectbox("Run folder", options=list(by_name.keys()), index=0)
    chosen_dir = by_name[chosen_name] if chosen_name in by_name else runs[0]
    return load_run_data(chosen_dir)
