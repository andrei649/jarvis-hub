"""
agent_templates.py — H10.29 Agent Templates Library.

A small library of pre-configured agent archetypes (researcher, coder, analyst,
assistant, ops) that a user can instantiate quickly instead of hand-writing a
SOUL.md + registry entry. `build_agent_config()` renders a ready-to-save agent
definition (agents.yaml-shaped fields + a SOUL.md skeleton) from a template,
with optional per-field overrides.
"""

from __future__ import annotations

import re
from typing import Optional

# Each template is an archetype: sensible defaults for tier/model/plugins plus a
# SOUL.md skeleton. Models are tier hints; callers may override.
AGENT_TEMPLATES: dict[str, dict] = {
    "researcher": {
        "name": "Researcher",
        "role": "Research & OSINT analyst",
        "description": "Gathers, cross-checks, and synthesizes information from many sources.",
        "tier": "specialist",
        "model": "deepseek-r1:32b",
        "plugins": ["websearch", "news"],
        "has_heartbeat": False,
        "voice": "precise, source-citing, skeptical",
    },
    "coder": {
        "name": "Coder",
        "role": "Software engineer",
        "description": "Writes, reviews, and refactors code; explains trade-offs.",
        "tier": "specialist",
        "model": "qwen2.5:14b",
        "plugins": [],
        "has_heartbeat": False,
        "voice": "concise, pragmatic, test-first",
    },
    "analyst": {
        "name": "Analyst",
        "role": "Business intelligence analyst",
        "description": "Turns data into decisions: metrics, trends, recommendations.",
        "tier": "specialist",
        "model": "deepseek-r1:32b",
        "plugins": ["analytics", "balance"],
        "has_heartbeat": True,
        "voice": "data-driven, executive-summary first",
    },
    "assistant": {
        "name": "Assistant",
        "role": "General personal assistant",
        "description": "Day-to-day help: scheduling, reminders, quick answers.",
        "tier": "cns",
        "model": "qwen2.5:7b",
        "plugins": ["google_calendar"],
        "has_heartbeat": True,
        "voice": "warm, efficient, proactive",
    },
    "ops": {
        "name": "Ops",
        "role": "Infrastructure & automation operator",
        "description": "Runs workflows, watches systems, automates chores.",
        "tier": "foundation",
        "model": "qwen2.5:7b",
        "plugins": ["n8n", "homebridge"],
        "has_heartbeat": True,
        "voice": "terse, checklist-oriented, safety-conscious",
    },
}


def list_templates() -> list[dict]:
    """Return the template catalog (key + summary fields)."""
    return [
        {
            "key": key,
            "name": t["name"],
            "role": t["role"],
            "description": t["description"],
            "tier": t["tier"],
            "model": t["model"],
            "plugins": list(t["plugins"]),
        }
        for key, t in AGENT_TEMPLATES.items()
    ]


def get_template(key: str) -> Optional[dict]:
    t = AGENT_TEMPLATES.get((key or "").strip().lower())
    return dict(t) if t else None


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return slug or "agent"


def _render_soul(agent_id: str, name: str, tmpl: dict) -> str:
    return (
        f"# {name} — SOUL\n\n"
        f"**id:** `{agent_id}`\n\n"
        f"## Mission\n{tmpl['role']}. {tmpl['description']}\n\n"
        f"## Voice\n{tmpl.get('voice', 'clear and helpful')}\n\n"
        f"## Rules\n"
        f"- Stay within your role: {tmpl['role']}.\n"
        f"- Defer to the orchestrator's guardrails and permission gate.\n"
        f"- Be honest about uncertainty; cite sources where relevant.\n"
    )


def build_agent_config(
    template: str,
    name: Optional[str] = None,
    overrides: Optional[dict] = None,
) -> dict:
    """Render a ready-to-save agent definition from a template.

    Returns a dict with agents.yaml-shaped fields (`id`, `name`, `status`,
    `model`, `tier`, `plugins`, `has_heartbeat`) plus a `soul` skeleton. Raises
    KeyError if the template is unknown.
    """
    tmpl = get_template(template)
    if tmpl is None:
        raise KeyError(f"unknown template: {template}")

    overrides = overrides or {}
    display_name = name or overrides.get("name") or tmpl["name"]
    agent_id = _slugify(overrides.get("id") or display_name)

    config = {
        "id": agent_id,
        "name": display_name,
        "status": overrides.get("status", "active"),
        "model": overrides.get("model", tmpl["model"]),
        "tier": overrides.get("tier", tmpl["tier"]),
        "plugins": list(overrides.get("plugins", tmpl["plugins"])),
        "has_heartbeat": bool(overrides.get("has_heartbeat", tmpl["has_heartbeat"])),
        "template": template,
    }
    config["soul"] = _render_soul(agent_id, display_name, tmpl)
    return config
