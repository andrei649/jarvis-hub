"""E4.1 / #1008 — the record of what Nerva says it is, and who may change it.

Every other governed thing in this codebase is a capability. This is the one
record about Nerva itself, and it needs governance for a reason that has nothing
to do with capability: **a system that can silently rewrite what it says its
boundaries are has no boundaries — it has a current opinion about them**, and an
opinion is not something anyone can rely on.

So the tests are all about the sentence the module exists to make true, which is
E4.1 criterion 10: *no identity change becomes authoritative without a versioned
proposal and a human decision.* Each is one way that sentence could quietly stop
being true:

  · a proposal that changed the current version on its own;
  · a machine decider counting as a person;
  · a payload edited between the card and the adoption;
  · a rollback that deleted the versions it was rolling back past;
  · a chain that still verified after someone edited a version;
  · a migration that ran twice, so an import looked like a decision.

Hermetic: a tmp_path store, an injected key and clock, a fake enqueue.
"""

from __future__ import annotations

import json
import types

import pytest

from agents.core.identity_manifest import (
    AUTHORITY,
    FIELDS,
    KIND,
    MACHINE_DECIDERS,
    SCHEMA,
    IdentityError,
    IdentityManifest,
    IdentityStore,
    apply_change,
    diff_manifests,
    migrate_from_soul,
    parse_soul_front_matter,
    propose_change,
    rollback,
)


def _manifest(**over) -> IdentityManifest:
    base = {
        "name": "Nerva",
        "purpose": "a local-first personal AI that asks before it acts",
        "truthfulness": "says what it does not know, and never invents a source",
        "values": ["the data trains no one", "every fact is inspectable"],
        "boundaries": ["never spends money without an approval"],
    }
    base.update(over)
    return IdentityManifest.from_dict(base)


@pytest.fixture
def store(tmp_path):
    return IdentityStore(tmp_path / "manifest.json", secret=b"test-key")


@pytest.fixture
def seeded(store):
    store.adopt(_manifest(), adopted_by="accept:owner", now=1_000.0)
    return store


class _Inbox:
    def __init__(self):
        self.tasks: list[dict] = []

    def __call__(self, **kwargs):
        self.tasks.append(kwargs)
        return len(self.tasks)


def _task(payload, *, decided_by="owner", decision="accept"):
    return types.SimpleNamespace(
        id=1, kind=KIND, payload=payload, decided_by=decided_by, decision=decision
    )


# ── criterion 10, stated as one test ─────────────────────────────────────────

def test_no_identity_change_becomes_authoritative_without_a_proposal_and_a_person(seeded):
    """E4.1 criterion 10, as a single assertion about the whole path.

    Proposing does not change anything; only a task a human accepted does; and
    what lands is a new VERSION rather than an overwrite.
    """
    inbox = _Inbox()
    proposed = _manifest(purpose="something else entirely")

    result = propose_change(seeded, proposed, enqueue=inbox)
    assert seeded.current().purpose != "something else entirely"   # nothing changed
    assert seeded.current_version == 1

    task = inbox.tasks[0]
    assert task["autonomy_level"] == "ask"          # it went to the decision inbox
    assert task["kind"] == KIND

    version = apply_change(seeded, _task(task["payload"]))
    assert version.version == 2                     # a new version, not an overwrite
    assert seeded.current().purpose == "something else entirely"
    assert seeded.version(1).manifest.purpose != "something else entirely"
    assert result["task_id"] == 1


# ── a proposal is not a change ───────────────────────────────────────────────

def test_proposing_leaves_the_current_version_untouched(seeded):
    before = seeded.current().as_dict()
    propose_change(seeded, _manifest(name="Somebody Else"), enqueue=_Inbox())
    assert seeded.current().as_dict() == before
    assert seeded.current_version == 1


