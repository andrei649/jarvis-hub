"""Contract tests for orchestrator attributes owned by external wiring modules."""

from __future__ import annotations

import ast
import inspect
import textwrap
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path

import pytest

from agents.core.config import JarvisConfig
from agents.core.orchestrator import Orchestrator
from agents.core.orchestrator_bindings import (
    EXTERNAL_BINDING_WRITERS,
    ExternalOrchestratorBindings,
    bind_external_orchestrator_attribute,
)

BINDING_API_NAME = "bind_external_orchestrator_attribute"


def _dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = _dotted_name(node.value)
        return f"{owner}.{node.attr}" if owner else None
    return None


def _binding_api_call_names(
    source: str,
    *,
    filename: str,
) -> tuple[set[str], list[str]]:
    tree = ast.parse(source, filename=filename)
    function_aliases: set[str] = set()
    module_aliases: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for imported in node.names:
                if (
                    module.endswith("orchestrator_bindings")
                    and imported.name == BINDING_API_NAME
                ):
                    function_aliases.add(imported.asname or imported.name)
                if imported.name == "orchestrator_bindings":
                    module_aliases.add(imported.asname or imported.name)
        elif isinstance(node, ast.Import):
            for imported in node.names:
                if imported.name.endswith(".orchestrator_bindings"):
                    module_aliases.add(imported.asname or imported.name)

    def is_binding_reference(node: ast.expr) -> bool:
        dotted = _dotted_name(node)
        if dotted is None:
            return False
        if dotted in function_aliases:
            return True
        if dotted.endswith(f".orchestrator_bindings.{BINDING_API_NAME}"):
            return True
        return any(
            dotted == f"{module_alias}.{BINDING_API_NAME}"
            for module_alias in module_aliases
        )

    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if value is None or not is_binding_reference(value):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in function_aliases:
                    function_aliases.add(target.id)
                    changed = True

    calls: set[str] = set()
    errors: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not is_binding_reference(node.func):
            continue
        if (
            len(node.args) < 2
            or not isinstance(node.args[1], ast.Constant)
            or not isinstance(node.args[1].value, str)
        ):
            errors.append(f"{filename}:{node.lineno}:dynamic-binding-name")
            continue
        name = node.args[1].value
        if name not in EXTERNAL_BINDING_WRITERS:
            errors.append(f"{filename}:{node.lineno}:undeclared-binding:{name}")
            continue
        calls.add(name)
    return calls, errors


def _binding_api_calls(path: Path) -> set[str]:
    calls, _errors = _binding_api_call_names(
        path.read_text(encoding="utf-8"), filename=str(path)
    )
    return calls


def _observed_binding_writer_map(
    repo_root: Path,
) -> tuple[dict[str, set[str]], list[str]]:
    observed: defaultdict[str, set[str]] = defaultdict(set)
    errors: list[str] = []
    binding_module = repo_root / "agents/core/orchestrator_bindings.py"
    for path in (repo_root / "agents").rglob("*.py"):
        if path == binding_module:
            continue
        relative_path = path.relative_to(repo_root).as_posix()
        calls, call_errors = _binding_api_call_names(
            path.read_text(encoding="utf-8"), filename=relative_path
        )
        for attribute in calls:
            observed[attribute].add(relative_path)
        errors.extend(call_errors)
    return dict(observed), errors


def _writer_inventory_mismatches(
    observed: Mapping[str, set[str]],
    expected: Mapping[str, tuple[str, ...]] = EXTERNAL_BINDING_WRITERS,
) -> list[str]:
    mismatches: list[str] = []
    for attribute in sorted(set(expected) | set(observed)):
        expected_paths = set(expected.get(attribute, ()))
        observed_paths = observed.get(attribute, set())
        if observed_paths != expected_paths:
            mismatches.append(
                f"{attribute}: expected={sorted(expected_paths)!r} "
                f"observed={sorted(observed_paths)!r}"
            )
    return mismatches


def _annotation_names(annotation: ast.expr | None) -> set[str]:
    if annotation is None:
        return set()
    return {
        node.id
        for node in ast.walk(annotation)
        if isinstance(node, ast.Name)
    }


def _known_orchestrator_names(tree: ast.AST) -> set[str]:
    known = {"orch", "orchestrator", "orch_obj"}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            if "Orchestrator" in _annotation_names(argument.annotation):
                known.add(argument.arg)

    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if value is None or not _is_orchestrator_receiver(value, known):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in known:
                    known.add(target.id)
                    changed = True
    return known


def _is_orchestrator_receiver(node: ast.expr, known: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in known
    if isinstance(node, ast.Attribute):
        return node.attr in {"orchestrator", "_orch"}
    if isinstance(node, ast.Subscript):
        key = node.slice.value if isinstance(node.slice, ast.Constant) else None
        return key in {"orchestrator", "orch", "_orch"}
    return False


def _binding_contract_violations(
    source: str,
    *,
    initialized: set[str],
    filename: str = "<fixture>",
) -> list[str]:
    tree = ast.parse(source, filename=filename)
    known = _known_orchestrator_names(tree)
    violations: list[str] = []
    allowed = initialized | {"session_id"}

    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if not (
                isinstance(target, ast.Attribute)
                and _is_orchestrator_receiver(target.value, known)
            ):
                continue
            if target.attr in EXTERNAL_BINDING_WRITERS:
                violations.append(f"{filename}:{target.lineno}:direct:{target.attr}")
            elif target.attr not in allowed:
                violations.append(f"{filename}:{target.lineno}:undeclared:{target.attr}")

        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "setattr"
            and len(node.args) >= 2
            and _is_orchestrator_receiver(node.args[0], known)
        ):
            continue
        name_arg = node.args[1]
        name = name_arg.value if isinstance(name_arg, ast.Constant) else "<dynamic>"
        violations.append(f"{filename}:{node.lineno}:setattr:{name}")

    return violations


