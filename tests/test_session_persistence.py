"""H3.3 — conversation persistence across restarts + explicit session resume.

Covers the previously-untested persistence path in ConversationMemory and the
new resume_session() capability. Pure ConversationMemory (no FastAPI/Qdrant)."""
import json
import os
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.memory.conversation import ConversationMemory
from agents.core.memory import persistence


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


def _snapshot(path: Path, sid: str, turns: int = 1) -> None:
    """Write a `<sid>.json` in the shape `save_memory()` produces."""
    payload = {
        "session_id": sid,
        "turns": [{"role": "user", "content": f"turn {i}"} for i in range(turns)],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_list_sessions_breaks_mtime_tie_deterministically(tmp_path, monkeypatch):
    # Two sessions written within one filesystem mtime tick (common on Windows) used
    # to tie under the old `st_mtime` sort, and the stable sort then kept glob order
    # — so the OLDER session was restored on restart (Windows-only CI failure of
    # test_resume_specific_session). list_sessions must be deterministic on a tie.
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    _snapshot(tmp_path / "session_A.json", "session_A")
    _snapshot(tmp_path / "session_B.json", "session_B")
    t = 1_700_000_000_000_000_000  # identical mtime (ns) on both files
    os.utime(tmp_path / "session_A.json", ns=(t, t))
    os.utime(tmp_path / "session_B.json", ns=(t, t))
    # Deterministic newest-first: on an mtime tie the alphabetically-last name wins.
    assert persistence.list_sessions() == ["session_B", "session_A"]


def test_list_sessions_ignores_newer_non_session_json(tmp_path, monkeypatch):
    """Regression: runtime state in the data root must not be seen as a session.

    `entities.json` is rewritten by the knowledge graph on any turn mentioning a
    proper noun, so on a default install it is routinely the NEWEST `*.json` in
    the memory root. The old bare glob ranked it first, `_load_latest_session()`
    then "restored" the session id `entities` — which has no turns — and the
    user's history silently vanished across the restart. No flag was involved.
    """
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    _snapshot(tmp_path / "session_real.json", "session_real", turns=3)
    older = 1_700_000_000_000_000_000
    os.utime(tmp_path / "session_real.json", ns=(older, older))

    newer = older + 10_000_000_000
    for name, body in (
        ("entities.json", '{"entities": {"Andrei": {"kind": "person"}}}'),
        ("decay.json", "{}"),
        ("bitemporal_kg.json", '{"facts": []}'),
    ):
        (tmp_path / name).write_text(body, encoding="utf-8")
        os.utime(tmp_path / name, ns=(newer, newer))

    assert persistence.list_sessions() == ["session_real"]


def test_list_sessions_rejects_json_that_is_not_a_snapshot(tmp_path, monkeypatch):
    """A plausibly-named `*.json` still has to *be* a session snapshot.

    The denylist cannot know about a data file nobody has written yet, so the
    payload shape is the check that generalizes.
    """
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    (tmp_path / "session_bogus.json").write_text('{"unrelated": true}', encoding="utf-8")
    (tmp_path / "session_broken.json").write_text("{not json", encoding="utf-8")
    _snapshot(tmp_path / "session_good.json", "session_good")

    assert persistence.list_sessions() == ["session_good"]


async def test_restart_restores_history_with_kg_state_present(tmp_path, monkeypatch):
    """End-to-end shape of the bug: a real session survives a restart even when
    the knowledge graph has written newer state beside it."""
    monkeypatch.chdir(tmp_path)
    m = ConversationMemory(persist=True)
    sid = await m.new_session("session_live")
    await m.add_turn(sid, "user", "ține minte: Andrei")
    await m.add_turn(sid, "assistant", "reținut")

    # The KG writes entities.json into the same root, after the session snapshot.
    # resolved now, not at import — with the old import-time binding this pointed at
    # the real repo memory_logs/ and this test wrote entities.json into it.
    root = persistence.memory_dir()
    root.mkdir(parents=True, exist_ok=True)
    (root / "entities.json").write_text('{"entities": {"Andrei": {}}}', encoding="utf-8")

    restarted = ConversationMemory(persist=True)
    assert restarted.current_session_id == "session_live"
    hist = await restarted.get_history("session_live")
    assert [t["content"] for t in hist] == ["ține minte: Andrei", "reținut"]
