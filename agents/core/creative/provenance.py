"""creative/provenance.py — 0.47 Creative Asset Pipeline: content-addressed lineage.

`creative/pipeline.py:plan_pipeline` already emits a *coordinated* stage plan; this gives it a
tamper-evident provenance **chain**: one record per stage, linked parent→child, each
fingerprinting its inputs + generator with SHA-256 — **tamper-evidence + dedup without storing
the content**. Mirrors the ingestion `ProvenanceLedger` (0.37) discipline.

Honest by construction: `generated: False` on every record — it fingerprints what a stage
*would* produce from its declared inputs, never a fabricated asset. Pure, deterministic,
offline (no clocks / randomness / network — the same plan always yields the same hashes).
"""

from __future__ import annotations

import hashlib
import json


def stage_content(stage: dict) -> dict:
    """The canonical, hashable view of a plan stage (what its fingerprint is taken over)."""
    s = stage if isinstance(stage, dict) else {}
    return {"stage": s.get("id"), "generator": s.get("generator"), "inputs": s.get("inputs")}


def fingerprint(payload) -> str:
    """Stable SHA-256 over a JSON-canonicalized payload (sorted keys, str-coerced)."""
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_chain(plan: dict) -> list[dict]:
    """Build the ordered provenance chain for a ``plan_pipeline`` result.

    One record per stage: ``{id, stage, parent_id, content_hash, generator, generated}``.
    ``parent_id`` links a stage to the one that fed it (script ← image_prompts ← render ← …),
    so ``lineage(id)`` walks the derivation. ``content_hash`` fingerprints ``stage_content``.
    """
    p = plan if isinstance(plan, dict) else {}
    slug = str(p.get("slug") or "asset")
    records: list[dict] = []
    parent = None
    for st in p.get("stages") or []:
        st = st if isinstance(st, dict) else {}
        rid = f"{slug}:{st.get('id')}"
        records.append({
            "id": rid,
            "stage": st.get("id"),
            "parent_id": parent,
            "content_hash": fingerprint(stage_content(st)),
            "generator": st.get("generator"),
            "generated": False,
        })
        parent = rid
    return records


def verify(record: dict, stage: dict) -> bool:
    """True iff *stage* still fingerprints to *record*'s ``content_hash`` (tamper check)."""
    r = record if isinstance(record, dict) else {}
    return r.get("content_hash") == fingerprint(stage_content(stage))


def lineage(records, rid: str) -> list[str]:
    """Walk *rid* → root via ``parent_id`` (cycle-guarded). Returns child→…→root ids."""
    by_id = {r.get("id"): r for r in (records or []) if isinstance(r, dict)}
    out: list[str] = []
    seen: set[str] = set()
    cur = rid
    while cur and cur in by_id and cur not in seen:
        seen.add(cur)
        out.append(cur)
        cur = by_id[cur].get("parent_id")
    return out
