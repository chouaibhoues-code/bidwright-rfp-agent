"""Render a package: every document of a spec under `inputs/<package>/`, a `package.yaml` when
the package holds two or more documents, and each file's sha256 in `inputs/CORPUS.sha256`."""

import hashlib
from pathlib import Path

from evals.render.docx import render_docx
from evals.render.pdf import render_pdf
from evals.render.spec import REPO_ROOT, Document, Spec
from evals.render.xlsx import render_xlsx

INPUTS_DIR = REPO_ROOT / "inputs"
MANIFEST = INPUTS_DIR / "CORPUS.sha256"


def record_hash(path: Path, manifest: Path = MANIFEST) -> str:
    """Add or replace the file's line in the manifest, in `sha256sum` format, sorted by path."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    relative = path.relative_to(manifest.parent).as_posix()
    entries: dict[str, str] = {}
    if manifest.exists():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value, name = line.split(maxsplit=1)
                entries[name.strip()] = value
    entries[relative] = digest
    lines = "".join(f"{entries[name]}  {name}\n" for name in sorted(entries))
    manifest.write_text(lines, encoding="utf-8", newline="\n")
    return digest


def render_document(document: Document, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if document.format == "pdf":
        render_pdf(document, path)
    elif document.format == "docx":
        render_docx(document, path)
    else:
        render_xlsx(document, path)


def package_yaml(spec: Spec) -> str:
    """The package file the renderer writes: each document's role and precedence."""
    lines = [f"package: {spec.package}", "documents:"]
    for document in spec.documents:
        lines.append(
            f"  - {{file: {document.file}, role: {document.role},"
            f" precedence: {document.precedence}}}"
        )
    return "\n".join(lines) + "\n"


def render_package(
    spec: Spec, inputs_dir: Path = INPUTS_DIR, manifest: Path | None = None
) -> dict[str, str]:
    """Render every document, write the package file, and record the hashes.

    Returns each written file's path relative to `inputs_dir` with its sha256.
    """
    folder = inputs_dir / spec.package
    written: list[Path] = []
    for document in spec.documents:
        target = folder / document.file
        render_document(document, target)
        written.append(target)
    if len(spec.documents) > 1:
        target = folder / "package.yaml"
        target.write_text(package_yaml(spec), encoding="utf-8", newline="\n")
        written.append(target)
    manifest = manifest if manifest is not None else inputs_dir / "CORPUS.sha256"
    return {
        path.relative_to(inputs_dir).as_posix(): record_hash(path, manifest) for path in written
    }
