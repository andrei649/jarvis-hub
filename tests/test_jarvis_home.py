"""SEC-4 / audit F-08 — runtime state relocates via $JARVIS_HOME.

All stores resolve their paths through core.paths.data_path/data_root. The
default is the repo's memory_logs/ (unchanged), and setting JARVIS_HOME (or the
legacy JARVIS_MEMORY_DIR) relocates every store together.
"""
import importlib
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


def test_default_root_is_repo_memory_logs(monkeypatch):
    monkeypatch.delenv("JARVIS_HOME", raising=False)
    monkeypatch.delenv("JARVIS_MEMORY_DIR", raising=False)
    from agents.core import paths
    assert paths.data_root() == repo_root / "memory_logs"
    assert paths.data_path("settings.db") == repo_root / "memory_logs" / "settings.db"
    assert paths.is_inside_repo() is True  # default lives in the checkout


def test_jarvis_home_relocates_everything(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    from agents.core import paths
    assert paths.data_root() == tmp_path
    assert paths.data_path("security", "audit.db") == tmp_path / "security" / "audit.db"
    assert paths.is_inside_repo() is False  # relocated outside the checkout


def test_legacy_jarvis_memory_dir_still_honored(monkeypatch, tmp_path):
    monkeypatch.delenv("JARVIS_HOME", raising=False)
    monkeypatch.setenv("JARVIS_MEMORY_DIR", str(tmp_path))
    from agents.core import paths
    assert paths.data_root() == tmp_path


def test_store_default_relocates_under_jarvis_home(monkeypatch, tmp_path):
    # End-to-end: a store's module-level default path resolves under JARVIS_HOME.
    import agents.core.notes as notes
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    try:
        importlib.reload(notes)
        assert str(notes.DEFAULT_PATH).startswith(str(tmp_path))
    finally:
        monkeypatch.delenv("JARVIS_HOME", raising=False)
        importlib.reload(notes)  # restore the default for other tests
