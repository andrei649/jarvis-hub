"""Tests for the System Monitor skill (H4.5) — Steve's infrastructure monitoring.

Tests CPU, RAM, GPU, disk, temps, services, alerts, and auto-recovery logic.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


def _load():
    path = repo_root / "skills" / "system_monitor" / "main.py"
    spec = importlib.util.spec_from_file_location("system_monitor_skill_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def skill():
    return _load()


def test_collect_snapshot_returns_snapshot(skill):
    snap = skill.collect_snapshot()
    assert hasattr(snap, "cpu_percent")
    assert hasattr(snap, "ram_used_gb")
    assert hasattr(snap, "status")
    assert snap.status in ("OK", "WARN", "CRITICAL")


def test_alerts_cpu_warn(skill):
    snap = skill.SystemSnapshot(cpu_percent=85.0)
    skill._check_alerts(snap)
    assert any("CPU warn" in a for a in snap.alerts)


def test_alerts_ram_critical(skill):
    snap = skill.SystemSnapshot(ram_percent=96.0)
    skill._check_alerts(snap)
    assert any("RAM critical" in a for a in snap.alerts)


def test_alerts_gpu_temp(skill):
    snap = skill.SystemSnapshot(gpu_temp=90)
    skill._check_alerts(snap)
    assert any("GPU temp critical" in a for a in snap.alerts)


def test_alerts_disk_emergency(skill):
    snap = skill.SystemSnapshot(disks=[{"path": "C:", "percent": 97}])
    skill._check_alerts(snap)
    assert any("emergency" in a for a in snap.alerts)


def test_no_alerts_when_ok(skill):
    snap = skill.SystemSnapshot(
        cpu_percent=30.0,
        ram_percent=50.0,
        gpu_temp=60,
        disks=[{"path": "C:", "percent": 40}],
    )
    skill._check_alerts(snap)
    assert snap.alerts == []


def test_check_service_unknown(skill):
    result = skill._check_service("nonexistent", {"port": 99999})
    assert result["status"] in ("up", "down", "error", "unknown")


def test_try_recover_disabled(skill):
    result = skill._try_recover("test", {"auto_recover": False})
    assert result["recovered"] is False
    assert "disabled" in result["reason"]


def test_try_recover_no_cmd(skill):
    result = skill._try_recover("test", {"auto_recover": True})
    assert result["recovered"] is False
    assert "no recovery command" in result["reason"]


async def test_status_command(skill):
    out = await skill.status("")
    assert "System" in out
    assert "CPU" in out
    assert "RAM" in out


async def test_cpu_command(skill):
    out = await skill.cpu("")
    assert "CPU" in out or "error" in out.lower()


async def test_ram_command(skill):
    out = await skill.ram("")
    assert "RAM" in out or "error" in out.lower()


async def test_gpu_command(skill):
    out = await skill.gpu("")
    assert "GPU" in out or "VRAM" in out or "error" in out.lower() or "unavailable" in out.lower()


async def test_disk_command(skill):
    out = await skill.disk("")
    assert "GB" in out or "No disks" in out or "Error" in out


async def test_disk_with_path(skill):
    out = await skill.disk("C:\\")
    assert "C:\\" in out or "GB" in out or "Error" in out


async def test_temps_command(skill):
    out = await skill.temps("")
    assert "°C" in out or "No temperature" in out or "error" in out.lower()


async def test_services_command(skill):
    out = await skill.services("")
    assert "Services:" in out
    assert "ollama" in out


async def test_check_command_up_or_down(skill):
    out = await skill.check("ollama")
    assert "ollama" in out.lower()
    assert "UP" in out or "DOWN" in out


async def test_check_command_unknown(skill):
    out = await skill.check("nonexistent")
    assert "Unknown service" in out


async def test_check_command_empty(skill):
    out = await skill.check("")
    assert "Usage:" in out


async def test_handle_dispatch(skill):
    assert "unknown command" in await skill.handle("bogus", "")
    assert "System" in await skill.handle("status", "")


def test_manifest_parses_via_loader(skill):
    from agents.core.skills.loader import SkillLoader
    sl = SkillLoader()
    manifest = sl._parse_manifest(repo_root / "skills" / "system_monitor" / "SKILL.md")
    assert manifest["name"] == "System Monitor"
    assert "steve" in manifest["agents"]
    cmds = {c["command"] for c in manifest["commands"]}
    assert {"status", "cpu", "ram", "gpu", "disk", "temps", "services", "check"} <= cmds


def test_thresholds_defined(skill):
    assert "cpu_warn" in skill.THRESHOLDS
    assert "ram_warn" in skill.THRESHOLDS
    assert "gpu_temp_critical" in skill.THRESHOLDS
    assert skill.THRESHOLDS["cpu_warn"] == 80
    assert skill.THRESHOLDS["ram_warn"] == 85
    assert skill.THRESHOLDS["gpu_temp_critical"] == 85


def test_services_configured(skill):
    assert "ollama" in skill.SERVICES
    assert "qdrant" in skill.SERVICES
    assert skill.SERVICES["ollama"]["port"] == 11434
    assert skill.SERVICES["ollama"]["auto_recover"] is True
