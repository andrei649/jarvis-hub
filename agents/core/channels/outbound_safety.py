"""outbound_safety.py — the last gate before text leaves on a chat transport (H069).

The security guard scans and redacts at the *model's* mouth (``security/guardrails.py``).
Text that never passed the model reaches a channel too: a slash command's reply, a job's
output, a tool result echoed in a notice, an exception string, an approval card built
from an action's arguments. Hermes runs a final sanitizer at the transport boundary for
exactly that reason; this module is Nerva's, and every chat adapter's text goes through
it (``ChannelAdapter.send`` is wrapped for every adapter class, ``render.chunk`` runs it
for every chunked transport, and the Telegram adapter runs it on every Bot API text it
posts, cards and in-place edits included).

What it does, in order, and only this:

* **crash-inducing characters** — NUL and the other C0 controls (tab and newline stay,
  CR becomes a newline), DEL, lone UTF-16 surrogates (they make the JSON body of a Bot
  API call unencodable: the send raises and the reply is lost), the noncharacters
  U+FFFE/U+FFFF and the invisible Unicode TAG plane (it carries ASCII nobody sees);
* **cancellation metadata** — a line that is only the execute-code interruption marker
  (``code_interruptions.MARKER``) is internal bookkeeping for the model, never words for
  the person;
* **secrets** — every value the hub holds as a credential (a credential-named variable
  in the process environment, and whatever the installed known-secret redactor masks —
  the orchestrator installs the secret broker's), then every vendor key format the
  :class:`~agents.core.security.scanner.SecretScanner` knows. The scanner's generic
  high-entropy rule is *not* run here: it matches every UUID, session id and commit hash
  a status reply legitimately shows, and the known-value pass covers the hub's own keys.

* **provider errors** — a reply that is only a backend's failure marker (``[Claude API
  error: Error code: 401 - {... 'request_id': ...}]``) becomes one sentence naming the
  provider and the kind of failure (credentials, rate limit, server, unknown model,
  rejected, unreachable). The provider's body, request id and policy text never leave.

It never raises: a redactor that fails is logged and skipped, and the pattern pass still
runs. Every step is idempotent, so a text that crosses two wrapped seams is unchanged by
the second.

**Silence.** An agent that decides a message needs no answer replies with exactly
:data:`SILENCE_TOKEN` (``[SILENT]``, the token Hermes skills already use). The channel
turn treats that reply as "send nothing" — no message, no notices under it, and a reply
written in place does not start while the text could still become the token.

**A turn is never invisible.** A channel turn whose model produced no text is answered
with :data:`EMPTY_TURN_REPLY`, and one that failed with an exception with
:data:`FAILED_TURN_REPLY`, instead of leaving the person looking at nothing.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("jarvis.channels.outbound_safety")

#: The reply an agent gives when it chooses to send nothing.
SILENCE_TOKEN = "[SILENT]"

EMPTY_TURN_REPLY = ("I finished that turn without an answer to send. Send the message again, "
                    "or check /status if this keeps happening.")
FAILED_TURN_REPLY = ("Something went wrong on my side while answering that message, so there is "
                     "no reply. Send it again; if it keeps failing, check /status or the hub log.")

# C0 controls except TAB (\x09) and LF (\x0a); CR is handled first. DEL. Lone surrogates.
# The noncharacters U+FFFE/U+FFFF. The TAG plane (U+E0000–U+E007F).
_CRASH_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff￾￿\U000e0000-\U000e007f]")

#: Patterns run on top of the scanner's: formats the scanner does not know.
_EXTRA_PATTERNS: dict[str, str] = {
    # A Discord bot token: base64 user id, a timestamp part, an HMAC part.
    "discord_bot_token": r"\b[MNO][A-Za-z\d_-]{23,27}\.[A-Za-z\d_-]{6}\.[A-Za-z\d_-]{27,40}\b",
}
#: Scanner rules not run at the transport (see the module docstring).
_SKIPPED_SCANNER_RULES = frozenset({"high_entropy_secret"})

_known_redactor: Callable[[str], str] | None = None
_patterns: list[tuple[str, re.Pattern]] | None = None


def install_known_secret_redactor(redactor: Callable[[str], str] | None) -> None:
    """Install the callable that masks every secret value the hub stores (the secret
    broker's ``redact``). ``None`` uninstalls it. Process-wide: one hub, one store."""
    global _known_redactor
    _known_redactor = redactor if callable(redactor) else None


def _compiled() -> list[tuple[str, re.Pattern]]:
    global _patterns
    if _patterns is None:
        from ..security.scanner import SecretScanner

        compiled = [(name, pattern) for name, pattern, _threat, _desc in SecretScanner()._compiled
                    if name not in _SKIPPED_SCANNER_RULES]
        compiled += [(name, re.compile(pattern)) for name, pattern in _EXTRA_PATTERNS.items()]
        _patterns = compiled
    return _patterns


def _env_credentials() -> list[tuple[str, str]]:
    from .. import env_alias
    from ..env_config import credential_values
    from ..env_provenance import masked

    def credential(name: str) -> bool:
        bare = name
        for prefix in ("JARVIS_", "NERVA_"):
            if name.startswith(prefix):
                bare = name[len(prefix):]
        return masked(name) and bare not in env_alias.NOT_CREDENTIALS

    return credential_values(credential)


def redact_secrets(text: str) -> str:
    """*text* with every credential value and every known key format masked."""
    out = text
    try:
        # Longest first, so a value that contains another is masked whole.
        for name, value in sorted(_env_credentials(), key=lambda item: -len(item[1])):
            if value in out:
                out = out.replace(value, f"[REDACTED:{name}]")
    except Exception:
        logger.warning("outbound credential masking unavailable; key formats are still masked",
                       exc_info=True)
    redactor = _known_redactor
    if redactor is not None:
        try:
            masked_text = redactor(out)
            if isinstance(masked_text, str):
                out = masked_text
        except Exception:
            logger.warning("outbound known-secret redactor failed; key formats are still masked",
                           exc_info=True)
    for name, pattern in _compiled():
        out = pattern.sub(f"[REDACTED:{name}]", out)
    return out


# A whole reply that is a backend failure marker: "[<Provider> [API] [stream] error[: detail]]".
_PROVIDER_ERROR = re.compile(
    r"\A\s*\[(?P<who>[A-Za-z][\w .()/-]{0,40}?)(?: API)?(?: stream)? error\b(?P<detail>[^\n]{0,4000}?)\]\s*\Z")
_STATUS = re.compile(r"(?:Error code|status(?:_code)?|HTTP)\D{0,3}(?P<code>[1-5]\d\d)\b", re.IGNORECASE)
_PROVIDER_KINDS = (
    ((401, 403), "refused the hub's credentials"),
    ((404,), "does not know the requested model"),
    ((429,), "is rate limiting requests"),
)


def map_provider_error(text: str) -> str | None:
    """One user-safe sentence for a reply that is only a provider failure marker, or
    None when *text* is not one. Only the provider's name and the status code are read."""
    match = _PROVIDER_ERROR.match(text or "")
    if match is None:
        return None
    who = match.group("who").strip()
    status_match = _STATUS.search(match.group("detail"))
    status = int(status_match.group("code")) if status_match else None
    what = "could not answer (the request failed or the provider was unreachable)"
    if status is not None:
        what = next((label for codes, label in _PROVIDER_KINDS if status in codes),
                    "had a server error" if status >= 500 else "rejected the request")
        what = f"{what} (HTTP {status})"
    return f"The model provider {who} {what}, so there is no answer. Try again shortly, or check /status."


def _strip_cancellation(text: str) -> str:
    from ..code_interruptions import MARKER

    if MARKER not in text:
        return text
    return "\n".join(line for line in text.split("\n") if line.strip() != MARKER)


def sanitize_text(text: str) -> str:
    """The plain-string sanitizer: crash characters, cancellation lines, secrets."""
    if not text:
        return text
    mapped = map_provider_error(text)
    if mapped is not None:
        return mapped
    out = text.replace("\r\n", "\n").replace("\r", "\n")
    out = _CRASH_CHARS.sub("", out)
    out = _strip_cancellation(out)
    return redact_secrets(out)


def sanitize_outbound(message: Any) -> Any:
    """*message* made safe to send, of the same type.

    A ``str`` subclass (an ``EphemeralReply`` with its TTL, a ``FootedReply`` with its
    spoken part) comes back as the same class with every string attribute sanitized too;
    an unchanged message comes back as the very same object. Anything that is not text is
    returned as it is (adapters only ever send text)."""
    if not isinstance(message, str) or not message:
        return message
    try:
        clean = sanitize_text(str.__str__(message))
    except Exception:
        # The gate must not lose the message, and must not send it raw either.
        logger.warning("outbound sanitizer failed; sending a notice instead", exc_info=True)
        return "A reply could not be checked before sending, so it was withheld."
    attrs = getattr(message, "__dict__", None) or {}
    changed_attrs = {key: sanitize_text(value) if isinstance(value, str) else value
                     for key, value in attrs.items()}
    if clean == message and changed_attrs == attrs:
        return message
    if type(message) is str:
        return clean
    rebuilt = str.__new__(type(message), clean)
    rebuilt.__dict__.update(changed_attrs)
    return rebuilt


def is_silence(message: Any) -> bool:
    """Whether *message* is the agent's choice to send nothing: exactly the token."""
    return isinstance(message, str) and message.strip().upper() == SILENCE_TOKEN


def may_become_silence(partial: Any) -> bool:
    """Whether streamed text so far could still turn out to be the silence token (a reply
    written in place must not start until it cannot)."""
    if not isinstance(partial, str):
        return False
    head = partial.lstrip().upper()
    return bool(head) and len(head) <= len(SILENCE_TOKEN) + 8 and SILENCE_TOKEN.startswith(head.rstrip())


__all__ = [
    "EMPTY_TURN_REPLY", "FAILED_TURN_REPLY", "SILENCE_TOKEN", "install_known_secret_redactor",
    "is_silence", "map_provider_error", "may_become_silence", "redact_secrets", "sanitize_outbound", "sanitize_text",
]
