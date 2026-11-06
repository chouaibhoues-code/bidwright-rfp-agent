"""The Run page (`WP-3.6`, `CH-94`): run manifest, solution summary's four parts, capability map
by status, solution manifest breakdown tree (with dictionary, effort, evidence class and checks),
technology verdicts, and the compliance matrix table. Every artifact is rendered as plain text or
table cells, never as Markdown or HTML.
"""

import streamlit as st

from app.data import Requirement, select_run_data
from bidwright.render import STATUS_LINE
from bidwright.schemas import SolutionManifest, WorkPackage


def _wbs_sort_key(code: str) -> tuple[int, ...]:
    return tuple(int(part) if part.isdigit() else 0 for part in code.split("."))


def _requirement_rows(items: list[Requirement]) -> list[dict[str, str]]:
    return [
        {
            "id": req.id,
            "disposition": req.disposition,
            "modality": req.modality,
            "statement": req.statement,
            "src_ids": ", ".join(req.src_ids),
            "quote": req.quote,
            "quote_status": req.quote_status,
        }
        for req in items
    ]


def _effort_summary(wp: WorkPackage) -> str:
    if wp.effort is None:
        return "None"
    roles = ", ".join(wp.effort.role_ids) if wp.effort.role_ids else "none"
    return (
        f"{wp.effort.low_days:g}-{wp.effort.high_days:g}d "
        f"({wp.effort.basis}, {wp.effort.maturity}, provisional={wp.effort.provisional}, "
        f"roles={roles})"
    )


def _render_manifest_section(sol: SolutionManifest) -> None:
    st.header("Solution manifest")
    st.text(f"Option: {sol.option_id or 'None'} | Revision: {sol.revision} | Failed: {sol.failed}")

    st.subheader("Breakdown tree")
    ws_by_code = {ws.code: (ws.name, ws.objective) for ws in sol.workstreams}
    wbs_by_code = {node.code: (node.name, node.deliverable) for node in sol.wbs}
    children_by_parent: dict[str, list[WorkPackage]] = {}
    for wp in sorted(sol.work_packages, key=lambda item: _wbs_sort_key(item.code)):
        parent_code = wp.code.rsplit(".", 1)[0] if "." in wp.code else wp.code
        children_by_parent.setdefault(parent_code, []).append(wp)

    parent_codes = sorted(
        set(ws_by_code) | set(wbs_by_code) | set(children_by_parent),
        key=_wbs_sort_key,
    )
    for code in parent_codes:
        if code in ws_by_code:
            ws_name, ws_obj = ws_by_code[code]
            st.text(f"Workstream {code}: {ws_name} — {ws_obj}")
        if code in wbs_by_code:
            node_name, deliverable = wbs_by_code[code]
            st.text(f"WBS {code}: {node_name} ({deliverable})")
        for wp in children_by_parent.get(code, []):
            parent_name = wbs_by_code.get(code, ws_by_code.get(code, (code, "")))[0]
            effort_str = _effort_summary(wp)
            st.text(
                f"Parent {code} ({parent_name}) -> {wp.code} {wp.name} "
                f"[{wp.evidence_class}] (deliverable: {wp.deliverable})"
            )
            st.text(
                f"  Dictionary — scope: {wp.scope} | exclusions: {wp.exclusions} | "
                f"acceptance: {wp.acceptance}"
            )
            st.text(
                f"  Effort: {effort_str} | Predecessors: {', '.join(wp.predecessors) or 'None'} | "
                f"Needs proof: {wp.needs_proof} | Untraced: {wp.untraced}"
            )

    if sol.work_packages:
        st.table(
            [
                {
                    "parent": wp.code.rsplit(".", 1)[0] if "." in wp.code else wp.code,
                    "code": wp.code,
                    "name": wp.name,
                    "deliverable": wp.deliverable,
                    "scope": wp.scope,
                    "exclusions": wp.exclusions,
                    "acceptance": wp.acceptance,
                    "effort": _effort_summary(wp),
                    "evidence_class": wp.evidence_class,
                    "needs_proof": str(wp.needs_proof),
                    "untraced": str(wp.untraced),
                }
                for wp in sorted(sol.work_packages, key=lambda item: _wbs_sort_key(item.code))
            ]
        )

    st.subheader("Manifest checks")
    if sol.checks:
        st.table(
            [
                {
                    "name": chk.name,
                    "passed": "PASS" if chk.passed else "FAIL",
                    "detail": chk.detail,
                }
                for chk in sol.checks
            ]
        )
        for chk in sol.checks:
            st.text(f"{chk.name}: {'PASS' if chk.passed else 'FAIL'} — {chk.detail}")
    else:
        st.text("No manifest checks recorded.")


