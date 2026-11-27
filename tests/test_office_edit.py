"""Targeted, data-only edits of existing Office packages."""

import hashlib
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from docx import Document
from lxml import etree as LET

from agents.core.office_export import create_docx, create_xlsx, edit_office

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _parts(data):
    with ZipFile(BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}


def _package(parts):
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return output.getvalue()


def _docx_with_runs():
    document = Document()
    paragraph = document.add_paragraph()
    paragraph.add_run("Invoice ")
    paragraph.add_run("OLD").bold = True
    paragraph.add_run(" value")
    document.add_paragraph("Unrelated paragraph")
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def test_docx_edits_one_run_and_preserves_other_parts_styles_and_input():
    original = _docx_with_runs()
    digest = hashlib.sha256(original).digest()
    before = _parts(original)
    edited = edit_office(original, "docx", "OLD", "NEW")
    assert hashlib.sha256(original).digest() == digest
    document = Document(BytesIO(edited))
    assert document.paragraphs[0].text == "Invoice NEW value"
    assert [(run.text, run.bold) for run in document.paragraphs[0].runs] == [
        ("Invoice ", None), ("NEW", True), (" value", None)]
    assert document.paragraphs[1].text == "Unrelated paragraph"
    after = _parts(edited)
    assert before.keys() == after.keys()
    assert all(before[name] == after[name] for name in before if name != "word/document.xml")
    word_root = LET.fromstring(after["word/document.xml"])
    ignorable = word_root.get("{http://schemas.openxmlformats.org/markup-compatibility/2006}Ignorable", "")
    assert ignorable and all(prefix in word_root.nsmap for prefix in ignorable.split())


def test_docx_replaces_split_runs_and_keeps_the_start_style():
    document = Document()
    paragraph = document.add_paragraph()
    paragraph.add_run("before ")
    paragraph.add_run("AB").bold = True
    paragraph.add_run("CD").italic = True
    paragraph.add_run(" after")
    output = BytesIO()
    document.save(output)
    edited = Document(BytesIO(edit_office(output.getvalue(), "docx", "ABCD", "replacement")))
    runs = edited.paragraphs[0].runs
    assert edited.paragraphs[0].text == "before replacement after"
    assert runs[1].text == "replacement" and runs[1].bold is True
    assert runs[-1].text == " after"


def test_docx_refuses_ambiguous_or_non_text_range():
    with pytest.raises(ValueError, match="unique"):
        edit_office(create_docx("OLD\n\nOLD"), "docx", "OLD", "NEW")
    with pytest.raises(ValueError, match="unique"):
        edit_office(create_docx("OLD" * 20_000), "docx", "OLD", "NEW")
    document = Document()
    paragraph = document.add_paragraph()
    paragraph.add_run("OLD")
    paragraph.add_run().add_break()
    output = BytesIO()
    document.save(output)
    with pytest.raises(ValueError, match="non-text"):
        edit_office(output.getvalue(), "docx", "OLD", "NEW")
    blanked = edit_office(create_docx("old"), "docx", "old", "")
    assert Document(BytesIO(blanked)).paragraphs[0].text == ""
    with pytest.raises(ValueError, match="Replacement"):
        edit_office(create_docx("old"), "docx", "old", "two\nlines")


def test_xlsx_edits_selected_cell_as_literal_or_number_and_preserves_others():
    original = create_xlsx([["Header", "old"], ["other", "17"]])
    before = _parts(original)
    edited = edit_office(original, "xlsx", "B1", "=SUM(A1)&_x0041_", sheet="Sheet1")
    assert original == create_xlsx([["Header", "old"], ["other", "17"]])
    after = _parts(edited)
    assert all(before[name] == after[name] for name in before if name != "xl/worksheets/sheet1.xml")
    root = ET.fromstring(after["xl/worksheets/sheet1.xml"])
    cells = {cell.attrib["r"]: cell for cell in root.iter(f"{S}c")}
    assert cells["B1"].attrib["t"] == "inlineStr"
    assert cells["B1"].find(f"{S}is/{S}t").text == "=SUM(A1)&_x005F_x0041_"
    assert cells["B1"].find(f"{S}f") is None
    assert cells["A1"].find(f"{S}is/{S}t").text == "Header"
    assert cells["B2"].find(f"{S}v").text == "17"
    numeric = edit_office(edited, "xlsx", "B1", "12.5", sheet="Sheet1")
    cell = next(cell for cell in ET.fromstring(_parts(numeric)["xl/worksheets/sheet1.xml"]).iter(f"{S}c")
                if cell.attrib["r"] == "B1")
    assert cell.attrib.get("t") is None and cell.find(f"{S}v").text == "12.5"


