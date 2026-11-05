"""The research pack builder (Iteration 2, step 13; ADR-033): `bidwright research pack`.

    bidwright research pack --domain <id> --title <text> --keyword <words> ...
        --select-for <run> (--run <run> | --notebook <id> --job <task id> --topic <words> ...)
        [--leave-out <source id> ...] [--profile free|paid]

`build_pack` writes `research_packs/<domain>/` from recorded research, in one of two ways.

- `--run`: a finished run in research mode `live` whose research job completed. The pack's
  sources, excerpts and answers come from the run's `research.json`, which never enters the
  pack; its domain brief from the run's `domain_brief.json`, with `domain_id` set; and its
  topics from the run's `brief.json`. No model call is made.
- `--notebook` and `--job`: a NotebookLM job no run started, such as one launched by hand.
  The builder reads it in a run of its own, under a `RunSupervisor`, with a manifest of no
  documents, data class `synthetic` and `run_args` naming the command; egress checks the
  research server and the model backends as for a synthetic run. With no RFP, the gateway's
  rule G3 has no passage a question could copy. The run records the job as
  finished, with no second job to spend, and its research provider calls, in order: `status`
  for the report and the listing, taking any new task id; `sources`, which must list at least
  one, since the build imports nothing; `bind`; the follow-up questions; then the extraction
  call, as `discover_ask` and `discover_extract` make them. The pack is then built from that
  run as from `--run`, with the `--topic` words as its topics. Such a run is not resumable:
  a stopped one is started again. Its run id is `<UTC time>-pack-<domain>-<profile>`.

A pack leaves out a quarantined excerpt or answer, an answer left with no excerpt, and a source
no kept excerpt cites. It also leaves out each source `--leave-out` names, such as a published
tender, which the data rule keeps out of the repository, and, when `HYGIENE_HASHES` is set
(`bidwright.restricted`), a source the restricted-name check flags, each with its excerpts and
every answer that cites them, whose text may draw on that source, and any excerpt, answer,
item, need or open question the check flags. The domain brief is then settled again, with the
tier rule, so nothing cites what was left out and no item rests on tier-4 sources alone; a
file that still flags refuses the pack. `summary.md` lists the sources left out by id and
reason. A source whose title or URL reads like a published solicitation is named in the
result's `review`, so the operator can check it and build again with `--leave-out`.

Refusals, before anything is written: a domain id that is not lower-case words joined by
hyphens, fewer than 2 keywords, more than 5 topics, a `--select-for` run with no brief topics,
and a pack those topics would not select over the other packs present, by `select_pack`'s rule.
Rebuilding a domain's pack replaces it, so its earlier version does not compete, and raises its
`version` by one. The pack is staged and loaded with `load_pack` before it replaces anything,
so a pack `load_pack` would refuse is never written; a pack with no domain item or need is
refused too. `pack.yaml` takes the flags, each file's hash and the counts.
"""

import json
import os
import re
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from langgraph.runtime import RunControl
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import BaseModel, ValidationError

