"""Real, small sample documents for the workspace knowledge-base tests (Romanian text).

The committed files next to this module are what an office actually uploads:
``regulament-intern.pdf`` (two pages, written by :func:`build_pdf`),
``politica-concedii.md``, ``note-sedinta.txt``, ``contacte-cp1250.csv`` (legacy Windows
code page, ``;`` delimiter) and ``vanzari-utf8-bom.csv`` (Excel's "CSV UTF-8").

DOCX and XLSX packages and PDF variants (encrypted, very long, image-only) are built
in code by the helpers below, so each test states exactly what the file contains.
The PDF writer emits a standard Type 1 font with a ``ToUnicode`` map, the way Word and
LibreOffice exports carry Romanian letters, so extraction yields the exact characters.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Sequence
from pathlib import Path

HERE = Path(__file__).resolve().parent

PDF_PAGES: list[list[str]] = [
    ["Regulament intern - Acme SRL",
     "Angajații au dreptul la 21 de zile de concediu de odihnă pe an.",
     "Cererea de concediu se depune cu cel puțin 10 zile înainte."],
    ["Ședința anuală a departamentului are loc în luna martie, la Brașov.",
     "Facturile se emit prin sistemul e-Factura în termen de 5 zile lucrătoare."],
]

_SPECIAL_CODES = {"ă": 0x80, "ș": 0x81, "ț": 0x82, "Ă": 0x83, "Ș": 0x84, "Ț": 0x85}
_DIFFERENCES = b"/Differences [128 /abreve /scommaaccent /tcommaaccent /Abreve /Scommaaccent /Tcommaaccent]"
_TO_UNICODE = (
    b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap "
    b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def "
    b"/CMapName /Adobe-Identity-UCS def /CMapType 2 def "
    b"1 begincodespacerange <00> <FF> endcodespacerange "
    b"6 beginbfchar <80> <0103> <81> <0219> <82> <021B> <83> <0102> <84> <0218> <85> <021A> "
    b"endbfchar endcmap CMapName currentdict /CMapResource defineresource pop end end"
)


def _pdf_string(text: str) -> bytes:
    raw = bytearray()
    for ch in text:
        code = _SPECIAL_CODES.get(ch)
        raw += bytes([code]) if code is not None else ch.encode("cp1252")
    return bytes(raw).replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def build_pdf(pages: Sequence[Sequence[str]] = PDF_PAGES) -> bytes:
    """A valid PDF with one page per item of *pages*, each line a text line."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    # An unreferenced binary stream: the NUL bytes make git (and Windows autocrlf) treat
    # the committed sample as binary, so its byte offsets survive any checkout.
    add(b"<< /Length 4 >>\nstream\n\x00\xff\x00\xff\nendstream")
    to_unicode = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(_TO_UNICODE), _TO_UNICODE))
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding << /Type /Encoding "
               b"/BaseEncoding /WinAnsiEncoding " + _DIFFERENCES + b" >> /ToUnicode %d 0 R >>"
               % to_unicode)
    pages_id = add(b"")
    kids = []
    for lines in pages:
        content = b"BT /F1 11 Tf 72 760 Td 14 TL " + b"".join(
            b"(" + _pdf_string(line) + b") Tj T* " for line in lines) + b"ET"
        stream = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content))
        kids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] "
                        b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
                        % (pages_id, font, stream)))
    objects[pages_id - 1] = (b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % kid for kid in kids)
                             + b"] /Count %d >>" % len(kids))
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, catalog, xref)
    return bytes(out)


def build_encrypted_pdf(*, user_password: str = "secret") -> bytes:
    """A real PDF protected with AES-256; ``user_password=''`` only restricts editing."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(build_pdf())))
    writer.encrypt(user_password=user_password, owner_password="owner-secret",
                   algorithm="AES-256")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def build_blank_pdf(pages: int) -> bytes:
    """A PDF of *pages* empty pages (a scan without a text layer reads the same)."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


# ── Office Open XML ──────────────────────────────────────────────────────────────────

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
S_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

_CONTENT_TYPES_DOCX = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
    'officedocument.wordprocessingml.document.main+xml"/></Types>'
)
_CONTENT_TYPES_XLSX = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
    'officedocument.spreadsheetml.sheet.main+xml"/></Types>'
)


def _package_rels(main_part: str) -> str:
    return (f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{REL_NS}">'
            f'<Relationship Id="rId1" Type="{DOC_REL}/officeDocument" Target="{main_part}"/>'
            '</Relationships>')


_FIXED_TIME = (2026, 10, 17, 12, 0, 0)


