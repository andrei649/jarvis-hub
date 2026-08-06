"""Uncollected E1.2a contract assertions for owner-local route labels."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from agents.core import cortex_measured_compare as measured_compare
from agents.core.cortex_decision import DecisionRecord, DecisionRequest
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
    BenchmarkStore,
    Measurement,
)
from agents.core.observability.scheduled_report import (
    EnvironmentProfile,
    run_fingerprint,
)
from agents.core.router import Intent

_REVISION = "a" * 40


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


class _NoCaptureRouter:
    def __init__(self, router, _writer) -> None:
        self._router = router

    async def classify(self, text: str, agents: dict[str, object]):
        return await self._router.classify(text, agents)

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

    def __getattr__(self, name: str):
        return getattr(self._router, name)


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

    def __getattr__(self, name: str):
        return getattr(self._router, name)


def _check_measured_runner() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set = _load(_write(directory, _document()))
        agents = {"friday": object(), "jarvis": object()}
        prompt = label_set.cases[0].text

        configured = _MeasuredRouter()
        configured.llm_classifier = object()
        with pytest.raises(ValueError, match="llm_classifier=None"):
            measured_current_router_runner(configured, agents, label_set)

        mutable = _MeasuredRouter()
        runner = measured_current_router_runner(mutable, agents, label_set)
        mutable.llm_classifier = object()
        with pytest.raises(ValueError, match="llm_classifier=None"):
            asyncio.run(runner(prompt))
        assert mutable.classify_calls == 0

        unknown = _MeasuredRouter()
        unknown_runner = measured_current_router_runner(unknown, agents, label_set)
        with pytest.raises(ValueError, match="known route label"):
            asyncio.run(unknown_runner("  UNKNOWN NORMALIZED PROMPT  "))
        assert unknown.classify_calls == 0

        accepted_router = _MeasuredRouter("friday")
        accepted = asyncio.run(
            measured_current_router_runner(accepted_router, agents, label_set)(prompt)
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
        )
        assert prompt not in "".join(accepted.artifact_refs)
        assert label_set.cases[0].source_record_digest not in "".join(
            accepted.artifact_refs
        )

        rejected = asyncio.run(
            measured_current_router_runner(_MeasuredRouter("jarvis"), agents, label_set)(
                prompt
            )
        )
        assert rejected.response == "rejected"
        assert rejected.route_id == "jarvis"

        for wrapper in (_NoCaptureRouter, _DoubleCaptureRouter, _MismatchedCaptureRouter):
            with patch.object(measured_compare, "ShadowDecisionRouter", wrapper):
                bad_runner = measured_current_router_runner(
                    _MeasuredRouter(), agents, label_set
                )
                with pytest.raises(RuntimeError):
                    asyncio.run(bad_runner(prompt))

        async def _run_concurrently() -> tuple[object, object]:
            _InterleavingCaptureRouter.reset()
            concurrent_runner = measured_current_router_runner(
                _MeasuredRouter(), agents, label_set
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
            raise RuntimeError("synthetic retained measured-router failure")
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
        label_set = _load(_write(directory, _document()))
        agents = {"friday": object(), "jarvis": object()}

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
                            agents=agents,
                            label_set=label_set,
                            store_root=invalid,
                            source_revision=_REVISION,
                        )
                    )
            with pytest.raises(TypeError):
                asyncio.run(
                    measured_compare.run_measured_comparison(
                        router=_MeasuredRouter(),
                        agents=agents,
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
                        agents=agents,
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
                        agents=agents,
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
                            agents=agents,
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
                            agents=agents,
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
                        agents=agents,
                        label_set=label_set,
                        store_root=preflight_root,
                        source_revision=revision,
                    )
                )
        with pytest.raises(ValueError, match="RouteLabelSet"):
            asyncio.run(
                measured_compare.run_measured_comparison(
                    router=_MeasuredRouter(),
                    agents=agents,
                    label_set=object(),
                    store_root=preflight_root,
                    source_revision=_REVISION,
                )
            )
        with pytest.raises(ValueError, match="registered"):
            asyncio.run(
                measured_compare.run_measured_comparison(
                    router=_MeasuredRouter(),
                    agents={"jarvis": object()},
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
                    agents=agents,
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
                    agents=agents,
                    label_set=label_set,
                    store_root=store_root,
                    source_revision=_REVISION,
                    run_nonce=lambda: "fixednonce",
                )
            )
        detect.assert_called_once_with(runner_id="owner-local-e1-2a")
        assert constructed_roots == [(store_root.resolve(),)]
        assert router.classify_calls == 20 * 6
        assert batch.store_root == store_root.resolve()
        assert batch.label_set_fingerprint == label_set.content_fingerprint
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
                f"environment-fingerprint:{batch.environment_fingerprint}",
            )

        with pytest.raises(FrozenInstanceError):
            batch.source_revision = "b" * 40
        with pytest.raises(ValueError, match="internally"):
            measured_compare.MeasuredRunBatch(
                label_set_fingerprint=label_set.content_fingerprint,
                suite_name=batch.suite_name,
                suite_version=batch.suite_version,
                environment=environment,
                environment_fingerprint=batch.environment_fingerprint,
                source_revision=_REVISION,
                run_fingerprints=batch.run_fingerprints,
                store_root=store_root,
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
                    agents=agents,
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
                    agents=agents,
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
                agents=agents,
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
                    agents=agents,
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
                    agents=agents,
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
            pytest.raises(OSError, match="retained-write"),
        ):
            asyncio.run(
                measured_compare.run_measured_comparison(
                    router=write_failure_router,
                        agents=agents,
                        label_set=label_set,
                        store_root=write_failure_root,
                        source_revision="b" * 64,
                        run_nonce=lambda: "writefail",
                )
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
                    agents=agents,
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
                    agents=agents,
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
                    agents=agents,
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
    router: _MeasuredRouter | None = None,
    nonce: str = "reportfixture",
):
    label_set = _load(_write(directory, document or _document()))
    store_root = directory / "report-store"
    store_root.mkdir()
    environment = EnvironmentProfile.detect(runner_id="owner-local-e1-2a")
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
                agents={"friday": object(), "jarvis": object()},
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
    raw["environment_fingerprint"] = environment["content_fingerprint"]


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
        return measured_compare.build_measured_report(
            changed_batch,
            store,
            label_set,
        )
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
        report = measured_compare.build_measured_report(batch, store, label_set)

        impossible = json.loads(report.to_json())
        impossible.update(
            {
                "accepted_count": 0,
                "rejected_count": 0,
                "incomplete_count": 0,
                "overall_adequacy": {
                    "source": None,
                    "status": "not_measured",
                    "unit": None,
                    "value": None,
                },
            }
        )
        for route in impossible["per_actual_route"]:
            route.update(
                {
                    "accepted_count": 0,
                    "rejected_count": 0,
                    "incomplete_count": 0,
                    "adequacy": {
                        "source": None,
                        "status": "not_measured",
                        "unit": None,
                        "value": None,
                    },
                }
            )
        with pytest.raises(ValueError, match="incomplete"):
            measured_compare.MeasuredComparisonReport.from_json(
                _refingerprint_report(impossible)
            )

        impossible_route = json.loads(report.to_json())
        friday, jarvis = impossible_route["per_actual_route"]
        friday.update(
            {
                "accepted_count": 0,
                "rejected_count": 0,
                "incomplete_count": 0,
                "adequacy": {
                    "source": None,
                    "status": "not_measured",
                    "unit": None,
                    "value": None,
                },
            }
        )
        jarvis.update({"accepted_count": 25, "rejected_count": 0})
        jarvis["adequacy"]["value"] = 1.0
        impossible_route.update(
            {
                "accepted_count": 25,
                "rejected_count": 0,
                "overall_adequacy": {
                    "source": "benchmark.harness",
                    "status": "measured",
                    "unit": "ratio",
                    "value": 1.0,
                },
            }
        )
        with pytest.raises(ValueError, match="route incomplete"):
            measured_compare.MeasuredComparisonReport.from_json(
                _refingerprint_report(impossible_route)
            )


def _check_report_environment_parser_attacks() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set, batch, store, _ = _report_fixture(directory)
        report = measured_compare.build_measured_report(batch, store, label_set)
        for field, attack in (
            ("runner_id", "owner-local-e1-2a-arbitrary-note-andrei649"),
            ("platform", "windows-amd64-arbitrary-note-andrei649"),
            ("python_version", "3.12.1-arbitrary-note-andrei649"),
        ):
            raw = json.loads(report.to_json())
            raw["environment"][field] = attack
            _refingerprint_environment(raw)
            with pytest.raises(ValueError, match="environment"):
                measured_compare.MeasuredComparisonReport.from_json(
                    _refingerprint_report(raw)
                )

        markdown = measured_compare.render_measured_report(report)
        for value in (
            report.environment.runner_id,
            report.environment.platform,
            report.environment.python_version,
        ):
            assert value not in markdown


def _check_report_parser_strictness() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set, batch, store, _ = _report_fixture(directory)
        report = measured_compare.build_measured_report(batch, store, label_set)
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
            (("environment",), lambda value: value.pop("platform")),
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
            measured_compare.validate_measured_report_against_evidence(
                structural,
                batch,
                store,
                label_set,
            )

        constructor = {
            field.name: getattr(report, field.name)
            for field in fields(report)
            if field.init
        }
        constructor["_guard"] = measured_compare._MEASURED_REPORT_GUARD
        for flag in (
            "can_change_routing",
            "can_authorize",
            "can_execute",
            "can_promote",
            "can_mark_complete",
        ):
            with pytest.raises(TypeError):
                measured_compare.MeasuredComparisonReport(
                    **constructor,
                    **{flag: True},
                )
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
            measured_compare.build_measured_report(
                batch,
                BenchmarkStore(wrong_root),
                label_set,
            )
        with pytest.raises(ValueError, match="stored suite"):
            measured_compare.build_measured_report(
                _guarded_batch(batch, suite_version=batch.suite_version + 1),
                store,
                label_set,
            )
        for changed_suite in (
            tuple(reversed(suite)),
            (replace(suite[0], task_type="forecast"), *suite[1:]),
        ):
            with (
                patch.object(store, "load_suite", return_value=changed_suite),
                pytest.raises(ValueError, match="stored suite"),
            ):
                measured_compare.build_measured_report(batch, store, label_set)

        original_runs = _ordered_runs(store, batch.suite_name)
        path = _runs_path(store, batch.suite_name)
        original_text = path.read_text(encoding="utf-8")
        try:
            path.write_text(
                original_text + original_runs[0].to_json() + "\n",
                encoding="utf-8",
            )
            with pytest.raises(ValueError, match="fingerprint"):
                measured_compare.build_measured_report(batch, store, label_set)
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
            measured_compare.build_measured_report(
                _guarded_batch(
                    batch,
                    run_fingerprints=("f" * 64, *batch.run_fingerprints[1:]),
                ),
                store,
                label_set,
            )
        with pytest.raises(ValueError, match="ordered repetitions"):
            measured_compare.build_measured_report(
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
                measured_compare.build_measured_report(batch, store, label_set)
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
                    f"environment-fingerprint:{'e' * 64}",
                ),
            ),
            lambda run: replace(
                run,
                artifact_refs=(
                    f"label-fingerprint:{'d' * 64}",
                    run.artifact_refs[1],
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
        measured_compare.build_measured_report(
            other_batch,
            other_store,
            other_labels,
        )
        with pytest.raises(ValueError):
            measured_compare.build_measured_report(
                other_batch,
                other_store,
                label_set,
            )


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


def _assert_privacy_minimised(report, label_set, store) -> None:
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
        "arbitrary-note-sentinel",
        "synthetic measured-router failure",
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
        label_set, batch, store, _ = _report_fixture(directory)
        complete = measured_compare.build_measured_report(batch, store, label_set)
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
        assert wrong_source.accepted_count == 75
        assert wrong_source.rejected_count == 25
        assert wrong_source.incomplete_count == 1
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
            assert changed.incomplete_count == 1
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
            incomplete.accepted_count,
            incomplete.rejected_count,
            incomplete.error_count,
            incomplete.incomplete_count,
        ) == (73, 25, 1, 3)
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


def _check_measured_report() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set, batch, store, environment = _report_fixture(directory)
        report = measured_compare.build_measured_report(batch, store, label_set)

        assert isinstance(report, measured_compare.MeasuredComparisonReport)
        assert report.schema == measured_compare.REPORT_SCHEMA
        assert report.label_set_id == label_set.label_set_id
        assert report.label_set_fingerprint == label_set.content_fingerprint
        assert report.suite_name == batch.suite_name
        assert report.suite_version == batch.suite_version
        assert report.source_revision == _REVISION
        assert report.candidate_id == measured_compare.CANDIDATE_ID
        assert report.baseline_id is None
        assert report.environment == measured_compare.EnvironmentEvidence.from_profile(
            environment
        )
        assert report.environment_fingerprint == batch.environment_fingerprint
        assert report.run_fingerprints == batch.run_fingerprints
        assert report.repetition_count == 5
        assert report.task_count == 20
        assert report.sample_count == 100
        assert report.accepted_count == 75
        assert report.rejected_count == 25
        assert report.error_count == 0
        assert report.incomplete_count == 0
        assert report.overall_adequacy == Measurement(
            "measured", 0.75, "ratio", "benchmark.harness"
        )
        assert tuple(route.route_id for route in report.per_actual_route) == (
            "friday",
            "jarvis",
        )
        assert tuple(
            (
                route.sample_count,
                route.accepted_count,
                route.rejected_count,
                route.incomplete_count,
                route.adequacy.value,
            )
            for route in report.per_actual_route
        ) == ((75, 75, 0, 0, 1.0), (25, 0, 25, 0, 0.0))
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
        assert len(report.limitations) >= 1
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

        measured_compare.validate_measured_report_against_evidence(
            report,
            batch,
            store,
            label_set,
        )
        encoded = report.to_json()
        assert encoded == json.dumps(
            json.loads(encoded),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        structural = measured_compare.MeasuredComparisonReport.from_json(encoded)
        assert structural == report
        measured_compare.validate_measured_report_against_evidence(
            structural,
            batch,
            store,
            label_set,
        )

        markdown = measured_compare.render_measured_report(report)
        assert "owner evidence: blocked" in markdown.lower()
        assert "real task-outcome quality: not_measured" in markdown.lower()
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


def _check_measured_report_adversarial() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set, batch, store, _environment = _report_fixture(directory)
        report = measured_compare.build_measured_report(batch, store, label_set)
        raw = json.loads(report.to_json())

        for mutation in (
            lambda value: value.update({"unknown": True}),
            lambda value: value.pop("sample_count"),
            lambda value: value.update({"sample_count": 99}),
            lambda value: value.update({"complete": False}),
            lambda value: value.update({"authority": "production"}),
            lambda value: value.update({"can_execute": True}),
            lambda value: value.update({"content_fingerprint": "0" * 64}),
            lambda value: value["latency_p95"].update({"value": -1.0}),
            lambda value: value["overall_adequacy"].update({"value": 1.1}),
        ):
            changed = deepcopy(raw)
            mutation(changed)
            with pytest.raises((TypeError, ValueError)):
                measured_compare.MeasuredComparisonReport.from_json(
                    json.dumps(changed)
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
            measured_compare.build_measured_report(batch, store, other_labels)
        with pytest.raises(ValueError):
            measured_compare.validate_measured_report_against_evidence(
                report,
                batch,
                store,
                other_labels,
            )

        runs_path = store.root / "suites" / batch.suite_name / "runs.jsonl"
        retained_lines = runs_path.read_text(encoding="utf-8").splitlines()
        runs_path.write_text("\n".join(retained_lines[:-1]) + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="fingerprint"):
            measured_compare.build_measured_report(batch, store, label_set)

    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        label_set, error_batch, error_store, _ = _report_fixture(
            directory,
            router=_FailAfterWarmupRouter(),
            nonce="reporterrors",
        )
        error_report = measured_compare.build_measured_report(
            error_batch,
            error_store,
            label_set,
        )
        assert error_report.accepted_count == 0
        assert error_report.rejected_count == 0
        assert error_report.error_count == 100
        assert error_report.incomplete_count == 100
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
                    agents={"friday": object(), "jarvis": object()},
                    label_set=label_set,
                    store_root=store_root,
                    source_revision=_REVISION,
                    run_nonce=lambda: "reportunscored",
                )
            )
        unscored_report = measured_compare.build_measured_report(
            batch,
            BenchmarkStore(store_root),
            label_set,
        )
        assert unscored_report.accepted_count == 95
        assert unscored_report.rejected_count == 0
        assert unscored_report.error_count == 0
        assert unscored_report.incomplete_count == 5
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
        provider_report = measured_compare.build_measured_report(
            batch,
            store,
            label_set,
        )
        assert provider_report.provider_charge == Measurement("not_measured")
        assert provider_report.complete is False


def run_e1_2_checks() -> None:
    _check_strict_route_labels()
    _check_suite_binding()
    _check_measured_runner()
    _check_measured_run_batch()
    _check_measured_report()
    _check_measured_report_adversarial()
    _check_report_count_parser_attacks()
    _check_report_environment_parser_attacks()
    _check_report_parser_strictness()
    _check_retained_evidence_tamper_matrix()
    _check_measurement_provider_privacy_matrix()
