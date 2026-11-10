"""The Review page (WP-3.6, ADR-053, ADR-060): the person's work on a run, in the order of
consequence.

- Gate: for a run waiting at `solution_gate`, everything the decision rests on, on the page
  itself: the options ranked, each with its scores and reasons, how it answers every need and
  what supports that (a need answered with no claim says so), and its assumptions; the
  capability map; the manifest's work packages with their evidence class, its failed checks,
  gaps, assumptions, ground rules and technology verdicts; the risks; then the decision.
  The decision is one of approve, approve with edits, switch to another option, or reject. The
  form shows the fields that decision takes: the edits are grouped by work package, under its
  code and name, with text boxes for text. Submitting runs `bidwright approve` with the edits on
  standard input; the gate node writes the approval. Once the command succeeds the tab shows
  the recorded decision, with the command's output, and no form. For a run past the gate, its
  approval file.
- Records: the run's records from `review_queue`, hazards first, each with the verbatim source
  beside it, taking accept, correct (with the corrected text), reject or flag. The page runs
  `bidwright review`, the one writer of `review/decisions.jsonl`.
- Negative space: passages no record cites, each marked clear or missed.
- After each batch of verdicts the page can send them to Phoenix (`bidwright phoenix sync`),
  where they sit as HUMAN annotations on the spans that made the records.

One role, entered at the top, signs both the gate decision and the verdicts. Artifact text is
shown as plain text, never as Markdown or HTML, and the page writes no file.
"""

from typing import Any

import streamlit as st
import yaml

import app.actions as actions
import app.data as app_data
from app.data import (
    RunData,
    allowed_edit_fields,
    build_approve_command,
    changed_edits,
    edit_groups,
    fact_rows,
    factor_labels,
    option_approach_rows,
    option_score_rows,
    risk_rows,
    unsupported_needs,
    work_package_rows,
)
from app.phoenix_view import links_for
from app.state import current_run, default
from bidwright.render import STATUS_LINE
from bidwright.review import KIND_ORDER, KIND_TITLES, ReviewItem, latest, progress, review_queue
from bidwright.schemas import ReviewDecision

NOT_REVIEWED = "(not reviewed)"
RECORD_KINDS = [k for k in KIND_ORDER if k != "passage"]

APPROVE = "Approve"
EDIT = "Approve with edits"
SWITCH = "Switch to another option"
REJECT = "Reject"
DECISIONS = (APPROVE, EDIT, SWITCH, REJECT)
RESULT_KEY = "gate_result"
RESET_KEY = "gate_reset"
GATE_KEYS = ("gate_option", "gate_override", "gate_reject")
TEXT_HEIGHT = 90


# --- the gate: what the decision rests on -----------------------------------------------------


def _table(rows: list[dict[str, str]], widths: dict[str, int]) -> None:
    """A table whose long-text columns get room: `st.dataframe` cells do not wrap, so each
    column has a width in pixels, and the full text of anything long is also on the page."""
    st.dataframe(
        rows,
        hide_index=True,
        column_config={name: st.column_config.Column(width=w) for name, w in widths.items()},
    )


def _blocking(data: RunData) -> list[str]:
    return [tv.claim_id for tv in data.tech_validations if tv.verdict == "INVALIDATED"]


def _waiting(data: RunData) -> None:
    st.info(
        "This run waits at the solution gate. Read the options and the manifest below, then"
        " decide at the bottom of this tab. Approving starts nothing outside this machine: the"
        " run drafts the proposal, and every output stays UNREVIEWED_DRAFT."
    )
    blocking = _blocking(data)
    if blocking:
        st.error(
            "Blocked by technology claims still INVALIDATED: "
            + ", ".join(blocking)
            + ". Approve only with an override reason, or reject."
        )
    if data.bid_signal is not None:
        st.text(f"Bid signal: {data.bid_signal.signal}. Whether to bid is a person's decision.")
        if data.bid_signal.missing_inputs:
            st.text("Missing for a signal: " + ", ".join(data.bid_signal.missing_inputs))
    if data.options is not None:
        if data.options.hypothetical:
            st.text("The ranking is hypothetical: no approved bid policy is loaded.")
        if data.options.weighting == "equal":
            st.text("A weight is not stated, so every factor counts equally.")


