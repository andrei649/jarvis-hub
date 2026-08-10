"""Regression guards for directly collected Nerva check manifests."""

from __future__ import annotations

import asyncio
import importlib
import inspect
from pathlib import Path

from tests.nerva_check_cases import (
    NervaCheckCase,
    case,
    run_cases,
    run_cases_async,
    validate_cases,
)

ROOT = Path(__file__).resolve().parent.parent
COLLECTOR_MODULES = (
    "tests.test_nerva_e1_1_collected",
    "tests.test_nerva_e1_2_collected",
    "tests.test_nerva_e2_0_collected",
    "tests.test_nerva_e3_0_collected",
    "tests.test_nerva_e3_0_revision_collected",
    "tests.test_nerva_e3_1_collected",
    "tests.test_nerva_e6_0_collected",
    "tests.test_nerva_e6_1_collected",
    "tests.test_nerva_e9_1_collected",
    "tests.test_nerva_innovation_lab_collected",
)


def _manifest(module):
    manifests = [
        value
        for value in vars(module).values()
        if isinstance(value, tuple)
        and value
        and all(isinstance(item, NervaCheckCase) for item in value)
    ]
    # Some thin collectors import and expose the same tuple under one name only.
    unique = {id(value): value for value in manifests}
    assert len(unique) == 1, module.__name__
    return next(iter(unique.values()))


def _collected_function(module):
    functions = [
        value
        for name, value in vars(module).items()
        if name.startswith("test_nerva_") and inspect.isfunction(value)
    ]
    assert len(functions) == 1, module.__name__
    return functions[0]


def test_all_ten_hidden_wrappers_have_distinct_direct_collection_files():
    modules = [importlib.import_module(name) for name in COLLECTOR_MODULES]
    assert len(modules) == 10
    assert len({module.__file__ for module in modules}) == 10

    manifests = [_manifest(module) for module in modules]
    cases = [item for manifest in manifests for item in manifest]
    assert len(cases) == 83
    assert len({item.id for item in cases}) == len(cases)
    prefixes = ("e1.", "e2.", "e3.", "e6.", "e9.", "innovation-lab.")
    assert all(item.id.startswith(prefixes) for item in cases)


def test_every_collector_exposes_explicit_meaningful_param_ids():
    for name in COLLECTOR_MODULES:
        module = importlib.import_module(name)
        manifest = _manifest(module)
        generated = _collected_function(module)
        marks = [mark for mark in generated.pytestmark if mark.name == "parametrize"]
        assert len(marks) == 1
        assert marks[0].kwargs["ids"] == [item.id for item in manifest]


def test_high_cost_manifests_are_split_without_changing_legacy_entrypoints():
    expected = {
        "tests._nerva_e1_2_checks": ("NERVA_E1_2_CASES", "run_e1_2_checks", 17),
        "tests._nerva_e6_0_checks": ("NERVA_E6_0_CASES", "run_e6_0_checks", 14),
        "tests._nerva_e6_1_checks": ("NERVA_E6_1_CASES", "run_e6_1_checks", 22),
        "tests._nerva_e9_1_checks": ("NERVA_E9_1_CASES", "run_e9_1_checks", 24),
    }
    for module_name, (manifest_name, runner_name, count) in expected.items():
        module = importlib.import_module(module_name)
        manifest = getattr(module, manifest_name)
        assert len(manifest) == count
        source = inspect.getsource(getattr(module, runner_name))
        assert manifest_name in source
        assert "run_cases" in source


def test_legacy_caller_tests_no_longer_hide_nerva_mega_checks():
    callers = (
        "tests/test_router_v2.py",
        "tests/test_h14_1_bitemporal_kg.py",
        "tests/test_daily_reflection.py",
        "tests/test_nerva_benchmark_e9_0.py",
    )
    for relative in callers:
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "run_e1_1_checks" not in source
        assert "run_e1_2_checks" not in source
        assert "run_e2_0_checks" not in source
        assert "run_e3_0_checks" not in source
        assert "run_e3_0_revision_checks" not in source
        assert "run_e3_1_checks" not in source
        assert "run_e6_0_checks" not in source
        assert "run_e6_1_checks" not in source
        assert "run_e9_1_checks" not in source


def test_case_runner_preserves_order_static_args_fixtures_and_async_behavior():
    events = []

    def first(prefix, value):
        events.append((prefix, value))

    async def second(value):
        await asyncio.sleep(0)
        events.append(("async", value))

    sync_cases = (
        case("proof", first, args=("static",), fixtures=("value",)),
    )
    async_cases = (case("proof", second, fixtures=("value",)),)
    run_cases(sync_cases, value=1)
    asyncio.run(run_cases_async(async_cases, value=2))
    assert events == [("static", 1), ("async", 2)]
    assert validate_cases((*sync_cases, *async_cases)) == (*sync_cases, *async_cases)
    try:
        run_cases(async_cases, value=3)
    except TypeError as exc:
        assert "requires run_cases_async" in str(exc)
    else:
        raise AssertionError("the synchronous adapter accepted an async case")
