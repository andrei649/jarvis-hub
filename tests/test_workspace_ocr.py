"""Optional OCR is bounded and is reachable only through the extraction child."""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import suppress
from types import SimpleNamespace

import pytest

from agents.core.workspace import extract
from tests.fixtures.workspace import samples
from tests.fixtures.workspace.doc_helpers import docs_client, upload
from tests.support.workspace_fixtures import (  # noqa: F401 (ws is a fixture)
    authed,
    db,
    login,
    seed_company,
    ws,
)

_FAKE_ENGINE_PATCH = (
    "from tests.support.workspace_ocr_page import fake_engine; "
    "extract._ocr_engine = lambda: fake_engine; "
)


def _owned_script(monkeypatch, script: str) -> None:
    from agents.core.workspace import extract_process

    monkeypatch.setattr(extract_process, "_owned_command",
                        lambda: [sys.executable, "-c", script])


def _capture_owned(monkeypatch, script: str) -> tuple[dict, object, object]:
    from agents.core.workspace import extract_process

    command = extract_process._owned_command
    spawn = extract_process._spawn_owned
    captured = {}
    _owned_script(monkeypatch, script)

    def capture(kind, seconds, env):
        captured["scratch"] = env["TMPDIR"]
        process = spawn(kind, seconds, env)
        captured["process"] = process
        return process

    monkeypatch.setattr(extract_process, "_spawn_owned", capture)
    return captured, command, spawn


@pytest.fixture(autouse=True)
def opt_in(monkeypatch):
    monkeypatch.setenv("NERVA_WORKSPACE_KILLABLE_EXTRACTION", "1")
    monkeypatch.setenv("NERVA_WORKSPACE_OCR", "1")


def test_sync_entry_does_not_invoke_native_engine(monkeypatch):
    def forbidden():
        pytest.fail("synchronous extraction reached the native OCR engine")

    monkeypatch.setattr(extract, "_ocr_engine", forbidden, raising=False)
    with pytest.raises(extract.ExtractionError) as caught:
        extract.extract_bytes(samples.build_blank_pdf(1), "pdf")
    assert caught.value.code == "no_text"


def test_windows_native_ocr_fails_closed_without_job_containment(monkeypatch):
    monkeypatch.setattr(extract.sys, "platform", "win32")
    monkeypatch.setattr(extract, "_ocr_engine", lambda: pytest.fail("engine invoked"))
    assert extract._ocr_pdf(b"ignored", 1, extract._Guard(1, 100)) is None


@pytest.mark.parametrize("flag", ["NERVA_WORKSPACE_OCR", "NERVA_WORKSPACE_KILLABLE_EXTRACTION"])
async def test_ocr_needs_both_flags(monkeypatch, flag):
    monkeypatch.delenv(flag)
    with pytest.raises(extract.ExtractionError) as caught:
        await extract.extract_document(samples.build_blank_pdf(1), "pdf")
    assert caught.value.code == "no_text"


async def test_enabled_child_without_engine_keeps_no_text(monkeypatch):
    script = (
        "from agents.core.workspace import extract; "
        "extract._ocr_engine = lambda: None; "
        "from agents.core.workspace.extract_process import _worker; _worker()"
    )
    _owned_script(monkeypatch, script)
    with pytest.raises(extract.ExtractionError) as caught:
        await extract.extract_document(samples.build_blank_pdf(1), "pdf")
    assert caught.value.code == "no_text"


@pytest.mark.skipif(os.name == "nt", reason="native OCR is disabled on Windows")
async def test_real_child_reports_ocr_marker_and_page_text(monkeypatch):
    script = (
        "import sys; from agents.core.workspace import extract; "
        + _FAKE_ENGINE_PATCH +
        "from agents.core.workspace.extract_process import _worker; _worker()"
    )
    _owned_script(monkeypatch, script)
    result = await extract.extract_document(samples.build_blank_pdf(2), "pdf")
    assert [(s.page, s.text) for s in result.segments] == [
        (1, "Scannedword page 1"), (2, "Scannedword page 2")]
    assert "ocr" in result.limits
    assert "wall_time" in result.limits


