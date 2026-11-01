"""H026 — named skill bundles: several skills under one name, switched as one unit.

Hermes keeps ``hermes bundles list|show|create|delete|reload`` over YAML files of
``{name, skills[], description?}``. Nerva keeps the same files under the data root
(``agents/core/skills/bundles.py``), serves them at ``/api/skills/bundles*`` and drives
them from ``nerva skills bundles`` and the Skill Switches panel. A bundle is switched off
or on as one unit through the H329 switch (``POST /api/skills/switch`` with ``bundle``):
off narrows at once, on queues the same exact-target, once-scoped approval one skill
gets, and the worker refuses it when the bundle no longer means those skills. These
tests pin the lifecycle and that a bundle never reaches further than its members'
own switches.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import settings_db  # noqa: E402
from agents.core.skills import bundles, switches  # noqa: E402
from agents.core.skills import loader as loader_mod  # noqa: E402
from tests.test_h329_skill_switches import (  # noqa: E402
    _TOKEN,
    _approve,
    _cli,
    _client,
    _ready_approval,
    _skill,
)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", tmp_path / "skills")
    monkeypatch.setattr(bundles, "bundles_dir", lambda: tmp_path / "skill-bundles")
    monkeypatch.setattr(bundles, "_CACHE", {"dir": None, "key": None, "bundles": {}, "problems": []})
    yield


def _dir(tmp_path) -> Path:
    return tmp_path / "skill-bundles"


def _write(tmp_path, filename, text):
    folder = _dir(tmp_path)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    path.write_text(text, encoding="utf-8")
    return path


def _admin(client, method, path, body=None):
    return client.request(method, path, json=body, headers={"X-Admin-Token": _TOKEN})


def _switch(client, body):
    return _admin(client, "POST", "/api/skills/switch", body)


# ── the store ────────────────────────────────────────────────────────────────────

def test_the_slug_follows_hermes():
    assert bundles.slugify("My Bundle") == "my-bundle"
    assert bundles.slugify("my_bundle") == "my-bundle"
    assert bundles.slugify("  Ops!!  Pack  ") == "ops-pack"
    assert bundles.slugify("--a--b--") == "a-b"
    assert bundles.slugify("!!!") == "" and bundles.slugify("") == "" and bundles.slugify(None) == ""
    assert bundles.slugify("x" * 64) == "x" * 64 and bundles.slugify("x" * 65) == ""


def test_create_show_list_replace_and_delete(tmp_path):
    bundle, replaced = bundles.save("Morning Brief", ["Weather Intel", "News", "news"],
                                    description="  what I read  at  breakfast ")
    assert replaced is False and bundle.slug == "morning-brief"
    assert bundle.skills == ("Weather Intel", "News") and bundle.description == "what I read at breakfast"
    path = _dir(tmp_path) / "morning-brief.yaml"
    assert bundle.path == path
    assert path.read_text(encoding="utf-8") == (
        "name: Morning Brief\nskills:\n- Weather Intel\n- News\ndescription: what I read at breakfast\n")
    # Any casing, spaces or underscores name it.
    assert bundles.get("MORNING_BRIEF") == bundle and bundles.get("morning brief") == bundle
    bundles.save("Evening", ["Spotify"])
    assert [b.slug for b in bundles.list_bundles()] == ["evening", "morning-brief"]

    with pytest.raises(bundles.BundleError) as refused:
        bundles.save("morning_brief", ["Spotify"])
    assert refused.value.reason == "exists"
    assert bundles.get("Morning Brief").skills == ("Weather Intel", "News")
    again, replaced = bundles.save("Morning Brief", ["Spotify"], overwrite=True)
    assert replaced is True and again.skills == ("Spotify",) and again.description == ""
    assert sorted(p.name for p in _dir(tmp_path).iterdir()) == ["evening.yaml", "morning-brief.yaml"]

    gone = bundles.delete("Morning Brief")
    assert gone.slug == "morning-brief" and not path.exists() and bundles.get("morning-brief") is None
    with pytest.raises(bundles.BundleError) as refused:
        bundles.delete("Morning Brief")
    assert refused.value.reason == "not_found"


@pytest.mark.parametrize("name,members,reason", [
    ("", ["a"], "bad_name"),
    ("!!!", ["a"], "bad_name"),
    ("x" * 65, ["a"], "bad_name"),
    ("ok", [], "no_skills"),
    ("ok", ["  "], "no_skills"),
    ("ok", "Spotify", "bad_skills"),
    ("ok", ["a", 3], "bad_skills"),
    ("ok", ["x" * 200], "bad_skills"),
    ("ok", [f"s{i}" for i in range(bundles.MAX_MEMBERS + 1)], "too_many"),
])
def test_a_bad_bundle_is_refused_and_nothing_is_written(tmp_path, name, members, reason):
    with pytest.raises(bundles.BundleError) as refused:
        bundles.save(name, members)
    assert refused.value.reason == reason
    assert not _dir(tmp_path).exists() or list(_dir(tmp_path).iterdir()) == []


def test_the_bundle_count_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(bundles, "MAX_BUNDLES", 2)
    bundles.save("a", ["x"])
    bundles.save("b", ["x"])
    with pytest.raises(bundles.BundleError) as refused:
        bundles.save("c", ["x"])
    assert refused.value.reason == "too_many_bundles"
    assert bundles.save("b", ["y"], overwrite=True)[1] is True        # replacing one still works


def test_a_hand_written_or_hermes_file_loads_and_a_broken_one_is_named(tmp_path):
    _write(tmp_path, "focus.yml", "name: Deep Focus\nskills: [Spotify, notes]\n"
                                  "description: quiet hours\ninstruction: ignored here\n")
    _write(tmp_path, "broken.yaml", "name: [unclosed\n")
    _write(tmp_path, "list.yaml", "- a\n- b\n")
    _write(tmp_path, "empty.yaml", "name: Empty\nskills: []\n")
    _write(tmp_path, "nameless.yaml", "skills: [a]\n")
    _write(tmp_path, "twin.yaml", "name: deep_focus\nskills: [a]\n")       # the same slug, later file
    _write(tmp_path, "huge.yaml", "name: Huge\nskills: [a]\n# " + "x" * bundles.MAX_FILE_BYTES + "\n")
    _write(tmp_path, "notes.txt", "name: Not a bundle\nskills: [a]\n")
    os.symlink(_dir(tmp_path) / "focus.yml", _dir(tmp_path) / "link.yaml")
    rows, skipped = bundles.snapshot()
    assert [(b.name, b.slug, b.skills, b.description) for b in rows] == [
        ("Deep Focus", "deep-focus", ("Spotify", "notes"), "quiet hours")]
    reasons = {p["file"]: p["reason"] for p in skipped}
    assert reasons == {"broken.yaml": "invalid_yaml", "list.yaml": "invalid_yaml", "empty.yaml": "no_skills",
                       "nameless.yaml": "bad_name", "twin.yaml": "duplicate", "huge.yaml": "too_large",
                       "link.yaml": "not_a_file"}
    assert all(p["detail"] for p in skipped)


def test_a_hand_edit_is_read_without_a_reload_and_reload_reports_changes(tmp_path):
    assert bundles.reload() == {"added": [], "removed": [], "changed": [], "total": 0, "problems": []}
    _write(tmp_path, "a.yaml", "name: Alpha\nskills: [x]\ndescription: first\n")
    _write(tmp_path, "b.yaml", "name: Beta\nskills: [y]\n")
    report = bundles.reload()
    assert report["added"] == [{"name": "Alpha", "slug": "alpha", "description": "first"},
                               {"name": "Beta", "slug": "beta", "description": ""}]
    assert report["removed"] == [] and report["total"] == 2
    assert bundles.reload()["added"] == []                                 # nothing new since
    (_dir(tmp_path) / "b.yaml").unlink()
    _write(tmp_path, "a.yaml", "name: Alpha\nskills: [x, z]\n")
    _write(tmp_path, "bad.yaml", "name: Bad\n")
    assert bundles.get("alpha").skills == ("x", "z")                       # a read sees the edit
    report = bundles.reload()
    assert report["changed"] == [] and report["total"] == 1                # already seen by that read
    assert [p["file"] for p in report["problems"]] == ["bad.yaml"]
    _write(tmp_path, "a.yaml", "name: Alpha\nskills: [q]\n")
    report = bundles.reload()
    assert report["changed"] == ["alpha"] and report["removed"] == []
    (_dir(tmp_path) / "a.yaml").unlink()
    assert bundles.reload()["removed"] == [{"name": "Alpha", "slug": "alpha"}]


def test_members_resolve_like_one_skill_switch_and_missing_ones_are_named(tmp_path):
    weather = _skill(tmp_path, "weather", "Weather Intel")
    other = _skill(tmp_path, "weather2", "weather")              # a manifest name equal to a folder
    news = _skill(tmp_path, "news", "News")
    loaded = [weather, other, news]
    targets, missing = bundles.resolve(["WEATHER", "Weather Intel", "news", "ghost", "weath"], loaded)
    assert [s.name for s in targets] == ["weather", "Weather Intel", "News"] and missing == ["ghost", "weath"]
    assert switches.find(loaded, "weather") is other and switches.find(loaded, "  ") is None


# ── the routes ───────────────────────────────────────────────────────────────────

def test_the_routes_keep_bundles_with_installed_members(monkeypatch, tmp_path):
    client, _orch = _client(monkeypatch, tmp_path)
    resp = _admin(client, "POST", "/api/skills/bundles",
                  {"name": "Morning", "skills": ["weather", "News", "security_monitor"], "description": "am"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["replaced"] is False
    row = body["bundle"]
    assert row["slug"] == "morning" and row["skills"] == ["Weather Intel", "News", "Security Monitor"]
    assert row["installed"] == row["skills"] and row["missing"] == []
    # An unknown member is refused by name, nothing is written.
    resp = _admin(client, "POST", "/api/skills/bundles", {"name": "Ghosts", "skills": ["ghost", "news"]})
    assert resp.status_code == 422 and resp.json()["reason"] == "unknown_skill" and resp.json()["unknown"] == ["ghost"]
    assert bundles.get("ghosts") is None
    resp = _admin(client, "POST", "/api/skills/bundles", {"name": "morning", "skills": ["spotify"]})
    assert resp.status_code == 409 and resp.json()["reason"] == "exists"
    resp = _admin(client, "POST", "/api/skills/bundles", {"name": "morning", "skills": ["spotify"], "overwrite": True})
    assert resp.status_code == 200 and resp.json()["replaced"] is True
    assert _admin(client, "POST", "/api/skills/bundles", {"name": "x", "skills": []}).status_code == 422
    # A member uninstalled later is reported missing, never matched loosely.
    _write(tmp_path, "later.yaml", "name: Later\nskills: [Spotify, Old Skill]\n")
    listing = client.get("/api/skills/bundles").json()
    rows = {r["slug"]: r for r in listing["bundles"]}
    assert set(rows) == {"later", "morning"} and rows["later"]["missing"] == ["Old Skill"]
    assert rows["later"]["installed"] == ["Spotify"] and listing["problems"] == []
    assert listing["directory"] == str(_dir(tmp_path))
    shown = client.get("/api/skills/bundles/LATER").json()["bundle"]
    assert shown["name"] == "Later" and shown["file"] == str(_dir(tmp_path) / "later.yaml")
    assert client.get("/api/skills/bundles/nope").status_code == 404
    reload = _admin(client, "POST", "/api/skills/bundles/reload").json()
    assert reload["ok"] is True and reload["total"] == 2
    deleted = _admin(client, "DELETE", "/api/skills/bundles/later")
    assert deleted.status_code == 200 and deleted.json()["deleted"]["slug"] == "later"
    assert not (_dir(tmp_path) / "later.yaml").exists()
    assert _admin(client, "DELETE", "/api/skills/bundles/later").status_code == 404
    assert switches.state() == {"disabled": [], "channel_disabled": {}}     # keeping bundles switches nothing


def test_the_bundle_writes_are_admin_only_and_the_reads_are_not_open(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import _deps

    client, _orch = _client(monkeypatch, tmp_path)
    monkeypatch.delitem(web.app.dependency_overrides, _deps.user_guard)    # the suite's no-op guard
    bundles.save("Morning", ["Weather Intel"])
    assert client.post("/api/skills/bundles", json={"name": "x", "skills": ["news"]}).status_code in (401, 403)
    assert client.delete("/api/skills/bundles/morning").status_code in (401, 403)
    assert client.post("/api/skills/bundles/reload").status_code in (401, 403)
    assert client.post("/api/skills/switch", json={"bundle": "morning", "enabled": False}).status_code in (401, 403)
    assert bundles.get("morning") is not None and bundles.get("x") is None
    lan = TestClient(web.app, client=("192.168.1.77", 5555), base_url="http://192.168.1.10:8000")
    assert lan.get("/api/skills/bundles").status_code in (401, 403)
    assert lan.get("/api/skills/bundles/morning").status_code in (401, 403)
    monkeypatch.setattr(web, "USER_TOKEN", "h026-user")
    assert lan.get("/api/skills/bundles", headers={"X-User-Token": "h026-user"}).status_code == 200


def test_a_bundle_switches_off_as_one_unit_like_its_members(monkeypatch, tmp_path):
    client, orch = _client(monkeypatch, tmp_path)
    _write(tmp_path, "morning.yaml", "name: Morning\nskills: [Weather Intel, news, Security Monitor, Gone]\n")
    resp = _switch(client, {"bundle": "Morning", "enabled": False, "channel": "Telegram"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["changed"] == ["Weather Intel", "News"] and body["essential"] == ["Security Monitor"]
    assert body["bundle"] == "morning" and body["missing"] == ["Gone"] and body["channel"] == "telegram"
    assert switches.state() == {"disabled": [], "channel_disabled": {"telegram": ["Weather Intel", "News"]}}
    row = orch.intent_log.rows[0]
    assert row["action"] == "skill.disable" and row["metadata"]["bundle"] == "morning"
    assert row["metadata"]["skills"] == ["Weather Intel", "News"]
    again = _switch(client, {"bundle": "morning", "enabled": False, "channel": "telegram"}).json()
    assert again["changed"] == [] and again["unchanged"] == ["Weather Intel", "News"]


@pytest.mark.parametrize("payload,status,reason", [
    ({"bundle": "ghost", "enabled": False}, 404, "not_found"),
    ({"bundle": "nobody", "enabled": False}, 404, "not_found"),
    ({"bundle": "morning", "skill": "weather", "enabled": False}, 422, "bad_target"),
    ({"bundle": "morning", "category": "info", "enabled": True}, 422, "bad_target"),
])
def test_the_bundle_switch_refuses(monkeypatch, tmp_path, payload, status, reason):
    client, orch = _client(monkeypatch, tmp_path)
    _write(tmp_path, "morning.yaml", "name: Morning\nskills: [Weather Intel]\n")
    _write(tmp_path, "nobody.yaml", "name: Nobody\nskills: [Gone, Also Gone]\n")
    resp = _switch(client, payload)
    assert resp.status_code == status and resp.json()["reason"] == reason
    if payload["bundle"] == "nobody":
        assert resp.json()["missing"] == ["Gone", "Also Gone"]
    assert switches.state() == {"disabled": [], "channel_disabled": {}} and orch.intent_log.rows == []


def test_a_bundle_switches_on_through_the_same_exact_approval_as_its_members(monkeypatch, tmp_path):
    client, orch = _client(monkeypatch, tmp_path)
    _ready_approval(monkeypatch, tmp_path, orch)
    bundles.save("Morning", ["Weather Intel", "News", "Gone"])
    assert _switch(client, {"bundle": "morning", "enabled": False}).json()["changed"] == ["Weather Intel", "News"]
    assert _switch(client, {"skill": "spotify", "enabled": False}).status_code == 200

    pending = _switch(client, {"bundle": "morning", "enabled": True})
    assert pending.status_code == 202, pending.text
    body = pending.json()
    assert body["status"] == "pending" and body["pending"] == ["Weather Intel", "News"]
    assert body["bundle"] == "morning" and body["missing"] == ["Gone"]
    assert switches.state()["disabled"] == ["Weather Intel", "News", "Spotify"]     # nothing widened yet
    # The same queued kind, surface, scope and risk tier one skill's switch-on gets.
    single = _switch(client, {"skill": "spotify", "enabled": True})
    assert single.status_code == 202
    bundle_task, skill_task = orch._queued_switches
    for key in ("agent", "kind", "risk_tier", "autonomy_level", "origin"):
        assert bundle_task[key] == skill_task[key], key
    for key in ("kind", "surface", "scope", "risk_tier", "reversible", "requested_by"):
        assert bundle_task["payload"][key] == skill_task["payload"][key], key
    assert bundle_task["payload"]["kind"] == "permission.grant" and bundle_task["payload"]["scope"] == "once"
    assert bundle_task["title"] == "Switch on News, Weather Intel everywhere (bundle morning)"

    assert _approve(orch, body["task_id"])["status"] == "ok"
    assert switches.state()["disabled"] == ["Spotify"]                    # exactly the members, no more
    assert _approve(orch, body["task_id"])["status"] == "refused"          # no replay


@pytest.mark.parametrize("edit", ["add_member", "drop_member", "delete_bundle", "install_missing"])
def test_a_bundle_changed_before_approval_widens_nothing(monkeypatch, tmp_path, edit):
    client, orch = _client(monkeypatch, tmp_path)
    _ready_approval(monkeypatch, tmp_path, orch)
    bundles.save("Morning", ["Weather Intel", "News", "Late"])
    _switch(client, {"bundle": "morning", "enabled": False})
    _switch(client, {"skill": "spotify", "enabled": False})
    pending = _switch(client, {"bundle": "morning", "enabled": True}).json()
    if edit == "add_member":
        bundles.save("Morning", ["Weather Intel", "News", "Spotify"], overwrite=True)
    elif edit == "drop_member":
        bundles.save("Morning", ["Weather Intel"], overwrite=True)
    elif edit == "delete_bundle":
        bundles.delete("morning")
    else:
        from agents.core.skills import signing

        late = _skill(tmp_path, "late", "Late")
        late.source_fingerprint = signing.source_snapshot(late.path).fingerprint
        orch.skills.skills["Late"] = late
    assert _approve(orch, pending["task_id"]) == {"status": "refused", "reason": "stale_skill_bundle"}
    assert switches.state()["disabled"] == ["Weather Intel", "News", "Spotify"]
    grant = orch.permission_ledger.list_grants(include_inactive=True)[0]
    assert grant.status != "active"                                        # the minted grant is retired


def _stored_records():
    import json

    conn = settings_db.get_conn()
    try:
        return [json.loads(row["record"]) for row in
                conn.execute("SELECT record FROM skill_switch_requests ORDER BY task_id").fetchall()]
    finally:
        conn.close()


def test_only_a_bundle_request_carries_the_bundle_so_older_bindings_hold(monkeypatch, tmp_path):
    """A skill or category approval queued before H026 still matches its binding: the
    stored record gains a ``bundle`` key only for a bundle's request."""
    client, orch = _client(monkeypatch, tmp_path)
    _ready_approval(monkeypatch, tmp_path, orch)
    bundles.save("Evening", ["Spotify"])
    _switch(client, {"category": "info", "enabled": False})
    _switch(client, {"bundle": "evening", "enabled": False})
    category = _switch(client, {"category": "info", "enabled": True}).json()
    _switch(client, {"bundle": "evening", "enabled": True})
    first, second = _stored_records()
    assert set(first) == {"targets", "channel", "category", "revision", "requested_by"}
    assert first["category"] == "info" and second["bundle"] == "evening" and second["category"] == ""
    assert orch._queued_switches[0]["title"].endswith("everywhere (category info)")
    assert _approve(orch, category["task_id"])["status"] == "ok"
    assert switches.state()["disabled"] == ["Spotify"]