from bidwright.config import Config, SelectionConfig, compile_patterns, load_config
from bidwright.fileio import write_atomic
from bidwright.graph.build import current_commit
from bidwright.graph.discover import (
    BRIEF_FILE,
    FAILURES,
    NODE,
    RESEARCH_FILE,
    Discovery,
    settle_brief,
)
from bidwright.graph.nodes import RunContext
from bidwright.harness.budget import BudgetExceeded, RunBudget
from bidwright.harness.context import ContextManager
from bidwright.harness.egress import RESEARCH_DESTINATION, EgressRefused, check_run
from bidwright.harness.gateway import ToolLog
from bidwright.harness.recovery import CircuitBreaker
from bidwright.harness.rules import query_sha256
from bidwright.harness.supervisor import STOP_REASON, RunSupervisor, environment
from bidwright.llm.client import LLMClient
from bidwright.llm.limits import Limiter, tier_for
from bidwright.llm.types import Backend, CircuitOpen, LLMError, QuotaExhausted
from bidwright.obs.ledger import LedgerFile, models_used, totals_of
from bidwright.obs.tracing import Tracing, trace_endpoint
from bidwright.preflight import HOME
from bidwright.prompts import load_prompt_ref
from bidwright.research.nlm import notebooklm_provider
from bidwright.research.pack import (
    DATA_FILES,
    PACK_FILE,
    PackRefused,
    choose,
    digest,
    keyword_matches,
    load_pack,
    pack_keywords,
    packs_root,
    read_manifest,
)
from bidwright.research.provider import ResearchProvider
from bidwright.research.trust import solicitation
from bidwright.restricted import RestrictedNames
from bidwright.schemas import (
    DiscoveryExtract,
    DomainBrief,
    OpportunityBrief,
    PackAnswer,
    PackExcerpt,
    PackManifest,
    PackSource,
    ResearchJob,
    ResearchRecord,
    RunManifest,
    RunStatus,
)

PACK_COMMAND = "research pack"
MIN_KEYWORDS = 2
MAX_TOPICS = 5
DOMAIN_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LABEL = "J1"  # the job a build reads, as its run records it
EXISTING_JOB = "an existing research job, read by bidwright research pack"
FINISHED = ("COMPLETED", "DEGRADED")
LIMITS_TIER = "dev"  # a build's run makes a few model calls, well inside the dev limits


class BuildRefused(Exception):
    """The research pack cannot be built as asked; no pack file was written."""


@dataclass(frozen=True)
class PackRequest:
    domain_id: str
    title: str
    keywords: Sequence[str]
    select_for: Path  # a run folder whose brief topics must select the pack
    run: Path | None = None  # a finished run in research mode `live`
    notebook_id: str | None = None  # with `job`, an existing NotebookLM job
    job: str | None = None
    topics: Sequence[str] = ()  # with `notebook_id`, the pack's topics
    leave_out: Sequence[str] = ()  # source ids the operator leaves out, such as a tender
    profile: str = "free"


@dataclass(frozen=True)
class BuiltPack:
    path: Path
    manifest: PackManifest
    run_dir: Path  # the run the pack was built from
    left_out: list[str] = field(default_factory=list)
    review: list[str] = field(default_factory=list)  # sources that read like a tender


def build_pack(
    request: PackRequest,
    *,
    config: Config | None = None,
    outputs: Path | None = None,
    backends: Mapping[str, Backend] | None = None,
    provider: ResearchProvider | None = None,
    restricted: RestrictedNames | None = None,
    today: Callable[[], date] = date.today,
) -> BuiltPack:
    """Build and write the pack `request` names. `outputs` holds a `--notebook` build's run,
    `HOME/outputs` by default; `provider`, for tests, is used instead of the configured
    NotebookLM server; `restricted` is the restricted-name list, or None when the check cannot
    run."""
    config = config or load_config()
    keywords = _checked_keywords(request)
    root = packs_root(config.research.packs_dir)
    version = _checked_selection(request, keywords, root, config.research.selection)
    if request.run is not None:
        run_dir = request.run
        topics = _brief_topics(run_dir, "--run")
        if len(topics) > MAX_TOPICS:
            raise BuildRefused(
                f"a pack takes at most {MAX_TOPICS} topics; the run has {len(topics)}"
            )
    else:
        topics = _checked_topics(request.topics)
        run_dir = _notebook_run(
            request, keywords, topics, config, outputs or HOME / "outputs", backends, provider
        )
    texts, left_out, review = _pack_texts(run_dir, request, restricted)
    manifest = PackManifest(
        domain_id=request.domain_id,
        title=" ".join(request.title.split()),
        version=version,
        created=today(),
        keywords=keywords,
        topics=list(topics),
        files={name: digest(text.encode("utf-8")) for name, text in texts.items()},
        counts=_counts(texts),
    )
    manifest_text = _manifest_text(manifest)
    if restricted is not None and restricted.flags(manifest_text):
        raise BuildRefused(f"{PACK_FILE} would hold a restricted name: check the flags")
    path = _write(root / request.domain_id, texts, manifest_text, config)
    return BuiltPack(path, manifest, run_dir, left_out, review)


