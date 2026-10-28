"""H361: signed provider hooks run through one awaited sealed worker batch."""

import asyncio
import json
import os
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from agents.core.acquisition.sandbox_profile import AcquisitionSandboxProfile, SandboxExecution
from agents.core.llm.providers import ProviderProfile
from agents.core.llm.providers.hook_runtime import ProviderHookRuntime, ProviderHookRuntimeError

IMAGE = "python@sha256:" + "a" * 64
HOOKS = (
    "prepare_messages",
    "build_extra_body",
    "build_api_kwargs_extras",
    "get_max_tokens",
    "supported_reasoning_efforts",
)


@dataclass(frozen=True)
class Record:
    provider_id: str
    package_hash: str
    manifest: dict
    signature: str
    profile: ProviderProfile
    hooks: tuple[str, ...]
    members: tuple[tuple[str, bytes], ...]


class Packages:
    def __init__(self, record):
        self.record = record
        self.revoked = False
        self.calls = 0

    def require_runnable(self, provider_id, *, expected_hash=None, home=None):
        self.calls += 1
        if (
            self.revoked
            or provider_id != self.record.provider_id
            or expected_hash != self.record.package_hash
        ):
            raise ValueError("not runnable")
        if home not in (None, "profile-home"):
            raise ValueError("wrong home")
        return self.record


class SimulatedSealedRunner:
    """Executes the real generated worker in a distinct Python interpreter.

    Mount translation is simulation only; these tests cannot prove Docker isolation.
    """

    def __init__(self):
        self.commands = []
        self.input = None
        self.sources = None
        self.directories = None
        self.result = None
        self.before_return = None

    async def run(self, command, *, container_name):
        self.commands.append(command)
        assert command[:2] == ["docker", "run"]
        assert "--network" in command and command[command.index("--network") + 1] == "none"
        assert "--read-only" in command and "--cap-drop" in command
        assert [command[i + 1] for i, item in enumerate(command) if item == "--env"] == [
            "PYTHONDONTWRITEBYTECODE=1",
            "PYTHONHASHSEED=0",
        ]
        assert command[-3:] == [IMAGE, "python", "-I", "/workspace/contract/invoke.py"][-3:]
        mounts = [command[i + 1] for i, item in enumerate(command) if item == "--mount"]
        paths = {
            item.rsplit("target=", 1)[1].split(",", 1)[0]: Path(
                item.split("source=", 1)[1].split(",", 1)[0]
            )
            for item in mounts
        }
        source, contract = paths["/workspace/source"], paths["/workspace/contract"]
        self.input = json.loads((contract / "input.json").read_text())
        self.sources = sorted(
            str(path.relative_to(source)) for path in source.rglob("*") if path.is_file()
        )
        self.directories = sorted(
            str(path.relative_to(source)) for path in source.rglob("*") if path.is_dir()
        )
        script = (contract / "invoke.py").read_text()
        script = script.replace("/workspace/source", str(source)).replace(
            "/workspace/contract", str(contract)
        )
        with tempfile.TemporaryDirectory() as temporary:
            local = Path(temporary) / "simulate.py"
            local.write_text(script)
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                str(local),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
        if self.before_return:
            self.before_return()
        if self.result is not None:
            return self.result
        return SandboxExecution(process.returncode, stdout.decode(), stderr.decode(), False, 0.01)


def fixture(tmp_path, *, source=None, hooks=HOOKS):
    profile = AcquisitionSandboxProfile(image=IMAGE, uid=os.getuid(), gid=os.getgid())
    host = ProviderProfile(
        "fixture",
        "Fixture",
        "openai-compatible",
        default_max_tokens=333,
        reasoning_declarations={"m": ("low", "high")},
    )
    source = (
        source
        or b"""from helper import marker
def register_provider():
    return {"id": "fixture", "hooks": ["prepare_messages", "build_extra_body", "build_api_kwargs_extras", "get_max_tokens", "supported_reasoning_efforts"]}
def prepare_messages(messages):
    messages[0]["content"] += marker()
    return messages
def build_extra_body(session_id=None, **context):
    context["reasoning_config"]["effort"] = "high"
    return {"session": session_id}
def build_api_kwargs_extras(reasoning_config=None, **context):
    return {"detail": reasoning_config["effort"]}, {"tracking": True}
def get_max_tokens(model):
    return 100
def supported_reasoning_efforts(model):
    return ["low", "high"]
"""
    )
    record = Record(
        "fixture",
        "f" * 64,
        {"runtime_image": IMAGE, "runtime_config_hash": profile.config_hash, "directories": []},
        "signed",
        host,
        hooks,
        (("main.py", source), ("helper.py", b'def marker():\n    return "!"\n')),
    )
    packages = Packages(record)
    runner = SimulatedSealedRunner()
    runtime = ProviderHookRuntime(packages, profile, tmp_path, runner=runner, enabled=lambda: True)
    return runtime, packages, runner


