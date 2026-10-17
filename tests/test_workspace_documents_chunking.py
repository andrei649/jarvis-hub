"""Chunking of extracted text (spec §6/§7): ~1000 chars, ~150 overlap, boundaries, pages.

A chunk is what retrieval returns and what the model cites, so the properties pinned
here are the ones answers depend on: no text is lost, a fact on a boundary appears whole
in one chunk, the page a citation names is right, and a slice of a table still says
what its columns mean.
"""

from __future__ import annotations

import random
from itertools import pairwise

import pytest

from agents.core.workspace import documents, extract
from agents.core.workspace.documents import CHUNK_OVERLAP, CHUNK_TARGET, chunk_segments
from agents.core.workspace.extract import Segment

_VOCABULARY = ("angajatul are dreptul la concediu de odihnă plătit iar cererea se depune la "
               "resurse umane cu cel puțin zece zile înainte de data începerii ședinței anuale")
_WORDS = tuple(_VOCABULARY.split())
_MAX_CHUNK = CHUNK_TARGET + 200 + 2  # a small chunk may take one more full-size piece


def _sentence(rng: random.Random) -> str:
    return " ".join(rng.choice(_WORDS) for _ in range(rng.randint(5, 28))).capitalize() + "."


def _prose(rng: random.Random, paragraphs: int) -> str:
    return "\n\n".join(" ".join(_sentence(rng) for _ in range(rng.randint(1, 9)))
                       for _ in range(paragraphs))


def _merged(chunks: list[documents.Chunk]) -> str:
    merged = ""
    for chunk in chunks:
        if not merged:
            merged = chunk.text
            continue
        repeated = documents._overlap_length(merged, chunk.text)
        merged += chunk.text[repeated:] if repeated else "\n\n" + chunk.text
    return merged


def test_nothing_to_chunk_gives_no_chunks():
    assert chunk_segments([]) == []
    assert chunk_segments([Segment(None, "")]) == []


def test_a_short_document_is_one_chunk_with_its_page():
    chunks = chunk_segments([Segment(3, "Ședința are loc în martie.")])
    assert chunks == [documents.Chunk(ord=0, page=3, text="Ședința are loc în martie.")]


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_long_prose_is_about_a_thousand_chars_per_chunk_and_loses_nothing(seed):
    text = _prose(random.Random(seed), 60)
    chunks = chunk_segments([Segment(None, text)])
    sizes = [len(chunk.text) for chunk in chunks]
    assert max(sizes) <= _MAX_CHUNK
    assert sum(sizes[:-1]) / len(sizes[:-1]) >= 0.6 * CHUNK_TARGET
    assert [chunk.ord for chunk in chunks] == list(range(len(chunks)))
    assert _merged(chunks).split() == text.split()


@pytest.mark.parametrize("seed", [4, 5])
def test_consecutive_chunks_overlap_by_a_word_bounded_suffix(seed):
    chunks = chunk_segments([Segment(None, _prose(random.Random(seed), 40))])
    overlaps = [documents._overlap_length(a.text, b.text) for a, b in pairwise(chunks)]
    assert all(20 <= size <= CHUNK_OVERLAP for size in overlaps), overlaps
    for (previous, current), size in zip(pairwise(chunks), overlaps, strict=True):
        assert previous.text.endswith(current.text[:size])
        assert previous.text[-size - 1].isspace()  # the overlap starts at a word boundary


def test_long_paragraphs_are_cut_at_sentence_ends():
    sentences = [f"Propoziția numărul {n} descrie o regulă a firmei pe larg și clar." for n in range(60)]
    chunks = chunk_segments([Segment(None, " ".join(sentences))])
    assert len(chunks) > 2
    assert all(chunk.text.endswith(".") for chunk in chunks)
    assert all(chunk.text[0].isupper() for chunk in chunks)  # each starts at a sentence start


def test_a_word_longer_than_a_chunk_is_cut_hard():
    blob = "x" * 2500
    chunks = chunk_segments([Segment(None, f"Cod: {blob} sfârșit.")])
    assert all(len(chunk.text) <= _MAX_CHUNK for chunk in chunks)
    assert "".join(chunks[i].text for i in range(len(chunks))).count("x") >= 2500


def test_page_numbers_follow_the_new_text_of_each_chunk():
    rng = random.Random(7)
    pages = [Segment(page, _prose(rng, 6)) for page in (1, 2, 3, 4)]
    chunks = chunk_segments(pages)
    assert [chunk.page for chunk in chunks] == sorted(chunk.page for chunk in chunks)
    assert {chunk.page for chunk in chunks} == {1, 2, 3, 4}
    for previous, current in pairwise(chunks):
        fresh = current.text[documents._overlap_length(previous.text, current.text):].strip()
        source = next(segment for segment in pages if segment.page == current.page)
        assert " ".join(fresh.split()[:6]) in " ".join(source.text.split())


def test_a_big_table_is_split_between_rows_and_every_part_repeats_heading_and_header():
    rows = [["Lună", "Regiune", "Valoare (lei)"]] + [
        [f"Luna {n}", "Brașov" if n % 2 else "Cluj-Napoca", str(n * 1000)] for n in range(300)]
    text = "## Vânzări 2026\n\n" + extract.markdown_table(rows)
    chunks = chunk_segments([Segment(None, text)])
    assert len(chunks) > 3
    for chunk in chunks:
        lines = chunk.text.split("\n")
        assert lines[:4] == ["## Vânzări 2026", "", "| Lună | Regiune | Valoare (lei) |",
                             "| --- | --- | --- |"]
        assert all(line.startswith("| Luna ") and line.endswith(" |") for line in lines[4:])
        assert len(chunk.text) <= CHUNK_TARGET
    body_rows = [line for chunk in chunks for line in chunk.text.split("\n")[4:]]
    assert len(body_rows) == 300 and len(set(body_rows)) == 300  # no row lost or repeated


def test_a_table_without_a_heading_repeats_only_its_header():
    rows = [["Cod", "Produs"]] + [[f"P{n:04d}", "Țeavă de cupru de 22 mm"] for n in range(120)]
    chunks = chunk_segments([Segment(None, "Introducere scurtă.\n\n" + extract.markdown_table(rows))])
    assert all("| Cod | Produs |\n| --- | --- |" in chunk.text for chunk in chunks)
    assert not any(chunk.text.startswith("Introducere") for chunk in chunks[1:])


def test_a_table_row_longer_than_a_chunk_is_still_kept():
    rows = [["Câmp", "Descriere"], ["lung", "cuvânt " * 400], ["scurt", "ok"]]
    chunks = chunk_segments([Segment(None, extract.markdown_table(rows))])
    joined = " ".join(chunk.text for chunk in chunks)
    assert joined.count("cuvânt") == 400 and "| scurt | ok |" in joined


def test_tiny_chunks_carry_no_overlap():
    pieces = documents._overlap_pieces([documents._Piece("Scurt.", None, "\n\n", True)],
                                       CHUNK_OVERLAP)
    assert pieces == []


def test_the_default_sizes_are_the_spec_values():
    assert (CHUNK_TARGET, CHUNK_OVERLAP) == (1000, 150)
