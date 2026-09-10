"""One effort ladder for every wire, clamped to what each wire actually accepts.

Nerva's only "think harder" lever used to be swapping to a different *local*
model, which is coarse and cloud-blind. This module is the other lever: one
ordered ladder the rest of the system speaks, plus a per-model capability table
that decides, per request, three separate things:

  1. whether the wire has an effort vocabulary at all (if not: send nothing),
  2. which level of ours it accepts (clamped to the nearest **weaker** one —
     asking for more thinking than a wire offers must never silently buy more
     than its own default), and
  3. which parameters the wire *rejects* once thinking is in play — the reason
     this module removes ``temperature`` rather than only adding keys.

Point 3 is not hypothetical: Anthropic removed the sampling parameters on the
4.7 generation and later, so a request that carries ``temperature`` to
``claude-opus-5`` is a 400 whether or not anyone asked for effort. That is why
``apply_anthropic`` runs on every call, not only when an effort is configured.

Nothing here changes behaviour on a default install: with no effort requested
and a model whose wire accepts sampling, the payload comes out unchanged.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

# The ladder is deliberately wider than any single vendor's vocabulary: it is the
# language the *caller* speaks, and each wire's table narrows it. Ordered weakest
# to strongest; "none" means "do not think", "ultra" means "everything you have".
LADDER: tuple[str, ...] = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
    "ultra",
)

_RANK = {level: index for index, level in enumerate(LADDER)}

# Spellings people (and other products) actually use for the same rungs.
_ALIASES: dict[str, str] = {
    "off": "none",
    "disabled": "none",
    "zero": "none",
    "min": "minimal",
    "lowest": "minimal",
    "med": "medium",
    "normal": "medium",
    "default": "medium",
    "x-high": "xhigh",
    "extra-high": "xhigh",
    "veryhigh": "xhigh",
    "very-high": "xhigh",
    "maximum": "max",
    "highest": "ultra",
    "ultra-high": "ultra",
}


def normalize(value: object) -> str | None:
    """Return a ladder level for *value*, or None when it names no rung.

    None is the "say nothing" answer: an empty setting, a typo, or a level this
    build has never heard of all mean *leave the request alone*, never guess.
    """
    if value is None:
        return None
    text = str(value).strip().lower().replace("_", "-").replace(" ", "-")
    if not text:
        return None
    if text in _RANK:
        return text
    return _ALIASES.get(text)


def rank(level: str) -> int:
    """Position of *level* on the ladder; raises for anything not on it."""
    try:
        return _RANK[level]
    except KeyError as exc:
        raise ValueError(f"unknown reasoning effort level: {level!r}") from exc


def clamp(level: str, supported: tuple[str, ...] | list[str]) -> str | None:
    """The strongest supported level that is no stronger than *level*.

    This is the nearest-**weaker** rule: a wire that tops out at ``high`` answers
    a request for ``max`` with ``high``, never the other way round. Returns None
    when the wire supports nothing weak enough (the caller decides whether to
    floor or to send nothing — see ``resolve``).
    """
    ceiling = rank(level)
    best: str | None = None
    for candidate in supported:
        candidate_rank = _RANK.get(candidate)
        if candidate_rank is None or candidate_rank > ceiling:
            continue
        if best is None or candidate_rank > _RANK[best]:
            best = candidate
    return best


def resolve(level: str, supported: tuple[str, ...] | list[str]) -> tuple[str | None, str]:
    """Clamp *level* into *supported*, flooring rather than falling silent.

    Returns ``(effort, reason)``. The floor case matters: a wire whose weakest
    rung is ``low`` cannot honor ``minimal``, and answering with *nothing* would
    hand the request the wire's own default — ``high`` on the current Anthropic
    models, i.e. the opposite of what was asked. Flooring to the weakest rung is
    the closest honest answer and is never stronger than that default.
    """
    if not supported:
        return None, "unsupported"
    exact = clamp(level, supported)
    if exact is not None:
        return exact, "exact" if exact == level else "clamped"
    floor = min(supported, key=lambda candidate: _RANK.get(candidate, len(LADDER)))
    return floor, "floored"


@dataclass(frozen=True, slots=True)
class WireCapability:
    """What one model family accepts — both what to add and what to remove."""

    # Levels this family's effort vocabulary accepts, weakest first. Empty means
    # the family has no effort parameter and none must ever be sent.
    efforts: tuple[str, ...] = ()
    # "adaptive"  → thinking: {"type": "adaptive"}
    # "budget"    → thinking: {"type": "enabled", "budget_tokens": N}
    # "none"      → construct no thinking block at all
    thinking: str = "none"
    # True when the family thinks unless told otherwise (Opus 5, Sonnet 5,
    # Fable 5). Only then does "none" have to be *said*; elsewhere omitting the
    # thinking block already means off.
    thinking_default_on: bool = False
    # Strongest effort at which the family accepts thinking: {"type": "disabled"}.
    # None means thinking cannot be turned off on this family at all.
    disable_max: str | None = None
    # False when temperature/top_p/top_k return a 400 on this family.
    accepts_sampling: bool = True

    def strongest(self) -> str | None:
        if not self.efforts:
            return None
        return max(self.efforts, key=lambda level: _RANK.get(level, -1))


#: The family that has no opinion: send nothing, remove nothing.
UNSUPPORTED = WireCapability()

# ── Anthropic ────────────────────────────────────────────────────────────────
# Four generations with four different contracts. Patterns are matched against a
# normalized model id, longest pattern first, so "claude-opus-4-8" is decided
# before the "claude-opus-4" catch-all can claim it.

_FIVE_LEVELS = ("low", "medium", "high", "xhigh", "max")
_FOUR_SIX_LEVELS = ("low", "medium", "high", "max")
_FOUR_FIVE_LEVELS = ("low", "medium", "high")

# Opus 5 / Sonnet 5: full ladder, thinking on by default, sampling rejected, and
# thinking may only be disabled at effort "high" or lower.
_CAP_FIVE = WireCapability(
    efforts=_FIVE_LEVELS,
    thinking="adaptive",
    thinking_default_on=True,
    disable_max="high",
    accepts_sampling=False,
)
# Fable 5 / 5.1: same ladder, but thinking is always on — there is no off switch.
_CAP_FABLE = WireCapability(
    efforts=_FIVE_LEVELS,
    thinking="adaptive",
    thinking_default_on=True,
    disable_max=None,
    accepts_sampling=False,
)
# Opus 4.7 / 4.8: full ladder and adaptive thinking, but omitting the thinking
# block already means "off", so "none" needs no disable block. Sampling rejected.
_CAP_FOUR_SEVEN = WireCapability(
    efforts=_FIVE_LEVELS,
    thinking="adaptive",
    thinking_default_on=False,
    disable_max=None,
    accepts_sampling=False,
)
# Opus 4.6 / Sonnet 4.6: adaptive thinking arrived here, "xhigh" had not; still
# accepts sampling parameters.
_CAP_FOUR_SIX = WireCapability(
    efforts=_FOUR_SIX_LEVELS,
    thinking="adaptive",
    thinking_default_on=False,
    disable_max=None,
    accepts_sampling=True,
)
# Opus 4.5: the first model with an effort parameter, before adaptive thinking.
# Effort alone carries the request — this build sends no thinking block here,
# which is the conservative reading of a contract we have not verified on a wire.
_CAP_FOUR_FIVE = WireCapability(
    efforts=_FOUR_FIVE_LEVELS,
    thinking="none",
    accepts_sampling=True,
)
# Everything older that thinks: no effort vocabulary, a manual token budget.
_CAP_BUDGET = WireCapability(efforts=(), thinking="budget", accepts_sampling=True)

_ANTHROPIC_TABLE: tuple[tuple[str, WireCapability], ...] = (
    ("claude-fable-5", _CAP_FABLE),
    ("claude-mythos-5", _CAP_FABLE),
    ("claude-opus-5", _CAP_FIVE),
    ("claude-sonnet-5", _CAP_FIVE),
    ("claude-opus-4-8", _CAP_FOUR_SEVEN),
    ("claude-opus-4-7", _CAP_FOUR_SEVEN),
    ("claude-opus-4-6", _CAP_FOUR_SIX),
    ("claude-sonnet-4-6", _CAP_FOUR_SIX),
    ("claude-opus-4-5", _CAP_FOUR_FIVE),
    ("claude-sonnet-4-5", _CAP_BUDGET),
    ("claude-haiku-4-5", _CAP_BUDGET),
    ("claude-opus-4-1", _CAP_BUDGET),
    ("claude-opus-4", _CAP_BUDGET),
    ("claude-sonnet-4", _CAP_BUDGET),
    ("claude-3-7-sonnet", _CAP_BUDGET),
)

# Longest pattern first: prefix matching is only safe if the specific families
# get to answer before the generic ones.
_ANTHROPIC_PATTERNS: tuple[tuple[str, WireCapability], ...] = tuple(
    sorted(_ANTHROPIC_TABLE, key=lambda row: len(row[0]), reverse=True)
)

# How a ladder rung becomes a token budget on the families that only speak
# budgets. Anthropic's floor is 1024 and the budget must stay under max_tokens.
_MIN_BUDGET = 1024
_BUDGETS: dict[str, int] = {
    "minimal": 1024,
    "low": 2048,
    "medium": 4096,
    "high": 8192,
    "xhigh": 16384,
    "max": 24576,
    "ultra": 32768,
}


def _split_levels(raw: str) -> list[object]:
    """Split a human-written level list: commas and/or whitespace, either way."""

    return list(raw.replace(",", " ").split())


def _model_key(model: str) -> str:
    """Normalize a model id enough to match a family pattern against it."""
    return str(model or "").strip().lower().replace(".", "-").replace("_", "-")


def parse_overrides(raw: object) -> dict[str, tuple[str, ...]]:
    """Read the owner's per-model override map.

    Accepts a mapping or a JSON object string, ``{"model-prefix": ["low", ...]}``.
    An empty list is meaningful and is the point of the whole mechanism: it says
    "this model takes no effort key", which is how a family that starts
    rejecting the parameter gets silenced without a release.
    """
    if not raw:
        return {}
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return {}
    if not isinstance(data, Mapping):
        return {}
    parsed: dict[str, tuple[str, ...]] = {}
    for key, value in data.items():
        pattern = _model_key(key)
        if not pattern:
            continue
        if isinstance(value, str):
            candidates: list[object] = _split_levels(value)
        elif isinstance(value, (list, tuple)):
            candidates = list(value)
        else:
            continue
        levels = tuple(
            level for level in (normalize(item) for item in candidates)
            if level is not None and level != "none"
        )
        parsed[pattern] = levels
    return parsed


def anthropic_capability(
    model: str, overrides: Mapping[str, tuple[str, ...]] | None = None
) -> WireCapability:
    """The capability record for an Anthropic model id.

    Unknown ids resolve to ``UNSUPPORTED`` on purpose: a model this build has
    never heard of gets exactly the request it would have got before this module
    existed. Silence is the only answer that cannot 400.
    """
    key = _model_key(model)
    base = UNSUPPORTED
    for pattern, capability in _ANTHROPIC_PATTERNS:
        if key.startswith(pattern) or pattern in key:
            base = capability
            break
    if not overrides:
        return base
    for pattern in sorted(overrides, key=len, reverse=True):
        if pattern and (key.startswith(pattern) or pattern in key):
            return replace(base, efforts=tuple(overrides[pattern]))
    return base


@dataclass(frozen=True, slots=True)
class EffortPlan:
    """What one request should carry, decided before it is built."""

    effort: str | None = None
    thinking: dict | None = None
    drop_sampling: bool = False
    requested: str | None = None
    reason: str = "none"
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def changes_payload(self) -> bool:
        return bool(self.effort or self.thinking or self.drop_sampling)


def plan(
    capability: WireCapability,
    requested: str | None,
    *,
    max_tokens: int = 0,
) -> EffortPlan:
    """Turn a request for *requested* into the parameters this wire accepts.

    The three interesting outcomes: nothing asked (only the removals the wire
    demands survive), "none" asked (say it where it has to be said, floor where
    it cannot), and a level asked (clamped, with the matching thinking block).
    """
    drop = not capability.accepts_sampling
    if requested is None:
        # No effort asked for. The wire's own rejections still apply — that is
        # the 400 this row is named after, and it does not wait for a knob.
        return EffortPlan(drop_sampling=drop, reason="unset")

    if requested == "none":
        if capability.thinking == "adaptive" and capability.thinking_default_on:
            if capability.disable_max is not None:
                # Disabling is only accepted alongside a low enough effort, so the
                # two have to be decided together or the pair is a 400.
                effort, why = resolve(capability.disable_max, capability.efforts)
                return EffortPlan(
                    effort=effort,
                    thinking={"type": "disabled"},
                    drop_sampling=drop,
                    requested=requested,
                    reason="disabled",
                    notes=(why,),
                )
            # Thinking cannot be turned off here; the weakest rung is as close as
            # this wire gets to "don't think".
            effort, why = resolve("minimal", capability.efforts)
            return EffortPlan(
                effort=effort,
                thinking={"type": "adaptive"},
                drop_sampling=drop,
                requested=requested,
                reason="floored-instead-of-disabled",
                notes=(why,),
            )
        # Everywhere else, omitting the thinking block already means off.
        return EffortPlan(drop_sampling=drop, requested=requested, reason="omitted")

    effort, why = resolve(requested, capability.efforts)
    thinking: dict | None = None
    if capability.thinking == "adaptive":
        thinking = {"type": "adaptive"}
    elif capability.thinking == "budget":
        budget = _budget_for(requested, max_tokens)
        if budget is not None:
            thinking = {"type": "enabled", "budget_tokens": budget}
            # A manual thinking budget and a custom temperature do not travel
            # together on these families; dropping it takes the wire default.
            drop = True
    if effort is None and thinking is None:
        return EffortPlan(drop_sampling=drop, requested=requested, reason="unsupported")
    return EffortPlan(
        effort=effort,
        thinking=thinking,
        drop_sampling=drop,
        requested=requested,
        # No effort field went out, but a thinking block did. Naming this
        # "budget" was wrong on the adaptive families, which never build one.
        reason=why if effort is not None else "thinking-only",
        notes=(why,),
    )


def _budget_for(level: str, max_tokens: int) -> int | None:
    """A thinking budget for *level* that fits under *max_tokens*, or None.

    None means "this answer has no room to think": a budget must be at least
    1024 tokens and strictly smaller than the answer budget, so a small
    ``max_tokens`` ends the conversation rather than buying a 400.
    """
    wanted = _BUDGETS.get(level)
    if wanted is None:
        return None
    ceiling = int(max_tokens or 0) - _MIN_BUDGET
    if ceiling < _MIN_BUDGET:
        return None
    return max(_MIN_BUDGET, min(wanted, ceiling))


_SAMPLING_KEYS = ("temperature", "top_p", "top_k")


def apply_anthropic(
    payload: dict,
    model: str,
    requested: object = None,
    *,
    overrides: Mapping[str, tuple[str, ...]] | None = None,
) -> EffortPlan:
    """Fit *payload* to what *model* accepts, in place. Returns the plan applied.

    Called on every Anthropic request, including the ones nobody asked to think
    harder about: the sampling removal is a property of the model, not of the
    knob.
    """
    capability = anthropic_capability(model, overrides)
    # H679 — the registry is the front door, the family table only the source
    # behind it. A declaration recorded off the hot path (a catalog probe, an
    # operator correction) therefore reaches the wire without a release, and a
    # model nobody has declared stays exactly as silent as it was.
    vocabulary = supported_reasoning_efforts("anthropic", model, overrides=overrides)
    if vocabulary is not None and vocabulary != capability.efforts:
        capability = replace(capability, efforts=vocabulary)
    decided = plan(
        capability,
        normalize(requested),
        max_tokens=int(payload.get("max_tokens") or 0),
    )
    if decided.drop_sampling:
        for key in _SAMPLING_KEYS:
            payload.pop(key, None)
    if decided.thinking is not None:
        payload["thinking"] = dict(decided.thinking)
    if decided.effort is not None:
        output_config = payload.get("output_config")
        if isinstance(output_config, dict):
            output_config["effort"] = decided.effort
        else:
            payload["output_config"] = {"effort": decided.effort}
    return decided



# ── H679 — the tri-state reasoning-effort registry ───────────────────────────
#
# One question, asked per request, with three genuinely different answers:
#
#   None          undeclared. Nobody has told this build what the model takes,
#                 so the transport keeps whatever defaults it already had. This
#                 is also the answer while a live catalog is still cold — the
#                 hot path never blocks on I/O to find out.
#   ()            declared empty. This model accepts no effort level at all, so
#                 the effort field is omitted (and stripped if a caller set it).
#   ("low", ...)  declared vocabulary, weakest first. Clamp into it.
#
# Collapsing the first two is the bug this row exists to prevent: "we do not
# know" and "it rejects the parameter" produce opposite request bodies, and only
# one of them is safe to guess. Nerva shipped exactly that collapse — every
# non-Anthropic profile carried an empty tuple meaning "undeclared".
#
# The registry governs the *effort vocabulary* only. Whether a model takes a
# thinking block, and in which shape, stays with ``WireCapability``: a family can
# reject every effort level and still accept a manual thinking budget.

_VOCAB_CACHE: dict[tuple[str, str], tuple[str, ...]] = {}


def _vocab_key(provider_id: object, model: object) -> tuple[str, str]:
    return (
        str(provider_id or "").strip().lower(),
        _model_key(model),
    )


def declare_reasoning_efforts(
    provider_id: str, model: str, efforts: object
) -> tuple[str, ...]:
    """Record what one model accepts, so the hot path can answer from cache.

    This is the write half of the contract: a catalog probe, an admin setting or
    a provider's own ``/models`` response calls it once, off the request path,
    and every later request reads the answer without waiting. Passing an empty
    iterable declares "no effort level at all", which is a real answer and not
    the same as never having called this.

    Levels that are not on the ladder are dropped rather than trusted — a
    vocabulary is only useful if ``clamp`` can rank every rung in it.
    """
    if isinstance(efforts, str):
        candidates: list[object] = _split_levels(efforts)
    elif isinstance(efforts, (list, tuple, set, frozenset)):
        candidates = list(efforts)
    else:
        candidates = []
    levels = tuple(
        level for level in (normalize(item) for item in candidates)
        if level is not None and level != "none"
    )
    ordered = tuple(rung for rung in LADDER if rung in levels)
    _VOCAB_CACHE[_vocab_key(provider_id, model)] = ordered
    return ordered


def forget_reasoning_efforts(provider_id: str = "", model: str = "") -> None:
    """Drop declarations, so a refresh cannot be shadowed by a stale answer."""

    if not provider_id:
        _VOCAB_CACHE.clear()
        return
    wanted = str(provider_id).strip().lower()
    if model:
        _VOCAB_CACHE.pop(_vocab_key(provider_id, model), None)
        return
    for key in [key for key in _VOCAB_CACHE if key[0] == wanted]:
        del _VOCAB_CACHE[key]


def _builtin_vocab(
    provider_id: str,
    model: str,
    overrides: Mapping[str, tuple[str, ...]] | None = None,
) -> tuple[str, ...] | None:
    """The vocabulary this build knows synchronously, or None if it knows none.

    Anthropic is the one vendor whose families are pinned in-tree, so it answers
    without a catalog and is always warm. Everything else stays undeclared until
    something declares it — which is the honest answer, not a guess.
    """
    if provider_id != "anthropic":
        return None
    capability = anthropic_capability(model, overrides)
    if capability is UNSUPPORTED:
        # A model id this build has never seen. Undeclared, not "rejects".
        return None
    return capability.efforts


def supported_reasoning_efforts(
    provider_id: str,
    model: str,
    *,
    overrides: Mapping[str, tuple[str, ...]] | None = None,
) -> tuple[str, ...] | None:
    """The tri-state answer for one model. Never blocks; never guesses.

    A declaration always wins over the built-in table: that is how a family whose
    contract moves under us gets corrected without a release.
    """
    declared = _VOCAB_CACHE.get(_vocab_key(provider_id, model))
    if declared is not None:
        return declared
    return _builtin_vocab(str(provider_id or "").strip().lower(), model, overrides)


def clamp_reasoning_effort(
    provider_id: str,
    model: str,
    level: object,
    *,
    overrides: Mapping[str, tuple[str, ...]] | None = None,
) -> tuple[str | None, str]:
    """``(effort_to_send, reason)`` for one model — the canonical clamp, once.

    ``reason`` is one of ``undeclared``, ``unsupported``, ``unreadable``,
    ``exact``, ``clamped`` or ``floored``. The two None-effort reasons are kept
    apart on purpose: ``undeclared`` means the transport should leave its own
    defaults alone, ``unsupported`` means the field must be omitted.

    Every caller goes through here rather than writing its own map. A hand-rolled
    ladder is what inverts — ``ultra`` quietly falling through to ``medium`` while
    ``xhigh`` maps to ``high`` — and an inverted ladder spends more on the cheap
    request and less on the expensive one, silently.
    """
    vocabulary = supported_reasoning_efforts(provider_id, model, overrides=overrides)
    if vocabulary is None:
        return None, "undeclared"
    if not vocabulary:
        return None, "unsupported"
    wanted = normalize(level)
    if wanted is None or wanted == "none":
        return None, "unreadable" if wanted is None else "unsupported"
    return resolve(wanted, vocabulary)

def vendor_efforts(vendor: str) -> tuple[str, ...]:
    """The union of levels one vendor can express, weakest first.

    This is what a provider profile advertises: not what a given model takes,
    which only ``anthropic_capability`` can answer, but the vocabulary the
    vendor's families draw from.
    """
    if str(vendor or "").strip().lower() != "anthropic":
        return ()
    union: set[str] = set()
    for _pattern, capability in _ANTHROPIC_TABLE:
        union.update(capability.efforts)
    return tuple(level for level in LADDER if level in union)


__all__ = [
    "LADDER",
    "EffortPlan",
    "UNSUPPORTED",
    "WireCapability",
    "anthropic_capability",
    "apply_anthropic",
    "clamp",
    "clamp_reasoning_effort",
    "declare_reasoning_efforts",
    "forget_reasoning_efforts",
    "normalize",
    "parse_overrides",
    "plan",
    "rank",
    "resolve",
    "supported_reasoning_efforts",
    "vendor_efforts",
]