def test_the_card_carries_a_field_by_field_diff(seeded):
    """A card that said "the identity changed" and no more is one nobody can
    decide on."""
    inbox = _Inbox()
    propose_change(seeded, _manifest(name="Nerva II", values=["a new value"]), enqueue=inbox)
    changes = inbox.tasks[0]["payload"]["changes"]
    assert set(changes) == {"name", "values"}
    assert changes["name"] == {"from": "Nerva", "to": "Nerva II"}


def test_a_proposal_that_changes_nothing_is_refused(seeded):
    """A card asking the owner to approve nothing teaches them to approve without
    reading, which makes every other card weaker."""
    with pytest.raises(IdentityError) as exc:
        propose_change(seeded, seeded.current(), enqueue=_Inbox())
    assert exc.value.reason == "no_change"


def test_the_first_identity_is_still_a_proposal(store):
    """There is no "bootstrap" path that skips the decision for version 1."""
    inbox = _Inbox()
    propose_change(store, _manifest(), enqueue=inbox)
    assert store.current_version == 0
    assert inbox.tasks[0]["payload"]["from_version"] == 0


# ── only a person ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("decider", sorted(MACHINE_DECIDERS))
def test_a_machine_decision_can_never_adopt_an_identity(seeded, decider):
    inbox = _Inbox()
    propose_change(seeded, _manifest(name="Autonomous"), enqueue=inbox)
    with pytest.raises(IdentityError) as exc:
        apply_change(seeded, _task(inbox.tasks[0]["payload"], decided_by=decider))
    assert exc.value.reason == "not_decided_by_a_person"
    assert seeded.current_version == 1


@pytest.mark.parametrize("decision", ["reject", "defer", "", "maybe", "approve"])
def test_only_an_accept_or_an_edit_adopts(seeded, decision):
    """"approve" is deliberately NOT in the set: the inbox's human verbs are
    accept and edit, and quietly widening the set here would be a second, looser
    approval vocabulary for the most sensitive record in the product."""
    inbox = _Inbox()
    propose_change(seeded, _manifest(name="Whoever"), enqueue=inbox)
    with pytest.raises(IdentityError) as exc:
        apply_change(seeded, _task(inbox.tasks[0]["payload"], decision=decision))
    assert exc.value.reason == "not_accepted"


def test_an_edit_counts_because_it_is_still_a_person_deciding(seeded):
    inbox = _Inbox()
    propose_change(seeded, _manifest(name="Edited"), enqueue=inbox)
    version = apply_change(seeded, _task(inbox.tasks[0]["payload"], decision="edit"))
    assert version.adopted_by == "edit:owner"


# ── the payload cannot change between the card and the adoption ──────────────

def test_an_edited_payload_cannot_ride_the_approval_given_for_another(seeded):
    """The approval that was given was for a different identity than this one."""
    inbox = _Inbox()
    propose_change(seeded, _manifest(name="Shown on the card"), enqueue=inbox)
    payload = dict(inbox.tasks[0]["payload"])
    payload["manifest"] = {**payload["manifest"], "name": "Something else"}
    with pytest.raises(IdentityError) as exc:
        apply_change(seeded, _task(payload))
    assert exc.value.reason == "fingerprint_mismatch"
    assert seeded.current().name == "Nerva"


def test_a_proposal_against_a_superseded_version_is_refused(seeded):
    """Someone else changed the identity in between; applying this would silently
    revert them."""
    inbox = _Inbox()
    propose_change(seeded, _manifest(name="First proposal"), enqueue=inbox)
    seeded.adopt(_manifest(name="Adopted in between"), adopted_by="accept:owner", now=2_000.0)
    with pytest.raises(IdentityError) as exc:
        apply_change(seeded, _task(inbox.tasks[0]["payload"]))
    assert exc.value.reason == "stale_proposal"


def test_a_payload_from_another_schema_is_refused(seeded):
    with pytest.raises(IdentityError) as exc:
        apply_change(seeded, _task({"schema": "something.else"}))
    assert exc.value.reason == "unknown_schema"


