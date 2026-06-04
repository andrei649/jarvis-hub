"""
lmstudio_control.py — start the LM Studio server and load/unload models.

Jarvis connects to a *running* LM Studio (OpenAI-compatible API on :1234) and
auto-detects the loaded model; it does not, by itself, start LM Studio. This
module adds that control via the `lms` CLI — the same commands documented in
JARVIS.md and run by hand: `lms server start`, `lms load <model>`,
`lms unload`. It deliberately mirrors autonomy/remediation.py's safety posture:

  - **No shell** — commands run via argv (`create_subprocess_exec`), never a
    shell string, so a model name cannot inject.
  - **Fixed verb set** — only `server start`, `load`, `unload` are ever run;
    the only variable is a validated model identifier.
  - **Bounded + probed** — every action has a timeout and a port recovery probe
    so success is judged by the server actually coming up, not just an exit code.

After a model change it refreshes the live router so routing + the runtime
state agents report reflect the real loaded model immediately, no restart.

All I/O is injectable (exec_fn / probe_fn) so the controller is unit-tested
offline without spawning processes or opening sockets.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Awaitable, Callable, Optional
from urllib.parse import urlparse

from ..autonomy.remediation import ExecResult, _default_exec, _default_probe

logger = logging.getLogger("jarvis.llm.lmstudio_control")

# A model identifier is a path-ish token: letters, digits and . _ - / : @
# (covers "google/gemma-4-12b", "deepseek-r1-distill-qwen-32b", quant suffixes).
_MODEL_RE = re.compile(r"^[A-Za-z0-9._/:@\-]{1,200}$")

ExecFn = Callable[[list[str], float, bool], Awaitable[ExecResult]]
ProbeFn = Callable[[str, int], bool]


def _clip(result: ExecResult) -> str:
    return ((result.stdout or result.stderr) or "")[:500]


class LMStudioController:
    def __init__(
        self,
        *,
        lms_bin: str = "lms",
        server_url: str = "http://localhost:1234",
        router=None,
        permission_gate=None,
        enabled: bool = True,
        exec_fn: Optional[ExecFn] = None,
        probe_fn: Optional[ProbeFn] = None,
        timeout: float = 60.0,
        verify_attempts: int = 8,
        verify_delay: float = 0.75,
    ):
        self.lms_bin = lms_bin
        self.server_url = server_url.rstrip("/")
        self.router = router
        self.permission_gate = permission_gate
        # Master kill-switch. When False, every *mutating* action (start / load /
        # unload) is a no-op that returns status "disabled" without touching the
        # host — read-only status() still works. Flipped live from settings (see
        # Orchestrator._control_master_enabled) or hard-off via env at boot.
        self.enabled = enabled
        self._exec_fn = exec_fn or _default_exec
        self._probe_fn = probe_fn or _default_probe
        self.timeout = timeout
        self.verify_attempts = verify_attempts
        self.verify_delay = verify_delay
        parsed = urlparse(self.server_url)
        self._host = parsed.hostname or "localhost"
        self._port = parsed.port or 1234

    # ── public API ────────────────────────────────────────────────
    def set_enabled(self, value: bool) -> None:
        """Flip the master kill-switch at runtime (driven by settings sync)."""
        value = bool(value)
        if value != self.enabled:
            logger.info("lmstudio_control %s", "enabled" if value else "disabled")
        self.enabled = value

    async def status(self) -> dict:
        online = self._probe()
        model = getattr(self.router, "active_model", None) if (online and self.router) else None
        return {"online": online, "enabled": self.enabled,
                "server_url": self.server_url, "active_model": model}

    async def start_server(self, agent: str = "jarvis") -> dict:
        if not self.enabled:
            return self._done("disabled", "start_server", reason="LM Studio control is disabled")
        blocked = self._gate(agent, "start_server")
        if blocked:
            return blocked
        if self._probe():
            return self._done("ok", "start_server", already_running=True, online=True)
        try:
            result = await self._exec_fn([self.lms_bin, "server", "start"], self.timeout, False)
        except Exception as e:  # never let host control raise into the caller
            return self._done("failed", "start_server", reason=str(e))
        recovered = await self._verify()
        return self._done("ok" if recovered else "failed", "start_server",
                          online=recovered, output=_clip(result))

    async def load_model(self, model: str, agent: str = "jarvis") -> dict:
        if not self.enabled:
            return self._done("disabled", "load_model", model=model, reason="LM Studio control is disabled")
        blocked = self._gate(agent, "load_model")
        if blocked:
            return blocked
        if not _MODEL_RE.match(model or ""):
            return self._done("rejected", "load_model", reason=f"invalid model id: {model!r}")
        if not self._probe():
            started = await self.start_server(agent=agent)
            if started.get("status") != "ok":
                return self._done("failed", "load_model", model=model,
                                  reason="LM Studio server not running and could not be started")
        try:
            result = await self._exec_fn([self.lms_bin, "load", model, "-y"], self.timeout, False)
        except Exception as e:
            return self._done("failed", "load_model", model=model, reason=str(e))
        if result.ok:
            await self._refresh_router()
        return self._done("ok" if result.ok else "failed", "load_model",
                          model=model, exit_code=result.exit_code, output=_clip(result))

    async def unload_model(self, model: Optional[str] = None, agent: str = "jarvis") -> dict:
        if not self.enabled:
            return self._done("disabled", "unload_model", model=model, reason="LM Studio control is disabled")
        blocked = self._gate(agent, "unload_model")
        if blocked:
            return blocked
        if model and not _MODEL_RE.match(model):
            return self._done("rejected", "unload_model", reason=f"invalid model id: {model!r}")
        argv = [self.lms_bin, "unload", model] if model else [self.lms_bin, "unload", "--all"]
        try:
            result = await self._exec_fn(argv, self.timeout, False)
        except Exception as e:
            return self._done("failed", "unload_model", model=model, reason=str(e))
        if result.ok:
            await self._refresh_router()
        return self._done("ok" if result.ok else "failed", "unload_model",
                          model=model, exit_code=result.exit_code, output=_clip(result))

    # ── helpers ───────────────────────────────────────────────────
    def _gate(self, agent: str, action: str) -> Optional[dict]:
        if self.permission_gate is not None and not self.permission_gate.check_call("system-control", agent):
            return self._done("blocked", action, reason=f"agent '{agent}' not permitted for system-control")
        return None

    def _probe(self) -> bool:
        try:
            return bool(self._probe_fn(self._host, self._port))
        except Exception:
            logger.warning("LM Studio probe failed for %s:%s", self._host, self._port, exc_info=True)
            return False

    async def _verify(self) -> bool:
        for _ in range(max(1, self.verify_attempts)):
            if self._probe():
                return True
            await asyncio.sleep(self.verify_delay)
        return False

    async def _refresh_router(self) -> None:
        refresh = getattr(self.router, "refresh_active_model", None)
        if refresh is None:
            return
        try:
            await refresh()
        except Exception:
            logger.warning("router refresh after model change failed", exc_info=True)

    def _done(self, status: str, action: str, **extra) -> dict:
        result = {"status": status, "action": action, "kind": "lmstudio_control", **extra}
        log = logger.info if status in ("ok", "disabled") else logger.warning
        log(f"lmstudio_control {action}: {status} ({extra.get('reason', '')})".rstrip())
        return result
