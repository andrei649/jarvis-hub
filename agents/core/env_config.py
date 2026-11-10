"""
env_config.py — O26-P2.1 (AUD-14): ONE home for reading environment variables.

Before this module the tree had 163 env-read sites with EIGHT divergent
boolean conventions — ``.lower() in ("1","true","yes")`` (no "on"),
``("1","true","yes","on")``, case-sensitive ``("1","true","True")`` where
"TRUE" silently meant off, negated-falsy ``not in ("0","false","False")``
where "off" silently meant on, exact ``== "1"``, inverted disable-flags,
presence checks, and one helper (`_env_int`) written twice. The same var
could parse differently in two files (JARVIS_WORKFLOW_PERSIST=0 *enabled*
the coordinator drain while the engine read it as off).

The rules here:

- **Leaf module.** Standard library only (``os``). No imports from
  ``agents.core`` — anything (web.py, orchestrator, kernel, security,
  routers) may import this at module top without a cycle. The module is
  stateless, so the dual import identity (``core.env_config`` and
  ``agents.core.env_config`` are distinct module objects) is harmless.
- **Read at call time, never cache.** ~210 ``monkeypatch.setenv`` sites in
  the test suite assert that flag functions re-read the environment on every
  call. Env reads are cheap; correctness beats micro-optimization.
- **Never raise, never log values.** Getters degrade to their default on
  garbage input; many vars are credentials, so nothing here prints, logs,
  or enumerates values.
- **No side effects.** This module must NOT load ``.env`` — dotenv loads
  late (plugin build, inside the app lifespan, ``override=False``) and
  moving it earlier would silently activate ``.env`` keys for import-time
  posture reads (DEV_MODE, admin tokens). That is a posture change, not a
  refactor.
- **Unknown spellings resolve to the flag's DEFAULT, in both directions.**
  Historically, default-off opt-ins parsed with truthy-membership (junk →
  off) while default-on strict flags parsed with falsy-membership (junk →
  on). Both meant the same thing: *unrecognized input falls back to the
  declared default*. ``truthy(value, default)`` says it once, so a typo in
  JARVIS_ALLOW_INSECURE_BIND can never open the bind, and a typo in
  JARVIS_STRICT_EGRESS can never relax egress.

- **Two spellings, one variable (RB-2).** Every hub variable ``JARVIS_<X>`` is also
  read as ``NERVA_<X>``, the preferred spelling; ``JARVIS_<X>`` is deprecated and
  keeps working. ``other_spelling`` is THE map between the two names and
  ``resolve_spellings`` THE rule for a pair; every getter here reads through them at
  call time, so it needs no help from anyone. Code that reads ``os.environ`` directly
  keeps reading the ``JARVIS_`` name: ``env_alias`` folds a ``NERVA_`` spelling onto
  it at process start and after each ``.env`` layer, and refuses the boot when the
  two disagree (this module never raises, so it cannot; there is no "wins").

What does NOT belong here: the settings-DB plane (``settings_db.get_value``
is live-updatable /admin state with its own precedence at each call site),
composition/override logic (JARVIS_HARDENED forcing strict egress or
blocking mutating MCP stays with its owners), and the BUG-14 LOCAL_ONLY
floor (``hybrid_router.LOCAL_ONLY_AGENTS`` stays a code-enforced constant
that no env var — through this module or otherwise — can weaken).
"""

from __future__ import annotations

import json
import os

TRUTHY_SPELLINGS = frozenset({"1", "true", "yes", "on"})
FALSY_SPELLINGS = frozenset({"0", "false", "no", "off", "disable", "disabled"})


