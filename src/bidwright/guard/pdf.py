"""PDF: pikepdf opens the file, and an encrypted or unreadable file is refused. A pdfminer pass
then reads every character with its text render mode and fill color, through a subclass of
pdfminer's `PDFPageAggregator` whose `render_string` override records both for each character
it adds (C7-19). A character is hidden when its render mode is 3, its fill is within 0.05 of
white, its size is under 2 pt, or its box lies wholly outside the page's crop box. Hidden
characters are grouped into lines, and each line becomes one finding; visible characters from
2 pt up to, but not including, 6 pt become small-print boxes. Every box is given in
pdfplumber's top-left origin, for the parsers of step 7.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pikepdf
from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LTChar, LTContainer, LTItem
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.psexceptions import PSException

from bidwright.config import HiddenPdfRules, IngestConfig
from bidwright.guard.limits import PolicyBlocked, check_pages
from bidwright.guard.ooxml import Finding

# The kinds a character can be hidden by, in the order the guard tests them.
INVISIBLE, OFF_PAGE, BACKGROUND, TINY = (
    "pdf_invisible",
    "pdf_off_page",
    "pdf_background_color",
    "pdf_tiny_font",
)
SPACE_GAP = 0.3  # a gap wider than this share of the font size is a word break


@dataclass(frozen=True)
class HiddenChar:
    page: int
    x0: float
    top: float
    x1: float
    bottom: float
    text: str


@dataclass(frozen=True)
class SmallPrintBox:
    page: int
    x0: float
    top: float
    x1: float
    bottom: float


@dataclass(frozen=True)
class _Char:
    page: int
    x0: float
    top: float
    x1: float
    bottom: float
    size: float
    text: str
    kind: str | None  # the hidden kind, or None when the character is visible


@dataclass
class PdfScan:
    pages: int
    scanned: bool
    findings: list[Finding]
    hidden: list[HiddenChar]
    small_print: list[SmallPrintBox]
    small_print_chars: int


class _ModeAggregator(PDFPageAggregator):
    """Keeps, for each character it adds, the render mode and fill in force when it was drawn."""

    def __init__(self, manager: PDFResourceManager) -> None:
        super().__init__(manager, laparams=None)
        self.states: dict[int, tuple[int, Any]] = {}

    def render_string(self, textstate: Any, seq: Any, ncs: Any, graphicstate: Any) -> None:
        container = self.cur_item
        start = len(container._objs)
        super().render_string(textstate, seq, ncs, graphicstate)
        state = (textstate.render, graphicstate.ncolor)
        for item in container._objs[start:]:
            if isinstance(item, LTChar):
                self.states[id(item)] = state


def _characters(item: LTItem) -> Iterator[LTChar]:
    if isinstance(item, LTChar):
        yield item
    elif isinstance(item, LTContainer):
        for child in item:
            yield from _characters(child)


def is_white(fill: Any, tolerance: float) -> bool:
    """Gray and RGB at 1.0, or CMYK at 0.0, on every channel, within the tolerance."""
    if fill is None:
        return False
    values = fill if isinstance(fill, list | tuple) else (fill,)
    try:
        numbers = [float(value) for value in values]
    except (TypeError, ValueError):
        return False
    if len(numbers) == 4:
        return all(value <= tolerance for value in numbers)
    if len(numbers) in (1, 3):
        return all(value >= 1 - tolerance for value in numbers)
    return False


def _kind(
    char: LTChar, mode: int, fill: Any, crop: Sequence[float], rules: HiddenPdfRules
) -> str | None:
    if mode == rules.render_mode:
        return INVISIBLE
    x0, y0, x1, y1 = (float(v) for v in crop)
    if char.x1 <= x0 or char.x0 >= x1 or char.y1 <= y0 or char.y0 >= y1:
        return OFF_PAGE
    if is_white(fill, rules.white_tolerance):
        return BACKGROUND
    if char.size < rules.max_pt:
        return TINY
    return None


def _lines(chars: list[_Char], tolerance: float) -> list[list[_Char]]:
    """Characters of one page and kind whose tops lie within the tolerance share a line."""
    lines: list[list[_Char]] = []
    for char in sorted(chars, key=lambda c: (c.page, c.kind or "", c.top, c.x0)):
        last = lines[-1] if lines else None
        if (
            last is not None
            and last[0].page == char.page
            and last[0].kind == char.kind
            and abs(char.top - last[0].top) <= tolerance
        ):
            last.append(char)
        else:
            lines.append([char])
    return lines


def _line_text(line: list[_Char]) -> str:
    out: list[str] = []
    previous: _Char | None = None
    for char in sorted(line, key=lambda c: c.x0):
        gap = char.x0 - previous.x1 if previous is not None else 0.0
        if out and gap > SPACE_GAP * max(char.size, 1.0) and not out[-1].endswith(" "):
            out.append(" ")
        out.append(char.text)
        previous = char
    return "".join(out).strip()


def _box(line: list[_Char]) -> tuple[float, float, float, float]:
    return (
        min(c.x0 for c in line),
        min(c.top for c in line),
        max(c.x1 for c in line),
        max(c.bottom for c in line),
    )


def _read(path: Path, rules: HiddenPdfRules) -> list[_Char]:
    chars: list[_Char] = []
    with path.open("rb") as handle:
        manager = PDFResourceManager()
        device = _ModeAggregator(manager)
        interpreter = PDFPageInterpreter(manager, device)
        for number, page in enumerate(PDFPage.get_pages(handle), start=1):
            device.states.clear()
            interpreter.process_page(page)
            layout = device.get_result()
            for char in _characters(layout):
                mode, fill = device.states.get(id(char), (0, None))
                chars.append(
                    _Char(
                        page=number,
                        x0=char.x0,
                        top=layout.y1 - char.y1,
                        x1=char.x1,
                        bottom=layout.y1 - char.y0,
                        size=char.size,
                        text=char.get_text(),
                        kind=_kind(char, mode, fill, page.cropbox, rules),
                    )
                )
    return chars


def scan_pdf(path: Path, ingest: IngestConfig, label: str) -> PdfScan:
    try:
        with pikepdf.open(path) as pdf:
            if pdf.is_encrypted:
                raise PolicyBlocked(f"{label} is encrypted")
            pages = len(pdf.pages)
    except pikepdf.PasswordError as exc:
        raise PolicyBlocked(f"{label} is encrypted") from exc
    except pikepdf.PdfError as exc:
        raise PolicyBlocked(f"{label} cannot be read: {exc}") from exc
    check_pages(pages, ingest.limits, label)
    try:
        chars = _read(path, ingest.hidden_pdf)
    except (PSException, ValueError, KeyError) as exc:
        raise PolicyBlocked(f"{label} cannot be read: {exc}") from exc
    hidden = [c for c in chars if c.kind is not None]
    small = [
        c
        for c in chars
        if c.kind is None and ingest.small_print.min_pt <= c.size < ingest.small_print.max_pt
    ]
    findings = []
    for line in _lines(hidden, ingest.line_tolerance_pt):
        x0, top, x1, bottom = _box(line)
        location = f"page {line[0].page}, box ({x0:.1f}, {top:.1f}, {x1:.1f}, {bottom:.1f})"
        findings.append(Finding(line[0].kind or INVISIBLE, location, _line_text(line)))
    boxes = [
        SmallPrintBox(line[0].page, *_box(line)) for line in _lines(small, ingest.line_tolerance_pt)
    ]
    return PdfScan(
        pages=pages,
        scanned=len(chars) / max(pages, 1) < ingest.scanned.min_chars_per_page,
        findings=findings,
        hidden=[HiddenChar(c.page, c.x0, c.top, c.x1, c.bottom, c.text) for c in hidden],
        small_print=boxes,
        small_print_chars=len(small),
    )