def test_xlsx_shared_string_edit_changes_only_selected_sheet():
    parts = _parts(create_xlsx([["old", "keep"]]))
    workbook = parts["xl/workbook.xml"].decode()
    parts["xl/workbook.xml"] = workbook.replace(
        '</sheets>', '<sheet name="Second" sheetId="2" r:id="rId2"/></sheets>').encode()
    rels = parts["xl/_rels/workbook.xml.rels"].decode()
    parts["xl/_rels/workbook.xml.rels"] = rels.replace(
        '</Relationships>',
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/></Relationships>').encode()
    parts["xl/worksheets/sheet1.xml"] = parts["xl/worksheets/sheet1.xml"].replace(
        b'<c r="A1" t="inlineStr"><is><t xml:space="preserve">old</t></is></c>',
        b'<c r="A1" t="s"><v>0</v></c>')
    parts["xl/worksheets/sheet2.xml"] = (
        f'<worksheet xmlns="{S[1:-1]}"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c></row></sheetData></worksheet>').encode()
    parts["xl/sharedStrings.xml"] = (f'<sst xmlns="{S[1:-1]}" count="2" uniqueCount="1">'
                                      '<si><t>old</t></si></sst>').encode()
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
        b"</Types>",
        b'<Override PartName="/xl/worksheets/sheet2.xml" '
        b'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        b'<Override PartName="/xl/sharedStrings.xml" '
        b'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        b"</Types>")
    original = _package(parts)
    edited = edit_office(original, "xlsx", "A1", "new", sheet="Sheet1")
    after = _parts(edited)
    assert after["xl/worksheets/sheet2.xml"] == parts["xl/worksheets/sheet2.xml"]
    assert after["xl/sharedStrings.xml"] == parts["xl/sharedStrings.xml"]
    first = ET.fromstring(after["xl/worksheets/sheet1.xml"]).find(f".//{S}c")
    assert first.attrib["t"] == "inlineStr" and first.find(f"{S}is/{S}t").text == "new"
    with pytest.raises(ValueError, match="sheet"):
        edit_office(original, "xlsx", "A1", "new")


def test_xlsx_refuses_formula_merged_and_ambiguous_cells():
    base = _parts(create_xlsx([["old"]]))
    formula = dict(base)
    formula["xl/worksheets/sheet1.xml"] = formula["xl/worksheets/sheet1.xml"].replace(
        b'<c r="A1" t="inlineStr"><is><t xml:space="preserve">old</t></is></c>',
        b'<c r="A1"><f>2+2</f><v>4</v></c>')
    with pytest.raises(ValueError, match="Formula"):
        edit_office(_package(formula), "xlsx", "A1", "=5+5")
    merged = dict(base)
    merged["xl/worksheets/sheet1.xml"] = merged["xl/worksheets/sheet1.xml"].replace(
        b"</worksheet>", b'<mergeCells count="1"><mergeCell ref="A1:B1"/></mergeCells></worksheet>')
    with pytest.raises(ValueError, match="Merged"):
        edit_office(_package(merged), "xlsx", "A1", "new")
    duplicate = dict(base)
    duplicate["xl/worksheets/sheet1.xml"] = duplicate["xl/worksheets/sheet1.xml"].replace(
        b"</row>", b'<c r="A1"><v>2</v></c></row>')
    with pytest.raises(ValueError, match="one existing cell"):
        edit_office(_package(duplicate), "xlsx", "A1", "new")


def test_office_edit_refuses_unsafe_or_malformed_input():
    with pytest.raises(ValueError):
        edit_office(b"not a zip", "docx", "old", "new")
    with pytest.raises(ValueError):
        edit_office(_package({"../escape": b"x"}), "docx", "old", "new")
    with pytest.raises(ValueError):
        edit_office(create_docx("old"), "docx", "missing", "new")
    with pytest.raises(ValueError):
        edit_office(create_xlsx([["old"]]), "xlsx", "XFE1", "new")
    parts = _parts(create_xlsx([["old"]]))
    parts["xl/worksheets/sheet1.xml"] = b"<worksheet><broken>"
    with pytest.raises(ValueError):
        edit_office(_package(parts), "xlsx", "A1", "new")
    parts = _parts(create_xlsx([["old"]]))
    parts["xl/_rels/external.rels"] = (
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        b'<Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        b'TargetMode="External" Target="https://example.invalid/image.png"/></Relationships>')
    with pytest.raises(ValueError, match="external"):
        edit_office(_package(parts), "xlsx", "A1", "new")
    parts = _parts(create_xlsx([["old"]]))
    parts["xl/vbaProject.bin"] = b"active"
    with pytest.raises(ValueError, match="active"):
        edit_office(_package(parts), "xlsx", "A1", "new")
    parts = _parts(create_xlsx([["old"]]))
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
        b"spreadsheetml.sheet.main+xml", b"wordprocessingml.document.main+xml")
    with pytest.raises(ValueError, match="wrong document type"):
        edit_office(_package(parts), "xlsx", "A1", "new")


def test_passive_external_hyperlink_is_preserved_without_following_it():
    parts = _parts(create_docx("old"))
    relation = (b'<Relationship Id="rId99" '
                b'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
                b'Target="https://example.invalid/passive" TargetMode="External"/>')
    name = "word/_rels/document.xml.rels"
    parts[name] = parts[name].replace(b"</Relationships>",
                                     b"<!-- retained relationship comment -->" + relation + b"</Relationships>")
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
        b"</Types>", b"<!-- retained type comment --></Types>")
    edited = edit_office(_package(parts), "docx", "old", "new")
    assert _parts(edited)[name] == parts[name]