def test_a_bundle_switch_on_crosses_the_kernel_and_a_denial_queues_nothing(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from agents.core.kernel import Verdict

    client, orch = _client(monkeypatch, tmp_path)
    _ready_approval(monkeypatch, tmp_path, orch)
    bundles.save("Morning", ["Weather Intel", "News"])
    _switch(client, {"bundle": "morning", "enabled": False})
    seen = []
    orch.permission_ledger._authorizer = lambda action: (seen.append(action)
                                                         or SimpleNamespace(verdict=Verdict.DENY, reason="owner gate"))
    resp = _switch(client, {"bundle": "morning", "enabled": True})
    assert resp.status_code == 503 and resp.json()["reason"] == "approval_unavailable"
    assert [a.kind for a in seen] == ["permission.grant"] and seen[0].payload["surface"] == "skill_switch"
    assert orch._queued_switches == [] and switches.state()["disabled"] == ["Weather Intel", "News"]


# ── the CLI ──────────────────────────────────────────────────────────────────────

_ROW = {"name": "Morning", "slug": "morning", "skills": ["Weather Intel", "News", "Gone"],
        "description": "am", "file": "/data/skill-bundles/morning.yaml",
        "installed": ["Weather Intel", "News"], "missing": ["Gone"]}


def test_nerva_skills_bundles_create_list_show_delete_reload():
    code, out, _err, calls = _cli(
        ["skills", "bundles", "create", "Morning", "-s", "weather", "--skill", "news", "-d", "am"],
        {"POST /api/skills/bundles": {"ok": True, "replaced": False, "bundle": _ROW}})
    assert code == 0 and calls == [("POST", "/api/skills/bundles",
                                    {"name": "Morning", "skills": ["weather", "news"], "description": "am",
                                     "overwrite": False})]
    assert out.splitlines() == ["created bundle Morning (3 skills): /data/skill-bundles/morning.yaml",
                                "  switch it as one unit: nerva skills off|on --bundle morning"]
    code, _out, _err, calls = _cli(["skills", "bundles", "create", "Morning", "-s", "x", "--force"],
                                   {"POST /api/skills/bundles": {"ok": True, "replaced": True, "bundle": _ROW}})
    assert calls[0][2]["overwrite"] is True

    listing = {"bundles": [_ROW], "problems": [{"file": "bad.yaml", "reason": "invalid_yaml",
                                                "detail": "not UTF-8 YAML"}],
               "directory": "/data/skill-bundles"}
    code, out, _err, _calls = _cli(["skills", "bundles", "list"], {"GET /api/skills/bundles": listing})
    assert code == 0 and out.splitlines() == ["morning  Morning  3 skills (1 not installed)  am",
                                              "skipped bad.yaml: not UTF-8 YAML",
                                              "bundles folder: /data/skill-bundles"]
    code, out, _err, _calls = _cli(["skills", "bundles", "list"],
                                   {"GET /api/skills/bundles": {"bundles": [], "problems": []}})
    assert out.startswith("no bundles yet")

    code, out, _err, calls = _cli(["skills", "bundles", "show", "My Morning"],
                                  {"GET /api/skills/bundles/My%20Morning": {"bundle": _ROW}})
    assert code == 0 and out.splitlines() == ["morning  Morning", "  am", "  file: /data/skill-bundles/morning.yaml",
                                              "  skills (3):", "    - Weather Intel", "    - News",
                                              "    - Gone (not installed)"]

    _hub_delete = {"ok": True, "deleted": _ROW}
    from agents.cli import nerva

    class _Client:
        base_url = "http://127.0.0.1:8080"

        def __init__(self):
            self.calls = []

        def request(self, method, path, body=None):
            self.calls.append((method, path))
            return _hub_delete

    import io

    hub = _Client()
    out_buf = io.StringIO()
    ctx = nerva.Context(environ={}, out=out_buf, err=io.StringIO(), inp=io.StringIO(""),
                        client_factory=lambda env: hub)
    assert nerva.main(["skills", "bundles", "delete", "morning"], context=ctx) == 0
    assert hub.calls == [("DELETE", "/api/skills/bundles/morning")]
    assert out_buf.getvalue().strip() == ("deleted bundle Morning: /data/skill-bundles/morning.yaml; "
                                          "its skills and their switches are untouched")

    report = {"ok": True, "added": [{"name": "Focus", "slug": "focus", "description": "quiet"}],
              "removed": [{"name": "Old", "slug": "old"}], "changed": ["morning"], "total": 2, "problems": []}
    code, out, _err, calls = _cli(["skills", "bundles", "reload"], {"POST /api/skills/bundles/reload": report})
    assert code == 0 and calls == [("POST", "/api/skills/bundles/reload", {})]
    assert out.splitlines() == ["added (1):", "  + Focus — quiet", "removed (1):", "  - Old",
                                "changed (1): morning", "total bundles now: 2"]
    code, out, _err, _calls = _cli(["skills", "bundles", "reload"],
                                   {"POST /api/skills/bundles/reload": {"added": [], "removed": [], "changed": [],
                                                                        "total": 1, "problems": []}})
    assert out.strip() == "no changes; 1 bundle(s) loaded"


def test_nerva_skills_bundles_create_needs_a_skill():
    code, _out, err, calls = _cli(["skills", "bundles", "create", "Morning"], {})
    assert code == 2 and "at least one skill" in err and calls == []


def test_nerva_skills_off_and_on_switch_a_bundle_as_one_unit():
    reply = {"ok": True, "changed": ["Weather Intel", "News"], "unchanged": [], "essential": ["Security Monitor"],
             "audited": True, "bundle": "morning", "missing": ["Gone"]}
    code, out, _err, calls = _cli(["skills", "off", "--bundle", "morning", "--channel", "telegram"],
                                  {"POST /api/skills/switch": reply})
    assert code == 0 and calls == [("POST", "/api/skills/switch",
                                    {"enabled": False, "bundle": "morning", "channel": "telegram"})]
    assert out.splitlines() == ["switched off on telegram: Weather Intel, News",
                                "Security Monitor: essential, stays on",
                                "Gone: in the bundle but not installed, skipped"]
    pending = {"ok": True, "status": "pending", "task_id": 7, "pending": ["Weather Intel", "News"],
               "bundle": "morning", "missing": ["Gone"]}
    code, out, _err, calls = _cli(["skills", "on", "--bundle", "morning"], {"POST /api/skills/switch": pending})
    assert calls[0][2] == {"enabled": True, "bundle": "morning"}
    assert out.splitlines() == ["pending owner approval: task 7 · Weather Intel, News",
                                "Gone: in the bundle but not installed, skipped"]
    code, _out, err, calls = _cli(["skills", "on", "spotify", "--bundle", "morning"], {})
    assert code == 2 and "--bundle" in err and calls == []


# ── the real worker ──────────────────────────────────────────────────────────────

async def test_a_bundle_switch_on_runs_only_after_a_human_accepts_it_on_the_worker(tmp_path, monkeypatch):
    """The bundle's approval is the coordinator's registered ``permission.grant`` task:
    blocked until a human accepts it, applied by a worker tick, never replayed."""
    from types import SimpleNamespace

    from agents.core import permission_ledger
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.autonomy.queue import TaskQueue
    from agents.core.autonomy.worker import AutonomyWorker
    from agents.core.security.capability import KillSwitch
    from agents.core.skills import signing, switch_approval
    from tests.test_web_tools_wiring import _coordinator

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_TASK_MEDIATION", "off")
    real_ledger = permission_ledger.PermissionLedger
    monkeypatch.setattr(permission_ledger, "PermissionLedger",
                        lambda **kwargs: real_ledger(tmp_path / "permissions.db", enabled=True, **kwargs))
    weather, news = _skill(tmp_path, "weather", "Weather Intel"), _skill(tmp_path, "news", "News")
    for skill in (weather, news):
        skill.source_fingerprint = signing.source_snapshot(skill.path).fingerprint
    bundles.save("Morning", ["Weather Intel", "News"])
    queue = TaskQueue(str(tmp_path / "tasks.db"), mediation_mode="off").initialize()
    try:
        worker = AutonomyWorker(queue, policy=AutonomyPolicy(cap_per_action=50, daily_ceiling=200))
        coordinator = _coordinator({})
        orch = coordinator._orch
        orch.autonomy, orch.autonomy_queue = worker, queue
        orch.kill_switch = KillSwitch(tmp_path / "halt.json")
        orch.skills = SimpleNamespace(skills={weather.name: weather, news.name: news})
        orch.skill_usage = None
        executor = coordinator.build_executor()
        worker.executor = executor.execute

        switch_approval.disable([weather, news])
        targets, _missing = bundles.resolve(bundles.get("morning").skills, orch.skills.skills.values())
        request = switch_approval.request_enable(orch, targets, bundle="morning")
        task_id = request["task_id"]
        assert request["status"] == "pending" and queue.get(task_id).status == "blocked"
        await worker.tick(task_id=task_id)
        assert switches.state()["disabled"] == ["Weather Intel", "News"]       # not before a human accepts
        await worker.apply_decision(task_id, "accept", decided_by="alice")
        await worker.tick(task_id=task_id)
        done = queue.get(task_id)
        assert done.status == "done" and done.result["status"] == "ok"
        assert sorted(done.result["changed"]) == ["News", "Weather Intel"] and switches.state()["disabled"] == []
        switch_approval.disable([weather])
        replay = await executor.resolve("permission.grant")(done)
        assert replay["status"] == "refused" and switches.state()["disabled"] == ["Weather Intel"]
    finally:
        queue.close()


def test_the_cli_drives_the_real_routes_end_to_end(monkeypatch, tmp_path):
    """``nerva skills bundles`` and ``nerva skills off|on --bundle`` against the mounted
    app: the hub writes the file, and the switch goes through the same route."""
    import io

    from agents.cli.client import HubError
    from agents.cli.nerva import Context, main

    client, orch = _client(monkeypatch, tmp_path)
    _ready_approval(monkeypatch, tmp_path, orch)

    class _AppHub:
        base_url = "http://127.0.0.1:8080"

        def request(self, method, path, body=None):
            resp = client.request(method, path, json=body, headers={"X-Admin-Token": _TOKEN})
            if resp.status_code >= 400:
                raise HubError(resp.status_code, resp.json().get("error", ""))
            return resp.json()

        def get(self, path):
            return self.request("GET", path)

        def post(self, path, body=None):
            return self.request("POST", path, body if body is not None else {})

    def run(*argv):
        out, err = io.StringIO(), io.StringIO()
        ctx = Context(environ={}, out=out, err=err, inp=io.StringIO(""), client_factory=lambda env: _AppHub())
        return main(list(argv), context=ctx), out.getvalue(), err.getvalue()

    code, out, _err = run("skills", "bundles", "create", "Morning", "-s", "weather", "-s", "news")
    assert code == 0 and out.startswith("created bundle Morning (2 skills)")
    assert (_dir(tmp_path) / "morning.yaml").read_text(encoding="utf-8") == (
        "name: Morning\nskills:\n- Weather Intel\n- News\n")
    code, _out, err = run("skills", "bundles", "create", "Spare", "-s", "ghost")
    assert code == 1 and "not installed: ghost" in err and bundles.get("spare") is None
    code, out, _err = run("skills", "off", "--bundle", "morning")
    assert code == 0 and out.strip() == "switched off everywhere: Weather Intel, News"
    assert switches.state()["disabled"] == ["Weather Intel", "News"]
    code, out, _err = run("skills", "on", "--bundle", "morning")
    assert code == 0 and out.startswith("pending owner approval: task 1")
    assert switches.state()["disabled"] == ["Weather Intel", "News"]       # waits for the human
    code, out, _err = run("skills", "bundles", "delete", "morning")
    assert code == 0 and bundles.get("morning") is None
    assert switches.state()["disabled"] == ["Weather Intel", "News"]       # deleting switches nothing
