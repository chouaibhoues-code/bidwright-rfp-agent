"""Loopback-only FastAPI wrapper over `app/data.py`, `obs/replay.py` and the CLI (`WP-3.6`).

Exposes read-only inspection endpoints for every artifact the Streamlit Run, Review and Ops pages
display, plus safe control endpoints (`POST /runs/demo`, `POST /runs/{run_id}/stop` and
`POST /runs/{run_id}/spans/replay`). Every response includes `status_line` (`UNREVIEWED_DRAFT`),
`{run_id}` is resolved strictly against `list_runs()` so path traversal is impossible, and
`app/api.py` never writes run files directly.
"""

from collections.abc import Awaitable, Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.data import (
    RunData,
    list_runs,
    load_ladder_reports,
    load_matrix_totals,
    load_run_data,
    outputs_dir,
)
from bidwright import cli
from bidwright.obs.replay import replay_spans
from bidwright.preflight import Refused
from bidwright.render import STATUS_LINE

ALLOWED_HOSTS = frozenset({"127.0.0.1:8001", "localhost:8001"})

app = FastAPI(
    title="Bidwright API (UNREVIEWED_DRAFT)",
    version="0.3.0",
    description=STATUS_LINE,
)


@app.middleware("http")
async def _loopback_guard(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Enforce ADR-051: allow only loopback Host headers and require `X-Bidwright: 1` on POST."""
    host = request.headers.get("host", "").strip().lower()
    if host not in ALLOWED_HOSTS:
        return JSONResponse(
            status_code=400,
            content={
                "status_line": STATUS_LINE,
                "detail": f"Refused foreign Host header: {host!r}",
            },
        )
    if request.method.upper() == "POST" and request.headers.get("x-bidwright") != "1":
        return JSONResponse(
            status_code=403,
            content={
                "status_line": STATUS_LINE,
                "detail": "POST requests require header X-Bidwright: 1",
            },
        )
    return await call_next(request)


@app.exception_handler(StarletteHTTPException)
async def _with_status_line(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """ADR-051: every response carries the status line, an error's included, whether a route
    raised it or the router found no route."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"status_line": STATUS_LINE, "detail": exc.detail},
    )


class ReplayRequest(BaseModel):
    endpoint: str | None = None


def _resolve_run_dir(run_id: str) -> Path:
    """Resolve `run_id` strictly against `list_runs()` so arbitrary paths are never read."""
    for folder in list_runs():
        if folder.name == run_id:
            return folder
    raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")


def _serialize_summary(data: RunData) -> dict[str, Any] | None:
    bundle = data.summary_bundle
    if bundle is None:
        return None
    return {
        "summary": bundle.summary.model_dump(mode="json"),
        "requirements": [r.model_dump(mode="json") for r in bundle.requirements],
        "hazards": [r.model_dump(mode="json") for r in bundle.hazards],
        "binding": [r.model_dump(mode="json") for r in bundle.binding],
        "optional": [r.model_dump(mode="json") for r in bundle.optional],
        "approach": [a.model_dump(mode="json") for a in bundle.approach],
        "unmapped_requirement_ids": list(bundle.unmapped_requirement_ids),
        "risks": [r.model_dump(mode="json") for r in bundle.risks],
        "open_questions": [q.model_dump(mode="json") for q in bundle.open_questions],
        "brief_questions": [q.model_dump(mode="json") for q in bundle.brief_questions],
        "brief": bundle.brief.model_dump(mode="json") if bundle.brief else None,
        "domain_brief": (
            bundle.domain_brief.model_dump(mode="json") if bundle.domain_brief else None
        ),
    }


def _serialize_ledger(data: RunData) -> dict[str, Any]:
    return {
        "totals": asdict(data.ledger_totals),
        "by_node": [asdict(row) for row in data.by_node],
        "by_model": [asdict(row) for row in data.by_model],
        "entries": [entry.model_dump(mode="json") for entry in data.ledger],
    }


@app.get("/health")
def get_health() -> dict[str, str]:
    return {"status": "ok", "status_line": STATUS_LINE}


@app.get("/runs")
def get_runs() -> dict[str, Any]:
    runs = list_runs()
    return {
        "status_line": STATUS_LINE,
        "runs": [folder.name for folder in runs],
    }


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    run_dir = _resolve_run_dir(run_id)
    data = load_run_data(run_dir)
    return {
        "status_line": STATUS_LINE,
        "run_id": run_dir.name,
        "manifest": data.manifest.model_dump(mode="json"),
        "summary_bundle": _serialize_summary(data),
        "compliance_rows": data.compliance_rows,
        "quarantine_text": data.quarantine_text,
        "ledger": _serialize_ledger(data),
        "scores": {
            "scores": data.scores.scores,
            "scorecard_text": data.scores.scorecard_text,
        },
        "has_spans": data.has_spans,
        "capability_map": (
            data.capability_map.model_dump(mode="json") if data.capability_map else None
        ),
        "options": data.options.model_dump(mode="json") if data.options else None,
        "solution_manifest": (
            data.solution_manifest.model_dump(mode="json") if data.solution_manifest else None
        ),
        "tech_validations": [tv.model_dump(mode="json") for tv in data.tech_validations],
        "gate_text": data.gate_text,
        "gate_approval": (
            data.gate_approval.model_dump(mode="json") if data.gate_approval else None
        ),
        "bid_signal": data.bid_signal.model_dump(mode="json") if data.bid_signal else None,
        "bid_memo_text": data.bid_memo_text,
    }


