"""Append-only web stream framing through the existing outbound safety gate."""

from .outbound_safety import is_silence, may_become_silence, safe_stream_prefix, sanitize_outbound


def final_text(text: str) -> str:
    return "" if is_silence(text) else str(sanitize_outbound(text))


def safe_notices(notices: list[dict]) -> list[dict]:
    return [{**row, "text": str(sanitize_outbound(row.get("text", "")))} for row in notices]


def safe_prompt(prompt: dict) -> dict:
    """Display labels only: retain IDs, order and server-side choice values."""
    out = dict(prompt)
    if isinstance(out.get("question"), str):
        out["question"] = str(sanitize_outbound(out["question"]))
    if isinstance(out.get("choices"), list):
        out["choices"] = [str(sanitize_outbound(choice)) for choice in out["choices"]]
    return out


class OutboundStream:
    """Hold incomplete words/credentials; final events remain authoritative.

    If whole-text sanitation revises an already-emitted prefix (for example a
    provider error becomes recognizable), stop appending until the final event
    replaces the draft. Never manufacture a delta from a non-matching prefix.
    """

    def __init__(self):
        self._raw = ""
        self._shown = ""

    def _delta(self, clean: str) -> str:
        if not clean.startswith(self._shown):
            return ""
        delta = clean[len(self._shown):]
        self._shown = clean
        return delta

    def push(self, token: str) -> str:
        self._raw += token
        if may_become_silence(self._raw):
            return ""
        try:
            prefix = safe_stream_prefix(self._raw)
        except Exception:
            return ""  # the final whole-response sanitizer still supplies a safe answer
        return self._delta(str(sanitize_outbound(prefix)))

    def finish(self, text: str) -> tuple[str, str]:
        clean = final_text(text)
        return self._delta(clean), clean