# --- checks before anything runs -------------------------------------------------------------


def _checked_keywords(request: PackRequest) -> list[str]:
    if not DOMAIN_ID.match(request.domain_id):
        raise BuildRefused(
            f"the domain id {request.domain_id!r} must be lower-case words joined by hyphens"
        )
    if not request.title.strip():
        raise BuildRefused("a pack needs a title")
    keywords = list(dict.fromkeys(" ".join(k.split()) for k in request.keywords if k.strip()))
    if len(keywords) < MIN_KEYWORDS:
        raise BuildRefused(
            f"a pack needs at least {MIN_KEYWORDS} keywords, since a brief's topics select it"
            f" only on {MIN_KEYWORDS} matching keywords"
        )
    if (request.run is None) == (request.notebook_id is None):
        raise BuildRefused("name a finished live run with --run, or a job with --notebook")
    if request.notebook_id is not None and not request.job:
        raise BuildRefused("--notebook needs --job, the research job's task id")
    if request.run is not None and (request.job or request.topics):
        raise BuildRefused("--job and --topic go with --notebook; a run's topics are its brief's")
    return keywords


def _checked_topics(topics: Sequence[str]) -> list[str]:
    cleaned = list(dict.fromkeys(" ".join(t.split()) for t in topics if t.strip()))
    if not cleaned:
        raise BuildRefused("--notebook needs at least one --topic, the subjects it researched")
    if len(cleaned) > MAX_TOPICS:
        raise BuildRefused(f"a pack takes at most {MAX_TOPICS} topics, not {len(cleaned)}")
    return cleaned


def _brief_topics(run_dir: Path, flag: str) -> list[str]:
    path = run_dir / "brief.json"
    if not path.is_file():
        raise BuildRefused(f"{flag} {run_dir.name} holds no brief.json; run it to its brief first")
    try:
        return list(OpportunityBrief.model_validate_json(path.read_text("utf-8")).topics)
    except (OSError, ValidationError) as exc:
        raise BuildRefused(f"{flag} {run_dir.name}: brief.json cannot be read: {exc}") from exc


def _checked_selection(
    request: PackRequest, keywords: Sequence[str], root: Path, selection: SelectionConfig
) -> int:
    """Refuse a pack the `--select-for` run's brief topics would not select over the packs
    present; the version the pack takes."""
    topics = _brief_topics(request.select_for, "--select-for")
    if not topics:
        raise BuildRefused(
            f"the brief of {request.select_for.name} gave no topics, so it selects no pack"
        )
    target = root / request.domain_id
    previous = _stored_manifest(target)
    if previous is not None and previous.domain_id != request.domain_id:
        raise BuildRefused(f"{target.name} holds the pack {previous.domain_id}")
    try:
        packs = pack_keywords(root)
    except PackRefused as exc:
        raise BuildRefused(str(exc)) from exc
    held = packs.pop(request.domain_id, None)
    if held is not None and held[0].name != target.name:
        raise BuildRefused(f"{held[0].name} already holds the pack {request.domain_id}")
    matches = {domain: keyword_matches(words, topics) for domain, (_, words) in packs.items()}
    matches[request.domain_id] = keyword_matches(keywords, topics)
    chosen, note = choose(matches, selection.min_keyword_matches)
    if chosen != request.domain_id:
        counted = ", ".join(f"{domain} {count}" for domain, count in sorted(matches.items()))
        why = note or f"{chosen} matches more keywords"
        raise BuildRefused(
            f"the brief topics of {request.select_for.name} ({'; '.join(topics)}) would not"
            f" select {request.domain_id}: {why} (keywords matched: {counted})"
        )
    return previous.version + 1 if previous is not None else 1


