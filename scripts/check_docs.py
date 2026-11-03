"""Check the committed documents: links, wikilinks, dates, front matter and voice.

Run `uv run python scripts/check_docs.py`. It prints one line per problem, as
`path:line: message`, and exits 1 if there is any. CI runs it as the `docs-links` job, and
`scripts/gen_docs.py --check` as the `docs-generated` job.

The checks skip fenced code blocks and inline code, except the internal-marker check:
- links: a relative Markdown link resolves to a file in the repository, and an anchor names a
  heading of the Markdown file it points to;
- wikilinks: `[[Name]]` resolves to `Name.md` under `context/` or `docs/`;
- dates: no full date in another format (`11/02/2026`, `2 November 2026`), no relative date
  (`yesterday`, `next week`), and every ISO date is a real day;
- front matter: every file in `context/` has the fields and values in `FRONT_MATTER`;
- voice: no internal marker anywhere, and no first- or second-person pronoun in `context/`,
  `docs/`, `DECISIONS.md`, `ASSUMPTIONS.md` or `TIMELOG.md`. Quoted text is skipped, because a
  quotation keeps its source's words;
- test names: a `test_*` name in inline code under `docs/` is a test function or file under
  `tests/`, or a `test_x_*` pattern some function matches, so a renamed test shows up here
  rather than as a stale reference. `docs/designs/` is exempt, because a design names the
  tests it will build.
"""

import os
import re
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path
from urllib.parse import unquote

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROOT_DOCS = ("README.md", "DECISIONS.md", "ASSUMPTIONS.md", "TIMELOG.md", "AGENTS.md", "CLAUDE.md")
DOC_DIRS = ("docs", "context")
VOICE_ROOT_DOCS = frozenset({"DECISIONS.md", "ASSUMPTIONS.md", "TIMELOG.md"})
INTERNAL_MARKER = "*(Internal"

FRONT_MATTER = {
    "type": {"plan", "decision-form", "backlog", "register"},
    "status": {"draft", "current", "superseded"},
}

LINK = re.compile(r"\[(?:[^\]\[]|\[[^\]]*\])*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
WIKILINK = re.compile(r"\[\[([^\]|#]+)(#[^\]|]*)?(?:\|[^\]]*)?\]\]")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE = re.compile(r"(`+)(?:(?!\1).)+\1")
QUOTED = re.compile(r"\"[^\"\n]*\"|“[^”\n]*”")

MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?"
    r"|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
OTHER_DATE = re.compile(
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"
    rf"|\b{MONTH}\.? \d{{1,2}}(?:st|nd|rd|th)?,? \d{{4}}\b"
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)? {MONTH} \d{{4}}\b"
)
RELATIVE_DATE = re.compile(
    r"\b(?:yesterday|today|tomorrow|tonight|(?:last|next|this) (?:week|month|year))\b",
    re.IGNORECASE,
)
ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
TEST_NAME = re.compile(r"`(?:tests/)?(test_[A-Za-z0-9_]+(?:\*|\.py)?)`")
TEST_DEF = re.compile(r"^def (test_\w+)\(", re.MULTILINE)
SECOND_PERSON = re.compile(r"\b(?:you|your|yours|yourself|yourselves)\b", re.IGNORECASE)
FIRST_PERSON = re.compile(
    r"\bI(?=\s+[a-z]|['’])"
    r"|\b(?:[Mm]e|[Mm]y|[Mm]yself|[Ww]e|[Oo]ur|[Oo]urs|[Oo]urselves|[Uu]s)\b"
)
# A capital I after one of these words is a numeral or a label, as in "Phase I is done".
LABEL_WORDS = frozenset(
    """annex appendix article category chapter class figure grade item iteration level option
    part phase schedule section stage step table tier type volume""".split()
)


@dataclass(frozen=True)
class Problem:
    path: Path
    line: int
    message: str

    def __str__(self) -> str:
        shown = self.path.relative_to(ROOT) if ROOT in self.path.parents else self.path
        return f"{shown.as_posix()}:{self.line}: {self.message}"


