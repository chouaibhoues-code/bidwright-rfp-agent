"""Read-only data loader for the Streamlit Run, Review and Ops pages (`WP-3.6`, `CH-94`).

Reads a run's files under `outputs/` into `bidwright.schemas` models and reads scores and
`keep_or_drop` ladder reports from `evals/results/` when they exist. Writes no files.
"""

import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from openpyxl import load_workbook

from bidwright.obs.ledger import read_ledger, totals_of
from bidwright.preflight import HOME
from bidwright.schemas import (
    ApproachItem,
    BidSignal,
    CapabilityMap,
    ClarificationQuestion,
    DomainBrief,
    GateApproval,
    LedgerEntry,
    OpenQuestion,
    OpportunityBrief,
    Requirement,
    Risk,
    RunManifest,
    SolutionManifest,
    SolutionOptions,
    SolutionSummary,
    TechValidation,
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
    """Aggregated ledger metrics for a single group (`node`, `model`, `matrix`) or a run."""

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
class LadderRungRow:
    """One rung's row in a `keep_or_drop` ladder report."""

    rung: str
    comparator: str
    metric: str
    medians: str
    interval: str
    verdict: str
    cost_per_avoided_miss: str
    detail: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "rung": self.rung,
            "comparator": self.comparator,
            "metric": self.metric,
            "medians": self.medians,
            "interval": self.interval,
            "verdict": self.verdict,
            "cost_per_avoided_miss": self.cost_per_avoided_miss,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class LadderReport:
    """A parsed `keep_or_drop` matrix report from `evals/results/<matrix>/report.json`."""

    matrix: str
    gold: str
    rows: list[LadderRungRow]


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
    capability_map: CapabilityMap | None = None
    options: SolutionOptions | None = None
    solution_manifest: SolutionManifest | None = None
    tech_validations: list[TechValidation] = field(default_factory=list)
    gate_text: str | None = None
    gate_approval: GateApproval | None = None
    gate_approval_text: str | None = None
    bid_signal: BidSignal | None = None
    bid_memo_text: str | None = None


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


def load_capability_map(run_dir: Path) -> CapabilityMap | None:
    """Validate `<run_dir>/capability_map.json` into `CapabilityMap`, or None if absent."""
    path = run_dir / "capability_map.json"
    if not path.is_file():
        return None
    return CapabilityMap.model_validate_json(path.read_text(encoding="utf-8"))


def load_options(run_dir: Path) -> SolutionOptions | None:
    """Validate `<run_dir>/options.json` into `SolutionOptions`, or None if absent."""
    path = run_dir / "options.json"
    if not path.is_file():
        return None
    return SolutionOptions.model_validate_json(path.read_text(encoding="utf-8"))


def load_solution_manifest(run_dir: Path) -> SolutionManifest | None:
    """Validate `<run_dir>/manifest.json` into `SolutionManifest`, or None if absent."""
    path = run_dir / "manifest.json"
    if not path.is_file():
        return None
    return SolutionManifest.model_validate_json(path.read_text(encoding="utf-8"))


def load_tech_validations(run_dir: Path) -> list[TechValidation]:
    """Read `<run_dir>/tech_validations.jsonl` into `TechValidation` records."""
    path = run_dir / "tech_validations.jsonl"
    if not path.is_file():
        return []
    return [
        TechValidation.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_gate_text(run_dir: Path) -> str | None:
    """Read `<run_dir>/review/solution_gate.md` as plain text, or None if absent."""
    path = run_dir / "review" / "solution_gate.md"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def load_gate_approval(run_dir: Path) -> tuple[GateApproval | None, str | None]:
    """Validate `<run_dir>/review/solution_gate.approval.yaml` into `GateApproval` and raw text."""
    path = run_dir / "review" / "solution_gate.approval.yaml"
    if not path.is_file():
        return None, None
    raw = path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw)
    if not isinstance(parsed, Mapping):
        return None, raw
    return GateApproval.model_validate(dict(parsed)), raw


def load_bid_signal(run_dir: Path) -> BidSignal | None:
    """Validate `<run_dir>/bid_signal.json` into `BidSignal`, or None if absent."""
    path = run_dir / "bid_signal.json"
    if not path.is_file():
        return None
    return BidSignal.model_validate_json(path.read_text(encoding="utf-8"))


def load_bid_memo_text(run_dir: Path) -> str | None:
    """Read `<run_dir>/bid_memo.md` as plain text, or None if absent."""
    path = run_dir / "bid_memo.md"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def is_allowed_edit_field(
    field_path: str,
    manifest: SolutionManifest | None = None,
) -> bool:
    """Check whether `field_path` is one of section 4.8's allowed gate-edit field paths, by
    the gate's own rule (`blueprint.edit_path_problem`), and, with a manifest, one of its
    fields."""
    from bidwright.graph.blueprint import edit_path_problem

    if edit_path_problem(field_path) is not None:
        return False
    return manifest is None or field_path in allowed_edit_fields(manifest)


def allowed_edit_fields(
    manifest: SolutionManifest | None,
) -> dict[str, tuple[str, Any]]:
    """Return section 4.8's editable field paths mapped to `(kind, current_value)`. A fact's
    `<n>` counts from 1, as the gate and its review file count."""
    if manifest is None:
        return {}
    fields: dict[str, tuple[str, Any]] = {}
    for wp in manifest.work_packages:
        low_days = float(wp.effort.low_days) if wp.effort is not None else 0.0
        high_days = float(wp.effort.high_days) if wp.effort is not None else 0.0
        fields[f"work_packages[{wp.code}].effort.low_days"] = ("float", low_days)
        fields[f"work_packages[{wp.code}].effort.high_days"] = ("float", high_days)
        fields[f"work_packages[{wp.code}].predecessors"] = (
            "predecessors",
            list(wp.predecessors),
        )
        fields[f"work_packages[{wp.code}].scope"] = ("str", wp.scope)
        fields[f"work_packages[{wp.code}].exclusions"] = ("str", wp.exclusions)
        fields[f"work_packages[{wp.code}].acceptance"] = ("str", wp.acceptance)
    for idx, assumption in enumerate(manifest.assumptions, start=1):
        fields[f"assumptions[{idx}].text"] = ("str", assumption.text)
    for idx, rule in enumerate(manifest.ground_rules, start=1):
        fields[f"ground_rules[{idx}].text"] = ("str", rule.text)
    return fields


def build_approve_command(
    run_dir: Path,
    *,
    role: str,
    option_id: str | None = None,
    edits: Sequence[Mapping[str, Any]] | None = None,
    override_reason: str | None = None,
    reject_reason: str | None = None,
    manifest: SolutionManifest | None = None,
) -> tuple[list[str], str | None]:
    """Build the `bidwright approve` argument list and optional stdin YAML for `edits`.

    Raises `ValueError` if `role` is blank, if any edit field path lies outside section 4.8's
    allowed paths, or if incompatible flags are combined.
    """
    clean_role = role.strip()
    if not clean_role:
        raise ValueError("Approver role is required")
    clean_option = (option_id or "").strip() or None
    clean_override = (override_reason or "").strip() or None
    clean_reject = (reject_reason or "").strip() or None
    edit_list = list(edits or [])

    for item in edit_list:
        field_path = str(item.get("field", ""))
        if not is_allowed_edit_field(field_path, manifest):
            raise ValueError(f"Edit field path is not allowed by section 4.8: {field_path!r}")

    cmd = ["bidwright", "approve", str(run_dir), "--role", clean_role]
    if clean_reject is not None:
        if clean_option is not None or edit_list or clean_override is not None:
            raise ValueError("--reject takes no other flag")
        cmd.extend(["--reject", clean_reject])
        return cmd, None

    if clean_option is not None and edit_list:
        raise ValueError("--option does not combine with --edit")

    stdin_text: str | None = None
    if clean_option is not None:
        cmd.extend(["--option", clean_option])
    elif edit_list:
        cmd.extend(["--edit", "-"])
        payload = [{"field": str(item["field"]), "value": item["value"]} for item in edit_list]
        stdin_text = yaml.safe_dump(payload, sort_keys=False)

    if clean_override is not None:
        cmd.extend(["--override", clean_override])
    return cmd, stdin_text


def run_approve(
    cmd: Sequence[str],
    stdin_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `bidwright approve` as a subprocess, passing `stdin_text` on standard input."""
    return subprocess.run(  # noqa: S603
        list(cmd),
        input=stdin_text,
        text=True,
        capture_output=True,
        check=False,
    )


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


def _format_interval(decision: Mapping[str, Any]) -> str:
    raw = decision.get("interval")
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) and len(raw) == 2:
        return f"[{float(raw[0]):g}, {float(raw[1]):g}]"
    if isinstance(raw, Mapping) and "lo" in raw and "hi" in raw:
        return f"[{float(raw['lo']):g}, {float(raw['hi']):g}]"
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if "lo" in decision and "hi" in decision and decision["lo"] is not None:
        return f"[{float(decision['lo']):g}, {float(decision['hi']):g}]"
    return "n/a"


def _format_verdict(decision: Mapping[str, Any]) -> str:
    for key in ("verdict", "result", "decision"):
        val = decision.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    for key in ("kept", "passed"):
        val = decision.get(key)
        if isinstance(val, bool):
            return "keep" if val else "drop"
    return "n/a"


def _format_medians(
    decision: Mapping[str, Any],
    rungs_data: Mapping[str, Any],
) -> str:
    if isinstance(decision.get("medians"), str) and decision["medians"].strip():
        return str(decision["medians"]).strip()
    if isinstance(decision.get("medians"), Mapping):
        return ", ".join(f"{k}={float(v):g}" for k, v in decision["medians"].items())
    rung = str(decision.get("rung", ""))
    metric = str(decision.get("metric", ""))
    parts: list[str] = []
    if isinstance(decision.get("median"), (int, float)) and not isinstance(
        decision.get("median"), bool
    ):
        parts.append(
            f"{metric}={float(decision['median']):g}" if metric else f"{decision['median']:g}"
        )
    rung_stats = rungs_data.get(rung)
    if isinstance(rung_stats, Mapping):
        if not parts and metric and isinstance(rung_stats.get(metric), Mapping):
            med = rung_stats[metric].get("median")
            if isinstance(med, (int, float)):
                parts.append(f"{metric}={float(med):g}")
        for key, stats in rung_stats.items():
            if key == metric or not isinstance(stats, Mapping):
                continue
            med = stats.get("median")
            if isinstance(med, (int, float)):
                parts.append(f"{key}={float(med):g}")
    return ", ".join(parts) if parts else "n/a"


def _format_cost_per_avoided_miss(decision: Mapping[str, Any]) -> str:
    for key in ("cost_per_avoided_miss", "dollars_per_avoided_miss", "cost_per_miss"):
        if key in decision:
            val = decision[key]
            if val is None or val == "n/a":
                return "n/a"
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                return f"${float(val):g}"
            return str(val)
    return "n/a"


def load_ladder_reports(root: Path | None = None) -> list[LadderReport]:
    """Load every `keep_or_drop` matrix report under `evals/results/<matrix>/report.json`."""
    base = results_dir(root)
    if not base.is_dir():
        return []
    reports: list[LadderReport] = []
    for child in sorted(base.iterdir(), key=lambda p: p.name):
        if not child.is_dir() or child.name == "runs":
            continue
        report_path = child / "report.json"
        if not report_path.is_file():
            continue
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not isinstance(data, Mapping):
            continue
        decisions = data.get("decisions")
        if not isinstance(decisions, Sequence):
            continue
        kd_decisions = [
            d
            for d in decisions
            if isinstance(d, Mapping)
            and (
                d.get("kind") == "keep_or_drop"
                or "verdict" in d
                or "interval" in d
                or ("lo" in d and "hi" in d)
            )
        ]
        if not kd_decisions:
            continue
        raw_rungs = data.get("rungs")
        rungs_data: Mapping[str, Any] = raw_rungs if isinstance(raw_rungs, Mapping) else {}
        rows: list[LadderRungRow] = []
        seen_rungs = {str(d.get("rung", "")) for d in kd_decisions}
        first_control = str(
            kd_decisions[0].get("control") or kd_decisions[0].get("compare_to") or ""
        )
        first_metric = str(kd_decisions[0].get("metric", ""))
        if first_control and first_control not in seen_rungs and first_control in rungs_data:
            rows.append(
                LadderRungRow(
                    rung=first_control,
                    comparator="—",
                    metric=first_metric,
                    medians=_format_medians(
                        {"rung": first_control, "metric": first_metric},
                        rungs_data,
                    ),
                    interval="n/a",
                    verdict="control",
                    cost_per_avoided_miss="n/a",
                    detail="control rung",
                )
            )
        for d in kd_decisions:
            comparator = str(d.get("compare_to") or d.get("control") or d.get("comparator") or "—")
            rows.append(
                LadderRungRow(
                    rung=str(d.get("rung", "")),
                    comparator=comparator,
                    metric=str(d.get("metric", "")),
                    medians=_format_medians(d, rungs_data),
                    interval=_format_interval(d),
                    verdict=_format_verdict(d),
                    cost_per_avoided_miss=_format_cost_per_avoided_miss(d),
                    detail=str(d.get("detail", "")),
                )
            )
        reports.append(
            LadderReport(
                matrix=str(data.get("matrix", child.name)),
                gold=str(data.get("gold", "")),
                rows=rows,
            )
        )
    return reports


def load_matrix_totals(root: Path | None = None) -> list[LedgerRow]:
    """Sum each matrix's runs' `ledger.jsonl` files under `outputs/matrices/<matrix>/`."""
    matrices_root = outputs_dir(root) / "matrices"
    if not matrices_root.is_dir():
        return []
    totals: list[LedgerRow] = []
    for matrix_dir in sorted(matrices_root.iterdir(), key=lambda p: p.name):
        if not matrix_dir.is_dir():
            continue
        entries: list[LedgerEntry] = []
        for run_dir in sorted(matrix_dir.iterdir(), key=lambda p: p.name):
            if not run_dir.is_dir():
                continue
            ledger_path = run_dir / "ledger.jsonl"
            if ledger_path.is_file():
                entries.extend(read_ledger(ledger_path))
        if entries:
            totals.append(_summarize_entries(matrix_dir.name, entries))
    return totals


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
    capability_map = load_capability_map(run_dir)
    options = load_options(run_dir)
    solution_manifest = load_solution_manifest(run_dir)
    tech_validations = load_tech_validations(run_dir)
    gate_text = load_gate_text(run_dir)
    gate_approval, gate_approval_text = load_gate_approval(run_dir)
    bid_signal = load_bid_signal(run_dir)
    bid_memo_text = load_bid_memo_text(run_dir)
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
        capability_map=capability_map,
        options=options,
        solution_manifest=solution_manifest,
        tech_validations=tech_validations,
        gate_text=gate_text,
        gate_approval=gate_approval,
        gate_approval_text=gate_approval_text,
        bid_signal=bid_signal,
        bid_memo_text=bid_memo_text,
    )


# --- The run monitor and the record views (ADR-053) -------------------------------------------


def load_events(run_dir: Path) -> list[dict[str, Any]]:
    """The run's `events.jsonl`, oldest first."""
    from bidwright.fileio import read_lines

    return [json.loads(line) for line in read_lines(run_dir / "events.jsonl")]


def load_budget(run_dir: Path) -> dict[str, Any] | None:
    """What the run has spent so far, from `control/budget.json`, or None."""
    path = run_dir / "control" / "budget.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def run_limits(manifest: RunManifest) -> dict[str, float] | None:
    """The run's limits from `config/limits.yaml`, for its tier and profile, or None."""
    from bidwright.config import load_config

    tier = str(manifest.run_args.get("limits") or "dev")
    try:
        limits = load_config().limits.run(tier, manifest.profile)
    except KeyError:
        return None
    return {
        "requests": float(limits.requests),
        "tokens": float(limits.tokens),
        "active_minutes": float(limits.active_minutes),
    }


def load_passages(run_dir: Path) -> dict[str, dict[str, Any]]:
    """The run's passages by id, from `passages.jsonl`."""
    from bidwright.fileio import read_lines

    return {
        row["id"]: row
        for row in (json.loads(line) for line in read_lines(run_dir / "passages.jsonl"))
    }


def extract_batches(run_dir: Path) -> dict[str, str]:
    """Each passage id's extract call, from the calls' context manifests."""
    batches: dict[str, str] = {}
    for path in sorted((run_dir / "context").glob("extract-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for src in data.get("included_src_ids", []):
            batches.setdefault(src, data["call_id"])
    return batches