def _stored_manifest(folder: Path) -> PackManifest | None:
    path = folder / PACK_FILE
    if not path.is_file():
        return None
    try:
        return read_manifest(path)
    except PackRefused as exc:
        raise BuildRefused(str(exc)) from exc


# --- the run that reads an existing job --------------------------------------------------------


def _notebook_run(
    request: PackRequest,
    keywords: Sequence[str],
    topics: Sequence[str],
    config: Config,
    outputs: Path,
    backends: Mapping[str, Backend] | None,
    provider: ResearchProvider | None,
) -> Path:
    """Read the job in a run of its own, as the module docstring says; the run's folder."""
    notebook, job = str(request.notebook_id), str(request.job)
    profile = request.profile
    if profile not in config.models.profiles:
        raise BuildRefused(f"config/models.yaml has no profile {profile!r}")
    used = {role.provider for role in config.models.profiles[profile].values()}
    run_backends = {name: b for name, b in (backends or {}).items() if name in used}
    endpoint = trace_endpoint()
    server = config.research.servers[RESEARCH_DESTINATION]
    try:
        refused = check_run(
            run_backends,
            endpoint,
            None,
            "synthetic",
            register=config.egress,
            research=(RESEARCH_DESTINATION, server),
        )
    except EgressRefused as exc:
        raise BuildRefused(str(exc)) from exc
    agent = config.agents.agents[NODE]
    prompt = load_prompt_ref(agent.prompt)
    started = datetime.now(UTC)
    run_id = f"{started:%Y%m%dT%H%M%SZ}-pack-{request.domain_id}-{profile}"
    run_dir = outputs / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = RunManifest(
        run_id=run_id,
        commit=current_commit(),
        profile=profile,
        models={role: rc.model for role, rc in config.models.profiles[profile].items()},
        prompt_hashes={NODE: prompt.hash},
        started=started,
        status="RUNNING",
        data_class="synthetic",
        refused_destinations=refused,
        run_args={
            "command": PACK_COMMAND,
            "domain": request.domain_id,
            "title": request.title,
            "keywords": list(keywords),
            "select_for": _relative(request.select_for),
            "notebook": notebook,
            "job": job,
            "topics": list(topics),
            "profile": profile,
            "mode": "live",
            "environment": environment(),
        },
    )
    budget = RunBudget(config.limits.run(LIMITS_TIER, profile))
    control = RunControl()
    with RunSupervisor(run_dir, manifest, control=control, budget=budget, resume=False) as run:
        ledger_file = LedgerFile(run_dir / "ledger.jsonl")
        ledger_file.create()
        events = run.events
        breaker = CircuitBreaker(
            config.limits.breaker, on_change=lambda detail: events.record("recovery", None, detail)
        )
        tool_log = ToolLog(run_dir / "tool_calls.jsonl", part=run.part)
        tool_log.create()
        client = LLMClient(
            config,
            profile,
            dict(run_backends),
            mode="live",
            run_id=run_id,
            limiter=Limiter(config.limits, tier_for(profile)),
            breaker=breaker,
        )
        research = provider or notebooklm_provider(config, breaker)
        tracing = Tracing(
            run_id,
            run_dir,
            None if refused else endpoint,
            os.environ.get("PHOENIX_API_KEY") or None,
        )
        ctx = RunContext(
            run_id, client, budget, {NODE: prompt}, {}, tracing=tracing, ledger_file=ledger_file
        )
        one_job = config.research.jobs.model_copy(update={"max_per_run": 1})
        discovery = Discovery(
            ctx=ctx,
            provider=research,
            config=config.research.model_copy(update={"jobs": one_job}),
            agent=agent,
            run_dir=run_dir,
            manager=ContextManager(run_dir, config.limits.context, []),
            passages=[],
            patterns=compile_patterns(config.ingest.suspect_patterns, "config/ingest.yaml"),
            mode="live",
            events=events,
            tool_log=tool_log,
            control=control,
            budget_tokens=config.limits.context.budgets[NODE],
            rfp=False,
        )
        recorded = ResearchJob(
            label=LABEL,
            notebook_id=notebook,
            task_id=job,
            query=EXISTING_JOB,
            query_sha256=query_sha256(EXISTING_JOB),
            state="completed",
            started=started,
        )
        discovery.store.save(ResearchRecord(mode="live", notebooks=[notebook], jobs=[recorded]))
        status: RunStatus = "UNRECOVERABLE_FAULT"
        reason: str | None = "the build ended before it finished"
        budget.start()
        try:
            kind = OpenInferenceSpanKindValues.CHAIN
            with tracing.span(PACK_COMMAND, kind, **{"bidwright.run_id": run_id}):
                failure = _read_job(discovery, research, notebook, topics, control)
            if failure is None:
                status, reason = "COMPLETED", None
            elif failure == STOP_REASON:
                status, reason = "STOPPED", STOP_REASON
            else:
                status, reason = "UNRECOVERABLE_FAULT", failure
        except BudgetExceeded as exc:
            status, reason = "BUDGET_EXCEEDED", str(exc)
        except QuotaExhausted as exc:
            status, reason = "QUOTA_PAUSED", f"{exc}; build again after the quota resets"
        except CircuitOpen as exc:
            status, reason = "QUOTA_PAUSED", str(exc)
        except LLMError as exc:
            status, reason = "UNRECOVERABLE_FAULT", f"{type(exc).__name__}: {exc}"
        except KeyboardInterrupt:
            status, reason = "STOPPED", "interrupted by the operator"
            raise
        except Exception as exc:
            status, reason = "UNRECOVERABLE_FAULT", f"unexpected {type(exc).__name__}: {exc}"
            raise
        finally:
            budget.pause()
            try:
                tracing.close()
            finally:
                try:
                    entries = ledger_file.load()
                except (OSError, ValueError):
                    entries = list(ctx.ledger)
                run.finish(
                    status, reason, totals_of(entries, budget.active_seconds), models_used(entries)
                )
    if status != "COMPLETED":
        raise BuildRefused(
            f"the build's run {run_id} ended {status}: {reason}; such a run is not resumed,"
            " so build again"
        )
    return run_dir