@pytest.mark.asyncio
async def test_actual_worker_imports_all_signed_members_and_keeps_hook_inputs_independent(tmp_path):
    runtime, packages, runner = fixture(tmp_path)
    answer = await runtime.evaluate(
        "fixture",
        package_hash="f" * 64,
        home="profile-home",
        model="m",
        messages=[{"role": "user", "content": "hello"}],
        reasoning_config={"enabled": True, "effort": "low"},
        session_id="s",
    )
    assert answer == {
        "prepared_messages": [{"role": "user", "content": "hello!"}],
        "extra_body": {"session": "s"},
        "api_kwargs": {"extra_body": {"detail": "low"}, "kwargs": {"tracking": True}},
        "max_tokens": 100,
        "reasoning_vocabulary": ["low", "high"],
    }
    assert packages.calls == 2
    assert runner.sources == ["helper.py", "main.py"]
    assert runner.input == {
        "model": "m",
        "messages": [{"role": "user", "content": "hello"}],
        "reasoning_config": {"enabled": True, "effort": "low"},
        "session_id": "s",
    }


@pytest.mark.asyncio
async def test_undeclared_registration_refuses_before_any_hook_runs(tmp_path):
    source = b"""def register_provider():
    return {"id": "fixture", "hooks": ["prepare_messages"]}
def prepare_messages(messages):
    return messages
"""
    runtime, _, _ = fixture(tmp_path, source=source)
    with pytest.raises(ProviderHookRuntimeError, match="registration_mismatch"):
        await runtime.evaluate("fixture", package_hash="f" * 64, model="m", messages=[])


@pytest.mark.asyncio
async def test_absent_optional_hooks_use_signed_host_profile_fallback(tmp_path):
    source = b"""def register_provider():
    return {"id": "fixture", "hooks": ["prepare_messages", "build_extra_body", "build_api_kwargs_extras"]}
def prepare_messages(messages):
    return messages
def build_extra_body(session_id=None, **context):
    return {}
def build_api_kwargs_extras(reasoning_config=None, **context):
    return {}, {}
"""
    runtime, packages, _ = fixture(tmp_path, source=source, hooks=HOOKS[:3])
    answer = await runtime.evaluate("fixture", package_hash="f" * 64, model="m", messages=[])
    assert answer["max_tokens"] == 333
    assert answer["reasoning_vocabulary"] == ["low", "high"]
    assert packages.calls == 2


@pytest.mark.asyncio
async def test_host_fallback_cap_obeys_worker_output_bound(tmp_path):
    source = b"""def register_provider():
    return {"id": "fixture", "hooks": ["prepare_messages", "build_extra_body", "build_api_kwargs_extras"]}
def prepare_messages(messages):
    return messages
def build_extra_body(session_id=None, **context):
    return {}
def build_api_kwargs_extras(reasoning_config=None, **context):
    return {}, {}
"""
    runtime, packages, _ = fixture(tmp_path, source=source, hooks=HOOKS[:3])
    packages.record = replace(
        packages.record,
        profile=ProviderProfile(
            "fixture", "Fixture", "openai-compatible", default_max_tokens=1_000_001
        ),
    )
    with pytest.raises(ProviderHookRuntimeError, match="invalid_output"):
        await runtime.evaluate("fixture", package_hash="f" * 64, model="m", messages=[])


@pytest.mark.asyncio
async def test_signed_nested_assets_are_projected_with_source(tmp_path):
    runtime, packages, runner = fixture(tmp_path)
    packages.record = replace(
        packages.record,
        members=packages.record.members + (("assets/.well-known", b"signed asset"),),
    )
    await runtime.evaluate(
        "fixture",
        package_hash="f" * 64,
        model="m",
        messages=[{"content": "x"}],
        reasoning_config={"enabled": True, "effort": "low"},
    )
    assert runner.sources == ["assets/.well-known", "helper.py", "main.py"]


@pytest.mark.asyncio
async def test_signed_empty_directory_is_projected(tmp_path):
    runtime, packages, runner = fixture(tmp_path)
    packages.record.manifest["directories"] = ["empty"]
    await runtime.evaluate(
        "fixture",
        package_hash="f" * 64,
        model="m",
        messages=[{"content": "x"}],
        reasoning_config={"enabled": True, "effort": "low"},
    )
    assert "empty" in runner.directories