def _initialized_orchestrator_attributes() -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(Orchestrator.__init__)))
    return {
        node.target.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Attribute)
        and isinstance(node.target.value, ast.Name)
        and node.target.value.id == "self"
    } | {
        target.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
    }


def test_orchestrator_exposes_external_binding_protocol_before_wiring() -> None:
    orch = Orchestrator(JarvisConfig())

    assert isinstance(orch, ExternalOrchestratorBindings)
    assert all(getattr(orch, name) is None for name in EXTERNAL_BINDING_WRITERS)

    del orch.argus
    assert not isinstance(orch, ExternalOrchestratorBindings)


def test_external_binding_writer_inventory_exactly_matches_production_calls() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    observed, parse_errors = _observed_binding_writer_map(repo_root)

    assert parse_errors == []
    assert _writer_inventory_mismatches(observed) == []


def test_external_writers_cannot_create_undeclared_orchestrator_attributes() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    initialized = _initialized_orchestrator_attributes()
    offenders: list[str] = []
    excluded = {
        repo_root / "agents/core/orchestrator.py",
        repo_root / "agents/core/orchestrator_bindings.py",
    }
    for path in (repo_root / "agents").rglob("*.py"):
        if path in excluded:
            continue
        offenders.extend(
            _binding_contract_violations(
                path.read_text(encoding="utf-8"),
                initialized=initialized,
                filename=str(path.relative_to(repo_root)),
            )
        )

    assert offenders == []


@pytest.mark.parametrize(
    "source",
    [
        "def wire(target: Orchestrator):\n    target.undeclared = object()\n",
        "def wire(orchestrator):\n    target = orchestrator\n    target.undeclared = object()\n",
        "def wire(holder):\n    holder.orchestrator.undeclared = object()\n",
        'def wire(orchestrator):\n    setattr(orchestrator, "undeclared", object())\n',
    ],
)
def test_hostile_orchestrator_writer_forms_are_rejected(source: str) -> None:
    assert _binding_contract_violations(source, initialized=set())


def test_unrelated_same_named_assignment_cannot_satisfy_inventory(tmp_path: Path) -> None:
    source = "def wire(unrelated, value):\n    unrelated.argus = value\n"
    writer = tmp_path / "writer.py"
    writer.write_text(source, encoding="utf-8")

    assert "argus" not in _binding_api_calls(writer)


def test_binding_api_call_parser_tracks_import_alias(tmp_path: Path) -> None:
    source = """
from agents.core.orchestrator_bindings import (
    bind_external_orchestrator_attribute as write_binding,
)

def wire(orchestrator, value):
    write_binding(orchestrator, "argus", value)
"""
    writer = tmp_path / "writer.py"
    writer.write_text(source, encoding="utf-8")

    assert "argus" in _binding_api_calls(writer)


def test_binding_api_call_parser_tracks_qualified_call(tmp_path: Path) -> None:
    source = """
import agents.core.orchestrator_bindings as bindings

def wire(orchestrator, value):
    bindings.bind_external_orchestrator_attribute(orchestrator, "argus", value)
"""
    writer = tmp_path / "writer.py"
    writer.write_text(source, encoding="utf-8")

    assert "argus" in _binding_api_calls(writer)


@pytest.mark.parametrize(
    "source",
    [
        """
from agents.core.orchestrator_bindings import bind_external_orchestrator_attribute

def wire(orchestrator, value):
    bind_external_orchestrator_attribute(orchestrator, "argus", value)
""",
        """
from agents.core.orchestrator_bindings import (
    bind_external_orchestrator_attribute as write_binding,
)

def wire(orchestrator, value):
    write_binding(orchestrator, "argus", value)
""",
    ],
)
def test_unlisted_binding_api_writer_fails_inventory_closure(source: str) -> None:
    path = "agents/core/rogue_writer.py"
    calls, parse_errors = _binding_api_call_names(source, filename=path)
    observed = {attribute: {path} for attribute in calls}

    assert parse_errors == []
    assert _writer_inventory_mismatches(
        observed,
        expected={"argus": EXTERNAL_BINDING_WRITERS["argus"]},
    )


def test_binding_api_rejects_undeclared_binding_names() -> None:
    orch = Orchestrator(JarvisConfig())

    with pytest.raises(ValueError, match="undeclared external orchestrator binding"):
        bind_external_orchestrator_attribute(orch, "undeclared", object())  # type: ignore[arg-type]



def test_binding_consumers_check_availability_instead_of_attribute_presence() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    for path in (repo_root / "agents").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "hasattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in EXTERNAL_BINDING_WRITERS
            ):
                continue
            offenders.append(f"{path.relative_to(repo_root)}:{node.lineno}")

    assert offenders == []
