"""Remote skill pins and per-call authority fail before network or owner writes."""
from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from agents.core.skills.importer import SkillImporter
from agents.core.skills.remote_pin import (
    RemoteImportAuthorization,
    RemoteImportRefused,
    RemoteSkillPin,
)

_COMMIT = "a" * 40
_BODY = b"---\nname: sample\ndescription: Sample skill.\n---\n# Sample\n"


def _pin(**overrides):
    fields = {
        "repo": "example/tools", "commit": _COMMIT,
        "entry_path": "skills/sample/SKILL.md",
        "content_sha256": hashlib.sha256(_BODY).hexdigest(),
    }
    fields.update(overrides)
    return RemoteSkillPin.from_dict(fields)


def _real_importer(tmp_path, response_for):
    requests = []

    def transport_factory(_target):
        def respond(request):
            requests.append(request)
            assert request.headers["host"] == "raw.githubusercontent.com"
            return response_for(request)

        return httpx.MockTransport(respond)

    importer = SkillImporter(
        str(tmp_path / "skills"),
        resolver=lambda host, *, mode: (["93.184.216.34"], None),
        transport_factory=transport_factory,
    )
    return importer, requests


def test_remote_pin_rejects_mutable_or_unsafe_sources():
    for fields in (
        {"commit": "main"}, {"repo": "example/../tools"},
        {"entry_path": "skills/../sample/SKILL.md"},
        {"entry_path": "skills/sample/SKILL.md?raw=1"},
        {"content_sha256": "0" * 63},
        {"references": [{"path": "skills/other/references/a.md",
                         "content_sha256": "0" * 64}]},
    ):
        with pytest.raises(RemoteImportRefused) as caught:
            _pin(**fields)
        assert caught.value.code == "invalid_pin"


