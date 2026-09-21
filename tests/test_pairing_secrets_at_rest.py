"""H497 — what the sender-pairing store is allowed to keep on disk.

``agents/core/channels/pairing.py`` holds the two credentials that turn a stranger
into somebody the assistant answers: the self-service pairing code, and every
outstanding deeplink token. Until H497 both sat in ``memory_logs/sender_pairing.json``
in the clear — the code under ``"code"``, each token as a dict *key* — and the file
was written with a default-umask 0644. Anyone who could read it (another account on
the box, a backup, a synced folder, a support bundle, an agent with file access)
could pair themselves without the owner ever being asked. That is the whole of the
front door, bypassed by a ``cat``.

Both halves of the fix are pinned here, and both halves matter:

  · the raw bytes of the file contain neither credential, and the file is
    owner-only — without this the refactor is invisible;
  · a code still pairs and a link still redeems, across a restart *and* across an
    upgrade from a pre-H497 plaintext file — without this the change silently
    locks every already-paired owner out and kills links that are in flight.

Hermetic: a ``tmp_path`` store and an injected clock. No env, no network.
"""

from __future__ import annotations

import hashlib
import json
import stat

import pytest

from agents.core.channels.pairing import ALLOWED, PENDING, UNKNOWN, SenderPairing

CODE = "correct-horse-battery-staple"


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "sender_pairing.json"


@pytest.fixture
def store(store_path):
    return SenderPairing(store_path)


def _raw(path) -> str:
    return path.read_text(encoding="utf-8")


# ── the pairing code ─────────────────────────────────────────────────────────

def test_the_pairing_code_never_reaches_the_file(store, store_path):
    """The file used to carry `"code": "<the code>"`. Whoever read it could pair."""
    store.set_code(CODE)
    assert CODE not in _raw(store_path)
    # and not by accident — the digest really is there, under its own salt
    on_disk = json.loads(_raw(store_path))["code"]
    assert set(on_disk) == {"salt", "hash", "kdf", "rounds"}
    assert on_disk["hash"] == hashlib.pbkdf2_hmac(
        "sha256", CODE.encode(), on_disk["salt"].encode(), on_disk["rounds"]).hex()


def test_the_code_digest_is_stretched_not_a_bare_sha256(store, store_path):
    """The shape pin above was tightened after the review, not loosened.

    Its first form asserted a bare `sha256(salt + code)`, and that digest is a
    work factor of one: a four-digit code was recovered from a store file by
    exhausting 10,000 candidates in 0.006 s and then used to pair. Stretching does
    not make a weak code strong — it charges the attacker the round count per
    candidate, which is the only thing a KDF can honestly promise — so what this
    pins is that the cost is actually being charged.
    """
    store.set_code(CODE)
    on_disk = json.loads(_raw(store_path))["code"]

    assert on_disk["kdf"] == "pbkdf2-sha256"
    assert on_disk["rounds"] >= 200_000
    assert on_disk["hash"] != hashlib.sha256(
        f"{on_disk['salt']}{CODE}".encode()).hexdigest(), (
        "the code is stored as a single unstretched SHA-256 round"
    )


def test_a_code_hashed_before_stretching_still_pairs_and_is_upgraded(store, store_path):
    """An upgrade must not retire a code the owner has already handed out.

    A store written by the first cut of this slice carries `{"salt", "hash"}` with
    no KDF marker. That digest cannot be re-derived without the plaintext, so it
    has to keep verifying — and the one moment the plaintext IS in hand is a
    successful pair, which is where the record gets rewritten.
    """
    store.set_code(CODE)
    raw = json.loads(_raw(store_path))
    salt = raw["code"]["salt"]
    raw["code"] = {"salt": salt,
                   "hash": hashlib.sha256(f"{salt}{CODE}".encode()).hexdigest()}
    store_path.write_text(json.dumps(raw), encoding="utf-8")

    reopened = SenderPairing(store_path)
    assert reopened.request("telegram", "phone", code=CODE)["paired_by"] == "code"

    upgraded = json.loads(_raw(store_path))["code"]
    assert upgraded["kdf"] == "pbkdf2-sha256"
    assert CODE not in _raw(store_path)


def test_a_failed_guess_never_rewrites_the_stored_record(store, store_path):
    """Nothing about the stored form may depend on what a stranger guessed."""
    store.set_code(CODE)
    raw = json.loads(_raw(store_path))
    salt = raw["code"]["salt"]
    legacy = {"salt": salt, "hash": hashlib.sha256(f"{salt}{CODE}".encode()).hexdigest()}
    raw["code"] = legacy
    store_path.write_text(json.dumps(raw), encoding="utf-8")

    reopened = SenderPairing(store_path)
    assert reopened.request("telegram", "stranger", code="nope")["status"] == PENDING

    assert json.loads(_raw(store_path))["code"] == legacy


