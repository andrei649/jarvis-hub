"""Nerva source registry and owner-held session state.

Precedence follows Hermes agent/secret_sources/registry.py at 59b2aeef6c7a
(MIT): explicit mapped 1Password references beat bulk Bitwarden values.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from collections.abc import Callable

from agents.core.secrets import SecretStore

from . import bitwarden, onepassword
from .base import FetchResult, Runner, valid_env_name

_PROVIDERS = ("onepassword", "bitwarden")
_CONFIG_PREFIX = "h034.config."
_TOKEN_PREFIX = "h034.token."


class OwnerSessions:
    """In-process, per-owner session tokens with an idle TTL; no prompts."""

    def __init__(self, ttl_seconds: float = 1800, clock: Callable[[], float] = time.monotonic):
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._sessions: dict[tuple[str, str], tuple[str, float]] = {}
        self._lock = threading.Lock()

    def put(self, owner_id: str, provider: str, token: str) -> None:
        if not owner_id or not token or provider not in _PROVIDERS:
            raise ValueError("owner, provider and session token are required")
        with self._lock:
            self._sessions[(owner_id, provider)] = (token, self.clock())

    def get(self, owner_id: str | None, provider: str, *, touch: bool = True) -> str | None:
        if not owner_id:
            return None
        with self._lock:
            entry = self._sessions.get((owner_id, provider))
            if entry is None:
                return None
            token, last = entry
            if self.clock() - last > self.ttl_seconds:
                self._sessions.pop((owner_id, provider), None)
                return None
            if touch:
                self._sessions[(owner_id, provider)] = (token, self.clock())
            return token

    def lock(self, owner_id: str, provider: str | None = None) -> None:
        with self._lock:
            for key in tuple(self._sessions):
                if key[0] == owner_id and (provider is None or key[1] == provider):
                    self._sessions.pop(key, None)


class ExternalSecretSources:
    """Resolve only at an approved broker action. Configuration and tokens use SecretStore."""

    def __init__(self, store: SecretStore, *, runner: Runner = subprocess.run,
                 sessions: OwnerSessions | None = None, clock: Callable[[], float] = time.monotonic):
        self.store = store
        self.runner = runner
        self.sessions = sessions or OwnerSessions(clock=clock)
        self.clock = clock
        # value, expires, provider, owner (owner=None only for encrypted stored token)
        self._cache: dict[str, tuple[str, float, str, str | None]] = {}
        # Previously resolved values remain redactable after TTL/auth/config changes.
        # Process memory only; bounded to avoid an unbounded rotation history.
        self._redaction_history: list[tuple[str, str]] = []
        self._lock = threading.RLock()
        self._store_stamp = self._stamp()

    def _stamp(self) -> tuple[int, int, int] | None:
        try:
            stat = self.store.path.stat()
            return (stat.st_ino, stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            return None

    def _refresh_store(self) -> None:
        """Observe another process/SecretStore instance's atomic replacement."""
        stamp = self._stamp()
        with self._lock:
            if stamp != self._store_stamp:
                # SecretStore has no public refresh method. Its reads otherwise
                # reuse a per-instance decrypted snapshot until this flag resets.
                self.store._loaded = False
                self._store_stamp = stamp
                self._cache.clear()

    def _remember(self, name: str, value: str) -> None:
        if not value:
            return
        with self._lock:
            pair = (name, value)
            if pair not in self._redaction_history:
                self._redaction_history.append(pair)
                if len(self._redaction_history) > 1024:
                    self._redaction_history.pop(0)

    def redaction_values(self) -> list[tuple[str, str]]:
        with self._lock:
            return list(self._redaction_history)

    def configuration(self, provider: str) -> dict:
        self._check_provider(provider)
        self._refresh_store()
        raw = self.store.get(_CONFIG_PREFIX + provider)
        if not raw:
            return {}
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError):
            return {}

    def configure(self, provider: str, config: dict) -> None:
        self._check_provider(provider)
        if not isinstance(config, dict):
            raise ValueError("configuration must be an object")
        if any(key in config for key in ("token", "access_token", "service_account_token", "password")):
            raise ValueError("credentials must use set_token, not source configuration")
        if provider == "onepassword":
            refs = config.get("env", {})
            if not isinstance(refs, dict) or any(not valid_env_name(k) or not onepassword.valid_reference(v)
                                                    for k, v in refs.items()):
                raise ValueError("onepassword.env requires ENV_VAR to op://vault/item/field references")
            config = {**config, "env": {name: reference.strip() for name, reference in refs.items()}}
        if provider == "bitwarden" and config.get("server_url"):
            from urllib.parse import urlsplit
            parsed = urlsplit(str(config["server_url"]))
            if (parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password
                    or parsed.query or parsed.fragment):
                raise ValueError("Bitwarden server URL must be HTTPS without credentials")
        self.store.set(_CONFIG_PREFIX + provider, json.dumps(config, sort_keys=True))
        self.clear_cache()

    def set_token(self, provider: str, token: str) -> None:
        self._check_provider(provider)
        if not token or not token.strip():
            raise ValueError("empty token")
        self.store.set(_TOKEN_PREFIX + provider, token.strip())
        self.clear_cache()

    def token_present(self, provider: str) -> bool:
        self._check_provider(provider)
        self._refresh_store()
        return bool(self.store.get(_TOKEN_PREFIX + provider))

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def known_value(self, name: str) -> str | None:
        with self._lock:
            entry = self._cache.get(name)
            return entry[0] if entry is not None and self.clock() < entry[1] else None

    def known_values(self) -> dict[str, str]:
        with self._lock:
            return {key: entry[0] for key, entry in self._cache.items() if self.clock() < entry[1]}

    def resolve(self, name: str, *, owner_id: str | None = None, background: bool = False,
                fresh: bool = False) -> str | None:
        if not valid_env_name(name):
            return None
        self._refresh_store()
        with self._lock:
            entry = self._cache.get(name)
            if not fresh and entry and self.clock() < entry[1]:
                value, _expires, provider, cache_owner = entry
                current_token = self.store.get(_TOKEN_PREFIX + provider)
                if ((cache_owner is None and current_token)
                        or (cache_owner == owner_id and not background
                            and self.sessions.get(owner_id, provider, touch=False))):
                    return value
        for provider in _PROVIDERS:
            cfg = self.configuration(provider)
            if not cfg.get("enabled"):
                continue
            mapped_claim = provider == "onepassword" and name in cfg.get("env", {})
            if provider == "onepassword" and not mapped_claim:
                continue
            token = self.store.get(_TOKEN_PREFIX + provider)
            session = False
            if not token and not background:
                token = self.sessions.get(owner_id, provider)
                session = bool(token)
            if not token:
                if mapped_claim:
                    return None
                continue
            result = self._fetch(provider, cfg, token, session=session)
            protected = {"BWS_ACCESS_TOKEN", "OP_SERVICE_ACCOUNT_TOKEN", "OP_SESSION"}
            # A CLI process can revoke or rotate the source while its helper is
            # running. Remember returned values for scrubbing, but do not grant
            # credential use from a stale configuration or expired owner session.
            for key, value in result.secrets.items():
                if key not in protected:
                    self._remember(key, value)
            current_cfg = self.configuration(provider)
            current_token = self.store.get(_TOKEN_PREFIX + provider)
            session_current = self.sessions.get(owner_id, provider, touch=False) if session else None
            if (current_cfg != cfg or (not session and current_token != token)
                    or (session and (current_token or session_current != token))):
                return None
            if result.error_kind is not None:
                with self._lock:
                    for key, cached in tuple(self._cache.items()):
                        if cached[2] == provider:
                            self._cache.pop(key, None)
                if mapped_claim:
                    return None
                continue
            # The provider bootstrap credentials can never be sourced by themselves.
            try:
                ttl = min(max(float(cfg.get("cache_ttl_seconds", 60)), 0), 300)
            except (TypeError, ValueError):
                ttl = 60.0
            with self._lock:
                for key, value in result.secrets.items():
                    claimed_by_mapped = (provider == "bitwarden"
                                         and self.configuration("onepassword").get("enabled")
                                         and key in self.configuration("onepassword").get("env", {}))
                    if key not in protected and value and not claimed_by_mapped and not result.warnings:
                        self._cache[key] = (value, self.clock() + ttl, provider,
                                            owner_id if session else None)
                    if key not in protected and value and not claimed_by_mapped:
                        self._remember(key, value)
            if name in result.secrets and name not in protected:
                return result.secrets[name]
            if mapped_claim:
                return None
        return None

    def fetch_report(self, provider: str, *, owner_id: str | None = None) -> FetchResult:
        self._check_provider(provider)
        self._refresh_store()
        cfg = self.configuration(provider)
        if not cfg.get("enabled"):
            return FetchResult(error=f"{provider} is disabled")
        token = self.store.get(_TOKEN_PREFIX + provider)
        session = False
        if not token:
            token = self.sessions.get(owner_id, provider)
            session = bool(token)
        result = self._fetch(provider, cfg, token or "", session=session)
        for key in ("BWS_ACCESS_TOKEN", "OP_SERVICE_ACCOUNT_TOKEN", "OP_SESSION"):
            result.secrets.pop(key, None)
        for name, value in result.secrets.items():
            self._remember(name, value)
        return result

    def _fetch(self, provider: str, cfg: dict, token: str, *, session: bool) -> FetchResult:
        if provider == "onepassword":
            return onepassword.fetch(cfg, token, self.runner, session=session)
        return bitwarden.fetch(cfg, token, self.runner)

    @staticmethod
    def _check_provider(provider: str) -> None:
        if provider not in _PROVIDERS:
            raise ValueError("unknown secret source")
