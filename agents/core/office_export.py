"""Local, data-only Word and spreadsheet exports."""

import re
import tempfile
from html import escape
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, ZipFile

from agents.core.archive_safe import ArchiveLimits, ArchiveRejected, extract_zip_bytes

WORD_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
EXCEL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
_LIST = re.compile(r"^\s*(?:([-*+])|(\d+)\.)\s+(.+)$")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?")
_OOXML_ESCAPE = re.compile(r"_(?=[xX][0-9A-Fa-f]{4}_)")


def _valid_xml(text: str) -> bool:
    return all(char in "\t\n\r" or 0x20 <= ord(char) <= 0xD7FF
               or 0xE000 <= ord(char) <= 0xFFFD
               or 0x10000 <= ord(char) <= 0x10FFFF for char in text)


def _cells(line: str) -> list[str]:
    return [part.strip() for part in line.strip().strip("|").split("|")]


def _add_inline_strong(paragraph, text: str) -> None:
    # shortcut: only inline **strong** is styled; extend here if more Markdown styles are needed.
    if "**" not in text:
        paragraph.add_run(text)
        return
    code_ends = {}
    next_tick = {}
    for match in reversed(list(re.finditer(r"`+", text))):
        width = match.end() - match.start()
        if width in next_tick:
            code_ends[match.start()] = next_tick[width]
        next_tick[width] = match.end()
    plain: list[str] = []
    pending: list[str] | None = None
    runs: list[tuple[str, bool]] = []
    index = 0
    while index < len(text):
        if text.startswith("\\**", index):
            (pending if pending is not None else plain).append("**")
            index += 3
        elif text.startswith("\\`", index) and index + 1 in code_ends:
            (pending if pending is not None else plain).append("`")
            index += 2
        elif index in code_ends:
            end = code_ends[index]
            (pending if pending is not None else plain).append(text[index:end])
            index = end
        elif text.startswith("**", index):
            if pending is None:
                pending = []
            else:
                strong = "".join(pending)
                if strong and not strong[0].isspace() and not strong[-1].isspace():
                    if plain:
                        runs.append(("".join(plain), False))
                        plain = []
                    runs.append((strong, True))
                    pending = None
                else:
                    plain.extend(["**", *pending])
                    pending = []
            index += 2
        else:
            (pending if pending is not None else plain).append(text[index])
            index += 1
    if pending is not None:
        plain.extend(["**", *pending])
    if plain:
        runs.append(("".join(plain), False))
    for value, strong in runs:
        paragraph.add_run(value).bold = True if strong else None


def create_docx(text: str) -> bytes:
    """Build a readable Word document from bounded plain or simple Markdown text."""
    if not isinstance(text, str) or not text or len(text) > 65536 or not _valid_xml(text):
        raise ValueError("invalid document text")

    from docx import Document
    from docx.shared import Pt

    document = Document()
    lines = text.splitlines()
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            _add_inline_strong(document.add_paragraph(), "\n".join(paragraph))
            paragraph.clear()

    index = 0
    while index < len(lines):
        line = lines[index]
        heading = _HEADING.match(line)
        item = _LIST.match(line)
        fence = re.match(r"^\s*(`{3,})", line)
        if not line.strip():
            flush()
        elif fence:
            flush()
            code = []
            index += 1
            while index < len(lines) and not (set(lines[index].strip()) == {"`"}
                                               and len(lines[index].strip()) >= len(fence.group(1))):
                code.append(lines[index])
                index += 1
            run = document.add_paragraph().add_run("\n".join(code))
            run.font.name = "Consolas"
            run.font.size = Pt(9)
        elif heading:
            flush()
            _add_inline_strong(document.add_heading(level=len(heading.group(1))), heading.group(2))
        elif index + 1 < len(lines) and "|" in line and _TABLE_RULE.match(lines[index + 1]):
            flush()
            headers = _cells(line)
            index += 2
            body = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                body.append(_cells(lines[index]))
                index += 1
            values_by_row = [headers, *body]
            width = max(map(len, values_by_row))
            if width > 64 or width * len(values_by_row) > 4096:
                for values in values_by_row:
                    _add_inline_strong(document.add_paragraph(), " | ".join(values))
            else:
                table = document.add_table(rows=len(values_by_row), cols=width)
                table.style = "Table Grid"
                for row_num, (table_row, values) in enumerate(zip(table.rows, values_by_row, strict=True)):
                    for cell, value in zip(table_row.cells, values, strict=False):
                        _add_inline_strong(cell.paragraphs[0], value)
                        if row_num == 0:
                            for run in cell.paragraphs[0].runs:
                                run.bold = True
            continue
        elif item:
            flush()
            if item.group(1):
                _add_inline_strong(document.add_paragraph(style="List Bullet"), item.group(3))
            else:
                _add_inline_strong(document.add_paragraph(), f"{item.group(2)}. {item.group(3)}")
        else:
            paragraph.append(line)
        index += 1
    flush()
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _number(text: str) -> bool:
    # Excel retains at most 15 significant decimal digits; keep everything else as text.
    return (len(text) <= 18 and bool(_NUMBER.fullmatch(text))
            and len(text.lstrip("-").replace(".", "").lstrip("0")) <= 15
            and text != "-0")


