"""The checks every input file passes before its content is read: its root, its size and its
format, known by its signature rather than its extension."""

import os
import zipfile
from dataclasses import dataclass
from pathlib import Path

from bidwright.config import FileLimits
from bidwright.schemas import DocFormat

CLIENT_ROOT_VARIABLE = "BIDWRIGHT_CLIENT_ROOT"
PDF_SIGNATURE = b"%PDF-"
ZIP_SIGNATURE = b"PK\x03\x04"
SIGNATURE_WINDOW = 1024  # a PDF header may follow up to this many bytes of junk


class PolicyBlocked(Exception):
    """The run must stop before any parser or prompt sees the files: a file broke a limit,
    lies outside its root, cannot be read, or has a format the guard does not know. The run
    records it as POLICY_BLOCKED with the reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Roots:
    """Where input files may live: corpus files under `input_root`, client documents under
    `client_root`, which lies outside the repository (D-05)."""

    input_root: Path
    client_root: Path | None
    repo_root: Path


def client_root_from_env() -> Path | None:
    value = os.environ.get(CLIENT_ROOT_VARIABLE, "").strip()
    return Path(value) if value else None


def check_root(path: Path, *, corpus: bool, roots: Roots, label: str) -> None:
    resolved = path.resolve()
    if corpus:
        if not resolved.is_relative_to(roots.input_root.resolve()):
            raise PolicyBlocked(f"{label} lies outside the allowed root {roots.input_root}")
        return
    if roots.client_root is None:
        raise PolicyBlocked(
            f"{label} is a client document, and {CLIENT_ROOT_VARIABLE} is not set: put client"
            " documents in a folder outside the repository and name it there"
        )
    client = roots.client_root.resolve()
    if client.is_relative_to(roots.repo_root.resolve()):
        raise PolicyBlocked(
            f"{CLIENT_ROOT_VARIABLE} lies inside the repository; client documents stay outside it"
        )
    if not resolved.is_relative_to(client):
        raise PolicyBlocked(f"{label} is a client document outside {CLIENT_ROOT_VARIABLE}")


def check_size(size: int, limits: FileLimits, label: str) -> None:
    if size > limits.file_mb * 1024 * 1024:
        raise PolicyBlocked(f"{label} is {size / 1024 / 1024:.1f} MB, over {limits.file_mb} MB")


def check_pages(pages: int, limits: FileLimits, label: str) -> None:
    if pages > limits.pages:
        raise PolicyBlocked(f"{label} has {pages} pages, over {limits.pages}")


def sniff_format(path: Path) -> DocFormat | None:
    """The format by signature: a PDF header, or a zip whose main part names the format."""
    with path.open("rb") as handle:
        head = handle.read(SIGNATURE_WINDOW)
    if PDF_SIGNATURE in head:
        return "pdf"
    if not head.startswith(ZIP_SIGNATURE):
        return None
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile:
        return None
    if "word/document.xml" in names:
        return "docx"
    if "xl/workbook.xml" in names:
        return "xlsx"
    return None