def test_a_hashed_code_still_pairs_and_a_wrong_one_still_does_not(store):
    """The half that keeps the owner in: hashing must not retire the code."""
    store.set_code(CODE)
    assert store.has_code() is True
    assert store.request("telegram", "phone", code=CODE)["paired_by"] == "code"
    assert store.status("telegram", "phone") == ALLOWED
    assert store.request("telegram", "stranger", code="nope")["status"] == PENDING
    assert store.status("telegram", "stranger") == PENDING


def test_clearing_the_code_clears_the_digest_on_disk(store, store_path):
    store.set_code(CODE)
    store.set_code(None)
    assert store.has_code() is False
    assert json.loads(_raw(store_path))["code"] is None
    assert store.request("telegram", "stranger", code=CODE)["status"] == PENDING


def test_two_stores_with_the_same_code_do_not_share_a_digest(tmp_path):
    """Per-credential salt: one cracked install must not hand over the others, and
    a precomputed table of common codes must not match anything."""
    first, second = SenderPairing(tmp_path / "a.json"), SenderPairing(tmp_path / "b.json")
    first.set_code(CODE)
    second.set_code(CODE)
    a = json.loads(_raw(tmp_path / "a.json"))["code"]
    b = json.loads(_raw(tmp_path / "b.json"))["code"]
    assert a["salt"] != b["salt"] and a["hash"] != b["hash"]
    assert hashlib.sha256(CODE.encode()).hexdigest() not in _raw(tmp_path / "a.json")


# ── deeplink tokens ──────────────────────────────────────────────────────────

def test_a_deeplink_token_never_reaches_the_file(store, store_path):
    """The token used to BE the dict key. A reader of the file held a live link."""
    token = store.mint_deeplink(now=0.0)["token"]
    raw = _raw(store_path)
    assert token not in raw
    # not stored as a bare hash either: an unsalted digest is a lookup key across
    # every install that ever minted the same token-shaped string
    assert hashlib.sha256(token.encode()).hexdigest() not in raw
    entry = next(iter(json.loads(raw)["deeplinks"].values()))
    assert entry["hash"] == hashlib.sha256(
        f"{entry['salt']}{token}".encode()).hexdigest()


def test_a_hashed_link_still_redeems_exactly_once(store):
    link = store.mint_deeplink(now=0.0)
    assert store.redeem_deeplink(link["token"], "telegram", "42", now=1.0)["ok"] is True
    assert store.status("telegram", "42") == ALLOWED
    replay = store.redeem_deeplink(link["token"], "telegram", "99", now=2.0)
    assert replay == {"ok": False, "reason": "invalid_or_expired_token"}


def test_a_wrong_token_is_still_refused_indistinguishably(store):
    """Hashing must not turn "no match" into "match": every miss looks the same."""
    store.mint_deeplink(now=0.0)
    spent = store.mint_deeplink(now=0.0)
    store.redeem_deeplink(spent["token"], "telegram", "1", now=1.0)
    reasons = {
        store.redeem_deeplink("never-existed", "telegram", "2", now=2.0)["reason"],
        store.redeem_deeplink(spent["token"], "telegram", "3", now=2.0)["reason"],
    }
    assert reasons == {"invalid_or_expired_token"}
    assert store.status("telegram", "2") != ALLOWED


def test_both_credentials_survive_a_restart(store_path):
    """Hashed is only useful if it is also durable: reopening the file must not
    drop the code or the outstanding link."""
    first = SenderPairing(store_path)
    first.set_code(CODE)
    link = first.mint_deeplink(now=0.0)

    reopened = SenderPairing(store_path)
    assert reopened.has_code() is True
    assert reopened.request("telegram", "phone", code=CODE)["paired_by"] == "code"
    assert reopened.redeem_deeplink(link["token"], "telegram", "42", now=1.0)["ok"] is True


# ── the upgrade path (a file written by the previous release) ────────────────

LEGACY_TOKEN = "legacy-token-written-in-the-clear"


def _legacy_file(path, *, expires_at: float = 300.0) -> None:
    """Exactly what the release before H497 wrote: a plaintext code, and a deeplink
    entry keyed by the raw token."""
    path.write_text(json.dumps({
        "senders": {"telegram:7": {
            "channel": "telegram", "sender_id": "7", "name": "owner",
            "status": ALLOWED, "created_at": 0.0, "updated_at": 0.0,
        }},
        "code": CODE,
        "attempts": {},
        "deeplinks": {LEGACY_TOKEN: {
            "channel": "telegram", "created_at": 0.0, "expires_at": expires_at,
        }},
    }), encoding="utf-8")


