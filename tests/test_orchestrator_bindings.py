"""Contract tests for orchestrator attributes owned by external wiring modules."""

from __future__ import annotations

import ast
import inspect
import textwrap
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

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
_BUILTIN_GETATTR = "builtin-getattr"
_BUILTIN_OBJECT = "builtin-object"
_BUILTIN_SETATTR = "builtin-setattr"
_OBJECT_SETATTR = "object-setattr"
_ORCHESTRATOR_RECEIVER = "orchestrator-receiver"
_ORCHESTRATOR_SETATTR = "orchestrator-setattr"
_PYTHON_MODULE_PREFIX = "python-module:"

_BINDING_MODULE_NAMES = frozenset(
    {
        "agents.core.orchestrator_bindings",
        "core.orchestrator_bindings",
    }
)

_LexicalSymbol = str | tuple[object | None, ...] | frozenset[object | None]

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
        self.bindings: dict[str, _LexicalSymbol | None] = dict.fromkeys(local_names or set())

    def resolve(self, name: str) -> _LexicalSymbol | None:
        if name in self.bindings:
            return self.bindings[name]
        if self.parent is not None:
            return self.parent.resolve(name)
        return {
            "getattr": _BUILTIN_GETATTR,
            "object": _BUILTIN_OBJECT,
            "orch": _ORCHESTRATOR_RECEIVER,
            "orchestrator": _ORCHESTRATOR_RECEIVER,
            "orch_obj": _ORCHESTRATOR_RECEIVER,
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
        self.counts: Counter[str] = Counter()

    @property
    def names(self) -> set[str]:
        return set(self.counts)

    def _record(self, name: str) -> None:
        self.counts[name] += 1

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self._record(node.id)

    def visit_Import(self, node: ast.Import) -> None:
        for imported in node.names:
            self._record(imported.asname or imported.name.split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for imported in node.names:
            self._record(imported.asname or imported.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._record(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return


def _function_scope_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    collector = _LocalNameCollector()
    for statement in node.body:
        collector.visit(statement)
    arguments = [
        argument.arg
        for argument in (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        )
    ]
    if node.args.vararg is not None:
        arguments.append(node.args.vararg.arg)
    if node.args.kwarg is not None:
        arguments.append(node.args.kwarg.arg)
    for argument in arguments:
        collector._record(argument)
    return collector.names


def _orchestrator_argument_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    return {
        argument.arg
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        if argument.arg in {"orch", "orchestrator", "orch_obj"}
        or "Orchestrator" in _annotation_names(argument.annotation)
    }


def _module_symbol(module: str) -> str:
    return f"{_PYTHON_MODULE_PREFIX}{module}"


def _module_name(symbol: object) -> str | None:
    if isinstance(symbol, str) and symbol.startswith(_PYTHON_MODULE_PREFIX):
        return symbol.removeprefix(_PYTHON_MODULE_PREFIX)
    return None


def _symbol_options(symbol: _LexicalSymbol | None) -> frozenset[object | None]:
    if isinstance(symbol, frozenset):
        return symbol
    return frozenset({symbol})


def _merge_symbols(*symbols: _LexicalSymbol | None) -> _LexicalSymbol | None:
    options = frozenset(option for symbol in symbols for option in _symbol_options(symbol))
    if len(options) == 1:
        return next(iter(options))  # type: ignore[return-value]
    return options


def _has_symbol(symbol: _LexicalSymbol | None, expected: str) -> bool:
    return expected in _symbol_options(symbol)


def _module_names(symbol: _LexicalSymbol | None) -> set[str]:
    return {
        module for option in _symbol_options(symbol) if (module := _module_name(option)) is not None
    }


def _builtin_symbol(name: str) -> str | None:
    return {
        "getattr": _BUILTIN_GETATTR,
        "object": _BUILTIN_OBJECT,
        "setattr": _BUILTIN_SETATTR,
    }.get(name)


class _LexicalBindingPolicy(ast.NodeVisitor):
    """Conservative lexical resolver for the CI policy, not Python execution proof."""

    def __init__(self, filename: str, *, initialized: set[str] | None = None) -> None:
        self.filename = filename
        self.scope = _Scope()
        self.binding_calls: list[tuple[str, int, int]] = []
        self.call_errors: list[str] = []
        self.contract_violations: list[str] = []
        self.allowed_attributes = None if initialized is None else initialized | {"session_id"}
        self._deferred_functions: list[
            tuple[
                ast.FunctionDef | ast.AsyncFunctionDef,
                _Scope,
                dict[str, _LexicalSymbol | None],
            ]
        ] = []

    def _resolve(self, node: ast.expr) -> _LexicalSymbol | None:
        if isinstance(node, ast.Name):
            return self.scope.resolve(node.id)
        if isinstance(node, ast.NamedExpr):
            symbol = self._resolve(node.value)
            self._bind_symbol(node.target, symbol)
            return symbol
        if isinstance(node, ast.IfExp):
            return _merge_symbols(self._resolve(node.body), self._resolve(node.orelse))
        if isinstance(node, ast.Attribute):
            owner = self._resolve(node.value)
            if node.attr in {"orchestrator", "_orch"}:
                return _ORCHESTRATOR_RECEIVER
            return _merge_symbols(
                *(self._resolve_attribute(option, node.attr) for option in _symbol_options(owner))
            )
        if isinstance(node, ast.Tuple):
            return tuple(self._resolve(element) for element in node.elts)
        if isinstance(node, ast.Subscript):
            key = node.slice.value if isinstance(node.slice, ast.Constant) else None
            if key in {"orchestrator", "orch", "_orch"}:
                return _ORCHESTRATOR_RECEIVER
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, int)
        ):
            owner = self._resolve(node.value)
            index = node.slice.value
            if isinstance(owner, tuple) and -len(owner) <= index < len(owner):
                return owner[index]
        if (
            isinstance(node, ast.Call)
            and _has_symbol(self._resolve(node.func), _BUILTIN_GETATTR)
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            owner = self._resolve(node.args[0])
            attribute = node.args[1].value
            return _merge_symbols(
                *(self._resolve_attribute(option, attribute) for option in _symbol_options(owner))
            )
        return None

    @staticmethod
    def _resolve_attribute(owner: object | None, attribute: str) -> _LexicalSymbol | None:
        if owner == _BINDING_MODULE and attribute == BINDING_API_NAME:
            return _BINDING_FUNCTION
        if owner == _BUILTIN_OBJECT and attribute == "__setattr__":
            return _OBJECT_SETATTR
        if owner == _ORCHESTRATOR_RECEIVER and attribute == "__setattr__":
            return _ORCHESTRATOR_SETATTR
        module = _module_name(owner)
        if module is None:
            return None
        member = f"{module}.{attribute}"
        if member in _BINDING_MODULE_NAMES:
            return _BINDING_MODULE
        if module == "builtins":
            builtin = _builtin_symbol(attribute)
            if builtin is not None:
                return builtin
        return _module_symbol(member)

    def _absolute_import_module(self, module: str, level: int) -> str:
        if level == 0:
            return module
        path_parts = list(PurePosixPath(self.filename.replace("\\", "/")).parent.parts)
        if "agents" in path_parts:
            path_parts = path_parts[path_parts.index("agents") :]
        trim = level - 1
        if trim > len(path_parts):
            return ""
        package = path_parts[: len(path_parts) - trim] if trim else path_parts
        return ".".join((*package, *(module.split(".") if module else ())))

    def _bind_target(self, target: ast.expr, value: ast.expr) -> None:
        self._bind_symbol(target, self._resolve(value))

    def _bind_symbol(
        self,
        target: ast.expr,
        symbol: _LexicalSymbol | None,
    ) -> None:
        if isinstance(target, ast.Name):
            self.scope.bindings[target.id] = symbol
            return
        if (
            isinstance(target, (ast.Tuple, ast.List))
            and isinstance(symbol, tuple)
            and len(target.elts) == len(symbol)
        ):
            for child_target, child_symbol in zip(target.elts, symbol, strict=True):
                self._bind_symbol(child_target, child_symbol)  # type: ignore[arg-type]
            return
        for name in _stored_names(target):
            self.scope.bindings[name] = None

    def _merged_bindings(
        self,
        *states: dict[str, _LexicalSymbol | None],
    ) -> dict[str, _LexicalSymbol | None]:
        return {
            name: _merge_symbols(*(state.get(name) for state in states))
            for name in set().union(*(state.keys() for state in states))
        }

    def _iterated_symbol(self, expression: ast.expr) -> _LexicalSymbol | None:
        if isinstance(expression, (ast.Tuple, ast.List, ast.Set)):
            return _merge_symbols(*(self._resolve(element) for element in expression.elts))
        symbol = self._resolve(expression)
        if isinstance(symbol, tuple):
            return _merge_symbols(*symbol)  # type: ignore[arg-type]
        return None

    def _check_attribute_target(self, target: ast.expr) -> None:
        if self.allowed_attributes is None or not isinstance(target, ast.Attribute):
            return
        location = (
            self.filename.replace("\\", "/"),
            target.lineno,
            target.col_offset,
            target.attr,
        )
        if (
            target.attr in EXTERNAL_BINDING_WRITERS
            and location not in _UNRELATED_EXTERNAL_BINDING_WRITES
        ):
            self.contract_violations.append(f"{self.filename}:{target.lineno}:direct:{target.attr}")
        elif (
            _has_symbol(self._resolve(target.value), _ORCHESTRATOR_RECEIVER)
            and target.attr not in self.allowed_attributes
        ):
            self.contract_violations.append(
                f"{self.filename}:{target.lineno}:undeclared:{target.attr}"
            )

    def visit_Module(self, node: ast.Module) -> None:
        for statement in node.body:
            self.visit(statement)
        index = 0
        while index < len(self._deferred_functions):
            function, parent, default_symbols = self._deferred_functions[index]
            index += 1
            self._visit_function_body(function, parent, default_symbols)

    def visit_Import(self, node: ast.Import) -> None:
        for imported in node.names:
            local_name = imported.asname or imported.name.split(".")[0]
            if imported.asname and imported.name in _BINDING_MODULE_NAMES:
                symbol: _LexicalSymbol | None = _BINDING_MODULE
            else:
                module = imported.name if imported.asname else imported.name.split(".")[0]
                symbol = _module_symbol(module)
            self.scope.bindings[local_name] = symbol

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = self._absolute_import_module(node.module or "", node.level)
        for imported in node.names:
            local_name = imported.asname or imported.name
            if module in _BINDING_MODULE_NAMES and imported.name == BINDING_API_NAME:
                symbol = _BINDING_FUNCTION
            elif f"{module}.{imported.name}" in _BINDING_MODULE_NAMES:
                symbol = _BINDING_MODULE
            elif module == "builtins":
                symbol = _builtin_symbol(imported.name)
            else:
                symbol = None
            self.scope.bindings[local_name] = symbol

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            self._check_attribute_target(target)
            self._bind_target(target, node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
            self._check_attribute_target(node.target)
            self._bind_target(node.target, node.value)
        else:
            self._check_attribute_target(node.target)
            for name in _stored_names(node.target):
                self.scope.bindings[name] = None

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.target)
        self.visit(node.value)
        self._check_attribute_target(node.target)
        for name in _stored_names(node.target):
            self.scope.bindings[name] = None

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self._bind_target(node.target, node.value)

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        before = self.scope.bindings.copy()

        self.scope.bindings = before.copy()
        for statement in node.body:
            self.visit(statement)
        body = self.scope.bindings.copy()

        self.scope.bindings = before.copy()
        for statement in node.orelse:
            self.visit(statement)
        orelse = self.scope.bindings.copy()

        self.scope.bindings = self._merged_bindings(body, orelse)

    def _visit_for(self, node: ast.For | ast.AsyncFor) -> None:
        self.visit(node.iter)
        before = self.scope.bindings.copy()
        self._bind_symbol(node.target, self._iterated_symbol(node.iter))
        for statement in node.body:
            self.visit(statement)
        after_iteration = self.scope.bindings.copy()
        self.scope.bindings = self._merged_bindings(before, after_iteration)
        for statement in node.orelse:
            self.visit(statement)

    visit_For = _visit_for
    visit_AsyncFor = _visit_for

    def visit_While(self, node: ast.While) -> None:
        self.visit(node.test)
        before = self.scope.bindings.copy()
        self.scope.bindings = before.copy()
        for statement in node.body:
            self.visit(statement)
        after_iteration = self.scope.bindings.copy()
        self.scope.bindings = self._merged_bindings(before, after_iteration)
        for statement in node.orelse:
            self.visit(statement)

    def _visit_try(self, node: ast.Try | ast.TryStar) -> None:
        before = self.scope.bindings.copy()
        self.scope.bindings = before.copy()
        for statement in node.body:
            self.visit(statement)
        body = self.scope.bindings.copy()

        self.scope.bindings = body.copy()
        for statement in node.orelse:
            self.visit(statement)
        paths = [before, self.scope.bindings.copy()]

        handler_start = self._merged_bindings(before, body)
        for handler in node.handlers:
            self.scope.bindings = handler_start.copy()
            if handler.type is not None:
                self.visit(handler.type)
            if handler.name is not None:
                self.scope.bindings[handler.name] = None
            for statement in handler.body:
                self.visit(statement)
            paths.append(self.scope.bindings.copy())

        self.scope.bindings = self._merged_bindings(*paths)
        for statement in node.finalbody:
            self.visit(statement)

    visit_Try = _visit_try
    visit_TryStar = _visit_try

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        self.scope.bindings[node.name] = None
        for expression in (*node.decorator_list, *node.args.defaults, *node.args.kw_defaults):
            if expression is not None:
                self.visit(expression)
        positional = (*node.args.posonlyargs, *node.args.args)
        positional_defaults = positional[len(positional) - len(node.args.defaults) :]
        default_symbols = {
            argument.arg: _merge_symbols(self._resolve(default), None)
            for argument, default in zip(
                positional_defaults,
                node.args.defaults,
                strict=True,
            )
        }
        default_symbols.update(
            {
                argument.arg: _merge_symbols(self._resolve(default), None)
                for argument, default in zip(
                    node.args.kwonlyargs,
                    node.args.kw_defaults,
                    strict=True,
                )
                if default is not None
            }
        )
        self._deferred_functions.append((node, self.scope, default_symbols))

    def _visit_function_body(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        parent: _Scope,
        default_symbols: dict[str, _LexicalSymbol | None],
    ) -> None:
        previous = self.scope
        self.scope = _Scope(parent, _function_scope_names(node))
        self.scope.bindings.update(default_symbols)
        for name in _orchestrator_argument_names(node):
            self.scope.bindings[name] = _ORCHESTRATOR_RECEIVER
        try:
            for statement in node.body:
                self.visit(statement)
        finally:
            self.scope = previous

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_Call(self, node: ast.Call) -> None:
        symbol = self._resolve(node.func)
        if _has_symbol(symbol, _BINDING_FUNCTION):
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
        if _has_symbol(symbol, _BUILTIN_GETATTR) and node.args:
            owner = self._resolve(node.args[0])
            attribute_is_literal = (
                len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            )
            if (
                _has_symbol(owner, _BINDING_MODULE)
                or _has_symbol(owner, _BUILTIN_OBJECT)
                or "builtins" in _module_names(owner)
            ) and not attribute_is_literal:
                self.call_errors.append(
                    f"{self.filename}:{node.lineno}:dynamic-binding-api-reference"
                )
        if self.allowed_attributes is not None:
            setter_names: set[str] = set()
            if (
                any(_has_symbol(symbol, setter) for setter in (_BUILTIN_SETATTR, _OBJECT_SETATTR))
                and len(node.args) >= 2
            ):
                name_arg = node.args[1]
                name = name_arg.value if isinstance(name_arg, ast.Constant) else "<dynamic>"
                if name in EXTERNAL_BINDING_WRITERS or _has_symbol(
                    self._resolve(node.args[0]), _ORCHESTRATOR_RECEIVER
                ):
                    setter_names.add(name)
            if _has_symbol(symbol, _ORCHESTRATOR_SETATTR) and node.args:
                name_arg = node.args[0]
                name = name_arg.value if isinstance(name_arg, ast.Constant) else "<dynamic>"
                setter_names.add(name)
            self.contract_violations.extend(
                f"{self.filename}:{node.lineno}:setattr:{name}" for name in sorted(setter_names)
            )
        self.generic_visit(node)


def _lexical_policy(
    source: str,
    *,
    filename: str,
    initialized: set[str] | None = None,
) -> _LexicalBindingPolicy:
    tree = ast.parse(source, filename=filename)
    policy = _LexicalBindingPolicy(filename, initialized=initialized)
    policy.visit(tree)
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
        expected_entries = expected.get(attribute, ())
        expected_counts = Counter(expected_entries)
        duplicate_paths = sorted(path for path, count in expected_counts.items() if count > 1)
        if duplicate_paths:
            mismatches.append(f"{attribute}: duplicate expected callsites={duplicate_paths!r}")
        expected_paths = set(expected_entries)
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


def _binding_contract_violations(
    source: str,
    *,
    initialized: set[str],
    filename: str = "<fixture>",
) -> list[str]:
    policy = _lexical_policy(source, filename=filename, initialized=initialized)
    return policy.contract_violations


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


@pytest.mark.parametrize(
    "source",
    [
        """
def wire(orchestrator, unrelated, value):
    orchestrator = unrelated
    orchestrator.undeclared = value
""",
        """
def wire(orchestrator, unrelated, value):
    orchestrator = unrelated
    setattr(orchestrator, "undeclared", value)
""",
    ],
)
def test_scope_local_unrelated_receiver_replacement_is_not_rejected(source: str) -> None:
    assert _binding_contract_violations(textwrap.dedent(source), initialized=set()) == []


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


def test_setter_alias_call_before_later_reassignment_is_rejected() -> None:
    source = """
def wire(target, replacement, value):
    write_attribute = setattr
    write_attribute(target, "argus", value)
    write_attribute = replacement
"""

    assert _binding_contract_violations(textwrap.dedent(source), initialized=set())


def test_named_expression_setter_alias_is_rejected() -> None:
    source = """
def wire(target, value):
    (write_attribute := setattr)(target, "argus", value)
"""

    assert _binding_contract_violations(textwrap.dedent(source), initialized=set())


def test_conditional_setter_reassignment_remains_conservative() -> None:
    sources = [
        """
def wire(target, replacement, value, condition):
    write_attribute = setattr
    if condition:
        write_attribute = replacement
    write_attribute(target, "argus", value)
""",
        """
def wire(target, replacement, value, condition):
    write_attribute = setattr if condition else replacement
    write_attribute(target, "argus", value)
""",
        """
def wire(target, replacement, value, condition):
    (write_attribute := setattr if condition else replacement)(target, "argus", value)
""",
        """
def wire(target, replacement, value, condition):
    write_attribute = setattr
    while condition:
        write_attribute = replacement
    write_attribute(target, "argus", value)
""",
        """
def wire(target, replacement, value):
    write_attribute = setattr
    try:
        write_attribute = replacement
    except Exception:
        pass
    write_attribute(target, "argus", value)
""",
        """
def wire(target, value, write_attribute=setattr):
    write_attribute(target, "argus", value)
""",
        """
def wire(target, replacement, value, condition):
    for write_attribute in (setattr if condition else replacement,):
        write_attribute(target, "argus", value)
""",
    ]

    for source in sources:
        assert _binding_contract_violations(textwrap.dedent(source), initialized=set())


def test_for_loop_setter_target_alias_is_rejected() -> None:
    source = """
def wire(target, value):
    for write_attribute in (setattr,):
        write_attribute(target, "argus", value)
"""

    assert _binding_contract_violations(textwrap.dedent(source), initialized=set())


@pytest.mark.parametrize(
    "source",
    [
        """
def wire(orchestrator, value):
    orchestrator.__setattr__("undeclared", value)
""",
        """
def wire(orchestrator, value):
    getattr(orchestrator, "__setattr__")("undeclared", value)
""",
    ],
)
def test_receiver_bound_setters_are_rejected(source: str) -> None:
    assert _binding_contract_violations(textwrap.dedent(source), initialized=set())


@pytest.mark.parametrize(
    "source",
    [
        """
def wire(orchestrator, unrelated, value):
    orchestrator = unrelated
    orchestrator.__setattr__("undeclared", value)
""",
        """
def wire(orchestrator, unrelated, value):
    orchestrator = unrelated
    getattr(orchestrator, "__setattr__")("undeclared", value)
""",
    ],
)
def test_replaced_receiver_bound_setters_are_not_rejected(source: str) -> None:
    assert _binding_contract_violations(textwrap.dedent(source), initialized=set()) == []


def test_literal_getattr_from_builtins_module_is_rejected() -> None:
    source = """
import builtins

def wire(target, value):
    write_attribute = getattr(builtins, "setattr")
    write_attribute(target, "argus", value)
"""

    assert _binding_contract_violations(textwrap.dedent(source), initialized=set())


@pytest.mark.parametrize(
    "source",
    [
        """
from builtins import setattr as write_attribute

def wire(target, value):
    write_attribute(target, "argus", value)
""",
        """
from builtins import object as root_object

def wire(target, value):
    root_object.__setattr__(target, "argus", value)
""",
        """
import builtins

def wire(target, value):
    builtins.setattr(target, "argus", value)
""",
    ],
)
def test_imported_builtin_setter_aliases_are_rejected(source: str) -> None:
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


def test_binding_api_parser_tracks_tuple_subscript_alias() -> None:
    source = """
from agents.core.orchestrator_bindings import bind_external_orchestrator_attribute

binding_apis = (bind_external_orchestrator_attribute,)
write_binding = binding_apis[0]
write_binding(orchestrator, "argus", value)
"""

    calls, errors = _binding_api_call_names(
        textwrap.dedent(source), filename="agents/core/fixture.py"
    )

    assert errors == []
    assert calls == [("argus", 6, 0)]


def test_binding_api_alias_call_before_later_reassignment_is_inventoried() -> None:
    source = """
from agents.core.orchestrator_bindings import bind_external_orchestrator_attribute

def wire(orchestrator, replacement, value):
    write_binding = bind_external_orchestrator_attribute
    write_binding(orchestrator, "argus", value)
    write_binding = replacement
"""

    calls, errors = _binding_api_call_names(
        textwrap.dedent(source), filename="agents/core/fixture.py"
    )

    assert errors == []
    assert calls == [("argus", 6, 4)]


def test_named_expression_binding_alias_is_inventoried() -> None:
    source = """
from agents.core.orchestrator_bindings import bind_external_orchestrator_attribute

def wire(orchestrator, value):
    (write_binding := bind_external_orchestrator_attribute)(
        orchestrator, "argus", value
    )
"""

    calls, errors = _binding_api_call_names(
        textwrap.dedent(source), filename="agents/core/fixture.py"
    )

    assert errors == []
    assert calls == [("argus", 5, 4)]


def test_conditional_binding_reassignment_remains_conservative() -> None:
    sources = [
        """
from agents.core.orchestrator_bindings import bind_external_orchestrator_attribute

def wire(orchestrator, replacement, value, condition):
    write_binding = bind_external_orchestrator_attribute
    if condition:
        write_binding = replacement
    write_binding(orchestrator, "argus", value)
""",
        """
from agents.core.orchestrator_bindings import bind_external_orchestrator_attribute

def wire(orchestrator, replacement, value, condition):
    write_binding = bind_external_orchestrator_attribute if condition else replacement
    write_binding(orchestrator, "argus", value)
""",
        """
from agents.core.orchestrator_bindings import bind_external_orchestrator_attribute

def wire(orchestrator, replacement, value, condition):
    (write_binding := bind_external_orchestrator_attribute if condition else replacement)(
        orchestrator, "argus", value
    )
""",
        """
from agents.core.orchestrator_bindings import bind_external_orchestrator_attribute

def wire(orchestrator, replacement, value, condition):
    write_binding = bind_external_orchestrator_attribute
    while condition:
        write_binding = replacement
    write_binding(orchestrator, "argus", value)
""",
        """
from agents.core.orchestrator_bindings import bind_external_orchestrator_attribute

def wire(orchestrator, replacement, value):
    write_binding = bind_external_orchestrator_attribute
    try:
        write_binding = replacement
    except Exception:
        pass
    write_binding(orchestrator, "argus", value)
""",
        """
from agents.core.orchestrator_bindings import bind_external_orchestrator_attribute

def wire(orchestrator, value, write_binding=bind_external_orchestrator_attribute):
    write_binding(orchestrator, "argus", value)
""",
        """
from agents.core.orchestrator_bindings import bind_external_orchestrator_attribute

def wire(orchestrator, replacement, value, condition):
    for write_binding in (
        bind_external_orchestrator_attribute if condition else replacement,
    ):
        write_binding(orchestrator, "argus", value)
""",
    ]

    for source in sources:
        calls, errors = _binding_api_call_names(
            textwrap.dedent(source), filename="agents/core/fixture.py"
        )

        assert errors == []
        assert [name for name, _line, _column in calls] == ["argus"]


def test_for_loop_binding_target_alias_is_inventoried() -> None:
    source = """
from agents.core.orchestrator_bindings import bind_external_orchestrator_attribute

def wire(orchestrator, value):
    for write_binding in (bind_external_orchestrator_attribute,):
        write_binding(orchestrator, "argus", value)
"""

    calls, errors = _binding_api_call_names(
        textwrap.dedent(source), filename="agents/core/fixture.py"
    )

    assert errors == []
    assert calls == [("argus", 6, 8)]


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


@pytest.mark.parametrize(
    "source",
    [
        """
from unrelated import orchestrator_bindings

orchestrator_bindings.bind_external_orchestrator_attribute(
    orchestrator, "argus", value
)
""",
        """
from unrelated.orchestrator_bindings import bind_external_orchestrator_attribute

bind_external_orchestrator_attribute(orchestrator, "argus", value)
""",
    ],
)
def test_unrelated_same_named_imports_cannot_satisfy_inventory(source: str) -> None:
    calls, errors = _binding_api_call_names(
        textwrap.dedent(source), filename="agents/core/fixture.py"
    )

    assert errors == []
    assert calls == []


def test_late_global_shadow_cannot_satisfy_inventory() -> None:
    source = """
from agents.core.orchestrator_bindings import bind_external_orchestrator_attribute

def wire(orchestrator, value):
    bind_external_orchestrator_attribute(orchestrator, "argus", value)

def bind_external_orchestrator_attribute(*args):
    return None
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


def test_exact_callsite_inventory_rejects_duplicate_declared_locations() -> None:
    callsite = ("agents/core/plugin_manager.py", 188, 8)

    assert _writer_inventory_mismatches(
        {"argus": {callsite}},
        expected={"argus": (callsite, callsite)},
    ) == ["argus: duplicate expected callsites=[('agents/core/plugin_manager.py', 188, 8)]"]


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