def test_a_json_string_payload_is_accepted_because_the_queue_stores_it_that_way(seeded):
    inbox = _Inbox()
    propose_change(seeded, _manifest(name="Serialised"), enqueue=inbox)
    version = apply_change(seeded, _task(json.dumps(inbox.tasks[0]["payload"])))
    assert version.manifest.name == "Serialised"


def test_an_unparseable_payload_is_refused_not_ignored(seeded):
    with pytest.raises(IdentityError) as exc:
        apply_change(seeded, _task("{not json"))
    assert exc.value.reason == "invalid_payload"


# ── the chain ────────────────────────────────────────────────────────────────

def test_a_fresh_chain_verifies(seeded):
    assert seeded.verify() == {"ok": True, "signed": True, "versions": 1}


def test_an_edited_version_breaks_the_chain(tmp_path):
    """A chain does not PREVENT an edit — nobody can stop someone with disk
    access. It makes the edit visible, which is the guarantee that can be kept."""
    path = tmp_path / "manifest.json"
    store = IdentityStore(path, secret=b"k")
    store.adopt(_manifest(), adopted_by="accept:owner", now=1.0)
    store.adopt(_manifest(name="Two"), adopted_by="accept:owner", now=2.0)

    stored = json.loads(path.read_text())
    stored["versions"][0]["manifest"]["purpose"] = "quietly rewritten"
    path.write_text(json.dumps(stored))

    verdict = IdentityStore(path, secret=b"k").verify()
    assert verdict["ok"] is False
    assert verdict["broken_at"] == 1


def test_a_forged_signature_is_caught(tmp_path):
    path = tmp_path / "manifest.json"
    store = IdentityStore(path, secret=b"k")
    store.adopt(_manifest(), adopted_by="accept:owner", now=1.0)
    stored = json.loads(path.read_text())
    stored["versions"][0]["signature"] = "0" * 64
    path.write_text(json.dumps(stored))
    assert IdentityStore(path, secret=b"k").verify()["reason"] == "signature_mismatch"


def test_an_unsigned_store_says_so_rather_than_claiming_more(tmp_path):
    """"Verified" from an unsigned store would be a stronger claim than the data
    supports, so `signed` travels with the verdict."""
    store = IdentityStore(tmp_path / "m.json", secret=b"")
    store.adopt(_manifest(), adopted_by="accept:owner", now=1.0)
    verdict = store.verify()
    assert verdict["ok"] is True
    assert verdict["signed"] is False


def test_the_chain_survives_a_restart(tmp_path):
    path = tmp_path / "m.json"
    first = IdentityStore(path, secret=b"k")
    first.adopt(_manifest(), adopted_by="accept:owner", now=1.0)
    first.adopt(_manifest(name="Two"), adopted_by="accept:owner", now=2.0)
    reopened = IdentityStore(path, secret=b"k")
    assert reopened.current_version == 2
    assert reopened.verify()["ok"] is True


# ── rollback is a new version ────────────────────────────────────────────────

def test_a_rollback_writes_a_new_version_rather_than_deleting(seeded):
    """Deleting the versions rolled past would erase the fact that they were ever
    adopted — exactly what someone quietly rewriting an identity would want."""
    seeded.adopt(_manifest(name="Two"), adopted_by="accept:owner", now=2.0)
    seeded.adopt(_manifest(name="Three"), adopted_by="accept:owner", now=3.0)

    version = rollback(seeded, 1, adopted_by="accept:owner", now=4.0)
    assert version.version == 4
    assert version.rolled_back_to == 1
    assert seeded.current().name == "Nerva"
    # and versions 2 and 3 are still there, still readable
    assert [v.version for v in seeded.versions()] == [1, 2, 3, 4]
    assert seeded.version(3).manifest.name == "Three"


