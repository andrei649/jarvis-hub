"""TaskQueue must resolve its DB path against the JARVIS_HOME in effect *now*, not
the one bound when the module was imported. A stale module-level binding let test
fixtures reach the production Decision Inbox (2026-07-24 QA finding); conftest
redirects JARVIS_HOME to a temp dir, and this makes that redirect effective even
if queue.py was imported first."""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.autonomy import queue as q


def test_default_db_honors_jarvis_home_set_after_import(tmp_path, monkeypatch):
    # queue.py is already imported (top of file). Change JARVIS_HOME afterwards —
    # a lazy resolver must pick up the new root; a module-level binding would not.
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    tq = q.TaskQueue()                       # db_path=None → lazy default
    assert str(tmp_path) in tq.db_path, "queue did not honor the current JARVIS_HOME"
    assert tq.db_path.endswith("autonomy.db")


def test_explicit_db_path_still_wins(tmp_path):
    explicit = str(tmp_path / "custom.db")
    assert q.TaskQueue(db_path=explicit).db_path == explicit


def test_isolated_queue_does_not_touch_production_dir(tmp_path, monkeypatch):
    # Enqueue through an isolated queue and confirm it wrote only under the temp root.
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    tq = q.TaskQueue().initialize()
    tq.enqueue(agent="jarvis", kind="delete_file", title="Delete old logs",
               payload={}, risk_tier=3, autonomy_level="ask")
    assert Path(tq.db_path).exists()
    assert str(tmp_path) in tq.db_path
    tq.close()
