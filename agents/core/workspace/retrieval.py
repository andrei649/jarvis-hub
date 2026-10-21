"""Full-text retrieval over the workspace knowledge base (spec §5, Appendix A).

The assistant (S3) and the report runner (S4) ask one question: *which passages of the
documents this person may read best match this text?* :func:`search` answers it from
the ``chunks_fts`` index (FTS5, ``unicode61 remove_diacritics 2``), and enforces the
scope inside the SQL statement itself — department documents only of the listed
departments, company-wide documents only when asked for, ready documents only — so
no caller can widen it by passing odd ``document_ids``.

User text never reaches ``MATCH`` raw: FTS5 has its own query language and
``e-Factura`` is a syntax error in it. The query is reduced to plain word tokens
(case- and diacritic-folded, Romanian and English stopwords dropped), each one
truncated to a short prefix stem and quoted as ``"stem"*``, so ``concediul`` also finds
``concediu`` and ``concediile`` and ``sedinta`` finds ``ședință``. Odd input (emoji,
quotes, operators, an empty string, a non-string) yields ``[]``, never an exception.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

logger = logging.getLogger("nerva.workspace.retrieval")

MAX_TERMS = 16
MIN_TERM_LEN = 2
MAX_K = 50
DEFAULT_K = 6
#: Only the start of a very long query (report instructions) is tokenized.
MAX_QUERY_CHARS = 4000
_MAX_ID = 2 ** 63 - 1
# Letters and digits only: "_" is a word character for Python but a separator for
# the FTS tokenizer, so it must not glue two words into one term.
_TOKEN = re.compile(r"[^\W_]+")

# Stored diacritic-free, because queries are folded before the lookup ("si" = "și").
_STOPWORDS_RO = """
a acea aceasta aceea acei aceia acel acela acele acelea acest acesta aceste acestea acesti
acestia acum adica ai aia aici al ala ale alea alt alta alte alti altul am ar are as asa
asta astea ati au avea avem aveti avut azi ba bine ca cam cand care careia carora caruia cat
cata cate cati catre ce cea cei cel cele celor ceva chiar cine cineva cu cum cumva da daca
dar de deci deja desi despre din dintr dintre doar doresc dupa ea ei el ele era erau este
esti eu fara fi fie fiecare fii fim fiu fost i ia ii il im imi in inainte inca incat insa
intr intre iar isi la le li lor lui ma mai mea mei mele mereu meu mi mult multa multe multi
ne nici niciodata noi noastra noastre nostri nostru nu numai o ori oricare orice pe pentru
peste poate poti pot prin puteti putea rog sa sai sale sau se si sint sintem spre spune
spuneti spunem sub sunt suntem sunteti ta tai tale tau te ti tine toata toate tot toti
totusi tu un una unde unei unele uneori unii unor unui unul va vi voi vom vor vrea vreau
vreo vreun arata aratati
"""
_STOPWORDS_EN = """
about above after again against all am and any are as at be because been before being
below between both but by can could did do does doing down during each few for from
further had has have having he her here hers herself him himself his how i if in into is
it its itself just me more most my myself no nor not now of off on once only or other our
ours ourselves out over own please same she should show so some such tell than that the
their theirs them themselves then there these they this those through to too under until
up very was we were what when where which while who whom why will with would you your
yours yourself yourselves
"""
STOPWORDS = frozenset((_STOPWORDS_RO + _STOPWORDS_EN).split())


@dataclass
class Passage:
    """One retrieved chunk; ``score`` is the negated BM25 rank (higher is better)."""

    chunk_id: int
    document_id: int
    title: str
    department_id: int | None
    text: str
    page: int | None
    score: float


def fold(text: str) -> str:
    """Case- and diacritic-folded *text* (``Ședință`` → ``sedinta``), like the FTS tokenizer."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def query_terms(query: object) -> list[str]:
    """The distinct prefix stems of *query*'s meaningful words, at most :data:`MAX_TERMS`.

    Words shorter than two characters and stopwords are dropped; a word longer than
    four characters keeps all but its last two (never fewer than four), which covers
    the common Romanian and English inflections without a stemmer.
    """
    if not isinstance(query, str):
        return []
    terms: list[str] = []
    for token in _TOKEN.findall(fold(query[:MAX_QUERY_CHARS])):
        if len(token) < MIN_TERM_LEN or token in STOPWORDS:
            continue
        stem = token if len(token) <= 4 else token[: max(4, len(token) - 2)]
        if stem not in terms:
            terms.append(stem)
            if len(terms) == MAX_TERMS:
                break
    return terms


