"""S2: an extension's declared surface becomes callable only after isolation proves it.

S1 could read a descriptor and say what an extension *claims*. Nothing could run, so
a claim was all it was. This is the step that makes a claim callable, and the whole
design is one sentence: **the host never imports third-party code, and never trusts a
declaration it has not seen the code make from inside the sandbox.**

Four gates stand between a descriptor and a dispatch, in this order, each refusing on
its own:

1. **The runtime is enabled** — the same owner switch the acquisition path uses.
2. **Consent** — the owner agreed to exactly these declarations (``consent.py``). A
   manifest whose surface moved since comes back ``changed``, never silently granted.
3. **Signature and attestation** — the package store's existing ``require_runnable``
   proves the signed bytes, and the manifest must name this exact sandbox image and
   config. A signature is checked *again* at dispatch, against the hash pinned at
   activation, so a package swapped underneath an active extension is refused.
4. **Isolated registration** — ``register()`` runs in the sealed container and returns
   its declarations. ``validate_registration`` compares them with the manifest, exactly.
   Declaring one surface and registering another is the attack this closes, and it is
   the reason activation costs a sandbox round trip instead of a file read.

Two things are deliberately **not** here, because the rationale for these rows says
Nerva should not copy them:

* **No ``ctx``.** Hermes hands third-party code a host capability object. ``register()``
  takes no arguments and gets nothing. Declaring is data; every effect goes back
  through the host's own governed kinds.
* **No override.** An extension cannot replace a core command or a built-in tool.
  ``CommandRegistry.register`` refuses a duplicate name, so there is no last-writer.

The container itself is the acquisition profile: ``--network none``, ``--cap-drop ALL``,
``--read-only``, ``no-new-privileges``, bounded memory/pids/time. Nothing here relaxes it.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..capability_manifests import RollbackContract
from .command_bindings import CommandBindingError, ExtensionCommandBindings
from .consent import CHANGED, ExtensionConsentStore
from .manifest import MAX_EXTENSIONS, ExtensionManifest, ManifestError, validate_registration
from .manifest_catalog import ExtensionManifestCatalog

RESULT_PREFIX = "NERVA_EXTENSION_RESULT:"
# The in-sandbox refusal for a tool the extension does not declare. A rare code
# rather than 1 or 2, so it is not confused with an ordinary crash — and the worst
# an extension can do by exiting with it deliberately is refuse its own call.
UNDECLARED_EXIT = 97
# The extension declared the event but ships no `on_event`. Distinct from a crash:
# a manifest that declares an observation the code cannot perform is an authoring
# mistake, and saying so is more useful than "failed".
NO_OBSERVER_EXIT = 96
UNDECLARED_COMMAND_EXIT = 95
NO_COMMAND_HANDLER_EXIT = 94
MAX_INPUT_BYTES = 64 * 1024
SOURCE_MEMBER = "main.py"
#: H325 — what the capability registry says about an extension tool's call.
EXTENSION_TOOL_ROLLBACK = RollbackContract(
    mode="disable",
    description=("Revoke the extension's consent (nerva extensions consent <manifest> --revoke): "
                 "its tools come off the surface at once."),
    limitations="Completed calls are not undone; a manifest declares nothing about what a call writes.",
)


class ExtensionRuntimeError(RuntimeError):
    """Bounded reason codes only; third-party output never escapes as a message."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class Activation:
    manifest: ExtensionManifest
    package_hash: str
    version: str
    grant_revision: str

    def as_dict(self) -> dict:
        return {"id": self.manifest.id, "version": self.version,
                "package_hash": self.package_hash,
                "callable_tools": list(self.manifest.qualified_tools),
                "callable_commands": list(self.manifest.commands),
                "command_requires_args": list(self.manifest.command_requires_args),
                "observed_events": list(self.manifest.events)}