async def test_text_layer_never_calls_ocr_engine(monkeypatch):
    script = (
        "from agents.core.workspace import extract; "
        "extract._ocr_engine = lambda: (_ for _ in ()).throw(AssertionError('OCR called')); "
        "from agents.core.workspace.extract_process import _worker; _worker()"
    )
    _owned_script(monkeypatch, script)
    result = await extract.extract_document(samples.build_pdf(), "pdf")
    assert result.char_count > 0
    assert "ocr" not in result.limits


@pytest.mark.skipif(os.name == "nt", reason="native OCR is disabled on Windows")
async def test_failed_second_ocr_page_fails_whole_document(monkeypatch):
    script = (
        "import sys; from agents.core.workspace import extract; "
        + _FAKE_ENGINE_PATCH +
        "from agents.core.workspace.extract_process import _worker; _worker()"
    )
    _owned_script(monkeypatch, script)
    monkeypatch.setenv("NERVA_TEST_OCR_MODE", "fail_second")
    with pytest.raises(extract.ExtractionError) as caught:
        await extract.extract_document(samples.build_blank_pdf(2), "pdf")
    assert caught.value.code == "invalid_file"
    assert caught.value.page_count == 2


@pytest.mark.skipif(os.name == "nt", reason="native OCR is disabled on Windows")
async def test_native_c_page_timeout_fails_whole_child_and_frees_slot(monkeypatch):
    from agents.core.workspace import extract_process

    real_owned_command = extract_process._owned_command
    script = (
        "import sys; from agents.core.workspace import extract; "
        + _FAKE_ENGINE_PATCH +
        "extract.OCR_PAGE_TIMEOUT_SECONDS = 0.02; "
        "from agents.core.workspace.extract_process import _worker; _worker()"
    )
    _owned_script(monkeypatch, script)
    monkeypatch.setenv("NERVA_TEST_OCR_MODE", "c_stall")
    started = time.monotonic()
    with pytest.raises(extract.ExtractionError) as caught:
        await extract.extract_document(samples.build_blank_pdf(2), "pdf", timeout=3)
    assert caught.value.code == "timeout" and caught.value.page_count == 2
    assert time.monotonic() - started < 1.5
    monkeypatch.setattr(extract_process, "_owned_command", real_owned_command)
    monkeypatch.delenv("NERVA_TEST_OCR_MODE")
    assert (await extract.extract_document(samples.build_docx(), "docx")).char_count > 0


@pytest.mark.skipif(os.name == "nt", reason="native OCR is disabled on Windows")
def test_ocr_page_cap_and_text_budget(monkeypatch):
    monkeypatch.setattr(extract, "_ocr_engine", lambda: lambda *_: "More than ten chars")

    def progress(*_):
        return None
    with pytest.raises(extract.ExtractionError) as caught:
        extract._ocr_pdf(b"ignored", extract.MAX_OCR_PAGES + 1,
                         extract._Guard(1, 100), progress=progress)
    assert caught.value.code == "too_many_pages"
    with pytest.raises(extract.ExtractionError) as caught:
        extract._ocr_pdf(b"ignored", 1, extract._Guard(1, 10), progress=progress)
    assert caught.value.code == "too_much_text"


@pytest.mark.skipif(os.name == "nt", reason="native OCR is disabled on Windows")
def test_ocr_page_budget_includes_engine_work(monkeypatch):
    def slow(*_):
        time.sleep(0.03)
        return "Page text"

    monkeypatch.setattr(extract, "_ocr_engine", lambda: slow)
    with pytest.raises(extract.ExtractionError) as caught:
        extract._ocr_pdf(b"ignored", 1, extract._Guard(0.01, 100),
                         progress=lambda *_: None)
    assert caught.value.code == "timeout"


