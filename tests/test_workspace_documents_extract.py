"""Text extraction of uploaded documents (spec §6 "Uploads"): every format, every error code.

The samples are real files with Romanian text (``tests/fixtures/workspace``); DOCX and
XLSX packages are built in code so each test states exactly what the file holds.
"""

from __future__ import annotations

import asyncio
import codecs
import io
import threading
import time
import zipfile

import pytest

from agents.core.workspace import extract
from agents.core.workspace.extract import ExtractionError, Segment
from tests.fixtures.workspace import samples


def _text(result: extract.Extracted) -> str:
    return "\n\n".join(segment.text for segment in result.segments)


def _code(data: bytes, kind: str, **kwargs) -> str:
    with pytest.raises(ExtractionError) as caught:
        extract.extract_bytes(data, kind, **kwargs)
    assert caught.value.code in extract.ERROR_CODES
    return caught.value.code


# ── kinds, magic numbers, decoding, cleaning ─────────────────────────────────────────

@pytest.mark.parametrize(("name", "kind"), [
    ("raport.pdf", "pdf"), ("RAPORT.PDF", "pdf"), ("Ofertă.Docx", "docx"), ("buget.xlsx", "xlsx"),
    ("contacte.csv", "csv"), ("note.txt", "txt"), ("politica.md", "md"), ("arhiva.tar.pdf", "pdf"),
    ("vechi.doc", None), ("vechi.xls", None), ("poza.png", None), ("script.pdf.exe", None),
    ("fara-extensie", None), (".pdf", None),
])
def test_kind_follows_the_extension_case_insensitively(name, kind):
    assert extract.kind_for_filename(name) == kind


def test_the_allow_list_is_exactly_the_six_spec_formats():
    assert set(extract.ALLOWED_EXTENSIONS) == {".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md"}
    assert extract.MIME_TYPES["pdf"] == "application/pdf"


def test_magic_numbers_must_match_the_extension():
    pdf, docx, xlsx = samples.build_pdf(), samples.build_docx(), samples.build_xlsx()
    assert extract.content_matches("pdf", pdf)
    assert extract.content_matches("pdf", b"\n\n%PDF-1.7 header after a blank line")
    assert not extract.content_matches("pdf", b"\x89PNG\r\n\x1a\n" + b"0" * 100)
    assert extract.content_matches("docx", docx) and extract.content_matches("xlsx", xlsx)
    assert not extract.content_matches("docx", xlsx)  # a renamed workbook is not a document
    assert not extract.content_matches("xlsx", docx)
    plain_zip = io.BytesIO()
    with zipfile.ZipFile(plain_zip, "w") as archive:
        archive.writestr("word/document.xml", "<x/>")
    assert not extract.content_matches("docx", plain_zip.getvalue())  # no [Content_Types].xml
    assert extract.content_matches("txt", "Notă scurtă".encode())
    assert not extract.content_matches("txt", b"binary\x00data")
    assert not extract.content_matches("csv", pdf)  # a PDF under a text extension
    assert not extract.content_matches("md", docx)
    assert extract.content_matches("txt", "Notă".encode("utf-16"))  # NULs explained by a BOM
    assert not extract.content_matches("exe", b"MZ")


@pytest.mark.parametrize(("raw", "expected"), [
    ("Șeful a aprobat".encode(), "Șeful a aprobat"),
    (codecs.BOM_UTF8 + "Încasări".encode(), "Încasări"),
    ("Oraş Constanţa, îngheţată".encode("cp1250"), "Oraş Constanţa, îngheţată"),
    ("Notă de plată".encode("utf-16"), "Notă de plată"),
])
def test_text_is_decoded_utf8_bom_utf16_or_cp1250(raw, expected):
    assert extract.decode_text(raw) == expected


def test_a_utf8_file_with_one_stray_byte_is_not_reread_as_cp1250():
    raw = ("Țară, șantier, ședință, încasări, ăâîșț " * 5).encode() + b"\xff"
    decoded = extract.decode_text(raw)
    assert decoded.startswith("Țară, șantier") and decoded.endswith("\ufffd")


def test_clean_text_normalizes_without_losing_words():
    raw = ("Linia\u00a0unu\r\nLinia  doi\x00\x07\u00ad\ud800 \t\n\n\n\nĂ treia\x0cpagina"
           "\u2028sfârșit\ufeff")
    assert extract.clean_text(raw) == "Linia unu\nLinia doi\n\nĂ treia\npagina\nsfârșit"