def _options(data: RunData) -> None:
    if data.options is None or not data.options.options:
        return
    st.subheader("1. The options")
    labels = factor_labels(data.brief)
    chosen = data.solution_manifest.option_id if data.solution_manifest else None
    for option in sorted(data.options.options, key=lambda o: o.rank):
        with st.container(border=True):
            head = f"Rank {option.rank}: {option.id}, {option.name}. Total {option.total:g} of 4."
            if option.id == chosen:
                head += " The manifest below is built on this option."
            st.text(head)
            if option.summary:
                st.text(option.summary)
            unsupported = unsupported_needs(option)
            if unsupported:
                st.warning(
                    "Answers " + ", ".join(unsupported) + " with no claim behind it: there it"
                    " rests on the option's assumptions."
                )
            _table(option_score_rows(option, labels), {"factor": 260, "score": 70, "reason": 700})
            _table(
                option_approach_rows(option, data.capability_map, data.assessments),
                {"need": 75, "text": 330, "map status": 90, "delivery": 105, "support": 430},
            )
            for assumption in option.assumptions:
                st.text(f"Assumes: {assumption}")
            if option.needs_proof:
                st.text("Cites claims not supported: " + ", ".join(option.needs_proof))
            if option.failed_gates:
                st.text("Fails pass/fail factors: " + ", ".join(option.failed_gates))
    for note in data.options.notes:
        st.text(f"Note: {note}")


def _capability_map(data: RunData) -> None:
    if data.capability_map is None or not data.capability_map.rows:
        return
    st.subheader("2. What the supplier can prove")
    _table(
        [
            {
                "need": row.need_id,
                "origin": row.origin,
                "status": row.status,
                "text": row.text,
                "claims": ", ".join(
                    f"{c} {data.assessments[c].disposition}" if c in data.assessments else c
                    for c in row.claim_ids
                )
                or "none",
                "reason": row.reason,
            }
            for row in data.capability_map.rows
        ],
        {"need": 75, "origin": 75, "status": 80, "text": 330, "claims": 330, "reason": 220},
    )


def _manifest(data: RunData) -> None:
    manifest = data.solution_manifest
    if manifest is None:
        return
    st.subheader(f"3. The solution manifest, for {manifest.option_id or 'no option'}")
    failed = [c for c in manifest.checks if not c.passed]
    if failed:
        st.warning(f"{len(failed)} of {len(manifest.checks)} checks fail:")
        for check in failed:
            st.text(f"{check.name}: {check.detail}" if check.detail else check.name)
    if manifest.gaps:
        st.text(
            "Listed as gaps: "
            + ", ".join(f"{g.requirement_id} ({g.need_id}, {g.status})" for g in manifest.gaps)
        )
    _table(
        work_package_rows(manifest),
        {
            "code": 55,
            "name": 230,
            "effort (days)": 95,
            "basis": 160,
            "evidence": 170,
            "requirements": 300,
            "claims": 120,
            "after": 70,
        },
    )
    with st.expander("Each work package's scope, exclusions and acceptance"):
        for row in sorted(manifest.work_packages, key=lambda p: app_data.code_key(p.code)):
            st.text(f"{row.code} {row.name}")
            st.text(f"Scope: {row.scope}")
            st.text(f"Exclusions: {row.exclusions}")
            st.text(f"Acceptance: {row.acceptance}")
            if row.effort is not None and row.effort.basis_text:
                st.text(f"Effort basis: {row.effort.basis_text} {row.effort.uncertainty}".strip())
    facts = fact_rows(manifest)
    if facts:
        _table(facts, {"fact": 110, "text": 600, "evidence": 140, "sources": 180})
    if data.tech_validations:
        st.dataframe(
            [
                {
                    "claim": tv.claim_id,
                    "library": tv.library or "none",
                    "verdict": tv.verdict,
                    "reason": tv.reason,
                }
                for tv in data.tech_validations
            ],
            hide_index=True,
        )
    for note in manifest.notes:
        st.text(f"Note: {note}")
    with st.expander("Every check of the manifest"):
        st.dataframe(
            [
                {"check": c.name, "result": "pass" if c.passed else "FAIL", "detail": c.detail}
                for c in manifest.checks
            ],
            hide_index=True,
        )


