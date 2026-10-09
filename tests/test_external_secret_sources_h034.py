"""H034: synthetic checks at the external-manager and broker boundary."""

import argparse
import hashlib
import io
import os
import subprocess
import zipfile
from unittest.mock import patch

import pytest

from agents.cli import secrets as secrets_cli
from agents.core.secrets import SecretStore
from agents.core.security.secret_broker import SecretBroker
from agents.core.security.secret_sources import (
    ExternalSecretSources,
    OwnerSessions,
    bitwarden,
    install,
    onepassword,
)


def test_owner_approved_resolution_prefers_mapped_reference_and_redacts(tmp_path):
    store = SecretStore(tmp_path / "secrets.enc", key="test-key")
    bws, op = tmp_path / "bws", tmp_path / "op"
    bws.write_text("")
    op.write_text("")
    bws.chmod(0o700)
    op.chmod(0o700)
    sources = ExternalSecretSources(store, runner=lambda argv, **kw: subprocess.CompletedProcess(
        argv, 0, 'resolved-value\n' if argv[1] == 'read' else
        '[{"key":"API_KEY","value":"bulk-value"}]', ''))
    sources.configure("bitwarden", {"enabled": True, "project_id": "project", "binary_path": str(bws)})
    sources.configure("onepassword", {"enabled": True, "env": {"API_KEY": "op://vault/item/field"},
                                      "binary_path": str(op)})
    sources.set_token("bitwarden", "machine-token")
    sources.set_token("onepassword", "service-token")
    broker = SecretBroker(store, sources=sources)
    blocked = broker.inject("{{secret:API_KEY}}", approved=False)
    assert blocked["injected"] == []
    assert "resolved-value" not in blocked["text"]
    result = broker.inject("{{secret:API_KEY}}", approved=True)
    assert result["text"] == "resolved-value"
    assert broker.redact("got resolved-value") == "got [REDACTED:API_KEY]"
    assert b"machine-token" not in (tmp_path / "secrets.enc").read_bytes()
    assert b"resolved-value" not in (tmp_path / "secrets.enc").read_bytes()


def test_background_read_does_not_unlock_and_expired_session_fails_closed(tmp_path):
    store = SecretStore(tmp_path / "secrets.enc", key="test-key")
    calls = []
    sources = ExternalSecretSources(store, runner=lambda argv, **kw: calls.append(argv))
    sources.configure("onepassword", {"enabled": True, "env": {"K": "op://vault/item/field"},
                                      "binary_path": "/bin/op"})
    broker = SecretBroker(store, sources=sources)
    assert broker.inject("{{secret:K}}", approved=True)["blocked"] == ["K"]
    assert calls == []


def test_cli_maps_reference_without_leaking_token_or_value(tmp_path):
    store = SecretStore(tmp_path / "secrets.enc", key="test-key")
    parser = argparse.ArgumentParser()
    secrets_cli.register_parser(parser.add_subparsers(dest="verb"))
    class Context:
        out = io.StringIO()
        err = io.StringIO()
        inp = io.StringIO()
    ctx = Context()
    ns = parser.parse_args(["secrets", "onepassword", "set", "API_KEY", "op://vault/item/field"])
    assert secrets_cli.cmd_secrets(ns, ctx, store=store) == 0
    assert ExternalSecretSources(store).configuration("onepassword")["env"] == {
        "API_KEY": "op://vault/item/field"}
    assert "op://vault/item/field" not in ctx.out.getvalue()


