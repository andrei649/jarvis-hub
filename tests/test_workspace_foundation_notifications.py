"""Notification rows and the approver/admin recipient queries (spec §5 notifications.py)."""

from __future__ import annotations

import pytest

from agents.core.workspace import db as workspace_db
from agents.core.workspace import notifications
from tests.support.workspace_fixtures import (  # noqa: F401
    db,
    make_department,
    make_user,
    seed_company,
    ws,
)


def _rows(conn, user_id):
    return conn.execute("SELECT * FROM notifications WHERE user_id = ? ORDER BY id", (user_id,)).fetchall()


def test_notify_dedupes_and_commits_on_its_own(ws):
    conn = db()
    company = seed_company(conn)
    notifications.notify(conn, [company.member_a.id, company.member_a.id, None, company.member_b.id],
                         kind="report.ready", title="Raportul e gata", body="Detalii", link="/workspace/reports/3")
    assert not conn.in_transaction
    rows = _rows(db(), company.member_a.id)
    assert len(rows) == 1
    assert (rows[0]["title"], rows[0]["body"], rows[0]["link"]) == ("Raportul e gata", "Detalii",
                                                                    "/workspace/reports/3")
    assert len(_rows(conn, company.member_b.id)) == 1


def test_notify_joins_the_callers_transaction(ws):
    conn = db()
    company = seed_company(conn)
    with pytest.raises(RuntimeError), workspace_db.tx(conn):
        notifications.notify(conn, [company.member_a.id], kind="x", title="t")
        raise RuntimeError("rolled back together")
    assert _rows(conn, company.member_a.id) == []


def test_notify_nobody_is_a_no_op(ws):
    conn = db()
    notifications.notify(conn, [], kind="x", title="t")
    notifications.notify(conn, [None], kind="x", title="t")
    assert conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 0


@pytest.mark.parametrize(("link", "stored"), [
    ("/workspace/approvals/1", "/workspace/approvals/1"), ("javascript:alert(1)", ""),
    ("https://evil.example", ""), ("//evil.example/x", ""), ("", ""), ("/" + "x" * 600, ""),
    # browsers read these as //evil.example (backslash, or a tab/newline they strip)
    ("/\\evil.example", ""), ("/\tevil.example", ""), ("/\n/evil.example", ""),
    ("/ /evil.example", ""), ("/\u2028/evil.example", ""),
    ("/workspace/rapoarte/ședință?id=3", "/workspace/rapoarte/ședință?id=3"),
])
def test_only_app_relative_links_are_kept(ws, link, stored):
    conn = db()
    company = seed_company(conn)
    notifications.notify(conn, [company.member_a.id], kind="x", title="t", link=link)
    assert _rows(conn, company.member_a.id)[0]["link"] == stored


def test_long_texts_are_truncated(ws):
    conn = db()
    company = seed_company(conn)
    notifications.notify(conn, [company.member_a.id], kind="x", title="t" * 500, body="b" * 5000)
    row = _rows(conn, company.member_a.id)[0]
    assert len(row["title"]) == notifications.MAX_TITLE and len(row["body"]) == notifications.MAX_BODY


def test_admins_and_department_approvers(ws):
    conn = db()
    company = seed_company(conn)
    approver_b = make_user(conn, role="approver", department_ids=[company.dept_b])
    make_user(conn, role="approver", department_ids=[company.dept_a], status="disabled")
    make_user(conn, role="admin", department_ids=[company.dept_b], status="invited")
    second_admin = make_user(conn, role="admin", department_ids=[company.dept_b])
    assert notifications.admins(conn) == [company.admin.id, second_admin.id]
    assert notifications.admins(conn, exclude=company.admin.id) == [second_admin.id]
    assert notifications.department_approvers(conn, company.dept_a) == sorted(
        [company.admin.id, company.approver_a.id, second_admin.id])
    assert notifications.department_approvers(conn, company.dept_b, exclude=second_admin.id) == sorted(
        [company.admin.id, approver_b.id])
    archived = make_department(conn, "Vechi", archived=True)
    make_user(conn, role="approver", department_ids=[archived])
    assert notifications.department_approvers(conn, archived) == [company.admin.id, second_admin.id]


def test_unread_count_list_and_mark_read(ws):
    conn = db()
    company = seed_company(conn)
    for n in range(3):
        notifications.notify(conn, [company.member_a.id], kind="x", title=f"n{n}")
    notifications.notify(conn, [company.member_b.id], kind="x", title="other")
    ids = [row["id"] for row in _rows(conn, company.member_a.id)]
    other = _rows(conn, company.member_b.id)[0]["id"]
    assert notifications.unread_count(conn, company.member_a.id) == 3
    assert [n["title"] for n in notifications.list_for_user(conn, company.member_a.id,
                                                            unread_only=False, limit=2)] == ["n2", "n1"]
    assert notifications.mark_read(conn, company.member_a.id, ids=[ids[0], other]) == 1
    assert notifications.mark_read(conn, company.member_a.id, ids=[ids[0]]) == 0, "already read"
    assert notifications.mark_read(conn, company.member_a.id) == 0
    unread = notifications.list_for_user(conn, company.member_a.id, unread_only=True, limit=50)
    assert [n["title"] for n in unread] == ["n2", "n1"] and unread[0]["read"] is False
    assert notifications.mark_read(conn, company.member_a.id, all_unread=True) == 2
    assert notifications.unread_count(conn, company.member_a.id) == 0
    assert notifications.unread_count(conn, company.member_b.id) == 1
