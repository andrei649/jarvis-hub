"""Exact command-registration ownership for extension command surfaces.

This module owns only host ``SlashCommand`` objects. It never composes or imports
an extension runtime and never activates or dispatches extension code itself.
"""
from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from typing import Any

from ..channels.outbound_safety import sanitize_outbound
from ..commands import ADMIN, ALIASES, CommandContext, CommandRegistry, SlashCommand
from .manifest import ExtensionManifest


class CommandBindingError(RuntimeError):
    """Bounded command-binding failure; never carries third-party text."""

    _REASONS = frozenset({
        "commands_unavailable", "command_collision", "command_not_owned",
        "command_registration_failed",
    })

    def __init__(self, reason: str) -> None:
        self.reason = reason if reason in self._REASONS else "command_registration_failed"
        super().__init__(self.reason)


_COMMAND_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


class ExtensionCommandBindings:
    """Install and remove exact owner-only SlashCommand objects by extension id."""

    def __init__(self, commands: CommandRegistry, reserved_commands: Callable[[], Any] = lambda: ()) -> None:
        self.commands = commands
        self.reserved_commands = reserved_commands
        self.registrations: dict[str, tuple[SlashCommand, ...]] = {}

    def check(self, manifest: ExtensionManifest) -> None:
        """Refuse any declared name whose full host-visible spelling is occupied."""
        if not isinstance(self.commands, CommandRegistry) or not isinstance(manifest, ExtensionManifest):
            raise CommandBindingError("commands_unavailable")
        if (not isinstance(manifest.id, str) or not _COMMAND_NAME.fullmatch(manifest.id)
                or not isinstance(manifest.commands, tuple)
                or any(not isinstance(name, str) or not _COMMAND_NAME.fullmatch(name)
                       for name in manifest.commands)
                or len(set(manifest.commands)) != len(manifest.commands)):
            raise CommandBindingError("commands_unavailable")
        if not manifest.commands:
            return
        try:
            # Resolve the provider on each check so configured/test-swapped quick
            # command surfaces are observed just like the existing runtime gate.
            from ..quick_commands import named as quick_command_named

            reserved = set(self.reserved_commands()) | set(ALIASES) | {"nerva"}
            candidates = {
                spelling
                for name in manifest.commands
                for spelling in (name, name.replace("_", "-"))
            }
            reserved.update(name for name in candidates if quick_command_named(name))
        except Exception:
            raise CommandBindingError("commands_unavailable") from None
        owned = self.registrations.get(manifest.id, ())
        for name in candidates:
            existing = self.commands.get(name)
            if name in reserved or (existing is not None and not any(existing is item for item in owned)):
                raise CommandBindingError("command_collision")

    def current(self, extension_id: str) -> bool:
        """Whether every canonical name and alias still maps to the exact owned objects."""
        if not isinstance(self.commands, CommandRegistry):
            return False
        owned = self.registrations.get(extension_id)
        if not owned:
            return False
        for command in owned:
            if self.commands.get(command.name) is not command:
                return False
            if any(self.commands.get(alias) is not command for alias in command.aliases):
                return False
        return True

    def _owns(self, extension_id: str, command: SlashCommand | None) -> bool:
        """Whether this captured handler object is still part of the live owner set."""
        owned = self.registrations.get(extension_id, ())
        return (command is not None
                and any(item is command for item in owned)
                and self.current(extension_id))

    def _unregister_exact(self, command: SlashCommand) -> None:
        """Remove every exact-owned spelling, even if its canonical name moved."""
        if not isinstance(self.commands, CommandRegistry):
            return
        if self.commands.unregister(command):
            return
        # CommandRegistry.unregister intentionally leaves aliases alone when its
        # canonical object has been replaced. Clear only aliases still pointing at
        # our exact object; never disturb a foreign registration.
        for alias in command.aliases:
            if self.commands._aliases.get(alias) is command:
                del self.commands._aliases[alias]

    def remove(self, extension_id: str) -> bool:
        """Forget one binding set and unregister only its exact current objects."""
        owned = self.registrations.pop(extension_id, None)
        if owned is None:
            return False
        if isinstance(self.commands, CommandRegistry):
            for command in owned:
                self._unregister_exact(command)
        return True

    def install(self, manifest: ExtensionManifest,
                invoke: Callable[[str, CommandContext], Any]) -> tuple[SlashCommand, ...]:
        """Precheck and claim the complete declared command set.

        `invoke` owns post-await authority/liveness checks. A lazy placeholder may
        replace its own SlashCommand during a valid invocation, so this binding
        owner only checks the captured object immediately before calling it.
        """
        if not callable(invoke):
            raise CommandBindingError("commands_unavailable")
        self.check(manifest)
        previous = self.registrations.pop(manifest.id, ())
        for command in previous:
            self._unregister_exact(command)

        registered: list[SlashCommand] = []
        try:
            for name in manifest.commands:
                requires_args = name in manifest.command_requires_args
                aliases = (name.replace("_", "-"),) if "_" in name else ()
                binding: list[SlashCommand | None] = [None]

                async def handler(ctx: CommandContext, *, _name=name, _id=manifest.id,
                                  _binding=binding) -> str:
                    # The registry enforces ADMIN before calling handlers; retain this
                    # direct guard because adapters/tests/internal callers can call one.
                    principal = getattr(ctx, "principal", None)
                    if getattr(principal, "admin", False) is not True:
                        return "This extension command requires the owner."
                    captured = _binding[0]
                    if not self._owns(_id, captured):
                        raise CommandBindingError("command_not_owned")
                    result = invoke(_name, ctx)
                    if not inspect.isawaitable(result):
                        raise CommandBindingError("command_registration_failed")
                    result = await result
                    if not isinstance(result, str):
                        raise CommandBindingError("command_registration_failed")
                    clean = str(sanitize_outbound(result))
                    return re.sub(r"(?m)^([ \t]*MEDIA:)", r"> \1", clean)

                command = SlashCommand(
                    name,
                    f"Sandboxed command from {manifest.id}.",
                    handler,
                    tier=ADMIN,
                    usage="<arguments>" if requires_args else "[arguments]",
                    aliases=aliases,
                    requires_args=requires_args,
                )
                binding[0] = command
                # Record before register: a hostile/partial registry wrapper may
                # insert this exact object and then raise. unregister remains exact.
                registered.append(command)
                self.commands.register(command)
        except CommandBindingError:
            for command in registered:
                self._unregister_exact(command)
            self.registrations.pop(manifest.id, None)
            raise
        except Exception:
            for command in registered:
                self._unregister_exact(command)
            self.registrations.pop(manifest.id, None)
            raise CommandBindingError("command_registration_failed") from None
        result = tuple(registered)
        if result:
            self.registrations[manifest.id] = result
        return result


__all__ = ["CommandBindingError", "ExtensionCommandBindings"]
