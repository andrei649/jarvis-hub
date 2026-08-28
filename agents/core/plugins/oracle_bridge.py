"""
oracle_bridge.py — Pipeline Weaver: bridges Claude (GitHub) and OpenCode.

Monitors the GitHub repo for new commits from external agents (Claude),
auto-pulls and validates them, tracks session progress, detects parallel-work
conflicts, and exposes real-time status to the HUD and OpenCode CLI.
"""

import asyncio
import json
import logging
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from agents.core.automation_contracts import (
    ContractTemplate,
    contract_denial,
    field_present,
    one_of,
    predicate,
)
from agents.core.paths import data_path

from ..http_client import PluginHTTPClient

logger = logging.getLogger("jarvis.oracle")

REPO_DIR = Path(__file__).resolve().parent.parent.parent.parent
CONFLICT_DIR = data_path("oracle")
CONFLICT_DIR.mkdir(parents=True, exist_ok=True)
SESSION_FILE = CONFLICT_DIR / "sessions.json"
FILE_HASH_FILE = CONFLICT_DIR / "file_hashes.json"

GITHUB_API = "https://api.github.com/repos/andrei649/jarvis-hub"

# H34.3 — dev-swarm PR/CI feed: bounded so a 30s watcher tick never turns into
# an unbounded fan-out of GitHub API calls.
PR_FEED_CAP = 10
PR_FEED_INTERVAL_S = 120


def _sha_safe(view, now) -> bool:
    sha = str(view.get("sha") or "")
    return len(sha) in (40, 64) and all(c in "0123456789abcdefABCDEF" for c in sha)


def _trigger_verified(view, now) -> bool:
    return view.get("trigger_verified") is True


def _repo_sync_contract_template() -> ContractTemplate:
    return ContractTemplate(
        kind="repo.sync",
        description="External-triggered repository sync and test execution.",
        constraints=(
            field_present("action", "agent", "sha", "author_login"),
            one_of("action", {"pull_test"}),
            predicate("sha_safe", _sha_safe, reason="invalid_sha"),
            predicate("trigger_verified", _trigger_verified, reason="unverified_trigger"),
        ),
    )