def test_markdown_table_drops_empty_rows_and_columns_and_escapes_pipes():
    table = extract.markdown_table([["Cod", "", "Preț | lei"], ["", "", ""],
                                    ["A1", "", "12\n,5"], ["B2"]])
    assert table.split("\n") == ["| Cod | Preț \\| lei |", "| --- | --- |", "| A1 | 12 ,5 |",
                                 "| B2 | |"]
    assert extract.markdown_table([["", ""], []]) == ""


# ── PDF ──────────────────────────────────────────────────────────────────────────────

def test_the_committed_pdf_is_what_its_builder_writes():
    committed = samples.read_sample("regulament-intern.pdf")
    assert committed == samples.build_pdf()
    assert b"\x00" in committed  # git sees it as binary: no line-ending rewrite on checkout


def test_the_committed_pdf_keeps_pages_and_romanian_letters():
    result = extract.extract_bytes(samples.read_sample("regulament-intern.pdf"), "pdf")
    assert result.page_count == 2
    assert [segment.page for segment in result.segments] == [1, 2]
    assert "Angajații au dreptul la 21 de zile de concediu de odihnă pe an." in result.segments[0].text
    assert "Ședința anuală" in result.segments[1].text and "Brașov" in result.segments[1].text
    assert result.char_count == sum(len(segment.text) for segment in result.segments)


def test_a_pdf_that_needs_a_password_is_encrypted_pdf():
    assert _code(samples.build_encrypted_pdf(), "pdf") == "encrypted_pdf"


def test_a_pdf_with_only_an_owner_password_reads_like_any_viewer_reads_it():
    result = extract.extract_bytes(samples.build_encrypted_pdf(user_password=""), "pdf")
    assert "Regulament intern" in _text(result)


def test_a_pdf_without_a_text_layer_is_no_text_and_keeps_its_page_count():
    with pytest.raises(ExtractionError) as caught:
        extract.extract_bytes(samples.build_blank_pdf(3), "pdf")
    assert caught.value.code == "no_text" and caught.value.page_count == 3


def test_more_than_500_pages_is_too_many_pages():
    assert extract.MAX_PDF_PAGES == 500
    with pytest.raises(ExtractionError) as caught:
        extract.extract_bytes(samples.build_blank_pdf(501), "pdf")
    assert caught.value.code == "too_many_pages" and caught.value.page_count == 501


def test_exactly_the_page_limit_is_still_read(monkeypatch):
    monkeypatch.setattr(extract, "MAX_PDF_PAGES", 2)
    assert extract.extract_bytes(samples.build_pdf(), "pdf").page_count == 2


@pytest.mark.parametrize("data", [b"%PDF-1.4\nnot really a pdf", b"%PDF-", b"%PDF-1.7\n" + b"0" * 4096],
                         ids=["garbage", "header-only", "zeros"])
def test_a_damaged_pdf_is_invalid_file(data):
    assert _code(data, "pdf") == "invalid_file"


def test_one_unreadable_page_is_skipped_and_the_rest_kept(monkeypatch):
    from pypdf import PageObject

    original = PageObject.extract_text
    seen = []

    def flaky(self, *args, **kwargs):
        seen.append(1)
        if len(seen) == 1:
            raise KeyError("/Font")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(PageObject, "extract_text", flaky)
    result = extract.extract_bytes(samples.build_pdf(), "pdf")
    assert [segment.page for segment in result.segments] == [2]


# ── DOCX ─────────────────────────────────────────────────────────────────────────────

def test_docx_paragraphs_and_tables_come_out_in_document_order():
    text = _text(extract.extract_bytes(samples.build_docx(), "docx"))
    assert text.split("\n\n") == [
        "Procedură de achiziții",
        "Orice achiziție peste 5.000 lei necesită aprobarea directorului.",
        "| Furnizor | Termen de plată |\n| --- | --- |\n| Țesătoria Brașov | 30 de zile |\n"
        "| Șantierul Naval | 45 de zile |",
        "Ultima revizuire: martie 2026.",
    ]
    assert "\t" not in text  # tab-stop definitions in paragraph properties are not text


