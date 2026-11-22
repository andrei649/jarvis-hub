from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from docx import Document

from agents.core.office_export import create_docx, create_xlsx

S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _sheet(data: bytes):
    with ZipFile(BytesIO(data)) as archive:
        return ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))


def test_docx_formats_common_markdown_and_keeps_long_content():
    long_text = "Ț" * 20000
    data = create_docx(f"# Titlu\n\nParagraf {long_text}\n\n- primul\n- al doilea\n\n```py\nprint('ok')\n```\n\n| A | B |\n| --- | --- |\n| x | y |")
    document = Document(BytesIO(data))
    assert document.paragraphs[0].style.name == "Heading 1"
    assert long_text in "\n".join(p.text for p in document.paragraphs)
    assert any(p.style.name == "List Bullet" and p.text == "primul" for p in document.paragraphs)
    assert "print('ok')" in "\n".join(p.text for p in document.paragraphs)
    assert [[c.text for c in row.cells] for row in document.tables[0].rows] == [["A", "B"], ["x", "y"]]


def test_xlsx_readback_keeps_text_safe_and_numbers_useful():
    rows = [["Code", "Formula", "Number", "Precise", "Unicode"],
            ["00123", "=1+2", "-12.5", "12345678901234567890", "Țară 😀"],
            ["+SUM(A1)", "@cmd", "1.2", "1.20", " leading\rline "]]
    data = create_xlsx(rows)
    sheet = _sheet(data)
    cells = {cell.attrib["r"]: cell for cell in sheet.iter(f"{S}c")}
    assert cells["A2"].attrib["t"] == "inlineStr"
    assert cells["A2"].find(f"{S}is/{S}t").text == "00123"
    assert cells["B2"].attrib["t"] == "inlineStr"
    assert cells["B2"].find(f"{S}is/{S}t").text == "=1+2"
    assert cells["C2"].find(f"{S}v").text == "-12.5"
    assert cells["D2"].attrib["t"] == "inlineStr"
    assert cells["D2"].find(f"{S}is/{S}t").text == "12345678901234567890"
    assert cells["E2"].find(f"{S}is/{S}t").text == "Țară 😀"
    assert cells["D3"].attrib["t"] == "inlineStr"
    assert cells["E3"].find(f"{S}is/{S}t").text == " leading\rline "
    with ZipFile(BytesIO(data)) as archive:
        assert "xl/workbook.xml" in archive.namelist()
        assert b"<f>" not in archive.read("xl/worksheets/sheet1.xml")


def test_document_and_worksheet_limits_are_inclusive():
    assert "z" * 65536 in "\n".join(p.text for p in Document(BytesIO(create_docx("z" * 65536))).paragraphs)
    rows = [["x" * 32767] + [""] * 63] + [[""]] * 1000
    sheet = _sheet(create_xlsx(rows))
    assert len(sheet.findall(f"{S}sheetData/{S}row")) == 1001
    assert len(sheet.find(f"{S}sheetData/{S}row")) == 64


def test_wide_markdown_table_does_not_expand_into_huge_word_grid():
    header = "|".join(f"h{column}" for column in range(100))
    body = "\n".join("| narrow | cell |" for _ in range(100))
    document = Document(BytesIO(create_docx(f"|{header}|\n|" + "|".join("---" for _ in range(100)) + f"|\n{body}")))
    assert not document.tables
    content = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "h99" in content and content.count("narrow") == 100


def test_docx_preserves_long_fence_content_and_explicit_list_number():
    document = Document(BytesIO(create_docx("````python\n```\ncode\n````\n\n3. third")))
    content = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "```\ncode" in content
    assert "3. third" in content


def test_xlsx_escapes_literal_ooxml_sequences_and_non_ascii_digits():
    sheet = _sheet(create_xlsx([["_x0041_", "12٣", "A longer heading"]]))
    cells = list(sheet.iter(f"{S}c"))
    assert cells[0].find(f"{S}is/{S}t").text == "_x005F_x0041_"
    assert cells[1].attrib["t"] == "inlineStr"
    assert cells[1].find(f"{S}is/{S}t").text == "12٣"
    widths = [float(column.attrib["width"]) for column in sheet.findall(f"{S}cols/{S}col")]
    assert len(widths) == 3 and widths[2] > widths[0] and all(10 <= width <= 40 for width in widths)


@pytest.mark.parametrize("text", [None, 1, "", "x" * 65537, "bad\x00", "bad\ud800"])
def test_docx_rejects_invalid_text(text):
    with pytest.raises(ValueError):
        create_docx(text)


@pytest.mark.parametrize("rows", [None, [], [[]], [[1]], [["bad\x00"]], [["x" * 32768]],
                                  [["x"] * 65], [["x"]] * 1002,
                                  [["x" * 20000] * 6]])
def test_xlsx_rejects_invalid_rows(rows):
    with pytest.raises(ValueError):
        create_xlsx(rows)


def test_xlsx_cell_limit_counts_utf16_units_for_native_excel():
    allowed = "😀" * 16383 + "a"
    assert _sheet(create_xlsx([[allowed]])).find(f".//{S}t").text == allowed
    with pytest.raises(ValueError):
        create_xlsx([[allowed + "a"]])
