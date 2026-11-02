"""Repository hygiene checks: secrets and private material stay out of git."""

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _committable_files() -> list[Path]:
    """Tracked files plus untracked files that are not ignored, i.e. what a commit could add."""
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [ROOT / line for line in out.splitlines() if line]


def _is_ignored(relative_path: str) -> bool:
    return subprocess.run(["git", "check-ignore", "-q", relative_path], cwd=ROOT).returncode == 0


def test_secrets_and_private_material_are_ignored() -> None:
    for relative_path in (".env", "private/", "private/notes.md", "outputs/run/summary.json"):
        assert _is_ignored(relative_path), f"{relative_path} must be ignored"
    assert not _is_ignored(".env.example")


def test_no_pdf_committable_outside_inputs() -> None:
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in _committable_files()
        if path.suffix.lower() == ".pdf"
        and not path.relative_to(ROOT).as_posix().startswith("inputs/")
    ]
    assert offenders == []


def _tokens(text: str) -> set[str]:
    """Words, their path parts, adjacent path-part pairs, and their -_. fragments, lowercased."""
    cleaned = text.replace("\\", "/")
    for char in "`'\"()[]{}<>,;|":
        cleaned = cleaned.replace(char, " ")
    tokens: set[str] = set()
    for raw in cleaned.split():
        word = raw.strip(".:").lower()
        if not word:
            continue
        stems = [part.removesuffix(".git") for part in word.split("/") if part]
        tokens.add(word)
        tokens.update(stems)
        tokens.update(f"{left}/{right}" for left, right in zip(stems, stems[1:], strict=False))
        for stem in stems:
            tokens.update(fragment for fragment in re.split(r"[-_.]", stem) if fragment)
    return tokens


def test_no_committable_file_names_restricted_sources() -> None:
    """Compares salted token hashes, so the test never contains the names it forbids."""
    raw = os.environ.get("HYGIENE_HASHES")
    if not raw:
        pytest.skip("HYGIENE_HASHES is not set, so the restricted-name check cannot run")
    spec = json.loads(raw)
    salt, forbidden = spec["salt"], set(spec["sha256"])
    hits = []
    for path in _committable_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if any(
            hashlib.sha256((salt + token).encode()).hexdigest() in forbidden
            for token in _tokens(text)
        ):
            hits.append(path.relative_to(ROOT).as_posix())
    assert hits == []
