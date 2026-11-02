"""H202 — the owner's roster: create an agent, rename one, retire it and bring it back.

Hermes keeps profiles the owner can create, rename and delete beside its SOUL.md editor.
Nerva's agents were the shipped registry (``agents/_system/agents.yaml``) and nothing
else: a template could be previewed (``POST /api/agent-templates/instantiate``) but never
saved, the one rename was a display override held in memory and lost at the next restart
(``PUT /api/admin/agents/{id}``), and nothing took an agent away. This module is the
owner's side of the registry.

- **One overlay beside the shipped registry.** ``agent_roster.json`` in the data root
  holds the agents the owner created, the names they gave shipped ones and the agents they
  retired. ``JarvisConfig`` lays it over ``agents.yaml`` when it loads
  (:func:`merge_rows`), so a created agent loads at boot, a rename survives a restart and
  a retired agent stays out. The shipped file is never written.
- **Create** renders the persona from a template (``agent_templates``) or from nothing,
  refuses an id the hub already uses, reserves or has a folder for, and makes the persona
  live through the SOUL editor's own path (``soul_edit.apply_soul``: guard-scanned,
  written to the owner's overlay, version 1, audited). A created agent gets no plugins,
  no heartbeat and no model pin — the roster cannot grant anything, whatever its file
  says: what an agent may touch is granted the way it is for every agent.
- **Rename** changes the name the owner sees and the prompt uses (``Respond as …``); the
  id — the key of its persona, versions, run history and memory — stays.
- **Retire** takes the agent out of the running hub and out of every later boot, and
  deletes nothing: its persona file, persona versions, run history and memory stay where
  they are, and **restore** brings it back as it was. Jarvis, the agent every unmatched
  turn goes to, cannot be retired. A retire names the agent's id as its confirmation.
- **Versioned and audited like the SOUL save.** Every change is a numbered revision of the
  agent's roster entry (the newest :data:`MAX_REVISIONS` are kept) and a SETTINGS_CHANGE
  row in the security audit naming the agent, the change and the revision.

Safe mode reads no owner overlay, so the roster is not applied there and every change is
refused (409), as a persona edit is. An unreadable roster is reported and left out at
boot, and every change is refused (503) rather than written over it.
"""
from __future__ import annotations

import contextlib
import copy
import json
import logging
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

from .soul_edit import AGENT_ID_RE, MAX_SOUL_BYTES, SoulEditError

logger = logging.getLogger("jarvis.agent_roster")

FILENAME = "agent_roster.json"
SCHEMA = 1
NAME_CHARS = 64
REASON_CHARS = 200
#: The newest revisions an entry keeps (its revision numbers keep counting).
MAX_REVISIONS = 50
#: The most owner-created agents live at once.
MAX_CREATED = 32
#: The agent every unmatched turn goes to (``IntentRouter._general``).
PROTECTED = frozenset({"jarvis"})
#: Names that are not free (NERVA_VISION.md §2 sub-brands, the upstream project), and
#: words that would read as something other than an agent.
RESERVED = frozenset({"cortex", "atlas", "synapse", "nerva", "digitaholic", "hermes",
                      "agent", "agents", "admin", "system", "roster"})
#: The roster tiers (agents.yaml's), which the HUD maps to its tier codes.
TIERS = ("command", "business", "tech", "foundation")
STATUSES = ("active", "retired")
#: What a created agent's row is: the roster never grants plugins, a heartbeat or a model.
_CREATED_ROW = {"channel": "web-dashboard", "heartbeat": "no", "plugins": []}

_LOCK = threading.Lock()


def roster_path() -> Path:
    from .paths import data_path

    return data_path(FILENAME)


