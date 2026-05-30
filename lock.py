#!/usr/bin/env python3
"""
lock.py — Lock/unlock helper for parallel development.

Usage:
  python lock.py acquire opencode "building Oracle Bridge"
  python lock.py acquire claude   "implementing H2.x skills"
  python lock.py release opencode
  python lock.py release claude
  python lock.py status
"""

import json
import os
import sys
import time
from pathlib import Path

LOCK_DIR = Path(__file__).resolve().parent.parent / "memory_logs" / "oracle" / "locks"
LOCK_DIR.mkdir(parents=True, exist_ok=True)

AGENTS = {"opencode", "claude"}


def acquire(agent: str, message: str):
    path = LOCK_DIR / f"{agent}.active"
    if path.exists():
        data = json.loads(path.read_text())
        print(f"[LOCK] {agent} already locked: {data.get('message', '?')} (since {data.get('time', '?')})")
        return False
    data = {"agent": agent, "message": message, "time": time.strftime("%H:%M:%S"), "ts": time.time()}
    path.write_text(json.dumps(data))
    print(f"[LOCK] {agent} locked: {message}")
    return True


def release(agent: str):
    path = LOCK_DIR / f"{agent}.active"
    if not path.exists():
        print(f"[INFO] {agent} not locked")
        return False
    path.unlink()
    print(f"[UNLOCK] {agent} released")
    return True


def status():
    locks = []
    for f in LOCK_DIR.glob("*.active"):
        locks.append(json.loads(f.read_text()))
    if not locks:
        print("No active locks")
    else:
        for lk in locks:
            age = int(time.time() - lk.get("ts", 0))
            print(f"[LOCK] {lk['agent']}: {lk['message']} ({age}s ago)")
    return locks


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        status()
    elif args[0] == "acquire" and len(args) >= 3 and args[1] in AGENTS:
        acquire(args[1], " ".join(args[2:]))
    elif args[0] == "release" and len(args) >= 2 and args[1] in AGENTS:
        release(args[1])
    elif args[0] == "status":
        status()
    else:
        print("Usage: lock.py [acquire|release|status] [agent] [message]")
        sys.exit(1)