def _read_job(
    discovery: Discovery,
    provider: ResearchProvider,
    notebook: str,
    topics: Sequence[str],
    control: RunControl,
) -> str | None:
    """The provider calls in the module docstring's order; the failure, or None."""
    outcome = discovery.read_report(LABEL)
    if outcome.failed:
        return outcome.failed
    try:
        held = provider.sources(notebook)
    except FAILURES as exc:
        return f"research: {exc}"
    if not held:
        return "research: the notebook holds no sources; import the job's sources first"
    for step in (discovery.ask, discovery.extract):
        if control.drain_requested:
            return STOP_REASON
        outcome = step(topics)
        if outcome.failed:
            return outcome.failed
    return None


def _relative(path: Path) -> str:
    resolved = path.resolve()
    return resolved.relative_to(HOME).as_posix() if resolved.is_relative_to(HOME) else str(resolved)


# --- the pack's files --------------------------------------------------------------------------


def _pack_texts(
    run_dir: Path, request: PackRequest, restricted: RestrictedNames | None
) -> tuple[dict[str, str], list[str], list[str]]:
    """The five data files of the pack, from a finished live run; what was left out; and the
    kept sources that read like a published solicitation."""
    record, brief = _live_research(run_dir)

    def flags(text: str) -> bool:
        return restricted is not None and restricted.flags(text)

    unknown = sorted(set(request.leave_out) - {s.id for s in record.sources})
    if unknown:
        raise BuildRefused(f"--leave-out names sources the run does not hold: {unknown}")
    left_out: list[str] = []
    removed: dict[str, str] = {}  # source id to why, for summary.md
    allowed: dict[str, PackSource] = {}
    for source in record.sources:
        if source.id in request.leave_out:
            removed[source.id] = "left out by the operator"
        elif flags(f"{source.title} {source.url} {source.host}"):
            removed[source.id] = "the restricted-name check"
        else:
            allowed[source.id] = source
    left_out += [
        f"source {sid}, with its excerpts and the answers citing them: {why}"
        for sid, why in removed.items()
    ]
    tainted = {e.id for e in record.excerpts if e.source_id in removed}
    excerpts: list[PackExcerpt] = []
    for excerpt in record.excerpts:
        if excerpt.quarantined:
            left_out.append(f"excerpt {excerpt.id}: quarantined, it reads like an instruction")
        elif excerpt.source_id not in allowed:
            continue  # its source is left out, and noted
        elif flags(excerpt.text):
            left_out.append(f"excerpt {excerpt.id}: the restricted-name check")
        else:
            excerpts.append(excerpt)
    kept = {e.id for e in excerpts}
    answers: list[PackAnswer] = []
    for answer in record.answers:
        cited = [i for i in answer.excerpt_ids if i in kept]
        if answer.quarantined:
            left_out.append(f"the answer to {answer.question!r}: quarantined")
        elif tainted & set(answer.excerpt_ids):
            continue  # it cites a source left out, and is noted with it
        elif flags(f"{answer.question} {answer.answer}"):
            left_out.append(f"the answer to {answer.question!r}: the restricted-name check")
        elif not cited:
            left_out.append(f"the answer to {answer.question!r}: no excerpt of it is kept")
        else:
            answers.append(answer.model_copy(update={"excerpt_ids": cited, "job": None}))
    if flags(brief.summary):
        raise BuildRefused("the domain brief's summary holds a restricted name; extract again")
    proposal = DiscoveryExtract.model_validate(
        {
            "summary": brief.summary,
            "items": [i.model_dump(exclude={"id"}) for i in brief.items if not flags(i.statement)],
            "needs": [n.model_dump(exclude={"id"}) for n in brief.needs if not flags(n.need)],
            "open_questions": [q for q in brief.open_questions if not flags(q)],
        }
    )
    dropped = (
        len(brief.items)
        - len(proposal.items)
        + len(brief.needs)
        - len(proposal.needs)
        + len(brief.open_questions)
        - len(proposal.open_questions)
    )
    if dropped:
        left_out.append(f"{dropped} domain brief entries: the restricted-name check")
    cited_sources = {e.source_id for e in excerpts}
    sources = [s for s in allowed.values() if s.id in cited_sources]
    settled, notes = settle_brief(
        proposal, excerpts, sources, mode="pack", domain_id=request.domain_id, tier_rule=True
    )
    left_out += [f"domain brief: {note}" for note in notes]
    if not settled.items and not settled.needs:
        raise BuildRefused(
            f"{run_dir.name}'s research gave no domain item or need resting on a kept excerpt,"
            " so the pack would be empty"
        )
    texts = {
        "summary.md": _summary(request.title, settled.summary, sources, removed),
        "sources.jsonl": _lines(sources),
        "excerpts.jsonl": _lines(excerpts),
        "domain_brief.json": settled.model_dump_json(indent=1) + "\n",
        "answers.jsonl": _lines(answers, exclude={"job"}),
    }
    for name, text in texts.items():
        if flags(text):
            raise BuildRefused(f"{name} would still hold a restricted name")
    review = [f"{s.id}: {s.title}, {s.url}" for s in sources if solicitation(s.title, s.url)]
    return texts, left_out, review


