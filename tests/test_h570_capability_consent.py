"""H570 — the capability registry, the consent screen, and pip entry-point declarations.

What the owner can do: read every capability an extension asks for with its risk
sentence and what changed since they last agreed, before anything is recorded; and
check descriptors that installed Python distributions declare.

What an attacker cannot do: get consent recorded from a pipe without ``--yes``; smuggle
terminal text through the hub's diff; make Nerva import an installed distribution's
code by declaring an extension; ship a descriptor that is not in the distribution's
RECORD, or one behind a symlink.
"""

from __future__ import annotations

import io
import json
from importlib import metadata
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from agents import web
from agents.cli.nerva import Context, main
from agents.core.extensions.capabilities import (
    CAPABILITY_REGISTRY,
    EVENT_RISKS,
    consent_screen,
    registry_problems,
    render_screen,
)
from agents.core.extensions.consent import ExtensionConsentStore
from agents.core.extensions.distribution import descriptor_member, installed_declarations
from agents.core.extensions.doctor import doctor_installed
from agents.core.extensions.manifest import CAPABILITIES, ManifestError, parse_manifest
from agents.core.routers import plugins

BASE = {
    "manifest_version": 1, "api_version": 1, "id": "boats", "version": "1.0.0",
    "capabilities": ["tools"], "tools": ["summarize"], "commands": [], "events": [],
    "requires": {"extensions": {}, "python": {}},
}


def raw(**overrides):
    value = {**BASE, **overrides}
    value["capabilities"] = [name for name, declared in (
        ("tools", value["tools"]), ("commands", value["commands"]),
        ("events.observe", value["events"])) if declared]
    return value


# ── the registry ─────────────────────────────────────────────────────────────

def test_every_declarable_capability_has_a_risk_sentence_and_nothing_else_does():
    assert registry_problems() == []
    assert set(CAPABILITY_REGISTRY) == set(CAPABILITIES)
    for entry in CAPABILITY_REGISTRY.values():
        assert len(entry.risk) > 40 and entry.enforced_by


def test_the_screen_lists_each_declared_capability_with_its_risk_and_event_extras():
    manifest = parse_manifest(raw(commands=["boat_report"], events=["approval.smart.requested"]))
    screen = consent_screen(manifest, {"consent": "not_granted", "declared_digest": "a" * 64})
    assert [row["id"] for row in screen["capabilities"]] == ["commands", "events.observe", "tools"]
    assert all(row["risk"] == CAPABILITY_REGISTRY[row["id"]].risk for row in screen["capabilities"])
    assert screen["event_risks"] == [{"event": "approval.smart.requested",
                                      "risk": EVENT_RISKS["approval.smart.requested"]}]
    text = "\n".join(render_screen(screen))
    assert "boats.summarize" in text and "boat_report" in text and "masked" in text


def test_a_changed_screen_shows_the_diff():
    manifest = parse_manifest(raw(commands=["boat_report"]))
    screen = consent_screen(manifest, {"consent": "changed", "added_declarations": ["command:boat_report"],
                                       "removed_declarations": []})
    lines = render_screen(screen)
    assert "  + command:boat_report" in lines and any("different surface" in line for line in lines)


# ── the route: preview records nothing ───────────────────────────────────────

def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setattr(web, "USER_TOKEN", "extension-user")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "extension-admin")
    app = FastAPI()
    app.include_router(plugins.router)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app, client=("198.51.100.2", 1234)),
                             base_url="http://test")


HEADERS = {"X-User-Token": "extension-user", "X-Admin-Token": "extension-admin"}


