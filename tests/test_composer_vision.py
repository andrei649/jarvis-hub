"""Composer vision is bounded, explicit, destination-bound and never a file reader."""

import base64
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.core.llm import vlm

STATUS = "/api/vlm/composer/status"
DESCRIBE = "/api/vlm/composer/describe"
PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYPgPAAEDAQAIicLsAAAAAElFTkSuQmCC"


@pytest.fixture
def setup(monkeypatch, tmp_path):
    from agents.core import settings_db

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    config = vlm.VLMConfig("custom", "http://127.0.0.1:1234/v1", "vision-test", "test-key", True)
    state = SimpleNamespace(config=config, calls=[], closed=0, error=False, resolves=0)

    def resolve():
        state.resolves += 1
        return state.config

    class Backend:
        def __init__(self, base_url, api_key):
            self.base_url = base_url
            self.api_key = api_key

        async def generate_vision_checked(self, model, prompt, images):
            state.calls.append((self.base_url, self.api_key, model, prompt, images))
            if state.error:
                raise RuntimeError("private diagnostic")
            return "A screenshot."

        async def aclose(self):
            state.closed += 1

    monkeypatch.setattr(vlm, "resolve_vlm_config", resolve)
    monkeypatch.setattr(vlm, "VLMBackend", Backend)
    monkeypatch.setattr(web.app, "dependency_overrides", {})
    monkeypatch.setattr(web, "USER_TOKEN", "image-test")
    monkeypatch.setenv("JARVIS_USER_TOKEN", "image-test")
    state.client = TestClient(web.app, headers={"X-User-Token": "image-test"})
    return state


def body(state):
    response = state.client.get(STATUS)
    assert response.status_code == 200
    status = response.json()
    return {
        "prompt": "What is shown?",
        "images": [PNG],
        "expected_destination": status["destination"],
        "expected_binding": status["binding"],
        "remote_ack": False,
    }


def test_status_and_actual_model_provenance(setup):
    payload = body(setup)
    before = setup.resolves
    response = setup.client.post(DESCRIBE, json=payload)
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "response": "A screenshot.",
        "model": "vision-test",
        "backend": "custom",
        "destination": "http://127.0.0.1:1234/v1",
        "local": True,
    }
    assert setup.resolves == before + 1
    assert setup.calls[0][:3] == (setup.config.base_url, "test-key", "vision-test")
    assert setup.closed == 1


@pytest.mark.parametrize(
    "change",
    [
        {"base_url": "https://other.example/v1", "is_local": False},
        {"model": "new-model"},
        {"base_url": "http://127.0.0.1:1234/v1?new=1"},
    ],
)
def test_changed_destination_binding_never_calls_backend(setup, change):
    payload = body(setup)
    setup.config = replace(setup.config, **change)
    assert setup.client.post(DESCRIBE, json=payload).status_code == 409
    assert setup.calls == []


def test_remote_ack_names_public_destination_and_hides_credentials(setup):
    setup.config = replace(
        setup.config, base_url="https://user:password@example.com/v1?secret=value", is_local=False
    )
    payload = body(setup)
    assert payload["expected_destination"] == "https://example.com/v1"
    assert "password" not in str(setup.client.get(STATUS).json())
    assert setup.client.post(DESCRIBE, json=payload).status_code == 403
    payload["remote_ack"] = True
    assert setup.client.post(DESCRIBE, json=payload).status_code == 200


@pytest.mark.parametrize(
    "image",
    [
        "/etc/passwd",
        "https://example.com/image.png",
        "data:text/html;base64,SGk=",
        "data:image/svg+xml;base64,PHN2Zz4=",
        "data:image/png;base64,!!!!",
        "data:image/png;base64," + base64.b64encode(b"not png").decode(),
        "data:image/png;base64,"
        + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * (4 * 1024 * 1024)).decode(),
    ],
    ids=["path", "url", "html", "svg", "base64", "magic", "oversize"],
)
def test_rejects_non_bounded_raster_before_backend(setup, image):
    payload = body(setup)
    payload["images"] = [image]
    assert setup.client.post(DESCRIBE, json=payload).status_code == 422
    assert setup.calls == []


def test_image_count_unknown_fields_and_empty_prompt(setup):
    payload = body(setup)
    for patch in ({"images": []}, {"images": [PNG] * 9}, {"prompt": " "}, {"model": "injected"}):
        assert setup.client.post(DESCRIBE, json={**payload, **patch}).status_code == 422
    assert setup.calls == []


