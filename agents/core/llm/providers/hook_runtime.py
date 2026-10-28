"""Awaited request hooks for permanently admitted, sealed provider packages.

The store owns approval, signatures, and source verification. This runtime owns
one Docker-only execution of the copied signed members per request. The returned
JSON is untrusted until the native adapter applies its existing request guards.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import stat
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath

from agents.core.acquisition.sandbox_profile import AcquisitionSandboxProfile, DockerSandboxRunner

from .admission_contract import provider_sandbox_profile

_RESULT_PREFIX = "NERVA_PROVIDER_HOOK_RESULT:"
_REQUIRED_HOOKS = frozenset({"prepare_messages", "build_extra_body", "build_api_kwargs_extras"})
_OPTIONAL_HOOKS = frozenset({"get_max_tokens", "supported_reasoning_efforts"})
_KNOWN_HOOKS = _REQUIRED_HOOKS | _OPTIONAL_HOOKS
_MAX_INPUT_BYTES = 512 * 1024
_MAX_DEPTH = 16
_FORBIDDEN_KEYS = frozenset(
    {
        "apikey",
        "key",
        "accesskey",
        "accesstoken",
        "refreshtoken",
        "secretkey",
        "auth",
        "authorization",
        "bearer",
        "baseurl",
        "url",
        "endpoint",
        "client",
        "transport",
        "environment",
        "environ",
        "env",
        "headers",
        "cookie",
        "credential",
        "credentials",
        "secret",
        "token",
    }
)


class ProviderHookRuntimeError(RuntimeError):
    """Only bounded refusal codes are exposed; worker output is never quoted."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _validate_tree(value: object, *, depth: int = 0) -> None:
    if depth > _MAX_DEPTH:
        raise ProviderHookRuntimeError("invalid_input")
    if value is None or type(value) in (bool, int):
        return
    if type(value) is float:
        if math.isfinite(value):
            return
        raise ProviderHookRuntimeError("invalid_input")
    if type(value) is str:
        if len(value) <= _MAX_INPUT_BYTES:
            return
        raise ProviderHookRuntimeError("invalid_input")
    if type(value) is list:
        if len(value) > 4096:
            raise ProviderHookRuntimeError("invalid_input")
        for item in value:
            _validate_tree(item, depth=depth + 1)
        return
    if type(value) is dict:
        if len(value) > 128:
            raise ProviderHookRuntimeError("invalid_input")
        for key, item in value.items():
            if type(key) is not str or len(key) > 128:
                raise ProviderHookRuntimeError("invalid_input")
            _validate_tree(item, depth=depth + 1)
        return
    raise ProviderHookRuntimeError("invalid_input")


def _safe_json(value: object, *, max_bytes: int, reason: str) -> bytes:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ProviderHookRuntimeError(reason) from exc
    if len(encoded) > max_bytes:
        raise ProviderHookRuntimeError(reason)
    return encoded


def _private_runtime_root(path: Path) -> Path:
    """Open each path component without following links before making projections.

    The final directory is private and owned by this process. An existing
    ancestor may be writable by others only when sticky and root/user owned.
    Another process with this same filesystem owner's rights remains outside
    this boundary; it can replace any host path that owner controls.
    """
    if not path.is_absolute() or ".." in path.parts or len(path.parts) < 2:
        raise ProviderHookRuntimeError("unsafe_runtime_root")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        directory_fd = os.open(path.anchor, flags)
        try:
            for index, part in enumerate(path.parts[1:]):
                final = index == len(path.parts) - 2
                try:
                    child_fd = os.open(part, flags, dir_fd=directory_fd)
                except FileNotFoundError:
                    if not final:
                        raise ProviderHookRuntimeError("unsafe_runtime_root") from None
                    os.mkdir(part, mode=0o700, dir_fd=directory_fd)
                    child_fd = os.open(part, flags, dir_fd=directory_fd)
                info = os.fstat(child_fd)
                mode = stat.S_IMODE(info.st_mode)
                if (
                    not stat.S_ISDIR(info.st_mode)
                    or (final and (info.st_uid != os.getuid() or mode != 0o700))
                    or (
                        not final
                        and mode & 0o022
                        and not (mode & stat.S_ISVTX and info.st_uid in (0, os.getuid()))
                    )
                ):
                    os.close(child_fd)
                    raise ProviderHookRuntimeError("unsafe_runtime_root")
                os.close(directory_fd)
                directory_fd = child_fd
        finally:
            os.close(directory_fd)
    except ProviderHookRuntimeError:
        raise
    except OSError:
        raise ProviderHookRuntimeError("unsafe_runtime_root") from None
    return path