def test_docx_runs_tabs_breaks_and_tracked_changes():
    body = (
        '<w:p><w:r><w:t>Termen</w:t></w:r><w:r><w:tab/><w:t>30 zile</w:t></w:r>'
        '<w:r><w:br/><w:t>a doua linie</w:t></w:r></w:p>'
        '<w:p><w:ins><w:r><w:t>adăugat</w:t></w:r></w:ins>'
        '<w:del><w:r><w:delText>șters</w:delText></w:r></w:del>'
        '<w:r><w:instrText>PAGE</w:instrText></w:r></w:p>'
        '<w:sdt><w:sdtPr><w:alias w:val="x"/></w:sdtPr><w:sdtContent>'
        + samples.docx_paragraph("Din control de conținut") + '</w:sdtContent></w:sdt>'
    )
    text = _text(extract.extract_bytes(samples.build_docx(body), "docx"))
    assert text == "Termen\t30 zile\na doua linie\n\nadăugat\n\nDin control de conținut"


def test_docx_merged_cells_keep_the_columns_aligned():
    body = ('<w:tbl><w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>'
            + samples.docx_paragraph("Total") + '</w:tc><w:tc>'
            + samples.docx_paragraph("100") + '</w:tc></w:tr><w:tr>'
            + "".join(f"<w:tc>{samples.docx_paragraph(c)}</w:tc>" for c in ("a", "b", "c"))
            + "</w:tr></w:tbl>")
    text = _text(extract.extract_bytes(samples.build_docx(body), "docx"))
    assert text.split("\n") == ["| Total | | 100 |", "| --- | --- | --- |", "| a | b | c |"]


def test_docx_main_part_is_found_through_the_package_relationships():
    data = samples.build_docx(samples.docx_paragraph("Parte principală mutată"),
                              main_part="word/document2.xml")
    assert _text(extract.extract_bytes(data, "docx")) == "Parte principală mutată"


def test_strict_ooxml_namespaces_read_the_same():
    data = samples._zip({
        "[Content_Types].xml": samples._CONTENT_TYPES_DOCX,
        "_rels/.rels": samples._package_rels("word/document.xml"),
        "word/document.xml": ('<w:document xmlns:w="http://purl.oclc.org/ooxml/wordprocessingml/'
                              'main"><w:body>' + samples.docx_paragraph("Strict") + "</w:body>"
                              "</w:document>"),
    })
    assert _text(extract.extract_bytes(data, "docx")) == "Strict"


BILLION_LAUGHS = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
                  '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
                  f'<w:document xmlns:w="{samples.W_NS}"><w:body><w:p><w:r><w:t>&lol2;</w:t>'
                  '</w:r></w:p></w:body></w:document>')
EXTERNAL_ENTITY = ('<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
                   f'<w:document xmlns:w="{samples.W_NS}"><w:body><w:p><w:r><w:t>&x;</w:t>'
                   '</w:r></w:p></w:body></w:document>')


@pytest.mark.parametrize("document_xml", [BILLION_LAUGHS, EXTERNAL_ENTITY,
                                          "<w:document><unclosed>", ""])
def test_hostile_or_broken_docx_xml_is_invalid_file(document_xml):
    data = samples._zip({"[Content_Types].xml": samples._CONTENT_TYPES_DOCX,
                         "_rels/.rels": samples._package_rels("word/document.xml"),
                         "word/document.xml": document_xml})
    assert _code(data, "docx") == "invalid_file"


def test_docx_without_its_document_part_or_body_is_invalid_file():
    no_part = samples._zip({"[Content_Types].xml": samples._CONTENT_TYPES_DOCX,
                            "_rels/.rels": samples._package_rels("word/document.xml")})
    assert _code(no_part, "docx") == "invalid_file"
    no_body = samples._zip({"[Content_Types].xml": samples._CONTENT_TYPES_DOCX,
                            "word/document.xml": f'<w:document xmlns:w="{samples.W_NS}"/>'})
    assert _code(no_body, "docx") == "invalid_file"


def test_a_package_without_content_types_or_not_a_zip_is_invalid_file():
    assert _code(samples._zip({"word/document.xml": "<x/>"}), "docx") == "invalid_file"
    assert _code(b"PK\x03\x04 truncated [Content_Types].xml word/", "docx") == "invalid_file"


def test_traversal_member_names_are_refused_and_nothing_escapes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data = samples._zip({"[Content_Types].xml": samples._CONTENT_TYPES_DOCX,
                         "../evil.xml": "<x/>", "word/document.xml": "<x/>"})
    assert _code(data, "docx") == "invalid_file"
    assert not (tmp_path.parent / "evil.xml").exists() and not list(tmp_path.iterdir())


