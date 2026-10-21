"""
local_docs.py — H12.2 Onboarding "drop folder → private chat with your docs".

One low-friction step: point Jarvis at a local folder, it indexes the documents
into memory **locally** (using whatever embedding backend is configured, with the
hash fallback so it works fully offline), and you can then chat with them. No
cloud hop, no config.

Plain-text formats (.md / .markdown / .txt) are read natively. PDF / DOCX are
best-effort: if the optional parser isn't installed the file is skipped (counted,
never fatal). The ``remember`` callable is injected so this is offline-testable.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, BinaryIO, Callable, Iterator, Optional

logger = logging.getLogger("jarvis.local_docs")

TEXT_EXTS = {".md", ".markdown", ".txt", ".text", ".rst"}
DOC_EXTS = {".pdf", ".docx"}
SUPPORTED_EXTS = TEXT_EXTS | DOC_EXTS

# remember: ``async (text, metadata) -> Optional[str]``
RememberFn = Callable[[str, dict], Awaitable[Optional[str]]]


#: A parser input: a path on disk, or an in-memory binary stream (``file_read`` parses
#: the bounded bytes it read, never the path, so a file that grows after it was
#: measured cannot feed the parser more than was admitted — H444).
DocSource = Path | BinaryIO

#: H444 — the most extracted text one document read may build (UTF-8 bytes). Past it
#: extraction stops at a page boundary and says so, instead of allocating without end.
MAX_EXTRACTED_TEXT_BYTES = 32_000_000
#: H444 — the wall-clock budget for one document's extraction, checked between pages
#: (PDF) and paragraphs (DOCX). Past it extraction stops and says so.
MAX_EXTRACTION_SECONDS = 60.0
#: How many ranges a coverage report lists before it only counts the rest.
MAX_LISTED_RANGES = 16


def _parser_input(source: DocSource) -> Any:
    return str(source) if isinstance(source, Path) else source


def extract_pdf_pages(source: DocSource) -> list[str] | None:
    """Extract each PDF page's text once, or refuse the entire failed traversal."""
    try:
        import pypdf  # type: ignore

        reader = pypdf.PdfReader(_parser_input(source))
        pages: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if not isinstance(text, str):
                return None
            pages.append(text)
        return pages
    except Exception:
        return None  # Missing parser or unreadable/partially failed PDF.


@dataclass
class DocumentExtraction:
    """What one budgeted extraction produced (H444).

    ``pages`` holds the text of each page read (one entry for a DOCX). ``stopped`` is
    ``None`` when the whole document was read, else ``"text_limit"`` or
    ``"time_limit"``: the text is then a true prefix of the document, ending at a
    page (or paragraph) boundary, and ``units_read`` of ``units_total`` were read.
    ``image_pages`` are the 1-based PDF pages whose resources hold an image XObject.
    ``content_counts`` (DOCX) counts the parts read and those a text read cannot
    carry (see :func:`extract_docx_document`).
    """

    pages: list[str]
    units_total: int
    units_read: int
    stopped: str | None = None
    unit: str = "page"
    image_pages: list[int] = field(default_factory=list)
    content_counts: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_pages(cls, pages: list[str], *,
                   image_pages: list[int] | None = None) -> DocumentExtraction:
        return cls(pages=list(pages), units_total=len(pages), units_read=len(pages),
                   image_pages=list(image_pages or []))

    @property
    def text(self) -> str:
        return "\n".join(self.pages)


def _resolved(value: Any) -> Any:
    return value.get_object() if hasattr(value, "get_object") else value


def _has_image_xobject(page: Any) -> bool:
    """True when *page*'s resources name an image XObject (``/Subtype /Image``).

    Reads the resource dictionary only — no image is decoded. Inline images in a
    content stream and images nested inside form XObjects are not seen; a page
    whose structure cannot be read is reported as having none.
    """
    try:
        resources = _resolved(page.get("/Resources"))
        if not resources:
            return False
        xobjects = _resolved(resources.get("/XObject"))
        if not xobjects:
            return False
        return any(_resolved(ref).get("/Subtype") == "/Image" for ref in xobjects.values())
    except Exception:
        return False


