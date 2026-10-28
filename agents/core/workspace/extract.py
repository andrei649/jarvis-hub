"""Text extraction from uploaded workspace documents (spec §6 "Uploads").

Every file handled here comes from an employee's browser and is parsed on the hub
host, so each format is opened with the narrowest safe tool:

* Office Open XML (``.docx`` / ``.xlsx``) is a ZIP package. It is unpacked only through
  :func:`agents.core.archive_safe.extract_zip_bytes` — member-count and byte caps,
  traversal and link refusal — into a private temporary directory, and its XML parts
  are parsed with ``defusedxml`` with DTDs forbidden, so entity expansion and external
  entities fail as ``invalid_file`` instead of reaching the parser. The large parts (the
  document body, worksheets, shared strings) are read incrementally, one paragraph,
  table, cell or string at a time, and everything already read is dropped: a parsed
  element costs ~100 bytes, so building the whole tree of a 100 MiB part — a few KiB
  once deflated — would take gigabytes. Every tree that is built (a small part, or one
  block of a large one) is capped at :data:`MAX_XML_NODES` elements and
  :data:`MAX_XML_DEPTH` levels, and the deadline is checked while parsing.
* PDFs are read with ``pypdf``, at most :data:`MAX_PDF_PAGES` pages. A PDF that opens
  without a password (owner restrictions only) is read like any viewer would read it;
  one that needs a password fails as ``encrypted_pdf``.
* Text formats (``.txt``, ``.md``, ``.csv``) are decoded as UTF-8 (with or without a
  BOM), else as cp1250 — the Windows code page Romanian offices still export CSV in.

By default extraction runs on a small thread pool of its own, bounded at
:data:`EXTRACT_TIMEOUT_SECONDS`, and the worker also checks that deadline between pages,
rows and sheets. A parser stuck within one page cannot be stopped in that mode.
With ``NERVA_WORKSPACE_KILLABLE_EXTRACTION=1`` (default off), PDF/DOCX instead use
killable children with a POSIX address-space cap where supported; see
:mod:`.extract_process`. Optional OCR is available only in that child.
Every failure is an
:class:`ExtractionError` carrying one stable ``code`` from :data:`ERROR_CODES`; the
document row stores it and the UI translates it.

Tables (DOCX tables, every XLSX sheet, CSV files) are rendered as Markdown tables with
the first row as the header, because both the retrieval index and the model read
them as text, and a Markdown table keeps rows and columns legible to both.
"""

from __future__ import annotations

import asyncio
import codecs
import csv
import functools
import io
import logging
import math
import posixpath
import re
import shutil
import signal
import sys
import tempfile
import threading
import time
import unicodedata
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import ParseError, iterparse
from pypdf import PasswordType, PdfReader

from agents.core.archive_safe import ArchiveLimits, ArchiveRejected, extract_zip_bytes
from agents.core.env_config import env_flag, env_str, truthy

logger = logging.getLogger("nerva.workspace.extract")

#: Accepted kinds (the lower-cased extension without its dot) and their MIME types.
MIME_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "txt": "text/plain",
    "md": "text/markdown",
}
ALLOWED_EXTENSIONS: tuple[str, ...] = tuple(f".{kind}" for kind in MIME_TYPES)

MAX_PDF_PAGES = 500
MAX_OCR_PAGES = 50
OCR_PAGE_TIMEOUT_SECONDS = 20.0
OCR_RENDER_SCALE = 2.0
EXTRACT_TIMEOUT_SECONDS = 60.0
#: Upper bound on the extracted text of one document (about 4 000 dense pages). Beyond
#: it the index and every prompt built from it would be dominated by one file.
MAX_TEXT_CHARS = 10_000_000
OOXML_LIMITS = ArchiveLimits(max_members=2000, max_bytes=100 * 1024 * 1024)
MAX_SHEET_COLUMNS = 16_384  # Excel's own limit (column XFD)
#: Elements in one parsed tree: a small part, or one paragraph / table / cell / shared
#: string of a large one (~50-150 MB at most). A 5 000-row Word table fits.
MAX_XML_NODES = 500_000
#: Nesting depth of any XML part; real documents stay far below (nested tables, text
#: boxes and content controls included).
MAX_XML_DEPTH = 256
_TICK_EVERY_NODES = 4096

#: Every code an extraction failure can carry (stored in ``documents.error``).
ERROR_CODES = frozenset({
    "invalid_file", "encrypted_pdf", "too_many_pages", "no_text", "timeout", "too_much_text",
})

_OOXML_MARKERS = {"docx": b"word/", "xlsx": b"xl/"}
_ZIP_MAGIC = b"PK\x03\x04"
_PDF_MAGIC = b"%PDF-"
_PDF_HEADER_WINDOW = 1024  # readers accept the header anywhere in the first KiB
_SNIFF_BYTES = 8192
_UTF16_BOMS = (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)
_CSV_DELIMITERS = ",;\t|"
# csv.Sniffer's regexes backtrack quadratically on quote-heavy input and, like every
# regex, hold the GIL while they run (a crafted 16 KiB sample froze the hub for 5 s), so
# it only ever sees the first complete lines of the first 4 KiB.
_CSV_SNIFF_CHARS = 4096
_CSV_SNIFF_LINES = 20
#: Excel caps number format codes at 255 characters; longer ones are cut before parsing.
_MAX_FORMAT_CODE = 255
_TICK_EVERY_ROWS = 256

