"""The stall watcher observes processing progress, never inbound arrival."""

import asyncio
import math

import pytest

from agents.core.channels.session_stall import StallWatcher


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_pending_inbound_without_known_progress_never_notifies():
    async def scenario():
        clock = Clock()
        watcher = StallWatcher(clock=clock)
        token = watcher.begin("route")
        calls = []

        async def notify(*args):
            calls.append(args)
            return True

        clock.advance(900)
        assert watcher.matches("route", token)
        assert await watcher.check(30, notify) == 0
        assert calls == []

    asyncio.run(scenario())


def test_exact_episode_token_guards_progress_and_completion():
    async def scenario():
        clock = Clock()
        watcher = StallWatcher(clock=clock)
        old = watcher.begin("route")
        current = watcher.begin("route")
        assert current != old
        assert not watcher.progress("route", old)
        assert not watcher.finish("route", old)
        assert watcher.matches("route", current)
        assert watcher.progress("route", current)
        clock.advance(31)
        delivered = []

        async def notify(key, token, idle):
            delivered.append((key, token, idle))
            return True

        assert await watcher.check(30, notify) == 1
        assert delivered == [("route", current, 31.0)]
        assert watcher.finish("route", current)
        assert not watcher.matches("route", current)
        assert await watcher.check(30, notify) == 0

    asyncio.run(scenario())


def test_bool_and_noninteger_tokens_cannot_match_an_episode():
    watcher = StallWatcher(clock=Clock())
    token = watcher.begin("route")
    assert token == 1
    for wrong in (True, 1.0, "1"):
        assert not watcher.matches("route", wrong)
        assert not watcher.progress("route", wrong)
        assert not watcher.finish("route", wrong)
    assert watcher.matches("route", token)


def test_episode_keys_must_be_bounded_nonempty_strings():
    watcher = StallWatcher(clock=Clock())
    for invalid in ("", "  ", "x" * 1025, 42, object()):
        with pytest.raises((TypeError, ValueError)):
            watcher.begin(invalid)
    assert watcher.begin("x" * 1024) == 1


def test_is_due_rechecks_progress_token_and_live_timeout():
    clock = Clock()
    watcher = StallWatcher(clock=clock)
    token = watcher.begin("route")
    assert not watcher.is_due("route", token, 30)
    assert watcher.progress("route", token)
    clock.advance(30)
    assert watcher.is_due("route", token, 30)
    assert not watcher.is_due("route", token, 0)
    assert not watcher.is_due("route", True, 30)
    assert watcher.progress("route", token)
    assert not watcher.is_due("route", token, 30)
    clock.advance(30)
    assert watcher.is_due("route", token, 30)
    assert watcher.finish("route", token)
    assert not watcher.is_due("route", token, 30)


def test_success_latches_until_real_progress_or_new_episode():
    async def scenario():
        clock = Clock()
        watcher = StallWatcher(clock=clock)
        token = watcher.begin("route")
        watcher.progress("route", token)
        clock.advance(30)
        calls = []

        async def notify(*args):
            calls.append(args)
            return True

        assert await watcher.check(30, notify) == 1
        assert await watcher.check(30, notify) == 0
        assert watcher.progress("route", token)
        clock.advance(30)
        assert await watcher.check(30, notify) == 1
        assert watcher.finish("route", token)
        replacement = watcher.begin("route")
        assert replacement != token
        assert await watcher.check(30, notify) == 0
        assert len(calls) == 2

    asyncio.run(scenario())


def test_recovery_or_drain_while_sibling_send_waits_skips_stale_candidate():
    async def scenario():
        clock = Clock()
        watcher = StallWatcher(clock=clock)
        first = watcher.begin("first")
        second = watcher.begin("second")
        watcher.progress("first", first)
        watcher.progress("second", second)
        clock.advance(30)
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def notify(key, token, idle):
            calls.append(key)
            if key == "first":
                entered.set()
                await release.wait()
            return True

        task = asyncio.create_task(watcher.check(30, notify))
        await entered.wait()
        watcher.progress("second", second)
        release.set()
        assert await task == 1
        assert calls == ["first"]
        watcher.finish("first", first)
        clock.advance(30)
        assert await watcher.check(30, notify) == 1
        assert calls == ["first", "second"]

    asyncio.run(scenario())