def create_xlsx(rows: list[list[str]]) -> bytes:
    """Build a single-sheet XLSX, keeping ambiguous values and formulas as text."""
    if (not isinstance(rows, list) or not rows or len(rows) > 1001
            or any(not isinstance(row, list) or not row or len(row) > 64 for row in rows)):
        raise ValueError("invalid worksheet shape")
    total = 0
    for row in rows:
        for value in row:
            if (not isinstance(value, str) or len(value) > 32767 or not _valid_xml(value)
                    or len(value.encode("utf-16-le")) > 32767 * 2):
                raise ValueError("invalid cell text")
            total += len(value)
            if total > 100000:
                raise ValueError("worksheet text limit exceeded")

    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    package_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    office_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    cells = []
    widths = [10] * max(map(len, rows))
    for row_num, row in enumerate(rows, 1):
        columns = []
        for col_num, value in enumerate(row):
            widths[col_num] = max(widths[col_num], min(40, len(value) + 2))
            ref = f"{chr(65 + col_num) if col_num < 26 else chr(64 + col_num // 26) + chr(65 + col_num % 26)}{row_num}"
            if _number(value):
                columns.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                safe = escape(_OOXML_ESCAPE.sub("_x005F_", value), quote=False).replace("\r", "&#13;")
                columns.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{safe}</t></is></c>')
        cells.append(f'<row r="{row_num}">{"".join(columns)}</row>')
    column_xml = "".join(f'<col min="{number}" max="{number}" width="{width}" customWidth="1"/>'
                         for number, width in enumerate(widths, 1))

    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>'),
        "_rels/.rels": (
            f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{package_ns}">'
            f'<Relationship Id="rId1" Type="{office_ns}/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>'),
        "xl/workbook.xml": (
            f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="{namespace}" xmlns:r="{office_ns}">'
            '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'),
        "xl/_rels/workbook.xml.rels": (
            f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{package_ns}">'
            f'<Relationship Id="rId1" Type="{office_ns}/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>'),
        "xl/worksheets/sheet1.xml": (
            f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{namespace}">'
            f'<cols>{column_xml}</cols><sheetData>{"".join(cells)}</sheetData></worksheet>'),
    }
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content.encode("utf-8"))
    return output.getvalue()


_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_CELL_ADDRESS = re.compile(r"([A-Z]{1,3})([1-9][0-9]{0,6})\Z")
_EDIT_LIMITS = ArchiveLimits(max_members=512, max_bytes=32 * 1024 * 1024)
_MAX_EDIT_INPUT = 8 * 1024 * 1024
_MAX_XML_PART = 8 * 1024 * 1024
_MAX_XML_NODES = 200_000
_MAX_XML_DEPTH = 128


