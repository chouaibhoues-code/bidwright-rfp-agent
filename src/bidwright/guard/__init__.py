"""`guard`: the checks on raw input files before any parser or prompt sees them (Iteration 1,
step 6; ADR-020 and D-05).

Every file: its path resolves under its root, which is `inputs/` for a corpus file and
`BIDWRIGHT_CLIENT_ROOT`, outside the repository, for a client document; its size and page
count, and the package's file count, hold; and its format is known by its signature. A PDF is
scanned for hidden characters and small print, which the parsers of step 7 use. A DOCX or XLSX
is checked as an archive, its hidden content is quarantined, and a sanitized copy is saved
under `sanitized/` for the parser. A file with too little text per page is scanned and is not
parsed: if every file is, the run is refused with "no text layer". A refusal raises
`PolicyBlocked`, which the run records as POLICY_BLOCKED. `guard` writes `guard_report.json`
and `quarantine.jsonl`, and nothing else writes them.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from bidwright.config import Config
from bidwright.guard.docx import scan_docx
from bidwright.guard.limits import (
    PolicyBlocked,
    Roots,
    check_root,
    check_size,
    client_root_from_env,
    sniff_format,
)
from bidwright.guard.ooxml import Finding, check_archive
from bidwright.guard.pdf import HiddenChar, HiddenLine, SmallPrintBox, scan_pdf
from bidwright.guard.xlsx import scan_xlsx
from bidwright.ingest import doc_id_for, file_sha256
from bidwright.preflight import CORPUS_MANIFEST, HOME, corpus_entry
from bidwright.schemas import GuardFile, GuardReport, QuarantineRecord

__all__ = [
    "FileGuard",
    "GuardResult",
    "HiddenChar",
    "HiddenLine",
    "PolicyBlocked",
    "SmallPrintBox",
    "run_guard",
    "write_guard",
]


@dataclass
class FileGuard:
    """What the PDF parsers need from the guard: the hidden characters and small-print boxes."""

    hidden: list[HiddenChar] = field(default_factory=list)
    small_print: list[SmallPrintBox] = field(default_factory=list)
    hidden_lines: list[HiddenLine] = field(default_factory=list)


@dataclass
class GuardResult:
    report: GuardReport
    quarantine: list[QuarantineRecord]
    sanitized: dict[str, Path]  # by doc id: the sanitized copy the parser reads
    guards: dict[str, FileGuard]  # by doc id

    @property
    def degraded(self) -> list[str]:
        """The reasons the run continues DEGRADED: files left unparsed as scanned."""
        return [f"guard: scanned file {f.file} not parsed" for f in self.report.files if f.scanned]


def _record(number: int, doc_id: str, file: str, finding: Finding) -> QuarantineRecord:
    return QuarantineRecord.model_validate(
        {
            "id": f"QR-{number:04d}",
            "doc_id": doc_id,
            "file": file,
            "kind": finding.kind,
            "location": finding.location,
            "text": finding.text,
            "text_sha256": hashlib.sha256(finding.text.encode("utf-8")).hexdigest(),
            "chars": len(finding.text),
        }
    )


def run_guard(
    paths: Sequence[Path],
    run_dir: Path,
    config: Config,
    *,
    input_root: Path | None = None,
    client_root: Path | None = None,
    repo_root: Path = HOME,
    corpus_manifest: Path = CORPUS_MANIFEST,
    data_class: str | None = None,
) -> GuardResult:
    """Check and scan each file in order; raise `PolicyBlocked` on the first refusal.

    `data_class` is the run's, from the run entry: in a client package every file is a client
    file, for its root and its id, even one whose hash is in the corpus. With None, as in a
    replay, each file is classed by its own hash."""
    ingest = config.ingest
    if not paths:
        raise PolicyBlocked("no input files")
    if len(paths) > ingest.limits.files:
        raise PolicyBlocked(f"{len(paths)} files, over the limit of {ingest.limits.files}")
    roots = Roots(
        input_root=input_root or repo_root / ingest.input_root,
        client_root=client_root if client_root is not None else client_root_from_env(),
        repo_root=repo_root,
    )
    files: list[GuardFile] = []
    quarantine: list[QuarantineRecord] = []
    sanitized: dict[str, Path] = {}
    guards: dict[str, FileGuard] = {}
    small_print_chars = 0
    for path in paths:
        digest = file_sha256(path)
        corpus = (
            data_class == "synthetic"
            if data_class is not None
            else corpus_entry(digest, corpus_manifest) is not None
        )
        doc_id = doc_id_for(path, "synthetic" if corpus else "client", digest)
        label = path.name if corpus else doc_id  # a client file's name stays out of messages
        check_root(path, corpus=corpus, roots=roots, label=label)
        size = path.stat().st_size
        check_size(size, ingest.limits, label)
        fmt = sniff_format(path)
        if fmt is None:
            raise PolicyBlocked(f"{label}: unknown format")
        pages: int | None = None
        scanned = False
        if fmt == "pdf":
            scan = scan_pdf(path, ingest, label)
            pages, scanned, findings = scan.pages, scan.scanned, scan.findings
            guards[doc_id] = FileGuard(scan.hidden, scan.small_print, scan.hidden_lines)
            small_print_chars += scan.small_print_chars
        else:
            data = path.read_bytes()
            check_archive(data, ingest.archive, label)
            findings, clean = (scan_docx if fmt == "docx" else scan_xlsx)(data, label)
            target = run_dir / "sanitized" / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(clean)
            sanitized[doc_id] = target
        for finding in findings:
            quarantine.append(_record(len(quarantine) + 1, doc_id, path.name, finding))
        files.append(
            GuardFile(
                file=path.name,
                doc_id=doc_id,
                sha256=digest,
                format=fmt,
                bytes=size,
                pages=pages,
                scanned=scanned,
                accepted=not scanned,
                reason="no text layer: not parsed" if scanned else None,
            )
        )
    if all(f.scanned for f in files):
        raise PolicyBlocked("no text layer")
    report = GuardReport(
        files=files,
        quarantined=len(quarantine),
        small_print_chars=small_print_chars,
        limits={
            "file_mb": ingest.limits.file_mb,
            "pages": ingest.limits.pages,
            "files": ingest.limits.files,
            "archive_max_members": ingest.archive.max_members,
            "archive_max_ratio": ingest.archive.max_ratio,
            "archive_max_total_mb": ingest.archive.max_total_mb,
        },
    )
    result = GuardResult(report, quarantine, sanitized, guards)
    write_guard(result, run_dir)
    return result


def write_guard(result: GuardResult, run_dir: Path) -> None:
    """`guard_report.json` and `quarantine.jsonl`; guard is their only writer."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "guard_report.json").write_text(
        result.report.model_dump_json(indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    lines = "".join(record.model_dump_json() + "\n" for record in result.quarantine)
    (run_dir / "quarantine.jsonl").write_text(lines, encoding="utf-8", newline="\n")
