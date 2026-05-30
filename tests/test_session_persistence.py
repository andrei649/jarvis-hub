"""H3.3 — conversation persistence across restarts + explicit session resume.

Covers the previously-untested persistence path in ConversationMemory and the
new resume_session() capability. Pure ConversationMemory (no FastAPI/Qdrant)."""
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.memory.conversation import ConversationMemory


async def test_persistence_roundtrip_across_restart(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # isolate memory_logs/ to a temp dir
    m = ConversationMemory(persist=True)
    sid = await m.new_session("session_rt")
    await m.add_turn(sid, "user", "salut")
    await m.add_turn(sid, "assistant", "bună, domnule")

    # A fresh instance (simulating a restart) restores the latest session.
    restarted = ConversationMemory(persist=True)
    assert restarted.current_session_id == "session_rt"
    hist = await restarted.get_history("session_rt")
    assert [t["content"] for t in hist] == ["salut", "bună, domnule"]


async def test_resume_specific_session(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    m = ConversationMemory(persist=True)
    a = await m.new_session("session_A")
    await m.add_turn(a, "user", "context A")
    b = await m.new_session("session_B")
    await m.add_turn(b, "user", "context B")

    # Restart loads the newest (B); resume A explicitly and confirm its context.
    restarted = ConversationMemory(persist=True)
    assert restarted.current_session_id == "session_B"
    assert await restarted.resume_session("session_A") is True
    assert restarted.current_session_id == "session_A"
    hist = await restarted.get_history("session_A")
    assert hist[-1]["content"] == "context A"


async def test_resume_missing_session_returns_false(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    m = ConversationMemory(persist=True)
    assert await m.resume_session("does_not_exist") is False