# Text cleaning: line separators become newlines; other control characters, lone
# surrogates, BOMs, soft hyphens and zero-width spaces are dropped.
_LINE_BREAKS = re.compile(r"[\x0b\x0c\x85\u2028\u2029]")
_DROPPED = re.compile(r"[\x00-\x08\x0e-\x1f\x7f-\x9f\u00ad\u200b\ud800-\udfff\ufeff\ufffe\uffff]")
_INNER_SPACES = re.compile(r"(?<=\S) {2,}")
_BLANK_LINES = re.compile(r"\n{3,}")
_HAS_WORD = re.compile(r"[^\W_]")
_CELL_REF = re.compile(r"([A-Za-z]{1,3})")
# Spreadsheet number formats: literal text, escapes, padding/fill and [bracketed]
# sections carry no date or time meaning.
_FORMAT_LITERALS = re.compile(r'"[^"]*"|\\.|[_*].|\[[^\]]*\]')
_BUILTIN_DATE_FORMATS = frozenset({14, 15, 16, 17, *range(27, 37), *range(50, 59)})
_BUILTIN_DATETIME_FORMATS = frozenset({22})
_BUILTIN_TIME_FORMATS = frozenset({18, 19, 20, 21, 45, 46, 47})
_BUILTIN_PERCENT_FORMATS = frozenset({9, 10})
_MAX_EXCEL_SERIAL = 2_958_465  # 9999-12-31

#: Extraction is CPU-bound pure Python, so more threads add no throughput under the
#: GIL; a pool of its own keeps a burst of large uploads from filling the default
#: executor that password hashing and the rest of the hub share.
EXTRACTION_THREADS = 2
_POOL = ThreadPoolExecutor(max_workers=EXTRACTION_THREADS, thread_name_prefix="nerva-ws-extract")


class ExtractionError(Exception):
    """An upload that cannot be turned into text; ``code`` is stored on the document.

    ``detail`` is for the server log only (it may name a part of the user's file);
    ``page_count`` is kept when the failure happened after the pages were counted.
    """

    def __init__(self, code: str, detail: str = "", *, page_count: int | None = None) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.page_count = page_count


@dataclass(frozen=True)
class Segment:
    """A run of extracted text; ``page`` is the 1-based PDF page, else ``None``."""

    page: int | None
    text: str


@dataclass(frozen=True)
class Extracted:
    """The text of one document, in reading order."""

    segments: tuple[Segment, ...]
    page_count: int | None
    #: Enforced isolation limits; empty for the legacy pool. Platform gaps are explicit.
    limits: tuple[str, ...] = ()

    @property
    def char_count(self) -> int:
        return sum(len(segment.text) for segment in self.segments)


class _XmlNode(Protocol):
    """The slice of ``xml.etree`` elements this module reads (defusedxml returns them)."""

    tag: str
    text: str | None

    def __iter__(self) -> Iterator[_XmlNode]: ...

    def get(self, key: str, default: str | None = None) -> str | None: ...

    def items(self) -> Sequence[tuple[str, str]]: ...

    def remove(self, child: _XmlNode) -> None: ...


class _Guard:
    """The deadline and the text budget of one extraction, checked as it goes."""

    def __init__(self, seconds: float | None, max_chars: int) -> None:
        self._deadline = None if seconds is None else time.monotonic() + seconds
        self._chars_left = max_chars

    def tick(self) -> None:
        """``timeout`` once the deadline has passed (called between pages, rows, sheets)."""
        if self._deadline is not None and time.monotonic() > self._deadline:
            raise ExtractionError("timeout", "extraction ran past its deadline")

    def remaining(self) -> float | None:
        """Seconds until the document deadline, if one exists."""
        return None if self._deadline is None else max(0.0, self._deadline - time.monotonic())

    def spend(self, chars: int) -> None:
        """``too_much_text`` once the document's text exceeds :data:`MAX_TEXT_CHARS`."""
        self._chars_left -= chars
        if self._chars_left < 0:
            raise ExtractionError("too_much_text", "the document holds too much text")


# ── kinds, magic numbers, decoding ───────────────────────────────────────────────────

def kind_for_filename(filename: str) -> str | None:
    """The kind of *filename* by its extension (case-insensitive), or ``None``."""
    kind = posixpath.splitext(filename)[1].lower().lstrip(".")
    return kind if kind in MIME_TYPES else None


def content_matches(kind: str, data: bytes) -> bool:
    """Whether *data* looks like a *kind* file (the magic-number check of §6).

    PDF needs ``%PDF-`` in its first KiB; DOCX/XLSX must be a ZIP naming
    ``[Content_Types].xml`` and their own part folder (a renamed workbook is not a
    document); text kinds must not be binary — no NUL byte early on unless a UTF-16 BOM
    explains it, and not a PDF or ZIP under a text extension.
    """
    if kind == "pdf":
        return _PDF_MAGIC in data[:_PDF_HEADER_WINDOW]
    if kind in _OOXML_MARKERS:
        return (data.startswith(_ZIP_MAGIC) and b"[Content_Types].xml" in data
                and _OOXML_MARKERS[kind] in data)
    if kind not in MIME_TYPES:
        return False
    head = data[:_SNIFF_BYTES]
    if head.startswith(_UTF16_BOMS):
        return True
    return not head.startswith((_PDF_MAGIC, _ZIP_MAGIC)) and b"\x00" not in head


