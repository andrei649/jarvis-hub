"""Uncollected E1.2a contract assertions for owner-local route labels."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import traceback
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agents.core import cortex_measured_compare as measured_compare
from agents.core.cortex_decision import (
    DecisionRecord,
    DecisionRequest,
    ShadowDecisionRouter,
)
from agents.core.cortex_measured_compare import (
    LABEL_SCHEMA,
    build_owner_route_suite,
    ensure_owner_route_suite,
    load_route_label_set,
    measured_current_router_runner,
)
from agents.core.observability.benchmark import (
    BenchmarkHarness,
    BenchmarkObservation,
    BenchmarkRun,
    BenchmarkStore,
    Measurement,
)
from agents.core.observability.scheduled_report import (
    EnvironmentProfile,
    run_fingerprint,
)
from agents.core.router import Intent, IntentRouter

_REVISION = "a" * 40
_ARBITRARY_NOTE_SENTINEL = "arbitrary-note-sentinel"
_RETAINED_EXCEPTION_MESSAGE = "synthetic retained measured-router failure"
_LABEL_REGISTRIES: dict[int, object] = {}


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


def _privacy_document() -> dict[str, object]:
    document = _document()
    document["cases"][0]["text"] = (
        f"{_ARBITRARY_NOTE_SENTINEL} weather request 001"
    )
    document["cases"][1]["text"] = (
        f"{_RETAINED_EXCEPTION_MESSAGE} weather request 002"
    )
    return document


def _write(directory: Path, payload: object, name: str = "labels.json") -> Path:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _route_agents() -> dict[str, object]:
    return {"friday": object(), "jarvis": object()}


def _bind(agents: dict[str, object] | None = None):
    return measured_compare.bind_route_registry(
        _route_agents() if agents is None else agents
    )


def _load(path: Path, *, registry=None):
    binding = registry or _bind()
    label_set = load_route_label_set(path, registry=binding)
    _LABEL_REGISTRIES[id(label_set)] = binding
    return label_set


def _registry(label_set):
    try:
        return _LABEL_REGISTRIES[id(label_set)]
    except KeyError as exc:  # pragma: no cover - a test-fixture construction defect
        raise AssertionError("label fixture lost its registry capability") from exc


def _build_report(batch, store, label_set):
    return measured_compare.build_measured_report(
        batch,
        store,
        label_set,
        registry=_registry(label_set),
    )


def _validate_report(report, batch, store, label_set) -> None:
    measured_compare.validate_measured_report_against_evidence(
        report,
        batch,
        store,
        label_set,
        registry=_registry(label_set),
    )


def _assert_rejects(directory: Path, payload: object) -> None:
    with pytest.raises(ValueError):
        _load(_write(directory, payload))


def _capture_detached_private_error(operation, *sentinels: object) -> ValueError:
    """Require bounded failures to detach private parser/OS exception payloads."""

    with pytest.raises(ValueError) as captured:
        operation()
    error = captured.value
    assert error.__cause__ is None
    assert error.__context__ is None
    rendered = "".join(traceback.format_exception(error)).lower()
    for sentinel in sentinels:
        value = str(sentinel).lower()
        assert not value or value not in rendered
    return error


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
        assert loaded.route_registry_ids == ("friday", "jarvis")
        assert loaded.route_registry_fingerprint == _registry(loaded).fingerprint
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
        for invalid_registry in ({}, {"Friday": object()}, {True: object()}):
            with pytest.raises(ValueError):
                _bind(invalid_registry)

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
        invalid_utf8 = directory / "invalid.json"
        invalid_utf8.write_bytes(_ARBITRARY_NOTE_SENTINEL.encode("ascii") + b"\x80")
        _capture_detached_private_error(
            lambda: _load(invalid_utf8),
            _ARBITRARY_NOTE_SENTINEL,
            invalid_utf8,
        )
        malformed_private = directory / "malformed-private.json"
        malformed_private.write_text(
            '{"text":"' + _ARBITRARY_NOTE_SENTINEL + '",',
            encoding="utf-8",
        )
        _capture_detached_private_error(
            lambda: _load(malformed_private),
            _ARBITRARY_NOTE_SENTINEL,
            malformed_private,
        )
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

        private_os_path = "C:/private/owner/labels/route-labels.json"
        with patch.object(
            measured_compare.os,
            "lstat",
            side_effect=PermissionError(private_os_path),
        ):
            _capture_detached_private_error(
                lambda: _load(directory / "labels.json"),
                private_os_path,
                directory,
            )
        with patch.object(
            Path,
            "read_bytes",
            side_effect=PermissionError(private_os_path),
        ):
            _capture_detached_private_error(
                lambda: _load(directory / "labels.json"),
                private_os_path,
                directory,
            )

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
                f"registry-fingerprint:{label_set.route_registry_fingerprint}",
            )
            assert label_set.label_set_id not in "".join(benchmark.artifact_refs)
            assert source.source_record_digest not in "".join(benchmark.artifact_refs)
            assert "synthetic weather request" not in "".join(benchmark.artifact_refs)

        store = BenchmarkStore(directory / "store")
        store.root.mkdir()
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
        ordered_store.root.mkdir()
        ensure_owner_route_suite(ordered_store, label_set)
        reordered = deepcopy(_document())
        reordered["cases"] = list(reversed(reordered["cases"]))
        _, reordered_version, _ = ensure_owner_route_suite(
            ordered_store, _load(_write(directory, reordered, "reordered.json"))
        )
        assert reordered_version == 2


class _MeasuredRouter:
    def __init__(self, route_id: str = "friday") -> None:
        self.llm_classifier = None
        self.route_id = route_id
        self.classify_calls = 0
        self.last_intent: Intent | None = None

    async def classify(self, text: str, agents: dict[str, object]) -> Intent:
        self.classify_calls += 1
        self.last_intent = Intent(
            [self.route_id],
            is_general=False,
            context={"source": "deterministic-test"},
            confidence=1.0,
        )
        return self.last_intent

    async def classify_deterministic(
        self, text: str, agents: dict[str, object]
    ) -> Intent:
        return await self.classify(text, agents)


class _NoCaptureRouter:
    def __init__(self, router, _writer) -> None:
        self._router = router

    async def classify(self, text: str, agents: dict[str, object]):
        return await self._router.classify(text, agents)

    async def classify_deterministic(self, text: str, agents: dict[str, object]):
        return await self._router.classify_deterministic(text, agents)

    def __getattr__(self, name: str):
        return getattr(self._router, name)


class _DoubleCaptureRouter:
    def __init__(self, router, writer) -> None:
        self._router = router
        self._writer = writer

    async def classify(self, text: str, agents: dict[str, object]):
        intent = await self._router.classify(text, agents)
        record = DecisionRecord.from_intent(text=text, agents=agents, intent=intent)
        self._writer(record)
        self._writer(record)
        return intent

    async def classify_deterministic(self, text: str, agents: dict[str, object]):
        intent = await self._router.classify_deterministic(text, agents)
        record = DecisionRecord.from_intent(text=text, agents=agents, intent=intent)
        self._writer(record)
        self._writer(record)
        return intent

    def __getattr__(self, name: str):
        return getattr(self._router, name)


class _MismatchedCaptureRouter:
    def __init__(self, router, writer) -> None:
        self._router = router
        self._writer = writer

    async def classify(self, text: str, agents: dict[str, object]):
        intent = await self._router.classify(text, agents)
        self._writer(DecisionRecord.from_intent(text=text, agents=agents, intent=intent))
        return Intent(
            ["jarvis"],
            is_general=False,
            context={"source": "deterministic-test"},
            confidence=1.0,
        )

    async def classify_deterministic(self, text: str, agents: dict[str, object]):
        intent = await self._router.classify_deterministic(text, agents)
        self._writer(DecisionRecord.from_intent(text=text, agents=agents, intent=intent))
        return Intent(
            ["jarvis"],
            is_general=False,
            context={"source": "deterministic-test"},
            confidence=1.0,
        )

    def __getattr__(self, name: str):
        return getattr(self._router, name)


class _MismatchedRegistryCaptureRouter:
    def __init__(self, router, writer) -> None:
        self._router = router
        self._writer = writer

    async def classify_deterministic(self, text: str, agents: dict[str, object]):
        intent = await self._router.classify_deterministic(text, agents)
        self._writer(
            DecisionRecord.from_intent(
                text=text,
                agents={"friday": agents["friday"]},
                intent=intent,
            )
        )
        return intent

    def __getattr__(self, name: str):
        return getattr(self._router, name)


class _SnapshotAssertingRouter(_MeasuredRouter):
    def __init__(self, expected_agent: object) -> None:
        super().__init__()
        self.expected_agent = expected_agent
        self.saw_frozen_agent = False

    async def classify(self, text: str, agents: dict[str, object]) -> Intent:
        self.saw_frozen_agent = agents["friday"] is self.expected_agent
        return await super().classify(text, agents)


class _RegistryMutatingRouter(_MeasuredRouter):
    def __init__(self, source_agents: dict[str, object]) -> None:
        super().__init__()
        self.source_agents = source_agents

    async def classify(self, text: str, agents: dict[str, object]) -> Intent:
        intent = await super().classify(text, agents)
        self.source_agents["ultron"] = object()
        return intent


class _InterleavingCaptureRouter:
    started: asyncio.Event
    release: asyncio.Event
    calls = 0

    def __init__(self, router, writer) -> None:
        self._router = router
        self._writer = writer

    @classmethod
    def reset(cls) -> None:
        cls.started = asyncio.Event()
        cls.release = asyncio.Event()
        cls.calls = 0

    async def classify(self, text: str, agents: dict[str, object]):
        intent = await self._router.classify(text, agents)
        self._writer(DecisionRecord.from_intent(text=text, agents=agents, intent=intent))
        type(self).calls += 1
        if type(self).calls == 2:
            type(self).started.set()
        await type(self).release.wait()
        return intent

    async def classify_deterministic(self, text: str, agents: dict[str, object]):
        intent = await self._router.classify_deterministic(text, agents)
        self._writer(DecisionRecord.from_intent(text=text, agents=agents, intent=intent))
        type(self).calls += 1
        if type(self).calls == 2:
            type(self).started.set()
        await type(self).release.wait()
        return intent

    def __getattr__(self, name: str):
        return getattr(self._router, name)


def _check_route_registry_binding() -> None:
    ordered_agents = {"friday": object(), "jarvis": object()}
    reversed_agents = {"jarvis": object(), "friday": object()}
    binding = _bind(ordered_agents)
    equivalent = _bind(reversed_agents)
    expected = hashlib.sha256(
        json.dumps(
            {
                "route_ids": ["friday", "jarvis"],
                "schema": "nerva.cortex.route-registry.v1",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert binding.route_ids == ("friday", "jarvis")
    assert binding.fingerprint == equivalent.fingerprint == expected
    assert _bind({"friday": object()}).fingerprint != expected
    assert _bind({**ordered_agents, "ultron": object()}).fingerprint != expected
    assert repr(ordered_agents["friday"]) not in repr(binding)

    transient_agents = _route_agents()
    transient_binding = _bind(transient_agents)
    transient_agents["ultron"] = object()
    with pytest.raises(ValueError, match="drift|registry"):
        transient_binding.assert_unchanged()
    transient_agents.pop("ultron")
    with pytest.raises(ValueError, match="drift|registry"):
        transient_binding.assert_unchanged()

    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set = _load(_write(directory, _document()), registry=binding)
        assert label_set.route_registry_ids == binding.route_ids
        assert label_set.route_registry_fingerprint == binding.fingerprint

        expanded = _bind({**ordered_agents, "ultron": object()})
        expanded_labels = _load(
            _write(directory, _document(), "expanded-registry.json"),
            registry=expanded,
        )
        assert expanded_labels.content_fingerprint != label_set.content_fingerprint

        # A same-fingerprint binding is not the same in-memory capability.
        with pytest.raises(ValueError, match="registry|binding|capability"):
            measured_current_router_runner(_MeasuredRouter(), equivalent, label_set)
        lookalike_store = directory / "lookalike-store"
        lookalike_store.mkdir()
        with pytest.raises(ValueError, match="registry|binding|capability"):
            asyncio.run(
                measured_compare.run_measured_comparison(
                    router=_MeasuredRouter(),
                    registry=equivalent,
                    label_set=label_set,
                    store_root=lookalike_store,
                    source_revision=_REVISION,
                    run_nonce=lambda: "lookalike",
                )
            )
        assert list(lookalike_store.iterdir()) == []

        old_friday = ordered_agents["friday"]
        ordered_agents["friday"] = object()
        snapshot_router = _SnapshotAssertingRouter(old_friday)
        observation = asyncio.run(
            measured_current_router_runner(snapshot_router, binding, label_set)(
                label_set.cases[0].text
            )
        )
        assert observation.route_id == "friday"
        assert snapshot_router.saw_frozen_agent is True

        with pytest.raises(ValueError, match="registered|registry"):
            asyncio.run(
                measured_current_router_runner(
                    _MeasuredRouter("ultron"), binding, label_set
                )(label_set.cases[0].text)
            )
        benign_after_unregistered = _MeasuredRouter()
        with pytest.raises(ValueError, match="registered|registry"):
            measured_current_router_runner(
                benign_after_unregistered,
                binding,
                label_set,
            )
        assert benign_after_unregistered.classify_calls == 0

        mismatch_registry = _bind(_route_agents())
        mismatch_labels = _load(
            _write(directory, _document(), "mismatched-record-registry.json"),
            registry=mismatch_registry,
        )
        with (
            patch.object(
                measured_compare,
                "ShadowDecisionRouter",
                _MismatchedRegistryCaptureRouter,
            ),
            pytest.raises(ValueError, match="available|registry"),
        ):
            asyncio.run(
                measured_current_router_runner(
                    _MeasuredRouter(), mismatch_registry, mismatch_labels
                )(mismatch_labels.cases[0].text)
            )
        benign_after_mismatch = _MeasuredRouter()
        with pytest.raises(ValueError, match="available|registry"):
            measured_current_router_runner(
                benign_after_mismatch,
                mismatch_registry,
                mismatch_labels,
            )
        assert benign_after_mismatch.classify_calls == 0

    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        source_agents = _route_agents()
        registry = _bind(source_agents)
        label_set = _load(_write(directory, _document()), registry=registry)
        mutating = _RegistryMutatingRouter(source_agents)
        with pytest.raises(ValueError, match="drift|registry"):
            asyncio.run(
                measured_current_router_runner(mutating, registry, label_set)(
                    label_set.cases[0].text
                )
            )

    def assert_harness_phase_drift(mutate_after_call: int, name: str) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source_agents = _route_agents()
            registry = _bind(source_agents)
            label_set = _load(_write(directory, _document()), registry=registry)
            store_root = directory / name
            store_root.mkdir()
            original_run = BenchmarkHarness.run
            calls = 0

            async def mutate_after_phase(self: BenchmarkHarness, *args, **kwargs):
                nonlocal calls
                result = await original_run(self, *args, **kwargs)
                calls += 1
                if calls == mutate_after_call:
                    source_agents["ultron"] = object()
                return result

            with (
                patch.object(BenchmarkHarness, "run", mutate_after_phase),
                pytest.raises(ValueError, match="drift|registry"),
            ):
                asyncio.run(
                    measured_compare.run_measured_comparison(
                        router=_MeasuredRouter(),
                        registry=registry,
                        label_set=label_set,
                        store_root=store_root,
                        source_revision=_REVISION,
                        run_nonce=lambda: "registrydrift",
                    )
                )
            assert BenchmarkStore(store_root).runs(
                measured_compare._suite_name(label_set), last_n=sys.maxsize
            ) == ()

    assert_harness_phase_drift(1, "after-warmup-drift")
    assert_harness_phase_drift(2, "between-repetition-drift")

    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        source_agents = _route_agents()
        registry = _bind(source_agents)
        label_set = _load(_write(directory, _document()), registry=registry)
        source_agents.pop("jarvis")
        store_root = directory / "preflight-drift"
        store_root.mkdir()
        with pytest.raises(ValueError, match="drift|registry"):
            asyncio.run(
                measured_compare.run_measured_comparison(
                    router=_MeasuredRouter(),
                    registry=registry,
                    label_set=label_set,
                    store_root=store_root,
                    source_revision=_REVISION,
                )
            )
        assert list(store_root.iterdir()) == []


def _check_measured_runner() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        agents = {"friday": object(), "jarvis": object()}
        registry = _bind(agents)
        label_set = _load(_write(directory, _document()), registry=registry)
        prompt = label_set.cases[0].text

        configured = _MeasuredRouter()
        configured.llm_classifier = object()
        with pytest.raises(ValueError, match="llm_classifier=None"):
            measured_current_router_runner(configured, registry, label_set)

        mutable = _MeasuredRouter()
        runner = measured_current_router_runner(mutable, registry, label_set)
        mutable.llm_classifier = object()
        with pytest.raises(ValueError, match="llm_classifier=None"):
            asyncio.run(runner(prompt))
        assert mutable.classify_calls == 0

        unknown = _MeasuredRouter()
        unknown_runner = measured_current_router_runner(unknown, registry, label_set)
        with pytest.raises(ValueError, match="known route label"):
            asyncio.run(unknown_runner("  UNKNOWN NORMALIZED PROMPT  "))
        assert unknown.classify_calls == 0

        accepted_router = _MeasuredRouter("friday")
        accepted = asyncio.run(
            measured_current_router_runner(accepted_router, registry, label_set)(prompt)
        )
        expected_record = DecisionRecord.from_intent(
            text=prompt,
            agents=agents,
            intent=accepted_router.last_intent,
        )
        assert accepted.response == "accepted"
        assert accepted.route_id == "friday"
        assert accepted.artifact_refs == (
            f"decision:{expected_record.replay_fingerprint}",
            f"registry-fingerprint:{registry.fingerprint}",
        )
        assert prompt not in "".join(accepted.artifact_refs)
        assert label_set.cases[0].source_record_digest not in "".join(
            accepted.artifact_refs
        )

        rejected = asyncio.run(
            measured_current_router_runner(
                _MeasuredRouter("jarvis"), registry, label_set
            )(
                prompt
            )
        )
        assert rejected.response == "rejected"
        assert rejected.route_id == "jarvis"

        for wrapper in (_NoCaptureRouter, _DoubleCaptureRouter, _MismatchedCaptureRouter):
            with patch.object(measured_compare, "ShadowDecisionRouter", wrapper):
                bad_runner = measured_current_router_runner(
                    _MeasuredRouter(), registry, label_set
                )
                with pytest.raises(RuntimeError):
                    asyncio.run(bad_runner(prompt))

        async def _run_concurrently() -> tuple[object, object]:
            _InterleavingCaptureRouter.reset()
            concurrent_runner = measured_current_router_runner(
                _MeasuredRouter(), registry, label_set
            )
            first = asyncio.create_task(concurrent_runner(label_set.cases[0].text))
            second = asyncio.create_task(concurrent_runner(label_set.cases[1].text))
            await _InterleavingCaptureRouter.started.wait()
            _InterleavingCaptureRouter.release.set()
            return await asyncio.gather(first, second)

        with patch.object(
            measured_compare, "ShadowDecisionRouter", _InterleavingCaptureRouter
        ):
            first, second = asyncio.run(_run_concurrently())
        assert first.response == second.response == "accepted"
        assert first.artifact_refs != second.artifact_refs


class _FailingMeasuredRouter(_MeasuredRouter):
    async def classify(self, text: str, agents: dict[str, object]) -> Intent:
        self.classify_calls += 1
        raise RuntimeError("synthetic measured-router failure")


class _FailAfterWarmupRouter(_MeasuredRouter):
    async def classify(self, text: str, agents: dict[str, object]) -> Intent:
        if self.classify_calls >= 20:
            self.classify_calls += 1
            raise RuntimeError(_RETAINED_EXCEPTION_MESSAGE)
        return await super().classify(text, agents)


def _with_unscored_result(run: object):
    result = run.results[0]
    unscored = replace(
        result,
        status="unscored",
        passed=None,
        quality=Measurement("not_measured"),
    )
    return replace(run, results=(unscored, *run.results[1:]))


def _check_measured_run_batch() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        agents = {"friday": object(), "jarvis": object()}
        registry = _bind(agents)
        label_set = _load(_write(directory, _document()), registry=registry)

        constructed_roots: list[tuple[object, ...]] = []

        class _TrackingStore(BenchmarkStore):
            def __init__(self, *args: object, **kwargs: object) -> None:
                constructed_roots.append(args)
                super().__init__(*args, **kwargs)

        invalid_root = directory / "invalid-store"
        invalid_file = directory / "not-a-directory"
        invalid_file.write_text("not a benchmark store", encoding="utf-8")
        invalid_roots: tuple[object, ...] = (
            str(invalid_root),
            Path("relative-store"),
            invalid_root,
            invalid_file,
        )
        with patch.object(measured_compare, "BenchmarkStore", _TrackingStore):
            for invalid in invalid_roots:
                with pytest.raises((TypeError, ValueError)):
                    asyncio.run(
                        measured_compare.run_measured_comparison(
                            router=_MeasuredRouter(),
                            registry=registry,
                            label_set=label_set,
                            store_root=invalid,
                            source_revision=_REVISION,
                        )
                    )
            with pytest.raises(TypeError):
                asyncio.run(
                    measured_compare.run_measured_comparison(
                        router=_MeasuredRouter(),
                        registry=registry,
                        label_set=label_set,
                        source_revision=_REVISION,
                    )
                )
        assert constructed_roots == []
        assert not invalid_root.exists()

        link_target = directory / "link-target"
        link_target.mkdir()
        ancestor_target = directory / "ancestor-target"
        ancestor_store = ancestor_target / "store"
        ancestor_store.mkdir(parents=True)
        link_root = directory / "link-store"
        try:
            os.symlink(link_target, link_root, target_is_directory=True)
        except (NotImplementedError, OSError):
            pass
        else:
            constructed_roots.clear()
            with (
                patch.object(measured_compare, "BenchmarkStore", _TrackingStore),
                pytest.raises(ValueError, match="symlink|reparse"),
            ):
                asyncio.run(
                    measured_compare.run_measured_comparison(
                        router=_MeasuredRouter(),
                        registry=registry,
                        label_set=label_set,
                        store_root=link_root,
                        source_revision=_REVISION,
                    )
                )
            assert constructed_roots == []

            ancestor_link = directory / "ancestor-link"
            os.symlink(ancestor_target, ancestor_link, target_is_directory=True)
            constructed_roots.clear()
            with (
                patch.object(measured_compare, "BenchmarkStore", _TrackingStore),
                pytest.raises(ValueError, match="symlink|reparse"),
            ):
                asyncio.run(
                    measured_compare.run_measured_comparison(
                        router=_MeasuredRouter(),
                        registry=registry,
                        label_set=label_set,
                        store_root=ancestor_link / "store",
                        source_revision=_REVISION,
                    )
                )
            assert constructed_roots == []

        if os.name == "nt":
            junction_root = directory / "junction-store"
            created = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction_root), str(link_target)],
                check=False,
                capture_output=True,
                text=True,
            )
            assert created.returncode == 0, created.stderr
            try:
                constructed_roots.clear()
                with (
                    patch.object(
                        measured_compare, "BenchmarkStore", _TrackingStore
                    ),
                    pytest.raises(ValueError, match="symlink|reparse"),
                ):
                    asyncio.run(
                        measured_compare.run_measured_comparison(
                            router=_MeasuredRouter(),
                            registry=registry,
                            label_set=label_set,
                            store_root=junction_root,
                            source_revision=_REVISION,
                        )
                    )
                assert constructed_roots == []
            finally:
                os.rmdir(junction_root)

            ancestor_junction = directory / "ancestor-junction"
            created = subprocess.run(
                [
                    "cmd",
                    "/c",
                    "mklink",
                    "/J",
                    str(ancestor_junction),
                    str(ancestor_target),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            assert created.returncode == 0, created.stderr
            try:
                constructed_roots.clear()
                with (
                    patch.object(
                        measured_compare, "BenchmarkStore", _TrackingStore
                    ),
                    pytest.raises(ValueError, match="symlink|reparse"),
                ):
                    asyncio.run(
                        measured_compare.run_measured_comparison(
                            router=_MeasuredRouter(),
                            registry=registry,
                            label_set=label_set,
                            store_root=ancestor_junction / "store",
                            source_revision=_REVISION,
                        )
                    )
                assert constructed_roots == []
            finally:
                os.rmdir(ancestor_junction)

        preflight_root = directory / "preflight-store"
        preflight_root.mkdir()
        for revision in ("A" * 40, "a" * 39, "g" * 40, "a" * 41, True):
            with pytest.raises(ValueError, match="revision"):
                asyncio.run(
                    measured_compare.run_measured_comparison(
                        router=_MeasuredRouter(),
                        registry=registry,
                        label_set=label_set,
                        store_root=preflight_root,
                        source_revision=revision,
                    )
                )
        with pytest.raises(ValueError, match="RouteLabelSet"):
            asyncio.run(
                measured_compare.run_measured_comparison(
                    router=_MeasuredRouter(),
                    registry=registry,
                    label_set=object(),
                    store_root=preflight_root,
                    source_revision=_REVISION,
                )
            )
        lookalike_registry = _bind({"jarvis": object()})
        with pytest.raises(ValueError, match="registry|binding|capability"):
            asyncio.run(
                measured_compare.run_measured_comparison(
                    router=_MeasuredRouter(),
                    registry=lookalike_registry,
                    label_set=label_set,
                    store_root=preflight_root,
                    source_revision=_REVISION,
                )
            )
        configured = _MeasuredRouter()
        configured.llm_classifier = object()
        with pytest.raises(ValueError, match="llm_classifier=None"):
            asyncio.run(
                measured_compare.run_measured_comparison(
                    router=configured,
                    registry=registry,
                    label_set=label_set,
                    store_root=preflight_root,
                    source_revision=_REVISION,
                )
            )
        assert list(preflight_root.iterdir()) == []

        store_root = directory / "measured-store"
        store_root.mkdir()
        router = _MeasuredRouter()
        environment = EnvironmentProfile.detect(runner_id="owner-local-e1-2a")
        constructed_roots.clear()
        with (
            patch.object(measured_compare, "BenchmarkStore", _TrackingStore),
            patch.object(
                measured_compare.EnvironmentProfile,
                "detect",
                return_value=environment,
            ) as detect,
        ):
            batch = asyncio.run(
                measured_compare.run_measured_comparison(
                    router=router,
                    registry=registry,
                    label_set=label_set,
                    store_root=store_root,
                    source_revision=_REVISION,
                    run_nonce=lambda: "fixednonce",
                )
            )
        detect.assert_called_once_with(runner_id="owner-local-e1-2a")
        assert len(constructed_roots) > 1
        assert set(constructed_roots) == {(store_root.resolve(),)}
        assert router.classify_calls == 20 * 6
        assert batch.store_root == store_root.resolve()
        assert batch.label_set_fingerprint == label_set.content_fingerprint
        assert batch.route_registry_fingerprint == registry.fingerprint
        assert batch.suite_name.startswith("owner-route-")
        assert batch.suite_version == 1
        assert batch.environment == environment
        assert batch.environment_fingerprint == measured_compare._fingerprint(
            environment.canonical_payload()
        )
        assert batch.source_revision == _REVISION
        assert batch.repetitions == 5
        assert len(batch.run_fingerprints) == 5
        assert all(re.fullmatch(r"[0-9a-f]{64}", item) for item in batch.run_fingerprints)
        assert str(store_root) not in repr(batch)

        store = BenchmarkStore(store_root)
        retained_newest_first = store.runs(batch.suite_name, last_n=20)
        retained = tuple(reversed(retained_newest_first))
        assert len(retained) == 5
        assert batch.run_fingerprints == tuple(run_fingerprint(run) for run in retained)
        for repetition, run in enumerate(retained, start=1):
            assert run.lane == "local"
            assert run.candidate_id == "current-router-e1.2a"
            assert run.baseline_id is None
            assert run.source_revision == _REVISION
            assert run.run_id.startswith(
                f"run-{label_set.content_fingerprint[:12]}-fixednonce-"
            )
            assert run.run_id.endswith(f"-{repetition}")
            assert len(run.run_id) <= 128
            assert run.artifact_refs == (
                f"label-fingerprint:{label_set.content_fingerprint}",
                f"registry-fingerprint:{registry.fingerprint}",
                f"environment-fingerprint:{batch.environment_fingerprint}",
            )
            assert all(
                f"registry-fingerprint:{registry.fingerprint}"
                in result.candidate.artifact_refs
                for result in run.results
                if result.candidate is not None
            )

        with pytest.raises(FrozenInstanceError):
            batch.source_revision = "b" * 40
        with pytest.raises(ValueError, match="internally"):
            measured_compare.MeasuredRunBatch(
                label_set_fingerprint=label_set.content_fingerprint,
                route_registry_fingerprint=registry.fingerprint,
                suite_name=batch.suite_name,
                suite_version=batch.suite_version,
                environment=environment,
                environment_fingerprint=batch.environment_fingerprint,
                source_revision=_REVISION,
                run_fingerprints=batch.run_fingerprints,
                store_root=store_root,
                _route_registry_token=object(),
            )
        with pytest.raises(ValueError, match="internally"):
            replace(batch, source_revision="b" * 40)

        warmup_root = directory / "warmup-error-store"
        warmup_root.mkdir()
        failing_router = _FailingMeasuredRouter()
        with pytest.raises(RuntimeError, match="warm-up"):
            asyncio.run(
                measured_compare.run_measured_comparison(
                    router=failing_router,
                    registry=registry,
                    label_set=label_set,
                    store_root=warmup_root,
                    source_revision=_REVISION,
                )
            )
        warmup_store = BenchmarkStore(warmup_root)
        assert failing_router.classify_calls == 20
        assert warmup_store.runs(measured_compare._suite_name(label_set)) == ()

        warmup_unscored_root = directory / "warmup-unscored-store"
        warmup_unscored_root.mkdir()
        original_harness_run = BenchmarkHarness.run
        warmup_calls = 0

        async def _unscored_warmup(self: BenchmarkHarness, *args, **kwargs):
            nonlocal warmup_calls
            warmup_calls += 1
            return _with_unscored_result(
                await original_harness_run(self, *args, **kwargs)
            )

        with (
            patch.object(BenchmarkHarness, "run", _unscored_warmup),
            pytest.raises(RuntimeError, match="warm-up"),
        ):
            asyncio.run(
                measured_compare.run_measured_comparison(
                    router=_MeasuredRouter(),
                    registry=registry,
                    label_set=label_set,
                    store_root=warmup_unscored_root,
                    source_revision=_REVISION,
                )
            )
        assert warmup_calls == 1
        assert BenchmarkStore(warmup_unscored_root).runs(
            measured_compare._suite_name(label_set)
        ) == ()

        retained_error_root = directory / "retained-error-store"
        retained_error_root.mkdir()
        retained_error_router = _FailAfterWarmupRouter()
        error_batch = asyncio.run(
            measured_compare.run_measured_comparison(
                router=retained_error_router,
                registry=registry,
                label_set=label_set,
                store_root=retained_error_root,
                source_revision=_REVISION,
                run_nonce=lambda: "retainederror",
            )
        )
        error_runs = tuple(
            reversed(
                BenchmarkStore(retained_error_root).runs(
                    error_batch.suite_name,
                    last_n=20,
                )
            )
        )
        assert retained_error_router.classify_calls == 20 * 6
        assert len(error_runs) == 5
        assert all(any(result.status == "error" for result in run.results) for run in error_runs)
        assert error_batch.run_fingerprints == tuple(
            run_fingerprint(run) for run in error_runs
        )

        retained_unscored_root = directory / "retained-unscored-store"
        retained_unscored_root.mkdir()
        retained_calls = 0

        async def _unscored_retained(self: BenchmarkHarness, *args, **kwargs):
            nonlocal retained_calls
            retained_calls += 1
            run = await original_harness_run(self, *args, **kwargs)
            return run if retained_calls == 1 else _with_unscored_result(run)

        with patch.object(BenchmarkHarness, "run", _unscored_retained):
            unscored_batch = asyncio.run(
                measured_compare.run_measured_comparison(
                    router=_MeasuredRouter(),
                    registry=registry,
                    label_set=label_set,
                    store_root=retained_unscored_root,
                    source_revision=_REVISION,
                    run_nonce=lambda: "retainedunscored",
                )
            )
        unscored_runs = tuple(
            reversed(
                BenchmarkStore(retained_unscored_root).runs(
                    unscored_batch.suite_name,
                    last_n=20,
                )
            )
        )
        assert retained_calls == 6
        assert len(unscored_runs) == 5
        assert all(
            any(result.status == "unscored" for result in run.results)
            for run in unscored_runs
        )
        assert unscored_batch.run_fingerprints == tuple(
            run_fingerprint(run) for run in unscored_runs
        )

        before_collision = store.runs(batch.suite_name, last_n=20)
        collision_router = _MeasuredRouter()
        scan_requests: list[int] = []
        original_runs = BenchmarkStore.runs

        def _old_collision_only_for_complete_scan(
            self: BenchmarkStore, name: str, *, last_n: int = 20
        ):
            scan_requests.append(last_n)
            if last_n == sys.maxsize:
                return before_collision
            return ()

        with (
            patch.object(
                BenchmarkStore,
                "runs",
                _old_collision_only_for_complete_scan,
            ),
            pytest.raises(ValueError, match="collision"),
        ):
            asyncio.run(
                measured_compare.run_measured_comparison(
                    router=collision_router,
                    registry=registry,
                    label_set=label_set,
                    store_root=store_root,
                    source_revision=_REVISION,
                    run_nonce=lambda: "fixednonce",
                )
            )
        assert scan_requests == [sys.maxsize]
        assert collision_router.classify_calls == 20
        assert original_runs(store, batch.suite_name, last_n=20) == before_collision

        write_failure_root = directory / "write-failure-store"
        write_failure_root.mkdir()
        write_failure_router = _MeasuredRouter()
        original_record_run = BenchmarkStore.record_run
        writes = 0

        def _fail_second_write(self: BenchmarkStore, run: object) -> None:
            nonlocal writes
            writes += 1
            if writes == 2:
                raise OSError("synthetic retained-write failure")
            original_record_run(self, run)

        with (
            patch.object(BenchmarkStore, "record_run", _fail_second_write),
        ):
            _assert_bounded_topology_error(
                lambda: asyncio.run(
                    measured_compare.run_measured_comparison(
                        router=write_failure_router,
                        registry=registry,
                        label_set=label_set,
                        store_root=write_failure_root,
                        source_revision="b" * 64,
                        run_nonce=lambda: "writefail",
                    )
                ),
                write_failure_root,
            )
        failed_store = BenchmarkStore(write_failure_root)
        failed_suite_name = measured_compare._suite_name(label_set)
        assert writes == 2
        assert write_failure_router.classify_calls == 20 * 3
        written_before_failure = failed_store.runs(failed_suite_name, last_n=20)
        assert len(written_before_failure) == 1
        assert written_before_failure[0].source_revision == "b" * 64

        proof_failure_root = directory / "proof-failure-store"
        proof_failure_root.mkdir()
        proof_failure_router = _MeasuredRouter()
        original_runs = BenchmarkStore.runs
        reads = 0

        def _hide_just_written(
            self: BenchmarkStore, name: str, *, last_n: int = 20
        ) -> tuple[object, ...]:
            nonlocal reads
            reads += 1
            if reads == 2:
                return ()
            return original_runs(self, name, last_n=last_n)

        with (
            patch.object(BenchmarkStore, "runs", _hide_just_written),
            pytest.raises(RuntimeError, match="retrievable"),
        ):
            asyncio.run(
                measured_compare.run_measured_comparison(
                    router=proof_failure_router,
                    registry=registry,
                    label_set=label_set,
                    store_root=proof_failure_root,
                    source_revision=_REVISION,
                    run_nonce=lambda: "prooffail",
                )
            )
        assert proof_failure_router.classify_calls == 20 * 2
        assert len(BenchmarkStore(proof_failure_root).runs(failed_suite_name)) == 1

        duplicate_proof_root = directory / "duplicate-proof-store"
        duplicate_proof_root.mkdir()

        def _duplicate_just_written(
            self: BenchmarkStore, name: str, *, last_n: int = 20
        ):
            retained_records = original_runs(self, name, last_n=last_n)
            if retained_records:
                return (retained_records[0], retained_records[0])
            return ()

        with (
            patch.object(BenchmarkStore, "runs", _duplicate_just_written),
            pytest.raises(RuntimeError, match="retrievable"),
        ):
            asyncio.run(
                measured_compare.run_measured_comparison(
                    router=_MeasuredRouter(),
                    registry=registry,
                    label_set=label_set,
                    store_root=duplicate_proof_root,
                    source_revision=_REVISION,
                    run_nonce=lambda: "duplicateproof",
                )
            )
        assert len(BenchmarkStore(duplicate_proof_root).runs(failed_suite_name)) == 1

        mismatch_proof_root = directory / "mismatch-proof-store"
        mismatch_proof_root.mkdir()

        def _mismatch_just_written(
            self: BenchmarkStore, name: str, *, last_n: int = 20
        ):
            retained_records = original_runs(self, name, last_n=last_n)
            if not retained_records:
                return ()
            mismatched = replace(
                retained_records[0],
                artifact_refs=("environment-fingerprint:" + "f" * 64,),
            )
            return (mismatched,)

        with (
            patch.object(BenchmarkStore, "runs", _mismatch_just_written),
            pytest.raises(RuntimeError, match="retrievable"),
        ):
            asyncio.run(
                measured_compare.run_measured_comparison(
                    router=_MeasuredRouter(),
                    registry=registry,
                    label_set=label_set,
                    store_root=mismatch_proof_root,
                    source_revision=_REVISION,
                    run_nonce=lambda: "mismatchproof",
                )
            )
        assert len(BenchmarkStore(mismatch_proof_root).runs(failed_suite_name)) == 1


class _PatternMeasuredRouter(_MeasuredRouter):
    async def classify(self, text: str, agents: dict[str, object]) -> Intent:
        self.classify_calls += 1
        number = int(text.rsplit(" ", 1)[-1])
        route_id = "friday" if number <= 15 else "jarvis"
        self.last_intent = Intent(
            [route_id],
            is_general=False,
            context={"source": "deterministic-test"},
            confidence=1.0,
        )
        return self.last_intent


class _ControlledLatencyClock:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> float:
        pair = self.calls // 2
        is_finish = self.calls % 2 == 1
        self.calls += 1
        if not is_finish:
            return 0.0
        retained_sample = pair - 19
        return max(1, retained_sample) / 1_000


def _report_fixture(
    directory: Path,
    *,
    document: dict[str, object] | None = None,
    environment: EnvironmentProfile | None = None,
    router: _MeasuredRouter | None = None,
    nonce: str = "reportfixture",
):
    agents = _route_agents()
    registry = _bind(agents)
    label_set = _load(
        _write(directory, document or _document()),
        registry=registry,
    )
    store_root = directory / "report-store"
    store_root.mkdir()
    environment = environment or EnvironmentProfile.detect(
        runner_id="owner-local-e1-2a"
    )
    with (
        patch(
            "agents.core.observability.benchmark.time.perf_counter",
            side_effect=_ControlledLatencyClock(),
        ),
        patch.object(
            measured_compare.EnvironmentProfile,
            "detect",
            return_value=environment,
        ),
    ):
        batch = asyncio.run(
            measured_compare.run_measured_comparison(
                router=router or _PatternMeasuredRouter(),
                registry=registry,
                label_set=label_set,
                store_root=store_root,
                source_revision=_REVISION,
                run_nonce=lambda: nonce,
            )
        )
    return (
        label_set,
        batch,
        BenchmarkStore(store_root),
        environment,
    )


def _refingerprint_report(raw: dict[str, object]) -> str:
    raw["content_fingerprint"] = measured_compare._fingerprint(
        {key: value for key, value in raw.items() if key != "content_fingerprint"}
    )
    return json.dumps(raw)


def _refingerprint_environment(raw: dict[str, object]) -> None:
    environment = raw["environment"]
    assert isinstance(environment, dict)
    environment["content_fingerprint"] = measured_compare._fingerprint(
        {
            key: value
            for key, value in environment.items()
            if key != "content_fingerprint"
        }
    )


def _detected_environment(
    *,
    system: str,
    machine: str,
    python_version: str,
) -> EnvironmentProfile:
    with (
        patch(
            "agents.core.observability.scheduled_report.platform.system",
            return_value=system,
        ),
        patch(
            "agents.core.observability.scheduled_report.platform.machine",
            return_value=machine,
        ),
        patch(
            "agents.core.observability.scheduled_report.platform.python_version",
            return_value=python_version,
        ),
    ):
        return EnvironmentProfile.detect(runner_id="owner-local-e1-2a")


def _construct_report(report, **changes):
    constructor = {
        field.name: getattr(report, field.name)
        for field in fields(report)
        if field.init
    }
    constructor.update(changes)
    constructor["_guard"] = measured_compare._MEASURED_REPORT_GUARD
    return measured_compare.MeasuredComparisonReport(**constructor)


def _guarded_batch(batch, **changes):
    return replace(
        batch,
        _guard=measured_compare._MEASURED_BATCH_GUARD,
        **changes,
    )


def _runs_path(store: BenchmarkStore, suite_name: str) -> Path:
    return store.root / "suites" / suite_name / "runs.jsonl"


def _ordered_runs(store: BenchmarkStore, suite_name: str) -> tuple[object, ...]:
    return tuple(reversed(store.runs(suite_name, last_n=sys.maxsize)))


def _write_runs(store: BenchmarkStore, suite_name: str, runs: tuple[object, ...]) -> None:
    _runs_path(store, suite_name).write_text(
        "".join(f"{run.to_json()}\n" for run in runs),
        encoding="utf-8",
    )


def _replace_result(run, index: int, **changes):
    results = list(run.results)
    results[index] = replace(results[index], **changes)
    return replace(run, results=tuple(results))


def _build_with_run_mutation(batch, store, label_set, mutate):
    original = _ordered_runs(store, batch.suite_name)
    changed = (mutate(original[0]), *original[1:])
    _write_runs(store, batch.suite_name, changed)
    changed_batch = _guarded_batch(
        batch,
        run_fingerprints=tuple(run_fingerprint(run) for run in changed),
    )
    try:
        return _build_report(changed_batch, store, label_set)
    finally:
        _write_runs(store, batch.suite_name, original)


def _assert_run_mutation_rejected(batch, store, label_set, mutate) -> None:
    with pytest.raises((TypeError, ValueError)):
        _build_with_run_mutation(batch, store, label_set, mutate)


def _assert_raw_run_mutation_rejected(store, batch, mutate) -> None:
    path = _runs_path(store, batch.suite_name)
    original = path.read_text(encoding="utf-8")
    raw = [json.loads(line) for line in original.splitlines()]
    mutate(raw[0])
    path.write_text("".join(f"{json.dumps(run)}\n" for run in raw), encoding="utf-8")
    try:
        with pytest.raises((TypeError, ValueError)):
            store.runs(batch.suite_name, last_n=sys.maxsize)
    finally:
        path.write_text(original, encoding="utf-8")


def _check_report_count_parser_attacks() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set, batch, store, _ = _report_fixture(directory)
        report = _build_report(batch, store, label_set)
        raw = json.loads(report.to_json())

        mutations = (
            lambda value: value.update({"accepted_task_count": 14}),
            lambda value: value.update({"nondeterministic_task_count": 1}),
            lambda value: value.update({"error_observation_count": 1}),
            lambda value: value.update({"observation_count": 99}),
            lambda value: value["per_actual_route"][0].update(
                {"scored_task_count": 14}
            ),
            lambda value: value["per_actual_route"][1].update(
                {"accepted_task_count": 1}
            ),
        )
        for mutate in mutations:
            impossible = deepcopy(raw)
            mutate(impossible)
            with pytest.raises(ValueError):
                measured_compare.MeasuredComparisonReport.from_json(
                    _refingerprint_report(impossible)
                )

        route = report.per_actual_route[0]
        with pytest.raises(ValueError):
            measured_compare.RouteAdequacyAggregate(
                route_id=route.route_id,
                scored_task_count=route.scored_task_count,
                accepted_task_count=route.accepted_task_count,
                rejected_task_count=route.rejected_task_count + 1,
                adequacy=route.adequacy,
            )

        with pytest.raises(ValueError):
            _construct_report(
                report,
                accepted_task_count=14,
            )


def _check_report_environment_parser_attacks() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set, batch, store, environment = _report_fixture(directory)
        report = _build_report(batch, store, label_set)
        raw = json.loads(report.to_json())
        raw["environment"]["runner_id"] = (
            "owner-local-e1-2a-arbitrary-note-andrei649"
        )
        _refingerprint_environment(raw)
        with pytest.raises(ValueError, match="environment"):
            measured_compare.MeasuredComparisonReport.from_json(
                _refingerprint_report(raw)
            )

        for raw_field in ("platform", "python_version"):
            changed = json.loads(report.to_json())
            changed["environment"][raw_field] = "raw-environment-sentinel"
            _refingerprint_environment(changed)
            with pytest.raises(ValueError, match="environment"):
                measured_compare.MeasuredComparisonReport.from_json(
                    _refingerprint_report(changed)
                )

        markdown = measured_compare.render_measured_report(report)
        for value in (
            environment.platform,
            environment.python_version,
        ):
            assert value not in markdown


def _check_environment_digest_privacy() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        platform_sentinel = "windows-beats_current_andrei649"
        python_sentinel = "3.12.0"
        environment = _detected_environment(
            system="Windows",
            machine="beats_current_andrei649",
            python_version=python_sentinel,
        )
        assert environment.platform == platform_sentinel
        label_set, batch, store, _ = _report_fixture(
            directory,
            environment=environment,
            nonce="digestprivacy",
        )
        report = _build_report(batch, store, label_set)
        for output in (report.to_json(), measured_compare.render_measured_report(report)):
            assert platform_sentinel not in output
            assert python_sentinel not in output
            assert "beats_current" not in output
            assert "andrei649" not in output
        assert report.environment.platform_digest == hashlib.sha256(
            platform_sentinel.encode("utf-8")
        ).hexdigest()
        assert report.environment.python_version_digest == hashlib.sha256(
            python_sentinel.encode("utf-8")
        ).hexdigest()
        assert report.environment.content_fingerprint != report.environment_fingerprint
        _validate_report(report, batch, store, label_set)

    unusual = _detected_environment(
        system="Linux",
        machine="",
        python_version="3.12.0rc1",
    )
    assert unusual.platform == "linux-"
    evidence = measured_compare.EnvironmentEvidence.from_profile(unusual)
    encoded = json.dumps(evidence.to_dict())
    assert "linux-" not in encoded
    assert "3.12.0rc1" not in encoded
    assert evidence.platform_digest == hashlib.sha256(b"linux-").hexdigest()
    assert evidence.python_version_digest == hashlib.sha256(
        b"3.12.0rc1"
    ).hexdigest()


def _check_report_parser_strictness() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set, batch, store, _ = _report_fixture(directory)
        report = _build_report(batch, store, label_set)
        raw = json.loads(report.to_json())

        for flag in (
            "can_change_routing",
            "can_authorize",
            "can_execute",
            "can_promote",
            "can_mark_complete",
        ):
            for numeric_false in (0, 0.0, 1):
                changed = deepcopy(raw)
                changed[flag] = numeric_false
                with pytest.raises(ValueError, match="Boolean"):
                    measured_compare.MeasuredComparisonReport.from_json(
                        _refingerprint_report(changed)
                    )
        for numeric_true in (0, 0.0, 1, 1.0):
            changed = deepcopy(raw)
            changed["complete"] = numeric_true
            with pytest.raises(ValueError, match="Boolean"):
                measured_compare.MeasuredComparisonReport.from_json(
                    _refingerprint_report(changed)
                )

        for path, mutation in (
            (("environment",), lambda value: value.update({"unknown": True})),
            (("environment",), lambda value: value.pop("platform_digest")),
            (("latency_median",), lambda value: value.update({"unknown": True})),
            (("latency_median",), lambda value: value.pop("unit")),
            (("per_actual_route", 0), lambda value: value.update({"unknown": True})),
            (("per_actual_route", 0), lambda value: value.pop("route_id")),
        ):
            changed = deepcopy(raw)
            nested = changed
            for component in path:
                nested = nested[component]
            mutation(nested)
            with pytest.raises(ValueError):
                measured_compare.MeasuredComparisonReport.from_json(
                    json.dumps(changed)
                )

        divergent = deepcopy(raw)
        divergent["source_revision"] = "b" * 40
        structural = measured_compare.MeasuredComparisonReport.from_json(
            _refingerprint_report(divergent)
        )
        with pytest.raises(ValueError, match="retained evidence"):
            _validate_report(structural, batch, store, label_set)

        for flag in (
            "can_change_routing",
            "can_authorize",
            "can_execute",
            "can_promote",
            "can_mark_complete",
        ):
            with pytest.raises(TypeError):
                _construct_report(report, **{flag: True})
            with pytest.raises((TypeError, ValueError)):
                replace(report, **{flag: True})
        assert report.limitations == measured_compare.LIMITATION_CODES
        assert report.owner_gates == measured_compare.OWNER_GATE_CODES


def _with_declared_baseline(run):
    return replace(
        run,
        baseline_id="comparison-baseline",
        results=tuple(
            replace(
                result,
                baseline=result.candidate,
                baseline_quality=result.quality,
            )
            for result in run.results
        ),
    )


def _check_retained_evidence_tamper_matrix() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set, batch, store, _ = _report_fixture(directory)
        suite = build_owner_route_suite(label_set)

        wrong_root = directory / "wrong-store"
        wrong_root.mkdir()
        with pytest.raises(ValueError, match="store"):
            _build_report(batch, BenchmarkStore(wrong_root), label_set)
        with pytest.raises(ValueError, match="stored suite"):
            _build_report(
                _guarded_batch(batch, suite_version=batch.suite_version + 1),
                store,
                label_set,
            )
        for changed_suite in (
            tuple(reversed(suite)),
            (replace(suite[0], task_type="forecast"), *suite[1:]),
            (
                replace(
                    suite[0],
                    artifact_refs=(
                        suite[0].artifact_refs[0],
                        suite[0].artifact_refs[1],
                        f"registry-fingerprint:{'0' * 64}",
                    ),
                ),
                *suite[1:],
            ),
        ):
            with (
                patch.object(
                    BenchmarkStore,
                    "load_suite",
                    return_value=changed_suite,
                ),
                pytest.raises(ValueError, match="stored suite"),
            ):
                _build_report(batch, store, label_set)

        original_runs = _ordered_runs(store, batch.suite_name)
        path = _runs_path(store, batch.suite_name)
        original_text = path.read_text(encoding="utf-8")
        try:
            path.write_text(
                original_text + original_runs[0].to_json() + "\n",
                encoding="utf-8",
            )
            with pytest.raises(ValueError, match="fingerprint"):
                _build_report(batch, store, label_set)
        finally:
            path.write_text(original_text, encoding="utf-8")

        with pytest.raises(ValueError, match="unique"):
            _guarded_batch(
                batch,
                run_fingerprints=(
                    batch.run_fingerprints[0],
                    batch.run_fingerprints[0],
                    *batch.run_fingerprints[2:],
                ),
            )
        with pytest.raises(ValueError, match="fingerprint"):
            _build_report(
                _guarded_batch(
                    batch,
                    run_fingerprints=("f" * 64, *batch.run_fingerprints[1:]),
                ),
                store,
                label_set,
            )
        with pytest.raises(ValueError, match="ordered repetitions"):
            _build_report(
                _guarded_batch(
                    batch,
                    run_fingerprints=tuple(reversed(batch.run_fingerprints)),
                ),
                store,
                label_set,
            )
        try:
            _write_runs(store, batch.suite_name, original_runs[1:])
            with pytest.raises(ValueError, match="fingerprint"):
                _build_report(batch, store, label_set)
        finally:
            _write_runs(store, batch.suite_name, original_runs)

        mutations = (
            lambda run: replace(run, source_revision="b" * 40),
            lambda run: replace(run, candidate_id="other-candidate"),
            _with_declared_baseline,
            lambda run: replace(run, lane="ci"),
            lambda run: replace(run, suite_name="other-suite"),
            lambda run: replace(run, suite_version=run.suite_version + 1),
            lambda run: replace(
                run,
                artifact_refs=(
                    run.artifact_refs[0],
                    run.artifact_refs[1],
                    f"environment-fingerprint:{'e' * 64}",
                ),
            ),
            lambda run: replace(
                run,
                artifact_refs=(
                    f"label-fingerprint:{'d' * 64}",
                    run.artifact_refs[1],
                    run.artifact_refs[2],
                ),
            ),
            lambda run: replace(
                run,
                artifact_refs=(
                    run.artifact_refs[0],
                    f"registry-fingerprint:{'0' * 64}",
                    run.artifact_refs[2],
                ),
            ),
            lambda run: replace(run, results=tuple(reversed(run.results))),
            lambda run: replace(run, results=run.results[:-1]),
            lambda run: _replace_result(
                run,
                0,
                case_fingerprint="c" * 64,
            ),
            lambda run: _replace_result(
                run,
                0,
                privacy_class="synthetic_public",
            ),
            lambda run: _replace_result(run, 0, task_type="forecast"),
            lambda run: _replace_result(
                run,
                0,
                candidate=replace(
                    run.results[0].candidate,
                    hardware_profile="measured-hardware",
                ),
            ),
            lambda run: _replace_result(
                run,
                0,
                candidate=replace(run.results[0].candidate, artifact_refs=()),
            ),
            lambda run: _replace_result(
                run,
                0,
                candidate=replace(
                    run.results[0].candidate,
                    artifact_refs=("decision:not-a-digest",),
                ),
            ),
            lambda run: _replace_result(
                run,
                0,
                candidate=replace(
                    run.results[0].candidate,
                    artifact_refs=(
                        run.results[0].candidate.artifact_refs[0],
                        run.results[0].candidate.artifact_refs[0],
                    ),
                ),
            ),
            lambda run: _replace_result(
                run,
                0,
                candidate=replace(
                    run.results[0].candidate,
                    artifact_refs=(
                        run.results[0].candidate.artifact_refs[0],
                        f"registry-fingerprint:{'0' * 64}",
                    ),
                ),
            ),
        )
        for mutation in mutations:
            _assert_run_mutation_rejected(batch, store, label_set, mutation)

        def duplicate_result(raw):
            raw["results"].append(raw["results"][0])

        _assert_raw_run_mutation_rejected(store, batch, duplicate_result)

        other_directory = directory / "other-evidence"
        other_directory.mkdir()
        other_document = deepcopy(_document())
        other_document["cases"][0]["task_category"] = "forecast"
        other_labels, other_batch, other_store, _ = _report_fixture(
            other_directory,
            document=other_document,
            nonce="otherevidence",
        )
        _build_report(other_batch, other_store, other_labels)
        with pytest.raises(ValueError):
            _build_report(other_batch, other_store, label_set)


def _provider_result_mutation(**candidate_changes):
    def mutate(run):
        candidate = replace(run.results[0].candidate, **candidate_changes)
        return _replace_result(run, 0, candidate=candidate)

    return mutate


def _cost_result_mutation(measurement: Measurement):
    return lambda run: _replace_result(run, 0, cost=measurement)


def _incomplete_mixed_run(run):
    results = list(run.results)
    results[0] = replace(
        results[0],
        status="error",
        passed=None,
        candidate=None,
        baseline=None,
        quality=Measurement("failed", source="candidate.runner"),
        baseline_quality=Measurement("not_measured"),
        latency=Measurement("failed", source="candidate.runner"),
        cost=Measurement("not_measured"),
        reliability=Measurement("measured", 0.0, "ratio", "candidate.runner"),
        privacy=Measurement("failed", source="candidate.runner"),
        error_type="RuntimeError",
    )
    results[1] = replace(
        results[1],
        status="unscored",
        passed=None,
        quality=Measurement("not_measured"),
    )
    results[2] = replace(results[2], cost=Measurement("not_measured"))
    return replace(run, results=tuple(results))


def _assert_privacy_minimised(
    report,
    label_set,
    store,
) -> None:
    rendered = (report.to_json(), measured_compare.render_measured_report(report))
    sentinels = {
        *(case.text for case in label_set.cases),
        *(case.source_record_digest for case in label_set.cases),
        *(case.case_id for case in label_set.cases),
        *(case.task_category for case in label_set.cases),
        label_set.sampling_rule,
        label_set.retention_policy_id,
        label_set.source_window_start,
        label_set.source_window_end,
        _ARBITRARY_NOTE_SENTINEL,
        _RETAINED_EXCEPTION_MESSAGE,
        str(store.root),
        os.environ.get("USERNAME", "__no_local_username__"),
    }
    for output in rendered:
        lowered = output.lower()
        for sentinel in sentinels:
            assert not sentinel or sentinel.lower() not in lowered


def _check_measurement_provider_privacy_matrix() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        privacy_document = _privacy_document()
        privacy_router = _PatternMeasuredRouter()
        label_set, batch, store, _ = _report_fixture(
            directory,
            document=privacy_document,
            router=privacy_router,
        )
        assert privacy_router.classify_calls == 20 * 6
        suite_text = (
            store.root
            / "suites"
            / batch.suite_name
            / f"v{batch.suite_version}.jsonl"
        ).read_text(encoding="utf-8")
        for sentinel in (
            _ARBITRARY_NOTE_SENTINEL,
            _RETAINED_EXCEPTION_MESSAGE,
        ):
            assert any(sentinel in case.text for case in label_set.cases)
            assert sentinel in suite_text
        complete = _build_report(batch, store, label_set)
        _assert_privacy_minimised(complete, label_set, store)

        wrong_source = _build_with_run_mutation(
            batch,
            store,
            label_set,
            lambda run: _replace_result(
                run,
                0,
                latency=Measurement(
                    "measured",
                    run.results[0].latency.value,
                    "ms",
                    "candidate.runner",
                ),
            ),
        )
        assert wrong_source.accepted_task_count == 15
        assert wrong_source.rejected_task_count == 5
        assert wrong_source.incomplete_task_count == 0
        assert wrong_source.incomplete_observation_count == 1
        assert wrong_source.latency_median.value == 51.0
        assert wrong_source.latency_p95.value == 96.0
        assert wrong_source.complete is False

        for raw_latency in (
            {"source": None, "status": "not_measured", "unit": None, "value": None},
            {
                "source": "benchmark.harness",
                "status": "measured",
                "unit": "seconds",
                "value": 1.0,
            },
        ):
            _assert_raw_run_mutation_rejected(
                store,
                batch,
                lambda raw, value=raw_latency: raw["results"][0].update(
                    {"latency": value}
                ),
            )

        for mutation in (
            _provider_result_mutation(model_id="other-model"),
            _provider_result_mutation(provider_id="other-provider"),
            _cost_result_mutation(
                Measurement("measured", 1.0, "usd", "candidate.runner")
            ),
        ):
            changed = _build_with_run_mutation(
                batch,
                store,
                label_set,
                mutation,
            )
            assert changed.provider_charge == Measurement("not_measured")
            assert changed.complete is False

        for measurement in (
            Measurement("not_measured"),
            Measurement("measured", 0.0, "usd", "other.source"),
        ):
            changed = _build_with_run_mutation(
                batch,
                store,
                label_set,
                _cost_result_mutation(measurement),
            )
            assert changed.incomplete_task_count == 0
            assert changed.incomplete_observation_count == 1
            assert changed.provider_charge == Measurement("not_measured")
            assert changed.complete is False

        for raw_cost in (
            {
                "source": "candidate.runner",
                "status": "failed",
                "unit": None,
                "value": None,
            },
            {
                "source": "candidate.runner",
                "status": "measured",
                "unit": "tokens",
                "value": 0.0,
            },
            {"source": None, "status": "measured", "unit": "usd", "value": 0.0},
        ):
            _assert_raw_run_mutation_rejected(
                store,
                batch,
                lambda raw, value=raw_cost: raw["results"][0].update(
                    {"cost": value}
                ),
            )

        incomplete = _build_with_run_mutation(
            batch,
            store,
            label_set,
            _incomplete_mixed_run,
        )
        assert (
            incomplete.accepted_task_count,
            incomplete.rejected_task_count,
            incomplete.incomplete_task_count,
            incomplete.nondeterministic_task_count,
            incomplete.error_observation_count,
            incomplete.incomplete_observation_count,
        ) == (13, 5, 2, 0, 1, 3)
        assert incomplete.latency_median.value == 51.0
        assert incomplete.latency_p95.value == 96.0
        assert incomplete.provider_charge == Measurement("not_measured")
        assert incomplete.complete is False
        structural = measured_compare.MeasuredComparisonReport.from_json(
            incomplete.to_json()
        )
        assert structural == incomplete
        assert "complete: false" in measured_compare.render_measured_report(incomplete)
        _assert_privacy_minimised(incomplete, label_set, store)

        error_directory = directory / "actual-exception-evidence"
        error_directory.mkdir()
        error_router = _FailAfterWarmupRouter()
        error_labels, error_batch, error_store, _ = _report_fixture(
            error_directory,
            document=privacy_document,
            router=error_router,
            nonce="exceptionprivacy",
        )
        assert error_router.classify_calls == 20 * 6
        error_report = _build_report(error_batch, error_store, error_labels)
        _assert_privacy_minimised(
            error_report,
            error_labels,
            error_store,
        )


def _check_measured_report() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set, batch, store, environment = _report_fixture(directory)
        report = _build_report(batch, store, label_set)

        assert isinstance(report, measured_compare.MeasuredComparisonReport)
        assert report.schema == measured_compare.REPORT_SCHEMA
        assert report.label_set_id == label_set.label_set_id
        assert report.label_set_fingerprint == label_set.content_fingerprint
        assert report.route_registry_fingerprint == _registry(label_set).fingerprint
        assert report.suite_name == batch.suite_name
        assert report.suite_version == batch.suite_version
        assert report.source_revision == _REVISION
        assert report.candidate_id == measured_compare.CANDIDATE_ID
        assert report.baseline_id is None
        assert report.environment == measured_compare.EnvironmentEvidence.from_profile(
            environment
        )
        assert report.environment_fingerprint == batch.environment_fingerprint
        assert report.environment.content_fingerprint != report.environment_fingerprint
        assert report.environment.platform_digest == hashlib.sha256(
            environment.platform.encode("utf-8")
        ).hexdigest()
        assert report.environment.python_version_digest == hashlib.sha256(
            environment.python_version.encode("utf-8")
        ).hexdigest()
        assert report.run_fingerprints == batch.run_fingerprints
        assert report.repetition_count == 5
        assert report.unique_task_count == 20
        assert report.observation_count == 100
        assert report.accepted_task_count == 15
        assert report.rejected_task_count == 5
        assert report.incomplete_task_count == 0
        assert report.nondeterministic_task_count == 0
        assert report.incomplete_observation_count == 0
        assert report.error_observation_count == 0
        assert report.overall_adequacy == Measurement(
            "measured", 0.75, "ratio", "benchmark.harness"
        )
        assert tuple(route.route_id for route in report.per_actual_route) == (
            "friday",
            "jarvis",
        )
        assert tuple(
            (
                route.scored_task_count,
                route.accepted_task_count,
                route.rejected_task_count,
                route.adequacy.value,
            )
            for route in report.per_actual_route
        ) == ((15, 15, 0, 1.0), (5, 0, 5, 0.0))
        assert report.latency_median == Measurement(
            "measured", 50.5, "ms", "benchmark.harness"
        )
        assert report.latency_p95 == Measurement(
            "measured", 95.0, "ms", "benchmark.harness"
        )
        assert report.provider_charge == Measurement(
            "measured", 0.0, "usd", "candidate.runner"
        )
        for measurement in (
            report.compute,
            report.energy,
            report.hardware,
            report.downstream_agent,
            report.tool,
            report.action,
            report.executed_task_outcome,
        ):
            assert measurement == Measurement("not_measured")
        assert "filesystem_confidentiality_caller_managed" in report.limitations
        assert len(report.owner_gates) == 5
        assert report.complete is True
        assert report.authority == "evaluation_only"
        assert not any(
            (
                report.can_change_routing,
                report.can_authorize,
                report.can_execute,
                report.can_promote,
                report.can_mark_complete,
            )
        )

        _validate_report(report, batch, store, label_set)
        encoded = report.to_json()
        assert environment.platform not in encoded
        assert environment.python_version not in encoded
        assert encoded == json.dumps(
            json.loads(encoded),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        structural = measured_compare.MeasuredComparisonReport.from_json(encoded)
        assert structural == report
        _validate_report(structural, batch, store, label_set)

        markdown = measured_compare.render_measured_report(report)
        assert "owner evidence: blocked" in markdown.lower()
        assert "real task-outcome quality: not_measured" in markdown.lower()
        assert "filesystem_confidentiality_caller_managed" in markdown
        assert report.route_registry_fingerprint in markdown
        for caller_managed_boundary in (
            "windows dacl",
            "posix owner/mode",
            "encryption at rest",
            "exclusive local-volume",
            "backup/sync/index exclusion",
            "other-local-user exclusion",
            "secure deletion",
        ):
            assert caller_managed_boundary in markdown.lower()
        forbidden = (
            "synthetic weather request",
            label_set.cases[0].source_record_digest,
            str(store.root),
            os.environ.get("USERNAME", "__no_local_username__"),
            "beats_current",
            "selector-superiority",
            "answer-quality",
            "end-to-end-completion",
            "safety claim",
        )
        for value in forbidden:
            assert not value or value.lower() not in encoded.lower()
            assert not value or value.lower() not in markdown.lower()


def _check_unique_task_consensus() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set, batch, store, _ = _report_fixture(
            directory,
            router=_MeasuredRouter("friday"),
            nonce="taskconsensus",
        )

        complete = _build_report(batch, store, label_set)
        assert (
            complete.unique_task_count,
            complete.observation_count,
            complete.accepted_task_count,
            complete.rejected_task_count,
            complete.incomplete_task_count,
            complete.nondeterministic_task_count,
            complete.incomplete_observation_count,
            complete.error_observation_count,
        ) == (20, 100, 20, 0, 0, 0, 0, 0)

        def one_of_one_hundred_disagrees(run):
            original = run.results[0]
            assert original.candidate is not None
            return _replace_result(
                run,
                0,
                status="failed",
                passed=False,
                candidate=replace(original.candidate, route_id="jarvis"),
                quality=replace(original.quality, value=0.0),
            )

        disagreement = _build_with_run_mutation(
            batch,
            store,
            label_set,
            one_of_one_hundred_disagrees,
        )
        assert (
            disagreement.unique_task_count,
            disagreement.observation_count,
            disagreement.accepted_task_count,
            disagreement.rejected_task_count,
            disagreement.incomplete_task_count,
            disagreement.nondeterministic_task_count,
            disagreement.incomplete_observation_count,
            disagreement.error_observation_count,
        ) == (20, 100, 19, 0, 1, 1, 0, 0)
        assert disagreement.complete is False
        assert disagreement.overall_adequacy == Measurement(
            "measured", 1.0, "ratio", "benchmark.harness"
        )
        assert tuple(item.route_id for item in disagreement.per_actual_route) == (
            "friday",
        )
        assert disagreement.per_actual_route[0].scored_task_count == 19
        encoded = disagreement.to_json()
        assert '"accepted_task_count":19' in encoded
        assert '"accepted_count":99' not in encoded
        assert '"complete":false' in encoded

        both_routes_document = _document()
        both_routes_document["cases"][0]["acceptable_primary_routes"] = [
            "friday",
            "jarvis",
        ]
        both_routes_directory = directory / "two-acceptable-routes"
        both_routes_directory.mkdir()
        both_labels, both_batch, both_store, _ = _report_fixture(
            both_routes_directory,
            document=both_routes_document,
            router=_MeasuredRouter("friday"),
            nonce="twoacceptable",
        )

        def second_acceptable_route(run):
            original = run.results[0]
            assert original.candidate is not None
            return _replace_result(
                run,
                0,
                candidate=replace(original.candidate, route_id="jarvis"),
            )

        route_only_disagreement = _build_with_run_mutation(
            both_batch,
            both_store,
            both_labels,
            second_acceptable_route,
        )
        assert (
            route_only_disagreement.accepted_task_count,
            route_only_disagreement.rejected_task_count,
            route_only_disagreement.incomplete_task_count,
            route_only_disagreement.nondeterministic_task_count,
            route_only_disagreement.incomplete_observation_count,
        ) == (19, 0, 1, 1, 0)
        assert route_only_disagreement.complete is False
        assert tuple(
            item.route_id for item in route_only_disagreement.per_actual_route
        ) == ("friday",)
        assert route_only_disagreement.per_actual_route[0].scored_task_count == 19

        unscored = _build_with_run_mutation(
            batch,
            store,
            label_set,
            _with_unscored_result,
        )
        assert (
            unscored.accepted_task_count,
            unscored.incomplete_task_count,
            unscored.nondeterministic_task_count,
            unscored.incomplete_observation_count,
            unscored.error_observation_count,
        ) == (19, 1, 0, 1, 0)
        assert unscored.complete is False

        error = _build_with_run_mutation(
            batch,
            store,
            label_set,
            _incomplete_mixed_run,
        )
        assert (
            error.accepted_task_count,
            error.incomplete_task_count,
            error.nondeterministic_task_count,
            error.incomplete_observation_count,
            error.error_observation_count,
        ) == (18, 2, 0, 3, 1)
        assert error.complete is False


def _check_measured_report_adversarial() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set, batch, store, _environment = _report_fixture(directory)
        report = _build_report(batch, store, label_set)
        raw = json.loads(report.to_json())

        lookalike_registry = _bind(
            {"jarvis": object(), "friday": object()}
        )
        assert lookalike_registry.fingerprint == _registry(label_set).fingerprint
        with pytest.raises(ValueError, match="binding|capability|registry"):
            measured_compare.build_measured_report(
                batch,
                store,
                label_set,
                registry=lookalike_registry,
            )
        with pytest.raises(ValueError, match="binding|capability|registry"):
            measured_compare.validate_measured_report_against_evidence(
                report,
                batch,
                store,
                label_set,
                registry=lookalike_registry,
            )
        with pytest.raises(ValueError, match="registry"):
            _build_report(
                _guarded_batch(batch, route_registry_fingerprint="0" * 64),
                store,
                label_set,
            )

        for mutation in (
            lambda value: value.update({"unknown": True}),
            lambda value: value.pop("observation_count"),
            lambda value: value.update({"observation_count": 99}),
            lambda value: value.update({"complete": False}),
            lambda value: value.update({"authority": "production"}),
            lambda value: value.update({"can_execute": True}),
            lambda value: value.update({"content_fingerprint": "0" * 64}),
            lambda value: value.update({"route_registry_fingerprint": "0" * 64}),
            lambda value: value["limitations"].remove(
                "filesystem_confidentiality_caller_managed"
            ),
            lambda value: value["latency_p95"].update({"value": -1.0}),
            lambda value: value["overall_adequacy"].update({"value": 1.1}),
        ):
            changed = deepcopy(raw)
            mutation(changed)
            with pytest.raises((TypeError, ValueError)):
                measured_compare.MeasuredComparisonReport.from_json(
                    json.dumps(changed)
                )

        invalid_source_type = deepcopy(raw)
        invalid_source_type["source_revision"] = 1
        with pytest.raises(ValueError, match="source revision"):
            measured_compare.MeasuredComparisonReport.from_json(
                json.dumps(invalid_source_type)
            )

        rebound_registry = deepcopy(raw)
        rebound_registry["route_registry_fingerprint"] = "0" * 64
        structurally_valid_rebound = (
            measured_compare.MeasuredComparisonReport.from_json(
                _refingerprint_report(rebound_registry)
            )
        )
        assert structurally_valid_rebound.route_registry_fingerprint == "0" * 64
        with pytest.raises(ValueError, match="report|evidence|registry"):
            _validate_report(
                structurally_valid_rebound,
                batch,
                store,
                label_set,
            )

        duplicate = report.to_json()[:-1] + f',"schema":"{report.schema}"}}'
        with pytest.raises(ValueError, match="duplicate"):
            measured_compare.MeasuredComparisonReport.from_json(duplicate)
        non_finite = report.to_json().replace('"value":95.0', '"value":NaN')
        with pytest.raises(ValueError):
            measured_compare.MeasuredComparisonReport.from_json(non_finite)

        for flag in (
            "can_change_routing",
            "can_authorize",
            "can_execute",
            "can_promote",
            "can_mark_complete",
        ):
            with pytest.raises((TypeError, ValueError)):
                replace(report, **{flag: True})

        other_document = _document()
        other_document["cases"][0]["task_category"] = "forecast"
        other_labels = _load(_write(directory, other_document, "other-labels.json"))
        with pytest.raises(ValueError):
            _build_report(batch, store, other_labels)
        with pytest.raises(ValueError):
            _validate_report(report, batch, store, other_labels)

        runs_path = store.root / "suites" / batch.suite_name / "runs.jsonl"
        retained_lines = runs_path.read_text(encoding="utf-8").splitlines()
        runs_path.write_text("\n".join(retained_lines[:-1]) + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="fingerprint"):
            _build_report(batch, store, label_set)

    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set, error_batch, error_store, _ = _report_fixture(
            directory,
            router=_FailAfterWarmupRouter(),
            nonce="reporterrors",
        )
        error_report = _build_report(error_batch, error_store, label_set)
        assert error_report.accepted_task_count == 0
        assert error_report.rejected_task_count == 0
        assert error_report.incomplete_task_count == 20
        assert error_report.nondeterministic_task_count == 0
        assert error_report.error_observation_count == 100
        assert error_report.incomplete_observation_count == 100
        assert error_report.provider_charge == Measurement("not_measured")
        assert error_report.complete is False

    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set = _load(_write(directory, _document()))
        store_root = directory / "unscored-report-store"
        store_root.mkdir()
        original_harness_run = BenchmarkHarness.run
        calls = 0

        async def _unscored_retained(self: BenchmarkHarness, *args, **kwargs):
            nonlocal calls
            calls += 1
            run = await original_harness_run(self, *args, **kwargs)
            return run if calls == 1 else _with_unscored_result(run)

        with patch.object(BenchmarkHarness, "run", _unscored_retained):
            batch = asyncio.run(
                measured_compare.run_measured_comparison(
                    router=_MeasuredRouter(),
                    registry=_registry(label_set),
                    label_set=label_set,
                    store_root=store_root,
                    source_revision=_REVISION,
                    run_nonce=lambda: "reportunscored",
                )
            )
        unscored_report = _build_report(
            batch, BenchmarkStore(store_root), label_set
        )
        assert unscored_report.accepted_task_count == 19
        assert unscored_report.rejected_task_count == 0
        assert unscored_report.incomplete_task_count == 1
        assert unscored_report.nondeterministic_task_count == 0
        assert unscored_report.error_observation_count == 0
        assert unscored_report.incomplete_observation_count == 5
        assert unscored_report.complete is False

    def _provider_adapter(router, agents, *, host_id="in-process"):
        async def run(prompt: str):
            intent = await router.classify(prompt, dict(agents))
            return BenchmarkObservation(
                response=intent.primary,
                route_id=intent.primary,
                model_id="provider-model",
                provider_id="provider-backed",
                host_id=host_id,
                hardware_profile="not-measured",
                cost_usd=0.0,
                reliability=1.0,
                privacy_effect="local_only",
            )

        return run

    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        with patch.object(
            measured_compare,
            "current_router_runner",
            _provider_adapter,
        ):
            label_set, batch, store, _ = _report_fixture(
                directory,
                nonce="providerreport",
            )
        provider_report = _build_report(batch, store, label_set)
        assert provider_report.provider_charge == Measurement("not_measured")
        assert provider_report.complete is False


def _markdown_section(document: str, heading: str) -> str:
    """Return one level-two Markdown section without accepting nearby claims."""

    match = re.search(
        rf"^## {re.escape(heading)}\n(?P<body>.*?)(?=^## |\Z)",
        document,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing section {heading!r}"
    return match.group("body")


def _unchecked_task_section(document: str, task_id: str) -> str:
    """Return one unchecked owner task through its next peer task or heading."""

    match = re.search(
        rf"^- \[ \] \*\*{re.escape(task_id)}[^\n]*\*\*.*?(?=^- \[[ x]\] \*\*|^## |\Z)",
        document,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing unchecked task {task_id!r}"
    return match.group(0)


def _section_contains(section: str, statement: str) -> bool:
    """Compare Markdown prose without making semantic assertions wrap-sensitive."""

    return " ".join(statement.split()) in " ".join(section.split())


def _markdown_table_row(section: str, label: str) -> tuple[str, ...]:
    """Return one named Markdown table row from an already isolated section."""

    matches = []
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
        if cells and cells[0] == label:
            matches.append(cells)
    assert len(matches) == 1, f"expected one table row for {label!r}"
    return matches[0]


def _check_operator_contract_ledgers() -> None:
    """Keep E1.2a operator claims aligned with the checked-in contract."""

    repository = Path(__file__).resolve().parent.parent
    operator_contract = repository / "docs/nerva2/CORTEX_E1_2.md"
    assert operator_contract.is_file()
    contract = operator_contract.read_text(encoding="utf-8")

    state = _markdown_section(contract, "State and boundary")
    for value in (
        "IMPLEMENTED CONTRACT · MERGED",
        "CONTRACT READY",
        "merged onto `main`",
        "PR #842",
        "769b633",
        "contract_ready",
        "owner_evidence_blocked",
        "real_task_outcome_quality=not_measured",
        "neither program completion nor release readiness",
    ):
        assert _section_contains(state, value)
    assert "integration_pending" not in state
    assert "design_hold" not in state

    schema = _markdown_section(contract, "External owner label schema")
    for value in (
        "nerva.cortex.route-label-set.v1",
        "label_set_id",
        "sampling_rule",
        "source_window",
        "owner_attested",
        "retention_policy_id",
        "case_id",
        "acceptable_primary_routes",
        "source_record_digest",
    ):
        assert _section_contains(schema, value)

    invocation = _markdown_section(contract, "Local invocation, with explicit paths")
    assert _section_contains(invocation, "There is no committed E1.2a CLI.")
    assert _section_contains(invocation, "BenchmarkStore")
    assert _section_contains(invocation, "store_root = Path")
    assert _section_contains(invocation, "warm-up")
    assert _section_contains(invocation, "five retained runs")
    invocation_code = re.search(
        r"```python\n(?P<code>.*?)\n```",
        invocation,
        flags=re.DOTALL,
    )
    assert invocation_code is not None
    assert ".resolve()" not in invocation_code.group("code")

    retained_data = _markdown_section(contract, "Stored data and owner policy")
    for value in (
        "Label file",
        "E9 suite",
        "Retained runs",
        "vN.jsonl",
        "runs.jsonl",
        "JSON report",
        "Markdown report",
        "raw prompts",
        "pseudonymous and linkable",
        "filesystem_confidentiality_caller_managed",
        "retention_policy_id is declarative",
        "windows dacl",
        "posix owner/mode",
        "encryption at rest",
        "exclusive local-volume",
        "backup/sync/index exclusion",
        "other-local-user exclusion",
        "secure deletion",
    ):
        assert _section_contains(retained_data, value)
    for unsupported_claim in (
        "the store is access-controlled",
        "access-controlled by retention_policy_id",
        "retention_policy_id enforces",
    ):
        assert unsupported_claim not in retained_data.lower()

    measurements = _markdown_section(contract, "What is and is not measured")
    for value in (
        "accepted / (accepted + rejected)",
        "valid scored negative evidence",
        "may remain measured",
        "complete=false",
        "missing required measurement",
        "unavailable deterministic provider-charge proof",
        "real_task_outcome_quality=not_measured",
    ):
        assert _section_contains(measurements, value)
    provider_charge = _markdown_table_row(measurements, "Provider charge")
    assert provider_charge[1] == "conditionally measured `$0`"
    for value in (
        "every retained result",
        "baseline is `none`",
        "candidate exists",
        "model `none`",
        "provider `local-deterministic`",
        "cost is measured `0.0 usd`",
        "source `candidate.runner`",
    ):
        assert _section_contains(provider_charge[2], value)
    unmeasured = _markdown_table_row(
        measurements,
        "Compute, energy, hardware, downstream agent, tool, action, executed-task outcome",
    )
    assert unmeasured[1] == "unconditionally `not_measured`"
    assert "| Provider charge, compute, energy" not in measurements

    failure = _markdown_section(contract, "Failure and completeness")
    assert _section_contains(
        failure,
        "Scored adequacy remains visible in an incomplete report",
    )
    assert _section_contains(
        failure,
        "cannot establish completion, release, or representativeness",
    )
    assert "completion, release, or adequacy claim" not in failure

    report_contract = _markdown_section(contract, "Report v1 output contract")
    for value in (
        "nerva.cortex.measured-comparison.v1",
        "label ID/fingerprint",
        "suite name/version",
        "exact source revision",
        "fixed candidate/no baseline",
        "route-registry fingerprint",
        "five ordered retained-run fingerprints",
        "unique_task_count",
        "observation_count",
        "accepted_task_count",
        "rejected_task_count",
        "incomplete_task_count",
        "nondeterministic_task_count",
        "incomplete_observation_count",
        "error_observation_count",
        "raw E9 environment-profile fingerprint",
        "sanitised environment evidence fingerprint",
        "platform/Python digests",
        "scored adequacy",
        "sorted per-actual-route aggregates",
        "nearest-rank p95",
        "`benchmark.harness`/`ms`",
        "full local-deterministic/no-model/no-baseline/`candidate.runner` USD-zero conjunction",
        "compute/energy/hardware/downstream-agent/tool/action/executed-task-outcome",
        "evaluation_only",
        "all routing/authorization/execution/promotion/completion booleans false",
        "structural `from_json()` is not evidence acceptance",
        "exact batch/store/labels",
    ):
        assert _section_contains(report_contract, value)

    attestation = _markdown_section(contract, "Owner-attestation boundary")
    attestation_plain = attestation.replace("`", "")
    assert _section_contains(attestation_plain, "owner_attested=true is a typed declaration")
    assert _section_contains(attestation_plain, "not proof of consent or label correctness")
    assert _section_contains(attestation, "owner_evidence_blocked")

    owner_tasks = (repository / "docs/OWNER_TASKS.md").read_text(encoding="utf-8")
    assert owner_tasks.count("- [ ] **E1.2b") == 1
    e1_2b_task = _unchecked_task_section(owner_tasks, "E1.2b")
    for value in (
        "at least 20 historical tasks",
        "acceptable routes/categories",
        "sampling/exclusion rule",
        "retention/access/deletion policy",
        "permission for the local run",
        "owner_attested=true is a typed declaration",
        "not proof of consent or label correctness",
    ):
        assert _section_contains(e1_2b_task.replace("`", ""), value)

    for path in (
        "docs/nerva2/M1_DELIVERY.md",
        "BACKLOG.md",
        "docs/OWNER_TASKS.md",
    ):
        ledger = (repository / path).read_text(encoding="utf-8")
        assert _section_contains(ledger, "merged")
        assert "#842" in ledger
        assert "integration_pending" not in ledger
        assert "contract_ready" in ledger
        assert "owner_evidence_blocked" in ledger
        assert "real_task_outcome_quality=not_measured" in ledger

    manifest = json.loads(
        (repository / "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json").read_text(
            encoding="utf-8"
        )
    )
    e1 = next(stream for stream in manifest["streams"] if stream["id"] == "E1")
    assert e1["program_status"] == "building"
    assert e1["delivery_eligibility"] == "in_progress"
    assert {reference["value"] for reference in e1["references"]} >= {
        841,
        "docs/nerva2/CORTEX_E1_2.md",
    }
    assert manifest["authority"]["completion_authority"] is False
    assert manifest["authority"]["release_ready"] is False


class _LateInjectingNormalRouter(IntentRouter):
    """Fails closed only when E9 avoids the mutable normal classify path."""

    def __init__(self) -> None:
        super().__init__(config={})
        self.normal_prompts: list[str] = []
        self.classifier_prompts: list[str] = []

    async def classify(self, text: str, agents: dict[str, object]) -> Intent:
        self.normal_prompts.append(text)

        async def _fallback(prompt: str, _ranked: list[str]) -> list[str]:
            self.classifier_prompts.append(prompt)
            return ["vision"]

        self.llm_classifier = _fallback
        return await super().classify(text, agents)


def _marked_reparse_lstat(marked: Path):
    """Return an lstat shim that models a Windows junction at one exact path."""

    original = os.lstat

    def _lstat(path: str | bytes | os.PathLike[str] | os.PathLike[bytes]):
        metadata = original(path)
        candidate = Path(path)
        if (
            candidate.name == marked.name
            and candidate.parent.name == marked.parent.name
        ):
            return SimpleNamespace(
                st_mode=metadata.st_mode,
                st_file_attributes=getattr(
                    stat,
                    "FILE_ATTRIBUTE_REPARSE_POINT",
                    0x400,
                ),
            )
        return metadata

    return _lstat


def _broken_reparse_lstat(marked: Path, states: list[str] | None = None):
    """Model an absent final that lstat identifies as a broken reparse point."""

    original = os.lstat
    remaining = list(states or ["broken"])

    def _lstat(path: str | bytes | os.PathLike[str] | os.PathLike[bytes]):
        candidate = Path(path)
        if (
            candidate.name == marked.name
            and candidate.parent.name == marked.parent.name
        ):
            state = remaining.pop(0) if remaining else "broken"
            if state == "missing":
                raise FileNotFoundError(path)
            return SimpleNamespace(
                st_mode=stat.S_IFLNK | 0o777,
                st_file_attributes=getattr(
                    stat,
                    "FILE_ATTRIBUTE_REPARSE_POINT",
                    0x400,
                ),
            )
        return original(path)

    return _lstat


def _security_bound_capability_probes() -> None:
    prompt = "an unmatched owner-local prompt"
    agents = {"jarvis": object(), "vision": object()}
    failures: list[str] = []

    def probe(label: str, operation) -> None:
        try:
            operation()
        except BaseException as exc:
            failures.append(f"{label}: {type(exc).__name__}: {exc}")

    def runner_binding() -> None:
        router = IntentRouter(config={})
        runner = measured_compare.current_router_runner(router, agents)
        replacement_prompts: list[str] = []

        async def replacement(text: str, route_agents: dict[str, object]) -> Intent:
            replacement_prompts.append(text)
            return await router.classify(text, route_agents)

        router.classify_deterministic = replacement
        observation = asyncio.run(runner(prompt))
        assert observation.route_id == "jarvis"
        assert replacement_prompts == []

    def shadow_binding() -> None:
        router = IntentRouter(config={})
        records: list[DecisionRecord] = []
        shadow = ShadowDecisionRouter(router, records.append)
        replacement_prompts: list[str] = []

        async def replacement(text: str, route_agents: dict[str, object]) -> Intent:
            replacement_prompts.append(text)
            return await router.classify(text, route_agents)

        router.classify_deterministic = replacement
        intent = asyncio.run(shadow.classify_deterministic(prompt, agents))
        assert intent.primary == "jarvis"
        assert replacement_prompts == []
        assert len(records) == 1

        normal_prompts: list[str] = []

        async def normal_replacement(
            text: str, _route_agents: dict[str, object]
        ) -> Intent:
            normal_prompts.append(text)
            return Intent(["jarvis"], is_general=True, context={"source": "general"})

        router.classify = normal_replacement
        asyncio.run(shadow.classify("normal compatibility prompt", agents))
        assert normal_prompts == ["normal compatibility prompt"]

    def measured_runner_binding() -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            registry = _bind()
            labels = _load(_write(directory, _document()), registry=registry)
            router = _MeasuredRouter()
            runner = measured_current_router_runner(router, registry, labels)
            first = asyncio.run(runner(labels.cases[0].text))
            assert first.route_id == "friday"
            replacement_prompts: list[str] = []

            async def replacement(
                text: str,
                _route_agents: dict[str, object],
            ) -> Intent:
                replacement_prompts.append(text)
                return Intent(
                    ["friday"],
                    is_general=False,
                    context={"source": "keyword_match"},
                    confidence=1.0,
                )

            router.classify_deterministic = replacement
            second = asyncio.run(runner(labels.cases[1].text))
            assert second.route_id == "friday"
            assert replacement_prompts == []

    probe("current-router bound capability", runner_binding)
    probe("shadow-router bound capability", shadow_binding)
    probe("measured-router bound capability", measured_runner_binding)
    assert not failures, "deterministic capability binding failed: " + " | ".join(
        failures
    )


def _security_shadow_legacy_compatibility_probe() -> None:
    class LegacyRouter:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        async def classify(
            self, text: str, _agents: dict[str, object]
        ) -> Intent:
            self.prompts.append(text)
            return Intent(["jarvis"], is_general=True, context={"source": "general"})

    router = LegacyRouter()
    records: list[DecisionRecord] = []
    shadow = ShadowDecisionRouter(router, records.append)
    intent = asyncio.run(shadow.classify("legacy normal prompt", {"jarvis": object()}))
    assert intent.primary == "jarvis"
    assert router.prompts == ["legacy normal prompt"]
    assert len(records) == 1

    late_deterministic_prompts: list[str] = []

    async def late_deterministic(
        text: str, _agents: dict[str, object]
    ) -> Intent:
        late_deterministic_prompts.append(text)
        return Intent(["jarvis"], is_general=True, context={"source": "general"})

    router.classify_deterministic = late_deterministic
    with pytest.raises(TypeError, match="classify_deterministic"):
        asyncio.run(
            shadow.classify_deterministic(
                "legacy deterministic prompt", {"jarvis": object()}
            )
        )
    assert late_deterministic_prompts == []


def _security_broken_final_probes() -> None:
    failures: list[str] = []

    def probe(label: str, operation) -> None:
        try:
            operation()
        except BaseException as exc:
            failures.append(f"{label}: {type(exc).__name__}: {exc}")

    def report_final(filename: str) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            label_set, batch, store, _ = _report_fixture(directory)
            final_path = store.root / "suites" / batch.suite_name / filename
            final_path.unlink()
            sentinel = directory / "outside-sentinel.txt"
            sentinel.write_text("must-remain-unread-and-unchanged", encoding="utf-8")
            outside_output = directory / "outside-created.txt"
            outside_events: list[str] = []

            def forbidden_sink(_store: BenchmarkStore, *_args, **_kwargs):
                outside_events.append("outside-read")
                sentinel.read_text(encoding="utf-8")
                outside_output.write_text("forbidden", encoding="utf-8")
                return ()

            method = "load_suite" if filename.startswith("v") else "runs"
            with (
                patch.object(
                    measured_compare.os,
                    "lstat",
                    _broken_reparse_lstat(final_path),
                ),
                patch.object(BenchmarkStore, method, forbidden_sink),
                pytest.raises(ValueError, match="symlink|reparse"),
            ):
                _build_report(batch, store, label_set)
            assert outside_events == []
            assert sentinel.read_text(encoding="utf-8") == (
                "must-remain-unread-and-unchanged"
            )
            assert not outside_output.exists()

    def run_phase(
        states: list[str],
        forbidden_stage: str,
        expected_events: list[str],
    ) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            label_set = _load(_write(directory, _document()))
            store_root = directory / "store"
            store_root.mkdir()
            suite_name = measured_compare._suite_name(label_set)
            final_path = store_root / "suites" / suite_name / "runs.jsonl"
            sentinel = directory / "outside-sentinel.txt"
            sentinel.write_text("must-remain-unread-and-unchanged", encoding="utf-8")
            outside_output = directory / "outside-created.txt"
            events: list[str] = []
            reads = 0

            def outside_operation(label: str) -> None:
                events.append(label)
                sentinel.read_text(encoding="utf-8")
                outside_output.write_text("forbidden", encoding="utf-8")

            def runs(
                _store: BenchmarkStore, _name: str, *, last_n: int = 20
            ) -> tuple[object, ...]:
                nonlocal reads
                assert last_n == sys.maxsize
                reads += 1
                if (forbidden_stage == "collision" and reads == 1) or (
                    forbidden_stage == "readback" and reads > 1
                ):
                    outside_operation("outside-read")
                else:
                    events.append("collision-read")
                return ()

            def record_run(_store: BenchmarkStore, _run: object) -> None:
                if forbidden_stage == "write":
                    outside_operation("outside-write")
                else:
                    events.append("store-write")

            with (
                patch.object(
                    measured_compare.os,
                    "lstat",
                    _broken_reparse_lstat(final_path, states),
                ),
                patch.object(BenchmarkStore, "runs", runs),
                patch.object(BenchmarkStore, "record_run", record_run),
                pytest.raises(ValueError, match="symlink|reparse"),
            ):
                asyncio.run(
                    measured_compare.run_measured_comparison(
                        router=_MeasuredRouter(),
                        registry=_registry(label_set),
                        label_set=label_set,
                        store_root=store_root,
                        source_revision=_REVISION,
                        run_nonce=lambda: "brokenfinal",
                    )
                )
            assert events == expected_events
            assert sentinel.read_text(encoding="utf-8") == (
                "must-remain-unread-and-unchanged"
            )
            assert not outside_output.exists()

    probe("broken version report final", lambda: report_final("v1.jsonl"))
    probe("broken runs report final", lambda: report_final("runs.jsonl"))
    probe(
        "broken runs collision boundary",
        lambda: run_phase(["broken"], "collision", []),
    )
    probe(
        "broken runs write boundary",
        lambda: run_phase(["missing", "broken"], "write", ["collision-read"]),
    )
    probe(
        "broken runs readback boundary",
        lambda: run_phase(
            ["missing", "missing", "broken"],
            "readback",
            ["collision-read", "store-write"],
        ),
    )
    assert not failures, "broken measured-store finals failed: " + " | ".join(
        failures
    )


def _security_broken_create_directory_probes() -> None:
    failures: list[str] = []

    def probe(label: str, operation) -> None:
        try:
            operation()
        except BaseException as exc:
            failures.append(f"{label}: {type(exc).__name__}: {exc}")

    def broken_create_final(final_kind: str) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            label_set = _load(_write(directory, _document()))
            root = directory / "store"
            root.mkdir()
            suites = root / "suites"
            suite_name = measured_compare._suite_name(label_set)
            if final_kind == "selected-suite":
                suites.mkdir()
                marked = suites / suite_name
            else:
                marked = suites

            sentinel = directory / "outside-sentinel.txt"
            sentinel.write_text("must-remain-unchanged", encoding="utf-8")
            outside_output = directory / "outside-created.txt"
            create_events: list[str] = []
            original_exists = Path.exists
            original_mkdir = Path.mkdir

            def is_marked(path: Path) -> bool:
                candidate = Path(path)
                return (
                    candidate.name == marked.name
                    and candidate.parent.name == marked.parent.name
                )

            def missing_exists(path: Path) -> bool:
                if is_marked(path):
                    return False
                return original_exists(path)

            def forbidden_mkdir(
                path: Path,
                mode: int = 0o777,
                parents: bool = False,
                exist_ok: bool = False,
            ) -> None:
                if is_marked(path):
                    create_events.append("outside-create")
                    outside_output.write_text("forbidden", encoding="utf-8")
                    raise FileExistsError(path)
                original_mkdir(
                    path,
                    mode=mode,
                    parents=parents,
                    exist_ok=exist_ok,
                )

            with (
                patch.object(Path, "exists", missing_exists),
                patch.object(
                    measured_compare.os,
                    "lstat",
                    _broken_reparse_lstat(marked),
                ),
                patch.object(Path, "mkdir", forbidden_mkdir),
                pytest.raises(ValueError, match="symlink|reparse"),
            ):
                ensure_owner_route_suite(BenchmarkStore(root), label_set)
            assert create_events == []
            assert sentinel.read_text(encoding="utf-8") == "must-remain-unchanged"
            assert not outside_output.exists()

    def normal_missing_directories() -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            label_set = _load(_write(directory, _document()))
            root = directory / "store"
            root.mkdir()
            suite_name, version, _suite = ensure_owner_route_suite(
                BenchmarkStore(root), label_set
            )
            assert version == 1
            assert (root / "suites" / suite_name / "v1.jsonl").is_file()

    def missing_create_false() -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "store"
            root.mkdir()
            create_events: list[Path] = []

            def forbidden_mkdir(
                path: Path,
                mode: int = 0o777,
                parents: bool = False,
                exist_ok: bool = False,
            ) -> None:
                del mode, parents, exist_ok
                create_events.append(path)
                raise AssertionError("create=False attempted directory creation")

            boundary = measured_compare._MeasuredStoreBoundary(BenchmarkStore(root))
            with (
                patch.object(Path, "mkdir", forbidden_mkdir),
                pytest.raises(ValueError, match="must exist"),
            ):
                boundary.suite("missing-suite", create=False)
            assert create_events == []

    probe("broken suites create final", lambda: broken_create_final("suites"))
    probe(
        "broken selected-suite create final",
        lambda: broken_create_final("selected-suite"),
    )
    probe("normal missing-directory creation", normal_missing_directories)
    probe("missing create=False", missing_create_false)
    assert not failures, "broken create-directory finals failed: " + " | ".join(
        failures
    )


def _security_label_preallocation_probe() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        oversized = directory / "oversized-labels.json"
        oversized.write_bytes(b"{}" + b" " * 2_000_000)
        original_read_bytes = Path.read_bytes
        reads: list[Path] = []

        def read_bytes(path: Path) -> bytes:
            if path.name == oversized.name and path.parent.name == oversized.parent.name:
                reads.append(path)
                raise AssertionError("oversized label was bulk-read")
            return original_read_bytes(path)

        with (
            patch.object(Path, "read_bytes", read_bytes),
            pytest.raises(ValueError, match="bounded input limit"),
        ):
            load_route_label_set(oversized, registry=_bind())
        assert reads == []


def _security_redirection_probes() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        parent = directory / "label-parent"
        parent.mkdir()
        labels = parent / "labels.json"
        labels.write_text(json.dumps(_document()), encoding="utf-8")
        with (
            patch.object(measured_compare.os, "lstat", _marked_reparse_lstat(parent)),
            pytest.raises(ValueError),
        ):
            _load(parent / "labels.json")

    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set = _load(_write(directory, _document()))
        root = directory / "store"
        root.mkdir()
        suites = root / "suites"
        suites.mkdir()
        with (
            patch.object(measured_compare.os, "lstat", _marked_reparse_lstat(suites)),
            pytest.raises(ValueError),
        ):
            ensure_owner_route_suite(BenchmarkStore(root), label_set)

    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set = _load(_write(directory, _document()))
        root = directory / "store"
        root.mkdir()
        store = BenchmarkStore(root)
        suite_name = measured_compare._suite_name(label_set)
        (root / "suites").mkdir()
        selected_suite = root / "suites" / suite_name
        selected_suite.mkdir()
        with (
            patch.object(
                measured_compare.os, "lstat", _marked_reparse_lstat(selected_suite)
            ),
            pytest.raises(ValueError),
        ):
            ensure_owner_route_suite(store, label_set)

    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set, batch, store, _ = _report_fixture(directory)
        version_path = (
            store.root / "suites" / batch.suite_name / f"v{batch.suite_version}.jsonl"
        )
        with (
            patch.object(
                measured_compare.os, "lstat", _marked_reparse_lstat(version_path)
            ),
            pytest.raises(ValueError),
        ):
            _build_report(batch, store, label_set)

    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set, batch, store, _ = _report_fixture(directory)
        runs_path = _runs_path(store, batch.suite_name)
        with (
            patch.object(measured_compare.os, "lstat", _marked_reparse_lstat(runs_path)),
            pytest.raises(ValueError),
        ):
            _build_report(batch, store, label_set)


def _security_input_bound_probes() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        oversized = _write(directory, _document())
        payload = oversized.read_bytes()
        oversized.write_bytes(payload + b" " * (2_000_001 - len(payload)))
        with pytest.raises(ValueError):
            _load(oversized)

        too_many = _document()
        too_many["cases"] = [
            {
                **_document()["cases"][0],
                "case_id": f"task-{number:04}",
                "text": f"synthetic bounded request {number:04}",
                "source_record_digest": _digest(number),
            }
            for number in range(1, 1_002)
        ]
        with pytest.raises(ValueError):
            _load(_write(directory, too_many, "too-many.json"))

        too_many_routes = _document()
        routes = [f"route-{number:02}" for number in range(33)]
        too_many_routes["cases"][0]["acceptable_primary_routes"] = routes
        with pytest.raises(ValueError):
            load_route_label_set(
                _write(directory, too_many_routes, "too-many-routes.json"),
                registry=_bind({route: object() for route in routes}),
            )

        surrogate = _document()
        surrogate["cases"][0]["text"] = "escaped lone surrogate \ud800"
        with pytest.raises(ValueError):
            _load(_write(directory, surrogate, "surrogate.json"))

        deep = directory / "deep.json"
        deep.write_text("[" * 2_000 + "]" * 2_000, encoding="utf-8")
        with pytest.raises(ValueError):
            _load(deep)


def _security_benchmark_parser_probes() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set, batch, store, _ = _report_fixture(directory)
        report = _build_report(batch, store, label_set)
        with pytest.raises(ValueError):
            measured_compare.MeasuredComparisonReport.from_json(
                report.to_json() + " " * 2_000_001
            )

        retained = store.runs(batch.suite_name, last_n=sys.maxsize)[0]
        bool_as_number = retained.to_json().replace(
            '"can_change_routing":false', '"can_change_routing":0', 1
        )
        with pytest.raises(ValueError):
            BenchmarkRun.from_json(bool_as_number)
        duplicate_authority = retained.to_json().replace(
            '"can_authorize":false',
            '"can_authorize":false,"can_authorize":false',
            1,
        )
        with pytest.raises(ValueError):
            BenchmarkRun.from_json(duplicate_authority)


def _assert_bounded_topology_error(operation, root: Path) -> None:
    error = _capture_detached_private_error(
        operation,
        root,
        "C:/private/owner/store/v1.jsonl",
        "C:\\private\\owner\\store\\v1.jsonl",
    )
    message = str(error)
    assert len(message) <= 200
    assert str(root).lower() not in message.lower()
    assert "c:/private/owner/store/v1.jsonl" not in message.lower()
    assert "c:\\private\\owner\\store\\v1.jsonl" not in message.lower()


def _special_file_lstat(marked: Path):
    original = os.lstat

    def _lstat(path: str | bytes | os.PathLike[str] | os.PathLike[bytes]):
        metadata = original(path)
        candidate = Path(path)
        if (
            candidate.name == marked.name
            and candidate.parent.name == marked.parent.name
        ):
            return SimpleNamespace(
                st_mode=stat.S_IFCHR | 0o600,
                st_file_attributes=0,
            )
        return metadata

    return _lstat


def _check_exact_store_operation_types() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set = _load(_write(directory, _document()))
        root = directory / "canonical-store"
        outside = directory / "outside-store"
        root.mkdir()
        outside.mkdir()
        store = BenchmarkStore(root)
        store.suites_dir = outside
        suite_name, version, _ = ensure_owner_route_suite(store, label_set)
        assert version == 1
        assert (root / "suites" / suite_name / "v1.jsonl").is_file()
        assert tuple(outside.iterdir()) == ()

    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set, batch, store, _ = _report_fixture(
            directory,
            nonce="divergentstore",
        )
        outside = directory / "outside-read-store"
        outside.mkdir()
        sentinel = outside / "sentinel.txt"
        sentinel.write_text("must-remain-unread-and-unchanged", encoding="utf-8")
        store.suites_dir = outside
        report = _build_report(batch, store, label_set)
        assert report.run_fingerprints == batch.run_fingerprints
        assert sentinel.read_text(encoding="utf-8") == (
            "must-remain-unread-and-unchanged"
        )
        assert tuple(outside.iterdir()) == (sentinel,)

    for directory_slot in ("suites", "selected-suite"):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            label_set = _load(_write(directory, _document()))
            root = directory / "store"
            root.mkdir()
            suites = root / "suites"
            suite_name = measured_compare._suite_name(label_set)
            if directory_slot == "suites":
                suites.write_text("regular-file-directory-sentinel", encoding="utf-8")
                sentinel = suites
            else:
                suites.mkdir()
                sentinel = suites / suite_name
                sentinel.write_text(
                    "regular-file-directory-sentinel", encoding="utf-8"
                )
            _assert_bounded_topology_error(
                lambda root=root, label_set=label_set: ensure_owner_route_suite(
                    BenchmarkStore(root), label_set
                ),
                root,
            )
            assert sentinel.read_text(encoding="utf-8") == (
                "regular-file-directory-sentinel"
            )

    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set = _load(_write(directory, _document()))
        root = directory / "version-type-store"
        root.mkdir()
        store = BenchmarkStore(root)
        suite_name, version, _ = ensure_owner_route_suite(store, label_set)
        version_file = root / "suites" / suite_name / f"v{version}.jsonl"
        version_file.unlink()
        version_file.mkdir()
        _assert_bounded_topology_error(
            lambda: ensure_owner_route_suite(store, label_set),
            root,
        )
        assert version_file.is_dir()

    for final_name in ("version", "runs"):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            label_set, batch, store, _ = _report_fixture(
                directory,
                nonce=f"special{final_name}",
            )
            marked = (
                store.root
                / "suites"
                / batch.suite_name
                / (
                    f"v{batch.suite_version}.jsonl"
                    if final_name == "version"
                    else "runs.jsonl"
                )
            )
            with patch.object(
                measured_compare.os,
                "lstat",
                _special_file_lstat(marked),
            ):
                _assert_bounded_topology_error(
                    lambda batch=batch, store=store, label_set=label_set: _build_report(
                        batch, store, label_set
                    ),
                    store.root,
                )

    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set, batch, store, _ = _report_fixture(
            directory,
            nonce="runsdirectory",
        )
        runs_file = _runs_path(store, batch.suite_name)
        runs_file.unlink()
        runs_file.mkdir()
        _assert_bounded_topology_error(
            lambda: _build_report(batch, store, label_set),
            store.root,
        )
        assert runs_file.is_dir()

    for delegated_method, delegated_error in (
        ("save_suite", FileExistsError("C:/private/owner/store/v1.jsonl")),
        ("load_suite", PermissionError("C:/private/owner/store/v1.jsonl")),
    ):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            label_set = _load(_write(directory, _document()))
            root = directory / f"delegated-{delegated_method}"
            root.mkdir()
            store = BenchmarkStore(root)
            if delegated_method == "load_suite":
                ensure_owner_route_suite(store, label_set)
            with patch.object(
                BenchmarkStore,
                delegated_method,
                side_effect=delegated_error,
            ):
                _assert_bounded_topology_error(
                    lambda store=store, label_set=label_set: ensure_owner_route_suite(
                        store, label_set
                    ),
                    root,
                )

    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set, batch, store, _ = _report_fixture(
            directory,
            nonce="delegatedrunsread",
        )
        with patch.object(
            BenchmarkStore,
            "runs",
            side_effect=PermissionError("C:/private/owner/store/v1.jsonl"),
        ):
            _assert_bounded_topology_error(
                lambda: _build_report(batch, store, label_set),
                store.root,
            )

    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        registry = _bind()
        label_set = _load(
            _write(directory, _document()),
            registry=registry,
        )
        root = directory / "delegated-record-run"
        root.mkdir()
        with patch.object(
            BenchmarkStore,
            "record_run",
            side_effect=PermissionError("C:/private/owner/store/v1.jsonl"),
        ):
            _assert_bounded_topology_error(
                lambda: asyncio.run(
                    measured_compare.run_measured_comparison(
                        router=_MeasuredRouter(),
                        registry=registry,
                        label_set=label_set,
                        store_root=root,
                        source_revision=_REVISION,
                        run_nonce=lambda: "delegatedrecord",
                    )
                ),
                root,
            )


def _check_security_hold_remediation() -> None:
    """Consolidated red/green probes for every accepted Task 6 security finding."""

    failures: list[str] = []

    def probe(label: str, operation) -> None:
        try:
            operation()
        except BaseException as exc:  # collect every red class before failing once
            failures.append(f"{label}: {type(exc).__name__}: {exc}")

    def late_injection() -> None:
        router = _LateInjectingNormalRouter()
        observation = asyncio.run(
            measured_compare.current_router_runner(
                router,
                {"jarvis": object(), "vision": object()},
            )("an unmatched owner-local prompt")
        )
        assert observation.route_id == "jarvis"
        assert router.normal_prompts == []
        assert router.classifier_prompts == []

    probe("late classifier injection", late_injection)
    probe("bound deterministic capability", _security_bound_capability_probes)
    probe("legacy shadow compatibility", _security_shadow_legacy_compatibility_probe)
    probe("broken measured-store finals", _security_broken_final_probes)
    probe("broken create-directory finals", _security_broken_create_directory_probes)
    probe("label pre-allocation byte bound", _security_label_preallocation_probe)
    probe("retention path redirections", _security_redirection_probes)
    probe("retained-run authority parser", _security_benchmark_parser_probes)
    probe("bounded hostile parsers", _security_input_bound_probes)
    assert not failures, "security HOLD probes failed: " + " | ".join(failures)


def run_e1_2_checks() -> None:
    _check_route_registry_binding()
    _check_security_hold_remediation()
    _check_exact_store_operation_types()
    _check_strict_route_labels()
    _check_suite_binding()
    _check_measured_runner()
    _check_measured_run_batch()
    _check_measured_report()
    _check_unique_task_consensus()
    _check_measured_report_adversarial()
    _check_report_count_parser_attacks()
    _check_report_environment_parser_attacks()
    _check_environment_digest_privacy()
    _check_report_parser_strictness()
    _check_retained_evidence_tamper_matrix()
    _check_measurement_provider_privacy_matrix()
    _check_operator_contract_ledgers()
