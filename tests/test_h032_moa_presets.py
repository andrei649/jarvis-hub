"""H032 — Mixture-of-Agents (MoA) committee presets & resilient hybrid runtime tests."""

from __future__ import annotations

import asyncio
import io
import json
import os
import stat
import time
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.cli.nerva import Context
from agents.cli.nerva import main as nerva_main
from agents.core.llm.base import LLMBackend
from agents.core.llm.data_handling import DataHandlingRefused
from agents.core.llm.hybrid_router import (
    HybridRouter,
    LocalBackendUnavailableError,
    ModelNotApprovedError,
)
from agents.core.llm.job_selection import SelectionError, selection_scope
from agents.core.llm.moa import (
    MoAConfigError,
    clear_recent_runs,
    delete_preset,
    get_active_preset_name,
    get_preset,
    list_presets,
    recent_runs,
    save_preset,
    set_active_preset,
    validate_preset,
)
from agents.core.routers import moa as moa_router_mod
from agents.core.routers._deps import admin_guard
from agents.core.routers.moa import router as moa_router


class FakeBackend(LLMBackend):
    def __init__(self, name: str, *, delay_s: float = 0.0, fail: bool = False, degraded: bool = False, window: int = 16384):
        self.name = name
        self.delay_s = delay_s
        self.fail = fail
        self.degraded = degraded
        self._window = window
        self.calls: list[tuple[str, str]] = []

    def context_window(self, model: str | None = None) -> int:
        return self._window

    async def is_available(self) -> bool:
        return True

    async def list_models(self) -> list[str]:
        return [f"{self.name}-model"]

    async def generate(
        self,
        model: str,
        prompt: str,
        system: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        **kwargs,
    ) -> str:
        self.calls.append((model, prompt))
        if self.delay_s > 0:
            await asyncio.sleep(self.delay_s)
        if self.fail:
            raise RuntimeError(f"{self.name} failed")
        if self.degraded:
            return "⚠️ I can't reach the local LM Studio model right now."
        if "## Candidate Responses" in prompt:
            return f"SYNTH[{model}]: verified ({prompt.count('### Candidate ')} candidates)"
        return f"DRAFT[{self.name}:{model}] for {prompt}"


def _make_router(*, local_delay: float = 0.0, cloud: bool = True, cloud_delay: float = 0.0) -> HybridRouter:
    r = HybridRouter()
    r._backend = FakeBackend("local", delay_s=local_delay, window=32768)
    r._backend_name = "lm-studio"
    r._local_available = True
    r._local_model = "qwen-fast"
    r._deep_model = "qwen-deep"
    r._ollama_backend = FakeBackend("ollama", delay_s=local_delay, window=16384)
    r._ollama_available = True
    if cloud:
        r._gemini_backend = FakeBackend("gemini", delay_s=cloud_delay, window=128000)
        r._cloud_available = True
        r._gemini_model = "gemini-2.5-flash"
    return r


