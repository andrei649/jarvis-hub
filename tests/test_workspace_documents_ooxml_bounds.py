"""Office Open XML is read in bounded memory and time, whatever a package unpacks to.

A worksheet of millions of empty cells deflates to a few KiB, and a parsed element
costs ~100 bytes, so building the whole tree of one 100 MiB part would take gigabytes
with no deadline check inside it. Large parts are therefore read one block (cell,
paragraph, table, shared string) at a time and everything already read is dropped;
any tree that is built is capped in elements and depth; the deadline is checked while
parsing.
"""

from __future__ import annotations

import tracemalloc

import pytest
from defusedxml.ElementTree import fromstring

from agents.core.workspace import extract
from tests.fixtures.workspace import samples

S_NS = samples.S_NS


def _workbook(sheet_xml: str, *, shared_xml: str | None = None,
              styles_xml: str | None = None) -> bytes:
    rels = [f'<Relationship Id="rId1" Type="{samples.DOC_REL}/worksheet" '
            'Target="worksheets/s.xml"/>']
    parts = {
        "[Content_Types].xml": samples._CONTENT_TYPES_XLSX,
        "_rels/.rels": samples._package_rels("xl/workbook.xml"),
        "xl/workbook.xml": (f'<workbook xmlns="{S_NS}" xmlns:r="{samples.R_NS}"><sheets>'
                            '<sheet name="Foaie" sheetId="1" r:id="rId1"/></sheets></workbook>'),
        "xl/worksheets/s.xml": f'<worksheet xmlns="{S_NS}">{sheet_xml}</worksheet>',
    }
    if shared_xml is not None:
        rels.append(f'<Relationship Id="rId2" Type="{samples.DOC_REL}/sharedStrings" '
                    'Target="sharedStrings.xml"/>')
        parts["xl/sharedStrings.xml"] = shared_xml
    if styles_xml is not None:
        rels.append(f'<Relationship Id="rId3" Type="{samples.DOC_REL}/styles" '
                    'Target="styles.xml"/>')
        parts["xl/styles.xml"] = styles_xml
    parts["xl/_rels/workbook.xml.rels"] = (f'<Relationships xmlns="{samples.REL_NS}">'
                                           + "".join(rels) + "</Relationships>")
    return samples._zip(parts)


def _code(data: bytes, kind: str) -> str:
    with pytest.raises(extract.ExtractionError) as caught:
        extract.extract_bytes(data, kind)
    return caught.value.code


def _cell_bomb(empty_cells: int) -> str:
    return ('<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>real</t></is></c>'
            + "<c/>" * empty_cells + "</row></sheetData>")


def test_a_deflated_cell_bomb_is_tiny_to_upload_and_reads_in_bounded_memory():
    sheet = _cell_bomb(60_000)
    data = _workbook(sheet)
    assert len(data) < 16 * 1024  # what makes the attack cheap
    tracemalloc.start()
    try:
        fromstring(f'<worksheet xmlns="{S_NS}">{sheet}</worksheet>'.encode(), forbid_dtd=True)
        whole_tree = tracemalloc.get_traced_memory()[1]
        tracemalloc.reset_peak()
        text = extract.extract_bytes(data, "xlsx").segments[0].text
        streamed = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert text == "## Foaie\n\n| real |\n| --- |"
    assert streamed * 3 < whole_tree


def test_read_elements_are_dropped_so_the_tree_never_grows():
    rows = 5000
    data = _workbook("<sheetData>" + "".join(
        f'<row r="{r}"><c r="A{r}"><v>{r}</v></c><c r="B{r}"><v>{r * 2}</v></c></row>'
        for r in range(1, rows + 1)) + "</sheetData><mergeCells>"
        + '<mergeCell ref="A1:B1"/>' * rows + "</mergeCells>")
    guard = extract._Guard(None, extract.MAX_TEXT_CHARS)
    widest = 0
    root = None
    with extract._ooxml_package(data, guard) as package:
        for _node, ancestors in package.blocks("xl/worksheets/s.xml", frozenset({"c"}),
                                               frozenset({"row"})):
            root = ancestors[0]
            widest = max([widest, *(len(list(node)) for node in ancestors)])
    # Only the parser's read-ahead (one 16 KiB buffer) is ever attached, never the part.
    assert widest < 1000 < rows
    assert root is not None and len(list(root)) == 0