def _risks(data: RunData) -> None:
    st.subheader("4. Risks")
    if not data.risks:
        st.text("No risk passed the checks.")
    for risk in risk_rows(data.risks):
        with st.container(border=True):
            st.text(f"{risk['risk']} ({risk['owner']}): {risk['event']}")
            st.text(f"Trigger: {risk['trigger']}")
            if risk["bears on"]:
                st.text(f"Bears on: {risk['bears on']}")


def _documents(data: RunData) -> None:
    if data.bid_memo_text:
        with st.expander("The bid memo"):
            st.code(data.bid_memo_text, language=None)
    if data.gate_text is not None:
        with st.expander("The review file, review/solution_gate.md"):
            st.code(data.gate_text, language=None)


# --- the gate: the decision --------------------------------------------------------------------


def _reset_after_decision() -> None:
    """After a recorded decision, start the next form clean: the choice back to Approve, and no
    field keeps a value typed for the manifest just decided. Done before any of them is drawn."""
    if not st.session_state.pop(RESET_KEY, False):
        return
    for key in list(st.session_state):
        if str(key).startswith("edit:") or key in GATE_KEYS:
            del st.session_state[key]
    st.session_state["gate_decision"] = APPROVE


def _edit_fields(data: RunData) -> dict[str, Any]:
    """The edit fields, grouped by work package; returns each field's value by its path."""
    values: dict[str, Any] = {}
    codes = [p.code for p in data.solution_manifest.work_packages] if data.solution_manifest else []
    for group in edit_groups(data.solution_manifest):
        with st.container(border=True):
            st.text(group.title)
            if group.caption:
                st.text(group.caption)
            numbers = [f for f in group.fields if f.kind == "float"]
            if numbers:
                for column, field in zip(st.columns(len(numbers)), numbers, strict=True):
                    values[field.path] = column.number_input(
                        field.label,
                        min_value=0.0,
                        value=float(field.current),
                        step=0.5,
                        key=f"edit:{field.path}",
                    )
            for field in (f for f in group.fields if f.kind != "float"):
                if field.kind == "predecessors":
                    own = field.path.split("[", 1)[1].split("]", 1)[0]
                    values[field.path] = st.multiselect(
                        field.label,
                        options=[c for c in codes if c != own],
                        default=list(field.current),
                        key=f"edit:{field.path}",
                    )
                else:
                    values[field.path] = st.text_area(
                        field.label,
                        value=str(field.current),
                        height=TEXT_HEIGHT,
                        key=f"edit:{field.path}",
                    )
    return values