def test_ocr_render_consumes_engine_budget_without_rounding(monkeypatch):
    calls = []

    class FakePage:
        def render(self, *, scale):
            assert scale == extract.OCR_RENDER_SCALE
            time.sleep(0.02)
            return SimpleNamespace(to_pil=lambda: object())

    class FakeDocument:
        def __init__(self, data):
            assert data == b"pdf"

        def __getitem__(self, index):
            assert index == 0
            return FakePage()

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "pypdfium2", SimpleNamespace(PdfDocument=FakeDocument))
    monkeypatch.setitem(sys.modules, "pytesseract", SimpleNamespace(
        image_to_string=lambda *a, **kw: calls.append(kw["timeout"])))
    monkeypatch.setattr(extract.shutil, "which", lambda command: "/bin/true")
    reader = extract._ocr_engine()
    assert reader is not None
    with pytest.raises(TimeoutError):
        reader(b"pdf", 0, 0.01)
    assert calls == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX per-page timer")
def test_ocr_render_is_interrupted_at_page_deadline(monkeypatch):
    class SlowPage:
        def render(self, *, scale):
            time.sleep(0.2)
            return SimpleNamespace(to_pil=lambda: object())

    class FakeDocument:
        def __init__(self, data):
            pass

        def __getitem__(self, index):
            return SlowPage()

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "pypdfium2", SimpleNamespace(PdfDocument=FakeDocument))
    monkeypatch.setitem(sys.modules, "pytesseract", SimpleNamespace(
        image_to_string=lambda *a, **kw: pytest.fail("engine invoked")))
    monkeypatch.setattr(extract.shutil, "which", lambda command: "/bin/true")
    reader = extract._ocr_engine()
    assert reader is not None
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        reader(b"pdf", 0, 0.02)
    assert time.monotonic() - started < 0.1


@pytest.mark.skipif(os.name == "nt", reason="native OCR is disabled on Windows")
def test_ocr_memory_error_and_incomplete_page_are_failures(monkeypatch):
    def memory(*_):
        raise MemoryError("resource ceiling")

    monkeypatch.setattr(extract, "_ocr_engine", lambda: memory)
    with pytest.raises(MemoryError):
        extract._ocr_pdf(b"ignored", 1, extract._Guard(1, 100),
                         progress=lambda *_: None)
    monkeypatch.setattr(extract, "_ocr_engine", lambda: lambda _, index, __:
                        "" if index == 0 else "Second page text")
    with pytest.raises(extract.ExtractionError) as caught:
        extract._ocr_pdf(b"ignored", 2, extract._Guard(1, 100),
                         progress=lambda *_: None)
    assert caught.value.code == "no_text"
    assert caught.value.page_count == 2


@pytest.mark.skipif(os.name == "nt", reason="POSIX owner group proof")
async def test_document_handle_is_drained_when_both_enumerators_fail(monkeypatch):
    from agents.core.workspace import extract_process

    real_members = extract_process._session_members
    real_kernel = extract_process._kernel_session_members
    captured, command, spawn = _capture_owned(monkeypatch, "import time; time.sleep(120)")

    async def idle_watch(sid, stop, fault, signaled):
        await stop.wait()

    monkeypatch.setattr(extract_process, "_session_members", lambda sid: None)
    monkeypatch.setattr(extract_process, "_kernel_session_members", lambda sid: None)
    monkeypatch.setattr(extract_process, "_watch_owned_memory", idle_watch)
    with pytest.raises(extract.ExtractionError) as caught:
        await extract.extract_document(b"x", "pdf", timeout=0.2)
    assert caught.value.code == "timeout"
    assert captured["process"].returncode is not None
    assert not os.path.exists(captured["scratch"])
    monkeypatch.setattr(extract_process, "_owned_command", command)
    monkeypatch.setattr(extract_process, "_spawn_owned", spawn)
    monkeypatch.setattr(extract_process, "_session_members", real_members)
    monkeypatch.setattr(extract_process, "_kernel_session_members", real_kernel)
    assert (await extract.extract_document(samples.build_docx(), "docx")).char_count > 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX owner group proof")
