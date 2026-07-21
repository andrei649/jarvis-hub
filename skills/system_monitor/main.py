"""
system_monitor/main.py — Steve's infrastructure monitoring skill (H4.5).

Monitors CPU, GPU, RAM, disk, temperatures, and service health.
Auto-recovers failed services when safe. Alerts on configurable thresholds.
Degrades gracefully when psutil or nvidia-smi unavailable.

Commands (see get_commands):
  status          — full system snapshot
  cpu             — CPU usage and load
  ram             — RAM usage breakdown
  gpu             — GPU VRAM, utilization, temperature
  disk [path]     — disk usage
  temps           — temperature sensors
  services        — check all configured services
  check <service> — check single service + auto-recovery attempt
"""

import asyncio
import logging
import subprocess
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("jarvis.skills.system_monitor")

THRESHOLDS = {
    "cpu_warn": 80,
    "ram_warn": 85,
    "ram_critical": 95,
    "gpu_temp_critical": 85,
    "disk_warn": 80,
    "disk_critical": 90,
    "disk_emergency": 95,
}

SERVICES = {
    "ollama": {"port": 11434, "auto_recover": True, "cmd": "ollama serve"},
    "qdrant": {"port": 6333, "auto_recover": False},
    "neo4j": {"port": 7474, "auto_recover": False},
    "n8n": {"port": 5678, "auto_recover": False},
    "pihole": {"port": 53, "auto_recover": False},
}

_psutil = None


def _get_psutil():
    global _psutil
    if _psutil is not None:
        return _psutil
    try:
        import psutil as ps
        _psutil = ps
        return _psutil
    except ImportError:
        return None


@dataclass
class SystemSnapshot:
    cpu_percent: float = 0.0
    cpu_count: int = 0
    ram_used_gb: float = 0.0
    ram_total_gb: float = 0.0
    ram_percent: float = 0.0
    gpu_vram_used: int = 0
    gpu_vram_total: int = 0
    gpu_util: int = 0
    gpu_temp: Optional[int] = None
    disks: list = field(default_factory=list)
    temps: dict = field(default_factory=dict)
    alerts: list = field(default_factory=list)

    @property
    def status(self) -> str:
        if any("critical" in a or "emergency" in a for a in self.alerts):
            return "CRITICAL"
        if self.alerts:
            return "WARN"
        return "OK"


def get_commands() -> list[str]:
    return ["status", "cpu", "ram", "gpu", "disk", "temps", "services", "check"]


def _collect_cpu(ps) -> dict:
    if ps is None:
        return {"error": "psutil not available"}
    try:
        percent = ps.cpu_percent(interval=0.5)
        count = ps.cpu_count(logical=True)
        freq = ps.cpu_freq()
        return {
            "percent": round(percent, 1),
            "count": count,
            "freq_mhz": round(freq.current, 0) if freq else None,
        }
    except Exception as e:
        return {"error": str(e)}


def _collect_ram(ps) -> dict:
    if ps is None:
        return {"error": "psutil not available"}
    try:
        vm = ps.virtual_memory()
        return {
            "used_gb": round(vm.used / 1e9, 1),
            "total_gb": round(vm.total / 1e9, 1),
            "percent": vm.percent,
            "available_gb": round(vm.available / 1e9, 1),
        }
    except Exception as e:
        return {"error": str(e)}


def _collect_gpu() -> dict:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode != 0:
            return {"error": "nvidia-smi failed"}
        parts = [p.strip() for p in r.stdout.strip().split(",")]
        if len(parts) >= 3:
            result = {
                "vram_used_mb": int(float(parts[0])),
                "vram_total_mb": int(float(parts[1])),
                "util_percent": int(float(parts[2])),
            }
            if len(parts) >= 4:
                result["temp_c"] = int(float(parts[3]))
            return result
    except FileNotFoundError:
        return {"error": "nvidia-smi not found"}
    except Exception as e:
        return {"error": str(e)}
    return {"error": "GPU data unavailable"}


def _collect_disks(ps, path: str = None) -> list[dict]:
    if ps is None:
        return [{"error": "psutil not available"}]
    try:
        if path:
            usage = ps.disk_usage(path)
            return [{
                "path": path,
                "used_gb": round(usage.used / 1e9, 1),
                "total_gb": round(usage.total / 1e9, 1),
                "percent": usage.percent,
                "free_gb": round(usage.free / 1e9, 1),
            }]
        results = []
        for part in ps.disk_partitions(all=False):
            try:
                usage = ps.disk_usage(part.mountpoint)
                results.append({
                    "path": part.mountpoint,
                    "device": part.device,
                    "used_gb": round(usage.used / 1e9, 1),
                    "total_gb": round(usage.total / 1e9, 1),
                    "percent": usage.percent,
                    "free_gb": round(usage.free / 1e9, 1),
                })
            except PermissionError:
                continue
        return results
    except Exception as e:
        return [{"error": str(e)}]


