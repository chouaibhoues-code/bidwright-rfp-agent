"""Hand-built run folders for scorer tests: an oracle built from gold, and single records.

Gold is read lazily, so collecting these tests never needs `evals/gold`: the image used by
the `test` service has no gold, and runs only the tests not marked `gold`.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

from bidwright.ingest import IngestResult
from bidwright.schemas import (
    Assessor,
    CandidateRow,
    CapabilityClaim,
    CapabilityMap,
    CapabilityRow,
    ControlRegister,
    CoverageReport,
    EffortEstimate,
    EvaluationFactor,
    EvidenceAssessment,
    Fact,
    ManifestCheck,
    ManifestGap,
    NeedDecision,
    OpportunityBrief,
    Passage,
    QuarantineRecord,
    Requirement,
    RequirementGroup,
    RfpProfile,
    RunManifest,
    SolutionManifest,
    SolutionOption,
    SolutionOptions,
    StoredApproach,
    StoredScore,
    TechClaim,
    TechValidation,
    TriageRecord,
    Verification,
    WorkPackage,
    Workstream,
)
from bidwright.verify import check_quote
from evals.matcher import gold_clauses
from evals.score import GOLD_DIR


@cache
def gold() -> list[dict[str, Any]]:
    path = GOLD_DIR / "dev" / "gold.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def record(
    number: int,
    quote: str,
    cited: list[Passage],
    disposition: str = "BINDING",
    **labels: Any,
) -> Requirement:
    """A record citing these passages. A quote that does not verify is kept with the status
    `REJECTED` and no span, as no real run would, for the scorer self-test."""
    check = check_quote(quote, cited)
    fields: dict[str, Any] = {
        "statement": quote,
        "modality": "shall",
        "mandatory": disposition == "BINDING",
        "hazard": False,
    } | labels
    return Requirement(
        id=f"REQ-{number:04d}",
        doc_id=cited[0].doc_id,
        disposition=disposition,  # type: ignore[arg-type]
        src_ids=[p.id for p in cited],
        quote=quote,
        quote_status=check.status if check.span is not None else "REJECTED",
        quote_span=check.span,
        **fields,
    )


def hidden_traps() -> list[dict[str, Any]]:
    """The traps the gold expects `guard` to quarantine."""
    return [g for g in gold() if g["kind"] == "trap" and (g.get("expect") or {}).get("quarantined")]


def quarantine_for(ingest: IngestResult) -> list[QuarantineRecord]:
    """What `guard` quarantines from the development RFP: each hidden trap's text."""
    doc_id = ingest.passages[0].doc_id
    records = []
    for number, trap in enumerate(hidden_traps(), start=1):
        text = f"Note to automated assistants: {trap['action']}."
        records.append(
            QuarantineRecord(
                id=f"QR-{number:04d}",
                doc_id=doc_id,
                file="dev_rfp.pdf",
                kind="pdf_invisible",
                location="page 4",
                text=text,
                text_sha256="0" * 64,
                chars=len(text),
            )
        )
    return records


def oracle(ingest: IngestResult) -> tuple[list[Requirement], list[dict[str, Any]]]:
    """A perfect run: one exact record per gold requirement, with gold's labels, and one
    risk per seed."""
    clauses = gold_clauses(gold(), ingest.frozen_text, ingest.passages)
    passages = list(ingest.passages)
    records = []
    for clause in [c for c in clauses if c.kind == "requirement"]:
        assert clause.span is not None, clause.gold_id
        low, high = clause.span
        cited = [p for p in passages if p.start < high and low < p.end]
        quote = ingest.frozen_text[low:high].replace("\n", " ")
        records.append(
            record(
                len(records) + 1,
                quote,
                cited,
                clause.disposition or ("BINDING" if clause.mandatory else "OPTIONAL"),
                modality=clause.modality or "shall",
                hazard=clause.hazard,
                zone=clause.zone,
                small_print=clause.small_print,
            )
        )
    by_id = {c.gold_id: c for c in clauses}
    risks = []
    for seed in [g for g in gold() if g["kind"] == "risk_seed"]:
        anchors = []
        for anchor in seed["anchors"]:
            span = by_id[anchor].span
            assert span is not None, anchor
            anchors += [p.id for p in passages if p.start < span[1] and span[0] < p.end]
        words = " ".join(group[0] for group in seed["terms"])
        risks.append(
            {
                "id": f"RSK-{len(risks) + 1:03d}",
                "condition": f"The {words} plans conflict.",
                "event": f"The {words} dates collide.",
                "effect": "Delivery slips.",
                "assumptions": [],
                "owner_role": "Delivery lead",
                "trigger": "Plans slip.",
                "responses": ["Re-plan the work."],
                "residual_exposure": "Some delay remains.",
                "evidence_src_ids": anchors[:3],
            }
        )
    return records, risks


