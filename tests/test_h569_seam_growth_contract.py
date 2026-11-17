"""H569 — the seams Nerva exposes grow only through methods that have defaults, and the
published "I want to add X" table names the right seam for each kind of addition.

What a contributor can rely on: an implementation written against ProviderBase,
LLMBackend, ChannelAdapter, VectorStore or a provider package's hook set keeps
instantiating when Nerva adds a method, because a new method must come with a default.

What cannot happen silently: an abstract method (or a required provider hook) appearing
on a seam — that breaks every implementation outside this file — without this fixture
and docs/EXTENDING.md changing in the same commit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agents.core.channels.base import ChannelAdapter
from agents.core.llm.base import LLMBackend
from agents.core.llm.providers import hook_runtime
from agents.core.media_providers import ProviderBase
from agents.core.memory.store import VectorStore

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "docs" / "EXTENDING.md"

REQUIRED = {
    ProviderBase: frozenset({"name", "kind"}),
    LLMBackend: frozenset({"generate"}),
    ChannelAdapter: frozenset({"start", "stop", "send"}),
    VectorStore: frozenset({"add", "get", "remove", "remove_where", "search", "search_by_sender",
                            "search_by_text_subset", "clear", "__len__"}),
}


@pytest.mark.parametrize("seam", list(REQUIRED), ids=lambda seam: seam.__name__)
def test_the_required_methods_of_each_seam_are_frozen(seam):
    assert frozenset(seam.__abstractmethods__) == REQUIRED[seam]


def _minimal(seam):
    namespace = {}
    for name in REQUIRED[seam]:
        if name in {"name", "kind"}:
            namespace[name] = property(lambda self: "minimal")
        elif name == "__len__":
            namespace[name] = lambda self: 0
        else:
            namespace[name] = lambda self, *args, **kwargs: None
    return type(f"Minimal{seam.__name__}", (seam,), namespace)


@pytest.mark.parametrize("seam", list(REQUIRED), ids=lambda seam: seam.__name__)
def test_an_implementation_with_only_the_required_methods_still_builds(seam):
    cls = _minimal(seam)
    assert not getattr(cls, "__abstractmethods__", frozenset())
    if seam is ChannelAdapter:
        return  # its constructor takes the hub's wiring; abstractness is what is pinned
    try:
        cls()
    except TypeError as exc:
        assert "abstract" not in str(exc)


def test_provider_package_hooks_grow_only_as_optional_hooks():
    required, optional = hook_runtime._REQUIRED_HOOKS, hook_runtime._OPTIONAL_HOOKS
    assert required == {"prepare_messages", "build_extra_body", "build_api_kwargs_extras"}
    assert {"get_max_tokens", "supported_reasoning_efforts"} <= optional
    assert not hook_runtime._REQUIRED_HOOKS & hook_runtime._OPTIONAL_HOOKS


def test_the_published_table_matches_the_frozen_contract_and_names_real_paths():
    text = DOC.read_text(encoding="utf-8")
    for seam, names in REQUIRED.items():
        row = next(line for line in text.splitlines() if line.startswith(f"| `{seam.__name__}` |"))
        assert set(re.findall(r"`([A-Za-z_]+)`", row.split("|")[2])) == set(names), seam.__name__
    for path in set(re.findall(r"`((?:agents|docs)/[A-Za-z0-9_./-]+\.(?:py|md))`", text)):
        assert (REPO / path).exists(), path
    for needle in ("I want to add", "extensions install", "hooks.define", "provider package",
                   "secret source"):
        assert needle in text
