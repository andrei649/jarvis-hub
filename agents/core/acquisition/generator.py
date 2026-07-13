"""Strict-local, stdlib-only capability package generation."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import inspect
import json
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from agents.core.security.scanner import PIIScanner, SecretScanner

from .models import CapabilityRequest

_TOKEN = re.compile(r"[a-z][a-z0-9_]{0,63}")
_ENTRYPOINT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_ALLOWED_MODULES = frozenset(
    {
        "collections",
        "collections.abc",
        "dataclasses",
        "datetime",
        "decimal",
        "functools",
        "hashlib",
        "itertools",
        "json",
        "math",
        "operator",
        "re",
        "statistics",
        "string",
        "typing",
        "unicodedata",
        "unittest",
        "uuid",
    }
)
_FORBIDDEN_CALLS = frozenset(
    {
        "__import__",
        "breakpoint",
        "compile",
        "eval",
        "exec",
        "globals",
        "input",
        "locals",
        "open",
        "vars",
    }
)
_FORBIDDEN_ATTRIBUTES = frozenset(
    {
        "connect",
        "popen",
        "request",
        "socket",
        "spawn",
        "system",
        "urlopen",
    }
)
_OUTPUT_KEYS = frozenset({"name", "entrypoint", "code", "test"})
STDLIB_ALLOWLIST = tuple(sorted(_ALLOWED_MODULES))


class GenerationError(RuntimeError):
    pass


def _canonical_hash(payload: object) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class ContractCase:
    input: Any
    expected: Any

    def __post_init__(self) -> None:
        try:
            raw = json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValueError("contract cases must be JSON serializable") from exc
        if len(raw.encode("utf-8")) > 16_384:
            raise ValueError("contract case exceeds byte cap")


@dataclass(frozen=True, slots=True)
class CapabilityContract:
    goal: str
    entrypoint: str
    cases: tuple[ContractCase, ...]

    def __post_init__(self) -> None:
        goal = " ".join(str(self.goal or "").split())
        entrypoint = str(self.entrypoint or "").strip()
        cases = tuple(self.cases)
        if not goal or len(goal.encode("utf-8")) > 4096:
            raise ValueError("contract goal must be bounded")
        if _ENTRYPOINT.fullmatch(entrypoint) is None:
            raise ValueError("contract entrypoint must be a safe identifier")
        if not cases or len(cases) > 16 or not all(isinstance(case, ContractCase) for case in cases):
            raise ValueError("contract requires 1-16 system-owned cases")
        object.__setattr__(self, "goal", goal)
        object.__setattr__(self, "entrypoint", entrypoint)
        object.__setattr__(self, "cases", cases)

    @property
    def contract_hash(self) -> str:
        return _canonical_hash(asdict(self))


@dataclass(frozen=True, slots=True)
class GeneratedPackage:
    artifact_id: str
    request_id: str
    name: str
    entrypoint: str
    code: str
    test_code: str
    goal_hash: str
    plan_hash: str
    contract_hash: str
    model_route: str
    generated_at: float
    source_hash: str
    test_hash: str
    package_hash: str

    def canonical_members(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "request_id": self.request_id,
            "name": self.name,
            "entrypoint": self.entrypoint,
            "goal_hash": self.goal_hash,
            "plan_hash": self.plan_hash,
            "contract_hash": self.contract_hash,
            "model_route": self.model_route,
            "generated_at": self.generated_at,
            "source_hash": self.source_hash,
            "test_hash": self.test_hash,
        }


class StrictLocalGenerator:
    def __init__(
        self,
        *,
        generate: Callable[[dict], object],
        route: str,
        clock: Callable[[], float] = time.time,
        max_code_bytes: int = 64 * 1024,
        max_test_bytes: int = 64 * 1024,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._generate = generate
        self.route = str(route or "").strip().lower()
        self.clock = clock
        self.max_code_bytes = max(64, min(512 * 1024, int(max_code_bytes)))
        self.max_test_bytes = max(64, min(512 * 1024, int(max_test_bytes)))
        self.timeout_seconds = max(0.01, min(300.0, float(timeout_seconds)))
        self._secrets = SecretScanner()
        self._pii = PIIScanner()

    async def generate(
        self,
        *,
        request: CapabilityRequest,
        grounded_plan: dict,
        contract: CapabilityContract | None,
    ) -> GeneratedPackage:
        if self.route != "strict-local":
            raise GenerationError("strict-local generator route required")
        if not isinstance(contract, CapabilityContract):
            raise GenerationError("system-owned contract required")
        if contract.goal != request.goal:
            raise GenerationError("system-owned contract goal mismatch")
        if not isinstance(grounded_plan, dict) or grounded_plan.get("fully_grounded") is not True:
            raise GenerationError("fully grounded implementation plan required")

        plan_hash = _canonical_hash(grounded_plan)
        prompt = {
            "schema": 1,
            "goal": request.goal,
            "entrypoint": contract.entrypoint,
            "contract_hash": contract.contract_hash,
            "plan_hash": plan_hash,
            "requirements": [
                "Python stdlib allowlist only",
                "no filesystem, process, network, dynamic import, secrets, or credentials",
                "return JSON-serializable values",
                "include a non-vacuous unittest module",
            ],
        }
        try:
            output = self._generate(prompt)
            if inspect.isawaitable(output):
                output = await asyncio.wait_for(output, timeout=self.timeout_seconds)
        except TimeoutError as exc:
            raise GenerationError("strict-local generation timed out") from exc
        except Exception as exc:
            raise GenerationError("strict-local generation failed") from exc
        if not isinstance(output, dict):
            raise GenerationError("generator returned invalid package")
        if set(output) - _OUTPUT_KEYS:
            raise GenerationError("archive or path payloads are forbidden")

        name = str(output.get("name", "")).strip()
        entrypoint = str(output.get("entrypoint", "")).strip()
        code = output.get("code")
        test_code = output.get("test")
        if _TOKEN.fullmatch(name) is None:
            raise GenerationError("generated package name is invalid")
        if entrypoint != contract.entrypoint:
            raise GenerationError("generated entrypoint does not match system-owned contract")
        if not isinstance(code, str) or not code.strip():
            raise GenerationError("generated implementation required")
        if not isinstance(test_code, str) or not test_code.strip():
            raise GenerationError("generated verification test required")
        if len(code.encode("utf-8")) > self.max_code_bytes:
            raise GenerationError("generated code byte cap exceeded")
        if len(test_code.encode("utf-8")) > self.max_test_bytes:
            raise GenerationError("generated test byte cap exceeded")
        combined = f"{name}\n{entrypoint}\n{code}\n{test_code}"
        if self._secrets.scan(combined).findings or self._pii.scan(combined).findings:
            raise GenerationError("generated package contains a secret or personal data")

        code_tree = self._parse_and_validate(code, label="implementation", allow_main=False)
        test_tree = self._parse_and_validate(test_code, label="test", allow_main=True)
        self._validate_entrypoint(code_tree, entrypoint)
        self._validate_test(test_tree, entrypoint)

        source_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
        test_hash = hashlib.sha256(test_code.encode("utf-8")).hexdigest()
        artifact_id = uuid.uuid4().hex
        generated_at = float(self.clock())
        members = {
            "artifact_id": artifact_id,
            "request_id": request.request_id,
            "name": name,
            "entrypoint": entrypoint,
            "goal_hash": hashlib.sha256(request.goal.encode("utf-8")).hexdigest(),
            "plan_hash": plan_hash,
            "contract_hash": contract.contract_hash,
            "model_route": self.route,
            "generated_at": generated_at,
            "source_hash": source_hash,
            "test_hash": test_hash,
        }
        return GeneratedPackage(
            code=code,
            test_code=test_code,
            package_hash=_canonical_hash(members),
            **members,
        )

    @staticmethod
    def _parse_and_validate(code: str, *, label: str, allow_main: bool) -> ast.Module:
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            raise GenerationError(f"generated {label} has invalid syntax") from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "main" and allow_main:
                        continue
                    if alias.name not in _ALLOWED_MODULES:
                        raise GenerationError("generated import is outside the stdlib allowlist")
            elif isinstance(node, ast.ImportFrom):
                module = str(node.module or "")
                if module == "main" and allow_main:
                    continue
                if module not in _ALLOWED_MODULES:
                    raise GenerationError("generated import is outside the stdlib allowlist")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_CALLS:
                    raise GenerationError("generated package uses a forbidden operation")
                if isinstance(node.func, ast.Attribute) and node.func.attr in _FORBIDDEN_ATTRIBUTES:
                    raise GenerationError("generated package uses a forbidden operation")
            elif (
                isinstance(node, ast.Attribute)
                and node.attr.startswith("__")
                or isinstance(node, ast.Name)
                and node.id.startswith("__")
            ):
                raise GenerationError("generated package uses forbidden introspection")
        return tree

    @staticmethod
    def _validate_entrypoint(tree: ast.Module, entrypoint: str) -> None:
        functions = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == entrypoint
        ]
        if len(functions) != 1:
            raise GenerationError("generated entrypoint is missing or ambiguous")
        body = functions[0].body
        if not body or all(
            isinstance(node, ast.Pass)
            or (
                isinstance(node, ast.Raise)
                and isinstance(node.exc, ast.Call)
                and isinstance(node.exc.func, ast.Name)
                and node.exc.func.id == "NotImplementedError"
            )
            for node in body
        ):
            raise GenerationError("generated implementation is a placeholder")

    @staticmethod
    def _validate_test(tree: ast.Module, entrypoint: str) -> None:
        calls_entrypoint = any(
            isinstance(node, ast.Call)
            and (
                isinstance(node.func, ast.Name)
                and node.func.id == entrypoint
                or isinstance(node.func, ast.Attribute)
                and node.func.attr == entrypoint
            )
            for node in ast.walk(tree)
        )
        asserts = any(
            isinstance(node, ast.Assert)
            or (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr.startswith("assert")
            )
            for node in ast.walk(tree)
        )
        if not calls_entrypoint or not asserts:
            raise GenerationError("generated verification test must exercise and assert the entrypoint")


__all__ = [
    "CapabilityContract",
    "ContractCase",
    "GeneratedPackage",
    "GenerationError",
    "StrictLocalGenerator",
    "STDLIB_ALLOWLIST",
]