def truthy(value: object, default: bool = False) -> bool:
    """THE boolean parse: case-insensitive spellings, unknown → *default*.

    ``truthy`` on 1/true/yes/on; falsy on 0/false/no/off/disable/disabled;
    ``None``, empty/whitespace, and unrecognized strings resolve to
    *default* so a mis-spelled value can never flip a flag away from its
    declared posture. Non-strings are stringified first (settings values
    arrive as bool/int sometimes) — ``True``/``1`` stringify into the
    truthy set, ``False``/``0`` into the falsy set.
    """
    if value is None:
        return default
    text = str(value).strip().lower()
    if not text:
        return default
    if text in TRUTHY_SPELLINGS:
        return True
    if text in FALSY_SPELLINGS:
        return False
    return default


def is_recognized_bool(value: object) -> bool:
    """True when *value* spells a boolean this module actually recognizes.

    The companion to :func:`truthy`, which deliberately never tells its caller
    whether it *understood* the input or fell back to the default. Both answers
    are correct at a call site; a boot guard needs the second one so a typo in a
    posture flag can be refused instead of silently resolving (see
    ``boot_guards.assert_parseable_posture_flags``). Purely a question about the
    spelling — it does not parse, and it does not change what ``truthy`` returns.
    """
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in TRUTHY_SPELLINGS or text in FALSY_SPELLINGS


#: RB-2 — the deprecated and the preferred prefix of the hub's own variables.
DEPRECATED_PREFIX, PREFERRED_PREFIX = "JARVIS_", "NERVA_"


def is_hub_name(name: object) -> bool:
    """Whether *name* is one of the hub's own ``JARVIS_`` variables (``HUB_ENV_SUFFIXES``)."""
    return isinstance(name, str) and name.startswith(DEPRECATED_PREFIX) and other_spelling(name) is not None


def other_spelling(name: object) -> str | None:
    """THE map between the two spellings of a hub variable (RB-2).

    ``JARVIS_X`` gives ``NERVA_X`` and back, for the hub's own names only. ``None`` for
    anything else: another program's variable, and a ``NERVA_*`` variable that is its own
    (``NERVA_HUB_URL``, ``NERVA_WORKSPACE*`` — no ``JARVIS_`` name shares their suffix).
    A fixed name is one dictionary lookup (``_OTHER``, built once below); only a name
    with one of the two prefixes that is not in it is looked at again, for the run-time
    families.
    """
    try:
        found = _OTHER.get(name)
    except TypeError:                       # not hashable: not a name
        return None
    if found is not None or not isinstance(name, str):
        return found
    if name.startswith(_DEPRECATED_FAMILIES):
        return PREFERRED_PREFIX + name[len(DEPRECATED_PREFIX):]
    if name.startswith(_PREFERRED_FAMILIES):
        return DEPRECATED_PREFIX + name[len(PREFERRED_PREFIX):]
    return None


def resolve_spellings(environ, name: str) -> tuple[str | None, str | None]:
    """THE rule for a pair (RB-2): ``(value, the spelling that supplied it)`` for *name*
    read from *environ* under either spelling; ``(None, None)`` when neither is set.

    One spelling set: that one. Both set to the same value: that value, under the
    preferred ``NERVA_`` spelling. One of them blank: the other, because blank means "not
    set" everywhere in this module (a compose file that forwards both names hands the
    unused one over empty). Both set, different: there is no "wins" — every entry point
    refuses to start on that (``env_alias.refuse_conflicts``) — and until it has, this
    returns the ``JARVIS_`` value, which is what a direct ``os.environ`` reader of the
    same variable sees, so the two kinds of reader can never disagree.
    Never raises, never logs and never returns anything but what *environ* holds.
    """
    other = other_spelling(name)
    if other is None:
        value = environ.get(name)
        return value, (name if value is not None else None)
    preferred, legacy = (name, other) if name.startswith(PREFERRED_PREFIX) else (other, name)
    new, old = environ.get(preferred), environ.get(legacy)
    if new is None:
        return old, (legacy if old is not None else None)
    if old is None or new == old or not str(old).strip():
        return new, preferred
    return old, legacy


