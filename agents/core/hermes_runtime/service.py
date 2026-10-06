"""Owner-only complete Hermes runtime; process secrets never leave this service."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from agents.core.app_state import get_orch
from agents.core.paths import data_path

from .bridge import AuthorizationBridge
from .client import HermesRPCClient, RuntimeUnavailable
from .distribution import load_pin
from .policy import HermesGate, RuntimeDenied, catalog, classify
from .process import RuntimeProcess


class HermesRuntimeService:
    def __init__(self, *, process=None, gate=None):
        self._process, self._client, self._bridge = process, None, None
        self._gate = gate or HermesGate(orchestrator=get_orch)
        self._lock = asyncio.Lock()

    @staticmethod
    def enabled():
        from agents.core.safe_mode import enabled as safe_mode_enabled

        return (not safe_mode_enabled()
                and os.environ.get("JARVIS_HERMES_ENABLED", "").lower() in {"1", "true", "yes", "on"})

    def catalog(self):
        return catalog()

    async def status(self):
        state = self._process.status() if self._process else {"ready": False, "generation": None, "pid": None}
        reason = ""
        if not self.enabled():
            reason = "Hermes runtime disabled; provision it and enable JARVIS_HERMES_ENABLED"
        elif not self._process and not Path(data_path("hermes-runtime", "runtime.json")).is_file():
            reason = "Provision Hermes first: python scripts/hermes_runtime.py install"
        return {"enabled": self.enabled(), "ready": state["ready"] and bool(self._client and self._client.connected),
                "generation": state["generation"], "pid": state["pid"], "source_sha": load_pin()["commit"],
                "reason": reason}

    def _configured_process(self):
        # Only the owner CLI writes this descriptor; HTTP cannot choose a source,
        # executable, origin, profile, command or bridge destination.
        descriptor = Path(data_path("hermes-runtime", "runtime.json"))
        if descriptor.is_symlink() or not descriptor.is_file():
            raise RuntimeUnavailable("Provision Hermes first: python scripts/hermes_runtime.py install")
        config = json.loads(descriptor.read_text())
        root = descriptor.parent.resolve()
        if Path(config["source"]).resolve() != root / "source" or Path(config["home"]).resolve() != root / "home":
            raise RuntimeUnavailable("Hermes runtime descriptor is invalid")
        return RuntimeProcess(root / "source", root / "home", Path(config["python"]))

    async def start(self):
        async with self._lock:
            if not self.enabled():
                raise RuntimeUnavailable("Hermes runtime is disabled")
            if self._client and self._client.connected:
                return await self.status()
            self._gate.authorize("control", "start", {}, "startup")
            if self._process is None:
                self._process = self._configured_process()
            if self._client:
                await self._client.close()
                self._client = None
            # A replacement bridge cannot authorize an old worker that still
            # holds its previous credential; restart that generation explicitly.
            await self._process.stop()
            if self._bridge:
                await asyncio.to_thread(self._bridge.stop)
            self._bridge = AuthorizationBridge(lambda f: self._gate.authorize(f["kind"], f["target"], f["args"], f["generation"]))
            self._bridge.start()
            try:
                internal = await self._process.start(bridge_url=self._bridge.url, bridge_token=self._bridge.token)
                self._bridge.generation = internal["generation"]
                self._client = HermesRPCClient(internal["url"], internal["token"], internal["generation"])
                await self._client.open()
            except Exception as exc:
                await self._process.stop()
                await asyncio.to_thread(self._bridge.stop)
                self._bridge = self._client = None
                raise RuntimeUnavailable("Hermes startup failed; inspect private worker logs") from exc
            return await self.status()

    async def stop(self):
        async with self._lock:
            if self._bridge:
                self._bridge.generation = None  # revoke before closing either transport
            if self._client:
                await self._client.close()
                self._client = None
            if self._process:
                await self._process.stop()
            if self._bridge:
                await asyncio.to_thread(self._bridge.stop)
                self._bridge = None
            return await self.status()

    def _require_client(self):
        if not self.enabled() or not self._client or not self._bridge or not self._process.status()["ready"]:
            raise RuntimeUnavailable()
        return self._client

    async def rpc(self, method: str, params: dict):
        client = self._require_client()
        classify("rpc", method)
        if not isinstance(params, dict) or len(json.dumps(params, allow_nan=False).encode()) > 1024 * 1024:
            raise RuntimeDenied("Hermes arguments exceed the request contract")
        # Final authorization is in the worker AFTER upstream parameter validation.
        # The service never runs Hermes's tools in Jarvis's own agent loop.
        return await client.rpc(method, params)

    async def reply(self, frame: dict):
        return await self._require_client().reply(frame)

    async def events(self):
        async for frame in self._require_client().events():
            yield frame


_SERVICE = None


def get_service():
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = HermesRuntimeService()
    return _SERVICE
