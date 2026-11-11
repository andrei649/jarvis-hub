"""install.py — installing a language server: an approval card, then a pinned install.

A language server is third-party code that will run on the owner's machine, so an
install is never a click away:

* :func:`request_install` validates the request against the registry (a known
  server, an installable recipe, its toolchain present) and queues an ``lsp.install``
  card at the approval queue's irreversible tier
  (:mod:`agents.core.autonomy.irreversible`). The card shows the exact packages and
  versions, the registry, the target directory and the command line. Nothing is
  fetched yet.
* :func:`apply_approved` runs only on a person's accept of that card
  (``irreversible.execute`` refuses machine deciders), only while the recipe still
  says what the card said, and only once per card.

The install itself: a fixed argv (never a shell, never ``curl | sh``), one package
registry named explicitly (``--registry`` / ``--index-url`` / ``GOPROXY``), npm with
``--ignore-scripts`` (no install-time code), pip with ``--only-binary :all:`` (no
source builds), Go with the checksum database on and ``GOTOOLCHAIN=local``. It writes
into Nerva's own tools directory and nowhere else: under ``bwrap`` the rest of the
filesystem is read-only and the owner's home and data root are hidden; the
environment is scrubbed and ``HOME`` points into the tools directory. It is bounded
in time (:data:`INSTALL_TIMEOUT_SECONDS`) and its output is kept as a short tail.
What it cannot do is limit the network to the registry host alone — that needs an
egress proxy this module does not run; the registry is pinned on the command line.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any

from . import confine
from .registry import REGISTRIES, ServerSpec, spec

logger = logging.getLogger("jarvis.codeintel.lsp.install")

APPROVAL_KIND = "lsp.install"
INSTALL_TIMEOUT_SECONDS = 600
OUTPUT_TAIL_CHARS = 2000
_LOCK = threading.Lock()


class InstallRefused(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = detail


def _tools() -> Path:
    from .manager import get_manager

    return get_manager().tools


def _state_path(base: Path) -> Path:
    return base / "installs.json"


def install_state(base: Path) -> dict[str, dict]:
    try:
        data = json.loads(_state_path(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = data.get("servers") if isinstance(data, dict) else None
    return {k: v for k, v in rows.items() if isinstance(v, dict)} if isinstance(rows, dict) else {}


def _write_state(base: Path, rows: dict[str, dict]) -> None:
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = _state_path(base)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"format": "nerva-lsp-installs/1", "servers": rows}, indent=1, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, path)


def toolchain(kind: str) -> str | None:
    if kind == "npm":
        return shutil.which("npm")
    if kind == "go":
        return shutil.which("go")
    if kind == "pip":
        return sys.executable
    return None


def plan(row: ServerSpec, base: Path) -> list[list[str]]:
    """The exact argv list(s) an approved install runs for *row* (program first)."""
    recipe = row.recipe
    program = toolchain(recipe.kind) or recipe.kind
    if recipe.kind == "npm":
        return [[program, "install", "--prefix", str(base / "npm"), "--ignore-scripts", "--no-audit",
                 "--no-fund", "--save-exact", "--registry", REGISTRIES["npm"], *recipe.packages]]
    if recipe.kind == "pip":
        venv = base / "venv" / row.id
        return [[program, "-m", "venv", "--clear", str(venv)],
                [str(venv / "bin" / "python"), "-m", "pip", "install", "--disable-pip-version-check",
                 "--no-input", "--only-binary", ":all:", "--index-url", REGISTRIES["pip"], *recipe.packages]]
    if recipe.kind == "go":
        return [[program, "install", *recipe.packages]]
    return []


def _payload(row: ServerSpec, base: Path) -> dict:
    return {"operation": APPROVAL_KIND, "server": row.id, "kind": row.recipe.kind,
            "packages": list(row.recipe.packages), "registry": REGISTRIES.get(row.recipe.kind, ""),
            "target": str(base), "commands": [" ".join(argv) for argv in plan(row, base)]}


def request_install(orch: Any, server_id: str, *, requested_by: str = "owner") -> dict:
    """Queue the card: ``{"pending": task id, "server": …}`` or raise :class:`InstallRefused`."""
    from agents.core.autonomy import irreversible

    row = spec(server_id)
    if row is None:
        raise InstallRefused("unknown_server")
    if not row.recipe.installable:
        raise InstallRefused("manual_only", row.recipe.hint)
    if toolchain(row.recipe.kind) is None:
        raise InstallRefused("toolchain_missing", row.recipe.kind)
    base = _tools()
    with _LOCK:
        rows = install_state(base)
        current = rows.get(row.id) or {}
        if current.get("status") in ("pending", "installing"):
            queue = getattr(getattr(orch, "autonomy", None), "queue", None)
            can_ask = callable(getattr(queue, "pending_decisions", None))
            waiting = {getattr(t, "id", None) for t in irreversible.pending(orch, APPROVAL_KIND)}
            if (current.get("status") == "installing" or not can_ask
                    or current.get("task_id") in waiting):
                raise InstallRefused("already_pending", str(current.get("task_id") or ""))
            # The card was declined or expired: a new request replaces it.
        payload = _payload(row, base)
        preview = {
            "action": f"Install the {row.name} language server",
            "packages": ", ".join(row.recipe.packages), "registry": payload["registry"],
            "target": str(base), "commands": payload["commands"],
            "effect": ("downloads these exact versions from this registry into Nerva's tools "
                       "directory; afterwards the server runs as third-party code, sandboxed, "
                       "whenever the agent edits a matching file"),
        }
        queued = irreversible.enqueue(orch, APPROVAL_KIND,
                                      title=f"Install language server {row.id} ({row.recipe.version})",
                                      payload=payload, preview=preview)
        if "pending" not in queued:
            raise InstallRefused(str(queued.get("refused") or "approval_queue_unavailable"))
        rows[row.id] = {"status": "pending", "task_id": queued["pending"], "version": row.recipe.version,
                        "requested_by": requested_by, "requested_at": time.time(),
                        "payload_sha256": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()}
        _write_state(base, rows)
    return {"pending": queued["pending"], "server": row.id, "packages": list(row.recipe.packages)}


def _install_env(row: ServerSpec, base: Path) -> dict[str, str]:
    env = confine.child_env(base / "home-install", offline=False)
    env.update({"npm_config_registry": REGISTRIES["npm"], "npm_config_ignore_scripts": "true",
                "npm_config_cache": str(base / "cache" / "npm"),
                "PIP_INDEX_URL": REGISTRIES["pip"], "PIP_NO_CACHE_DIR": "1",
                "GOPROXY": REGISTRIES["go"], "GOSUMDB": "sum.golang.org", "GONOSUMDB": "", "GOFLAGS": "-mod=mod",
                "GOBIN": str(base / "go" / "bin"), "GOPATH": str(base / "go" / "path"),
                "GOMODCACHE": str(base / "go" / "mod"), "GOCACHE": str(base / "cache" / "go")})
    return env


async def _run(argv: list[str], env: dict[str, str], base: Path) -> tuple[int, str]:
    wrapped, _ = confine.wrap(argv, root=base, state_dir=base, network=True)
    kwargs: dict[str, Any] = {"start_new_session": True} if os.name == "posix" else {}
    proc = await asyncio.create_subprocess_exec(  # nosec B603 — fixed argv from the registry, no shell
        *wrapped, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT, cwd=str(base), env=env, **kwargs)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), INSTALL_TIMEOUT_SECONDS)
    except TimeoutError:
        from .client import kill_group

        kill_group(proc.pid)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), 5)
        return -1, "timed out"
    return proc.returncode or 0, (out or b"").decode("utf-8", "replace")[-OUTPUT_TAIL_CHARS:]


async def apply_approved(task: Any, orch: Any) -> dict:
    """A person accepted the card: run the install it describes, once."""
    decision = str(getattr(task, "decision", "") or "").strip().lower()
    if decision not in ("accept", "approve"):
        return {"status": "refused", "reason": "edit_not_supported"}
    payload = dict(getattr(task, "payload", {}) or {})
    row = spec(payload.get("server"))
    if row is None:
        return {"status": "refused", "reason": "unknown_server"}
    base = _tools()
    task_id = getattr(task, "id", None)
    with _LOCK:
        rows = install_state(base)
        current = rows.get(row.id) or {}
        if current.get("task_id") != task_id:
            return {"status": "refused", "reason": "not_requested"}
        if current.get("status") != "pending":
            return {"status": "refused", "reason": "already_applied"}
        expected = _payload(row, base)
        if any(payload.get(k) != v for k, v in expected.items()):
            return {"status": "refused", "reason": "payload_changed"}
        current["status"] = "installing"
        current["approved_by"] = str(getattr(task, "decided_by", "") or "owner")
        _write_state(base, rows)
    env = _install_env(row, base)
    code, tail = 0, ""
    for argv in plan(row, base):
        code, tail = await _run(argv, env, base)
        if code != 0:
            break
    from .manager import get_manager

    binary, source = get_manager().locate(row)
    ok = code == 0 and source == "nerva"
    with _LOCK:
        rows = install_state(base)
        entry = rows.get(row.id) or {}
        entry.update({"status": "installed" if ok else "failed", "finished_at": time.time(),
                      "binary": binary if ok else None,
                      "error": "" if ok else (f"exit {code}" if code else "binary_missing"),
                      "output_tail": tail})
        rows[row.id] = entry
        _write_state(base, rows)
    _audit(orch, entry.get("approved_by", "owner"), "lsp.install",
           f"language server {row.id} {row.recipe.version}: {entry['status']} (task {task_id})",
           {"server": row.id, "packages": list(row.recipe.packages), "status": entry["status"]})
    return {"status": "ok" if ok else "failed", "server": row.id, "reason": entry["error"] or None}


def _audit(orch: Any, actor: str, action: str, why: str, metadata: dict) -> None:
    audit = getattr(orch, "intent_log", None)
    if callable(getattr(audit, "record", None)):
        try:
            audit.record(actor=actor, action=action, why=why, cause="codeintel.lsp", metadata=metadata)
        except Exception:  # noqa: BLE001 — a projection
            logger.warning("language-server install audit failed", exc_info=True)


__all__ = ["APPROVAL_KIND", "InstallRefused", "apply_approved", "install_state", "plan", "request_install",
           "toolchain"]
