"""Outbound safety before native menu normalization and provider length limits."""

from .outbound_safety import sanitize_text

MAX_NAME_INPUT = 512
MAX_DESCRIPTION_INPUT = 16_384


def name_allowed(raw: str, wire: str) -> bool:
    """Hide unsafe identifiers: rewriting one would change command dispatch."""
    if not raw or len(raw) > MAX_NAME_INPUT or not wire or len(wire) > MAX_NAME_INPUT:
        return False
    try:
        return sanitize_text(raw) == raw and sanitize_text(wire) == wire
    except Exception:
        return False


def safe_description(raw: str, limit: int) -> str:
    """Never expose a secret prefix by cutting raw metadata before redaction."""
    if len(raw) > MAX_DESCRIPTION_INPUT:
        return "Description omitted"[:limit]
    try:
        clean = sanitize_text(raw)
    except Exception:
        return "Description unavailable"[:limit]
    return " ".join(clean.split())[:limit] or "Run command"[:limit]
