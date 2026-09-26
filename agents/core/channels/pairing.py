"""
pairing.py — H12.19 Inbound sender pairing / approval (anti-abuse).

Today an unknown sender on a chat channel is silently dropped against a static
``allowed_users`` list. This adds a *governed pairing flow* — the human-sender
mirror of the H16.2 A2A peer allowlist:

* **On by default (Hermes absorption 5b).** A stranger who finds the bot is held
  until the owner pairs them. ``JARVIS_CHANNEL_PAIRING=0`` switches the gate off and
  ``is_allowed`` then returns True for everyone — at which point the boot guard
  (``boot_guards.assert_guarded_channels``) demands a per-channel allowlist or an
  explicit ``JARVIS_CHANNEL_OPEN=1`` acknowledgement before a chat bot may start.
* **Known senders pass.** An approved ``(channel, sender_id)`` is allowed through
  immediately.
* **Unknown senders are held, not run.** First contact from an unknown sender
  creates a *pending* request the owner approves / rejects / blocks out-of-band —
  exactly like the A2A inbox / H6.2 decision queue. Nothing the unknown sender
  says reaches the orchestrator until approved.
* **Optional pairing code.** The owner can set a rotating code; a sender that
  presents it is auto-approved (self-service) without an owner tap.
* **Deeplink pairing (the 60-second path).** The owner mints a single-use,
  short-lived token and opens ``https://t.me/<bot>?start=<token>`` on their phone;
  Telegram delivers ``/start <token>`` and the first sender to redeem it is
  approved. This is the activation lever — copying a code between two devices is
  where people give up — and it is safe because the token is **one-use**, expires
  in minutes, is compared in constant time, and is never logged. A link that could
  pair twice would pair whoever saw the screen after the owner did.
* **The owner's own ids pass.** A channel allowlist (``TELEGRAM_ALLOWED_USER_IDS``)
  names the owner; those senders are allowed without a pairing record, so an
  install that upgrades with an allowlist is not locked out of its own bot. The
  boot guard treats the allowlist as an equivalent guard, and this is what makes
  that true at runtime. (Hermes absorption 5b)
* **Anti-abuse.** Pairing attempts are rate-limited per ``(channel, sender)``, the
  pending list is bounded, and wrong pairing-code guesses are throttled *globally*
  — sender ids on a webhook or an HTTP request are attacker-chosen, so a
  per-sender bucket alone never binds on a code brute-force. (Hermes absorption 5b)
* **Neither credential is written down.** The pairing code and every outstanding
  deeplink token are kept as a *salted digest only* — the code under its own salt,
  each link keyed by an opaque id with the token's digest inside the entry.
  Verifying is a hash-then-``compare_digest``, so it stays constant-time and the
  deeplink failure reasons stay indistinguishable.

  **What that is worth, credential by credential.** A deeplink token is 192 bits
  from ``token_urlsafe(24)``: its digest is not recoverable, full stop. The
  pairing code is whatever the owner typed, and a digest of a low-entropy secret
  is a *work factor*, never a wall — the first cut of this module claimed the
  store "holds nothing that can pair anybody", and a four-digit code was
  recovered from it by exhausting 10,000 candidates in 0.006 s, then used to
  pair. The code is therefore stretched (PBKDF2-HMAC-SHA256, see
  ``_CODE_ROUNDS``), which multiplies that cost by the round count rather than
  removing it: a four-digit code becomes minutes instead of milliseconds, and an
  eight-character code from a mixed alphabet becomes infeasible. Nothing here
  enforces a floor on what the owner types, and generating the code for them —
  the row's own prescription, eight characters from a 32-character unambiguous
  alphabet — is not implemented. A file
  written by an earlier release still carries them in the clear; it is accepted
  once on open and rewritten hashed, keeping each link's channel and expiry so an
  upgrade never locks the owner out or resurrects a spent link. (H497)

File-backed (JSON at ``data_path("sender_pairing.json")`` — ``memory_logs/`` in a
plain checkout, ``$JARVIS_HOME`` when the data root is relocated), pure-Python,
offline-testable.

**One instance per process.** The file is read once, at construction, and every save
writes the whole in-memory state back. A second ``SenderPairing`` over the same file
is therefore not a second view of the store but a second store: a link spent through
one is still outstanding in the other, and the other's next save — any save; a
stranger knocking is enough — puts the spent link back on disk, where a third
instance redeems it again. That is precisely the "pair twice" the deeplink promise
above forbids, and it once happened in production: the Telegram adapter built a
throwaway ``SenderPairing()`` per ``/start <token>`` while the orchestrator held the
long-lived one. The orchestrator's ``sender_pairing`` is the one instance — the
gateway gates on it, the pairing router mints and revokes on it, and every adapter
that redeems a link is handed it at construction (``TelegramChannel(pairing=...)``).
An adapter without one refuses to pair rather than opening its own.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Optional

from agents.core.paths import data_path

from ..persistence import JsonStore

DEFAULT_PATH = data_path("sender_pairing.json")

ALLOWED = "allowed"
PENDING = "pending"
BLOCKED = "blocked"
UNKNOWN = "unknown"

_MAX_PENDING = 200          # bound the pending inbox (anti-flood)
_ATTEMPT_WINDOW = 600.0     # rate-limit window for pairing attempts (10 min)
_MAX_ATTEMPTS = 5           # attempts allowed per (channel, sender) per window
# Wrong pairing-code guesses tolerated store-wide per window, whatever the sender id
# says. The per-sender bucket is keyed on an id the caller chooses, so on its own it
# never binds; this one does. A code is meant for one or two devices in the next few
# minutes, so the bound can be small. (Hermes absorption 5b)
_MAX_CODE_GUESSES_PER_WINDOW = 10

# Deeplink tokens. Short by design: the link is meant to be tapped in the next
# minute, on a phone the owner is holding. A longer window buys nothing and keeps
# a working credential alive in a chat log or a screenshot.
DEEPLINK_TTL_SECONDS = 300.0
_MAX_DEEPLINKS = 20         # bound outstanding links; minting a new one is cheap
# 32 bytes of urlsafe randomness. Telegram's `start` payload allows 64 chars, and
# guessing this is not a threat model anyone needs to worry about.
_DEEPLINK_BYTES = 24

# At-rest hashing for both credentials (H497). 128 bits of per-credential salt, so
# two installs with the same pairing code do not share a digest and a precomputed
# table buys nothing.
#
# The two credentials are hashed DIFFERENTLY, and the reason is the threat, not the
# convenience. A deeplink token is plain SHA-256 on purpose: ``redeem_deeplink``
# hashes the candidate once per OUTSTANDING LINK, so a deliberately slow hash there
# hands any stranger who can send `/start junk` a CPU lever — and at 192 bits of
# entropy there is nothing for stretching to buy.
#
# The pairing code is stretched, because none of that applies to it. It is verified
# once per attempt in ``_code_matches``, not once per link; it is whatever the owner
# typed; and the first cut of this module defended leaving it unstretched by
# pointing at the store-wide guess budget, which is an ONLINE control held in
# memory. That budget has no bearing on an attacker who has READ THE FILE, which is
# exactly the threat at-rest hashing answers — and against that attacker a 4-digit
# code fell in 0.006 s. Stretching does not make a weak code strong; it charges the
# attacker the round count for every candidate, which is the only thing a KDF can
# honestly promise.
_SALT_BYTES = 16
#: PBKDF2-HMAC-SHA256 rounds for the pairing code. ~90 ms per attempt here, which a
#: human typing a code never notices and which the store-wide guess budget bounds
#: anyway. Stored WITH each digest rather than read from here at verify time, so
#: raising it later cannot lock an owner out of a code hashed under the old count.
_CODE_ROUNDS = 240_000
#: Written into a stretched record so an unstretched one is recognisable and can be
#: upgraded in place the next time the owner successfully pairs.
_CODE_KDF = "pbkdf2-sha256"
# Opaque handle for a deeplink entry. It replaces the raw token as the dict key and
# is deliberately meaningless: it is not derived from the token, so the file reveals
# nothing about it, not even a digest that could be matched across stores.
_LINK_ID_BYTES = 8


def _new_salt() -> str:
    return secrets.token_hex(_SALT_BYTES)


def _digest(salt: str, value: str) -> str:
    """The stored form of a credential: hex SHA-256 over ``salt + value``.

    Encoded with ``surrogatepass`` so this function is *total*. A lone surrogate
    is not valid UTF-8 but ``json.loads`` produces one happily (from a ``\\ud800``
    escape), so such a string arrives from two directions: a hand-edited or
    corrupted store file, which the migration below hashes on open, and the body
    of ``POST /api/channels/pairing/request``, which is the one pairing route a
    stranger is meant to reach. A plain ``.encode()`` raises ``UnicodeEncodeError``
    on both — turning a bad file into a boot failure (breaking ``JsonStore``'s
    "a bad file never crashes startup" contract) and turning a four-byte request
    body into a 500. ``surrogatepass`` is WTF-8 and stays injective, so hashing
    those strings instead of raising collides nothing. (H497)
    """
    return hashlib.sha256(f"{salt}{value}".encode(errors="surrogatepass")).hexdigest()


def _stretch(salt: str, value: str, rounds: int) -> str:
    """PBKDF2-HMAC-SHA256 over ``salt + value``.

    Same ``surrogatepass`` encoding as :func:`_digest`, and for the same reason:
    this runs on a body a stranger controls, so it has to be total.
    """
    return hashlib.pbkdf2_hmac(
        "sha256", value.encode(errors="surrogatepass"),
        salt.encode(errors="surrogatepass"), rounds,
    ).hex()


def _hash_code(value: str, *, salt: Optional[str] = None, rounds: int = _CODE_ROUNDS) -> dict:
    """The stored form of the PAIRING CODE: a stretched, self-describing record.

    ``kdf`` and ``rounds`` ride along with the digest instead of being read from
    the module at verify time, so raising ``_CODE_ROUNDS`` later cannot lock an
    owner out of a code hashed under the old count.
    """
    chosen = _new_salt() if salt is None else salt
    return {"salt": chosen, "hash": _stretch(chosen, value, rounds),
            "kdf": _CODE_KDF, "rounds": int(rounds)}


def _code_record_matches(entry: object, candidate: str) -> bool:
    """True when *candidate* matches a code record, stretched or not.

    An unstretched record is a store written by the first cut of this slice. It
    still verifies — the digest cannot be re-derived without the plaintext — and
    :meth:`SenderPairing._code_matches` upgrades it in place on the next
    successful pair, which is the one moment the plaintext is in hand.
    """
    if not isinstance(entry, Mapping) or not candidate:
        return False
    salt, stored = entry.get("salt"), entry.get("hash")
    if not isinstance(salt, str) or not isinstance(stored, str) or not salt or not stored:
        return False
    if entry.get("kdf") == _CODE_KDF:
        rounds = entry.get("rounds")
        if not isinstance(rounds, int) or rounds < 1:
            return False      # a record we cannot reproduce is not a match
        return hmac.compare_digest(stored, _stretch(salt, candidate, rounds))
    if entry.get("kdf"):
        return False          # a KDF this build does not implement: fail closed
    return hmac.compare_digest(stored, _digest(salt, candidate))


def _code_needs_upgrade(entry: object) -> bool:
    """True for a record hashed before the code was stretched, or under fewer rounds."""
    if not isinstance(entry, Mapping):
        return False
    if entry.get("kdf") != _CODE_KDF:
        return True
    rounds = entry.get("rounds")
    return not isinstance(rounds, int) or rounds < _CODE_ROUNDS


def _hash_secret(value: str, *, salt: Optional[str] = None) -> dict:
    """``{"salt", "hash"}`` for *value* — the only shape that ever reaches disk."""
    chosen = _new_salt() if salt is None else salt
    return {"salt": chosen, "hash": _digest(chosen, value)}


def _secret_matches(entry: object, candidate: str) -> bool:
    """True when *candidate* hashes to the digest in *entry*, in constant time.

    The candidate is hashed first and only the two fixed-length hex digests are
    compared, so neither the length nor any prefix of the stored credential leaks
    through the comparison — the property the raw-string compare had, kept.
    """
    if not isinstance(entry, Mapping) or not candidate:
        return False
    salt, stored = entry.get("salt"), entry.get("hash")
    if not isinstance(salt, str) or not isinstance(stored, str) or not salt or not stored:
        return False
    return hmac.compare_digest(stored, _digest(salt, candidate))


def _install_id() -> str:
    """H689 — this install's id ('' when it is unavailable)."""
    from agents.core.install_identity import install_id

    return install_id() or ""