def test_utf16_xml_is_preserved_but_an_inert_utf16_doctype_is_refused():
    parts = _parts(create_docx("old"))
    ordinary = '<?xml version="1.0" encoding="UTF-16"?><extra>Țară</extra>'.encode("utf-16")
    parts["word/extra.xml"] = ordinary
    edited = edit_office(_package(parts), "docx", "old", "new")
    assert _parts(edited)["word/extra.xml"] == ordinary
    parts["word/extra.xml"] = (
        '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE extra []><extra>Țară</extra>'
    ).encode("utf-16")
    with pytest.raises(ValueError, match="DTD"):
        edit_office(_package(parts), "docx", "old", "new")


@pytest.mark.parametrize("declaration", [
    b'<Default Extension="unused" ContentType="application/vnd.ms-office.activeX+xml"/>',
    b'<Override PartName="/xl/unused.xml" ContentType="application/vnd.ms-word.document.macroEnabled.main+xml"/>',
])
def test_active_content_type_declarations_are_refused_without_active_payloads(declaration):
    parts = _parts(create_xlsx([["old"]]))
    original = parts["[Content_Types].xml"]
    parts["[Content_Types].xml"] = original.replace(b"</Types>", declaration + b"</Types>")
    assert parts["[Content_Types].xml"] != original
    with pytest.raises(ValueError, match="active"):
        edit_office(_package(parts), "xlsx", "A1", "new")


def test_utf16_content_type_attribute_is_checked_after_xml_decoding():
    parts = _parts(create_xlsx([["old"]]))
    types = parts["[Content_Types].xml"].decode("utf-8").replace("UTF-8", "UTF-16")
    types = types.replace(
        "</Types>",
        '<Default Extension="unused" ContentType="application/vnd.ms-office.activeX+xml"/></Types>')
    parts["[Content_Types].xml"] = types.encode("utf-16")
    with pytest.raises(ValueError, match="active"):
        edit_office(_package(parts), "xlsx", "A1", "new")