def _read(name: str) -> str | None:
    """The process environment's value for *name*, under either spelling, at call time
    (``resolve_spellings``' rule, written out for the hot path). One dictionary lookup
    decides whether *name* has a second spelling; a name without one costs a single
    ``os.environ`` read, as before RB-2, and a hub variable costs two — no string is
    built either way."""
    other = _OTHER.get(name)
    if other is None:
        if not name.startswith(_BOTH_PREFIXES):
            return os.environ.get(name)
        other = other_spelling(name)            # a run-time family, or not a hub name
        if other is None:
            return os.environ.get(name)
    if name.startswith(PREFERRED_PREFIX):
        new, old = os.environ.get(name), os.environ.get(other)
    else:
        old, new = os.environ.get(name), os.environ.get(other)
    if new is None:
        return old
    if old is None or new == old or not old.strip():
        return new
    return old


def env_flag_is_malformed(name: str) -> bool:
    """True when env var *name* is SET to a value no spelling recognizes.

    Unset, empty, and whitespace-only are the documented "use the declared
    default" state, not a mistake — only a deliberate but unparseable value
    counts. Callers get the variable name, never the value (this module never
    logs or returns values).
    """
    raw = _read(name)
    return raw is not None and raw.strip() != "" and not is_recognized_bool(raw)


# python-dotenv's own off switch, with python-dotenv's own spellings (its check in
# dotenv.main), not Nerva's truthy convention: it has to agree with the library that
# reads it (H273, env_provenance). This module still loads no .env file.
_DOTENV_DISABLED_SPELLINGS = frozenset({"1", "true", "t", "yes", "y"})


def dotenv_disabled(environ=None) -> bool:
    """Whether PYTHON_DOTENV_DISABLED stops python-dotenv loading any .env file."""
    environ = os.environ if environ is None else environ
    value = environ.get("PYTHON_DOTENV_DISABLED")
    return value is not None and value.casefold() in _DOTENV_DISABLED_SPELLINGS


def env_flag(name: str, default: bool = False) -> bool:
    """Boolean env flag with an explicit default direction.

    ``env_flag("JARVIS_HARDENED")`` — opt-in, off unless explicitly on.
    ``env_flag("JARVIS_LLM_WARMUP", True)`` — default-on, off only when
    explicitly disabled. Unset, empty, or unrecognized → *default*.
    """
    return truthy(_read(name), default)


def env_str(name: str, default: str = "") -> str:
    """Raw string env read (no strip — callers that trim, trim themselves)."""
    value = _read(name)
    return default if value is None else value


def env_list(name: str, default: list[str] | None = None, sep: str = ",") -> list[str]:
    """Best-effort separated string list: trims entries and skips blanks."""
    fallback = list(default or [])
    raw = (_read(name) or "").strip()
    if not raw:
        return fallback
    return [entry for entry in (part.strip() for part in raw.split(sep)) if entry]