def test_a_pre_h497_file_is_rewritten_hashed_on_open(store_path):
    _legacy_file(store_path)
    SenderPairing(store_path)
    raw = _raw(store_path)
    assert CODE not in raw
    assert LEGACY_TOKEN not in raw


def test_the_upgrade_keeps_the_code_and_the_outstanding_link_working(store_path):
    """The migration is where this breaks: an owner who upgrades must still be able
    to pair with the code they already handed out, and a link already sent must
    still redeem — otherwise the fix locks people out of their own assistant."""
    _legacy_file(store_path)
    migrated = SenderPairing(store_path)

    assert migrated.status("telegram", "7") == ALLOWED            # paired senders kept
    assert migrated.has_code() is True
    assert migrated.request("telegram", "phone", code=CODE)["paired_by"] == "code"
    assert migrated.redeem_deeplink(LEGACY_TOKEN, "telegram", "42", now=1.0)["ok"] is True
    assert migrated.status("telegram", "42") == ALLOWED


def test_a_migrated_link_keeps_its_original_expiry(store_path):
    """Rehashing must not hand an in-flight link a fresh TTL: it dies when it was
    always going to die."""
    _legacy_file(store_path, expires_at=300.0)
    migrated = SenderPairing(store_path)
    assert migrated.outstanding_deeplinks(now=299.0) == 1
    assert migrated.outstanding_deeplinks(now=301.0) == 0
    late = migrated.redeem_deeplink(LEGACY_TOKEN, "telegram", "42", now=301.0)
    assert late == {"ok": False, "reason": "invalid_or_expired_token"}
    assert migrated.status("telegram", "42") != ALLOWED


def test_the_upgrade_does_not_admit_a_wrong_credential(store_path):
    """A migration that accepted anything would be worse than the plaintext."""
    _legacy_file(store_path)
    migrated = SenderPairing(store_path)
    assert migrated.redeem_deeplink("not-the-token", "telegram", "9", now=1.0)["ok"] is False
    assert migrated.request("telegram", "stranger", code="not-the-code")["status"] == PENDING
    assert migrated.status("telegram", "9") != ALLOWED
    assert migrated.status("telegram", "stranger") == PENDING


def test_opening_a_store_with_nothing_to_migrate_does_not_rewrite_it(store_path, monkeypatch):
    """The rewrite is a one-time upgrade, not a write on every boot. An
    already-hashed store must open without touching the disk — otherwise every
    restart churns the file (and, on a read-only data dir, every restart fails a
    write for nothing)."""
    seeded = SenderPairing(store_path)
    seeded.set_code(CODE)
    seeded.mint_deeplink(now=0.0)

    writes: list[str] = []
    monkeypatch.setattr(SenderPairing, "_save", lambda self: writes.append("save"))
    SenderPairing(store_path)
    assert writes == []                       # nothing to migrate, nothing written
    _legacy_file(store_path)
    SenderPairing(store_path)
    assert writes == ["save"]                 # the plaintext file, rewritten once


def test_a_half_written_code_digest_is_treated_as_no_code(store_path):
    """A truncated or hand-edited digest can never match, so it must read as "no
    code" rather than as a code nobody can present."""
    store_path.write_text(json.dumps({"code": {"salt": "abc"}}), encoding="utf-8")
    broken = SenderPairing(store_path)
    assert broken.has_code() is False
    assert broken.request("telegram", "stranger", code="abc")["status"] == PENDING


# ── the file itself ──────────────────────────────────────────────────────────

def test_the_pairing_store_file_is_owner_only(store, store_path):
    """0644 on a default umask meant every account on the box could read the
    pairing state. Hashing the credentials does not excuse that."""
    store.set_code(CODE)
    assert stat.S_IMODE(store_path.stat().st_mode) == 0o600


def test_every_json_store_write_lands_owner_only(tmp_path):
    """The mode is set on the tmp before the replace, so there is no window in
    which the real file exists world-readable. Shared by every JsonStore."""
    from agents.core.persistence import atomic_write_json

    target = tmp_path / "anything.json"
    atomic_write_json(target, {"x": 1})
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    # a rewrite over an existing file keeps it owner-only too
    atomic_write_json(target, {"x": 2})
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


