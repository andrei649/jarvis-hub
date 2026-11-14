"""V51 lifecycle persistence semantics against the isolated runtime candidate."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agents.core.extensions.activation_hints import ActivationHintStore
from agents.core.extensions.consent import ExtensionConsentStore
from agents.core.extensions.runtime import ExtensionRuntime
from tests import test_extension_runtime as runtime_tests


@pytest.fixture()
def rig(tmp_path):
    packages = runtime_tests._Packages(tmp_path / "package")
    runner = runtime_tests._Runner()
    consent = ExtensionConsentStore(tmp_path / "consent.json")
    runtime = ExtensionRuntime(
        packages=packages,
        profile=runtime_tests._Profile(),
        runtime_root=tmp_path / "runs",
        runner=runner,
        consent=consent,
        enabled=lambda: True,
    )
    return SimpleNamespace(runtime=runtime, packages=packages, runner=runner,
                           consent=consent, root=tmp_path)


@pytest.fixture()
def consented(rig):
    rig.consent.grant(runtime_tests.descriptor())
    return rig


def _runtime(rig, *, activation_hints=None, rpc=None):
    return ExtensionRuntime(
        packages=rig.packages,
        profile=runtime_tests._Profile(),
        runtime_root=rig.root / "restart-runs",
        runner=rig.runner,
        consent=rig.consent,
        enabled=lambda: True,
        rpc=rpc,
        activation_hints=activation_hints,
    )


class _FailingStore:
    def __init__(self, *, put_error=None, remove_error=None):
        self.put_error = put_error
        self.remove_error = remove_error
        self.puts = []
        self.removes = []

    def put(self, manifest, package_hash, grant_revision):
        self.puts.append((manifest, package_hash, grant_revision))
        if self.put_error:
            raise self.put_error

    def remove(self, extension_id):
        self.removes.append(extension_id)
        if self.remove_error:
            raise self.remove_error
        return True


@pytest.mark.asyncio
async def test_activation_persists_complete_hint_and_new_store_reads_it(consented, tmp_path):
    path = tmp_path / "hints.json"
    store = ActivationHintStore(path)
    runtime = _runtime(consented, activation_hints=store)

    activation = await runtime.activate(runtime_tests.descriptor())

    reopened = ActivationHintStore(path)
    (hint,) = reopened.read_all()
    assert hint.manifest == activation.manifest
    assert hint.package_hash == activation.package_hash
    assert hint.grant_revision == activation.grant_revision
    assert runtime.restoration_status("boats") == {"state": "saved"}

    restarted = _runtime(consented, activation_hints=reopened)
    calls_before = len(consented.runner.calls)
    assert restarted.active() == ()
    assert len(consented.runner.calls) == calls_before
    assert restarted.restoration_status("boats") == {"state": "saved"}


def test_restoration_status_without_store_is_not_configured(rig):
    assert rig.runtime.restoration_status("boats") == {"state": "not_configured"}


def test_configured_store_without_observed_mutation_is_unknown(consented, tmp_path):
    runtime = _runtime(consented, activation_hints=ActivationHintStore(tmp_path / "hints.json"))
    assert runtime.restoration_status("boats") == {"state": "unknown"}


@pytest.mark.asyncio
async def test_save_failure_does_not_undo_live_activation(consented):
    store = _FailingStore(put_error=RuntimeError("secret filesystem path"))
    runtime = _runtime(consented, activation_hints=store)

    activation = await runtime.activate(runtime_tests.descriptor())

    assert runtime.active() == (activation,)
    status = runtime.restoration_status("boats")
    assert status == {"state": "save_failed", "reason": "activation_hints_unavailable"}
    assert "secret filesystem path" not in repr(status)


@pytest.mark.asyncio
async def test_remove_failure_retires_live_activation_and_reports_uncertain_durability(consented):
    error = RuntimeError("internal storage detail")
    error.reason = "activation_hints_durability_uncertain"
    store = _FailingStore()
    runtime = _runtime(consented, activation_hints=store)
    await runtime.activate(runtime_tests.descriptor())
    store.remove_error = error

    retired = await runtime.deactivate("boats")

    assert retired is True
    assert runtime.active() == ()
    assert runtime.restoration_status("boats") == {
        "state": "remove_failed", "reason": "activation_hints_durability_uncertain"
    }
    assert "internal storage detail" not in repr(runtime.restoration_status("boats"))


@pytest.mark.asyncio
async def test_deactivate_never_active_id_still_removes_saved_hint(consented, tmp_path):
    store = ActivationHintStore(tmp_path / "hints.json")
    manifest = runtime_tests.descriptor()
    store.put(manifest, "c" * 64, "d" * 64)
    runtime = _runtime(consented, activation_hints=store)

    assert await runtime.deactivate("boats") is False

    assert ActivationHintStore(tmp_path / "hints.json").read_all() == ()
    assert runtime.restoration_status("boats") == {"state": "removed"}


@pytest.mark.asyncio
async def test_deactivate_removes_hint_before_cancellable_rpc_unregister(consented, tmp_path):
    class BlockingRPC:
        def __init__(self):
            self.unregister_started = asyncio.Event()
            self.finish_unregister = asyncio.Event()

        def register_tool(self, *args, **kwargs):
            pass

        async def unregister_tool(self, tool, *, cancel_inflight):
            self.unregister_started.set()
            await self.finish_unregister.wait()

    path = tmp_path / "hints.json"
    store = ActivationHintStore(path)
    rpc = BlockingRPC()
    runtime = _runtime(consented, activation_hints=store, rpc=rpc)
    await runtime.activate(runtime_tests.descriptor())

    task = asyncio.create_task(runtime.deactivate("boats"))
    await asyncio.wait_for(rpc.unregister_started.wait(), timeout=2)
    assert ActivationHintStore(path).read_all() == ()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runtime.active() == ()
    assert runtime.restoration_status("boats") == {"state": "removed"}


@pytest.mark.asyncio
async def test_replacement_and_stale_conditional_cleanup_preserve_new_hint(consented, tmp_path):
    class TrackingStore:
        def __init__(self, path):
            self.inner = ActivationHintStore(path)
            self.removes = []

        def put(self, *args):
            return self.inner.put(*args)

        def remove(self, extension_id):
            self.removes.append(extension_id)
            return self.inner.remove(extension_id)

        def read_all(self):
            return self.inner.read_all()

    store = TrackingStore(tmp_path / "hints.json")
    runtime = _runtime(consented, activation_hints=store)
    old = await runtime.activate(runtime_tests.descriptor())
    consented.packages.record.package_hash = "e" * 64

    replacement = await runtime.activate(runtime_tests.descriptor())

    assert replacement is not old
    assert store.removes == []
    (hint,) = store.read_all()
    assert hint.package_hash == replacement.package_hash == "e" * 64
    assert await runtime.deactivate("boats", expected_activation=old) is False
    assert store.removes == []
    (hint_after_cleanup,) = store.read_all()
    assert hint_after_cleanup.package_hash == replacement.package_hash
    assert runtime.restoration_status("boats") == {"state": "saved"}
