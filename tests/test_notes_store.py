"""Tests for the block-tree notes store (agents/core/notes_store.py).

Offline, dependency-free. Covers: doc + nested blocks; stable ordering after an
insert-in-the-middle (siblings are NOT renumbered/reordered); move_block
reparent + reorder; cascade delete; render_tree nesting + order; persistence
round-trip across a reopen; and the fractional-index helper directly.
"""
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import pytest

from agents.core.notes_store import NotesStore, NotesStoreError, _key_between


@pytest.fixture
def store():
    s = NotesStore(":memory:").initialize()
    try:
        yield s
    finally:
        s.close()


def _ids(blocks):
    return [b["id"] for b in blocks]


# ── fractional-index helper ───────────────────────────────────────────
def test_key_between_orders_lexicographically():
    a = _key_between(None, None)
    b = _key_between(a, None)
    c = _key_between(b, None)
    assert a < b < c

    # Insert between a and b — strictly between, doesn't equal endpoints.
    mid = _key_between(a, b)
    assert a < mid < b
    assert mid not in (a, b)


def test_key_between_repeated_middle_inserts_stay_ordered():
    lo = _key_between(None, None)
    hi = _key_between(lo, None)
    inserted = []  # keys minted into the (lo, hi) gap, in mint order
    # Hammer the same gap 30 times; ordering must remain total + correct.
    left = lo
    for _ in range(30):
        k = _key_between(left, hi)
        assert left < k < hi
        inserted.append(k)
        left = k
    # Each mint lands just right of the previous one, so mint order == sort
    # order, and there are no collisions across the whole sequence.
    sequence = [lo] + inserted + [hi]
    assert sequence == sorted(sequence)
    assert len(set(sequence)) == len(sequence)


def test_key_between_rejects_inverted_bounds():
    with pytest.raises(ValueError):
        _key_between("Z", "A")


# ── docs + nested blocks ──────────────────────────────────────────────
def test_create_doc_and_nested_blocks(store):
    doc = store.create_doc("My Note")
    assert store.get_doc(doc)["title"] == "My Note"

    h = store.add_block(doc, "heading", "Title")
    p1 = store.add_block(doc, "paragraph", "intro", parent_id=h)
    p2 = store.add_block(doc, "paragraph", "more", parent_id=h)

    top = store.children(None, doc_id=doc)
    assert _ids(top) == [h]
    kids = store.children(h)
    assert _ids(kids) == [p1, p2]
    assert kids[0]["text"] == "intro"
    assert kids[0]["type"] == "paragraph"


def test_add_block_attrs_and_delta_path(store):
    doc = store.create_doc()
    b = store.add_block(
        doc, "paragraph", "hi",
        attrs={"delta": [{"insert": "hi", "attributes": {"bold": True}}]},
    )
    got = store.get_block(b)
    assert got["attrs"]["delta"][0]["attributes"]["bold"] is True


def test_add_block_validates_doc_and_parent(store):
    doc = store.create_doc()
    with pytest.raises(NotesStoreError):
        store.add_block("nope", "paragraph", "x")
    with pytest.raises(NotesStoreError):
        store.add_block(doc, "paragraph", "x", parent_id="ghost")
    # parent in a different doc is rejected
    other = store.create_doc()
    ob = store.add_block(other, "paragraph", "o")
    with pytest.raises(NotesStoreError):
        store.add_block(doc, "paragraph", "x", parent_id=ob)


# ── ordering: insert in the middle is stable ──────────────────────────
def test_insert_in_middle_does_not_renumber_siblings(store):
    doc = store.create_doc()
    a = store.add_block(doc, "list_item", "A")
    b = store.add_block(doc, "list_item", "B")
    c = store.add_block(doc, "list_item", "C")

    # Snapshot the ordering keys of the untouched siblings.
    before = {blk["id"]: blk["ordering"] for blk in store.children(None, doc_id=doc)}

    # Insert X between A and B.
    x = store.add_block(doc, "list_item", "X", after=a)

    order = _ids(store.children(None, doc_id=doc))
    assert order == [a, x, b, c]

    after = {blk["id"]: blk["ordering"] for blk in store.children(None, doc_id=doc)}
    # Existing siblings keep their EXACT ordering keys — nobody got renumbered.
    for sib in (a, b, c):
        assert after[sib] == before[sib]
    # X's key sits strictly between A and B.
    assert after[a] < after[x] < after[b]


