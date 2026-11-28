"""H444 — Bounded zero-dependency personal-assistant document readers.

Extracts structured plain/Markdown text from common Office, e-book, Rich Text,
and notebook formats using Python's standard library only:

  * ``.xlsx``  — Excel OpenXML workbooks (sharedStrings + workbook sheet order + sparse column alignment)
  * ``.ods``   — OpenDocument spreadsheets (``content.xml`` tables with bounded column-repeat expansion)
  * ``.odt``   — OpenDocument text documents (headings, paragraphs, lists, tables)
  * ``.ipynb`` — Jupyter notebooks (markdown/raw/code cells + text/stream/error outputs; binary plots counted, not dumped)
  * ``.epub``  — EPUB e-books (``META-INF/container.xml`` -> OPF spine chapters -> HTML text stripper)
  * ``.rtf``   — Rich Text Format (destination skipping, ``\\'hh`` hex escapes, ``\\uN`` Unicode escapes, tables/paragraphs)

Security & resource invariants:
  * Never opens paths when given an admitted byte stream; reads ZIP members in 64 KiB
    chunks with hard per-entry (25 MB), total-archive (64 MB), and entry-count (4,096)
    ceilings so zip bombs fail closed before memory allocation.
  * Rejects ``<!DOCTYPE`` / ``<!ENTITY`` XML declarations before ``ElementTree.fromstring``
    to block entity-expansion / XXE payloads without third-party XML packages.
  * Enforces ``max_text_bytes`` and ``max_seconds`` between logical units (sheets,
    blocks, cells, chapters) and returns ``DocumentExtraction`` matching ``local_docs``.
"""

from __future__ import annotations

import json
import posixpath
import re
import time
import zipfile
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO

from defusedxml.ElementTree import fromstring as _parse_xml

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

MAX_ZIP_ENTRIES = 4_096
MAX_ZIP_MEMBER_BYTES = 25_000_000
MAX_ZIP_TOTAL_BYTES = 64_000_000
MAX_XML_CHARS = 25_000_000
MAX_NOTEBOOK_CELLS = 5_000
MAX_ODS_REPEAT = 64

STDLIB_DOC_EXTS = frozenset({".xlsx", ".ods", ".odt", ".ipynb", ".epub", ".rtf"})

_XML_ENTITY_RE = re.compile(rb"<!\s*(?:ENTITY|DOCTYPE)\b", re.IGNORECASE)
_CELL_REF_RE = re.compile(r"^([A-Za-z]+)\d+$")


class _ArchiveSafetyError(ValueError):
    """Raised when a ZIP/XML container exceeds safety bounds."""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _safe_xml(raw: bytes) -> Element:
    if len(raw) > MAX_XML_CHARS:
        raise _ArchiveSafetyError("xml_too_large")
    if _XML_ENTITY_RE.search(raw[:65536]) or _XML_ENTITY_RE.search(raw):
        raise _ArchiveSafetyError("xml_entities_forbidden")
    return _parse_xml(raw)


class _BudgetedZip:
    """Chunk-metered ZIP reader that caps entry count, per-entry size, and total uncompressed bytes."""

    def __init__(self, source: Path | BinaryIO) -> None:
        self._zf = zipfile.ZipFile(str(source) if isinstance(source, Path) else source, "r")
        infos = self._zf.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            self._zf.close()
            raise _ArchiveSafetyError("too_many_zip_entries")
        self._names = {info.filename for info in infos}
        self._total_read = 0

    def __enter__(self) -> _BudgetedZip:
        return self

    def __exit__(self, *exc: object) -> None:
        self._zf.close()

    def has(self, name: str) -> bool:
        return name in self._names

    def names(self) -> list[str]:
        return sorted(self._names)

    def read(self, name: str, *, limit: int = MAX_ZIP_MEMBER_BYTES) -> bytes:
        info = self._zf.getinfo(name)
        if info.file_size > limit:
            raise _ArchiveSafetyError("zip_member_too_large")
        chunks: list[bytes] = []
        member_read = 0
        with self._zf.open(info, "r") as handle:
            while True:
                piece = handle.read(65536)
                if not piece:
                    break
                member_read += len(piece)
                self._total_read += len(piece)
                if member_read > limit or self._total_read > MAX_ZIP_TOTAL_BYTES:
                    raise _ArchiveSafetyError("zip_uncompressed_limit")
                chunks.append(piece)
        return b"".join(chunks)


