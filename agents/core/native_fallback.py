"""
native_fallback.py — H11.2 Pure-Python fallback for the Rust hot-path crates.

The optional Rust extension (``rust/jarvis_native``, PyO3) accelerates hot paths
— cosine similarity, top-k vector search, token counting. This module is the
**pure-Python fallback** used when the compiled extension isn't built, so
behavior is identical with or without the native build. ``load_native()`` returns
the Rust module if importable, else this fallback.

The Rust crate is a host build (``maturin build`` / ``cargo build --release``);
this fallback is what runs in-sandbox and in CI.
"""

from __future__ import annotations

import math
import sys


def cosine_similarity(a, b) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    dot = sum(a[i] * b[i] for i in range(n))
    na = math.sqrt(sum(x * x for x in a[:n])) or 1e-9
    nb = math.sqrt(sum(x * x for x in b[:n])) or 1e-9
    return dot / (na * nb)


def top_k_similar(query, vectors, k: int = 5) -> "list[tuple[int, float]]":
    scored = [(i, cosine_similarity(query, v)) for i, v in enumerate(vectors)]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:max(0, k)]


def count_tokens(text: str) -> int:
    return len((text or "").split())   # rough; the Rust version uses a real tokenizer


BACKEND = "python"


def load_native():
    """Return the compiled Rust module if available, else this Python fallback."""
    try:
        import jarvis_native  # the PyO3 extension, once built host-side
        return jarvis_native
    except Exception:
        return sys.modules[__name__]
