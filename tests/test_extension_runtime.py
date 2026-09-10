"""S2: a declared extension surface becomes callable only after isolation proves it.

The rule under test is one sentence. **The host never imports third-party code, and
never trusts a declaration it has not seen the code make from inside the sandbox.**

So the interesting tests here are not the happy path. They are the four gates —
enabled, consent, signature/attestation, isolated registration — each shown refusing
on its own, and shown refusing *before* any container is built. A gate that only
fires after the code has run is not a gate.

The sandbox is simulated, and that simulation is deliberate in one specific way: the
fake runner **executes the real invocation scripts** this module generates, with the
real interpreter, against a real file on disk. What is faked is the isolation, not
the protocol — so `register()` really is called, extension stdout really is swallowed,
and the in-sandbox tool check really does refuse an undeclared name.

**Not covered, and not claimed anywhere:** that any of this holds against a real
pinned Docker image. That is owner-host proof. Every container flag the profile sets
(`--network none`, `--cap-drop ALL`, `--read-only`) is the acquisition profile's own,
tested with the acquisition profile; nothing here relaxes or re-proves it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core.acquisition.package_store import PackageStoreError
from agents.core.extensions.consent import ExtensionConsentStore
from agents.core.extensions.manifest import parse_manifest
from agents.core.extensions.runtime import (
    UNDECLARED_EXIT,
    ExtensionRuntime,
    ExtensionRuntimeError,
)

IMAGE = "example.invalid/sandbox@sha256:" + "a" * 64
CONFIG_HASH = "b" * 64

EXTENSION = '''
def register():
    print("an extension trying to forge a result line")
    return {"tools": ["boats.summarize"], "commands": [], "events": []}


def call(tool, payload):
    return {"tool": tool, "seen": payload}
'''


def descriptor(**overrides):
    value = {
        "manifest_version": 1, "api_version": 1, "id": "boats", "version": "1.0.0",
        "capabilities": ["tools"], "tools": ["summarize"], "commands": [], "events": [],
        "requires": {"extensions": {}, "python": {}},
    }
    value.update(overrides)
    value["capabilities"] = [name for name, declared in (
        ("tools", value["tools"]), ("commands", value["commands"]),
        ("events.observe", value["events"])) if declared]
    return parse_manifest(value)


# ── a package store and a sandbox, faked only where the host cannot reach ────

@dataclass
class _Execution:
    exit_code: int
    stdout: str
    stderr: str = ""
    timed_out: bool = False


class _Packages:
    """Just enough AcquiredPackageStore: a signed record, or a refusal."""

    def __init__(self, root: Path, source: str = EXTENSION):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.available = True
        self.write(source)

    def write(self, source: str, *, name="boats", version="1.0.0"):
        body = source.encode("utf-8")
        (self.root / "main.py").write_bytes(body)
        self.record = SimpleNamespace(
            name=name, version=version, package_hash="c" * 64, path=self.root,
            manifest={
                "files": [{"path": "main.py", "size": len(body),
                           "sha256": hashlib.sha256(body).hexdigest()}],
                "runtime_image": IMAGE, "runtime_config_hash": CONFIG_HASH,
            },
        )
        return self.record

    def require_runnable(self, name):
        if not self.available or name != self.record.name:
            raise PackageStoreError("not runnable")
        return self.record


class _Profile:
    """Captures what would be mounted; the flags themselves are acquisition's own."""

    image = IMAGE
    config_hash = CONFIG_HASH
    timeout_seconds = 30.0
    max_output_bytes = 32 * 1024

    def seal_mount(self, path):
        pass

    def build_command(self, *, source_dir, contract_dir, container_name, command):
        return ["docker", "run", str(source_dir), str(contract_dir), container_name, *command]