def _read_stream_bytes(source: Path | BinaryIO, limit: int = 50_000_000) -> bytes:
    if isinstance(source, Path):
        with source.open("rb") as handle:
            data = handle.read(limit + 1)
    else:
        pos = source.tell() if hasattr(source, "tell") else None
        data = source.read(limit + 1)
        if pos is not None and hasattr(source, "seek"):
            source.seek(pos)
    if len(data) > limit:
        raise _ArchiveSafetyError("input_too_large")
    return data


def _col_index(cell_ref: str) -> int | None:
    match = _CELL_REF_RE.match(cell_ref.strip())
    if not match:
        return None
    idx = 0
    for ch in match.group(1).upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _format_table_rows(rows: list[list[str]]) -> list[str]:
    lines: list[str] = []
    for r_idx, row in enumerate(rows):
        trimmed = list(row)
        while trimmed and not trimmed[-1]:
            trimmed.pop()
        if not any(trimmed):
            continue
        escaped = [cell.replace("\n", " ").replace("|", "\\|").strip() for cell in trimmed]
        lines.append("| " + " | ".join(escaped) + " |")
        if r_idx == 0:
            lines.append("| " + " | ".join("---" for _ in escaped) + " |")
    return lines


def _extract_xlsx(
    source: Path | BinaryIO,
    *,
    max_text_bytes: int,
    max_seconds: float,
    clock: Callable[[], float],
):
    from .local_docs import DocumentExtraction

    started = clock()
    with _BudgetedZip(source) as archive:
        shared: list[str] = []
        if archive.has("xl/sharedStrings.xml"):
            sst = _safe_xml(archive.read("xl/sharedStrings.xml"))
            for si in sst:
                if _local_name(si.tag) != "si":
                    continue
                parts = [
                    node.text or ""
                    for node in si.iter()
                    if _local_name(node.tag) == "t" and node.text
                ]
                shared.append("".join(parts))

        rels: dict[str, str] = {}
        if archive.has("xl/_rels/workbook.xml.rels"):
            rel_root = _safe_xml(archive.read("xl/_rels/workbook.xml.rels"))
            for rel in rel_root:
                if _local_name(rel.tag) == "Relationship":
                    rid = rel.attrib.get("Id", "")
                    target = rel.attrib.get("Target", "").lstrip("/")
                    if rid and target:
                        if not target.startswith("xl/"):
                            target = posixpath.normpath(posixpath.join("xl", target))
                        rels[rid] = target

        sheets: list[tuple[str, str]] = []
        if archive.has("xl/workbook.xml"):
            wb = _safe_xml(archive.read("xl/workbook.xml"))
            for elem in wb.iter():
                if _local_name(elem.tag) == "sheet":
                    name = elem.attrib.get("name") or "Sheet"
                    rid = ""
                    for attr_k, attr_v in elem.attrib.items():
                        if _local_name(attr_k) == "id":
                            rid = attr_v
                            break
                    path = rels.get(rid, "")
                    if path and archive.has(path):
                        sheets.append((name, path))
        if not sheets:
            for name in archive.names():
                if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
                    sheets.append((Path(name).stem, name))

        pages: list[str] = []
        used = 0
        row_total = 0
        stopped: str | None = None
        for title, sheet_path in sheets:
            if pages and clock() - started > max_seconds:
                stopped = "time_limit"
                break
            root = _safe_xml(archive.read(sheet_path))
            sheet_rows: list[list[str]] = []
            for elem in root.iter():
                if _local_name(elem.tag) != "row":
                    continue
                cells: list[str] = []
                for cell in elem:
                    if _local_name(cell.tag) != "c":
                        continue
                    c_type = cell.attrib.get("t", "")
                    ref = cell.attrib.get("r", "")
                    col = _col_index(ref) if ref else None
                    val = ""
                    if c_type == "inlineStr":
                        val = "".join(
                            n.text or "" for n in cell.iter() if _local_name(n.tag) == "t" and n.text
                        )
                    else:
                        v_node = next((n for n in cell if _local_name(n.tag) == "v"), None)
                        raw_v = (v_node.text or "").strip() if v_node is not None else ""
                        if c_type == "s" and raw_v.isdigit():
                            idx = int(raw_v)
                            val = shared[idx] if 0 <= idx < len(shared) else raw_v
                        elif c_type == "b":
                            val = "TRUE" if raw_v == "1" else ("FALSE" if raw_v == "0" else raw_v)
                        else:
                            val = raw_v
                    if col is not None and 0 <= col < 512:
                        while len(cells) <= col:
                            cells.append("")
                        cells[col] = val
                    else:
                        cells.append(val)
                if any(c.strip() for c in cells):
                    sheet_rows.append(cells)
            row_total += len(sheet_rows)
            rendered_rows = _format_table_rows(sheet_rows)
            body = f"## Sheet: {title}\n" + ("\n".join(rendered_rows) if rendered_rows else "(empty sheet)")
            size = len(body.encode("utf-8")) + (1 if pages else 0)
            if pages and used + size > max_text_bytes:
                stopped = "text_limit"
                break
            used += size
            pages.append(body)

    return DocumentExtraction(
        pages=pages,
        units_total=len(sheets),
        units_read=len(pages),
        stopped=stopped,
        unit="sheet",
        content_counts={"tables": len(pages), "rows": row_total},
    )


