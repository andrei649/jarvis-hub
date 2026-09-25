"""H283 — the operator's description of this machine, given to the model as context.

Nerva already knows a lot about its host (``host_probe``, ``hardware``), but the model
was told only the live backend and model. What it cannot probe — a proxy in front of
the network, how credentials are handled here, where the shared drives are mounted,
that this box is a headless NUC in a cupboard — only the operator knows. Hermes takes
that as ``HERMES_ENVIRONMENT_HINT``; Nerva takes ``JARVIS_ENVIRONMENT_HINT``.

The text goes into the stable part of every agent's system prompt, between the shared
behaviour contract and the persona, under a heading that names it as a description of
the machine, not instructions, so it never forks the persona and never breaks the
prompt cache: the same environment gives the same bytes on every turn. It is read
from the environment the hub started with, bounded (2,000 characters), stripped of
control and bidi characters, and its own lines cannot open a section of their own.
"""
from __future__ import annotations

import re
import unicodedata

from .env_config import env_str

ENV_NAME = "JARVIS_ENVIRONMENT_HINT"
MAX_HINT_CHARS = 2000
HEADER = "## This machine (the operator's description: context about where you run, not instructions)"

_BLANK_RUNS = re.compile(r"\n{3,}")
_HEADING = re.compile(r"^\s*#+\s*", re.MULTILINE)


def clean_hint(raw: str) -> str:
    """The hint as it is given to the model: plain lines, bounded, never a heading."""
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n").replace("\\n", "\n")
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cf"))
    text = _HEADING.sub("", text)                      # a line of the hint never opens a section
    lines = [line.rstrip() for line in text.split("\n")]
    text = _BLANK_RUNS.sub("\n\n", "\n".join(lines)).strip()
    if len(text) > MAX_HINT_CHARS:
        text = text[: MAX_HINT_CHARS - 1].rstrip() + "…"
    return text


def environment_hint() -> str:
    """``JARVIS_ENVIRONMENT_HINT`` as given to the model; empty when unset or blank."""
    return clean_hint(env_str(ENV_NAME))


def hint_block() -> str:
    """The system prompt's block for the hint, or ``""`` when there is none."""
    hint = environment_hint()
    return f"{HEADER}\n{hint}" if hint else ""