def _load(path: Path) -> dict:
    """The roster on disk (an absent file is an empty roster); raises for one that cannot
    be read."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"schema": SCHEMA, "agents": {}}
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("agents", {}), dict):
        raise ValueError("the agent roster must be a mapping with an 'agents' mapping")
    data.setdefault("agents", {})
    return data


def read() -> dict:
    """The roster for a change; an unreadable one is refused, never written over."""
    path = roster_path()
    try:
        return _load(path)
    except (OSError, UnicodeError, ValueError) as exc:
        logger.warning("the agent roster %s could not be read: %s", path, type(exc).__name__)
        raise SoulEditError("roster_unreadable", 503,
                            detail=f"{FILENAME} in the data root could not be read; nothing was changed") from exc


def _write(data: dict) -> None:
    from .persistence.json_store import atomic_write_json

    try:
        atomic_write_json(roster_path(), data)
    except OSError as exc:
        logger.warning("the agent roster could not be written: %s", exc)
        raise SoulEditError("write_failed", 500) from exc


def _created_row(entry: dict) -> dict:
    tier = entry.get("tier") if entry.get("tier") in TIERS else "foundation"
    archetype = entry.get("archetype") if isinstance(entry.get("archetype"), str) else ""
    return {**_CREATED_ROW, "plugins": [], "tier": tier, "archetype": archetype[:NAME_CHARS * 2]}


def _overlay_row(agent_id: str, entry: Any, shipped: dict | None) -> dict | None:
    """The registry row *entry* makes of *agent_id* (over its shipped row, if any)."""
    if not isinstance(entry, dict) or not AGENT_ID_RE.match(str(agent_id)):
        return None
    if shipped is not None:
        row = dict(shipped)
    elif entry.get("created") is True:
        row = _created_row(entry)
        row["status"] = "active"
    else:
        return None
    name = entry.get("name")
    if isinstance(name, str) and name.strip():
        row["name"] = " ".join(name.split())[:NAME_CHARS]
    if entry.get("status") == "retired":
        row["status"] = "retired"
    return row


def merge_rows(shipped: dict) -> dict:
    """*shipped* (agents.yaml's ``agents:`` rows) with the owner's roster laid over it.

    Never raises: in safe mode, or when the roster cannot be read (it is reported, its
    bytes kept by ``report_unreadable``), the shipped rows come back unchanged."""
    rows = {agent_id: dict(row) for agent_id, row in shipped.items()}
    try:
        from . import safe_mode

        path = roster_path()
        if safe_mode.enabled():
            if path.exists():
                safe_mode.note("persona_overlays")
            return rows
        data = _load(path)
    except Exception as exc:
        try:
            from .config_read_errors import report_unreadable

            report_unreadable(roster_path(), exc)
        except Exception:
            logger.warning("the agent roster could not be read and was left out", exc_info=True)
        return rows
    for agent_id, entry in data["agents"].items():
        row = _overlay_row(str(agent_id), entry, rows.get(agent_id))
        if row is not None:
            rows[str(agent_id)] = row
    return rows


# ── shared checks ────────────────────────────────────────────────────────────


def _refuse_in_safe_mode() -> None:
    from . import safe_mode

    if safe_mode.enabled():
        raise SoulEditError("safe_mode", 409, detail="the owner's roster is not read in safe mode")


def clean_name(raw: Any) -> str:
    """*raw* as a display name: whitespace collapsed, 1-NAME_CHARS printable characters."""
    name = " ".join(raw.split()) if isinstance(raw, str) else ""
    if not name or len(name) > NAME_CHARS or any(unicodedata.category(ch).startswith("C") for ch in name):
        raise SoulEditError("bad_name", 422, detail=f"a name is 1-{NAME_CHARS} printable characters")
    return name


def _registry(orch: Any) -> dict:
    agents = getattr(getattr(orch, "config", None), "agents", None)
    if not isinstance(agents, dict):
        raise SoulEditError("hub_not_ready", 503, detail="the hub has no agent registry loaded")
    return agents


def _known(orch: Any, agent_id: Any) -> str:
    """*agent_id* as the registry knows it (active or retired), else a 404."""
    ident = str(agent_id or "").strip().lower()
    cfg = _registry(orch).get(ident) if AGENT_ID_RE.match(ident) else None
    if cfg is None or getattr(cfg, "status", "") not in STATUSES:
        raise SoulEditError("unknown_agent", 404, agent=str(agent_id)[:64])
    return ident


def _check_new_id(orch: Any, ident: str) -> None:
    from . import soul_edit

    if not AGENT_ID_RE.match(ident) or ident[0] in "_-":
        raise SoulEditError("bad_id", 422, detail="an id is 1-64 lowercase letters, digits, '_' or '-', "
                                                  "starting with a letter or digit")
    if ident in RESERVED:
        raise SoulEditError("reserved_id", 409, agent=ident)
    config = getattr(orch, "config", None)
    taken = set(getattr(orch, "agents", None) or {}) | set(_registry(orch)) | set(getattr(config, "bench", None) or {})
    if ident in taken:
        raise SoulEditError("agent_exists", 409, agent=ident)
    if soul_edit.agent_folder(ident) is not None:
        # A shipped folder (agents/<id>, which also holds the hub's own packages) or a
        # persona folder left behind: never adopted as a new agent's.
        raise SoulEditError("agent_exists", 409, agent=ident, detail="a folder by that name already exists")


def _refuse_taken_name(registry: dict, display: str, ident: str) -> None:
    """409 when another agent (active or retired) is called *display*, or has it as its id:
    two agents one name apart is the confusion a roster exists to avoid."""
    folded = display.casefold()
    clash = next((other for other, row in registry.items()
                  if other != ident and getattr(row, "status", "") in STATUSES
                  and (str(getattr(row, "name", "")).casefold() == folded or other == folded)), None)
    if clash is not None:
        raise SoulEditError("name_taken", 409, agent=clash)


def new_agent_id(name: Any, agent_id: Any = "") -> str:
    """The id :func:`create` gives a new agent: *agent_id* when one is named, else the
    template builders' slug of the cleaned *name*. The kernel names it as the target."""
    from .agent_templates import _slugify

    wanted = str(agent_id or "").strip().lower()
    return wanted or _slugify(" ".join(name.split()) if isinstance(name, str) else "")


def _revise(entry: dict, action: str, *, name: str, now: float, **extra: Any) -> int:
    revisions = entry.setdefault("revisions", [])
    number = int(revisions[-1].get("rev", 0)) + 1 if revisions else 1
    revisions.append({"rev": number, "at": now, "action": action, "name": name,
                      "status": entry.get("status", "active"), **extra})
    del revisions[:-MAX_REVISIONS]
    return number


def _audit(orch: Any, ident: str, action: str, revision: int, detail: str = "") -> bool:
    from .soul_edit import audit_change

    return audit_change(orch, f"agent {ident} {action}: roster rev {revision}" + (f" ({detail})" if detail else ""),
                        f"agent_{action}")


def _persona(ident: str, name: str, archetype: str, tier: str, description: str, body: str) -> str:
    import yaml

    meta = {"id": ident, "name": name, "archetype": archetype, "tier": tier}
    if description:
        meta["description"] = description
    head = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=1000)
    return f"---\n{head}---\n{body}"


