"""Tests for natural-language LLM-backend control detection + execution."""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core import llm_control as llm_control_module
from core.kernel import Decision, Verdict
from core.orchestrator import Orchestrator, detect_llm_control


# ── detector: positives ──────────────────────────────────────────

def test_detect_status_what_model_running():
    assert detect_llm_control("what model are you running?") == ("status", None)


def test_detect_status_which_llm():
    assert detect_llm_control("which LLM is this?") == ("status", None)


def test_detect_status_romanian():
    assert detect_llm_control("ce model folosești acum?") == ("status", None)


def test_detect_status_model_loaded():
    assert detect_llm_control("what model is loaded?") == ("status", None)


def test_detect_start_lmstudio():
    assert detect_llm_control("start LM Studio") == ("start", None)


def test_detect_start_romanian():
    assert detect_llm_control("pornește LM Studio te rog") == ("start", None)


def test_detect_start_llm_server():
    assert detect_llm_control("can you start the llm server") == ("start", None)


def test_detect_load_full_id():
    assert detect_llm_control("load google/gemma-4-12b") == ("load", "google/gemma-4-12b")


def test_detect_load_family_name():
    assert detect_llm_control("load gemma") == ("load", "gemma")


def test_detect_switch_to_model():
    assert detect_llm_control("switch to deepseek-r1-distill-qwen-32b") == (
        "load", "deepseek-r1-distill-qwen-32b")


def test_detect_load_romanian():
    assert detect_llm_control("încarcă modelul qwen2.5") == ("load", "qwen2.5")


def test_detect_unload_named():
    assert detect_llm_control("unload gemma") == ("unload", "gemma")


def test_detect_unload_generic():
    assert detect_llm_control("unload the model") == ("unload", None)


# ── detector: explicit "llm ..." command form ────────────────────

def test_detect_explicit_status():
    assert detect_llm_control("llm status") == ("status", None)


def test_detect_explicit_start():
    assert detect_llm_control("llm start") == ("start", None)


def test_detect_explicit_load():
    assert detect_llm_control("llm load google/gemma-4-12b") == ("load", "google/gemma-4-12b")


def test_detect_explicit_unload():
    assert detect_llm_control("llm unload") == ("unload", None)


def test_detect_lmstudio_prefix():
    assert detect_llm_control("lm studio status") == ("status", None)


# ── detector: negatives (must NOT trigger) ───────────────────────

def test_negative_load_up_friends():
    # the exact phrase from the reviewed chat — must not load a model
    assert detect_llm_control("can you load up our friends and test them?") is None


def test_negative_business_model():
    assert detect_llm_control("what's our business model for Q3?") is None


def test_negative_download():
    assert detect_llm_control("download the latest report") is None


def test_negative_reload_page():
    assert detect_llm_control("reload the page please") is None


def test_negative_start_the_car():
    assert detect_llm_control("start the car") is None


def test_negative_plain_chat():
    assert detect_llm_control("what time is it in Bucharest?") is None


def test_negative_empty():
    assert detect_llm_control("") is None


def test_negative_lmstudio_commentary():
    assert detect_llm_control("lm studio is great software") is None


# ── executor: _run_llm_control narrates the real result ──────────

class _FakeCtrl:
    def __init__(self, status_online=True):
        self.calls = []
        self._online = status_online

    async def status(self):
        return {"online": self._online,
                "active_model": "google/gemma-4-12b" if self._online else None}

    async def start_server(self, agent="jarvis"):
        self.calls.append("start")
        return {"status": "ok"}

    async def load_model(self, model, agent="jarvis"):
        self.calls.append(("load", model))
        return {"status": "ok"}

    async def unload_model(self, model=None, agent="jarvis"):
        self.calls.append(("unload", model))
        return {"status": "ok"}


class _FakeRouter:
    name = "lm-studio"
    active_model = "google/gemma-4-12b"


def _orch(online=True):
    o = Orchestrator.__new__(Orchestrator)
    o.lmstudio = _FakeCtrl(status_online=online)
    o.llm_router = _FakeRouter()
    o.permission_gate = type("_Gate", (), {
        "check_call": lambda self, plugin, agent: (
            plugin == "system-control" and agent == "jarvis"
        )
    })()
    o.audit = type("_Audit", (), {"log": lambda self, event: None})()
    return o


