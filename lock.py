#!/usr/bin/env python3
"""
lock.py — File-level locking for parallel AI development.
Prevents Claude and OpenCode from editing the same files simultaneously.
"""

import json
import sys
import time
from pathlib import Path

LOCKS_DIR = Path(".locks")
STALE_SECONDS = 30 * 60


def _lock_path(filepath: str) -> Path:
    encoded = filepath.replace("/", "__")
    return LOCKS_DIR / f"{encoded}.json"


def acquire(agent: str, files: list[str]) -> int:
    LOCKS_DIR.mkdir(exist_ok=True)
    conflicts = []
    for f in files:
        lp = _lock_path(f)
        if lp.exists():
            data = json.loads(lp.read_text())
            if data["agent"] != agent:
                conflicts.append((f, data["agent"]))
    if conflicts:
        for f, owner in conflicts:
            print(f"CONFLICT: {f} locked by {owner}")
        return 1
    for f in files:
        _lock_path(f).write_text(json.dumps({"agent": agent, "ts": time.time()}))
    print(f"Locked {len(files)} file(s) for {agent}")
    return 0


def release(agent: str, files: list[str]) -> int:
    for f in files:
        lp = _lock_path(f)
        if lp.exists():
            data = json.loads(lp.read_text())
            if data["agent"] == agent:
                lp.unlink()
    print(f"Released locks for {agent}")
    return 0


def status() -> int:
    if not LOCKS_DIR.exists():
        print("No locks held.")
        return 0
    held = False
    for lp in sorted(LOCKS_DIR.glob("*.json")):
        if lp.name.startswith("heartbeat_"):
            continue
        data = json.loads(lp.read_text())
        age = int(time.time() - data["ts"])
        print(f"{lp.stem.replace('__', '/')}  →  {data['agent']}  ({age}s ago)")
        held = True
    if not held:
        print("No locks held.")
    return 0


def release_stale() -> int:
    if not LOCKS_DIR.exists():
        return 0
    for lp in sorted(LOCKS_DIR.glob("*.json")):
        data = json.loads(lp.read_text())
        age = time.time() - data["ts"]
        if age > STALE_SECONDS:
            lp.unlink()
            print(f"Released stale lock: {lp.stem}")
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print("usage: lock.py [acquire|release|status|release-stale] ...")
        return 1
    cmd = argv[0]
    if cmd == "acquire" and len(argv) >= 3:
        return acquire(argv[1], argv[2:])
    elif cmd == "release" and len(argv) >= 3:
        return release(argv[1], argv[2:])
    elif cmd == "status":
        return status()
    elif cmd == "release-stale":
        return release_stale()
    else:
        print("usage: lock.py [acquire|release|status|release-stale] ...")
        return 1


if __name__ == "__main__":
    sys.exit(main())
