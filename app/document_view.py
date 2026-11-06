"""The run's input documents in the pages (ADR-053): a PDF page as an image, with a quote
highlighted where it stands, so a person checks a record against the page it came from.

A run names its input in `run_args["source"]` (a file, or a package folder) and lists each
document it read, with its hash, in the manifest's `documents`; a run made before `run_args`
existed is matched to a file under `inputs/` by name and hash. Only PDFs render; a DOCX or
XLSX document is shown through its passages' text. The images are made in memory and cached;
nothing is written.
"""

import hashlib
import io
from pathlib import Path

import pdfplumber
import streamlit as st

from app.data import RunData
from bidwright.preflight import HOME

RESOLUTION = 110
HIGHLIGHT = (255, 200, 0, 90)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_files(data: RunData) -> list[Path]:
    """The run's input files, in the order the manifest lists its documents."""
    source = str(data.manifest.run_args.get("source") or "")
    candidates: list[Path] = []
    if source:
        path = Path(source) if Path(source).is_absolute() else HOME / source
        candidates = sorted(path.iterdir()) if path.is_dir() else [path]
    found: list[Path] = []
    for document in data.manifest.documents:
        match = next((c for c in candidates if c.name == document.file and c.is_file()), None)
        if match is None:  # a run made before run_args: find the file by name and hash
            match = next(
                (
                    p
                    for p in sorted((HOME / "inputs").rglob(document.file))
                    if p.is_file() and _sha256(p) == document.sha256
                ),
                None,
            )
        if match is not None:
            found.append(match)
    return found or [c for c in candidates if c.is_file()]


def is_pdf(path: Path) -> bool:
    return path.suffix.lower() == ".pdf"


@st.cache_data(show_spinner=False)
def page_count(path: str) -> int:
    with pdfplumber.open(path) as pdf:
        return len(pdf.pages)


@st.cache_data(show_spinner=False)
def locate(path: str, quote: str) -> tuple[int, str] | None:
    """The page that holds `quote`, searched whole, then by its first 8 and 5 words, since a
    quote that wraps across lines may not match whole; the page index and the words found."""
    words = quote.split()
    if not words:
        return None
    with pdfplumber.open(path) as pdf:
        for n in dict.fromkeys((len(words), 8, 5)):
            probe = " ".join(words[:n])
            for index, page in enumerate(pdf.pages):
                if page.search(probe, regex=False):
                    return index, probe
    return None


@st.cache_data(show_spinner=False)
def render_page(path: str, index: int, probe: str = "") -> bytes:
    """One page as PNG bytes, with `probe` highlighted wherever it stands on the page."""
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[index]
        image = page.to_image(resolution=RESOLUTION)
        if probe:
            hits = page.search(probe, regex=False)
            if hits:
                image.draw_rects(hits, fill=HIGHLIGHT, stroke=(230, 120, 0), stroke_width=2)
        out = io.BytesIO()
        image.annotated.save(out, format="PNG")
        return out.getvalue()


def show_quote_on_page(data: RunData, quote: str) -> bool:
    """Show the input page that holds `quote`, highlighted; False when no PDF holds it."""
    for path in (p for p in source_files(data) if is_pdf(p)):
        found = locate(str(path), quote)
        if found is None:
            continue
        index, probe = found
        st.text(f"{path.name}, page {index + 1} of {page_count(str(path))}:")
        st.image(render_page(str(path), index, probe), width="stretch")
        return True
    return False


def document_browser(data: RunData) -> None:
    """Every input document of the run: a PDF page by page, other formats by their passages."""
    files = source_files(data)
    if not files:
        st.text("The run's input files are not under inputs/ on this machine.")
        return
    names = [p.name for p in files]
    if st.session_state.get("run_doc") not in names:
        st.session_state["run_doc"] = names[0]
    st.selectbox("Document", names, key="run_doc")
    path = files[names.index(st.session_state["run_doc"])]
    if not is_pdf(path):
        st.text(
            f"{path.name} is a {path.suffix} file, which does not render here; its text is in"
            " the Requirements tab's passages and in the run's frozen.txt."
        )
        return
    total = page_count(str(path))
    st.number_input("Page", min_value=1, max_value=total, step=1, key="run_page")
    index = min(int(st.session_state.get("run_page") or 1), total) - 1
    st.text(f"{path.name}, page {index + 1} of {total}")
    st.image(render_page(str(path), index), width="stretch")


__all__ = ["document_browser", "locate", "render_page", "show_quote_on_page", "source_files"]
