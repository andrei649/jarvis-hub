"""capabilities.py — K2: least-privilege capability set per agent.

Generalizes the seeded ``CapabilityBroker`` tokens (today: 2 callers) to **all** agents:
each agent's capability set is *derived* from what it declares in ``agents.yaml`` — its
plugins, channel, and llm policy — **least-privilege by default**, so an agent can only ever
be granted what it asked for. :func:`issue_for_agent` mints a scoped, expiring token from
that set; the kernel's ``authorize`` already enforces a presented token (K1), so this is the
*issuance* half (the per-action enforcement waves consume it). Strict-local agents
(``frigga``/``ultron``/``howard``) never receive a cloud capability.
"""

from __future__ import annotations

LOCAL_ONLY_AGENTS = frozenset({"frigga", "ultron", "howard"})
_CLOUD_POLICIES = frozenset({"auto", "cloud", "claude"})


def _attr(cfg, key, default=None):
    """Read *key* from an AgentConfig object or a plain agents.yaml dict."""
    return cfg.get(key, default) if isinstance(cfg, dict) else getattr(cfg, key, default)


def derive_agent_capabilities(agent_id: str, cfg) -> list[str]:
    """The least-privilege capability set for *agent_id* from its declared config.

    *cfg* may be an ``AgentConfig`` or a plain dict. Capabilities: ``agent:<id>`` (identity),
    ``plugin:<p>`` per declared plugin, ``channel:<c>``, ``model:local`` (always), and
    ``model:cloud`` only for a non-local-only agent whose policy permits the cloud.
    """
    caps = {f"agent:{agent_id}"}
    for p in (_attr(cfg, "plugins", []) or []):
        caps.add(f"plugin:{p}")
    channel = _attr(cfg, "channel", "") or ""
    if isinstance(channel, dict):
        channel = channel.get("primary", "")
    if channel and channel not in ("no",):
        caps.add(f"channel:{channel}")
    caps.add("model:local")  # every agent may use the local model
    policy = str(_attr(cfg, "llm_policy", "auto") or "auto").lower()
    if agent_id not in LOCAL_ONLY_AGENTS and policy in _CLOUD_POLICIES:
        caps.add("model:cloud")
    return sorted(caps)


def issue_for_agent(broker, agent_id: str, cfg, *, ttl: float = 86400.0, now=None) -> dict:
    """Mint a scoped CapabilityBroker token for the agent's derived least-privilege set."""
    caps = derive_agent_capabilities(agent_id, cfg)
    return broker.issue(caps, source=f"agent:{agent_id}", ttl=ttl, now=now)


def issue_all(broker, agents: dict, *, ttl: float = 86400.0, now=None) -> dict:
    """Issue a per-agent capability token for every agent. Returns ``{agent_id: token_id}``."""
    return {
        aid: issue_for_agent(broker, aid, cfg, ttl=ttl, now=now)["id"]
        for aid, cfg in (agents or {}).items()
    }