def decode_text(data: bytes) -> str:
    """Bytes of a text file → ``str``: UTF-8 (BOM or not), UTF-16 with a BOM, else cp1250.

    A UTF-8 file with a handful of stray bytes stays UTF-8 (those bytes become U+FFFD):
    re-reading all of it as cp1250 would garble every diacritic instead.
    """
    if data.startswith(codecs.BOM_UTF8):
        return data[len(codecs.BOM_UTF8):].decode("utf-8", errors="replace")
    if data.startswith(_UTF16_BOMS):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        lenient = data.decode("utf-8", errors="replace")
        replaced = lenient.count("\ufffd")
        multibyte = len(lenient) - len(lenient.encode("ascii", "ignore")) - replaced
        if multibyte > replaced * 20:
            return lenient
        return data.decode("cp1250", errors="replace")


def _strip_line_ends(text: str) -> str:
    """*text* without spaces and tabs at the end of its lines.

    Done line by line: the regex ``[ \t]+\n`` backtracks quadratically over a long run
    of blanks with no line break after it, holding the GIL — a 1 MB file of tabs would
    freeze every thread of the hub for half an hour.
    """
    return "\n".join(line.rstrip(" \t") for line in text.split("\n"))


def clean_text(text: str) -> str:
    """Normalize extracted text: NFC, ``\\n`` line ends, no control characters, tidy spaces."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _DROPPED.sub("", _LINE_BREAKS.sub("\n", text))
    text = unicodedata.normalize("NFC", text).replace("\u00a0", " ")
    text = _strip_line_ends(_INNER_SPACES.sub(" ", text))
    return _BLANK_LINES.sub("\n\n", text).strip()


def _table_cell(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")


def _row_line(cells: Sequence[str]) -> str:
    return "|" + "|".join(f" {cell} " if cell else " " for cell in cells) + "|"


def markdown_table(rows: Sequence[Sequence[str]]) -> str:
    """*rows* as a Markdown table (first row = header); empty rows and columns dropped."""
    cleaned = [[_table_cell(cell) for cell in row] for row in rows]
    cleaned = [row for row in cleaned if any(row)]
    if not cleaned:
        return ""
    width = max(len(row) for row in cleaned)
    used = [col for col in range(width) if any(col < len(row) and row[col] for row in cleaned)]
    table = [[row[col] if col < len(row) else "" for col in used] for row in cleaned]
    lines = [_row_line(table[0]), _row_line(["---"] * len(used))]
    lines.extend(_row_line(row) for row in table[1:])
    return "\n".join(lines)


def _single(text: str) -> tuple[Segment, ...]:
    return (Segment(None, text),) if text else ()


# ── PDF ──────────────────────────────────────────────────────────────────────────────

def _needs_password(reader: PdfReader) -> bool:
    """True unless the PDF opens with the empty user password (owner restrictions only)."""
    try:
        return reader.decrypt("") == PasswordType.NOT_DECRYPTED
    except Exception as exc:  # unsupported algorithm or a damaged encryption dictionary
        logger.info("PDF decryption refused (%s)", type(exc).__name__)
        return True


def _page_text(reader: PdfReader, index: int) -> str:
    try:
        return reader.pages[index].extract_text() or ""
    except MemoryError:
        # A resource ceiling is a document failure, never a silently omitted page.
        raise
    except Exception as exc:  # one damaged page must not lose the whole document
        logger.warning("PDF page %d could not be read (%s); it is skipped",
                       index + 1, type(exc).__name__)
        return ""


def _pdf(data: bytes, guard: _Guard, *, allow_ocr: bool = False,
         progress: Callable[[str, int, float, int], None] | None = None) -> Extracted:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and _needs_password(reader):
            raise ExtractionError("encrypted_pdf", "the PDF needs a password")
        count = len(reader.pages)
    except ExtractionError:
        raise
    except Exception as exc:  # pypdf raises many types on malformed input
        raise ExtractionError("invalid_file", f"unreadable PDF ({type(exc).__name__})") from exc
    if count > MAX_PDF_PAGES:
        raise ExtractionError("too_many_pages", f"{count} pages", page_count=count)
    segments: list[Segment] = []
    for index in range(count):
        guard.tick()
        text = clean_text(_page_text(reader, index))
        guard.spend(len(text))
        if text:
            segments.append(Segment(index + 1, text))
    extracted = Extracted(tuple(segments), page_count=count)
    if allow_ocr and not any(_HAS_WORD.search(segment.text) for segment in segments):
        return _ocr_pdf(data, count, guard, progress=progress) or extracted
    return extracted


@contextmanager
def _ocr_render_limit(seconds: float) -> Iterator[None]:
    """Interrupt a POSIX render at its page deadline; the child owns this timer."""
    if not hasattr(signal, "setitimer") or threading.current_thread() is not threading.main_thread():
        yield
        return
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_remaining, previous_interval = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()

    def expired(signum: int, frame: object) -> None:
        raise TimeoutError("OCR render exhausted the page budget")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_remaining > 0:
            left = max(1e-6, previous_remaining - (time.monotonic() - started))
            signal.setitimer(signal.ITIMER_REAL, left, previous_interval)


def _ocr_engine() -> Callable[[bytes, int, float], str] | None:
    """Load the optional local renderer and engine only inside the extraction child."""
    try:
        import pypdfium2
        import pytesseract
    except ImportError:
        return None
    command = getattr(getattr(pytesseract, "pytesseract", None), "tesseract_cmd", "tesseract")
    if shutil.which(command) is None:
        return None
    lang = env_str("NERVA_WORKSPACE_OCR_LANG").strip() or "eng"

    def read(data: bytes, index: int, seconds: float) -> str:
        started = time.monotonic()
        document = None
        try:
            with _ocr_render_limit(seconds):
                document = pypdfium2.PdfDocument(data)
                image = document[index].render(scale=OCR_RENDER_SCALE).to_pil()
            remaining = seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("OCR render exhausted the page budget")
            # pytesseract passes this float to subprocess timeout. Never round a
            # tiny remaining deadline up to a whole second.
            return pytesseract.image_to_string(image, lang=lang, timeout=remaining)
        finally:
            if document is not None:
                document.close()

    return read


def _ocr_pdf(data: bytes, count: int, guard: _Guard, *,
             progress: Callable[[str, int, float, int], None] | None = None) -> Extracted | None:
    """OCR all pages or fail; no successful result may silently omit a page."""
    if sys.platform == "win32":
        # Ordinary/synchronous Windows extraction cannot claim ownership from
        # a flag. Only the verified Job child enters this private scope.
        from agents.core.workspace.win_job_process import in_owned_child

        if not in_owned_child():
            return None
    if not (env_flag("NERVA_WORKSPACE_OCR", False)
            and env_flag("NERVA_WORKSPACE_KILLABLE_EXTRACTION", False)):
        return None
    # A native renderer requires a deadline enforced outside this process.
    if progress is None:
        return None
    engine = _ocr_engine()
    if engine is None:
        logger.info("OCR requested but no local engine is installed")
        return None
    if count > MAX_OCR_PAGES:
        raise ExtractionError("too_many_pages", f"{count} pages exceed the OCR cap",
                              page_count=count)
    segments: list[Segment] = []
    for index in range(count):
        guard.tick()
        left = guard.remaining()
        seconds = OCR_PAGE_TIMEOUT_SECONDS if left is None else min(OCR_PAGE_TIMEOUT_SECONDS, left)
        if seconds <= 0:
            raise ExtractionError("timeout", "OCR document deadline", page_count=count)
        started = time.monotonic()
        progress("page_start", index + 1, started + seconds, count)
        try:
            raw = engine(data, index, seconds)
        except MemoryError:
            raise
        except TimeoutError as exc:
            raise ExtractionError("timeout", "OCR page deadline", page_count=count) from exc
        except Exception as exc:
            raise ExtractionError("invalid_file", f"OCR page failed ({type(exc).__name__})",
                                  page_count=count) from exc
        if time.monotonic() - started > seconds:
            raise ExtractionError("timeout", "OCR page deadline", page_count=count)
        progress("page_done", index + 1, started + seconds, count)
        guard.tick()
        text = clean_text(raw or "")
        guard.spend(len(text))
        if not _HAS_WORD.search(text):
            if segments:
                raise ExtractionError("no_text", "OCR did not cover every page",
                                      page_count=count)
            # If a later page has text, still fail the whole document below.
            segments.append(Segment(index + 1, ""))
        else:
            segments.append(Segment(index + 1, text))
    if any(not _HAS_WORD.search(segment.text) for segment in segments):
        raise ExtractionError("no_text", "OCR did not cover every page", page_count=count)
    return Extracted(tuple(segments), page_count=count, limits=("ocr",))


# ── Office Open XML packages ─────────────────────────────────────────────────────────

def _local(tag: object) -> str:
    """``{namespace}name`` → ``name``: transitional and strict OOXML read the same."""
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _children(node: _XmlNode, name: str) -> Iterator[_XmlNode]:
    return (child for child in node if _local(child.tag) == name)


def _first(node: _XmlNode, name: str) -> _XmlNode | None:
    return next(_children(node, name), None)


def _attr(node: _XmlNode, name: str) -> str | None:
    """The attribute whose local name is *name*, whatever its namespace."""
    for key, value in node.items():
        if _local(key) == name:
            return value
    return None


def _resolve_target(source: str, target: str) -> str | None:
    """A relationship target as a package part name, or ``None`` when it escapes."""
    joined = target.lstrip("/") if target.startswith("/") else posixpath.join(
        posixpath.dirname(source), target)
    normalized = posixpath.normpath(joined)
    if normalized in (".", "..") or normalized.startswith("../"):
        return None
    return normalized


def _too_many_nodes(name: str) -> ExtractionError:
    return ExtractionError("too_much_text", f"{name} holds more than {MAX_XML_NODES} elements")


def _parse_events(path: Path, name: str, guard: _Guard) -> Iterator[tuple[str, _XmlNode]]:
    """``("start" | "end", element)`` for the XML part at *path*, read incrementally.

    DTDs are refused, nesting beyond :data:`MAX_XML_DEPTH` is ``invalid_file`` and the
    deadline is checked every few thousand elements, so neither memory nor time grows
    unchecked inside a single part.
    """
    depth = 0
    started = 0
    try:
        with path.open("rb") as handle:
            for event, node in iterparse(handle, events=("start", "end"), forbid_dtd=True):
                if event == "start":
                    depth += 1
                    started += 1
                    if depth > MAX_XML_DEPTH:
                        raise ExtractionError("invalid_file", f"{name} nests too deeply")
                    if started % _TICK_EVERY_NODES == 0:
                        guard.tick()
                else:
                    depth -= 1
                yield event, node
    except (ParseError, DefusedXmlException) as exc:
        raise ExtractionError("invalid_file",
                              f"unreadable XML in {name} ({type(exc).__name__})") from exc


class _Package:
    """An unpacked OOXML package: case-insensitive part lookup, relationships and bounded
    XML reading (whole small parts, or large parts block by block)."""

    def __init__(self, root: Path, members: list[tuple[str, ...]], guard: _Guard) -> None:
        self._parts = {"/".join(parts).lower(): root.joinpath(*parts) for parts in members}
        self._guard = guard

    def has(self, name: str) -> bool:
        return name.lower() in self._parts

    def _path(self, name: str) -> Path:
        path = self._parts.get(name.lower())
        if path is None:
            raise ExtractionError("invalid_file", f"the package has no {name}")
        return path

    def xml(self, name: str) -> _XmlNode:
        """A small part (workbook, styles, relationships) as one tree."""
        root: _XmlNode | None = None
        nodes = 0
        for event, node in _parse_events(self._path(name), name, self._guard):
            if event == "start":
                root = node if root is None else root
                nodes += 1
                if nodes > MAX_XML_NODES:
                    raise _too_many_nodes(name)
        if root is None:
            raise ExtractionError("invalid_file", f"{name} is empty")
        return root

    def blocks(self, name: str, blocks: frozenset[str], marks: frozenset[str] = frozenset(),
               ) -> Iterator[tuple[_XmlNode, tuple[_XmlNode, ...]]]:
        """Each complete *blocks* element of a large part, and the end of each *marks*
        element, in document order, with its open ancestors (outermost first).

        Whatever has been read and is not part of a block still open is dropped from
        the tree at once, so memory holds one block — at most :data:`MAX_XML_NODES`
        elements — however large the part is. A block inside a block is part of the
        outer one. A *marks* element arrives empty (its children were dropped) but with
        its attributes, after everything inside it.
        """
        stack: list[_XmlNode] = []
        block: _XmlNode | None = None
        nodes = 0
        for event, node in _parse_events(self._path(name), name, self._guard):
            if event == "start":
                if block is not None:
                    nodes += 1
                    if nodes > MAX_XML_NODES:
                        raise _too_many_nodes(name)
                elif _local(node.tag) in blocks:
                    block, nodes = node, 1
                stack.append(node)
                continue
            stack.pop()
            if node is block:
                block = None
                yield node, tuple(stack)
            elif block is None and _local(node.tag) in marks:
                yield node, tuple(stack)
            if block is None and stack:
                stack[-1].remove(node)

    def relationships(self, source: str) -> list[tuple[str, str, str]]:
        """``(id, type, part)`` for each internal relationship of *source* ('' = package)."""
        folder, base = posixpath.split(source)
        rels_name = posixpath.join(folder, "_rels", f"{base}.rels")
        if not self.has(rels_name):
            return []
        found = []
        for rel in self.xml(rels_name):
            if _local(rel.tag) != "Relationship" or rel.get("TargetMode") == "External":
                continue
            part = _resolve_target(source, rel.get("Target") or "")
            if part:
                found.append((rel.get("Id") or "", (rel.get("Type") or "").rsplit("/", 1)[-1],
                              part))
        return found

    def main_part(self, default: str) -> str:
        """The package's main document part (``officeDocument`` relationship)."""
        for _rel_id, rel_type, part in self.relationships(""):
            if rel_type == "officeDocument" and self.has(part):
                return part
        return default


