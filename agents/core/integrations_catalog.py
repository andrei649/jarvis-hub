"""integrations_catalog.py — one list of what needs the owner's setup (HUD Integrations panel).

Before this, the capabilities that need a key or a choice were spread out: model
providers in a long settings select (``llm.compatible_provider``), search backends in the
environment (``JARVIS_WEB_BACKEND``), the Hermes skills catalog inside the Skills Import
panel. This module lists them in one place, as data the panel renders:

* **search** — the native Tavily backend and the three adopted from Hermes (Exa, Brave
  Search, Parallel; ``hermes_compat.plugin_ctx``);
* **model** — the native cloud providers that take a key (Gemini, Anthropic, OpenRouter,
  DeepInfra, xAI, OpenAI Responses) and the 24 adopted from Hermes
  (``hermes_provider_table``);
* **skills** — the vendored Hermes skills catalog, as a summary that points at the Skills
  Import panel (installing stays there).

Each entry says where it comes from (``native`` / ``hermes``), its status (``not_set_up``,
``key_set``, ``active``, ``error``), and the facts the owner weighs before using it: the
host, the host country when Nerva's own data names one, the data policy and whether
Nerva knows a price. Never a key value: ``integration_keys.status`` gives "set", where it
was set and at most the last four characters.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from agents.core import integration_keys
from agents.core.env_config import env_str

logger = logging.getLogger("jarvis.integrations_catalog")

KIND_SEARCH = "search"
KIND_MODEL = "model"
KIND_SKILLS = "skills"
ORIGIN_NATIVE = "native"
ORIGIN_HERMES = "hermes"
WEB_BACKEND = "JARVIS_WEB_BACKEND"


@dataclass(frozen=True)
class SearchRow:
    name: str          # the registry name JARVIS_WEB_BACKEND takes
    display: str
    keys: tuple[str, ...]
    host: str
    origin: str
    tier: str


#: The search backends that need a key. Hosts are the ``websearch`` manifest's allowlist.
SEARCH_ROWS: tuple[SearchRow, ...] = (
    SearchRow("tavily", "Tavily", ("TAVILY_API_KEY",), "api.tavily.com", ORIGIN_NATIVE, "paid"),
    SearchRow("exa", "Exa", ("EXA_API_KEY",), "api.exa.ai", ORIGIN_HERMES, "paid"),
    SearchRow("brave-free", "Brave Search", ("BRAVE_SEARCH_API_KEY",), "api.search.brave.com",
              ORIGIN_HERMES, "paid"),
    SearchRow("parallel", "Parallel", ("PARALLEL_API_KEY",), "api.parallel.ai", ORIGIN_HERMES, "paid"),
)

#: Native model providers that take a key, and whether the owner chooses them in the
#: compatible slot (``llm.compatible_provider``) or the router uses them as soon as a key
#: is set (Gemini, Anthropic).
NATIVE_MODEL_IDS: tuple[tuple[str, bool], ...] = (
    ("gemini", False), ("anthropic", False), ("openrouter", True), ("deepinfra", True),
    ("xai", True), ("openai-responses", True),
)

#: Host countries Nerva's own data names (the profile's display name says "China"). No
#: other country is recorded anywhere in Nerva, so every other entry reads "not recorded".
_CHINA_IDS = frozenset({"alibaba-cn", "alibaba-token-plan-cn", "alibaba-coding-plan-cn", "kimi-coding-cn"})


def entry_id(kind: str, name: str) -> str:
    return f"{kind}.{name}"


@dataclass
class Entry:
    id: str
    kind: str
    name: str
    display_name: str
    origin: str
    keys: tuple[str, ...]
    host: str
    host_country: str | None
    data_policy: str
    data_policy_note: str
    price_known: str            # "yes" | "some" | "no"
    price_note: str
    selectable: bool
    models: tuple[str, ...] = ()
    extra: dict = field(default_factory=dict)


def search_entries() -> list[Entry]:
    out = []
    for row in SEARCH_ROWS:
        out.append(Entry(
            id=entry_id(KIND_SEARCH, row.name), kind=KIND_SEARCH, name=row.name,
            display_name=row.display, origin=row.origin, keys=row.keys, host=row.host,
            host_country=None, data_policy="unknown",
            data_policy_note=("how this service handles your search queries has not been verified"),
            price_known="no",
            price_note=f"{row.tier} service; Nerva has no price for its searches",
            selectable=True))
    return out


def _model_entry(profile, origin: str, selectable: bool) -> Entry:
    from agents.core.llm.selection_guards import price_of

    models = tuple(profile.fallback_models)
    priced = sum(1 for model in models if price_of(model) is not None)
    if models and priced == len(models):
        known, note = "yes", "Nerva knows the price of its listed models"
    elif priced:
        known, note = "some", f"Nerva knows the price of {priced} of {len(models)} listed models"
    else:
        known, note = "no", "Nerva has no price for this provider's models"
    keys = tuple(profile.env_vars) or ((profile.auth_env,) if profile.auth_env else ())
    return Entry(
        id=entry_id(KIND_MODEL, profile.id), kind=KIND_MODEL, name=profile.id,
        display_name=profile.display_name, origin=origin, keys=keys,
        host=str(profile.get_hostname() or ""),
        host_country="China (mainland)" if profile.id in _CHINA_IDS else None,
        data_policy=profile.data_policy, data_policy_note=profile.data_policy_note,
        price_known=known, price_note=note, selectable=selectable, models=models)


def model_entries() -> list[Entry]:
    from agents.core.llm.hermes_provider_table import ADOPTED_MODEL_PROVIDER_IDS
    from agents.core.llm.providers import get_profile

    out = []
    for pid, selectable in NATIVE_MODEL_IDS:
        try:
            out.append(_model_entry(get_profile(pid), ORIGIN_NATIVE, selectable))
        except KeyError:
            continue
    from agents.core.llm.hermes_profiles import is_adopted_profile

    for pid in ADOPTED_MODEL_PROVIDER_IDS:
        try:
            profile = get_profile(pid)
        except KeyError:
            continue
        if not is_adopted_profile(profile):
            # A signed package the owner installed under this id is theirs, not Hermes's.
            continue
        out.append(_model_entry(profile, ORIGIN_HERMES, True))
    return out


def entries() -> list[Entry]:
    return search_entries() + model_entries()


def find(eid: str) -> Entry | None:
    return next((e for e in entries() if e.id == eid), None)


def managed_keys() -> frozenset[str]:
    """Every key name the panel may set (nothing else is accepted)."""
    return frozenset(name for e in entries() for name in e.keys)


# ── status ───────────────────────────────────────────────────────────────────────

#: The outcome of the last "Test" per entry in this process (no value, no body).
LAST_TEST: dict[str, dict] = {}


def _selected_compatible() -> str:
    try:
        from agents.core.settings_db import get_value

        return str(get_value("llm", "compatible_provider", "") or "").strip().lower()
    except Exception:  # noqa: BLE001
        return ""


def _search_primary() -> tuple[str, str]:
    """(the backend choice, the provider that answers now) — read as a search would."""
    from agents.core.plugins import web_providers

    backend = web_providers.configured_backend()
    try:
        plugin = _search_view()
        selection = web_providers.resolve(plugin)
        return backend, (selection.primary.name if selection.primary else "")
    except Exception:  # noqa: BLE001
        return backend, ""


def _search_view():
    from types import SimpleNamespace

    return SimpleNamespace(tavily_api_key=env_str("TAVILY_API_KEY"), searxng_url=env_str("SEARXNG_URL"))


def readers(all_entries: list[Entry] | None = None) -> dict[str, list[str]]:
    """Key name -> the ids of every entry that reads it."""
    out: dict[str, list[str]] = {}
    for e in (entries() if all_entries is None else all_entries):
        for name in e.keys:
            out.setdefault(name, []).append(e.id)
    return out


def _key_state(entry: Entry, by_name: dict[str, list[str]] | None = None) -> dict:
    """The key in effect for *entry*: the first of its names that is set, else its own
    primary name (``entry.keys[0]``), not set.

    ``shared_with``: the other entries that read the same name. ``own``: whether the key
    in effect was given for this entry — typed in the panel for it (or confirmed as the
    same key), or set in ``.env`` under a name no other entry reads. A key typed for a
    sibling is never this entry's: it shows as ``shared``, is not tested here and is not
    used by this entry's choice without its own consent."""
    if not entry.keys:
        return {"name": "", "primary": "", "set": False, "source": None, "hint": None,
                "shared_with": [], "own": False, "stored_copy": False}
    by_name = readers() if by_name is None else by_name
    name = next((n for n in entry.keys if integration_keys.status(n)["set"]), entry.keys[0])
    state = integration_keys.status(name)
    shared_with = [eid for eid in by_name.get(name, []) if eid != entry.id]
    if not state["set"]:
        own = False
    elif state["source"] == "hub":
        own = entry.id in integration_keys.owners(name)
    else:
        own = not shared_with
    stored = state["source"] == "env" and integration_keys.stored_copy(name)
    return {"name": name, "primary": entry.keys[0], **state, "shared_with": shared_with,
            "own": own, "stored_copy": stored}


