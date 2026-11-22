"""Bounded, user-owned Office previews from real OOXML files."""

import asyncio

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

import agents.web as web
from agents.core.routers import canvas
from agents.core.routers._deps import user_guard
from agents.core.workspace.extract import Extracted, ExtractionError, Segment
from tests.fixtures.workspace import samples


URL = "/api/canvas/office-preview"
HEADERS = {"Content-Type": "application/octet-stream"}


def test_docx_preview_uses_real_extractor_and_bounds_codepoints():
    body = samples.docx_paragraph("Ț😀" * 6010)
    response = TestClient(web.app).post(URL, params={"kind": "docx"},
                                        content=samples.build_docx(body), headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["Cache-Control"].startswith("no-cache, no-store")
    assert response.json() == {"kind": "docx", "segments": [{
        "label": "Document", "text": "Ț😀" * 6000, "truncated": True,
    }], "total_segments": 1}


def test_xlsx_preview_keeps_headers_and_real_sheet_names():
    data = samples.build_xlsx({"Vânzări": [["Lună", "Încasări"], ["Mai", 123]],
                               "Termene": [["Activitate"], ["Bilanț"]]})
    response = TestClient(web.app).post(URL, params={"kind": "xlsx"}, content=data, headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["total_segments"] == 2
    assert [item["label"] for item in body["segments"]] == ["Vânzări", "Termene"]
    assert body["segments"][0]["text"].startswith("## Vânzări\n\n| Lună | Încasări |")
    assert all(not item["truncated"] for item in body["segments"])


def test_preview_caps_returned_sheets_and_reports_total():
    data = samples.build_xlsx({f"Tab {n}": [["Value"], [f"Row {n}"]] for n in range(34)})
    response = TestClient(web.app).post(URL, params={"kind": "xlsx"}, content=data, headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["total_segments"] == 34
    assert len(body["segments"]) == 32
    assert body["segments"][-1]["label"] == "Tab 31"


@pytest.mark.parametrize(("kind", "body", "headers", "status"), [
    ("docx", b"", HEADERS, 422),
    ("docx", samples.build_xlsx(), HEADERS, 422),
    ("xlsx", samples.build_docx(), HEADERS, 422),
    ("docx", b"PK\x03\x04[Content_Types].xmlword/", HEADERS, 422),
    ("docx", samples.build_docx(""), HEADERS, 422),
    ("docx", samples.build_docx(), {"Content-Type": "application/json"}, 415),
    ("docx", b"x" * (8 * 1024 * 1024 + 1), HEADERS, 413),
    ("pdf", samples.build_docx(), HEADERS, 422),
])
def test_preview_refuses_invalid_or_excess_input(kind, body, headers, status):
    response = TestClient(web.app).post(URL, params={"kind": kind}, content=body, headers=headers)
    assert response.status_code == status
    assert response.headers["Cache-Control"].startswith("no-cache, no-store")
    assert set(response.json()) <= {"error", "detail"}
    assert "PK" not in response.text and "word/" not in response.text


def test_preview_requires_user_guard(monkeypatch):
    monkeypatch.delitem(web.app.dependency_overrides, user_guard, raising=False)
    monkeypatch.delenv("JARVIS_USER_TOKEN", raising=False)
    monkeypatch.delenv("JARVIS_ADMIN_TOKEN", raising=False)
    remote = TestClient(web.app, client=("203.0.113.9", 50000))
    response = remote.post(URL, params={"kind": "docx"},
                           content=samples.build_docx(), headers=HEADERS)
    assert response.status_code in (401, 403)


def _request(data: bytes) -> Request:
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": data, "more_body": False}

    return Request({"type": "http", "method": "POST", "headers": [
        (b"content-type", b"application/octet-stream"),
    ]}, receive)


@pytest.mark.asyncio
async def test_cancelled_caller_keeps_parse_slot_until_extraction_finishes(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    active = 0

    async def slow_extract(data, kind):
        nonlocal active
        active += 1
        if active == 2:
            started.set()
        await release.wait()
        active -= 1
        return Extracted((Segment(None, "Preview"),), None)

    monkeypatch.setattr(canvas.extract, "extract_document", slow_extract)
    data = samples.build_docx()
    first = asyncio.create_task(canvas.canvas_office_preview(_request(data), "docx"))
    second = asyncio.create_task(canvas.canvas_office_preview(_request(data), "docx"))
    try:
        await asyncio.wait_for(started.wait(), 2)
        assert (await canvas.canvas_office_preview(_request(data), "docx")).status_code == 429
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert (await canvas.canvas_office_preview(_request(data), "docx")).status_code == 429
    finally:
        release.set()
        await second
        await asyncio.sleep(0)
    assert active == 0
    assert (await canvas.canvas_office_preview(_request(data), "docx")).status_code == 200


@pytest.mark.asyncio
async def test_extraction_error_is_static(monkeypatch):
    async def fail(data, kind):
        raise ExtractionError("invalid_file", "private file path /secret.docx")

    monkeypatch.setattr(canvas.extract, "extract_document", fail)
    response = await canvas.canvas_office_preview(_request(samples.build_docx()), "docx")
    assert response.status_code == 422
    assert b"secret" not in response.body
