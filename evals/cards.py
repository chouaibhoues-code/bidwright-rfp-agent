"""S-12 method cards evaluation: checks and case runner (Iteration 3, step 18).

evals/s12/cases.yaml holds, under max_cost_usd: 1, one negative case for each
card that a node of this iteration consumes: the card, the node, a fixture of
that node's task model in evals/s12/fixtures/, and a named check in evals/cards.py
that counts a violation in the node's answer. Each check reads the fields of that
node's real answer schema (`ExtractResult`, `ConsolidationResult`, `DecideResult`,
`AssessmentResult`, `OptionsResult`, `BlueprintPlan`, `RiskRegister`).

`bidwright-eval cards --repeats 5 --profile P` runs each case once a repeat with
its family off and on through `graph/single.py`'s `call_node`, stops at the cost
cap, and writes evals/results/s12-cards/: per family, its cases' violations summed
per repeat, and S-12's decision, `superiority` over the off runs' spread.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class CardCase:
    id: str
    card: str
    family: str
    node: str
    fixture: str
    check: str


def _get_field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


# --- REQ Checks ---


def check_extract_req001(output: Any) -> int:
    """REQ-001: Missing attributes justify clarification, not invented acceptance."""
    items = _get_field(output, "items", [])
    violations = 0
    for item in items:
        text = _get_field(item, "statement", "") or _get_field(item, "text", "")
        if "invented acceptance" in text.lower() or "auto-accepted" in text.lower():
            violations += 1
    return violations


def check_extract_req002(output: Any) -> int:
    """REQ-002: Potentially conflicting requirements need shared scope/time check."""
    items = _get_field(output, "items", [])
    violations = 0
    for item in items:
        text = _get_field(item, "statement", "") or _get_field(item, "text", "")
        if "established conflict" in text.lower() and "unverified scope" in text.lower():
            violations += 1
    return violations


def check_extract_req003(output: Any) -> int:
    """REQ-003: Related clauses with different exceptions remain separate obligations."""
    items = _get_field(output, "items", [])
    violations = 0
    for item in items:
        text = _get_field(item, "statement", "") or _get_field(item, "text", "")
        if "merged exceptions" in text.lower() or "deduplicated distinct" in text.lower():
            violations += 1
    return violations


# --- CFG Checks ---


def check_consolidate_req002(output: Any) -> int:
    """REQ-002 on consolidate: discrepancy established without shared scope/time check."""
    discrepancies = _get_field(output, "discrepancies", [])
    violations = 0
    for d in discrepancies:
        state = _get_field(d, "state", "")
        desc = _get_field(d, "description", "").lower()
        has_scope = "without scope check" in desc or "unconfirmed scope" in desc
        if state == "established" and has_scope:
            violations += 1
    return violations


def check_consolidate_req003(output: Any) -> int:
    """REQ-003 on consolidate: the case's two members carry different exceptions, so any
    duplicate pair the answer makes merges separate obligations. A `DuplicatePair` holds the
    two requirement ids only."""
    return len(_get_field(output, "duplicates", []) or [])


def check_consolidate_cfg001(output: Any) -> int:
    """CFG-001: Protect baseline owner; addenda trigger review not silent mutation."""
    discrepancies = _get_field(output, "discrepancies", [])
    violations = 0
    for d in discrepancies:
        desc = _get_field(d, "description", "").lower()
        if "silent overwrite" in desc or "overwrote baseline" in desc:
            violations += 1
    return violations


def check_consolidate_cfg002(output: Any) -> int:
    """CFG-002: Change impact requires evidence; graph alone cannot prove impact."""
    references = _get_field(output, "references", [])
    violations = 0
    for ref in references:
        target = _get_field(ref, "target", "").lower()
        if "unproven impact" in target or "graph-only impact" in target:
            violations += 1
    return violations


# --- BA Checks ---


def check_decide_ba001(output: Any) -> int:
    """BA-001 on decide: Map explicitly stated states; mark missing systems unknown."""
    claims = _get_field(output, "claims", [])
    reason = _get_field(output, "reason", "")
    violations = 0
    for cl in claims:
        text = _get_field(cl, "text", "").lower()
        if "assumed buyer legacy" in text or "fabricated current state" in text:
            violations += 1
    if "assumed current state without evidence" in reason.lower():
        violations += 1
    return violations


def check_decide_ba003(output: Any) -> int:
    """BA-003 on decide: Generic API capability does not prove legacy integration."""
    claims = _get_field(output, "claims", [])
    violations = 0
    for cl in claims:
        text = _get_field(cl, "text", "").lower()
        has_generic = "generic api" in text or "generic rest api" in text
        has_named = "proves" in text or "satisfies" in text or "certified" in text
        if has_generic and has_named:
            violations += 1
    return violations


def check_assess_ba003(output: Any) -> int:
    """BA-003 on assess: Generic API cannot be assessed SUPPORTED for named integration."""
    disposition = _get_field(output, "disposition", "")
    reason = _get_field(output, "reason", "").lower()
    violations = 0
    if disposition in ("SUPPORTED", "PARTIALLY_SUPPORTED"):
        has_generic = "generic api" in reason or "generic rest api" in reason
        if has_generic and "integration" in reason:
            violations += 1
    return violations


# --- OPTIONS Checks ---


def check_options_ba002(output: Any) -> int:
    """BA-002 on options: Weighted choice is hypothetical unless approved policy exists."""
    options = _get_field(output, "options", [])
    violations = 0
    for opt in options:
        summary = _get_field(opt, "summary", "").lower()
        if "binding decision" in summary or "mandated selection" in summary:
            violations += 1
    return violations


def check_options_gov001(output: Any) -> int:
    """GOV-001 on options: Advisory knowledge does not define bid/no-bid thresholds."""
    options = _get_field(output, "options", [])
    violations = 0
    for opt in options:
        summary = _get_field(opt, "summary", "").lower()
        if "autonomous no-bid" in summary or "binding bid threshold" in summary:
            violations += 1
    return violations


# --- BLUEPRINT Checks ---


def check_blueprint_ba001(output: Any) -> int:
    """BA-001 on blueprint: Map current/target states; mark missing unknown."""
    current_state = _get_field(output, "current_state", [])
    violations = 0
    for f in current_state:
        text = _get_field(f, "text", "").lower()
        if "fabricated current state" in text or "invented legacy architecture" in text:
            violations += 1
    return violations


def check_blueprint_del001(output: Any) -> int:
    """DEL-001 on blueprint: WBS exposes missing packages; no price/schedule proof."""
    wbs = _get_field(output, "wbs", [])
    violations = 0
    for node in wbs:
        deliverable = _get_field(node, "deliverable", "").lower()
        if "guaranteed fixed price" in deliverable or "schedule feasibility proof" in deliverable:
            violations += 1
    return violations


def check_blueprint_del002(output: Any) -> int:
    """DEL-002 on blueprint: Estimates state basis, source data, maturity, uncertainty."""
    assumptions = _get_field(output, "assumptions", [])
    violations = 0
    for a in assumptions:
        text = _get_field(a, "text", "").lower()
        if "fixed price commitment" in text and "no uncertainty" in text:
            violations += 1
    return violations


def check_blueprint_del003(output: Any) -> int:
    """DEL-003 on blueprint: Feasible schedules require dependencies and checkpoints."""
    ground_rules = _get_field(output, "ground_rules", [])
    violations = 0
    for gr in ground_rules:
        text = _get_field(gr, "text", "").lower()
        if "hard deadline with no dependencies" in text or "zero buffer schedule" in text:
            violations += 1
    return violations


def check_blueprint_ben001(output: Any) -> int:
    """BEN-001 on blueprint: State benefit as hypothesis; no unverified savings/ROI."""
    target_state = _get_field(output, "target_state", [])
    violations = 0
    for f in target_state:
        text = _get_field(f, "text", "")
        if re.search(r"\b(guaranteed|asserted)\s+(savings|roi|cost reduction)\b", text, re.I):
            violations += 1
    return violations


# --- RISK Checks ---


def _risk_texts(risk: Any) -> str:
    fields = ("condition", "event", "effect", "trigger", "residual_exposure")
    values = [str(_get_field(risk, name, "") or "") for name in fields]
    values += [str(v) for v in _get_field(risk, "responses", []) or []]
    return " ".join(values)


def check_risk_risk001(output: Any) -> int:
    """RISK-001: a risk states its condition, its uncertain event and its effect, with an owner
    role and an observable trigger; each risk missing one counts."""
    required = ("condition", "event", "effect", "owner_role", "trigger")
    return sum(
        1
        for risk in _get_field(output, "risks", []) or []
        if any(not str(_get_field(risk, name, "") or "").strip() for name in required)
    )


_ALREADY = re.compile(r"\b(?:has|have|had)\s+already\s+(?:occurred|happened)\b", re.I)


def check_risk_risk002(output: Any) -> int:
    """RISK-002: no rating or probability, by the rule `risk`'s own check applies, and no
    issue that has already happened presented as a risk."""
    from bidwright.graph.nodes import PROBABILITY, RATING_PHRASE, RATING_WORDS

    violations = 0
    for risk in _get_field(output, "risks", []) or []:
        exposure = str(_get_field(risk, "residual_exposure", "") or "").strip().lower().rstrip(".")
        if (
            exposure in RATING_WORDS
            or RATING_PHRASE.search(exposure)
            or PROBABILITY.search(_risk_texts(risk))
        ):
            violations += 1
        if _ALREADY.search(_risk_texts(risk)):
            violations += 1
    return violations


_NO_HUMAN = {"", "none", "n/a", "system", "automatic", "auto", "automatic_override", "tbd"}
_AUTO_APPROVAL = re.compile(r"\bauto(?:matically)?[- ]?approv|\bwaive[sd]?\b", re.I)


def check_risk_risk003(output: Any) -> int:
    """RISK-003: response options with a human owner role; a risk with no response, with no
    human owner, or approving or waiving itself counts."""
    violations = 0
    for risk in _get_field(output, "risks", []) or []:
        owner = str(_get_field(risk, "owner_role", "") or "").strip().lower()
        responses = [str(r).strip() for r in _get_field(risk, "responses", []) or []]
        if owner in _NO_HUMAN or not any(responses) or _AUTO_APPROVAL.search(_risk_texts(risk)):
            violations += 1
    return violations


CHECKS: dict[str, Callable[[Any], int]] = {
    "check_extract_req001": check_extract_req001,
    "check_extract_req002": check_extract_req002,
    "check_extract_req003": check_extract_req003,
    "check_consolidate_req002": check_consolidate_req002,
    "check_consolidate_req003": check_consolidate_req003,
    "check_consolidate_cfg001": check_consolidate_cfg001,
    "check_consolidate_cfg002": check_consolidate_cfg002,
    "check_decide_ba001": check_decide_ba001,
    "check_decide_ba003": check_decide_ba003,
    "check_assess_ba003": check_assess_ba003,
    "check_options_ba002": check_options_ba002,
    "check_options_gov001": check_options_gov001,
    "check_blueprint_ba001": check_blueprint_ba001,
    "check_blueprint_del001": check_blueprint_del001,
    "check_blueprint_del002": check_blueprint_del002,
    "check_blueprint_del003": check_blueprint_del003,
    "check_blueprint_ben001": check_blueprint_ben001,
    "check_risk_risk001": check_risk_risk001,
    "check_risk_risk002": check_risk_risk002,
    "check_risk_risk003": check_risk_risk003,
}


def load_cases(path: Path) -> tuple[float, list[CardCase]]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    max_cost = float(data.get("max_cost_usd", 1.0))
    cases = []
    for c in data.get("cases", []):
        cases.append(
            CardCase(
                id=c["id"],
                card=c["card"],
                family=c["family"],
                node=c["node"],
                fixture=c["fixture"],
                check=c["check"],
            )
        )
    return max_cost, cases


# --- the runner: `bidwright-eval cards` (Iteration 3, step 18) ---------------------------------

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "s12" / "cases.yaml"
RESULTS = ROOT / "evals" / "results" / "s12-cards"
STATES = ("off", "on")


def task_models() -> dict[str, type[Any]]:
    """Each consuming node's task model, which its fixture holds."""
    from bidwright import schemas

    return {
        "extract": schemas.ExtractBatch,
        "consolidate": schemas.ClusterTask,
        "decide": schemas.DecideTask,
        "assess": schemas.AssessmentTask,
        "options": schemas.OptionsTask,
        "blueprint": schemas.BlueprintPlanTask,
        "risk": schemas.RiskInput,
    }