@pytest.mark.asyncio
async def test_preview_returns_the_screen_and_records_nothing(tmp_path, monkeypatch):
    async with _app(tmp_path, monkeypatch) as client:
        assert (await client.post("/api/plugins/extensions/consent",
                                  json={"manifest": raw(), "preview": True})).status_code == 401
        reply = await client.post("/api/plugins/extensions/consent",
                                  json={"manifest": raw(), "preview": True}, headers=HEADERS)
        assert reply.status_code == 200
        body = reply.json()
        assert body["preview"] is True and body["consent"] == "not_granted"
        assert body["screen"]["capabilities"][0]["risk"] == CAPABILITY_REGISTRY["tools"].risk
        assert ExtensionConsentStore().granted_ids() == ()
        assert not (tmp_path / "extensions" / "consent.json").exists()
        granted = await client.post("/api/plugins/extensions/consent", json={"manifest": raw()}, headers=HEADERS)
        assert granted.json()["consent"] == "granted"
        widened = await client.post("/api/plugins/extensions/consent",
                                    json={"manifest": raw(commands=["boat_report"]), "preview": True},
                                    headers=HEADERS)
        assert widened.json()["consent"] == "changed"
        assert "command:boat_report" in widened.json()["screen"]["added_declarations"]
        # The preview of a widened surface did not widen the grant.
        assert ExtensionConsentStore().check(parse_manifest(raw(commands=["boat_report"]))).state == "changed"
        both = await client.post("/api/plugins/extensions/consent",
                                 json={"manifest": raw(), "preview": True, "revoke": True}, headers=HEADERS)
        assert both.status_code == 422 and both.json()["reason"] == "preview_with_revoke"


# ── the CLI screen ───────────────────────────────────────────────────────────

class _Tty(io.StringIO):
    def isatty(self):
        return True


def _cli(tmp_path, preview_reply, *args, inp=None):
    path = tmp_path / "boats.json"
    path.write_text(json.dumps(raw(commands=["boat_report"])), encoding="utf-8")
    posted = []

    def post(route, body):
        posted.append(body)
        if body.get("preview"):
            return preview_reply
        return {"ok": True, "revoked": False, "consent": "granted", "declared_digest": "a" * 64}

    out, err = io.StringIO(), io.StringIO()
    context = Context(environ={}, out=out, err=err, inp=inp or io.StringIO(),
                      client_factory=lambda _: SimpleNamespace(post=post))
    code = main(["extensions", "consent", str(path), *args], context=context)
    return code, out.getvalue(), err.getvalue(), posted


PREVIEW = {"ok": True, "preview": True, "consent": "changed", "declared_digest": "b" * 64,
           "granted_digest": "c" * 64, "added_declarations": ["command:boat_report"],
           "removed_declarations": []}


def test_a_pipe_never_agrees_without_yes(tmp_path):
    code, out, err, posted = _cli(tmp_path, PREVIEW)
    assert code == 1 and "confirmation_required" in err
    assert [body.get("preview") for body in posted] == [True]
    assert CAPABILITY_REGISTRY["commands"].risk in out and "+ command:boat_report" in out


def test_yes_shows_the_screen_then_records(tmp_path):
    code, out, _err, posted = _cli(tmp_path, PREVIEW, "--yes")
    assert code == 0 and [body.get("preview", False) for body in posted] == [True, False]
    assert "Consent recorded" in out and CAPABILITY_REGISTRY["tools"].risk in out


@pytest.mark.parametrize(("answer", "code", "posts"), [("y\n", 0, 2), ("no\n", 1, 1), ("", 1, 1)])
def test_an_interactive_owner_answers_the_question(tmp_path, answer, code, posts):
    result, out, _err, posted = _cli(tmp_path, PREVIEW, inp=_Tty(answer))
    assert result == code and len(posted) == posts and "Agree to exactly this?" in out


def test_preview_only_records_nothing(tmp_path):
    code, out, _err, posted = _cli(tmp_path, PREVIEW, "--preview")
    assert code == 0 and len(posted) == 1 and "What changed" in out


@pytest.mark.parametrize("reply", [
    {**PREVIEW, "added_declarations": ["command:boat\x1b[2Jreport"]},
    {**PREVIEW, "consent": "granted_forever"},
    {**PREVIEW, "declared_digest": "zz"},
    {"ok": True},
    ["not", "a", "dict"],
])
def test_a_malformed_or_hostile_preview_is_refused_and_nothing_printed_from_it(tmp_path, reply):
    code, out, err, posted = _cli(tmp_path, reply, "--yes")
    assert code == 1 and len(posted) == 1
    assert "\x1b" not in out + err