class _Runner:
    """Runs the module's real invocation script, locally, on the real files."""

    def __init__(self, *, fail=None):
        self.calls: list[list[str]] = []
        self.fail = fail

    async def run(self, command, *, container_name):
        self.calls.append(command)
        if self.fail is not None:
            return self.fail
        source_dir, contract_dir = Path(command[2]), Path(command[3])
        script = (contract_dir / "invoke.py").read_text(encoding="utf-8")
        script = script.replace("/workspace/source", str(source_dir)).replace(
            "/workspace/contract", str(contract_dir))
        local = contract_dir / "local_invoke.py"
        local.write_text(script, encoding="utf-8")
        done = subprocess.run([sys.executable, "-I", str(local)], capture_output=True,  # noqa: S603
                              text=True, timeout=60)
        return _Execution(done.returncode, done.stdout, done.stderr)


@pytest.fixture()
def rig(tmp_path):
    packages = _Packages(tmp_path / "package")
    runner = _Runner()
    consent = ExtensionConsentStore(tmp_path / "consent.json")
    runtime = ExtensionRuntime(
        packages=packages, profile=_Profile(), runtime_root=tmp_path / "runs",
        runner=runner, consent=consent, enabled=lambda: True,
    )
    return SimpleNamespace(runtime=runtime, packages=packages, runner=runner,
                           consent=consent, root=tmp_path)


@pytest.fixture()
def consented(rig):
    rig.consent.grant(descriptor())
    return rig


# ── the happy path, so the refusals below mean something ─────────────────────

@pytest.mark.asyncio
async def test_a_consented_signed_extension_registers_and_then_dispatches(consented):
    activation = await consented.runtime.activate(descriptor())
    assert activation.as_dict()["callable_tools"] == ["boats.summarize"]
    assert consented.runtime.callable_tools() == ("boats.summarize",)

    result = await consented.runtime.dispatch("boats.summarize", {"text": "a blue boat"})
    assert result == {"tool": "boats.summarize", "seen": {"text": "a blue boat"}}


@pytest.mark.asyncio
async def test_what_the_extension_prints_cannot_become_the_result(consented):
    """`register` above prints a line on purpose. Only the envelope is read."""
    await consented.runtime.activate(descriptor())
    assert await consented.runtime.dispatch("boats.summarize", {}) == {"tool": "boats.summarize", "seen": {}}


# ── gate 1: the runtime is enabled ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_disabled_runtime_activates_nothing_and_builds_no_container(rig):
    rig.consent.grant(descriptor())
    rig.runtime.enabled = lambda: False
    with pytest.raises(ExtensionRuntimeError, match="extensions_disabled"):
        await rig.runtime.activate(descriptor())
    assert rig.runner.calls == []


@pytest.mark.asyncio
async def test_an_enablement_check_that_raises_is_a_refusal(rig):
    rig.consent.grant(descriptor())

    def broken():
        raise RuntimeError("host state unavailable")

    rig.runtime.enabled = broken
    with pytest.raises(ExtensionRuntimeError, match="extensions_disabled"):
        await rig.runtime.activate(descriptor())


@pytest.mark.asyncio
async def test_disabling_the_runtime_stops_an_already_activated_tool(consented):
    await consented.runtime.activate(descriptor())
    consented.runtime.enabled = lambda: False
    with pytest.raises(ExtensionRuntimeError, match="extensions_disabled"):
        await consented.runtime.dispatch("boats.summarize", {})


# ── gate 2: consent ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_without_consent_nothing_activates_and_no_container_is_built(rig):
    with pytest.raises(ExtensionRuntimeError, match="consent_required"):
        await rig.runtime.activate(descriptor())
    assert rig.runner.calls == []


@pytest.mark.asyncio
async def test_an_update_that_declares_more_is_refused_as_changed_not_granted(rig):
    """The H570 case: consented at 1.0.0, now also wants a command."""
    rig.consent.grant(descriptor())
    widened = descriptor(version="1.1.0", commands=["boats_summary"])
    with pytest.raises(ExtensionRuntimeError, match="consent_changed"):
        await rig.runtime.activate(widened)
    assert rig.runner.calls == []


