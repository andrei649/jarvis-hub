"""Tests for the Email Triage skill (H2.2) — Pepper's inbox prioritization.

Follows the loader pattern from tests/test_brief.py.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


def _load():
    path = repo_root / "skills" / "email_triage" / "main.py"
    spec = importlib.util.spec_from_file_location("email_triage_skill_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def skill():
    return _load()


class _MockGmail:
    def __init__(self, messages=None):
        self.messages = messages or []

    async def list_messages(self, max_results=20, query=""):
        return self.messages


async def test_triage_empty_inbox(skill, monkeypatch):
    monkeypatch.setattr(skill, "_gmail", _MockGmail([]))
    result = await skill.triage()
    assert "gol" in result.lower() or "nimic" in result.lower()


async def test_triage_normal_inbox(skill, monkeypatch):
    msgs = [
        {
            "id": "1",
            "from": "boss@company.com",
            "subject": "Urgent: deadline mâine",
            "date": "Fri, 29 May 2026 22:00:00 +0000",
            "snippet": "We need the report by tomorrow EOD.",
        },
        {
            "id": "2",
            "from": "newsletter@saas.com",
            "subject": "Weekly SaaS roundup",
            "date": "Fri, 29 May 2026 19:00:00 +0000",
            "snippet": "Top stories from the SaaS world.",
        },
        {
            "id": "3",
            "from": "mama@family.ro",
            "subject": "Re: weekend plans",
            "date": "Fri, 29 May 2026 23:30:00 +0000",
            "snippet": "Do you want to come over Sunday?",
        },
    ]
    monkeypatch.setattr(skill, "_gmail", _MockGmail(msgs))
    result = await skill.triage()
    assert "Total" in result
    assert "inbox priorizat" in result
    assert "family" in result.lower() or "mama" in result.lower()
    assert "Urgent" in result or "deadline" in result


async def test_triage_gmail_unavailable(skill, monkeypatch):
    def _mock_get_gmail():
        return None
    monkeypatch.setattr(skill, "_get_gmail", _mock_get_gmail)
    result = await skill.triage()
    assert "indisponibil" in result.lower() or "indisponibilă" in result.lower()


async def test_triage_gmail_error(skill, monkeypatch):
    class _ErrorGmail:
        async def list_messages(self, max_results=20, query=""):
            raise ConnectionError("network down")

    monkeypatch.setattr(skill, "_gmail", _ErrorGmail())
    result = await skill.triage()
    assert "eroare" in result.lower() or "network down" in result.lower()


async def test_triage_gmail_api_error_in_messages(skill, monkeypatch):
    monkeypatch.setattr(skill, "_gmail", _MockGmail([{"error": "permission denied"}]))
    result = await skill.triage()
    assert "eroare" in result.lower()


async def test_priority_score_vip(skill):
    msg = {
        "from": "boss@company.com",
        "subject": "Weekly sync",
        "date": "Fri, 29 May 2026 22:00:00 +0000",
        "snippet": "Let's catch up.",
    }
    score = skill._priority_score(msg)
    assert score >= 30


async def test_priority_score_urgent_keyword(skill):
    msg = {
        "from": "colleague@company.com",
        "subject": "ASAP: review needed",
        "date": "Fri, 29 May 2026 22:00:00 +0000",
        "snippet": "Please review ASAP.",
    }
    score = skill._priority_score(msg)
    assert score >= 20


async def test_priority_score_low(skill):
    msg = {
        "from": "newsletter@saas.com",
        "subject": "Weekly roundup",
        "date": "Thu, 28 May 2026 10:00:00 +0000",
        "snippet": "Here's what happened.",
    }
    score = skill._priority_score(msg)
    assert score <= 5


async def test_get_commands(skill):
    cmds = skill.get_commands()
    assert "triage" in cmds
    assert len(cmds) >= 1


async def test_handle_dispatch(skill, monkeypatch):
    monkeypatch.setattr(skill, "_gmail", _MockGmail([]))
    unknown = await skill.handle("bogus", "")
    assert "necunoscută" in unknown or "necunoscut" in unknown
    result = await skill.handle("triage", "")
    assert "gol" in result.lower() or "nimic" in result.lower()


async def test_triage_with_query(skill, monkeypatch):
    msgs = [
        {
            "id": "1",
            "from": "client@partner.com",
            "subject": "Project update",
            "date": "Fri, 29 May 2026 20:00:00 +0000",
            "snippet": "The project is on track.",
        },
    ]
    gmail = _MockGmail(msgs)
    monkeypatch.setattr(skill, "_gmail", gmail)
    result = await skill.triage("project")
    assert "Project" in result
    assert "client" in result.lower()


async def test_triage_vip_sorting(skill, monkeypatch):
    msgs = [
        {
            "id": "1",
            "from": "news@generic.com",
            "subject": "Hello",
            "date": "Fri, 29 May 2026 22:00:00 +0000",
            "snippet": "Generic newsletter.",
        },
        {
            "id": "2",
            "from": "boss@company.com",
            "subject": "Critical: all hands",
            "date": "Fri, 29 May 2026 22:00:00 +0000",
            "snippet": "All hands meeting now.",
        },
    ]
    gmail = _MockGmail(msgs)
    monkeypatch.setattr(skill, "_gmail", gmail)
    result = await skill.triage()
    boss_pos = result.lower().find("boss")
    news_pos = result.lower().find("news")
    assert boss_pos >= 0 and news_pos >= 0
    assert boss_pos < news_pos, "VIP message should appear before generic"
