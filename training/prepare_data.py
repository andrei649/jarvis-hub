"""
prepare_data.py — H11.3 Build an SFT dataset from collected traces.

Pure-Python (no GPU/deps) — this part runs in-sandbox/CI. Converts trace records
into ShareGPT-style SFT examples, optionally filtered by a quality score, and
serializes them to JSONL for `sft_grpo.py`.
"""

from __future__ import annotations

import json
from typing import Optional


def trace_to_sft(trace: dict) -> Optional[dict]:
    """One trace → an SFT example ``{"messages": [...]}`` (or None if incomplete)."""
    inp = trace.get("input") or trace.get("prompt") or ""
    out = trace.get("output") or trace.get("response") or ""
    if not inp or not out:
        return None
    msgs = []
    if trace.get("system"):
        msgs.append({"role": "system", "content": trace["system"]})
    msgs.append({"role": "user", "content": inp})
    msgs.append({"role": "assistant", "content": out})
    return {"messages": msgs}


def build_sft_dataset(traces: "list[dict]", min_score: float = 0.0) -> "list[dict]":
    """Filter by score and convert to SFT examples."""
    examples = []
    for t in traces or []:
        if float(t.get("score", 1.0)) < min_score:
            continue
        ex = trace_to_sft(t)
        if ex:
            examples.append(ex)
    return examples


def to_jsonl(examples: "list[dict]") -> str:
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in examples)
