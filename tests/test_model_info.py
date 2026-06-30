"""H23.2 (reproducibility half) — per-run model fingerprints {id, version, quant, sha256}.

Covers agents/core/observability/model_info.py (quant parsing, entry normalization for
LM Studio + Ollama listing shapes, the registry: register/get/all/ingest_listing/stats/
bounded eviction/callable-resolver, opt-in default helper) and the Tracer enrichment hook
(stamps model_info via the resolver; stays {} when no resolver / unknown model). Pure/offline.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.observability import model_info as mi  # noqa: E402
from agents.core.observability.tracer import Tracer  # noqa: E402


# ── quant parsing ───────────────────────────────────────────────────────────────
def test_parse_quant_from_gguf_filename():
    assert mi.parse_quant("Qwen2.5-7B-Instruct-Q4_K_M.gguf") == "Q4_K_M"
    assert mi.parse_quant("llama-3.1-8b-IQ3_XXS") == "IQ3_XXS"
    assert mi.parse_quant("some-model-F16") == "F16"
    assert mi.parse_quant("plain-model-name") == ""


# ── entry normalization (LM Studio + Ollama shapes) ──────────────────────────────
def test_fingerprint_openai_shape():
    fp = mi.fingerprint_from_entry({"id": "qwen2.5-7b-Q4_K_M", "created": 1700000000})
    assert fp == {"id": "qwen2.5-7b-Q4_K_M", "version": "1700000000",
                  "quant": "Q4_K_M", "sha256": ""}


def test_fingerprint_ollama_shape():
    fp = mi.fingerprint_from_entry(
        {"name": "llama3.1:8b", "digest": "abc123", "modified_at": "2026-01-01T00:00:00Z"})
    assert fp["id"] == "llama3.1:8b"
    assert fp["sha256"] == "abc123" and fp["version"] == "2026-01-01T00:00:00Z"


def test_fingerprint_explicit_fields_win_over_parsing():
    fp = mi.fingerprint_from_entry(
        {"id": "m-Q4_K_M", "quant": "Q8_0", "sha256": "deadbeef", "version": "v2"})
    assert fp["quant"] == "Q8_0" and fp["sha256"] == "deadbeef" and fp["version"] == "v2"


def test_fingerprint_tolerates_garbage():
    assert mi.fingerprint_from_entry("not a dict")["id"] == ""
    assert mi.fingerprint_from_entry({})["id"] == ""


# ── registry ─────────────────────────────────────────────────────────────────────
def test_register_get_and_callable_resolver():
    reg = mi.ModelInfoRegistry()
    reg.register(id="m1", version="v1", quant="Q4_K_M", sha256="aa")
    assert reg.get("m1") == {"id": "m1", "version": "v1", "quant": "Q4_K_M", "sha256": "aa"}
    assert reg.get("missing") is None
    # callable: usable directly as the tracer resolver
    assert reg("m1")["quant"] == "Q4_K_M"
    # empty id is ignored
    assert reg.register(id="") == {}


def test_ingest_listing_accepts_wrappers_and_bare_list():
    reg = mi.ModelInfoRegistry()
    n = reg.ingest_listing({"models": [{"id": "a-Q4_0"}, {"name": "b:latest", "digest": "d"}]})
    assert n == 2
    assert reg.get("a-Q4_0")["quant"] == "Q4_0"
    assert reg.get("b:latest")["sha256"] == "d"
    # OpenAI {"data": [...]} wrapper + skips id-less entries
    reg2 = mi.ModelInfoRegistry()
    assert reg2.ingest_listing({"data": [{"id": "x"}, {"no_id": 1}]}) == 1
    assert [m["id"] for m in reg2.all()] == ["x"]


def test_all_is_sorted_and_stats():
    reg = mi.ModelInfoRegistry()
    reg.register(id="zeta", sha256="z")
    reg.register(id="alpha", quant="Q4_K_M")
    assert [m["id"] for m in reg.all()] == ["alpha", "zeta"]
    s = reg.stats()
    assert s == {"total": 2, "with_sha256": 1, "with_quant": 1}


def test_bounded_eviction_drops_oldest():
    reg = mi.ModelInfoRegistry(max_keep=2)
    reg.register(id="a")
    reg.register(id="b")
    reg.register(id="c")          # evicts "a" (oldest inserted)
    assert reg.get("a") is None
    assert reg.get("b") is not None and reg.get("c") is not None


def test_default_registry_if_enabled_is_opt_in(monkeypatch):
    assert mi.default_registry_if_enabled(env={}) is None
    assert mi.default_registry_if_enabled(env={"JARVIS_MODEL_INFO": ""}) is None
    reg = mi.default_registry_if_enabled(env={"JARVIS_MODEL_INFO": "1"})
    assert isinstance(reg, mi.ModelInfoRegistry)


# ── tracer enrichment hook ───────────────────────────────────────────────────────
def test_tracer_without_resolver_leaves_model_info_empty():
    t = Tracer()
    tid = t.record({"model": "qwen2.5-7b-Q4_K_M"})
    assert t.get(tid)["model_info"] == {}


def test_tracer_stamps_model_info_from_resolver():
    reg = mi.ModelInfoRegistry()
    reg.register(id="qwen2.5-7b-Q4_K_M", version="v1", quant="Q4_K_M", sha256="aa")
    t = Tracer(model_info=reg)
    tid = t.record({"model": "qwen2.5-7b-Q4_K_M"})
    info = t.get(tid)["model_info"]
    assert info["quant"] == "Q4_K_M" and info["sha256"] == "aa"
    # unknown model → stays empty (resolver returns None), never raises
    tid2 = t.record({"model": "unknown-model"})
    assert t.get(tid2)["model_info"] == {}
    # summary surface also carries the field (flows through /api/traces)
    summaries = t.list(5)
    assert all("model_info" in s for s in summaries)
    assert any(s["model_info"].get("quant") == "Q4_K_M" for s in summaries)


def test_tracer_resolver_hiccup_never_breaks_recording():
    def boom(_):
        raise RuntimeError("resolver down")
    t = Tracer(model_info=boom)
    tid = t.record({"model": "m1"})        # must not raise
    assert t.get(tid)["model_info"] == {}
