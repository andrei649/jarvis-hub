"""Password hashing and policy, the user value object and JSON shapes (spec §5, §6)."""

from __future__ import annotations

import pytest

from agents.core.workspace import db as workspace_db
from agents.core.workspace import identity
from agents.core.workspace.errors import WorkspaceError
from agents.core.workspace.identity import WorkspaceUser
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    DEFAULT_PASSWORD,
    db,
    make_department,
    make_user,
    seed_org,
    ws,
)


def test_hash_format_and_round_trip(ws):
    stored = identity.hash_password("correct horse battery")
    scheme, log_n, r, p, salt, digest = stored.split("$")
    assert (scheme, log_n, r, p) == ("scrypt", "10", "8", "1")
    assert len(salt) == 24 and len(digest) == 44  # base64 of 16 and 32 bytes
    assert identity.verify_password("correct horse battery", stored)
    assert not identity.verify_password("correct horse batterY", stored)
    assert identity.hash_password("correct horse battery") != stored, "fresh salt every time"


def test_work_factor_lives_in_the_hash(ws, monkeypatch):
    stored = identity.hash_password("a long enough secret phrase")
    monkeypatch.setattr(identity, "SCRYPT_N", 2 ** 11)
    assert identity.verify_password("a long enough secret phrase", stored)
    assert identity.hash_password("x" * 12).split("$")[1] == "11"


def test_production_work_factor_fits_the_memory_cap():
    """n=2**15, r=8 needs 32 MiB+ — the default maxmem would refuse it (spec Appendix A)."""
    assert identity.SCRYPT_N == 2 ** 15
    stored = identity.hash_password("production strength phrase")
    assert stored.split("$")[1] == "15"
    assert identity.verify_password("production strength phrase", stored)


@pytest.mark.parametrize("stored", [None, "", "plain", "scrypt$10$8$1$bad$", "md5$x$y$z$a$b",
                                    "scrypt$30$8$1$AAAAAAAAAAAAAAAAAAAAAA==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="])
def test_unusable_hashes_fail_after_a_dummy_verify(ws, monkeypatch, stored):
    calls = []
    real = identity._scrypt

    def counting(*args, **kwargs):
        calls.append(args[2])  # n
        return real(*args, **kwargs)

    identity._DUMMY_HASHES.clear()
    identity._dummy_hash()  # precompute, so only the verify itself is counted
    monkeypatch.setattr(identity, "_scrypt", counting)
    assert identity.verify_password("whatever-you-type", stored) is False
    assert calls == [identity.SCRYPT_N], "exactly one scrypt at the current work factor"


_SALT = "AAAAAAAAAAAAAAAAAAAAAA=="
_DIGEST = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


@pytest.mark.parametrize("stored", [
    f"scrypt$17$8$1${_SALT}${_DIGEST}",   # 128 MiB: over the 64 MiB maxmem
    f"scrypt$15$16$1${_SALT}${_DIGEST}",  # r=16 doubles it past the cap
    f"scrypt$18$1$1${_SALT}${_DIGEST}",   # OpenSSL wants n < 2**(16 r)
])
def test_hashes_scrypt_would_refuse_are_a_failed_login_not_a_crash(ws, monkeypatch, stored):
    calls = []
    real = identity._scrypt
    identity._DUMMY_HASHES.clear()
    identity._dummy_hash()
    monkeypatch.setattr(identity, "_scrypt",
                        lambda *args, **kwargs: calls.append(args[2]) or real(*args, **kwargs))
    assert identity.verify_password("whatever-you-type", stored) is False
    assert calls == [identity.SCRYPT_N], "refused parameters burn the dummy verify instead"


def test_an_openssl_refusal_during_verify_is_a_failed_login(ws, monkeypatch, caplog):
    stored = identity.hash_password("correct horse battery")

    def refuse(*args, **kwargs):
        raise ValueError("[digital envelope routines] memory limit exceeded")

    monkeypatch.setattr(identity, "_scrypt", refuse)
    assert identity.verify_password("correct horse battery", stored) is False
    assert "correct horse" not in caplog.text


@pytest.mark.parametrize(("password", "reason"), [
    ("short-1A!", "too_short"),
    ("x" * 257, "too_long"),
    ("ana.popescu-2026!", "contains_email"),
    ("password1234", "too_common"),
    ("Password2026!", "too_common"),
    ("parolaparola", "too_common"),
    ("Bucuresti!!!123", "too_common"),
    ("aaaaaaaaaaaaaaa", "too_common"),
    ("abababababab", "too_common"),
])
def test_validate_password_reasons(password, reason):
    with pytest.raises(WorkspaceError) as caught:
        identity.validate_password(password, email="Ana.Popescu@acme.test")
    assert (caught.value.status, caught.value.code) == (422, "weak_password")
    assert caught.value.extra["reason"] == reason


@pytest.mark.parametrize("password", [DEFAULT_PASSWORD, ("Ana are mere " * 20)[:256], "un camion verde pe deal",
                                      "Ana are mere 2026"])
def test_validate_password_accepts_good_ones(password):
    identity.validate_password(password, email="ana.popescu@acme.test")


