"""Safe Ollama lifecycle control for Jarvis.

The controller owns only fixed local operations:

* ``ollama serve`` via argv and ``create_subprocess_exec`` (never a shell);
* load/pin through ``POST /api/generate`` with an empty prompt;
* unload through the same endpoint with ``keep_alive=0``.

It repeats the system-control permission and host-contract checks as defence in
depth.  The conversational entry point additionally performs identity, Action
Kernel and durable audit preflight immediately before calling this controller.
All I/O is injectable for hermetic tests.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urlparse

from ..automation_contracts import contract_denial
from ..autonomy.remediation import (
    HOST_CONTROL_CONTRACT,
    HOST_CONTROL_CONTRACT_KIND,
    ExecFn,
    ProbeFn,
    _default_exec,
    _default_probe,
)

logger = logging.getLogger("jarvis.llm.ollama_control")

_MODEL_RE = re.compile(r"^[A-Za-z0-9._/:@\-]{1,200}$")


class OllamaController:
    def __init__(
        self,
        *,
        ollama_bin: str = "ollama",
        server_url: str = "http://localhost:11434",
        router=None,
        permission_gate=None,
        enabled: bool = True,
        exec_fn: ExecFn | None = None,
        probe_fn: ProbeFn | None = None,
        client: Any = None,
        timeout: float = 60.0,
        verify_attempts: int = 8,
        verify_delay: float = 0.75,
    ) -> None:
        self.ollama_bin = ollama_bin
        self.server_url = server_url.rstrip("/")
        self.router = router
        self.permission_gate = permission_gate
        self.enabled = bool(enabled)
        self._exec_fn = exec_fn or _default_exec
        self._probe_fn = probe_fn or _default_probe
        self.timeout = timeout
        self.verify_attempts = verify_attempts
        self.verify_delay = verify_delay
        parsed = urlparse(self.server_url)
        self._host = parsed.hostname or "localhost"
        self._port = parsed.port or 11434
        self._owns_client = client is None
        self._client = client

    def set_enabled(self, value: bool) -> None:
        self.enabled = bool(value)

    async def status(self) -> dict:
        online = self._probe()
        models = await self._active_models() if online else []
        return {
            "online": online,
            "enabled": self.enabled,
            "server_url": self.server_url,
            "active_models": models,
        }

    async def start_server(self, agent: str = "jarvis") -> dict:
        if not self.enabled:
            return self._done("disabled", "start_server", reason="Ollama control is disabled")
        blocked = self._gate(agent, "start_server")
        if blocked:
            return blocked
        if self._probe():
            return self._done("ok", "start_server", already_running=True, online=True)
        blocked = self._contract_blocked("ollama.start", "start_server", agent=agent)
        if blocked:
            return blocked
        try:
            result = await self._exec_fn(
                [self.ollama_bin, "serve"], self.timeout, True
            )
        except Exception as exc:
            return self._done("failed", "start_server", reason=str(exc))
        recovered = await self._verify()
        return self._done(
            "ok" if recovered else "failed",
            "start_server",
            online=recovered,
            exit_code=result.exit_code,
            output=((result.stdout or result.stderr) or "")[:500],
        )

    async def load_model(self, model: str, agent: str = "jarvis") -> dict:
        if not self.enabled:
            return self._done("disabled", "load_model", model=model,
                              reason="Ollama control is disabled")
        blocked = self._gate(agent, "load_model")
        if blocked:
            return blocked
        if not _MODEL_RE.fullmatch(model or ""):
            return self._done("rejected", "load_model", model=model,
                              reason=f"invalid model id: {model!r}")
        blocked = self._contract_blocked(
            "ollama.load", "load_model", agent=agent, model=model
        )
        if blocked:
            return blocked
        if not self._probe():
            started = await self.start_server(agent=agent)
            if started.get("status") != "ok":
                return self._done(
                    "failed", "load_model", model=model,
                    reason="Ollama server not running and could not be started",
                )
        try:
            response = await self._http_client().post("/api/generate", json={
                "model": model,
                "prompt": "",
                "keep_alive": -1,
                "stream": False,
            })
            response.raise_for_status()
        except Exception as exc:
            return self._done("failed", "load_model", model=model, reason=str(exc))
        await self._refresh_router()
        return self._done("ok", "load_model", model=model)

    async def unload_model(
        self, model: str | None = None, agent: str = "jarvis"
    ) -> dict:
        if not self.enabled:
            return self._done("disabled", "unload_model", model=model,
                              reason="Ollama control is disabled")
        blocked = self._gate(agent, "unload_model")
        if blocked:
            return blocked
        if model and not _MODEL_RE.fullmatch(model):
            return self._done("rejected", "unload_model", model=model,
                              reason=f"invalid model id: {model!r}")
        blocked = self._contract_blocked(
            "ollama.unload", "unload_model", agent=agent, model=model or ""
        )
        if blocked:
            return blocked
        if not self._probe():
            return self._done("failed", "unload_model", model=model,
                              reason="Ollama server is not running")
        targets = [model] if model else await self._active_models()
        for target in targets:
            if not _MODEL_RE.fullmatch(target or ""):
                return self._done("rejected", "unload_model", model=target,
                                  reason=f"invalid active model id: {target!r}")
            try:
                response = await self._http_client().post("/api/generate", json={
                    "model": target,
                    "prompt": "",
                    "keep_alive": 0,
                    "stream": False,
                })
                response.raise_for_status()
            except Exception as exc:
                return self._done("failed", "unload_model", model=target, reason=str(exc))
        await self._refresh_router()
        return self._done("ok", "unload_model", model=model, unloaded=targets)

    async def aclose(self) -> None:
        if not self._owns_client:
            return
        closer = getattr(self._client, "aclose", None)
        if callable(closer):
            await closer()

    def _gate(self, agent: str, action: str) -> dict | None:
        if self.permission_gate is not None and not self.permission_gate.check_call(
            "system-control", agent
        ):
            return self._done(
                "blocked", action,
                reason=f"agent '{agent}' not permitted for system-control",
            )
        return None

    def _contract_blocked(
        self, contract_action: str, action: str, *, agent: str, model: str = ""
    ) -> dict | None:
        try:
            decision = HOST_CONTROL_CONTRACT.evaluate({
                "kind": HOST_CONTROL_CONTRACT_KIND,
                "action": contract_action,
                "agent": agent,
                "provider": "ollama",
                "model": model,
                "target": model or self.server_url,
                "server_url": self.server_url,
            })
        except Exception:
            logger.warning("Ollama host-control contract failed", exc_info=True)
            return self._done("blocked", action, reason="contract_error")
        reason = contract_denial(decision)
        if reason:
            return self._done("blocked", action, reason=reason)
        return None

    def _probe(self) -> bool:
        try:
            return bool(self._probe_fn(self._host, self._port))
        except Exception:
            logger.warning("Ollama probe failed", exc_info=True)
            return False

    async def _verify(self) -> bool:
        for _ in range(max(1, self.verify_attempts)):
            if self._probe():
                return True
            await asyncio.sleep(self.verify_delay)
        return False

    async def _active_models(self) -> list[str]:
        try:
            response = await self._http_client().get("/api/ps")
            response.raise_for_status()
            payload = response.json() or {}
            return [
                str(row.get("name") or row.get("model") or "").strip()
                for row in (payload.get("models") or [])
                if str(row.get("name") or row.get("model") or "").strip()
            ]
        except Exception:
            logger.warning("Ollama active-model listing failed", exc_info=True)
            return []

    def _http_client(self):
        """Create the pooled localhost client only when an HTTP operation needs it."""
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(
                base_url=self.server_url, timeout=self.timeout
            )
        return self._client

    async def _refresh_router(self) -> None:
        refresh = getattr(self.router, "detect", None)
        if callable(refresh):
            try:
                await refresh()
            except Exception:
                logger.warning("Ollama router refresh failed", exc_info=True)

    @staticmethod
    def _done(status: str, action: str, **extra) -> dict:
        return {"status": status, "action": action, "provider": "ollama", **extra}
