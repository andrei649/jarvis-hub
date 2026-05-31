#!/usr/bin/env python3
"""
lock.py — Lock/unlock helper for parallel development.

Usage:
  # Agent-level lock (for an entire session)
  python lock.py acquire opencode "building Oracle Bridge"
  python lock.py acquire claude   "implementing H2.x skills"
  python lock.py release opencode
  python lock.py release claude --force

  # Component-level lock (for a specific file or directory)
  python lock.py acquire-component opencode agents/web.py "adding oracle endpoints"
  python lock.py release-component opencode agents/web.py
  python lock.py release-component opencode agents/web.py --force

  # Status / check / stale
  python lock.py status
  python lock.py check agents/web.py
  python lock.py release-stale
"""

import json
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOCK_DIR = BASE_DIR / "memory_logs" / "oracle" / "locks"
LOCK_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = LOCK_DIR / "lock_state.json"
STALE_TIMEOUT = 1800  # 30 minutes in seconds

AGENTS = {"opencode", "claude", "antigravity"}


# ── State file helpers ──────────────────────────────────────────────

def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _normalize(path: str) -> str:
    return str(Path(path).resolve()).lower()


# ── Stale lock detection ────────────────────────────────────────────

def _check_stale(path: str, info: dict) -> bool:
    age = time.time() - info.get("ts", 0)
    return age > STALE_TIMEOUT


def _auto_release_stale(state: dict) -> dict:
    stale = []
    for path, info in list(state.items()):
        if _check_stale(path, info):
            stale.append((path, info["entity"]))
            del state[path]
    if stale:
        for path, entity in stale:
            print(f"[STALE] Released {entity} lock on {Path(path).name} (>{STALE_TIMEOUT//60}min)")
        _save_state(state)
    return state


def release_stale() -> int:
    """Explicitly release all stale component locks. Returns count released."""
    state = _load_state()
    stale = []
    for path, info in list(state.items()):
        if _check_stale(path, info):
            stale.append(path)
            del state[path]
    if stale:
        _save_state(state)
        for path in stale:
            print(f"[STALE] Released lock on {Path(path).name}")
    else:
        print("No stale locks found")
    # Also check agent-level locks
    for f in LOCK_DIR.glob("*.active"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if _check_stale(str(f), data):
                f.unlink()
                print(f"[STALE] Released agent lock: {f.stem}")
                stale.append(str(f))
        except (json.JSONDecodeError, OSError):
            pass
    return len(stale)


# ── Component-level locks ───────────────────────────────────────────

def acquire_component(entity: str, component_path: str, message: str) -> bool:
    state = _load_state()
    state = _auto_release_stale(state)
    norm = _normalize(component_path)

    for locked_path, info in state.items():
        if info["entity"] != entity:
            if norm.startswith(locked_path) or locked_path.startswith(norm):
                age = int(time.time() - info.get("ts", 0))
                print(f"[BLOCKED] {component_path} is locked by {info['entity']} "
                      f"({info.get('task', '?')}, {age}s old)")
                return False

    state[norm] = {
        "entity": entity,
        "task": message,
        "ts": time.time(),
        "time": time.strftime("%H:%M:%S"),
    }
    _save_state(state)
    print(f"[LOCK] {entity} locked component: {component_path} ({message})")
    return True


def release_component(entity: str, component_path: str, force: bool = False) -> bool:
    state = _load_state()
    norm = _normalize(component_path)
    if norm not in state:
        print(f"[INFO] Component {component_path} is not locked")
        return False
    if state[norm]["entity"] != entity and not force:
        print(f"[BLOCKED] {component_path} is locked by {state[norm]['entity']}, use --force to override")
        return False
    info = state.pop(norm)
    _save_state(state)
    action = "FORCE-UNLOCK" if force else "UNLOCK"
    print(f"[{action}] {entity} released component: {Path(component_path).name} ({info.get('task', '?')})")
    return True


def check_component(component_path: str) -> dict | None:
    state = _load_state()
    state = _auto_release_stale(state)
    norm = _normalize(component_path)
    for locked_path, info in state.items():
        if norm.startswith(locked_path) or locked_path.startswith(norm):
            return info
    return None


# ── Agent-level locks (legacy, backward compatible) ─────────────────

def acquire(agent: str, message: str) -> bool:
    path = LOCK_DIR / f"{agent}.active"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        print(f"[LOCK] {agent} already locked: {data.get('message', '?')} (since {data.get('time', '?')})")
        return False
    data = {"agent": agent, "message": message, "time": time.strftime("%H:%M:%S"), "ts": time.time()}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"[LOCK] {agent} locked: {message}")
    return True