def _collect_temps(ps) -> dict:
    if ps is None:
        return {"error": "psutil not available"}
    try:
        temps = ps.sensors_temperatures()
        if not temps:
            return {}
        result = {}
        for name, entries in temps.items():
            result[name] = [
                {"label": e.label or name, "current": e.current, "high": e.high, "critical": e.critical}
                for e in entries
            ]
        return result
    except AttributeError:
        return {}
    except Exception as e:
        return {"error": str(e)}


def _check_alerts(snap: SystemSnapshot):
    if snap.cpu_percent > THRESHOLDS["cpu_warn"]:
        snap.alerts.append(f"CPU warn: {snap.cpu_percent}% > {THRESHOLDS['cpu_warn']}%")
    if snap.ram_percent > THRESHOLDS["ram_critical"]:
        snap.alerts.append(f"RAM critical: {snap.ram_percent}% > {THRESHOLDS['ram_critical']}%")
    elif snap.ram_percent > THRESHOLDS["ram_warn"]:
        snap.alerts.append(f"RAM warn: {snap.ram_percent}% > {THRESHOLDS['ram_warn']}%")
    if snap.gpu_temp and snap.gpu_temp > THRESHOLDS["gpu_temp_critical"]:
        snap.alerts.append(f"GPU temp critical: {snap.gpu_temp}°C > {THRESHOLDS['gpu_temp_critical']}°C")
    for d in snap.disks:
        if "error" in d:
            continue
        pct = d.get("percent", 0)
        path = d.get("path", "?")
        if pct > THRESHOLDS["disk_emergency"]:
            snap.alerts.append(f"Disk emergency: {path} {pct}% > {THRESHOLDS['disk_emergency']}%")
        elif pct > THRESHOLDS["disk_critical"]:
            snap.alerts.append(f"Disk critical: {path} {pct}% > {THRESHOLDS['disk_critical']}%")
        elif pct > THRESHOLDS["disk_warn"]:
            snap.alerts.append(f"Disk warn: {path} {pct}% > {THRESHOLDS['disk_warn']}%")


def collect_snapshot(path: str = None) -> SystemSnapshot:
    ps = _get_psutil()
    snap = SystemSnapshot()

    cpu = _collect_cpu(ps)
    snap.cpu_percent = cpu.get("percent", 0)
    snap.cpu_count = cpu.get("count", 0)

    ram = _collect_ram(ps)
    snap.ram_used_gb = ram.get("used_gb", 0)
    snap.ram_total_gb = ram.get("total_gb", 0)
    snap.ram_percent = ram.get("percent", 0)

    gpu = _collect_gpu()
    snap.gpu_vram_used = gpu.get("vram_used_mb", 0) // 1024 if "vram_used_mb" in gpu else 0
    snap.gpu_vram_total = gpu.get("vram_total_mb", 0) // 1024 if "vram_total_mb" in gpu else 0
    snap.gpu_util = gpu.get("util_percent", 0)
    snap.gpu_temp = gpu.get("temp_c")

    snap.disks = _collect_disks(ps, path)
    snap.temps = _collect_temps(ps)

    _check_alerts(snap)
    return snap


def _check_service(name: str, cfg: dict) -> dict:
    port = cfg.get("port")
    ps = _get_psutil()
    if ps is None:
        return {"name": name, "status": "unknown", "error": "psutil not available"}
    try:
        for conn in ps.net_connections(kind="inet"):
            if conn.laddr and conn.laddr.port == port and conn.status == "LISTEN":
                return {"name": name, "status": "up", "port": port}
        return {"name": name, "status": "down", "port": port}
    except Exception as e:
        return {"name": name, "status": "error", "error": str(e)}


def _try_recover(name: str, cfg: dict) -> dict:
    if not cfg.get("auto_recover"):
        return {"name": name, "recovered": False, "reason": "auto-recover disabled"}
    cmd = cfg.get("cmd")
    if not cmd:
        return {"name": name, "recovered": False, "reason": "no recovery command"}
    try:
        subprocess.Popen(
            cmd, shell=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP") else 0,
        )
        return {"name": name, "recovered": True, "cmd": cmd}
    except Exception as e:
        return {"name": name, "recovered": False, "error": str(e)}


