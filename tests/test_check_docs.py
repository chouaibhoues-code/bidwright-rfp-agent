"""`scripts/check_docs.py` finds each kind of problem, and passes a clean tree (WP-0b.5)."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_docs.py"

pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="scripts/ is not in this image")

GOOD_FRONT = """---
title: Plan
type: plan
applies-to: bidwright
related: ["[[Backlog]]"]
date: 2026-11-02
status: current
tags: [bidwright]
---
"""


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_docs", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return tmp_path


def _messages(tmp_path: Path, files: dict[str, str]) -> list[str]:
    root = _tree(tmp_path, files)
    return [p.message for p in _module().check(root)]


def _clean() -> dict[str, str]:
    return {
        "context/Plan.md": (
            GOOD_FRONT + "# Plan\n\nSee [[Backlog]] and"
            " [the ADR](../DECISIONS.md#adr-001-gemini-through-the-sdk).\n"
        ),
        "context/Backlog.md": GOOD_FRONT.replace("[[Backlog]]", "[[Plan]]") + "# Backlog\n",
        "DECISIONS.md": (
            "# Decisions\n\n### ADR-001: Gemini through the `SDK`\n\nDated 2026-11-02.\n"
        ),
        "docs/a.md": (
            '# A\n\nThe owner decides. Claude drafts. A quote keeps its words: "you decide".\n\n'
            "```text\nyou and we, 11/02/2026, next week\n```\n\n"
            "Code such as `we_count` is skipped. Spelled the US way.\n"
        ),
    }


def test_clean_tree_passes(tmp_path: Path) -> None:
    assert _messages(tmp_path, _clean()) == []


def test_broken_link_and_missing_anchor(tmp_path: Path) -> None:
    files = _clean()
    files["docs/a.md"] += "\nSee [gone](missing.md) and [here](../DECISIONS.md#no-such-heading).\n"
    messages = _messages(tmp_path, files)
    assert "broken link: missing.md" in messages
    assert "no heading for anchor: ../DECISIONS.md#no-such-heading" in messages


def test_repeated_headings_get_numbered_anchors(tmp_path: Path) -> None:
    files = _clean()
    files["docs/b.md"] = "# B\n\n## Notes\n\n## Notes\n\n[second](#notes-1)\n"
    assert _messages(tmp_path, files) == []


def test_unresolved_wikilink(tmp_path: Path) -> None:
    files = _clean()
    files["context/Plan.md"] += "\nAlso [[Nowhere]].\n"
    assert "wikilink resolves to no file: [[Nowhere]]" in _messages(tmp_path, files)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Due 11/02/2026.", "date not in ISO 8601: '11/02/2026'"),
        ("Due 2 November 2026.", "date not in ISO 8601: '2 November 2026'"),
        ("Due November 2, 2026.", "date not in ISO 8601: 'November 2, 2026'"),
        ("Due next week.", "relative date: 'next week'"),
        ("Due 2026-02-30.", "not a real day: 2026-02-30"),
    ],
)
def test_dates(tmp_path: Path, text: str, expected: str) -> None:
    files = _clean()
    files["docs/a.md"] += f"\n{text}\n"
    assert expected in _messages(tmp_path, files)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Then you decide.", "second-person pronoun: 'you'"),
        ("Your call.", "second-person pronoun: 'Your'"),
        ("Then we decide.", "first-person pronoun: 'we'"),
        ("I think so.", "first-person pronoun: 'I'"),
        ("Let us see.", "first-person pronoun: 'us'"),
        ("*(Internal: a note.)*", "internal marker"),
    ],
)
def test_voice(tmp_path: Path, text: str, expected: str) -> None:
    files = _clean()
    files["docs/a.md"] += f"\n{text}\n"
    assert expected in _messages(tmp_path, files)


@pytest.mark.parametrize(
    "text", ["Phase I is done.", "Option I covers parsing.", "Annex I sets the format."]
)
def test_a_numeral_or_label_i_is_not_a_pronoun(tmp_path: Path, text: str) -> None:
    files = _clean()
    files["docs/a.md"] += f"\n{text}\n"
    assert _messages(tmp_path, files) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [("I’m sure.", "first-person pronoun: 'I'"), ("Us first.", "first-person pronoun: 'Us'")],
)
def test_more_first_person_forms(tmp_path: Path, text: str, expected: str) -> None:
    files = _clean()
    files["docs/a.md"] += f"\n{text}\n"
    assert expected in _messages(tmp_path, files)


def test_wikilinks_in_code_are_examples(tmp_path: Path) -> None:
    files = _clean()
    files["docs/a.md"] += "\nThe syntax is `[[Name]]`.\n\n```markdown\n[[Other]]\n```\n"
    assert _messages(tmp_path, files) == []


def test_a_link_must_match_the_file_name_case(tmp_path: Path) -> None:
    files = _clean()
    files["docs/a.md"] += "\nSee [the plan](../context/plan.md).\n"
    assert "broken link: ../context/plan.md" in _messages(tmp_path, files)


def test_a_link_out_of_the_repository_is_named_as_such(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (tmp_path / "outside.md").write_text("# Outside\n", encoding="utf-8")
    files = _clean()
    files["docs/a.md"] += "\nSee [it](../../outside.md#nowhere).\n"
    _tree(root, files)
    messages = [p.message for p in _module().check(root)]
    assert "link leaves the repository: ../../outside.md#nowhere" in messages


def test_front_matter_with_a_list_value_is_a_problem_not_a_crash(tmp_path: Path) -> None:
    files = _clean()
    files["context/Plan.md"] = files["context/Plan.md"].replace("type: plan", "type: [plan]", 1)
    assert any(m.startswith("type must be one of") for m in _messages(tmp_path, files))


def test_front_matter_is_checked_in_subfolders(tmp_path: Path) -> None:
    files = _clean()
    files["context/registers/Extra.md"] = "# Extra\n"
    assert "front matter missing" in _messages(tmp_path, files)


def test_readme_may_address_the_reader(tmp_path: Path) -> None:
    files = _clean()
    files["README.md"] = "# Readme\n\nYou can run the demo.\n"
    assert _messages(tmp_path, files) == []


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("type: plan", "type: memo", "type must be one of"),
        ("status: current", "status: done", "status must be one of"),
        ("applies-to: bidwright", "applies-to: other", "applies-to must be bidwright"),
        ("date: 2026-11-02", "date: soon", "date must be an ISO 8601 date, YYYY-MM-DD"),
        ('related: ["[[Backlog]]"]', "related: [Backlog]", "related must be a list of wikilinks"),
        ("tags: [bidwright]\n", "", "front matter lacks 'tags'"),
    ],
)
def test_front_matter(tmp_path: Path, old: str, new: str, expected: str) -> None:
    files = _clean()
    files["context/Plan.md"] = files["context/Plan.md"].replace(old, new, 1)
    assert any(m.startswith(expected) for m in _messages(tmp_path, files))


def test_front_matter_missing(tmp_path: Path) -> None:
    files = _clean()
    files["context/Plan.md"] = "# Plan\n\nSee [[Backlog]].\n"
    assert "front matter missing" in _messages(tmp_path, files)


def test_repository_documents_pass() -> None:
    problems = _module().check()
    assert not problems, "\n".join(str(p) for p in problems)
