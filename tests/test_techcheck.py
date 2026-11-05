"""`techcheck` (Iteration 3, step 8; ADR-044): verdicts against the fake Context7 of
`tests/mcp_fakes.py`, the quote check, the cap, the research modes and the gateway's rules."""

import contextlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from bidwright.config import ServerPins, compile_patterns, load_config
from bidwright.graph.nodes import CallManifests
from bidwright.graph.techcheck import (
    CAPPED,
    NO_LIBRARY,
    NOT_IN_PACK,
    OFF,
    Sources,
    TechcheckOutcome,
    ordered,
    settle,
    techcheck,
    write_techcheck,
)
from bidwright.harness.context import ContextManager
from bidwright.harness.rules import RuleContext
from bidwright.obs.events import EventRecorder
from bidwright.research.context7 import SENT, Context7Docs, paragraphs, query_for
from bidwright.research.mcp_client import McpClient, McpError
from bidwright.research.pack import LibraryPack
from bidwright.research.pins import pinned
from bidwright.schemas import (
    LibraryExcerpt,
    LibraryManifest,
    LibrarySource,
    SolutionManifest,
    TechClaim,
    TechVerdict,
    WorkPackage,
)
from tests.mcp_fakes import INJECTED, PDFPLUMBER_NO_PDFA, PDFPLUMBER_TEXT, http_server, serving
from tests.node_fakes import ScriptBackend, context, dev_ingest, text

CONFIG = load_config()
PATTERNS = compile_patterns(CONFIG.ingest.suspect_patterns, "config/ingest.yaml")
ALLOWED = CONFIG.agents.agents["techcheck"].tools
CAP = CONFIG.limits.solution.tech_claim_cap
MAX_CHARS = 4500 * CONFIG.limits.context.chars_per_token
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
EXTRACT = "Page text is extracted with pdfplumber's extract_text()."
PDFA = "Documents of closed cases are converted to PDF/A with pdfplumber's to_pdfa() export."


@pytest.fixture(scope="module")
def c7_url() -> Iterator[str]:
    with serving("--context7") as url:
        yield url


def pins_of(url: str) -> ServerPins:
    reported, tools = McpClient("context7", http_server(url)).list_tools()
    return pinned("context7", reported, tools, SENT, None)


def docs_for(url: str, pins: ServerPins | None = None, events: EventRecorder | None = None) -> Any:
    client = McpClient("context7", http_server(url))
    return Context7Docs(client, pins or pins_of(url), PATTERNS, events)


def claim(
    n: int, claim_text: str, library: str | None = "pdfplumber", code: str | None = "1.1"
) -> TechClaim:
    return TechClaim(
        id=f"TC-{n:02d}",
        text=claim_text,
        library=library,
        version=None,
        wbs_code=code,
        kind="LIBRARY" if library else "NOT_CHECKABLE",
    )


def manifest(*claims: TechClaim, revision: int = 0) -> SolutionManifest:
    packages = [WorkPackage(code=c, name=f"Package {c}") for c in ("1.1", "1.2")]
    return SolutionManifest(work_packages=packages, tech_claims=list(claims), revision=revision)


def verdict(label: str, quote: str) -> str:
    return text({"reason": "The documentation says so.", "verdict": label, "quote": quote})


def live(url: str, docs: Any = None, events: EventRecorder | None = None) -> Sources:
    docs = docs or docs_for(url, events=events)
    with contextlib.suppress(McpError):  # an unreachable server: techcheck reports it
        docs.connect()
    context = RuleContext(passages=dev_ingest().passages, events=events, node="techcheck")
    return Sources("live", docs=docs, gateway=docs.gateway(context, ALLOWED, 2 * CAP))


def run(
    sources: Sources,
    the_manifest: SolutionManifest,
    replies: list[str],
    tmp_path: Path | None = None,
) -> tuple[TechcheckOutcome, ScriptBackend]:
    backend = ScriptBackend(list(replies))
    calls = None
    if tmp_path is not None:
        calls = CallManifests(
            ContextManager(tmp_path, CONFIG.limits.context, dev_ingest().passages),
            CONFIG.limits.context.budgets["techcheck"],
        )
    outcome = techcheck(
        context(backend),
        the_manifest,
        sources,
        cap=CAP,
        max_chars=MAX_CHARS,
        manifests=calls,
        now=lambda: NOW,
    )
    return outcome, backend


def counts(url: str) -> dict[str, Any]:
    return McpClient("context7", http_server(url)).call("fake_counts", {})


