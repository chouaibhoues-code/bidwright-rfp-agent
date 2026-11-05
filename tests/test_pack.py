"""Research packs and `ask_research` (Iteration 2, step 10): the hash check, inbound trust
(FI-10), pack selection, ADR-034's matching rule and the authority tiers."""

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from bidwright.config import TiersConfig, compile_patterns, load_config
from bidwright.obs.events import EventRecorder, read_events
from bidwright.preflight import HOME
from bidwright.research.pack import (
    NO_PACK,
    PACK_FILE,
    PackProvider,
    PackRefused,
    digest,
    load_pack,
    packs_root,
    select_pack,
)
from bidwright.research.provider import ResearchRefused
from bidwright.research.trust import tier
from bidwright.schemas import ToolResult
from bidwright.tools import NOT_IN_PACK, AskResearchArgs, ask_tool

CONFIG = load_config()
QUESTIONS = CONFIG.research.questions
PATTERNS = compile_patterns(CONFIG.ingest.suspect_patterns, "config/ingest.yaml")
FIXTURE = Path(__file__).resolve().parent / "data" / "packs" / "fixture"
DOMAIN = "fixture-records-management"
MATCHING_TOPICS = ["records management in councils", "retention schedules for digital records"]

Row = dict[str, Any]


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def _copy(tmp_path: Path, name: str = "fixture") -> Path:
    folder = tmp_path / name
    shutil.copytree(FIXTURE, folder)
    return folder


def _manifest(folder: Path) -> dict[str, Any]:
    return yaml.safe_load((folder / PACK_FILE).read_text(encoding="utf-8"))


def _rehash(folder: Path) -> None:
    """Write each file's hash into `pack.yaml` again, as the builder would."""
    manifest = _manifest(folder)
    manifest["files"] = {name: digest((folder / name).read_bytes()) for name in manifest["files"]}
    _write(folder / PACK_FILE, yaml.safe_dump(manifest, sort_keys=False))


def _edit_rows(folder: Path, name: str, change: Callable[[Row], Row]) -> None:
    """Change each row of one JSON Lines file, then hash the pack again."""
    path = folder / name
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    _write(path, "".join(json.dumps(change(row), ensure_ascii=False) + "\n" for row in rows))
    _rehash(folder)


def _ask(folder: Path, question: str, events: EventRecorder | None = None) -> ToolResult:
    provider = PackProvider(load_pack(folder, PATTERNS, events), QUESTIONS)
    tool = ask_tool(provider, max_excerpts=QUESTIONS.max_matches)
    return tool.run(AskResearchArgs(question=question))


def _ids(result: ToolResult) -> list[str]:
    return [excerpt["id"] for excerpt in result.data["excerpts"]]


def test_fi10_poisoned_excerpt_is_quarantined(tmp_path: Path) -> None:
    events = EventRecorder(tmp_path / "events.jsonl")
    pack = load_pack(FIXTURE, PATTERNS, events)
    assert [e.id for e in pack.excerpts if e.quarantined] == ["PX-0005"]
    stored = (FIXTURE / "excerpts.jsonl").read_text(encoding="utf-8")
    assert '"quarantined": true' not in stored, "the file is untouched; the quarantine is in memory"
    first = read_events(tmp_path / "events.jsonl")[0]
    assert (first.kind, first.node, first.attribution) == (
        "security",
        "discover",
        "injection-dominant",
    )
    assert first.detail == "PX-0005 quarantined: it reads like an instruction to a model"

    question = "Which certification does the supplier hold?"
    poisoned = _ask(FIXTURE, question)
    assert (poisoned.status, poisoned.data, poisoned.reason) == ("EMPTY", None, NOT_IN_PACK)

    clean = _copy(tmp_path)
    honest = "Suppliers state each certification they hold, with its issuing body and expiry date."
    _edit_rows(
        clean, "excerpts.jsonl", lambda r: r | {"text": honest} if r["id"] == "PX-0005" else r
    )
    control = _ask(clean, question)
    assert control.status == "OK" and _ids(control) == ["PX-0005"], "the clean control returns it"
    assert control.data["excerpts"][0]["source"] == "Notes on records services"