@contextmanager
def _ooxml_package(data: bytes, guard: _Guard) -> Iterator[_Package]:
    """Unpack *data* into a private temporary directory through ``archive_safe``."""
    with tempfile.TemporaryDirectory(prefix="nerva-ws-") as tmp:
        dest = Path(tmp) / "package"
        try:
            members = extract_zip_bytes(data, dest, limits=OOXML_LIMITS)
        except ArchiveRejected as exc:
            raise ExtractionError("invalid_file", f"the archive was refused ({exc})") from exc
        package = _Package(dest, members, guard)
        if not package.has("[Content_Types].xml"):
            raise ExtractionError("invalid_file", "not an Office Open XML package")
        yield package


# ── DOCX ─────────────────────────────────────────────────────────────────────────────

# Elements that only wrap block content (content controls, custom XML, tracked inserts).
_DOCX_WRAPPERS = frozenset({"sdt", "sdtContent", "customXml", "ins", "smartTag"})
# Run/paragraph subtrees that hold no visible text: properties (tab-stop definitions
# would read as tabs), tracked deletions and field instructions.
_DOCX_SKIPPED = frozenset({"pPr", "rPr", "del", "moveFrom", "instrText", "sdtPr", "sdtEndPr"})


def _collect_runs(node: _XmlNode, parts: list[str]) -> None:
    for child in node:
        name = _local(child.tag)
        if name in _DOCX_SKIPPED:
            continue
        if name == "t":
            parts.append(child.text or "")
        elif name == "tab":
            parts.append("\t")
        elif name in ("br", "cr"):
            parts.append("\n")
        elif name == "noBreakHyphen":
            parts.append("-")
        else:
            _collect_runs(child, parts)


