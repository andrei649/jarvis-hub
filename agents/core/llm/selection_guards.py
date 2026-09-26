"""H378 — be warned before choosing a model that is very expensive or trains on your data.

Choosing a model was an ordinary settings write. A $50-per-million-tokens model, or an
OpenRouter ``:free`` variant served by providers that may train on the prompts, was stored
at once with no price shown and nothing asked. Now every model choice passes one registry
of guards, server-side and before it is stored, on every surface that picks a model: the
settings write (HUD and v1 console), a settings import, ``nerva config set`` and a job's
model pin. A guard registered here appears on all of them at once.

- **cost** — a model whose output costs at least ``llm.cost_confirm_usd_per_mtok`` ($40 per
  million tokens by default; 0 never asks) needs ``confirm_expensive``. The finding names
  its input and output prices (``cost_estimator.MODELS``; an unpriced model is not asked).
- **data policy** — a model or route whose vendor trains on prompts (the provider profile's
  ``data_policy``, agents/core/llm/providers) needs ``acknowledge_training``. That
  acknowledgement is a consent event: it is written to the audit log before the choice is
  stored, and a choice whose consent row cannot be written is not stored.

A confirmation is never stored with the choice: the next choice asks again.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from .providers import DATA_POLICIES, get_profile, list_profiles

logger = logging.getLogger("jarvis.llm.selection_guards")

__all__ = ["DATA_POLICIES", "Choice", "Finding", "SelectionRefused", "GUARDS", "register", "evaluate",
           "enforce", "price_of", "choices_from_settings", "choices_from_job", "consent_rows"]

COST_SETTING = ("llm", "cost_confirm_usd_per_mtok")
DEFAULT_COST_LINE = 40.0
CONFIRM_EXPENSIVE = "confirm_expensive"
ACKNOWLEDGE_TRAINING = "acknowledge_training"


@dataclass(frozen=True)
class Choice:
    """One model being chosen: the setting (or pin) that picks it, its provider and model.
    ``route`` names a routing choice that is not a model (OpenRouter's data collection)."""

    setting: str
    provider: str
    model: str
    route: str = ""


@dataclass(frozen=True)
class Finding:
    guard: str
    needs: str
    choice: Choice
    message: str
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"guard": self.guard, "needs": self.needs, "setting": self.choice.setting,
                "provider": self.choice.provider, "model": self.choice.model,
                "message": self.message, "detail": dict(self.detail)}


class SelectionRefused(ValueError):
    """A model choice a guard asked about and the caller did not clear."""

    def __init__(self, findings: list[Finding], missing: list[str]) -> None:
        self.findings = findings
        self.missing = missing
        super().__init__("; ".join(f.message for f in findings))

    def payload(self) -> dict:
        """The 409 body: every finding (so a caller resends every flag at once) and the
        flags still missing."""
        return {"error": "selection_guard", "detail": str(self), "needs": self.missing,
                "guards": [f.as_dict() for f in self.findings]}


# ── the price table ──────────────────────────────────────────────────────────────

def price_of(model: str) -> dict | None:
    """``{"input", "output"}`` USD per million tokens for *model*, or None if unpriced. A routed
    slug (``vendor/model``) and a variant (``model:beta``) are priced by the model."""
    from . import cost_estimator

    name = str(model or "").strip()
    if not name:
        return None
    base = name.split(":", 1)[0]
    for candidate in (name, base, base.rsplit("/", 1)[-1]):
        row = cost_estimator.MODELS.get(candidate)
        if row is not None:
            return {"input": float(row["input"]), "output": float(row["output"])}
    return None


def _cost_line() -> float:
    try:
        from agents.core import settings_db

        value = settings_db.get_value(*COST_SETTING, DEFAULT_COST_LINE)
    except Exception:  # noqa: BLE001 — an unreadable store keeps the shipped line
        value = DEFAULT_COST_LINE
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return DEFAULT_COST_LINE
    return float(value)


def _usd(amount: float) -> str:
    return f"${amount:g}"


# ── the guards ───────────────────────────────────────────────────────────────────

Guard = Callable[[Choice], "Finding | None"]
GUARDS: list[Guard] = []


def register(guard: Guard) -> Guard:
    """Add a guard; it runs on every model-selection surface from then on."""
    GUARDS.append(guard)
    return guard


@register
def cost_guard(choice: Choice) -> Finding | None:
    if not choice.model:
        return None
    line = _cost_line()
    price = price_of(choice.model)
    if line <= 0 or price is None or price["output"] < line:
        return None
    return Finding("cost", CONFIRM_EXPENSIVE, choice,
                   f"{choice.model} costs {_usd(price['input'])}/M input and {_usd(price['output'])}/M output tokens "
                   f"(the owner is asked at {_usd(line)}/M output and up, {COST_SETTING[0]}.{COST_SETTING[1]})",
                   {"input": price["input"], "output": price["output"], "threshold": line})


def _profiles_for(provider: str):
    if provider:
        try:
            return [get_profile(provider)]
        except KeyError:
            pass
    return list_profiles()