def _live_research(run_dir: Path) -> tuple[ResearchRecord, DomainBrief]:
    """A finished run's research record and domain brief, which must come from a live job."""
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.is_file():
        raise BuildRefused(f"{run_dir} holds no run")
    try:
        manifest = RunManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        if manifest.status not in FINISHED:
            raise BuildRefused(f"the run {run_dir.name} is {manifest.status}, not finished")
        record = ResearchRecord.model_validate_json(
            (run_dir / RESEARCH_FILE).read_text(encoding="utf-8")
        )
        brief = DomainBrief.model_validate_json((run_dir / BRIEF_FILE).read_text("utf-8"))
    except (OSError, ValidationError) as exc:
        raise BuildRefused(f"{run_dir.name} holds no live research to build from: {exc}") from exc
    if record.mode != "live" or not any(job.state == "completed" for job in record.jobs):
        raise BuildRefused(f"{run_dir.name} completed no live research job")
    if brief.mode != "live":
        raise BuildRefused(
            f"{run_dir.name}'s domain brief came from a research pack, not from its live research"
        )
    return record, brief


def _lines(rows: Sequence[BaseModel], exclude: set[str] | None = None) -> str:
    return "".join(row.model_dump_json(exclude=exclude) + "\n" for row in rows)


def _summary(
    title: str, summary: str, sources: Sequence[PackSource], removed: Mapping[str, str]
) -> str:
    """The domain brief's summary with the pack's sources, and the ids of the sources left
    out with the reason, never their titles, for people."""
    lines = [f"# {' '.join(title.split())}", "", summary or "No summary was extracted.", ""]
    lines += ["## Sources", ""]
    lines += [f"- {s.id}: {s.title}, tier {s.tier}, {s.url}" for s in sources]
    if removed:
        lines += ["", "## Sources left out", ""]
        lines += [f"- {sid}: {why}" for sid, why in removed.items()]
    return "\n".join(lines) + "\n"