def test_one_block_over_the_element_budget_is_too_much_text(monkeypatch):
    monkeypatch.setattr(extract, "MAX_XML_NODES", 50)
    many_small = "".join(samples.docx_paragraph(f"Paragraful {n}.") for n in range(200))
    assert "Paragraful 199." in extract.extract_bytes(samples.build_docx(many_small),
                                                      "docx").segments[0].text
    one_big = "<w:p>" + "<w:r><w:t>x</w:t></w:r>" * 60 + "</w:p>"
    assert _code(samples.build_docx(one_big), "docx") == "too_much_text"


def test_a_small_part_over_the_element_budget_is_too_much_text(monkeypatch):
    monkeypatch.setattr(extract, "MAX_XML_NODES", 50)
    styles = (f'<styleSheet xmlns="{S_NS}"><cellXfs>' + '<xf numFmtId="0"/>' * 60
              + "</cellXfs></styleSheet>")
    sheet = '<sheetData><row r="1"><c r="A1"><v>1</v></c></row></sheetData>'
    assert _code(_workbook(sheet, styles_xml=styles), "xlsx") == "too_much_text"


def test_nesting_beyond_the_depth_cap_is_invalid_file():
    deep = "<x>" * (extract.MAX_XML_DEPTH + 5) + "</x>" * (extract.MAX_XML_DEPTH + 5)
    sheet = f'<sheetData><row r="1"><c r="A1"><v>1</v></c></row></sheetData>{deep}'
    assert _code(_workbook(sheet), "xlsx") == "invalid_file"


def test_the_deadline_is_checked_inside_a_single_large_part(monkeypatch):
    monkeypatch.setattr(extract, "_TICK_EVERY_NODES", 64)
    ticks = []

    def tick(self):
        ticks.append(1)
        if len(ticks) == 5:
            raise extract.ExtractionError("timeout", "simulated deadline")

    monkeypatch.setattr(extract._Guard, "tick", tick)
    sheet = "<sheetData>" + "".join(f'<row r="{r}"><c r="A{r}"><v>{r}</v></c></row>'
                                    for r in range(1, 2000)) + "</sheetData>"
    assert _code(_workbook(sheet), "xlsx") == "timeout"  # one sheet, stopped mid-part


def test_shared_strings_have_a_text_budget_of_their_own(monkeypatch):
    monkeypatch.setattr(extract, "MAX_TEXT_CHARS", 100)
    shared = f'<sst xmlns="{S_NS}">' + "<si><t></t></si>" * 150 + "</sst>"
    sheet = '<sheetData><row r="1"><c r="A1"><v>1</v></c></row></sheetData>'
    assert _code(_workbook(sheet, shared_xml=shared), "xlsx") == "too_much_text"


def test_rows_stay_rows_across_a_long_sheet_and_stray_cells_are_ignored():
    rows = "".join(f'<row r="{r}"><c r="A{r}" t="inlineStr"><is><t>Produs {r}</t></is></c>'
                   f'<c r="C{r}"><v>{r * 3}</v></c></row>' for r in range(1, 1201))
    stray = ('<extLst><ext><c r="A1"><v>424242</v></c><row><c><v>515151</v></c></row></ext>'
             "</extLst>")
    lines = extract.extract_bytes(_workbook(f"<sheetData>{rows}</sheetData>{stray}"),
                                  "xlsx").segments[0].text.split("\n")
    assert lines[:4] == ["## Foaie", "", "| Produs 1 | 3 |", "| --- | --- |"]
    assert lines[-1] == "| Produs 1200 | 3600 |" and len(lines) == 1200 + 3
    assert not any("424242" in line or "515151" in line for line in lines)


def test_docx_blocks_outside_the_body_or_behind_alternate_content_are_ignored():
    mc = "http://schemas.openxmlformats.org/markup-compatibility/2006"
    body = (samples.docx_paragraph("Înainte")
            + f'<mc:AlternateContent xmlns:mc="{mc}"><mc:Choice Requires="w14">'
            + samples.docx_paragraph("Varianta nouă") + "</mc:Choice><mc:Fallback>"
            + samples.docx_paragraph("Varianta veche") + "</mc:Fallback></mc:AlternateContent>"
            + "<w:sdt><w:sdtContent>" + samples.docx_paragraph("În control") + "</w:sdtContent></w:sdt>")
    text = extract.extract_bytes(samples.build_docx(body), "docx").segments[0].text
    assert text == "Înainte\n\nÎn control"