def _decision(data: RunData) -> None:
    st.subheader("5. The decision")
    _reset_after_decision()
    role = str(st.session_state.get("review_role") or "").strip()
    if role:
        st.text(f"Deciding as: {role}")
    else:
        st.warning("Enter your role at the top of the page: a decision names a role, never a name.")
    manifest = data.solution_manifest
    chosen = manifest.option_id if manifest is not None else None
    others = [o for o in (data.options.options if data.options else []) if o.id != chosen]
    choices = [d for d in DECISIONS if d != SWITCH or others]
    default("gate_decision", APPROVE)
    if st.session_state["gate_decision"] not in choices:
        st.session_state["gate_decision"] = APPROVE
    decision = st.radio("Decision", choices, key="gate_decision", horizontal=True)
    blocked = bool(_blocking(data))
    values: dict[str, Any] = {}
    with st.form("solution_gate_form"):
        if decision == APPROVE:
            st.text(f"Approve {chosen or 'the manifest'} as it stands; the run then drafts.")
        elif decision == EDIT:
            st.text(
                "Change only what needs changing; every other field stays as it is. The run"
                " checks the edited work packages' technology claims and the risks again, then"
                " drafts."
            )
            values = _edit_fields(data)
        elif decision == SWITCH:
            st.selectbox(
                "Option",
                [o.id for o in others],
                format_func=lambda oid: next(f"{o.id}, {o.name}" for o in others if o.id == oid),
                key="gate_option",
            )
            st.text(
                "The run goes back to blueprint, builds the manifest for that option, checks it"
                " and stops at this gate again for a new decision."
            )
        else:
            st.text_area("Why the solution is rejected", height=TEXT_HEIGHT, key="gate_reject")
            st.text("The run ends POLICY_BLOCKED (GATE_REJECTED), and nothing is drafted.")
        if blocked and decision in (APPROVE, EDIT):
            st.text_input("Override reason: the gate is blocked", key="gate_override")
        submitted = st.form_submit_button(
            {
                APPROVE: f"Approve {chosen or ''}".strip(),
                EDIT: "Approve with these edits",
                SWITCH: "Switch option",
                REJECT: "Reject the solution",
            }[decision]
        )
    if submitted:
        _submit(data, decision, role, values)


def _submit(data: RunData, decision: str, role: str, values: dict[str, Any]) -> None:
    edits = (
        changed_edits(allowed_edit_fields(data.solution_manifest), values)
        if decision == EDIT
        else []
    )
    reject = str(st.session_state.get("gate_reject") or "").strip() if decision == REJECT else ""
    option = str(st.session_state.get("gate_option") or "") if decision == SWITCH else None
    override = str(st.session_state.get("gate_override") or "").strip()
    if not role:
        st.error("Enter your role at the top of the page first.")
        return
    if decision == EDIT and not edits:
        st.error("No field changed: change at least one, or choose Approve.")
        return
    if decision == REJECT and not reject:
        st.error("Give the reason for the rejection.")
        return
    try:
        cmd, stdin_text = build_approve_command(
            data.run_dir,
            role=role,
            option_id=option,
            edits=edits,
            override_reason=override,
            reject_reason=reject,
            manifest=data.solution_manifest,
        )
    except ValueError as exc:
        st.error(f"Refused: {exc}")
        return
    shown = "bidwright " + " ".join(cmd[1:])
    with st.status(
        "The run continues from the gate to its next stop: about half a minute on the"
        " development RFP, several minutes on the hero. Keep this page open.",
        expanded=True,
    ) as status:
        st.text(f"Running: {shown}")
        done = app_data.run_approve(cmd, stdin_text)
        ok = done.returncode == 0
        status.update(
            label="The decision is recorded." if ok else "The decision was refused.",
            state="complete" if ok else "error",
        )
    output = (done.stdout or "") + (done.stderr or "")
    if not ok:
        st.error(f"Exit code {done.returncode}: the run still waits at the gate.")
        if output.strip():
            st.code(output, language=None)
        return
    st.session_state[RESULT_KEY] = {"command": shown, "output": output}
    st.session_state[RESET_KEY] = True
    st.cache_data.clear()
    st.rerun()


def _result() -> None:
    """The last decision's command and output, shown once after the page reruns on it."""
    result = st.session_state.pop(RESULT_KEY, None)
    if not result:
        return
    st.success("The decision is recorded, and the run went on to its next stop.")
    st.text(f"Ran: {result['command']}")
    if str(result["output"]).strip():
        st.code(result["output"], language=None)


