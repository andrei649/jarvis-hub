"""Uncollected E1.2a contract assertions for owner-local route labels."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from agents.core.cortex_decision import DecisionRequest
from agents.core.cortex_measured_compare import (
    LABEL_SCHEMA,
    build_owner_route_suite,
    ensure_owner_route_suite,
    load_route_label_set,
)
from agents.core.observability.benchmark import BenchmarkStore


def _digest(number: int) -> str:
    return f"{number:064x}"


def _document() -> dict[str, object]:
    return {
        "schema": LABEL_SCHEMA,
        "label_set_id": "owner-history-2026-08",
        "sampling_rule": "consecutive-distinct-eligible-tasks",
        "source_window": {
            "start": "2026-07-01T00:00:00.000Z",
            "end": "2026-07-31T23:59:59.000Z",
        },
        "owner_attested": True,
        "retention_policy_id": "owner-local-e1-2-v1",
        "cases": [
            {
                "case_id": f"task-{number:03}",
                "text": f"synthetic weather request {number:03}",
                "privacy_class": "owner_private_local",
                "acceptable_primary_routes": ["friday"],
                "task_category": "weather",
                "source_record_digest": _digest(number),
            }
            for number in range(1, 21)
        ],
    }


def _write(directory: Path, payload: object, name: str = "labels.json") -> Path:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _load(path: Path):
    return load_route_label_set(path, allowed_routes=("friday", "jarvis"))


def _assert_rejects(directory: Path, payload: object) -> None:
    with pytest.raises(ValueError):
        _load(_write(directory, payload))


def _check_strict_route_labels() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        document = _document()
        loaded = _load(_write(directory, document))

        assert len(loaded.cases) == 20
        assert [case.case_id for case in loaded.cases] == [
            f"task-{number:03}" for number in range(1, 21)
        ]
        assert "synthetic weather request 001" not in repr(loaded)
        assert loaded.cases[0].request_digest == DecisionRequest.from_input(
            "synthetic weather request 001", {}
        ).text_digest
        assert loaded.cases[0].acceptable_primary_routes == ("friday",)
        assert len(loaded.cases[0].content_fingerprint) == 64
        assert len(loaded.content_fingerprint) == 64
        assert "synthetic weather request 001" not in loaded.cases[0].content_fingerprint
        assert "synthetic weather request 001" not in loaded.content_fingerprint
        reloaded = _load(_write(directory, document, "repeat.json"))
        assert reloaded.cases[0].content_fingerprint == loaded.cases[0].content_fingerprint
        assert reloaded.content_fingerprint == loaded.content_fingerprint

        sorted_routes = deepcopy(document)
        sorted_routes["cases"][0]["acceptable_primary_routes"] = [
            "jarvis",
            "friday",
        ]
        assert _load(_write(directory, sorted_routes, "sorted.json")).cases[
            0
        ].acceptable_primary_routes == ("friday", "jarvis")

        mutated = deepcopy(document)
        mutated["cases"] = mutated["cases"][:-1]
        _assert_rejects(directory, mutated)

        for field, value in (
            ("owner_attested", False),
            ("owner_attested", None),
            ("sampling_rule", ""),
            ("retention_policy_id", ""),
        ):
            mutated = deepcopy(document)
            mutated[field] = value
            _assert_rejects(directory, mutated)

        for field, value in (
            ("label_set_id", True),
            ("sampling_rule", True),
            ("retention_policy_id", True),
        ):
            mutated = deepcopy(document)
            mutated[field] = value
            _assert_rejects(directory, mutated)

        for mutate in (
            lambda item: item.__setitem__("case_id", "task-001"),
            lambda item: item.__setitem__("text", "  SYNTHETIC WEATHER REQUEST 001  "),
            lambda item: item.__setitem__("source_record_digest", _digest(1)),
            lambda item: item.__setitem__("privacy_class", "synthetic_public"),
            lambda item: item.__setitem__("acceptable_primary_routes", []),
            lambda item: item.__setitem__("acceptable_primary_routes", ["friday", "friday"]),
            lambda item: item.__setitem__("acceptable_primary_routes", ["Friday"]),
            lambda item: item.__setitem__("acceptable_primary_routes", ["ultron"]),
            lambda item: item.__setitem__("source_record_digest", "bad"),
            lambda item: item.__setitem__("case_id", "task/002"),
            lambda item: item.__setitem__("task_category", "weather\nforecast"),
            lambda item: item.__setitem__("text", True),
        ):
            mutated = deepcopy(document)
            mutate(mutated["cases"][1])
            _assert_rejects(directory, mutated)

        for separator in ("\u2028", "\u2029"):
            mutated = deepcopy(document)
            mutated["cases"][0]["text"] = f"weather{separator}request"
            _assert_rejects(directory, mutated)

        mutated = deepcopy(document)
        mutated["cases"][0]["acceptable_primary_routes"] = [["friday"]]
        _assert_rejects(directory, mutated)
        with pytest.raises(ValueError):
            load_route_label_set(
                _write(directory, document, "registry.json"),
                allowed_routes=(["friday"],),
            )

        for start, end in (
            ("2026-07-31T23:59:59.000Z", "2026-07-01T00:00:00.000Z"),
            ("2026-07-01T00:00:00Z", "2026-07-31T23:59:59.000Z"),
            ("2026-07-01T00:00:00.000+00:00", "2026-07-31T23:59:59.000Z"),
        ):
            mutated = deepcopy(document)
            mutated["source_window"] = {"start": start, "end": end}
            _assert_rejects(directory, mutated)

        for level, mutate in (
            ("root", lambda item: item.__setitem__("extra", "value")),
            ("root", lambda item: item.pop("schema")),
            ("window", lambda item: item.__setitem__("extra", "value")),
            ("window", lambda item: item.pop("start")),
            ("case", lambda item: item.__setitem__("extra", "value")),
            ("case", lambda item: item.pop("text")),
        ):
            mutated = deepcopy(document)
            target = (
                mutated
                if level == "root"
                else mutated["source_window"]
                if level == "window"
                else mutated["cases"][0]
            )
            mutate(target)
            _assert_rejects(directory, mutated)

        duplicate_key = directory / "duplicate-key.json"
        duplicate_key.write_text(
            '{"schema":"a","schema":"b"}', encoding="utf-8"
        )
        with pytest.raises(ValueError):
            _load(duplicate_key)
        (directory / "bom.json").write_bytes(b"\xef\xbb\xbf{}")
        with pytest.raises(ValueError):
            _load(directory / "bom.json")
        (directory / "invalid.json").write_bytes(b"\x80")
        with pytest.raises(ValueError):
            _load(directory / "invalid.json")
        for literal in ("1.0", "NaN", "Infinity"):
            (directory / "number.json").write_text(literal, encoding="utf-8")
            with pytest.raises(ValueError):
                _load(directory / "number.json")
        with pytest.raises(ValueError):
            _load(directory)
        link = directory / "labels-link.json"
        try:
            os.symlink(_write(directory, document), link)
        except (NotImplementedError, OSError):
            pass
        else:
            with pytest.raises(ValueError):
                _load(link)

        mutated = deepcopy(document)
        mutated["cases"][0]["text"] = "x" * 10_001
        _assert_rejects(directory, mutated)
        for field in ("label_set_id", "sampling_rule", "retention_policy_id"):
            mutated = deepcopy(document)
            mutated[field] = "a" * 129
            _assert_rejects(directory, mutated)


def _check_suite_binding() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set = _load(_write(directory, _document()))
        suite = build_owner_route_suite(label_set)
        assert len(suite) == 20
        assert all(case.privacy_class == "owner_private_local" for case in suite)
        assert all(case.allowed_lanes == ("local",) for case in suite)
        assert all(case.criterion and case.criterion.kind == "exact" for case in suite)
        assert all(case.criterion and case.criterion.expected == "accepted" for case in suite)
        assert all(case.task_type == "weather" for case in suite)
        for source, benchmark in zip(label_set.cases, suite, strict=True):
            assert benchmark.artifact_refs == (
                f"label-fingerprint:{label_set.content_fingerprint}",
                f"case-fingerprint:{source.content_fingerprint}",
            )
            assert label_set.label_set_id not in "".join(benchmark.artifact_refs)
            assert source.source_record_digest not in "".join(benchmark.artifact_refs)
            assert "synthetic weather request" not in "".join(benchmark.artifact_refs)

        store = BenchmarkStore(directory / "store")
        name, version, stored = ensure_owner_route_suite(store, label_set)
        assert stored == suite
        assert version == 1
        assert name == ensure_owner_route_suite(store, label_set)[0]
        assert ensure_owner_route_suite(store, label_set)[1] == 1
        stored_path = directory / "store" / "suites" / name / "v1.jsonl"
        assert "synthetic weather request 001" in stored_path.read_text(encoding="utf-8")
        changed = deepcopy(_document())
        changed["cases"][0]["task_category"] = "forecast"
        _, changed_version, _ = ensure_owner_route_suite(
            store, _load(_write(directory, changed, "changed.json"))
        )
        assert changed_version == 2

        ordered_store = BenchmarkStore(directory / "ordered-store")
        ensure_owner_route_suite(ordered_store, label_set)
        reordered = deepcopy(_document())
        reordered["cases"] = list(reversed(reordered["cases"]))
        _, reordered_version, _ = ensure_owner_route_suite(
            ordered_store, _load(_write(directory, reordered, "reordered.json"))
        )
        assert reordered_version == 2


def run_e1_2_checks() -> None:
    _check_strict_route_labels()
    _check_suite_binding()