def test_a_rollback_keeps_the_chain_verifiable(seeded):
    seeded.adopt(_manifest(name="Two"), adopted_by="accept:owner", now=2.0)
    rollback(seeded, 1, adopted_by="accept:owner", now=3.0)
    assert seeded.verify()["ok"] is True


def test_rolling_back_to_a_version_that_does_not_exist_is_refused(seeded):
    with pytest.raises(IdentityError) as exc:
        rollback(seeded, 99, adopted_by="accept:owner")
    assert exc.value.reason == "unknown_version"


def test_rolling_back_to_the_current_version_is_refused(seeded):
    """It would append a version identical to the one before it and call that a
    rollback, which is a record of a decision nobody made."""
    with pytest.raises(IdentityError) as exc:
        rollback(seeded, 1, adopted_by="accept:owner")
    assert exc.value.reason == "already_current"


# ── the record is never an authority ─────────────────────────────────────────

def test_the_manifest_cannot_act_or_authorise():
    """A document describing an identity must not become one granting
    permissions, and that is exactly one careless field away."""
    manifest = _manifest()
    assert manifest.authority == AUTHORITY == "identity_record_only"
    assert manifest.can_act is False
    assert manifest.can_authorise is False
    assert manifest.can_self_amend is False


def test_the_stored_file_records_the_authority(seeded, tmp_path):
    stored = json.loads(seeded.path.read_text())
    assert stored["authority"] == "identity_record_only"
    assert stored["schema"] == SCHEMA


# ── what an identity has to say ──────────────────────────────────────────────

@pytest.mark.parametrize("missing", ["name", "purpose", "truthfulness"])
def test_a_manifest_without_its_required_fields_is_refused(missing):
    payload = _manifest().as_dict()
    payload[missing] = ""
    with pytest.raises(IdentityError) as exc:
        IdentityManifest.from_dict(payload)
    assert exc.value.reason == "field_required"


def test_a_manifest_with_no_values_is_a_name_and_a_job_title():
    payload = _manifest().as_dict()
    payload["values"] = []
    with pytest.raises(IdentityError) as exc:
        IdentityManifest.from_dict(payload)
    assert exc.value.reason == "values_required"


def test_a_list_field_given_a_string_is_refused_not_split():
    """Splitting "honest, careful" into two values would invent a value nobody
    wrote."""
    payload = _manifest().as_dict()
    payload["values"] = "honest, careful"
    with pytest.raises(IdentityError) as exc:
        IdentityManifest.from_dict(payload)
    assert exc.value.reason == "field_not_a_list"


def test_duplicate_entries_collapse_rather_than_inflating_a_list():
    manifest = _manifest(values=["one", "one", "two"])
    assert manifest.values == ("one", "two")


def test_a_diff_against_nothing_reports_every_field():
    changes = diff_manifests(None, _manifest())
    assert set(changes) <= set(FIELDS)
    assert "name" in changes and changes["name"]["from"] == ""


# ── the one-time import ──────────────────────────────────────────────────────

SOUL = """---
name: Nerva
purpose: a local-first personal AI
values:
  - asks before it acts
  - the data trains no one
mood: cheerful
---
The prose body is not imported.
"""


def test_a_migration_imports_what_it_can(store):
    version = migrate_from_soul(store, SOUL, now=1.0)
    assert version.version == 1
    assert version.manifest.name == "Nerva"
    assert version.manifest.values == ("asks before it acts", "the data trains no one")


def test_a_migration_records_what_it_could_not_read(store):
    """A value silently dropped because nobody mapped its key is a value the
    identity claims it never had."""
    version = migrate_from_soul(store, SOUL, now=1.0)
    assert any("mood" in note for note in version.limitations)


def test_a_missing_field_becomes_a_placeholder_that_says_so(store):
    """A manifest that invented a purpose is worse than one admitting it does not
    have one yet."""
    version = migrate_from_soul(store, SOUL, now=1.0)
    assert "not imported" in version.manifest.truthfulness


