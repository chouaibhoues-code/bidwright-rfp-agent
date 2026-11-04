"""DOCX: content a reader of the document does not see is quarantined and removed from a
sanitized copy: hidden runs, tracked deletions, comments, alternative text, custom XML parts,
document-property text, field instructions and external relationships. Inserted text stays,
unwrapped so the parser reads it as plain runs, since a reader sees it.

A run is hidden when its own properties, its character style or its paragraph style, followed
through `basedOn` up to five levels, or the document defaults set `w:vanish`, `w:webHidden` or
`w:specVanish` to anything other than false. The scan covers every content part under
`word/`: the body, with its text boxes, the headers, footers, footnotes and endnotes.
"""

import re

from lxml import etree

from bidwright.guard.ooxml import (
    Finding,
    parse,
    read_parts,
    serialize,
    strip_external_relationships,
    write_parts,
)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
HIDING = ("vanish", "webHidden", "specVanish")
FALSE = frozenset({"false", "0", "off"})
BASED_ON_DEPTH = 5
CONTENT_ROOTS = frozenset({"document", "hdr", "ftr", "footnotes", "endnotes", "glossaryDocument"})
CUSTOM_XML = re.compile(r"^customXml/item\d+\.xml$")
PROPERTY_PARTS = ("docProps/core.xml", "docProps/app.xml", "docProps/custom.xml")
APP_TEXT_FIELDS = frozenset({"Company", "Manager", "HyperlinkBase"})
DATE_FIELDS = frozenset({"created", "modified", "lastPrinted", "revision"})
ANCHORS = ("commentRangeStart", "commentRangeEnd", "commentReference")

StyleTable = dict[str, tuple[bool | None, str | None]]


def _w(tag: str) -> str:
    return f"{{{W}}}{tag}"


def _local(element: etree._Element) -> str:
    return etree.QName(element).localname


def _hiding(rpr: etree._Element | None) -> bool | None:
    """True or False when the run properties set a hiding toggle, None when they set none."""
    if rpr is None:
        return None
    for name in HIDING:
        element = rpr.find(_w(name))
        if element is not None:
            return (element.get(_w("val")) or "true").lower() not in FALSE
    return None


def _styles(data: bytes | None, label: str) -> tuple[StyleTable, bool, str | None]:
    """Each style's own hiding setting and parent, whether the defaults hide text, and the id
    of the default paragraph style."""
    if data is None:
        return {}, False, None
    root = parse(data, label)
    table: StyleTable = {}
    default_paragraph = None
    for style in root.iter(_w("style")):
        style_id = style.get(_w("styleId"))
        if style_id is None:
            continue
        based = style.find(_w("basedOn"))
        parent = based.get(_w("val")) if based is not None else None
        table[style_id] = (_hiding(style.find(_w("rPr"))), parent)
        if style.get(_w("type")) == "paragraph" and style.get(_w("default")) in ("1", "true"):
            default_paragraph = style_id
    defaults = root.find(f"{_w('docDefaults')}/{_w('rPrDefault')}/{_w('rPr')}")
    return table, bool(_hiding(defaults)), default_paragraph


def _style_hides(style_id: str | None, table: StyleTable, depth: int = 0) -> bool | None:
    if style_id is None or style_id not in table or depth > BASED_ON_DEPTH:
        return None
    own, parent = table[style_id]
    return own if own is not None else _style_hides(parent, table, depth + 1)


def _run_hidden(
    run: etree._Element, paragraph_style: str | None, table: StyleTable, default: bool
) -> bool:
    rpr = run.find(_w("rPr"))
    direct = _hiding(rpr)
    if direct is not None:
        return direct
    character = rpr.find(_w("rStyle")) if rpr is not None else None
    if character is not None:
        by_character = _style_hides(character.get(_w("val")), table)
        if by_character is not None:
            return by_character
    by_paragraph = _style_hides(paragraph_style, table)
    return by_paragraph if by_paragraph is not None else default


def _remove(element: etree._Element) -> None:
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)


def _unwrap(element: etree._Element) -> None:
    """Replace the element by its children, in place."""
    parent = element.getparent()
    if parent is None:
        return
    index = parent.index(element)
    for offset, child in enumerate(list(element)):
        parent.insert(index + offset, child)
    parent.remove(element)


def _text(element: etree._Element, tag: str = "t") -> str:
    return "".join(node.text or "" for node in element.iter(_w(tag)))