def _paragraph_text(paragraph: _XmlNode) -> str:
    parts: list[str] = []
    _collect_runs(paragraph, parts)
    return "".join(parts)


def _blocks(parent: _XmlNode, name: str) -> Iterator[_XmlNode]:
    """Direct *name* children of *parent*, looking through wrapper elements."""
    for child in parent:
        local = _local(child.tag)
        if local == name:
            yield child
        elif local in _DOCX_WRAPPERS:
            yield from _blocks(child, name)


def _cell_texts(container: _XmlNode) -> Iterator[str]:
    """The paragraphs of a table cell in order; a nested table reads as its cells' text."""
    for child in container:
        name = _local(child.tag)
        if name == "p":
            yield _paragraph_text(child)
        elif name == "tbl":
            for row in _blocks(child, "tr"):
                for cell in _blocks(row, "tc"):
                    yield from _cell_texts(cell)
        elif name in _DOCX_WRAPPERS:
            yield from _cell_texts(child)


def _grid_span(cell: _XmlNode) -> int:
    props = _first(cell, "tcPr")
    span = _first(props, "gridSpan") if props is not None else None
    raw = _attr(span, "val") if span is not None else None
    try:
        return max(1, min(int(raw or "1"), 64))
    except ValueError:
        return 1


def _docx_table(table: _XmlNode) -> str:
    rows: list[list[str]] = []
    for row in _blocks(table, "tr"):
        cells: list[str] = []
        for cell in _blocks(row, "tc"):
            cells.append(" ".join(text.strip() for text in _cell_texts(cell) if text.strip()))
            cells.extend([""] * (_grid_span(cell) - 1))
        rows.append(cells)
    return markdown_table(rows)