def test_fi10_poisoned_answer_is_withheld(tmp_path: Path) -> None:
    events = EventRecorder(tmp_path / "events.jsonl")
    question = "How long does a records migration take?"
    poisoned = _ask(FIXTURE, question, events)
    assert poisoned.status == "OK" and poisoned.data["answer"] is None, "its text is withheld"
    assert _ids(poisoned) == ["PX-0006"], "while its clean excerpt still returns"
    details = [e.detail for e in read_events(tmp_path / "events.jsonl")]
    assert (
        "the recorded answer to 'How long does a records migration take?' quarantined: it reads"
        " like an instruction to a model" in details
    )

    clean = _copy(tmp_path)
    honest = "Migrations take longer than planned when the old metadata is incomplete [1]."
    _edit_rows(
        clean, "answers.jsonl", lambda r: r | {"answer": honest} if r["question"] == question else r
    )
    control = _ask(clean, question)
    assert control.data["answer"] == honest and _ids(control) == ["PX-0006"]


def _changed(folder: Path) -> None:
    path = folder / "excerpts.jsonl"
    _write(path, path.read_text(encoding="utf-8").replace("three years", "five years"))


def _missing(folder: Path) -> None:
    (folder / "answers.jsonl").unlink()


def _unknown_file(folder: Path) -> None:
    manifest = _manifest(folder)
    manifest["files"]["notes.txt"] = digest(b"")
    _write(folder / PACK_FILE, yaml.safe_dump(manifest))


def _unhashed(folder: Path) -> None:
    manifest = _manifest(folder)
    del manifest["files"]["summary.md"]
    _write(folder / PACK_FILE, yaml.safe_dump(manifest))


def _unknown_source(folder: Path) -> None:
    _edit_rows(
        folder,
        "excerpts.jsonl",
        lambda r: r | {"source_id": "PS-009"} if r["id"] == "PX-0006" else r,
    )


def _other_domain(folder: Path) -> None:
    path = folder / "domain_brief.json"
    brief = json.loads(path.read_text(encoding="utf-8"))
    _write(path, json.dumps(brief | {"domain_id": "another-domain"}))
    _rehash(folder)


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        (_changed, "fixture: excerpts.jsonl does not match its hash in pack.yaml"),
        (_missing, "fixture: answers.jsonl is missing"),
        (_unknown_file, "fixture: pack.yaml lists files a pack does not hold: ['notes.txt']"),
        (_unhashed, "fixture: pack.yaml gives no hash for summary.md"),
        (_unknown_source, "fixture: names ids the pack does not hold: PS-009"),
        (_other_domain, "fixture: domain_brief.json is for 'another-domain', not"),
    ],
)
def test_a_pack_with_a_tampered_file_is_refused(
    tmp_path: Path, tamper: Callable[[Path], None], message: str
) -> None:
    folder = _copy(tmp_path)
    load_pack(folder, PATTERNS)  # the copy loads before it is changed
    tamper(folder)
    with pytest.raises(PackRefused) as refused:
        load_pack(folder, PATTERNS)
    assert str(refused.value).startswith(message)


def test_the_fixture_is_selected_for_matching_topics_and_none_for_a_tie_or_one_keyword(
    tmp_path: Path,
) -> None:
    packs = FIXTURE.parent
    chosen = select_pack(MATCHING_TOPICS, packs, min_matches=2)
    assert (chosen.path, chosen.domain_id, chosen.note) == (FIXTURE, DOMAIN, None)
    assert chosen.matches == {DOMAIN: 3}, "records management, retention schedule, digital records"

    single = select_pack(["archives of the county"], packs, min_matches=2)
    assert (single.path, single.matches, single.note) == (None, {DOMAIN: 1}, NO_PACK)
    assert select_pack([], packs, min_matches=2).note == f"{NO_PACK}: the brief gave no topics"

    _copy(tmp_path / "packs")
    twin = _copy(tmp_path / "packs", "twin")
    manifest = _manifest(twin)
    _write(twin / PACK_FILE, yaml.safe_dump(manifest | {"domain_id": "fixture-twin"}))
    tie = select_pack(MATCHING_TOPICS, tmp_path / "packs", min_matches=2)
    assert tie.path is None and tie.matches == {DOMAIN: 3, "fixture-twin": 3}
    assert tie.note == f"{NO_PACK}: {DOMAIN}, fixture-twin tie with 3 keywords each"

    _write(twin / PACK_FILE, yaml.safe_dump(manifest))
    with pytest.raises(PackRefused, match="fixture and twin both hold fixture-records-management"):
        select_pack(MATCHING_TOPICS, tmp_path / "packs", min_matches=2)


