"""One call of one node outside a run (Iteration 3, step 16), and `bidwright-eval techcheck`
on it: each technology seed judged by `techcheck`'s own code in research mode `pack`, with
the Master-Plan's rule over the repeats. Scripted models answer; the library pack is the
committed one."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from bidwright.graph.single import call_node, read_calls
from bidwright.llm.replay import CassetteStore
from bidwright.llm.types import Request, Response
from bidwright.preflight import Refused
from bidwright.schemas import TechVerdict, TechVerdictTask
from evals.techcheck import judge_seeds, report
from tests.node_fakes import _DATA, USAGE, ScriptBackend, fake_backends, text

FALSE_SEED = {
    "gold_id": "TS-01",
    "library": "pdfplumber",
    "text": "pdfplumber exports documents as PDF/A files",
    "holds": False,
}
NO_DOCS_SEED = {
    "gold_id": "TS-02",
    "library": "reportlab",
    "text": "reportlab renders tables on PDF pages",
    "holds": True,
}


def _verdict(label: str) -> Callable[[Request], Response]:
    """A verdict that quotes the start of the documentation it was given, as code requires."""

    def answer(request: Request) -> Response:
        user = next(m.content for m in request.messages if m.role == "user")
        found = _DATA.search(user)
        assert found is not None
        documentation = json.loads(found.group(2))["documentation"]
        quote = documentation.split("\n")[0][:60].strip()
        body = {"reason": "The documentation says so.", "verdict": label, "quote": quote}
        return Response(text=text(body), usage=USAGE)

    return answer


def test_one_call_writes_its_own_ledger_and_no_run_manifest(tmp_path: Path) -> None:
    task = TechVerdictTask(claim_text="pdfplumber reads PDF files", library="pdfplumber")
    reply = {"reason": "Stated.", "verdict": "INSUFFICIENT_DOCS", "quote": ""}
    backend = ScriptBackend([text(reply)])
    store = CassetteStore(tmp_path / "cassettes")
    first = call_node(
        "techcheck",
        task,
        TechVerdict,
        profile="free",
        mode="record",
        name="one",
        backends=fake_backends(backend),
        cassettes=store,
        outputs=tmp_path,
    )
    assert isinstance(first.parsed, TechVerdict) and first.parsed.verdict == "INSUFFICIENT_DOCS"
    assert first.folder == tmp_path / "single" / "one"
    [entry] = read_calls(first.folder)
    assert entry["node"] == "techcheck" and not entry["replayed"]
    assert not (first.folder / "run_manifest.json").exists()
    again = call_node(
        "techcheck",
        task,
        TechVerdict,
        profile="free",
        mode="replay",
        name="one",
        cassettes=store,
        outputs=tmp_path,
    )
    assert again.parsed == first.parsed and len(backend.requests) == 1, "the replay calls nothing"
    assert [e["replayed"] for e in read_calls(first.folder)] == [False, True]


def test_a_live_call_needs_a_backend_and_a_known_node(tmp_path: Path) -> None:
    task = TechVerdictTask(claim_text="x")
    with pytest.raises(Refused, match="backend"):
        call_node("techcheck", task, TechVerdict, profile="free", mode="live", name="n")
    with pytest.raises(Refused, match="no prompt"):
        call_node(
            "nothing",
            task,
            TechVerdict,
            profile="free",
            mode="record",
            name="n",
            backends=fake_backends(ScriptBackend([])),
            cassettes=CassetteStore(tmp_path),
            outputs=tmp_path,
        )


def _judge(tmp_path: Path, label: str) -> tuple[Any, ScriptBackend]:
    backend = ScriptBackend([_verdict(label) for _ in range(5)])
    results = judge_seeds(
        [FALSE_SEED, NO_DOCS_SEED],
        repeats=5,
        profile="free",
        mode="record",
        backends=fake_backends(backend),
        cassettes=CassetteStore(tmp_path / "cassettes"),
        outputs=tmp_path,
    )
    return results, backend


def test_techcheck_on_the_seeds_applies_the_rule(tmp_path: Path) -> None:
    results, backend = _judge(tmp_path / "invalidated", "INVALIDATED")
    false_seed, no_docs = results
    assert false_seed.verdicts == ["INVALIDATED"] * 5 and false_seed.passed(5)
    assert no_docs.verdicts == ["INSUFFICIENT_DOCS"] * 5 and no_docs.passed(5), "never invalidated"
    assert len(backend.requests) == 5, "a claim the pack holds nothing for makes no call"
    out = report(results, 5, tmp_path / "res")
    data = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert data["passed"] is True
    assert "at least 4 of 5" in data["rule"]
    assert "| TS-01 | pdfplumber | False | 5 |" in (out / "report.md").read_text("utf-8")


def test_a_false_seed_validated_fails_the_rule(tmp_path: Path) -> None:
    results, _ = _judge(tmp_path, "VALIDATED")
    assert not results[0].passed(5)
    assert (
        json.loads((report(results, 5, tmp_path / "res") / "report.json").read_text())["passed"]
        is False
    )