def env_int(name: str, default: int, minimum: int | None = None) -> int:
    """Best-effort int: unset, blank, or non-numeric → *default* (never raises).

    With *minimum*, an out-of-range value also falls back to *default*
    (e.g. a negative VRAM budget) — fall back, not clamp: a nonsense value
    means the operator's intent is unknown, so the shipped default wins.
    """
    raw = (_read(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return default
    return value


def env_float(name: str, default: float, minimum: float | None = None) -> float:
    """Best-effort float: unset, blank, non-numeric, or out-of-range → *default*."""
    raw = (_read(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return default
    return value


def env_json_object(name: str, default: dict | None = None) -> dict:
    """Best-effort JSON object: unset, invalid, or non-object → *default*.

    This is for structured env knobs such as provider config maps. It never
    raises and returns a fresh dict so callers cannot mutate a shared fallback.
    """
    fallback = dict(default or {})
    raw = (_read(name) or "").strip()
    if not raw:
        return fallback
    try:
        value = json.loads(raw)
    except ValueError:
        return fallback
    if not isinstance(value, dict):
        return fallback
    return dict(value)


def env_int_map(name: str, default: dict[str, int] | None = None) -> dict[str, int]:
    """Best-effort ``key:int`` map: bad entries are skipped, never raised.

    Format is a comma-separated list such as ``"whatsapp:10,teams:30"``.
    Whitespace is ignored around keys and values; blank keys, missing separators,
    and non-integer values are omitted. A fresh dict is returned every time.
    """
    fallback = dict(default or {})
    raw = (_read(name) or "").strip()
    if not raw:
        return fallback
    out: dict[str, int] = {}
    for pair in raw.split(","):
        key, sep, value = pair.strip().partition(":")
        key = key.strip()
        if not sep or not key:
            continue
        try:
            out[key] = int(value)
        except ValueError:
            continue
    return out


# ── RB-2: the hub's own environment variable names (data only) ────────────────────
#
# Every ``JARVIS_<X>`` variable the hub reads is also accepted as ``NERVA_<X>`` (the
# preferred spelling since the product rename; ``JARVIS_<X>`` is the deprecated one).
# The alias applies to the names listed here and nothing else: a ``NERVA_*`` variable
# that is its own variable (``NERVA_HUB_URL``, ``NERVA_WORKSPACE*``,
# ``NERVA_PUBLIC_PROFILE``, a plugin's, a test harness's) is never touched, because no
# hub variable shares its suffix (``tests/test_rb2_env_alias_inventory.py`` fails if one
# ever does).
#
# The list is measured, not remembered: that test reads ``agents/``, ``scripts/`` and
# ``serve.py`` and fails when a ``JARVIS_`` name in the source is missing here, so a new
# variable cannot ship without its ``NERVA_`` spelling. The names are stored as the
# ``<X>`` both spellings share (no prefix), which also keeps this list out of the way of
# the source scans that pin where a given variable may be mentioned. It lives at the end
# of this module (the getters above read it at call time) so the module stays a leaf.

#: ``<X>`` of every fixed ``JARVIS_<X>`` variable name in the hub's source.
HUB_ENV_SUFFIXES = frozenset({
    "A2A_ENABLED", "A2A_KEY", "ACQUISITION_SANDBOX_IMAGE", "ACTION_KERNEL", "ADMIN_TOKEN",
    "ALLOWED_HOSTS", "ALLOW_INSECURE_BIND", "ANALYTICS_MAX_EVENTS", "APP_ROOT", "AUDIT_KEY",
    "AUTO_DEEP", "AUX_ACQUISITION_CAPABILITY_MODEL", "AUX_ACQUISITION_DRAFT_MODEL",
    "AUX_COMPRESSION_MODEL", "AUX_ONESHOT_MODEL", "AUX_QUERY_REWRITE_MODEL", "AUX_REVIEW_MODEL",
    "AUX_SESSION_TITLE_MODEL", "AUX_SOUL_DESCRIPTION_MODEL", "BACKUP_KEY", "BACKUP_MAX_BYTES",
    "BACKUP_MAX_MEMBERS", "BACKUP_QUICK_KEEP", "BINARY_ARTIFACTS", "BROWSER_ALLOWED_DOMAINS",
    "BROWSER_ALLOW_PRIVATE_URLS", "BUDGET_MAX_DEPTH", "BUDGET_MAX_TOKENS",
    "BUDGET_MAX_WALL_SECONDS", "CALL_CONFIG", "CALL_LIVE", "CA_BUNDLE", "CHANNEL_OPEN",
    "CHANNEL_PAIRING", "CHANNEL_SEND_RATE", "CHANNEL_SEND_RATES", "COMFYUI_CHECKPOINT",
    "COMFYUI_CHECKPOINTS", "COMFYUI_URL", "COMPANY_MODE", "CONTAINER", "CORS_ORIGINS", "CSP",
    "DEEP_MODEL", "DESKTOP_HOST", "DESKTOP_ISOLATED", "DEVICE_ID", "DISABLE_CSP", "DRIVE_AI_DEST",
    "DRIVE_AI_FLAGS", "DRIVE_AI_INDEX", "DRIVE_AI_MODE", "DRIVE_AI_REMOTE", "DRIVE_AI_SYNC",
    "E2E_SYNC", "E2E_SYNC_KEY", "EMAIL_REPLY_MAX_PER_HOUR", "ENV", "ENVIRONMENT_HINT", "EVAL_LIVE",
    "EVAL_LIVE_MIN_SCORE", "EVAL_LIVE_MODEL", "EVAL_LIVE_URL", "EVAL_STORE", "EXEC_TEMP_DIR",
    "FAULT_INJECT", "FILE_MAX_BYTES", "FILE_ROOTS", "FILE_TOOLS", "FORGET_ARCHIVE_DIR",
    "FORGET_ARCHIVE_KEEP", "H30_HA_LIVE", "H30_HA_TOKEN", "H31_FRIGATE_CAMERA_ID",
    "H31_FRIGATE_LIVE", "H31_FRIGATE_ORIGIN", "H31_FRIGATE_TOKEN", "HARDENED", "HA_ALLOWED_HOSTS",
    "HA_TOKEN_REF", "HA_URL", "HERMES_BRIDGE_TOKEN", "HERMES_BRIDGE_URL", "HERMES_ENABLED",
    "HERMES_GENERATION", "HESTIA_BRIDGE", "HOME", "HOME_ASSISTANT", "HOST", "HOUSE_BRAIN",
    "HOUSE_PRESENCE", "HUD", "INBOUND_BATCH_MAX_MS", "INBOUND_BATCH_MS", "KEEP_AWAKE", "KEY_DIR",
    "LATEST_CI_COMMIT", "LLM_WARMUP", "LMSTUDIO_CHAT_CONTROL", "LMSTUDIO_CONTROL", "LM_STUDIO_URL",
    "LOCAL_IMAGE_BACKENDS", "LOCAL_IMAGE_DEFAULT_BACKEND", "LOCAL_IMAGE_GENERATION",
    "LOCAL_IMAGE_PROVIDERS", "LOG_BACKUPS", "LOG_FILE", "LOG_LEVEL", "LOG_MAX_MB", "LOG_REDACTION",
    "MACHINE_ID", "MCP_HTTP_CLIENT", "MCP_MUTATING_TOOLS", "MCP_ROUTE_TOOLS",
    "MCP_STDIO_ALLOWED_ENV", "MCP_STDIO_ENV_BASELINE", "MEDIA_CATALOG", "MEDIA_DIRECTOR",
    "MEDIA_DRIVERS", "MEDIA_PRESENCE_ROOM", "MEDIA_ROOTS", "MEDIA_URL_ALLOWLIST", "MEMORY_DIR",
    "MIC_MUTED", "MODEL_INFO", "MODEL_MANAGER", "MODEL_PULL", "NOUS_ANTHROPIC_WIRE",
    "NOUS_CLIENT_ID", "NOUS_INFERENCE_BASE_URL", "NOUS_PORTAL_URL", "OLLAMA_URL", "ORACLE_WATCH",
    "OSINT_ENRICH", "PASSIVE_CAPTURE", "PERMISSION_LEDGER", "PLAYWRIGHT_BROWSER",
    "PLAYWRIGHT_DOWNLOAD_DIR", "PLAYWRIGHT_HEADLESS", "PLAYWRIGHT_HOST", "PLUGIN_GRANTS",
    "PLUGIN_LEAST_PRIVILEGE", "PORT", "PROFILE", "PROVENANCE", "PROVIDER_PLUGINS", "RATE_LIMIT",
    "REALITY_HARNESS", "REQUIRE_REVIEWED_SKILLS", "REQUIRE_SIGNED_SKILLS",
    "RESTART_PREDECESSOR_WAIT_SECONDS", "RESTORE_RUNTIME_WAIT_SECONDS", "RESTORE_STAGE_TTL_HOURS",
    "ROOM_AWARE_VOICE", "ROOT_PATH", "RUNTIME_CYCLE_SECONDS", "RUNTIME_FAKE_LLM", "RUNTIME_LOG",
    "RUNTIME_RESPAWN_DELAY", "RUNTIME_RESTORE_GRACE_SECONDS", "RUNTIME_RESTORE_POLL",
    "RUNTIME_STATE", "SAFE_MODE", "SCANNER_EXTRA_PATTERNS", "SECRET_KEY", "SELF_RESTART",
    "SESSION_BACKUP_KEEP", "SHUTDOWN_TIMEOUT", "SIGNAL_LAYER", "SIGNAL_LAYER_MODE", "SIGNAL_GOVERNANCE", "SKILL_ENVIRONMENTS",
    "SKILL_HISTORY", "SKILL_SIGNING_KEY", "SMART_APPROVALS", "SMART_APPROVAL_DENY",
    "SMART_APPROVAL_POLICY", "SMART_DENIAL_BREAKER_THRESHOLD", "SOCIAL_LIVE", "SOUL_MAX_CHARS",
    "STRICT_EGRESS", "STRICT_LOCAL", "STRICT_MODELS", "STT_BEAM_SIZE", "STT_COMPUTE_TYPE",
    "SUBAGENT_SPAWN_LOG", "SYSTEM_PROFILE", "TASK_MAX_SECONDS", "TASK_MEDIATION",
    "TERMINAL_CHECKPOINTS", "TERMINAL_LOCAL_HOST", "TERMINAL_LOCAL_ROOTS", "TERMINAL_TARGETS",
    "TERMINAL_TIMEOUT_S", "TESTING", "TLS_INSECURE_TARGETS", "TOKEN_KEY", "TRUSTED_PROXIES", "TZ",
    "TRUSTED_PROXY", "UNIFIED_ACTION_API", "USER_HOME", "USER_TOKEN", "VIDEO_ANALYSIS",
    "VOICE_COMMANDS", "VOICE_COMMAND_TIMEOUT_S", "VRAM_RESERVE_MB", "VRAM_TOTAL_MB", "WASM_PYTHON",
    "WEBHOOK_CHANNELS", "WEB_BACKEND", "WEB_BLOCKED_DOMAINS", "WEB_PROVIDER_TIER", "WEB_RESCUE",
    "WLED_URL", "WORKFLOW_PERSIST", "WRITEBACK_LIVE",
})

#: Name families built at run time (``JARVIS_ROLE_<NAME>_MODEL``, ``JARVIS_VLM_<PRESET>…``,
#: ``JARVIS_TERMINAL_SSH_<HOST>…``): any ``<X>`` with one of these prefixes is a hub name.
HUB_ENV_FAMILIES = ('ROLE_', 'VLM_', 'TERMINAL_SSH_')

#: Prefixes in the source that are deliberately NOT aliased: the private control channel
#: the hub hands a sandboxed child (``JARVIS_RPC_*``, ``JARVIS_TOOL_RPC_*``). It is not
#: operator configuration, and nothing outside the hub may name it under any spelling
#: (``code_env`` refuses both prefixes).
UNALIASED_FAMILIES = ("RPC_", "TOOL_RPC_")


def _other_spellings() -> dict[str, str]:
    table: dict[str, str] = {}
    for suffix in HUB_ENV_SUFFIXES:
        table[DEPRECATED_PREFIX + suffix] = PREFERRED_PREFIX + suffix
        table[PREFERRED_PREFIX + suffix] = DEPRECATED_PREFIX + suffix
    return table


#: Either spelling of every fixed hub variable -> the other one (``other_spelling``).
_OTHER = _other_spellings()
_BOTH_PREFIXES = (DEPRECATED_PREFIX, PREFERRED_PREFIX)
_DEPRECATED_FAMILIES = tuple(DEPRECATED_PREFIX + prefix for prefix in HUB_ENV_FAMILIES)
_PREFERRED_FAMILIES = tuple(PREFERRED_PREFIX + prefix for prefix in HUB_ENV_FAMILIES)
