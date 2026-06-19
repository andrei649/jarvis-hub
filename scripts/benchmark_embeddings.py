"""Benchmark embedding quality: dedicated model vs hash fallback.

Runs 10 sample queries, computes cosine similarity between semantically
related pairs, and prints a comparison table showing which backend retrieves
more semantically relevant content.

Usage:
    python scripts/benchmark_embeddings.py

Works offline — uses the deterministic hash fallback if both LM Studio and
Ollama are unavailable, so the script always produces output.  Set env vars
to benchmark a live embedding backend:

    EMBED_BACKEND=lmstudio EMBED_MODEL=mxbai-embed-large python scripts/benchmark_embeddings.py
    EMBED_BACKEND=ollama   EMBED_MODEL=mxbai-embed-large python scripts/benchmark_embeddings.py
"""

from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path

# Allow running from repo root without installing the package.
_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root))
sys.path.insert(0, str(_repo_root / "agents"))

from agents.core.ingestion.embedder import Embedder  # noqa: E402

# ---------------------------------------------------------------------------
# Sample queries: 5 related pairs  (anchor, related, unrelated)
# ---------------------------------------------------------------------------
BENCHMARK_PAIRS = [
    {
        "label": "Finance",
        "anchor": "What is my bank account balance?",
        "related": "Show me my current savings and checking balance",
        "unrelated": "How do I make pasta carbonara?",
    },
    {
        "label": "Calendar",
        "anchor": "What meetings do I have today?",
        "related": "List my appointments and events for this afternoon",
        "unrelated": "Deploy the latest Docker container to production",
    },
    {
        "label": "Health",
        "anchor": "How many steps did I walk yesterday?",
        "related": "Show my fitness activity and step count from Apple Health",
        "unrelated": "What is the capital of Romania?",
    },
    {
        "label": "Email",
        "anchor": "Do I have any unread emails from my manager?",
        "related": "Check my inbox for new messages from the team",
        "unrelated": "Turn off the living room lights",
    },
    {
        "label": "Weather",
        "anchor": "Will it rain in Bucharest tomorrow?",
        "related": "What is the weather forecast for this weekend in Bucharest?",
        "unrelated": "Summarize the latest news about AI startups",
    },
    {
        "label": "Code",
        "anchor": "How do I fix a Python import error?",
        "related": "Resolve ModuleNotFoundError when running a Python script",
        "unrelated": "Book a restaurant reservation for Friday evening",
    },
    {
        "label": "Music",
        "anchor": "Play some chill lo-fi music on Spotify",
        "related": "Start a lo-fi hip-hop playlist for focus and relaxation",
        "unrelated": "Generate a monthly expense report",
    },
    {
        "label": "Security",
        "anchor": "Was there any suspicious login activity?",
        "related": "Check audit logs for unusual access or security events",
        "unrelated": "What temperature should I cook chicken to?",
    },
    {
        "label": "Smart home",
        "anchor": "Set the bedroom temperature to 22 degrees",
        "related": "Adjust the thermostat in the bedroom to 22°C",
        "unrelated": "Explain the concept of reinforcement learning",
    },
    {
        "label": "Tasks",
        "anchor": "Remind me to call the dentist on Monday",
        "related": "Add a reminder to schedule a dental appointment next week",
        "unrelated": "What are the latest football match results?",
    },
]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _build_embedder(backend: str, model: str, base_url: str) -> Embedder:
    """Build embedder; falls back to hash if backend is unreachable."""
    e = Embedder(backend=backend, model=model, base_url=base_url,
                 max_retries=1, backoff_base=0.0)
    return e


def _run_benchmark(embedder: Embedder) -> list[dict]:
    results = []
    for pair in BENCHMARK_PAIRS:
        t0 = time.perf_counter()
        anchor_vec = embedder.embed(pair["anchor"])
        related_vec = embedder.embed(pair["related"])
        unrelated_vec = embedder.embed(pair["unrelated"])
        elapsed = time.perf_counter() - t0

        sim_related = _cosine(anchor_vec, related_vec)
        sim_unrelated = _cosine(anchor_vec, unrelated_vec)
        gap = sim_related - sim_unrelated

        results.append({
            "label": pair["label"],
            "sim_related": sim_related,
            "sim_unrelated": sim_unrelated,
            "gap": gap,
            "elapsed_s": elapsed,
        })
    return results