def test_generation_failure_is_not_a_successful_transcript(setup):
    payload = body(setup)
    setup.error = True
    response = setup.client.post(DESCRIBE, json=payload)
    assert response.status_code == 502
    assert response.json() == {"error": "Vision analysis failed", "reason": "vlm_generation_failed"}
    assert setup.closed == 1


def test_missing_user_token_cannot_read_or_send_images(setup):
    payload = body(setup)
    assert setup.client.get(STATUS, headers={"X-User-Token": ""}).status_code == 401
    assert (
        setup.client.post(DESCRIBE, json=payload, headers={"X-User-Token": ""}).status_code == 401
    )
    assert setup.calls == []


def test_public_binding_is_random_revision_not_a_secret_guessing_oracle(setup):
    import hashlib
    import json

    config = setup.config
    digest = hashlib.sha256(
        json.dumps([config.backend, config.base_url, config.model, config.is_local]).encode()
    ).hexdigest()
    first = setup.client.get(STATUS).json()["binding"]
    assert first != digest
    assert setup.client.get(STATUS).json()["binding"] == first
    from agents.core import settings_db

    settings_db._initialized = False
    assert setup.client.get(STATUS).json()["binding"] == first
    # A separately imported worker has no process-local cache or signing key.
    import subprocess
    import sys
    from dataclasses import asdict

    script = """import json,sys
from pathlib import Path
from agents.core import settings_db
from agents.core.llm.vlm import VLMConfig
from agents.core.routers.composer_vision import public_config
payload=json.load(sys.stdin)
settings_db.DB_PATH=Path(payload['db'])
print(public_config(VLMConfig(**payload['config']))['binding'])
"""
    worker = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps({"db": str(settings_db.DB_PATH), "config": asdict(config)}),
        text=True,
        capture_output=True,
        check=True,
    )
    assert worker.stdout.strip() == first


@pytest.mark.asyncio
async def test_checked_backend_raises_while_legacy_wrapper_keeps_sentinel():
    class FailedClient:
        async def post(self, *args, **kwargs):
            raise RuntimeError("provider unavailable")

    backend = vlm.VLMBackend(client=FailedClient())
    with pytest.raises(RuntimeError):
        await backend.generate_vision_checked("model", "question", [PNG])
    assert await backend.generate_vision("model", "question", [PNG]) == "[VLM error]"


def test_revision_store_failure_never_contacts_model(setup, monkeypatch):
    import sqlite3

    from agents.core import settings_db

    payload = body(setup)
    monkeypatch.setattr(
        settings_db,
        "get_conn",
        lambda: (_ for _ in ()).throw(sqlite3.OperationalError("private path")),
    )
    assert setup.client.post(DESCRIBE, json=payload).status_code == 503
    assert setup.calls == []


@pytest.mark.parametrize("kind", ["magic-only", "truncated", "edge", "pixels", "animated"])
def test_rejects_invalid_or_excessive_decoded_raster(setup, kind):
    import io
    import struct
    import zlib

    from PIL import Image

    output = io.BytesIO()
    Image.new("RGB", (2, 2), "blue").save(output, format="PNG")
    raw = output.getvalue()
    if kind == "magic-only":
        raw = b"\x89PNG\r\n\x1a\nimage"
    elif kind == "truncated":
        raw = raw[:-15]
    elif kind in ("edge", "pixels"):
        data = bytearray(raw)
        data[16:24] = struct.pack(
            ">II", 9000 if kind == "edge" else 4096, 1 if kind == "edge" else 4097
        )
        data[29:33] = struct.pack(">I", zlib.crc32(data[12:29]) & 0xFFFFFFFF)
        raw = bytes(data)
    else:
        output = io.BytesIO()
        Image.new("RGB", (2, 2), "red").save(
            output, format="PNG", save_all=True, append_images=[Image.new("RGB", (2, 2), "blue")]
        )
        raw = output.getvalue()
    payload = body(setup)
    payload["images"] = ["data:image/png;base64," + base64.b64encode(raw).decode()]
    response = setup.client.post(DESCRIBE, json=payload)
    assert response.status_code == 422
    assert setup.calls == []


@pytest.mark.parametrize(
    "fmt,mime",
    [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("GIF", "image/gif"), ("WEBP", "image/webp")],
)
def test_static_raster_formats_are_decoded_and_forwarded_as_bounded_bytes(setup, fmt, mime):
    import io

    from PIL import Image

    output = io.BytesIO()
    Image.new("RGB", (3, 2), "blue").save(output, format=fmt)
    payload = body(setup)
    payload["images"] = [f"data:{mime};base64," + base64.b64encode(output.getvalue()).decode()]
    assert setup.client.post(DESCRIBE, json=payload).status_code == 200
    assert setup.calls[0][4] == [output.getvalue()]