@pytest.mark.asyncio
async def test_withdrawing_consent_stops_dispatch_without_needing_a_deactivate(consented):
    """Activation is not a standing permission. Consent is re-read every call."""
    await consented.runtime.activate(descriptor())
    consented.consent.revoke("boats")
    with pytest.raises(ExtensionRuntimeError, match="consent_required"):
        await consented.runtime.dispatch("boats.summarize", {})


@pytest.mark.asyncio
async def test_a_consent_store_that_raises_is_a_refusal(consented):
    class _Broken:
        def check(self, _manifest):
            raise OSError("consent store unavailable")

    consented.runtime.consent = _Broken()
    with pytest.raises(ExtensionRuntimeError, match="consent_unavailable"):
        await consented.runtime.activate(descriptor())


# ── gate 3: signature, attestation and identity ──────────────────────────────

@pytest.mark.asyncio
async def test_an_unsigned_or_missing_package_is_refused(consented):
    consented.packages.available = False
    with pytest.raises(ExtensionRuntimeError, match="package_unavailable"):
        await consented.runtime.activate(descriptor())
    assert consented.runner.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["runtime_image", "runtime_config_hash"])
async def test_a_package_attested_to_another_sandbox_is_refused(consented, field):
    consented.packages.record.manifest[field] = "d" * 64
    with pytest.raises(ExtensionRuntimeError, match="attestation_mismatch"):
        await consented.runtime.activate(descriptor())


@pytest.mark.asyncio
async def test_a_descriptor_and_a_package_must_be_the_same_version(consented):
    consented.packages.record.version = "2.0.0"
    with pytest.raises(ExtensionRuntimeError, match="version_mismatch"):
        await consented.runtime.activate(descriptor())


@pytest.mark.asyncio
async def test_source_bytes_that_moved_since_signing_are_not_source(consented):
    """The signed manifest names a size and a hash. Anything else is not the package."""
    (consented.packages.root / "main.py").write_text("def register():\n    return {}\n")
    with pytest.raises(ExtensionRuntimeError, match="source_changed"):
        await consented.runtime.activate(descriptor())


@pytest.mark.asyncio
async def test_a_package_swapped_under_an_active_extension_is_refused_at_dispatch(consented):
    """Activation pinned a package hash; dispatch checks it again rather than trusting it."""
    await consented.runtime.activate(descriptor())
    consented.packages.record.package_hash = "e" * 64
    with pytest.raises(ExtensionRuntimeError, match="package_changed"):
        await consented.runtime.dispatch("boats.summarize", {})


# ── gate 4: the isolated registration ────────────────────────────────────────

@pytest.mark.asyncio
async def test_declaring_one_surface_and_registering_another_activates_nothing(consented):
    """The attack this whole round trip exists to close."""
    consented.packages.write(
        'def register():\n'
        '    return {"tools": ["boats.summarize", "boats.exfiltrate"], "commands": [], "events": []}\n'
        'def call(tool, payload):\n    return {}\n'
    )
    with pytest.raises(ExtensionRuntimeError, match="registration_mismatch"):
        await consented.runtime.activate(descriptor())
    assert consented.runtime.callable_tools() == ()


@pytest.mark.asyncio
async def test_registering_less_than_declared_is_also_a_mismatch(consented):
    consented.packages.write(
        'def register():\n    return {"tools": [], "commands": [], "events": []}\n'
        'def call(tool, payload):\n    return {}\n'
    )
    with pytest.raises(ExtensionRuntimeError, match="registration_mismatch"):
        await consented.runtime.activate(descriptor())


@pytest.mark.asyncio
async def test_an_extension_that_raises_on_register_activates_nothing(consented):
    consented.packages.write('def register():\n    raise RuntimeError("boom")\n')
    with pytest.raises(ExtensionRuntimeError, match="extension_failed"):
        await consented.runtime.activate(descriptor())
    assert consented.runtime.callable_tools() == ()


