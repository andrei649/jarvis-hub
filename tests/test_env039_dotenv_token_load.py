"""ENV-039 — tokens supplied only via .env must still activate the auth posture.

`JARVIS_ADMIN_TOKEN` / `JARVIS_USER_TOKEN` / `DEV_MODE` were read once at module
import (`agents/web.py`), while `load_dotenv` runs later (`PluginManager.build`).
A token written only into `.env` therefore never activated the guards and the hub
silently stayed in the localhost-only dev posture — exactly what the QA runbook
tells testers to configure. The guards now resolve lazily: the module global
(the tests' monkeypatch channel and the import-time bootstrap) wins when set,
else the environment is re-read at call time.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.web as web
from agents.core import app_state


def test_env_only_user_token_activates_after_late_dotenv(monkeypatch):
    # Import-time state on a box whose token lives only in .env …
    monkeypatch.setattr(web, "USER_TOKEN", "")
    # … and what load_dotenv() does later, during PluginManager.build():
    monkeypatch.setenv("JARVIS_USER_TOKEN", "late-env-user")
    assert web._env_user_active() is True


def test_env_only_admin_token_activates_after_late_dotenv(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", "")
    monkeypatch.setenv("JARVIS_ADMIN_TOKEN", "late-env-admin")
    assert web._env_admin_active() is True
    assert web._admin_credential_ok("late-env-admin") is True
    assert web._admin_credential_ok("wrong") is False


def test_monkeypatched_global_still_wins_over_env(monkeypatch):
    # The test suite's established channel must keep working unchanged.
    monkeypatch.setattr(web, "ADMIN_TOKEN", "global-tok")
    monkeypatch.setenv("JARVIS_ADMIN_TOKEN", "env-tok")
    assert web._admin_credential_ok("global-tok") is True
    assert web._admin_credential_ok("env-tok") is False


def test_no_token_anywhere_stays_dev_posture(monkeypatch):
    monkeypatch.setattr(web, "USER_TOKEN", "")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "")
    monkeypatch.delenv("JARVIS_USER_TOKEN", raising=False)
    monkeypatch.delenv("JARVIS_ADMIN_TOKEN", raising=False)
    assert web._env_user_active() is False
    assert web._env_admin_active() is False


def test_dev_mode_env_only_late_load(monkeypatch):
    monkeypatch.setattr(web, "DEV_MODE", False)
    monkeypatch.setenv("DEV_MODE", "1")
    assert app_state.dev_mode() is True
    monkeypatch.delenv("DEV_MODE", raising=False)
    assert app_state.dev_mode() is False
    monkeypatch.setattr(web, "DEV_MODE", True)
    assert app_state.dev_mode() is True