def test_append_keeps_order(store):
    doc = store.create_doc()
    ids = [store.add_block(doc, "paragraph", str(i)) for i in range(5)]
    assert _ids(store.children(None, doc_id=doc)) == ids


def test_after_must_be_sibling(store):
    doc = store.create_doc()
    a = store.add_block(doc, "paragraph", "A")
    child = store.add_block(doc, "paragraph", "child", parent_id=a)
    # `after` a block under a different parent is rejected.
    with pytest.raises(NotesStoreError):
        store.add_block(doc, "paragraph", "B", after=child)


# ── move_block reparent + reorder ─────────────────────────────────────
def test_move_block_reparents(store):
    doc = store.create_doc()
    h1 = store.add_block(doc, "heading", "H1")
    h2 = store.add_block(doc, "heading", "H2")
    p = store.add_block(doc, "paragraph", "p", parent_id=h1)

    assert _ids(store.children(h1)) == [p]
    moved = store.move_block(p, new_parent=h2)
    assert moved["parent_id"] == h2
    assert _ids(store.children(h1)) == []
    assert _ids(store.children(h2)) == [p]


def test_move_block_reorders_among_siblings(store):
    doc = store.create_doc()
    a = store.add_block(doc, "list_item", "A")
    b = store.add_block(doc, "list_item", "B")
    c = store.add_block(doc, "list_item", "C")
    # Move C to sit right after A.
    store.move_block(c, after=a)
    assert _ids(store.children(None, doc_id=doc)) == [a, c, b]


def test_move_to_top_level(store):
    doc = store.create_doc()
    h = store.add_block(doc, "heading", "H")
    p = store.add_block(doc, "paragraph", "p", parent_id=h)
    store.move_block(p, new_parent=None)
    assert _ids(store.children(None, doc_id=doc)) == [h, p]


def test_move_under_own_descendant_rejected(store):
    doc = store.create_doc()
    a = store.add_block(doc, "list_item", "A")
    b = store.add_block(doc, "list_item", "B", parent_id=a)
    c = store.add_block(doc, "list_item", "C", parent_id=b)
    with pytest.raises(NotesStoreError):
        store.move_block(a, new_parent=c)   # would create a cycle
    with pytest.raises(NotesStoreError):
        store.move_block(a, new_parent=a)   # under itself


# ── delete cascades to descendants ────────────────────────────────────
def test_delete_cascades_to_descendants(store):
    doc = store.create_doc()
    root = store.add_block(doc, "list_item", "root")
    c1 = store.add_block(doc, "list_item", "c1", parent_id=root)
    c2 = store.add_block(doc, "list_item", "c2", parent_id=root)
    g1 = store.add_block(doc, "list_item", "g1", parent_id=c1)
    sibling = store.add_block(doc, "list_item", "sibling")

    n = store.delete_block(root)
    assert n == 4  # root + c1 + c2 + g1
    for gone in (root, c1, c2, g1):
        assert store.get_block(gone) is None
    # The unrelated sibling survives.
    assert store.get_block(sibling) is not None
    assert _ids(store.children(None, doc_id=doc)) == [sibling]


def test_delete_missing_raises(store):
    with pytest.raises(NotesStoreError):
        store.delete_block("ghost")


# ── update_block ──────────────────────────────────────────────────────
def test_update_block_text_attrs_type(store):
    doc = store.create_doc()
    b = store.add_block(doc, "paragraph", "old")
    updated = store.update_block(b, text="new", attrs={"k": 1}, type="todo")
    assert updated["text"] == "new"
    assert updated["attrs"] == {"k": 1}
    assert updated["type"] == "todo"
    # updated_at advanced (or at least is present).
    assert updated["updated_at"]