def test_owner_session_cache_cannot_cross_owner_or_outlive_ttl(tmp_path):
    now = [0.0]
    op = tmp_path / "op"
    op.write_text("")
    op.chmod(0o700)
    seen = []
    def run(argv, **kw):
        seen.append(kw["env"])
        return subprocess.CompletedProcess(argv, 0, "owner-only\n", "")
    store = SecretStore(tmp_path / "secrets.enc", key="test-key")
    sessions = OwnerSessions(ttl_seconds=5, clock=lambda: now[0])
    sources = ExternalSecretSources(store, runner=run, sessions=sessions, clock=lambda: now[0])
    sources.configure("onepassword", {"enabled": True, "env": {"K": "op://v/i/f"},
                                      "binary_path": str(op), "cache_ttl_seconds": 60})
    sessions.put("alice", "onepassword", "session-token")
    assert sources.resolve("K", owner_id="alice") == "owner-only"
    assert seen[0]["OP_SESSION"] == "session-token"
    assert sources.resolve("K", owner_id="bob") is None
    assert sources.resolve("K", background=True) is None
    now[0] = 6
    assert sources.resolve("K", owner_id="alice") is None
    assert len(seen) == 1


def test_fresh_auth_rejection_drops_prior_cached_value(tmp_path):
    bws = tmp_path / "bws"
    bws.write_text("")
    bws.chmod(0o700)
    replies = [subprocess.CompletedProcess([], 0, '[{"key":"K","value":"old"}]', ''),
               subprocess.CompletedProcess([], 1, '', 'unauthorized')]
    def run(*args, **kwargs):
        return replies.pop(0) if len(replies) > 1 else replies[0]
    store = SecretStore(tmp_path / "secrets.enc", key="test-key")
    sources = ExternalSecretSources(store, runner=run)
    sources.configure("bitwarden", {"enabled": True, "project_id": "p", "binary_path": str(bws)})
    sources.set_token("bitwarden", "token")
    assert sources.resolve("K") == "old"
    assert sources.resolve("K", fresh=True) is None
    assert sources.resolve("K") is None
    assert "old" not in SecretBroker(store, sources=sources).redact("old")


def test_internal_bootstrap_token_is_not_a_broker_handle(tmp_path):
    store = SecretStore(tmp_path / "secrets.enc", key="test-key")
    sources = ExternalSecretSources(store)
    sources.set_token("bitwarden", "bootstrap-token")
    broker = SecretBroker(store, sources=sources)
    assert "h034.token.bitwarden" not in broker.names()
    assert broker.inject("{{secret:h034.token.bitwarden}}", approved=True)["blocked"] == [
        "h034.token.bitwarden"]
    assert "bootstrap-token" not in broker.redact("bootstrap-token")


def test_donor_bws_region_and_op_reference_transport_are_isolated(tmp_path):
    """Adapted from donor tests/agent/test_{bitwarden,onepassword}_secrets.py."""
    bws, op = tmp_path / "bws", tmp_path / "op"
    for binary in (bws, op):
        binary.write_text("")
        binary.chmod(0o700)
    calls = []
    def run(argv, **kw):
        calls.append((argv, kw))
        output = '[{"key":"K","value":"bulk"},{"key":"BAD NAME","value":"skip"}]' if argv[1] == "secret" else "mapped\n"
        return subprocess.CompletedProcess(argv, 0, output, "")
    old = os.environ.get("BWS_ACCESS_TOKEN")
    bw = bitwarden.fetch({"project_id": "project", "binary_path": str(bws),
                          "server_url": "https://vault.bitwarden.eu"}, "test-token", run)
    assert bw.secrets == {"K": "bulk"}
    assert calls[0][0] == [str(bws), "secret", "list", "project", "--output", "json"]
    assert calls[0][1]["env"]["BWS_SERVER_URL"] == "https://vault.bitwarden.eu"
    assert calls[0][1]["env"]["BWS_ACCESS_TOKEN"] == "test-token"
    assert calls[0][1]["stdin"] == subprocess.DEVNULL
    assert os.environ.get("BWS_ACCESS_TOKEN") == old
    result = onepassword.fetch({"env": {"K": "op://Private/OpenAI/api key"},
                                "binary_path": str(op)}, "service-token", run)
    assert result.secrets == {"K": "mapped"}
    assert calls[1][0] == [str(op), "read", "--", "op://Private/OpenAI/api key"]
    assert calls[1][1]["env"]["OP_SERVICE_ACCOUNT_TOKEN"] == "service-token"
    assert "BWS_ACCESS_TOKEN" not in calls[1][1]["env"]