def _counts(texts: Mapping[str, str]) -> dict[str, int]:
    brief = DomainBrief.model_validate_json(texts["domain_brief.json"])

    def rows(name: str) -> int:
        return sum(1 for line in texts[name].splitlines() if line.strip())

    return {
        "sources": rows("sources.jsonl"),
        "excerpts": rows("excerpts.jsonl"),
        "items": len(brief.items),
        "needs": len(brief.needs),
        "answers": rows("answers.jsonl"),
    }


def _manifest_text(manifest: PackManifest) -> str:
    """`pack.yaml`, in the layout of the README's example: JSON strings and lists, which YAML
    reads as they are."""

    def quoted(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    lines = [
        f"domain_id: {manifest.domain_id}",
        f"title: {quoted(manifest.title)}",
        f"version: {manifest.version}",
        f"created: {manifest.created.isoformat()}",
        f"keywords: {quoted(manifest.keywords)}",
        f"topics: {quoted(manifest.topics)}",
        "files:",
        *(f"  {name}: {quoted(manifest.files[name])}" for name in DATA_FILES),
        "counts: {" + ", ".join(f"{k}: {v}" for k, v in manifest.counts.items()) + "}",
    ]
    return "\n".join(lines) + "\n"


def _write(target: Path, texts: Mapping[str, str], manifest_text: str, config: Config) -> Path:
    """Stage the pack and load it, then replace the target's files, `pack.yaml` last."""
    patterns = compile_patterns(config.ingest.suspect_patterns, "config/ingest.yaml")
    with tempfile.TemporaryDirectory() as staging:
        staged = Path(staging) / target.name
        for name, text in {**texts, PACK_FILE: manifest_text}.items():
            write_atomic(staged / name, text)
        try:
            load_pack(staged, patterns)
        except PackRefused as exc:
            raise BuildRefused(f"the staged pack does not load: {exc}") from exc
    for name in DATA_FILES:
        write_atomic(target / name, texts[name])
    write_atomic(target / PACK_FILE, manifest_text)
    try:
        load_pack(target, patterns)
    except PackRefused as exc:
        raise BuildRefused(f"the written pack does not load: {exc}") from exc
    return target


__all__ = [
    "PACK_COMMAND",
    "BuildRefused",
    "BuiltPack",
    "PackRequest",
    "build_pack",
]