@pytest.fixture(autouse=True)
def _isolated_moa_store(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.delenv("JARVIS_STRICT_LOCAL", raising=False)
    clear_recent_runs()
    yield
    clear_recent_runs()


def test_preset_validation_and_private_store_crud(tmp_path):
    # Recursive or malformed specs are rejected
    with pytest.raises(MoAConfigError, match="recursive"):
        validate_preset("bad", proposers=["local", "moa:other"], aggregator="local-deep")
    with pytest.raises(MoAConfigError, match="recursive"):
        validate_preset("bad", proposers=["local", "local-deep"], aggregator="moa:other")
    with pytest.raises(MoAConfigError, match="2 to 6"):
        validate_preset("solo", proposers=["local"], aggregator="local-deep")

    p = validate_preset(
        "council",
        proposers=["local", "local-deep", "ollama:llama3"],
        aggregator="local-deep",
        description="Local 3-way quorum",
        min_quorum=2,
        timeout_s=30.0,
    )
    assert p.model_id == "moa:council"
    assert p.is_pure_local is True
    save_preset(p)

    # Verify 0o600 file permissions on POSIX
    store_files = list(tmp_path.rglob("moa_presets.json"))
    assert len(store_files) == 1
    if os.name != "nt":
        mode = stat.S_IMODE(store_files[0].stat().st_mode)
        assert mode == 0o600

    assert [x.name for x in list_presets()] == ["council"]
    assert get_preset("moa:council") == p
    set_active_preset("council")
    assert get_active_preset_name() == "council"

    assert delete_preset("council") is True
    assert get_active_preset_name() is None
    assert list_presets() == []


@pytest.mark.asyncio
async def test_parallel_quorum_speedup_and_streaming():
    router = _make_router(local_delay=0.08, cloud=True, cloud_delay=0.08)
    save_preset(
        validate_preset(
            "fast-trio",
            proposers=["local", "local-deep", "ollama:qwen"],
            aggregator="local-deep",
            min_quorum=3,
            timeout_s=5.0,
        )
    )
    backend, model_id, route = router.resolve_moa_preset("jarvis", "moa:fast-trio")
    assert model_id == "moa:fast-trio"
    assert route == "local-moa"
    assert backend.context_window(model_id) == 16384

    t0 = time.perf_counter()
    out = await backend.generate(model_id, "Analyze Nerva latency")
    wall_s = time.perf_counter() - t0
    assert out == "SYNTH[qwen-deep]: verified (3 candidates)"
    # 3 x 80ms proposers in parallel + 1 x 80ms aggregator should finish well below sequential (320ms)
    assert wall_s < 0.28
    tel = backend.last_run_telemetry
    assert tel is not None
    assert tel["ok"] is True
    assert tel["succeeded"] == 3
    assert tel["parallel_speedup"] >= 1.7
    assert len(recent_runs()) == 1

    # Stream synthesis emits tokens via on_token and pings on_activity
    tokens: list[str] = []
    pings: list[int] = []
    streamed = await backend.generate_stream(
        model_id,
        "Stream check",
        on_token=lambda tok: tokens.append(tok),
        on_activity=lambda: pings.append(1),
    )
    assert streamed == "SYNTH[qwen-deep]: verified (3 candidates)"
    assert "".join(tokens) == streamed
    assert len(pings) >= 3


@pytest.mark.asyncio
async def test_quorum_resilience_tolerates_slow_or_failed_member_and_fails_below_quorum():
    router = _make_router()
    # Make ollama fail, while local + local-deep succeed -> 2/3 >= min_quorum=2
    router._ollama_backend = FakeBackend("ollama", fail=True)
    save_preset(
        validate_preset(
            "resilient",
            proposers=["local", "local-deep", "ollama:broken"],
            aggregator="local-deep",
            min_quorum=2,
            timeout_s=2.0,
        )
    )
    backend, model_id, _ = router.resolve_moa_preset("jarvis", "resilient")
    ans = await backend.generate(model_id, "Check quorum resilience")
    assert "2 candidates" in ans
    assert backend.last_run_telemetry["quorum_met"] is True

    # Now make local degraded as well -> only 0/3 succeed (< min_quorum=2) -> raises honestly
    router._backend = FakeBackend("local", degraded=True)
    router._moa_backend_cache.clear()
    backend2, _, _ = router.resolve_moa_preset("jarvis", "resilient")
    with pytest.raises(RuntimeError, match="quorum not met"):
        await backend2.generate(model_id, "Check quorum failure")
    assert backend2.last_run_telemetry["ok"] is False


@pytest.mark.asyncio
async def test_strict_local_approved_models_and_h513_consent_enforced_across_every_member(monkeypatch):
    router = _make_router(cloud=True)
    save_preset(
        validate_preset(
            "hybrid-council",
            proposers=["local", "gemini"],
            aggregator="local-deep",
            min_quorum=2,
        )
    )
    save_preset(
        validate_preset(
            "local-council",
            proposers=["local", "local-deep"],
            aggregator="local-deep",
            min_quorum=2,
        )
    )

    # 1. Strict-local specialist (`ultron`) refuses hybrid preset, allows pure-local preset
    with pytest.raises(LocalBackendUnavailableError, match="strict-local"):
        router.resolve_moa_preset("ultron", "hybrid-council")
    _, _, u_route = router.resolve_moa_preset("ultron", "local-council")
    assert u_route == "local-moa"

    # 2. Global active hybrid preset routes `jarvis` to hybrid-moa without breaking `ultron`!
    set_active_preset("hybrid-council")
    _, j_model, j_route = router.select_backend("jarvis", "hello")
    assert (j_model, j_route) == ("moa:hybrid-council", "hybrid-moa")
    _, u_model, u_fallback_route = router.select_backend("ultron", "status")
    assert (u_model, u_fallback_route) == ("qwen-fast", "local")

    # 3. JARVIS_STRICT_LOCAL=1 fails closed on hybrid preset even for `jarvis`, allows pure-local
    monkeypatch.setenv("JARVIS_STRICT_LOCAL", "1")
    with pytest.raises(LocalBackendUnavailableError):
        router.select_backend("jarvis", "hello")
    set_active_preset("local-council")
    _, j_local_model, j_local_route = router.select_backend("jarvis", "hello")
    assert (j_local_model, j_local_route) == ("moa:local-council", "local-moa")
    monkeypatch.delenv("JARVIS_STRICT_LOCAL", raising=False)
    set_active_preset(None)

    # 4. `approved_models` allowlist blocks unapproved member inside committee
    monkeypatch.setattr(router, "approved_models", lambda aid: ["qwen-fast", "qwen-deep"] if aid == "pinned" else [])
    with pytest.raises(ModelNotApprovedError):
        router.resolve_moa_preset("pinned", "hybrid-council")
    _, p_model, p_route = router.resolve_moa_preset("pinned", "local-council")
    assert (p_model, p_route) == ("moa:local-council", "local-moa")

    # 5. Job `selection_scope({"model": "moa:local-council"})` pins cleanly & rejects conflicting provider
    with selection_scope({"model": "moa:local-council"}):
        scoped, s_model, s_route = router.select_backend("jarvis", "scheduled check")
        assert (s_model, s_route) == ("moa:local-council", "local-moa")
        res = await scoped.generate(s_model, "scheduled check", max_tokens=512)
        assert "SYNTH[qwen-deep]" in res
    with (
        selection_scope({"model": "moa:local-council", "provider": "gemini"}),
        pytest.raises(SelectionError, match="omit provider"),
    ):
        router.select_backend("jarvis", "bad pin")

    # 6. H513 `check_data_handling`: unattended call on hybrid-council (unconsented Gemini proposer
    #    hidden behind a local aggregator!) MUST raise DataHandlingRefused!
    hb, hm, hr = router.resolve_moa_preset("jarvis", "hybrid-council")
    with pytest.raises(DataHandlingRefused):
        router.check_data_handling(hb, hm, hr, actual_use=True)


def test_http_routes_and_nerva_moa_cli_online_and_offline(monkeypatch):
    router = _make_router(cloud=False)
    fake_orch = SimpleNamespace(llm_router=router)
    from agents import web

    monkeypatch.setattr(web, "orch", fake_orch)
    test_app = FastAPI()
    test_app.include_router(moa_router)
    test_app.dependency_overrides[admin_guard] = lambda: None
    client = TestClient(test_app)

    # Offline CLI: set + list + activate + clear
    out = io.StringIO()
    err = io.StringIO()
    ctx = Context(environ=dict(os.environ), out=out, err=err)

    rc = nerva_main(
        ["moa", "set", "council", "--proposers", "local,local-deep", "--aggregator", "local-deep", "--offline"],
        context=ctx,
    )
    assert rc == 0
    assert "saved moa:council" in out.getvalue()

    # HTTP GET /api/llm/moa/presets sees the saved preset
    r = client.get("/api/llm/moa/presets")
    assert r.status_code == 200
    assert r.json()["presets"][0]["name"] == "council"

    # Online CLI via HubClient stub wired to TestClient
    class StubHubClient:
        def request(self, method: str, path: str, body: Any = None):
            resp = client.request(method, path, json=body) if body is not None else client.request(method, path)
            assert resp.status_code < 400, resp.text
            return resp.json()

    out2 = io.StringIO()
    ctx_online = Context(environ=dict(os.environ), out=out2, err=io.StringIO(), client_factory=lambda _e: StubHubClient())

    assert nerva_main(["moa", "activate", "council"], context=ctx_online) == 0
    assert get_active_preset_name() == "council"

    out3 = io.StringIO()
    ctx_run = Context(environ=dict(os.environ), out=out3, err=io.StringIO(), client_factory=lambda _e: StubHubClient())
    assert nerva_main(["moa", "run", "council", "Evaluate ZFS scrub schedule", "--json"], context=ctx_run) == 0
    payload = json.loads(out3.getvalue())
    assert payload["ok"] is True
    assert payload["route"] == "local-moa"
    assert "SYNTH[qwen-deep]" in payload["answer"]
    assert payload["telemetry"]["succeeded"] == 2

    assert nerva_main(["moa", "activate", "--clear"], context=ctx_online) == 0
    assert get_active_preset_name() is None
    assert nerva_main(["moa", "delete", "council"], context=ctx_online) == 0
    assert list_presets() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ["claude", "gemini"])