def test_archive_bomb_limits_apply(monkeypatch):
    monkeypatch.setattr(extract, "OOXML_LIMITS", extract.ArchiveLimits(max_members=2000,
                                                                       max_bytes=2048))
    big = samples.build_docx(samples.docx_paragraph("ă" * 5000))
    assert _code(big, "docx") == "invalid_file"
    monkeypatch.setattr(extract, "OOXML_LIMITS", extract.ArchiveLimits(max_members=2,
                                                                       max_bytes=10 ** 7))
    assert _code(samples.build_docx(), "docx") == "invalid_file"  # the sample has 3 members


def test_the_spec_archive_limits_are_in_force():
    assert extract.OOXML_LIMITS.max_members == 2000
    assert extract.OOXML_LIMITS.max_bytes == 100 * 1024 * 1024


def test_an_empty_docx_body_is_no_text():
    assert _code(samples.build_docx(samples.docx_paragraph("   ")), "docx") == "no_text"


def test_deeply_nested_docx_xml_is_invalid_file_not_a_crash():
    depth = 5000
    body = "<w:sdt><w:sdtContent>" * depth + samples.docx_paragraph("adânc") + \
        "</w:sdtContent></w:sdt>" * depth
    assert _code(samples.build_docx(body), "docx") == "invalid_file"


# ── XLSX ─────────────────────────────────────────────────────────────────────────────

def test_every_sheet_is_a_markdown_table_under_its_name():
    result = extract.extract_bytes(samples.build_xlsx(), "xlsx")
    assert [segment.text for segment in result.segments] == [
        "## Vânzări\n\n| Lună | Regiune | Încasări (lei) |\n| --- | --- | --- |\n"
        "| Ianuarie | Brașov | 12500 |\n| Februarie | Timișoara | 13250.5 |",
        "## Termene\n\n| Activitate | Data |\n| --- | --- |\n| Depunere bilanț | 2026-04-01 |",
    ]
    assert result.page_count is None


def test_xlsx_cell_types_inline_strings_booleans_percent_and_sparse_columns():
    data = samples.build_xlsx({"Indicatori": [
        ["Indicator", None, None, "Valoare"],
        [("inline", "Marjă"), None, None, ("pct", 0.15)],
        ["Activ", None, None, True],
        ["Pierdere", None, None, -0.1 + 0.3],
    ]})
    text = _text(extract.extract_bytes(data, "xlsx"))
    assert text.split("\n")[2:] == ["| Indicator | Valoare |", "| --- | --- |",
                                    "| Marjă | 15% |", "| Activ | TRUE |", "| Pierdere | 0.2 |"]


def test_the_1904_date_system_is_honoured():
    data = samples.build_xlsx({"Date": [["Zi"], [("date", 0)], [("date", 44651)]]},
                              date1904=True)
    lines = _text(extract.extract_bytes(data, "xlsx")).split("\n")
    assert lines[-2:] == ["| 1904-01-01 |", "| 2026-04-01 |"]  # 1904 serials are 1462 lower


def test_empty_sheets_are_skipped_and_an_empty_workbook_is_no_text():
    data = samples.build_xlsx({"Gol": [], "Plin": [["Doar", "un rând"]]})
    assert [segment.text.split("\n")[0] for segment in
            extract.extract_bytes(data, "xlsx").segments] == ["## Plin"]
    assert _code(samples.build_xlsx({"Gol": [[None, None]]}), "xlsx") == "no_text"


def _workbook_with_sheet(sheet_xml: str, *, shared: str | None = None,
                         shared_xml: str | None = None) -> bytes:
    parts = {
        "[Content_Types].xml": samples._CONTENT_TYPES_XLSX,
        "_rels/.rels": samples._package_rels("xl/workbook.xml"),
        "xl/workbook.xml": (f'<workbook xmlns="{samples.S_NS}" xmlns:r="{samples.R_NS}"><sheets>'
                            '<sheet name="Foaie" sheetId="1" r:id="rId1"/>'
                            '<sheet name="Grafic" sheetId="2" r:id="rId3"/></sheets></workbook>'),
        "xl/_rels/workbook.xml.rels": (
            f'<Relationships xmlns="{samples.REL_NS}">'
            f'<Relationship Id="rId1" Type="{samples.DOC_REL}/worksheet" Target="/xl/worksheets/s.xml"/>'
            f'<Relationship Id="rId2" Type="{samples.DOC_REL}/sharedStrings" Target="sharedStrings.xml"/>'
            f'<Relationship Id="rId3" Type="{samples.DOC_REL}/chartsheet" Target="chartsheets/c.xml"/>'
            f'<Relationship Id="rId4" Type="{samples.DOC_REL}/worksheet" Target="../../escape.xml"/>'
            "</Relationships>"),
        "xl/worksheets/s.xml": f'<worksheet xmlns="{samples.S_NS}"><sheetData>{sheet_xml}'
                               "</sheetData></worksheet>",
        "xl/chartsheets/c.xml": f'<chartsheet xmlns="{samples.S_NS}"/>',
    }
    if shared is not None:
        parts["xl/sharedStrings.xml"] = f'<sst xmlns="{samples.S_NS}">{shared}</sst>'
    if shared_xml is not None:
        parts["xl/sharedStrings.xml"] = shared_xml
    return samples._zip(parts)