def _fresh_link_id(existing: Mapping) -> str:
    """An opaque, unused key for a deeplink entry."""
    while True:
        link_id = secrets.token_hex(_LINK_ID_BYTES)
        if link_id not in existing:
            return link_id


#: The inbound pairing gate. Default-on: unset means "hold strangers".
PAIRING_ENV = "JARVIS_CHANNEL_PAIRING"
#: The operator's written acknowledgement that a chat bot answers any sender.
CHANNEL_OPEN_ENV = "JARVIS_CHANNEL_OPEN"


def pairing_enabled() -> bool:
    """Pairing is an inbound gate — on unless explicitly switched off (Hermes absorption 5b).

    Default-deny: a stranger who finds the bot is held until the owner pairs them
    from the HUD or with a deeplink. A fresh install therefore answers nobody it does
    not know, which is the only posture a front door reachable from a public chat
    network can safely ship with. ``JARVIS_CHANNEL_PAIRING=0`` turns the gate off,
    and then ``boot_guards.assert_guarded_channels`` demands a per-channel allowlist
    or an explicit ``JARVIS_CHANNEL_OPEN=1`` acknowledgement before a bot may start,
    so switching pairing off can never quietly open the bot to everyone. Unset,
    empty and unrecognized spellings resolve to *on* (``env_flag`` semantics); the
    parse-critical boot guard refuses a typo outright rather than guessing.
    """
    from agents.core.env_config import env_flag
    return env_flag(PAIRING_ENV, True)