def _register_source() -> str:
    return (
        "import contextlib\n"
        "import importlib.util\n"
        "import io\n"
        "import json\n\n"
        "spec = importlib.util.spec_from_file_location('nerva_extension', '/workspace/source/main.py')\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        # Anything the extension prints is swallowed: only the envelope below is
        # read, so an extension cannot forge a result line by printing one.
        "with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):\n"
        "    declared = module.register()\n"
        "    if declared.get('commands') and not callable(getattr(module, 'command', None)):\n"
        f"        raise SystemExit({NO_COMMAND_HANDLER_EXIT})\n"
        f"print({RESULT_PREFIX!r} + json.dumps({{'ok': True, 'registered': declared}}, separators=(',', ':')))\n"
    )


def _dispatch_source() -> str:
    return (
        "import contextlib\n"
        "import importlib.util\n"
        "import io\n"
        "import json\n\n"
        "payload = json.loads(open('/workspace/contract/input.json', encoding='utf-8').read())\n"
        "spec = importlib.util.spec_from_file_location('nerva_extension', '/workspace/source/main.py')\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):\n"
        "    declared = module.register()\n"
        # The host checked this already. Checking it again *inside* the sandbox means
        # a tool the extension no longer declares cannot be reached even if the host's
        # view of it were stale.
        "    if payload['tool'] not in list(declared.get('tools') or ()):\n"
        f"        raise SystemExit({UNDECLARED_EXIT})\n"
        "    result = module.call(payload['tool'], payload['args'])\n"
        f"print({RESULT_PREFIX!r} + json.dumps({{'ok': True, 'result': result}}, separators=(',', ':')))\n"
    )


def _observe_source() -> str:
    """Deliver one lifecycle event. Nothing the observer returns is read.

    This script deliberately prints no result envelope. `observe` below checks the
    exit code and nothing else, so "an observer cannot inject prompt text, rewrite
    an identity or veto a decision" is true *by construction* rather than by
    filtering something out of a reply.
    """
    return (
        "import contextlib\n"
        "import importlib.util\n"
        "import io\n"
        "import json\n\n"
        "payload = json.loads(open('/workspace/contract/input.json', encoding='utf-8').read())\n"
        "spec = importlib.util.spec_from_file_location('nerva_extension', '/workspace/source/main.py')\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):\n"
        "    declared = module.register()\n"
        # Checked again inside the sandbox, exactly as dispatch does: an event the
        # extension no longer declares is not delivered even on a stale host view.
        "    if payload['event'] not in list(declared.get('events') or ()):\n"
        f"        raise SystemExit({UNDECLARED_EXIT})\n"
        "    observer = getattr(module, 'on_event', None)\n"
        "    if not callable(observer):\n"
        f"        raise SystemExit({NO_OBSERVER_EXIT})\n"
        "    observer(payload['event'], payload['payload'])\n"
    )


def _command_source() -> str:
    """No host context is passed to third-party command code."""
    return _dispatch_source().replace(
        "payload['tool']", "payload['command']"
    ).replace("declared.get('tools')", "declared.get('commands')").replace(
        f"SystemExit({UNDECLARED_EXIT})", f"SystemExit({UNDECLARED_COMMAND_EXIT})"
    ).replace("module.call(", "module.command(")