def describe(orch: Any, ident: str, entry: dict | None = None) -> dict:
    """One roster row: who the agent is, whether it is live, and what changed it."""
    cfg = _registry(orch).get(ident)
    entry = entry if isinstance(entry, dict) else {}
    revisions = entry.get("revisions") if isinstance(entry.get("revisions"), list) else []
    return {
        "id": ident,
        "name": getattr(cfg, "name", ident),
        "status": getattr(cfg, "status", entry.get("status", "active")),
        "live": ident in (getattr(orch, "agents", None) or {}),
        "created": entry.get("created") is True,
        "template": entry.get("template"),
        "protected": ident in PROTECTED,
        "retired_at": entry.get("retired_at"),
        "reason": entry.get("reason") or "",
        "revision": revisions[-1].get("rev") if revisions else 0,
        "revisions": list(reversed(revisions[-10:])),
    }


def roster(orch: Any) -> dict:
    """Every agent the registry knows, active and retired, with the roster's revisions."""
    from . import safe_mode
    from .agent_templates import BLANK, list_templates

    error = None
    try:
        data = _load(roster_path())
    except (OSError, UnicodeError, ValueError):
        data, error = {"agents": {}}, "roster_unreadable"
    entries = data["agents"]
    rows = [describe(orch, ident, entries.get(ident)) for ident, cfg in _registry(orch).items()
            if getattr(cfg, "status", "") in STATUSES]
    body = {
        "agents": rows,
        "templates": [{"key": BLANK, "name": "Blank", "role": "", "description": "an empty persona to fill in"},
                      *list_templates()],
        "tiers": list(TIERS),
        "safe_mode": safe_mode.enabled(),
        "limits": {"name_chars": NAME_CHARS, "max_created": MAX_CREATED, "revisions_kept": MAX_REVISIONS},
    }
    if error:
        body["error"] = error
    return body