@pytest.mark.parametrize("ending", ["cancel", "deadline", "leader_exit"])
async def test_owned_cleanup_survives_dual_enumerator_failure(
        monkeypatch, tmp_path, ending):
    from agents.core.workspace import extract_process

    real_members = extract_process._session_members
    real_kernel = extract_process._kernel_session_members
    pid_file = tmp_path / "native.pid"
    script = (
        "from agents.core.workspace import extract; "
        + _FAKE_ENGINE_PATCH +
        "from agents.core.workspace.extract_process import _worker; _worker()"
    )
    captured, command, spawn = _capture_owned(monkeypatch, script)

    async def idle_watch(sid, stop, fault, signaled):
        await stop.wait()

    mode = "early_exit_descendant" if ending == "leader_exit" else "sleep_descendant"
    monkeypatch.setenv("NERVA_TEST_OCR_MODE", mode)
    monkeypatch.setenv("NERVA_TEST_OCR_PID_FILE", str(pid_file))
    monkeypatch.setattr(extract_process, "_session_members", lambda sid: None)
    monkeypatch.setattr(extract_process, "_kernel_session_members", lambda sid: None)
    monkeypatch.setattr(extract_process, "_watch_owned_memory", idle_watch)
    task = asyncio.create_task(extract.extract_document(
        samples.build_blank_pdf(1), "pdf", timeout=0.8 if ending == "deadline" else 4))
    try:
        for _ in range(200):
            if pid_file.exists():
                break
            await asyncio.sleep(0.01)
        assert pid_file.exists()
        if ending == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(extract.ExtractionError) as caught:
                await task
            assert caught.value.code == ("timeout" if ending == "deadline" else "invalid_file")
        assert not os.path.exists(captured["scratch"])
        assert captured["process"].returncode is not None
        grandchild = int(pid_file.read_text())
        status = subprocess.run(["ps", "-o", "stat=", "-p", str(grandchild)],
                                capture_output=True, check=False).stdout.strip()
        assert not status or status.startswith(b"Z")
        monkeypatch.setattr(extract_process, "_owned_command", command)
        monkeypatch.setattr(extract_process, "_spawn_owned", spawn)
        monkeypatch.setattr(extract_process, "_session_members", real_members)
        monkeypatch.setattr(extract_process, "_kernel_session_members", real_kernel)
        monkeypatch.delenv("NERVA_TEST_OCR_MODE")
        assert (await extract.extract_document(samples.build_docx(), "docx")).char_count > 0
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError, extract.ExtractionError):
                await task
        if pid_file.exists():
            with suppress(ProcessLookupError):
                child = int(pid_file.read_text())
                if os.getsid(child) != os.getsid(0):
                    os.killpg(os.getpgid(child), signal.SIGKILL)


@pytest.mark.skipif(os.name == "nt", reason="native OCR is disabled on Windows")
@pytest.mark.parametrize("mode", ["hang_descendant", "early_exit_descendant"])
async def test_ocr_owned_group_survives_dual_enumerator_failure_until_kill(
        monkeypatch, tmp_path, mode):
    from agents.core.workspace import extract_process

    real_spawn = extract_process._spawn_owned
    pid_file = tmp_path / "native.pid"
    scratch = None
    script = (
        "import sys; from agents.core.workspace import extract; "
        "from tests.support.workspace_ocr_page import fake_engine; "
        "extract._ocr_engine = lambda: fake_engine; "
        f"extract.OCR_PAGE_TIMEOUT_SECONDS = {0.5 if mode == 'early_exit_descendant' else 0.1}; "
        "from agents.core.workspace.extract_process import _worker; _worker()"
    )

    def spawn(kind, seconds, env):
        nonlocal scratch
        scratch = env["TMPDIR"]
        return real_spawn(kind, seconds, env)

    async def idle_watch(sid, stop, fault, signaled):
        await stop.wait()

    monkeypatch.setenv("NERVA_TEST_OCR_MODE", mode)
    monkeypatch.setenv("NERVA_TEST_OCR_PID_FILE", str(pid_file))
    monkeypatch.setattr(extract_process, "_session_members", lambda sid: None)
    monkeypatch.setattr(extract_process, "_kernel_session_members", lambda sid: None)
    monkeypatch.setattr(extract_process, "_watch_owned_memory", idle_watch)
    monkeypatch.setattr(extract_process, "_owned_command", lambda: [sys.executable, "-c", script])
    monkeypatch.setattr(extract_process, "_spawn_owned", spawn)
    try:
        with pytest.raises(extract.ExtractionError) as caught:
            await extract.extract_document(samples.build_blank_pdf(1), "pdf", timeout=2)
        assert caught.value.code == ("timeout" if mode == "hang_descendant" else "invalid_file")
        assert scratch is not None and not os.path.exists(scratch)
        child = int(pid_file.read_text())
        status = subprocess.run(["ps", "-o", "stat=", "-p", str(child)],
                                capture_output=True, check=False).stdout.strip()
        assert not status or status.startswith(b"Z")
    finally:
        if pid_file.exists():
            with suppress(ProcessLookupError):
                child = int(pid_file.read_text())
                if os.getsid(child) != os.getsid(0):
                    os.killpg(os.getpgid(child), signal.SIGKILL)