def channel_open_acknowledged() -> bool:
    """True when the operator has written down that an open bot is intended.

    Off unless explicitly set: this is the acknowledgement, never a default. It is
    read only by the boot guard, which prints a ``[SECURITY]`` line when honouring
    it; the pairing gate itself never consults it. (Hermes absorption 5b)
    """
    from agents.core.env_config import env_flag
    return env_flag(CHANNEL_OPEN_ENV)


#: Channels that carry a per-channel allowlist of the owner's own sender ids, and the
#: env var that holds it. Read by the runtime gate and by the boot guard, so the two
#: cannot disagree about which channels have one. (Hermes absorption 5b)
CHANNEL_ALLOWLIST_ENVS: dict[str, str] = {"telegram": "TELEGRAM_ALLOWED_USER_IDS"}


def parse_sender_allowlist(raw: object) -> tuple[str, ...]:
    """The usable ids in a comma-separated allowlist, as strings (Hermes absorption 5b).

    The same tiny parse the web app applies: integers only, blanks and non-numeric
    entries dropped, so a typo in one id narrows the list rather than widening it or
    taking the bot down. Ids come back as the canonical string of the integer, which
    is what channels thread as ``sender``. Only ids leave here, never a value that
    was not one.
    """
    ids: list[str] = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(str(int(part)))
        except ValueError:
            continue
    return tuple(ids)


