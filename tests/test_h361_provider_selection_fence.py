"""Inert signed selection storage and cross-process pair-write fencing."""
from __future__ import annotations

import argparse
import asyncio
import json
import multiprocessing as mp
import os
import sqlite3
import threading
import time
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from agents.core import settings_db
from agents.core.llm import provider_selection
from agents.core.llm.providers import selection_gates


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    return tmp_path / "settings.db"


def _binding(store: Path):
    return provider_selection.SelectionBinding(
        authority="local-owner-v1", home=str(store.parent), provider_id="signed-test",
        model="signed-model", source="user", artifact_id="a" * 32,
        package_hash="b" * 64, endpoint="https://api.example.test/v1",
        auth_type="bearer", credential_generation=1,
    )


def test_signed_selection_cas_strict_readback_and_pair_trigger(store):
    assert provider_selection.read_selection(store) is None
    first = provider_selection.compare_and_swap(store, _binding(store), expected_revision=2)
    assert first.revision == 3 and provider_selection.read_selection(store) == first
    with pytest.raises(provider_selection.SelectionConflict):
        provider_selection.compare_and_swap(store, _binding(store), expected_revision=2)
    settings_db.put_category("system", {"error_backlog_sync_enabled": False})
    assert provider_selection.read_selection(store) == first
    settings_db.put_category("llm", {"compatible_model": "builtin-new"})
    assert provider_selection.read_selection(store) is None
    assert provider_selection.current_revision(store) > first.revision
    second = provider_selection.compare_and_swap(
        store, _binding(store), expected_revision=provider_selection.current_revision(store))
    with sqlite3.connect(store) as conn:
        conn.execute("UPDATE settings SET value=? WHERE category='llm' AND key='compatible_model'",
                     ('"manual-bypass"',))
    assert provider_selection.read_selection(store) is None
    assert provider_selection.current_revision(store) > second.revision


def test_signed_selection_tamper_refuses_readback(store):
    first = provider_selection.compare_and_swap(
        store, _binding(store), expected_revision=2)
    with sqlite3.connect(store) as conn:
        conn.execute("UPDATE signed_provider_selection SET record_hash=? WHERE singleton=1",
                     ("0" * 64,))
    with pytest.raises(provider_selection.SelectionInvalid):
        provider_selection.read_selection(store)
    with pytest.raises(provider_selection.SelectionInvalid):
        provider_selection.compare_and_swap(store, _binding(store), expected_revision=first.revision)


