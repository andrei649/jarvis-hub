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

_BINDING_FUNCTION = "binding-function"
_BINDING_MODULE = "binding-module"
_BINDING_ROOT = "binding-root"
_BUILTIN_GETATTR = "builtin-getattr"
_BUILTIN_OBJECT = "builtin-object"
_BUILTIN_SETATTR = "builtin-setattr"
_OBJECT_SETATTR = "object-setattr"

# These are lexically identical to orchestrator-slot writes but are writes to an
# unrelated domain object. Keep the exception exact so a moved or duplicated write
# must be reviewed instead of broadening the receiver-name heuristics.
_UNRELATED_EXTERNAL_BINDING_WRITES = {
    ("agents/core/acquisition/promotion.py", 359, 8, "tool_rpc"),
}


class _Scope:
    def __init__(
        self,
        parent: _Scope | None = None,
        local_names: set[str] | None = None,
    ) -> None:
        self.parent = parent
        self.bindings: dict[str, str | None] = dict.fromkeys(local_names or set())

    def resolve(self, name: str) -> str | None:
        if name in self.bindings:
            return self.bindings[name]
        if self.parent is not None:
            return self.parent.resolve(name)
        return {
            "getattr": _BUILTIN_GETATTR,
            "object": _BUILTIN_OBJECT,
            "setattr": _BUILTIN_SETATTR,
        }.get(name)


def _stored_names(target: ast.AST) -> set[str]:
    return {
        node.id
        for node in ast.walk(target)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }


class _LocalNameCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.names.add(node.id)

    def visit_Import(self, node: ast.Import) -> None:
        for imported in node.names:
            self.names.add(imported.asname or imported.name.split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for imported in node.names:
            self.names.add(imported.asname or imported.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return


def _function_local_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    collector = _LocalNameCollector()
    for statement in node.body:
        collector.visit(statement)
    arguments = {
        argument.arg
        for argument in (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        )
    }
    if node.args.vararg is not None:
        arguments.add(node.args.vararg.arg)
    if node.args.kwarg is not None:
        arguments.add(node.args.kwarg.arg)
    return collector.names | arguments


class _LexicalBindingPolicy(ast.NodeVisitor):
    """Conservative lexical resolver for the CI policy, not Python execution proof."""

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.scope = _Scope()
        self.binding_calls: list[tuple[str, int, int]] = []
        self.call_errors: list[str] = []
        self.setter_calls: list[ast.Call] = []

    def _resolve(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return self.scope.resolve(node.id)
        if isinstance(node, ast.Attribute):
            owner = self._resolve(node.value)
            if owner == _BINDING_ROOT:
                return _BINDING_MODULE if node.attr == "orchestrator_bindings" else owner
            if owner == _BINDING_MODULE and node.attr == BINDING_API_NAME:
                return _BINDING_FUNCTION
            if owner == _BUILTIN_OBJECT and node.attr == "__setattr__":
                return _OBJECT_SETATTR
            return None
        if (
            isinstance(node, ast.Call)
            and self._resolve(node.func) == _BUILTIN_GETATTR
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            owner = self._resolve(node.args[0])
            attribute = node.args[1].value
            if owner == _BINDING_MODULE and attribute == BINDING_API_NAME:
                return _BINDING_FUNCTION
            if owner == _BUILTIN_OBJECT and attribute == "__setattr__":
                return _OBJECT_SETATTR
        return None

    def _bind_target(self, target: ast.expr, value: ast.expr) -> None:
        if isinstance(target, ast.Name):
            self.scope.bindings[target.id] = self._resolve(value)
            return
        if (
            isinstance(target, (ast.Tuple, ast.List))
            and isinstance(value, (ast.Tuple, ast.List))
            and len(target.elts) == len(value.elts)
        ):
            for child_target, child_value in zip(target.elts, value.elts, strict=True):
                self._bind_target(child_target, child_value)
            return
        for name in _stored_names(target):
            self.scope.bindings[name] = None

    def visit_Import(self, node: ast.Import) -> None:
        for imported in node.names:
            local_name = imported.asname or imported.name.split(".")[0]
            if imported.name.endswith(".orchestrator_bindings"):
                self.scope.bindings[local_name] = (
                    _BINDING_MODULE if imported.asname else _BINDING_ROOT
                )
            else:
                self.scope.bindings[local_name] = None

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for imported in node.names:
            local_name = imported.asname or imported.name
            if module.endswith("orchestrator_bindings") and imported.name == BINDING_API_NAME:
                symbol = _BINDING_FUNCTION
            elif imported.name == "orchestrator_bindings":
                symbol = _BINDING_MODULE
            else:
                symbol = None
            self.scope.bindings[local_name] = symbol

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            self._bind_target(target, node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
            self._bind_target(node.target, node.value)
        else:
            for name in _stored_names(node.target):
                self.scope.bindings[name] = None

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self._bind_target(node.target, node.value)

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        self.scope.bindings[node.name] = None
        for expression in (*node.decorator_list, *node.args.defaults, *node.args.kw_defaults):
            if expression is not None:
                self.visit(expression)
        previous = self.scope
        self.scope = _Scope(previous, _function_local_names(node))
        try:
            for statement in node.body:
                self.visit(statement)
        finally:
            self.scope = previous

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_Call(self, node: ast.Call) -> None:
        symbol = self._resolve(node.func)
        if symbol == _BINDING_FUNCTION:
            if (
                len(node.args) < 2
                or not isinstance(node.args[1], ast.Constant)
                or not isinstance(node.args[1].value, str)
            ):
                self.call_errors.append(f"{self.filename}:{node.lineno}:dynamic-binding-name")
            else:
                name = node.args[1].value
                if name not in EXTERNAL_BINDING_WRITERS:
                    self.call_errors.append(
                        f"{self.filename}:{node.lineno}:undeclared-binding:{name}"
                    )
                else:
                    self.binding_calls.append((name, node.lineno, node.col_offset))
        elif symbol == _BUILTIN_GETATTR and node.args:
            owner = self._resolve(node.args[0])
            attribute_is_literal = (
                len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            )
            if owner in {_BINDING_MODULE, _BUILTIN_OBJECT} and not attribute_is_literal:
                self.call_errors.append(
                    f"{self.filename}:{node.lineno}:dynamic-binding-api-reference"
                )
        elif symbol in {_BUILTIN_SETATTR, _OBJECT_SETATTR}:
            self.setter_calls.append(node)
        self.generic_visit(node)


def _lexical_policy(source: str, *, filename: str) -> _LexicalBindingPolicy:
    policy = _LexicalBindingPolicy(filename)
    policy.visit(ast.parse(source, filename=filename))
    return policy


def _binding_api_call_names(
    source: str,
    *,
    filename: str,
) -> tuple[list[tuple[str, int, int]], list[str]]:
    policy = _lexical_policy(source, filename=filename)
    return policy.binding_calls, policy.call_errors


def _binding_api_calls(path: Path) -> set[str]:
    calls, _errors = _binding_api_call_names(path.read_text(encoding="utf-8"), filename=str(path))
    return {name for name, _line, _column in calls}


def _observed_binding_writer_map(
    repo_root: Path,
) -> tuple[dict[str, set[tuple[str, int, int]]], list[str]]:
    observed: defaultdict[str, set[tuple[str, int, int]]] = defaultdict(set)
    errors: list[str] = []
    binding_module = repo_root / "agents/core/orchestrator_bindings.py"
    for path in (repo_root / "agents").rglob("*.py"):
        if path == binding_module:
            continue
        relative_path = path.relative_to(repo_root).as_posix()
        calls, call_errors = _binding_api_call_names(
            path.read_text(encoding="utf-8"), filename=relative_path
        )
        for attribute, line, column in calls:
            observed[attribute].add((relative_path, line, column))
        errors.extend(call_errors)
    return dict(observed), errors


def _writer_inventory_mismatches(
    observed: Mapping[str, set[tuple[str, int, int]]],
    expected: Mapping[str, tuple[tuple[str, int, int], ...]] = EXTERNAL_BINDING_WRITERS,
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
    return {node.id for node in ast.walk(annotation) if isinstance(node, ast.Name)}


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
    lexical_policy = _lexical_policy(source, filename=filename)
    violations: list[str] = []
    allowed = initialized | {"session_id"}

    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if not isinstance(target, ast.Attribute):
                continue
            location = (
                filename.replace("\\", "/"),
                target.lineno,
                target.col_offset,
                target.attr,
            )
            if (
                target.attr in EXTERNAL_BINDING_WRITERS
                and location not in _UNRELATED_EXTERNAL_BINDING_WRITES
            ):
                violations.append(f"{filename}:{target.lineno}:direct:{target.attr}")
            elif _is_orchestrator_receiver(target.value, known) and target.attr not in allowed:
                violations.append(f"{filename}:{target.lineno}:undeclared:{target.attr}")

    for node in lexical_policy.setter_calls:
        if len(node.args) < 2:
            continue
        name_arg = node.args[1]
        name = name_arg.value if isinstance(name_arg, ast.Constant) else "<dynamic>"
        if name in EXTERNAL_BINDING_WRITERS or _is_orchestrator_receiver(node.args[0], known):
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


def test_untyped_target_external_binding_write_is_rejected() -> None:
    source = "def wire(target, value):\n    target.argus = value\n"

    assert _binding_contract_violations(source, initialized=set()) == ["<fixture>:2:direct:argus"]


@pytest.mark.parametrize(
    "source",
    [
        """
def wire(target, value):
    write_attribute = setattr
    write_attribute(target, "argus", value)
""",
        """
def wire(target, value):
    object.__setattr__(target, "argus", value)
""",
        """
def wire(target, value):
    write_attribute = getattr(object, "__setattr__")
    write_attribute(target, "argus", value)
""",
    ],
)
def test_aliased_external_binding_setters_are_rejected(source: str) -> None:
    assert _binding_contract_violations(textwrap.dedent(source), initialized=set())


@pytest.mark.parametrize(
    "source",
    [
        """
def wire(target, value, setattr):
    setattr(target, "argus", value)
""",
        """
def wire(target, value, object):
    object.__setattr__(target, "argus", value)
""",
    ],
)
def test_shadowed_builtin_setter_names_are_not_treated_as_writers(source: str) -> None:
    assert _binding_contract_violations(textwrap.dedent(source), initialized=set()) == []


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
    ("source", "expected_line"),
    [
        (
            """
from agents.core.orchestrator_bindings import bind_external_orchestrator_attribute

(write_binding,) = (bind_external_orchestrator_attribute,)
write_binding(orchestrator, "argus", value)
""",
            5,
        ),
        (
            """
from agents.core import orchestrator_bindings

local_bindings = orchestrator_bindings
local_bindings.bind_external_orchestrator_attribute(orchestrator, "argus", value)
""",
            5,
        ),
        (
            """
import agents.core.orchestrator_bindings as bindings

write_binding = getattr(bindings, "bind_external_orchestrator_attribute")
write_binding(orchestrator, "argus", value)
""",
            5,
        ),
    ],
)
def test_binding_api_parser_tracks_lexical_alias_forms(
    source: str,
    expected_line: int,
) -> None:
    calls, errors = _binding_api_call_names(
        textwrap.dedent(source), filename="agents/core/fixture.py"
    )

    assert errors == []
    assert calls == [("argus", expected_line, 0)]


def test_dynamic_getattr_binding_api_reference_fails_closed() -> None:
    source = """
import agents.core.orchestrator_bindings as bindings

API_NAME = "bind_external_orchestrator_attribute"
write_binding = getattr(bindings, API_NAME)
write_binding(orchestrator, "argus", value)
"""

    calls, errors = _binding_api_call_names(
        textwrap.dedent(source), filename="agents/core/fixture.py"
    )

    assert calls == []
    assert errors == ["agents/core/fixture.py:5:dynamic-binding-api-reference"]


def test_shadowed_binding_api_name_is_not_counted() -> None:
    source = """
from agents.core.orchestrator_bindings import bind_external_orchestrator_attribute

def wire(bind_external_orchestrator_attribute, orchestrator, value):
    bind_external_orchestrator_attribute(orchestrator, "argus", value)
"""

    calls, errors = _binding_api_call_names(
        textwrap.dedent(source), filename="agents/core/fixture.py"
    )

    assert errors == []
    assert calls == []


def test_duplicate_binding_api_callsites_are_not_collapsed() -> None:
    source = """
from agents.core.orchestrator_bindings import bind_external_orchestrator_attribute

bind_external_orchestrator_attribute(orchestrator, "argus", first)
bind_external_orchestrator_attribute(orchestrator, "argus", second)
"""

    calls, errors = _binding_api_call_names(
        textwrap.dedent(source), filename="agents/core/fixture.py"
    )

    assert errors == []
    assert calls == [("argus", 4, 0), ("argus", 5, 0)]


def test_exact_callsite_inventory_reports_missing_and_extra_locations() -> None:
    expected = {"argus": (("agents/core/plugin_manager.py", 188, 8),)}

    assert _writer_inventory_mismatches(
        {"argus": {("agents/core/plugin_manager.py", 189, 8)}},
        expected=expected,
    ) == [
        "argus: expected=[('agents/core/plugin_manager.py', 188, 8)] "
        "observed=[('agents/core/plugin_manager.py', 189, 8)]"
    ]


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
    observed: defaultdict[str, set[tuple[str, int, int]]] = defaultdict(set)
    for attribute, line, column in calls:
        observed[attribute].add((path, line, column))

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