def test_packs_dir_resolves_against_home(tmp_path: Path) -> None:
    assert packs_root("research_packs") == HOME / "research_packs"
    assert packs_root(tmp_path) == tmp_path
    assert select_pack(MATCHING_TOPICS, tmp_path / "none", min_matches=2).note == NO_PACK


@pytest.mark.parametrize(
    "question",
    ["What does the council charge for parking permits?", "Records?", "Why?"],
)
def test_ask_research_returns_not_in_pack(question: str) -> None:
    """Nothing in the pack holds enough of the question's stems, or the question has fewer
    than two: 'Records?' has one, though every excerpt holds it."""
    result = _ask(FIXTURE, question)
    assert (result.status, result.data, result.reason) == ("EMPTY", None, NOT_IN_PACK)


def test_a_question_the_pack_answers_returns_its_excerpts_with_their_sources() -> None:
    question = "What metadata should digital records keep?"
    result = _ask(FIXTURE, question)
    assert result.status == "OK"
    assert result.data["answer"].startswith("Digital records keep the creator")
    assert [(e["id"], e["source"], e["tier"]) for e in result.data["excerpts"]] == [
        ("PX-0003", "A digital records standard", 4),
        ("PX-0001", "Records retention guidance for public bodies", 4),
        ("PX-0004", "A digital records standard", 4),
        ("PX-0006", "Notes on records services", 4),
    ], "the answer's excerpts first, then by stems held, then pack order"
    assert result.data["excerpts"][0]["text"].startswith("Digital records keep their metadata")
    provider = PackProvider(load_pack(FIXTURE, PATTERNS), QUESTIONS)
    capped = ask_tool(provider, max_excerpts=2).run(AskResearchArgs(question=question))
    assert _ids(capped) == ["PX-0003", "PX-0001"]


def test_with_two_matching_answers_the_one_holding_more_stems_fills_the_answer() -> None:
    """Both recorded answers on retention match; the second, on digital records in a retention
    schedule, holds five of the question's six stems against the first's three."""
    result = _ask(FIXTURE, "How long should digital records be kept under a retention schedule?")
    assert result.data["answer"].startswith("A retention schedule sets how long each class")
    assert _ids(result) == ["PX-0001", "PX-0003", "PX-0004"]


def test_a_pack_starts_no_job() -> None:
    provider = PackProvider(load_pack(FIXTURE, PATTERNS), QUESTIONS)
    calls: list[Callable[[], object]] = [
        lambda: provider.create_notebook("run"),
        lambda: provider.start("notebook", "query"),
        lambda: provider.status("notebook", "task", 1.0),
        lambda: provider.import_sources("notebook", "task"),
        lambda: provider.sources("notebook"),
        lambda: provider.bind("notebook"),
    ]
    for call in calls:
        with pytest.raises(ResearchRefused, match="a research pack cannot"):
            call()


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.gov.uk/guidance/records", 1),  # a suffix entry, ".gov.uk"
        ("https://www.w3.org/TR/WCAG22/", 1),  # a subdomain of the entry "w3.org"
        ("https://w3.org/", 1),  # the entry's own host
        ("https://notw3.org/", 4),  # an entry with no dot is not a bare suffix
        ("https://www.ox.ac.uk/research", 2),
        ("https://socitm.net/", 3),
        ("https://notes.example.net/records-services", 4),  # an unknown host
    ],
)
def test_tiers_follow_the_host(url: str, expected: int) -> None:
    assert tier(url, CONFIG.research.tiers) == expected


def test_a_host_takes_the_lowest_matching_tier() -> None:
    tiers = TiersConfig.model_validate({1: ["example.org"], 3: [".org"], "default": 4})
    assert tier("https://docs.example.org/page", tiers) == 1
    assert tier("https://other.org/page", tiers) == 3