def _kept(orch: Any, ident: str) -> dict:
    """What a retire leaves in place (all of it): for the confirmation and the reply."""
    from .agent import soul_path_for

    store = getattr(orch, "soul_versions", None)
    runs = getattr(orch, "run_history", None)
    try:
        persona = soul_path_for(ident).exists()
    except OSError:
        persona = False
    return {
        "persona": persona,
        "persona_versions": len(store.history(ident)) if store is not None else None,
        "runs": len(runs.list(ident, 200)) if runs is not None else None,
        "memory": True,
    }


def _go_live(orch: Any, ident: str, cfg: Any) -> None:
    """Make *cfg* live as ``Orchestrator.load_agents`` would have at boot."""
    register = getattr(orch, "register_live_agent", None)
    agent_dict = getattr(orch, "agent_dict", None)
    if not callable(register) or not callable(agent_dict):
        raise SoulEditError("hub_not_ready", 503, detail="this hub cannot add an agent while it runs")
    register(ident, agent_dict(cfg))


def _entry_quiet(ident: str) -> dict | None:
    try:
        return _load(roster_path())["agents"].get(ident)
    except (OSError, UnicodeError, ValueError):
        return None


# ── the four changes ─────────────────────────────────────────────────────────


def create(orch: Any, *, name: Any, template: Any = "", agent_id: Any = "", tier: Any = "",
           persona: Any = None, author: str = "owner") -> dict:
    """Create an agent from *template* (a key of ``agent_templates``; empty or ``blank``
    starts from nothing), persist it in the roster and make it live with its persona.

    Raises :class:`SoulEditError`: 409 safe mode, a taken/reserved id, a name another agent
    has, or too many created agents; 404 an unknown template; 413/422 a persona the SOUL guard refuses, a bad name,
    id or tier; 503 an unreadable roster. Blocking I/O: call it off the event loop.
    """
    from . import soul_edit
    from .agent_templates import (
        BLANK,
        ROSTER_TIERS,
        blank_agent_config,
        build_agent_config,
        get_template,
    )
    from .config import AgentConfig

    _refuse_in_safe_mode()
    display = clean_name(name)
    key = str(template or "").strip().lower() or BLANK
    wanted = str(agent_id or "").strip().lower()
    if key == BLANK:
        tmpl, config = None, blank_agent_config(display, wanted or None)
    else:
        tmpl = get_template(key)
        if tmpl is None:
            raise SoulEditError("unknown_template", 404, template=key[:64])
        config = build_agent_config(key, name=display, overrides={"id": wanted} if wanted else {})
    ident = new_agent_id(display, wanted)
    _check_new_id(orch, ident)
    _refuse_taken_name(_registry(orch), display, ident)
    roster_tier = str(tier or "").strip().lower() or ROSTER_TIERS.get(key, "foundation")
    if roster_tier not in TIERS:
        raise SoulEditError("bad_tier", 422, tiers=list(TIERS))
    archetype = tmpl["role"] if tmpl else "Custom agent"
    text = persona if persona is not None else _persona(
        ident, display, archetype, roster_tier, tmpl["description"] if tmpl else "", config["soul"])
    # The SOUL editor's own refusals, before anything is written.
    if not isinstance(text, str):
        raise SoulEditError("content_not_text", 422)
    if len(text.encode("utf-8")) > MAX_SOUL_BYTES:
        raise SoulEditError("too_large", 413, max_bytes=MAX_SOUL_BYTES)
    verdict = soul_edit.guard_verdict(text)
    if verdict["blocked"]:
        raise SoulEditError("soul_blocked", 422, guard=verdict)

    registry = _registry(orch)
    now = time.time()
    with _LOCK:
        # Again under the lock: another create or rename may have taken the id or the
        # name between the checks above and here.
        _check_new_id(orch, ident)
        _refuse_taken_name(registry, display, ident)
        data = read()
        entries = data["agents"]
        if ident in entries:
            raise SoulEditError("agent_exists", 409, agent=ident)
        live_created = sum(1 for e in entries.values()
                           if isinstance(e, dict) and e.get("created") is True and e.get("status") != "retired")
        if live_created >= MAX_CREATED:
            raise SoulEditError("too_many_agents", 409, max_created=MAX_CREATED)
        entry = {"created": True, "template": key, "name": display, "status": "active",
                 "archetype": archetype, "tier": roster_tier, "created_at": now, "revisions": []}
        revision = _revise(entry, "create", name=display, now=now, template=key)
        entries[ident] = entry
        _write(data)
        cfg = AgentConfig({**_overlay_row(ident, entry, None), "id": ident})
        target, _where = soul_edit.overlay_path(ident)
        made_folder = not target.parent.exists()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            registry[ident] = cfg
            _go_live(orch, ident, cfg)
            message = f"created from the {key} template" if tmpl else "created blank"
            soul = soul_edit.apply_soul(orch, ident, text, message=message, author=author, action="create")
        except BaseException:
            # Nothing half-made is left: not live, not in the registry, not in the roster.
            retire_live = getattr(orch, "retire_live_agent", None)
            if callable(retire_live) and ident in (getattr(orch, "agents", None) or {}):
                retire_live(ident)
            registry.pop(ident, None)
            entries.pop(ident, None)
            try:
                _write(data)
            except SoulEditError:
                logger.error("agent %s: the roster entry of a failed create could not be removed", ident)
            if made_folder:
                with contextlib.suppress(OSError):
                    target.parent.rmdir()
            raise
    audited = _audit(orch, ident, "create", revision, f"template {key}")
    return {"agent": describe(orch, ident, entry), "revision": revision, "soul": soul, "audited": audited}