@pytest.mark.skipif(os.name == "nt", reason="native OCR is disabled on Windows")
@pytest.mark.parametrize("mode", ["normal_descendant", "error_descendant",
                                    "early_exit_descendant", "sleep_descendant"])
async def test_owned_ocr_reaps_native_descendants_without_enumeration(
        monkeypatch, tmp_path, mode):
    from agents.core.workspace import extract_process

    pid_file = tmp_path / "native.pid"
    script = (
        "from agents.core.workspace import extract; "
        + _FAKE_ENGINE_PATCH +
        "extract.OCR_PAGE_TIMEOUT_SECONDS = 0.3; "
        "from agents.core.workspace.extract_process import _worker; _worker()"
    )
    captured, _, _ = _capture_owned(monkeypatch, script)

    async def idle_watch(sid, stop, fault, signaled):
        await stop.wait()

    monkeypatch.setenv("NERVA_TEST_OCR_MODE", mode)
    monkeypatch.setenv("NERVA_TEST_OCR_PID_FILE", str(pid_file))
    monkeypatch.setattr(extract_process, "_session_members", lambda sid: None)
    monkeypatch.setattr(extract_process, "_kernel_session_members", lambda sid: None)
    monkeypatch.setattr(extract_process, "_watch_owned_memory", idle_watch)
    try:
        if mode == "normal_descendant":
            result = await extract.extract_document(samples.build_blank_pdf(1), "pdf", timeout=2)
            assert result.segments[0].text == "Scannedword page 1"
            assert "ocr" in result.limits
        else:
            with pytest.raises(extract.ExtractionError) as caught:
                await extract.extract_document(samples.build_blank_pdf(1), "pdf", timeout=2)
            assert caught.value.code == ("timeout" if mode == "sleep_descendant"
                                         else "invalid_file")
        assert not os.path.exists(captured["scratch"])
        child = int(pid_file.read_text())
        status = subprocess.run(["ps", "-o", "stat=", "-p", str(child)],
                                capture_output=True, check=False).stdout.strip()
        assert not status or status.startswith(b"Z")
    finally:
        if pid_file.exists():
            with suppress(ProcessLookupError):
                child = int(pid_file.read_text())
                if os.getsid(child) != os.getsid(0):
                    os.killpg(os.getpgid(child), signal.SIGKILL)