def _approval_record(data: RunData) -> None:
    if data.gate_approval_text is None:
        st.text("This run has no gate decision: it took no solution gate, or has not reached it.")
        return
    approval = data.gate_approval
    if approval is not None:
        st.text(
            f"Decision: {approval.decision} | Role: {approval.approver_role}"
            f" | Option: {approval.option_id or 'None'}"
            f" | Automatic: {approval.auto_selected}"
        )
        for edit in approval.edits:
            st.text(f"Edited {edit.field}: {edit.value}")
        if approval.override_reason:
            st.text(f"Override reason: {approval.override_reason}")
        if approval.reject_reason:
            st.text(f"Reject reason: {approval.reject_reason}")
    with st.expander("The approval file, review/solution_gate.approval.yaml"):
        st.code(data.gate_approval_text, language=None)


def _gate(data: RunData) -> None:
    _result()
    if data.manifest.status == "WAITING_HUMAN" and data.solution_manifest is not None:
        _waiting(data)
        _options(data)
        _capability_map(data)
        _manifest(data)
        _risks(data)
        _documents(data)
        _decision(data)
    else:
        _approval_record(data)


# --- the records -----------------------------------------------------------------------------


def _item_view(item: ReviewItem, decision: ReviewDecision | None) -> None:
    current = decision is not None and decision.item_sha256 == item.sha256
    stale = "" if current else " (STALE: the record changed; record a verdict again)"
    status = (
        "not reviewed"
        if decision is None
        else f"{decision.verdict} by {decision.role}, {decision.decided:%Y-%m-%d %H:%M} UTC{stale}"
    )
    st.text(f"{item.id} | {item.kind} | {status}")
    st.text(item.title)
    if item.source:
        st.code(item.source, language=None)
    for key, value in item.detail.items():
        if value not in (None, "", [], {}):
            text = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
            st.text(f"{key}: {text}")
    # Each choice starts from the verdict and note that count now, so changing one and
    # recording again updates it.
    default(f"verdict:{item.id}", decision.verdict if decision is not None else NOT_REVIEWED)
    default(f"note:{item.id}", decision.note if decision is not None else "")
    left, right = st.columns([1, 2])
    left.radio("Verdict", [NOT_REVIEWED, *item.verdicts], key=f"verdict:{item.id}", horizontal=True)
    right.text_input("Note, or the corrected text", key=f"note:{item.id}")


def _changed(item: ReviewItem, decision: ReviewDecision | None) -> dict[str, str] | None:
    """The entry to record for an item, or None when its choice is what already counts."""
    verdict = st.session_state.get(f"verdict:{item.id}", NOT_REVIEWED)
    note = str(st.session_state.get(f"note:{item.id}") or "").strip()
    if verdict == NOT_REVIEWED:
        return None
    if (
        decision is not None
        and decision.item_sha256 == item.sha256
        and decision.verdict == verdict
        and decision.note == note
    ):
        return None
    return {"item": item.id, "verdict": verdict, "note": note}


def _queue_form(
    data: RunData, items: list[ReviewItem], decisions: dict[str, ReviewDecision], form: str
) -> None:
    if not items:
        st.text("Nothing to review here.")
        return
    st.text(
        "Choose a verdict, or change one already recorded, and record: the latest verdict for"
        " an item is the one that counts, and every earlier one stays in the file."
    )
    with st.form(form):
        for item in items:
            with st.container(border=True):
                _item_view(item, decisions.get(item.id))
        submitted = st.form_submit_button("Record these verdicts")
    if not submitted:
        return
    role = str(st.session_state.get("review_role") or "").strip()
    entries = [e for item in items if (e := _changed(item, decisions.get(item.id)))]
    if not entries:
        st.text("Nothing changed: every choice is what already counts.")
        return
    if not role:
        st.error("Enter your role above first: a decision names a role, never a name.")
        return
    done = actions.run(actions.review(data.run_dir, role), yaml.safe_dump(entries, sort_keys=False))
    output = (done.stdout or "") + (done.stderr or "")
    if done.returncode == 0 and st.session_state.get("review_auto_sync"):
        synced = actions.run(actions.phoenix_sync(data.run_dir))
        output += (synced.stdout or "") + (synced.stderr or "")
        st.cache_data.clear()
    st.session_state["review_output"] = output
    st.rerun()