def _enable_governance(monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setattr(
        llm_control_module,
        "make_action_kernel",
        lambda _orch: lambda _action: Decision(Verdict.GRANT, reason="test", tier=1),
    )


async def test_run_status_reports_real_model():
    r = await _orch()._run_llm_control("status", None)
    assert "google/gemma-4-12b" in r and "lm-studio" in r


async def test_run_status_offline():
    r = await _orch(online=False)._run_llm_control("status", None)
    assert "offline" in r.lower()


async def test_run_start(monkeypatch):
    _enable_governance(monkeypatch)
    o = _orch()
    r = await o._run_llm_control("start", None)
    assert "up" in r.lower() and "start" in o.lmstudio.calls


async def test_run_load_invokes_controller(monkeypatch):
    _enable_governance(monkeypatch)
    o = _orch()
    r = await o._run_llm_control("load", "google/gemma-4-12b")
    assert "Loaded" in r and ("load", "google/gemma-4-12b") in o.lmstudio.calls


async def test_run_load_missing_model_asks():
    r = await _orch()._run_llm_control("load", None)
    assert "Which model" in r


async def test_run_load_narrates_resolved_id(monkeypatch):
    _enable_governance(monkeypatch)
    o = _orch()

    async def _load(model, agent="jarvis"):
        return {"status": "ok", "model": "google/gemma-4-12b", "resolved_from": model}
    o.lmstudio.load_model = _load
    o.llm_router.active_model = None  # force narration to use the controller result
    r = await o._run_llm_control("load", "gemma")
    assert "gemma" in r and "google/gemma-4-12b" in r


async def test_run_load_ambiguous_asks_to_pick(monkeypatch):
    _enable_governance(monkeypatch)
    o = _orch()

    async def _load(model, agent="jarvis"):
        return {"status": "ambiguous",
                "candidates": ["google/gemma-4-12b", "google/gemma-2-9b"]}
    o.lmstudio.load_model = _load
    r = await o._run_llm_control("load", "gemma")
    assert "match" in r.lower() and "gemma-2-9b" in r and "Which one" in r


async def test_run_unload_all(monkeypatch):
    _enable_governance(monkeypatch)
    o = _orch()
    r = await o._run_llm_control("unload", None)
    assert "All models" in r and ("unload", None) in o.lmstudio.calls


# ── kill-switch: master + chat gates ─────────────────────────────

def test_chat_control_enabled_by_default(monkeypatch):
    monkeypatch.delenv("JARVIS_LMSTUDIO_CONTROL", raising=False)
    monkeypatch.delenv("JARVIS_LMSTUDIO_CHAT_CONTROL", raising=False)
    o = _orch()
    o._runtime_settings = {}
    assert o._control_master_enabled() is True
    assert o._chat_control_enabled() is True


def test_master_env_off_disables_everything(monkeypatch):
    monkeypatch.setenv("JARVIS_LMSTUDIO_CONTROL", "0")
    o = _orch()
    o._runtime_settings = {}
    assert o._control_master_enabled() is False
    assert o._chat_control_enabled() is False


def test_live_setting_off_disables_master(monkeypatch):
    monkeypatch.delenv("JARVIS_LMSTUDIO_CONTROL", raising=False)
    o = _orch()
    o._runtime_settings = {"llm.control_enabled": "false"}
    assert o._control_master_enabled() is False


def test_chat_setting_off_keeps_master_on(monkeypatch):
    monkeypatch.delenv("JARVIS_LMSTUDIO_CONTROL", raising=False)
    monkeypatch.delenv("JARVIS_LMSTUDIO_CHAT_CONTROL", raising=False)
    o = _orch()
    o._runtime_settings = {"llm.chat_control": False}
    # ambient chat detection muted, but the master (admin buttons) stays live
    assert o._control_master_enabled() is True
    assert o._chat_control_enabled() is False


async def test_disabled_controller_is_a_noop():
    from core.llm.lmstudio_control import LMStudioController

    calls = []

    async def exec_fn(argv, timeout, shell):
        calls.append(argv)
        raise AssertionError("exec must not run while disabled")

    ctrl = LMStudioController(enabled=False, exec_fn=exec_fn, probe_fn=lambda h, p: True)
    for res in (await ctrl.start_server(),
                await ctrl.load_model("google/gemma-4-12b"),
                await ctrl.unload_model()):
        assert res["status"] == "disabled"
    assert calls == []
    # read-only status still reports, and exposes the switch state
    st = await ctrl.status()
    assert st["enabled"] is False


async def test_set_enabled_toggles_live():
    from core.llm.lmstudio_control import LMStudioController

    ran = []

    async def exec_fn(argv, timeout, shell):
        ran.append(argv)
        return _ExecOK()

    ctrl = LMStudioController(enabled=False, exec_fn=exec_fn, probe_fn=lambda h, p: True)
    assert (await ctrl.start_server())["status"] == "disabled"
    ctrl.set_enabled(True)
    assert (await ctrl.start_server())["status"] == "ok"  # already running (probe True)


class _ExecOK:
    ok = True
    exit_code = 0
    stdout = "ok"
    stderr = ""