def _zip(parts: dict[str, str | bytes]) -> bytes:
    """A deflated ZIP with fixed timestamps, so the same parts give the same bytes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(zipfile.ZipInfo(name, date_time=_FIXED_TIME), data,
                             compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


def _xml_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def docx_paragraph(text: str) -> str:
    """One ``w:p`` (a tab-stop definition included, which must not read as a tab)."""
    return (f'<w:p><w:pPr><w:tabs><w:tab w:val="left" w:pos="720"/></w:tabs></w:pPr>'
            f'<w:r><w:t xml:space="preserve">{_xml_text(text)}</w:t></w:r></w:p>')


def docx_table(rows: Sequence[Sequence[str]]) -> str:
    """One ``w:tbl`` with a cell per string."""
    body = "".join(
        "<w:tr>" + "".join(f"<w:tc>{docx_paragraph(cell)}</w:tc>" for cell in row) + "</w:tr>"
        for row in rows)
    return f"<w:tbl><w:tblPr/>{body}</w:tbl>"


def build_docx(body_xml: str | None = None, *, main_part: str = "word/document.xml",
               extra_parts: dict[str, str | bytes] | None = None) -> bytes:
    """A DOCX package; *body_xml* is the inner XML of ``w:body`` (default: a sample)."""
    if body_xml is None:
        body_xml = (
            docx_paragraph("Procedură de achiziții")
            + docx_paragraph("Orice achiziție peste 5.000 lei necesită aprobarea directorului.")
            + docx_table([["Furnizor", "Termen de plată"], ["Țesătoria Brașov", "30 de zile"],
                          ["Șantierul Naval", "45 de zile"]])
            + docx_paragraph("Ultima revizuire: martie 2026.")
        )
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<w:document xmlns:w="{W_NS}"><w:body>{body_xml}</w:body></w:document>')
    parts: dict[str, str | bytes] = {
        "[Content_Types].xml": _CONTENT_TYPES_DOCX,
        "_rels/.rels": _package_rels(main_part),
        main_part: document,
    }
    parts.update(extra_parts or {})
    return _zip(parts)


def _column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(ord("A") + rest) + letters
    return letters


def build_xlsx(sheets: dict[str, list[list[object]]] | None = None, *,
               date1904: bool = False) -> bytes:
    """An XLSX workbook; strings go to shared strings, ``("date", serial)`` cells get a
    date style, ``("pct", value)`` a percent style, ``("inline", text)`` an inline string,
    ``True``/``False`` booleans, numbers plain numbers."""
    if sheets is None:
        sheets = {
            "Vânzări": [["Lună", "Regiune", "Încasări (lei)"],
                        ["Ianuarie", "Brașov", 12500],
                        ["Februarie", "Timișoara", 13250.5]],
            "Termene": [["Activitate", "Data"],
                        ["Depunere bilanț", ("date", 46113)]],
        }
    shared: list[str] = []

    def shared_index(text: str) -> int:
        if text not in shared:
            shared.append(text)
        return shared.index(text)

    def cell_xml(ref: str, value: object) -> str:
        if isinstance(value, bool):
            return f'<c r="{ref}" t="b"><v>{int(value)}</v></c>'
        if isinstance(value, int | float):
            return f'<c r="{ref}"><v>{value}</v></c>'
        if isinstance(value, tuple):
            kind, payload = value
            if kind == "date":
                return f'<c r="{ref}" s="1"><v>{payload}</v></c>'
            if kind == "pct":
                return f'<c r="{ref}" s="2"><v>{payload}</v></c>'
            return f'<c r="{ref}" t="inlineStr"><is><t>{_xml_text(str(payload))}</t></is></c>'
        return f'<c r="{ref}" t="s"><v>{shared_index(str(value))}</v></c>'

    parts: dict[str, str | bytes] = {"[Content_Types].xml": _CONTENT_TYPES_XLSX,
                                     "_rels/.rels": _package_rels("xl/workbook.xml")}
    sheet_entries, rels = [], []
    for number, (name, rows) in enumerate(sheets.items(), start=1):
        row_xml = "".join(
            f'<row r="{r}">' + "".join(cell_xml(f"{_column_letter(c)}{r}", value)
                                       for c, value in enumerate(row) if value is not None)
            + "</row>"
            for r, row in enumerate(rows, start=1))
        parts[f"xl/worksheets/sheet{number}.xml"] = (
            f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{S_NS}">'
            f"<sheetData>{row_xml}</sheetData></worksheet>")
        sheet_entries.append(f'<sheet name="{_xml_text(name)}" sheetId="{number}" r:id="rId{number}"/>')
        rels.append(f'<Relationship Id="rId{number}" Type="{DOC_REL}/worksheet" '
                    f'Target="worksheets/sheet{number}.xml"/>')
    count = len(sheets)
    rels.append(f'<Relationship Id="rId{count + 1}" Type="{DOC_REL}/sharedStrings" '
                'Target="sharedStrings.xml"/>')
    rels.append(f'<Relationship Id="rId{count + 2}" Type="{DOC_REL}/styles" Target="styles.xml"/>')
    workbook_pr = '<workbookPr date1904="1"/>' if date1904 else "<workbookPr/>"
    parts["xl/workbook.xml"] = (f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="{S_NS}" '
                                f'xmlns:r="{R_NS}">{workbook_pr}<sheets>{"".join(sheet_entries)}'
                                "</sheets></workbook>")
    parts["xl/_rels/workbook.xml.rels"] = (f'<?xml version="1.0" encoding="UTF-8"?>'
                                           f'<Relationships xmlns="{REL_NS}">{"".join(rels)}'
                                           "</Relationships>")
    parts["xl/sharedStrings.xml"] = (
        f'<?xml version="1.0" encoding="UTF-8"?><sst xmlns="{S_NS}" count="{len(shared)}">'
        + "".join(f"<si><t>{_xml_text(text)}</t></si>" for text in shared) + "</sst>")
    parts["xl/styles.xml"] = (
        f'<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="{S_NS}">'
        '<numFmts count="1"><numFmt numFmtId="164" formatCode="dd/mm/yyyy"/></numFmts>'
        '<cellXfs count="3"><xf numFmtId="0"/><xf numFmtId="164"/><xf numFmtId="9"/></cellXfs>'
        "</styleSheet>")
    return _zip(parts)


def read_sample(name: str) -> bytes:
    """The bytes of a committed sample file."""
    return (HERE / name).read_bytes()
