"""`techcheck` (Iteration 3, step 8; ADR-044): each technology claim of the manifest judged
against current documentation, by one `assess`-role call that must quote it.

- A technology claim with no library is `NOT_CHECKABLE`. The checkable ones are taken in work
  package order, then those with no work package, at most `tech_claim_cap` a run; the rest are
  `SKIPPED_CAP`.
- Research mode `off`: each checkable claim is `UNVALIDATED`, "research off", and nothing is
  called.
- Research mode `live`: `Context7Docs` fetches the documentation through the gateway; Context7
  out of reach, its breaker open, a denied call or no library found leaves the claim
  `UNVALIDATED` with the reason.
- Research mode `pack`: no network call; the library pack's matching excerpts, joined by blank
  lines and cut within the documentation budget, take the documentation's place, and none
  gives `INSUFFICIENT_DOCS`, "not in the library pack".
- The verdict (`techcheck.md`, a `TechVerdict`): `VALIDATED`, `INVALIDATED` or
  `INSUFFICIENT_DOCS`, with a quote. A `VALIDATED` or `INVALIDATED` verdict whose quote, after
  `verify.normalize`, is not in the documentation normalized the same way becomes
  `INSUFFICIENT_DOCS`. Documentation left empty by the screen makes no call.

`write_techcheck` is the one writer of `tech_validations.jsonl` and `tech_docs.jsonl`. Context
manifests name the technology claim: `context/techcheck-TC-03.json`. `TechcheckOutcome`
reports whether P03, `blueprint`'s revision, is due: a technology claim `INVALIDATED` on a
manifest at revision 0.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from bidwright.config import QuestionsConfig
from bidwright.graph.nodes import CallManifests, RunContext
from bidwright.harness.gateway import ToolGateway
from bidwright.llm.types import CircuitOpen
from bidwright.research.context7 import Context7Docs, NotFetched, joined, query_for
from bidwright.research.mcp_client import McpError
from bidwright.research.pack import LibraryPack
from bidwright.schemas import (
    InvalidatedView,
    ResearchModeName,
    SolutionManifest,
    TechClaim,
    TechDoc,
    TechValidation,
    TechValidationVerdict,
    TechVerdict,
    TechVerdictTask,
)
from bidwright.verify import normalize

NODE = "techcheck"
OFF = "research off"
NO_LIBRARY = "names no library"
CAPPED = "past the run's technology claim cap"
NOT_IN_PACK = "not in the library pack"
SCREENED_EMPTY = "no documentation is left after the screen"
NO_ANSWER = "the verdict call broke its schema twice"


@dataclass
class TechcheckOutcome:
    validations: list[TechValidation] = field(default_factory=list)
    docs: list[TechDoc] = field(default_factory=list)
    revision: int = 0  # the manifest revision judged

    @property
    def invalidated(self) -> list[TechValidation]:
        return [v for v in self.validations if v.verdict == "INVALIDATED"]

    def revision_due(self) -> bool:
        """P03 is due once: a technology claim `INVALIDATED` on a manifest at revision 0."""
        return bool(self.invalidated) and self.revision == 0

    def revision_task(self, manifest: SolutionManifest) -> list[InvalidatedView]:
        """What P03 receives for each `INVALIDATED` technology claim."""
        claims = {c.id: c for c in manifest.tech_claims}
        return [
            InvalidatedView(
                text=claims[v.claim_id].text, library=v.library, reason=v.reason, quote=v.quote
            )
            for v in self.invalidated
            if v.claim_id in claims
        ]


def ordered(manifest: SolutionManifest) -> list[TechClaim]:
    """The technology claims in work package order, then those with no work package."""
    position = {p.code: n for n, p in enumerate(manifest.work_packages)}
    last = len(position)
    indexed = list(enumerate(manifest.tech_claims))
    indexed.sort(key=lambda pair: (position.get(pair[1].wbs_code or "", last), pair[0]))
    return [claim for _, claim in indexed]


@dataclass
class Sources:
    """Where the documentation comes from, by research mode."""

    mode: ResearchModeName
    docs: Context7Docs | None = None  # live
    gateway: ToolGateway | None = None  # live: the gateway for agent techcheck
    library_pack: LibraryPack | None = None  # pack
    questions: QuestionsConfig | None = None  # pack: ADR-034's matching rule


def techcheck(
    ctx: RunContext,
    manifest: SolutionManifest,
    sources: Sources,
    *,
    cap: int,
    max_chars: int,
    manifests: CallManifests | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> TechcheckOutcome:
    outcome = TechcheckOutcome(revision=manifest.revision)
    reachable = _reachable(sources)
    checked = 0
    for turn, claim in enumerate(ordered(manifest), start=1):
        if claim.library is None:
            outcome.validations.append(_row(claim, "NOT_CHECKABLE", manifest, reason=NO_LIBRARY))
            continue
        checked += 1
        if checked > cap:
            outcome.validations.append(_row(claim, "SKIPPED_CAP", manifest, reason=CAPPED))
            continue
        if sources.mode == "off":
            outcome.validations.append(_row(claim, "UNVALIDATED", manifest, reason=OFF))
            continue
        if reachable is not None:
            outcome.validations.append(_row(claim, "UNVALIDATED", manifest, reason=reachable))
            continue
        found = _documentation(claim, sources, max_chars, now, turn)
        if isinstance(found, NotFetched):
            outcome.validations.append(_row(claim, "UNVALIDATED", manifest, reason=found.reason))
            continue
        if isinstance(found, str):  # the pack holds nothing for it
            outcome.validations.append(
                _row(claim, "INSUFFICIENT_DOCS", manifest, reason=found, source=_ref(sources))
            )
            continue
        doc = found
        outcome.docs.append(doc)
        source = doc.library_id if sources.mode == "live" else _ref(sources)
        if not doc.text.strip():
            outcome.validations.append(
                _row(claim, "INSUFFICIENT_DOCS", manifest, reason=SCREENED_EMPTY, source=source)
            )
            continue
        verdict = judge(ctx, claim, doc.text, manifests)
        label, quote, reason = settle(verdict, doc.text)
        outcome.validations.append(
            _row(claim, label, manifest, reason=reason, quote=quote, source=source)
        )
    return outcome


def _reachable(sources: Sources) -> str | None:
    """None when the documentation can be fetched; else why every claim stays unvalidated."""
    if sources.mode != "live":
        return None
    if sources.docs is None or sources.gateway is None:
        return "Context7 is not configured for this run"
    try:
        sources.docs.connect()
    except (McpError, CircuitOpen) as exc:
        return f"Context7 is out of reach: {exc}"
    if sources.gateway.context is not None:  # G4 reads the pin result of this connection
        sources.gateway.context.pinned = bool(sources.docs.pinned)
    return None


def _ref(sources: Sources) -> str | None:
    return sources.library_pack.ref if sources.library_pack is not None else None


def _documentation(
    claim: TechClaim,
    sources: Sources,
    max_chars: int,
    now: Callable[[], datetime],
    turn: int,
) -> TechDoc | NotFetched | str:
    library = claim.library or ""
    query = query_for(library, claim.version, claim.text)
    if sources.mode == "live":
        if sources.docs is None or sources.gateway is None:
            return NotFetched("Context7 is not configured for this run")
        fetched = sources.docs.fetch(sources.gateway, library, claim.version, claim.text, turn)
        if isinstance(fetched, NotFetched):
            return fetched
        return TechDoc(
            claim_id=claim.id,
            library=library,
            library_id=fetched.library_id,
            query=fetched.query,
            text=fetched.text,
            retrieved=now(),
        )
    pack = sources.library_pack
    if pack is None or sources.questions is None:
        return NotFetched("no library pack is loaded")
    excerpts = pack.answer(library, query, sources.questions)
    if not excerpts:
        return NOT_IN_PACK
    used = {e.source_id for e in excerpts}
    retrieved = max(s.retrieved for s in pack.sources if s.id in used)
    return TechDoc(
        claim_id=claim.id,
        library=library,
        library_id=pack.ref,
        query=query,
        text=joined([e.text for e in excerpts], max_chars),
        retrieved=retrieved,
    )


def judge(
    ctx: RunContext, claim: TechClaim, documentation: str, manifests: CallManifests | None
) -> TechVerdict | None:
    """The one `assess`-role call, with its one format repair."""
    prompt = ctx.prompts[NODE]
    task = TechVerdictTask(
        claim_text=claim.text,
        library=claim.library,
        version=claim.version,
        documentation=documentation,
    )
    data = task.model_dump_json()
    rendered = prompt.render(data, run_id=ctx.run_id)

    def record(call_id: str, history: Sequence[object]) -> None:
        if manifests is not None:
            turns = list(history[len(rendered.messages) :])
            manifests.record(prompt, NODE, call_id, [claim.id], data, turns)  # type: ignore[arg-type]

    record(claim.id, rendered.messages)
    parsed, _ = ctx.structured(
        prompt,
        list(rendered.messages),
        TechVerdict,
        node=NODE,
        input_hash=rendered.input_hash,
        on_repair=lambda sent: record(f"{claim.id}-repair", sent),
    )
    return parsed if isinstance(parsed, TechVerdict) else None


def found_in(quote: str, documentation: str) -> bool:
    wanted = normalize(quote)[0].strip()
    return bool(wanted) and wanted in normalize(documentation)[0]


def settle(
    verdict: TechVerdict | None, documentation: str
) -> tuple[TechValidationVerdict, str, str]:
    """Code's check on the verdict: a verdict that settles the claim must quote the
    documentation."""
    if verdict is None:
        return "INSUFFICIENT_DOCS", "", NO_ANSWER
    reason = " ".join(verdict.reason.split())
    if verdict.verdict == "INSUFFICIENT_DOCS":
        quote = verdict.quote if found_in(verdict.quote, documentation) else ""
        return "INSUFFICIENT_DOCS", quote, reason
    if not found_in(verdict.quote, documentation):
        note = "the verdict's quote is not in the documentation"
        return "INSUFFICIENT_DOCS", "", f"{note}: {reason}" if reason else note
    return verdict.verdict, verdict.quote.strip(), reason


def _row(
    claim: TechClaim,
    verdict: TechValidationVerdict,
    manifest: SolutionManifest,
    *,
    reason: str = "",
    quote: str = "",
    source: str | None = None,
) -> TechValidation:
    return TechValidation(
        claim_id=claim.id,
        library=claim.library,
        version=claim.version,
        verdict=verdict,
        quote=quote,
        source=source,
        reason=reason,
        revision=manifest.revision,
    )


def write_techcheck(run_dir: Path, outcome: TechcheckOutcome) -> None:
    """`tech_validations.jsonl` and `tech_docs.jsonl`, written by this function only."""
    for name, rows in (
        ("tech_validations.jsonl", outcome.validations),
        ("tech_docs.jsonl", outcome.docs),
    ):
        body = "".join(
            json.dumps(row.model_dump(mode="json"), ensure_ascii=False) + "\n" for row in rows
        )
        (run_dir / name).write_text(body, encoding="utf-8", newline="\n")


__all__ = [
    "CAPPED",
    "NODE",
    "NOT_IN_PACK",
    "NO_LIBRARY",
    "OFF",
    "Sources",
    "TechcheckOutcome",
    "judge",
    "ordered",
    "settle",
    "techcheck",
    "write_techcheck",
]
