"""
oracle_bridge.py — Pipeline Weaver: bridges Claude (GitHub) and OpenCode.

Monitors the GitHub repo for new commits from external agents (Claude),
auto-pulls and validates them, tracks session progress, detects parallel-work
conflicts, and exposes real-time status to the HUD and OpenCode CLI.
"""

import asyncio
import json
import logging
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from agents.core.paths import data_path

from ..http_client import PluginHTTPClient

logger = logging.getLogger("jarvis.oracle")

REPO_DIR = Path(__file__).resolve().parent.parent.parent.parent
CONFLICT_DIR = data_path("oracle")
CONFLICT_DIR.mkdir(parents=True, exist_ok=True)
SESSION_FILE = CONFLICT_DIR / "sessions.json"
FILE_HASH_FILE = CONFLICT_DIR / "file_hashes.json"

GITHUB_API = "https://api.github.com/repos/andrei649/jarvis-hub"


@dataclass
class ClaudeSession:
    session_id: str
    status: str = "pending"  # pending | running | done | failed
    started_at: float = 0.0
    completed_at: Optional[float] = None
    commit_sha: str = ""
    commit_msg: str = ""
    tasks_completed: list[str] = field(default_factory=list)
    tests_total: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    error: str = ""


@dataclass
class Conflict:
    file_path: str
    local_hash: str
    remote_hash: str
    detected_at: float
    resolved: bool = False