def _status(entry: Entry, key: dict, selected: str, primary: str) -> str:
    last = LAST_TEST.get(entry.id)
    if not key["set"]:
        return "not_set_up"
    if not key["own"]:
        return "shared"
    if last is not None and not last.get("ok"):
        return "error"
    if entry.kind == KIND_SEARCH:
        return "active" if primary == entry.name else "key_set"
    if entry.kind == KIND_MODEL:
        try:
            from agents.core.llm import provider_probe

            seen = provider_probe.last(entry.name)
        except Exception:  # noqa: BLE001
            seen = None
        if seen is not None and seen.get("verdict") not in ("ok", "no_listing", "rate_limited"):
            return "error"
        if not entry.selectable or selected == entry.name:
            return "active"
    return "key_set"


def as_dict(entry: Entry, *, selected: str, backend: str, primary: str,
            by_name: dict[str, list[str]] | None = None) -> dict:
    key = _key_state(entry, by_name)
    choice_env = integration_keys.env_owned(WEB_BACKEND) if entry.kind == KIND_SEARCH else False
    primary_shared = [eid for eid in (by_name or readers()).get(key["primary"], []) if eid != entry.id]
    return {
        "id": entry.id, "kind": entry.kind, "name": entry.name, "display_name": entry.display_name,
        "origin": entry.origin, "status": _status(entry, key, selected, primary),
        "key": {"names": list(entry.keys), "name": key["name"], "primary": key["primary"],
                "set": key["set"], "source": key["source"], "hint": key["hint"],
                "own": key["own"], "shared_with": key["shared_with"],
                "primary_shared_with": primary_shared,
                "stored_copy": key["stored_copy"],
                "editable": not integration_keys.env_owned(key["primary"])},
        "facts": {"host": entry.host, "host_country": entry.host_country,
                  "data_policy": entry.data_policy, "data_policy_note": entry.data_policy_note,
                  "price_known": entry.price_known, "price_note": entry.price_note,
                  "receives": ("your search queries" if entry.kind == KIND_SEARCH
                               else "your conversations (the prompts and replies of the turns it answers)")},
        "selectable": entry.selectable,
        "selected": ((backend == entry.name) if entry.kind == KIND_SEARCH
                     else (selected == entry.name if entry.selectable else (key["set"] and key["own"]))),
        "choice_editable": not choice_env,
        "models": list(entry.models),
        "last_test": LAST_TEST.get(entry.id),
    }


