"""H275 — safe mode: boot the hub with every owner customization left out.

A persona overlay that breaks the model, a skill that crashes discovery, a scheduled
job that runs away, an MCP server that hangs the lifespan: when an install is broken
by something the owner added, the owner needs to start the hub without it, fix it and
start again. Hermes has ``--safe-mode``; Nerva has ``JARVIS_SAFE_MODE=1``, which
``python serve.py --safe-mode`` sets before anything loads.

Safe mode only takes things away. It leaves out, at boot and at every later reload:

- skills that did not ship (the data home's skills and any generated, imported or
  pending-review skill in the bundled tree): only the shipped skills are discovered;
- the persisted MCP servers: none is registered, and their saved configuration is not
  touched (the routes that would rewrite it refuse, since the manager holds none);
- acquired packages and extensions: the acquisition runtime reports itself disabled,
  so nothing promoted is re-registered and no extension can be activated;
- the owner's plugin grants (``JARVIS_PLUGIN_GRANTS``), which only ever widen access;
- the persona, behaviour-contract and heartbeat overlays (``*.local.md`` in the data
  home or the repository): the shipped templates are read, at construction and at the
  compaction boundary (H672), so a session cannot pick an overlay back up;
- the owner's scheduled jobs: none is put on the scheduler.

Nothing is relaxed: the kernel, the approval floor, the plugin gate and the egress
policy do not read this flag. It is said on ``/healthz``, ``/readyz``, ``/status`` and
``/api/status``, in the HUD as a banner, and in the boot log.
"""
from __future__ import annotations

import logging
import threading

from .env_config import env_flag

logger = logging.getLogger("jarvis.safe_mode")

ENV_NAME = "JARVIS_SAFE_MODE"
#: What safe mode leaves out, in the order the boot meets them.
LAYERS = (
    "owner_skills",
    "mcp_servers",
    "acquired_packages",
    "plugin_grants",
    "persona_overlays",
    "heartbeat_overlays",
    "owner_jobs",
)
#: The refusal a write that would need a skipped layer answers with.
REASON = "safe_mode"

_lock = threading.Lock()
_skipped: set[str] = set()


def enabled() -> bool:
    """Whether the hub runs in safe mode (``JARVIS_SAFE_MODE``), read at call time."""
    return env_flag(ENV_NAME)


def note(layer: str) -> None:
    """Record that something of *layer* was left out (the status rows name it); the
    first time, say so in the log."""
    if layer not in LAYERS:
        raise ValueError(f"unknown safe-mode layer: {layer!r}")
    with _lock:
        first = layer not in _skipped
        _skipped.add(layer)
    if first:
        logger.warning("Safe mode: %s left out", layer.replace("_", " "))


def reset() -> None:
    """Forget what was recorded (tests; a hub that reloads its layers)."""
    with _lock:
        _skipped.clear()


def status() -> dict:
    """``{"enabled", "skipped"}``: the flag, and the layers something was left out of."""
    if not enabled():
        return {"enabled": False, "skipped": []}
    with _lock:
        skipped = [layer for layer in LAYERS if layer in _skipped]
    return {"enabled": True, "skipped": skipped}