def test_cli_setup_token_status_sync_disable_and_remove_are_local(tmp_path):
    store = SecretStore(tmp_path / "secrets.enc", key="test-key")
    op = tmp_path / "op"
    op.write_text("")
    op.chmod(0o700)
    calls = []
    sources = ExternalSecretSources(store, runner=lambda argv, **kw: (
        calls.append((argv, kw)) or subprocess.CompletedProcess(argv, 0, "value\n", "")))
    parser = argparse.ArgumentParser()
    secrets_cli.register_parser(parser.add_subparsers(dest="verb"))
    class Context:
        out = io.StringIO()
        err = io.StringIO()
        inp = io.StringIO("private-token\n")
    ctx = Context()
    def invoke(*args):
        return secrets_cli.cmd_secrets(parser.parse_args(["secrets", "onepassword", *args]),
                                       ctx, sources=sources)
    assert invoke("setup", "--binary-path", str(op), "--account", "work") == 0
    assert invoke("set", "API_KEY", "op://vault/item/field") == 0
    assert invoke("token", "--token-stdin", "--no-verify") == 0
    assert invoke("status") == 0
    assert invoke("sync") == 0
    assert "API_KEY" in ctx.out.getvalue()
    assert "private-token" not in ctx.out.getvalue() + ctx.err.getvalue()
    assert b"private-token" not in (tmp_path / "secrets.enc").read_bytes()
    assert calls[0][1]["env"]["OP_SERVICE_ACCOUNT_TOKEN"] == "private-token"
    assert invoke("remove", "API_KEY") == 0
    assert invoke("disable") == 0
    assert not sources.configuration("onepassword")["enabled"]


def test_setup_refuses_missing_helper_and_malformed_self_hosted_region(tmp_path):
    store = SecretStore(tmp_path / "secrets.enc", key="test-key")
    parser = argparse.ArgumentParser()
    secrets_cli.register_parser(parser.add_subparsers(dest="verb"))
    class Context:
        out = io.StringIO()
        err = io.StringIO()
        inp = io.StringIO()
    ctx = Context()
    command = ["secrets", "bitwarden", "setup", "--project-id", "p", "--binary-path",
               str(tmp_path / "missing-bws")]
    assert secrets_cli.cmd_secrets(parser.parse_args(command), ctx, store=store) == 1
    assert ExternalSecretSources(store).configuration("bitwarden") == {}
    binary = tmp_path / "bws"
    binary.write_text("")
    binary.chmod(0o700)
    command = ["secrets", "bitwarden", "setup", "--project-id", "p", "--binary-path", str(binary),
               "--region", "self-hosted", "--server-url", "https://vault.example/?token=bad"]
    assert secrets_cli.cmd_secrets(parser.parse_args(command), ctx, store=store) == 1
    assert ExternalSecretSources(store).configuration("bitwarden") == {}


def test_mapped_1password_auth_failure_never_falls_back_to_bulk(tmp_path):
    store = SecretStore(tmp_path / "secrets.enc", key="test-key")
    bws, op = tmp_path / "bws", tmp_path / "op"
    for binary in (bws, op):
        binary.write_text("")
        binary.chmod(0o700)
    calls = []
    def run(argv, **kw):
        calls.append(argv)
        if argv[1] == "read":
            return subprocess.CompletedProcess(argv, 1, "", "not signed in")
        return subprocess.CompletedProcess(argv, 0, '[{"key":"K","value":"bulk"}]', "")
    sources = ExternalSecretSources(store, runner=run)
    sources.configure("onepassword", {"enabled": True, "env": {"K": "op://v/i/f"},
                                      "binary_path": str(op)})
    sources.configure("bitwarden", {"enabled": True, "project_id": "p", "binary_path": str(bws)})
    sources.set_token("onepassword", "bad-token")
    sources.set_token("bitwarden", "good-token")
    assert sources.resolve("K") is None
    assert len(calls) == 1 and calls[0][1] == "read"


