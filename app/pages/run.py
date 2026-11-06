"""The Run page (WP-3.6, ADR-053): start a run, follow it live, steer it, and read what it
produced.

- Start: a form over the corpus inputs and the run's settings, which starts `bidwright run`;
  without automatic approval the run stops at the solution gate for a person. The demo
  replays with no keys.
- Follow: while the run is RUNNING the panel refreshes every two seconds: its status, its
  spend against its limits, its latest events and calls, and Stop; a paused or stopped run
  offers Resume; a run waiting at the gate points to the Review page.
- Read: the requirements with filters, each with the passages it quotes beside it and a link
  to the extract call in Phoenix; the solution; the risks with their evidence; the files.

Every artifact is shown as plain text or table cells, never as Markdown or HTML, and the page
writes no file: each action runs the CLI.
"""

from pathlib import Path
from typing import Any

import streamlit as st

import app.actions as actions
from app.data import (
    RunData,
    extract_batches,
    load_budget,
    load_events,
    load_manifest,
    load_passages,
    run_limits,
)
from app.phoenix_view import links_for, span_url
from app.state import current_run, default, run_names, select_run
from bidwright.obs.phoenix import run_spans
from bidwright.render import STATUS_LINE
from bidwright.schemas import Requirement, SolutionManifest

RESUMABLE = ("STOPPED", "QUOTA_PAUSED", "BUDGET_EXCEEDED")
KINDS = ("Submission hazards", "Mandatory", "Optional")
FILES = (
    ("solution_summary.md", "text/plain"),
    ("solution_summary.json", "application/json"),
    ("proposal.md", "text/plain"),
    ("clarification_questions.md", "text/plain"),
    ("bid_memo.md", "text/plain"),
    ("compliance_matrix.csv", "text/csv"),
    (
        "compliance_matrix.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
)


def _jobs() -> list[actions.Job]:
    return st.session_state.setdefault("jobs", [])


# --- Start ---------------------------------------------------------------------------------


def _launcher() -> None:
    sources = actions.inputs()
    default("launch_profile", "free")
    default("launch_research", "pack")
    default("launch_solution", "manifest")
    default("launch_risk_mode", "agent")
    default("launch_reflect", False)
    default("launch_until", "render")
    default("launch_auto_select", False)
    with st.form("launch_form"):
        st.selectbox("RFP file or package under inputs/", sources, key="launch_input")
        left, middle, right = st.columns(3)
        left.selectbox("Profile", actions.PROFILES, key="launch_profile")
        middle.selectbox("Research", actions.RESEARCH, key="launch_research")
        right.selectbox("Last node", actions.UNTIL, key="launch_until")
        left.selectbox("Solution path", actions.SOLUTIONS, key="launch_solution")
        middle.selectbox("Risk", actions.RISK_MODES, key="launch_risk_mode")
        right.checkbox("Offer the reflect tool", key="launch_reflect")
        st.checkbox(
            "Approve the top-ranked option automatically (for evaluation; a person decides"
            " otherwise)",
            key="launch_auto_select",
        )
        started = st.form_submit_button("Start the run")
    if started:
        request = actions.LaunchRequest(
            source=str(st.session_state.get("launch_input") or ""),
            profile=st.session_state["launch_profile"],
            research=st.session_state["launch_research"],
            solution=st.session_state["launch_solution"],
            risk_mode=st.session_state["launch_risk_mode"],
            reflect=bool(st.session_state["launch_reflect"]),
            until=st.session_state["launch_until"],
            auto_select=bool(st.session_state["launch_auto_select"]),
        )
        request.run_id = actions.new_run_id(request.source, request.profile)
        try:
            command = request.command()
        except ValueError as exc:
            st.error(f"Refused: {exc}")
            return
        _jobs().append(actions.start(f"run {request.run_id}", command, request.run_id))
        st.session_state["pending_run"] = request.run_id
        st.success("Started. The run appears in the selector once its folder exists.")
    if st.button("Replay the demo (no keys)", key="launch_demo"):
        _jobs().append(actions.start("demo", actions.demo()))
        st.session_state["pending_newest"] = True


def _running(jobs: list[actions.Job]) -> bool:
    return any(job.poll() is None for job in jobs)


def _job_panel() -> None:
    """The commands this session started; refreshed every two seconds while one runs."""
    jobs = _jobs()
    if not jobs:
        return
    st.fragment(_job_list, run_every=2.0 if _running(jobs) else None)()


def _job_list() -> None:
    jobs = _jobs()
    st.subheader("Commands started here")
    for job in reversed(jobs[-5:]):
        code = job.poll()
        state = "running" if code is None else f"ended, exit status {code}"
        st.text(f"{job.label}: {state} ({job.elapsed:.0f} s)")
        if job.output:
            st.code(job.output[-3000:], language=None)
    pending = st.session_state.get("pending_run")
    if pending and pending in run_names():
        select_run(pending)
        st.session_state.pop("pending_run", None)
        st.rerun()
    if st.session_state.get("pending_newest") and not _running(jobs):
        names = list(run_names())
        st.session_state.pop("pending_newest", None)
        if names:
            select_run(names[0])
            st.rerun()


# --- Follow ----------------------------------------------------------------------------------


def _spend(run_dir: Path, limits: dict[str, float] | None) -> None:
    budget = load_budget(run_dir)
    if budget is None or limits is None:
        return
    used = (
        ("Requests", float(budget.get("attempts", 0)), limits["requests"]),
        ("Tokens", float(budget.get("tokens", 0)), limits["tokens"]),
        ("Active minutes", float(budget.get("active_seconds", 0)) / 60, limits["active_minutes"]),
    )
    for column, (label, value, limit) in zip(st.columns(3), used, strict=True):
        column.metric(label, f"{value:,.0f} of {limit:,.0f}")
        column.progress(min(value / limit, 1.0) if limit else 0.0)


def _controls(data: RunData, status: str) -> None:
    if status == "RUNNING":
        if st.button("Stop at the end of the current step", key="run_stop"):
            done = actions.run(actions.stop(data.run_dir))
            st.code((done.stdout or "") + (done.stderr or ""), language=None)
    elif status in RESUMABLE:
        raise_budget = st.number_input(
            "Raise each limit by this percent (0 for none)", 0, 500, 0, step=25, key="run_raise"
        )
        paid = (
            st.checkbox("Continue on the paid key", key="run_paid")
            if status == "QUOTA_PAUSED"
            else False
        )
        if st.button("Resume the run", key="run_resume"):
            command = actions.resume(data.run_dir, raise_budget or None, paid)
            _jobs().append(actions.start(f"resume {data.manifest.run_id}", command))
            st.rerun()
    elif status == "WAITING_HUMAN":
        st.warning("The run waits at the solution gate for a person's decision.")
        st.page_link("pages/review.py", label="Decide the gate on the Review page")


def _monitor(run_dir: Path, shown: str) -> None:
    """The run's state, read again at each refresh; a change of status reruns the page, so the
    controls and the results follow it."""
    manifest = load_manifest(run_dir)
    status = manifest.status
    if status != shown:
        st.rerun()
    st.text(f"Run {manifest.run_id}: {status}")
    if manifest.status_reason:
        st.text(manifest.status_reason)
    _spend(run_dir, run_limits(manifest))
    events = load_events(run_dir)[-8:]
    if events:
        st.dataframe(
            [
                {
                    "at": e.get("at"),
                    "kind": e.get("kind"),
                    "node": e.get("node") or "",
                    "detail": e.get("detail"),
                }
                for e in reversed(events)
            ],
            hide_index=True,
        )


def _follow(data: RunData) -> None:
    st.header("Follow and steer")
    status = data.manifest.status
    refresh = 2.0 if status == "RUNNING" else None
    st.fragment(_monitor, run_every=refresh)(data.run_dir, status)
    _controls(data, status)


# --- Read ------------------------------------------------------------------------------------


def _kind(req: Requirement) -> str:
    return KINDS[0] if req.hazard else KINDS[1] if req.mandatory else KINDS[2]


def _requirements(data: RunData) -> None:
    bundle = data.summary_bundle
    if bundle is None:
        st.text("No solution_summary.json yet.")
        return
    default("run_kinds", list(KINDS))
    left, right = st.columns([2, 1])
    left.text_input("Search the statements and quotes", key="run_search")
    right.multiselect("Show", KINDS, key="run_kinds")
    words = str(st.session_state.get("run_search") or "").lower().split()
    shown = [
        r
        for r in bundle.requirements
        if r.disposition in ("BINDING", "OPTIONAL")
        and _kind(r) in st.session_state["run_kinds"]
        and all(w in f"{r.statement} {r.quote}".lower() for w in words)
    ]
    order = {k: n for n, k in enumerate(KINDS)}
    shown.sort(key=lambda r: (order[_kind(r)], r.id))
    st.dataframe(
        [
            {
                "id": r.id,
                "kind": _kind(r),
                "modality": r.modality,
                "statement": r.statement,
                "quote status": r.quote_status,
                "passages": ", ".join(r.src_ids),
            }
            for r in shown
        ],
        hide_index=True,
    )
    st.text(f"{len(shown)} of {len(bundle.requirements)} requirements shown")
    if not shown:
        return
    ids = [r.id for r in shown]
    if st.session_state.get("run_tab_requirement") not in ids:
        st.session_state["run_tab_requirement"] = ids[0]
    st.selectbox("Check one against its source", ids, key="run_tab_requirement")
    chosen = next(r for r in shown if r.id == st.session_state["run_tab_requirement"])
    _source_view(data, chosen)


def _source_view(data: RunData, req: Requirement) -> None:
    passages = load_passages(data.run_dir)
    st.text(f"{req.id} ({req.modality}, {req.disposition}): {req.statement}")
    st.text(f"Quote ({req.quote_status}):")
    st.code(req.quote, language=None)
    for src in req.src_ids:
        passage = passages.get(src)
        if passage is None:
            continue
        st.text(f"{src}, {passage.get('section_path', '')}:")
        st.code(passage.get("text", ""), language=None)
    batch = next((b for s in req.src_ids if (b := extract_batches(data.run_dir).get(s))), None)
    if batch:
        links = links_for(data)
        url = span_url(data, links, run_spans(data.run_dir).node("extract", batch))
        if url:
            st.link_button(f"Open the extract call {batch} in Phoenix", url)
        else:
            st.text(f"Read by the extract call {batch}.")


def _solution(data: RunData) -> None:
    if data.capability_map is not None:
        st.subheader("Capability map")
        st.table([dict(data.capability_map.counts)] if data.capability_map.counts else [])
        st.dataframe(
            [
                {
                    "need": row.need_id,
                    "status": row.status,
                    "origin": row.origin,
                    "decision": row.decision or "",
                    "text": row.text,
                    "claims": ", ".join(row.claim_ids),
                    "reason": row.reason,
                }
                for row in data.capability_map.rows
            ],
            hide_index=True,
        )
        for status in ("COVERED", "PARTIAL", "PARTNER", "GAP"):
            for row in (r for r in data.capability_map.rows if r.status == status):
                st.text(
                    f"{row.need_id} [{row.status}] ({row.origin}, {row.decision or 'NONE'}):"
                    f" {row.text} — {row.reason}"
                )
    if data.options is not None and data.options.options:
        st.subheader("Options")
        st.dataframe(
            [
                {
                    "rank": o.rank,
                    "id": o.id,
                    "name": o.name,
                    "total": o.total,
                    "needs proof": ", ".join(o.needs_proof),
                    "failed gates": ", ".join(o.failed_gates),
                    "summary": o.summary,
                }
                for o in data.options.options
            ],
            hide_index=True,
        )
    if data.solution_manifest is not None:
        _manifest(data.solution_manifest)
    if data.tech_validations:
        st.subheader("Technology verdicts")
        st.dataframe(
            [
                {
                    "claim": tv.claim_id,
                    "library": tv.library or "",
                    "verdict": tv.verdict,
                    "reason": tv.reason,
                    "quote": tv.quote,
                }
                for tv in data.tech_validations
            ],
            hide_index=True,
        )
        for tv in data.tech_validations:
            st.text(
                f"{tv.claim_id} ({tv.library or 'none'} {tv.version or ''}): {tv.verdict}"
                f" — {tv.reason} [{tv.quote}]"
            )
    if data.bid_signal is not None:
        st.subheader("Bid signal")
        st.text(f"{data.bid_signal.signal}: a person decides.")
        if data.bid_memo_text:
            st.code(data.bid_memo_text, language=None)
    if data.capability_map is None and data.solution_manifest is None:
        st.text("This run took no solution path past the approach.")


def _code_key(code: str) -> list[int]:
    return [int(part) for part in code.split(".") if part.isdigit()]


def _tree(sol: SolutionManifest) -> None:
    """The breakdown as a tree: each workstream and WBS node, and each work package under its
    parent with its dictionary, effort and evidence class."""
    names = {ws.code: ws.name for ws in sol.workstreams} | {n.code: n.name for n in sol.wbs}
    for ws in sorted(sol.workstreams, key=lambda w: _code_key(w.code)):
        st.text(f"Workstream {ws.code}: {ws.name} — {ws.objective}")
    for node in sorted(sol.wbs, key=lambda n: _code_key(n.code)):
        st.text(f"{'  ' * node.code.count('.')}WBS {node.code}: {node.name} ({node.deliverable})")
    for wp in sorted(sol.work_packages, key=lambda p: _code_key(p.code)):
        parent = wp.code.rsplit(".", 1)[0] if "." in wp.code else wp.code
        effort = (
            f"{wp.effort.low_days:g}-{wp.effort.high_days:g} days ({wp.effort.basis},"
            f" {wp.effort.maturity})"
            if wp.effort
            else "none"
        )
        st.text(
            f"Parent {parent} ({names.get(parent, parent)}) -> {wp.code} {wp.name}"
            f" [{wp.evidence_class}]"
        )
        st.text(
            f"    scope: {wp.scope} | exclusions: {wp.exclusions} | acceptance: {wp.acceptance}"
            f" | effort: {effort} | predecessors: {', '.join(wp.predecessors) or 'none'}"
        )


def _manifest(sol: SolutionManifest) -> None:
    st.subheader("Solution manifest")
    st.text(f"Option {sol.option_id or 'none'}, revision {sol.revision}, failed: {sol.failed}")
    _tree(sol)
    st.dataframe(
        [
            {
                "code": wp.code,
                "name": wp.name,
                "deliverable": wp.deliverable,
                "effort (days)": f"{wp.effort.low_days:g}-{wp.effort.high_days:g}"
                if wp.effort
                else "",
                "predecessors": ", ".join(wp.predecessors),
                "evidence": wp.evidence_class,
                "needs proof": wp.needs_proof,
                "scope": wp.scope,
                "acceptance": wp.acceptance,
            }
            for wp in sorted(
                sol.work_packages, key=lambda p: [int(x) for x in p.code.split(".") if x.isdigit()]
            )
        ],
        hide_index=True,
    )
    if sol.checks:
        st.table(
            [
                {"check": c.name, "result": "pass" if c.passed else "FAIL", "detail": c.detail}
                for c in sol.checks
            ]
        )


def _risks(data: RunData) -> None:
    bundle = data.summary_bundle
    if bundle is None:
        return
    passages = load_passages(data.run_dir)
    st.subheader("Risks")
    for risk in bundle.risks:
        st.text(f"{risk.id} ({risk.owner_role}): {risk.event}")
        st.text(f"Condition: {risk.condition}")
        st.text(f"Effect: {risk.effect}  |  Trigger: {risk.trigger}")
        st.text("Responses: " + " / ".join(risk.responses))
        for src in risk.evidence_src_ids:
            if src in passages:
                st.code(f"{src}: {passages[src]['text']}", language=None)
    if not bundle.risks:
        st.text("No risk passed the checks.")
    st.subheader("Open questions")
    rows: list[dict[str, Any]] = [
        {"id": "", "text": q.text, "passages": ", ".join(q.src_ids)} for q in bundle.open_questions
    ] + [
        {"id": q.id, "text": q.text, "passages": ", ".join(q.src_ids)}
        for q in bundle.brief_questions
    ]
    if rows:
        st.dataframe(rows, hide_index=True)
    else:
        st.text("None.")


def _files(data: RunData) -> None:
    for name, mime in FILES:
        path = data.run_dir / name
        if path.is_file():
            st.download_button(
                f"Download {name}", path.read_bytes(), file_name=name, mime=mime, key=f"dl:{name}"
            )
    if data.compliance_rows:
        st.subheader("Compliance matrix")
        st.dataframe(data.compliance_rows, hide_index=True)


def render_run_page() -> None:
    st.title("Bidwright: Run")
    st.text(STATUS_LINE)
    with st.expander("Start a run", expanded=not run_names()):
        _launcher()
    _job_panel()
    data = current_run()
    if data is None:
        return
    _follow(data)
    st.header("What the run produced")
    requirements, solution, risks, files = st.tabs(
        ["Requirements", "Solution", "Risks and questions", "Files"]
    )
    with requirements:
        _requirements(data)
    with solution:
        _solution(data)
    with risks:
        _risks(data)
    with files:
        _files(data)


render_run_page()
