"""
prepare_data.py — H11.3 Build an SFT dataset from collected traces.

Pure-Python (no GPU/deps) — this part runs in-sandbox/CI. Converts trace records
into ShareGPT-style SFT examples, optionally filtered by a quality score, and
serializes them to JSONL for `sft_grpo.py`.

Speaks the H7.11 learning-log format (`memory_logs/learning/*.jsonl`:
``task`` / ``response`` / ``success``) as well as generic ``input`` / ``output`` /
``score`` traces. CLI:

    python training/prepare_data.py memory_logs/learning/*.jsonl --min-score 1.0 -o sft.jsonl
"""

from __future__ import annotations

import json
from typing import Optional


def trace_to_sft(trace: dict) -> Optional[dict]:
    """One trace → an SFT example ``{"messages": [...]}`` (or None if incomplete)."""
    inp = trace.get("input") or trace.get("prompt") or trace.get("task") or ""
    out = trace.get("output") or trace.get("response") or ""
    if not inp or not out:
        return None
    msgs = []
    if trace.get("system"):
        msgs.append({"role": "system", "content": trace["system"]})
    msgs.append({"role": "user", "content": inp})
    msgs.append({"role": "assistant", "content": out})
    return {"messages": msgs}


def trace_score(trace: dict) -> float:
    """Quality signal: explicit score/reward, else success→1.0/0.0, else 1.0."""
    if "score" in trace:
        return float(trace["score"])
    if "reward" in trace:
        return float(trace["reward"])
    if "success" in trace:
        return 1.0 if trace["success"] else 0.0
    return 1.0


def build_sft_dataset(traces: "list[dict]", min_score: float = 0.0) -> "list[dict]":
    """Filter by score and convert to SFT examples."""
    examples = []
    for t in traces or []:
        if trace_score(t) < min_score:
            continue
        ex = trace_to_sft(t)
        if ex:
            examples.append(ex)
    return examples


def to_jsonl(examples: "list[dict]") -> str:
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in examples)


def load_traces(paths: "list[str]") -> "list[dict]":
    """Read one JSON object per line from each file (bad lines skipped)."""
    rows: list[dict] = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def main() -> None:
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="Build an SFT JSONL from learning/trace logs.")
    ap.add_argument("inputs", nargs="+", help="trace JSONL files (e.g. memory_logs/learning/*.jsonl)")
    ap.add_argument("--min-score", type=float, default=1.0,
                    help="keep traces with score >= this (success→1.0; default 1.0 = only successes)")
    ap.add_argument("-o", "--out", default="-", help="output JSONL path ('-' = stdout)")
    args = ap.parse_args()

    examples = build_sft_dataset(load_traces(args.inputs), min_score=args.min_score)
    data = to_jsonl(examples)
    if args.out == "-":
        sys.stdout.write(data + ("\n" if data else ""))
    else:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(data + ("\n" if data else ""))
    sys.stderr.write(f"Wrote {len(examples)} SFT examples to {args.out}\n")


if __name__ == "__main__":
    main()
