"""The audit row of a settings write, one wording for every surface (AUD-8, H257).

The HTTP route (``PUT /api/admin/settings/{category}``) and the offline CLI (``nerva
config set|unset|edit``) both write a settings change straight to the store; before H257
only the route recorded it. Both now build the row here, so a write made on a box with no
running hub is on the same audit log, in the same words, as one made from the HUD.

The row names the changed KEYS, and the new value only for a key whose declared kind is a
choice (a switch, a list pick, a number) — never a secret, never free text (a URL, a note
or a typed model id can carry a credential).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

#: Setting kinds whose value is a choice, never a secret: a switch, a pick from a list,
#: a number. The audit row says what such a key became (H153 review: "when was the
#: webhook receiver off?" had no answer in a row that named only the key). A model id is
#: typed, not picked (``model-select`` takes any string), so it is free text: a pasted
#: key would land in the row.
VALUE_AUDITED_KINDS = frozenset({"toggle", "select", "number", "slider"})

#: The audit action of a settings write (the route's and the CLI's).
ACTION = "settings_update"


def audited_values(category: str, values: Mapping[str, Any]) -> str:
    """``key=value`` for the keys whose declared kind is a choice; never a secret key,
    never free text."""
    from agents.core import settings_db

    kinds = {(row["category"], row["key"]): row.get("kind") for row in settings_db.DEFAULTS}
    parts = []
    for key in sorted(values):
        if (category, key) == ("autonomy", "agent_modes"):
            # H484: a validated map of agent id → mode; the row says what the write made it.
            from agents.core.autonomy.mode import _map_text

            parts.append(f"agent_modes={_map_text(values[key])}")
            continue
        if key in settings_db.SECRET_KEYS or kinds.get((category, key)) not in VALUE_AUDITED_KINDS:
            continue
        try:
            parts.append(f"{key}={json.dumps(values[key], ensure_ascii=False)[:64]}")
        except (TypeError, ValueError):
            continue
    return " ".join(parts)


def change_preview(category: str, keys, values: Mapping[str, Any] | None = None, *, surface: str = "") -> str:
    """The audit preview of a write that changed *keys* of *category* to *values*;
    ``surface`` (``cli``) is named at the end when the write did not come from the hub."""
    values = values or {}
    preview = f"settings.{category} updated: {sorted(keys)}"
    shown = audited_values(category, {key: values.get(key) for key in keys if key in values})
    if shown:
        preview = f"{preview} · {shown}"
    if surface:
        preview = f"{preview} (via {surface})"
    return preview


def record(audit: Any, preview: str, action: str = ACTION) -> bool:
    """Write one settings-change row to *audit* (an ``AuditLogger``); False when there is
    no log or the row could not be written (the write it describes still stands)."""
    if audit is None:
        return False
    try:
        from agents.core.security.types import SecurityEvent, SecurityEventType

        audit.log(SecurityEvent(event_type=SecurityEventType.SETTINGS_CHANGE, timestamp=time.time(),
                                content_preview=preview, action_taken=action))
        return True
    except Exception:  # noqa: BLE001 — reported to the caller
        logger.warning("settings change could not be recorded in the audit log", exc_info=True)
        return False


__all__ = ["ACTION", "VALUE_AUDITED_KINDS", "audited_values", "change_preview", "record"]
