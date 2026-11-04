"""What DOCX and XLSX share: the archive checks, a parser that resolves no entity and opens no
network connection, external relationships, and the rewrite of a sanitized archive."""

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from lxml import etree

from bidwright.config import ArchiveLimits
from bidwright.guard.limits import PolicyBlocked

REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
MACRO_PART = "vbaproject.bin"
LARGE_MEMBER = 1024 * 1024  # a member this large is also checked for its own ratio
_DRIVE = re.compile(r"^[A-Za-z]:")


@dataclass(frozen=True)
class Finding:
    """One piece of hidden content: its kind, where it was, and its text."""

    kind: str
    location: str
    text: str


def parser() -> etree.XMLParser:
    """An XML parser that resolves no entity, loads no DTD and opens no network connection."""
    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)


def parse(data: bytes, label: str) -> etree._Element:
    try:
        return etree.fromstring(data, parser())
    except etree.XMLSyntaxError as exc:
        raise PolicyBlocked(f"{label}: a part is not well-formed XML ({exc})") from exc


def serialize(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def check_archive(data: bytes, limits: ArchiveLimits, label: str) -> None:
    """Member count, expansion and ratio within limits; safe member paths; no macros."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise PolicyBlocked(f"{label}: unreadable archive") from exc
    with archive:
        members = archive.infolist()
        if len(members) > limits.max_members:
            raise PolicyBlocked(
                f"{label} has {len(members)} archive members, over {limits.max_members}"
            )
        total = sum(member.file_size for member in members)
        packed = sum(member.compress_size for member in members) or 1
        if total > limits.max_total_mb * 1024 * 1024:
            raise PolicyBlocked(f"{label} expands to {total / 1024 / 1024:.0f} MB, over the limit")
        if total / packed > limits.max_ratio:
            raise PolicyBlocked(f"{label} expands {total / packed:.0f} times, over the limit")
        for member in members:
            name = member.filename
            parts = PurePosixPath(name.replace("\\", "/")).parts
            if name.startswith(("/", "\\")) or _DRIVE.match(name) or ".." in parts:
                raise PolicyBlocked(f"{label} has an unsafe archive member path: {name}")
            if parts and parts[-1].lower() == MACRO_PART:
                raise PolicyBlocked(f"{label} holds a macro part ({name})")
            ratio = member.file_size / (member.compress_size or 1)
            if member.file_size > LARGE_MEMBER and ratio > limits.max_ratio:
                raise PolicyBlocked(f"{label}: member {name} expands {ratio:.0f} times")
        if "[Content_Types].xml" in archive.namelist():
            types = archive.read("[Content_Types].xml")
            if b"macroenabled" in types.lower():
                raise PolicyBlocked(f"{label} declares a macro-enabled content type")


def read_parts(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def write_parts(parts: dict[str, bytes]) -> bytes:
    """The parts as a new archive, in their original order."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return out.getvalue()


def strip_external_relationships(
    parts: dict[str, bytes], label: str
) -> tuple[list[Finding], dict[str, set[str]]]:
    """Quarantine and remove every relationship with TargetMode="External".

    Returns the findings and, for each part that owned a removed relationship, the removed ids.
    """
    findings: list[Finding] = []
    removed: dict[str, set[str]] = {}
    for name in [n for n in parts if n.endswith(".rels")]:
        root = parse(parts[name], label)
        changed = False
        for rel in root.findall(f"{{{REL_NS}}}Relationship"):
            if rel.get("TargetMode") == "External":
                rel_id = rel.get("Id", "")
                findings.append(
                    Finding(
                        "ooxml_external_relationship",
                        f"{name}, relationship {rel_id}",
                        rel.get("Target", ""),
                    )
                )
                owner = _owner_of(name)
                removed.setdefault(owner, set()).add(rel_id)
                root.remove(rel)
                changed = True
        if changed:
            parts[name] = serialize(root)
    return findings, removed


def _owner_of(rels_name: str) -> str:
    """`word/_rels/document.xml.rels` belongs to `word/document.xml`."""
    path = PurePosixPath(rels_name)
    return str(path.parent.parent / path.name.removesuffix(".rels"))