@pytest.mark.skipif(os.name == "nt", reason="POSIX owned memory refusal proof")
async def test_memory_sampler_failure_kills_owned_native_descendant(monkeypatch, tmp_path):
    from agents.core.workspace import extract_process

    pid_file = tmp_path / "native.pid"
    script = (
        "from agents.core.workspace import extract; "
        + _FAKE_ENGINE_PATCH +
        "from agents.core.workspace.extract_process import _worker; _worker()"
    )
    captured, _, _ = _capture_owned(monkeypatch, script)
    real_members = extract_process._session_members
    unavailable = threading.Event()

    def members(sid):
        return None if unavailable.is_set() else real_members(sid)

    monkeypatch.setattr(extract_process, "_session_members", members)
    monkeypatch.setattr(extract_process, "_kernel_session_members", lambda sid: None)
    monkeypatch.setenv("NERVA_TEST_OCR_MODE", "sleep_descendant")
    monkeypatch.setenv("NERVA_TEST_OCR_PID_FILE", str(pid_file))
    task = asyncio.create_task(extract.extract_document(samples.build_blank_pdf(1),
                                                        "pdf", timeout=3))
    for _ in range(200):
        if pid_file.exists():
            break
        await asyncio.sleep(0.01)
    assert pid_file.exists()
    unavailable.set()
    with pytest.raises(extract.ExtractionError) as caught:
        await task
    assert caught.value.code == "invalid_file"
    assert not os.path.exists(captured["scratch"])
    child = int(pid_file.read_text())
    status = subprocess.run(["ps", "-o", "stat=", "-p", str(child)],
                            capture_output=True, check=False).stdout.strip()
    assert not status or status.startswith(b"Z")


@pytest.mark.skipif(os.name == "nt", reason="POSIX group identity proof")
async def test_group_is_signaled_while_original_leader_pid_is_reserved(monkeypatch, tmp_path):
    from agents.core.workspace import extract_process

    pid_file = tmp_path / "native.pid"
    script = (
        "from agents.core.workspace import extract; "
        + _FAKE_ENGINE_PATCH +
        "from agents.core.workspace.extract_process import _worker; _worker()"
    )
    _owned_script(monkeypatch, script)
    real_spawn = extract_process._spawn_owned
    real_killpg = os.killpg
    events = []
    captured = {}

    def spawn(kind, seconds, env):
        process = real_spawn(kind, seconds, env)
        captured["process"] = process
        captured["scratch"] = env["TMPDIR"]
        real_wait = process.wait

        def wait(*args, **kwargs):
            assert events == [("kill", process.pid)]
            events.append(("wait", process.pid))
            return real_wait(*args, **kwargs)

        process.wait = wait
        return process

    def killpg(pgid, sig):
        process = captured["process"]
        assert pgid == process.pid and sig == signal.SIGKILL
        assert process.returncode is None  # Popen has not waited or polled
        assert os.kill(process.pid, 0) is None  # the original PID is still reserved
        native = int(pid_file.read_text())
        assert os.getsid(native) == process.pid
        assert os.getpgid(native) == process.pid
        events.append(("kill", pgid))
        return real_killpg(pgid, sig)

    async def idle_watch(sid, stop, fault, signaled):
        await stop.wait()

    monkeypatch.setenv("NERVA_TEST_OCR_MODE", "early_exit_descendant")
    monkeypatch.setenv("NERVA_TEST_OCR_PID_FILE", str(pid_file))
    monkeypatch.setattr(extract_process, "_spawn_owned", spawn)
    monkeypatch.setattr(extract_process, "_watch_owned_memory", idle_watch)
    monkeypatch.setattr(extract_process.os, "killpg", killpg)
    with pytest.raises(extract.ExtractionError) as caught:
        await extract.extract_document(samples.build_blank_pdf(1), "pdf", timeout=3)
    assert caught.value.code == "invalid_file"
    assert events == [("kill", captured["process"].pid),
                      ("wait", captured["process"].pid)]
    assert not os.path.exists(captured["scratch"])
    native = int(pid_file.read_text())
    status = subprocess.run(["ps", "-o", "stat=", "-p", str(native)],
                            capture_output=True, check=False).stdout.strip()
    assert not status or status.startswith(b"Z")