@pytest.mark.asyncio
async def test_a_tool_the_extension_no_longer_declares_is_refused_inside_the_sandbox(consented):
    """The host checks first. The sandbox checks again, so a stale host view is not enough."""
    await consented.runtime.activate(descriptor())
    consented.packages.write(
        'def register():\n    return {"tools": [], "commands": [], "events": []}\n'
        'def call(tool, payload):\n    return {"should": "never be reached"}\n'
    )
    with pytest.raises(ExtensionRuntimeError, match="tool_not_declared"):
        await consented.runtime.dispatch("boats.summarize", {})


# ── dispatch bounds and revocation ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_unactivated_tool_is_never_dispatched(consented):
    with pytest.raises(ExtensionRuntimeError, match="tool_not_activated"):
        await consented.runtime.dispatch("boats.summarize", {})
    await consented.runtime.activate(descriptor())
    with pytest.raises(ExtensionRuntimeError, match="tool_not_activated"):
        await consented.runtime.dispatch("boats.exfiltrate", {})
    with pytest.raises(ExtensionRuntimeError, match="tool_not_activated"):
        await consented.runtime.dispatch("summarize", {})


@pytest.mark.asyncio
async def test_deactivation_is_immediate_and_host_side(consented):
    await consented.runtime.activate(descriptor())
    assert await consented.runtime.deactivate("boats") is True
    assert consented.runtime.callable_tools() == ()
    with pytest.raises(ExtensionRuntimeError, match="tool_not_activated"):
        await consented.runtime.dispatch("boats.summarize", {})
    assert await consented.runtime.deactivate("boats") is False


@pytest.mark.asyncio
async def test_an_oversized_payload_never_reaches_the_sandbox(consented):
    await consented.runtime.activate(descriptor())
    before = len(consented.runner.calls)
    with pytest.raises(ExtensionRuntimeError, match="input_too_large"):
        await consented.runtime.dispatch("boats.summarize", {"blob": "x" * 200_000})
    assert len(consented.runner.calls) == before


@pytest.mark.asyncio
async def test_an_unserializable_payload_is_refused_rather_than_coerced(consented):
    await consented.runtime.activate(descriptor())
    with pytest.raises(ExtensionRuntimeError, match="invalid_call"):
        await consented.runtime.dispatch("boats.summarize", {"when": object()})
    with pytest.raises(ExtensionRuntimeError, match="invalid_call"):
        await consented.runtime.dispatch("boats.summarize", ["not", "an", "object"])


@pytest.mark.asyncio
async def test_a_timeout_and_a_crash_are_distinct_bounded_reasons(rig):
    rig.consent.grant(descriptor())
    rig.runtime.runner = _Runner(fail=_Execution(-1, "", "took too long", timed_out=True))
    with pytest.raises(ExtensionRuntimeError, match="extension_timeout"):
        await rig.runtime.activate(descriptor())
    rig.runtime.runner = _Runner(fail=_Execution(9, "", "segfault"))
    with pytest.raises(ExtensionRuntimeError, match="extension_failed"):
        await rig.runtime.activate(descriptor())


@pytest.mark.asyncio
@pytest.mark.parametrize("stdout", [
    "", "no envelope here",
    "NERVA_EXTENSION_RESULT:not json",
    'NERVA_EXTENSION_RESULT:{"ok": false}',
    'NERVA_EXTENSION_RESULT:["ok"]',
    'NERVA_EXTENSION_RESULT:{"ok": true}\nNERVA_EXTENSION_RESULT:{"ok": true}',
], ids=["empty", "no-prefix", "not-json", "not-ok", "not-object", "two-envelopes"])
async def test_a_malformed_envelope_is_never_a_result(rig, stdout):
    rig.consent.grant(descriptor())
    rig.runtime.runner = _Runner(fail=_Execution(0, stdout))
    with pytest.raises(ExtensionRuntimeError, match="invalid_envelope"):
        await rig.runtime.activate(descriptor())


# ── the RPC surface ──────────────────────────────────────────────────────────

