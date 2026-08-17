"""Tests for LMStudioController — start/load/unload via injected exec + probe.

No subprocesses, no sockets: exec_fn and probe_fn are faked, mirroring the
offline pattern used by the autonomy remediation tests.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.llm.lmstudio_control import LMStudioController
from agents.core.autonomy.remediation import ExecResult


class _Exec:
    """Records argv calls; returns a preset ExecResult or raises."""
    def __init__(self, result=None, raises=None):
        self.calls = []
        self._result = result if result is not None else ExecResult(exit_code=0, stdout="ok")
        self._raises = raises

    async def __call__(self, argv, timeout, detach):
        self.calls.append(list(argv))
        if self._raises:
            raise self._raises
        return self._result


class _Probe:
    """Returns values from a sequence (repeats the last). Default: online."""
    def __init__(self, seq=(True,)):
        self.seq = list(seq)
        self.i = 0

    def __call__(self, host, port):
        v = self.seq[min(self.i, len(self.seq) - 1)]
        self.i += 1
        return v


class _Router:
    def __init__(self):
        self.refreshed = 0
        self.active_model = "google/gemma-4-12b"

    async def refresh_active_model(self):
        self.refreshed += 1
        return self.active_model


def _models(ids=()):
    """A models_fn returning a fixed servable list (keeps tests off the network)."""
    async def _fn():
        return list(ids)
    return _fn


def _ctrl(**kw):
    kw.setdefault("verify_attempts", 3)
    kw.setdefault("verify_delay", 0)
    # Hermetic default: no /v1/models probe, so resolution falls through to the
    # literal name. Resolution tests pass their own models_fn with candidates.
    kw.setdefault("models_fn", _models())
    return LMStudioController(**kw)


# ── start_server ─────────────────────────────────────────────────

async def test_start_server_already_online():
    ctrl = _ctrl(exec_fn=_Exec(), probe_fn=_Probe([True]))
    out = await ctrl.start_server()
    assert out["status"] == "ok" and out.get("already_running") is True


async def test_start_server_starts_and_recovers():
    ex = _Exec()
    ctrl = _ctrl(exec_fn=ex, probe_fn=_Probe([False, True]))
    out = await ctrl.start_server()
    assert out["status"] == "ok"
    assert ex.calls == [["lms", "server", "start"]]


async def test_start_server_exec_raises():
    ctrl = _ctrl(exec_fn=_Exec(raises=OSError("no lms binary")), probe_fn=_Probe([False]))
    out = await ctrl.start_server()
    assert out["status"] == "failed"


async def test_start_server_never_recovers():
    ctrl = _ctrl(exec_fn=_Exec(), probe_fn=_Probe([False]))
    out = await ctrl.start_server()
    assert out["status"] == "failed"


# ── load_model ───────────────────────────────────────────────────

async def test_load_invalid_model_rejected_and_nothing_runs():
    ex = _Exec()
    ctrl = _ctrl(exec_fn=ex, probe_fn=_Probe([True]))
    out = await ctrl.load_model("evil; rm -rf /")
    assert out["status"] == "rejected"
    assert ex.calls == []


async def test_load_model_ok_refreshes_router():
    ex = _Exec()
    router = _Router()
    ctrl = _ctrl(exec_fn=ex, probe_fn=_Probe([True]), router=router)
    out = await ctrl.load_model("google/gemma-4-12b")
    assert out["status"] == "ok"
    assert ex.calls == [["lms", "load", "google/gemma-4-12b", "-y"]]
    assert router.refreshed == 1


async def test_load_model_refuses_to_auto_start_if_down():
    ex = _Exec()
    router = _Router()
    ctrl = _ctrl(exec_fn=ex, probe_fn=_Probe([False]), router=router)
    out = await ctrl.load_model("m/x")
    assert out["status"] == "failed"
    assert "authorize and start" in out["reason"]
    assert ex.calls == []


async def test_load_model_offline_never_executes_load():
    ex = _Exec()
    ctrl = _ctrl(exec_fn=ex, probe_fn=_Probe([False]))  # never comes up
    out = await ctrl.load_model("m/x")
    assert out["status"] == "failed"
    assert ["lms", "load", "m/x", "-y"] not in ex.calls


async def test_load_model_exec_nonzero_no_refresh():
    ex = _Exec(result=ExecResult(exit_code=1, stderr="oom"))
    router = _Router()
    ctrl = _ctrl(exec_fn=ex, probe_fn=_Probe([True]), router=router)
    out = await ctrl.load_model("m/x")
    assert out["status"] == "failed"
    assert router.refreshed == 0


# ── fuzzy model resolution (load "gemma" → full id via /v1/models) ──

CATALOG = ["google/gemma-4-12b", "qwen/qwen3-14b", "deepseek-r1-distill-qwen-32b"]


async def test_load_resolves_partial_name_to_full_id():
    ex = _Exec()
    ctrl = _ctrl(exec_fn=ex, probe_fn=_Probe([True]), models_fn=_models(CATALOG))
    out = await ctrl.load_model("gemma")
    assert out["status"] == "ok"
    assert out["model"] == "google/gemma-4-12b"
    assert out["resolved_from"] == "gemma"
    assert ex.calls == [["lms", "load", "google/gemma-4-12b", "-y"]]


async def test_load_exact_id_is_not_marked_resolved():
    ex = _Exec()
    ctrl = _ctrl(exec_fn=ex, probe_fn=_Probe([True]), models_fn=_models(CATALOG))
    out = await ctrl.load_model("google/gemma-4-12b")
    assert out["status"] == "ok"
    assert "resolved_from" not in out
    assert ex.calls == [["lms", "load", "google/gemma-4-12b", "-y"]]


async def test_load_ambiguous_partial_stops_and_reports_candidates():
    ex = _Exec()
    catalog = ["google/gemma-4-12b", "google/gemma-2-9b"]
    ctrl = _ctrl(exec_fn=ex, probe_fn=_Probe([True]), models_fn=_models(catalog))
    out = await ctrl.load_model("gemma")
    assert out["status"] == "ambiguous"
    assert sorted(out["candidates"]) == sorted(catalog)
    assert ex.calls == []  # nothing loaded when ambiguous


async def test_load_unique_exact_segment_breaks_tie():
    # "qwen" substring-matches two ids, but the query equals one's last segment.
    ex = _Exec()
    catalog = ["qwen/qwen", "deepseek-r1-distill-qwen-32b"]
    ctrl = _ctrl(exec_fn=ex, probe_fn=_Probe([True]), models_fn=_models(catalog))
    out = await ctrl.load_model("qwen")
    assert out["status"] == "ok"
    assert out["model"] == "qwen/qwen"


async def test_load_unknown_name_falls_through_to_literal():
    # Name not in the catalog → literal passthrough (LM Studio JIT may still find it).
    ex = _Exec()
    ctrl = _ctrl(exec_fn=ex, probe_fn=_Probe([True]), models_fn=_models(CATALOG))
    out = await ctrl.load_model("mistral-7b")
    assert out["status"] == "ok"
    assert "resolved_from" not in out
    assert ex.calls == [["lms", "load", "mistral-7b", "-y"]]


async def test_load_unreachable_catalog_falls_through_to_literal():
    # models_fn raises (server flaky) → empty list → literal passthrough, no crash.
    async def _boom():
        raise RuntimeError("connection refused")
    ex = _Exec()
    ctrl = _ctrl(exec_fn=ex, probe_fn=_Probe([True]), models_fn=_boom)
    out = await ctrl.load_model("google/gemma-4-12b")
    assert out["status"] == "ok"
    assert ex.calls == [["lms", "load", "google/gemma-4-12b", "-y"]]


def test_resolve_model_pure_cases():
    r = LMStudioController._resolve_model
    # exact id present
    assert r("a/b", ["a/b", "a/c"]) == ("a/b", ["a/b"])
    # single substring match
    assert r("gem", ["google/gemma-4-12b", "qwen/q"]) == ("google/gemma-4-12b", ["google/gemma-4-12b"])
    # ambiguous
    resolved, cands = r("g", ["g/one", "g/two"])
    assert resolved is None and sorted(cands) == ["g/one", "g/two"]
    # no match → literal
    assert r("zzz", ["a/b"]) == ("zzz", [])
    # empty catalog → literal
    assert r("anything", []) == ("anything", [])


# ── unload_model ─────────────────────────────────────────────────

async def test_unload_named_ok_refreshes():
    ex = _Exec()
    router = _Router()
    ctrl = _ctrl(exec_fn=ex, probe_fn=_Probe([True]), router=router)
    out = await ctrl.unload_model("m/x")
    assert out["status"] == "ok"
    assert ex.calls == [["lms", "unload", "m/x"]]
    assert router.refreshed == 1


async def test_unload_all_when_no_model():
    ex = _Exec()
    ctrl = _ctrl(exec_fn=ex, probe_fn=_Probe([True]))
    await ctrl.unload_model()
    assert ex.calls == [["lms", "unload", "--all"]]


# ── permission gate + status ─────────────────────────────────────

async def test_permission_gate_blocks_and_nothing_runs():
    class Gate:
        def check_call(self, plugin, agent):
            return False
    ex = _Exec()
    ctrl = _ctrl(exec_fn=ex, probe_fn=_Probe([True]), permission_gate=Gate())
    out = await ctrl.load_model("m/x", agent="frigga")
    assert out["status"] == "blocked"
    assert ex.calls == []


async def test_status_reports_model_when_online():
    router = _Router()
    ctrl = _ctrl(exec_fn=_Exec(), probe_fn=_Probe([True]), router=router)
    st = await ctrl.status()
    assert st["online"] is True
    assert st["active_model"] == "google/gemma-4-12b"


async def test_status_offline_hides_model():
    router = _Router()
    ctrl = _ctrl(exec_fn=_Exec(), probe_fn=_Probe([False]), router=router)
    st = await ctrl.status()
    assert st["online"] is False
    assert st["active_model"] is None