def test_xlsx_formula_strings_errors_rich_text_and_cells_without_refs():
    shared = ('<si><r><t>Bogat </t></r><r><rPr/><t>în stil</t></r><rPh><t>ignorat</t></rPh></si>'
              '<si><t>simplu</t></si>')
    sheet = ('<row r="1"><c t="s"><v>0</v></c><c t="s"><v>1</v></c><c t="s"><v>99</v></c></row>'
             '<row r="2"><c r="A2" t="str"><f>A1</f><v>calculat</v></c>'
             '<c r="B2" t="e"><v>#N/A</v></c><c r="ZZZ2"><v>1</v></c></row>')
    lines = _text(extract.extract_bytes(_workbook_with_sheet(sheet, shared=shared), "xlsx"))
    assert lines.split("\n") == ["## Foaie", "", "| Bogat în stil | simplu |", "| --- | --- |",
                                 "| calculat | #N/A |"]


def test_xlsx_parts_with_a_dtd_are_invalid_file():
    sheet = '<row r="1"><c r="A1" t="s"><v>0</v></c></row>'
    assert _text(extract.extract_bytes(_workbook_with_sheet(sheet, shared="<si><t>ok</t></si>"),
                                       "xlsx")) == "## Foaie\n\n| ok |\n| --- |"
    undefined_entity = _workbook_with_sheet(sheet, shared="<si><t>&e;</t></si>")
    assert _code(undefined_entity, "xlsx") == "invalid_file"
    with_dtd = _workbook_with_sheet(sheet, shared_xml=(
        '<?xml version="1.0"?><!DOCTYPE sst [<!ENTITY e "x">]>'
        f'<sst xmlns="{samples.S_NS}"><si><t>&e;</t></si></sst>'))
    assert _code(with_dtd, "xlsx") == "invalid_file"


@pytest.mark.parametrize(("code", "kind"), [
    ("dd/mm/yyyy", "date"), ("mmm-yy", "date"), ("d mmmm yyyy", "date"), ("h:mm", "time"),
    ("[h]:mm:ss", "time"), ("mm:ss", "time"), ("yyyy-mm-dd hh:mm", "datetime"),
    ("0.00%", "percent"), ('#,##0 "lei"', ""), ("General", ""), ("0.00E+00", ""),
    ('_-* #,##0.00\\ _l_e_i_-', ""), ("[Red]0.00", ""), ('"Data: "0', ""),
])
def test_number_format_classification(code, kind):
    assert extract._classify_format(code) == kind


@pytest.mark.parametrize(("serial", "kind", "epoch_1904", "text"), [
    (46113, "date", False, "2026-04-01"), (59, "date", False, "1900-02-28"),
    (61, "date", False, "1900-03-01"), (46113.5, "datetime", False, "2026-04-01 12:00"),
    (0.75, "time", False, "18:00"), (1.0 / 86400 * 3661, "time", False, "01:01:01"),
    (0, "date", False, None), (3_000_000, "date", False, None), (0, "date", True, "1904-01-01"),
    (1, "date", True, "1904-01-02"),
])
def test_excel_serials_become_iso_dates(serial, kind, epoch_1904, text):
    assert extract._serial_text(serial, kind, epoch_1904) == text


# ── CSV and plain text ───────────────────────────────────────────────────────────────

def test_cp1250_csv_with_semicolons_and_a_quoted_delimiter():
    text = _text(extract.extract_bytes(samples.read_sample("contacte-cp1250.csv"), "csv"))
    assert text.split("\n") == [
        "| Nume | Funcţie | Oraş | Telefon |", "| --- | --- | --- | --- |",
        "| Ana Brătianu | Contabil şef | Bucureşti | 0721 000 111 |",
        "| Mircea Ţăranu | Agent vânzări | Constanţa | 0744 222 333 |",
        "| Irina Stănescu | Director; resurse umane | Iaşi | 0755 444 555 |",
    ]