class _ToolRPC:
    def __init__(self):
        self.tools: dict[str, dict] = {}
        self.cancelled: list[str] = []

    def register_tool(self, name, handler, **kwargs):
        self.tools[name] = {"handler": handler, **kwargs}

    async def unregister_tool(self, name, *, cancel_inflight=False):
        self.tools.pop(name, None)
        self.cancelled.append(name)


@pytest.mark.asyncio
async def test_activation_exposes_the_proven_tools_as_untrusted_output(consented):
    rpc = _ToolRPC()
    consented.runtime.rpc = rpc
    await consented.runtime.activate(descriptor())
    assert list(rpc.tools) == ["boats.summarize"]
    spec = rpc.tools["boats.summarize"]
    assert spec["untrusted_output"] is True, "third-party output is data, not instructions"
    assert spec["gated"] is False
    assert spec["capability_id"] == "tool:extension.boats.summarize"
    assert await spec["handler"]({"text": "hi"}) == {"tool": "boats.summarize", "seen": {"text": "hi"}}


@pytest.mark.asyncio
async def test_deactivation_takes_the_tools_off_the_surface_with_inflight_cancelled(consented):
    rpc = _ToolRPC()
    consented.runtime.rpc = rpc
    await consented.runtime.activate(descriptor())
    await consented.runtime.deactivate("boats")
    assert rpc.tools == {} and rpc.cancelled == ["boats.summarize"]


@pytest.mark.asyncio
async def test_an_extension_stays_revoked_even_if_unregistering_fails(consented):
    class _Stuck(_ToolRPC):
        async def unregister_tool(self, name, *, cancel_inflight=False):
            raise RuntimeError("rpc unavailable")

    consented.runtime.rpc = _Stuck()
    await consented.runtime.activate(descriptor())
    assert await consented.runtime.deactivate("boats") is True
    assert consented.runtime.callable_tools() == ()


def test_the_dispatch_script_refuses_an_undeclared_tool_on_its_own(tmp_path):
    """Read directly, because the host's own check would otherwise mask this one."""
    from agents.core.extensions.runtime import _dispatch_source

    source = tmp_path / "main.py"
    source.write_text(
        'def register():\n    return {"tools": ["boats.summarize"], "commands": [], "events": []}\n'
        'def call(tool, payload):\n    return {"reached": True}\n', encoding="utf-8")
    (tmp_path / "input.json").write_text(json.dumps({"tool": "boats.exfiltrate", "args": {}}), encoding="utf-8")
    script = tmp_path / "invoke.py"
    script.write_text(_dispatch_source().replace("/workspace/source", str(tmp_path))
                      .replace("/workspace/contract", str(tmp_path)), encoding="utf-8")
    done = subprocess.run([sys.executable, "-I", str(script)], capture_output=True, text=True, timeout=60)  # noqa: S603
    assert done.returncode == UNDECLARED_EXIT and "reached" not in done.stdout


def test_capacity_is_bounded(rig):
    from agents.core.extensions.manifest import MAX_EXTENSIONS

    rig.runtime._active = {f"ext{index}": object() for index in range(MAX_EXTENSIONS)}
    with pytest.raises(ExtensionRuntimeError, match="extension_capacity"):
        asyncio.run(rig.runtime.activate(descriptor()))


# ── S3: observation, and the gates it does not get to skip ───────────────────

OBSERVING = '''
def register():
    return {"tools": ["boats.summarize"], "commands": [], "events": ["tool.completed"]}


def call(tool, payload):
    return {"tool": tool, "seen": payload}


def on_event(event, payload):
    open(MARKER, "a", encoding="utf-8").write(event + "\\n")
'''


def observing(rig, marker):
    return rig.packages.write(OBSERVING.replace("MARKER", repr(str(marker))))


def watching_descriptor():
    return descriptor(events=["tool.completed"])