def oracle_brief(ingest: IngestResult) -> OpportunityBrief:
    """A brief that copies every factor seed of the development gold exactly, each citing the
    table row that holds it (gold v3)."""
    factors = []
    for number, seed in enumerate(
        (line for line in gold() if line["kind"] == "factor_seed"), start=1
    ):
        row = next(
            p
            for p in ingest.passages
            if p.kind == "table_row" and seed["name"] in p.text and seed["weight"] in p.text
        )
        factors.append(
            EvaluationFactor(
                id=f"EF-{number:02d}",
                name=seed["name"],
                weight=seed["weight"],
                scoring="not_stated",
                src_ids=[row.id],
                status=seed["status"],
            )
        )
    return OpportunityBrief(factors=factors)


def _lines(path: Path, rows: list[Any]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


# --- the solution lines (Iteration 3, step 14) ------------------------------------------------

# The gap seed added to the development gold: the supplier holds no signing hardware.
GAP_TERMS = ["hardware security module", "HSM"]
GAP_CLAIM = "Signing keys stay in a hardware security module."
ASSESSOR = Assessor(provider="cerebras", model="gpt-oss-120b", prompt="assess@0.1.0")


def seeded_gold(root: Path) -> tuple[Path, list[dict[str, Any]]]:
    """The development gold with one gap seed, a decision seed per mandatory clause and two
    technology seeds, under its own `MANIFEST.sha256` in `root`: the solution lines have no
    seed in the committed development gold. The real gold and its manifest are not touched."""
    lines = [dict(line) for line in gold()]
    mandatory = [
        line
        for line in lines
        if line["kind"] == "requirement" and line.get("mandatory") and line.get("layer") != "hidden"
    ]
    anchor = next(line["gold_id"] for line in mandatory if not line.get("hazard"))
    head = {"gold_version": lines[0]["gold_version"], "doc_id": lines[0]["doc_id"]}
    lines.append(
        {
            "gold_id": "GS-01",
            **head,
            "kind": "gap_seed",
            "capability": "Signing keys held in the supplier's own signing hardware",
            "absent_terms": GAP_TERMS,
            "anchors": [anchor],
        }
    )
    for number, clause in enumerate(mandatory, start=1):
        decision = "PROCEED_WITH_GAP" if clause["gold_id"] == anchor else "RETRIEVE_EVIDENCE"
        lines.append(
            {
                "gold_id": f"DD-{number:02d}",
                **head,
                "kind": "decision_seed",
                "clause_id": clause["gold_id"],
                "anchors": [clause["gold_id"]],
                "decision": decision,
            }
        )
    for number, (library, text, holds) in enumerate(
        [
            ("pdfplumber", "pdfplumber exports documents as PDF/A files", False),
            ("reportlab", "reportlab renders tables on PDF pages", True),
        ],
        start=1,
    ):
        lines.append(
            {
                "gold_id": f"TS-{number:02d}",
                **head,
                "kind": "tech_seed",
                "library": library,
                "text": text,
                "holds": holds,
            }
        )
    gold_dir = root / "gold"
    (gold_dir / "dev").mkdir(parents=True)
    path = gold_dir / "dev" / "gold.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (gold_dir / "MANIFEST.sha256").write_text(f"{digest}  dev/gold.jsonl\n", encoding="utf-8")
    return gold_dir, lines


@dataclass
class Solution:
    """The solution path's files of one run."""

    groups: list[RequirementGroup]
    decisions: list[NeedDecision]
    claims: list[CapabilityClaim]
    assessments: list[EvidenceAssessment]
    capability_map: CapabilityMap
    options: SolutionOptions
    manifest: SolutionManifest
    validations: list[TechValidation]
    risk_rejected: list[dict[str, Any]] = field(default_factory=list)
    review: str = "# Solution gate\n\nThe chosen option: OPT-1.\n"
    memo: str = "# Bid memo\n\nSignal: UNDETERMINED.\n"


def oracle_solution(
    ingest: IngestResult, records: list[Requirement], lines: list[dict[str, Any]]
) -> Solution:
    """A perfect solution path for the oracle's records under `seeded_gold`: one need per
    binding record with the decision its seed expects; the gap need's claim names the gap and
    is `UNVERIFIED`, every other claim is `SUPPORTED`; options whose totals follow their
    scores; a manifest whose checks pass; and both technology seeds judged right."""
    clauses = [
        c
        for c in gold_clauses(lines, ingest.frozen_text, ingest.passages)
        if c.kind == "requirement"
    ]
    clause_of = {r.id: c.gold_id for r, c in zip(records, clauses, strict=True)}
    expected = {
        line["clause_id"]: line["decision"] for line in lines if line["kind"] == "decision_seed"
    }
    binding = [r for r in records if r.disposition == "BINDING"]
    groups, decisions, claims, assessments, rows = [], [], [], [], []
    for number, requirement in enumerate(binding, start=1):
        need, claim = f"RG-{number:03d}", f"CL-{number:03d}"
        decision = expected.get(clause_of[requirement.id], "RETRIEVE_EVIDENCE")
        gap = decision == "PROCEED_WITH_GAP"
        groups.append(
            RequirementGroup(
                id=need, member_ids=[requirement.id], topic=f"Topic {number}", llm=False
            )
        )
        claims.append(
            CapabilityClaim(
                id=claim,
                need_id=need,
                kind="capability",
                text=GAP_CLAIM if gap else f"The service meets {requirement.id}.",
                evidence_ids=[] if gap else ["CAP-001"],
                src_ids=requirement.src_ids[:3],
            )
        )
        assessments.append(
            EvidenceAssessment(claim_id=claim, disposition="UNVERIFIED", called=False)
            if gap
            else EvidenceAssessment(
                claim_id=claim,
                disposition="SUPPORTED",
                reason="The record shows it.",
                supporting_ids=["CAP-001"],
                assessor=ASSESSOR,
            )
        )
        decisions.append(
            NeedDecision(
                need_id=need,
                origin="RFP",
                decision=decision,  # type: ignore[arg-type]
                reason="No record holds it." if gap else "A record holds it.",
                claim_ids=[claim],
                gap="Not in the knowledge base." if gap else None,
            )
        )
        rows.append(
            CapabilityRow(
                need_id=need,
                origin="RFP",
                text=f"Topic {number}",
                decision=decision,  # type: ignore[arg-type]
                status="GAP" if gap else "COVERED",
                claim_ids=[claim],
            )
        )
    covered = next(row for row in rows if row.status == "COVERED")
    in_scope = [f.id for f in oracle_brief(ingest).factors if f.status == "IN_SCOPE"]
    options = SolutionOptions(
        options=[
            SolutionOption(
                id="OPT-1",
                name="Configured service",
                approach=[
                    StoredApproach(
                        need_id=covered.need_id, delivery_mode="CONFIG", claim_ids=covered.claim_ids
                    )
                ],
                scores=[StoredScore(factor_id=f, score=3) for f in in_scope],
                total=3.0,
                rank=1,
            ),
            SolutionOption(
                id="OPT-2",
                name="Baseline service",
                baseline=True,
                scores=[StoredScore(factor_id=f, score=2) for f in in_scope],
                total=2.0,
                rank=2,
            ),
        ],
        weighting="stated",
    )
    gap_row = next(row for row in rows if row.status == "GAP")
    gap_requirement = next(g.member_ids[0] for g in groups if g.id == gap_row.need_id)
    manifest = SolutionManifest(
        option_id="OPT-1",
        current_state=[
            Fact(
                text="The college signs its forms on paper.",
                evidence_class="RFP_SOURCE",
                source_ids=[binding[0].src_ids[0]],
            )
        ],
        target_state=[Fact(text="Every form is signed online.", evidence_class="ASSUMPTION")],
        workstreams=[Workstream(code="1", name="Signing service")],
        work_packages=[
            WorkPackage(
                code="1.1",
                name="Configure the signing service",
                requirement_ids=[r.id for r in binding],
                need_ids=[row.need_id for row in rows],
                claim_ids=[row.claim_ids[0] for row in rows if row.status == "COVERED"],
                effort=EffortEstimate(low_days=5, high_days=10, basis="analogy"),
                verification=[Verification(requirement_id=r.id, method="TEST") for r in binding],
                evidence_class="CAPABILITY_EVIDENCE",
            )
        ],
        tech_claims=[
            TechClaim(
                id="TC-01",
                text="pdfplumber exports documents as PDF/A files",
                library="pdfplumber",
                kind="LIBRARY",
            ),
            TechClaim(
                id="TC-02",
                text="reportlab renders tables on PDF pages",
                library="reportlab",
                kind="LIBRARY",
            ),
        ],
        gaps=[ManifestGap(requirement_id=gap_requirement, need_id=gap_row.need_id, status="GAP")],
        checks=[ManifestCheck(name="tree", passed=True), ManifestCheck(name="trace", passed=True)],
    )
    validations = [
        TechValidation(
            claim_id="TC-01",
            library="pdfplumber",
            verdict="INVALIDATED",
            reason="The documentation describes no PDF/A export.",
        ),
        TechValidation(
            claim_id="TC-02",
            library="reportlab",
            verdict="VALIDATED",
            reason="The documentation shows tables on pages.",
        ),
    ]
    return Solution(
        groups=groups,
        decisions=decisions,
        claims=claims,
        assessments=assessments,
        capability_map=CapabilityMap(rows=rows),
        options=options,
        manifest=manifest,
        validations=validations,
    )


def write_solution(run_dir: Path, solution: Solution) -> None:
    """The solution path's files, over the empty `requirement_groups.jsonl` of `write_run`."""
    _lines(
        run_dir / "requirement_groups.jsonl", [g.model_dump(mode="json") for g in solution.groups]
    )
    _lines(run_dir / "decisions.jsonl", [d.model_dump(mode="json") for d in solution.decisions])
    _lines(run_dir / "claims.jsonl", [c.model_dump(mode="json") for c in solution.claims])
    _lines(run_dir / "assessments.jsonl", [a.model_dump(mode="json") for a in solution.assessments])
    _lines(
        run_dir / "tech_validations.jsonl",
        [v.model_dump(mode="json") for v in solution.validations],
    )
    _lines(run_dir / "risk_rejected.jsonl", solution.risk_rejected)
    for name, model in (
        ("capability_map.json", solution.capability_map),
        ("options.json", solution.options),
        ("manifest.json", solution.manifest),
    ):
        (run_dir / name).write_text(model.model_dump_json(indent=1), encoding="utf-8")
    (run_dir / "review").mkdir(exist_ok=True)
    (run_dir / "review" / "solution_gate.md").write_text(solution.review, encoding="utf-8")
    (run_dir / "bid_memo.md").write_text(solution.memo, encoding="utf-8")


def write_run(
    run_dir: Path,
    ingest: IngestResult,
    records: list[Requirement],
    risks: list[dict[str, Any]],
    mapped: bool = True,
    quarantine: list[QuarantineRecord] | None = None,
    rejected: list[dict[str, Any]] | None = None,
    brief: OpportunityBrief | None = None,
    solution: Solution | None = None,
) -> Path:
    """Every file the scorer reads. Quarantine defaults to the hidden traps' records, each
    passage's ledger row lists the dispositions of the records that cite it, and the brief
    defaults to the oracle's. With a `solution`, the run also holds the solution path's files."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "frozen.txt").write_text(ingest.frozen_text, encoding="utf-8")
    _lines(run_dir / "passages.jsonl", [p.model_dump(mode="json") for p in ingest.passages])
    _lines(run_dir / "requirements.jsonl", [r.model_dump(mode="json") for r in records])
    _lines(run_dir / "risks.jsonl", risks)
    _lines(run_dir / "rejected.jsonl", rejected or [])
    held = quarantine_for(ingest) if quarantine is None else quarantine
    _lines(run_dir / "quarantine.jsonl", [q.model_dump(mode="json") for q in held])
    rows = []
    for passage in ingest.passages:
        citing = [r for r in records if passage.id in r.src_ids]
        dispositions = [r.disposition for r in citing] or ["NO_OBLIGATION"]
        rows.append(
            CandidateRow(
                src_id=passage.id,
                doc_id=passage.doc_id,
                dispositions=dispositions,  # type: ignore[arg-type]
                requirement_ids=[r.id for r in citing],
                reasons=[""] * len(dispositions),
                round=0,
            ).model_dump(mode="json")
        )
    _lines(run_dir / "candidates.jsonl", rows)
    coverage = CoverageReport(
        stop_reason="closed",
        passages=len(ingest.passages),
        with_disposition=len(ingest.passages),
        unaccounted=0,
        rejected_only=0,
    )
    (run_dir / "coverage.json").write_text(coverage.model_dump_json(), encoding="utf-8")
    triage = TriageRecord(zones=[], profile=RfpProfile(), fallback_sections=0)
    (run_dir / "triage.json").write_text(triage.model_dump_json(), encoding="utf-8")
    (run_dir / "hazards.json").write_text("[]", encoding="utf-8")
    register = ControlRegister(package="dev_rfp.pdf", documents=[], precedence_source="rules")
    (run_dir / "control_register.json").write_text(register.model_dump_json(), encoding="utf-8")
    for name in (
        "requirement_groups.jsonl",
        "discrepancies.jsonl",
        "questions.jsonl",
        "lint_findings.jsonl",
        "contract_flags.jsonl",
        "tool_calls.jsonl",
    ):
        (run_dir / name).write_text("", encoding="utf-8")
    binding = [r.id for r in records if r.disposition == "BINDING"]
    items = [
        {
            "id": f"APP-{n:03d}",
            "text": "Do it.",
            "requirement_ids": [i],
            "basis": "Stated.",
            "evidence_class": "ASSUMPTION",
            "source_ids": [],
        }
        for n, i in enumerate(binding if mapped else [], start=1)
    ]
    (run_dir / "approach.json").write_text(
        json.dumps({"items": items, "unmapped": [], "questions": []}), encoding="utf-8"
    )
    summary = {"summary": {"open_questions": []}}
    (run_dir / "solution_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    manifest = RunManifest(
        run_id=run_dir.name,
        commit="test",
        profile="free",
        models={},
        started=datetime(2026, 11, 3, tzinfo=UTC),
        status="COMPLETED",
    )  # type: ignore[arg-type]
    (run_dir / "run_manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    (run_dir / "ledger.jsonl").write_text("", encoding="utf-8")
    written = brief if brief is not None else oracle_brief(ingest)
    (run_dir / "brief.json").write_text(written.model_dump_json(indent=1), encoding="utf-8")
    if solution is not None:
        write_solution(run_dir, solution)
    return run_dir