def skills_summary() -> dict:
    try:
        from agents.core.skills import hermes_catalog

        catalog = hermes_catalog.load()
        counts = dict(catalog.index.get("counts", {}))
        return {"id": "skills.hermes-catalog", "kind": KIND_SKILLS, "origin": ORIGIN_HERMES,
                "display_name": "Hermes skills catalog", "available": True,
                "commit": str(catalog.commit or "")[:8], "counts": counts,
                "installable": int(counts.get("instruction", 0) or 0),
                "status": "active", "where": "skills-import"}
    except Exception as exc:  # noqa: BLE001
        return {"id": "skills.hermes-catalog", "kind": KIND_SKILLS, "origin": ORIGIN_HERMES,
                "display_name": "Hermes skills catalog", "available": False,
                "error": type(exc).__name__, "status": "error", "where": "skills-import"}


def listing() -> dict:
    selected = _selected_compatible()
    backend, primary = _search_primary()
    all_entries = entries()
    by_name = readers(all_entries)
    rows = [as_dict(e, selected=selected, backend=backend, primary=primary, by_name=by_name)
            for e in all_entries]
    return {"integrations": rows, "skills": skills_summary(),
            "search": {"backend": backend, "answers": primary,
                       "choice_source": ("env" if integration_keys.env_owned(WEB_BACKEND)
                                         else ("hub" if integration_keys.placed_here(WEB_BACKEND) else None))},
            "model": {"selected": selected},
            "precedence": "env"}


__all__ = ["KIND_MODEL", "KIND_SEARCH", "KIND_SKILLS", "LAST_TEST", "SEARCH_ROWS", "WEB_BACKEND",
           "entries", "find", "listing", "managed_keys", "skills_summary"]
