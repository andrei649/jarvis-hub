"""H595 environment names allowed into an execute_code interpreter.

The host calls ``declare`` only after a successful owner-vouched SKILL.md view.
The registry stores names, never values. A fresh validator can bind a declaration
to the exact skill/catalog/trust snapshot that was viewed. The spawn path resolves
names in its trusted invocation scope and supplies a scoped value reader to
``prepare_code_env`` before starting the interpreter.
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from itertools import islice
from threading import RLock

_NAME = re.compile(r"[A-Z_][A-Z0-9_]{0,127}\Z")
_MAX_ID_LENGTH = 256

# These are location/context hints already passed by Nerva's scrub_child_env and
# Hermes' _HERMES_CHILD_ALLOWED. A broad JARVIS_/HERMES_ prefix is never safe.
_OPERATIONAL_NAMES = frozenset({
    "JARVIS_HOME", "JARVIS_PROFILE", "JARVIS_ENV",
    "HERMES_HOME", "HERMES_PROFILE", "HERMES_CONFIG", "HERMES_ENV",
    "HERMES_DELEGATED_CHILD_CONTEXT",
})

# Exact Hermes-managed provider, tool and gateway values from the pinned donor's
# local_env_policy.py, with Nerva provider-registry additions. A declared skill
# cannot re-grant one of these (GHSA-rhgp-j443-p4rf). Keep this exact-name set:
# an unrelated third-party key such as MY_CUSTOM_KEY remains declarable.
_MANAGED_NAMES = frozenset({
    "OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_API_BASE", "OPENAI_ORG_ID",
    "OPENAI_ORGANIZATION", "OPENROUTER_API_KEY", "ANTHROPIC_BASE_URL",
    "ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN", "LLM_MODEL", "GOOGLE_API_KEY",
    "VERTEX_CREDENTIALS_PATH", "GOOGLE_APPLICATION_CREDENTIALS", "DEEPSEEK_API_KEY",
    "MISTRAL_API_KEY", "GROQ_API_KEY", "TOGETHER_API_KEY", "PERPLEXITY_API_KEY",
    "COHERE_API_KEY", "FIREWORKS_API_KEY", "XAI_API_KEY", "HELICONE_API_KEY",
    "PARALLEL_API_KEY", "FIRECRAWL_API_KEY", "FIRECRAWL_API_URL",
    "TELEGRAM_HOME_CHANNEL", "TELEGRAM_HOME_CHANNEL_NAME", "DISCORD_HOME_CHANNEL",
    "DISCORD_HOME_CHANNEL_NAME", "DISCORD_REQUIRE_MENTION",
    "DISCORD_FREE_RESPONSE_CHANNELS", "DISCORD_AUTO_THREAD", "SLACK_HOME_CHANNEL",
    "SLACK_HOME_CHANNEL_NAME", "SLACK_ALLOWED_USERS", "WHATSAPP_ENABLED",
    "WHATSAPP_MODE", "WHATSAPP_ALLOWED_USERS", "SIGNAL_HTTP_URL", "SIGNAL_ACCOUNT",
    "SIGNAL_ALLOWED_USERS", "SIGNAL_GROUP_ALLOWED_USERS", "SIGNAL_HOME_CHANNEL",
    "SIGNAL_HOME_CHANNEL_NAME", "SIGNAL_IGNORE_STORIES", "HASS_TOKEN", "HASS_URL",
    "EMAIL_ADDRESS", "EMAIL_PASSWORD", "EMAIL_IMAP_HOST", "EMAIL_SMTP_HOST",
    "EMAIL_HOME_ADDRESS", "EMAIL_HOME_ADDRESS_NAME", "HERMES_DASHBOARD_SESSION_TOKEN",
    "GATEWAY_ALLOWED_USERS", "GH_TOKEN", "GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY_PATH",
    "GITHUB_APP_INSTALLATION_ID", "MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET",
    "DAYTONA_API_KEY", "GATEWAY_RELAY_ID", "GATEWAY_RELAY_SECRET",
    "GATEWAY_RELAY_DELIVERY_KEY", "VERCEL_OIDC_TOKEN", "VERCEL_TOKEN",
    "VERCEL_PROJECT_ID", "VERCEL_TEAM_ID", "AWS_BEARER_TOKEN_BEDROCK",
    # Nerva's builtin provider registry and host controls.
    "GEMINI_API_KEY", "DEEPINFRA_API_KEY", "OPENROUTER_BASE_URL",
    "DEEPINFRA_BASE_URL", "JARVIS_NOUS_INFERENCE_BASE_URL",
    "JARVIS_LM_STUDIO_URL", "JARVIS_OLLAMA_URL", "GITHUB_TOKEN",
})

# These names either load code, alter the host's controlled child base, or carry
# private RPC/control authority. They cannot be supplied by a skill or config.
_CONTROL_NAMES = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM", "TMP", "TEMP", "TMPDIR",
    "TZ", "LANG", "ENV", "BASH_ENV", "PROMPT_COMMAND", "NODE_OPTIONS", "RUBYOPT",
    "PERL5OPT", "JAVA_TOOL_OPTIONS", "ELECTRON_RUN_AS_NODE", "SSL_CERT_FILE",
    "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "VIRTUAL_ENV",
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "APPDATA",
    "LOCALAPPDATA", "USERPROFILE", "USERNAME", "HOMEDRIVE", "HOMEPATH",
})
_CONTROL_PREFIXES = (
    "PYTHON", "LD_", "DYLD_", "GIT_CONFIG", "JARVIS_RPC_", "HERMES_RPC_",
    "JARVIS_TOOL_RPC_", "HERMES_TOOL_RPC_", "GATEWAY_RELAY_", "CODEX_",
    "LC_", "XDG_", "CONDA_",
)


def _valid_name(name: object) -> bool:
    return isinstance(name, str) and _NAME.fullmatch(name) is not None


def _passable_name(name: object) -> bool:
    if not _valid_name(name):
        return False
    upper = name.upper()
    if upper in _MANAGED_NAMES or upper in _CONTROL_NAMES:
        return False
    if upper.startswith(_CONTROL_PREFIXES):
        return False
    return not upper.startswith(("AUXILIARY_", "JARVIS_", "HERMES_"))


@dataclass(frozen=True, repr=False)
class _Declaration:
    names: frozenset[str]
    expires_at: float
    validator: Callable[[], bool] | None


class CodeEnvRegistry:
    """Bounded host-owned permissions for one exact owner/agent/session scope."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        ttl_seconds: float = 3600,
        max_scopes: int = 256,
        max_variables: int = 64,
    ) -> None:
        if not callable(clock) or not 0 < ttl_seconds <= 86_400:
            raise ValueError("invalid code environment clock or lifetime")
        if not 1 <= max_scopes <= 4096 or not 1 <= max_variables <= 256:
            raise ValueError("invalid code environment capacity")
        self._clock = clock
        self._ttl = float(ttl_seconds)
        self._max_scopes = max_scopes
        self._max_variables = max_variables
        self._entries: dict[tuple[str, str, str], dict[str, _Declaration]] = {}
        self._lock = RLock()

    def __repr__(self) -> str:
        return "CodeEnvRegistry()"

    @staticmethod
    def _scope(agent: str, principal: str, session_id: str) -> tuple[str, str, str]:
        if principal != "owner":
            raise ValueError("code environment declarations require owner principal")
        if any(not isinstance(part, str) or not part or len(part) > _MAX_ID_LENGTH
               for part in (agent, session_id)):
            raise ValueError("invalid code environment scope")
        return agent, principal, session_id

    def _now(self) -> float:
        now = float(self._clock())
        if not math.isfinite(now):
            raise ValueError("invalid code environment clock")
        return now

    @staticmethod
    def _valid_declaration(entry: _Declaration, now: float) -> bool:
        if now >= entry.expires_at:
            return False
        if entry.validator is None:
            return True
        try:
            return entry.validator() is True
        except Exception:
            return False

    def _sweep(self, now: float) -> None:
        for scope, entries in tuple(self._entries.items()):
            for skill_id, entry in tuple(entries.items()):
                if not self._valid_declaration(entry, now):
                    del entries[skill_id]
            if not entries:
                del self._entries[scope]

    def declare(
        self,
        *,
        agent: str,
        principal: str,
        session_id: str,
        skill_id: str,
        names: Iterable[str],
        validator: Callable[[], bool] | None = None,
    ) -> None:
        """Record a successful host-verified skill view; no values are accepted.

        ``validator`` should compare the original viewed snapshot and its current
        catalog/trust standing. It runs on registration and on every resolution.
        A missing or unreadable validator result grants nothing.
        """
        scope = self._scope(agent, principal, session_id)
        if not isinstance(skill_id, str) or not skill_id or len(skill_id) > _MAX_ID_LENGTH:
            raise ValueError("invalid skill identity")
        if validator is not None and not callable(validator):
            raise ValueError("invalid skill validator")
        try:
            if isinstance(names, str):
                raise ValueError("invalid environment names")
            proposed = tuple(islice(names, self._max_variables + 1))
        except TypeError as exc:
            raise ValueError("invalid environment names") from exc
        if len(proposed) > self._max_variables or any(
            not _valid_name(name) for name in proposed
        ):
            raise ValueError("invalid environment names")
        accepted = frozenset(name for name in proposed if _passable_name(name))
        with self._lock:
            now = self._now()
            self._sweep(now)
            if validator is not None and not self._valid_declaration(
                _Declaration(accepted, now + self._ttl, validator), now
            ):
                self._entries.get(scope, {}).pop(skill_id, None)
                return
            current = self._entries.get(scope, {})
            total = set(accepted)
            for old_skill_id, entry in current.items():
                if old_skill_id != skill_id:
                    total.update(entry.names)
            if len(total) > self._max_variables:
                raise ValueError("code environment scope capacity exceeded")
            if not accepted:
                if current:
                    current.pop(skill_id, None)
                    if not current:
                        self._entries.pop(scope, None)
                return
            if scope not in self._entries:
                if len(self._entries) >= self._max_scopes:
                    raise ValueError("code environment registry capacity exceeded")
                self._entries[scope] = {}
            self._entries[scope][skill_id] = _Declaration(
                accepted, now + self._ttl, validator
            )

    def revoke(
        self,
        *,
        agent: str,
        principal: str,
        session_id: str,
        skill_id: str | None = None,
    ) -> None:
        """Revoke a skill or the whole exact scope (for reset/end of session)."""
        if principal != "owner":
            return
        scope = self._scope(agent, principal, session_id)
        with self._lock:
            if skill_id is None:
                self._entries.pop(scope, None)
            else:
                entries = self._entries.get(scope)
                if entries is not None:
                    entries.pop(skill_id, None)
                    if not entries:
                        self._entries.pop(scope, None)

    def resolve_names(
        self,
        *,
        agent: str,
        principal: str,
        session_id: str,
        machine_allowlist: Iterable[str] | Callable[[], Iterable[str]] = (),
    ) -> frozenset[str]:
        """Return declared names plus owner-only machine config, never values."""
        if principal != "owner":
            return frozenset()
        scope = self._scope(agent, principal, session_id)
        with self._lock:
            try:
                now = self._now()
            except (TypeError, ValueError, OverflowError):
                self._entries.clear()
                return frozenset()
            self._sweep(now)
            result = set().union(*(e.names for e in self._entries.get(scope, {}).values()))
        try:
            configured = machine_allowlist() if callable(machine_allowlist) else machine_allowlist
            if isinstance(configured, str):
                return frozenset(result)
            config_names = tuple(islice(configured, self._max_variables + 1))
            if len(config_names) > self._max_variables:
                return frozenset(result)
            configured_names = {name for name in config_names if _passable_name(name)}
            if len(result | configured_names) <= self._max_variables:
                result.update(configured_names)
        except Exception:
            return frozenset(result)  # Unreadable config grants no configured names.
        return frozenset(result)


def prepare_code_env(
    source_env: Mapping[str, str] | Callable[[str], str | None],
    *,
    allowed_names: Iterable[str] = (),
) -> dict[str, str]:
    """Read only approved names for one interpreter's immutable startup env.

    ``source_env`` may be a trusted scope-aware resolver. A missing value or
    resolver failure never falls back to process-global ``os.environ``. The caller
    merges this result into its controlled backend base and sends the snapshot to
    the child at process startup; later namespace revocation is parent-side.
    """
    try:
        if isinstance(allowed_names, str):
            raise ValueError("invalid environment names")
        proposed = tuple(islice(allowed_names, 257))
        names = set(proposed) if len(proposed) <= 256 else set()
    except (TypeError, ValueError):
        names = set()
    names = _OPERATIONAL_NAMES | frozenset(name for name in names if _passable_name(name))
    result: dict[str, str] = {}
    for name in sorted(names):
        try:
            value = source_env(name) if callable(source_env) else source_env.get(name)
        except Exception:
            value = None
        if isinstance(value, str) and "\x00" not in value:
            result[name] = value
    return result


__all__ = ["CodeEnvRegistry", "prepare_code_env"]
