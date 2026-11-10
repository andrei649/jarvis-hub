"""The Hermes internals the adopted video files import (rewrite rules ``video-shared``,
``video-xai-http-module``, ``video-mimetypes``), each mapped onto a Nerva control.

* **Provider base and registry** (``agent.provider_base``, ``agent.provider_registry``):
  the identity/catalog base classes and a plain name -> provider map. The configured
  provider is the owner's consented choice (``JARVIS_VIDEO_PROVIDER``, set by the HUD's
  Integrations panel after its consent card), never a config file; there are no profile
  scopes.
* **Keys** (``agent.secret_scope.get_secret_str``): only the key of the provider the Nerva
  runtime is running (``provider_scope``), read through ``env_config`` at call time:
  FAL reads ``FAL_KEY``, xAI ``XAI_API_KEY``, DeepInfra ``DEEPINFRA_API_KEY``. Any other
  name (another provider's key, a ``*_BASE_URL`` override) reads as unset.
* **FAL queue** (``tools.fal_common``): ``import_fal_client`` gives a small client whose
  ``submit`` posts to ``https://queue.fal.run/<endpoint>`` and ``wait_fal_queue_result``
  polls the request's status, both through the compat ``httpx``. The managed Nous gateway
  (``tools.managed_tool_gateway``) is never available, so every FAL call is direct with the
  owner's own key. ``read_selection`` answers "nothing stored" (Nerva passes the provider
  and model explicitly).
* **xAI helpers** (``tools.xai_http``): the fixed ``https://api.x.ai/v1`` base, the scoped
  key, user agent "Nerva", and xAI's server-side storage off (Nerva keeps the file locally).
* **No local file reads** (``pathlib.Path``, ``agent.file_safety``): the xAI plugin would
  inline a local file the model names as a data URI. Here ``Path`` is inert (``is_file``
  is always false) and the read guard always refuses; image inputs reach a provider only as
  data URIs Nerva builds from its own generated artifacts, or as the provider's own media
  URLs.
* **No live catalog fetch** (``hermes_cli.models``): DeepInfra's model list is empty, so a
  DeepInfra video names its model.
* ``hermes_cli.config.load_config`` reads as empty; ``agent.process_bootstrap`` builds no
  HTTP client; ``mimetypes`` is a suffix table.
"""

from __future__ import annotations

import abc
import logging
import re
import threading
from types import SimpleNamespace
from typing import Any

from agents.core.env_config import env_str
from agents.vendor.hermes_compat import httpx, video_clock
from agents.vendor.hermes_compat.web_search_provider import current_provider, provider_scope

#: The owner's consented video provider (the Integrations panel's "use").
CHOICE_ENV = "JARVIS_VIDEO_PROVIDER"
#: Keys each adopted video provider may read (documented in .env.example).
VIDEO_PROVIDER_KEYS: dict[str, frozenset[str]] = {
    "fal": frozenset({"FAL_KEY"}),
    "xai": frozenset({"XAI_API_KEY"}),
    "deepinfra": frozenset({"DEEPINFRA_API_KEY"}),
}
XAI_BASE_URL = "https://api.x.ai/v1"
FAL_QUEUE = "https://queue.fal.run"
#: Seconds between FAL status polls.
FAL_POLL_SECONDS = 3.0
NOUS_MANAGED_PROVIDER = "nous"

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}")
_ENDPOINT = re.compile(r"[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*){1,6}")


# ── keys ─────────────────────────────────────────────────────────────────────────

def get_secret_str(name: str, default: str = "") -> str:
    """The value of a key the current video provider may read, else *default*."""
    if name not in VIDEO_PROVIDER_KEYS.get(current_provider(), frozenset()):
        return default
    return str(env_str(name, "") or "").strip() or default


# ── provider base ────────────────────────────────────────────────────────────────

class ProviderBase(abc.ABC):
    """Identity + picker metadata (upstream ``agent.provider_base.ProviderBase``)."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Stable short identifier."""

    @property
    def display_name(self) -> str:
        return self.name

    def get_setup_schema(self) -> dict[str, Any]:
        return {"name": self.display_name, "badge": "", "tag": "", "env_vars": []}


class CatalogProviderBase(ProviderBase):
    """A provider with a model catalog (upstream ``CatalogProviderBase``)."""

    @property
    def display_name(self) -> str:
        return self.name.title()

    def is_available(self) -> bool:
        return True

    def list_models(self) -> list[dict[str, Any]]:
        return []

    def default_model(self) -> str | None:
        models = self.list_models()
        return models[0].get("id") if models else None


# ── registry ─────────────────────────────────────────────────────────────────────

