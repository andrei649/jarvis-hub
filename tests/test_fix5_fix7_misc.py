"""Small regression tests for FIX 5 (Argus HUD metadata) and FIX 7 (embedder
in-process cache thread-safety)."""

import sys
import threading
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


# ── FIX 5: Argus present in the HUD agent metadata ────────────────────────────


def test_argus_in_agent_meta():
    from agents import web

    assert "argus" in web._AGENT_META, "argus missing from _AGENT_META"
    meta = web._AGENT_META["argus"]
    # tier business → BIZ, consistent with the other business-tier agents.
    assert meta["tier"] == "BIZ"
    assert "OSINT" in meta["role"] or "Intel" in meta["role"]


# ── FIX 7: _PROC_CACHE get/put are lock-guarded ───────────────────────────────


def test_embedder_proc_cache_has_lock():
    from agents.core.ingestion import embedder

    assert hasattr(embedder, "_PROC_CACHE_LOCK")
    assert isinstance(embedder._PROC_CACHE_LOCK, type(threading.Lock()))


def test_embedder_proc_cache_concurrent_access_is_safe():
    """Hammer the module-global cache from many threads; without the lock the
    OrderedDict's internal linked list corrupts (RuntimeError / KeyError) under
    concurrent move_to_end/popitem. With the lock it stays consistent."""
    from agents.core.ingestion import embedder

    embedder._PROC_CACHE.clear()
    errors = []

    def worker(n):
        try:
            for i in range(2000):
                key = ("ollama", "m", f"t{(n * 7 + i) % 64}")
                embedder._proc_cache_put(key, [float(i)])
                embedder._proc_cache_get(key)
        except Exception as e:  # pragma: no cover - only on a regression
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent cache access raised: {errors[:3]}"
    # Bound is respected even under concurrency.
    assert len(embedder._PROC_CACHE) <= embedder._PROC_CACHE_MAX
    embedder._PROC_CACHE.clear()