def extract_pdf_document(
    source: DocSource,
    *,
    max_text_bytes: int = MAX_EXTRACTED_TEXT_BYTES,
    max_seconds: float = MAX_EXTRACTION_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> DocumentExtraction | None:
    """A PDF's page texts within a text-size and time budget, or ``None`` on failure.

    A failed traversal still refuses as a whole (as :func:`extract_pdf_pages`). A
    budget that runs out is not a failure: the pages read so far come back with
    ``stopped`` naming the budget, never presented as the whole document. The first
    page is always attempted, so a budget can never yield an empty "success".
    """
    try:
        import pypdf  # type: ignore

        started = clock()
        reader = pypdf.PdfReader(_parser_input(source))
        page_list = reader.pages
        try:
            total: int | None = len(page_list)
        except Exception:
            total = None
        pages: list[str] = []
        image_pages: list[int] = []
        used = 0
        stopped: str | None = None
        for number, page in enumerate(page_list, 1):
            if pages and clock() - started > max_seconds:
                stopped = "time_limit"
                break
            text = page.extract_text() or ""
            if not isinstance(text, str):
                return None
            size = len(text.encode("utf-8")) + (1 if pages else 0)
            if pages and used + size > max_text_bytes:
                stopped = "text_limit"
                break
            used += size
            pages.append(text)
            if _has_image_xobject(page):
                image_pages.append(number)
        return DocumentExtraction(
            pages=pages, units_total=total if total is not None else len(pages),
            units_read=len(pages), stopped=stopped, image_pages=image_pages,
        )
    except Exception:
        return None  # Missing parser or unreadable/partially failed PDF.


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_W_P, _W_TBL, _W_TR, _W_TC = _W + "p", _W + "tbl", _W + "tr", _W + "tc"
_W_T, _W_TAB, _W_BR, _W_CR = _W + "t", _W + "tab", _W + "br", _W + "cr"
_W_NB_HYPHEN, _W_TXBX, _W_OBJECT = _W + "noBreakHyphen", _W + "txbxContent", _W + "object"
_W_FOOTNOTE, _W_ENDNOTE = _W + "footnote", _W + "endnote"
#: Wrappers whose children are blocks (or rows, or cells) in their own right.
_W_WRAPPERS = {_W + "sdt", _W + "sdtContent", _W + "customXml", _W + "smartTag"}
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
_M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
_M_MATH = {_M + "oMath", _M + "oMathPara"}
_A_BLIP = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
_V_IMAGEDATA = "{urn:schemas-microsoft-com:vml}imagedata"
_C_CHART = "{http://schemas.openxmlformats.org/drawingml/2006/chart}chart"
_DGM_RELIDS = "{http://schemas.openxmlformats.org/drawingml/2006/diagram}relIds"
#: The relationship types (by suffix) whose parts hold more of the document's text,
#: and the label each of their lines carries.
_DOCX_STORIES = {"/header": "header", "/footer": "footer",
                 "/footnotes": "footnote", "/endnotes": "endnote"}
#: H444 — what a DOCX read counts: the parts it read beside the body paragraphs,
#: and the visual parts a text read cannot carry.
DOCX_READ_KINDS = ("tables", "text_boxes", "headers_footers", "notes")
DOCX_VISUAL_KINDS = ("images", "charts", "diagrams", "embedded_objects")


def _docx_children(element: Any, tags: set[str] | str) -> Iterator[Any]:
    """The children of *element* with one of *tags*, looking through content-control
    and custom-XML wrappers (a row or a paragraph may sit inside one)."""
    wanted = {tags} if isinstance(tags, str) else tags
    for child in element:
        tag = child.tag
        if not isinstance(tag, str):
            continue  # an XML comment or processing instruction
        if tag in wanted:
            yield child
        elif tag in _W_WRAPPERS:
            yield from _docx_children(child, wanted)


def _docx_inline_text(element: Any, out: list[str]) -> None:
    """The visible text of a paragraph's runs. Text boxes are read on their own
    lines (:func:`_docx_textboxes`), a compatibility fallback repeats its choice and
    is skipped, equations are counted rather than flattened, and property elements
    (whose ``w:tab`` is a tab *stop*, not a tab) carry no text."""
    for child in element:
        tag = child.tag
        if not isinstance(tag, str) or tag in (_W_TXBX, _MC_FALLBACK) or tag in _M_MATH:
            continue
        if tag.startswith(_W) and tag.endswith("Pr"):
            continue
        if tag == _W_T:
            out.append(child.text or "")
        elif tag == _W_TAB:
            out.append("\t")
        elif tag in (_W_BR, _W_CR):
            out.append("\n")
        elif tag == _W_NB_HYPHEN:
            out.append("-")
        else:
            _docx_inline_text(child, out)


def _docx_paragraph_text(paragraph: Any) -> str:
    out: list[str] = []
    _docx_inline_text(paragraph, out)
    return "".join(out)


def _docx_textboxes(element: Any) -> Iterator[Any]:
    """Each text box in *element* (not one inside another text box, which the outer
    box's text already holds, nor a compatibility-fallback copy of a box)."""
    for child in element:
        tag = child.tag
        if not isinstance(tag, str) or tag == _MC_FALLBACK:
            continue
        if tag == _W_TXBX:
            yield child
        else:
            yield from _docx_textboxes(child)


def _docx_flat_text(container: Any) -> str:
    """Everything readable in a block container on one line: a table cell, a text
    box or a note, whose paragraphs, nested tables and text boxes are joined by
    spaces (nested table cells by `` / ``)."""
    parts: list[str] = []
    for block in _docx_children(container, {_W_P, _W_TBL}):
        if block.tag == _W_P:
            parts.append(_docx_paragraph_text(block))
            parts.extend(_docx_flat_text(box) for box in _docx_textboxes(block))
        else:
            parts.extend(" / ".join(_docx_flat_text(tc) for tc in _docx_children(tr, _W_TC))
                         for tr in _docx_children(block, _W_TR))
    return " ".join(part.strip() for part in parts if part.strip())


def _docx_row_text(row: Any, *, first: bool) -> str:
    cells = [_docx_flat_text(tc).replace("|", "\\|").replace("\n", " ")
             for tc in _docx_children(row, _W_TC)]
    line = "| " + " | ".join(cells) + " |"
    return line + "\n|" + " --- |" * len(cells) if first else line


def _docx_units(container: Any, label: str, counts: dict[str, int]) -> Iterator[Callable[[], str]]:
    """One deferred renderer per block of *container*, in document order: a
    paragraph (with any text box it anchors on following lines), or one table row.
    Rendering is deferred so the time budget is checked between blocks."""
    prefix = f"[{label}] " if label else ""
    for block in _docx_children(container, {_W_P, _W_TBL}):
        if block.tag == _W_P:
            boxes = list(_docx_textboxes(block))
            counts["text_boxes"] += len(boxes)

            def paragraph(block: Any = block, boxes: list[Any] = boxes) -> str:
                lines = [prefix + _docx_paragraph_text(block)]
                lines.extend(f"{prefix}[text box] {_docx_flat_text(box)}" for box in boxes)
                return "\n".join(lines)

            yield paragraph
        else:
            counts["tables"] += 1
            for index, row in enumerate(_docx_children(block, _W_TR)):
                yield lambda row=row, first=index == 0: prefix + _docx_row_text(row, first=first)


def _docx_count_visuals(element: Any, counts: dict[str, int]) -> None:
    """Count what a text read cannot carry. A compatibility fallback (a copy of the
    choice beside it) is not counted again, and an OLE object counts once — its
    preview picture is the object itself, not another image."""
    for child in element:
        tag = child.tag
        if not isinstance(tag, str) or tag == _MC_FALLBACK:
            continue
        if tag == _W_OBJECT:
            counts["embedded_objects"] += 1
            continue
        if tag in _M_MATH:
            counts["equations"] += 1
            continue
        if tag in (_A_BLIP, _V_IMAGEDATA):
            counts["images"] += 1
        elif tag == _C_CHART:
            counts["charts"] += 1
        elif tag == _DGM_RELIDS:
            counts["diagrams"] += 1
        _docx_count_visuals(child, counts)


def _docx_story_root(part: Any) -> Any:
    element = getattr(part, "element", None)
    if element is not None:
        return element
    from docx.oxml.parser import parse_xml  # type: ignore

    return parse_xml(part.blob)


def _docx_stories(document: Any) -> tuple[list[tuple[str, Any]], list[tuple[str, Any]]]:
    """Header roots (read before the body), then footer and foot/endnote roots
    (read after it), as ``(label, root)``."""
    headers: list[tuple[str, Any]] = []
    footers: list[tuple[str, Any]] = []
    notes: list[tuple[str, Any]] = []
    for rel in list(getattr(document.part, "rels", {}).values()):
        reltype = str(getattr(rel, "reltype", ""))
        label = next((name for suffix, name in _DOCX_STORIES.items()
                      if reltype.endswith(suffix)), None)
        if label is None or getattr(rel, "is_external", False):
            continue
        root = _docx_story_root(rel.target_part)
        {"header": headers, "footer": footers}.get(label, notes).append((label, root))
    return headers, footers + notes


def extract_docx_document(
    source: DocSource,
    *,
    max_text_bytes: int = MAX_EXTRACTED_TEXT_BYTES,
    max_seconds: float = MAX_EXTRACTION_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> DocumentExtraction | None:
    """A DOCX's text in document order within the same budgets, or ``None`` on failure.

    H444 — the body is walked as Word lays it out: paragraphs and tables (each row a
    ``|``-separated line, the first followed by a Markdown rule), text boxes on their
    own ``[text box]`` lines, content controls looked through. Header parts come
    first (``[header]``), footer parts last (``[footer]``), then foot- and endnotes
    (``[footnote N]``). ``content_counts`` names what was read (tables, text boxes,
    headers/footers, notes) and what a text read cannot carry: images, charts,
    SmartArt diagrams, embedded objects and equations. A budget stops between
    blocks (a paragraph or one table row).
    """
    try:
        import docx  # type: ignore

        started = clock()
        document = docx.Document(_parser_input(source))
        counts = dict.fromkeys(DOCX_READ_KINDS + DOCX_VISUAL_KINDS + ("equations",), 0)
        before, after = _docx_stories(document)
        units: list[Callable[[], str]] = []
        for label, root in before:
            units.extend(_docx_units(root, label, counts))
        units.extend(_docx_units(document.element.body, "", counts))
        for label, root in after:
            if label == "footer":
                units.extend(_docx_units(root, label, counts))
                continue
            for note in _docx_children(root, _W_FOOTNOTE if label == "footnote" else _W_ENDNOTE):
                if note.get(_W + "type") not in (None, "normal"):
                    continue  # the separator lines Word draws above the notes
                counts["notes"] += 1
                units.append(lambda note=note, label=label:
                             f"[{label} {note.get(_W + 'id')}] {_docx_flat_text(note)}")
        counts["headers_footers"] = sum(1 for label, _ in before + after
                                        if label in ("header", "footer"))
        for _, root in [*before, ("", document.element.body), *after]:
            _docx_count_visuals(root, counts)
        kept: list[str] = []
        used = 0
        stopped: str | None = None
        for unit in units:
            if kept and clock() - started > max_seconds:
                stopped = "time_limit"
                break
            text = unit()
            size = len(text.encode("utf-8")) + (1 if kept else 0)
            if kept and used + size > max_text_bytes:
                stopped = "text_limit"
                break
            used += size
            kept.append(text)
        return DocumentExtraction(
            pages=["\n".join(kept)], units_total=len(units), units_read=len(kept),
            stopped=stopped, unit="block", content_counts=counts,
        )
    except Exception:
        return None


#: A page needs this many non-space characters before its quality is judged, and is
#: garbled when at least this share of them is unusable (or ``(cid:N)`` glyph codes).
GARBLED_MIN_CHARS = 20
GARBLED_RATIO = 0.3
_CID = re.compile(r"\(cid:\d+\)")


def _unusable_char(char: str) -> bool:
    """The replacement mark a decoder leaves for an unmapped byte, and control,
    private-use (where a PDF font without a ToUnicode map often extracts to),
    surrogate and unassigned code points."""
    if char == "\ufffd":
        return True
    return unicodedata.category(char) in ("Cc", "Co", "Cs", "Cn")


def page_text_garbled(text: str) -> bool:
    """True when *text* is mostly characters a reader cannot use (H444).

    A heuristic over the extracted text itself: it never looks at the page image,
    so well-formed but wrong text (a bad font encoding onto real letters) is not
    caught.
    """
    cid_chars = sum(len(match) for match in _CID.findall(text))
    chars = [c for c in _CID.sub("", text) if not c.isspace()]
    considered = len(chars) + cid_chars
    if considered < GARBLED_MIN_CHARS:
        return False
    bad = sum(1 for c in chars if _unusable_char(c)) + cid_chars
    return bad / considered >= GARBLED_RATIO


def page_ranges(numbers: list[int], *, limit: int = MAX_LISTED_RANGES) -> dict:
    """Group ascending 1-based page *numbers* into ranges; list the first *limit*."""
    ranges: list[dict] = []
    count = 0
    start: int | None = None
    prev = 0
    for number in [*numbers, None]:
        if start is not None and number == prev + 1:
            prev = number
            continue
        if start is not None:
            count += 1
            if len(ranges) < limit:
                ranges.append({"start_page": start, "end_page": prev})
        if number is not None:
            start = prev = number
    omitted = count - len(ranges)
    return {"range_count": count, "ranges": ranges, "omitted_range_count": omitted,
            "ranges_truncated": omitted > 0}


def pdf_coverage_warning(pages: list[str]) -> dict | None:
    """Describe significant gaps in extracted PDF text, never inferred visuals.

    Two kinds of unusable page are counted: pages with no text at all (``gaps``,
    grouped, each naming the nearest prior text) and pages whose text is mostly
    unusable characters (``garbled_ranges``, present only when there are any; H444 —
    see :func:`page_text_garbled`).
    The warning appears when the two together pass the threshold: over 20 % of the
    pages, or ten pages or more.
    """
    total = len(pages)
    missing = 0
    gap_count = 0
    gaps: list[dict] = []
    gap_start: int | None = None
    last_text_page: int | None = None
    last_after = ""
    last_after_truncated = False
    gap_after_page: int | None = None
    gap_after = ""
    gap_after_truncated = False

    def close_gap(end_page: int) -> None:
        nonlocal gap_count
        gap_count += 1
        if len(gaps) < MAX_LISTED_RANGES:
            gaps.append({
                "start_page": gap_start,
                "end_page": end_page,
                "after_page": gap_after_page,
                "after": gap_after,
                "after_truncated": gap_after_truncated,
            })

    for number, text in enumerate(pages, 1):
        if not text.strip():
            missing += 1
            if gap_start is None:
                gap_start = number
                gap_after_page = last_text_page
                gap_after = last_after
                gap_after_truncated = last_after_truncated
            continue
        if gap_start is not None:
            close_gap(number - 1)
            gap_start = None
        trimmed = text.rstrip()
        last_text_page = number
        last_after = trimmed[-160:]
        last_after_truncated = len(trimmed) > 160
    if gap_start is not None:
        close_gap(total)
    garbled = [number for number, text in enumerate(pages, 1)
               if text.strip() and page_text_garbled(text)]
    unusable = missing + len(garbled)
    if not total or (unusable * 5 <= total and unusable < 10):
        return None
    omitted = gap_count - len(gaps)
    garbled_ranges = page_ranges(garbled)
    garbled_fields = {
        "pages_with_garbled_text": len(garbled),
        "garbled_ranges": garbled_ranges["ranges"],
        "omitted_garbled_range_count": garbled_ranges["omitted_range_count"],
    } if garbled else {}
    return {
        "reason": "pdf_text_layer_gaps",
        "detail": (
            "Some PDF pages yielded no extractable text. Do not assume the document "
            "is silent on a topic; inspect only the relevant page gaps."
        ),
        "total_pages": total,
        "pages_without_text": missing,
        "gap_count": gap_count,
        "gaps": gaps,
        "omitted_gap_count": omitted,
        "gaps_truncated": omitted > 0,
        **garbled_fields,
    }


def extract_text(path: Path) -> Optional[str]:
    """Return the document's text, or None if unreadable / parser missing."""
    ext = path.suffix.lower()
    if ext in TEXT_EXTS:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            logger.debug("read failed for %s: %s", path, exc)
            return None
    if ext == ".pdf":
        pages = extract_pdf_pages(path)
        return "\n".join(pages) if pages is not None else None
    if ext == ".docx":
        try:
            import docx  # type: ignore
            return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
        except Exception:
            return None
    return None


def chunk_text(text: str, chunk_words: int = 400, overlap: int = 40) -> list[str]:
    """Split text into ~chunk_words word windows with a small overlap."""
    words = text.split()
    if not words:
        return []
    if len(words) <= chunk_words:
        return [" ".join(words)]
    step = max(1, chunk_words - overlap)
    chunks = []
    for start in range(0, len(words), step):
        chunk = words[start:start + chunk_words]
        if chunk:
            chunks.append(" ".join(chunk))
        if start + chunk_words >= len(words):
            break
    return chunks


class LocalDocsIndexer:
    def __init__(self, remember: RememberFn, chunk_words: int = 400) -> None:
        self.remember = remember
        self.chunk_words = chunk_words

    async def index(self, folder: str | Path) -> dict:
        """Index every supported document under *folder* (recursively).

        *folder* is a **trusted** path: it comes from owner configuration, not
        from a request (the endpoint selects a pre-configured folder by key), so
        there is no request-controlled path expression here.
        """
        root = Path(folder).expanduser()
        if not root.exists() or not root.is_dir():
            return {"error": f"not a folder: {folder}"}

        # Walk + read + PDF/DOCX-parse + chunk are all blocking; run them in a
        # worker thread so indexing a large drop folder can't freeze the event
        # loop (this is awaited directly by the onboarding route). Only the async
        # remember() writes stay on the loop.
        parsed, files_skipped, skipped = await asyncio.to_thread(self._collect, root)

        files_indexed = 0
        chunks_total = 0
        for rel, chunks in parsed:
            for i, chunk in enumerate(chunks):
                await self.remember(
                    chunk,
                    {"source": "local_docs", "file": rel, "chunk": i},
                )
            files_indexed += 1
            chunks_total += len(chunks)

        return {
            "folder": str(root),
            "files_indexed": files_indexed,
            "files_skipped": files_skipped,
            "chunks": chunks_total,
            "skipped": skipped[:50],
        }

    def _collect(self, root: Path) -> tuple[list[tuple[str, list[str]]], int, list[str]]:
        """Blocking walk/extract/chunk of *root*; safe to run in a thread.

        Returns ``([(rel_path, chunks)…], files_skipped, skipped_names)``.
        """
        parsed: list[tuple[str, list[str]]] = []
        files_skipped = 0
        skipped: list[str] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTS:
                continue
            text = extract_text(path)
            if not text or not text.strip():
                files_skipped += 1
                skipped.append(path.name)
                continue
            rel = str(path.relative_to(root))
            parsed.append((rel, chunk_text(text, self.chunk_words)))
        return parsed, files_skipped, skipped
