"""The Review page (`WP-3.6`, `CH-94`): for a run waiting at `solution_gate`, shows
`review/solution_gate.md`, options ranking, capability map, manifest work packages, and the
approval form (which runs `bidwright approve` via subprocess with `--edit -` on standard input,
writing no file directly). For a run not waiting at the gate, shows its approval file. Also shows
`review/quarantine.md` and open questions strictly as plain text and tables, never Markdown/HTML.
"""

from typing import Any

import streamlit as st

import app.data as app_data
from app.data import (
    RunData,
    allowed_edit_fields,
    build_approve_command,
    select_run_data,
)
from bidwright.render import STATUS_LINE


def _render_waiting_gate(data: RunData) -> None:
    st.header("Solution gate (review/solution_gate.md)")
    if data.gate_text is not None:
        st.code(data.gate_text, language=None)
    else:
        st.text("No review/solution_gate.md found for this run.")

    if data.options is not None and data.options.options:
        st.subheader("Options ranking")
        st.table(
            [
                {
                    "rank": opt.rank,
                    "id": opt.id,
                    "name": opt.name,
                    "total": opt.total,
                    "baseline": str(opt.baseline),
                    "needs_proof": ", ".join(opt.needs_proof),
                    "failed_gates": ", ".join(opt.failed_gates),
                    "summary": opt.summary,
                }
                for opt in data.options.options
            ]
        )

    if data.capability_map is not None and data.capability_map.rows:
        st.subheader("Capability map")
        st.table(
            [
                {
                    "need_id": row.need_id,
                    "origin": row.origin,
                    "status": row.status,
                    "decision": row.decision or "NONE",
                    "text": row.text,
                    "claim_ids": ", ".join(row.claim_ids),
                    "reason": row.reason,
                }
                for row in data.capability_map.rows
            ]
        )

    if data.solution_manifest is not None and data.solution_manifest.work_packages:
        st.subheader("Manifest work packages")
        st.table(
            [
                {
                    "code": wp.code,
                    "name": wp.name,
                    "scope": wp.scope,
                    "exclusions": wp.exclusions,
                    "acceptance": wp.acceptance,
                    "low_days": wp.effort.low_days if wp.effort else 0.0,
                    "high_days": wp.effort.high_days if wp.effort else 0.0,
                    "predecessors": ", ".join(wp.predecessors),
                    "evidence_class": wp.evidence_class,
                }
                for wp in data.solution_manifest.work_packages
            ]
        )

    st.subheader("Gate approval form")
    editable = allowed_edit_fields(data.solution_manifest)
    option_choices = ["(keep current)"]
    if data.options is not None:
        option_choices.extend(opt.id for opt in data.options.options)

    with st.form("solution_gate_form"):
        role = st.text_input("Approver role", value="", key="gate_role")
        selected_option = st.selectbox(
            "Option",
            options=option_choices,
            index=0,
            key="gate_option",
        )
        widget_values: dict[str, Any] = {}
        all_wp_codes = [
            wp.code
            for wp in (
                data.solution_manifest.work_packages if data.solution_manifest is not None else []
            )
        ]
        for field_path, (kind, default_val) in editable.items():
            widget_key = f"edit:{field_path}"
            if kind == "float":
                widget_values[field_path] = st.number_input(
                    field_path,
                    min_value=0.0,
                    value=float(default_val),
                    step=0.5,
                    key=widget_key,
                )
            elif kind == "predecessors":
                wp_code = field_path.split("[", 1)[1].split("]", 1)[0]
                other_codes = [code for code in all_wp_codes if code != wp_code]
                widget_values[field_path] = st.multiselect(
                    field_path,
                    options=other_codes,
                    default=list(default_val),
                    key=widget_key,
                )
            else:
                widget_values[field_path] = st.text_input(
                    field_path,
                    value=str(default_val),
                    key=widget_key,
                )
        override_reason = st.text_input("Override reason", value="", key="gate_override")
        reject_reason = st.text_input("Reject reason", value="", key="gate_reject")
        submitted = st.form_submit_button("Submit gate decision")

    if submitted:
        edits: list[dict[str, Any]] = []
        for field_path, (kind, default_val) in editable.items():
            current = widget_values[field_path]
            if kind == "float":
                if float(current) != float(default_val):
                    edits.append({"field": field_path, "value": float(current)})
            elif kind == "predecessors":
                if list(current) != list(default_val):
                    edits.append({"field": field_path, "value": list(current)})
            else:
                if str(current) != str(default_val):
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
            completed = app_data.run_approve(cmd, stdin_text)
            combined_out = (completed.stdout or "") + (completed.stderr or "")
            st.text(f"Exit code: {completed.returncode}")
            if combined_out.strip():
                st.code(combined_out, language=None)
        except ValueError as exc:
            st.text(f"Refused: {exc}")


def _render_approval_record(data: RunData) -> None:
    st.header("Gate approval (review/solution_gate.approval.yaml)")
    if data.gate_approval_text is not None:
        if data.gate_approval is not None:
            st.text(
                f"Decision: {data.gate_approval.decision} | "
                f"Role: {data.gate_approval.approver_role} | "
                f"Option: {data.gate_approval.option_id or 'None'}"
            )
        st.code(data.gate_approval_text, language=None)
    else:
        st.text("No review/solution_gate.approval.yaml found for this run.")


def render_review_page() -> None:
    st.title("Bidwright — Review")
    st.text(STATUS_LINE)
    data = select_run_data()
    if data is None:
        return

    if data.manifest.status == "WAITING_HUMAN":
        _render_waiting_gate(data)
    else:
        _render_approval_record(data)

    st.header("Quarantine and suspect text (review/quarantine.md)")
    if data.quarantine_text is not None:
        st.code(data.quarantine_text, language=None)
    else:
        st.text("No review/quarantine.md found for this run.")

    st.header("Open questions")
    bundle = data.summary_bundle
    if bundle is None:
        st.text("No solution_summary.json found for this run.")
        return

    rows = [
        {
            "id": "",
            "origin": "summary",
            "text": q.text,
            "src_ids": ", ".join(q.src_ids),
        }
        for q in bundle.open_questions
    ] + [
        {
            "id": q.id,
            "origin": q.origin,
            "text": q.text,
            "src_ids": ", ".join(q.src_ids),
        }
        for q in bundle.brief_questions
    ]
    if rows:
        st.table(rows)
        for row in rows:
            label = f"{row['id']}: " if row["id"] else ""
            st.text(f"{label}{row['text']} [{row['src_ids']}]")
    else:
        st.text("None.")


render_review_page()