def release(agent: str, force: bool = False) -> bool:
    path = LOCK_DIR / f"{agent}.active"
    if not path.exists():
        print(f"[INFO] {agent} not locked")
        return False
    if force:
        path.unlink()
        print(f"[FORCE-UNLOCK] {agent} released")
        return True
    data = json.loads(path.read_text(encoding="utf-8"))
    age = time.time() - data.get("ts", 0)
    if age > STALE_TIMEOUT:
        path.unlink()
        print(f"[STALE] {agent} lock was stale (>{STALE_TIMEOUT//60}min), auto-released")
        return True
    path.unlink()
    print(f"[UNLOCK] {agent} released")
    return True


# ── Status ──────────────────────────────────────────────────────────

def status() -> tuple:
    agent_locks = []
    for f in sorted(LOCK_DIR.glob("*.active")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            agent_locks.append(data)
        except (json.JSONDecodeError, OSError):
            pass

    state = _auto_release_stale(_load_state())
    component_locks = list(state.items())

    if not agent_locks and not component_locks:
        print("No active locks")
        return [], []

    for lk in agent_locks:
        age = int(time.time() - lk.get("ts", 0))
        status_flag = " [STALE]" if age > STALE_TIMEOUT else ""
        print(f"[AGENT] {lk['agent']}: {lk['message']} ({age}s ago){status_flag}")

    for path, info in component_locks:
        age = int(time.time() - info.get("ts", 0))
        name = Path(path).name or path
        status_flag = " [STALE]" if age > STALE_TIMEOUT else ""
        print(f"[COMPONENT] {info['entity']}: {name} ({info.get('task', '?')}, {age}s ago){status_flag}")

    return agent_locks, component_locks


# ── CLI ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]
    force = "--force" in args
    args = [a for a in args if a != "--force"]

    if not args:
        status()
    elif args[0] == "acquire" and len(args) >= 3 and args[1] in AGENTS:
        acquire(args[1], " ".join(args[2:]))
    elif args[0] == "release" and len(args) >= 2 and args[1] in AGENTS:
        release(args[1], force=force)
    elif args[0] == "acquire-component" and len(args) >= 4 and args[1] in AGENTS:
        acquire_component(args[1], args[2], " ".join(args[3:]))
    elif args[0] == "release-component" and len(args) >= 3 and args[1] in AGENTS:
        release_component(args[1], args[2], force=force)
    elif args[0] == "check" and len(args) >= 2:
        info = check_component(args[1])
        if info:
            age = int(time.time() - info.get("ts", 0))
            print(f"Locked by {info['entity']}: {info.get('task', '?')} ({age}s ago)")
        else:
            print("Free")
    elif args[0] == "release-stale":
        release_stale()
    elif args[0] == "status":
        status()
    else:
        print("Usage:")
        print("  lock.py acquire <agent> <message>")
        print("  lock.py release <agent> [--force]")
        print("  lock.py acquire-component <agent> <path> <message>")
        print("  lock.py release-component <agent> <path> [--force]")
        print("  lock.py check <path>")
        print("  lock.py release-stale")
        print("  lock.py status")
        sys.exit(1)