_DOCX_BLOCKS = frozenset({"p", "tbl"})
_DOCX_BODY = frozenset({"body"})


def _in_body(ancestors: Sequence[_XmlNode]) -> bool:
    """True for a block of ``document/body``, directly or inside wrapper elements only."""
    return (len(ancestors) >= 2 and _local(ancestors[1].tag) == "body"
            and all(_local(node.tag) in _DOCX_WRAPPERS for node in ancestors[2:]))


def _docx(data: bytes, guard: _Guard) -> Extracted:
    """Body paragraphs and tables in document order, read one block at a time."""
    blocks: list[str] = []
    has_body = False
    with _ooxml_package(data, guard) as package:
        part = package.main_part("word/document.xml")
        for node, ancestors in package.blocks(part, _DOCX_BLOCKS, _DOCX_BODY):
            name = _local(node.tag)
            if name == "body":
                has_body = has_body or len(ancestors) == 1
                continue
            if not _in_body(ancestors):
                continue
            text = _paragraph_text(node) if name == "p" else _docx_table(node)
            if text.strip():
                guard.spend(len(text))
                blocks.append(text)
    if not has_body:
        raise ExtractionError("invalid_file", "the document has no body")
    return Extracted(_single(clean_text("\n\n".join(blocks))), page_count=None)


# ── XLSX ─────────────────────────────────────────────────────────────────────────────

def _rich_text(node: _XmlNode) -> str:
    """Text of a shared-string ``si`` or an inline ``is`` (plain or rich runs; no phonetics)."""
    parts: list[str] = []
    for child in node:
        name = _local(child.tag)
        if name == "t":
            parts.append(child.text or "")
        elif name == "r":
            parts.extend(run.text or "" for run in _children(child, "t"))
    return "".join(parts)


_SHARED_ITEM = frozenset({"si"})


def _shared_strings(package: _Package, rels: list[tuple[str, str, str]]) -> list[str]:
    """The shared-string table, read one item at a time.

    It gets a text budget of its own (each item costs at least one character), so a
    table of millions of empty items cannot fill memory before any cell is read.
    """
    part = next((p for _i, kind, p in rels if kind == "sharedStrings"), "xl/sharedStrings.xml")
    if not package.has(part):
        return []
    strings: list[str] = []
    budget = MAX_TEXT_CHARS
    for item, ancestors in package.blocks(part, _SHARED_ITEM):
        if len(ancestors) != 1:  # only the table's own items (sst/si) count
            continue
        text = _rich_text(item)
        budget -= len(text) + 1
        if budget < 0:
            raise ExtractionError("too_much_text", "the shared strings hold too much text")
        strings.append(text)
    return strings


def _classify_format(code: str) -> str:
    """'date' | 'datetime' | 'time' | 'percent' | '' for a custom number format code."""
    bare = _FORMAT_LITERALS.sub("", code.split(";", 1)[0]).lower()
    if "%" in bare:
        return "percent"
    has_date = any(ch in bare for ch in "dy")
    has_time = any(ch in bare for ch in "hs")
    if "m" in bare and not has_time:
        has_date = True  # "m" next to d/y or alone is a month; next to h/s it is minutes
    if has_date and has_time:
        return "datetime"
    if has_date:
        return "date"
    return "time" if has_time else ""


def _format_kind(format_id: int, custom: dict[int, str]) -> str:
    """The display kind of number format *format_id*; *custom* maps ids to known kinds."""
    if format_id in custom:
        return custom[format_id]
    if format_id in _BUILTIN_DATE_FORMATS:
        return "date"
    if format_id in _BUILTIN_DATETIME_FORMATS:
        return "datetime"
    if format_id in _BUILTIN_TIME_FORMATS:
        return "time"
    return "percent" if format_id in _BUILTIN_PERCENT_FORMATS else ""


def _int_or(raw: str | None, default: int) -> int:
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


def _cell_formats(package: _Package, rels: list[tuple[str, str, str]]) -> list[str]:
    """The display kind of every cell style index (``c/@s``), from ``styles.xml``."""
    part = next((p for _i, kind, p in rels if kind == "styles"), "xl/styles.xml")
    if not package.has(part):
        return []
    styles = package.xml(part)
    custom: dict[int, str] = {}
    formats = _first(styles, "numFmts")
    if formats is not None:
        for item in _children(formats, "numFmt"):
            code = (item.get("formatCode") or "")[:_MAX_FORMAT_CODE]
            custom[_int_or(item.get("numFmtId"), -1)] = _classify_format(code)
    cell_xfs = _first(styles, "cellXfs")
    if cell_xfs is None:
        return []
    return [_format_kind(_int_or(xf.get("numFmtId"), 0), custom)
            for xf in _children(cell_xfs, "xf")]


