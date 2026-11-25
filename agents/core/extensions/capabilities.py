"""The canonical extension capability registry, and the consent screen built from it.

Hermes keeps a ``CAPABILITY_REGISTRY`` of seven ids, each with the config gate it
replaces and the one risk sentence shown on the consent screen
(acp-mcp-dev.plugin-capabilities). Nerva's registry has exactly the capabilities a
descriptor may declare (``manifest.CAPABILITIES``) and nothing more: an extension
cannot override a core tool, a core command or a model call, so the Hermes
``tools.override`` and ``llm.*`` ids have no Nerva counterpart to gate. They are not
missing grants; the manifest parser refuses the surfaces they would unlock.

Each entry says what the capability lets the extension do, the sentence the owner
reads before agreeing, and which host mechanism enforces it — so a consent screen is
generated from data that a test can compare against the parser, and a capability
added to the parser without a risk sentence fails loudly here instead of reaching an
owner as a blank line.

Some events carry more than names (the guardian approval events carry masked
excerpts of the command under review), so those events have their own risk sentence
on top of the ``events.observe`` one.
"""

from __future__ import annotations

from dataclasses import dataclass

from .manifest import CAPABILITIES, EVENTS, ExtensionManifest


@dataclass(frozen=True, slots=True)
class Capability:
    id: str
    title: str
    risk: str
    enforced_by: str


CAPABILITY_REGISTRY: dict[str, Capability] = {
    "tools": Capability(
        "tools",
        "Add tools the assistant can call",
        "The assistant may call this extension's code with arguments taken from the "
        "conversation; the code runs in a sealed container with no network, no host "
        "files and no credentials, and what it returns reaches the model fenced as "
        "untrusted data.",
        "signed acquired package; isolated register() must match the declaration; "
        "sandbox profile (--network none, --read-only, --cap-drop ALL)",
    ),
    "commands": Capability(
        "commands",
        "Add owner slash commands",
        "You will be able to run this extension's code from chat by typing its "
        "commands; only the owner sees and runs them, a core command can never be "
        "replaced, and replies pass the outbound sanitizer.",
        "shared chat registry (owner-only, collision refused); same sealed sandbox",
    ),
    "events.observe": Capability(
        "events.observe",
        "Be told when things happen",
        "The extension is started once per delivered event and receives the event's "
        "fixed summary fields; nothing it answers is read, so it can watch but never "
        "block, change or approve anything.",
        "observer bus with fixed fields; delivery script reads only the exit code",
    ),
}

EVENT_RISKS: dict[str, str] = {
    "approval.smart.requested": (
        "Receives a masked 200-character excerpt of each command the guardian is asked "
        "to judge and its description; private paths or prose may remain."
    ),
    "approval.smart.decided": (
        "Receives the same masked excerpts plus the guardian's verdict."
    ),
}


def registry_problems() -> list[str]:
    """Drift between the parser's vocabulary and this registry, as named problems."""
    problems = []
    for name in sorted(CAPABILITIES - set(CAPABILITY_REGISTRY)):
        problems.append(f"capability_without_risk:{name}")
    for name in sorted(set(CAPABILITY_REGISTRY) - CAPABILITIES):
        problems.append(f"risk_without_capability:{name}")
    for name in sorted(set(EVENT_RISKS) - EVENTS):
        problems.append(f"risk_without_event:{name}")
    for entry in CAPABILITY_REGISTRY.values():
        if not entry.risk.strip() or not entry.title.strip():
            problems.append(f"blank_risk:{entry.id}")
    return problems


def consent_screen(manifest: ExtensionManifest, decision: dict | None = None) -> dict:
    """What an owner reads before agreeing: every capability with its risk sentence,
    the exact declarations, and — when consent exists for another surface — the diff.

    ``decision`` is :meth:`ConsentDecision.as_dict`; its state and diff are copied, not
    recomputed, so the screen and the store can never disagree about what changed.
    """
    decision = decision or {}
    capabilities = []
    for name in manifest.capabilities:
        entry = CAPABILITY_REGISTRY.get(name)
        if entry is None:  # pragma: no cover - registry_problems() is pinned by a test
            raise ValueError(f"capability_without_risk:{name}")
        capabilities.append({"id": entry.id, "title": entry.title, "risk": entry.risk})
    return {
        "extension": manifest.id,
        "version": manifest.version,
        "state": decision.get("consent", "not_granted"),
        "declared_digest": decision.get("declared_digest", ""),
        "capabilities": capabilities,
        "tools": list(manifest.qualified_tools),
        "commands": list(manifest.commands),
        "events": list(manifest.events),
        "event_risks": [{"event": name, "risk": EVENT_RISKS[name]}
                        for name in manifest.events if name in EVENT_RISKS],
        "added_declarations": list(decision.get("added_declarations") or ()),
        "removed_declarations": list(decision.get("removed_declarations") or ()),
    }


def render_screen(screen: dict) -> list[str]:
    """The same screen as plain lines (the CLI prints these before asking)."""
    lines = [f"Extension {screen['extension']} {screen['version']} asks to:"]
    for row in screen["capabilities"]:
        lines.append(f"  * {row['title']} [{row['id']}]")
        lines.append(f"    {row['risk']}")
    for label, key in (("Tools", "tools"), ("Commands", "commands"), ("Events", "events")):
        if screen[key]:
            lines.append(f"  {label}: {', '.join(screen[key])}")
    for row in screen["event_risks"]:
        lines.append(f"  ! {row['event']}: {row['risk']}")
    if screen["state"] == "changed":
        lines.append("You agreed to a different surface before. What changed:")
        lines.extend(f"  + {item}" for item in screen["added_declarations"])
        lines.extend(f"  - {item}" for item in screen["removed_declarations"])
    elif screen["state"] == "granted":
        lines.append("You already agreed to exactly this surface.")
    return lines


__all__ = ["CAPABILITY_REGISTRY", "EVENT_RISKS", "Capability", "consent_screen",
           "registry_problems", "render_screen"]
