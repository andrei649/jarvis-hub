"""Owner chat maintenance commands (H084)."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import threading
import time
from collections import Counter
from contextlib import suppress
from pathlib import Path
from typing import Any

from . import load_set, settings_db
from .channels.outbound_safety import sanitize_text
from .skills import loader as skill_loader
from .skills import signing, switches

logger = logging.getLogger("nerva.maintenance_commands")

_RELOAD_LOCK = threading.Lock()
_REPORT_NAMES = 12
_MENU_REFRESH_WAIT_SECONDS = 5.0


def _policy(approval_store: Any) -> dict:
    """Strict effective policy snapshot; an unreadable store cannot widen H285."""
    settings_db.ensure_initialized()
    settings_db._require_readable_store()
    lists = {
        "disabled": load_set.parse_names(settings_db.get_value("loadset", "skills_disabled", "")),
        "only": load_set.parse_names(settings_db.get_value("loadset", "skills_only", "")),
    }
    key = signing._signing_key() or b""
    approval_path = approval_store.path
    approval_digest = (hashlib.sha256(approval_path.read_bytes()).digest()
                       if approval_path.exists() else None)
    return {"load_set": lists, "switches": switches.state(),
            "safe_mode": skill_loader.safe_mode.enabled(),
            "require_signed": signing.require_signed(),
            "signing_key_id": hashlib.sha256(key).digest(),
            "approval_store_id": approval_digest}


async def _finish_worker_before_cancellation(fn, *args, **kwargs):
    """Keep the reload lock until an off-loop authority read or scan has stopped.

    Cancellation is still delivered to the caller, and no cancelled candidate is
    published. Shielding only the first await would leave its thread running after
    the lock's finally block, allowing a second scan to overlap it.
    """
    worker = asyncio.create_task(asyncio.to_thread(fn, *args, **kwargs))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        with suppress(BaseException):
            worker.result()
        raise


def _registry_snapshot(loader: Any) -> dict:
    """Identity and authority-relevant values of each current registry slot."""
    return {name: (id(skill), str(getattr(skill, "path", "")),
                   getattr(skill, "source_fingerprint", None),
                   getattr(skill, "trusted", None), getattr(skill, "sandboxed", None),
                   getattr(skill, "owner_vouched", None), id(getattr(skill, "module", None)))
            for name, skill in loader.skills.items()}


def _candidate_still_admitted(candidate: skill_loader.SkillLoader, policy: dict) -> bool:
    """Recheck the exact candidate bytes and any external code approval at commit."""
    for skill in candidate.skills.values():
        fingerprint = getattr(skill, "source_fingerprint", None)
        if not fingerprint:
            if not skill.sandboxed:
                return False
            continue
        try:
            path = Path(skill.path)
            snapshot = signing.source_snapshot(path)
            if snapshot.fingerprint != fingerprint:
                return False
            if not skill.external or not skill.owner_vouched:
                continue
            trusted, reason = signing.verify_skill(path, snapshot=snapshot)
            signed = trusted and reason == "signed"
            approved = candidate._approval_store.approved_snapshot(path, snapshot=snapshot) is not None
            if not (signed or approved):
                return False
            if policy["require_signed"] and not skill.trusted and not skill.sandboxed:
                return False
        except Exception:
            return False
    return True


def _diff(before: dict, after: dict) -> dict[str, list[str] | int]:
    old, new = set(before), set(after)
    changed: list[str] = []
    unverified: list[str] = []
    unchanged = 0
    for name in sorted(old & new):
        prior, current = before[name], after[name]
        first = getattr(prior, "source_fingerprint", None)
        second = getattr(current, "source_fingerprint", None)
        if not first or not second:
            unverified.append(name)
        elif (first, str(prior.path), prior.trusted, prior.sandboxed,
              prior.owner_vouched, prior.module is not None) != (
                  second, str(current.path), current.trusted, current.sandboxed,
                  current.owner_vouched, current.module is not None):
            changed.append(name)
        else:
            unchanged += 1
    return {"added": sorted(new - old), "removed": sorted(old - new), "changed": changed,
            "unverified": unverified, "unchanged": unchanged}


def _names(label: str, names: list[str]) -> str:
    safe = [_safe_report_name(name, 64) for name in names[:_REPORT_NAMES]]
    suffix = f", +{len(names) - _REPORT_NAMES} more" if len(names) > _REPORT_NAMES else ""
    return f"{label} ({len(names)}): {', '.join(safe) if safe else 'none'}{suffix}"


def _safe_report_name(value: object, limit: int) -> str:
    raw = str(value)
    if len(raw) > 256:
        return "(long name withheld)"
    return (" ".join(sanitize_text(raw).split())[:limit] or "(unprintable)")


def _report(diff: dict, candidate: skill_loader.SkillLoader) -> str:
    skipped = sorted(set(candidate.discovery_skipped))
    pending = sorted(name for name, skill in candidate.skills.items()
                     if "pending review" in str(skill.signature_reason).lower())
    restricted = sorted(name for name, skill in candidate.skills.items()
                        if name not in pending and (skill.sandboxed or not skill.owner_vouched))
    return "\n".join((
        "Skills reloaded; registry diff:",
        _names("Added", diff["added"]), _names("Removed", diff["removed"]),
        _names("Changed", diff["changed"]), _names("Unverified", diff["unverified"]),
        _names("Skipped", skipped), _names("Pending review", pending),
        _names("Unapproved or sandboxed", restricted),
        f"Unchanged with verified source: {diff['unchanged']}",
    ))


async def reload_skills(ctx) -> str:
    """Rescan the installed tree without exposing a partial registry to other turns."""
    if not ctx.principal.admin:
        return "Only the owner can reload skills; nothing changed."
    if ctx.args.strip():
        return "Usage: /reload_skills (no arguments); nothing changed."
    live = getattr(ctx.orch, "skills", None)
    if not isinstance(live, skill_loader.SkillLoader):
        return "Skill loader unavailable; nothing changed."
    if not _RELOAD_LOCK.acquire(blocking=False):
        return "A skill reload is already running; nothing changed."
    committed = False
    report = ""
    menu_task = None
    menu_manager_present = False
    menu_queue_failed = False
    try:
        try:
            before_policy = await _finish_worker_before_cancellation(_policy,
                                                                       live._approval_store)
            before_map = _registry_snapshot(live)
            before_registry = live.skills
            before_skills = dict(before_registry)
            candidate = skill_loader.SkillLoader(approval_store=live._approval_store)
            candidate.kernel_gate = live.kernel_gate
            await _finish_worker_before_cancellation(
                candidate.discover, staging=True, declared_lists=before_policy["load_set"])
            if candidate.discovery_failures:
                return ("Skill scan skipped invalid or unreadable folders; live registry unchanged. "
                        + _names("Failed", sorted(set(candidate.discovery_failures))))
            after_policy = await _finish_worker_before_cancellation(_policy, live._approval_store)
            if before_policy != after_policy or not await _finish_worker_before_cancellation(
                    _candidate_still_admitted, candidate, after_policy):
                return "Skill policy changed during reload; live registry unchanged. Retry."
            # The admission walk can take time. Re-read live authority directly
            # before the no-await registry compare-and-swap.
            if before_policy != _policy(live._approval_store):
                return "Skill policy changed during reload; live registry unchanged. Retry."
            if (live is not ctx.orch.skills or live.skills is not before_registry
                    or before_map != _registry_snapshot(live)):
                return "Skills changed during reload; live registry unchanged. Retry."
            diff = _diff(before_skills, candidate.skills)
            usage = getattr(live, "_usage", None)
            if usage is not None:
                for skill in candidate.skills.values():
                    skill.usage_hook = lambda name, kind, sink=usage: sink.bump(name, kind)
            # One pointer replacement on the original loader, which curator and
            # ToolRPC holders already reference. No await separates check and swap.
            live.skills = candidate.skills
            committed = True
            # Enqueue synchronously before any later await or fallible status sync.
            # The channel owns its task; a cancelled command cannot cancel a
            # committed menu update or hold the scan lock across network I/O.
            manager = getattr(ctx.orch, "channel_manager", None)
            menu_manager_present = manager is not None
            if menu_manager_present:
                try:
                    queue = manager.queue_command_menu_refresh
                    menu_task = queue(owner_current=lambda: (
                        getattr(ctx.orch, "channel_manager", None) is manager))
                except Exception:
                    menu_queue_failed = True
                    logger.warning("Skill reload committed; Telegram menu refresh enqueue failed")
            status_warning = False
            try:
                load_set.begin("skills")
                for name in candidate.discovery_load_set_skipped:
                    load_set.note_skipped("skills", name)
                if not candidate.discovery_owner_unread:
                    load_set.finish("skills", candidate.discovery_folders | set(live.skills)
                                    | set(candidate.discovery_load_set_skipped),
                                    lists=after_policy["load_set"])
                live.sync_origins()
            except Exception:
                logger.warning("Skill reload committed; status or usage sync needs retry", exc_info=True)
                status_warning = True
            report = _report(diff, candidate)
            if status_warning:
                report += "\nStatus or usage sync needs retry."
        except Exception:
            if not committed:
                logger.warning("Skill reload failed; live registry retained", exc_info=True)
                return "Skill reload failed; live registry unchanged. Check the hub log."
            logger.warning("Skill reload committed; report needs retry", exc_info=True)
            report = "Skills reloaded; registry committed. Status or report needs retry."
    finally:
        _RELOAD_LOCK.release()
    if not menu_manager_present:
        return report
    if menu_queue_failed:
        return report + "\nTelegram menu refresh needs retry."
    if menu_task is None:
        return report + "\nTelegram menu will refresh when Telegram starts."
    try:
        done, _pending = await asyncio.wait({menu_task}, timeout=_MENU_REFRESH_WAIT_SECONDS)
        if not done:
            state = "Telegram menu refresh pending."
        elif menu_task.cancelled() or menu_task.result() is not True:
            state = "Telegram menu refresh needs retry."
        else:
            state = "Telegram menu updated."
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("Skill reload committed; Telegram menu refresh result unavailable")
        state = "Telegram menu refresh needs retry."
    return report + "\n" + state


async def reload_mcp(ctx) -> str:
    """Preview, then confirm a saved MCP configuration reread for this owner."""
    if not ctx.principal.admin:
        return "Only the owner can reload MCP servers; nothing changed."
    from . import mcp_reload_confirmation as confirmation
    from . import safe_mode
    from .mcp.client import MCPManager

    words = ctx.args.strip().split()
    if words and words != ["cancel"] and not (
        len(words) == 2 and words[0] == "confirm"
        and re.fullmatch(r"[A-Za-z0-9_-]{16,64}", words[1])
    ):
        return "Usage: /reload_mcp | /reload_mcp confirm <nonce> | /reload_mcp cancel; nothing changed."
    actor = confirmation.actor_for(ctx.principal)
    if actor is None:
        return "MCP reload needs a stable owner chat identity; nothing changed."
    if words == ["cancel"]:
        confirmation.cancel(actor)
        return "Pending MCP reload proposal cleared; this does not stop an already running reload."

    if safe_mode.enabled():
        return "Safe mode keeps saved MCP servers unloaded; nothing changed."
    manager = getattr(ctx.orch, "mcp", None)
    if not isinstance(manager, MCPManager):
        return "MCP manager unavailable; nothing changed."

    def local_gate() -> bool:
        try:
            return (getattr(ctx.orch, "mcp", None) is manager
                    and not safe_mode.enabled() and not manager._halted()
                    and callable(getattr(manager, "saved_reload_commit_held", None)))
        except Exception:
            return False

    if not local_gate():
        return "MCP saved reload is unavailable or halted; nothing changed."

    async def read_saved():
        return await _finish_worker_before_cancellation(confirmation._read_saved_config, manager)

    try:
        saved = await read_saved()
        if not local_gate():
            return "MCP manager or safety policy changed; nothing changed."
        plan = manager.prepare_saved_reload(saved.allowed_rows)
        if not isinstance(plan.fingerprint, str) or not plan.fingerprint:
            return "MCP saved reload plan unavailable; nothing changed."
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("MCP saved reload preview failed", exc_info=True)
        return "Saved MCP configuration is unreadable or malformed; nothing changed."

    if not words:
        try:
            counts = _mcp_summary(plan.summary)
            nonce = confirmation.issue(actor, manager, saved, plan.fingerprint)
        except Exception:
            logger.warning("MCP saved reload preview unavailable", exc_info=True)
            return "MCP saved reload preview unavailable; nothing changed."
        if nonce is None:
            return "Too many MCP reload proposals are pending; nothing changed."
        if not local_gate():
            confirmation.cancel(actor)
            return "MCP manager or safety policy changed; nothing changed."
        return ("Saved MCP configuration preview (boot load set still applies): " + counts + ". "
                "New servers stay disconnected. To apply this exact plan, send "
                f"/reload_mcp confirm {nonce} within 2 minutes; /reload_mcp cancel clears it. "
                "No permanent always-reload switch is available.")

    proposal = confirmation.consume(actor, words[1])
    if proposal is None:
        return "MCP reload confirmation is invalid, expired or already used; nothing changed."
    if not local_gate() or not confirmation.matches(proposal, actor, manager, saved, plan.fingerprint):
        return "MCP saved configuration, manager or boot policy changed; request a new preview. Nothing changed."

    async def still_current() -> bool:
        if not local_gate() or proposal.expires_at <= time.monotonic():
            return False
        try:
            current = await read_saved()
        except asyncio.CancelledError:
            raise
        except Exception:
            return False
        return local_gate() and confirmation.matches(proposal, actor, manager, current, plan.fingerprint)

    try:
        result = await manager.apply_saved_reload(plan, still_current=still_current)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("MCP saved reload failed", exc_info=True)
        return "MCP saved reload failed; inspect the MCP status before retrying."
    if getattr(ctx.orch, "mcp", None) is not manager:
        return "MCP manager replaced during reload; the old manager may have changed. Inspect MCP status."
    status = result.get("status") if isinstance(result, dict) else None
    if status == "busy":
        return "An MCP reload is already running; nothing changed."
    if status == "halted":
        return "MCP reload stopped by safe mode or the emergency stop; inspect MCP status."
    if status == "stale":
        return "MCP saved reload became stale; some earlier server changes may have occurred. Inspect MCP status."
    if status not in {"ok", "partial"}:
        return "MCP saved reload returned an unknown result; inspect MCP status."
    if status == "ok":
        if not await still_current():
            return "MCP reload finished but saved policy changed; held state was not committed. Inspect MCP status."
        try:
            manager.saved_reload_commit_held(saved.held_rows)
        except Exception:
            logger.warning("MCP saved reload held-state commit failed", exc_info=True)
            return "MCP reload finished, but held-state sync failed. Inspect MCP status before another save."
    try:
        return _mcp_result_report(result)
    except Exception:
        logger.warning("MCP saved reload report failed closed", exc_info=True)
        return "MCP reload finished, but its report is unavailable. Inspect MCP status."


def _mcp_summary(summary: Any) -> str:
    if (not isinstance(summary, dict) or len(summary) > 16
            or any(not isinstance(key, str) or not re.fullmatch(r"[a-z_]{1,32}", key)
                   or type(value) is not int or not 0 <= value <= 1_000_000
                   for key, value in summary.items())):
        raise ValueError("invalid MCP summary")
    return "; ".join(f"{key.replace('_', ' ')} {summary[key]}" for key in sorted(summary)) or "no server changes"


def _mcp_result_report(result: dict) -> str:
    rows = result.get("servers")
    if not isinstance(rows, dict):
        return "MCP reload result unavailable; inspect MCP status."
    counts = Counter(str(row.get("status", "unknown")) for row in rows.values() if isinstance(row, dict))
    failed = sum(count for status, count in counts.items() if status.startswith("failed"))
    skipped = sum(count for status, count in counts.items() if status.startswith("skipped"))
    connected = sum(row.get("connected_after") is True for row in rows.values() if isinstance(row, dict))
    prefix = "MCP saved configuration applied" if result.get("status") == "ok" else "MCP saved reload partial"
    lines = [f"{prefix}; actual server and tool changes:",
             f"Summary: {len(rows)} servers; failed {failed}; skipped {skipped}; connected {connected}."]
    for name in sorted(rows)[:8]:
        row = rows[name]
        if not isinstance(row, dict):
            continue
        connected_text = "connected" if row.get("connected_after") is True else "disconnected"
        status = _safe_report_name(row.get("status", "unknown"), 40)
        added = row.get("added") if isinstance(row.get("added"), list) else []
        removed = row.get("removed") if isinstance(row.get("removed"), list) else []
        changed = row.get("changed") if isinstance(row.get("changed"), list) else []
        lines.append(f"{_safe_report_name(name, 64)}: {status}; {connected_text}; "
                     f"+{len(added)} -{len(removed)} ~{len(changed)}")
        for label, names in (("Added", added), ("Removed", removed), ("Changed", changed)):
            if names:
                shown = [_safe_report_name(item, 40) for item in names[:2]]
                suffix = f", +{len(names) - 2} more" if len(names) > 2 else ""
                lines.append(f"  {label} ({len(names)}): {', '.join(shown)}{suffix}")
    if len(rows) > 8:
        lines.append(f"+{len(rows) - 8} more servers (not shown)")
    return "\n".join(lines)