@pytest.mark.skipif(os.name == "nt", reason="POSIX owned launch proof")
async def test_cancellation_during_owned_launch_reaps_before_slot_release(monkeypatch):
    from agents.core.workspace import extract_process

    started = threading.Event()
    release = threading.Event()
    real_spawn = extract_process._spawn_owned
    captured = {}
    _owned_script(monkeypatch, "import time; time.sleep(120)")

    def delayed(kind, seconds, env):
        captured["scratch"] = env["TMPDIR"]
        started.set()
        assert release.wait(2)
        child = real_spawn(kind, seconds, env)
        captured["process"] = child
        return child

    monkeypatch.setattr(extract_process, "_spawn_owned", delayed)
    task = asyncio.create_task(extract.extract_document(b"x", "pdf", timeout=3))
    assert await asyncio.to_thread(started.wait, 1)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert captured["process"].returncode is not None
    assert not os.path.exists(captured["scratch"])


@pytest.mark.skipif(os.name == "nt", reason="POSIX owned queue proof")
async def test_owned_ocr_queue_deadline_counts_before_launch(monkeypatch):
    from agents.core.workspace import extract_process

    def forbidden_command():
        pytest.fail("queued OCR started after its deadline")

    monkeypatch.setattr(extract_process, "_owned_command", forbidden_command)
    assert extract_process._SLOTS.acquire(blocking=False)
    assert extract_process._SLOTS.acquire(blocking=False)
    try:
        with pytest.raises(extract.ExtractionError) as caught:
            await extract.extract_document(b"x", "pdf", timeout=0.03)
        assert caught.value.code == "timeout"
    finally:
        extract_process._SLOTS.release()
        extract_process._SLOTS.release()


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS sampled-RSS fallback")
async def test_mac_memory_watchdog_refuses_over_budget_child(monkeypatch):
    from agents.core.workspace import extract_process

    monkeypatch.setattr(extract_process, "MEMORY_LIMIT_BYTES", 1)
    _owned_script(monkeypatch, "import time; time.sleep(120)")
    with pytest.raises(extract.ExtractionError) as caught:
        await extract.extract_document(b"x", "pdf", timeout=3)
    assert caught.value.code == "too_much_text"


@pytest.mark.skipif(os.name == "nt", reason="POSIX descendant proof")
async def test_orphaned_native_child_is_reaped_after_worker_exits(monkeypatch, tmp_path):
    pid_file = tmp_path / "grandchild.pid"
    script = (
        "import subprocess,sys; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'],"
        "stdout=sys.stdout,stderr=sys.stderr); "
        f"open({str(pid_file)!r},'w').write(str(child.pid))"
    )
    _capture_owned(monkeypatch, script)
    with pytest.raises(extract.ExtractionError) as caught:
        await extract.extract_document(b"x", "pdf", timeout=0.5)
    assert caught.value.code == "timeout"
    grandchild = int(pid_file.read_text())
    status = subprocess.run(["ps", "-o", "stat=", "-p", str(grandchild)],
                            capture_output=True, check=False).stdout.strip()
    assert not status or status.startswith(b"Z")


@pytest.mark.skipif(os.name == "nt", reason="POSIX descendant proof")
async def test_early_worker_failure_reaps_native_descendant_and_scratch(monkeypatch, tmp_path):
    from agents.core.workspace import extract_process

    pid_file = tmp_path / "grandchild.pid"
    script = (
        "import subprocess,sys; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'],"
        "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
        f"open({str(pid_file)!r},'w').write(str(child.pid)); "
        "sys.exit(7)"
    )
    captured, command, spawn = _capture_owned(monkeypatch, script)
    with pytest.raises(extract.ExtractionError) as caught:
        await extract.extract_document(b"x", "pdf", timeout=3)
    assert caught.value.code == "invalid_file"
    assert not os.path.exists(captured["scratch"])
    grandchild = int(pid_file.read_text())
    status = subprocess.run(["ps", "-o", "stat=", "-p", str(grandchild)],
                            capture_output=True, check=False).stdout.strip()
    assert not status or status.startswith(b"Z")
    monkeypatch.setattr(extract_process, "_owned_command", command)
    monkeypatch.setattr(extract_process, "_spawn_owned", spawn)
    assert (await extract.extract_document(samples.build_docx(), "docx")).char_count > 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX descendant proof")