def documents(root: Path = ROOT) -> list[Path]:
    """The Markdown files the checks cover."""
    found = [root / name for name in ROOT_DOCS if (root / name).exists()]
    for folder in DOC_DIRS:
        found += sorted((root / folder).rglob("*.md")) if (root / folder).exists() else []
    return found


def slug(heading: str) -> str:
    """A heading's anchor, as GitHub writes it."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)
    text = text.replace("`", "").strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def prose_lines(text: str) -> Iterator[tuple[int, str]]:
    """Numbered lines outside fenced code, with inline code blanked out."""
    for number, line in unfenced_lines(text):
        yield number, INLINE_CODE.sub(" ", line)


def unfenced_lines(text: str) -> Iterator[tuple[int, str]]:
    fenced = False
    for number, line in enumerate(text.splitlines(), start=1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            yield number, line


@cache
def anchors(path: Path) -> frozenset[str]:
    """The anchors of a Markdown file's headings, numbered as GitHub numbers repeats."""
    seen: Counter[str] = Counter()
    found = set()
    for _, line in unfenced_lines(path.read_text(encoding="utf-8")):
        match = HEADING.match(line)
        if not match:
            continue
        base = slug(match.group(2))
        found.add(base if not seen[base] else f"{base}-{seen[base]}")
        seen[base] += 1
    return frozenset(found)


def front_matter(text: str) -> tuple[dict[str, object] | None, str | None]:
    if not text.startswith("---\n"):
        return None, "front matter missing"
    end = text.find("\n---\n", 4)
    if end < 0:
        return None, "front matter not closed"
    try:
        data = yaml.safe_load(text[4:end])
    except yaml.YAMLError as exc:
        return None, f"front matter is not valid YAML: {exc}"
    if not isinstance(data, dict):
        return None, "front matter is not a mapping"
    return data, None


def check_front_matter(path: Path, text: str) -> list[Problem]:
    data, error = front_matter(text)
    if data is None:
        return [Problem(path, 1, error or "front matter missing")]
    problems = []
    for key in ("title", "type", "applies-to", "related", "date", "status", "tags"):
        if key not in data:
            problems.append(Problem(path, 1, f"front matter lacks {key!r}"))
    for key, allowed in FRONT_MATTER.items():
        value = data.get(key)
        if key in data and not (isinstance(value, str) and value in allowed):
            problems.append(Problem(path, 1, f"{key} must be one of {sorted(allowed)}"))
    if "applies-to" in data and data["applies-to"] != "bidwright":
        problems.append(Problem(path, 1, "applies-to must be bidwright"))
    when = data.get("date")
    if "date" in data and not isinstance(when, date):
        problems.append(Problem(path, 1, "date must be an ISO 8601 date, YYYY-MM-DD"))
    related = data.get("related")
    if "related" in data and not (
        isinstance(related, list)
        and all(isinstance(r, str) and WIKILINK.fullmatch(r) for r in related)
    ):
        problems.append(Problem(path, 1, "related must be a list of wikilinks"))
    if "tags" in data and not isinstance(data["tags"], list):
        problems.append(Problem(path, 1, "tags must be a list"))
    return problems


def doc_names(root: Path) -> frozenset[str]:
    """The names a wikilink may use: Markdown file stems under `context/` and `docs/`."""
    folders = [root / folder for folder in DOC_DIRS if (root / folder).exists()]
    return frozenset(p.stem for folder in folders for p in folder.rglob("*.md"))


def exists_exactly(path: Path, root: Path) -> bool:
    """Whether `path` exists with exactly this case, as on Linux, where CI runs."""
    current = root
    for part in path.relative_to(root).parts:
        if not current.is_dir() or part not in os.listdir(current):
            return False
        current = current / part
    return True