@pytest.mark.asyncio
async def test_vision_url_and_harmless_user_json_survive_sealed_batch(tmp_path):
    source = b"""def register_provider():
    return {"id": "fixture", "hooks": ["prepare_messages", "build_extra_body", "build_api_kwargs_extras"]}
def prepare_messages(messages):
    return messages
def build_extra_body(session_id=None, **context):
    return {}
def build_api_kwargs_extras(reasoning_config=None, **context):
    return {}, {}
"""
    runtime, _, runner = fixture(tmp_path, source=source, hooks=HOOKS[:3])
    messages = [
        {
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}],
            "tool_data": {"key": "literal user data", "token": "word in a document"},
        }
    ]
    answer = await runtime.evaluate("fixture", package_hash="f" * 64, model="m", messages=messages)
    assert answer["prepared_messages"] == messages
    assert runner.input["messages"] == messages


@pytest.mark.asyncio
async def test_runtime_root_rejects_symlink_final_or_ancestor_and_public_parent(tmp_path):
    runtime, _, runner = fixture(tmp_path)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    link = tmp_path / "root-link"
    link.symlink_to(private, target_is_directory=True)
    for root in (link, link / "new-runtime"):
        runtime.runtime_root = root
        with pytest.raises(ProviderHookRuntimeError, match="unsafe_runtime_root"):
            await runtime.evaluate("fixture", package_hash="f" * 64, model="m", messages=[])
    public = tmp_path / "public"
    public.mkdir(mode=0o777)
    public.chmod(0o777)
    runtime.runtime_root = public / "new-runtime"
    with pytest.raises(ProviderHookRuntimeError, match="unsafe_runtime_root"):
        await runtime.evaluate("fixture", package_hash="f" * 64, model="m", messages=[])
    assert not (public / "new-runtime").exists()
    assert not runner.commands


@pytest.mark.asyncio
async def test_disabled_stale_attestation_and_revocation_refuse(tmp_path):
    runtime, packages, runner = fixture(tmp_path)
    runtime.enabled = lambda: False
    with pytest.raises(ProviderHookRuntimeError, match="disabled"):
        await runtime.evaluate("fixture", package_hash="f" * 64, model="m", messages=[])
    assert not runner.commands
    runtime.enabled = lambda: True
    packages.record.manifest["runtime_config_hash"] = "wrong"
    with pytest.raises(ProviderHookRuntimeError, match="attestation_mismatch"):
        await runtime.evaluate("fixture", package_hash="f" * 64, model="m", messages=[])
    packages.record.manifest["runtime_config_hash"] = runtime.profile.config_hash
    with pytest.raises(ProviderHookRuntimeError, match="not_runnable"):
        await runtime.evaluate(
            "fixture", package_hash="f" * 64, home="other-home", model="m", messages=[]
        )
    packages.revoked = True
    with pytest.raises(ProviderHookRuntimeError, match="not_runnable"):
        await runtime.evaluate("fixture", package_hash="f" * 64, model="m", messages=[])


@pytest.mark.asyncio
async def test_unknown_declared_hook_and_unsafe_member_path_refuse_before_dispatch(tmp_path):
    runtime, packages, runner = fixture(tmp_path)
    packages.record = replace(packages.record, hooks=HOOKS + ("get_api_key",))
    with pytest.raises(ProviderHookRuntimeError, match="unsupported_hooks"):
        await runtime.evaluate("fixture", package_hash="f" * 64, model="m", messages=[])
    packages.record = replace(
        packages.record, hooks=HOOKS, members=packages.record.members + (("../escape.py", b"bad"),)
    )
    with pytest.raises(ProviderHookRuntimeError, match="invalid_members"):
        await runtime.evaluate("fixture", package_hash="f" * 64, model="m", messages=[])
    assert not runner.commands


@pytest.mark.asyncio
async def test_revocation_during_worker_discards_result(tmp_path):
    runtime, packages, runner = fixture(tmp_path)
    runner.before_return = lambda: setattr(packages, "revoked", True)
    with pytest.raises(ProviderHookRuntimeError, match="not_runnable"):
        await runtime.evaluate(
            "fixture",
            package_hash="f" * 64,
            model="m",
            messages=[{"content": "x"}],
            reasoning_config={"enabled": True, "effort": "low"},
        )
    assert packages.calls == 2


@pytest.mark.asyncio
async def test_input_and_output_bounds_refuse_without_leaking_worker_text(tmp_path):
    runtime, _, runner = fixture(tmp_path)
    with pytest.raises(ProviderHookRuntimeError, match="invalid_input"):
        await runtime.evaluate(
            "fixture",
            package_hash="f" * 64,
            model="m",
            messages=[],
            reasoning_config={"api_key": "secret"},
        )
    assert not runner.commands
    runner.result = SandboxExecution(
        0, "x" * (runtime.profile.max_output_bytes + 1), "", False, 0.01
    )
    with pytest.raises(ProviderHookRuntimeError, match="invalid_output"):
        await runtime.evaluate(
            "fixture",
            package_hash="f" * 64,
            model="m",
            messages=[],
            reasoning_config={"enabled": True, "effort": "low"},
        )