def _plain_number(value: float) -> str:
    if value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return format(value, ".15g")


def _serial_text(serial: float, kind: str, epoch_1904: bool) -> str | None:
    """An Excel date serial as ISO text, or ``None`` when it is not a plausible date."""
    first_day = 0 if epoch_1904 else 1  # serial 0 is 1904-01-01, but "1900-01-00"
    if kind != "time" and not first_day <= serial <= _MAX_EXCEL_SERIAL:
        return None
    if kind == "time":
        serial %= 1
    if epoch_1904:
        base = datetime(1904, 1, 1)
    else:  # Excel counts the nonexistent 1900-02-29 as day 60
        base = datetime(1899, 12, 31) if serial < 60 else datetime(1899, 12, 30)
    moment = base + timedelta(seconds=round(serial * 86400))
    day = f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d}"
    clock = f"{moment.hour:02d}:{moment.minute:02d}"
    if moment.second:
        clock += f":{moment.second:02d}"
    if kind == "date":
        return day
    return clock if kind == "time" else f"{day} {clock}"


def _number_text(raw: str, kind: str, epoch_1904: bool) -> str:
    try:
        value = float(raw)
    except ValueError:
        return raw
    if not math.isfinite(value):
        return raw
    if kind in ("date", "datetime", "time"):
        converted = _serial_text(value, kind, epoch_1904)
        if converted is not None:
            return converted
    if kind == "percent":
        return _plain_number(value * 100) + "%"
    return _plain_number(value)


@dataclass(frozen=True)
class _SheetContext:
    shared: list[str]
    formats: list[str]
    epoch_1904: bool


def _cell_text(cell: _XmlNode, context: _SheetContext) -> str:
    cell_type = cell.get("t") or "n"
    if cell_type == "inlineStr":
        inline = _first(cell, "is")
        return _rich_text(inline) if inline is not None else ""
    value = _first(cell, "v")
    raw = (value.text or "") if value is not None else ""
    if not raw:
        return ""
    if cell_type == "s":
        index = _int_or(raw.strip(), -1)
        return context.shared[index] if 0 <= index < len(context.shared) else ""
    if cell_type == "b":
        return "TRUE" if raw.strip() == "1" else "FALSE"
    if cell_type in ("str", "e", "d"):
        return raw
    style = _int_or(cell.get("s"), 0)
    kind = context.formats[style] if 0 <= style < len(context.formats) else ""
    return _number_text(raw.strip(), kind, context.epoch_1904)


def _column_index(ref: str | None) -> int | None:
    match = _CELL_REF.match(ref or "")
    if match is None:
        return None
    index = 0
    for letter in match.group(1).upper():
        index = index * 26 + (ord(letter) - ord("A") + 1)
    return index - 1


_SHEET_CELL = frozenset({"c"})
_SHEET_ROW = frozenset({"row"})


def _under(ancestors: Sequence[_XmlNode], *names: str) -> bool:
    """True when the ancestors below the root are exactly *names* (local names)."""
    return (len(ancestors) == len(names) + 1
            and all(_local(node.tag) == name for node, name in zip(ancestors[1:], names,
                                                                    strict=True)))


def _sheet_rows(package: _Package, part: str, context: _SheetContext,
                guard: _Guard) -> list[list[str]]:
    """The worksheet's non-empty cells as rows of text, read one cell at a time.

    Cells come from ``worksheet/sheetData/row/c``; each ``row`` end closes a row. Empty
    cells cost nothing, filled ones spend from the document's text budget.
    """
    sparse: list[dict[int, str]] = []
    cells: dict[int, str] = {}
    position = 0
    row: _XmlNode | None = None  # the open row whose place in the sheet was checked
    for node, ancestors in package.blocks(part, _SHEET_CELL, _SHEET_ROW):
        if _local(node.tag) == "row":
            if _under(ancestors, "sheetData"):
                if cells:
                    sparse.append(cells)
                cells, position, row = {}, 0, None
            continue
        if not ancestors or ancestors[-1] is not row:
            if not _under(ancestors, "sheetData", "row"):
                continue
            row = ancestors[-1]
        column = _column_index(node.get("r"))
        column = position if column is None else column
        position = column + 1
        if column >= MAX_SHEET_COLUMNS:
            continue
        text = _cell_text(node, context)
        if text.strip():
            guard.spend(len(text) + 3)
            cells[column] = text
    used = sorted({column for row in sparse for column in row})
    return [[row.get(column, "") for column in used] for row in sparse]


def _workbook_sheets(workbook: _XmlNode,
                     rels: list[tuple[str, str, str]]) -> Iterator[tuple[str, str]]:
    """``(sheet name, worksheet part)`` in tab order; chart sheets have no rows and are skipped."""
    targets = {rel_id: part for rel_id, kind, part in rels if kind == "worksheet"}
    sheets = _first(workbook, "sheets")
    if sheets is None:
        return
    for number, sheet in enumerate(_children(sheets, "sheet"), start=1):
        part = targets.get(_attr(sheet, "id") or "")
        if part:
            yield (sheet.get("name") or f"Sheet{number}").strip(), part


def _uses_1904(workbook: _XmlNode) -> bool:
    """``workbookPr/@date1904`` is an xsd:boolean; the tree has one spelling parser."""
    props = _first(workbook, "workbookPr")
    return props is not None and truthy(props.get("date1904"))


