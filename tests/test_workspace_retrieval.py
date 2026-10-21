"""Retrieval over the knowledge base (spec §5 ``retrieval.search``, Appendix A FTS rules).

The assistant and the report runner call ``search`` with the caller's departments; the
properties pinned here are scope enforced in SQL, diacritic-insensitive matching with
prefix stems, Romanian and English stopwords, ranking, and that no query text — however
odd — can raise or reach FTS5's query language raw.
"""

from __future__ import annotations

import sqlite3

import pytest

from agents.core.workspace import retrieval
from agents.core.workspace.retrieval import Passage, search
from tests.fixtures.workspace.doc_helpers import seed_document
from tests.support.workspace_fixtures import db, make_department, seed_org, ws  # noqa: F401


@pytest.fixture
def kb(ws):
    conn = db()
    seed_org(conn)
    sales = make_department(conn, "Vânzări")
    hr = make_department(conn, "Resurse Umane")
    docs = {
        "leave": seed_document(conn, department_id=hr, uploader_id=None, title="Politica de concedii",
                               chunks=["Angajații au dreptul la 21 de zile de concediu de odihnă.",
                                       "Concediul medical se anunță în 3 zile."], pages=[1, 2]),
        "invoice": seed_document(conn, department_id=sales, uploader_id=None, title="Facturare",
                                 chunks=["Facturile se transmit prin e-Factura în 5 zile."]),
        "meeting": seed_document(conn, department_id=sales, uploader_id=None, title="Ședințe",
                                 chunks=["Ședința anuală are loc la Brașov, în martie."]),
        "cedilla": seed_document(conn, department_id=sales, uploader_id=None, title="Contacte",
                                 chunks=["Agentul din Constanţa răspunde de ţara întreagă."]),
        "public": seed_document(conn, department_id=hr, uploader_id=None, title="Cod etic",
                                visibility="company",
                                chunks=["Codul etic se aplică tuturor angajaților și concediului."]),
        "global": seed_document(conn, department_id=None, uploader_id=None, title="Program",
                                visibility="company", chunks=["Programul de lucru: 9-18, luni-vineri."]),
        "failed": seed_document(conn, department_id=sales, uploader_id=None, title="Eșuat",
                                status="failed", chunks=["concediu de odihnă eșuat"]),
        "processing": seed_document(conn, department_id=sales, uploader_id=None, title="În lucru",
                                    status="processing", chunks=["concediu în procesare"]),
    }
    yield conn, sales, hr, docs
    conn.close()


def _docs(passages: list[Passage]) -> list[int]:
    return [passage.document_id for passage in passages]


# ── query building ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("query", "terms"), [
    ("Câte zile de concediu am?", ["zile", "conced"]),  # "câte" is a stopword
    ("e-Factura", ["factu"]),
    ("Ședința ANUALĂ, ședința!", ["sedin", "anua"]),
    ("Ce este și cum se face?", ["face"]),
    ("What is the leave policy?", ["leav", "poli"]),
    ("a b c 1 2", []),
    ("", []), ("🙂🙂", []), ('"""', []),
    ("foo_bar", ["foo", "bar"]),
    ("Raport 2026 Q3", ["rapo", "2026", "q3"]),
])
def test_query_terms_are_folded_stemmed_and_stopword_free(query, terms):
    assert retrieval.query_terms(query) == terms


def test_at_most_sixteen_distinct_terms_are_used():
    query = " ".join(f"cuvant{n:02d}xx" for n in range(40)) + " cuvant00xx"
    terms = retrieval.query_terms(query)
    assert len(terms) == 16 and len(set(terms)) == 16


@pytest.mark.parametrize("odd", [None, 42, b"concediu", ["concediu"], {"q": 1}])
def test_non_string_queries_have_no_terms(odd):
    assert retrieval.query_terms(odd) == [] and retrieval.build_match_query(odd) == ""


