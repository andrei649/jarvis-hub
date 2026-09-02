"""An install refusal has to name the reason a caller can act on.

From a real session: three `POST /api/skills/marketplace/install` in two seconds,
all 404. The route exists — the 404 is `install_skill`'s "not found in registry"
`ValueError` — but nothing in the server log said so, and the neighbouring
refusal was worse: an *acquired* package (sandbox-broker deployment only) came
back as "blocked by moderation/signature policy", which sends an operator off to
moderate a package that moderation can never unblock, because both refusals were
a bare `PermissionError`.

`list_skills` compounded it by returning acquired rows in the same uniform shape
as installable ones, so a UI has no way to know which entries the install
endpoint must reject.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.skills.marketplace import (  # noqa: E402
    BrokerOnlyInstall,
    SkillMarketplace,
)


@pytest.fixture()
def marketplace(tmp_path) -> SkillMarketplace:
    return SkillMarketplace(
        skills_dir=str(tmp_path / "skills"),
        db_path=str(tmp_path / "marketplace.db"),
    )


def _publish(marketplace: SkillMarketplace, name: str) -> None:
    """Put a plain, installable skill into the registry."""
    skill_dir = marketplace.skills_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"# {name}\n\nA test skill.\n", encoding="utf-8"
    )
    marketplace.publish_skill(name)


def _index_acquired(marketplace: SkillMarketplace, name: str) -> None:
    """Write an acquired row directly — the store's own plumbing is not the subject."""
    conn = sqlite3.connect(str(marketplace.db_path))
    try:
        conn.execute(
            "INSERT INTO marketplace_acquired_skills "
            "(name, version, description, author, execution_mode, package_hash, "
            "receipt_hash, runtime_image, signature_json, indexed_at, review_status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                name, "1.0.0", "An acquired package.", "acquisition",
                "acquired_sandbox", "h" * 64, "r" * 64, "python:3.12-slim",
                '{"sig":"x"}', "2026-09-02T10:00:00Z", "approved",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_an_acquired_package_is_refused_as_a_wrong_path_not_a_moderation_verdict(
    marketplace,
):
    _index_acquired(marketplace, "acquired-thing")

    with pytest.raises(BrokerOnlyInstall, match="sandbox broker"):
        marketplace.install_skill("acquired-thing")


def test_the_broker_refusal_is_still_a_permission_error(marketplace):
    """Existing `except PermissionError` handlers must keep catching it."""
    assert issubclass(BrokerOnlyInstall, PermissionError)

    _index_acquired(marketplace, "acquired-thing")
    with pytest.raises(PermissionError):
        marketplace.install_skill("acquired-thing")


def test_an_unknown_name_is_a_registry_miss(marketplace):
    """The observed 404: the name is in neither table."""
    with pytest.raises(ValueError, match="not found in registry"):
        marketplace.install_skill("never-published")


def test_the_listing_marks_which_rows_the_install_endpoint_can_accept(marketplace):
    _publish(marketplace, "plain-skill")
    _index_acquired(marketplace, "acquired-thing")

    rows = {row["name"]: row for row in marketplace.list_skills()}

    assert rows["plain-skill"]["installable"] is True
    assert rows["acquired-thing"]["installable"] is False
    assert rows["acquired-thing"]["install_path"] == "sandbox-broker"


def test_every_listed_row_declares_installability(marketplace):
    """A UI can only rely on the flag if it is on every row, not most of them."""
    _publish(marketplace, "plain-skill")
    _index_acquired(marketplace, "acquired-thing")

    rows = marketplace.list_skills()

    assert rows, "expected the fixture to have populated the registry"
    assert all("installable" in row for row in rows)


def test_the_flag_agrees_with_what_install_actually_does(marketplace):
    """The listing must not be able to drift from the endpoint's behaviour."""
    _publish(marketplace, "plain-skill")
    _index_acquired(marketplace, "acquired-thing")

    for row in marketplace.list_skills():
        if row["installable"]:
            continue
        with pytest.raises(PermissionError):
            marketplace.install_skill(row["name"])


def test_the_route_reports_the_broker_path_separately(marketplace, monkeypatch):
    """End-to-end through the handler: the two 403s must not read the same."""
    import asyncio

    from agents.core.routers import skills as skills_router

    class _Orch:
        def __init__(self, mp):
            self.marketplace = mp

    _index_acquired(marketplace, "acquired-thing")
    monkeypatch.setattr(skills_router, "get_orch", lambda: _Orch(marketplace))

    body = skills_router.InstallSkillBody(name="acquired-thing")
    response = asyncio.run(skills_router.marketplace_install(body))

    assert response.status_code == 403
    payload = response.body.decode()
    assert "sandbox broker" in payload
    assert "moderation" not in payload, (
        "an acquired package has passed moderation; saying otherwise sends the "
        "operator to a gate that cannot unblock it"
    )


def test_the_route_still_reports_a_moderation_block_as_one(marketplace, monkeypatch):
    import asyncio

    from agents.core.routers import skills as skills_router

    class _Blocked:
        def install_skill(self, name):
            raise PermissionError("not approved (review status: pending)")

    class _Orch:
        marketplace = _Blocked()

    monkeypatch.setattr(skills_router, "get_orch", lambda: _Orch())

    response = asyncio.run(
        skills_router.marketplace_install(skills_router.InstallSkillBody(name="x"))
    )

    assert response.status_code == 403
    assert "moderation/signature policy" in response.body.decode()


def test_the_route_reports_a_registry_miss_as_404(marketplace, monkeypatch):
    import asyncio

    from agents.core.routers import skills as skills_router

    class _Orch:
        def __init__(self, mp):
            self.marketplace = mp

    monkeypatch.setattr(skills_router, "get_orch", lambda: _Orch(marketplace))

    response = asyncio.run(
        skills_router.marketplace_install(
            skills_router.InstallSkillBody(name="never-published")
        )
    )

    assert response.status_code == 404
    assert "not found in registry" in response.body.decode()
