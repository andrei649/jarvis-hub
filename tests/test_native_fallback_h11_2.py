"""H11.2 — pure-Python fallback for the Rust hot-path crates (testable part)."""
import sys, os
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

from agents.core.memory import store as store_mod
from agents.core.memory.store import InMemoryVectorStore
from agents.core.native_fallback import (
    cosine_similarity, top_k_similar, count_tokens, load_native, BACKEND,
)


def test_cosine_similarity():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert abs(cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-9
    assert cosine_similarity([], []) == 0.0


def test_top_k_similar():
    q = [1.0, 0.0]
    vecs = [[0.0, 1.0], [1.0, 0.0], [0.7, 0.7]]
    out = top_k_similar(q, vecs, k=2)
    assert out[0][0] == 1                       # best match is index 1
    assert len(out) == 2


def test_count_tokens():
    assert count_tokens("hello world foo") == 3
    assert count_tokens("") == 0


def test_load_native_falls_back_to_python():
    # the Rust extension isn't built in-sandbox → fallback module
    mod = load_native()
    assert getattr(mod, "BACKEND", "python") == "python"
    assert BACKEND == "python"


# ── DRA-40: the hot path must actually reach load_native() ──────────────────────
#
# H11.2 claims `load_native()` "preferă extensia compilată, altfel Python →
# comportament identic cu/fără build". Before this, nothing outside this test file
# called it, so a built Rust crate was unreachable. These pin the wiring: the
# ranking dispatch consults the resolved module, prefers it when it reports
# BACKEND == "rust", and is byte-identical to the numpy path when it does not.


def _fake_rust(calls: list):
    """A stand-in for the built PyO3 extension, with real cosine math."""
    def _top_k(query, vectors, k):
        calls.append((list(query), [list(v) for v in vectors], k))
        return top_k_similar(query, vectors, k)

    return SimpleNamespace(BACKEND="rust", top_k_similar=_top_k)


def _seeded_store():
    store = InMemoryVectorStore(dimension=2)
    store.add("a", [0.0, 1.0], {"tag": "a"})
    store.add("b", [1.0, 0.0], {"tag": "b"})
    store.add("c", [0.7, 0.7], {"tag": "c"})
    return store


def test_vector_search_uses_the_native_backend_when_it_is_built(monkeypatch):
    calls = []
    monkeypatch.setattr(store_mod, "_NATIVE_BACKEND", _fake_rust(calls))
    store = _seeded_store()

    hits = store.search([1.0, 0.0], k=2)

    assert calls, "search must route through the resolved native module when BACKEND == 'rust'"
    assert [h["id"] for h in hits] == ["b", "c"]
    assert hits[0]["metadata"] == {"tag": "b"}
    assert hits[0]["score"] == pytest.approx(1.0, abs=1e-6)


def test_native_ranking_matches_the_numpy_path(monkeypatch):
    """'comportament identic cu/fără build' — same ids, same order, same scores."""
    query = [0.3, 0.9]
    expected = _seeded_store()._search_numpy(query, 3)

    monkeypatch.setattr(store_mod, "_NATIVE_BACKEND", _fake_rust([]))
    native = _seeded_store().search(query, k=3)

    assert [h["id"] for h in native] == [h["id"] for h in expected]
    for got, want in zip(native, expected, strict=True):
        assert got["score"] == pytest.approx(want["score"], abs=1e-6)
        assert got["metadata"] == want["metadata"]


def test_zero_query_guard_matches_the_numpy_path(monkeypatch):
    """The numpy path returns [] for a directionless query; native must not differ."""
    assert _seeded_store()._search_numpy([0.0, 0.0], 3) == []

    calls = []
    monkeypatch.setattr(store_mod, "_NATIVE_BACKEND", _fake_rust(calls))
    assert _seeded_store().search([0.0, 0.0], k=3) == []
    assert not calls, "a zero-norm query must short-circuit before the native call"


def test_unbuilt_extension_leaves_the_python_path_untouched(monkeypatch):
    """Default install (no crate): the fallback must not be used for ranking."""
    calls = []
    fallback = SimpleNamespace(
        BACKEND="python",
        top_k_similar=lambda *a, **kw: calls.append(a) or [],
    )
    monkeypatch.setattr(store_mod, "_NATIVE_BACKEND", fallback)
    store = _seeded_store()

    hits = store.search([1.0, 0.0], k=2)

    assert not calls, "BACKEND == 'python' must keep the existing numpy/naive dispatch"
    assert [h["id"] for h in hits] == ["b", "c"]


def test_native_rejects_a_wrong_length_query_like_numpy_does(monkeypatch):
    """np.dot raises on a dimension mismatch; the crate would silently truncate."""
    with pytest.raises(ValueError):
        _seeded_store()._search_numpy([1.0, 0.0, 0.0], 2)

    calls = []
    monkeypatch.setattr(store_mod, "_NATIVE_BACKEND", _fake_rust(calls))
    with pytest.raises(ValueError):
        _seeded_store().search([1.0, 0.0, 0.0], k=2)
    assert not calls, "the dimension guard must fire before the native call"


def test_search_by_text_subset_also_reaches_the_native_backend(monkeypatch):
    """The second ranking site must not be left half-wired."""
    calls = []
    monkeypatch.setattr(store_mod, "_NATIVE_BACKEND", _fake_rust(calls))
    store = _seeded_store()

    hits = store.search_by_text_subset([1.0, 0.0], k=2)

    assert calls, "search_by_text_subset must share the ranking dispatch"
    assert [h["id"] for h in hits] == ["b", "c"]
