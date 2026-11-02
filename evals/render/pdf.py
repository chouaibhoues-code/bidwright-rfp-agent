"""Render a corpus spec to PDF with ReportLab.

Output is reproducible: invariant mode fixes the dates and document id, so the same spec
always gives the same bytes and the hash in `inputs/CORPUS.sha256` stays valid. Text uses the
standard Helvetica fonts, without hyphenation or ligatures, so every clause can be found again
in the extracted text.
"""

from collections.abc import Callable
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Flowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from evals.render.spec import Clause, ListBlock, Para, Section, Spec, TableBlock, Text

MARGIN = 2.5 * cm
PAGE_WIDTH, PAGE_HEIGHT = A4


def _styles(font_size: float) -> dict[str, ParagraphStyle]:
    body = ParagraphStyle(
        "Body", fontName="Helvetica", fontSize=font_size, leading=font_size * 1.35, spaceAfter=6
    )
    return {
        "body": body,
        "item": ParagraphStyle("Item", parent=body, leftIndent=18, spaceAfter=3),
        "h1": ParagraphStyle(
            "H1",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=font_size * 1.3,
            leading=font_size * 1.7,
            spaceBefore=10,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=font_size * 1.2,
            leading=font_size * 1.6,
            spaceBefore=6,
        ),
        "title": ParagraphStyle(
            "Title", parent=body, fontName="Helvetica-Bold", fontSize=20, leading=26
        ),
    }


def _section(section: Section) -> list[Flowable]:
    styles = _styles(section.layout.font_size)
    story: list[Flowable] = [PageBreak()] if section.page_break_before else []
    story.append(Paragraph(escape(section.heading), styles[f"h{section.level}"]))
    for block in section.blocks:
        if isinstance(block, Text | Clause):
            story.append(Paragraph(escape(block.text), styles["body"]))
        elif isinstance(block, Para):
            text = " ".join(part if isinstance(part, str) else part.text for part in block.para)
            story.append(Paragraph(escape(text), styles["body"]))
        elif isinstance(block, ListBlock):
            story.append(Paragraph(escape(block.list.lead_in), styles["body"]))
            story += [Paragraph(escape(item.text), styles["item"]) for item in block.list.items]
        elif isinstance(block, TableBlock):
            table = Table([block.table.header, *block.table.rows], hAlign="LEFT")
            table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 0), (-1, -1), section.layout.font_size),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story += [table, Spacer(1, 6)]
    return story


def _page_decoration(header: str) -> Callable[[Canvas, SimpleDocTemplate], None]:
    """The same header on every page, and a page number in the footer."""

    def draw(canvas: Canvas, doc: SimpleDocTemplate) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawString(MARGIN, PAGE_HEIGHT - 1.5 * cm, header)
        canvas.drawRightString(PAGE_WIDTH - MARGIN, 1.5 * cm, f"Page {doc.page}")
        canvas.restoreState()

    return draw


def render_pdf(spec: Spec, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=spec.title,
        author="Bidwright synthetic corpus",
        subject=spec.notice,
        creator="evals/render/pdf.py",
        invariant=1,
    )
    styles = _styles(spec.sections[0].layout.font_size)
    story: list[Flowable] = [Paragraph(escape(spec.title), styles["title"])]
    story += [Paragraph(escape(line), styles["body"]) for line in spec.subtitle]
    story += [Paragraph(escape(spec.notice), styles["body"]), Spacer(1, 12)]
    for section in spec.sections:
        story += _section(section)
    decorate = _page_decoration(spec.header)
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