def _validate_extra_authority(answer: dict) -> None:
    """Reject control keys at the structured request-extra surfaces only."""
    extras = (
        answer["extra_body"],
        answer["api_kwargs"]["extra_body"],
        answer["api_kwargs"]["kwargs"],
    )
    for mapping in extras:
        for key in mapping:
            if re.sub(r"[_-]", "", key.lower()) in _FORBIDDEN_KEYS:
                raise ProviderHookRuntimeError("invalid_output")


_WORKER = r"""import contextlib
import importlib.util
import json
import sys

SOURCE = "/workspace/source"
CONTRACT = "/workspace/contract"
EXPECTED_ID = __EXPECTED_ID__
EXPECTED_HOOKS = __EXPECTED_HOOKS__
PREFIX = __PREFIX__

class _Discard:
    def write(self, value):
        return len(value)
    def flush(self):
        pass

def _copy(value):
    return json.loads(json.dumps(value, allow_nan=False))

def _run():
    sys.path[:] = [SOURCE, *[path for path in sys.path if path and
                   "site-packages" not in path and "dist-packages" not in path]]
    payload = json.loads(open(CONTRACT + "/input.json", encoding="utf-8").read())
    with contextlib.redirect_stdout(_Discard()), contextlib.redirect_stderr(_Discard()):
        spec = importlib.util.spec_from_file_location("admitted_provider", SOURCE + "/main.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        registration = module.register_provider()
        if (type(registration) is not dict or set(registration) != {"id", "hooks"}
                or registration["id"] != EXPECTED_ID
                or type(registration["hooks"]) is not list
                or len(registration["hooks"]) != len(EXPECTED_HOOKS)
                or set(registration["hooks"]) != set(EXPECTED_HOOKS)):
            raise SystemExit(71)
        hooks = {}
        for name in EXPECTED_HOOKS:
            function = getattr(module, name, None)
            if not callable(function):
                raise SystemExit(71)
            hooks[name] = function
        messages = hooks["prepare_messages"](_copy(payload["messages"]))
        body = hooks["build_extra_body"](
            session_id=payload["session_id"], model=payload["model"],
            reasoning_config=_copy(payload["reasoning_config"]))
        extra, kwargs = hooks["build_api_kwargs_extras"](
            reasoning_config=_copy(payload["reasoning_config"]),
            model=payload["model"], session_id=payload["session_id"])
        result = {"prepared_messages": messages, "extra_body": body,
                  "api_kwargs": {"extra_body": extra, "kwargs": kwargs}}
        if "get_max_tokens" in hooks:
            result["max_tokens"] = hooks["get_max_tokens"](payload["model"])
        if "supported_reasoning_efforts" in hooks:
            result["reasoning_vocabulary"] = hooks["supported_reasoning_efforts"](
                payload["model"])
    return result

try:
    answer = _run()
    print(PREFIX + json.dumps({"ok": True, "result": answer},
                              ensure_ascii=False, allow_nan=False, separators=(",", ":")))
except SystemExit:
    raise
except BaseException:
    raise SystemExit(72) from None
"""


def _worker_source(provider_id: str, hooks: tuple[str, ...]) -> str:
    return (
        _WORKER.replace("__EXPECTED_ID__", repr(provider_id))
        .replace("__EXPECTED_HOOKS__", repr(hooks))
        .replace("__PREFIX__", repr(_RESULT_PREFIX))
    )