@pytest.mark.asyncio
async def test_nonfinite_or_duplicate_worker_envelopes_refuse(tmp_path):
    runtime, _, runner = fixture(tmp_path)
    envelope = (
        'NERVA_PROVIDER_HOOK_RESULT:{"ok":true,"result":'
        '{"prepared_messages":[],"extra_body":{"x":NaN},'
        '"api_kwargs":{"extra_body":{},"kwargs":{}}}}\n'
    )
    runner.result = SandboxExecution(0, envelope, "", False, 0.01)
    with pytest.raises(ProviderHookRuntimeError, match="invalid_output"):
        await runtime.evaluate("fixture", package_hash="f" * 64, model="m", messages=[])
    duplicate_field = (
        'NERVA_PROVIDER_HOOK_RESULT:{"ok":false,"ok":true,"result":'
        '{"prepared_messages":[],"extra_body":{},'
        '"api_kwargs":{"extra_body":{},"kwargs":{}}}}\n'
    )
    runner.result = SandboxExecution(0, duplicate_field, "", False, 0.01)
    with pytest.raises(ProviderHookRuntimeError, match="invalid_output"):
        await runtime.evaluate("fixture", package_hash="f" * 64, model="m", messages=[])
    runner.result = SandboxExecution(0, duplicate_field + duplicate_field, "", False, 0.01)
    with pytest.raises(ProviderHookRuntimeError, match="invalid_output"):
        await runtime.evaluate("fixture", package_hash="f" * 64, model="m", messages=[])


@pytest.mark.asyncio
async def test_worker_request_extras_cannot_supply_auth_control(tmp_path):
    runtime, _, runner = fixture(tmp_path)
    envelope = (
        'NERVA_PROVIDER_HOOK_RESULT:{"ok":true,"result":'
        '{"prepared_messages":[],"extra_body":{"api-key":"leak"},'
        '"api_kwargs":{"extra_body":{},"kwargs":{}}}}\n'
    )
    runner.result = SandboxExecution(0, envelope, "", False, 0.01)
    with pytest.raises(ProviderHookRuntimeError, match="invalid_output"):
        await runtime.evaluate("fixture", package_hash="f" * 64, model="m", messages=[])


@pytest.mark.asyncio
async def test_deeply_nested_bounded_worker_json_refuses_with_reason_code(tmp_path):
    runtime, _, runner = fixture(tmp_path)
    nested = "[" * 10_000 + "null" + "]" * 10_000
    envelope = (
        'NERVA_PROVIDER_HOOK_RESULT:{"ok":true,"result":'
        '{"prepared_messages":' + nested + ',"extra_body":{},'
        '"api_kwargs":{"extra_body":{},"kwargs":{}}}}\n'
    )
    assert len(envelope.encode()) < runtime.profile.max_output_bytes
    runner.result = SandboxExecution(0, envelope, "", False, 0.01)
    with pytest.raises(ProviderHookRuntimeError, match="invalid_output"):
        await runtime.evaluate("fixture", package_hash="f" * 64, model="m", messages=[])


@pytest.mark.asyncio
async def test_reasoning_input_only_accepts_selected_control(tmp_path):
    runtime, _, runner = fixture(tmp_path)
    with pytest.raises(ProviderHookRuntimeError, match="invalid_input"):
        await runtime.evaluate(
            "fixture",
            package_hash="f" * 64,
            model="m",
            messages=[],
            reasoning_config={"enabled": True, "effort": "low", "budget": 900},
        )
    assert not runner.commands


@pytest.mark.asyncio
async def test_literal_user_json_key_reaches_worker_without_becoming_authority(tmp_path):
    runtime, _, runner = fixture(tmp_path)
    answer = await runtime.evaluate(
        "fixture",
        package_hash="f" * 64,
        model="m",
        messages=[{"role": "user", "content": "hello", "api-key": "literal"}],
        reasoning_config={"enabled": True, "effort": "low"},
    )
    assert runner.input["messages"][0]["api-key"] == "literal"
    assert answer["prepared_messages"][0]["api-key"] == "literal"


@pytest.mark.asyncio
async def test_timeout_and_cancellation_refuse_or_propagate(tmp_path):
    runtime, _, runner = fixture(tmp_path)
    runner.result = SandboxExecution(-1, "", "secret", True, 0.01)
    with pytest.raises(ProviderHookRuntimeError, match="timeout"):
        await runtime.evaluate(
            "fixture",
            package_hash="f" * 64,
            model="m",
            messages=[],
            reasoning_config={"enabled": True, "effort": "low"},
        )

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError

    runner.run = cancelled
    with pytest.raises(asyncio.CancelledError):
        await runtime.evaluate(
            "fixture",
            package_hash="f" * 64,
            model="m",
            messages=[],
            reasoning_config={"enabled": True, "effort": "low"},
        )