class OracleBridgePlugin:
    def __init__(self, github_token: str = ""):
        self.github_token = github_token
        self.last_checked_sha: str = ""
        self.sessions: list[ClaudeSession] = []
        self.current_session: Optional[ClaudeSession] = None
        self.file_hashes: dict[str, str] = {}
        self.conflicts: list[Conflict] = []
        self._watcher_task: Optional[asyncio.Task] = None
        self._running = False
        self._client = PluginHTTPClient.for_plugin("oracle")
        self._load_state()

    # ── Public API ────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "current_session": asdict(self.current_session) if self.current_session else None,
            "sessions": [asdict(s) for s in self.sessions[-10:]],
            "conflicts": [asdict(c) for c in self.conflicts if not c.resolved],
            "total_sessions": len(self.sessions),
            "total_conflicts": len(self.conflicts),
            "watcher_running": self._running,
            "last_checked": self.last_checked_sha[:8] if self.last_checked_sha else "",
        }

    def start_watcher(self):
        if self._running:
            return
        self._running = True
        self._watcher_task = asyncio.create_task(self._watcher_loop())
        logger.info("Oracle watcher started (30s poll)")

    async def stop_watcher(self):
        self._running = False
        if self._watcher_task:
            self._watcher_task.cancel()
            self._watcher_task = None

    async def sync_now(self) -> dict:
        return await self._check_github()

    async def check_conflicts(self) -> list[dict]:
        self._scan_file_hashes()
        result = [asdict(c) for c in self.conflicts if not c.resolved]
        return result

    # ── GitHub monitoring ─────────────────────────────────────────

    async def _watcher_loop(self):
        while self._running:
            try:
                await self._check_github()
            except Exception as e:
                logger.warning(f"Oracle watcher error: {e}")
            await asyncio.sleep(30)

    async def _check_github(self) -> dict:
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.github_token:
            headers["Authorization"] = f"token {self.github_token}"

        try:
            resp = await self._client.get(f"{GITHUB_API}/commits?per_page=1", headers=headers)
            if resp.status_code != 200:
                return {"ok": False, "error": f"GitHub API: {resp.status_code}"}
            data = resp.json()
            if not data:
                return {"ok": False, "error": "no commits"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

        sha = data[0]["sha"]
        msg = data[0]["commit"]["message"].split("\n")[0]
        author = data[0].get("author", {})
        author_name = (author or {}).get("login", "unknown")

        if sha == self.last_checked_sha:
            return {"ok": True, "new": False, "sha": sha[:8]}

        self.last_checked_sha = sha

        if author_name != "andrei649":
            result = await self._process_claude_commit(sha, msg)
            return {"ok": True, "new": True, "sha": sha[:8], "author": author_name, **result}

        return {"ok": True, "new": True, "sha": sha[:8], "author": author_name, "note": "own commit, skipped"}

    async def _process_claude_commit(self, sha: str, msg: str) -> dict:
        sid = f"claude-{sha[:8]}-{int(time.time())}"
        session = ClaudeSession(
            session_id=sid,
            status="running",
            started_at=time.time(),
            commit_sha=sha,
            commit_msg=msg,
        )
        self.current_session = session
        self.sessions.append(session)
        self._save_state()

        pull_ok, pull_err = self._git_pull()
        if not pull_ok:
            session.status = "failed"
            session.error = f"git pull failed: {pull_err}"
            self._save_state()
            return {"pull": False, "error": pull_err}

        session.tasks_completed = self._parse_commit_tasks(msg)

        self._scan_file_hashes()

        passed, total, failed, test_err = self._run_tests()
        session.tests_passed = passed
        session.tests_total = total
        session.tests_failed = failed
        session.status = "done" if failed == 0 else "failed"
        if test_err:
            session.error = test_err
        session.completed_at = time.time()
        self._save_state()

        return {
            "pull": True,
            "tests": {"passed": passed, "total": total, "failed": failed},
            "tasks": session.tasks_completed,
        }

    # ── Git operations ────────────────────────────────────────────

    def _git_pull(self) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["git", "pull", "--rebase"],
                cwd=REPO_DIR,
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                return False, result.stderr.strip() or result.stdout.strip()
            return True, ""
        except Exception as e:
            return False, str(e)

    # ── Test runner ───────────────────────────────────────────────

    def _run_tests(self) -> tuple[int, int, int, str]:
        try:
            result = subprocess.run(
                ["python", "-m", "pytest", "tests/", "-v", "--tb=short"],
                cwd=REPO_DIR,
                capture_output=True, text=True, timeout=120,
            )
            out = result.stdout + result.stderr
            passed = total = 0
            for line in out.split("\n"):
                if "passed" in line and "failed" in line and "=" not in line:
                    parts = line.strip().split()
                    for p in parts:
                        if "passed" in p:
                            try:
                                passed = int(parts[parts.index(p) - 1])
                            except (ValueError, IndexError):
                                pass
                        if "failed" in p:
                            try:
                                total = passed + int(parts[parts.index(p) - 1])
                            except (ValueError, IndexError):
                                pass
            if result.returncode == 0:
                total = passed
            else:
                total = passed + (total - passed) if total > passed else passed + 1
            error = result.stderr.strip() if result.returncode != 0 else ""
            return passed, total, total - passed if result.returncode != 0 else 0, error
        except Exception as e:
            return 0, 0, 0, str(e)

    # ── File hash scanning (conflict detection) ───────────────────

    def _scan_file_hashes(self):
        import hashlib
        patterns = ["agents/core/**/*.py", "agents/web/**/*.py",
                     "agents/web/static/*.js", "tests/*.py"]
        from glob import glob
        new_hashes = {}
        for pattern in patterns:
            for f in glob(str(REPO_DIR / pattern), recursive=True):
                path = Path(f)
                rel = str(path.relative_to(REPO_DIR))
                try:
                    h = hashlib.md5(path.read_bytes()).hexdigest()
                    new_hashes[rel] = h
                    old = self.file_hashes.get(rel)
                    if old and old != h:
                        self.conflicts.append(Conflict(
                            file_path=rel,
                            local_hash=old,
                            remote_hash=h,
                            detected_at=time.time(),
                        ))
                        logger.warning(f"Conflict detected: {rel} changed")
                except Exception:
                    logger.warning("Failed to hash file for conflict detection: %s", rel, exc_info=True)
        self.file_hashes = new_hashes

    # ── Task parsing from commit message ──────────────────────────

    def _parse_commit_tasks(self, msg: str) -> list[str]:
        tasks = []
        for prefix in ["H2.", "H3.", "H4."]:
            for word in msg.split():
                if word.startswith(prefix):
                    tasks.append(word.rstrip(":,"))
        if not tasks:
            if "fix" in msg.lower() or "bug" in msg.lower():
                tasks.append("bugfix")
            else:
                tasks.append("general")
        return tasks

    # ── State persistence ─────────────────────────────────────────

    def _save_state(self):
        data = {
            "last_checked_sha": self.last_checked_sha,
            "sessions": [asdict(s) for s in self.sessions],
            "file_hashes": self.file_hashes,
            "conflicts": [asdict(c) for c in self.conflicts],
        }
        try:
            SESSION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to save Oracle state: {e}")

    def _load_state(self):
        try:
            if SESSION_FILE.exists():
                data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
                self.last_checked_sha = data.get("last_checked_sha", "")
                self.sessions = [ClaudeSession(**s) for s in data.get("sessions", [])]
                self.file_hashes = data.get("file_hashes", {})
                self.conflicts = [Conflict(**c) for c in data.get("conflicts", [])]
                if self.sessions:
                    self.current_session = self.sessions[-1]
        except Exception as e:
            logger.warning(f"Failed to load Oracle state: {e}")
