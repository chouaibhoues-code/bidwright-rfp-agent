"""The Review page (WP-3.6, ADR-053): the person's work on a run, in the order of consequence.

- Gate: for a run waiting at `solution_gate`, what blocks it, the bid signal and memo, the
  ranking, the capability map and the work packages, then the decision form, which runs
  `bidwright approve` with the edits on standard input; the gate node writes the approval.
  For a run past the gate, its approval file.
- Records: the run's records from `review_queue`, hazards first, each with the verbatim source
  beside it, taking accept, correct (with the corrected text), reject or flag. The page runs
  `bidwright review`, the one writer of `review/decisions.jsonl`.
- Negative space: passages no record cites, each marked clear or missed.
- After each batch of verdicts the page can send them to Phoenix (`bidwright phoenix sync`),
  where they sit as HUMAN annotations on the spans that made the records.

Artifact text is shown as plain text, never as Markdown or HTML, and the page writes no file.
"""

from typing import Any

import streamlit as st
import yaml

import app.actions as actions
import app.data as app_data
from app.data import RunData, allowed_edit_fields, build_approve_command
from app.phoenix_view import links_for
from app.state import current_run, default
from bidwright.render import STATUS_LINE
from bidwright.review import KIND_ORDER, KIND_TITLES, ReviewItem, latest, progress, review_queue
from bidwright.schemas import ReviewDecision

NOT_REVIEWED = "(not reviewed)"
RECORD_KINDS = [k for k in KIND_ORDER if k != "passage"]


# --- the gate --------------------------------------------------------------------------------


def _gate_context(data: RunData) -> None:
    blocking = [tv.claim_id for tv in data.tech_validations if tv.verdict == "INVALIDATED"]
    if blocking:
        st.error(
            "Blocked by technology claims still INVALIDATED: "
            + ", ".join(blocking)
            + ". Approve only with an override reason, or reject."
        )
    if data.bid_signal is not None:
        st.text(f"Bid signal: {data.bid_signal.signal}; a person decides.")
        if data.bid_signal.missing_inputs:
            st.text("Missing inputs: " + ", ".join(data.bid_signal.missing_inputs))
    if data.bid_memo_text:
        with st.expander("Bid memo"):
            st.code(data.bid_memo_text, language=None)
    if data.gate_text is not None:
        with st.expander("The review file, review/solution_gate.md"):
            st.code(data.gate_text, language=None)
    if data.options is not None and data.options.options:
        st.subheader("Options ranking")
        st.dataframe(
            [
                {
                    "rank": opt.rank,
                    "id": opt.id,
                    "name": opt.name,
                    "total": opt.total,
                    "needs proof": ", ".join(opt.needs_proof),
                    "failed gates": ", ".join(opt.failed_gates),
                    "summary": opt.summary,
                }
                for opt in data.options.options
            ],
            hide_index=True,
        )
    if data.capability_map is not None and data.capability_map.rows:
        st.subheader("Capability map")
        st.dataframe(
            [
                {
                    "need": row.need_id,
                    "status": row.status,
                    "decision": row.decision or "",
                    "text": row.text,
                    "reason": row.reason,
                }
                for row in data.capability_map.rows
            ],
            hide_index=True,
        )


def _gate_form(data: RunData) -> None:
    st.subheader("Gate decision")
    editable = allowed_edit_fields(data.solution_manifest)
    option_choices = ["(keep current)"]
    if data.options is not None:
        option_choices.extend(opt.id for opt in data.options.options)
    codes = [
        wp.code for wp in (data.solution_manifest.work_packages if data.solution_manifest else [])
    ]
    with st.form("solution_gate_form"):
        role = st.text_input("Approver role", value="", key="gate_role")
        selected_option = st.selectbox("Option", options=option_choices, index=0, key="gate_option")
        widget_values: dict[str, Any] = {}
        st.text("Edits: change a value to edit it; unchanged values are left as they are.")
        for field_path, (kind, default_val) in editable.items():
            widget_key = f"edit:{field_path}"
            if kind == "float":
                widget_values[field_path] = st.number_input(
                    field_path, min_value=0.0, value=float(default_val), step=0.5, key=widget_key
                )
            elif kind == "predecessors":
                wp_code = field_path.split("[", 1)[1].split("]", 1)[0]
                widget_values[field_path] = st.multiselect(
                    field_path,
                    options=[c for c in codes if c != wp_code],
                    default=list(default_val),
                    key=widget_key,
                )
            else:
                widget_values[field_path] = st.text_input(
                    field_path, value=str(default_val), key=widget_key
                )
        override_reason = st.text_input("Override reason", value="", key="gate_override")
        reject_reason = st.text_input("Reject reason", value="", key="gate_reject")
        submitted = st.form_submit_button("Submit gate decision")
    if not submitted:
        return
    edits: list[dict[str, Any]] = []
    for field_path, (kind, default_val) in editable.items():
        current = widget_values[field_path]
        if kind == "float" and float(current) != float(default_val):
            edits.append({"field": field_path, "value": float(current)})
        elif kind == "predecessors" and list(current) != list(default_val):
            edits.append({"field": field_path, "value": list(current)})
        elif kind not in ("float", "predecessors") and str(current) != str(default_val):
            edits.append({"field": field_path, "value": str(current)})
    option_arg = None if selected_option == "(keep current)" else str(selected_option)
    try:
        cmd, stdin_text = build_approve_command(
            data.run_dir,
            role=role,
            option_id=option_arg,
            edits=edits,
            override_reason=override_reason,
            reject_reason=reject_reason,
            manifest=data.solution_manifest,
        )
    except ValueError as exc:
        st.text(f"Refused: {exc}")
        return
    st.text("Running: " + " ".join(cmd[1:] if cmd[0] == "bidwright" else cmd))
    with st.spinner("The run resumes from the gate; this lasts until its next stop."):
        completed = app_data.run_approve(cmd, stdin_text)
    st.text(f"Exit code: {completed.returncode}")
    combined = (completed.stdout or "") + (completed.stderr or "")
    if combined.strip():
        st.code(combined, language=None)


def _approval_record(data: RunData) -> None:
    if data.gate_approval_text is None:
        st.text("This run has no gate decision: it took no solution gate, or has not reached it.")
        return
    if data.gate_approval is not None:
        st.text(
            f"Decision: {data.gate_approval.decision} | Role: {data.gate_approval.approver_role}"
            f" | Option: {data.gate_approval.option_id or 'None'}"
            f" | Automatic: {data.gate_approval.auto_selected}"
        )
    st.code(data.gate_approval_text, language=None)


def _gate(data: RunData) -> None:
    if data.manifest.status == "WAITING_HUMAN":
        _gate_context(data)
        _gate_form(data)
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
