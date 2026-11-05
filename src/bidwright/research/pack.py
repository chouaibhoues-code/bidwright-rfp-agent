"""Research packs (Iteration 2, step 10; ADR-033 and ADR-034): recorded research, loaded with
no login, so CI, reviewers and research mode `pack` reproduce it.

A pack is one folder of six files, which `research_packs/README.md` lists: `pack.yaml`, a
`PackManifest` holding the `sha256:` hash of each other file, then `summary.md`,
`sources.jsonl`, `excerpts.jsonl`, `domain_brief.json` and `answers.jsonl`.

- `load_pack` refuses a pack, with `PackRefused`, when `pack.yaml` lists a file a pack does not
  hold or gives no hash for one it must, when a file is missing or differs from its hash, and
  when an excerpt, an answer or an item of the domain brief names a source or an excerpt the
  pack lacks. It screens every excerpt and answer each time (`trust.screen`), quarantining a
  suspect one in memory, with a security event.
- `select_pack` reads each pack's keywords. A keyword matches when one of its content stems
  (`text.content_stems`) is among the stems of the brief's topics, and the pack with the most
  matching keywords is selected when it has at least `min_matches` and no other pack has as
  many. A tie selects none, and so do no topics; the selection's note says why, for the
  research record. `packs_dir` resolves against `preflight.HOME`.
- `PackProvider` is research mode `pack`'s research provider: `ask` answers from its pack by
  ADR-034's rule, and every other method refuses, since a pack starts no job.
"""

import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn

import yaml
from pydantic import BaseModel, ValidationError

from bidwright.config import QuestionsConfig
from bidwright.obs.events import EventRecorder
from bidwright.preflight import HOME
from bidwright.research.provider import NotebookSource, ResearchRefused
from bidwright.research.trust import screen
from bidwright.schemas import (
    AskResult,
    DomainBrief,
    JobStatus,
    PackAnswer,
    PackExcerpt,
    PackManifest,
    PackSource,
)
from bidwright.text import content_stems

PACK_FILE = "pack.yaml"
DATA_FILES = ("summary.md", "sources.jsonl", "excerpts.jsonl", "domain_brief.json", "answers.jsonl")
NO_PACK = "no pack for this domain"


class PackRefused(Exception):
    """A research pack that must not be used: a file changed or went missing, or the pack
    names what it does not hold."""