def _xlsx(data: bytes, guard: _Guard) -> Extracted:
    segments: list[Segment] = []
    with _ooxml_package(data, guard) as package:
        workbook_part = package.main_part("xl/workbook.xml")
        workbook = package.xml(workbook_part)
        rels = package.relationships(workbook_part)
        context = _SheetContext(shared=_shared_strings(package, rels),
                                formats=_cell_formats(package, rels),
                                epoch_1904=_uses_1904(workbook))
        for name, part in _workbook_sheets(workbook, rels):
            guard.tick()
            if not package.has(part):
                continue
            table = markdown_table(_sheet_rows(package, part, context, guard))
            if table:
                segments.append(Segment(None, clean_text(f"## {name}\n\n{table}")))
    return Extracted(tuple(segments), page_count=None)


# ── CSV and plain text ───────────────────────────────────────────────────────────────

def sniff_delimiter(text: str) -> str:
    """The CSV delimiter among ``, ; TAB |`` (``csv.Sniffer`` first, then a count)."""
    lines = text[:_CSV_SNIFF_CHARS].split("\n")
    if len(text) > _CSV_SNIFF_CHARS and len(lines) > 1:
        lines.pop()  # cut short by the sample window
    sample = "\n".join(lines[:_CSV_SNIFF_LINES])
    try:
        return csv.Sniffer().sniff(sample, delimiters=_CSV_DELIMITERS).delimiter
    except csv.Error:
        first_line = sample.split("\n", 1)[0]
        counts = {delimiter: first_line.count(delimiter) for delimiter in _CSV_DELIMITERS}
        best = max(counts, key=lambda delimiter: counts[delimiter])
        return best if counts[best] else ","


def _csv(data: bytes, guard: _Guard) -> Extracted:
    text = decode_text(data).replace("\r\n", "\n").replace("\r", "\n")
    reader = csv.reader(io.StringIO(text), delimiter=sniff_delimiter(text), quotechar='"')
    rows: list[list[str]] = []
    try:
        for number, row in enumerate(reader):
            if number % _TICK_EVERY_ROWS == 0:
                guard.tick()
            guard.spend(sum(len(cell) + 3 for cell in row))
            rows.append(row)
    except csv.Error as exc:
        raise ExtractionError("invalid_file", f"malformed CSV ({exc})") from exc
    return Extracted(_single(clean_text(markdown_table(rows))), page_count=None)


def _plain(data: bytes, guard: _Guard) -> Extracted:
    guard.tick()
    text = clean_text(decode_text(data))
    guard.spend(len(text))
    return Extracted(_single(text), page_count=None)


_HANDLERS: dict[str, Callable[[bytes, _Guard], Extracted]] = {
    "pdf": _pdf, "docx": _docx, "xlsx": _xlsx, "csv": _csv, "txt": _plain, "md": _plain,
}


# ── entry points ─────────────────────────────────────────────────────────────────────

def _extract_bytes_impl(data: bytes, kind: str, *, timeout: float | None,
                        allow_ocr: bool,
                        progress: Callable[[str, int, float, int], None] | None = None) -> Extracted:
    """Extract the text of *data* as a *kind* file (synchronous; see :func:`extract_document`).

    Raises :class:`ExtractionError` — ``no_text`` when nothing readable came out (a
    scanned PDF without a text layer, an empty sheet).
    """
    handler = _HANDLERS.get(kind)
    if handler is None:
        raise ExtractionError("invalid_file", f"unsupported kind {kind!r}")
    guard = _Guard(timeout, MAX_TEXT_CHARS)
    try:
        extracted = (_pdf(data, guard, allow_ocr=allow_ocr, progress=progress)
                     if kind == "pdf" else handler(data, guard))
    except ExtractionError:
        raise
    except (ParseError, DefusedXmlException, csv.Error, ValueError, KeyError, IndexError,
            RecursionError) as exc:
        raise ExtractionError("invalid_file",
                              f"{kind} could not be parsed ({type(exc).__name__})") from exc
    if not any(_HAS_WORD.search(segment.text) for segment in extracted.segments):
        raise ExtractionError("no_text", "no readable text", page_count=extracted.page_count)
    return extracted


def extract_bytes(data: bytes, kind: str, *, timeout: float | None = None) -> Extracted:
    """Synchronous extraction. Native OCR is never invoked through this entry point."""
    return _extract_bytes_impl(data, kind, timeout=timeout, allow_ocr=False)


def _extract_bytes_in_child(data: bytes, kind: str, *, timeout: float,
                            progress: Callable[[str, int, float, int], None] | None = None) -> Extracted:
    """Extraction-child-only entry point for opt-in native OCR."""
    return _extract_bytes_impl(data, kind, timeout=timeout, allow_ocr=True, progress=progress)


async def extract_document(data: bytes, kind: str, *,
                           timeout: float = EXTRACT_TIMEOUT_SECONDS) -> Extracted:
    """:func:`extract_bytes` off-loop, bounded at *timeout* → ``timeout``.

    The bound counts from submission, so under a burst a queued file times out rather
    than waiting without limit. Opt-in PDF/DOCX children are killed and reaped before
    returning; legacy pool workers stop only at their cooperative checkpoints.
    """
    if kind in {"pdf", "docx"} and env_flag("NERVA_WORKSPACE_KILLABLE_EXTRACTION", False):
        from agents.core.workspace.extract_process import extract_in_child

        return await extract_in_child(data, kind, timeout=timeout)
    job = asyncio.get_running_loop().run_in_executor(
        _POOL, functools.partial(extract_bytes, data, kind, timeout=timeout))
    try:
        return await asyncio.wait_for(job, timeout)
    except TimeoutError as exc:
        raise ExtractionError("timeout", f"no result within {timeout:g} s") from exc