# ── shapes that must narrow rather than raise ────────────────────────────────
#
# Both halves of the store now pass every value through a hash, which a raw-string
# compare never did. That makes *encodability* a new precondition where there was
# none, and `json.loads` hands out strings that are not UTF-8-encodable: a `\ud800`
# escape decodes to a lone surrogate. Such a string reaches the hash from a crafted
# or corrupted store file (on open) and from the body of
# `POST /api/channels/pairing/request`, the one pairing route a stranger is meant to
# reach. Unguarded, the first is a boot failure and the second a 500 — so these pin
# that hashing stayed total.

SURROGATE = json.loads(r'"\ud800bad"')   # exactly what a JSON body/file yields


def test_a_store_file_with_an_unencodable_code_does_not_crash_startup(store_path):
    """JsonStore promises "a bad file never crashes startup". Hashing on open must
    not quietly revoke that promise for the one store holding credentials."""
    store_path.write_text(json.dumps({"code": SURROGATE}), encoding="utf-8")
    opened = SenderPairing(store_path)                    # must not raise
    assert opened.has_code() is True                      # accepted, as before H497
    assert SURROGATE not in _raw(store_path)              # but not left in the clear
    assert opened.request("telegram", "a", code=SURROGATE)["paired_by"] == "code"
    assert opened.request("telegram", "b", code="other")["status"] == PENDING


def test_a_store_file_with_an_unencodable_deeplink_key_does_not_crash_startup(store_path):
    store_path.write_text(json.dumps({"deeplinks": {SURROGATE: {
        "channel": "telegram", "created_at": 0.0, "expires_at": 1e12,
    }}}), encoding="utf-8")
    opened = SenderPairing(store_path)                    # must not raise
    assert opened.outstanding_deeplinks(now=1.0) == 1     # in-flight link survives
    assert SURROGATE not in _raw(store_path)
    assert opened.redeem_deeplink(SURROGATE, "telegram", "42", now=1.0)["ok"] is True


def test_an_unencodable_credential_is_refused_not_raised(store):
    """The live half: `/api/channels/pairing/request` takes a `code` from an
    unauthenticated body, and telegram hands `/start <token>` straight to redeem.
    A guess that cannot be UTF-8 encoded must miss like any other guess — a raise
    here is a 500 any stranger can trigger four bytes at a time."""
    store.set_code(CODE)
    store.mint_deeplink(now=0.0)
    assert store.request("telegram", "attacker", code=SURROGATE)["status"] == PENDING
    assert store.redeem_deeplink(SURROGATE, "telegram", "attacker", now=1.0) == {
        "ok": False, "reason": "invalid_or_expired_token"}
    assert store.status("telegram", "attacker") == PENDING


def test_a_migration_that_cannot_rewrite_the_file_still_boots(store_path):
    """The one-time rewrite is best-effort against *any* failure, not just the
    read-only/full data dir its docstring names. The same store can hold a value
    no `_save` can serialize — here a sender name with a lone surrogate — and the
    migration is the first thing that tries to write it. Catching only OSError
    turned that into a boot failure; the gate must come up on the hashed in-memory
    state regardless, with the plaintext left on disk until a later save succeeds.

    (Whether such a store can be *written* afterwards is a separate, pre-existing
    matter: `_save` raises on that sender name at HEAD too, with or without this
    change. Only the constructor is this slice's to keep quiet.)"""
    store_path.write_text(json.dumps({
        "senders": {"telegram:7": {
            "channel": "telegram", "sender_id": "7", "name": SURROGATE,
            "status": ALLOWED, "created_at": 0.0, "updated_at": 0.0,
        }},
        "code": CODE, "attempts": {}, "deeplinks": {},
    }), encoding="utf-8")

    opened = SenderPairing(store_path)                    # must not raise
    # read-only surface of the gate is intact and running on the hashed state
    assert opened.has_code() is True
    assert opened.summary()["has_code"] is True
    assert opened.status("telegram", "7") == ALLOWED
    assert opened.is_allowed("telegram", "7") is True
    assert opened.status("telegram", "stranger") == UNKNOWN
    # honest about the cost: the rewrite failed, so the plaintext is still there,
    # and no half-written tmp was left beside it
    assert CODE in _raw(store_path)
    assert not (store_path.parent / (store_path.name + ".tmp")).exists()