def check_links(path: Path, text: str, root: Path, names: frozenset[str]) -> list[Problem]:
    problems = []
    for number, line in prose_lines(text):
        for match in LINK.finditer(line):
            target = match.group(1)
            if re.match(r"[a-z][a-z0-9+.-]*:", target):
                continue
            file_part, _, anchor = target.partition("#")
            # normpath folds ".." without touching case, which resolve() may change on Windows.
            linked = Path(os.path.normpath(path.parent / unquote(file_part))) if file_part else path
            if root not in linked.parents and linked != root:
                problems.append(Problem(path, number, f"link leaves the repository: {target}"))
            elif not exists_exactly(linked, root):
                problems.append(Problem(path, number, f"broken link: {target}"))
            elif anchor and linked.suffix == ".md" and anchor not in anchors(linked):
                problems.append(Problem(path, number, f"no heading for anchor: {target}"))
    for number, line in prose_lines(text):
        for match in WIKILINK.finditer(line):
            name = match.group(1).strip()
            if name not in names:
                problems.append(Problem(path, number, f"wikilink resolves to no file: [[{name}]]"))
    return problems


def check_dates(path: Path, text: str) -> list[Problem]:
    problems = []
    for number, line in prose_lines(text):
        for match in OTHER_DATE.finditer(line):
            problems.append(Problem(path, number, f"date not in ISO 8601: {match.group(0)!r}"))
        for match in RELATIVE_DATE.finditer(QUOTED.sub(" ", line)):
            problems.append(Problem(path, number, f"relative date: {match.group(0)!r}"))
        for match in ISO_DATE.finditer(line):
            year, month, day = (int(g) for g in match.groups())
            try:
                date(year, month, day)
            except ValueError:
                problems.append(Problem(path, number, f"not a real day: {match.group(0)}"))
    return problems


def check_voice(path: Path, text: str, *, pronouns: bool) -> list[Problem]:
    problems = []
    for number, line in enumerate(text.splitlines(), start=1):
        if INTERNAL_MARKER in line:
            problems.append(Problem(path, number, "internal marker"))
    if not pronouns:
        return problems
    for number, line in prose_lines(text):
        bare = QUOTED.sub(" ", re.sub(r"\]\([^)]*\)", "]", line))
        for pattern, kind in ((SECOND_PERSON, "second"), (FIRST_PERSON, "first")):
            for match in pattern.finditer(bare):
                before = re.findall(r"[A-Za-z]+", bare[: match.start()])
                if match.group(0) == "I" and before and before[-1].lower() in LABEL_WORDS:
                    continue
                problems.append(Problem(path, number, f"{kind}-person pronoun: {match.group(0)!r}"))
    return problems


def test_names(root: Path) -> frozenset[str] | None:
    """The test functions and files under `tests/`, or None when there is no such folder."""
    folder = root / "tests"
    if not folder.is_dir():
        return None
    names: set[str] = set()
    for path in folder.rglob("test_*.py"):
        names.add(path.name)
        names.update(TEST_DEF.findall(path.read_text(encoding="utf-8")))
    return frozenset(names)


def check_test_names(path: Path, text: str, names: frozenset[str]) -> list[Problem]:
    problems = []
    for number, line in unfenced_lines(text):
        for match in TEST_NAME.finditer(line):
            name = match.group(1)
            if name.endswith("*"):
                if not any(n.startswith(name[:-1]) for n in names):
                    problems.append(Problem(path, number, f"no test matches {name!r}"))
            elif name not in names:
                problems.append(Problem(path, number, f"no such test: {name}"))
    return problems


def needs_voice(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return relative.parts[0] in DOC_DIRS or relative.as_posix() in VOICE_ROOT_DOCS


def names_tests_that_exist(path: Path, root: Path) -> bool:
    """`docs/` describes the current tag, so its test names must exist; designs may look ahead."""
    return root / "docs" in path.parents and root / "docs" / "designs" not in path.parents


def check(root: Path = ROOT) -> list[Problem]:
    root = root.resolve()
    names = doc_names(root)
    tests = test_names(root)
    problems = []
    for path in documents(root):
        text = path.read_text(encoding="utf-8")
        problems += check_links(path, text, root, names)
        problems += check_dates(path, text)
        problems += check_voice(path, text, pronouns=needs_voice(path, root))
        if root / "context" in path.parents:
            problems += check_front_matter(path, text)
        if tests is not None and names_tests_that_exist(path, root):
            problems += check_test_names(path, text, tests)
    return problems


def main() -> int:
    problems = check()
    for problem in problems:
        print(problem)
    print(f"{len(documents())} documents checked, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