def test_a_supported_claim_is_validated_and_a_false_one_invalidated(
    c7_url: str, tmp_path: Path
) -> None:
    replies = [verdict("VALIDATED", PDFPLUMBER_TEXT), verdict("INVALIDATED", PDFPLUMBER_NO_PDFA)]
    outcome, backend = run(
        live(c7_url), manifest(claim(1, EXTRACT), claim(2, PDFA)), replies, tmp_path
    )
    found = [(v.claim_id, v.verdict, v.source) for v in outcome.validations]
    assert found == [
        ("TC-01", "VALIDATED", "/jsvine/pdfplumber"),
        ("TC-02", "INVALIDATED", "/jsvine/pdfplumber"),
    ]
    assert outcome.validations[1].quote == PDFPLUMBER_NO_PDFA
    assert outcome.revision_due()
    task = outcome.revision_task(manifest(claim(1, EXTRACT), claim(2, PDFA)))
    assert [(t.text, t.quote) for t in task] == [(PDFA, PDFPLUMBER_NO_PDFA)]
    assert PDFPLUMBER_TEXT in backend.requests[0].messages[-1].content
    names = sorted(p.name for p in (tmp_path / "context").glob("techcheck-*.json"))
    assert names == ["techcheck-TC-01.json", "techcheck-TC-02.json"]
    write_techcheck(tmp_path, outcome)
    rows = (tmp_path / "tech_validations.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(r)["verdict"] for r in rows] == ["VALIDATED", "INVALIDATED"]
    docs = (tmp_path / "tech_docs.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(docs[0])["library_id"] == "/jsvine/pdfplumber"


def test_a_verdict_whose_quote_is_not_in_the_documentation_is_insufficient_docs() -> None:
    label, quote, reason = settle(
        TechVerdict(reason="It exists.", verdict="VALIDATED", quote="pdfplumber.to_pdfa(path)"),
        "pdfplumber reads PDF files.",
    )
    assert (label, quote) == ("INSUFFICIENT_DOCS", "")
    assert reason.startswith("the verdict's quote is not in the documentation")
    spaced = settle(
        TechVerdict(reason="", verdict="VALIDATED", quote="reads   “PDF” files"),
        'pdfplumber reads "PDF" files.',
    )
    assert spaced[0] == "VALIDATED", "the quote check normalizes spaces and quote marks"
    assert settle(None, "text")[0] == "INSUFFICIENT_DOCS"


def test_three_claims_on_one_library_make_one_resolve_call(c7_url: str) -> None:
    before = counts(c7_url)
    claims = [
        claim(n, f"pdfplumber {word} on each page.")
        for n, word in enumerate(("extracts text", "extracts words", "extracts tables"), start=1)
    ]
    replies = [verdict("INSUFFICIENT_DOCS", "")] * 3
    outcome, _ = run(live(c7_url), manifest(*claims), replies)
    after = counts(c7_url)
    assert after["resolve-library-id"] - before["resolve-library-id"] == 1
    assert after["query-docs"] - before["query-docs"] == 3
    assert [v.verdict for v in outcome.validations] == ["INSUFFICIENT_DOCS"] * 3


def test_the_cap_skips_the_sixteenth_and_a_claim_with_no_library_is_not_checkable() -> None:
    claims = [claim(n, f"Claim {n}.", code="1.2") for n in range(1, CAP + 2)]
    claims.append(claim(CAP + 2, "Forms are configured by staff.", library=None))
    outcome, backend = run(Sources("off"), manifest(*claims), [])
    verdicts = {v.claim_id: (v.verdict, v.reason) for v in outcome.validations}
    assert verdicts[f"TC-{CAP:02d}"] == ("UNVALIDATED", OFF)
    assert verdicts[f"TC-{CAP + 1:02d}"] == ("SKIPPED_CAP", CAPPED)
    assert verdicts[f"TC-{CAP + 2:02d}"] == ("NOT_CHECKABLE", NO_LIBRARY)
    assert backend.requests == [] and outcome.docs == [], "research off calls nothing"


def test_claims_are_taken_in_work_package_order() -> None:
    claims = [claim(1, "A.", code="1.2"), claim(2, "B.", code=None), claim(3, "C.", code="1.1")]
    assert [c.id for c in ordered(manifest(*claims))] == ["TC-03", "TC-01", "TC-02"]


def test_techcheck_unknown_when_context7_is_out_of_reach() -> None:
    gone = docs_for_unreachable()
    outcome, backend = run(live("", docs=gone), manifest(claim(1, EXTRACT)), [])
    [row] = outcome.validations
    assert row.verdict == "UNVALIDATED" and row.reason.startswith("Context7 is out of reach")
    assert backend.requests == []


def docs_for_unreachable() -> Context7Docs:
    from tests.mcp_fakes import free_port

    url = f"http://127.0.0.1:{free_port()}/mcp"
    return Context7Docs(McpClient("context7", http_server(url)), ServerPins(), PATTERNS)


def test_a_changed_tool_description_refuses_the_server(c7_url: str, tmp_path: Path) -> None:
    pins = pins_of(c7_url)
    events = EventRecorder(tmp_path / "events.jsonl")
    with serving("--context7", "--changed-description") as changed:
        docs = docs_for(changed, pins)
        outcome, backend = run(live(changed, docs, events), manifest(claim(1, EXTRACT)), [])
    [row] = outcome.validations
    assert row.verdict == "UNVALIDATED" and "server refused" in row.reason
    assert docs.pinned is False and "changed since it was pinned" in (docs.refusal or "")
    assert backend.requests == []


def test_g3_denies_a_library_name_that_copies_a_passage(c7_url: str) -> None:
    """Code builds the query from content words, so the text a model controls that could carry
    a passage out is the claim's library name."""
    passage = max(dev_ingest().passages, key=lambda p: len(p.text.split()))
    copied = " ".join(passage.text.split()[:9])[:100]
    outcome, backend = run(live(c7_url), manifest(claim(1, EXTRACT, library=copied)), [])
    [row] = outcome.validations
    assert row.verdict == "UNVALIDATED" and "research queries never carry RFP text" in row.reason
    assert passage.id in row.reason and backend.requests == []


def test_a_paragraph_that_reads_like_an_instruction_never_reaches_the_verdict(
    tmp_path: Path,
) -> None:
    events = EventRecorder(tmp_path / "events.jsonl")
    events.create()
    with serving("--context7", "--injected") as injected:
        sources = live(injected, events=events)
        outcome, backend = run(
            sources, manifest(claim(1, EXTRACT)), [verdict("VALIDATED", PDFPLUMBER_TEXT)]
        )
    sent = backend.requests[0].messages[-1].content
    assert INJECTED not in sent and PDFPLUMBER_TEXT in sent
    assert INJECTED not in outcome.docs[0].text
    logged = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert "quarantined" in logged and "injection-dominant" in logged


def library_pack() -> LibraryPack:
    source = LibrarySource(
        id="LS-001",
        library="pdfplumber",
        library_id="/jsvine/pdfplumber",
        query="pdfplumber PDF/A export",
        retrieved=NOW,
    )
    excerpts = [
        LibraryExcerpt(id=f"LX-{n:04d}", source_id="LS-001", library="pdfplumber", text=t)
        for n, t in enumerate(paragraphs(f"{PDFPLUMBER_TEXT}\n\n{PDFPLUMBER_NO_PDFA}"), start=1)
    ]
    manifest_ = LibraryManifest(
        version=2,
        created=NOW.date(),
        libraries=["pdfplumber"],
        files={"sources.jsonl": "sha256:" + "0" * 64, "excerpts.jsonl": "sha256:" + "0" * 64},
    )
    return LibraryPack(Path("."), manifest_, "sha256:" + "0" * 64, [source], excerpts)


def test_research_mode_pack_judges_from_the_library_pack_with_no_network_call() -> None:
    pack = library_pack()
    sources = Sources("pack", library_pack=pack, questions=CONFIG.research.questions)
    converts = "pdfplumber converts PDF files to PDF/A on export."
    claims = [
        claim(1, converts),
        claim(2, "Charts are drawn with matplotlib.", library="matplotlib"),
    ]
    outcome, backend = run(sources, manifest(*claims), [verdict("INVALIDATED", PDFPLUMBER_NO_PDFA)])
    first, second = outcome.validations
    assert (first.verdict, first.source) == ("INVALIDATED", "libraries@2")
    assert PDFPLUMBER_NO_PDFA in backend.requests[0].messages[-1].content
    assert (second.verdict, second.reason) == ("INSUFFICIENT_DOCS", NOT_IN_PACK)
    assert len(backend.requests) == 1 and outcome.docs[0].library_id == "libraries@2"
    assert query_for("pdfplumber", None, PDFA).startswith("pdfplumber Documents closed")
    unrelated = pack.answer(
        "pdfplumber", query_for("pdfplumber", None, PDFA), CONFIG.research.questions
    )
    assert unrelated == [], "ADR-034's rule needs half the query's stems"


def test_a_revised_manifest_is_not_due_a_second_revision() -> None:
    outcome = TechcheckOutcome(revision=1)
    outcome.validations = []
    assert not outcome.revision_due()