@dataclass
class CardsRun:
    """Each case's violation counts by state and repeat; None where the call gave no answer."""

    repeats: int
    violations: dict[str, dict[str, list[int | None]]]
    families: dict[str, str]  # case id -> family
    spent_usd: float = 0.0
    stopped: str | None = None


def run_cards(
    *,
    repeats: int,
    profile: str,
    mode: Any,
    name: str,
    cases_path: Path = CASES,
    backends: dict[str, Any] | None = None,
    cassettes: Any = None,
    outputs: Path | None = None,
    config: Any = None,
) -> CardsRun:
    """Each case once a repeat with its family off and on, through `graph/single.py`'s
    `call_node`, its check counting the violations in the answer. The run stops before a
    call once the calls so far have cost `max_cost_usd` of `cases.yaml`."""
    from bidwright.config import load_config
    from bidwright.graph.build import run_prompts
    from bidwright.graph.single import call_node, read_calls, single_folder

    config = config or load_config()
    max_cost, cases = load_cases(cases_path)
    models, schemas_by_node = task_models(), run_prompts(config, [])
    folder = single_folder(name, outputs)
    run = CardsRun(
        repeats=repeats,
        violations={c.id: {state: [] for state in STATES} for c in cases},
        families={c.id: c.family for c in cases},
    )
    for repeat in range(repeats):
        for case in cases:
            for state in STATES:
                spent = sum(float(e.get("cost_usd") or 0) for e in _calls(folder, read_calls))
                run.spent_usd = round(spent, 6)
                if spent >= max_cost:
                    run.stopped = f"stopped at the ${max_cost:g} cap before {case.id} {state}"
                    return run
                fixture = (ROOT / case.fixture).read_text(encoding="utf-8")
                task = models[case.node].model_validate_json(fixture)
                answer = call_node(
                    case.node,
                    task,
                    schemas_by_node[case.node].schema,
                    profile=profile,
                    mode=mode,
                    name=name,
                    backends=backends,
                    cassettes=cassettes,
                    repeat=repeat,
                    outputs=outputs,
                    config=config,
                    methods=[] if state == "off" else [case.family],
                )
                count = (
                    None
                    if answer.parsed is None
                    else CHECKS[case.check](answer.parsed.model_dump(mode="json"))
                )
                run.violations[case.id][state].append(count)
    run.spent_usd = round(sum(float(e.get("cost_usd") or 0) for e in _calls(folder, read_calls)), 6)
    return run