REPO_SYNC_CONTRACT = _repo_sync_contract_template()


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
    def __init__(
        self,
        github_token: str = "",
        *,
        kernel=None,
        enqueue=None,
        owner_logins: Optional[set[str]] = None,
    ):
        self.github_token = github_token
        self._kernel = kernel
        self._enqueue = enqueue
        owners = {"andrei649"} if owner_logins is None else owner_logins
        self.owner_logins = {str(v).lower() for v in owners}
        self.last_checked_sha: str = ""
        self.sessions: list[ClaudeSession] = []
        self.current_session: Optional[ClaudeSession] = None
        self.file_hashes: dict[str, str] = {}
        self.conflicts: list[Conflict] = []
        self._watcher_task: Optional[asyncio.Task] = None
        self._running = False
        self._client = PluginHTTPClient.for_plugin("oracle-bridge")
        self.pr_feed: dict = {
            "available": False, "prs": [], "checked_at": 0.0, "capped": False, "error": None,
        }
        self._pr_feed_checked_at: float = 0.0
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
            "pr_feed": dict(self.pr_feed),
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
        result = await self._check_github()
        await self._refresh_pr_feed(force=True)
        return result

    async def check_conflicts(self) -> list[dict]:
        await asyncio.to_thread(self._scan_file_hashes)
        result = [asdict(c) for c in self.conflicts if not c.resolved]
        return result

    # ── GitHub monitoring ─────────────────────────────────────────

    async def _watcher_loop(self):
        while self._running:
            try:
                await self._check_github()
            except Exception as e:
                logger.warning(f"Oracle watcher error: {e}")
            try:
                await self._refresh_pr_feed()
            except Exception as e:
                logger.warning(f"Oracle PR feed refresh error: {e}")
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
        verified = bool(((data[0].get("commit") or {}).get("verification") or {}).get("verified"))

        if sha == self.last_checked_sha:
            return {"ok": True, "new": False, "sha": sha[:8]}

        self.last_checked_sha = sha

        if not self._is_owner_commit(author_name, verified):
            result = await self._process_claude_commit(
                sha,
                msg,
                author_login=author_name,
                trigger_verified=verified,
            )
            return {"ok": True, "new": True, "sha": sha[:8], "author": author_name, **result}

        return {"ok": True, "new": True, "sha": sha[:8], "author": author_name, "note": "own commit, skipped"}

    def _is_owner_commit(self, author_login: str, verified: bool) -> bool:
        return bool(verified and str(author_login or "").lower() in self.owner_logins)

    # ── Dev-swarm PR/CI feed (H34.3) ────────────────────────────────

    async def _refresh_pr_feed(self, *, force: bool = False) -> dict:
        """Bounded, read-only open-PR + check-run summary, next to the lock panel.

        Gated on an explicit ``github_token``: an unauthenticated GitHub API call
        is capped at 60/hr, far below what listing PRs plus one check-run call
        per PR needs every refresh, so without a token this reports an honest
        disabled state instead of silently rate-limiting itself. Refreshed at
        most once per ``PR_FEED_INTERVAL_S`` unless ``force`` is set (the
        30s watcher tick and the admin-triggered sync both call this; the
        cadence only throttles the watcher's own calls).
        """
        if not self.github_token:
            self.pr_feed = {
                "available": False, "prs": [], "checked_at": time.time(),
                "capped": False, "error": "no_github_token",
            }
            return self.pr_feed

        now = time.time()
        if not force and (now - self._pr_feed_checked_at) < PR_FEED_INTERVAL_S:
            return self.pr_feed
        self._pr_feed_checked_at = now

        headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"token {self.github_token}",
        }
        try:
            resp = await self._client.get(
                f"{GITHUB_API}/pulls",
                headers=headers,
                params={
                    "state": "open", "sort": "updated", "direction": "desc",
                    "per_page": PR_FEED_CAP,
                },
            )
            if resp.status_code != 200:
                self.pr_feed = {
                    "available": False, "prs": [], "checked_at": now,
                    "capped": False, "error": f"github_api_{resp.status_code}",
                }
                return self.pr_feed
            pulls = resp.json() or []
            capped = 'rel="next"' in (resp.headers.get("Link") or "")
        except Exception as e:
            self.pr_feed = {
                "available": False, "prs": [], "checked_at": now,
                "capped": False, "error": str(e),
            }
            return self.pr_feed

        prs = []
        for pr in pulls[:PR_FEED_CAP]:
            head = pr.get("head") or {}
            checks = await self._pr_check_summary(str(head.get("sha") or ""), headers)
            prs.append({
                "number": pr.get("number"),
                "title": str(pr.get("title") or "")[:120],
                "author": (pr.get("user") or {}).get("login") or "unknown",
                "url": pr.get("html_url") or "",
                "draft": bool(pr.get("draft")),
                "branch": head.get("ref") or "",
                "updated_at": pr.get("updated_at") or "",
                "checks": checks,
            })

        self.pr_feed = {
            "available": True, "prs": prs, "checked_at": now,
            "capped": capped, "error": None,
        }
        return self.pr_feed

    async def _pr_check_summary(self, sha: str, headers: dict) -> dict:
        """One PR's check-run tally. Never raises — a broken/rate-limited call
        degrades to an honest empty summary rather than dropping the whole feed."""
        empty = {"total": 0, "passed": 0, "failed": 0, "pending": 0, "state": "none"}
        if not sha:
            return empty
        try:
            resp = await self._client.get(f"{GITHUB_API}/commits/{sha}/check-runs", headers=headers)
            if resp.status_code != 200:
                return empty
            data = resp.json() or {}
        except Exception:
            return empty

        runs = data.get("check_runs") or []
        passed = failed = pending = 0
        for run in runs:
            if not isinstance(run, dict):
                continue
            if run.get("status") != "completed":
                pending += 1
            elif run.get("conclusion") in ("failure", "timed_out", "action_required", "cancelled"):
                failed += 1
            else:  # success / neutral / skipped / stale — not a breach
                passed += 1
        total = len(runs)
        state = "failure" if failed else ("pending" if pending else ("success" if total else "none"))
        return {"total": total, "passed": passed, "failed": failed, "pending": pending, "state": state}

    async def _process_claude_commit(
        self,
        sha: str,
        msg: str,
        *,
        author_login: str = "unknown",
        trigger_verified: bool = False,
    ) -> dict:
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

        blocked = self._repo_sync_block(
            sha=sha,
            msg=msg,
            author_login=author_login,
            trigger_verified=trigger_verified,
        )
        if blocked is not None:
            session.status = "failed"
            session.error = f"repo sync blocked: {blocked.get('reason', 'blocked')}"
            session.completed_at = time.time()
            self._save_state()
            return {"pull": False, **blocked}

        # git pull (≤30s) and pytest (≤120s) are blocking subprocesses and the
        # hash scan walks the whole repo — run them off the event loop so a
        # commit or the /sync route can't freeze every channel/SSE stream.
        pull_ok, pull_err = await asyncio.to_thread(self._git_pull)
        if not pull_ok:
            session.status = "failed"
            session.error = f"git pull failed: {pull_err}"
            self._save_state()
            return {"pull": False, "error": pull_err}

        session.tasks_completed = self._parse_commit_tasks(msg)

        await asyncio.to_thread(self._scan_file_hashes)

        passed, total, failed, test_err = await asyncio.to_thread(self._run_tests)
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

    def _repo_sync_block(
        self,
        *,
        sha: str,
        msg: str,
        author_login: str,
        trigger_verified: bool,
    ) -> dict | None:
        payload = {
            "kind": "repo.sync",
            "action": "pull_test",
            "agent": "oracle",
            "sha": sha,
            "author_login": author_login,
            "trigger_verified": bool(trigger_verified),
            "message": (msg or "")[:240],
            "risk_tier": 3,
        }
        try:
            decision = REPO_SYNC_CONTRACT.evaluate(payload)
        except Exception:
            logger.warning("repo-sync contract evaluation failed", exc_info=True)
            return {"blocked": True, "reason": "contract_error"}
        reason = contract_denial(decision)
        if reason:
            return {"blocked": True, "reason": reason}

        from agents.core.kernel import Action, Verdict, kernel_enabled

        if not kernel_enabled():
            return {"blocked": True, "reason": "kernel_required"}
        if self._kernel is None:
            return {"blocked": True, "reason": "kernel_unavailable"}

        kdec = self._kernel(Action(
            kind="repo.sync",
            agent="oracle",
            title="Review external repo sync",
            payload=payload,
            origin="external",
        ))
        if kdec.verdict is Verdict.DENY:
            return {"blocked": True, "reason": kdec.reason or "kernel_denied"}
        if kdec.verdict is Verdict.QUEUE:
            out = {"blocked": True, "reason": "approval_required"}
            if self._enqueue is not None:
                try:
                    task_id = self._enqueue(
                        "oracle",
                        "repo.sync",
                        "Review external repo sync",
                        payload=payload,
                        risk_tier=3,
                        autonomy_level="ask",
                        origin="external",
                    )
                    out["task_id"] = task_id
                except Exception:
                    logger.warning("repo-sync enqueue failed", exc_info=True)
                    out["reason"] = "enqueue_failed"
            return out
        return None

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
            # Parse pytest's summary line (e.g. "= 2 failed, 3 passed in 0.1s =")
            # directly with regexes over the whole output; the old heuristic
            # required a line with both words and no "=", which the real summary
            # (always "=…="'d) never matched, so counts were fabricated.
            m_passed = re.search(r"(\d+) passed", out)
            m_failed = re.search(r"(\d+) failed", out)
            passed = int(m_passed.group(1)) if m_passed else 0
            failed = int(m_failed.group(1)) if m_failed else 0
            total = passed + failed
            error = result.stderr.strip() if result.returncode != 0 else ""
            return passed, total, failed, error
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
                    # Content fingerprint for change-detection only (not security);
                    # usedforsecurity=False keeps it FIPS-safe and silences B324.
                    h = hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()
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
        # Bound the append-only history: sessions and conflicts otherwise grow
        # forever (rewritten in full on every 30s tick), so cap sessions to the
        # most recent 50 and drop resolved conflicts before persisting.
        self.sessions = self.sessions[-50:]
        self.conflicts = [c for c in self.conflicts if not c.resolved]
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
