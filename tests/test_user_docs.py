"""H23.18 — user docs exist, cover the essentials, and are discoverable.

Light guard against bit-rot for USER_GUIDE / FAQ / UPGRADE.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_user_guide_covers_install_run_and_data():
    g = _read("docs/USER_GUIDE.md").lower()
    for topic in ("install", "start", "admin", "model", "127.0.0.1:8080"):
        assert topic in g, f"USER_GUIDE missing: {topic}"


def test_faq_answers_core_privacy_and_update_questions():
    f = _read("docs/FAQ.md").lower()
    assert "leave my machine" in f          # the #1 question
    assert "telemetry" in f
    assert "gpu" in f
    assert "update" in f or "upgrade" in f


def test_upgrade_doc_has_steps_and_migration_note():
    u = _read("docs/UPGRADE.md").lower()
    assert "migration" in u                 # automatic schema migrations
    assert "back up" in u or "backup" in u  # rollback path
    assert "rollback" in u


def test_user_docs_are_discoverable():
    readme = _read("README.md")
    for name in ("USER_GUIDE.md", "FAQ.md", "UPGRADE.md"):
        assert name in readme, f"README does not link {name}"
