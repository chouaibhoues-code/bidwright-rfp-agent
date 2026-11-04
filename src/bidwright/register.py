"""The solicitation control register: every document of a package, with its role and its place
in the order of precedence (Iteration 1, step 7; the design's section 6.2).

Roles and precedence come from `package.yaml` when the package has one. Otherwise a file's
role comes from its name: `addendum` or `amendment` gives an addendum; `annex`, `appendix`,
`schedule` or `attachment` an annex; `form`, `template` or `declaration` a form; anything else
the main document. If more than one file is main, the first by name stays main and the others
become annexes. Precedence then runs: addenda, the latest file name first; the main document;
annexes by name; forms by name. `ingest` fills each entry's title and pages after parsing.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from bidwright.config import ParserChoice
from bidwright.schemas import ControlRegister, DocFormat, DocRole, DocumentEntry

PACKAGE_FILE = "package.yaml"
ROLE_WORDS: tuple[tuple[DocRole, tuple[str, ...]], ...] = (
    ("addendum", ("addendum", "addenda", "amendment")),
    ("annex", ("annex", "appendix", "appendices", "schedule", "attachment")),
    ("form", ("form", "template", "declaration")),
)


@dataclass(frozen=True)
class RegisterInput:
    """One document as the guard accepted it."""

    path: Path
    doc_id: str
    sha256: str
    format: DocFormat
    sanitized: bool


def role_from_name(name: str) -> DocRole:
    tokens = [t for t in re.split(r"[^a-z0-9]+", Path(name).stem.lower()) if t]
    for role, words in ROLE_WORDS:
        if any(token.startswith(word) for token in tokens for word in words):
            return role
    return "main"


def _entry(
    item: RegisterInput, role: DocRole, precedence: int, parsers: ParserChoice
) -> DocumentEntry:
    return DocumentEntry(
        doc_id=item.doc_id,
        file=item.path.name,
        sha256=item.sha256,
        format=item.format,
        role=role,
        title=item.path.stem,
        precedence=precedence,
        sanitized=item.sanitized,
        parser=getattr(parsers, item.format),
    )


def _by_rules(items: Sequence[RegisterInput]) -> list[tuple[RegisterInput, DocRole]]:
    roles: list[tuple[RegisterInput, DocRole]] = []
    main_seen = False
    for item in sorted(items, key=lambda i: i.path.name):
        role = role_from_name(item.path.name)
        if role == "main":
            role = "annex" if main_seen else "main"
            main_seen = True
        roles.append((item, role))
    return roles


def _precedence(roles: list[tuple[RegisterInput, DocRole]]) -> dict[str, int]:
    """Addenda first, the latest name first; then the main document, annexes and forms."""
    ordered: list[RegisterInput] = []
    for role in ("addendum", "main", "annex", "form"):
        group = [item for item, r in roles if r == role]
        ordered += sorted(group, key=lambda i: i.path.name, reverse=role == "addendum")
    return {item.doc_id: number for number, item in enumerate(ordered, start=1)}


def build_register(
    source: Path, items: Sequence[RegisterInput], parsers: ParserChoice
) -> ControlRegister:
    """The register for a file or a package folder, before parsing."""
    package_file = source / PACKAGE_FILE if source.is_dir() else None
    if package_file is not None and package_file.exists():
        data = yaml.safe_load(package_file.read_text(encoding="utf-8")) or {}
        listed = {d["file"]: d for d in data.get("documents", [])}
        by_name = {item.path.name: item for item in items}
        entries = [
            _entry(by_name[name], spec["role"], int(spec["precedence"]), parsers)
            for name, spec in listed.items()
            if name in by_name
        ]
        rest = [item for item in items if item.path.name not in listed]
        start = max((e.precedence for e in entries), default=0)
        for offset, (item, role) in enumerate(_by_rules(rest), start=1):
            entries.append(_entry(item, role, start + offset, parsers))
        return ControlRegister(
            package=str(data.get("package") or source.name),
            documents=entries,
            precedence_source="package.yaml",
        )
    roles = _by_rules(items)
    numbers = _precedence(roles)
    entries = [_entry(item, role, numbers[item.doc_id], parsers) for item, role in roles]
    return ControlRegister(package=source.name, documents=entries, precedence_source="rules")
