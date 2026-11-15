"""Restore consent-pinned command placeholders without activating extensions.

Stored rows are routing hints only. Current consent is checked synchronously during
restore and again around every awaited activation/dispatch; package identity and
activation epoch are enforced by the runtime's pinned activate/dispatch APIs.
"""
from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .consent import declared_digest
from .manifest import ExtensionManifest

logger = logging.getLogger("jarvis.extensions.restore")

_HASH = re.compile(r"[0-9a-f]{64}\Z")


class RestoredCommandError(RuntimeError):
    """Bounded failure for a restored command callback."""

    _REASONS = frozenset({
        "restored_command_unavailable", "restored_command_superseded",
        "restored_command_activation_failed", "restored_command_dispatch_failed",
    })

    def __init__(self, reason: str = "restored_command_unavailable") -> None:
        self.reason = reason if reason in self._REASONS else "restored_command_unavailable"
        super().__init__(self.reason)


@dataclass(slots=True)
class _Row:
    hint: Any
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    runtime: Any = None
    expected_epoch: int = 0
    activation: Any = None
    attempt_epoch: int | None = None
    placeholder_bindings: tuple[Any, ...] = ()
    activation_bindings: tuple[Any, ...] = ()


class RestoredExtensionCommands:
    """Install data-only command routes and activate only on an owner invocation."""

    def __init__(self, bindings, consent, hints, runtime_provider: Callable[[], Any], enabled: Callable[[], bool]):
        self.bindings = bindings
        self.consent = consent
        self.hints = hints
        self.runtime_provider = runtime_provider
        self.enabled = enabled
        self._rows: dict[str, _Row] = {}

    def restore(self) -> tuple[str, ...]:
        """Synchronously register eligible placeholders; never obtain a runtime."""
        for extension_id in tuple(self._rows):
            self.forget(extension_id)
        try:
            hints = tuple(self.hints.read_all())
        except Exception:
            return ()
        if self._enabled_now() is not True:
            return ()

        # Reject duplicate ids and every participant in a cross-row canonical or
        # underscore/hyphen spelling collision before any host command is installed.
        id_counts: dict[str, int] = {}
        spelling_owners: dict[str, set[str]] = {}
        for hint in hints:
            manifest = getattr(hint, "manifest", None)
            extension_id = getattr(manifest, "id", None)
            commands = getattr(manifest, "commands", ())
            if isinstance(extension_id, str):
                id_counts[extension_id] = id_counts.get(extension_id, 0) + 1
            if not isinstance(extension_id, str) or not isinstance(commands, (tuple, list)):
                continue
            for name in commands:
                if not isinstance(name, str):
                    continue
                for spelling in {name, name.replace("_", "-")}:
                    spelling_owners.setdefault(spelling, set()).add(extension_id)
        colliding_ids = {name for owners in spelling_owners.values() if len(owners) > 1 for name in owners}

        accepted: list[tuple[str, Any]] = []
        for hint in hints:
            manifest = getattr(hint, "manifest", None)
            extension_id = getattr(manifest, "id", None)
            if (not isinstance(manifest, ExtensionManifest) or not isinstance(extension_id, str)
                    or id_counts.get(extension_id) != 1 or extension_id in colliding_ids
                    or not manifest.commands):
                continue
            if not self._hint_well_formed(hint):
                continue
            if not self._authorized(hint):
                continue
            try:
                self.bindings.check(manifest)
            except Exception:
                logger.warning("Saved extension route skipped: command namespace unavailable")
                continue
            accepted.append((extension_id, hint))

        restored: list[str] = []
        for extension_id, hint in sorted(accepted):
            state = _Row(hint)
            self._rows[extension_id] = state

            async def invoke(name, ctx, *, _id=extension_id, _state=state):
                principal = getattr(ctx, "principal", None)
                if getattr(principal, "admin", False) is not True:
                    return "This extension command requires the owner."
                return await self._invoke(_id, _state, name, ctx)

            try:
                installed = self.bindings.install(hint.manifest, invoke)
            except Exception:
                self._rows.pop(extension_id, None)
                continue
            if not installed:
                self._rows.pop(extension_id, None)
                continue
            state.placeholder_bindings = tuple(installed)
            restored.append(extension_id)
        return tuple(restored)

    @staticmethod
    def _same_bindings(left: Any, right: tuple[Any, ...]) -> bool:
        return (isinstance(left, tuple) and bool(right) and len(left) == len(right)
                and all(actual is expected for actual, expected in zip(left, right, strict=True)))

    def _registrations(self, extension_id: str):
        registrations = getattr(self.bindings, "registrations", None)
        if not isinstance(registrations, dict):
            return None
        return registrations.get(extension_id)

    def _fence_owned_runtime(self, extension_id: str, state: _Row) -> None:
        runtime = state.runtime
        if runtime is None:
            return
        epochs = getattr(runtime, "_activation_epochs", None)
        if not isinstance(epochs, dict):
            return
        current_epoch = epochs.get(extension_id, 0)
        if type(current_epoch) is not int or current_epoch < 0:
            return
        active = self._runtime_activation(runtime, extension_id)
        # Fence only an epoch this callback can attribute to its in-flight attempt,
        # or an exact activation handle it successfully acquired. Never advance a
        # foreign activation's epoch just because this old route is being forgotten.
        if (state.attempt_epoch is not None
                and current_epoch == state.attempt_epoch + 1 and active is None) or (state.activation is not None and active is state.activation
              and current_epoch == state.expected_epoch):
            epochs[extension_id] = current_epoch + 1

    def forget(self, extension_id: str) -> bool:
        """Invalidate callback state and remove only this row's exact bindings."""
        state = self._rows.pop(extension_id, None)
        if state is None:
            return False
        self._fence_owned_runtime(extension_id, state)
        current = self._registrations(extension_id)
        if (self._same_bindings(current, state.placeholder_bindings)
                or self._same_bindings(current, state.activation_bindings)):
            with contextlib.suppress(Exception):
                self.bindings.remove(extension_id)
        return True

    @staticmethod
    def _hint_well_formed(hint: Any) -> bool:
        manifest = getattr(hint, "manifest", None)
        package_hash = getattr(hint, "package_hash", None)
        revision = getattr(hint, "grant_revision", None)
        digest = getattr(hint, "declared_digest", None)
        if (not isinstance(manifest, ExtensionManifest)
                or not isinstance(package_hash, str) or _HASH.fullmatch(package_hash) is None
                or not isinstance(revision, str) or _HASH.fullmatch(revision) is None
                or not isinstance(digest, str) or _HASH.fullmatch(digest) is None):
            return False
        try:
            return declared_digest(manifest) == digest
        except Exception:
            return False

    def _enabled_now(self) -> bool:
        try:
            result = self.enabled()
        except Exception:
            return False
        return result if type(result) is bool else False

    def _authorized(self, hint: Any) -> bool:
        if self._enabled_now() is not True:
            return False
        try:
            decision = self.consent.check(hint.manifest)
        except Exception:
            return False
        return (getattr(decision, "allowed", False) is True
                and getattr(decision, "declared_digest", getattr(decision, "digest", None))
                == hint.declared_digest
                and getattr(decision, "grant_revision", None) == hint.grant_revision)

    def _provider_runtime(self, state: _Row):
        try:
            runtime = self.runtime_provider()
        except Exception:
            raise RestoredCommandError() from None
        if inspect.isawaitable(runtime) or runtime is None:
            raise RestoredCommandError() from None
        if state.runtime is not None and runtime is not state.runtime:
            raise RestoredCommandError("restored_command_superseded")
        return runtime

    @staticmethod
    def _runtime_epoch(runtime: Any, extension_id: str) -> int | None:
        epochs = getattr(runtime, "_activation_epochs", None)
        if not isinstance(epochs, dict):
            return None
        value = epochs.get(extension_id, 0)
        return value if type(value) is int and value >= 0 else None

    @staticmethod
    def _runtime_activation(runtime: Any, extension_id: str):
        active = getattr(runtime, "_active", None)
        if isinstance(active, dict):
            return active.get(extension_id)
        active_method = getattr(runtime, "active", None)
        if callable(active_method):
            try:
                return next((item for item in active_method()
                             if getattr(getattr(item, "manifest", None), "id", None) == extension_id), None)
            except Exception:
                return None
        return None

    def _row_authorized_for_runtime(self, extension_id: str, state: _Row, runtime: Any) -> bool:
        if self._rows.get(extension_id) is not state or not self._authorized(state.hint):
            return False
        try:
            return self.runtime_provider() is runtime and state.runtime is runtime
        except Exception:
            return False

    def _row_is_current(self, extension_id: str, state: _Row, runtime: Any | None = None,
                        activation: Any | None = None) -> bool:
        if self._rows.get(extension_id) is not state or not self._authorized(state.hint):
            return False
        if runtime is None:
            return True
        if not self._row_authorized_for_runtime(extension_id, state, runtime):
            return False
        if self._runtime_epoch(runtime, extension_id) != state.expected_epoch:
            return False
        return (activation is None or (state.activation is activation
                and self._runtime_activation(runtime, extension_id) is activation))

    def _invalidate(self, extension_id: str, state: _Row) -> None:
        if self._rows.get(extension_id) is state:
            self.forget(extension_id)

    async def _retire_late_owned_activation(self, runtime: Any, extension_id: str, activation: Any) -> None:
        if self._runtime_activation(runtime, extension_id) is not activation:
            return
        deactivate = getattr(runtime, "deactivate", None)
        if not callable(deactivate):
            return
        try:
            result = deactivate(extension_id, expected_activation=activation)
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.warning("Stale extension activation cleanup could not be confirmed")

    async def _invoke(self, extension_id: str, state: _Row, name: str, ctx: Any) -> str:
        if self._rows.get(extension_id) is not state:
            raise RestoredCommandError()
        async with state.lock:
            if not self._row_is_current(extension_id, state):
                self._invalidate(extension_id, state)
                raise RestoredCommandError()
            try:
                runtime = self._provider_runtime(state)
            except RestoredCommandError:
                self._invalidate(extension_id, state)
                raise

            if state.runtime is None:
                state.runtime = runtime
                state.expected_epoch = 0
                epoch = self._runtime_epoch(runtime, extension_id)
                if epoch != 0 or self._runtime_activation(runtime, extension_id) is not None:
                    self._invalidate(extension_id, state)
                    raise RestoredCommandError("restored_command_superseded")
            elif not self._row_is_current(extension_id, state, runtime):
                self._invalidate(extension_id, state)
                raise RestoredCommandError("restored_command_superseded")

            if state.activation is None:
                captured_epoch = state.expected_epoch
                if (self._runtime_epoch(runtime, extension_id) != captured_epoch
                        or self._runtime_activation(runtime, extension_id) is not None):
                    self._invalidate(extension_id, state)
                    raise RestoredCommandError("restored_command_superseded")
                state.attempt_epoch = captured_epoch
                try:
                    activation = await runtime.activate(
                        state.hint.manifest,
                        expected_package_hash=state.hint.package_hash,
                        expected_grant_revision=state.hint.grant_revision,
                        expected_epoch=captured_epoch,
                    )
                except Exception:
                    state.attempt_epoch = None
                    if self._rows.get(extension_id) is not state:
                        # No activation handle was returned, so a current active
                        # object cannot safely be attributed to this attempt.
                        raise RestoredCommandError() from None
                    now_epoch = self._runtime_epoch(runtime, extension_id)
                    if (self._authorized(state.hint)
                            and self._runtime_activation(runtime, extension_id) is None
                            and now_epoch == captured_epoch + 1
                            and self._row_authorized_for_runtime(extension_id, state, runtime)):
                        state.expected_epoch = now_epoch
                        raise RestoredCommandError("restored_command_activation_failed") from None
                    self._invalidate(extension_id, state)
                    raise RestoredCommandError("restored_command_superseded") from None

                state.attempt_epoch = None
                if self._rows.get(extension_id) is not state:
                    await self._retire_late_owned_activation(runtime, extension_id, activation)
                    raise RestoredCommandError()
                current_epoch = self._runtime_epoch(runtime, extension_id)
                state.expected_epoch = current_epoch if current_epoch is not None else captured_epoch
                state.activation = activation
                if (current_epoch != captured_epoch + 1
                        or self._runtime_activation(runtime, extension_id) is not activation
                        or not self._row_is_current(extension_id, state, runtime, activation)):
                    await self._retire_late_owned_activation(runtime, extension_id, activation)
                    self._invalidate(extension_id, state)
                    raise RestoredCommandError("restored_command_superseded")
                state.activation_bindings = tuple(self._registrations(extension_id) or ())

            activation = state.activation
            if not self._row_is_current(extension_id, state, runtime, activation):
                self._invalidate(extension_id, state)
                raise RestoredCommandError("restored_command_superseded")
            args = getattr(ctx, "args", None)
            if not isinstance(name, str) or not isinstance(args, str):
                raise RestoredCommandError()
            try:
                result = await runtime.dispatch_command(name, args, expected_activation=activation)
            except Exception:
                if not self._row_is_current(extension_id, state, runtime, activation):
                    self._invalidate(extension_id, state)
                    raise RestoredCommandError("restored_command_superseded") from None
                raise RestoredCommandError("restored_command_dispatch_failed") from None
            if not isinstance(result, str):
                raise RestoredCommandError("restored_command_dispatch_failed")
            if not self._row_is_current(extension_id, state, runtime, activation):
                self._invalidate(extension_id, state)
                raise RestoredCommandError("restored_command_superseded")
            return result


__all__ = ["RestoredCommandError", "RestoredExtensionCommands"]