def test_legacy_selection_row_reads_with_empty_inert_proof(store):
    first = provider_selection.compare_and_swap(
        store, _binding(store), expected_revision=2)
    fields = asdict(first.binding)
    fields.pop('consent_proof')
    payload = json.dumps(fields, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    with sqlite3.connect(store) as conn:
        conn.execute('UPDATE signed_provider_selection SET record_json=?,record_hash=? '
                     'WHERE singleton=1',
                     (payload, provider_selection._digest(first.revision, payload)))
    loaded = provider_selection.read_selection(store)
    assert loaded == first
    assert loaded.binding.consent_proof == ''
    with pytest.raises(provider_selection.SelectionInvalid):
        replace(loaded.binding, consent_proof='not-a-mac')


def test_rehashed_malformed_consent_proof_is_not_a_valid_selection(store):
    first = provider_selection.compare_and_swap(
        store, _binding(store), expected_revision=2)
    fields = asdict(first.binding)
    fields['consent_proof'] = 'not-a-mac'
    payload = json.dumps(fields, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    with sqlite3.connect(store) as conn:
        conn.execute('UPDATE signed_provider_selection SET record_json=?,record_hash=? '
                     'WHERE singleton=1',
                     (payload, provider_selection._digest(first.revision, payload)))
    with pytest.raises(provider_selection.SelectionInvalid):
        provider_selection.read_selection(store)


def test_selection_generation_matches_credential_vault_contract(store):
    base = _binding(store)
    no_auth = replace(base, auth_type='none', credential_generation=0)
    assert provider_selection.compare_and_swap(
        store, no_auth, expected_revision=2).binding == no_auth
    with pytest.raises(provider_selection.SelectionInvalid):
        replace(base, credential_generation=0)
    with pytest.raises(provider_selection.SelectionInvalid):
        replace(no_auth, credential_generation=1)


def _hold_shared(path: str, ready, release):
    settings_db.DB_PATH = Path(path)
    with selection_gates.shared(path):
        ready.set()
        release.wait(5)


def _special_store_probe(path: str, mode: str, channel, start, startup_gate=None,
                         operation_gate=None):
    if startup_gate is not None:
        startup_gate.wait(10)
    settings_db.DB_PATH = Path(path)

    async def cancelled_acquire():
        task = asyncio.create_task(selection_gates.acquire_shared_async(path))
        await asyncio.sleep(0.03)
        task.cancel()
        try:
            await asyncio.wait_for(task, 0.4)
        except asyncio.CancelledError:
            return 'cancelled'

    try:
        channel.send('ready')
        if not start.wait(10):
            return
        channel.send('entered')
        if operation_gate is not None:
            operation_gate.wait(10)
        if mode == 'shared':
            with selection_gates.shared(path):
                channel.send('accepted')
        elif mode == 'exclusive':
            with selection_gates.exclusive(path):
                channel.send('accepted')
        else:
            channel.send(asyncio.run(cancelled_acquire()))
    except selection_gates.SelectionUnavailable:
        channel.send('refused')
    finally:
        channel.close()


class _ProbeDeadline(AssertionError):
    def __init__(self, phase: str, mode: str):
        self.phase = phase
        super().__init__(f'{mode} FIFO probe {phase} deadline exceeded')


def _run_special_store_probe(path: Path, mode: str, *, startup_gate=None,
                             operation_gate=None, after_start=None,
                             startup_timeout=8.0, dispatch_timeout=2.0,
                             operation_timeout=1.5, timings=None):
    """Measure interpreter startup separately from the bounded gate operation."""
    ctx = mp.get_context('spawn')
    receive, send = ctx.Pipe(duplex=False)
    start = ctx.Event()
    child = ctx.Process(target=_special_store_probe,
                        args=(str(path), mode, send, start, startup_gate, operation_gate))
    started = False
    try:
        child.start()
        started = True
        startup_started = time.monotonic()
        send.close()
        if after_start is not None:
            after_start(receive)
        if not receive.poll(startup_timeout):
            raise _ProbeDeadline('startup', mode)
        try:
            ready = receive.recv()
        except EOFError:
            raise AssertionError(f'{mode} FIFO probe exited during startup') from None
        assert ready == 'ready', f'{mode} FIFO probe did not become ready'
        startup_elapsed = time.monotonic() - startup_started
        start.set()
        if not receive.poll(dispatch_timeout):
            raise _ProbeDeadline('dispatch', mode)
        try:
            entered = receive.recv()
        except EOFError:
            raise AssertionError(f'{mode} FIFO probe exited before operation') from None
        assert entered == 'entered', f'{mode} FIFO probe did not enter its operation'
        operation_started = time.monotonic()
        if not receive.poll(operation_timeout):
            raise _ProbeDeadline('operation', mode)
        try:
            result = receive.recv()
        except EOFError:
            raise AssertionError(f'{mode} FIFO probe exited during operation') from None
        if timings is not None:
            timings.update(startup_s=startup_elapsed,
                           operation_s=time.monotonic() - operation_started)
        assert result in {'refused', 'cancelled'}, f'{mode} FIFO gate accepted unsafe store: {result}'
        child.join(2)
        assert child.exitcode == 0, f'{mode} FIFO probe exit failed after gate result'
        return result
    finally:
        start.set()
        if started and child.is_alive():
            child.terminate()
            child.join(2)
        if started and child.is_alive():
            child.kill()
            child.join(2)
        send.close()
        receive.close()
        assert not started or not child.is_alive(), f'{mode} FIFO probe could not be reaped'


@pytest.mark.parametrize('mode', ['shared', 'exclusive', 'async_cancel'])
def test_fifo_store_refuses_with_bounded_gate_and_cancellation(tmp_path, mode):
    if not hasattr(os, 'mkfifo'):
        pytest.skip('POSIX FIFO unavailable')
    fifo = tmp_path / 'settings.db'
    os.mkfifo(fifo, 0o600)
    assert _run_special_store_probe(fifo, mode) in {'refused', 'cancelled'}


def test_fifo_probe_distinguishes_slow_startup_from_gate_deadline(tmp_path):
    if not hasattr(os, 'mkfifo'):
        pytest.skip('POSIX FIFO unavailable')
    fifo = tmp_path / 'settings.db'
    os.mkfifo(fifo, 0o600)
    startup_gate = mp.get_context('spawn').Event()
    timings = {}

    def delayed_start(receive):
        assert not receive.poll(0.25), 'child unexpectedly passed the controlled startup gate'
        startup_gate.set()

    assert _run_special_store_probe(fifo, 'shared', startup_gate=startup_gate,
                                    after_start=delayed_start, operation_timeout=0.4,
                                    timings=timings) == 'refused'
    assert timings['startup_s'] >= 0.25
    assert timings['operation_s'] < 0.4


def test_fifo_probe_bounds_startup_and_reaps_child(tmp_path):
    if not hasattr(os, 'mkfifo'):
        pytest.skip('POSIX FIFO unavailable')
    fifo = tmp_path / 'settings.db'
    os.mkfifo(fifo, 0o600)
    startup_gate = mp.get_context('spawn').Event()
    with pytest.raises(_ProbeDeadline, match='startup deadline exceeded') as error:
        _run_special_store_probe(fifo, 'shared', startup_gate=startup_gate,
                                 startup_timeout=0.25)
    assert error.value.phase == 'startup'


def test_fifo_probe_detects_a_deliberately_stalled_operation_and_reaps_child(tmp_path):
    if not hasattr(os, 'mkfifo'):
        pytest.skip('POSIX FIFO unavailable')
    fifo = tmp_path / 'settings.db'
    os.mkfifo(fifo, 0o600)
    operation_gate = mp.get_context('spawn').Event()
    with pytest.raises(_ProbeDeadline, match='operation deadline exceeded') as error:
        _run_special_store_probe(fifo, 'async_cancel', operation_gate=operation_gate,
                                 operation_timeout=0.25)
    assert error.value.phase == 'operation'


def test_crossprocess_shared_lease_refuses_pair_writer_without_partial_batch(store):
    before = settings_db.get_value("system", "error_backlog_sync_enabled")
    ctx = mp.get_context("spawn")
    ready, release = ctx.Event(), ctx.Event()
    child = ctx.Process(target=_hold_shared, args=(str(store), ready, release))
    child.start()
    try:
        assert ready.wait(5)
        revision = provider_selection.current_revision(store)
        with pytest.raises(selection_gates.SelectionBusy):
            provider_selection.compare_and_swap(store, _binding(store),
                                                expected_revision=revision)
        with pytest.raises(selection_gates.SelectionBusy):
            settings_db.apply_import({"system": {"error_backlog_sync_enabled": not before},
                                      "llm": {"compatible_model": "busy-test"}})
        assert settings_db.get_value("system", "error_backlog_sync_enabled") == before
        settings_db.put_category('system', {'error_backlog_sync_enabled': not before})
        assert settings_db.get_value('system', 'error_backlog_sync_enabled') == (not before)
    finally:
        release.set()
        child.join(5)
        assert child.exitcode == 0


def test_crossprocess_shared_lease_fences_all_pair_writer_paths(store, monkeypatch):
    from agents.cli import nerva
    from agents.core import settings_migrate

    settings_db.put_category('llm', {'compatible_model': 'before-reset'})
    assert settings_db.reset_settings('llm') is not None  # Creates an undo snapshot.
    settings_db.get_value('llm', 'compatible_model')  # Complete lazy bootstrap before lease.
    before = settings_db.compatible_pair_state()
    ctx = mp.get_context('spawn')
    ready, release = ctx.Event(), ctx.Event()
    child = ctx.Process(target=_hold_shared, args=(str(store), ready, release))
    child.start()
    try:
        assert ready.wait(5)
        writers = (
            lambda: settings_db.put_category('llm', {'compatible_model': 'blocked'}),
            lambda: settings_db.reset_settings('llm'),
            lambda: settings_db.reset_category('llm'),
            lambda: settings_db.reset_settings(None),
            lambda: settings_db.undo_last_reset(),
            lambda: settings_migrate.apply([settings_migrate.Change(
                'llm.compatible_model', 'seed', None, 'blocked', 'synthetic')]),
            lambda: settings_db.init_db(force=True),
            lambda: settings_db.init_db(),
        )
        for writer in writers:
            with pytest.raises(selection_gates.SelectionBusy):
                writer()
            assert settings_db.compatible_pair_state() == before
        # The CLI uses the same final writer fence and reports retry, never success.
        monkeypatch.setattr(nerva, '_audit_log', lambda: None)
        import io
        out, err = io.StringIO(), io.StringIO()
        code = nerva.main(['config', 'set', 'llm.compatible_model', 'blocked'],
                          context=nerva.Context(environ={}, out=out, err=err))
        assert code != 0 and 'not changed' in err.getvalue()
        assert settings_db.compatible_pair_state() == before
    finally:
        release.set()
        child.join(5)
        assert child.exitcode == 0


def test_selection_lock_rejects_symlink_root_and_unsupported_signed_host(store, tmp_path, monkeypatch):
    alias = tmp_path / "alias.db"
    alias.symlink_to(store)
    with pytest.raises(selection_gates.SelectionUnavailable):
        selection_gates.acquire_shared(alias)
    lock = store.parent / '.settings.db.selection.lock'
    lock.unlink()
    lock.symlink_to(store)
    with pytest.raises(selection_gates.SelectionUnavailable):
        selection_gates.acquire_shared(store)
    lock.unlink()
    revision = provider_selection.current_revision(store)
    monkeypatch.setattr(selection_gates, "fcntl", None)
    with pytest.raises(selection_gates.SelectionUnavailable):
        selection_gates.acquire_shared(store)
    with pytest.raises(selection_gates.SelectionUnavailable):
        provider_selection.compare_and_swap(store, _binding(store),
                                            expected_revision=revision)
    # A nested signed CAS must not inherit a built-in writer's no-flock path.
    with selection_gates.exclusive(store), pytest.raises(selection_gates.SelectionUnavailable):
        provider_selection.compare_and_swap(store, _binding(store),
                                            expected_revision=revision)
    # Ordinary built-in settings remain writable on a host lacking signed leases.
    settings_db.put_category("llm", {"compatible_model": "builtin"})


def test_hardlinked_store_alias_refuses_crossprocess_split_gate(store, tmp_path, monkeypatch):
    ctx = mp.get_context('spawn')
    ready, release = ctx.Event(), ctx.Event()
    child = ctx.Process(target=_hold_shared, args=(str(store), ready, release))
    child.start()
    alias = tmp_path / 'alias.db'
    try:
        assert ready.wait(5)
        os.link(store, alias)
        assert os.stat(store).st_ino == os.stat(alias).st_ino
        monkeypatch.setattr(settings_db, 'DB_PATH', alias)
        with pytest.raises(selection_gates.SelectionUnavailable):
            selection_gates.acquire_shared(alias)
        with pytest.raises(selection_gates.SelectionUnavailable):
            settings_db.put_category('llm', {'compatible_model': 'alias-write'})
    finally:
        monkeypatch.setattr(settings_db, 'DB_PATH', store)
        alias.unlink(missing_ok=True)
        release.set()
        child.join(5)
        assert child.exitcode == 0
    alias.symlink_to(store)
    monkeypatch.setattr(settings_db, 'DB_PATH', alias)
    with pytest.raises(selection_gates.SelectionUnavailable):
        selection_gates.acquire_shared(alias)
    monkeypatch.setattr(settings_db, 'DB_PATH', store)
    alias.unlink()
    with selection_gates.shared(store):
        pass


@pytest.mark.asyncio
async def test_admin_pair_put_sqlite_contention_keeps_loop_live(store, monkeypatch):
    from agents.core.routers import admin

    held = sqlite3.connect(store, check_same_thread=False)

    async def no_retention(_changes, *, confirm=False):
        held.execute('BEGIN IMMEDIATE')
        held.execute("UPDATE settings SET value=value WHERE category='system' AND key='error_backlog_sync_enabled'")
        return [], {}, None

    monkeypatch.setattr(admin, '_retention_gate', no_retention)
    tick = asyncio.Event()
    loop = asyncio.get_running_loop()
    entered_at = []
    real_put = admin.put_category
    release = threading.Timer(0.8, held.rollback)

    def timed_put(*args, **kwargs):
        entered_at.append(time.monotonic())
        loop.call_soon_threadsafe(tick.set)
        release.start()
        return real_put(*args, **kwargs)

    monkeypatch.setattr(admin, 'put_category', timed_put)
    task = asyncio.create_task(admin.admin_put_category('llm', admin.AdminPutBody(values={
        'compatible_model': 'after-sqlite-contention'})))
    try:
        await asyncio.wait_for(tick.wait(), 2)
        assert entered_at and time.monotonic() - entered_at[0] < 0.25
    finally:
        if release.ident is not None:
            release.join(2)
        else:
            held.rollback()
        held.close()
    response = await asyncio.wait_for(task, 2)
    assert response['updated'] == 1
    assert settings_db.get_value('llm', 'compatible_model') == 'after-sqlite-contention'


@pytest.mark.asyncio
async def test_admin_pair_put_sqlite_busy_refuses_without_partial_write(store, monkeypatch):
    from agents.core.routers import admin

    held = sqlite3.connect(store)

    async def no_retention(_changes, *, confirm=False):
        held.execute('BEGIN IMMEDIATE')
        held.execute("UPDATE settings SET value=value WHERE category='system' AND key='error_backlog_sync_enabled'")
        return [], {}, None

    monkeypatch.setattr(admin, '_retention_gate', no_retention)
    before = settings_db.get_value('llm', 'compatible_model')
    tick = asyncio.Event()
    asyncio.get_running_loop().call_later(0.05, tick.set)
    task = asyncio.create_task(admin.admin_put_category('llm', admin.AdminPutBody(values={
        'compatible_model': 'never-committed-busy'})))
    try:
        await asyncio.wait_for(tick.wait(), 0.25)
        response = await asyncio.wait_for(task, 7)
        assert response.status_code == 409
        assert settings_db.get_value('llm', 'compatible_model') == before
    finally:
        held.rollback()
        held.close()


@pytest.mark.asyncio
async def test_cancelled_admin_pair_put_drains_complete_worker(store, monkeypatch):
    from agents.core.routers import admin

    async def no_retention(_changes, *, confirm=False):
        return [], {}, None

    monkeypatch.setattr(admin, '_retention_gate', no_retention)
    real_put = settings_db.put_category
    entered, release = threading.Event(), threading.Event()

    def delayed_put(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return real_put(*args, **kwargs)

    monkeypatch.setattr(admin, 'put_category', delayed_put)
    task = asyncio.create_task(admin.admin_put_category('llm', admin.AdminPutBody(values={
        'compatible_model': 'after-cancelled-route'})))
    assert await asyncio.to_thread(entered.wait, 1)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert settings_db.get_value('llm', 'compatible_model') == 'after-cancelled-route'


def test_cli_guard_rechecks_other_half_after_consent_record(store, monkeypatch):
    from agents.cli import nerva
    from agents.core.llm import selection_guards as guards

    settings_db.put_category('llm', {'compatible_provider': 'openrouter'})
    model = 'meta-llama/llama-4-maverick:free'

    def changed_after_consent(*_args, **_kwargs):
        settings_db.put_category('llm', {'compatible_provider': 'openai-compatible'})

    monkeypatch.setattr(guards, 'record', changed_after_consent)
    lines = nerva._write_setting(
        settings_db, 'llm.compatible_model', 'llm', 'compatible_model', model,
        argparse.Namespace(confirm_expensive=False, acknowledge_training=True))
    assert lines and 'not changed' in lines[0]
    assert settings_db.get_value('llm', 'compatible_provider') == 'openai-compatible'
    assert settings_db.get_value('llm', 'compatible_model') != model


@pytest.mark.asyncio
async def test_cancelled_offloaded_pair_write_drains_durable_result(store):
    from agents.core.routers import admin

    started, release = threading.Event(), threading.Event()

    def delayed_write():
        started.set()
        assert release.wait(2)
        settings_db.put_category('llm', {'compatible_model': 'after-cancel'})

    task = asyncio.create_task(admin._drain_settings_write(delayed_write))
    assert await asyncio.to_thread(started.wait, 1)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    heartbeat = asyncio.Event()
    asyncio.get_running_loop().call_soon(heartbeat.set)
    await asyncio.wait_for(heartbeat.wait(), 0.2)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert settings_db.get_value('llm', 'compatible_model') == 'after-cancel'


@pytest.mark.asyncio
async def test_cancelled_shared_acquire_closes_late_lease(store, monkeypatch):
    started, release = threading.Event(), threading.Event()
    closed = []

    class Lease:
        def close(self):
            closed.append(True)

    def delayed(_path):
        started.set()
        assert release.wait(2)
        return Lease()

    monkeypatch.setattr(selection_gates, 'acquire_shared', delayed)
    task = asyncio.create_task(selection_gates.acquire_shared_async(store))
    assert await asyncio.to_thread(started.wait, 1)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert closed == [True]


@pytest.mark.asyncio
async def test_busy_admin_pair_write_refuses_without_event_loop_wait(store, monkeypatch):
    from agents.core.routers import admin

    settings_db.get_value('llm', 'compatible_model')
    ctx = mp.get_context('spawn')
    ready, release = ctx.Event(), ctx.Event()
    child = ctx.Process(target=_hold_shared, args=(str(store), ready, release))
    child.start()

    async def no_retention(_changes, *, confirm=False):
        return [], {}, None

    monkeypatch.setattr(admin, '_retention_gate', no_retention)
    try:
        assert await asyncio.to_thread(ready.wait, 5)
        tick = asyncio.Event()
        asyncio.get_running_loop().call_soon(tick.set)
        response = await asyncio.wait_for(
            admin.admin_put_category('llm', admin.AdminPutBody(values={
                'compatible_model': 'busy-model'})), 0.5)
        assert tick.is_set() and response.status_code == 409
        assert settings_db.get_value('llm', 'compatible_model') != 'busy-model'
    finally:
        release.set()
        child.join(5)
        assert child.exitcode == 0


@pytest.mark.asyncio
async def test_admin_other_half_changed_during_retention_await_refuses_stale_guard(store, monkeypatch):
    from agents.core.routers import admin

    settings_db.put_category('llm', {'compatible_provider': 'openai-compatible'})
    model = 'meta-llama/llama-4-maverick:free'

    async def changed_other_half(_changes, *, confirm=False):
        settings_db.put_category('llm', {'compatible_provider': 'openrouter'})
        return [], {}, None

    monkeypatch.setattr(admin, '_retention_gate', changed_other_half)
    response = await admin.admin_put_category('llm', admin.AdminPutBody(values={
        'compatible_model': model}))
    assert response.status_code == 409
    assert settings_db.get_value('llm', 'compatible_provider') == 'openrouter'
    assert settings_db.get_value('llm', 'compatible_model') != model
