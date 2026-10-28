"""Opt-in extraction must contain a parser that never reaches a checkpoint."""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

from agents.core.workspace import extract
from tests.fixtures.workspace import samples


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setenv("NERVA_WORKSPACE_KILLABLE_EXTRACTION", "1")


@pytest.mark.parametrize("kind", ["pdf", "docx"])
async def test_real_child_preserves_text_and_reports_enforced_limits(kind):
    data = samples.build_pdf() if kind == "pdf" else samples.build_docx()
    result = await extract.extract_document(data, kind)
    expected = extract.extract_bytes(data, kind)
    assert (result.segments, result.page_count) == (expected.segments, expected.page_count)
    assert "wall_time" in result.limits
    assert ("memory_unavailable" if sys.platform == "win32" else "address_space") in result.limits


async def test_child_preserves_stable_error_and_page_count():
    with pytest.raises(extract.ExtractionError) as caught:
        await extract.extract_document(samples.build_blank_pdf(3), "pdf")
    assert caught.value.code == "no_text"
    assert caught.value.page_count == 3


async def test_pathological_pdf_is_killed_and_reaped_before_timeout_returns(monkeypatch, tmp_path):
    from agents.core.workspace import extract_process

    real_spawn = asyncio.create_subprocess_exec
    children = []
    started = asyncio.Event()
    marker = tmp_path / "entered-page"
    handler = f'def stuck(*a, **kw):\n open({str(marker)!r}, "w").close()\n while True: pass'
    script = (
        "from pypdf import PageObject; "
        f"exec({handler!r}); "
        "PageObject.extract_text = stuck; "
        "from agents.core.workspace.extract_process import _worker; _worker()"
    )

    async def spawn(*args, **kwargs):
        child = await real_spawn(sys.executable, "-c", script, *args[-2:], **kwargs)
        children.append(child)
        started.set()
        return child

    monkeypatch.setattr(extract_process.asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(extract.extract_document(samples.build_pdf(), "pdf", timeout=5))
    await started.wait()
    with pytest.raises(extract.ExtractionError) as caught:
        await task
    assert caught.value.code == "timeout"
    assert marker.exists(), "the parser entered a page that never reached a checkpoint"
    assert children[0].returncode is not None
    assert children[0].returncode != 0
    # No hung parser occupies a pool thread or a process slot after the failure.
    monkeypatch.setattr(extract_process.asyncio, "create_subprocess_exec", real_spawn)
    assert (await extract.extract_document(samples.build_docx(), "docx")).char_count > 0


@pytest.mark.parametrize("script", ["raise SystemExit(7)", "print('invalid JSON')"])
async def test_child_crash_or_bad_output_is_an_honest_failure(monkeypatch, script):
    from agents.core.workspace import extract_process

    real_spawn = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        return await real_spawn(sys.executable, "-c", script, **kwargs)

    monkeypatch.setattr(extract_process.asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(extract.ExtractionError) as caught:
        await extract.extract_document(samples.build_docx(), "docx")
    assert caught.value.code == "invalid_file"


async def test_cancellation_during_launch_still_reaps_child_and_removes_scratch(monkeypatch):
    from agents.core.workspace import extract_process

    real_spawn = asyncio.create_subprocess_exec
    children = []
    started, release = asyncio.Event(), asyncio.Event()
    scratch = None

    async def spawn(*args, **kwargs):
        nonlocal scratch
        scratch = kwargs["env"]["TMPDIR"]
        child = await real_spawn(sys.executable, "-c", "import time; time.sleep(120)", **kwargs)
        children.append(child)
        started.set()
        await release.wait()
        return child

    monkeypatch.setattr(extract_process.asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(extract.extract_document(b"x", "pdf"))
    await started.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert children[0].returncode is not None
    assert not os.path.exists(scratch)


async def test_cancellation_kills_and_reaps_child(monkeypatch):
    from agents.core.workspace import extract_process

    real_spawn = asyncio.create_subprocess_exec
    children = []
    started = asyncio.Event()

    async def spawn(*args, **kwargs):
        child = await real_spawn(sys.executable, "-c", "import time; time.sleep(120)", **kwargs)
        children.append(child)
        started.set()
        return child

    monkeypatch.setattr(extract_process.asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(extract.extract_document(b"x", "pdf"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert children[0].returncode is not None


async def test_queue_deadline_does_not_start_a_third_child(monkeypatch):
    from agents.core.workspace import extract_process

    assert extract_process._SLOTS.acquire(blocking=False)
    assert extract_process._SLOTS.acquire(blocking=False)

    async def forbidden(*a, **kw):
        pytest.fail("a queued extraction must not launch a third child")

    monkeypatch.setattr(extract_process.asyncio, "create_subprocess_exec", forbidden)
    try:
        with pytest.raises(extract.ExtractionError, match="timeout"):
            await extract.extract_document(b"x", "pdf", timeout=0.02)
    finally:
        extract_process._SLOTS.release()
        extract_process._SLOTS.release()


async def test_feature_is_default_off(monkeypatch):
    monkeypatch.delenv("NERVA_WORKSPACE_KILLABLE_EXTRACTION", raising=False)
    result = await extract.extract_document(samples.build_docx(), "docx")
    assert result.limits == ()


async def test_frozen_worker_uses_early_dispatch_without_booting_hub(monkeypatch, tmp_path):
    from agents.core.workspace import extract_process

    real_spawn = asyncio.create_subprocess_exec
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "unused-home"))
    monkeypatch.setenv("JARVIS_PROFILE", "../must-not-boot")

    async def spawn(*args, **kwargs):
        assert args[1] == "--nerva-workspace-extract-worker"
        assert "-m" not in args
        return await real_spawn(sys.executable, str(extract_process._REPO / "serve.py"),
                                *args[1:], **kwargs)

    monkeypatch.setattr(extract_process.asyncio, "create_subprocess_exec", spawn)
    result = await extract.extract_document(samples.build_docx(), "docx")
    assert result.char_count > 0
    assert not (tmp_path / "unused-home").exists()


async def test_page_memory_exhaustion_fails_the_whole_child_result(monkeypatch):
    from agents.core.workspace import extract_process

    real_spawn = asyncio.create_subprocess_exec
    handler = ('calls = 0\ndef page(*a, **kw):\n global calls\n calls += 1\n'
               ' if calls == 2: raise MemoryError("page ceiling")\n return "first page text"')
    script = (f"from pypdf import PageObject; exec({handler!r}); PageObject.extract_text = page; "
              "from agents.core.workspace.extract_process import _worker; _worker()")

    async def spawn(*args, **kwargs):
        return await real_spawn(sys.executable, "-c", script, *args[-2:], **kwargs)

    monkeypatch.setattr(extract_process.asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(extract.ExtractionError) as caught:
        await extract.extract_document(samples.build_pdf(), "pdf")
    assert caught.value.code == "too_much_text"


@pytest.mark.skipif(os.name == "nt", reason="RLIMIT_AS is a POSIX-only resource limit")
async def test_child_sets_an_actual_address_space_ceiling(monkeypatch):
    from agents.core.workspace import extract_process

    real_spawn = asyncio.create_subprocess_exec
    script = (
        "import resource; "
        "from agents.core.workspace import extract_process as p; "
        "p._apply_memory_limit(); "
        "assert resource.getrlimit(resource.RLIMIT_AS)[0] <= p.MEMORY_LIMIT_BYTES; "
        "from agents.core.workspace.extract_process import _worker; _worker()"
    )

    async def spawn(*args, **kwargs):
        return await real_spawn(sys.executable, "-c", script, *args[-2:], **kwargs)

    monkeypatch.setattr(extract_process.asyncio, "create_subprocess_exec", spawn)
    assert (await extract.extract_document(samples.build_docx(), "docx")).char_count > 0


def _fake_engine(pages):
    return lambda data, index, seconds: pages[index]


def test_scanned_pdf_stays_no_text_when_ocr_is_off_or_engine_absent(monkeypatch):
    blank = samples.build_blank_pdf(2)
    with pytest.raises(extract.ExtractionError) as off:
        extract.extract_bytes(blank, "pdf")
    assert off.value.code == "no_text"
    monkeypatch.setenv("NERVA_WORKSPACE_OCR", "1")
    monkeypatch.setattr(extract, "_ocr_engine", lambda: None)
    with pytest.raises(extract.ExtractionError) as absent:
        extract.extract_bytes(blank, "pdf")
    assert absent.value.code == "no_text"


def test_ocr_needs_killable_extraction_too(monkeypatch):
    monkeypatch.setenv("NERVA_WORKSPACE_OCR", "1")
    monkeypatch.delenv("NERVA_WORKSPACE_KILLABLE_EXTRACTION")
    monkeypatch.setattr(extract, "_ocr_engine", lambda: _fake_engine(["Factura 42", "Total"]))
    with pytest.raises(extract.ExtractionError) as caught:
        extract.extract_bytes(samples.build_blank_pdf(2), "pdf")
    assert caught.value.code == "no_text"


def test_ocr_reads_pages_and_marks_the_result(monkeypatch):
    monkeypatch.setenv("NERVA_WORKSPACE_OCR", "1")
    monkeypatch.setattr(extract, "_ocr_engine",
                        lambda: _fake_engine(["Factura 42", "", "Total 100 lei"]))
    result = extract.extract_bytes(samples.build_blank_pdf(3), "pdf")
    assert [(s.page, s.text) for s in result.segments] == [(1, "Factura 42"), (3, "Total 100 lei")]
    assert result.page_count == 3
    assert "ocr" in result.limits


def test_ocr_page_failure_skips_the_page_and_all_blank_is_no_text(monkeypatch):
    def engine(data, index, seconds):
        raise RuntimeError("tesseract crashed")

    monkeypatch.setenv("NERVA_WORKSPACE_OCR", "1")
    monkeypatch.setattr(extract, "_ocr_engine", lambda: engine)
    with pytest.raises(extract.ExtractionError) as caught:
        extract.extract_bytes(samples.build_blank_pdf(2), "pdf")
    assert caught.value.code == "no_text"


def test_ocr_refuses_documents_over_its_page_cap(monkeypatch):
    monkeypatch.setenv("NERVA_WORKSPACE_OCR", "1")
    monkeypatch.setattr(extract, "MAX_OCR_PAGES", 2)
    monkeypatch.setattr(extract, "_ocr_engine", lambda: _fake_engine(["x"] * 3))
    with pytest.raises(extract.ExtractionError) as caught:
        extract.extract_bytes(samples.build_blank_pdf(3), "pdf")
    assert (caught.value.code, caught.value.page_count) == ("too_many_pages", 3)


def test_ocr_page_timeout_is_bounded_by_the_document_deadline(monkeypatch):
    seen = []

    def engine(data, index, seconds):
        seen.append(seconds)
        return "text"

    monkeypatch.setenv("NERVA_WORKSPACE_OCR", "1")
    monkeypatch.setattr(extract, "_ocr_engine", lambda: engine)
    extract.extract_bytes(samples.build_blank_pdf(1), "pdf", timeout=5.0)
    assert 0 < seen[0] <= 5.0
    extract.extract_bytes(samples.build_blank_pdf(1), "pdf")
    assert seen[1] == extract.OCR_PAGE_TIMEOUT_SECONDS