class ExtensionRuntime:
    """Activate and dispatch declared extension tools, in the acquisition sandbox."""

    def __init__(self, *, packages, profile, runtime_root, runner=None,
                 consent: ExtensionConsentStore | None = None, rpc=None,
                 enabled=lambda: False, max_input_bytes: int = MAX_INPUT_BYTES,
                 catalog: ExtensionManifestCatalog | None = None, commands=None,
                 reserved_commands=lambda: (),
                 command_bindings: ExtensionCommandBindings | None = None,
                 activation_hints=None) -> None:
        from ..acquisition.sandbox_profile import DockerSandboxRunner

        self.packages = packages
        self.profile = profile
        self.runtime_root = Path(runtime_root)
        self.runner = runner or DockerSandboxRunner(
            timeout_seconds=profile.timeout_seconds,
            max_output_bytes=profile.max_output_bytes,
        )
        self.consent = consent if consent is not None else ExtensionConsentStore()
        consent_path = getattr(self.consent, "_path", None)
        self.catalog = (catalog if catalog is not None else ExtensionManifestCatalog(
            Path(consent_path).with_name("manifest_catalog.json") if consent_path else None,
            consent_path=consent_path,
        ))
        # Named `rpc`, not `tool_rpc`: that attribute name is reserved for the
        # orchestrator's own binding contract, which is enforced lexically across
        # `agents/` (tests/test_orchestrator_bindings.py). This is a plain injected
        # collaborator, so it takes a name that cannot be confused with a binding.
        self.rpc = rpc
        self.enabled = enabled
        self.max_input_bytes = max(1024, min(1024 * 1024, int(max_input_bytes)))
        self._active: dict[str, Activation] = {}
        self._activation_epochs: dict[str, int] = {}
        self._mutation_locks: dict[str, asyncio.Lock] = {}
        self.activation_hints = activation_hints
        self._restoration_states: dict[str, dict[str, str]] = {}
        if command_bindings is None:
            command_bindings = ExtensionCommandBindings(commands, reserved_commands)
        elif commands is not None and commands is not command_bindings.commands:
            raise ValueError("command_bindings owns the command registry")
        self.command_bindings = command_bindings

    @property
    def command_bindings(self) -> ExtensionCommandBindings:
        return self._command_bindings

    @command_bindings.setter
    def command_bindings(self, value: ExtensionCommandBindings) -> None:
        self._command_bindings = value
        # Preserve the doctor projection API when composition injects or replaces
        # the shared helper after constructing the runtime.
        self._command_registrations = value.registrations

    @property
    def commands(self):
        return self.command_bindings.commands

    @commands.setter
    def commands(self, value):
        # Some compositions inject the registry after constructing the runtime.
        # Keep the shared helper pointed at that same live registry.
        self.command_bindings.commands = value

    @property
    def reserved_commands(self):
        return self.command_bindings.reserved_commands

    @reserved_commands.setter
    def reserved_commands(self, value):
        self.command_bindings.reserved_commands = value

    # ── state ────────────────────────────────────────────────────────────────
    def active(self) -> tuple[Activation, ...]:
        return tuple(self._active[name] for name in sorted(self._active))

    def callable_tools(self) -> tuple[str, ...]:
        return tuple(sorted(tool for row in self._active.values() for tool in row.manifest.qualified_tools))

    def restoration_status(self, extension_id: str) -> dict[str, str]:
        """Report only bounded persistence state, never store paths or exceptions."""
        if self.activation_hints is None:
            return {"state": "not_configured"}
        state = self._restoration_states.get(extension_id)
        if state is not None:
            return dict(state)
        try:
            if any(hint.manifest.id == extension_id for hint in self.activation_hints.read_all()):
                return {"state": "saved"}
        except Exception as exc:
            return {"state": "unknown", "reason": self._hint_failure_reason(exc)}
        return {"state": "unknown"}

    @staticmethod
    def _hint_failure_reason(error: Exception) -> str:
        allowed = {
            "activation_hints_unavailable", "activation_hints_corrupt",
            "activation_hints_capacity", "activation_hint_invalid",
            "activation_hints_durability_uncertain",
        }
        reason = getattr(error, "reason", None)
        return reason if isinstance(reason, str) and reason in allowed else "activation_hints_unavailable"

    def _save_activation_hint(self, activation: Activation) -> None:
        if self.activation_hints is None:
            return
        try:
            self.activation_hints.put(
                activation.manifest, activation.package_hash, activation.grant_revision
            )
        except Exception as exc:
            self._restoration_states[activation.manifest.id] = {
                "state": "save_failed", "reason": self._hint_failure_reason(exc)
            }
        else:
            self._restoration_states[activation.manifest.id] = {"state": "saved"}

    def _remove_activation_hint(self, extension_id: str) -> None:
        if self.activation_hints is None:
            return
        try:
            self.activation_hints.remove(extension_id)
        except Exception as exc:
            self._restoration_states[extension_id] = {
                "state": "remove_failed", "reason": self._hint_failure_reason(exc)
            }
        else:
            self._restoration_states[extension_id] = {"state": "removed"}

    async def deactivate(
        self, extension_id: str, *, expected_activation: Activation | None = None
    ) -> bool:
        """Revocation is host-side and immediate; no sandbox call can refuse it.

        The tools come off the RPC surface with in-flight calls cancelled, and the
        activation is dropped even if that removal fails — an extension the owner
        revoked must not stay callable because unregistering raised.

        A caller cleaning up a particular activation can pin that exact object.
        Its identity check must happen under the same lock as replacement so a
        delayed cleanup cannot retire a newer activation.
        """
        lock = self._mutation_locks.setdefault(extension_id, asyncio.Lock())
        if expected_activation is not None:
            async with lock:
                if self._active.get(extension_id) is not expected_activation:
                    return False
                self._activation_epochs[extension_id] = self._activation_epochs.get(extension_id, 0) + 1
                return await self._retire_activation(extension_id)

        # Deactivation is also a lifecycle fence for an activation that has not
        # finished or been published yet (including first activation from a hint).
        self._activation_epochs[extension_id] = self._activation_epochs.get(extension_id, 0) + 1
        async with lock:
            # Clear durable authority before unregistering: RPC cancellation can
            # block or cancel the rest of retirement, but a restart must not revive
            # this extension from an old grant hint.
            self._remove_activation_hint(extension_id)
            retired = await self._retire_activation(extension_id)
            return retired

    async def _retire_activation(self, extension_id: str) -> bool:
        activation = self._active.pop(extension_id, None)
        if activation is None:
            return False
        self.command_bindings.remove(extension_id)
        if self.rpc is not None:
            for tool in activation.manifest.qualified_tools:
                with contextlib.suppress(Exception):
                    await self.rpc.unregister_tool(tool, cancel_inflight=True)
        return True

    def _expose(self, activation: Activation) -> None:
        """Put the proven tools on the RPC surface.

        ``gated=False`` follows the acquired-capability precedent, and for the same
        reason: the container has no network, no capabilities and a read-only root,
        so the call itself is a contained computation rather than an external
        effect. The human decision is the owner's consent and activation, taken
        once — not an approval prompt per call. ``untrusted_output=True`` is the
        part that does matter every call: what comes back is third-party content,
        so the tool loop fences it as DATA and raises the turn's taint.
        """
        if self.rpc is None:
            return
        for tool in activation.manifest.qualified_tools:
            async def handler(args, _tool=tool):
                return await self.dispatch(_tool, args, expected_activation=activation)

            self.rpc.register_tool(
                tool, handler, gated=False, untrusted_output=True,
                # H399 — fail closed: a manifest has no read-only declaration, so
                # an extension tool never overlaps the other calls of its step.
                parallel_safe=False,
                description=f"Sandboxed extension tool {tool}.",
                input_schema={"type": "object", "additionalProperties": True},
                capability_id=f"tool:extension.{tool}",
                # H325 — ungated, but a manifest says nothing about what a call writes,
                # so the capability registry must not call it read-only.
                risk="sensitive",
                rollback=EXTENSION_TOOL_ROLLBACK,
            )

    # ── gates ────────────────────────────────────────────────────────────────
    def _require_enabled(self) -> None:
        try:
            live = self.enabled() is True
        except Exception:
            live = False
        if not live:
            raise ExtensionRuntimeError("extensions_disabled")

    def _check_commands(self, manifest) -> None:
        if not manifest.commands:
            return
        try:
            self.command_bindings.check(manifest)
        except CommandBindingError as exc:
            raise ExtensionRuntimeError(exc.reason) from None

    def _expose_commands(self, activation) -> None:
        if not activation.manifest.commands:
            return

        async def invoke(name, ctx):
            return await self.dispatch_command(name, ctx.args, expected_activation=activation)

        try:
            self.command_bindings.install(activation.manifest, invoke)
        except CommandBindingError as exc:
            raise ExtensionRuntimeError(exc.reason) from None

    def _require_consent(self, manifest: ExtensionManifest, revision: str | None = None) -> str:
        try:
            decision = self.consent.check(manifest)
        except Exception:
            raise ExtensionRuntimeError("consent_unavailable") from None
        if not decision.allowed:
            raise ExtensionRuntimeError("consent_changed" if decision.state == CHANGED else "consent_required")
        current = getattr(decision, "grant_revision", None)
        if not isinstance(current, str) or not current:
            raise ExtensionRuntimeError("consent_unavailable")
        if revision is not None and current != revision:
            raise ExtensionRuntimeError("consent_changed")
        return current

    def _require_package(self, manifest: ExtensionManifest):
        from ..acquisition.package_store import PackageStoreError

        try:
            record = self.packages.require_runnable(manifest.id)
        except PackageStoreError:
            raise ExtensionRuntimeError("package_unavailable") from None
        except Exception:
            raise ExtensionRuntimeError("package_unavailable") from None
        if (record.manifest.get("runtime_image") != self.profile.image
                or record.manifest.get("runtime_config_hash") != self.profile.config_hash):
            raise ExtensionRuntimeError("attestation_mismatch")
        if record.name != manifest.id or record.version != manifest.version:
            raise ExtensionRuntimeError("version_mismatch")
        return record

    @staticmethod
    def _signed_source(record) -> bytes:
        """The signed bytes, or nothing. A member whose hash moved is not source."""
        metadata = next((row for row in record.manifest.get("files", [])
                         if row.get("path") == SOURCE_MEMBER), None)
        if metadata is None:
            raise ExtensionRuntimeError("source_missing")
        try:
            content = (record.path / SOURCE_MEMBER).read_bytes()
        except OSError:
            raise ExtensionRuntimeError("source_missing") from None
        if len(content) != metadata.get("size") or hashlib.sha256(content).hexdigest() != metadata.get("sha256"):
            raise ExtensionRuntimeError("source_changed")
        return content

    # ── the sandbox round trip ───────────────────────────────────────────────
    async def _run(self, record, *, script: str, payload: bytes | None, envelope: bool = True):
        source_bytes = self._signed_source(record)
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="ext-run-", dir=self.runtime_root) as temporary:
            source = Path(temporary) / "source"
            contract = Path(temporary) / "contract"
            source.mkdir()
            contract.mkdir()
            (source / SOURCE_MEMBER).write_bytes(source_bytes)
            (contract / "invoke.py").write_text(script, encoding="utf-8")
            if payload is not None:
                (contract / "input.json").write_bytes(payload)
            self.profile.seal_mount(source)
            self.profile.seal_mount(contract)
            container_name = f"jarvis-ext-run-{uuid.uuid4().hex[:12]}"
            command = self.profile.build_command(
                source_dir=source, contract_dir=contract, container_name=container_name,
                command=["python", "-I", "/workspace/contract/invoke.py"],
            )
            result = await self.runner.run(command, container_name=container_name)
        if result.timed_out:
            raise ExtensionRuntimeError("extension_timeout")
        if result.exit_code == UNDECLARED_EXIT:
            # The sandbox refused it, not us: the code no longer declares this tool
            # or event. Worth its own reason — an owner reading "failed" would go
            # looking for a bug that is not there.
            raise ExtensionRuntimeError("tool_not_declared" if envelope else "event_not_declared")
        if result.exit_code == NO_OBSERVER_EXIT:
            raise ExtensionRuntimeError("observer_missing")
        if result.exit_code == UNDECLARED_COMMAND_EXIT:
            raise ExtensionRuntimeError("command_not_declared")
        if result.exit_code == NO_COMMAND_HANDLER_EXIT:
            raise ExtensionRuntimeError("command_handler_missing")
        if result.exit_code != 0:
            raise ExtensionRuntimeError("extension_failed")
        if not envelope:
            # An observation reads nothing back — not even a well-formed envelope.
            return None
        return self._envelope(result.stdout)

    @staticmethod
    def _envelope(stdout) -> dict:
        lines = [line for line in str(stdout or "").splitlines() if line.startswith(RESULT_PREFIX)]
        if len(lines) != 1:
            raise ExtensionRuntimeError("invalid_envelope")
        try:
            value = json.loads(lines[0][len(RESULT_PREFIX):])
        except ValueError:
            raise ExtensionRuntimeError("invalid_envelope") from None
        if not isinstance(value, dict) or value.get("ok") is not True:
            raise ExtensionRuntimeError("invalid_envelope")
        return value

    # ── api ──────────────────────────────────────────────────────────────────
    async def activate(
        self,
        manifest: ExtensionManifest,
        *,
        expected_package_hash: str | None = None,
        expected_grant_revision: str | None = None,
        expected_epoch: int | None = None,
    ) -> Activation:
        """Prove the declared surface from inside the sandbox, then make it callable."""
        if not isinstance(manifest, ExtensionManifest):
            raise ExtensionRuntimeError("invalid_manifest")
        if len(self._active) >= MAX_EXTENSIONS and manifest.id not in self._active:
            raise ExtensionRuntimeError("extension_capacity")
        self._require_enabled()
        grant_revision = self._require_consent(manifest)
        if expected_grant_revision is not None and grant_revision != expected_grant_revision:
            raise ExtensionRuntimeError("consent_changed")
        self._check_commands(manifest)
        record = self._require_package(manifest)
        current_epoch = self._activation_epochs.get(manifest.id, 0)
        if expected_package_hash is not None and record.package_hash != expected_package_hash:
            raise ExtensionRuntimeError("package_changed")
        if expected_epoch is not None and current_epoch != expected_epoch:
            raise ExtensionRuntimeError("activation_superseded")
        epoch = current_epoch + 1
        self._activation_epochs[manifest.id] = epoch
        envelope = await self._run(record, script=_register_source(), payload=None)
        try:
            validate_registration(manifest, envelope.get("registered"))
        except ManifestError:
            raise ExtensionRuntimeError("registration_mismatch") from None
        # Activation awaited untrusted registration: consent and namespace may have
        # changed meanwhile. Revalidate immediately before exposing any handler.
        self._require_enabled()
        self._require_consent(manifest, grant_revision)
        if self._activation_epochs.get(manifest.id) != epoch:
            raise ExtensionRuntimeError("activation_superseded")
        self._check_commands(manifest)
        current = self._require_package(manifest)
        if current.package_hash != record.package_hash:
            raise ExtensionRuntimeError("package_changed")
        # Registration has been proved, but no callable host surface exists yet.
        # A failed metadata write must refuse before `_active` or RPC exposure,
        # rather than reporting failure after an activation that callers retry.
        try:
            self.catalog.record(manifest)
        except Exception:
            raise ExtensionRuntimeError("manifest_catalog_unavailable") from None
        async with self._mutation_locks.setdefault(manifest.id, asyncio.Lock()):
            activation = Activation(manifest, record.package_hash, record.version, grant_revision)
            if self._activation_epochs.get(manifest.id) != epoch:
                raise ExtensionRuntimeError("activation_superseded")
            if len(self._active) >= MAX_EXTENSIONS and manifest.id not in self._active:
                raise ExtensionRuntimeError("extension_capacity")
            await self._retire_activation(manifest.id)
            self._require_enabled()
            self._require_consent(manifest, grant_revision)
            if self._activation_epochs.get(manifest.id) != epoch:
                raise ExtensionRuntimeError("activation_superseded")
            self._check_commands(manifest)
            if self._require_package(manifest).package_hash != record.package_hash:
                raise ExtensionRuntimeError("package_changed")
            self._active[manifest.id] = activation
            try:
                self._expose_commands(activation)
                self._expose(activation)
            except Exception:
                await self._retire_activation(manifest.id)
                raise ExtensionRuntimeError("registration_failed") from None
            self._save_activation_hint(activation)
            return activation

    async def dispatch_command(
        self, command: str, args: str, *, expected_activation: Activation | None = None
    ) -> str:
        """Execute only a currently active, signed command in the sealed sandbox."""
        if not isinstance(command, str) or not isinstance(args, str):
            raise ExtensionRuntimeError("invalid_call")
        self._require_enabled()
        activation = next((row for row in self._active.values()
                           if command in row.manifest.commands), None)
        if activation is None:
            raise ExtensionRuntimeError("command_not_activated")
        if expected_activation is not None and activation is not expected_activation:
            raise ExtensionRuntimeError("command_not_activated")
        self._check_commands(activation.manifest)
        self._require_consent(activation.manifest, activation.grant_revision)
        record = self._require_package(activation.manifest)
        if record.package_hash != activation.package_hash:
            raise ExtensionRuntimeError("package_changed")
        payload = json.dumps({"command": command, "args": args}, ensure_ascii=False).encode("utf-8")
        if len(payload) > self.max_input_bytes:
            raise ExtensionRuntimeError("input_too_large")
        envelope = await self._run(record, script=_command_source(), payload=payload)
        if not isinstance(envelope.get("result"), str):
            raise ExtensionRuntimeError("invalid_envelope")
        # A revoked/replaced activation cannot deliver a late result.
        if self._active.get(activation.manifest.id) is not activation:
            raise ExtensionRuntimeError("command_not_activated")
        self._require_enabled()
        self._require_consent(activation.manifest, activation.grant_revision)
        if self._require_package(activation.manifest).package_hash != activation.package_hash:
            raise ExtensionRuntimeError("package_changed")
        return envelope["result"]

    def observers(self, event: str) -> tuple[str, ...]:
        """Activated extensions that declared this event. Consent is checked at delivery."""
        return tuple(sorted(row.manifest.id for row in self._active.values()
                            if event in row.manifest.events))

    async def observe(self, extension_id: str, event: str, payload: dict) -> None:
        """Hand one event to one activated observer. Returns nothing, ever.

        Every gate `dispatch` applies applies here too — enabled, consent, signature,
        attestation, the pinned package hash — because an observer is third-party code
        running on the owner's box for the same reasons a tool is. What is different is
        the direction: nothing comes back. There is no return value to trust, so there
        is nothing an observer can say that changes what the hub does next.
        """
        if not isinstance(event, str) or not isinstance(payload, dict):
            raise ExtensionRuntimeError("invalid_event")
        self._require_enabled()
        activation = self._active.get(extension_id)
        if activation is None or event not in activation.manifest.events:
            raise ExtensionRuntimeError("event_not_observed")
        self._require_consent(activation.manifest, activation.grant_revision)
        record = self._require_package(activation.manifest)
        if record.package_hash != activation.package_hash:
            raise ExtensionRuntimeError("package_changed")
        try:
            body = json.dumps({"event": event, "payload": payload}, ensure_ascii=False,
                              separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (TypeError, ValueError):
            raise ExtensionRuntimeError("invalid_event") from None
        if len(body) > self.max_input_bytes:
            raise ExtensionRuntimeError("input_too_large")
        await self._run(record, script=_observe_source(), payload=body, envelope=False)

    async def dispatch(
        self, tool: str, args: dict, *, expected_activation: Activation | None = None
    ):
        """Call one activated, declared tool. Every gate is rechecked, not remembered."""
        if not isinstance(tool, str) or not isinstance(args, dict):
            raise ExtensionRuntimeError("invalid_call")
        self._require_enabled()
        activation = next((row for row in self._active.values()
                           if tool in row.manifest.qualified_tools), None)
        if activation is None:
            raise ExtensionRuntimeError("tool_not_activated")
        if expected_activation is not None and activation is not expected_activation:
            raise ExtensionRuntimeError("tool_not_activated")
        # Consent and signature are re-read here rather than trusted from activation:
        # a revoke, a re-sign or a swapped package between the two must bite.
        self._require_consent(activation.manifest, activation.grant_revision)
        record = self._require_package(activation.manifest)
        if record.package_hash != activation.package_hash:
            raise ExtensionRuntimeError("package_changed")
        try:
            payload = json.dumps({"tool": tool, "args": args}, ensure_ascii=False,
                                 separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (TypeError, ValueError):
            raise ExtensionRuntimeError("invalid_call") from None
        if len(payload) > self.max_input_bytes:
            raise ExtensionRuntimeError("input_too_large")
        envelope = await self._run(record, script=_dispatch_source(), payload=payload)
        if "result" not in envelope:
            raise ExtensionRuntimeError("invalid_envelope")
        if self._active.get(activation.manifest.id) is not activation:
            raise ExtensionRuntimeError("tool_not_activated")
        self._require_enabled()
        self._require_consent(activation.manifest, activation.grant_revision)
        if self._require_package(activation.manifest).package_hash != activation.package_hash:
            raise ExtensionRuntimeError("package_changed")
        return envelope["result"]


__all__ = ["Activation", "ExtensionRuntime", "ExtensionRuntimeError", "NO_OBSERVER_EXIT",
           "RESULT_PREFIX", "UNDECLARED_EXIT"]
