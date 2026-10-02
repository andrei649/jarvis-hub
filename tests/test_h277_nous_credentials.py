"""H277 profile storage and inference token usability with synthetic credentials."""

import base64
import json
import threading
import time

import pytest

from agents.core.llm.nous_credentials import NousAuthStore, usable_inference_token
from agents.core.secrets import SecretStore

KEY = base64.urlsafe_b64encode(b"nous-test-key-is-exactly-32-bytes!").decode()


def _jwt(*, exp=None, scope=None, scp=None):
    claims = {}
    if exp is not None:
        claims["exp"] = exp
    if scope is not None:
        claims["scope"] = scope
    if scp is not None:
        claims["scp"] = scp

    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return f"{encode({'alg': 'RS256', 'typ': 'JWT'})}.{encode(claims)}.{encode({'sig': 'synthetic'})}"


def _store(tmp_path):
    return NousAuthStore(
        tmp_path / "security" / "nous.sqlite3",
        cipher=SecretStore(tmp_path / "cipher.keys", key=KEY),
    )


def test_absent_read_does_not_create_directory_or_key(tmp_path):
    root = tmp_path / "missing"
    store = NousAuthStore(root / "nous.sqlite3")
    assert store.read() == {}
    assert not root.exists()


def test_transactions_encrypt_and_survive_restart(tmp_path):
    store = _store(tmp_path)
    with store.transaction("alice") as state:
        state.update(access_token="synthetic-secret-access", refresh_token="synthetic-secret-refresh")

    database = (tmp_path / "security" / "nous.sqlite3").read_bytes()
    assert b"synthetic-secret-access" not in database
    assert b"synthetic-secret-refresh" not in database
    assert _store(tmp_path).read("alice") == {
        "access_token": "synthetic-secret-access",
        "refresh_token": "synthetic-secret-refresh",
    }


def test_profiles_isolated_and_empty_transaction_deletes_only_its_profile(tmp_path):
    store = _store(tmp_path)
    with store.transaction("alice") as state:
        state["access_token"] = "alice-token"
    with store.transaction("bob") as state:
        state["access_token"] = "bob-token"
    with store.transaction("alice") as state:
        state.clear()
    assert store.read("alice") == {}
    assert store.read("bob") == {"access_token": "bob-token"}


def test_exception_rolls_back_existing_profile(tmp_path):
    store = _store(tmp_path)
    with store.transaction() as state:
        state["access_token"] = "before"
    with pytest.raises(RuntimeError, match="abort"), store.transaction() as state:
        state["access_token"] = "after"
        raise RuntimeError("abort")
    assert _store(tmp_path).read() == {"access_token": "before"}


def test_transactions_from_distinct_instances_serialize_updates(tmp_path):
    first = _store(tmp_path)
    second = _store(tmp_path)
    entered = threading.Event()
    errors = []

    def slow_update():
        try:
            with first.transaction() as state:
                state["count"] = int(state.get("count", 0)) + 1
                entered.set()
                time.sleep(0.15)
        except Exception as exc:
            errors.append(exc)

    def peer_update():
        try:
            assert entered.wait(2)
            with second.transaction() as state:
                state["count"] = int(state.get("count", 0)) + 1
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=slow_update), threading.Thread(target=peer_update)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(3)
    assert not errors
    assert not any(thread.is_alive() for thread in threads)
    assert _store(tmp_path).read() == {"count": 2}


@pytest.mark.parametrize("profile", ["", "../alice", "a.b", "a" * 65, " café", "x/y"])
def test_invalid_profile_names_are_rejected(tmp_path, profile):
    store = NousAuthStore(tmp_path / "nous.sqlite3")
    with pytest.raises(ValueError):
        store.read(profile)
    with pytest.raises(ValueError), store.transaction(profile):
        pass
    assert not (tmp_path / "nous.sqlite3").exists()


def test_oversized_state_rolls_back_without_plaintext(tmp_path):
    store = _store(tmp_path)
    with store.transaction() as state:
        state["access_token"] = "before"
    with pytest.raises(ValueError), store.transaction() as state:
        state["refresh_token"] = "secret-" + "x" * 70000
    assert store.read() == {"access_token": "before"}
    assert b"secret-" not in (tmp_path / "security" / "nous.sqlite3").read_bytes()


def test_jwt_selection_prefers_usable_agent_key_and_falls_back_to_access_token():
    now = 1_700_000_000
    agent = _jwt(exp=now + 600, scope="inference:invoke")
    access = _jwt(exp=now + 500, scope="inference:invoke")
    assert usable_inference_token({"agent_key": agent, "access_token": access}, now=now) == agent
    near = _jwt(exp=now + 119, scope="inference:invoke")
    assert usable_inference_token({"agent_key": near, "access_token": access}, now=now) == access


@pytest.mark.parametrize(
    "claims,declared",
    [
        ({"exp": 1_700_000_600, "scope": "openid"}, None),
        ({"exp": 1_700_000_600, "scp": ["profile"]}, None),
        ({"exp": True, "scope": "inference:invoke"}, None),
        ({"exp": float("inf"), "scope": "inference:invoke"}, None),
        ({"exp": 1_700_000_119, "scope": "inference:invoke"}, None),
    ],
)
def test_invalid_expiry_or_scope_cannot_enable_inference(claims, declared):
    token = _jwt(**claims)
    state = {"access_token": token}
    if declared is not None:
        state["scope"] = declared
    assert usable_inference_token(state, now=1_700_000_000) is None


def test_declared_scope_and_iso_expiry_support_jwt_without_claims():
    token = _jwt()
    state = {"access_token": token, "scope": "openid inference:invoke", "expires_at": "2023-11-14T22:23:30Z"}
    assert usable_inference_token(state, now=1_700_000_000) == token
    assert usable_inference_token({"access_token": "opaque", "scope": "inference:invoke", "expires_at": 1_700_000_600}, now=1_700_000_000) is None


def test_scp_claim_grants_inference_when_declared_scope_absent():
    token = _jwt(exp=1_700_000_600, scp=["inference:invoke"])
    assert usable_inference_token({"access_token": token}, now=1_700_000_000) == token


def test_comma_separated_declared_scope_grants_inference():
    token = _jwt(exp=1_700_000_600)
    assert usable_inference_token(
        {"access_token": token, "scope": "openid,inference:invoke"}, now=1_700_000_000
    ) == token


def test_list_scope_entries_may_contain_separated_scopes():
    token = _jwt(exp=1_700_000_600, scp=["openid inference:invoke"])
    assert usable_inference_token({"access_token": token}, now=1_700_000_000) == token


def test_declared_and_claim_scopes_form_union():
    token = _jwt(exp=1_700_000_600, scope="openid")
    assert usable_inference_token(
        {"access_token": token, "scope": "inference:invoke"}, now=1_700_000_000
    ) == token


def test_huge_expiry_is_rejected_without_raising():
    token = _jwt(exp=10**1000, scope="inference:invoke")
    assert usable_inference_token({"access_token": token}, now=1_700_000_000) is None


def test_timezone_free_expiry_does_not_depend_on_host_timezone():
    token = _jwt()
    assert usable_inference_token(
        {"access_token": token, "scope": "inference:invoke", "expires_at": "2023-11-14T22:23:30"},
        now=1_700_000_000,
    ) is None
