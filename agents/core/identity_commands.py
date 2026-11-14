"""Read-only chat identity reports for the running Nerva process (H084)."""

from __future__ import annotations

from . import paths
from .channels.outbound_safety import sanitize_text

_MAX_SOURCE_CHARS = 4096


def _display(value: object, *, limit: int, withheld: str) -> str:
    """Sanitize the entire value before shortening; never expose a secret prefix."""
    raw = str(value)
    if len(raw) > _MAX_SOURCE_CHARS:
        return withheld
    clean = " ".join(sanitize_text(raw).split())
    return clean[:limit] or withheld


def version_command(ctx) -> str:
    """The same canonical version used by the HTTP metadata and /status."""
    from agents import __version__

    if ctx.args.strip():
        return "Usage: /version (no arguments)."
    return _display(f"Nerva {__version__}", limit=128, withheld="Nerva version unavailable.")


def profile_command(ctx) -> str:
    """The process profile ID and its actual profile-local data home."""
    if not ctx.principal.admin:
        return "Only the owner can view the active profile and home."
    if ctx.args.strip():
        return "Usage: /profile (no arguments)."
    try:
        if paths.profile_error():
            return "Active profile unavailable; check the hub configuration."
        profile = paths.profile_name() or "default"
        home = paths.data_root()
    except Exception:
        return "Active profile unavailable; check the hub configuration."
    # Nerva has no independent profile display-name metadata. Keep the serving ID
    # explicit and describe the effective presentation label's real provenance.
    label = _display(profile, limit=64, withheld="(label withheld)")
    display_home = _display(home, limit=512, withheld="(path withheld)")
    return (f"Profile ID: {label}\n"
            f"Display label: {label} (canonical ID; no separate label configured)\n"
            f"Home: {display_home}")


__all__ = ["version_command", "profile_command"]