def test_owner_session_does_not_survive_new_registry_instance(tmp_path):
    store = SecretStore(tmp_path / "secrets.enc", key="test-key")
    op = tmp_path / "op"
    op.write_text("")
    op.chmod(0o700)
    calls = []
    def run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "live\n", "")
    first = ExternalSecretSources(store, runner=run)
    first.configure("onepassword", {"enabled": True, "env": {"K": "op://v/i/f"},
                                     "binary_path": str(op)})
    first.sessions.put("alice", "onepassword", "ephemeral")
    assert first.resolve("K", owner_id="alice") == "live"
    restarted = ExternalSecretSources(store, runner=run)
    assert restarted.resolve("K", owner_id="alice") is None
    assert len(calls) == 1
    assert b"ephemeral" not in (tmp_path / "secrets.enc").read_bytes()


def test_explicit_installer_rejects_checksum_without_replacing_binary(tmp_path):
    dest = tmp_path / "bws"
    dest.write_bytes(b"existing")
    target = (install.sys.platform, install.platform.machine().lower())
    if target not in install._PINNED:
        return
    with patch.object(install.urllib.request, "urlopen", return_value=io.BytesIO(b"not the pinned release")):
        try:
            install.install_bws(destination=dest)
        except RuntimeError as exc:
            assert "checksum" in str(exc)
        else:
            assert False, "a checksum mismatch must fail closed"
    assert dest.read_bytes() == b"existing"


def test_explicit_installer_accepts_pinned_archive_and_replaces_atomically(tmp_path):
    dest = tmp_path / "bws"
    dest.write_bytes(b"previous")
    target = (install.sys.platform, install.platform.machine().lower())
    if target not in install._PINNED:
        return
    fixture = io.BytesIO()
    with zipfile.ZipFile(fixture, "w") as zipped:
        zipped.writestr("release/bws", b"new-binary")
    archive = fixture.getvalue()
    filename = install._PINNED[target][0]
    with (patch.dict(install._PINNED, {target: (filename, hashlib.sha256(archive).hexdigest())}),
          patch.object(install.urllib.request, "urlopen", return_value=io.BytesIO(archive))):
        assert install.install_bws(destination=dest) == dest
    assert dest.read_bytes() == b"new-binary"
    assert dest.stat().st_mode & 0o077 == 0
    assert list(tmp_path.glob("bws-install-*")) == []


def test_running_broker_sees_external_disable_rotation_and_reference_change(tmp_path):
    path = tmp_path / "secrets.enc"
    store = SecretStore(path, key="test-key")
    other = SecretStore(path, key="test-key")
    op = tmp_path / "op"
    op.write_text("")
    op.chmod(0o700)
    seen = []
    def run(argv, **kw):
        seen.append((argv, kw["env"]["OP_SERVICE_ACCOUNT_TOKEN"]))
        return subprocess.CompletedProcess(argv, 0, f"value-{len(seen)}\n", "")
    sources = ExternalSecretSources(store, runner=run)
    sources.configure("onepassword", {"enabled": True, "env": {"K": "op://v/i/old"},
                                      "binary_path": str(op), "cache_ttl_seconds": 300})
    sources.set_token("onepassword", "token-1")
    broker = SecretBroker(store, sources=sources)
    assert broker.inject("{{secret:K}}", approved=True)["text"] == "value-1"
    external = ExternalSecretSources(other)
    external.set_token("onepassword", "token-2")
    assert broker.inject("{{secret:K}}", approved=True)["text"] == "value-2"
    assert seen[-1][1] == "token-2"
    external.configure("onepassword", {"enabled": True, "env": {"K": "op://v/i/new"},
                                         "binary_path": str(op), "cache_ttl_seconds": 300})
    assert broker.inject("{{secret:K}}", approved=True)["text"] == "value-3"
    assert seen[-1][0][-1] == "op://v/i/new"
    external.configure("onepassword", {"enabled": False,
        "env": {"K": "op://v/i/new"}, "binary_path": str(op)})
    assert broker.inject("{{secret:K}}", approved=True)["blocked"] == ["K"]
    assert "value-1" not in broker.redact("value-1")
    assert "value-2" not in broker.redact("value-2")