async def test_streaming_cloud_aggregator_accepts_real_adapter_signature(monkeypatch, adapter):
    from types import MethodType
    from unittest.mock import create_autospec

    from agents.core.llm.anthropic import ClaudeBackend
    from agents.core.llm.gemini import GeminiBackend

    router = _make_router()
    monkeypatch.setattr(router, "check_data_handling", lambda *a, **kw: None)
    adapter_class = ClaudeBackend if adapter == "claude" else GeminiBackend
    # Enforce the actual production signature, while replacing all transport work.
    async def transport_stub(_self, model, prompt, **kwargs):
        assert "## Candidate Responses" in prompt
        kwargs["on_token"]("synthesized")
        return "synthesized"

    stream = create_autospec(adapter_class.generate_stream, side_effect=transport_stub)
    aggregator = adapter_class.__new__(adapter_class)
    aggregator.generate_stream = MethodType(stream, aggregator)
    if adapter == "claude":
        router._claude_backend = aggregator
        router._claude_available = True
    else:
        router._gemini_backend = aggregator
    save_preset(validate_preset("cloud-stream", proposers=["local", "local-deep"], aggregator=adapter))
    backend, model, _ = router.resolve_moa_preset("jarvis", "cloud-stream")
    tokens, activity = [], []
    answer = await backend.generate_stream(model, "request", on_token=tokens.append,
                                          on_activity=lambda: activity.append(True))
    assert answer == "synthesized" and tokens == [answer]
    assert len(activity) == 2  # proposers still report activity
    assert stream.call_count == 1