def test_revoke_needs_no_screen(tmp_path):
    code, _out, _err, posted = _cli(tmp_path, PREVIEW, "--revoke")
    assert code == 0 and posted == [{"manifest": posted[0]["manifest"], "revoke": True}]


# ── pip entry-point declarations, never imported ─────────────────────────────

def _site(tmp_path, *, entry="boats = nerva_boats:extension", record=True, descriptor=None, symlink=False):
    site = tmp_path / "site"
    package = site / "nerva_boats"
    info = site / "nerva_boats-1.0.0.dist-info"
    package.mkdir(parents=True)
    info.mkdir()
    sentinel = tmp_path / "imported"
    (package / "__init__.py").write_text(f"open({str(sentinel)!r}, 'w').write('x')\nraise SystemExit(9)\n")
    target = package / "extension.json"
    content = json.dumps(descriptor or raw())
    if symlink:
        real = tmp_path / "elsewhere.json"
        real.write_text(content)
        target.symlink_to(real)
    else:
        target.write_text(content)
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: nerva-boats\nVersion: 1.0.0\n")
    (info / "entry_points.txt").write_text(f"[nerva.extensions]\n{entry}\n")
    rows = ["nerva_boats/__init__.py,,", "nerva_boats-1.0.0.dist-info/METADATA,,"]
    if record:
        rows.append("nerva_boats/extension.json,,")
    (info / "RECORD").write_text("\n".join(rows) + "\n")
    return list(metadata.distributions(path=[str(site)])), sentinel


def test_an_installed_declaration_is_read_and_its_code_is_never_imported(tmp_path):
    dists, sentinel = _site(tmp_path)
    found = installed_declarations(distributions=dists)
    assert found["errors"] == []
    [row] = found["extensions"]
    assert row["manifest"].id == "boats" and row["distribution"] == "nerva-boats"
    report = doctor_installed(distributions=dists)
    assert report["ok"] is True and report["extensions"][0]["source"] == "installed_distribution"
    assert report["extensions"][0]["execution_available"] is False
    assert not sentinel.exists()


@pytest.mark.parametrize(("kwargs", "reason"), [
    ({"record": False}, "descriptor_not_recorded"),
    ({"symlink": True}, "manifest_unreadable"),
    ({"entry": "other = nerva_boats:extension"}, "entry_point_id_mismatch"),
    ({"entry": "boats = ../../etc:passwd"}, "invalid_entry_point"),
    ({"entry": "boats = nerva_boats"}, "invalid_entry_point"),
    ({"descriptor": {**BASE, "tools": ["Bad"]}}, "invalid_declarations"),
])
def test_a_bad_installed_declaration_is_named_and_skipped(tmp_path, kwargs, reason):
    dists, sentinel = _site(tmp_path, **kwargs)
    found = installed_declarations(distributions=dists)
    assert found["extensions"] == [] and found["errors"][0]["reason"] == reason
    assert doctor_installed(distributions=dists)["ok"] is False
    assert not sentinel.exists()


def test_descriptor_member_maps_module_and_stem():
    assert str(descriptor_member("pkg.sub:ext")) == "pkg/sub/ext.json"
    with pytest.raises(ManifestError):
        descriptor_member("pkg:a/b")


def test_cli_doctor_needs_paths_or_installed_but_not_both(tmp_path, monkeypatch):
    err = io.StringIO()
    context = Context(environ={}, out=io.StringIO(), err=err)
    assert main(["extensions", "doctor"], context=context) == 1
    assert main(["extensions", "doctor", "x.json", "--installed"], context=context) == 1
    calls = []
    monkeypatch.setattr("agents.core.extensions.doctor.doctor_installed",
                        lambda: calls.append(1) or {"ok": True, "mode": "inspection_only",
                                                     "extensions": [], "errors": [], "order": []})
    assert main(["extensions", "doctor", "--installed", "--json"], context=context) == 0 and calls == [1]