# ── Skill commands ──────────────────────────────────────────────────

async def status(args: str, context: dict = None) -> str:
    # collect_snapshot blocks (cpu_percent sleeps 0.5s, nvidia-smi subprocess) —
    # run it off the event loop so a per-turn status check can't stall the server.
    snap = await asyncio.to_thread(collect_snapshot)
    parts = [f"System {snap.status}"]
    parts.append(f"CPU {snap.cpu_percent}% ({snap.cpu_count} cores)")
    parts.append(f"RAM {snap.ram_used_gb}/{snap.ram_total_gb} GB ({snap.ram_percent}%)")
    if snap.gpu_vram_total:
        parts.append(f"GPU {snap.gpu_temp or '?'}°C, VRAM {snap.gpu_vram_used}/{snap.gpu_vram_total} GB")
    if snap.alerts:
        parts.append(f"ALERTS: {'; '.join(snap.alerts)}")
    return " — ".join(parts)


async def cpu(args: str, context: dict = None) -> str:
    ps = _get_psutil()
    data = await asyncio.to_thread(_collect_cpu, ps)  # cpu_percent(interval=0.5) blocks
    if "error" in data:
        return f"CPU error: {data['error']}"
    return f"CPU {data['percent']}% — {data['count']} logical cores" + (
        f" @ {data['freq_mhz']:.0f} MHz" if data.get("freq_mhz") else ""
    )


async def ram(args: str, context: dict = None) -> str:
    ps = _get_psutil()
    data = _collect_ram(ps)
    if "error" in data:
        return f"RAM error: {data['error']}"
    return f"RAM {data['used_gb']}/{data['total_gb']} GB ({data['percent']}%) — {data['available_gb']} GB available"


async def gpu(args: str, context: dict = None) -> str:
    data = await asyncio.to_thread(_collect_gpu)  # runs nvidia-smi subprocess
    if "error" in data:
        return f"GPU: {data['error']}"
    parts = [f"VRAM {data['vram_used_mb']}/{data['vram_total_mb']} MB"]
    parts.append(f"util {data['util_percent']}%")
    if "temp_c" in data:
        parts.append(f"temp {data['temp_c']}°C")
    return "GPU — " + ", ".join(parts)


async def disk(args: str, context: dict = None) -> str:
    ps = _get_psutil()
    path = (args or "").strip() or None
    disks = _collect_disks(ps, path)
    if not disks:
        return "No disks found"
    lines = []
    for d in disks:
        if "error" in d:
            lines.append(f"Error: {d['error']}")
        else:
            lines.append(f"{d['path']}: {d['used_gb']}/{d['total_gb']} GB ({d['percent']}%) — {d['free_gb']} GB free")
    return "\n".join(lines)


async def temps(args: str, context: dict = None) -> str:
    ps = _get_psutil()
    data = _collect_temps(ps)
    if not data:
        return "No temperature sensors available"
    if "error" in data:
        return f"Temps: {data['error']}"
    lines = []
    for sensor, entries in data.items():
        for e in entries:
            lines.append(f"{e['label']}: {e['current']}°C" + (
                f" (high {e['high']}°C)" if e.get("high") else ""
            ))
    return "\n".join(lines)


async def services(args: str, context: dict = None) -> str:
    results = []
    for name, cfg in SERVICES.items():
        r = _check_service(name, cfg)
        icon = "✓" if r["status"] == "up" else "✗" if r["status"] == "down" else "?"
        results.append(f"{name} {icon}")
    return "Services: " + ", ".join(results)


async def check(args: str, context: dict = None) -> str:
    name = (args or "").strip().lower()
    if not name:
        return "Usage: check <service_name>"
    cfg = SERVICES.get(name)
    if not cfg:
        return f"Unknown service: {name}. Available: {', '.join(SERVICES.keys())}"
    r = _check_service(name, cfg)
    if r["status"] == "up":
        return f"{name}: UP on port {r['port']}"
    recover = _try_recover(name, cfg)
    if recover.get("recovered"):
        return f"{name}: was DOWN — recovery started ({recover.get('cmd', 'restart')})"
    return f"{name}: DOWN — recovery failed: {recover.get('reason', recover.get('error', 'unknown'))}"


async def handle(cmd: str, args: str, context: dict = None) -> str:
    dispatch = {
        "status": status,
        "cpu": cpu,
        "ram": ram,
        "gpu": gpu,
        "disk": disk,
        "temps": temps,
        "services": services,
        "check": check,
    }
    fn = dispatch.get(cmd)
    if fn:
        return await fn(args, context)
    return f"[system_monitor] unknown command: {cmd}"