@pytest.mark.asyncio
async def test_generic_import_requires_pin_and_request_authority_before_fetch(tmp_path):
    importer = SkillImporter(str(tmp_path / "skills"))
    with pytest.raises(RemoteImportRefused) as caught:
        await importer.import_from_github("example/tools", "sample")
    assert caught.value.code == "missing_pin"
    with pytest.raises(RemoteImportRefused) as caught:
        await importer.import_from_github("example/tools", "sample", pin=_pin())
    assert caught.value.code == "authorization_unavailable"
    auth = RemoteImportAuthorization(lambda _payload: "grant", lambda *_: None)
    with pytest.raises(RemoteImportRefused) as caught:
        await importer.import_from_github("other/tools", "sample", pin=_pin(), authorization=auth)
    assert caught.value.code == "invalid_pin"
    assert list(importer.skills_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_hermes_import_requires_context_before_pin_or_network(tmp_path, monkeypatch):
    from agents.core.skills import importer as importer_module

    monkeypatch.setattr(importer_module, "_load_hermes_pin",
                        lambda: pytest.fail("pin read reached"))
    importer = SkillImporter(str(tmp_path / "skills"))
    with pytest.raises(RemoteImportRefused) as caught:
        await importer.import_from_hermes("sample")
    assert caught.value.code == "authorization_unavailable"
    assert list(importer.skills_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_install_denial_precedes_generic_network_and_write(tmp_path):
    importer = SkillImporter(str(tmp_path / "skills"))
    seen = []

    def deny_install(payload):
        seen.append(payload)
        return "deny"

    auth = RemoteImportAuthorization(
        install_gate=deny_install,
        egress_gate=lambda *_: pytest.fail("network gate reached"),
    )
    with pytest.raises(RemoteImportRefused) as caught:
        await importer.import_from_github("example/tools", "sample", pin=_pin(), authorization=auth)
    assert caught.value.code == "install_denied"
    assert seen[0]["source_commit"] == _COMMIT
    assert seen[0]["content_sha256"] == hashlib.sha256(_BODY).hexdigest()
    assert list(importer.skills_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_real_shared_transport_pins_bytes_and_keeps_owner_review(tmp_path):
    importer, requests = _real_importer(tmp_path, lambda _request: httpx.Response(200, content=_BODY))
    decisions = []

    def install(payload):
        decisions.append(payload)
        return "grant"

    egress = []
    auth = RemoteImportAuthorization(
        install_gate=install,
        egress_gate=lambda *args: egress.append(args) or None,
    )
    assert await importer.import_from_github(
        "example/tools", "sample", pin=_pin(), authorization=auth) is True
    assert len(decisions) == 2
    assert decisions[0] == decisions[1]
    assert decisions[0]["kind"] == "skill.install"
    assert requests[0].url.path == f"/example/tools/{_COMMIT}/skills/sample/SKILL.md"
    assert egress == [("skill-import", "GET",
                       f"https://raw.githubusercontent.com/example/tools/{_COMMIT}/skills/sample/SKILL.md",
                       "raw.githubusercontent.com")]
    target = importer.skills_dir / "sample"
    assert (target / "SKILL.md").read_bytes() == _BODY
    assert (target / "PENDING_REVIEW").is_file()
    assert json.loads((target / "manifest.json").read_text(encoding="utf-8"))["source_commit"] == _COMMIT


@pytest.mark.asyncio
async def test_live_egress_denial_or_exception_has_no_fetch_or_write(tmp_path):
    for decision in ("deny", False, RuntimeError("kernel missing")):
        importer, requests = _real_importer(
            tmp_path / str(decision), lambda _request: pytest.fail("HTTP fetch reached"))

        def egress(*_args, result=decision):
            if isinstance(result, Exception):
                raise result
            return result

        auth = RemoteImportAuthorization(lambda _payload: "grant", egress)
        with pytest.raises(RemoteImportRefused) as caught:
            await importer.import_from_github(
                "example/tools", "sample", pin=_pin(), authorization=auth)
        assert caught.value.code == "egress_denied"
        assert requests == []
        assert list(importer.skills_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_shared_ssrf_refuses_private_resolution_before_http(tmp_path):
    importer, requests = _real_importer(
        tmp_path, lambda _request: pytest.fail("HTTP fetch reached"))
    importer._remote_resolver = lambda _host, *, mode: (["169.254.169.254"], None)
    auth = RemoteImportAuthorization(lambda _payload: "grant", lambda *_: None)
    with pytest.raises(RemoteImportRefused) as caught:
        await importer.import_from_github("example/tools", "sample", pin=_pin(), authorization=auth)
    assert caught.value.code == "egress_denied"
    assert requests == []
    assert list(importer.skills_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_redirect_is_refused_without_following_metadata_location(tmp_path):
    importer, requests = _real_importer(
        tmp_path, lambda _request: httpx.Response(
            302, headers={"Location": "http://169.254.169.254/latest/meta-data"}))
    auth = RemoteImportAuthorization(lambda _payload: "grant", lambda *_: None)
    with pytest.raises(RemoteImportRefused) as caught:
        await importer.import_from_github("example/tools", "sample", pin=_pin(), authorization=auth)
    assert caught.value.code == "source_identity_mismatch"
    assert len(requests) == 1
    assert requests[0].headers["host"] == "raw.githubusercontent.com"
    assert list(importer.skills_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_prestage_recheck_refuses_after_verified_fetch(tmp_path):
    importer, requests = _real_importer(tmp_path, lambda _request: httpx.Response(200, content=_BODY))
    decisions = iter(("queue", "deny"))
    auth = RemoteImportAuthorization(lambda _payload: next(decisions), lambda *_: None)
    with pytest.raises(RemoteImportRefused) as caught:
        await importer.import_from_github("example/tools", "sample", pin=_pin(), authorization=auth)
    assert caught.value.code == "install_denied"
    assert len(requests) == 1
    assert list(importer.skills_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_missing_kernel_after_fetch_returns_authorization_unavailable(tmp_path):
    importer, requests = _real_importer(tmp_path, lambda _request: httpx.Response(200, content=_BODY))
    decisions = iter(("grant", "error"))
    auth = RemoteImportAuthorization(lambda _payload: next(decisions), lambda *_: None)
    with pytest.raises(RemoteImportRefused) as caught:
        await importer.import_from_github("example/tools", "sample", pin=_pin(), authorization=auth)
    assert caught.value.code == "authorization_unavailable"
    assert len(requests) == 1
    assert list(importer.skills_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_reference_digest_failure_writes_no_partial_skill(tmp_path):
    reference = b"# Guide\n"
    ref_path = "skills/sample/references/guide.md"
    pin = _pin(references=[{"path": ref_path, "content_sha256": "0" * 64}])

    def respond(request):
        body = reference if request.url.path.endswith("guide.md") else _BODY
        return httpx.Response(200, content=body)

    importer, requests = _real_importer(tmp_path, respond)
    auth = RemoteImportAuthorization(lambda _payload: "grant", lambda *_: None)
    with pytest.raises(RemoteImportRefused) as caught:
        await importer.import_from_github("example/tools", "sample", pin=pin, authorization=auth)
    assert caught.value.code == "digest_mismatch"
    assert len(requests) == 2
    assert list(importer.skills_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_verified_generic_reference_is_staged_with_exact_provenance(tmp_path):
    reference = b"# Owner guide\n"
    ref_path = "skills/sample/references/guide.md"
    pin = _pin(references=[{"path": ref_path,
                            "content_sha256": hashlib.sha256(reference).hexdigest()}])

    def respond(request):
        return httpx.Response(
            200, content=reference if request.url.path.endswith("guide.md") else _BODY)

    importer, requests = _real_importer(tmp_path, respond)
    auth = RemoteImportAuthorization(lambda _payload: "grant", lambda *_: None)
    assert await importer.import_from_github(
        "example/tools", "sample", pin=pin, authorization=auth) is True
    target = importer.skills_dir / "sample"
    assert (target / "references/guide.md").read_bytes() == reference
    sidecar = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert sidecar["source_files"] == [{"path": ref_path,
                                        "content_sha256": hashlib.sha256(reference).hexdigest()}]
    assert (target / "PENDING_REVIEW").is_file()
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_explicit_pinned_legacy_manifest_stages_synthesized_skill(tmp_path):
    manifest = b'{"name":"sample","description":"Pinned legacy skill.","prompt":"Hello."}'
    pin = _pin(entry_path="skills/sample/manifest.json",
               content_sha256=hashlib.sha256(manifest).hexdigest())
    importer, requests = _real_importer(
        tmp_path, lambda _request: httpx.Response(200, content=manifest))
    auth = RemoteImportAuthorization(lambda _payload: "queue", lambda *_: None)
    assert await importer.import_from_github("example/tools", "sample", pin=pin,
                                             authorization=auth) is True
    assert requests[0].url.path.endswith("/skills/sample/manifest.json")
    target = importer.skills_dir / "sample"
    assert b"Hello." in (target / "SKILL.md").read_bytes()
    assert (target / "PENDING_REVIEW").is_file()


@pytest.mark.asyncio
async def test_pinned_legacy_manifest_with_unusable_fields_refuses_without_write(tmp_path):
    manifest = b'{"name":"sample","description":123,"prompt":["not","text"]}'
    pin = _pin(entry_path="skills/sample/manifest.json",
               content_sha256=hashlib.sha256(manifest).hexdigest())
    importer, requests = _real_importer(
        tmp_path, lambda _request: httpx.Response(200, content=manifest))
    auth = RemoteImportAuthorization(lambda _payload: "grant", lambda *_: None)
    with pytest.raises(RemoteImportRefused) as caught:
        await importer.import_from_github("example/tools", "sample", pin=pin,
                                          authorization=auth)
    assert caught.value.code == "invalid_skill"
    assert len(requests) == 1
    assert list(importer.skills_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_generic_sync_without_explicit_pins_refuses_before_network(tmp_path):
    importer, requests = _real_importer(tmp_path, lambda _request: pytest.fail("HTTP fetch reached"))
    auth = RemoteImportAuthorization(lambda _payload: "grant", lambda *_: None)
    with pytest.raises(RemoteImportRefused) as caught:
        await importer.sync_source("example/tools", authorization=auth)
    assert caught.value.code == "missing_pin"
    assert requests == []


@pytest.mark.asyncio
async def test_generic_sync_uses_only_explicit_pins(tmp_path):
    importer, requests = _real_importer(tmp_path, lambda _request: httpx.Response(200, content=_BODY))
    auth = RemoteImportAuthorization(lambda _payload: "grant", lambda *_: None)
    assert await importer.sync_source("example/tools", pins=(_pin(),),
                                      authorization=auth) == ["sample"]
    assert len(requests) == 1
    assert requests[0].url.path.endswith(f"/{_COMMIT}/skills/sample/SKILL.md")
    assert (importer.skills_dir / "sample/PENDING_REVIEW").is_file()


@pytest.mark.asyncio
async def test_generic_pinned_import_does_not_replace_owner_copy(tmp_path):
    importer, requests = _real_importer(tmp_path, lambda _request: httpx.Response(200, content=_BODY))
    owner = importer.skills_dir / "sample"
    owner.mkdir()
    (owner / "SKILL.md").write_bytes(b"owner copy")
    original_inode = owner.stat().st_ino
    auth = RemoteImportAuthorization(lambda _payload: "grant", lambda *_: None)
    assert await importer.import_from_github(
        "example/tools", "sample", pin=_pin(), authorization=auth) is False
    assert len(requests) == 1
    assert owner.stat().st_ino == original_inode
    assert (owner / "SKILL.md").read_bytes() == b"owner copy"
    assert not list(importer.skills_dir.glob(".hermes-stage-*"))
