"""``providers`` (Hermes's model-provider registry) for vendored profile modules.

Upstream's ``providers/__init__.py`` discovers plugins on disk, reads Hermes config and
imports entry points. None of that is adopted. A vendored profile module only calls
:func:`register_provider` (and, rarely, :func:`get_provider_profile`), so this is a plain
dictionary that Nerva's bridge (``agents/core/llm/hermes_profiles.py``) loads the adopted
modules into and reads back. Registering a profile here selects nothing: a provider is used
only when the owner picks it and its key is set.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
_REGISTRY: dict[str, Any] = {}

#: Where the vendored profile modules live (``plugins/model-providers/<dir>/__init__.py``).
MODEL_PROVIDERS = Path(__file__).resolve().parent.parent / "hermes" / "plugins" / "model-providers"
_PACKAGE = "agents.vendor.hermes.plugins.model_providers"


def register_provider(profile: Any) -> None:
    """Keep *profile* under its ``name``. A second profile under the same name is refused."""
    name = str(getattr(profile, "name", "") or "")
    if not name:
        raise ValueError("a provider profile needs a name")
    with _LOCK:
        if name in _REGISTRY and _REGISTRY[name] is not profile:
            raise ValueError(f"duplicate provider profile: {name}")
        _REGISTRY[name] = profile


def get_provider_profile(name: str) -> Any | None:
    with _LOCK:
        return _REGISTRY.get(str(name or ""))


def registered() -> dict[str, Any]:
    with _LOCK:
        return dict(_REGISTRY)


def load_profile_module(directory: str) -> None:
    """Import the vendored ``plugins/model-providers/<directory>/__init__.py`` once.

    The upstream directory names carry hyphens, so they are not importable by dotted name;
    upstream's loader takes them by file path too. *directory* must be one plain name under
    the vendored tree: the bridge passes only names from its reviewed table.
    """
    if (not isinstance(directory, str) or not directory or "/" in directory
            or "\\" in directory or directory.startswith(".")):
        raise ValueError(f"not a profile directory name: {directory!r}")
    folder = MODEL_PROVIDERS / directory
    path = folder / "__init__.py"
    if (folder.is_symlink() or path.is_symlink() or not path.is_file()
            or path.resolve().parent.parent != MODEL_PROVIDERS):
        raise FileNotFoundError(f"no vendored profile module {directory!r}")
    module_name = f"{_PACKAGE}.{directory.replace('-', '_')}"
    with _LOCK:
        if module_name in sys.modules:
            return
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load vendored profile module {directory!r}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(module_name, None)
            raise