class ProviderRegistry[P]:
    """A name -> provider map (upstream's engine without profile scopes)."""

    def __init__(self, *, label: str, provider_cls: type, logger: logging.Logger, **_unused: Any) -> None:
        self.label = label
        self.provider_cls = provider_cls
        self.logger = logger
        self._providers: dict[str, P] = {}
        self._lock = threading.Lock()

    def register(self, provider: P, **_unused: Any) -> None:
        if not isinstance(provider, self.provider_cls):
            raise TypeError(f"register_provider() expects a {self.provider_cls.__name__}")
        name = getattr(provider, "name", "")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{self.label} provider .name must be a non-empty string")
        with self._lock:
            self._providers[name.strip()] = provider

    def merged(self, scope: Any = None) -> dict[str, P]:
        with self._lock:
            return dict(self._providers)

    def list_providers(self, **_unused: Any) -> list[P]:
        return sorted(self.merged().values(), key=lambda p: p.name)

    def get_provider(self, name: str, **_unused: Any) -> P | None:
        if not isinstance(name, str):
            return None
        with self._lock:
            return self._providers.get(name.strip())

    def reset_for_tests(self) -> None:
        with self._lock:
            self._providers.clear()

    def export(self, module_name: str) -> None:
        """Bind the module-level API into the vendored registry module (upstream passes
        ``globals()``; the rewrite passes ``__name__``)."""
        import sys

        module = sys.modules.get(str(module_name))
        if module is None:
            raise RuntimeError("registry module not loaded")
        for key, value in (("register_provider", self.register), ("list_providers", self.list_providers),
                           ("get_provider", self.get_provider), ("reset_for_tests", self.reset_for_tests)):
            setattr(module, key, value)


def is_available_safe(provider: Any, logger: logging.Logger, fmt: str, **_unused: Any) -> bool:
    try:
        with provider_scope(str(getattr(provider, "name", "") or "")):
            return bool(provider.is_available())
    except Exception as exc:  # noqa: BLE001 — a raising provider is unavailable
        logger.debug(fmt, getattr(provider, "name", "?"), type(exc).__name__)
        return False


def configured_provider_name(section: str, logger: logging.Logger) -> str | None:
    if section != "video_gen":
        return None
    value = str(env_str(CHOICE_ENV, "") or "").strip()
    return value or None


# ── upstream leaves that are off or empty here ───────────────────────────────────

def build_keepalive_http_client(base_url: str) -> None:
    return None


def raise_if_read_blocked(path: Any) -> None:
    raise PermissionError("a provider never reads a local file in Nerva")


def load_config(*_args: Any, **_kwargs: Any) -> dict:
    return {}


def cfg_get(config: Any, *keys: str, default: Any = None) -> Any:
    return default


def _fetch_deepinfra_models_by_tag(tag: str) -> list:
    return []


def resolve_managed_tool_gateway(name: str) -> None:
    return None


def read_selection(section: str) -> None:
    return None


def selection_error(section: str, provider: str, why: str) -> str:
    return f"{section}: {provider} cannot run ({why})"


def fal_key_is_configured() -> bool:
    with provider_scope("fal"):
        return bool(get_secret_str("FAL_KEY"))


class Path:
    """Inert ``pathlib.Path``: no file is ever found or read through it."""

    def __init__(self, *parts: Any) -> None:
        self._text = "/".join(str(part) for part in parts)

    def expanduser(self) -> Path:
        return self

    def is_file(self) -> bool:
        return False

    def exists(self) -> bool:
        return False

    def read_bytes(self) -> bytes:
        raise PermissionError("a provider never reads a local file in Nerva")

    @property
    def name(self) -> str:
        return self._text.rstrip("/").rsplit("/", 1)[-1]

    def __str__(self) -> str:
        return self._text

    def __fspath__(self) -> str:
        raise PermissionError("a provider never reads a local file in Nerva")


_TYPES = {"mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime", "mkv": "video/x-matroska",
          "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp",
          "gif": "image/gif"}


def _guess_type(name: Any, strict: bool = True) -> tuple[str | None, None]:
    suffix = str(name or "").rsplit(".", 1)[-1].lower() if "." in str(name or "") else ""
    return _TYPES.get(suffix), None


mimetypes = SimpleNamespace(guess_type=_guess_type)


# ── xAI ──────────────────────────────────────────────────────────────────────────

def resolve_xai_http_credentials() -> dict[str, str]:
    """The scoped xAI key (empty outside xAI's scope) and the fixed API base."""
    return {"api_key": get_secret_str("XAI_API_KEY"), "base_url": XAI_BASE_URL}


def build_xai_storage_options(*_args: Any, **_kwargs: Any) -> None:
    return None


def maybe_mark_xai_storage_notice_seen(*_args: Any) -> None:
    return None


