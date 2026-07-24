"""`run_llm_control("status")` must report the model actually loaded now, not the
stale configured default (2026-07-24 QA finding: chat said `gemma` while `qwen`
was resident and the HUD badge correctly showed qwen)."""

import sys
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import llm_control


class _Ctrl:
    async def status(self):
        # The controller reflects router.active_model — the stale configured value.
        return {"online": True, "active_model": "gemma-STALE"}


async def test_status_reports_live_loaded_model_not_stale_configured():
    router = SimpleNamespace(name="lm-studio", active_model="gemma-STALE")

    async def _refresh():
        router.active_model = "qwen-LIVE"      # adopt the live model, as the real one does
        return "qwen-LIVE"
    router.refresh_active_model = _refresh

    orch = SimpleNamespace(lmstudio=_Ctrl(), llm_router=router)
    out = await llm_control.run_llm_control(orch, "status", None)
    assert "qwen-LIVE" in out
    assert "gemma-STALE" not in out


async def test_status_degrades_when_refresh_fails():
    async def _boom():
        raise RuntimeError("backend unreachable")
    router = SimpleNamespace(name="lm-studio", active_model="gemma-cached",
                             refresh_active_model=_boom)
    orch = SimpleNamespace(lmstudio=_Ctrl(), llm_router=router)
    out = await llm_control.run_llm_control(orch, "status", None)
    # falls back to the controller/router value instead of crashing
    assert "gemma-STALE" in out or "gemma-cached" in out


async def test_status_offline_backend_unchanged():
    class _Off:
        async def status(self):
            return {"online": False}
    orch = SimpleNamespace(lmstudio=_Off(),
                           llm_router=SimpleNamespace(name="lm-studio", active_model="x"))
    out = await llm_control.run_llm_control(orch, "status", None)
    assert "offline" in out.lower()
