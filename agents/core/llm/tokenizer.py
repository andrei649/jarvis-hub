"""
tokenizer.py — Token estimator for hybrid routing decisions.
Uses tiktoken cl100k_base when available, character-based fallback otherwise.
"""

from typing import Optional

try:
    import tiktoken
    _ENCODING = tiktoken.get_encoding("cl100k_base")
except Exception:
    _ENCODING = None


def estimate_tokens(text: str) -> int:
    if _ENCODING:
        return len(_ENCODING.encode(text))
    return len(text) // 4 + 1


def estimate_messages(messages: list[dict]) -> int:
    total = 0
    for msg in messages:
        total += estimate_tokens(msg.get("content", ""))
        total += estimate_tokens(msg.get("role", ""))
    return total