def digest(data: bytes) -> str:
    """A file's hash as `pack.yaml` writes it."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


@dataclass(frozen=True)
class Pack:
    """A loaded research pack, its excerpts and answers screened."""

    path: Path
    manifest: PackManifest
    sha256: str  # the hash of pack.yaml, which covers every other file through their hashes
    summary: str
    sources: list[PackSource]
    excerpts: list[PackExcerpt]
    answers: list[PackAnswer]
    domain_brief: DomainBrief

    @property
    def domain_id(self) -> str:
        return self.manifest.domain_id


def _manifest(path: Path) -> PackManifest:
    try:
        return PackManifest.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise PackRefused(f"{path.parent.name}/{path.name} is not a pack manifest: {exc}") from exc


def _rows[R: BaseModel](pack: str, name: str, text: str, model: type[R]) -> list[R]:
    rows: list[R] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(model.model_validate_json(line))
        except ValidationError as exc:
            raise PackRefused(f"{pack}: {name}, line {number}: {exc.errors()[0]['msg']}") from exc
    return rows


def _check_references(
    pack: str,
    manifest: PackManifest,
    sources: Sequence[PackSource],
    excerpts: Sequence[PackExcerpt],
    answers: Sequence[PackAnswer],
    brief: DomainBrief,
) -> None:
    source_ids = [s.id for s in sources]
    excerpt_ids = [e.id for e in excerpts]
    for kind, ids in (("source", source_ids), ("excerpt", excerpt_ids)):
        repeated = sorted({i for i in ids if ids.count(i) > 1})
        if repeated:
            raise PackRefused(f"{pack}: {kind} ids appear twice: {', '.join(repeated)}")
    named = {e.source_id for e in excerpts} - set(source_ids)
    cited = {i for a in answers for i in a.excerpt_ids}
    cited |= {i for item in [*brief.items, *brief.needs] for i in item.excerpt_ids}
    unknown = sorted(named | (cited - set(excerpt_ids)))
    if unknown:
        raise PackRefused(f"{pack}: names ids the pack does not hold: {', '.join(unknown)}")
    if brief.domain_id != manifest.domain_id:
        raise PackRefused(
            f"{pack}: domain_brief.json is for {brief.domain_id!r}, not {manifest.domain_id!r}"
        )


def load_pack(
    path: Path,
    patterns: Sequence[re.Pattern[str]],
    events: EventRecorder | None = None,
    *,
    node: str = "discover",
) -> Pack:
    """The pack in `path`, every file checked against its hash, its excerpts and answers
    screened with the suspect `patterns`."""
    name = path.name
    manifest_path = path / PACK_FILE
    if not manifest_path.is_file():
        raise PackRefused(f"{name}: no {PACK_FILE}")
    manifest = _manifest(manifest_path)
    unknown = sorted(set(manifest.files) - set(DATA_FILES))
    if unknown:
        raise PackRefused(f"{name}: {PACK_FILE} lists files a pack does not hold: {unknown}")
    unlisted = [f for f in DATA_FILES if f not in manifest.files]
    if unlisted:
        raise PackRefused(f"{name}: {PACK_FILE} gives no hash for {', '.join(unlisted)}")
    data: dict[str, str] = {}
    for file in DATA_FILES:
        try:
            raw = (path / file).read_bytes()
        except OSError as exc:
            raise PackRefused(f"{name}: {file} is missing") from exc
        if digest(raw) != manifest.files[file]:
            raise PackRefused(f"{name}: {file} does not match its hash in {PACK_FILE}")
        data[file] = raw.decode("utf-8")
    sources = _rows(name, "sources.jsonl", data["sources.jsonl"], PackSource)
    excerpts = _rows(name, "excerpts.jsonl", data["excerpts.jsonl"], PackExcerpt)
    answers = _rows(name, "answers.jsonl", data["answers.jsonl"], PackAnswer)
    try:
        brief = DomainBrief.model_validate_json(data["domain_brief.json"])
    except ValidationError as exc:
        raise PackRefused(f"{name}: domain_brief.json: {exc.errors()[0]['msg']}") from exc
    _check_references(name, manifest, sources, excerpts, answers, brief)
    return Pack(
        path=path,
        manifest=manifest,
        sha256=digest(manifest_path.read_bytes()),
        summary=data["summary.md"],
        sources=sources,
        excerpts=screen(excerpts, patterns, events, node=node),
        answers=screen(answers, patterns, events, node=node),
        domain_brief=brief,
    )


@dataclass(frozen=True)
class Selection:
    """The pack the brief's topics select, or none, with the reason for the research record."""

    path: Path | None
    domain_id: str | None
    matches: dict[str, int] = field(default_factory=dict)  # matching keywords, by domain id
    note: str | None = None


def packs_root(packs_dir: str | Path) -> Path:
    """`research.yaml`'s `packs_dir`, against `preflight.HOME` unless absolute."""
    path = Path(packs_dir)
    return path if path.is_absolute() else HOME / path


def keyword_matches(keywords: Sequence[str], topics: Sequence[str]) -> int:
    """How many keywords have a content stem among the topics' stems."""
    wanted: set[str] = set()
    for topic in topics:
        wanted |= content_stems(topic)
    return sum(1 for keyword in keywords if content_stems(keyword) & wanted)


def select_pack(topics: Sequence[str], packs_dir: str | Path, *, min_matches: int) -> Selection:
    """The pack with the most matching keywords, at least `min_matches` and no tie."""
    if not topics:
        return Selection(None, None, note=f"{NO_PACK}: the brief gave no topics")
    folders: dict[str, Path] = {}
    matches: dict[str, int] = {}
    for manifest_path in sorted(packs_root(packs_dir).glob(f"*/{PACK_FILE}")):
        manifest = _manifest(manifest_path)
        domain = manifest.domain_id
        if domain in folders:
            raise PackRefused(
                f"{folders[domain].name} and {manifest_path.parent.name} both hold {domain}"
            )
        folders[domain] = manifest_path.parent
        matches[domain] = keyword_matches(manifest.keywords, topics)
    best = max(matches.values(), default=0)
    if best < min_matches:
        return Selection(None, None, matches, NO_PACK)
    top = sorted(domain for domain, count in matches.items() if count == best)
    if len(top) > 1:
        tied = ", ".join(top)
        return Selection(None, None, matches, f"{NO_PACK}: {tied} tie with {best} keywords each")
    return Selection(folders[top[0]], top[0], matches)


