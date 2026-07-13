"""Canonical bridge from ambient decisions to the governed TaskQueue intake."""

from __future__ import annotations

from collections.abc import Callable

from .contracts import AmbientDecision, AmbientEvent, MonitorDefinition


class AmbientProposalSink:
    """Turn a disposition into a sanitized proposal, never an action call."""

    def __init__(
        self,
        govern_enqueue: Callable,
        *,
        generation_provider: Callable[[], int],
        remember_sink: Callable[[AmbientDecision, AmbientEvent, MonitorDefinition], object]
        | None = None,
    ) -> None:
        if not callable(govern_enqueue) or not callable(generation_provider):
            raise ValueError("ambient governed intake and generation provider are required")
        if remember_sink is not None and not callable(remember_sink):
            raise ValueError("ambient remember sink must be callable")
        self._enqueue = govern_enqueue
        self._generation = generation_provider
        self._remember = remember_sink

    def __call__(
        self,
        decision: AmbientDecision,
        event: AmbientEvent,
        definition: MonitorDefinition,
    ) -> int | None:
        if not isinstance(decision, AmbientDecision):
            raise ValueError("ambient decision is required")
        if decision.rung == "remember":
            if self._remember is not None:
                self._remember(decision, event, definition)
            return None
        if decision.rung in {"ignore", "monitor"}:
            return None
        generation = self._generation()
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            raise ValueError("ambient generation is invalid")
        payload = {
            "ambient_generation": generation,
            "consent_generation": decision.consent_generation,
            "event_fingerprint": decision.event_fingerprint,
            "monitor_hash": decision.monitor_hash,
            "monitor_id": decision.monitor_id,
            "monitor_version": decision.monitor_version,
            "rung": decision.rung,
            "source": event.source,
        }
        silent = decision.rung == "act_silently"
        return self._enqueue(
            "jarvis",
            "ambient.action" if silent else "ambient.decision",
            f"Ambient decision: {decision.monitor_id}",
            payload=payload,
            risk_tier=1 if silent else 2,
            autonomy_level="act" if silent else "ask",
            attention_mode=decision.attention_mode,
            origin="generated",
        )


__all__ = ["AmbientProposalSink"]