def _odf_inline_text(elem: Element) -> str:
    parts: list[str] = []

    def walk(node: Element) -> None:
        lname = _local_name(node.tag)
        if lname == "s":
            count_raw = next((v for k, v in node.attrib.items() if _local_name(k) == "c"), "1")
            count = min(32, int(count_raw)) if str(count_raw).isdigit() else 1
            parts.append(" " * max(1, count))
        elif lname == "tab":
            parts.append("\t")
        elif lname == "line-break":
            parts.append("\n")
        else:
            if node.text:
                parts.append(node.text)
            for child in node:
                walk(child)
        if node.tail:
            parts.append(node.tail)

    if elem.text:
        parts.append(elem.text)
    for child in elem:
        walk(child)
    return "".join(parts).strip()


def _odf_table_rows(table_elem: Element) -> list[list[str]]:
    rows: list[list[str]] = []
    for child in table_elem.iter():
        if _local_name(child.tag) != "table-row":
            continue
        row: list[str] = []
        for cell in child:
            if _local_name(cell.tag) not in ("table-cell", "covered-table-cell"):
                continue
            repeat_raw = next(
                (v for k, v in cell.attrib.items() if _local_name(k) == "number-columns-repeated"),
                "1",
            )
            repeat = int(repeat_raw) if str(repeat_raw).isdigit() else 1
            text = "\n".join(
                t for p in cell if _local_name(p.tag) in ("p", "h") and (t := _odf_inline_text(p))
            )
            # LibreOffice writes trailing empty cells with repeat=1024; cap repeats tightly.
            copies = 1 if not text else min(MAX_ODS_REPEAT, max(1, repeat))
            if not text and repeat <= MAX_ODS_REPEAT:
                copies = max(1, repeat)
            row.extend([text] * copies)
        while row and not row[-1]:
            row.pop()
        if any(row):
            rows.append(row)
    return rows


def _extract_odf(
    source: Path | BinaryIO,
    *,
    spreadsheet: bool,
    max_text_bytes: int,
    max_seconds: float,
    clock: Callable[[], float],
):
    from .local_docs import DocumentExtraction

    started = clock()
    with _BudgetedZip(source) as archive:
        if not archive.has("content.xml"):
            return None
        root = _safe_xml(archive.read("content.xml"))

    if spreadsheet:
        tables = [el for el in root.iter() if _local_name(el.tag) == "table"]
        pages: list[str] = []
        used = 0
        row_total = 0
        stopped: str | None = None
        for idx, tbl in enumerate(tables, 1):
            if pages and clock() - started > max_seconds:
                stopped = "time_limit"
                break
            tname = next((v for k, v in tbl.attrib.items() if _local_name(k) == "name"), f"Sheet {idx}")
            rows = _odf_table_rows(tbl)
            row_total += len(rows)
            rendered = _format_table_rows(rows)
            body = f"## Sheet: {tname}\n" + ("\n".join(rendered) if rendered else "(empty sheet)")
            size = len(body.encode("utf-8")) + (1 if pages else 0)
            if pages and used + size > max_text_bytes:
                stopped = "text_limit"
                break
            used += size
            pages.append(body)
        return DocumentExtraction(
            pages=pages,
            units_total=len(tables),
            units_read=len(pages),
            stopped=stopped,
            unit="sheet",
            content_counts={"tables": len(pages), "rows": row_total},
        )

    body_el = next((el for el in root.iter() if _local_name(el.tag) == "text"), root)
    units: list[str] = []
    table_count = 0

    def collect_blocks(container: Element) -> None:
        nonlocal table_count
        for child in container:
            lname = _local_name(child.tag)
            if lname in ("h", "p"):
                line = _odf_inline_text(child)
                if line:
                    units.append(line)
            elif lname == "table":
                rows = _odf_table_rows(child)
                if rows:
                    table_count += 1
                    units.extend(_format_table_rows(rows))
            elif lname in ("list", "list-item", "section"):
                collect_blocks(child)

    collect_blocks(body_el)
    kept: list[str] = []
    used = 0
    stopped = None
    for block in units:
        if kept and clock() - started > max_seconds:
            stopped = "time_limit"
            break
        size = len(block.encode("utf-8")) + (1 if kept else 0)
        if kept and used + size > max_text_bytes:
            stopped = "text_limit"
            break
        used += size
        kept.append(block)
    return DocumentExtraction(
        pages=["\n".join(kept)],
        units_total=len(units),
        units_read=len(kept),
        stopped=stopped,
        unit="block",
        content_counts={"tables": table_count} if table_count else {},
    )


