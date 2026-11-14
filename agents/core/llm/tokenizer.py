"""
tokenizer.py — Token estimator for hybrid routing decisions.
Uses tiktoken cl100k_base when available, conservative Unicode fallback otherwise.
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
    # Retain the ASCII estimate; rare Unicode may require several tokens per
    # character. Without an encoding, charge its UTF-8 bytes conservatively so
    # an unavailable optional tokenizer cannot bypass a known context limit.
    ascii_chars = sum(char.isascii() for char in text)
    non_ascii_bytes = len(text.encode("utf-8", errors="replace")) - ascii_chars
    return ascii_chars // 4 + non_ascii_bytes + 1


def estimate_messages(messages: list[dict]) -> int:
    total = 0
    for msg in messages:
        total += estimate_tokens(msg.get("content", ""))
        total += estimate_tokens(msg.get("role", ""))
    return total