def test_update_missing_raises(store):
    with pytest.raises(NotesStoreError):
        store.update_block("ghost", text="x")


# ── render_tree: nested order ─────────────────────────────────────────
def test_render_tree_nested_order(store):
    doc = store.create_doc("Doc")
    h = store.add_block(doc, "heading", "H")
    a = store.add_block(doc, "list_item", "A", parent_id=h)
    b = store.add_block(doc, "list_item", "B", parent_id=h)
    a1 = store.add_block(doc, "list_item", "A.1", parent_id=a)
    foot = store.add_block(doc, "paragraph", "foot")

    tree = store.render_tree(doc)
    assert tree["title"] == "Doc"
    top = tree["children"]
    assert [n["id"] for n in top] == [h, foot]
    hkids = top[0]["children"]
    assert [n["id"] for n in hkids] == [a, b]
    assert [n["id"] for n in hkids[0]["children"]] == [a1]
    assert hkids[1]["children"] == []


def test_render_tree_reflects_midinsert_order(store):
    doc = store.create_doc()
    a = store.add_block(doc, "list_item", "A")
    b = store.add_block(doc, "list_item", "B")
    x = store.add_block(doc, "list_item", "X", after=a)
    tree = store.render_tree(doc)
    assert [n["text"] for n in tree["children"]] == ["A", "X", "B"]


# ── persistence round-trip ────────────────────────────────────────────
def test_round_trip_persist_reopen(tmp_path):
    db = str(tmp_path / "notes.db")
    s1 = NotesStore(db).initialize()
    doc = s1.create_doc("Persisted")
    h = s1.add_block(doc, "heading", "H")
    p = s1.add_block(doc, "paragraph", "body", parent_id=h)
    x = s1.add_block(doc, "list_item", "mid", after=h)  # top-level, between h and end
    s1.close()

    s2 = NotesStore(db).initialize()
    try:
        tree = s2.render_tree(doc)
        assert tree["title"] == "Persisted"
        top = [n["id"] for n in tree["children"]]
        assert top == [h, x]
        assert tree["children"][0]["children"][0]["id"] == p
        assert s2.get_block(p)["text"] == "body"
    finally:
        s2.close()


def test_round_trip_preserves_ordering_keys(tmp_path):
    db = str(tmp_path / "notes2.db")
    s1 = NotesStore(db).initialize()
    doc = s1.create_doc()
    ids = [s1.add_block(doc, "paragraph", str(i)) for i in range(4)]
    keys = {b["id"]: b["ordering"] for b in s1.children(None, doc_id=doc)}
    s1.close()

    s2 = NotesStore(db).initialize()
    try:
        keys2 = {b["id"]: b["ordering"] for b in s2.children(None, doc_id=doc)}
        assert keys2 == keys
        assert _ids(s2.children(None, doc_id=doc)) == ids
    finally:
        s2.close()


# ── DRA-53: the two methods adoption behind a route actually needs ────
def test_list_docs_returns_docs_most_recently_updated_first(store):
    """Without list_docs a HUD panel can create a doc and then lose its id on
    reload — the surface would be write-only and degenerate."""
    a = store.create_doc("alpha")
    b = store.create_doc("beta")
    # touching alpha's blocks bumps its updated_at (add_block does the UPDATE)
    store.add_block(a, "paragraph", "hello")

    docs = store.list_docs()
    assert [d["id"] for d in docs] == [a, b]
    assert docs[0]["title"] == "alpha"
    # the listing is a summary, not the whole tree
    assert set(docs[0]) == {"id", "title", "created_at", "updated_at"}


def test_list_docs_respects_limit(store):
    for i in range(5):
        store.create_doc(f"doc-{i}")
    assert len(store.list_docs(limit=2)) == 2


