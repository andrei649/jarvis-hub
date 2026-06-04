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
from core.autonomy.remediation import ExecResult


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


def _ctrl(**kw):
    kw.setdefault("verify_attempts", 3)
    kw.setdefault("verify_delay", 0)
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


async def test_load_model_starts_server_if_down():
    ex = _Exec()
    router = _Router()
    # down at load pre-check, down at start pre-check, up at start verify
    ctrl = _ctrl(exec_fn=ex, probe_fn=_Probe([False, False, True]), router=router)
    out = await ctrl.load_model("m/x")
    assert out["status"] == "ok"
    assert ["lms", "server", "start"] in ex.calls
    assert ["lms", "load", "m/x", "-y"] in ex.calls


async def test_load_model_start_fails_then_no_load():
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
