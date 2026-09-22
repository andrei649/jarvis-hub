"""provider_routing.py — H583: which upstream provider may serve an OpenRouter request.

OpenRouter is an aggregator: one model id is served by several upstream providers,
and by default OpenRouter picks among them on its own. Six knobs steer that pick,
and they travel as one ``provider`` object in the request body:

* ``sort`` — rank the candidates by ``price``, ``throughput`` or ``latency``;
* ``only`` — a whitelist of provider slugs, everything else is excluded;
* ``ignore`` — a blacklist of provider slugs;
* ``order`` — an explicit priority; providers not listed remain as fallbacks;
* ``require_parameters`` — refuse a provider that would silently drop a request
  parameter (the tool schema, temperature, …);
* ``data_collection`` — ``deny`` routes only to providers that do not store or train
  on prompts, ``allow`` lets any provider serve.

The last two are privacy and correctness controls rather than tuning: a product
that measures its %-local should not, the one time it does route to the cloud, land
the prompt on a provider that trains on it. ``data_collection`` is therefore seeded
``deny`` in the ``llm`` settings (``openrouter_*`` rows beside ``compatible_provider``)
and an owner opts in to ``allow``. The object goes to OpenRouter only — an arbitrary
OpenAI-compatible server does not know it — and falsy knobs are omitted so
OpenRouter's own defaults apply to them.

Pure module (no I/O, no httpx): ``settings_db`` imports the slug check from here to
refuse a bad write with a 422, and ``OpenRouterBackend`` rebuilds the object from
the settings rows before every request (and once at construction, to refuse a bad
stored value up front), so an owner's change governs the next request. An invalid
value raises :class:`ProviderRoutingInvalid` instead of being dropped, because
dropping an ``only`` or ``ignore`` entry would *widen* the set of providers the
owner allowed; the backend then sends nothing.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any

SORTS = ("price", "throughput", "latency")
DATA_COLLECTION = ("deny", "allow")
DEFAULT_DATA_COLLECTION = "deny"
SLUG_LISTS = ("only", "ignore", "order")
MAX_SLUGS = 32
# OpenRouter's lower-case provider slugs, with the ``/``-qualified variants it also
# accepts (``deepinfra/turbo``). Anything else — spaces, quotes, ``;`` — is not a slug.
SLUG = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,63}$")

# llm settings key → knob. The rows themselves are declared in settings_db.DEFAULTS.
SETTINGS_KEYS = {
    "sort": "openrouter_sort",
    "only": "openrouter_only",
    "ignore": "openrouter_ignore",
    "order": "openrouter_order",
    "require_parameters": "openrouter_require_parameters",
    "data_collection": "openrouter_data_collection",
}


class ProviderRoutingInvalid(ValueError):
    """A provider-routing knob holds a value OpenRouter would not understand."""


def _as_list(value: Any) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return list(value)
    raise ProviderRoutingInvalid(f"expected a list of provider slugs, got {type(value).__name__}")


def invalid_slugs(values: Iterable[Any]) -> list[str]:
    """The entries of *values* that are not provider slugs (case-insensitive)."""
    bad = []
    for value in values:
        if not isinstance(value, str) or not SLUG.match(value.strip().lower()):
            bad.append(repr(value)[:40])
    return bad


def _slugs(name: str, value: Any) -> list[str]:
    items = _as_list(value)
    bad = invalid_slugs(items)
    if bad:
        raise ProviderRoutingInvalid(f"{name}: not a provider slug: {', '.join(bad)}")
    out: list[str] = []
    for item in items:
        slug = item.strip().lower()
        if slug not in out:
            out.append(slug)
    if len(out) > MAX_SLUGS:
        raise ProviderRoutingInvalid(f"{name}: more than {MAX_SLUGS} provider slugs")
    return out


def slug_list_problem(name: str, values: Any) -> str:
    """``""`` when *values* is a usable slug list for knob *name*, else the reason.

    The settings write path calls this so a list the backend would refuse is
    refused at the 422 instead of disabling the route later.
    """
    try:
        _slugs(name, values)
    except ProviderRoutingInvalid as exc:
        return str(exc)
    return ""


def build_provider_block(
    *,
    sort: Any = "",
    only: Any = (),
    ignore: Any = (),
    order: Any = (),
    require_parameters: Any = False,
    data_collection: Any = "",
) -> dict[str, Any] | None:
    """OpenRouter's ``provider`` object from the six knobs, or ``None`` when all are unset.

    Validates every knob and raises :class:`ProviderRoutingInvalid` on the first bad
    one. Slugs are lower-cased and de-duplicated in order; ``require_parameters`` is
    sent only as a literal ``True``; empty knobs are left out.
    """
    block: dict[str, Any] = {}
    if sort not in ("", None):
        if not isinstance(sort, str) or sort.strip().lower() not in SORTS:
            raise ProviderRoutingInvalid(f"sort: {sort!r} is not one of {SORTS}")
        block["sort"] = sort.strip().lower()
    for name, value in (("only", only), ("ignore", ignore), ("order", order)):
        slugs = _slugs(name, value)
        if slugs:
            block[name] = slugs
    if not isinstance(require_parameters, bool):
        raise ProviderRoutingInvalid("require_parameters: expected a boolean")
    if require_parameters:
        block["require_parameters"] = True
    if data_collection not in ("", None):
        if not isinstance(data_collection, str) or data_collection.strip().lower() not in DATA_COLLECTION:
            raise ProviderRoutingInvalid(
                f"data_collection: {data_collection!r} is not one of {DATA_COLLECTION}")
        block["data_collection"] = data_collection.strip().lower()
    return block or None


def provider_routing_from_settings(read: Callable[[str, Any], Any]) -> dict[str, Any]:
    """The six knobs from the ``llm`` settings rows, via ``read(key, default)``."""
    return {
        "sort": read(SETTINGS_KEYS["sort"], "") or "",
        "only": read(SETTINGS_KEYS["only"], []) or [],
        "ignore": read(SETTINGS_KEYS["ignore"], []) or [],
        "order": read(SETTINGS_KEYS["order"], []) or [],
        "require_parameters": read(SETTINGS_KEYS["require_parameters"], False) or False,
        "data_collection": read(SETTINGS_KEYS["data_collection"], DEFAULT_DATA_COLLECTION)
        or DEFAULT_DATA_COLLECTION,
    }