def rename(orch: Any, agent_id: Any, name: Any) -> dict:
    """Give *agent_id* the display name *name*, for good; the id stays. A name another
    agent uses (or another agent's id) is refused (409)."""
    _refuse_in_safe_mode()
    ident = _known(orch, agent_id)
    display = clean_name(name)
    registry = _registry(orch)
    cfg = registry[ident]
    before = cfg.name
    if display == before:
        return {"agent": describe(orch, ident, _entry_quiet(ident)), "changed": False, "audited": False}
    _refuse_taken_name(registry, display, ident)
    now = time.time()
    with _LOCK:
        _refuse_taken_name(registry, display, ident)                    # again, under the lock
        data = read()
        entry = data["agents"].setdefault(ident, {"created": False, "status": cfg.status})
        entry["name"] = display
        revision = _revise(entry, "rename", name=display, now=now, previous=before)
        _write(data)
        cfg.name = display
        agent = (getattr(orch, "agents", None) or {}).get(ident)
        if agent is not None:
            agent.name = display
            if isinstance(getattr(agent, "config", None), dict):
                agent.config["name"] = display
    audited = _audit(orch, ident, "rename", revision)
    return {"agent": describe(orch, ident, entry), "changed": True, "previous": before,
            "revision": revision, "audited": audited}