class PackProvider:
    """The research provider of research mode `pack`, bound to one pack.

    `ask` applies ADR-034's rule. The question's content stems are `text.content_stems` of it;
    a recorded answer matches on its own question's stems, and an excerpt on its text's. Each
    must hold at least `max(min_terms, ceil(match_share × n))` of the question's `n` stems,
    and a question with fewer than `min_terms` stems matches nothing. The matching answer that
    holds the most stems fills `answer`, the first in pack order on a tie, and its excerpts come
    first; then the other matching excerpts, by stems held, then pack order; at most
    `max_matches`. A quarantined excerpt never returns, and a quarantined answer's text is
    withheld while its clean excerpts still return."""

    def __init__(self, pack: Pack, questions: QuestionsConfig) -> None:
        self.pack = pack
        self.rules = questions
        self._sources = {s.id: s for s in pack.sources}
        self._excerpts = {e.id: e for e in pack.excerpts}
        self._answer_stems = [content_stems(a.question) for a in pack.answers]
        self._excerpt_stems = [content_stems(e.text) for e in pack.excerpts]

    def _refuse(self, what: str) -> NoReturn:
        raise ResearchRefused(f"a research pack cannot {what}; it only answers questions")

    def create_notebook(self, title: str) -> str:
        self._refuse("create a notebook")

    def start(self, notebook_id: str, query: str) -> str:
        self._refuse("start a research job")

    def status(self, notebook_id: str, task_id: str, wait_s: float) -> JobStatus:
        self._refuse("poll a research job")

    def import_sources(self, notebook_id: str, task_id: str) -> int:
        self._refuse("import sources")

    def sources(self, notebook_id: str) -> list[NotebookSource]:
        self._refuse("list a notebook's sources")

    def bind(self, notebook_id: str) -> None:
        self._refuse("bind a notebook")

    def ask(self, question: str) -> AskResult:
        wanted = content_stems(question)
        if len(wanted) < self.rules.min_terms:
            return AskResult()
        needed = max(self.rules.min_terms, math.ceil(self.rules.match_share * len(wanted)))
        best: int | None = None
        best_held = 0
        for index, stems in enumerate(self._answer_stems):
            held = len(wanted & stems)
            if held >= needed and held > best_held:
                best, best_held = index, held
        chosen: dict[str, PackExcerpt] = {}
        if best is not None:
            for excerpt_id in self.pack.answers[best].excerpt_ids:
                excerpt = self._excerpts[excerpt_id]
                if not excerpt.quarantined:
                    chosen.setdefault(excerpt.id, excerpt)
        held_by = [len(wanted & stems) for stems in self._excerpt_stems]
        ranked = sorted(
            (index for index, held in enumerate(held_by) if held >= needed),
            key=lambda index: (-held_by[index], index),
        )
        for index in ranked:
            excerpt = self.pack.excerpts[index]
            if not excerpt.quarantined:
                chosen.setdefault(excerpt.id, excerpt)
        excerpts = list(chosen.values())[: self.rules.max_matches]
        recorded = self.pack.answers[best] if best is not None else None
        return AskResult(
            answer=recorded.answer if recorded is not None and not recorded.quarantined else None,
            excerpts=excerpts,
            sources=list({e.source_id: self._sources[e.source_id] for e in excerpts}.values()),
        )


__all__ = [
    "DATA_FILES",
    "NO_PACK",
    "PACK_FILE",
    "Pack",
    "PackProvider",
    "PackRefused",
    "Selection",
    "digest",
    "keyword_matches",
    "load_pack",
    "packs_root",
    "select_pack",
]