@app.get("/runs/{run_id}/manifest")
def get_run_manifest(run_id: str) -> dict[str, Any]:
    run_dir = _resolve_run_dir(run_id)
    data = load_run_data(run_dir)
    return {
        "status_line": STATUS_LINE,
        "manifest": data.manifest.model_dump(mode="json"),
    }


@app.get("/runs/{run_id}/summary")
def get_run_summary(run_id: str) -> dict[str, Any]:
    run_dir = _resolve_run_dir(run_id)
    data = load_run_data(run_dir)
    summary = _serialize_summary(data)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"No solution_summary.json for run {run_id!r}")
    return {
        "status_line": STATUS_LINE,
        **summary,
    }


@app.get("/runs/{run_id}/matrix")
def get_run_matrix(run_id: str) -> dict[str, Any]:
    run_dir = _resolve_run_dir(run_id)
    data = load_run_data(run_dir)
    return {
        "status_line": STATUS_LINE,
        "rows": data.compliance_rows,
    }


@app.get("/runs/{run_id}/quarantine")
def get_run_quarantine(run_id: str) -> dict[str, Any]:
    run_dir = _resolve_run_dir(run_id)
    data = load_run_data(run_dir)
    return {
        "status_line": STATUS_LINE,
        "quarantine_text": data.quarantine_text,
    }


@app.get("/runs/{run_id}/ledger")
def get_run_ledger(run_id: str) -> dict[str, Any]:
    run_dir = _resolve_run_dir(run_id)
    data = load_run_data(run_dir)
    return {
        "status_line": STATUS_LINE,
        **_serialize_ledger(data),
    }


@app.get("/runs/{run_id}/scores")
def get_run_scores(run_id: str) -> dict[str, Any]:
    run_dir = _resolve_run_dir(run_id)
    data = load_run_data(run_dir)
    return {
        "status_line": STATUS_LINE,
        "scores": data.scores.scores,
        "scorecard_text": data.scores.scorecard_text,
    }


@app.get("/ops/ladders")
def get_ops_ladders() -> dict[str, Any]:
    reports = load_ladder_reports()
    return {
        "status_line": STATUS_LINE,
        "ladders": [
            {
                "matrix": r.matrix,
                "gold": r.gold,
                "rows": [row.as_dict() for row in r.rows],
            }
            for r in reports
        ],
    }


@app.get("/ops/matrices")
def get_ops_matrices() -> dict[str, Any]:
    totals = load_matrix_totals()
    return {
        "status_line": STATUS_LINE,
        "matrices": [asdict(row) for row in totals],
    }


@app.post("/runs/demo")
def post_run_demo() -> dict[str, Any]:
    out = outputs_dir()
    code = cli.main(["demo", "--outputs", str(out)])
    runs = list_runs(out)
    if code != 0 or not runs:
        raise HTTPException(status_code=500, detail=f"bidwright demo exited with status {code}")
    latest = load_run_data(runs[0])
    return {
        "status_line": STATUS_LINE,
        "run_id": latest.run_dir.name,
        "status": latest.manifest.status,
        "reason": latest.manifest.status_reason,
    }


@app.post("/runs/{run_id}/stop")
def post_stop_run(run_id: str) -> dict[str, str]:
    run_dir = _resolve_run_dir(run_id)
    code = cli.main(["stop", str(run_dir)])
    if code != 0:
        raise HTTPException(
            status_code=409,
            detail=f"Run {run_id!r} cannot be stopped (not RUNNING)",
        )
    return {
        "status_line": STATUS_LINE,
        "run_id": run_id,
        "status": "STOP_REQUESTED",
    }


@app.post("/runs/{run_id}/spans/replay")
def post_replay_spans(
    run_id: str,
    body: ReplayRequest | None = None,
) -> dict[str, Any]:
    run_dir = _resolve_run_dir(run_id)
    endpoint = body.endpoint if body is not None else None
    try:
        count, url = replay_spans(run_dir, endpoint=endpoint)
    except Refused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status_line": STATUS_LINE,
        "run_id": run_id,
        "replayed": count,
        "url": url,
        "note": (
            "Replaying a run twice sends its spans twice, so the trace appears twice in Phoenix."
        ),
    }