@register
def data_policy_guard(choice: Choice) -> Finding | None:
    if choice.route == "data_collection=allow":
        return Finding("data_policy", ACKNOWLEDGE_TRAINING, choice,
                       "OpenRouter may then send your prompts to upstream providers that store or train on them "
                       "(llm.openrouter_data_collection=allow)",
                       {"policy": "trains-on-inputs", "provider": "openrouter"})
    if not choice.model:
        return None
    # An unknown provider (a job pin without one) is checked against every profile's
    # model rows: the stricter answer, since the pin may be served by any of them.
    for profile in _profiles_for(choice.provider):
        policy, note = profile.data_policy_for(choice.model)
        if policy == "trains-on-inputs":
            return Finding("data_policy", ACKNOWLEDGE_TRAINING, choice,
                           f"{choice.model} on {profile.display_name}: the vendor may train on your prompts and "
                           f"completions — {note}",
                           {"policy": policy, "provider": profile.id, "note": note})
    return None


# ── running them ─────────────────────────────────────────────────────────────────

def evaluate(choices: Iterable[Choice]) -> list[Finding]:
    """Every guard, once per choice."""
    findings: list[Finding] = []
    for choice in choices:
        for guard in list(GUARDS):
            finding = guard(choice)
            if finding is not None:
                findings.append(finding)
    return findings


def enforce(choices: Iterable[Choice], *, confirm_expensive: bool = False,
            acknowledge_training: bool = False) -> list[Finding]:
    """The findings, all cleared — or :class:`SelectionRefused` naming the flags missing.
    A flag clears only a literal ``True``."""
    findings = evaluate(choices)
    given = {CONFIRM_EXPENSIVE: confirm_expensive is True, ACKNOWLEDGE_TRAINING: acknowledge_training is True}
    missing = sorted({f.needs for f in findings if not given.get(f.needs, False)})
    if missing:
        raise SelectionRefused(findings, missing)
    return findings


def consent_rows(findings: Iterable[Finding], surface: str) -> list[tuple[str, str, bool]]:
    """``(action, preview, required)`` audit rows for cleared findings. A training
    acknowledgement is a consent row that must land before the choice is stored; a cost
    confirmation is recorded best-effort."""
    rows = []
    for f in findings:
        what = f"{f.choice.provider or 'any provider'}/{f.choice.model}" if f.choice.model else f.choice.setting
        if f.needs == ACKNOWLEDGE_TRAINING:
            rows.append(("model_training_consent",
                         f"consent ({surface}): {f.choice.setting} → {what}, knowing the vendor may train on prompts "
                         f"({f.detail.get('provider', f.choice.provider)})", True))
        elif f.needs == CONFIRM_EXPENSIVE:
            rows.append(("model_cost_confirmed",
                         f"confirmed ({surface}): {f.choice.setting} → {what} at {_usd(f.detail['input'])}/M input, "
                         f"{_usd(f.detail['output'])}/M output", False))
    return rows


class ConsentNotRecorded(RuntimeError):
    """The audit log could not take a required consent row, so the choice is not stored."""


def _orch():
    from agents.core.app_state import get_orch

    return get_orch()


_HUB = object()


def record(findings: Iterable[Finding], surface: str, audit_log: Any = _HUB) -> None:
    """Write the rows of :func:`consent_rows` to *audit_log* (default: the hub's; None:
    there is none). Raises :class:`ConsentNotRecorded` when a required row cannot be
    written."""
    rows = consent_rows(findings, surface)
    if not rows:
        return
    if audit_log is _HUB:
        orch = _orch()
        audit_log = getattr(orch, "audit", None) if orch is not None else None
    from agents.core.security.types import SecurityEvent, SecurityEventType

    for action, preview, required in rows:
        try:
            if audit_log is None:
                raise RuntimeError("no audit log")
            audit_log.log(SecurityEvent(event_type=SecurityEventType.SETTINGS_CHANGE, timestamp=time.time(),
                                        content_preview=preview, action_taken=action))
        except Exception as exc:  # noqa: BLE001
            if required:
                raise ConsentNotRecorded("the acknowledgement could not be written to the audit log; "
                                         "nothing was changed") from exc
            logger.warning("could not audit a confirmed model choice (%s)", action)


# ── what a surface is choosing ───────────────────────────────────────────────────

def choices_from_settings(category: str, values: dict, current: Callable[[str], Any]) -> list[Choice]:
    """The model choices an ``llm`` settings write makes. *current* reads a stored ``llm``
    key, for the half of a provider/model pair the write leaves as it is."""
    if category != "llm" or not isinstance(values, dict):
        return []
    choices = []
    if isinstance(values.get("claude_model"), str) and values["claude_model"].strip():
        choices.append(Choice("llm.claude_model", "anthropic", values["claude_model"].strip()))
    if isinstance(values.get("gemini_model"), str) and values["gemini_model"].strip():
        choices.append(Choice("llm.gemini_model", "gemini", values["gemini_model"].strip()))
    if "compatible_model" in values or "compatible_provider" in values:
        provider = values["compatible_provider"] if "compatible_provider" in values else current("compatible_provider")
        model = values["compatible_model"] if "compatible_model" in values else current("compatible_model")
        # An empty provider routes the compatible slot to Gemini's own model setting.
        if isinstance(provider, str) and provider and isinstance(model, str) and model.strip():
            choices.append(Choice("llm.compatible_model", provider, model.strip()))
    if values.get("openrouter_data_collection") == "allow":
        choices.append(Choice("llm.openrouter_data_collection", "openrouter", "", route="data_collection=allow"))
    return choices


def choices_from_job(options: Any) -> list[Choice]:
    """The choice a job's model pin makes (none without a model pin)."""
    if not isinstance(options, dict) or not isinstance(options.get("model"), str) or not options["model"].strip():
        return []
    provider = options.get("provider") if isinstance(options.get("provider"), str) else ""
    return [Choice("job.model", provider, options["model"].strip())]
