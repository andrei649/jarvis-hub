"""Guide-gap tails: STT dictation cleanup wiring (0.24) + governed Postiz
scheduling (0.69). All offline.

- /api/voice/stt applies clean_dictation only when `voice.dictation_cleanup`
  is on, reports inspectable removal counts, and never touches sentinel
  transcripts;
- SocialBroker gains the postiz.schedule catalog action: request queues an
  ask-tier `social.postiz.schedule` task, execute delegates to the PostizPlugin
  with the explicit `kind="schedule"` (the only caller allowed to arm a live
  publish), and an unconfigured plugin fails honestly.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.social import SOCIAL_DRAFT_CONTRACT, SocialBroker
from fastapi.testclient import TestClient

from agents import web
from agents.core.routers import voice as voice_router

# ---------------------------------------------------------------------------
# 0.24 — /api/voice/stt dictation cleanup
# ---------------------------------------------------------------------------

def _fake_engine(transcript: str):
    engine = MagicMock()
    engine.transcribe_async = AsyncMock(return_value=transcript)
    return engine


def _post_stt(transcript: str, settings: dict):
    def fake_get_value(category, key, default=None):
        return settings.get(f"{category}.{key}", default)

    with (
        patch("core.voice.stt.HAS_WHISPER", True),
        patch("core.settings_db.get_value", side_effect=fake_get_value),
        patch.object(voice_router, "_stt_engine", return_value=_fake_engine(transcript)),
        TestClient(web.app) as client,
    ):
        return client.post("/api/voice/stt?lang=en", content=b"AUDIO")


def test_stt_cleanup_off_by_default_returns_raw():
    resp = _post_stt("um hello hello world", {})
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "um hello hello world"
    assert "dictation" not in body


def test_stt_cleanup_on_strips_and_reports():
    resp = _post_stt("um hello hello world period", {"voice.dictation_cleanup": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "Hello world."
    assert body["dictation"]["cleaned"] is True
    assert body["dictation"]["removed"]["fillers"] == 1
    assert body["dictation"]["removed"]["repeats"] == 1


def test_stt_cleanup_leaves_sentinels_alone():
    resp = _post_stt("[silence]", {"voice.dictation_cleanup": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "[silence]"
    assert "dictation" not in body


# ---------------------------------------------------------------------------
# 0.69 — governed Postiz scheduling through SocialBroker
# ---------------------------------------------------------------------------

FIELDS = {"text": "Launch day!", "integration_id": "int-1",
          "publish_at": "2026-07-21T10:00:00Z"}


class FakePostiz:
    def __init__(self, ok=True, configured=True):
        self.ok = ok
        self.configured = configured
        self.calls = []

    def available(self):
        return self.configured

    async def schedule_post(self, content, integration_ids, publish_at, kind="draft"):
        self.calls.append({"content": content, "integration_ids": integration_ids,
                           "publish_at": publish_at, "kind": kind})
        if not self.ok:
            return {"ok": False, "error": "Postiz HTTP 500"}
        return {"ok": True, "data": {"id": "p1"}}


class FakeTask:
    def __init__(self, payload):
        self.payload = payload


def test_postiz_schedule_request_queues_ask_tier_task():
    queued = []

    def enqueue(agent, kind, title, payload=None, **kw):
        queued.append({"agent": agent, "kind": kind, "payload": payload, **kw})
        return "task-1"

    broker = SocialBroker(enqueue=enqueue)
    out = broker.request("postiz", "schedule", dict(FIELDS))
    assert out["ok"] is True and out["queued"] is True
    q = queued[0]
    assert q["kind"] == "social.postiz.schedule"
    assert q["autonomy_level"] == "ask"          # never auto-fires without the kernel
    assert q["payload"]["fields"]["integration_id"] == "int-1"
    assert q["payload"]["credential_ref"] == ""  # auth lives in the plugin, not SecretBroker


def test_postiz_schedule_request_refuses_missing_fields():
    broker = SocialBroker(enqueue=lambda *a, **k: "t")
    out = broker.request("postiz", "schedule", {"text": "hi"})
    assert out["ok"] is False and out["reason"] == "missing_fields"
    assert set(out["missing"]) == {"integration_id", "publish_at"}


def test_postiz_schedule_contract_admits_valid_payload():
    decision = SOCIAL_DRAFT_CONTRACT.evaluate({
        "kind": "social.postiz.schedule", "platform": "postiz", "action": "schedule",
        "fields": dict(FIELDS), "credential_ref": "", "agent": "pepper", "risk_tier": 2,
    }, now=0.0)
    assert decision.admissible


async def test_postiz_execute_delegates_with_schedule_kind():
    plugin = FakePostiz()
    broker = SocialBroker(postiz_resolver=lambda: plugin)
    task = FakeTask({"platform": "postiz", "action": "schedule", "fields": dict(FIELDS)})
    result = await broker.execute(task)
    assert result["status"] == "ok" and result["social"] == {"id": "p1"}
    call = plugin.calls[0]
    assert call["kind"] == "schedule"            # the governed caller arms the live publish
    assert call["integration_ids"] == ["int-1"]


async def test_postiz_execute_unconfigured_fails_honestly():
    broker = SocialBroker(postiz_resolver=lambda: FakePostiz(configured=False))
    task = FakeTask({"platform": "postiz", "action": "schedule", "fields": dict(FIELDS)})
    result = await broker.execute(task)
    assert result == {"status": "failed", "reason": "postiz_not_configured",
                      "platform": "postiz", "action": "schedule"}

    broker_no_resolver = SocialBroker()
    result2 = await broker_no_resolver.execute(task)
    assert result2["reason"] == "postiz_not_configured"


async def test_postiz_execute_plugin_error_fails_honestly():
    broker = SocialBroker(postiz_resolver=lambda: FakePostiz(ok=False))
    task = FakeTask({"platform": "postiz", "action": "schedule", "fields": dict(FIELDS)})
    result = await broker.execute(task)
    assert result["status"] == "failed" and "500" in result["reason"]


def test_postiz_schedule_visible_in_targets_catalog():
    rows = {t["kind"]: t for t in SocialBroker().targets()}
    row = rows["social.postiz.schedule"]
    assert set(row["required"]) == {"text", "integration_id", "publish_at"}
    assert row["credential"] == ""


# ---------------------------------------------------------------------------
# Fish Audio surfaces in /api/voice/capabilities (honest provider state)
# ---------------------------------------------------------------------------

def test_capabilities_report_fish_audio(monkeypatch):
    monkeypatch.setenv("FISH_AUDIO_API_KEY", "fa-key")
    monkeypatch.delenv("XTTS_SERVER_URL", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with TestClient(web.app) as client:
        data = client.get("/api/voice/capabilities").json()
    assert data["providers"]["fish_audio"] is True
    assert data["tts"] is True          # fish alone is a real TTS path


def test_capabilities_fish_absent_is_false(monkeypatch):
    monkeypatch.delenv("FISH_AUDIO_API_KEY", raising=False)
    with TestClient(web.app) as client:
        data = client.get("/api/voice/capabilities").json()
    assert data["providers"]["fish_audio"] is False