def retire(orch: Any, agent_id: Any, *, confirm: Any = None, reason: Any = "") -> dict:
    """Take *agent_id* out of the hub, now and at every boot, keeping all it left behind.

    *confirm* must be the agent's id: without it nothing changes, and the refusal (400
    ``retire_unconfirmed``) says what would stop and what is kept. Jarvis is refused (409
    ``protected``), and so is an agent already retired (409)."""
    _refuse_in_safe_mode()
    ident = _known(orch, agent_id)
    registry = _registry(orch)
    cfg = registry[ident]
    if cfg.status == "retired":
        raise SoulEditError("already_retired", 409, agent=ident)
    if ident in PROTECTED:
        raise SoulEditError("protected", 409, agent=ident,
                            detail="every turn no other agent takes goes to this agent")
    kept = _kept(orch, ident)
    if str(confirm or "").strip().lower() != ident:
        raise SoulEditError("retire_unconfirmed", 400, would_retire={
            "agent": ident, "name": cfg.name, "kept": kept,
            "confirm": f'send {{"confirm": "{ident}"}}; restore brings it back as it was'})
    note = " ".join(str(reason or "").split())[:REASON_CHARS]
    now = time.time()
    with _LOCK:
        data = read()
        entry = data["agents"].setdefault(ident, {"created": False})
        entry.update(status="retired", retired_at=now, reason=note)
        revision = _revise(entry, "retire", name=cfg.name, now=now)
        _write(data)
        cfg.status = "retired"
        retire_live = getattr(orch, "retire_live_agent", None)
        if callable(retire_live):
            retire_live(ident)
        else:
            (getattr(orch, "agents", None) or {}).pop(ident, None)
    audited = _audit(orch, ident, "retire", revision)
    return {"agent": describe(orch, ident, entry), "revision": revision, "kept": kept, "audited": audited}


def restore(orch: Any, agent_id: Any) -> dict:
    """Bring a retired agent back: live again, with the persona, versions and history it
    had. 409 for one that is not retired, or when as many created agents as allowed are
    live."""
    _refuse_in_safe_mode()
    ident = _known(orch, agent_id)
    cfg = _registry(orch)[ident]
    if cfg.status != "retired":
        raise SoulEditError("not_retired", 409, agent=ident)
    now = time.time()
    with _LOCK:
        data = read()
        entries = data["agents"]
        entry = entries.get(ident)
        if not isinstance(entry, dict):
            raise SoulEditError("not_retired", 409, agent=ident)
        if entry.get("created") is True:
            live_created = sum(1 for e in entries.values()
                               if isinstance(e, dict) and e.get("created") is True and e.get("status") != "retired")
            if live_created >= MAX_CREATED:
                raise SoulEditError("too_many_agents", 409, max_created=MAX_CREATED)
        previous = copy.deepcopy(entry)
        entry.update(status="active", retired_at=None, reason="")
        revision = _revise(entry, "restore", name=cfg.name, now=now)
        _write(data)
        cfg.status = "active"
        try:
            _go_live(orch, ident, cfg)
        except BaseException:
            # Still retired, on disk as in the hub.
            cfg.status = "retired"
            entries[ident] = previous
            try:
                _write(data)
            except SoulEditError:
                logger.error("agent %s: a failed restore could not be undone in the roster", ident)
            raise
    audited = _audit(orch, ident, "restore", revision)
    return {"agent": describe(orch, ident, entry), "revision": revision, "audited": audited}


__all__ = [
    "FILENAME", "MAX_CREATED", "MAX_REVISIONS", "NAME_CHARS", "PROTECTED", "RESERVED", "TIERS",
    "clean_name", "create", "describe", "merge_rows", "new_agent_id", "read", "rename", "restore",
    "retire", "roster", "roster_path",
]