def test_expired_value_still_redacts_but_no_longer_resolves(tmp_path):
    now = [0.0]
    store = SecretStore(tmp_path / "secrets.enc", key="test-key")
    op = tmp_path / "op"
    op.write_text("")
    op.chmod(0o700)
    sessions = OwnerSessions(ttl_seconds=1, clock=lambda: now[0])
    sources = ExternalSecretSources(store, sessions=sessions, clock=lambda: now[0],
        runner=lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "secret-value\n", ""))
    sources.configure("onepassword", {"enabled": True, "env": {"K": "op://v/i/f"},
                                      "binary_path": str(op), "cache_ttl_seconds": 1})
    sessions.put("owner", "onepassword", "session")
    broker = SecretBroker(store, sources=sources)
    assert broker.inject("{{secret:K}}", approved=True, owner_id="owner")["text"] == "secret-value"
    now[0] = 2
    assert broker.inject("{{secret:K}}", approved=True, owner_id="owner")["blocked"] == ["K"]
    assert "secret-value" not in broker.redact("secret-value")


def test_cli_install_and_sync_helper_failures_are_controlled(tmp_path):
    store = SecretStore(tmp_path / "secrets.enc", key="test-key")
    bws = tmp_path / "bws"
    bws.write_text("")
    bws.chmod(0o700)
    sources = ExternalSecretSources(store, runner=lambda *a, **kw: (_ for _ in ()).throw(
        RuntimeError("provider stderr included secret-sensitive material")))
    parser = argparse.ArgumentParser()
    secrets_cli.register_parser(parser.add_subparsers(dest="verb"))
    class Context:
        out = io.StringIO()
        err = io.StringIO()
        inp = io.StringIO("token\n")
    ctx = Context()
    def invoke(*args):
        return secrets_cli.cmd_secrets(parser.parse_args(["secrets", "bitwarden", *args]),
                                       ctx, sources=sources)
    assert invoke("setup", "--project-id", "project", "--binary-path", str(bws)) == 0
    assert invoke("token", "--token-stdin", "--no-verify") == 0
    assert invoke("sync") == 1
    with patch.object(install, "install_bws", side_effect=RuntimeError("secret-sensitive")):
        assert invoke("install") == 1
    assert "secret-sensitive" not in ctx.out.getvalue() + ctx.err.getvalue()


def test_cli_token_verify_timeout_preserves_previous_encrypted_token(tmp_path):
    store = SecretStore(tmp_path / "secrets.enc", key="test-key")
    bws = tmp_path / "bws"
    bws.write_text("")
    bws.chmod(0o700)
    sources = ExternalSecretSources(store, runner=lambda *a, **kw: (_ for _ in ()).throw(
        subprocess.TimeoutExpired(cmd="bws", timeout=1)))
    sources.configure("bitwarden", {"enabled": True, "project_id": "p", "binary_path": str(bws)})
    sources.set_token("bitwarden", "old-token")
    parser = argparse.ArgumentParser()
    secrets_cli.register_parser(parser.add_subparsers(dest="verb"))
    class Context:
        out = io.StringIO()
        err = io.StringIO()
        inp = io.StringIO("new-token\n")
    ctx = Context()
    ns = parser.parse_args(["secrets", "bitwarden", "token", "--token-stdin"])
    assert secrets_cli.cmd_secrets(ns, ctx, sources=sources) == 1
    assert store.get("h034.token.bitwarden") == "old-token"