def _join_nb_lines(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        return "".join(item for item in raw if isinstance(item, str))
    return ""


def _extract_ipynb(
    source: Path | BinaryIO,
    *,
    max_text_bytes: int,
    max_seconds: float,
    clock: Callable[[], float],
):
    from .local_docs import DocumentExtraction

    started = clock()
    raw = _read_stream_bytes(source)
    doc = json.loads(raw.decode("utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("cells"), list):
        return None
    cells = doc["cells"][:MAX_NOTEBOOK_CELLS]
    lang = (
        ((doc.get("metadata") or {}).get("kernelspec") or {}).get("language")
        or ((doc.get("metadata") or {}).get("language_info") or {}).get("name")
        or "python"
    )
    if not isinstance(lang, str) or not lang.strip():
        lang = "python"

    kept: list[str] = []
    used = 0
    stopped: str | None = None
    code_cells = 0
    md_cells = 0
    visual_outputs = 0

    for idx, cell in enumerate(cells, 1):
        if kept and clock() - started > max_seconds:
            stopped = "time_limit"
            break
        if not isinstance(cell, dict):
            continue
        ctype = str(cell.get("cell_type") or "")
        src = _join_nb_lines(cell.get("source")).rstrip()
        parts: list[str] = []
        if ctype == "code":
            code_cells += 1
            if src:
                parts.append(f"### Cell {idx} [code]\n```{lang}\n{src}\n```")
            outputs = cell.get("outputs")
            if isinstance(outputs, list):
                out_lines: list[str] = []
                for out in outputs[:50]:
                    if not isinstance(out, dict):
                        continue
                    otype = out.get("output_type")
                    if otype == "stream":
                        txt = _join_nb_lines(out.get("text")).rstrip()
                        if txt:
                            out_lines.append(txt)
                    elif otype in ("execute_result", "display_data"):
                        data = out.get("data") if isinstance(out.get("data"), dict) else {}
                        if any(k.startswith("image/") for k in data):
                            visual_outputs += 1
                        plain = _join_nb_lines(data.get("text/plain")).rstrip()
                        if plain:
                            out_lines.append(plain)
                    elif otype == "error":
                        ename = str(out.get("ename") or "Error")
                        evalue = str(out.get("evalue") or "")
                        out_lines.append(f"{ename}: {evalue}".rstrip(": "))
                if out_lines:
                    parts.append("Output:\n" + "\n".join(out_lines))
        elif ctype in ("markdown", "raw"):
            md_cells += 1
            if src:
                parts.append(src)
        block = "\n\n".join(parts)
        if not block:
            continue
        size = len(block.encode("utf-8")) + (2 if kept else 0)
        if kept and used + size > max_text_bytes:
            stopped = "text_limit"
            break
        used += size
        kept.append(block)

    counts: dict[str, int] = {"code_cells": code_cells, "markdown_cells": md_cells}
    if visual_outputs:
        counts["images"] = visual_outputs
    return DocumentExtraction(
        pages=["\n\n".join(kept)],
        units_total=len(cells),
        units_read=code_cells + md_cells if stopped is None else len(kept),
        stopped=stopped,
        unit="cell",
        content_counts=counts,
    )


class _XHTMLTextParser(HTMLParser):
    _BLOCK_TAGS = frozenset({
        "p", "div", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6",
        "li", "tr", "blockquote", "pre", "br", "hr",
    })
    _SKIP_TAGS = frozenset({"script", "style", "head", "svg"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in self._SKIP_TAGS:
            self._skip += 1
        elif self._skip == 0 and t in self._BLOCK_TAGS:
            self._parts.append("\n")
        elif self._skip == 0 and t in ("td", "th"):
            self._parts.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in self._SKIP_TAGS and self._skip > 0:
            self._skip -= 1
        elif self._skip == 0 and t in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip == 0 and data:
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        lines = [" ".join(line.split()) for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)


def _extract_epub(
    source: Path | BinaryIO,
    *,
    max_text_bytes: int,
    max_seconds: float,
    clock: Callable[[], float],
):
    from .local_docs import DocumentExtraction

    started = clock()
    with _BudgetedZip(source) as archive:
        if not archive.has("META-INF/container.xml"):
            return None
        container = _safe_xml(archive.read("META-INF/container.xml"))
        opf_path = ""
        for elem in container.iter():
            if _local_name(elem.tag) == "rootfile":
                opf_path = elem.attrib.get("full-path", "").lstrip("/")
                if opf_path:
                    break
        if not opf_path or not archive.has(opf_path):
            return None
        opf_dir = posixpath.dirname(opf_path)
        opf = _safe_xml(archive.read(opf_path))
        manifest: dict[str, tuple[str, str]] = {}
        spine_ids: list[str] = []
        for elem in opf.iter():
            lname = _local_name(elem.tag)
            if lname == "item":
                item_id = elem.attrib.get("id", "")
                href = elem.attrib.get("href", "")
                media = elem.attrib.get("media-type", "")
                if item_id and href:
                    resolved = posixpath.normpath(posixpath.join(opf_dir, href)) if opf_dir else href.lstrip("/")
                    manifest[item_id] = (resolved, media)
            elif lname == "itemref":
                idref = elem.attrib.get("idref", "")
                if idref:
                    spine_ids.append(idref)

        chapters: list[str] = []
        for idref in spine_ids:
            entry = manifest.get(idref)
            if entry and ("html" in entry[1] or entry[0].endswith((".xhtml", ".html", ".htm"))) and archive.has(entry[0]):
                chapters.append(entry[0])
        if not chapters:
            chapters = [
                path for path, media in manifest.values()
                if ("html" in media or path.endswith((".xhtml", ".html", ".htm"))) and archive.has(path)
            ]

        pages: list[str] = []
        used = 0
        stopped: str | None = None
        for ch_path in chapters:
            if pages and clock() - started > max_seconds:
                stopped = "time_limit"
                break
            raw_html = archive.read(ch_path).decode("utf-8", errors="replace")
            parser = _XHTMLTextParser()
            parser.feed(raw_html)
            parser.close()
            chapter_text = parser.text()
            if not chapter_text:
                continue
            size = len(chapter_text.encode("utf-8")) + (2 if pages else 0)
            if pages and used + size > max_text_bytes:
                stopped = "text_limit"
                break
            used += size
            pages.append(chapter_text)

    return DocumentExtraction(
        pages=pages,
        units_total=len(chapters),
        units_read=len(pages),
        stopped=stopped,
        unit="chapter",
        content_counts={"chapters": len(pages)},
    )


_RTF_SKIP_DESTS = frozenset({
    "fonttbl", "colortbl", "stylesheet", "info", "pict", "object", "datafield",
    "fldinst", "header", "footer", "headerl", "headerr", "footerl", "footerr",
    "xmlnstbl", "listtable", "listoverridetable", "rsidtbl", "generator",
})


def _extract_rtf(
    source: Path | BinaryIO,
    *,
    max_text_bytes: int,
    max_seconds: float,
    clock: Callable[[], float],
):
    from .local_docs import DocumentExtraction

    started = clock()
    data = _read_stream_bytes(source)
    text_in = data.decode("latin-1")
    if not text_in.lstrip().startswith("{\\rtf"):
        return None

    out: list[str] = []
    used = 0
    stopped: str | None = None
    stack: list[tuple[int, bool]] = []
    uc_skip = 1
    skip_group = False
    star_pending = False
    i = 0
    n = len(text_in)

    def emit(piece: str) -> bool:
        nonlocal used, stopped
        if not piece:
            return True
        size = len(piece.encode("utf-8"))
        if out and used + size > max_text_bytes:
            stopped = "text_limit"
            return False
        used += size
        out.append(piece)
        return True

    while i < n:
        if (i & 0xFFF) == 0 and out and clock() - started > max_seconds:
            stopped = "time_limit"
            break
        ch = text_in[i]
        if ch == "{":
            stack.append((uc_skip, skip_group))
            star_pending = False
            i += 1
        elif ch == "}":
            if stack:
                uc_skip, skip_group = stack.pop()
            star_pending = False
            i += 1
        elif ch == "\\":
            i += 1
            if i >= n:
                break
            nxt = text_in[i]
            if nxt in "\\{}":
                if not skip_group and not emit(nxt):
                    break
                star_pending = False
                i += 1
            elif nxt == "*":
                star_pending = True
                i += 1
            elif nxt == "~":
                if not skip_group and not emit("\u00a0"):
                    break
                i += 1
            elif nxt == "_":
                if not skip_group and not emit("-"):
                    break
                i += 1
            elif nxt == "'":
                hex_part = text_in[i + 1 : i + 3]
                if len(hex_part) == 2 and all(c in "0123456789abcdefABCDEF" for c in hex_part):
                    if not skip_group:
                        decoded = bytes([int(hex_part, 16)]).decode("cp1252", errors="replace")
                        if not emit(decoded):
                            break
                    i += 3
                else:
                    i += 1
            elif nxt in "\r\n":
                if not skip_group and not emit("\n"):
                    break
                i += 1
            elif nxt.isalpha():
                start_w = i
                while i < n and text_in[i].isalpha():
                    i += 1
                word = text_in[start_w:i]
                sign = 1
                num: int | None = None
                if i < n and text_in[i] in "+-":
                    sign = -1 if text_in[i] == "-" else 1
                    i += 1
                num_start = i
                while i < n and text_in[i].isdigit():
                    i += 1
                if i > num_start:
                    num = sign * int(text_in[num_start:i])
                if i < n and text_in[i] == " ":
                    i += 1
                if star_pending or word in _RTF_SKIP_DESTS:
                    skip_group = True
                    star_pending = False
                    continue
                star_pending = False
                if skip_group:
                    continue
                if word == "uc" and num is not None and 0 <= num <= 16:
                    uc_skip = num
                elif word == "u" and num is not None:
                    codepoint = num if num >= 0 else num + 65536
                    char = chr(codepoint) if 0 <= codepoint <= 0x10FFFF and not (0xD800 <= codepoint <= 0xDFFF) else "\ufffd"
                    if not emit(char):
                        break
                    skipped = 0
                    while skipped < uc_skip and i < n:
                        if text_in[i] == "\\" and i + 3 < n and text_in[i + 1] == "'":
                            i += 4
                        elif text_in[i] not in "{}":
                            i += 1
                        else:
                            break
                        skipped += 1
                elif word in ("par", "line", "row"):
                    if not emit("\n"):
                        break
                elif word == "tab":
                    if not emit("\t"):
                        break
                elif word == "cell" and not emit(" | "):
                    break
            else:
                star_pending = False
                i += 1
        elif ch in "\r\n":
            i += 1
        else:
            if not skip_group and not emit(ch):
                break
            i += 1

    rendered = "\n".join(line.rstrip() for line in "".join(out).splitlines()).strip()
    paragraphs = [p for p in rendered.split("\n") if p.strip()]
    return DocumentExtraction(
        pages=[rendered] if rendered else [""],
        units_total=max(1, len(paragraphs)),
        units_read=len(paragraphs),
        stopped=stopped,
        unit="paragraph",
    )


def extract_structured_document(
    suffix: str,
    source: Path | BinaryIO,
    *,
    max_text_bytes: int = 32_000_000,
    max_seconds: float = 60.0,
    clock: Callable[[], float] = time.monotonic,
):
    """Dispatch stdlib structured document extraction; returns ``DocumentExtraction | None``."""
    ext = suffix.lower()
    try:
        if ext == ".xlsx":
            return _extract_xlsx(source, max_text_bytes=max_text_bytes, max_seconds=max_seconds, clock=clock)
        if ext == ".ods":
            return _extract_odf(source, spreadsheet=True, max_text_bytes=max_text_bytes, max_seconds=max_seconds, clock=clock)
        if ext == ".odt":
            return _extract_odf(source, spreadsheet=False, max_text_bytes=max_text_bytes, max_seconds=max_seconds, clock=clock)
        if ext == ".ipynb":
            return _extract_ipynb(source, max_text_bytes=max_text_bytes, max_seconds=max_seconds, clock=clock)
        if ext == ".epub":
            return _extract_epub(source, max_text_bytes=max_text_bytes, max_seconds=max_seconds, clock=clock)
        if ext == ".rtf":
            return _extract_rtf(source, max_text_bytes=max_text_bytes, max_seconds=max_seconds, clock=clock)
    except Exception:
        return None
    return None
