"""Owner-only complete Hermes runtime; process secrets never leave this service."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from agents.core.app_state import get_orch
from agents.core.env_config import env_flag
from agents.core.kernel import kernel_enabled
from agents.core.paths import data_path

from .approvals import HermesApprovals
from .bridge import AuthorizationBridge
from .client import HermesRPCClient, RuntimeUnavailable
from .distribution import load_pin
from .policy import HermesGate, RuntimeDenied, catalog, classify
from .process import RuntimeProcess


class HermesRuntimeService:
    def __init__(self, *, process=None, gate=None):
        self._process, self._client, self._bridge = process, None, None
        self._approvals = None
        self._loop = None
        self._gate = gate or HermesGate(orchestrator=get_orch)
        self._lock = asyncio.Lock()

    @staticmethod
    def enabled():
        from agents.core.safe_mode import enabled as safe_mode_enabled

        return not safe_mode_enabled() and env_flag("JARVIS_HERMES_ENABLED")

    def catalog(self):
        return catalog()

    def _live_approvals(self):
        approvals = self._approvals
        if approvals is None:
            return None
        try:
            live = bool(
                self.enabled() and self._process and self._process.status()["ready"]
                and self._client and self._client.connected and self._bridge
                and self._bridge.generation == approvals.generation
            )
        except Exception:
            live = False
        if not live:
            approvals.revoke()
            self._approvals = None
            if self._bridge:
                self._bridge.generation = None
            return None
        return approvals

    async def status(self):
        state = self._process.status() if self._process else {"ready": False, "generation": None, "pid": None}
        self._live_approvals()
        reason = ""
        try:
            approvals_ready = bool(
                self._approvals and not self._approvals._revoked
                and self._approvals.queue.mediation_mode == "enforce"
                and self._approvals.queue.verified_mediation_stats().get("valid") is True
                and kernel_enabled()
            )
        except Exception:
            approvals_ready = False
        if not self.enabled():
            reason = "Hermes runtime disabled; provision it and enable JARVIS_HERMES_ENABLED"
        elif not self._process and not Path(data_path("hermes-runtime", "runtime.json")).is_file():
            reason = "Provision Hermes first: python scripts/hermes_runtime.py install"
        elif state["ready"] and not approvals_ready:
            reason = "Privileged approvals require JARVIS_TASK_MEDIATION=enforce and JARVIS_ACTION_KERNEL=1"
        return {"enabled": self.enabled(), "ready": state["ready"] and bool(self._client and self._client.connected),
                "generation": state["generation"], "pid": state["pid"], "source_sha": load_pin()["commit"],
                "reason": reason, "approvals_ready": approvals_ready}

    def _configured_process(self):
        # Only the owner CLI writes this descriptor; HTTP cannot choose a source,
        # executable, origin, profile, command or bridge destination.
        descriptor = Path(data_path("hermes-runtime", "runtime.json"))
        if descriptor.is_symlink() or not descriptor.is_file():
            raise RuntimeUnavailable("Provision Hermes first: python scripts/hermes_runtime.py install")
        config = json.loads(descriptor.read_text(encoding="utf-8"))
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
            if self._approvals:
                self._approvals.revoke()
                self._approvals = None
            # A replacement bridge cannot authorize an old worker that still
            # holds its previous credential; restart that generation explicitly.
            await self._process.stop()
            if self._bridge:
                await asyncio.to_thread(self._bridge.stop)
            self._loop = asyncio.get_running_loop()
            self._bridge = AuthorizationBridge(self._bridge_authorize)
            self._bridge.start()
            try:
                internal = await self._process.start(bridge_url=self._bridge.url, bridge_token=self._bridge.token)
                self._bridge.generation = internal["generation"]
                self._client = HermesRPCClient(internal["url"], internal["token"], internal["generation"])
                await self._client.open()
                orch = get_orch()
                self._approvals = HermesApprovals(
                    worker=orch.autonomy, queue=orch.autonomy_queue, gate=self._gate,
                    generation=internal["generation"], client=self._client,
                )
            except Exception as exc:
                await self._process.stop()
                await asyncio.to_thread(self._bridge.stop)
                self._bridge = self._client = None
                raise RuntimeUnavailable("Hermes startup failed; inspect private worker logs") from exc
            return await self.status()

    async def stop(self):
        async with self._lock:
            if self._approvals:
                self._approvals.revoke()
                self._approvals = None
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

    def _bridge_authorize(self, frame):
        approvals = self._live_approvals()
        if approvals is None:
            # The worker can contact the bridge before client.open() completes.
            # Start control is authorized directly, but worker effects require
            # the canonical manager even when the bare Kernel would grant them.
            raise RuntimeDenied("Hermes generation revoked" if self._bridge is None
                                or self._bridge.generation is None
                                else "Hermes approval manager unavailable")
        if frame.get("phase") == "continue":
            return approvals.continue_tool(frame)
        if frame.get("phase") == "complete":
            return approvals.complete(frame)
        try:
            return approvals.authorize(frame)
        except RuntimeDenied as exc:
            if exc.verdict != "queue" or frame.get("request_id", "").startswith("hermes-approved-"):
                raise
            if self._loop is None:
                raise RuntimeDenied("Hermes approval loop unavailable") from exc
            future = asyncio.run_coroutine_threadsafe(approvals.submit(frame), self._loop)
            try:
                return future.result(timeout=10)
            except Exception as error:
                approvals.abort_submission(frame["nonce"])
                future.cancel()
                raise RuntimeDenied("Hermes canonical approval intake unavailable") from error

    async def approval_list(self):
        if not self.enabled():
            raise RuntimeUnavailable()
        orch = get_orch()
        queue = getattr(orch, "autonomy_queue", None)
        if queue is None:
            raise RuntimeUnavailable()
        approvals = self._live_approvals()
        if approvals:
            return approvals.list()
        from .approvals import public_task
        rows = [public_task(task, generation="") for task in queue.list(kind="hermes.runtime", limit=100)]
        return {"tasks": rows, "total": len(rows)}

    async def approval_decide(self, task_id: int, approved: bool):
        approvals = self._live_approvals()
        if not self.enabled() or approvals is None:
            raise RuntimeUnavailable()
        return await approvals.decide(task_id, approved)

    def _require_client(self):
        if (self._approvals is not None and self._live_approvals() is None
                or not self.enabled() or not self._client or not self._bridge
                or self._bridge.generation is None or not self._process.status()["ready"]):
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
