"""Tests for natural-language LLM-backend control detection + execution."""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

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

    async def start_server(self):
        self.calls.append("start")
        return {"status": "ok"}

    async def load_model(self, model):
        self.calls.append(("load", model))
        return {"status": "ok"}

    async def unload_model(self, model=None):
        self.calls.append(("unload", model))
        return {"status": "ok"}


class _FakeRouter:
    name = "lm-studio"
    active_model = "google/gemma-4-12b"


def _orch(online=True):
    o = Orchestrator.__new__(Orchestrator)
    o.lmstudio = _FakeCtrl(status_online=online)
    o.llm_router = _FakeRouter()
    return o


async def test_run_status_reports_real_model():
    r = await _orch()._run_llm_control("status", None)
    assert "google/gemma-4-12b" in r and "lm-studio" in r


async def test_run_status_offline():
    r = await _orch(online=False)._run_llm_control("status", None)
    assert "offline" in r.lower()


async def test_run_start():
    o = _orch()
    r = await o._run_llm_control("start", None)
    assert "up" in r.lower() and "start" in o.lmstudio.calls


async def test_run_load_invokes_controller():
    o = _orch()
    r = await o._run_llm_control("load", "google/gemma-4-12b")
    assert "Loaded" in r and ("load", "google/gemma-4-12b") in o.lmstudio.calls


async def test_run_load_missing_model_asks():
    r = await _orch()._run_llm_control("load", None)
    assert "Which model" in r


async def test_run_unload_all():
    o = _orch()
    r = await o._run_llm_control("unload", None)
    assert "All models" in r and ("unload", None) in o.lmstudio.calls