def test_false_error_and_timeout_retry_without_latching(monkeypatch):
    async def scenario():
        from agents.core.channels import session_stall

        monkeypatch.setattr(session_stall, "_SEND_TIMEOUT_SECONDS", 0.01)
        clock = Clock()
        watcher = StallWatcher(clock=clock)
        token = watcher.begin("route")
        watcher.progress("route", token)
        clock.advance(30)
        attempts = 0

        async def notify(*args):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return False
            if attempts == 2:
                raise RuntimeError("send failed")
            if attempts == 3:
                await asyncio.Event().wait()
            return True

        assert await watcher.check(30, notify) == 0
        assert await watcher.check(30, notify) == 0
        assert await watcher.check(30, notify) == 0
        # The canceled send is retained until its task has actually settled.
        for _ in range(3):
            if watcher.pending_send_count == 0:
                break
            await asyncio.sleep(0)
        assert watcher.pending_send_count == 0
        assert await watcher.check(30, notify) == 1
        assert attempts == 4

    asyncio.run(scenario())


def test_cancel_resistant_send_does_not_hold_pass_or_spawn_duplicate(monkeypatch):
    async def scenario():
        from agents.core.channels import session_stall

        monkeypatch.setattr(session_stall, "_SEND_TIMEOUT_SECONDS", 0.01)
        clock = Clock()
        watcher = StallWatcher(clock=clock)
        token = watcher.begin("route")
        watcher.progress("route", token)
        clock.advance(30)
        started = asyncio.Event()
        cancelled = asyncio.Event()
        release = asyncio.Event()
        attempts = 0

        async def notify(*args):
            nonlocal attempts
            attempts += 1
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
                return True

        check = asyncio.create_task(watcher.check(30, notify))
        try:
            await started.wait()
            await cancelled.wait()
            await asyncio.sleep(0.03)
            assert check.done(), "a cancellation-resistant send held the watcher pass"
            assert await check == 0
            assert watcher.pending_send_count == 1
            assert await watcher.check(30, notify) == 0
            assert attempts == 1
        finally:
            release.set()
            await check
            await asyncio.sleep(0)
        assert watcher.pending_send_count == 0
        assert await watcher.check(30, lambda *_: asyncio.sleep(0, result=True)) == 1

    asyncio.run(scenario())


def test_close_bounds_stubborn_send_and_disables_new_episodes(monkeypatch):
    async def scenario():
        from agents.core.channels import session_stall

        monkeypatch.setattr(session_stall, "_SEND_TIMEOUT_SECONDS", 0.01)
        clock = Clock()
        watcher = StallWatcher(clock=clock)
        token = watcher.begin("route")
        assert watcher.progress("route", token)
        clock.advance(30)
        started = asyncio.Event()
        cancelled = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def stubborn(*args):
            nonlocal calls
            calls += 1
            started.set()
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    cancelled.set()
            return True

        check = asyncio.create_task(watcher.check(30, stubborn))
        try:
            await started.wait()
            await cancelled.wait()
            assert await check == 0
            before = asyncio.get_running_loop().time()
            assert await watcher.close(timeout=0.01) == 1
            assert asyncio.get_running_loop().time() - before < 0.2
            assert watcher.pending_send_count == 1
            assert not watcher.matches("route", token)
            assert not watcher.progress("route", token)
            assert not watcher.is_due("route", token, 30)
            with pytest.raises(RuntimeError):
                watcher.begin("new")
            assert await watcher.check(30, stubborn) == 0
            assert calls == 1
        finally:
            release.set()
            await check
            for _ in range(3):
                if watcher.pending_send_count == 0:
                    break
                await asyncio.sleep(0)
        assert watcher.pending_send_count == 0
        assert await watcher.close(timeout=0) == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("bad", [True, "2", -1, math.nan, math.inf])
