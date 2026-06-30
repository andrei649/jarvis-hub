"""model_info.py — H23.2: per-run model fingerprints ``{id, version, quant, sha256}``.

H23.2's *pinning* half (the approved-model allowlist) shipped already; this is the
*reproducibility* half — recording **which exact model build produced a run** so a
trace can be tied back to an id + version + quantization + content hash.

**Opt-in / default-off** (``JARVIS_MODEL_INFO``): a small in-memory registry the
:class:`~agents.core.observability.tracer.Tracer` consults to stamp each trace with
the model's fingerprint. With the flag unset there is no registry, the tracer's
resolver is ``None``, and a trace's ``model_info`` stays ``{}`` — byte-identical.

The registry is **pure/offline**: it's populated by ingesting a backend model
listing (LM Studio / Ollama ``/v1/models``). The *live fetch* of that listing is the
host seam (network, owner-gated) — this module only parses + stores what it's given,
so the rail is fully testable without a backend.
"""

from __future__ import annotations

import os
import re

_DEFAULT_MAX_KEEP = 200
# Quant tags as they appear in GGUF ids/filenames: Q4_K_M, Q8_0, IQ3_XXS, F16, BF16…
_QUANT_RE = re.compile(r"\b(IQ\d\w*|Q\d\w*|BF16|F16|F32)\b", re.IGNORECASE)


def parse_quant(model_id: str) -> str:
    """Best-effort quantization tag from a model id / GGUF filename.

    ``"Qwen2.5-7B-Instruct-Q4_K_M.gguf"`` → ``"Q4_K_M"``; ``""`` when none is found.
    """
    m = _QUANT_RE.search(model_id or "")
    return m.group(1) if m else ""


def fingerprint_from_entry(entry: dict) -> dict:
    """Normalize one ``/v1/models``-style entry into ``{id, version, quant, sha256}``.

    Tolerates the differing shapes of LM Studio (OpenAI-compatible: ``id``/``created``)
    and Ollama (``name``/``model``/``digest``/``modified_at``). ``quant`` falls back to
    parsing the id when the backend doesn't report it. Never raises on a partial entry.
    """
    if not isinstance(entry, dict):
        return {"id": "", "version": "", "quant": "", "sha256": ""}
    mid = str(entry.get("id") or entry.get("model") or entry.get("name") or "")
    return {
        "id": mid,
        "version": str(entry.get("version") or entry.get("modified_at") or entry.get("created") or ""),
        "quant": str(entry.get("quant") or entry.get("quantization") or parse_quant(mid)),
        "sha256": str(entry.get("sha256") or entry.get("digest") or ""),
    }


def _listing_entries(listing) -> list[dict]:
    """Coax a backend listing into a flat list of entry dicts.

    Accepts a bare ``list`` or the common wrappers ``{"models": [...]}`` (Ollama /
    this app's ``_list_local_models``) and ``{"data": [...]}`` (OpenAI ``/v1/models``).
    """
    if isinstance(listing, dict):
        listing = listing.get("models") or listing.get("data") or []
    return [e for e in listing if isinstance(e, dict)] if isinstance(listing, list) else []


class ModelInfoRegistry:
    """Bounded in-memory map ``model_id -> fingerprint`` (read-mostly).

    Callable, so an instance can be passed straight to ``Tracer(model_info=...)`` as
    the resolver: ``registry(model_id)`` returns the fingerprint dict or ``None``.
    """

    def __init__(self, *, max_keep: int = _DEFAULT_MAX_KEEP) -> None:
        self._max_keep = max(1, int(max_keep))
        self._by_id: dict[str, dict] = {}

    def register(self, *, id: str, version: str = "", quant: str = "", sha256: str = "") -> dict:
        """Record (or overwrite) one model's fingerprint. Ignores an empty id."""
        mid = str(id or "")
        if not mid:
            return {}
        fp = {"id": mid, "version": str(version), "quant": str(quant), "sha256": str(sha256)}
        # Bound the registry: drop the oldest-inserted id when over capacity.
        if mid not in self._by_id and len(self._by_id) >= self._max_keep:
            oldest = next(iter(self._by_id))
            self._by_id.pop(oldest, None)
        self._by_id[mid] = fp
        return dict(fp)

    def ingest_listing(self, listing) -> int:
        """Register every entry from a backend model listing. Returns how many were
        stored (entries with no resolvable id are skipped). Idempotent per id."""
        count = 0
        for entry in _listing_entries(listing):
            fp = fingerprint_from_entry(entry)
            if fp["id"]:
                self.register(**fp)
                count += 1
        return count

    def get(self, model_id: str) -> dict | None:
        fp = self._by_id.get(str(model_id or ""))
        return dict(fp) if fp is not None else None

    # The tracer resolver protocol is just "call me with a model id".
    __call__ = get

    def all(self) -> list[dict]:
        """Every known fingerprint, sorted by id."""
        return [dict(v) for _, v in sorted(self._by_id.items())]

    def stats(self) -> dict:
        items = self._by_id.values()
        return {
            "total": len(self._by_id),
            "with_sha256": sum(1 for v in items if v.get("sha256")),
            "with_quant": sum(1 for v in items if v.get("quant")),
        }


def default_registry_if_enabled(env=None) -> ModelInfoRegistry | None:
    """Return a fresh :class:`ModelInfoRegistry` when ``JARVIS_MODEL_INFO`` is set,
    else ``None`` — the opt-in switch. ``None`` → the tracer records no ``model_info``
    and the read surface reports ``enabled: false`` (byte-identical default)."""
    e = os.environ if env is None else env
    return ModelInfoRegistry() if e.get("JARVIS_MODEL_INFO") else None
