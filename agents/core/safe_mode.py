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
- the owner's scheduled jobs: none is put on the scheduler;
- (H490) the plugins: none is built, so no integration is reached and no plugin data
  (WorldView, the Signal Layer) enters a prompt, and the plugin toggle refuses;
- (H490) the outbound webhooks: the owner-configured webhook channels and ntfy are not
  started, the proactive sends to the owner's channels refuse, and the inbound webhook
  receiver answers 503;
- (H490) the memory a turn is given: the pre-turn recall, the core block and the
  ``memory`` tool, which reads as memory switched off (the conversation's own history
  stays);
- (H490) the settings that loosen an approval or widen a budget
  (:data:`FORCED_SETTINGS`): each reads the stricter of the owner's value and its
  shipped default, so an owner who tightened one keeps it. A setting whose default is
  already the loosest value keeps the owner's choice;
- (H594) the project's convention files (``AGENTS.md``, ``CLAUDE.md``, ``.cursorrules``,
  ``.cursor/rules``): none is read into a turn or a tool result.

There are no shell hooks to leave out: Nerva runs no owner-configured hook commands.

Nothing is relaxed: the kernel, the approval floor, the plugin gate and the egress
policy do not read this flag. It is said on ``/healthz``, ``/readyz``, ``/status``,
``/api/status`` and ``/api/security/posture``, in the HUD as a banner, and in the boot log.
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
    # H490 — the rest of Hermes' reduced posture.
    "plugins",
    "outbound_webhooks",
    "memory_injection",
    "settings_overrides",
    # H594 — a project's convention files (AGENTS.md, CLAUDE.md, .cursorrules).
    "project_context",
)
#: H490 — settings an owner can set looser than the shipped default (an approval that
#: stops being asked, a wider tool offer, a bigger budget), each with how to take the
#: stricter of the owner's value and the shipped default. In safe mode a setting reads
#: that stricter value, never a looser one: an owner who tightened a setting keeps it.
#: Settings whose default is already the loosest value (autonomy.mode,
#: security.guardrails_mode, autonomy.night_shift, the control switches) are not here.
_ON_LOOSENS, _OFF_LOOSENS, _MORE_LOOSENS = "on-loosens", "off-loosens", "more-loosens"
FORCED_SETTINGS: dict[str, object] = {
    "llm.inbound_actuation": _ON_LOOSENS,
    "llm.internal_actuation": _ON_LOOSENS,
    "llm.tool_loop_enabled": _ON_LOOSENS,
    "autonomy.earned_autonomy_enabled": _ON_LOOSENS,
    "ambient.enabled": _ON_LOOSENS,
    "acquisition.enabled": _ON_LOOSENS,
    "security.scan_input": _OFF_LOOSENS,
    "security.scan_output": _OFF_LOOSENS,
    "llm.model_pull_max_gb": _MORE_LOOSENS,
    "autonomy.cap_per_action": _MORE_LOOSENS,
    "autonomy.daily_ceiling": _MORE_LOOSENS,
    "autonomy.interrupt_budget": _MORE_LOOSENS,
    "security.sandbox_timeout": _MORE_LOOSENS,
    "security.sandbox_memory": _MORE_LOOSENS,
    # A list: only the shipped names the owner also kept.
    "llm.guest_tools": "subset",
    # An order, strictest first.
    "llm.cloud_fallback": ("never", "on-demand", "always"),
    "product.posture": ("off", "companion_wave1", "design_partner"),
}
#: Loosening settings with no shipped row: in safe mode they are absent, so the code's
#: own default applies.
UNSEEDED_SETTINGS: tuple[str, ...] = (
    "autonomy.agent_modes", "learning.auto_promote", "security.sandbox_max_tool_calls",
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


def shipped_default(key: str):
    """The shipped default of a settings key (``category.key``), or KeyError."""
    from .settings_db import DEFAULTS

    category, _, name = key.partition(".")
    for row in DEFAULTS:
        if row["category"] == category and row["key"] == name:
            return row["value"]
    raise KeyError(key)


def stricter(key: str, owner, shipped):
    """The stricter of the owner's value and the shipped default for a forced key. A
    switch is read by truthiness, as the runtime reads it; a number, list or choice that
    is not of the setting's kind counts as the shipped default."""
    rule = FORCED_SETTINGS[key]
    if rule == _ON_LOOSENS:
        return bool(shipped) and bool(owner)
    if rule == _OFF_LOOSENS:
        return bool(shipped) or bool(owner)
    if rule == _MORE_LOOSENS:
        if isinstance(owner, bool) or not isinstance(owner, (int, float)):
            return shipped
        return min(owner, shipped)
    if rule == "subset":
        kept = owner if isinstance(owner, list) else shipped
        return [name for name in shipped if name in kept]
    order = list(rule)
    owner_rank = order.index(owner) if owner in order else len(order)
    return order[min(owner_rank, order.index(shipped))]


def override_settings(flat: dict) -> dict:
    """H490 — the runtime settings as safe mode serves them: every loosening key at the
    stricter of its value and its shipped default, every unseeded one absent. A copy;
    ``flat`` is not changed."""
    if not enabled():
        return flat
    out = dict(flat)
    moved = False
    for key in FORCED_SETTINGS:
        shipped = shipped_default(key)
        value = stricter(key, out.get(key, shipped), shipped)
        if key in out and out[key] != value:
            moved = True
        out[key] = value
    for key in UNSEEDED_SETTINGS:
        moved = out.pop(key, None) is not None or moved
    if moved:
        note("settings_overrides")
    return out


def get_value(category: str, key: str, default=None):
    """``settings_db.get_value`` for a boot read, with safe mode's shipped default for a
    forced key the stricter of the stored value and the shipped default (the
    orchestrator's sandbox and autonomy caps are read this way)."""
    from .settings_db import get_value as stored

    value = stored(category, key, default)
    full = f"{category}.{key}"
    if enabled() and full in FORCED_SETTINGS:
        safe = stricter(full, value, shipped_default(full))
        if safe != value:
            note("settings_overrides")
        return safe
    return value


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