def test_utf8_bom_csv_with_commas_crlf_and_quoted_commas():
    text = _text(extract.extract_bytes(samples.read_sample("vanzari-utf8-bom.csv"), "csv"))
    assert text.split("\n")[0] == "| Produs | Cantitate | Preț unitar (lei) | Observații |"
    assert "| Șuruburi M8 | 1200 | 0.35 | livrare parțială, restul în noiembrie |" in text
    assert "\ufeff" not in text


@pytest.mark.parametrize(("raw", "delimiter"), [
    ("Nume\tOraș\nAna\tIași\nIon\tCluj\n", "\t"), ("Nume|Oraș\nAna|Iași\nIon|Cluj\n", "|"),
    ("Nume;Sumă\nAna;1,5\nIon;2,75\n", ";"), ("o singură coloană\nfără separator\n", ","),
])
def test_csv_delimiter_sniffing(raw, delimiter):
    assert extract.sniff_delimiter(raw) == delimiter
    assert extract.extract_bytes(raw.encode(), "csv").segments


def test_a_csv_cell_beyond_the_field_limit_is_invalid_file():
    assert _code(b'a,b\n"' + b"x" * 200_000 + b'",1\n', "csv") == "invalid_file"


@pytest.mark.parametrize("raw", [b"", b" \n\t\n", b";;;\n,,,\n"])
def test_empty_text_files_are_no_text(raw):
    for kind in ("txt", "md", "csv"):
        assert _code(raw, kind) == "no_text"


def test_markdown_and_text_are_kept_as_written():
    md = _text(extract.extract_bytes(samples.read_sample("politica-concedii.md"), "md"))
    assert md.startswith("# Politica de concedii — Acme SRL\n\n## Concediul de odihnă")
    assert "| Odihnă | 21 | Șeful de echipă |" in md
    txt = _text(extract.extract_bytes(samples.read_sample("note-sedinta.txt"), "txt"))
    assert "Ștefan Țurcanu" in txt and "e-Factura" in txt


# ── limits, deadline, unknown kinds, the async entry point ───────────────────────────

def test_too_much_text_is_refused(monkeypatch):
    monkeypatch.setattr(extract, "MAX_TEXT_CHARS", 50)
    for data, kind in ((samples.read_sample("note-sedinta.txt"), "txt"),
                       (samples.build_xlsx(), "xlsx"), (samples.build_docx(), "docx"),
                       (samples.read_sample("contacte-cp1250.csv"), "csv"),
                       (samples.build_pdf(), "pdf")):
        assert _code(data, kind) == "too_much_text", kind


def test_a_passed_deadline_stops_extraction_between_pages():
    assert _code(samples.build_blank_pdf(5), "pdf", timeout=-1) == "timeout"
    assert _code(samples.build_xlsx(), "xlsx", timeout=-1) == "timeout"


def test_an_unknown_kind_is_invalid_file():
    assert _code(b"MZ", "exe") == "invalid_file"


async def test_extract_document_runs_off_the_loop_and_matches_the_sync_result():
    data = samples.read_sample("regulament-intern.pdf")
    assert await extract.extract_document(data, "pdf") == extract.extract_bytes(data, "pdf")


async def test_extract_document_is_bounded(monkeypatch):
    def slow(data: bytes, guard) -> extract.Extracted:
        time.sleep(0.3)
        return extract.Extracted((Segment(None, "târziu"),), None)

    monkeypatch.setitem(extract._HANDLERS, "txt", slow)
    started = time.monotonic()
    with pytest.raises(ExtractionError) as caught:
        await extract.extract_document(b"x", "txt", timeout=0.05)
    assert caught.value.code == "timeout" and time.monotonic() - started < 0.25
    await asyncio.sleep(0.3)  # let the worker finish before the monkeypatch is undone


def test_the_extraction_bound_is_sixty_seconds():
    assert extract.EXTRACT_TIMEOUT_SECONDS == 60.0


async def test_extraction_runs_on_its_own_pool_not_the_default_executor(monkeypatch):
    threads: list[str] = []

    def record(data: bytes, guard) -> extract.Extracted:
        threads.append(threading.current_thread().name)
        return extract.Extracted((Segment(None, "text"),), None)

    monkeypatch.setitem(extract._HANDLERS, "txt", record)
    await asyncio.gather(*(extract.extract_document(b"x", "txt") for _ in range(4)))
    assert len(threads) == 4 and all(name.startswith("nerva-ws-extract") for name in threads)
    assert extract.EXTRACTION_THREADS == 2