def _print_table(backend: str, model: str, results: list[dict]) -> None:
    header = f"Backend: {backend}  |  Model: {model}"
    print(f"\n{'=' * 74}")
    print(f"  {header}")
    print(f"{'=' * 74}")
    print(f"  {'Category':<14} {'Sim(related)':>13} {'Sim(unrelated)':>15} {'Gap':>8} {'OK?':>5}")
    print(f"  {'-'*14} {'-'*13} {'-'*15} {'-'*8} {'-'*5}")
    good = 0
    for r in results:
        ok = "YES" if r["gap"] > 0.02 else ("~" if r["gap"] > 0 else "NO")
        if ok == "YES":
            good += 1
        print(
            f"  {r['label']:<14} {r['sim_related']:>13.4f} {r['sim_unrelated']:>15.4f}"
            f" {r['gap']:>8.4f} {ok:>5}"
        )
    avg_gap = sum(r["gap"] for r in results) / len(results)
    avg_time = sum(r["elapsed_s"] for r in results) / len(results)
    print(f"  {'-'*14} {'-'*13} {'-'*15} {'-'*8} {'-'*5}")
    print(f"  {'AVERAGE':<14} {'':>13} {'':>15} {avg_gap:>8.4f} {good}/{len(results)}")
    print(f"  Avg embed time: {avg_time * 1000:.1f} ms/pair")
    print(f"{'=' * 74}")


def main() -> None:
    backend = os.getenv("EMBED_BACKEND", "lmstudio")
    default_model = (
        "mxbai-embed-large" if backend == "lmstudio"
        else "mxbai-embed-large"
    )
    model = os.getenv("EMBED_MODEL", default_model)
    base_url = os.getenv("EMBED_BASE_URL", "http://localhost:1234")

    print(f"Jarvis Hub — Embedding Quality Benchmark (H8.4)")
    print(f"Attempting backend: {backend!r}, model: {model!r}, url: {base_url!r}")
    print("(Falls back to hash embedding if backend is unreachable.)")

    embedder = _build_embedder(backend, model, base_url)

    # Detect if we actually fell back to hash after setup.
    actual_backend = embedder.backend
    if actual_backend != backend:
        print(f"  [WARN] Backend unavailable — using {actual_backend!r} fallback.")

    results = _run_benchmark(embedder)
    _print_table(actual_backend, embedder.model, results)

    # Also benchmark hash for comparison when we have a real backend.
    if actual_backend != "hash":
        print("\nComparing against hash fallback...")
        hash_embedder = Embedder(backend="hash", model="hash", max_retries=0, backoff_base=0.0)
        hash_results = _run_benchmark(hash_embedder)
        _print_table("hash", "hash", hash_results)

        # Summary comparison.
        live_avg = sum(r["gap"] for r in results) / len(results)
        hash_avg = sum(r["gap"] for r in hash_results) / len(hash_results)
        print(f"\nSummary: {actual_backend}/{model} avg gap = {live_avg:.4f} "
              f"vs hash avg gap = {hash_avg:.4f}")
        if live_avg > hash_avg:
            print(f"  => {actual_backend}/{model} is MORE semantically discriminating (+{live_avg - hash_avg:.4f})")
        else:
            print(f"  => hash fallback produces similar or better gaps ({hash_avg - live_avg:.4f} diff) "
                  "— check that the model is loaded correctly in LM Studio.")
    else:
        print("\n[INFO] No live backend available. Re-run with LM Studio or Ollama to compare.")
        print("  Recommended: load mxbai-embed-large in LM Studio, then:")
        print("    EMBED_BACKEND=lmstudio EMBED_MODEL=mxbai-embed-large python scripts/benchmark_embeddings.py")


if __name__ == "__main__":
    main()