@pytest.fixture
def moa_selection_pin(tmp_path, monkeypatch):
    from agents.core import managed_scope

    directory = tmp_path / "managed"
    directory.mkdir()
    monkeypatch.setenv("NERVA_MANAGED_DIR", str(directory))
    monkeypatch.delenv("JARVIS_MANAGED_DIR", raising=False)
    monkeypatch.setattr(managed_scope, "_TRUST_ANY_OWNER_FOR_TESTS", True)
    managed_scope.invalidate()
    yield directory
    managed_scope.invalidate()


@pytest.mark.asyncio
@pytest.mark.parametrize("writer", ["http", "offline"])
async def test_active_preset_edit_respects_selection_pin(moa_selection_pin, monkeypatch, writer):
    from agents.core import managed_scope

    original = validate_preset("pinned", proposers=["local", "local-deep"], aggregator="local")
    save_preset(original)
    set_active_preset("pinned")
    (moa_selection_pin / "config.yaml").write_text('llm:\n  compatible_model: admin-model\n')
    managed_scope.invalidate()
    if writer == "http":
        body = moa_router_mod.MoAPresetBody(proposers=["local", "local-deep"], aggregator="local-deep")
        with pytest.raises(managed_scope.ManagedRefused):
            await moa_router_mod.moa_put_preset("pinned", body)
    else:
        ctx = Context(environ=dict(os.environ), out=io.StringIO(), err=io.StringIO())
        rc = nerva_main(["moa", "set", "pinned", "--proposers", "local,local-deep",
                         "--aggregator", "local-deep", "--offline"], context=ctx)
        assert rc != 0
        assert "managed by your administrator" in ctx.err.getvalue()
    assert get_preset("pinned") == original
    assert get_active_preset_name() == "pinned"
    # A selection pin does not prohibit editing a dormant preset.
    save_preset(validate_preset("dormant", proposers=["local", "local-deep"], aggregator="local"))