def read_xai_imagine_storage_config(*_args: Any) -> dict:
    return {"enabled": False}


xai_http = SimpleNamespace(
    resolve_xai_http_credentials=resolve_xai_http_credentials,
    hermes_xai_user_agent=lambda: "Nerva",
    xai_storage_notice_text=lambda *_a: "",
    build_xai_storage_options=build_xai_storage_options,
    maybe_mark_xai_storage_notice_seen=maybe_mark_xai_storage_notice_seen,
    read_xai_imagine_storage_config=read_xai_imagine_storage_config,
)


# ── FAL queue ────────────────────────────────────────────────────────────────────

class FalQueueError(Exception):
    """The FAL queue refused or failed a request (status code only, never a body)."""


class _FalHandle:
    def __init__(self, request_id: str, status_url: str, response_url: str) -> None:
        self.request_id = request_id
        self.status_url = status_url
        self.response_url = response_url


def _fal_headers() -> dict[str, str]:
    return {"Authorization": f"Key {get_secret_str('FAL_KEY')}", "Content-Type": "application/json"}


def _queue_url(value: Any, request_id: str) -> str | None:
    text = str(value or "")
    if text.startswith(FAL_QUEUE + "/") and request_id in text and ".." not in text and "?" not in text:
        return text
    return None


class _FalClient:
    """The two calls the FAL video plugin makes on ``fal_client``."""

    def submit(self, endpoint: str, arguments: dict | None = None, headers: dict | None = None,
               **_unused: Any) -> _FalHandle:
        path = str(endpoint or "")
        if not _ENDPOINT.fullmatch(path) or ".." in path:
            raise FalQueueError("invalid FAL endpoint")
        extra = {str(k): str(v) for k, v in dict(headers or {}).items()
                 if str(k).lower() == "x-idempotency-key"}
        resp = httpx.post(f"{FAL_QUEUE}/{path}", json=dict(arguments or {}),
                          headers={**_fal_headers(), **extra}, timeout=60)
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
        request_id = str(data.get("request_id") or "") if isinstance(data, dict) else ""
        if not _TOKEN.fullmatch(request_id):
            raise FalQueueError("FAL answered without a request id")
        app = "/".join(path.split("/")[:2])
        status_url = (_queue_url(data.get("status_url"), request_id)
                      or f"{FAL_QUEUE}/{app}/requests/{request_id}/status")
        response_url = (_queue_url(data.get("response_url"), request_id)
                        or f"{FAL_QUEUE}/{app}/requests/{request_id}")
        return _FalHandle(request_id, status_url, response_url)


def import_fal_client() -> _FalClient:
    return _FalClient()


def wait_fal_queue_result(handle: _FalHandle) -> Any:
    """Poll the request until FAL reports it completed, then read its result. Bounded by
    the approved task's deadline: the compat ``httpx`` refuses a request once the task is
    cancelled or out of time, and the sleep between polls wakes for the same reasons."""
    if not isinstance(handle, _FalHandle):
        raise FalQueueError("not a FAL request")
    while True:
        resp = httpx.get(handle.status_url, headers=_fal_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
        status = str(data.get("status") or "").upper() if isinstance(data, dict) else ""
        if status == "COMPLETED":
            break
        if status not in ("IN_QUEUE", "IN_PROGRESS"):
            raise FalQueueError("FAL request ended without a result")
        video_clock.sleep(FAL_POLL_SECONDS)
    resp = httpx.get(handle.response_url, headers=_fal_headers(), timeout=60)
    resp.raise_for_status()
    return resp.json()


class _ManagedFalSyncClient:
    """The managed Nous gateway client: never available in Nerva."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("the managed FAL gateway is not used in Nerva")


def submit_managed_fal_with_rate_limit_retry(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("the managed FAL gateway is not used in Nerva")


def _extract_http_status(exc: Any) -> int | None:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _managed_fal_billing_error(*_args: Any) -> None:
    return None


__all__ = [
    "CHOICE_ENV", "CatalogProviderBase", "NOUS_MANAGED_PROVIDER", "Path", "ProviderBase",
    "ProviderRegistry", "VIDEO_PROVIDER_KEYS", "build_keepalive_http_client",
    "build_xai_storage_options", "cfg_get", "configured_provider_name", "fal_key_is_configured",
    "get_secret_str", "import_fal_client", "is_available_safe", "load_config",
    "maybe_mark_xai_storage_notice_seen", "mimetypes", "raise_if_read_blocked",
    "read_selection", "read_xai_imagine_storage_config", "resolve_managed_tool_gateway",
    "selection_error", "submit_managed_fal_with_rate_limit_retry", "wait_fal_queue_result",
    "xai_http",
]