class ProviderHookRuntime:
    def __init__(
        self,
        packages,
        profile: AcquisitionSandboxProfile,
        runtime_root,
        runner=None,
        enabled=lambda: False,
    ) -> None:
        self.packages = packages
        self.profile = provider_sandbox_profile(profile)
        self.runtime_root = Path(runtime_root)
        self.runner = runner or DockerSandboxRunner(
            timeout_seconds=self.profile.timeout_seconds,
            max_output_bytes=self.profile.max_output_bytes,
        )
        self.enabled = enabled

    def _require_record(self, provider_id: str, package_hash: str, home):
        try:
            record = self.packages.require_runnable(
                provider_id, expected_hash=package_hash, home=home
            )
        except Exception as exc:
            raise ProviderHookRuntimeError("not_runnable") from exc
        return self._check_record(record, provider_id, package_hash)

    def _check_record(self, record, provider_id: str, package_hash: str):
        if record.provider_id != provider_id or record.package_hash != package_hash:
            raise ProviderHookRuntimeError("not_runnable")
        if (
            record.manifest.get("runtime_image") != self.profile.image
            or record.manifest.get("runtime_config_hash") != self.profile.config_hash
        ):
            raise ProviderHookRuntimeError("attestation_mismatch")
        hooks = record.hooks
        if (
            type(hooks) is not tuple
            or len(hooks) != len(set(hooks))
            or not _REQUIRED_HOOKS.issubset(hooks)
            or not set(hooks).issubset(_KNOWN_HOOKS)
        ):
            raise ProviderHookRuntimeError("unsupported_hooks")
        return record

    @asynccontextmanager
    async def dispatch_lease(self, provider_id: str, *, package_hash: str, home=None):
        """Serialize revocation with the entire awaited native transport send."""
        try:
            active = self.enabled() is True
        except Exception:
            active = False
        if not active:
            raise ProviderHookRuntimeError("disabled")
        admitted = False
        try:
            async with self.packages.dispatch_lease(
                    provider_id, expected_hash=package_hash, home=home) as record:
                self._check_record(record, provider_id, package_hash)
                admitted = True
                yield
        except ProviderHookRuntimeError:
            raise
        except Exception as exc:
            if admitted:
                raise
            raise ProviderHookRuntimeError("not_runnable") from exc

    async def assert_runnable(self, provider_id: str, *, package_hash: str, home=None) -> None:
        """Recheck the current signed grant at each native HTTPX send."""
        try:
            active = self.enabled() is True
        except Exception:
            active = False
        if not active:
            raise ProviderHookRuntimeError("disabled")
        await asyncio.to_thread(self._require_record, provider_id, package_hash, home)

    @staticmethod
    def _member_path(name: str) -> PurePosixPath:
        if type(name) is not str or not name or "\\" in name or "\x00" in name:
            raise ProviderHookRuntimeError("invalid_members")
        try:
            path = PurePosixPath(name)
            invalid = (
                len(name.encode("utf-8")) > 1024
                or path.is_absolute()
                or any(part in ("", ".", "..") for part in name.split("/"))
                or any(len(part.encode("utf-8")) > 255 for part in path.parts)
            )
        except UnicodeError:
            raise ProviderHookRuntimeError("invalid_members") from None
        if invalid:
            raise ProviderHookRuntimeError("invalid_members")
        return path

    @classmethod
    def _project_members(cls, source: Path, members, directories) -> None:
        if type(directories) is not list or len(directories) > 512:
            raise ProviderHookRuntimeError("invalid_members")
        for name in directories:
            path = cls._member_path(name)
            source.joinpath(*path.parts).mkdir(parents=True, exist_ok=True)
        seen: set[str] = set()
        for name, content in members:
            if type(content) is not bytes or name in seen:
                raise ProviderHookRuntimeError("invalid_members")
            path = cls._member_path(name)
            seen.add(name)
            destination = source.joinpath(*path.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        if "main.py" not in seen:
            raise ProviderHookRuntimeError("invalid_members")

    @staticmethod
    def _result(stdout: str, cap: int) -> dict:
        if type(stdout) is not str or len(stdout.encode("utf-8")) >= cap:
            raise ProviderHookRuntimeError("invalid_output")
        lines = stdout.splitlines()
        if len(lines) != 1 or not lines[0].startswith(_RESULT_PREFIX):
            raise ProviderHookRuntimeError("invalid_output")
        try:

            def reject_constant(_value: str):
                raise ValueError("non-finite worker value")

            def unique_pairs(pairs: list[tuple[str, object]]) -> dict:
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate worker field")
                    result[key] = value
                return result

            envelope = json.loads(
                lines[0][len(_RESULT_PREFIX) :],
                parse_constant=reject_constant,
                object_pairs_hook=unique_pairs,
            )
        except (ValueError, TypeError, RecursionError, OverflowError):
            raise ProviderHookRuntimeError("invalid_output") from None
        if (
            type(envelope) is not dict
            or set(envelope) != {"ok", "result"}
            or envelope["ok"] is not True
        ):
            raise ProviderHookRuntimeError("invalid_output")
        answer = envelope["result"]
        if (
            type(answer) is not dict
            or not {"prepared_messages", "extra_body", "api_kwargs"}.issubset(answer)
            or not set(answer).issubset(
                {
                    "prepared_messages",
                    "extra_body",
                    "api_kwargs",
                    "max_tokens",
                    "reasoning_vocabulary",
                }
            )
            or type(answer["prepared_messages"]) is not list
            or type(answer["extra_body"]) is not dict
            or type(answer["api_kwargs"]) is not dict
            or set(answer["api_kwargs"]) != {"extra_body", "kwargs"}
            or type(answer["api_kwargs"]["extra_body"]) is not dict
            or type(answer["api_kwargs"]["kwargs"]) is not dict
        ):
            raise ProviderHookRuntimeError("invalid_output")
        _validate_extra_authority(answer)
        ProviderHookRuntime._validate_optional(answer)
        try:
            _validate_tree(answer)
        except ProviderHookRuntimeError:
            raise ProviderHookRuntimeError("invalid_output") from None
        return answer

    @staticmethod
    def _validate_optional(answer: dict) -> None:
        cap_value = answer.get("max_tokens")
        if cap_value is not None and (
            type(cap_value) is not int or not 1 <= cap_value <= 1_000_000
        ):
            raise ProviderHookRuntimeError("invalid_output")
        vocabulary = answer.get("reasoning_vocabulary")
        if vocabulary is not None and (
            type(vocabulary) is not list
            or len(vocabulary) > 16
            or any(
                type(item) is not str or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", item)
                for item in vocabulary
            )
            or len(set(vocabulary)) != len(vocabulary)
        ):
            raise ProviderHookRuntimeError("invalid_output")

    async def evaluate(
        self,
        provider_id: str,
        *,
        package_hash: str,
        home=None,
        model: str,
        messages: list,
        reasoning_config=None,
        session_id=None,
    ) -> dict:
        try:
            active = self.enabled() is True
        except Exception:
            active = False
        if not active:
            raise ProviderHookRuntimeError("disabled")
        if (
            type(model) is not str
            or not 1 <= len(model) <= 256
            or type(messages) is not list
            or reasoning_config is not None
            and type(reasoning_config) is not dict
            or session_id is not None
            and (type(session_id) is not str or len(session_id) > 256)
        ):
            raise ProviderHookRuntimeError("invalid_input")
        if reasoning_config is not None and (
            reasoning_config != {"enabled": False}
            and (
                set(reasoning_config) != {"enabled", "effort"}
                or reasoning_config.get("enabled") is not True
                or type(reasoning_config.get("effort")) is not str
                or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", reasoning_config["effort"])
            )
        ):
            raise ProviderHookRuntimeError("invalid_input")
        request = {
            "model": model,
            "messages": messages,
            "reasoning_config": reasoning_config,
            "session_id": session_id,
        }
        _validate_tree(request)
        payload = _safe_json(request, max_bytes=_MAX_INPUT_BYTES, reason="invalid_input")
        record = self._require_record(provider_id, package_hash, home)
        try:
            _private_runtime_root(self.runtime_root)
            with tempfile.TemporaryDirectory(
                prefix="provider-hook-", dir=self.runtime_root
            ) as directory:
                source = Path(directory) / "source"
                contract = Path(directory) / "contract"
                source.mkdir()
                contract.mkdir()
                self._project_members(
                    source, record.members, record.manifest.get("directories", [])
                )
                (contract / "input.json").write_bytes(payload)
                (contract / "invoke.py").write_text(
                    _worker_source(record.provider_id, record.hooks), encoding="utf-8"
                )
                self.profile.seal_mount(source)
                self.profile.seal_mount(contract)
                container_name = f"nerva-provider-{uuid.uuid4().hex[:12]}"
                command = self.profile.build_command(
                    source_dir=source,
                    contract_dir=contract,
                    container_name=container_name,
                    command=["python", "-I", "/workspace/contract/invoke.py"],
                )
                result = await self.runner.run(command, container_name=container_name)
        except asyncio.CancelledError:
            raise
        except ProviderHookRuntimeError:
            raise
        except Exception as exc:
            raise ProviderHookRuntimeError("sandbox_failed") from exc
        # A permanent approval may be revoked while the worker is running.
        refreshed = self._require_record(provider_id, package_hash, home)
        if refreshed.signature != record.signature:
            raise ProviderHookRuntimeError("not_runnable")
        if result.timed_out:
            raise ProviderHookRuntimeError("timeout")
        if result.exit_code == 71:
            raise ProviderHookRuntimeError("registration_mismatch")
        if result.exit_code != 0:
            raise ProviderHookRuntimeError("sandbox_failed")
        answer = self._result(result.stdout, self.profile.max_output_bytes)
        if "get_max_tokens" not in record.hooks:
            answer["max_tokens"] = record.profile.default_max_tokens
        if "supported_reasoning_efforts" not in record.hooks:
            vocabulary = record.profile.supported_reasoning_efforts(model)
            answer["reasoning_vocabulary"] = list(vocabulary) if vocabulary is not None else None
        self._validate_optional(answer)
        return answer
