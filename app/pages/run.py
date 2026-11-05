"""The Run page (`WP-3.6`, `CH-94`): run manifest, solution summary's four parts, and the
compliance matrix table. Every artifact is rendered as plain text or table cells, never as
Markdown or HTML.
"""

import streamlit as st

from app.data import Requirement, select_run_data
from bidwright.render import STATUS_LINE


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