def _edit_xml(data: bytes):
    if len(data) > _MAX_XML_PART:
        raise ValueError("Office XML part is too large to edit")
    from lxml import etree as ET

    try:
        parser = ET.XMLParser(resolve_entities=False, load_dtd=False, no_network=True,
                              recover=False, huge_tree=False, remove_comments=False, remove_pis=False)
        root = ET.fromstring(data, parser=parser)
    except Exception as exc:
        raise ValueError("Office XML is malformed or unsafe") from exc
    if root.getroottree().docinfo.doctype:
        raise ValueError("Office XML DTD declarations are not allowed")
    count = 0
    stack = [(root, 1)]
    while stack:
        node, depth = stack.pop()
        if not isinstance(node.tag, str):
            continue  # XML comments and processing instructions are not elements.
        count += 1
        if count > _MAX_XML_NODES or depth > _MAX_XML_DEPTH:
            raise ValueError("Office XML is too complex to edit")
        stack.extend((child, depth + 1) for child in node)
    return root


def _xml_bytes(root) -> bytes:
    from lxml import etree as ET

    return ET.tostring(root.getroottree(), encoding="utf-8", xml_declaration=True)


def _edit_package(data: bytes, kind: str) -> dict[str, bytes]:
    if type(data) is not bytes or not data.startswith(b"PK\x03\x04") or len(data) > _MAX_EDIT_INPUT:
        raise ValueError("Supply a bounded DOCX or XLSX file")
    try:
        with tempfile.TemporaryDirectory(prefix="nerva-office-edit-") as temporary:
            root = Path(temporary)
            names = extract_zip_bytes(data, root, limits=_EDIT_LIMITS)
            parts = {"/".join(name): (root.joinpath(*name)).read_bytes()
                     for name in names if (root.joinpath(*name)).is_file()}
    except (ArchiveRejected, OSError) as exc:
        raise ValueError("Office package is malformed or unsafe") from exc
    if ("[Content_Types].xml" not in parts or "_rels/.rels" not in parts
            or (kind == "docx" and "word/document.xml" not in parts)
            or (kind == "xlsx" and ("xl/workbook.xml" not in parts
                                    or "xl/_rels/workbook.xml.rels" not in parts))):
        raise ValueError("Office package is missing required parts")
    types = None
    for name, content in parts.items():
        lower = name.lower()
        if ("vbaproject" in lower or "activex" in lower or "embedding" in lower
                or "externallink" in lower or "_xmlsignatures" in lower or lower.endswith(".bin")):
            raise ValueError("Office active content cannot be edited safely")
        xml_root = _edit_xml(content) if lower.endswith((".xml", ".rels")) else None
        if name == "[Content_Types].xml":
            types = xml_root
        if lower.endswith(".rels"):
            rels = xml_root
            if rels.tag != f"{{{_PACKAGE_REL_NS}}}Relationships":
                raise ValueError("Office relationships are malformed")
            for relation in rels:
                if not isinstance(relation.tag, str):
                    continue
                if relation.tag != f"{{{_PACKAGE_REL_NS}}}Relationship":
                    raise ValueError("Office relationships are malformed")
                target = relation.get("Target", "")
                mode = relation.get("TargetMode", "").lower()
                if mode not in ("", "internal", "external"):
                    raise ValueError("Office relationships are malformed")
                external = mode == "external"
                if external:
                    uri = urlsplit(target)
                    passive = (relation.get("Type") == f"{_OFFICE_REL_NS}/hyperlink"
                               and uri.scheme in ("http", "https", "mailto")
                               and bool(uri.netloc if uri.scheme in ("http", "https") else uri.path)
                               and not any(char in target for char in "\r\n\x00"))
                    if passive:
                        continue
                if external or ":" in target or target.startswith(("//", "\\\\")):
                    raise ValueError("Office package has an external relationship")
    if types.tag != "{http://schemas.openxmlformats.org/package/2006/content-types}Types":
        raise ValueError("Office package has invalid content types")
    overrides = []
    for part in types:
        if not isinstance(part.tag, str):
            continue
        if part.tag == "{http://schemas.openxmlformats.org/package/2006/content-types}Override":
            overrides.append(part)
        elif part.tag != "{http://schemas.openxmlformats.org/package/2006/content-types}Default":
            raise ValueError("Office package has invalid content types")
        content_type = part.get("ContentType")
        if not content_type:
            raise ValueError("Office package has invalid content types")
        if any(marker in content_type.casefold() for marker in
               ("macroenabled", "activex", "oleobject", "vbaproject")):
            raise ValueError("Office active content cannot be edited safely")
    declared = {part.get("PartName"): part.get("ContentType") for part in overrides}
    main = ("/word/document.xml" if kind == "docx" else "/xl/workbook.xml")
    expected = ("application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
                if kind == "docx" else
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml")
    if declared.get(main) != expected or sum(part.get("PartName") == main for part in overrides) != 1:
        raise ValueError("Office package declares the wrong document type")
    return parts


def _write_edited_package(parts: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return output.getvalue()


def _replace_docx(parts: dict[str, bytes], target: str, replacement: str) -> None:
    root = _edit_xml(parts["word/document.xml"])
    paragraph_tag = f"{{{_WORD_NS}}}p"
    text_tag = f"{{{_WORD_NS}}}t"
    hit = None
    for paragraph in root.iter(paragraph_tag):
        nodes = list(paragraph.iter(text_tag))
        joined = "".join(node.text or "" for node in nodes)
        at = joined.find(target)
        if at >= 0:
            if hit is not None or joined.find(target, at + 1) >= 0:
                raise ValueError("Select a unique text match in one document paragraph")
            hit = (paragraph, nodes, at)
    if hit is None:
        raise ValueError("Select a unique text match in one document paragraph")
    paragraph, nodes, at = hit
    for child in paragraph:
        if child.tag == f"{{{_WORD_NS}}}pPr":
            continue
        if child.tag != f"{{{_WORD_NS}}}r" or any(
                node.tag not in (f"{{{_WORD_NS}}}rPr", text_tag) for node in child):
            raise ValueError("Selected paragraph contains non-text content")
    stop = at + len(target)
    cursor = 0
    inserted = False
    for node in nodes:
        text = node.text or ""
        end = cursor + len(text)
        if end > at and cursor < stop:
            left = text[:max(0, at - cursor)]
            right = text[max(0, stop - cursor):]
            node.text = left + (replacement if not inserted else "") + right
            inserted = True
            if node.text and (node.text[0].isspace() or node.text[-1].isspace()):
                node.set(_XML_SPACE, "preserve")
        cursor = end
    parts["word/document.xml"] = _xml_bytes(root)


def _address(value: str) -> tuple[int, int]:
    match = _CELL_ADDRESS.fullmatch(value.upper()) if isinstance(value, str) else None
    if match is None:
        raise ValueError("Select an A1 cell address")
    column = 0
    for char in match.group(1):
        column = column * 26 + ord(char) - 64
    row = int(match.group(2))
    if column > 16_384 or row > 1_048_576:
        raise ValueError("Cell address is outside the worksheet")
    return column, row


def _sheet_part(parts: dict[str, bytes], sheet: str | None) -> str:
    workbook = _edit_xml(parts["xl/workbook.xml"])
    sheets = list(workbook.iter(f"{{{_SHEET_NS}}}sheet"))
    selected = [row for row in sheets if row.get("name") == sheet] if sheet is not None else sheets
    if len(selected) != 1:
        raise ValueError("Select one existing sheet by name")
    relation_id = selected[0].get(f"{{{_OFFICE_REL_NS}}}id")
    rels = _edit_xml(parts["xl/_rels/workbook.xml.rels"])
    matches = [rel for rel in rels.iter(f"{{{_PACKAGE_REL_NS}}}Relationship")
               if rel.get("Id") == relation_id and rel.get("Type") == f"{_OFFICE_REL_NS}/worksheet"]
    if len(matches) != 1:
        raise ValueError("Selected sheet has no safe worksheet part")
    target = matches[0].get("Target", "")
    if target.startswith("/xl/"):
        name = target[1:]
    elif target and not target.startswith("/") and ".." not in target.split("/"):
        name = "xl/" + target
    else:
        raise ValueError("Selected sheet has no safe worksheet part")
    if name not in parts or not name.startswith("xl/worksheets/"):
        raise ValueError("Selected sheet has no safe worksheet part")
    return name


def _replace_xlsx(parts: dict[str, bytes], target: str, replacement: str,
                  sheet: str | None) -> None:
    from lxml import etree as ET

    column, row = _address(target)
    address = target.upper()
    name = _sheet_part(parts, sheet)
    root = _edit_xml(parts[name])
    cell_tag = f"{{{_SHEET_NS}}}c"
    matches = [cell for cell in root.iter(cell_tag) if cell.get("r") == address]
    if len(matches) != 1:
        raise ValueError("Select one existing cell")
    for merged in root.iter(f"{{{_SHEET_NS}}}mergeCell"):
        endpoints = (merged.get("ref") or "").split(":")
        if len(endpoints) != 2:
            raise ValueError("Worksheet has an unsafe merged range")
        first, last = _address(endpoints[0]), _address(endpoints[1])
        if first[0] <= column <= last[0] and first[1] <= row <= last[1]:
            raise ValueError("Merged cells cannot be edited safely")
    for formula in root.iter(f"{{{_SHEET_NS}}}f"):
        if formula.get("t") in ("shared", "array", "dataTable"):
            raise ValueError("Shared or array formulas cannot be edited safely")
    cell = matches[0]
    if set(cell.attrib) - {"r", "s", "t"} or any(
            child.tag not in (f"{{{_SHEET_NS}}}v", f"{{{_SHEET_NS}}}is") for child in cell):
        raise ValueError("Formula or structured cell cannot be edited safely")
    if cell.find(f"{{{_SHEET_NS}}}is/{{{_SHEET_NS}}}r") is not None:
        raise ValueError("Rich text cell cannot be edited safely")
    for child in list(cell):
        cell.remove(child)
    if _number(replacement):
        cell.attrib.pop("t", None)
        ET.SubElement(cell, f"{{{_SHEET_NS}}}v").text = replacement
    else:
        cell.set("t", "inlineStr")
        inline = ET.SubElement(cell, f"{{{_SHEET_NS}}}is")
        text = ET.SubElement(inline, f"{{{_SHEET_NS}}}t")
        text.set(_XML_SPACE, "preserve")
        text.text = _OOXML_ESCAPE.sub("_x005F_", replacement)
    parts[name] = _xml_bytes(root)


def edit_office(data: bytes, kind: str, target: str, replacement: str,
                sheet: str | None = None) -> bytes:
    """Edit one exact DOCX paragraph match or one XLSX cell in a bounded OOXML package."""
    if kind not in ("docx", "xlsx"):
        raise ValueError("Choose docx or xlsx")
    if (not isinstance(replacement, str) or not _valid_xml(replacement)
            or (kind == "docx" and (len(replacement) > 65_536
                                   or any(char in replacement for char in "\t\n\r")))
            or (kind == "xlsx" and (len(replacement) > 32_767
                                   or len(replacement.encode("utf-16-le")) > 65_534))):
        raise ValueError("Replacement text is invalid or too long")
    if kind == "docx" and (not isinstance(target, str) or not target or len(target) > 8_192
                            or sheet is not None):
        raise ValueError("Select text in one document paragraph")
    if kind == "xlsx" and sheet is not None and (not isinstance(sheet, str) or not sheet):
        raise ValueError("Select one existing sheet by name")
    parts = _edit_package(data, kind)
    if kind == "docx":
        _replace_docx(parts, target, replacement)
    else:
        _replace_xlsx(parts, target, replacement, sheet)
    return _write_edited_package(parts)
