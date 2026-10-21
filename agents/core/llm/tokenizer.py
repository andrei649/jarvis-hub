"""
tokenizer.py — Token estimator for hybrid routing decisions.
Uses tiktoken cl100k_base when available, character-based fallback otherwise.
"""


try:
    import tiktoken
    _ENCODING = tiktoken.get_encoding("cl100k_base")
except Exception:
    _ENCODING = None


#: H297 — what one attached image costs the context window: about what a provider
#: charges for a 1,000 x 1,000-pixel image ((w*h)/750 tokens, rounded up). An image's
#: base64 bytes are not text the model reads, so no estimate counts them as tokens;
#: every accounting (the tool loop's compaction budget, a pinned job's window check)
#: charges this flat cost per image instead.
IMAGE_TOKEN_COST = 1_600


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
