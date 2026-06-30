"""0.62 — system-profile posture consumed by subagent concurrency.

AutonomyCoordinator._subagent_concurrency() caps the autonomy.max_subagents
setting by the active system profile's max_parallel_agents hint (None = no hint
→ setting unchanged). So selecting e.g. the 'gaming' profile (cap 1) constrains
background agent throughput, while the default 'balanced' profile (None) is
transparent.
"""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.core.autonomy_coordinator as acmod  # noqa: E402
from agents.core.autonomy_coordinator import AutonomyCoordinator  # noqa: E402


class _Orch:
    def __init__(self, max_subagents=3):
        self._s = {"autonomy.max_subagents": max_subagents}

    def get_setting(self, key, default=None):
        return self._s.get(key, default)


def _coord(max_subagents=3):
    return AutonomyCoordinator(_Orch(max_subagents))


def test_default_balanced_profile_is_transparent(monkeypatch):
    # real active_posture, default env → 'balanced' has max_parallel_agents=None
    monkeypatch.delenv("JARVIS_SYSTEM_PROFILE", raising=False)
    assert _coord(5)._subagent_concurrency() == 5


def test_profile_caps_below_setting(monkeypatch):
    monkeypatch.setattr(acmod, "active_posture", lambda: {"max_parallel_agents": 1})
    assert _coord(5)._subagent_concurrency() == 1


def test_profile_hint_above_setting_keeps_setting(monkeypatch):
    monkeypatch.setattr(acmod, "active_posture", lambda: {"max_parallel_agents": 10})
    assert _coord(3)._subagent_concurrency() == 3   # min(3, 10)


def test_bad_profile_read_falls_back_to_setting(monkeypatch):
    def _boom():
        raise RuntimeError("no profile")
    monkeypatch.setattr(acmod, "active_posture", _boom)
    assert _coord(4)._subagent_concurrency() == 4


@pytest.mark.parametrize("hint", [0, -1, True, "2", None, 1.5])
def test_invalid_or_absent_hints_ignored(monkeypatch, hint):
    monkeypatch.setattr(acmod, "active_posture", lambda: {"max_parallel_agents": hint})
    assert _coord(3)._subagent_concurrency() == 3