def _scan_content(
    root: etree._Element,
    part: str,
    styles: tuple[StyleTable, bool, str | None],
    removed_rels: set[str],
) -> list[Finding]:
    table, default, default_paragraph = styles
    findings: list[Finding] = []
    for deleted in list(root.iter(_w("del"))):
        text = _text(deleted, "delText")
        if text.strip():
            findings.append(Finding("docx_deleted_revision", f"{part}, tracked deletion", text))
        _remove(deleted)
    for inserted in list(root.iter(_w("ins"))):
        parent = inserted.getparent()
        if parent is not None and _local(parent) != "rPr":
            _unwrap(inserted)
    for instruction in list(root.iter(_w("instrText"))):
        if (instruction.text or "").strip():
            findings.append(
                Finding("docx_field_instruction", f"{part}, field", instruction.text or "")
            )
        _remove(instruction)
    for simple in list(root.iter(_w("fldSimple"))):
        findings.append(
            Finding("docx_field_instruction", f"{part}, field", simple.get(_w("instr"), ""))
        )
        _unwrap(simple)
    for drawing in root.iter(f"{{{WP}}}docPr"):
        text = " ".join(v for v in (drawing.get("title"), drawing.get("descr")) if v)
        if text.strip():
            findings.append(
                Finding("docx_alt_text", f"{part}, drawing {drawing.get('id', '')}", text)
            )
        for attribute in ("title", "descr"):
            if attribute in drawing.attrib:
                del drawing.attrib[attribute]
    for link in list(root.iter(_w("hyperlink"))):
        if link.get(f"{{{R}}}id") in removed_rels:
            _unwrap(link)
    for name in ANCHORS:
        for anchor in list(root.iter(_w(name))):
            _remove(anchor)
    # The dict holds each paragraph element, so lxml hands back the same proxy for it below.
    paragraphs = {p: index for index, p in enumerate(root.iter(_w("p")), start=1)}
    hidden: dict[int, list[str]] = {}
    for run in list(root.iter(_w("r"))):
        paragraph = next(run.iterancestors(_w("p")), None)
        style_id = default_paragraph
        if paragraph is not None:
            pstyle = paragraph.find(f"{_w('pPr')}/{_w('pStyle')}")
            if pstyle is not None:
                style_id = pstyle.get(_w("val"))
        if _run_hidden(run, style_id, table, default):
            index = paragraphs.get(paragraph, 0) if paragraph is not None else 0
            hidden.setdefault(index, []).append(_text(run))
            _remove(run)
    for index, texts in sorted(hidden.items()):
        text = "".join(texts)
        if text.strip():
            findings.append(Finding("docx_hidden_run", f"{part}, paragraph {index}", text))
    return findings


def _scan_comments(root: etree._Element, part: str) -> list[Finding]:
    findings = []
    for comment in list(root.findall(_w("comment"))):
        text = _text(comment)
        author = comment.get(_w("author"), "")
        location = f"{part}, comment {comment.get(_w('id'), '')}" + (
            f" by {author}" if author else ""
        )
        if text.strip():
            findings.append(Finding("docx_comment", location, text))
        root.remove(comment)
    return findings


def _scan_properties(root: etree._Element, part: str) -> list[Finding]:
    findings = []
    if part == "docProps/app.xml":
        elements = [e for e in root if _local(e) in APP_TEXT_FIELDS]
    elif part == "docProps/custom.xml":
        elements = [v for prop in root for v in prop]
    else:
        elements = [e for e in root if not len(e)]
    for element in elements:
        text = (element.text or "").strip()
        if text and _local(element) not in DATE_FIELDS:
            name = _local(element)
            if part == "docProps/custom.xml":
                parent = element.getparent()
                name = parent.get("name", name) if parent is not None else name
            findings.append(Finding("docx_property", f"{part}, {name}", text))
            element.text = None
    return findings


def scan_docx(data: bytes, label: str) -> tuple[list[Finding], bytes]:
    """The hidden content of a DOCX, and the bytes of its sanitized copy."""
    parts = read_parts(data)
    findings, removed = strip_external_relationships(parts, label)
    styles = _styles(parts.get("word/styles.xml"), label)
    for part in sorted(parts):
        if not (part.startswith("word/") and part.endswith(".xml")):
            continue
        root = parse(parts[part], label)
        local = _local(root)
        if local in CONTENT_ROOTS:
            findings += _scan_content(root, part, styles, removed.get(part, set()))
        elif local == "comments":
            findings += _scan_comments(root, part)
        else:
            continue
        parts[part] = serialize(root)
    for part in sorted(p for p in parts if CUSTOM_XML.match(p)):
        root = parse(parts[part], label)
        text = " ".join(t.strip() for t in root.itertext() if t.strip())
        if text:
            findings.append(Finding("docx_custom_xml", part, text))
        parts[part] = serialize(etree.Element(root.tag, nsmap=root.nsmap))
    for part in PROPERTY_PARTS:
        if part in parts:
            root = parse(parts[part], label)
            findings += _scan_properties(root, part)
            parts[part] = serialize(root)
    return findings, write_parts(parts)