def test_delete_doc_removes_the_doc_and_all_of_its_blocks(store):
    doc = store.create_doc("throwaway")
    head = store.add_block(doc, "heading", "H")
    child = store.add_block(doc, "paragraph", "under H", parent_id=head)
    keeper = store.create_doc("kept")
    kept_block = store.add_block(keeper, "paragraph", "still here")

    removed = store.delete_doc(doc)

    assert removed == 2                      # both blocks, counted honestly
    assert store.get_doc(doc) is None
    assert store.get_block(head) is None
    assert store.get_block(child) is None
    # a delete must not reach into a different document
    assert store.get_doc(keeper) is not None
    assert store.get_block(kept_block) is not None
    assert [d["id"] for d in store.list_docs()] == [keeper]


def test_delete_doc_raises_on_an_unknown_doc(store):
    with pytest.raises(NotesStoreError):
        store.delete_doc("no-such-doc")


# ── strictly-monotonic _now(): list_docs must not flake inside one clock tick ─
def test_now_is_strictly_monotonic_when_the_wall_clock_stands_still(monkeypatch):
    """On Windows (pre-3.13) the wall clock ticks every ~15.6 ms, so two
    writes routinely read the *same* instant; ``list_docs`` orders on
    ``updated_at`` alone and the tie broke on a random UUID (~50% red in CI).
    ``_now`` must hand out strictly increasing stamps regardless of the clock."""
    from datetime import UTC, datetime

    from agents.core import notes_store

    frozen = datetime(2026, 9, 2, 12, 0, 0, 500_000, tzinfo=UTC)
    monkeypatch.setattr(notes_store, "_wall_clock", lambda: frozen)
    monkeypatch.setattr(notes_store, "_LAST_NOW", None)

    stamps = [notes_store._now() for _ in range(5)]
    # Strictly increasing both as datetimes and as the TEXT SQLite compares.
    assert stamps == sorted(stamps) and len(set(stamps)) == len(stamps)
    for earlier, later in zip(stamps, stamps[1:], strict=False):
        assert later > earlier
        assert datetime.fromisoformat(later) > datetime.fromisoformat(earlier)
    # Format is unchanged (ISO-8601 UTC with microseconds) so rows written
    # before the fix still compare correctly with rows written after it.
    assert stamps[0] == "2026-09-02T12:00:00.500000+00:00"
    assert stamps[1] == "2026-09-02T12:00:00.500001+00:00"


def test_now_never_goes_backwards_if_the_wall_clock_does(monkeypatch):
    from datetime import UTC, datetime, timedelta

    from agents.core import notes_store

    base = datetime(2026, 9, 2, 12, 0, 0, tzinfo=UTC)
    reads = iter([base, base - timedelta(seconds=5), base + timedelta(seconds=1)])
    monkeypatch.setattr(notes_store, "_wall_clock", lambda: next(reads))
    monkeypatch.setattr(notes_store, "_LAST_NOW", None)
    first, second, third = (notes_store._now() for _ in range(3))
    assert first < second < third
    # once the clock genuinely advances, the real reading is used again
    assert third == "2026-09-02T12:00:01.000000+00:00"


def test_list_docs_orders_correctly_inside_a_single_clock_tick(store, monkeypatch):
    """The Windows-red regression, forced deterministically: every writer of
    docs.updated_at (create_doc, add_block, update/move/delete_block) reads the
    same wall-clock instant, yet the most recently touched doc still lists first."""
    from datetime import UTC, datetime

    from agents.core import notes_store

    frozen = datetime(2026, 9, 2, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(notes_store, "_wall_clock", lambda: frozen)
    monkeypatch.setattr(notes_store, "_LAST_NOW", None)

    a = store.create_doc("alpha")
    b = store.create_doc("beta")
    assert [d["id"] for d in store.list_docs()] == [b, a]

    block = store.add_block(a, "paragraph", "hello")
    assert [d["id"] for d in store.list_docs()] == [a, b]

    store.add_block(b, "paragraph", "world")
    assert [d["id"] for d in store.list_docs()] == [b, a]

    store.update_block(block, text="hello again")
    assert [d["id"] for d in store.list_docs()] == [a, b]

    c = store.create_doc("gamma")
    assert [d["id"] for d in store.list_docs()] == [c, a, b]

    store.delete_block(block)
    assert [d["id"] for d in store.list_docs()] == [a, c, b]
