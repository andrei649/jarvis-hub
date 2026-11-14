"""Registered device/room/browser options use the central alias readers."""
from types import SimpleNamespace

import pytest

from agents.core import env_config


@pytest.fixture(autouse=True)
def clean_device_environment(monkeypatch):
    monkeypatch.setattr(env_config, "_PINNED", {})
    for suffix in ("DEVICE_ID", "DEVICE_LABEL", "E2E_SYNC", "E2E_SYNC_KEY", "E2E_SYNC_DIR",
                   "HOST_ID", "ROOM_FENCING_SECRET", "BROWSER_BROKER_ALLOW_LOOPBACK_HTTP"):
        for prefix in ("JARVIS", "NERVA"):
            monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)


@pytest.mark.parametrize("prefix", ["JARVIS", "NERVA"])
def test_device_sync_reads_environment_aliases(tmp_path, monkeypatch, prefix):
    from cryptography.fernet import Fernet

    from agents.core import env_alias, env_provenance
    from agents.core.e2e_sync import DirectorySyncTransport, E2ESync

    # Missing interpolation must not silently turn a spool into /spool.
    spool_name = f"{prefix}_E2E_SYNC_DIR"
    values = env_provenance.layer_values(((spool_name, "${MISSING_SYNC_ROOT}/spool"),), {})
    verdict = env_provenance.judge(values, env_alias.fold(values.values))
    assert verdict.refused == {spool_name: env_provenance.PATH_UNSET}

    key = Fernet.generate_key()
    monkeypatch.setenv(f"{prefix}_E2E_SYNC", "1")
    monkeypatch.setenv(f"{prefix}_DEVICE_ID", "alias-device")
    monkeypatch.setenv(f"{prefix}_DEVICE_LABEL", "  Travel laptop  ")
    monkeypatch.setenv(f"{prefix}_E2E_SYNC_KEY", key.decode("ascii"))
    monkeypatch.setenv(f"{prefix}_E2E_SYNC_DIR", str(tmp_path / "spool"))
    sync = E2ESync(state_path=tmp_path / "state.json", skills_dir=tmp_path / "skills")
    assert sync.enabled() and sync.available
    assert sync.device_id == "alias-device" and sync.device_label == "Travel laptop"
    transports = sync._active_transports()
    assert len(transports) == 1 and isinstance(transports[0], DirectorySyncTransport)
    assert transports[0].spool_dir == tmp_path / "spool"
    record = {"marker": "synthetic alias key roundtrip"}
    envelope = sync.encrypt_record(record)
    assert Fernet(key).decrypt(envelope["ct"].encode("ascii"))
    assert sync.decrypt_record(envelope) == record
    explicit = E2ESync(device_id="explicit", device_label="Explicit", key=key.decode("ascii"),
                       state_path=tmp_path / "explicit.json")
    assert explicit.device_id == "explicit" and explicit.device_label == "Explicit"


@pytest.mark.parametrize("prefix", ["JARVIS", "NERVA"])
def test_room_host_fallback_and_fencing_secret_aliases(tmp_path, monkeypatch, prefix):
    from agents.core import env_alias, env_provenance
    from agents.core.rooms import RoomStore

    # An unresolved HMAC secret must be refused, rather than disable signatures.
    secret_name = f"{prefix}_ROOM_FENCING_SECRET"
    values = env_provenance.layer_values(((secret_name, "${MISSING_ROOM_SECRET}"),), {})
    verdict = env_provenance.judge(values, env_alias.fold(values.values))
    assert verdict.refused == {secret_name: env_provenance.CREDENTIAL_UNSET}

    monkeypatch.setenv(f"{prefix}_HOST_ID", " alias-host ")
    monkeypatch.setenv(f"{prefix}_DEVICE_ID", "fallback-device")
    monkeypatch.setenv(f"{prefix}_ROOM_FENCING_SECRET", "  synthetic room fixture  ")
    store = RoomStore(tmp_path / "rooms.json")
    assert store.host_id == "alias-host"
    assert store._signing_secret == "  synthetic room fixture  "  # secret bytes are not trimmed
    explicit = RoomStore(tmp_path / "explicit.json", host_id="explicit", signing_secret="")
    assert explicit.host_id == "explicit" and explicit._signing_secret == ""
    monkeypatch.setenv(f"{prefix}_HOST_ID", " ")
    assert RoomStore(tmp_path / "fallback.json").host_id == "fallback-device"


@pytest.mark.parametrize("prefix", ["JARVIS", "NERVA"])
def test_browser_loopback_option_alias_keeps_https_and_remote_floor(monkeypatch, prefix):
    from agents.core.browser_broker import BrowserBrokerError, _check_https_transport

    monkeypatch.setenv(f"{prefix}_BROWSER_BROKER_ALLOW_LOOPBACK_HTTP", "0")
    with pytest.raises(BrowserBrokerError, match="HTTPS"):
        _check_https_transport("http", "127.0.0.1")
    _check_https_transport("https", "remote.example")
    monkeypatch.setenv(f"{prefix}_BROWSER_BROKER_ALLOW_LOOPBACK_HTTP", "1")
    _check_https_transport("http", "127.0.0.1")
    with pytest.raises(BrowserBrokerError, match="HTTPS"):
        _check_https_transport("http", "remote.example")


@pytest.mark.asyncio
@pytest.mark.parametrize("verb,field", [("roam", "roam"), ("overlay", "overlay_enabled")])
@pytest.mark.parametrize("value,expected", [("YeS", True), ("off", False), ("invalid", False)])
async def test_pet_toggle_commands_parse_arguments_without_environment(monkeypatch, verb, field, value, expected):
    from agents.core.commands import _pet_command

    # Command text, rather than an environment-variable name, is being parsed.
    monkeypatch.setenv("YeS", "0")
    updates = []
    store = SimpleNamespace(update_preferences=lambda **kw: updates.append(kw))
    await _pet_command(SimpleNamespace(args=f"{verb} {value}", orch=SimpleNamespace(pets=store)))
    assert updates == [{field: expected}]