def test_short_local_parts_do_not_block_passwords():
    identity.validate_password("a quite long passphrase", email="a@acme.test")


def test_common_list_is_large_enough():
    assert len(identity._COMMON_CHOICES) >= 100


def _user(role="member", departments=(1, 2)) -> WorkspaceUser:
    return WorkspaceUser(id=7, email="u@acme.test", name="U", role=role, status="active",
                         locale="ro", theme="light", department_ids=tuple(departments))


@pytest.mark.parametrize("bad", [None, "company", identity.COMPANY, True, 1.0])
def test_department_checks_refuse_non_ids(bad):
    with pytest.raises(TypeError):
        _user().can_access_department(bad)
    with pytest.raises(TypeError):
        _user("admin").can_approve_in(bad)


def test_department_access_and_approval_rules():
    member, approver, admin = _user(), _user("approver"), _user("admin", ())
    assert member.can_access_department(1) and not member.can_access_department(3)
    assert admin.can_access_department(3), "admins reach every department"
    assert not member.can_approve_in(1)
    assert approver.can_approve_in(2) and not approver.can_approve_in(3)
    assert admin.can_approve_in(99)
    assert admin.is_admin and not approver.is_admin


def test_archived_departments_are_admin_only(ws):
    conn = db()
    seed_org(conn)
    live = make_department(conn, "Live")
    gone = make_department(conn, "Gone", archived=True)
    member = make_user(conn, role="member", department_ids=[live, gone])
    admin = make_user(conn, role="admin", department_ids=[live])
    assert member.department_ids == (live,)
    assert not member.can_access_department(gone)
    assert admin.can_access_department(gone)
    assert member.allowed_department_ids(conn) == [live]
    assert admin.allowed_department_ids(conn) == [live], "admins work in non-archived ones"
    assert identity.member_department_ids(conn, member.id) == sorted([live, gone])
    conn.close()


def test_get_user_and_lookup_by_email(ws):
    conn = db()
    seed_org(conn)
    dept = make_department(conn, "Sales")
    user = make_user(conn, role="approver", department_ids=[dept], email="Mixed.Case@Acme.test")
    assert user.email == "mixed.case@acme.test"
    assert identity.get_user(conn, user.id) == user
    assert identity.get_user(conn, 999) is None
    assert identity.get_user_by_email(conn, "MIXED.case@acme.TEST")["id"] == user.id
    assert identity.get_user_by_email(conn, "nobody@acme.test") is None
    conn.close()


def test_user_to_json_shape(ws):
    conn = db()
    seed_org(conn)
    a = make_department(conn, "A")
    b = make_department(conn, "B")
    member = make_user(conn, role="member", department_ids=[a])
    admin = make_user(conn, role="admin", department_ids=[a])
    data = identity.user_to_json(member)
    assert set(data) == {"id", "email", "name", "role", "status", "locale", "theme",
                         "department_ids", "permissions"}
    assert data["permissions"] == {"admin_console": False, "approve": False,
                                   "decide_admin_approvals": False, "upload_company": False}
    assert identity.user_to_json(member, conn)["permissions"]["department_ids"] == [a]
    admin_perms = identity.user_to_json(admin, conn)["permissions"]
    assert admin_perms["admin_console"] and admin_perms["upload_company"]
    assert admin_perms["department_ids"] == [a, b]
    conn.close()


def test_department_and_org_json(ws):
    conn = db()
    org = seed_org(conn, "Acme SRL")
    assert org == {"name": "Acme SRL", "default_locale": "ro", "model_policy": "local_only",
                   "created_at": org["created_at"]}
    with workspace_db.tx(conn):
        conn.execute("UPDATE org SET settings_json = '{\"smtp\": {\"host\": \"x\"}}'")
    assert "settings_json" not in identity.org_to_json(identity.ensure_org(conn))
    dept = make_department(conn, "HR", archived=True)
    row = conn.execute("SELECT * FROM departments WHERE id = ?", (dept,)).fetchone()
    data = identity.department_to_json(row, counts={"member_count": 3})
    assert data["archived"] is True and data["member_count"] == 3 and data["slug"] == "hr"
    conn.close()


def test_ensure_org_is_none_before_setup(ws):
    conn = db()
    assert identity.ensure_org(conn) is None
    conn.close()


@pytest.mark.parametrize(("name", "slug"), [
    ("Vânzări & Marketing", "vanzari-marketing"), ("  Resurse Umane ", "resurse-umane"),
    ("Țesături/Ștofe", "tesaturi-stofe"), ("!!!", "departament"), ("IT", "it"),
])
def test_slugify(name, slug):
    assert identity.slugify(name) == slug


def test_slugs_are_bounded_and_unique(ws):
    conn = db()
    long_name = "Departamentul " * 10
    first = make_department(conn, long_name)
    second = make_department(conn, long_name)
    slugs = [row["slug"] for row in conn.execute(
        "SELECT slug FROM departments WHERE id IN (?, ?) ORDER BY id", (first, second))]
    assert all(len(slug) <= 64 for slug in slugs)
    assert slugs[1].endswith("-2") and slugs[0] != slugs[1]
    assert identity.unique_department_slug(conn, long_name).endswith("-3")
    conn.close()
