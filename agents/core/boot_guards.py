"""
boot_guards.py — O26-P0.6 (finding F6): one set of fail-closed boot checks.

The repo documents two entry points: ``python serve.py`` and
``python -m uvicorn agents.web:app``. The guards below used to live only in
``serve.py``, so the raw-uvicorn path silently skipped both the
unauthenticated-external-bind refusal (AUD-4 analog) and the hardened-profile
precondition check (CDX-12) — a "hardened" box started with an unkeyed audit
chain and never knew. They now live here and run from the app lifespan too,
so every entry point enforces the same posture. ``serve.py`` re-exports them.

A third guard (H23.30 / DRA-07 / DRA-14) refuses to start when a *parse-critical*
posture flag is set to a value no spelling recognizes — the boolean flags below and
the ``JARVIS_TASK_MEDIATION`` mode enum. It runs first, before anything constructs a
memory graph or a task queue.

A fourth guard (Hermes absorption 5b) is the front door: an inbound channel that is
configured must be *guarded* — the inbound pairing gate on (its default), or a
per-channel allowlist of the owner's own ids — or the operator must have written
down ``JARVIS_CHANNEL_OPEN=1``. Otherwise the box refuses to start rather than
answer any stranger who finds the bot. ``assert_front_door`` bundles that guard
with the parse check of its two flags for a caller that runs *after* the ``.env``
files are loaded — the lifespan runs ``enforce_boot_posture`` before them, so a
token that lives only in ``.env`` is invisible to the early pass.

Residual (documented, not silently ignored): a bind host passed only as a raw
uvicorn CLI flag (``--host 0.0.0.0`` without ``JARVIS_HOST``) is invisible to
the app; the lifespan check covers the env-driven deployments (systemd/Docker
templates use ``JARVIS_HOST``), and ``serve.py`` remains the canonical entry.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from typing import NamedTuple

_LOOPBACK_HOSTS = {"", "127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"}

# Flags whose *unrecognized* spelling resolves to the UNSAFE direction. The AUD-14 rule
# (``env_config.truthy``) sends junk to the flag's declared default, which is right
# everywhere the default is the safe position. NERVA_PUBLIC_PROFILE is the inverse: it is a
# default-off opt-in whose "on" position is the safe one, so ``NERVA_PUBLIC_PROFILE=pubic``
# reads as *private* and a public demo box seeds the owner's family into a stranger's graph
# (H23.30; tests/test_public_profile_seed_gate.py). A typo there must stop the boot rather
# than resolve to the default.
#
# JARVIS_CHANNEL_PAIRING and JARVIS_CHANNEL_OPEN (Hermes absorption 5b) decide whether a
# stranger who messages the bot is held or answered. Their defaults are the closed
# position, but an operator who typed a value meant to change the posture must be told
# the spelling was not understood rather than have the box guess which way they meant.
_PARSE_CRITICAL_BOOL_FLAGS = (
    "NERVA_PUBLIC_PROFILE",
    "JARVIS_CHANNEL_PAIRING",
    "JARVIS_CHANNEL_OPEN",
)


def _env_set(*names: str) -> Callable[[Mapping[str, str]], bool]:
    """A channel is configured when every one of *names* is non-empty after strip."""
    return lambda env: all(str(env.get(n, "") or "").strip() for n in names)


def _json_object_set(name: str) -> Callable[[Mapping[str, str]], bool]:
    """A channel map is configured when *name* parses to a non-empty JSON object.

    Mirrors ``env_config.env_json_object``: unset, invalid or non-object wires
    nothing in the app, so there is nothing to guard.
    """
    def _configured(env: Mapping[str, str]) -> bool:
        raw = str(env.get(name, "") or "").strip()
        if not raw:
            return False
        try:
            value = json.loads(raw)
        except ValueError:
            return False
        return isinstance(value, dict) and bool(value)
    return _configured


class _InboundChannel(NamedTuple):
    name: str
    label: str                 # how the refusal names it ("telegram bot")
    configured: Callable[[Mapping[str, str]], bool]
    allowlist_env: str | None  # the owner's own sender ids, when the channel has such a knob


# Every inbound path the app wires that threads a ``sender`` into the gateway — that
# is, every door a stranger can knock on. Each entry mirrors the wiring condition in
# the app lifespan so the guard neither misses a wired door nor refuses one that is
# never wired: Slack receives events automatically only when both its bot token
# and Socket Mode app token are set; bot-token-only hosts retain manual ingress. Only
# Telegram has an allowlist knob; the others rely on pairing. Two doors are outside
# this table on purpose: the admin-minted public widget (``routers/secrets.py``) is an
# intentionally anonymous door governed by its own token and the gateway rate limit,
# never by pairing; and the email channel's sender is the bare address parsed from the
# ``From`` header, which pairing can hold but which any sender can forge unless the
# IMAP provider enforces DMARC — a held stranger, not an authenticated owner.
# (Hermes absorption 5b)
_INBOUND_CHANNELS: tuple[_InboundChannel, ...] = (
    _InboundChannel("telegram", "telegram bot", _env_set("TELEGRAM_BOT_TOKEN"),
                    "TELEGRAM_ALLOWED_USER_IDS"),
    _InboundChannel("discord", "discord bot", _env_set("DISCORD_BOT_TOKEN"), None),
    _InboundChannel("slack", "slack bot", _env_set("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"), None),
    _InboundChannel("webhook", "webhook channel", _json_object_set("JARVIS_WEBHOOK_CHANNELS"),
                    None),
    _InboundChannel("email", "email channel", _env_set("IMAP_HOST", "SMTP_HOST"), None),
)
#: An allowlist counts as a guard once it names at least this many ids.
_MIN_ALLOWLIST_IDS = 1


def assert_safe_bind(host: str) -> None:
    """Fail-closed on an unauthenticated external bind (mirrors WorldView AUD-4).

    Binding to a non-loopback address exposes the unauthenticated public routes
    (``/status``, ``/dashboard``, …) on the network, so we refuse to start unless
    the deployment is either authenticated (a ``JARVIS_USER_TOKEN`` /
    ``JARVIS_ADMIN_TOKEN`` is configured) or the insecure posture is explicitly
    acknowledged with ``JARVIS_ALLOW_INSECURE_BIND=1``. Loopback always allowed.
    """
    if host.strip().lower() in _LOOPBACK_HOSTS:
        return
    has_token = bool(os.environ.get("JARVIS_USER_TOKEN", "").strip()
                     or os.environ.get("JARVIS_ADMIN_TOKEN", "").strip())
    from agents.core.env_config import env_flag
    ack = env_flag("JARVIS_ALLOW_INSECURE_BIND")
    if has_token or ack:
        print(f"[SECURITY] binding to non-loopback host {host!r} — public routes are "
              f"reachable from the network ({'authenticated' if has_token else 'INSECURE, acknowledged'}).")
        return
    raise SystemExit(
        f"Refusing to bind to non-loopback host {host!r} without authentication.\n"
        "Set JARVIS_USER_TOKEN (and/or JARVIS_ADMIN_TOKEN) to require a credential for "
        "remote access, or set JARVIS_ALLOW_INSECURE_BIND=1 to accept an open bind. "
        "The default 127.0.0.1 keeps the hub loopback-only."
    )


def assert_hardened_posture() -> None:
    """Fail-closed on a mis-configured hardened profile (CDX-12).

    ``JARVIS_HARDENED=1`` requires its hard preconditions (today: a
    ``JARVIS_AUDIT_KEY`` so the audit log is HMAC-keyed). A hardened deployment
    that can't meet them is mis-configured, not merely suboptimal, so we refuse
    to start rather than run a weaker posture than the operator asked for.
    No-op when hardening is off.
    """
    from agents.core.security import hardened
    problems = hardened.enforce()
    if problems:
        raise SystemExit(
            "Refusing to start with JARVIS_HARDENED=1:\n  - " + "\n  - ".join(problems)
        )


def _bool_flag_malformed(env: Mapping[str, str], name: str) -> bool:
    """``env_config.env_flag_is_malformed`` over an explicit mapping (Hermes absorption 5b).

    Same rule: unset, empty and whitespace-only are "use the default", not a mistake;
    only a deliberate value no spelling recognizes counts. The value never leaves here.
    """
    from agents.core.env_config import is_recognized_bool

    raw = env.get(name)
    return raw is not None and str(raw).strip() != "" and not is_recognized_bool(raw)


def _unparseable_bool_flags(env: Mapping[str, str], names: tuple[str, ...]) -> None:
    """Raise the shared refusal for every flag in *names* that is set but unparseable."""
    bad = [name for name in names if _bool_flag_malformed(env, name)]
    if bad:
        raise SystemExit(
            "Refusing to start: unparseable value for " + ", ".join(bad) + ".\n"
            "Use one of 1/true/yes/on or 0/false/no/off. An unrecognized spelling silently "
            "falls back to the flag's default — for NERVA_PUBLIC_PROFILE that is the private "
            "install, which seeds the owner's personal knowledge graph, and for "
            "JARVIS_CHANNEL_PAIRING / JARVIS_CHANNEL_OPEN it decides whether a stranger who "
            "messages the bot is held or answered — so this fails closed instead."
        )


def assert_parseable_posture_flags(environ: Mapping[str, str] | None = None) -> None:
    """Fail-closed on a set-but-unparseable posture flag (H23.30 residual).

    This does **not** change the AUD-14 parse: ``env_config`` stays the one parse home and
    still never raises, so ``env_flag("NERVA_PUBLIC_PROFILE")`` keeps returning the declared
    default for a typo. What changes is that the box no longer *starts* with that typo, so
    the operator fixes the spelling instead of shipping the wrong posture silently. Unset,
    empty and whitespace-only mean "unset", exactly as ``env_flag`` treats them.

    The message names the variable and the accepted spellings, never the offending value —
    ``env_config``'s module contract is that nothing here logs values, and a future entry in
    ``_PARSE_CRITICAL_BOOL_FLAGS`` may well be sensitive.

    ``environ`` is the mapping the boolean flags are read from (``os.environ`` by
    default) so a caller holding a loaded ``.env`` gets the same verdict the process
    env would; the task-mediation mode has no mapping form and is read from
    ``os.environ`` by its own helper. (Hermes absorption 5b)
    """
    env = os.environ if environ is None else environ
    _unparseable_bool_flags(env, _PARSE_CRITICAL_BOOL_FLAGS)
    # Same rule, non-boolean flag: JARVIS_TASK_MEDIATION selects the B7 tamper-evidence
    # posture (off|hold|enforce) and its default, `off`, is the UNPROTECTED position — so
    # `JARVIS_TASK_MEDIATION=enfroce` must stop the boot, not quietly disable mediation.
    from agents.core.autonomy.mediation_head_store import (
        MALFORMED_MODE_MESSAGE,
        task_mediation_mode_is_malformed,
    )

    if task_mediation_mode_is_malformed():
        raise SystemExit(MALFORMED_MODE_MESSAGE)


def _count_allowlisted_ids(raw: str | None) -> int:
    """How many usable ids a comma-separated allowlist names.

    One parse, shared with the runtime gate (``pairing.parse_sender_allowlist``), so
    the guard cannot count an id the gate would not honour. Only the count leaves
    this function: the ids are the owner's, and nothing in a boot message should
    echo them. (Hermes absorption 5b)
    """
    from agents.core.channels.pairing import parse_sender_allowlist

    return len(parse_sender_allowlist(raw))


def _front_door_flags(env: Mapping[str, str]) -> tuple[bool, bool]:
    """``(pairing_on, open_acknowledged)`` read from one mapping (Hermes absorption 5b).

    The same defaults as ``pairing.pairing_enabled`` / ``channel_open_acknowledged``
    (on, off) through the same parse, so a caller handing in a captured environment
    gets the verdict that environment deserves — not a mix of its tokens with the
    process's flags. With ``os.environ`` the two agree by construction.
    """
    from agents.core.channels.pairing import CHANNEL_OPEN_ENV, PAIRING_ENV
    from agents.core.env_config import truthy

    return truthy(env.get(PAIRING_ENV), True), truthy(env.get(CHANNEL_OPEN_ENV), False)


def assert_guarded_channels(environ: Mapping[str, str] | None = None) -> None:
    """Fail-closed on an inbound channel that would answer any sender (Hermes absorption 5b).

    A bot token, a webhook map or an inbox turns a public network into a front door:
    whoever finds it can type at the house. The door is *guarded* when the inbound
    pairing gate is on (its default — strangers are held until the owner pairs them)
    or, for channels that have one, when an allowlist names at least one of the
    owner's own ids. A configured channel that is neither is refused at boot. The one
    way past is the operator writing ``JARVIS_CHANNEL_OPEN=1``, which is honoured with
    a ``[SECURITY]`` line on the console so the open posture is never silent.

    Everything — the channel configuration, the allowlist and the two posture flags —
    is read from ``environ`` (``os.environ`` by default), so the verdict belongs to one
    environment. The refusal names the channel and the remedies — never a token,
    never an id.
    """
    env = os.environ if environ is None else environ
    pairing_on, acknowledged = _front_door_flags(env)
    for channel in _INBOUND_CHANNELS:
        if not channel.configured(env):
            continue
        allowlisted = (
            channel.allowlist_env is not None
            and _count_allowlisted_ids(env.get(channel.allowlist_env)) >= _MIN_ALLOWLIST_IDS
        )
        if pairing_on or allowlisted:
            continue
        if acknowledged:
            print(f"[SECURITY] {channel.label} answers any sender (JARVIS_CHANNEL_OPEN acknowledged).")
            continue
        remedies = []
        if channel.allowlist_env is not None:
            remedies.append(f"set {channel.allowlist_env} to your own ids")
        remedies.append("leave JARVIS_CHANNEL_PAIRING on and pair from the HUD")
        remedies.append("acknowledge an open bot with JARVIS_CHANNEL_OPEN=1")
        raise SystemExit(
            f"Refusing to start: the {channel.label} would answer any sender.\n"
            "JARVIS_CHANNEL_PAIRING is off and nothing else guards the front door. "
            "Either " + ", or ".join(remedies) + "."
        )


#: The two flags the front door decides on; a typo in either must refuse, not guess.
_FRONT_DOOR_FLAGS = ("JARVIS_CHANNEL_PAIRING", "JARVIS_CHANNEL_OPEN")


def assert_front_door(environ: Mapping[str, str] | None = None) -> None:
    """The front-door guard for a caller that runs after ``.env`` is loaded.

    ``enforce_boot_posture`` runs at the top of the app lifespan, *before* the repo
    and user ``.env`` files are read, so a bot token or a ``JARVIS_CHANNEL_PAIRING=0``
    that lives only there is invisible to it and the early pass is decorative for
    the documented install path. This is the same checks — a typo in either
    front-door flag refuses, a malformed trusted-proxy or allowed-host list refuses,
    then the channel guard — over whatever environment the caller holds at the
    moment the channels are about to be wired. It re-checks rather than trusting
    the early pass because the environment has changed in between. The web
    lifespan calls it right after ``load_agents`` (which loads ``.env``) and before
    any channel is constructed. (Hermes absorption 5b)
    """
    env = os.environ if environ is None else environ
    _unparseable_bool_flags(env, _FRONT_DOOR_FLAGS)
    # The two network-edge lists live in ``.env`` too (that is where .env.example
    # puts them), so their parse check has the same blind spot as the front door
    # when it runs early: re-run it over the loaded environment.
    from agents.core.host_policy import assert_parseable_allowed_hosts
    from agents.core.proxy_trust import assert_parseable_trusted_proxies

    assert_parseable_trusted_proxies(env)
    assert_parseable_allowed_hosts(env)
    assert_guarded_channels(env)


def enforce_boot_posture() -> None:
    """Run every boot guard from the app itself (called by the web lifespan).

    The order is part of the contract: the parse checks come first — the posture
    flags, then the two network-edge lists (Hermes absorption 5b) — so a value the
    box cannot read is refused before any guard reasons about the posture that
    value was meant to set. Then the bind, then the front door, then the hardened
    profile. The bind host is read from ``JARVIS_HOST`` (the knob the deploy
    templates and ``serve.py`` use); see the module docstring for the raw-CLI
    residual.
    """
    # First: a mistyped posture flag must be refused before anything constructs a
    # MemoryManager or touches the graph.
    assert_parseable_posture_flags()
    # A trust-widening list (which peers may name the real client) or a
    # host-accepting list (which names this box answers to) that cannot be parsed
    # must stop the boot, not degrade: the runtime parse fails closed on its own,
    # but an operator who believes the proxy is trusted or the tailnet name is
    # allowed would otherwise debug a box that silently ignores what they wrote —
    # and the likely next move is a wildcard. (Hermes absorption 5b)
    from agents.core.host_policy import assert_parseable_allowed_hosts
    from agents.core.proxy_trust import assert_parseable_trusted_proxies

    assert_parseable_trusted_proxies()
    assert_parseable_allowed_hosts()
    assert_safe_bind(os.environ.get("JARVIS_HOST", "127.0.0.1"))
    # The front door (Hermes absorption 5b): a configured inbound channel must be
    # guarded. Runs again as ``assert_front_door`` once ``.env`` has been loaded.
    assert_guarded_channels()
    assert_hardened_posture()