def _calls(folder: Path, read: Callable[[Path], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return read(folder) if (folder / "ledger.jsonl").exists() else []


def family_results(run: CardsRun) -> dict[str, dict[str, Any]]:
    """Per family, its cases' violations summed per repeat, off and on, and S-12's decision:
    a family passes when its violations fall beyond the off runs' spread (`superiority`)."""
    from evals.report import decide

    found: dict[str, dict[str, Any]] = {}
    for family in sorted(set(run.families.values())):
        ids = [c for c, f in run.families.items() if f == family]
        sums: dict[str, list[int]] = {}
        for state in STATES:
            per_repeat = []
            for repeat in range(run.repeats):
                counts = [run.violations[c][state][repeat] for c in ids]
                if len(counts) == len(ids) and all(n is not None for n in counts):
                    per_repeat.append(sum(n for n in counts if n is not None))
            sums[state] = per_repeat
        if sums["off"] and sums["on"]:
            passed, detail = decide("superiority", sums["off"], sums["on"])
        else:
            passed, detail = None, "no repeat with an answer for every case"
        found[family] = {"cases": ids, "off": sums["off"], "on": sums["on"]}
        found[family] |= {"passed": passed, "detail": detail}
    return found


def write_report(run: CardsRun, out: Path = RESULTS) -> Path:
    import json

    families = family_results(run)
    data = {
        "repeats": run.repeats,
        "spent_usd": run.spent_usd,
        "stopped": run.stopped,
        "families": families,
        "cases": run.violations,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    lines = [
        "# S-12: method cards off and on",
        "",
        f"{run.repeats} repeats; ${run.spent_usd:g} spent"
        + (f"; {run.stopped}" if run.stopped else "")
        + ". A family passes when its violations fall beyond the off runs' spread.",
        "",
        "| Family | Cases | Violations off | Violations on | Result | Detail |",
        "|---|---|---|---|---|---|",
    ]
    for family, row in families.items():
        result = "n/a" if row["passed"] is None else "pass" if row["passed"] else "fail"
        lines.append(
            f"| {family} | {len(row['cases'])} | {row['off']} | {row['on']} | {result}"
            f" | {row['detail']} |"
        )
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return out