def allowlisted_sender_ids(
    channel: str, environ: "Mapping[str, str] | None" = None,
) -> frozenset[str]:
    """The owner's own ids for *channel*, or an empty set when it has no allowlist."""
    env_name = CHANNEL_ALLOWLIST_ENVS.get(str(channel or ""))
    if env_name is None:
        return frozenset()
    env = os.environ if environ is None else environ
    return frozenset(parse_sender_allowlist(env.get(env_name)))


def sender_allowlisted(
    channel: str, sender_id: str, environ: "Mapping[str, str] | None" = None,
) -> bool:
    """True when the channel's allowlist names this sender (Hermes absorption 5b).

    The allowlist is the owner's own ids, written down by the operator; it composes
    with pairing rather than being overridden by it, so an owner who set it before
    pairing became the default is still able to reach their own bot. It never widens
    anything by itself: an unset or empty allowlist names nobody.
    """
    return str(sender_id) in allowlisted_sender_ids(channel, environ)


def _key(channel: str, sender_id: str) -> str:
    return f"{channel}:{sender_id}"


class SenderPairing(JsonStore):
    """Per-``(channel, sender)`` allow/pending/block state + an optional code."""

    def __init__(self, path: "str | Path | None" = DEFAULT_PATH) -> None:
        super().__init__(path)
        # A store written before H497 carries the code and the deeplink tokens in
        # the clear. ``_deserialize`` has already hashed them in memory; push that
        # back so the plaintext stops existing on disk on the first open, rather
        # than whenever the next write happens to come.
        if self._migrated and self._rewrite_hashed():
            self._migrated = False

    def _rewrite_hashed(self) -> bool:
        """Persist the migrated (hashed) state. False when the write failed.

        Best-effort on purpose: nothing about this one-time upgrade may stop the
        process from booting, and the in-memory state is already hashed either way
        — the gate behaves identically, the plaintext simply survives on disk until
        a later save succeeds. Every failure is swallowed, not just ``OSError``: a
        read-only or full data directory raises that, but the same store can also
        hold a value that ``json.dumps``/UTF-8 refuses (a sender name with a lone
        surrogate, say), and a file that merely *cannot be rewritten* must read the
        same as one that can — ``JsonStore``'s "a bad file never crashes startup"
        contract, kept through the migration too.
        """
        try:
            with self._lock:
                self._save()
        except Exception:
            return False
        return True

    def _serialize(self):
        return {
            "senders": self._senders, "code": self._code_hash,
            "attempts": self._attempts, "deeplinks": self._deeplinks,
        }

    def _deserialize(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self._senders = raw.get("senders", {})
        self._attempts = raw.get("attempts", {})
        # Set before the two loaders: either may flip it when it finds plaintext.
        self._migrated = False
        self._code_hash = self._load_code(raw.get("code"))
        self._deeplinks = self._load_deeplinks(raw.get("deeplinks"))
        # Wrong-code guesses store-wide, in memory only: a restart clears it, and a
        # restart is not something a guesser can cause. Persisting would add a write
        # per guess — exactly the load a flood is trying to create.
        self._code_guesses: list[float] = []

    def _load_code(self, stored: object) -> Optional[dict]:
        """The code's digest from disk, migrating a pre-H497 plaintext code.

        The KDF fields are carried through rather than rebuilt. Reconstructing the
        record as ``{"salt", "hash"}`` alone drops ``kdf``/``rounds``, and a
        stretched digest then reads as an unstretched one on the next boot — the
        owner's code stops verifying at all, which is worse than the weakness the
        stretching was added for.
        """
        if isinstance(stored, Mapping):
            salt, digest = stored.get("salt"), stored.get("hash")
            if isinstance(salt, str) and isinstance(digest, str) and salt and digest:
                record = {"salt": salt, "hash": digest}
                kdf, rounds = stored.get("kdf"), stored.get("rounds")
                if isinstance(kdf, str) and kdf:
                    record["kdf"] = kdf
                if isinstance(rounds, int):
                    record["rounds"] = rounds
                return record
            return None  # a half-written digest can never match; treat it as no code
        if isinstance(stored, str) and stored.strip():
            # Pre-H497 file. Accept it once — an upgrade must not silently retire a
            # code the owner has already handed out — and mark the store for rewrite.
            self._migrated = True
            return _hash_code(stored.strip())
        return None

    def _load_deeplinks(self, stored: object) -> dict:
        """Outstanding links from disk, migrating pre-H497 raw-token keys.

        A pre-H497 entry *is* keyed by its token, so the token is recoverable here
        and only here: it is rehashed under a fresh opaque id and the entry keeps
        its channel, ``created_at`` and ``expires_at``. An outstanding link
        therefore still redeems after the upgrade, and still dies at its original
        moment rather than getting a fresh TTL.

        "Legacy" is decided by the *absence of both* digest fields, not by the
        digest being unusable. Since H497 a dict key is an opaque id rather than a
        token, so "no digest means the key is the token" is only sound for an entry
        that predates the change entirely. An entry carrying one of the two fields
        is a post-H497 entry with a broken digest: it is dropped, exactly as
        ``_load_code`` drops a half-written code digest. Re-migrating it would hash
        its id and hand the id — which is printed in the file — the power to pair,
        putting a usable credential back in the clear.
        """
        if not isinstance(stored, Mapping):
            return {}
        links: dict = {}
        for key, raw_entry in stored.items():
            if not isinstance(raw_entry, Mapping):
                continue
            entry = dict(raw_entry)
            salt, digest = entry.get("salt"), entry.get("hash")
            if isinstance(salt, str) and isinstance(digest, str) and salt and digest:
                links[str(key)] = entry
                continue
            if "salt" in entry or "hash" in entry:
                continue  # a digest that can never match is no link (see above)
            entry.update(_hash_secret(str(key)))
            links[_fresh_link_id(links)] = entry
            self._migrated = True
        return links

    # ── pairing code (optional self-service) ──────────────────────────────────

    def set_code(self, code: Optional[str]) -> None:
        """Set/rotate the pairing code; ``None``/empty clears it (no self-pair).

        Only a salted digest is kept, in memory and on disk (H497). The code the
        owner typed is never written down, so whoever reads the store file cannot
        pair with what they find — and clearing the code clears the digest too.
        """
        cleaned = (code or "").strip() or None
        self._code_hash = _hash_code(cleaned) if cleaned else None
        with self._lock:
            self._save()

    def has_code(self) -> bool:
        return self._code_hash is not None

    def _code_matches(self, code: Optional[str]) -> bool:
        """Verify the pairing code, upgrading an unstretched record as it goes.

        A successful match is the only moment the plaintext is in hand, so it is
        the only moment a record hashed by the first cut of this slice — or under
        a lower round count — can be rewritten. A failed match leaves the record
        exactly as it was: nothing about the stored form may depend on what a
        stranger guessed.
        """
        if not self._code_hash or not code:
            return False
        candidate = str(code).strip()
        if not _code_record_matches(self._code_hash, candidate):
            return False
        if _code_needs_upgrade(self._code_hash):
            self._code_hash = _hash_code(candidate)
            with self._lock:
                self._save()
        return True

    # ── state queries ─────────────────────────────────────────────────────────

    def status(self, channel: str, sender_id: str) -> str:
        rec = self._senders.get(_key(channel, sender_id))
        return rec["status"] if rec else UNKNOWN

    def is_allowed(self, channel: str, sender_id: str) -> bool:
        """Gate used by channels/gateway. When pairing is disabled, allow all.

        The channel's allowlist (the owner's own ids) passes too, without a pairing
        record — see ``sender_allowlisted``. (Hermes absorption 5b)
        """
        if not pairing_enabled():
            return True
        if sender_allowlisted(channel, sender_id):
            return True
        return self.status(channel, sender_id) == ALLOWED

    # ── inbound first-contact ─────────────────────────────────────────────────

    def _record_attempt(self, key: str) -> int:
        now = time.time()
        hits = [t for t in self._attempts.get(key, []) if now - t < _ATTEMPT_WINDOW]
        hits.append(now)
        self._attempts[key] = hits
        # Garbage-collect dead keys: sender ids are attacker-chosen on webhook
        # channels, so without this the anti-flood map (and its JSON file) grows
        # one entry per fake sender forever — the anti-abuse layer becomes the
        # abuse vector. Sweep stale/empty keys once the map gets large.
        if len(self._attempts) > 1000:
            self._attempts = {
                k: fresh
                for k, v in self._attempts.items()
                if (fresh := [t for t in v if now - t < _ATTEMPT_WINDOW])
            }
        return len(hits)

    def _set(self, channel: str, sender_id: str, status: str, name: str = "") -> dict:
        key = _key(channel, sender_id)
        existing = self._senders.get(key, {})
        rec = {
            "channel": channel,
            "sender_id": sender_id,
            "name": name or existing.get("name", "") or sender_id,
            "status": status,
            "created_at": existing.get("created_at", time.time()),
            "updated_at": time.time(),
        }
        self._senders[key] = rec
        return rec

    def request(self, channel: str, sender_id: str, code: Optional[str] = None,
                name: str = "") -> dict:
        """Inbound first-contact from a sender. Records intent; NEVER executes.

        Returns ``{"status": …, "allowed": bool}``. A blocked sender or an
        already-allowed sender short-circuits. A correct code auto-approves;
        otherwise a (bounded, rate-limited) pending request is created.
        """
        if not channel or not sender_id:
            raise ValueError("channel and sender_id are required")
        key = _key(channel, sender_id)
        current = self.status(channel, sender_id)

        if current == BLOCKED:
            return {"status": BLOCKED, "allowed": False}
        if current == ALLOWED:
            return {"status": ALLOWED, "allowed": True}

        # Rate-limit pairing attempts (anti-abuse) — applies to unknown/pending.
        attempts = self._record_attempt(key)
        if attempts > _MAX_ATTEMPTS:
            with self._lock:
                self._save()
            return {"status": "rate_limited", "allowed": False}

        # A presented code is checked against a store-wide guess budget first: the
        # per-sender bucket above is keyed on an id the caller chose, so it would let
        # a guesser rotate ids and try the code five times per fresh id forever. Once
        # the budget is spent, code checks stop for the window and the sender is held
        # like anyone else — the owner can still approve them by hand.
        if code and self._code_hash and self._code_guess_budget_spent():
            with self._lock:
                self._save()
            return {"status": "rate_limited", "allowed": False}
        # A correct code is self-service approval (no owner tap needed).
        if self._code_matches(code):
            self._set(channel, sender_id, ALLOWED, name)
            with self._lock:
                self._save()
            return {"status": ALLOWED, "allowed": True, "paired_by": "code"}

        # Otherwise hold for owner approval (idempotent; bounded inbox).
        if current != PENDING:
            self._evict_if_full()
            self._set(channel, sender_id, PENDING, name)
        with self._lock:
            self._save()
        return {"status": PENDING, "allowed": False}

    def _code_guess_budget_spent(self) -> bool:
        """Record one code guess; True when the store-wide window is already full.

        Every presented code counts, right or wrong: deciding *after* the compare
        would tell a guesser something about the compare. (Hermes absorption 5b)
        """
        now = time.time()
        fresh = [t for t in self._code_guesses if now - t < _ATTEMPT_WINDOW]
        if len(fresh) >= _MAX_CODE_GUESSES_PER_WINDOW:
            self._code_guesses = fresh
            return True
        fresh.append(now)
        self._code_guesses = fresh
        return False

    def _evict_if_full(self) -> None:
        pend = [(k, r) for k, r in self._senders.items() if r.get("status") == PENDING]
        if len(pend) >= _MAX_PENDING:
            pend.sort(key=lambda kv: kv[1].get("created_at", 0))
            for k, _ in pend[: len(pend) - _MAX_PENDING + 1]:
                del self._senders[k]

    # ── owner decisions ───────────────────────────────────────────────────────

    def approve(self, channel: str, sender_id: str, name: str = "") -> dict:
        """Approve a sender — now allowed through. (Owner action.)"""
        rec = self._set(channel, sender_id, ALLOWED, name)
        with self._lock:
            self._save()
        return rec

    def reject(self, channel: str, sender_id: str) -> bool:
        """Drop a pending request without blocking (sender may try again)."""
        key = _key(channel, sender_id)
        if self._senders.get(key, {}).get("status") == PENDING:
            del self._senders[key]
            with self._lock:
                self._save()
            return True
        return False

    def block(self, channel: str, sender_id: str, name: str = "") -> dict:
        """Block a sender — future contact is dropped silently. (Owner action.)"""
        rec = self._set(channel, sender_id, BLOCKED, name)
        with self._lock:
            self._save()
        return rec

    def unpair(self, channel: str, sender_id: str) -> bool:
        """Revoke any state for a sender (approved or blocked → unknown)."""
        key = _key(channel, sender_id)
        if key in self._senders:
            del self._senders[key]
            with self._lock:
                self._save()
            return True
        return False

    def decide(self, channel: str, sender_id: str, action: str, name: str = "") -> dict:
        """Convenience dispatcher for the management endpoint."""
        action = (action or "").lower()
        if action == "approve":
            return self.approve(channel, sender_id, name)
        if action == "block":
            return self.block(channel, sender_id, name)
        if action == "reject":
            return {"rejected": self.reject(channel, sender_id)}
        if action == "unpair":
            return {"unpaired": self.unpair(channel, sender_id)}
        raise ValueError(f"unknown action: {action}")

    # ── listing ───────────────────────────────────────────────────────────────

    def list_senders(self, status: Optional[str] = None) -> list[dict]:
        items = [dict(r) for r in self._senders.values()
                 if status is None or r.get("status") == status]
        return sorted(items, key=lambda r: r.get("updated_at", 0), reverse=True)

    def summary(self) -> dict:
        counts = {ALLOWED: 0, PENDING: 0, BLOCKED: 0}
        for r in self._senders.values():
            counts[r.get("status")] = counts.get(r.get("status"), 0) + 1
        return {"enabled": pairing_enabled(), "has_code": self.has_code(),
                "deeplinks_outstanding": self.outstanding_deeplinks(), **counts}

    # ── deeplink pairing (the 60-second path) ─────────────────────────────────

    def mint_deeplink(
        self, channel: str = "telegram", *, now: Optional[float] = None,
        ttl: float = DEEPLINK_TTL_SECONDS,
    ) -> dict:
        """Mint one single-use pairing token. The caller builds the URL.

        Returns ``{"token", "channel", "expires_at", "ttl"}``. The token is the
        credential: it is returned exactly once, to an admin-guarded caller, and
        the store keeps only what it needs to redeem it — which since H497 is a
        salted digest under an opaque id, never the token itself.
        """
        moment = time.time() if now is None else float(now)
        token = secrets.token_urlsafe(_DEEPLINK_BYTES)
        with self._lock:
            self._expire_deeplinks(moment)
            if len(self._deeplinks) >= _MAX_DEEPLINKS:
                # Drop the oldest rather than refusing: minting is the owner's
                # deliberate act, and a full table is a stale table.
                oldest = min(
                    self._deeplinks,
                    key=lambda k: float(self._deeplinks[k].get("created_at", 0.0)),
                )
                self._deeplinks.pop(oldest, None)
            self._deeplinks[_fresh_link_id(self._deeplinks)] = {
                "channel": str(channel or "telegram"),
                "hub": _install_id(),          # H689: redeemable only on this install
                "created_at": moment,
                "expires_at": moment + max(1.0, float(ttl)),
                **_hash_secret(token),
            }
            self._save()
        return {
            "token": token,
            "channel": channel,
            "expires_at": moment + max(1.0, float(ttl)),
            "ttl": max(1.0, float(ttl)),
        }

    def redeem_deeplink(
        self, token: Optional[str], channel: str, sender_id: str, *,
        name: str = "", now: Optional[float] = None,
    ) -> dict:
        """Spend a deeplink token and approve this sender. One use, ever.

        The token is hashed and compared in constant time against each outstanding
        entry's digest (H497) and the entry is removed the moment it matches —
        before the sender is approved — so two redemptions racing each other
        resolve to exactly one winner. A token for a different channel is refused
        rather than honoured: a link minted for Telegram must not pair a Discord
        account.
        """
        candidate = str(token or "").strip()
        moment = time.time() if now is None else float(now)
        if not candidate:
            return {"ok": False, "reason": "no_token"}
        with self._lock:
            self._expire_deeplinks(moment)
            matched = None
            for link_id, stored in list(self._deeplinks.items()):
                if _secret_matches(stored, candidate):
                    matched = link_id
                    break
            if matched is None:
                # Wrong, already spent, or expired all look the same from outside,
                # on purpose: distinguishing them tells a guesser which it was.
                return {"ok": False, "reason": "invalid_or_expired_token"}
            entry = self._deeplinks.pop(matched)
            self._save()
        if entry.get("channel") and entry["channel"] != channel:
            return {"ok": False, "reason": "wrong_channel"}
        if entry.get("hub") and entry["hub"] != _install_id():
            return {"ok": False, "reason": "other_install"}
        record = self.approve(channel, sender_id, name=name)
        return {"ok": True, "status": ALLOWED, "channel": channel,
                "sender_id": sender_id, "record": record}

    def _expire_deeplinks(self, now: float) -> int:
        """Drop expired tokens. Caller holds the lock."""
        dead = [t for t, e in self._deeplinks.items() if float(e.get("expires_at", 0)) <= now]
        for token in dead:
            self._deeplinks.pop(token, None)
        return len(dead)

    def outstanding_deeplinks(self, *, now: Optional[float] = None) -> int:
        """How many links are live. The tokens themselves are never returned."""
        moment = time.time() if now is None else float(now)
        return sum(
            1 for e in self._deeplinks.values()
            if float(e.get("expires_at", 0)) > moment
        )

    def revoke_deeplinks(self) -> int:
        """Invalidate every outstanding link. Returns how many were dropped."""
        with self._lock:
            count = len(self._deeplinks)
            self._deeplinks = {}
            self._save()
        return count

    # ── gateway helper ────────────────────────────────────────────────────────

    def gate_inbound(self, channel: str, sender_id: str, code: Optional[str] = None,
                     name: str = "") -> dict:
        """Resolve an inbound message into an allow/hold decision for the gateway.

        Disabled, an allowlisted sender (the owner's own id, see
        ``sender_allowlisted``) or a known-allowed sender → ``allowed=True`` (route
        normally). Otherwise record the attempt and return a friendly hold message.
        """
        if not pairing_enabled() or self.status(channel, sender_id) == ALLOWED:
            return {"allowed": True, "status": ALLOWED if sender_id else UNKNOWN}
        if sender_id and sender_allowlisted(channel, sender_id):
            return {"allowed": True, "status": ALLOWED, "allowlisted": True}
        result = self.request(channel, sender_id, code=code, name=name)
        if result["allowed"]:
            return result
        msgs = {
            BLOCKED: "",  # blocked senders get no reply (silent drop)
            PENDING: "Thanks — your message is awaiting approval by the owner.",
            "rate_limited": "Too many attempts. Please wait before trying again.",
        }
        result["message"] = msgs.get(result["status"], "")
        return result