@pytest.mark.asyncio
async def test_an_activated_extension_observes_the_events_it_declared(consented, tmp_path):
    marker = tmp_path / "seen.txt"
    observing(consented, marker)
    consented.consent.grant(watching_descriptor())
    await consented.runtime.activate(watching_descriptor())
    assert consented.runtime.observers("tool.completed") == ("boats",)
    assert consented.runtime.observers("session.started") == ()

    assert await consented.runtime.observe("boats", "tool.completed", {"tool": "file_read"}) is None
    assert marker.read_text(encoding="utf-8").split() == ["tool.completed"]


@pytest.mark.asyncio
async def test_an_undeclared_event_is_never_delivered(consented, tmp_path):
    observing(consented, tmp_path / "seen.txt")
    consented.consent.grant(watching_descriptor())
    await consented.runtime.activate(watching_descriptor())
    with pytest.raises(ExtensionRuntimeError, match="event_not_observed"):
        await consented.runtime.observe("boats", "session.started", {})
    with pytest.raises(ExtensionRuntimeError, match="event_not_observed"):
        await consented.runtime.observe("ships", "tool.completed", {})


@pytest.mark.asyncio
async def test_observation_crosses_the_same_gates_as_dispatch(consented, tmp_path):
    """An observer is third-party code on the owner's box for the same reasons a
    tool is, so consent, the signature and the pinned package hash all apply."""
    observing(consented, tmp_path / "seen.txt")
    consented.consent.grant(watching_descriptor())
    await consented.runtime.activate(watching_descriptor())

    consented.consent.revoke("boats")
    with pytest.raises(ExtensionRuntimeError, match="consent_required"):
        await consented.runtime.observe("boats", "tool.completed", {})
    consented.consent.grant(watching_descriptor())

    consented.packages.record.package_hash = "f" * 64
    with pytest.raises(ExtensionRuntimeError, match="package_changed"):
        await consented.runtime.observe("boats", "tool.completed", {})
    consented.packages.record.package_hash = "c" * 64

    consented.runtime.enabled = lambda: False
    with pytest.raises(ExtensionRuntimeError, match="extensions_disabled"):
        await consented.runtime.observe("boats", "tool.completed", {})


@pytest.mark.asyncio
async def test_an_extension_declaring_an_event_it_cannot_observe_says_so(consented, tmp_path):
    consented.packages.write(
        'def register():\n'
        '    return {"tools": ["boats.summarize"], "commands": [], "events": ["tool.completed"]}\n'
        'def call(tool, payload):\n    return {}\n'
    )
    consented.consent.grant(watching_descriptor())
    await consented.runtime.activate(watching_descriptor())
    with pytest.raises(ExtensionRuntimeError, match="observer_missing"):
        await consented.runtime.observe("boats", "tool.completed", {})


@pytest.mark.asyncio
async def test_an_oversized_or_unserializable_event_never_reaches_the_sandbox(consented, tmp_path):
    observing(consented, tmp_path / "seen.txt")
    consented.consent.grant(watching_descriptor())
    await consented.runtime.activate(watching_descriptor())
    before = len(consented.runner.calls)
    with pytest.raises(ExtensionRuntimeError, match="input_too_large"):
        await consented.runtime.observe("boats", "tool.completed", {"blob": "x" * 200_000})
    with pytest.raises(ExtensionRuntimeError, match="invalid_event"):
        await consented.runtime.observe("boats", "tool.completed", {"when": object()})
    with pytest.raises(ExtensionRuntimeError, match="invalid_event"):
        await consented.runtime.observe("boats", "tool.completed", ["not", "an", "object"])
    assert len(consented.runner.calls) == before


@pytest.mark.asyncio
async def test_deactivation_stops_observation_too(consented, tmp_path):
    observing(consented, tmp_path / "seen.txt")
    consented.consent.grant(watching_descriptor())
    await consented.runtime.activate(watching_descriptor())
    await consented.runtime.deactivate("boats")
    assert consented.runtime.observers("tool.completed") == ()
    with pytest.raises(ExtensionRuntimeError, match="event_not_observed"):
        await consented.runtime.observe("boats", "tool.completed", {})
