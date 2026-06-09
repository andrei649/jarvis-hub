"""H11.2 — pure-Python fallback for the Rust hot-path crates (testable part)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

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