async def test_cancellation_reaps_native_descendant(monkeypatch, tmp_path):
    pid_file = tmp_path / "grandchild.pid"
    script = (
        "import subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'],"
        "stdout=sys.stdout,stderr=sys.stderr); "
        f"open({str(pid_file)!r},'w').write(str(child.pid)); "
        "time.sleep(120)"
    )
    captured, _, _ = _capture_owned(monkeypatch, script)
    task = asyncio.create_task(extract.extract_document(b"x" * (2 * 1024 * 1024),
                                                        "pdf", timeout=5))
    for _ in range(100):
        if pid_file.exists():
            break
        await asyncio.sleep(0.01)
    assert pid_file.exists()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not os.path.exists(captured["scratch"])
    grandchild = int(pid_file.read_text())
    status = subprocess.run(["ps", "-o", "stat=", "-p", str(grandchild)],
                            capture_output=True, check=False).stdout.strip()
    assert not status or status.startswith(b"Z")


@pytest.mark.skipif(os.name == "nt", reason="POSIX session accounting proof")
def test_session_memory_enumeration_includes_separate_page_group():
    from agents.core.workspace import extract_process

    page = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"],
                            process_group=0)
    try:
        members = extract_process._session_members(os.getsid(0))
        assert members is not None
        assert any(pid == page.pid and pgid == page.pid and rss > 0
                   for pid, pgid, rss in members)
    finally:
        page.kill()
        page.wait()


async def test_session_memory_watchdog_sums_document_and_page_groups(monkeypatch):
    from agents.core.workspace import extract_process

    killed = []
    monkeypatch.setattr(extract_process, "MEMORY_LIMIT_BYTES", 10)
    monkeypatch.setattr(extract_process, "_session_members",
                        lambda sid: [(101, 101, 6), (202, 202, 6)])
    monkeypatch.setattr(extract_process, "_kill_session_groups", killed.append)
    fault = []
    await extract_process._watch_memory(101, asyncio.Event(), fault)
    assert fault == ["too_much_text"]
    assert killed == [101]


@pytest.mark.skipif(os.name == "nt", reason="native OCR is disabled on Windows")
def test_scanned_pdf_upload_retrieval_original_and_reindex(ws, monkeypatch):
    from agents.core.workspace import documents, retrieval

    script = (
        "import sys; from agents.core.workspace import extract; "
        + _FAKE_ENGINE_PATCH +
        "from agents.core.workspace.extract_process import _worker; _worker()"
    )
    _owned_script(monkeypatch, script)
    conn = db()
    company = seed_company(conn)
    client = docs_client()
    try:
        csrf = login(client, company.member_a.email)
        original = samples.build_blank_pdf(2)
        doc = upload(client, csrf, company.dept_a, "scan.pdf", original).json()
        assert doc["status"] == "ready" and doc["page_count"] == 2
        assert documents.file_path(doc["id"]).read_bytes() == original
        assert client.get(f"/api/workspace/documents/{doc['id']}/file").content == original
        hits = retrieval.search(conn, department_ids=[company.dept_a],
                                include_company=False, query="Scannedword")
        assert hits and hits[0].page == 1
        indexed = " ".join(row[0] for row in conn.execute(
            "SELECT text FROM chunks WHERE document_id = ?", (doc["id"],)))
        assert "page 1" in indexed and "page 2" in indexed
        with conn:
            conn.execute("UPDATE chunks SET text = 'stale' WHERE document_id = ?", (doc["id"],))
        updated = client.post(f"/api/workspace/documents/{doc['id']}/reindex",
                              headers=authed(client, csrf)).json()
        assert updated["status"] == "ready"
        hits = retrieval.search(conn, department_ids=[company.dept_a],
                                include_company=False, query="Scannedword")
        assert hits and hits[0].page == 1
        assert not conn.execute("SELECT 1 FROM chunks WHERE text = 'stale'").fetchone()
    finally:
        conn.close()