@pytest.mark.parametrize("present, missing", [("salt", "hash"), ("hash", "salt")])
def test_a_deeplink_entry_with_a_half_written_digest_is_dropped(store_path, present, missing):
    """The mirror of `test_a_half_written_code_digest_is_treated_as_no_code`, and
    the sharper of the two. Before H497 a deeplink's dict key *was* its token, so
    "this entry has no digest" could safely mean "the key is the token". Since
    H497 the key is an opaque id printed in the file, so applying that rule to a
    post-H497 entry that lost one of its two digest fields would re-migrate it and
    make the id itself pair — putting a working credential back in the clear,
    which is the whole thing this change exists to prevent."""
    entry = {"channel": "telegram", "created_at": 0.0, "expires_at": 1e12,
             present: "zz"}
    store_path.write_text(
        json.dumps({"deeplinks": {"0123456789abcdef": entry}}), encoding="utf-8")

    opened = SenderPairing(store_path)
    assert missing not in entry                           # the shape under test
    assert opened.outstanding_deeplinks(now=1.0) == 0     # dropped, not kept
    assert opened.redeem_deeplink(
        "0123456789abcdef", "telegram", "99", now=1.0) == {
            "ok": False, "reason": "invalid_or_expired_token"}
    assert opened.status("telegram", "99") != ALLOWED


def test_the_payload_is_never_written_into_a_world_readable_file(tmp_path, monkeypatch):
    """The chmod-after-write ordering did not close the window it claimed to.

    The first cut wrote the payload with `write_text` and chmod'd the tmp before
    the `replace`, on the reasoning that `replace` moves the tmp's inode over the
    target. True, and still not enough: `write_text` creates the tmp at
    `0o666 & ~umask` — 0644 on a default umask — and the *whole payload is already
    in it* by the time the chmod runs. A store holding a pairing digest sits
    world-readable for the length of that write.

    Neutralising the chmod is what separates the two: with the payload written
    through a descriptor opened 0600, the mode is right without it.
    """
    import os as _os

    from agents.core.persistence import atomic_write_json

    monkeypatch.setattr(_os, "chmod", lambda *a, **k: None)
    target = tmp_path / "secrets.json"

    atomic_write_json(target, {"code": {"salt": "s", "hash": "h"}})

    assert stat.S_IMODE(target.stat().st_mode) == 0o600, (
        "the payload was written into a file created with the default umask mode"
    )


def test_the_write_is_still_atomic_and_still_cleans_up_after_itself(tmp_path):
    """The properties the descriptor rewrite must not have cost.

    A raising serializer leaves the previous good file intact and no `*.tmp`
    behind — the whole reason this helper exists.
    """
    from agents.core.persistence import atomic_write_json

    target = tmp_path / "store.json"
    atomic_write_json(target, {"good": 1})

    class _Unserializable:
        pass

    with pytest.raises(TypeError):
        atomic_write_json(target, {"bad": _Unserializable()})

    assert json.loads(target.read_text(encoding="utf-8")) == {"good": 1}
    assert not list(tmp_path.glob("*.tmp"))


def test_the_kdf_a_stranger_can_trigger_stays_inside_the_guess_budget(store):
    """Stretching the code hands a stranger a CPU lever; the budget is what bounds it.

    ``POST /api/channels/pairing/request`` is the one pairing route an unpaired sender is
    meant to reach, and a presented code costs 240k PBKDF2 rounds to check. The per-sender
    limit cannot bound that on its own — the sender id is whatever the caller wrote in the
    body, so a guesser rotates it — which is exactly why ``_code_guess_budget_spent`` is
    store-wide and is consulted BEFORE the compare.

    Counting the hashes rather than timing them: a slow CI box must not be able to fail
    this, and the round count is the cost.
    """
    from agents.core.channels import pairing as mod

    store.set_code("7777")
    calls = []
    real = mod._stretch
    mod._stretch = lambda salt, value, rounds: (calls.append(rounds), real(salt, value, rounds))[1]
    try:
        statuses = [store.request("telegram", f"stranger-{i}", code="0000")["status"]
                    for i in range(mod._MAX_CODE_GUESSES_PER_WINDOW * 6)]
    finally:
        mod._stretch = real

    assert len(calls) <= mod._MAX_CODE_GUESSES_PER_WINDOW, (
        f"{len(calls)} KDF runs for {len(statuses)} requests — the budget is not holding "
        "the lever down"
    )
    assert statuses.count("rate_limited") > len(statuses) // 2, (
        "premise: the flood must actually be turned away, not merely un-hashed"
    )
    # And a sender who presents no code at all never reaches the KDF in the first place.
    calls.clear()
    mod._stretch = lambda salt, value, rounds: (calls.append(rounds), real(salt, value, rounds))[1]
    try:
        store.request("telegram", "polite-stranger")
    finally:
        mod._stretch = real
    assert calls == []