def test_the_match_expression_quotes_every_prefix_term():
    assert retrieval.build_match_query("concediul de odihnă") == '"concedi"* OR "odih"*'
    assert retrieval.build_match_query("concediul odihnă", require_all=True) == \
        '"concedi"* AND "odih"*'


def test_fold_matches_the_tokenizer_on_romanian_letters():
    assert retrieval.fold("ȘEDINȚĂ Ţară şi ÎNCÂNTAT") == "sedinta tara si incantat"


def test_the_stopword_lists_cover_both_languages_without_diacritics():
    for word in ("si", "este", "pentru", "care", "the", "what", "and", "unde"):
        assert word in retrieval.STOPWORDS
    for meaningful in ("concediu", "an", "lei", "zile", "factura", "date"):
        assert meaningful not in retrieval.STOPWORDS
    assert all(word.isascii() for word in retrieval.STOPWORDS)


# ── matching and ranking ─────────────────────────────────────────────────────────────

def test_search_finds_the_passage_with_its_page_title_and_a_positive_score(kb):
    conn, sales, hr, docs = kb
    hits = search(conn, department_ids=[hr], include_company=False,
                  query="Câte zile de concediu de odihnă am?")
    assert _docs(hits)[0] == docs["leave"]
    best = hits[0]
    assert best.title == "Politica de concedii" and best.page == 1 and best.department_id == hr
    assert best.text.startswith("Angajații au dreptul")
    assert all(isinstance(hit.chunk_id, int) and hit.score > 0 for hit in hits)
    assert [hit.score for hit in hits] == sorted((hit.score for hit in hits), reverse=True)


@pytest.mark.parametrize("query", ["sedinta anuala", "ȘEDINȚA", "ședințele anuale", "Brasov"])
def test_diacritics_and_inflections_do_not_matter(kb, query):
    conn, sales, hr, docs = kb
    assert _docs(search(conn, department_ids=[sales], include_company=False,
                        query=query)) == [docs["meeting"]]


def test_cedilla_and_comma_below_letters_match_each_other(kb):
    conn, sales, hr, docs = kb
    assert _docs(search(conn, department_ids=[sales], include_company=False,
                        query="Constanța țara")) == [docs["cedilla"]]


def test_e_factura_is_found_and_never_raises(kb):
    conn, sales, hr, docs = kb
    assert _docs(search(conn, department_ids=[sales], include_company=False,
                        query="e-Factura")) == [docs["invoice"]]


def test_more_matching_terms_rank_higher(kb):
    conn, sales, hr, docs = kb
    hits = search(conn, department_ids=[hr], include_company=True,
                  query="concediu de odihnă zile angajații")
    assert _docs(hits)[0] == docs["leave"]
    assert docs["public"] in _docs(hits)


def test_only_stopwords_find_nothing(kb):
    conn, sales, hr, docs = kb
    assert search(conn, department_ids=[sales, hr], include_company=True,
                  query="ce este și cum") == []


# ── scope ────────────────────────────────────────────────────────────────────────────

def test_department_documents_only_of_the_listed_departments(kb):
    conn, sales, hr, docs = kb
    assert search(conn, department_ids=[sales], include_company=False, query="concediu") == []
    assert set(_docs(search(conn, department_ids=[hr], include_company=False,
                            query="concediu"))) == {docs["leave"], docs["public"]}


def test_company_documents_only_when_asked_for(kb):
    conn, sales, hr, docs = kb
    with_company = _docs(search(conn, department_ids=[sales], include_company=True,
                                query="concediului programul"))
    assert set(with_company) == {docs["public"], docs["global"]}
    assert search(conn, department_ids=[], include_company=True, query="programul") != []
    assert search(conn, department_ids=[], include_company=False, query="programul") == []


def test_failed_and_processing_documents_are_never_retrieved(kb):
    conn, sales, hr, docs = kb
    hits = search(conn, department_ids=[sales], include_company=False, query="concediu procesare eșuat")
    assert docs["failed"] not in _docs(hits) and docs["processing"] not in _docs(hits)


