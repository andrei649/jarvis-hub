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


def test_docx_real_approval_answer_has_bold_word_runs():
    answer = ("*   **Approval ID:** AUR-841 (Date: 2027-04-09)\n"
              "*   **Booking ID:** PINE-263 (Date: 2027-04-14)\n\n"
              "The booking is scheduled for **5 calendar days** after the approval date.")
    approval, booking, deadline = Document(BytesIO(create_docx(answer))).paragraphs
    assert approval.style.name == booking.style.name == "List Bullet"
    assert [(run.text, run.bold) for run in approval.runs] == [
        ("Approval ID:", True), (" AUR-841 (Date: 2027-04-09)", None)]
    assert [(run.text, run.bold) for run in booking.runs] == [
        ("Booking ID:", True), (" PINE-263 (Date: 2027-04-14)", None)]
    assert [(run.text, run.bold) for run in deadline.runs] == [
        ("The booking is scheduled for ", None), ("5 calendar days", True),
        (" after the approval date.", None)]


def test_docx_strong_runs_cover_headings_lists_and_table_cells():
    text = ("# **Approval** summary\n\n- **ID:** AP-247\n2. Reply in **5 calendar days**\n\n"
            "| Field | **Value** |\n| --- | --- |\n| Deadline | **5 calendar days** |")
    document = Document(BytesIO(create_docx(text)))
    heading, bullet, numbered = document.paragraphs
    assert heading.style.name == "Heading 1" and heading.text == "Approval summary"
    assert [(run.text, run.bold) for run in heading.runs] == [("Approval", True), (" summary", None)]
    assert bullet.style.name == "List Bullet" and bullet.text == "ID: AP-247"
    assert [(run.text, run.bold) for run in bullet.runs] == [("ID:", True), (" AP-247", None)]
    assert numbered.text == "2. Reply in 5 calendar days"
    assert [(run.text, run.bold) for run in numbered.runs] == [
        ("2. Reply in ", None), ("5 calendar days", True)]
    header, body = document.tables[0].rows
    assert [cell.text for cell in header.cells] == ["Field", "Value"]
    assert all(run.bold for cell in header.cells for run in cell.paragraphs[0].runs)
    assert [(run.text, run.bold) for run in body.cells[1].paragraphs[0].runs] == [("5 calendar days", True)]


def test_docx_inline_code_escaped_unmatched_and_fenced_markers_stay_literal():
    text = (r"Escaped \**literal** and `**inline code**` and **unmatched at C:\\server\\share"
            "\n\n" + r"C:\docs\*.xlsx and **ready**" + "\n\n" + r"C:\docs\*.xlsx"
            + "\n\n```text\n**literal fence**\n```")
    document = Document(BytesIO(create_docx(text)))
    assert document.paragraphs[0].text == (
        r"Escaped **literal** and `**inline code**` and **unmatched at C:\\server\\share")
    assert all(run.bold is None for run in document.paragraphs[0].runs)
    assert document.paragraphs[1].text == r"C:\docs\*.xlsx and ready"
    assert [(run.text, run.bold) for run in document.paragraphs[1].runs] == [
        (r"C:\docs\*.xlsx and ", None), ("ready", True)]
    assert document.paragraphs[2].text == r"C:\docs\*.xlsx"
    assert document.paragraphs[3].text == "**literal fence**"
    assert document.paragraphs[3].runs[0].bold is None
    assert document.paragraphs[3].runs[0].font.name == "Consolas"


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
