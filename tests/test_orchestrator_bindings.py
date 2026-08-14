"""Contract tests for orchestrator attributes owned by external wiring modules."""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path

import pytest

from agents.core.config import JarvisConfig
from agents.core.orchestrator import Orchestrator
from agents.core.orchestrator_bindings import (
    EXTERNAL_BINDING_WRITERS,
    ExternalOrchestratorBindings,
    bind_external_orchestrator_attribute,
)


def _binding_api_calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.args[1].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "bind_external_orchestrator_attribute"
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and isinstance(node.args[1].value, str)
    }


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


def test_external_binding_writer_inventory_matches_production_assignments() -> None:
    repo_root = Path(__file__).resolve().parent.parent

    for attribute, writer_paths in EXTERNAL_BINDING_WRITERS.items():
        assert writer_paths, attribute
        assert any(
            attribute in _binding_api_calls(repo_root / writer_path)
            for writer_path in writer_paths
        ), attribute


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
