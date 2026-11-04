"""The package path of step 7, end to end on the corpus, with Docling replayed from cassettes:
guard, register, parse and ingest, as the graph will run them from step 16."""

from pathlib import Path

from bidwright.config import Config, compile_patterns, load_config
from bidwright.guard import run_guard
from bidwright.ingest import IngestResult, ingest_package
from bidwright.parsers import ParsedDocument
from bidwright.parsers.docling_client import DoclingClient
from bidwright.parsers.docling_parser import DoclingParser
from bidwright.preflight import HOME, package_documents
from bidwright.register import RegisterInput, build_register

INPUTS = HOME / "inputs"
DEV_PDF = INPUTS / "dev" / "dev_rfp.pdf"
DEV_DOCX = INPUTS / "dev-docx" / "dev_docx_rfp.docx"
HERO = INPUTS / "hero"
HIDDEN_MARKERS = (
    "ZX-78-BIRCH",
    "ZX-61-BRAMBLE",
    "ZX-62-CLOVER",
    "ZX-42-ROWAN",
    "ZX-43-SORREL",
    "ZX-44-TANSY",
    "ZX-45-UMBER",
    "ZX-46-VETCH",
    "ZX-47-WILLOW",
    "ZX-48-YARROW",
    "ZX-49-ZINNIA",
    "ZX-50-ALDER",
)
VISIBLE_MARKERS = ("ZX-77-ASPEN", "ZX-41-QUILL")


def parse_package(
    source: Path, run_dir: Path, config: Config | None = None
) -> tuple[list[ParsedDocument], IngestResult]:
    config = config or load_config()
    paths = package_documents(source) if source.is_dir() else [source]
    guard = run_guard(paths, run_dir, config)
    items = [
        RegisterInput(
            path, entry.doc_id, entry.sha256, entry.format, entry.doc_id in guard.sanitized
        )
        for path, entry in zip(paths, guard.report.files, strict=True)
        if entry.format is not None
    ]
    register = build_register(source, items, config.ingest.parsers)
    parser = DoclingParser(DoclingClient.from_config(config, "replay"))
    parsed = [
        parser.parse(
            guard.sanitized.get(item.doc_id, item.path), item.doc_id, guard.guards.get(item.doc_id)
        )
        for item in items
    ]
    suspect = compile_patterns(config.ingest.suspect_patterns, "config/ingest.yaml")
    return parsed, ingest_package(register, parsed, run_dir, suspect)
