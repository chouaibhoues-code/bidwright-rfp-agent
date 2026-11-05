"""Repository hygiene checks: secrets and private material stay out of git."""

import hashlib
import subprocess
from pathlib import Path

import pytest

from bidwright.restricted import RestrictedNames, tokens

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    not (ROOT / ".git").exists(), reason="not a git checkout, as inside the Docker image"
)


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


def test_the_wheel_and_the_image_exclude_the_same_evaluation_paths() -> None:
    """Gold, corpus specs, results, labels and spikes ship in neither (ADR-014)."""
    import tomllib

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    excluded = set(pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["exclude"])
    ignored = {
        line.strip().rstrip("/")
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.startswith("evals/")
    }
    expected = {"evals/corpus", "evals/gold", "evals/results", "evals/labels", "evals/spikes"}
    assert expected <= excluded and expected <= ignored


def test_no_pdf_committable_outside_inputs() -> None:
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in _committable_files()
        if path.suffix.lower() == ".pdf"
        and not path.relative_to(ROOT).as_posix().startswith("inputs/")
    ]
    assert offenders == []


def test_no_committable_file_names_restricted_sources() -> None:
    """Compares salted token hashes, so the test never contains the names it forbids. The
    research pack builder leaves out what the same check flags (`bidwright.restricted`)."""
    restricted = RestrictedNames.from_environment()
    if restricted is None:
        pytest.skip("HYGIENE_HASHES is not set, so the restricted-name check cannot run")
    hits = []
    for path in _committable_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if restricted.flags(text):
            hits.append(path.relative_to(ROOT).as_posix())
    assert hits == []


def test_the_check_flags_a_salted_token_and_its_fragments() -> None:
    """With a made-up list: a name is flagged alone, in a path and in a hyphenated word, and
    text without it is not."""
    salt = "test-salt"
    forbidden = frozenset({hashlib.sha256((salt + "zebrafish").encode()).hexdigest()})
    restricted = RestrictedNames(salt, forbidden)
    assert restricted.flags("Notes on ZebraFish, 2026.")
    assert restricted.flags(r"see C:\work\zebrafish-tools\readme.md")
    assert not restricted.flags("Notes on zebras and fish")
    assert "zebrafish" in tokens("[zebrafish_v2](https://example.com/zebrafish.git)")
