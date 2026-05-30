"""
health/main.py — Hercules' health telemetry skill (H2.4).

Loader-pattern skill. Analyzes health metric series (heart rate, HRV, sleep…)
and can pull a summary from the AppleHealthPlugin bridge when configured.
Degrades gracefully when the bridge is unreachable.

Commands (see get_commands):
  analyze <v1,v2,v3,...>   — basic stats over a numeric series
  summary [days]           — fetch a health summary from the Apple Health bridge
"""

import logging
import os

logger = logging.getLogger("jarvis.skills.health")

_plugin = None


def _get_plugin():
    global _plugin
    if _plugin is not None:
        return _plugin
    try:
        from agents.core.plugins.apple_health import AppleHealthPlugin
    except ImportError:
        from core.plugins.apple_health import AppleHealthPlugin
    _plugin = AppleHealthPlugin(
        bridge_url=os.environ.get("APPLE_HEALTH_BRIDGE_URL", "http://192.168.1.100:8081"),
    )
    return _plugin


def get_commands() -> list[str]:
    return ["analyze", "summary"]


# ── Programmatic API ────────────────────────────────────────────────

def analyze_values(values: list[float]) -> dict:
    """Return mean/max/min/trend over a numeric series."""
    if not values:
        return {"mean": 0, "max": 0, "min": 0, "trend": "flat", "n": 0}
    n = len(values)
    mean = sum(values) / n
    trend = "flat"
    if n >= 2:
        first_half = sum(values[: n // 2]) / max(1, n // 2)
        second_half = sum(values[n // 2:]) / max(1, n - n // 2)
        if second_half > first_half * 1.05:
            trend = "up"
        elif second_half < first_half * 0.95:
            trend = "down"
    return {"mean": mean, "max": max(values), "min": min(values), "trend": trend, "n": n}


def process_metrics(payload: dict) -> dict:
    """Contract kept compatible with the original spec/test."""
    vals = payload.get("values", [])
    return {"status": "processed", "analysis": analyze_values(vals)}


# ── Skill commands ──────────────────────────────────────────────────

def _parse_numbers(args: str) -> list[float]:
    out = []
    for tok in (args or "").replace(";", ",").split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(float(tok))
        except ValueError:
            continue
    return out


async def analyze(args: str, context: dict = None) -> str:
    """`analyze <v1,v2,...>` — quick stats over a series."""
    vals = _parse_numbers(args)
    if not vals:
        return "Folosire: analyze <valori separate prin virgulă>"
    a = analyze_values(vals)
    arrow = {"up": "↑", "down": "↓", "flat": "→"}[a["trend"]]
    return (
        f"{a['n']} valori — medie {a['mean']:.1f}, "
        f"min {a['min']:g}, max {a['max']:g}, trend {arrow}"
    )


async def summary(args: str, context: dict = None) -> str:
    """`summary [days]` — pull a health summary from the bridge."""
    days = 1
    tok = (args or "").strip().split(" ")[0]
    if tok.isdigit():
        days = int(tok)
    plugin = _get_plugin()
    try:
        data = await plugin.get_summary(days=days)
    except Exception as e:
        logger.warning(f"Apple Health bridge unreachable: {e}")
        return "Bridge-ul Apple Health nu răspunde — verifică APPLE_HEALTH_BRIDGE_URL."
    if not data:
        return "Nu am date de sănătate momentan."
    parts = [f"{k}: {v}" for k, v in data.items()]
    return "Sumar sănătate — " + ", ".join(parts)


async def handle(cmd: str, args: str, context: dict = None) -> str:
    dispatch = {"analyze": analyze, "summary": summary}
    fn = dispatch.get(cmd)
    if fn:
        return await fn(args, context)
    return f"[health] comandă necunoscută: {cmd}"
