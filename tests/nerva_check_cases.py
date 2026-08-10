"""Reusable collection adapter for bounded Nerva assertion functions.

Private ``_nerva_*_checks.py`` modules remain importable compatibility helpers.
Their independent checks are described as immutable cases here, then exposed by
thin ``test_nerva_*_collected.py`` modules so pytest and xdist can attribute and
schedule them without rewriting their assertion bodies.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

_CASE_ID_RE = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")


@dataclass(frozen=True)
class NervaCheckCase:
    """One assertion callback plus the pytest fixtures it consumes."""

    id: str
    callback: Callable[..., object]
    fixtures: tuple[str, ...] = ()
    args: tuple[object, ...] = ()


def case(
    group: str,
    callback: Callable[..., object],
    *,
    fixtures: tuple[str, ...] = (),
    args: tuple[object, ...] = (),
    name: str | None = None,
) -> NervaCheckCase:
    """Build a stable case ID from a callback name or an explicit label."""
    label = name or callback.__name__.removeprefix("_check_").removeprefix("run_")
    case_id = f"{group}.{label.replace('_', '-')}"
    if not _CASE_ID_RE.fullmatch(case_id):
        raise ValueError(f"invalid Nerva check case ID: {case_id!r}")
    if len(fixtures) != len(set(fixtures)):
        raise ValueError(f"duplicate fixtures in Nerva check case {case_id}")
    return NervaCheckCase(case_id, callback, tuple(fixtures), tuple(args))


def validate_cases(cases: Iterable[NervaCheckCase]) -> tuple[NervaCheckCase, ...]:
    normalized = tuple(cases)
    ids = [item.id for item in normalized]
    if not normalized:
        raise ValueError("a Nerva check group cannot be empty")
    if len(ids) != len(set(ids)):
        raise ValueError("Nerva check case IDs must be unique")
    return normalized


def _invoke(item: NervaCheckCase, fixture_values: dict[str, object]) -> object:
    try:
        resolved = tuple(fixture_values[name] for name in item.fixtures)
    except KeyError as exc:
        raise ValueError(f"missing fixture context {exc.args[0]!r} for {item.id}") from exc
    return item.callback(*item.args, *resolved)


def run_cases(cases: Iterable[NervaCheckCase], **fixture_values: object) -> None:
    """Preserve the legacy synchronous ``run_*`` wrapper behavior."""
    for item in validate_cases(cases):
        result = _invoke(item, fixture_values)
        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                result.close()
            raise TypeError(f"async Nerva case {item.id} requires run_cases_async")


async def run_cases_async(
    cases: Iterable[NervaCheckCase], **fixture_values: object
) -> None:
    """Preserve the legacy async wrapper behavior and ordering."""
    for item in validate_cases(cases):
        result = _invoke(item, fixture_values)
        if inspect.isawaitable(result):
            await result


def collected_test(cases: Iterable[NervaCheckCase]):
    """Return one parametrized pytest function with stable per-check node IDs."""
    import pytest

    normalized = validate_cases(cases)

    @pytest.mark.parametrize(
        "nerva_case",
        normalized,
        ids=[item.id for item in normalized],
    )
    def test_nerva_case(nerva_case: NervaCheckCase, request: Any) -> None:
        fixture_values = {
            name: request.getfixturevalue(name) for name in nerva_case.fixtures
        }
        result = _invoke(nerva_case, fixture_values)
        if inspect.isawaitable(result):
            asyncio.run(result)

    return test_nerva_case
