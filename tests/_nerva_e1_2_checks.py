"""Uncollected E1.2a contract assertions for owner-local route labels."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
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
from agents.core.observability.benchmark import BenchmarkStore
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
        link_root = directory / "link-store"
        try:
            os.symlink(link_target, link_root, target_is_directory=True)
        except (NotImplementedError, OSError):
            pass
        else:
            with pytest.raises(ValueError, match="symlink|reparse"):
                asyncio.run(
                    measured_compare.run_measured_comparison(
                        router=_MeasuredRouter(),
                        agents=agents,
                        label_set=label_set,
                        store_root=link_root,
                        source_revision=_REVISION,
                    )
                )

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
                with pytest.raises(ValueError, match="symlink|reparse"):
                    asyncio.run(
                        measured_compare.run_measured_comparison(
                            router=_MeasuredRouter(),
                            agents=agents,
                            label_set=label_set,
                            store_root=junction_root,
                            source_revision=_REVISION,
                        )
                    )
            finally:
                os.rmdir(junction_root)

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

        before_collision = store.runs(batch.suite_name, last_n=20)
        collision_router = _MeasuredRouter()
        with pytest.raises(ValueError, match="collision"):
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
        assert collision_router.classify_calls == 20
        assert store.runs(batch.suite_name, last_n=20) == before_collision

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


def run_e1_2_checks() -> None:
    _check_strict_route_labels()
    _check_suite_binding()
    _check_measured_runner()
    _check_measured_run_batch()