def build_match_query(query: object, *, require_all: bool = False) -> str:
    """A safe FTS5 ``MATCH`` expression for *query* ('' when nothing meaningful is left).

    Terms are joined with ``OR`` (ranking decides) or, with *require_all*, ``AND``
    (the documents list's search box).
    """
    terms = query_terms(query)
    return (" AND " if require_all else " OR ").join(f'"{term}"*' for term in terms)


def _clean_ids(values: object) -> list[int]:
    """Positive SQLite-range integer ids from *values*, de-duplicated; junk is dropped."""
    if isinstance(values, str | bytes | bytearray | Mapping) or not isinstance(values, Iterable):
        return []
    ids: list[int] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        if 1 <= value <= _MAX_ID and value not in ids:
            ids.append(value)
    return ids


_SEARCH_SQL = (
    "SELECT c.id AS chunk_id, c.document_id, c.page, c.text, d.title, d.department_id, "
    "bm25(chunks_fts) AS bm25_rank "
    "FROM chunks_fts "
    "JOIN chunks c ON c.id = chunks_fts.rowid "
    "JOIN documents d ON d.id = c.document_id "
    "WHERE chunks_fts MATCH ? AND d.status = 'ready' "
    "AND (d.department_id IN (SELECT value FROM json_each(?)) "
    "     OR (? = 1 AND d.visibility = 'company')) "
    "AND (? IS NULL OR d.id IN (SELECT value FROM json_each(?))) "
    "ORDER BY bm25_rank, c.id LIMIT ?"
)


def search(conn: sqlite3.Connection, *, department_ids: Sequence[int], include_company: bool,
           query: str, k: int = DEFAULT_K,
           document_ids: Sequence[int] | None = None) -> list[Passage]:
    """The *k* best passages for *query* among the documents in scope, best first.

    Scope: ready documents whose department is one of *department_ids* (department or
    company visibility), plus every ready company-wide document when
    *include_company*; *document_ids*, when given, narrows that scope further and can
    never widen it (an empty list therefore finds nothing). Never raises on odd input.
    """
    match = build_match_query(query)
    departments = _clean_ids(department_ids)
    if not match or (not departments and not include_company):
        return []
    only_documents = None if document_ids is None else _clean_ids(document_ids)
    if only_documents == []:
        return []
    limit = k if isinstance(k, int) and not isinstance(k, bool) else DEFAULT_K
    limit = max(1, min(limit, MAX_K))
    restriction = None if only_documents is None else json.dumps(only_documents)
    try:
        rows = conn.execute(_SEARCH_SQL, (match, json.dumps(departments),
                                          1 if include_company else 0, restriction,
                                          restriction, limit)).fetchall()
    except sqlite3.OperationalError as exc:
        # The message can quote the query (user content), so only its code is logged.
        logger.warning("workspace search failed (%s); answering with no passages",
                       getattr(exc, "sqlite_errorname", type(exc).__name__))
        return []
    return [
        Passage(chunk_id=int(row["chunk_id"]), document_id=int(row["document_id"]),
                title=row["title"], department_id=row["department_id"], text=row["text"],
                page=row["page"], score=-float(row["bm25_rank"]))
        for row in rows
    ]
