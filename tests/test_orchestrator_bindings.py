"""Contract tests for orchestrator attributes owned by external wiring modules."""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path

from agents.core.config import JarvisConfig
from agents.core.orchestrator import Orchestrator
from agents.core.orchestrator_bindings import (
    EXTERNAL_BINDING_WRITERS,
    ExternalOrchestratorBindings,
)


def _assigned_attributes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assigned: set[str] = set()
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Attribute):
                assigned.add(target.attr)
    return assigned


def _external_orchestrator_assignments(repo_root: Path) -> set[str]:
    assigned: set[str] = set()
    for path in (repo_root / "agents").rglob("*.py"):
        if path.name == "orchestrator.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if not isinstance(target, ast.Attribute):
                    continue
                owner = target.value
                direct_orch = isinstance(owner, ast.Name) and owner.id in {
                    "orch",
                    "orch_obj",
                }
                coordinator_orch = (
                    isinstance(owner, ast.Attribute)
                    and isinstance(owner.value, ast.Name)
                    and owner.value.id == "self"
                    and owner.attr == "_orch"
                )
                if direct_orch or coordinator_orch:
                    assigned.add(target.attr)
    return assigned


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
            attribute in _assigned_attributes(repo_root / writer_path)
            for writer_path in writer_paths
        ), attribute


def test_external_writers_cannot_create_undeclared_orchestrator_attributes() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    initialized = _initialized_orchestrator_attributes()
    property_slots = {"session_id"}

    assert _external_orchestrator_assignments(repo_root) <= initialized | property_slots


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