def test_a_migration_is_idempotent(store):
    """A second run adopting another version would make an import look like a
    change somebody decided — the one thing this module exists to prevent."""
    assert migrate_from_soul(store, SOUL, now=1.0) is not None
    assert migrate_from_soul(store, SOUL, now=2.0) is None
    assert store.current_version == 1


def test_a_file_with_no_front_matter_records_that_and_imports_nothing_real(store):
    version = migrate_from_soul(store, "just prose, no front matter", now=1.0)
    assert any("no front matter" in note for note in version.limitations)
    assert "not imported" in version.manifest.name


def test_the_parser_reports_a_line_it_could_not_read():
    _fields, limitations = parse_soul_front_matter("---\nthis line has no colon\n---\n")
    assert any("could not read" in note for note in limitations)


def test_the_parser_maps_synonyms_to_one_field():
    fields, _ = parse_soul_front_matter("---\nmission: to help\nprinciples:\n  - be honest\n---\n")
    assert fields["purpose"] == "to help"
    assert fields["values"] == ["be honest"]


# ── bounds ───────────────────────────────────────────────────────────────────

def test_a_list_longer_than_the_bound_is_refused():
    with pytest.raises(IdentityError) as exc:
        IdentityManifest.from_dict({**_manifest().as_dict(), "traits": [f"t{i}" for i in range(100)]})
    assert exc.value.reason == "field_too_long"


def test_the_history_is_bounded(tmp_path, monkeypatch):
    import agents.core.identity_manifest as mod

    monkeypatch.setattr(mod, "MAX_VERSIONS", 3)
    store = IdentityStore(tmp_path / "m.json", secret=b"k")
    for i in range(3):
        store.adopt(_manifest(name=f"v{i}"), adopted_by="accept:owner", now=float(i))
    with pytest.raises(IdentityError) as exc:
        store.adopt(_manifest(name="one too many"), adopted_by="accept:owner", now=9.0)
    assert exc.value.reason == "too_many_versions"


def test_a_corrupt_store_reads_as_empty_rather_than_raising(tmp_path):
    path = tmp_path / "m.json"
    path.write_text("{not json")
    store = IdentityStore(path, secret=b"k")
    assert store.current_version == 0
    assert store.current() is None


# ── lifecycle: the posture is a decision, not an accident ────────────────────

def test_a_forget_erases_the_identity_record():
    """The purge is KEEP-inverted, so this only holds while `identity` stays off
    the keep list. `roles` and `commitments` can name the owner, and a forget is
    the owner erasing themselves."""
    from agents.core.data_purge import KEEP_DIRS, KEEP_FILES

    assert "identity" not in KEEP_DIRS
    assert "manifest.json" not in KEEP_FILES


def test_an_export_includes_the_identity_and_its_history():
    """Its `commitments` are promises made TO the owner; an export that omitted
    them would omit the half of the record that is about them."""
    from agents.core.data_export import EXPORT_JSON

    assert "identity/manifest.json" in EXPORT_JSON


def test_there_is_no_route_that_edits_an_identity():
    """A surface for editing an identity would be a second path to the thing that
    must only ever have one."""
    import subprocess  # nosec B404 - argv list, no shell
    from pathlib import Path as _P

    repo = _P(__file__).resolve().parent.parent
    hits = subprocess.run(  # nosec B603 - fixed argv, repo-local paths
        ["grep", "-rl", "identity_manifest", str(repo / "agents" / "core" / "routers")],
        capture_output=True, text=True, check=False,
    )
    assert hits.stdout.strip() == ""


def test_the_design_note_ships_with_the_code():
    """A governance contract whose reasoning lives only in a commit message is
    one nobody can review later."""
    from pathlib import Path as _P

    doc = _P(__file__).resolve().parent.parent / "docs/nerva2/IDENTITY_E4_1.md"
    text = doc.read_text(encoding="utf-8")
    assert "criterion 10" in text
    assert "identity_record_only" in text
