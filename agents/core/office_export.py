"""Local, data-only Word and spreadsheet exports."""

import re
from io import BytesIO
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

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
            document.add_paragraph("\n".join(paragraph))
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
            document.add_heading(heading.group(2), level=len(heading.group(1)))
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
                    document.add_paragraph(" | ".join(values))
            else:
                table = document.add_table(rows=len(values_by_row), cols=width)
                table.style = "Table Grid"
                for row_num, (table_row, values) in enumerate(zip(table.rows, values_by_row, strict=True)):
                    for cell, value in zip(table_row.cells, values, strict=False):
                        cell.text = value
                        if row_num == 0:
                            for run in cell.paragraphs[0].runs:
                                run.bold = True
            continue
        elif item:
            flush()
            if item.group(1):
                document.add_paragraph(item.group(3), style="List Bullet")
            else:
                document.add_paragraph(f"{item.group(2)}. {item.group(3)}")
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
                safe = escape(_OOXML_ESCAPE.sub("_x005F_", value)).replace("\r", "&#13;")
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
