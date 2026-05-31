"""
security_monitor/main.py — Ultron's local security monitoring skill (H4.4).

Monitors open ports/sockets, network devices (ARP), Pi-hole logs, firewall
status, and derives simple threat heuristics. All sources are optional — the
skill degrades gracefully when a source is unavailable. No external network
calls. Designed for local-first operation (dev machine or Pi).

Commands (see get_commands):
  security_status  — full snapshot: ports, devices, firewall, pihole, threats
  ports            — listening sockets with owning process
  devices          — LAN devices from ARP table
  pihole           — Pi-hole blocked query summary
  firewall         — ufw / iptables status
  threats          — heuristic threat summary
"""

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("jarvis.skills.security_monitor")

# Ports that are unusual to expose on 0.0.0.0 — trigger a threat hint
SUSPICIOUS_WILDCARD_PORTS = {
    23,    # telnet
    2323,  # alt telnet
    3389,  # RDP
    5900,  # VNC
    6881,  # BitTorrent
    4444,  # common malware
    1337,  # common malware
}

# Well-known service names for common ports
KNOWN_PORTS = {
    22: "ssh", 53: "dns", 80: "http", 443: "https",
    3306: "mysql", 5432: "postgres", 6333: "qdrant",
    6379: "redis", 7474: "neo4j", 8080: "http-alt",
    11434: "ollama", 5678: "n8n", 8443: "https-alt",
    5353: "mdns", 631: "cups",
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


# ── Data classes ────────────────────────────────────────────────────


@dataclass
class ListeningPort:
    port: int
    address: str       # bound address ("0.0.0.0", "127.0.0.1", "::", ...)
    pid: Optional[int]
    process: str       # process name or "unknown"
    proto: str = "tcp"


@dataclass
class ArpDevice:
    ip: str
    mac: str
    iface: str


@dataclass
class SecuritySnapshot:
    listening_ports: list = field(default_factory=list)
    arp_devices: list = field(default_factory=list)
    pihole: dict = field(default_factory=dict)
    firewall: dict = field(default_factory=dict)
    threats: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def status(self) -> str:
        if any(t.get("severity") == "high" for t in self.threats):
            return "WARN"
        return "OK"


# ── Collectors ──────────────────────────────────────────────────────


_UNSET = object()  # sentinel for "caller did not supply ps"


def _collect_ports(ps=_UNSET) -> list[ListeningPort]:
    """Return all LISTEN sockets with process info (best-effort).

    Pass *ps=None* explicitly to force "no psutil" (returns []).
    Omit the argument to auto-discover psutil.
    """
    if ps is _UNSET:
        ps = _get_psutil()
    if ps is None:
        return []

    results = []
    try:
        conns = ps.net_connections(kind="inet")
    except (PermissionError, AttributeError, Exception) as e:
        logger.warning("net_connections failed: %s", e)
        return []

    pid_cache: dict[int, str] = {}

    for conn in conns:
        if conn.status != "LISTEN":
            continue
        laddr = conn.laddr
        if not laddr:
            continue

        port = laddr.port
        addr = laddr.ip if hasattr(laddr, "ip") else str(laddr[0])
        pid = conn.pid

        # Resolve process name
        proc_name = "unknown"
        if pid:
            if pid in pid_cache:
                proc_name = pid_cache[pid]
            else:
                try:
                    proc_name = ps.Process(pid).name()
                    pid_cache[pid] = proc_name
                except (ps.NoSuchProcess, ps.AccessDenied, Exception):
                    proc_name = KNOWN_PORTS.get(port, "unknown")
                    pid_cache[pid] = proc_name
        else:
            proc_name = KNOWN_PORTS.get(port, "unknown")

        proto = "tcp6" if ":" in addr else "tcp"
        results.append(ListeningPort(port=port, address=addr, pid=pid, process=proc_name, proto=proto))

    # Deduplicate by (port, addr)
    seen = set()
    deduped = []
    for p in results:
        key = (p.port, p.address)
        if key not in seen:
            seen.add(key)
            deduped.append(p)

    return sorted(deduped, key=lambda p: p.port)


def _collect_arp_devices() -> list[ArpDevice]:
    """Parse /proc/net/arp for LAN devices (Linux only). Graceful fallback."""
    arp_path = Path("/proc/net/arp")
    if not arp_path.exists():
        return []

    devices = []
    try:
        lines = arp_path.read_text(encoding="utf-8").splitlines()
        # Header: IP address  HW type  Flags  HW address  Mask  Device
        for line in lines[1:]:
            parts = line.split()
            if len(parts) < 6:
                continue
            ip, _hw_type, flags, mac, _mask, iface = parts[:6]
            # Skip incomplete entries (flags 0x0)
            if flags == "0x0" or mac == "00:00:00:00:00:00":
                continue
            devices.append(ArpDevice(ip=ip, mac=mac, iface=iface))
    except Exception as e:
        logger.warning("ARP parse failed: %s", e)

    return devices


def _collect_pihole() -> dict:
    """Check Pi-hole log or FTL socket. Returns status dict."""
    # Try /var/log/pihole.log
    log_path = Path("/var/log/pihole.log")
    ftl_path = Path("/run/pihole/FTL.sock")

    if not log_path.exists() and not ftl_path.exists():
        return {"available": False, "reason": "pihole: unavailable"}

    if log_path.exists():
        try:
            # Read last 200 lines to summarize recent blocks
            text = log_path.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()[-200:]
            blocked = [l for l in lines if " blocked " in l or "gravity" in l.lower()]
            total = len(lines)
            return {
                "available": True,
                "recent_lines": total,
                "blocked_count": len(blocked),
                "top_blocked": _top_blocked_domains(blocked),
            }
        except PermissionError:
            return {"available": False, "reason": "pihole: log permission denied"}
        except Exception as e:
            return {"available": False, "reason": f"pihole: read error ({e})"}

    # FTL socket present but no log
    return {"available": True, "blocked_count": 0, "note": "FTL present, log unavailable"}


def _top_blocked_domains(blocked_lines: list[str], n: int = 5) -> list[str]:
    """Extract most-seen domains from pihole blocked log lines."""
    from collections import Counter
    domains: list[str] = []
    for line in blocked_lines:
        parts = line.split()
        # Typical format: date time dnsmasq[PID]: blocked <domain> ...
        for i, part in enumerate(parts):
            if part == "blocked" and i + 1 < len(parts):
                domains.append(parts[i + 1].rstrip("."))
                break
    if not domains:
        return []
    return [domain for domain, _ in Counter(domains).most_common(n)]


def _collect_firewall() -> dict:
    """Try ufw status then iptables -L. Catch all failures gracefully."""
    # Try ufw first (most common on Ubuntu/Debian)
    try:
        r = subprocess.run(
            ["ufw", "status"],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0:
            first_line = r.stdout.splitlines()[0] if r.stdout.strip() else ""
            lower = first_line.lower()
            # "Status: active" → True; "Status: inactive" → False
            active = "active" in lower and "inactive" not in lower
            return {
                "tool": "ufw",
                "active": active,
                "status_line": first_line.strip(),
                "raw": r.stdout.strip()[:500],
            }
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.debug("ufw failed: %s", e)

    # Try iptables (requires root on most systems; catch permission errors)
    try:
        r = subprocess.run(
            ["iptables", "-L", "--line-numbers", "-n"],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0:
            lines = r.stdout.splitlines()
            rule_count = sum(1 for l in lines if l and not l.startswith("Chain") and not l.startswith("target"))
            return {
                "tool": "iptables",
                "active": True,
                "rule_count": rule_count,
            }
        if r.returncode == 4 or "permission denied" in r.stderr.lower():
            return {"tool": "iptables", "active": None, "status_line": "firewall: permission denied (needs root)"}
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.debug("iptables failed: %s", e)

    return {"tool": "none", "active": None, "status_line": "firewall: unknown (ufw/iptables not found)"}


def _derive_threats(ports: list[ListeningPort], pihole: dict, arp_devices: list[ArpDevice]) -> list[dict]:
    """Derive simple threat heuristics from collected local data."""
    threats = []

    # Check for suspicious ports exposed on 0.0.0.0
    for p in ports:
        wildcard = p.address in ("0.0.0.0", "::", "")
        if wildcard and p.port in SUSPICIOUS_WILDCARD_PORTS:
            threats.append({
                "severity": "high",
                "type": "suspicious_port",
                "detail": f"Port {p.port}/{p.process} exposed on {p.address} — unusual service",
                "action": f"Verify intent; consider restricting port {p.port} to localhost",
            })

    # Pi-hole blocked spike (crude heuristic)
    if pihole.get("available") and pihole.get("blocked_count", 0) > 50:
        threats.append({
            "severity": "low",
            "type": "dns_spike",
            "detail": f"Pi-hole blocked {pihole['blocked_count']} queries in recent log window",
            "action": "Review blocked domains for unusual patterns",
        })

    return threats


# ── Public API ──────────────────────────────────────────────────────


def collect_snapshot() -> SecuritySnapshot:
    """Gather all security data into a SecuritySnapshot. Never raises."""
    snap = SecuritySnapshot()

    try:
        snap.listening_ports = _collect_ports()
    except Exception as e:
        snap.errors.append(f"ports: {e}")

    try:
        snap.arp_devices = _collect_arp_devices()
    except Exception as e:
        snap.errors.append(f"arp: {e}")

    try:
        snap.pihole = _collect_pihole()
    except Exception as e:
        snap.pihole = {"available": False, "reason": f"pihole: error ({e})"}
        snap.errors.append(f"pihole: {e}")

    try:
        snap.firewall = _collect_firewall()
    except Exception as e:
        snap.firewall = {"tool": "none", "active": None, "status_line": f"firewall: error ({e})"}
        snap.errors.append(f"firewall: {e}")

    try:
        snap.threats = _derive_threats(snap.listening_ports, snap.pihole, snap.arp_devices)
    except Exception as e:
        snap.errors.append(f"threats: {e}")

    return snap


def _fmt_ports(ports: list[ListeningPort]) -> str:
    if not ports:
        return "No listening ports found"
    parts = [f"{p.port}/{p.process}({p.address})" for p in ports[:20]]
    suffix = f" (+{len(ports) - 20} more)" if len(ports) > 20 else ""
    return f"Listening ({len(ports)}): " + ", ".join(parts) + suffix


def _fmt_devices(devices: list[ArpDevice]) -> str:
    if not devices:
        return "Devices: none (ARP table unavailable or empty)"
    parts = [f"{d.ip}[{d.mac}]" for d in devices[:15]]
    suffix = f" (+{len(devices) - 15} more)" if len(devices) > 15 else ""
    return f"Devices ({len(devices)}): " + ", ".join(parts) + suffix


def _fmt_pihole(pihole: dict) -> str:
    if not pihole.get("available", False):
        return pihole.get("reason", "Pi-hole: unavailable")
    blocked = pihole.get("blocked_count", 0)
    top = pihole.get("top_blocked", [])
    top_str = ", ".join(top) if top else "none"
    return f"Pi-hole: {blocked} blocked (top: {top_str})"


def _fmt_firewall(fw: dict) -> str:
    tool = fw.get("tool", "none")
    active = fw.get("active")
    if tool == "none":
        return fw.get("status_line", "Firewall: unknown")
    if active is None:
        return fw.get("status_line", f"Firewall ({tool}): status unknown")
    state = "active" if active else "inactive"
    return f"Firewall ({tool}): {state}"


def _fmt_threats(threats: list[dict]) -> str:
    if not threats:
        return "Threats: none detected"
    parts = [f"[{t['severity'].upper()}] {t['detail']}" for t in threats]
    return "Threats:\n  " + "\n  ".join(parts)


# ── Skill command handlers ──────────────────────────────────────────


def get_commands() -> list[str]:
    return ["security_status", "ports", "devices", "pihole", "firewall", "threats"]


async def security_status(args: str = "", context: dict = None) -> str:
    snap = collect_snapshot()
    lines = [
        f"Security status: {snap.status}",
        _fmt_ports(snap.listening_ports),
        _fmt_devices(snap.arp_devices),
        _fmt_firewall(snap.firewall),
        _fmt_pihole(snap.pihole),
        _fmt_threats(snap.threats),
    ]
    if snap.errors:
        lines.append("Errors: " + "; ".join(snap.errors))
    return "\n".join(lines)


async def ports(args: str = "", context: dict = None) -> str:
    ps = _get_psutil()
    result = _collect_ports(ps)
    return _fmt_ports(result)


async def devices(args: str = "", context: dict = None) -> str:
    result = _collect_arp_devices()
    return _fmt_devices(result)


async def pihole(args: str = "", context: dict = None) -> str:
    result = _collect_pihole()
    return _fmt_pihole(result)


async def firewall(args: str = "", context: dict = None) -> str:
    result = _collect_firewall()
    return _fmt_firewall(result)


async def threats(args: str = "", context: dict = None) -> str:
    ps = _get_psutil()
    listening_ports = _collect_ports(ps)
    pihole_data = _collect_pihole()
    arp_devices = _collect_arp_devices()
    threat_list = _derive_threats(listening_ports, pihole_data, arp_devices)
    return _fmt_threats(threat_list)


async def handle(cmd: str, args: str, context: dict = None) -> str:
    dispatch = {
        "security_status": security_status,
        "ports": ports,
        "devices": devices,
        "pihole": pihole,
        "firewall": firewall,
        "threats": threats,
    }
    fn = dispatch.get(cmd)
    if fn:
        return await fn(args, context)
    return f"[security_monitor] unknown command: {cmd}"