def test_document_ids_narrow_the_scope_and_never_widen_it(kb):
    conn, sales, hr, docs = kb
    assert _docs(search(conn, department_ids=[hr], include_company=True, query="concediu",
                        document_ids=[docs["public"]])) == [docs["public"]]
    assert search(conn, department_ids=[sales], include_company=False, query="concediu",
                  document_ids=[docs["leave"]]) == []
    assert search(conn, department_ids=[hr], include_company=True, query="concediu",
                  document_ids=[]) == []
    assert search(conn, department_ids=[sales], include_company=True, query="programul",
                  document_ids=[docs["global"], "x", True, -1, 2 ** 70, None]) != []


@pytest.mark.parametrize("department_ids", [None, "1", 7, [True], ["1"], [1.5], [-1], [2 ** 80],
                                            {"a": 1}])
def test_junk_department_ids_mean_no_department(kb, department_ids):
    conn, sales, hr, docs = kb
    assert search(conn, department_ids=department_ids, include_company=False,
                  query="concediu") == []
    assert set(_docs(search(conn, department_ids=department_ids, include_company=True,
                            query="programul"))) == {docs["global"]}


def test_ids_may_come_as_any_iterable(kb):
    conn, sales, hr, docs = kb
    hits = search(conn, department_ids=(d for d in [hr]), include_company=False,
                  query="concediu", document_ids={docs["leave"]})
    assert set(_docs(hits)) == {docs["leave"]}


# ── k and odd input ──────────────────────────────────────────────────────────────────

def test_k_is_clamped_and_defaults_to_six(ws):
    conn = db()
    dept = make_department(conn, "Arhivă")
    for n in range(60):
        seed_document(conn, department_id=dept, uploader_id=None, title=f"Act {n}",
                      chunks=[f"Contractul numărul {n} privind furnizarea."])
    assert len(search(conn, department_ids=[dept], include_company=False, query="contractul")) == 6
    assert len(search(conn, department_ids=[dept], include_company=False, query="contractul",
                      k=1)) == 1
    assert len(search(conn, department_ids=[dept], include_company=False, query="contractul",
                      k=0)) == 1
    assert len(search(conn, department_ids=[dept], include_company=False, query="contractul",
                      k=1000)) == retrieval.MAX_K
    for odd_k in ("3", None, True, 2.5):
        assert len(search(conn, department_ids=[dept], include_company=False,
                          query="contractul", k=odd_k)) == 6
    conn.close()


ODD_QUERIES = [
    "e-Factura", '"', '""', "'", 'a"b"c', "🙂", "😀 concediu 😀", "", "   ", "\x00", "\n\t",
    "NEAR(concediu zile)", "concediu AND OR NOT", "*", "concediu*", "text:concediu", "^concediu",
    "(", ")", "col:*", "{concediu}", "-concediu", "+zile", "concediu NOT odihna",
    "'; DROP TABLE chunks; --", "x" * 100_000, "١٢٣ ٤٥", "\ud800 broken", "ﬁşă", "%_%",
]


@pytest.mark.parametrize("query", ODD_QUERIES, ids=[f"odd{n}" for n in range(len(ODD_QUERIES))])
def test_odd_queries_never_raise_and_leave_the_index_intact(kb, query):
    conn, sales, hr, docs = kb
    hits = search(conn, department_ids=[sales, hr], include_company=True, query=query)
    assert isinstance(hits, list) and all(isinstance(hit, Passage) for hit in hits)
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 9


@pytest.mark.parametrize("query", [None, 12, b"bytes", ["concediu"]])
def test_non_string_queries_return_nothing(kb, query):
    conn, sales, hr, docs = kb
    assert search(conn, department_ids=[hr], include_company=True, query=query) == []


def test_a_database_without_the_index_answers_empty_not_an_exception(caplog):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY, document_id INTEGER, page INTEGER,"
                 " text TEXT)")
    assert search(conn, department_ids=[1], include_company=True, query="concediu secret") == []
    assert "secret" not in caplog.text  # the query is user content and is never logged
    conn.close()