def render_run_page() -> None:
    st.title("Bidwright — Run")
    st.text(STATUS_LINE)
    data = select_run_data()
    if data is None:
        return

    manifest = data.manifest
    st.header("Run manifest")
    st.text(f"Run ID: {manifest.run_id}")
    st.text(f"Status: {manifest.status}")
    st.text(f"Reason: {manifest.status_reason or 'None'}")
    st.text(f"Profile: {manifest.profile} | Commit: {manifest.commit}")
    st.text(f"Started: {manifest.started} | Ended: {manifest.ended or 'None'}")

    st.subheader("Models")
    model_rows = [
        {
            "role": role,
            "model": model_spec,
        }
        for role, model_spec in manifest.models.items()
    ]
    if model_rows:
        st.table(model_rows)
    else:
        st.text("No models recorded.")

    st.subheader("Prompt versions")
    prompt_rows = [
        {
            "prompt": name,
            "sha256": digest,
        }
        for name, digest in manifest.prompt_hashes.items()
    ]
    if prompt_rows:
        st.table(prompt_rows)
    else:
        st.text("No prompts recorded.")

    st.subheader("Manifest totals")
    st.table([manifest.totals.model_dump(mode="json")])

    if data.capability_map is not None:
        st.header("Capability map")
        if data.capability_map.counts:
            st.table([dict(data.capability_map.counts)])
        for status in ("COVERED", "PARTIAL", "PARTNER", "GAP"):
            rows_for_status = [row for row in data.capability_map.rows if row.status == status]
            st.subheader(f"Capability map — {status}")
            if rows_for_status:
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
                        for row in rows_for_status
                    ]
                )
                for row in rows_for_status:
                    st.text(
                        f"{row.need_id} [{row.status}] ({row.origin}, "
                        f"{row.decision or 'NONE'}): {row.text} — {row.reason}"
                    )
            else:
                st.text("None.")

    if data.solution_manifest is not None:
        _render_manifest_section(data.solution_manifest)

    if data.tech_validations:
        st.header("Technology verdicts")
        st.table(
            [
                {
                    "claim_id": tv.claim_id,
                    "library": tv.library or "",
                    "version": tv.version or "",
                    "verdict": tv.verdict,
                    "source": tv.source or "",
                    "reason": tv.reason,
                    "quote": tv.quote,
                    "revision": tv.revision,
                }
                for tv in data.tech_validations
            ]
        )
        for tv in data.tech_validations:
            st.text(
                f"{tv.claim_id} ({tv.library or 'none'} {tv.version or ''}): "
                f"{tv.verdict} — {tv.reason} [{tv.quote}]"
            )

    bundle = data.summary_bundle
    if bundle is not None:
        st.header("Solution summary")
        st.subheader("1. Requirements — Submission hazards")
        if bundle.hazards:
            st.table(_requirement_rows(bundle.hazards))
            for req in bundle.hazards:
                st.text(
                    f'{req.id} ({req.modality}): {req.statement} [{req.src_ids[0]}] "{req.quote}"'
                )
        else:
            st.text("None found.")

        if bundle.brief and bundle.brief.factors:
            st.subheader("Evaluation factors")
            st.table(
                [
                    {
                        "id": factor.id,
                        "name": factor.name,
                        "weight": factor.weight,
                        "status": factor.status,
                        "src_ids": ", ".join(factor.src_ids),
                    }
                    for factor in bundle.brief.factors
                ]
            )

        st.subheader("1. Requirements — Mandatory requirements")
        if bundle.binding:
            st.table(_requirement_rows(bundle.binding))
            for req in bundle.binding:
                st.text(
                    f'{req.id} ({req.modality}): {req.statement} [{req.src_ids[0]}] "{req.quote}"'
                )
        else:
            st.text("None found.")

        st.subheader("1. Requirements — Optional requirements")
        if bundle.optional:
            st.table(_requirement_rows(bundle.optional))
            for req in bundle.optional:
                st.text(
                    f'{req.id} ({req.modality}): {req.statement} [{req.src_ids[0]}] "{req.quote}"'
                )
        else:
            st.text("None found.")

        if bundle.summary.counts:
            st.table([dict(bundle.summary.counts)])

        st.subheader("2. Approach")
        if bundle.approach:
            st.table(
                [
                    {
                        "id": item.id,
                        "requirements": ", ".join(item.requirement_ids),
                        "basis": item.basis,
                        "text": item.text,
                    }
                    for item in bundle.approach
                ]
            )
            for item in bundle.approach:
                st.text(f"{item.id} ({', '.join(item.requirement_ids)}): {item.text}")
        else:
            st.text("No approach items.")
        if bundle.unmapped_requirement_ids:
            st.text(f"Unmapped requirements: {', '.join(bundle.unmapped_requirement_ids)}")

        st.subheader("3. Risks")
        if bundle.risks:
            st.table(
                [
                    {
                        "id": risk.id,
                        "condition": risk.condition,
                        "event": risk.event,
                        "effect": risk.effect,
                        "owner_role": risk.owner_role,
                        "trigger": risk.trigger,
                        "responses": " ".join(risk.responses),
                        "residual_exposure": risk.residual_exposure,
                        "evidence_src_ids": ", ".join(risk.evidence_src_ids),
                    }
                    for risk in bundle.risks
                ]
            )
        else:
            st.text("No risks passed the checks.")

        st.subheader("4. Open questions")
        question_rows = [
            {"id": "", "text": q.text, "src_ids": ", ".join(q.src_ids)}
            for q in bundle.open_questions
        ] + [
            {"id": q.id, "text": q.text, "src_ids": ", ".join(q.src_ids)}
            for q in bundle.brief_questions
        ]
        if question_rows:
            st.table(question_rows)
            for row in question_rows:
                prefix = f"{row['id']} " if row["id"] else ""
                st.text(f"{prefix}{row['text']} ({row['src_ids']})")
        else:
            st.text("None.")

        if bundle.domain_brief and (bundle.domain_brief.items or bundle.domain_brief.needs):
            st.subheader("Appendix: domain research (external, unverified)")
            if bundle.domain_brief.items:
                st.table(
                    [
                        {
                            "id": item.id,
                            "kind": item.kind,
                            "statement": item.statement,
                            "excerpt_ids": ", ".join(item.excerpt_ids),
                        }
                        for item in bundle.domain_brief.items
                    ]
                )
            if bundle.domain_brief.needs:
                st.table(
                    [
                        {
                            "id": need.id,
                            "need": need.need,
                            "excerpt_ids": ", ".join(need.excerpt_ids),
                        }
                        for need in bundle.domain_brief.needs
                    ]
                )

    st.header("Compliance matrix")
    if data.compliance_rows:
        st.dataframe(data.compliance_rows)
    else:
        st.text("No compliance_matrix.xlsx found for this run.")


render_run_page()
