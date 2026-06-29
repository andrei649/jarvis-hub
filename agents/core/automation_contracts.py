"""automation_contracts.py — 0.45 reusable high-risk-automation contract templates.

A **pure, offline decision layer** that generalizes the mandate→gate pattern
already hand-rolled in ``payments.py`` (per-payment cap, allowlist, currency,
expiry, cumulative cap) so a *new* high-risk automation can declare its policy
as a **contract template** instead of re-implementing a bespoke gate.

Design — deliberately conservative, matching the project's invariants:

- **Decision only, never executes.** ``evaluate`` returns whether a request is
  *admissible* and whether it *requires approval*. There is no executor here; the
  caller still routes an admissible request through the existing approval queue.
- **Denial is a controlled reason code, not an exception.** Ordinary input never
  raises; a violated constraint returns a stable ``reason`` string.
- **Fail-closed.** An unknown contract kind, or any internal error inside a
  constraint, denies (``admissible=False``) rather than letting a request through.
- **Pure & offline.** No I/O, no globals, no clock except an injectable ``now`` —
  fully unit-testable. ``requires_approval`` defaults to ``True`` (high-risk).
- **Opt-in / default-off.** This is a library. Nothing in the running app wires a
  registry or evaluates a contract until a caller adopts it, so behavior is
  unchanged by default. Binding it into ``plugin_gate``/the action kernel is a
  deliberate later wave.

A constraint reads from a single merged *view* (``{**context, **payload}`` —
payload wins), so a cap/allowlist can be either a template-time constant **or** a
runtime value supplied via ``context`` (e.g. a mandate's per-payment cap). Limits
may be a literal or a ``callable(view) -> value`` for the runtime case.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

# A limit is either a constant or a function of the merged view (runtime value).
Limit = float | int | Callable[[Mapping[str, Any]], Any]
# A constraint check: given the merged view + now, return a denial reason or None.
Check = Callable[[Mapping[str, Any], float], str | None]


def _resolve(limit: Limit, view: Mapping[str, Any]) -> Any:
    """A limit may be a constant or ``callable(view)`` for a runtime value."""
    return limit(view) if callable(limit) else limit


@dataclass(frozen=True)
class Constraint:
    """A named, pure predicate over the merged request view.

    ``check(view, now)`` returns a denial reason code (str) if violated, else
    ``None``. Any exception raised inside the check is treated as a denial
    (fail-closed), reported as ``constraint_error:<name>``.
    """

    name: str
    check: Check

    def evaluate(self, view: Mapping[str, Any], now: float) -> str | None:
        try:
            return self.check(view, now)
        except Exception:
            return f"constraint_error:{self.name}"


# ── reusable constraint factories (the building blocks distilled from payments) ──

def field_present(*fields: str) -> Constraint:
    """Every named field must be present and non-empty."""
    names = tuple(fields)

    def _check(view: Mapping[str, Any], now: float) -> str | None:
        for f in names:
            v = view.get(f)
            if v is None or v == "":
                return f"missing_field:{f}"
        return None

    return Constraint(name=f"field_present({','.join(names)})", check=_check)


def positive(field_name: str) -> Constraint:
    """Field must be a real, finite number > 0 (rejects bools/NaN/strings)."""

    def _check(view: Mapping[str, Any], now: float) -> str | None:
        v = view.get(field_name)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return f"invalid_number:{field_name}"
        if v != v or v <= 0:  # NaN or non-positive
            return f"non_positive:{field_name}"
        return None

    return Constraint(name=f"positive({field_name})", check=_check)


def at_most(field_name: str, limit: Limit) -> Constraint:
    """Field must be ``<= limit`` (the per-payment-cap shape). Over → ``over_max:<f>``."""

    def _check(view: Mapping[str, Any], now: float) -> str | None:
        v = view.get(field_name)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return f"invalid_number:{field_name}"
        if v > _resolve(limit, view):
            return f"over_max:{field_name}"
        return None

    return Constraint(name=f"at_most({field_name})", check=_check)


def at_least(field_name: str, limit: Limit) -> Constraint:
    """Field must be ``>= limit``. Under → ``under_min:<f>``."""

    def _check(view: Mapping[str, Any], now: float) -> str | None:
        v = view.get(field_name)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return f"invalid_number:{field_name}"
        if v < _resolve(limit, view):
            return f"under_min:{field_name}"
        return None

    return Constraint(name=f"at_least({field_name})", check=_check)


def one_of(field_name: str, allowed: set | frozenset | list | tuple | Callable[[Mapping[str, Any]], Any]) -> Constraint:
    """Field must be in the allowed set (the payee-allowlist shape).

    ``allowed`` may be a constant collection or ``callable(view) -> collection``
    so the allowlist can come from a runtime mandate.
    """

    def _check(view: Mapping[str, Any], now: float) -> str | None:
        pool = _resolve(allowed, view)
        try:
            ok = view.get(field_name) in pool
        except TypeError:
            return f"value_not_allowed:{field_name}"
        return None if ok else f"value_not_allowed:{field_name}"

    return Constraint(name=f"one_of({field_name})", check=_check)


def equals(field_name: str, expected: Any | Callable[[Mapping[str, Any]], Any]) -> Constraint:
    """Field must equal ``expected`` (the currency-match shape). Else ``mismatch:<f>``."""

    def _check(view: Mapping[str, Any], now: float) -> str | None:
        if view.get(field_name) != _resolve(expected, view):
            return f"mismatch:{field_name}"
        return None

    return Constraint(name=f"equals({field_name})", check=_check)


def not_expired(field_name: str) -> Constraint:
    """If ``view[field]`` is set (epoch seconds), ``now`` must not be past it.

    A missing/``None`` expiry means "no expiry" and passes — mirroring an
    open-ended mandate.
    """

    def _check(view: Mapping[str, Any], now: float) -> str | None:
        exp = view.get(field_name)
        if exp is None:
            return None
        if not isinstance(exp, (int, float)) or isinstance(exp, bool):
            return f"invalid_expiry:{field_name}"
        return "expired" if now > exp else None

    return Constraint(name=f"not_expired({field_name})", check=_check)


def cumulative_at_most(value_field: str, total: Limit, *, spent_field: str) -> Constraint:
    """``spent + value`` must stay ``<= total`` (the cumulative total-cap shape).

    ``spent`` defaults to 0 when absent. Rounds to 2 dp to match the money path.
    """

    def _check(view: Mapping[str, Any], now: float) -> str | None:
        v = view.get(value_field)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return f"invalid_number:{value_field}"
        spent = view.get(spent_field, 0) or 0
        if not isinstance(spent, (int, float)) or isinstance(spent, bool):
            return f"invalid_number:{spent_field}"
        if round(spent + v, 2) > _resolve(total, view):
            return "over_total"
        return None

    return Constraint(name=f"cumulative_at_most({value_field}+{spent_field})", check=_check)


def predicate(name: str, ok: Callable[[Mapping[str, Any], float], bool], *, reason: str) -> Constraint:
    """Escape hatch: ``ok(view, now)`` truthy passes, else returns ``reason``."""

    def _check(view: Mapping[str, Any], now: float) -> str | None:
        return None if ok(view, now) else reason

    return Constraint(name=name, check=_check)


# ── the decision + template ──────────────────────────────────────────────────

@dataclass(frozen=True)
class ContractDecision:
    """The outcome of evaluating a request against a contract template."""

    kind: str
    admissible: bool
    requires_approval: bool
    reason: str | None = None
    checked: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "admissible": self.admissible,
            "requires_approval": self.requires_approval,
            "reason": self.reason,
            "checked": list(self.checked),
        }


@dataclass(frozen=True)
class ContractTemplate:
    """A declarative policy for one high-risk automation *kind*.

    Constraints are evaluated **in declared order**; the first violation
    short-circuits and is reported (deterministic reason). An admissible result
    still carries ``requires_approval`` — defaulting to ``True`` for high-risk —
    so the caller knows to route it through human approval before acting.
    """

    kind: str
    constraints: tuple[Constraint, ...] = ()
    requires_approval: bool = True
    description: str = ""

    def evaluate(
        self,
        payload: Mapping[str, Any] | None = None,
        *,
        context: Mapping[str, Any] | None = None,
        now: float | None = None,
        audit: Callable[[str, dict], None] | None = None,
    ) -> ContractDecision:
        """Run the constraints; return a controlled decision. Never raises for
        ordinary input. ``payload`` wins over ``context`` in the merged view."""
        ts = time.time() if now is None else now
        view: dict = {}
        if context:
            view.update(context)
        if payload:
            view.update(payload)

        checked: list[str] = []
        reason: str | None = None
        for c in self.constraints:
            checked.append(c.name)
            reason = c.evaluate(view, ts)
            if reason is not None:
                break

        decision = ContractDecision(
            kind=self.kind,
            admissible=reason is None,
            requires_approval=self.requires_approval,
            reason=reason,
            checked=tuple(checked),
        )
        if audit is not None:
            # Auditing is best-effort and must never break the gate.
            with contextlib.suppress(Exception):
                audit("contract.evaluate", decision.as_dict())
        return decision


@dataclass
class ContractRegistry:
    """A small in-memory registry of templates, keyed by automation ``kind``.

    Opt-in: an app builds one and looks up a template by the action kind.
    ``evaluate`` on an unknown kind **fails closed** (denied, requires approval).
    """

    _templates: dict[str, ContractTemplate] = field(default_factory=dict)

    def register(self, template: ContractTemplate, *, replace: bool = False) -> ContractRegistry:
        if not isinstance(template, ContractTemplate) or not template.kind:
            raise ValueError("a ContractTemplate with a non-empty kind is required")
        if template.kind in self._templates and not replace:
            raise ValueError(f"contract kind already registered: {template.kind}")
        self._templates[template.kind] = template
        return self

    def get(self, kind: str) -> ContractTemplate | None:
        return self._templates.get(kind)

    def kinds(self) -> list[str]:
        return sorted(self._templates)

    def evaluate(self, kind: str, payload: Mapping[str, Any] | None = None, **kwargs) -> ContractDecision:
        template = self._templates.get(kind)
        if template is None:
            return ContractDecision(
                kind=kind,
                admissible=False,
                requires_approval=True,
                reason="unknown_contract",
                checked=(),
            )
        return template.evaluate(payload, **kwargs)