def test_active_preset_edit_check_serializes_with_activation(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from agents.core import managed_scope

    original = validate_preset("locked", proposers=["local", "local-deep"], aggregator="local")
    changed = validate_preset("locked", proposers=["local", "local-deep"], aggregator="local-deep")
    save_preset(original)
    set_active_preset("locked")
    checking, release, activation_started, activation_finished = (Event() for _ in range(4))

    def selection_guard(*, selection):
        assert selection is True
        checking.set()
        assert release.wait(5)
        raise managed_scope.ManagedRefused("selection pinned")

    def deactivate():
        activation_started.set()
        set_active_preset(None)
        activation_finished.set()

    monkeypatch.setattr(managed_scope, "check_llm_write", selection_guard)
    with ThreadPoolExecutor(max_workers=2) as pool:
        edit = pool.submit(save_preset, changed)
        try:
            assert checking.wait(5)
            activation = pool.submit(deactivate)
            assert activation_started.wait(5)
            # An activation cannot invalidate the active-state decision mid-write.
            assert not activation_finished.wait(0.05)
        finally:
            release.set()
        with pytest.raises(managed_scope.ManagedRefused, match="selection pinned"):
            edit.result(timeout=5)
        activation.result(timeout=5)
    assert get_preset("locked") == original
    assert get_active_preset_name() is None


@pytest.mark.parametrize("home_variable", ["JARVIS_HOME", "NERVA_HOME", None])
def test_store_path_testing_isolation_honors_home_alias(tmp_path, monkeypatch, home_variable):
    from agents.core import env_config
    from agents.core.llm import moa

    monkeypatch.setattr(env_config, "_PINNED", {})
    monkeypatch.setattr(moa, "data_root", lambda: tmp_path)
    monkeypatch.setenv("JARVIS_TESTING", "1")
    monkeypatch.delenv("JARVIS_HOME", raising=False)
    monkeypatch.delenv("NERVA_HOME", raising=False)
    if home_variable:
        monkeypatch.setenv(home_variable, str(tmp_path))
    expected = "moa_presets.json" if home_variable else ".test_isolated_moa_presets.json"
    assert moa._store_path() == tmp_path / expected


@pytest.mark.parametrize("orch", [None, SimpleNamespace(), SimpleNamespace(llm_router=object())])
def test_run_unavailable_contract_and_body_validation(monkeypatch, orch):
    from agents import web

    monkeypatch.setattr(web, "orch", orch)
    app = FastAPI()
    app.include_router(moa_router)
    app.dependency_overrides[admin_guard] = lambda: None
    client = TestClient(app)
    response = client.post("/api/llm/moa/run", json={"preset": "council", "prompt": "hello"})
    assert response.status_code == 503
    assert response.json() == {"error": "router_unavailable", "detail": "LLM router is not initialized"}
    assert response.headers["cache-control"] == "no-cache, no-store, must-revalidate"
    # FastAPI validates the body before invoking the request-time component guard.
    assert client.post("/api/llm/moa/run", json={"preset": "council"}).status_code == 422
