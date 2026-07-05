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
  - **Fuzzy load target** — a partial name ("load gemma") is resolved to the full
    servable id ("google/gemma-4-12b") via `/v1/models` before `lms load`, so the
    load hits an exact model instead of relying on LM Studio to guess. Best-effort:
    if the list is unavailable the literal name is used (unchanged); if several
    models match, the load stops and reports them (status "ambiguous").

After a model change it refreshes the live router so routing + the runtime
state agents report reflect the real loaded model immediately, no restart.

All I/O is injectable (exec_fn / probe_fn / models_fn) so the controller is
unit-tested offline without spawning processes or opening sockets.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Awaitable, Callable, Optional
from urllib.parse import urlparse

from ..automation_contracts import contract_denial
from ..autonomy.remediation import (
    HOST_CONTROL_CONTRACT,
    HOST_CONTROL_CONTRACT_KIND,
    ExecResult,
    _default_exec,
    _default_probe,
)

logger = logging.getLogger("jarvis.llm.lmstudio_control")

# A model identifier is a path-ish token: letters, digits and . _ - / : @
# (covers "google/gemma-4-12b", "deepseek-r1-distill-qwen-32b", quant suffixes).
_MODEL_RE = re.compile(r"^[A-Za-z0-9._/:@\-]{1,200}$")

ExecFn = Callable[[list[str], float, bool], Awaitable[ExecResult]]
ProbeFn = Callable[[str, int], bool]
ModelsFn = Callable[[], Awaitable[list[str]]]


def _clip(result: ExecResult) -> str:
    return ((result.stdout or result.stderr) or "")[:500]


async def _default_models(server_url: str, timeout: float) -> list[str]:
    """List the model ids LM Studio can serve, via the OpenAI-compatible
    ``GET /v1/models`` ({"data": [{"id": ...}]}). Best-effort: any failure
    (server down, bad payload) returns an empty list so resolution degrades to
    using the literal name the caller asked for."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{server_url}/v1/models")
            if resp.status_code != 200:
                return []
            data = resp.json() or {}
            return [m.get("id") for m in (data.get("data") or []) if m.get("id")]
    except Exception:
        return []


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
        models_fn: Optional[ModelsFn] = None,
        timeout: float = 60.0,
        resolve_timeout: float = 5.0,
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
        self._models_fn = models_fn
        self.timeout = timeout
        self.resolve_timeout = resolve_timeout
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
        blocked = self._contract_blocked("lmstudio.start", "start_server", agent=agent)
        if blocked:
            return blocked
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
        blocked = self._contract_blocked("lmstudio.load", "load_model", agent=agent, model=model)
        if blocked:
            return blocked
        if not self._probe():
            started = await self.start_server(agent=agent)
            if started.get("status") != "ok":
                return self._done("failed", "load_model", model=model,
                                  reason="LM Studio server not running and could not be started")
        # Resolve a partial name to the full servable id (the server is up by now,
        # so /v1/models is reachable). Best-effort: no list / no match → use the
        # literal name (unchanged); several matches → stop and report them.
        target, resolved_from = model, None
        resolved, candidates = self._resolve_model(model, await self._available_models())
        if resolved is None:
            return self._done("ambiguous", "load_model", model=model, candidates=candidates,
                              reason=f"{len(candidates)} models match {model!r}")
        if resolved != model:
            if not _MODEL_RE.match(resolved):  # defense in depth on the resolved id
                return self._done("rejected", "load_model", reason=f"invalid model id: {resolved!r}")
            target, resolved_from = resolved, model
        try:
            result = await self._exec_fn([self.lms_bin, "load", target, "-y"], self.timeout, False)
        except Exception as e:
            return self._done("failed", "load_model", model=target, reason=str(e))
        if result.ok:
            await self._refresh_router()
        extra = {"model": target, "exit_code": result.exit_code, "output": _clip(result)}
        if resolved_from is not None:
            extra["resolved_from"] = resolved_from
        return self._done("ok" if result.ok else "failed", "load_model", **extra)

    async def unload_model(self, model: Optional[str] = None, agent: str = "jarvis") -> dict:
        if not self.enabled:
            return self._done("disabled", "unload_model", model=model, reason="LM Studio control is disabled")
        blocked = self._gate(agent, "unload_model")
        if blocked:
            return blocked
        if model and not _MODEL_RE.match(model):
            return self._done("rejected", "unload_model", reason=f"invalid model id: {model!r}")
        blocked = self._contract_blocked("lmstudio.unload", "unload_model", agent=agent, model=model or "")
        if blocked:
            return blocked
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
    async def _available_models(self) -> list[str]:
        """Model ids LM Studio can serve, for load-target resolution. Never
        raises — a failure degrades to an empty list (→ literal passthrough)."""
        try:
            if self._models_fn is not None:
                return list(await self._models_fn())
            return await _default_models(self.server_url, self.resolve_timeout)
        except Exception:
            logger.warning("listing servable models failed", exc_info=True)
            return []

    @staticmethod
    def _resolve_model(query: str, available: list[str]) -> tuple[Optional[str], list[str]]:
        """Resolve a (possibly partial) model name against the servable list.

        Returns ``(resolved_id, candidates)``:
          - exact id present            → ``(query, [query])``
          - one case-insensitive match  → ``(match, [match])``
          - several matches             → ``(None, candidates)``  — ambiguous
          - empty list / no match       → ``(query, [])``  — literal passthrough

        A unique exact last-segment match (e.g. query ``"gemma-4-12b"`` against
        ``"google/gemma-4-12b"``) breaks an otherwise-ambiguous tie.
        """
        if not available:
            return query, []
        if query in available:
            return query, [query]
        q = query.lower()
        matches = [m for m in available if q in m.lower()]
        if len(matches) == 1:
            return matches[0], matches
        if len(matches) > 1:
            exact_seg = [m for m in matches if m.rsplit("/", 1)[-1].lower() == q]
            if len(exact_seg) == 1:
                return exact_seg[0], exact_seg
            return None, matches
        return query, []

    def _gate(self, agent: str, action: str) -> Optional[dict]:
        if self.permission_gate is not None and not self.permission_gate.check_call("system-control", agent):
            return self._done("blocked", action, reason=f"agent '{agent}' not permitted for system-control")
        return None

    def _contract_blocked(self, contract_action: str, action: str, *,
                          agent: str, model: str = "") -> Optional[dict]:
        try:
            decision = HOST_CONTROL_CONTRACT.evaluate({
                "kind": HOST_CONTROL_CONTRACT_KIND,
                "action": contract_action,
                "agent": agent,
                "model": model,
                "target": model or self.server_url,
                "server_url": self.server_url,
            })
        except Exception:
            logger.warning("host-control contract evaluation failed", exc_info=True)
            return self._done("blocked", action, reason="contract_error")
        reason = contract_denial(decision)
        if reason:
            return self._done("blocked", action, reason=reason)
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