def test_close_rejects_invalid_timeout_without_closing(bad):
    async def scenario():
        watcher = StallWatcher(clock=Clock())
        with pytest.raises((TypeError, ValueError)):
            await watcher.close(timeout=bad)
        assert watcher.begin("route") == 1

    asyncio.run(scenario())


def test_progress_during_successful_send_does_not_latch_rearmed_activity():
    async def scenario():
        clock = Clock()
        watcher = StallWatcher(clock=clock)
        token = watcher.begin("route")
        watcher.progress("route", token)
        clock.advance(30)
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def notify(*args):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return True

        check = asyncio.create_task(watcher.check(30, notify))
        await started.wait()
        assert watcher.progress("route", token)
        release.set()
        assert await check == 1
        assert await watcher.check(30, notify) == 0
        clock.advance(30)
        assert await watcher.check(30, notify) == 1
        assert calls == 2

    asyncio.run(scenario())


def test_overlapping_checks_serialize_and_cancellation_propagates():
    async def scenario():
        clock = Clock()
        watcher = StallWatcher(clock=clock)
        token = watcher.begin("route")
        watcher.progress("route", token)
        clock.advance(30)
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def notify(*args):
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return True

        first = asyncio.create_task(watcher.check(30, notify))
        await entered.wait()
        second = asyncio.create_task(watcher.check(30, notify))
        await asyncio.sleep(0)
        assert calls == 1
        release.set()
        assert await first == 1
        assert await second == 0

        watcher.progress("route", token)
        clock.advance(30)
        release.clear()
        entered.clear()
        blocked = asyncio.create_task(watcher.check(30, notify))
        await entered.wait()
        blocked.cancel()
        try:
            await blocked
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancellation was swallowed")
        release.set()
        assert await watcher.check(30, notify) == 1

    asyncio.run(scenario())


def test_notifier_self_cancellation_retries_and_does_not_skip_due_sibling():
    async def scenario():
        clock = Clock()
        watcher = StallWatcher(clock=clock)
        first = watcher.begin("first")
        second = watcher.begin("second")
        assert watcher.progress("first", first)
        assert watcher.progress("second", second)
        clock.advance(30)
        calls = []

        async def notify(key, token, idle):
            calls.append(key)
            if key == "first" and calls.count("first") == 1:
                asyncio.current_task().cancel()
                await asyncio.sleep(0)
            return True

        assert await watcher.check(30, notify) == 1
        assert calls == ["first", "second"]
        assert await watcher.check(30, notify) == 1
        assert calls == ["first", "second", "first"]
        assert await watcher.check(30, notify) == 0

    asyncio.run(scenario())


def test_zero_timeout_disables_and_clears_latch_nonfinite_clock_fails_closed():
    async def scenario():
        clock = Clock()
        watcher = StallWatcher(clock=clock)
        token = watcher.begin("route")
        watcher.progress("route", token)
        clock.advance(30)
        calls = []

        async def notify(*args):
            calls.append(args)
            return True

        assert await watcher.check(30, notify) == 1
        assert await watcher.check(0, notify) == 0
        assert await watcher.check(30, notify) == 1
        clock.now = math.nan
        assert not watcher.progress("route", token)
        assert await watcher.check(30, notify) == 0
        assert await watcher.check(math.inf, notify) == 0
        assert len(calls) == 2

    asyncio.run(scenario())


def test_capacity_refuses_new_episode_without_dropping_existing():
    watcher = StallWatcher(clock=Clock())
    tokens = [watcher.begin(f"route-{n}") for n in range(4096)]
    try:
        watcher.begin("overflow")
    except OverflowError:
        pass
    else:
        raise AssertionError("capacity was not enforced")
    assert watcher.matches("route-0", tokens[0])
    assert watcher.finish("route-0", tokens[0])
    assert watcher.begin("overflow") is not None
