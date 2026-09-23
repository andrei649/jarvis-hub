"""host_protocol.py — H368: the host decides the wire protocol, never the config.

Some hosts accept exactly one protocol. ``api.anthropic.com`` speaks Anthropic
Messages; the official OpenAI host family (``api.openai.com`` and its regional
``<region>.api.openai.com`` data-residency hosts) speaks OpenAI's own wire; a
``bedrock-runtime.<region>.amazonaws.com`` host speaks Bedrock Converse. A backend
aimed at one of those hosts while speaking something else is not a harmless
misconfiguration: its request carries *its* credential in *its* auth header, so an
``OPENAI_API_KEY`` bearer would be handed to Anthropic, or a local server's
OpenAI-shaped request to Bedrock. The table below pins the protocol by host, and
``egress.llm_async_client`` refuses the mismatch before the request leaves.

Matching is on the **parsed hostname** — lower-cased, one trailing dot dropped,
compared exactly or as a whole leading label — never a substring. Hermes had to fix
exactly that (its #32243): ``api.openai.com.attacker.test`` is not OpenAI,
``proxy.test/api.openai.com/v1`` names OpenAI only in its path, and
``api.openai.com@attacker.test`` only in its userinfo; none of them mandates
anything, so none of them is ever treated as the vendor.

Adaptation from Hermes: Hermes carries an ``api_mode`` per session and the host
mandate *overrides* a stale one. Nerva has no per-session mode to go stale — each
backend class *is* its protocol (``BACKEND_PROTOCOLS``) — so the mandate cannot
re-pick a protocol; it refuses the backend whose protocol differs, at the wire
(:func:`agents.core.llm.egress.llm_async_client`, every backend, every hop of a
redirect) and at ``HybridRouter.detect()`` for the configurable compatible
endpoint, so the refusal is visible when the route is built. Nerva's OpenAI family
admits both OpenAI dialects (chat completions and Responses): the
``openai-compatible`` profile has always defaulted to ``api.openai.com`` with chat
completions, and both dialects carry the same OpenAI credential to the same vendor.

Pure module: no I/O, no settings.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import httpx

ANTHROPIC_MESSAGES = "anthropic_messages"
OPENAI = "openai"  # OpenAI's own wire: chat completions and Responses
BEDROCK_CONVERSE = "bedrock_converse"
GEMINI = "gemini_generate_content"
OLLAMA = "ollama"

# What each backend speaks, keyed by the name it passes to ``llm_async_client``
# (which is also its ``llm:<name>`` egress-ledger row).
BACKEND_PROTOCOLS: dict[str, str] = {
    "anthropic": ANTHROPIC_MESSAGES,
    "openrouter": OPENAI,
    "openai-compatible": OPENAI,
    "openai-responses": OPENAI,
    "xai": OPENAI,
    "lm-studio": OPENAI,
    "vlm": OPENAI,
    "gemini": GEMINI,
    "ollama": OLLAMA,
}

# Host → the one protocol it accepts. Exact hosts first, then whole-label patterns.
_EXACT_HOSTS: dict[str, str] = {
    "api.anthropic.com": ANTHROPIC_MESSAGES,
    "api.openai.com": OPENAI,
}
_PATTERN_HOSTS: tuple[tuple[re.Pattern[str], str], ...] = (
    # One regional label in front of api.openai.com (us., eu., …), nothing deeper.
    (re.compile(r"^[a-z0-9-]+\.api\.openai\.com$"), OPENAI),
    (re.compile(r"^bedrock-runtime(?:-fips)?\.[a-z0-9-]+\.amazonaws\.com(?:\.cn)?$"), BEDROCK_CONVERSE),
)


class HostProtocolRefused(Exception):
    """A backend tried to speak a protocol its target host does not accept.

    Raised from the egress request hook before the transport is touched, so neither
    the body nor the credential in the auth header left the machine. Deliberately
    neither an ``OSError`` nor an ``httpx.HTTPError``: a connection-failure handler
    (``except OSError`` / ``except httpx.HTTPError``) must not read a refusal as
    "backend down, try elsewhere". Backends that catch ``Exception`` degrade to their
    usual error reply.
    """


def hostname_of(url: object) -> str:
    """The parsed, lower-cased hostname of *url* without a trailing dot; ``""`` if none.

    Accepts an ``httpx.URL``, a URL string, or a bare ``host[/path]`` (read as a
    network location, so ``proxy.test/api.openai.com/v1`` is ``proxy.test``).
    Strings are parsed by ``httpx.URL`` — the parser the wire dials with — so an
    IDNA dot equivalent (``api．anthropic．com``) folds to the host httpx would
    actually connect to; ``urlsplit`` is only the fallback for text httpx rejects.
    """
    if isinstance(url, httpx.URL):
        host = url.host or ""
    else:
        text = str(url or "").strip()
        if not text:
            return ""
        if "://" not in text:
            text = "//" + text
        try:
            host = httpx.URL(text).host or ""
        except (httpx.InvalidURL, ValueError, TypeError):
            try:
                host = urlsplit(text).hostname or ""
            except ValueError:
                return ""
    return host.lower().rstrip(".")


def host_mandated_protocol(url: object) -> str | None:
    """The one protocol *url*'s host accepts, or ``None`` when the host mandates none."""
    host = hostname_of(url)
    if not host:
        return None
    mandated = _EXACT_HOSTS.get(host)
    if mandated:
        return mandated
    for pattern, protocol in _PATTERN_HOSTS:
        if pattern.match(host):
            return protocol
    return None


def backend_protocol(backend: str) -> str | None:
    """The protocol a backend speaks; ``None`` for a name this table does not know."""
    return BACKEND_PROTOCOLS.get(str(backend or "").strip().lower())


def protocol_refusal(backend: str, url: object) -> str:
    """``""`` when *backend* may speak to *url*'s host; otherwise why it may not.

    A host without a mandate constrains nobody. A host with one admits only the
    backends declared to speak it — an undeclared backend cannot prove it does, so
    it is refused too.
    """
    mandated = host_mandated_protocol(url)
    if mandated is None:
        return ""
    spoken = backend_protocol(backend)
    if spoken == mandated:
        return ""
    return (
        f"{hostname_of(url)} accepts only {mandated}; llm:{backend} speaks "
        f"{spoken or 'an undeclared protocol'} — refused before the request or its credential left"
    )