def test_provider_disabled_while_fetching_cannot_inject_its_result(tmp_path):
    path = tmp_path / "secrets.enc"
    store = SecretStore(path, key="test-key")
    external = ExternalSecretSources(SecretStore(path, key="test-key"))
    binary = tmp_path / "bws"
    binary.write_text("")
    binary.chmod(0o700)

    def run(argv, **_kwargs):
        external.configure("bitwarden", {"enabled": False})
        return subprocess.CompletedProcess(argv, 0, '[{"key":"K","value":"stale-value"}]', "")

    sources = ExternalSecretSources(store, runner=run)
    sources.configure("bitwarden", {"enabled": True, "project_id": "p", "binary_path": str(binary)})
    sources.set_token("bitwarden", "token")
    broker = SecretBroker(store, sources=sources)
    assert broker.inject("{{secret:K}}", approved=True)["blocked"] == ["K"]
    assert "stale-value" not in broker.redact("stale-value")


def test_owner_session_expiring_during_fetch_refuses_injection(tmp_path):
    now = [0.0]
    store = SecretStore(tmp_path / "secrets.enc", key="test-key")
    binary = tmp_path / "op"
    binary.write_text("")
    binary.chmod(0o700)
    sessions = OwnerSessions(ttl_seconds=1, clock=lambda: now[0])

    def run(argv, **_kwargs):
        now[0] = 2
        return subprocess.CompletedProcess(argv, 0, "expired-session-value\n", "")

    sources = ExternalSecretSources(store, runner=run, sessions=sessions, clock=lambda: now[0])
    sources.configure("onepassword", {"enabled": True, "env": {"K": "op://v/i/f"}, "binary_path": str(binary)})
    sessions.put("owner", "onepassword", "session")
    broker = SecretBroker(store, sources=sources)
    assert broker.inject("{{secret:K}}", approved=True, owner_id="owner")["blocked"] == ["K"]
    assert "expired-session-value" not in broker.redact("expired-session-value")


@pytest.mark.parametrize("server_url", ["", "https://vault.bitwarden.eu", "https://owner-vault.example"])
def test_cli_token_verification_uses_the_configured_region(tmp_path, server_url):
    store = SecretStore(tmp_path / "secrets.enc", key="test-key")
    binary = tmp_path / "bws"
    binary.write_text("")
    binary.chmod(0o700)
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0 if kwargs["env"].get("BWS_SERVER_URL", "") == server_url else 1,
                                           "[]", "")

    sources = ExternalSecretSources(store, runner=run)
    sources.configure("bitwarden", {"enabled": True, "project_id": "p", "binary_path": str(binary),
                                    "server_url": server_url})
    parser = argparse.ArgumentParser()
    secrets_cli.register_parser(parser.add_subparsers(dest="verb"))
    ctx = type("Context", (), {"out": io.StringIO(), "err": io.StringIO(), "inp": io.StringIO("candidate-token\n")})()
    ns = parser.parse_args(["secrets", "bitwarden", "token", "--token-stdin"])
    assert secrets_cli.cmd_secrets(ns, ctx, sources=sources) == 0
    assert store.get("h034.token.bitwarden") == "candidate-token"
    assert calls[0][1]["env"].get("BWS_SERVER_URL", "") == server_url


def test_op_read_cannot_trigger_desktop_unlock_or_disk_cache(tmp_path):
    binary = tmp_path / "op"
    binary.write_text("")
    binary.chmod(0o700)
    calls = []

    def run(argv, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(argv, 0, "synthetic-value\n", "")

    assert onepassword.fetch({"env": {"K": "op://v/i/f"}, "binary_path": str(binary)}, "token", run).secrets == {
        "K": "synthetic-value"}
    assert calls[0]["env"]["OP_BIOMETRIC_UNLOCK_ENABLED"] == "false"
    assert calls[0]["env"]["OP_CACHE"] == "false"