def _records(data: RunData, queue: list[ReviewItem], decisions: dict[str, ReviewDecision]) -> None:
    default("review_kinds", list(RECORD_KINDS))
    left, right = st.columns([3, 1])
    left.multiselect(
        "Kinds", RECORD_KINDS, key="review_kinds", format_func=lambda k: KIND_TITLES[k]
    )
    right.checkbox("Unreviewed only", key="review_unreviewed_only")
    kinds = st.session_state["review_kinds"]
    items = [
        item
        for item in queue
        if item.kind in kinds
        and not (
            st.session_state.get("review_unreviewed_only")
            and item.id in decisions
            and decisions[item.id].item_sha256 == item.sha256
        )
    ]
    _queue_form(data, items, decisions, "review_records_form")


def _negative_space(
    data: RunData, queue: list[ReviewItem], decisions: dict[str, ReviewDecision]
) -> None:
    st.text(
        "Passages no record cites, sampled with a seed from the run id. Mark each clear, or"
        " missed when it holds an obligation the extraction lost."
    )
    _queue_form(data, [i for i in queue if i.kind == "passage"], decisions, "review_passages_form")


def _sync(data: RunData) -> None:
    done = actions.run(actions.phoenix_sync(data.run_dir))
    st.code((done.stdout or "") + (done.stderr or ""), language=None)
    st.cache_data.clear()


def _progress(queue: list[ReviewItem], decisions: dict[str, ReviewDecision]) -> None:
    done = progress(queue, decisions)
    columns = st.columns(4)
    columns[0].metric("Reviewed", f"{done.reviewed} of {done.total}")
    columns[1].metric("Stale", done.stale)
    columns[2].metric(
        "Rejected or missed", done.by_verdict.get("reject", 0) + done.by_verdict.get("missed", 0)
    )
    columns[3].metric("Flagged", done.by_verdict.get("flag", 0))
    st.progress(done.reviewed / done.total if done.total else 0.0)
    st.dataframe(
        [
            {"kind": KIND_TITLES[kind], "reviewed": f"{n} of {total}"}
            for kind, (n, total) in sorted(
                done.by_kind.items(), key=lambda kv: KIND_ORDER.index(kv[0])
            )
        ],
        hide_index=True,
    )


def render_review_page() -> None:
    st.title("Bidwright: Review")
    st.text(STATUS_LINE)
    data = current_run()
    if data is None:
        st.text("No run folders with run_manifest.json found under outputs/.")
        return
    default("review_auto_sync", True)
    queue = review_queue(data.run_dir)
    decisions = latest(data.run_dir)
    left, right = st.columns([2, 1])
    left.text_input("Your role (never a name)", key="review_role")
    right.checkbox("Send verdicts to Phoenix as they are recorded", key="review_auto_sync")
    _progress(queue, decisions)
    if st.session_state.get("review_output"):
        st.code(st.session_state.pop("review_output"), language=None)
    gate, records, passages, quarantine = st.tabs(
        ["Solution gate", "Records", "Negative space", "Quarantine report and open questions"]
    )
    with gate:
        _gate(data)
    with records:
        _records(data, queue, decisions)
    with passages:
        _negative_space(data, queue, decisions)
    with quarantine:
        _quarantine(data)
    if links_for(data).available and st.button(
        "Send this run's review to Phoenix", key="review_sync"
    ):
        _sync(data)


def _quarantine(data: RunData) -> None:
    if data.quarantine_text is not None:
        st.code(data.quarantine_text, language=None)
    else:
        st.text("No review/quarantine.md for this run.")
    bundle = data.summary_bundle
    if bundle is None:
        return
    rows = [
        {"id": "", "origin": "summary", "text": q.text, "passages": ", ".join(q.src_ids)}
        for q in bundle.open_questions
    ] + [
        {"id": q.id, "origin": q.origin, "text": q.text, "passages": ", ".join(q.src_ids)}
        for q in bundle.brief_questions
    ]
    if rows:
        st.dataframe(rows, hide_index=True)


render_review_page()
