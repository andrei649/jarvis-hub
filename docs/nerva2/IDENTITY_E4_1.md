# E4.1 — The Identity Manifest (#1008)

> **Status:** delivered, not program-accepted. The code and its acceptance test ship
> here; the E4 program gate stays open until a reviewer distinct from the builder
> attests it.
> **Authority:** `identity_record_only`. Nothing in this contract can act, and nothing
> can authorise. It records what Nerva claims about itself.

## Why this exists at all

Every other governed thing in the codebase is a **capability** — something Nerva may
or may not do to the world. This is the one record about **Nerva itself**: its name,
purpose, values, stance on truthfulness, boundaries, stable traits, the roles it holds
toward the people it works with, and the commitments it has made.

It needs governance for a reason that has nothing to do with capability:

> A system that can silently rewrite what it says its boundaries are **has no
> boundaries** — it has a *current opinion* about them, and an opinion is not something
> anyone can rely on.

That is the whole argument. Everything below is machinery in service of one sentence,
which is E4.1 **criterion 10**:

> **No identity change becomes authoritative without a versioned proposal and a human
> decision.**

`tests/test_identity_manifest.py::test_no_identity_change_becomes_authoritative_without_a_proposal_and_a_person`
is that sentence, executable.

## What the record contains

`nerva.identity.v1`, in `agents/core/identity_manifest.py`:

| Field | Kind | Required |
|---|---|---|
| `name` | text | yes |
| `purpose` | text | yes |
| `truthfulness` | text | yes |
| `values` | list | **at least one** |
| `boundaries` | list | no |
| `traits` | list | no |
| `roles` | list | no |
| `commitments` | list | no |

`values` is required because a manifest without one is a name and a job title. It is
the field that makes this an *identity* rather than a label.

## How a change happens

```
propose_change(store, manifest, enqueue=…)     # writes an ASK task, changes NOTHING
        ↓  … the decision inbox, like every other privileged act …
apply_change(store, task)                      # only from a HUMAN accept or edit
        ↓
store.adopt(…)                                 # a NEW version, appended
```

Each refusal in `apply_change` is one way the sentence above could quietly stop being
true:

| Refusal | What it prevents |
|---|---|
| `not_decided_by_a_person` | a policy / worker / scheduler decision adopting an identity. Same `MACHINE_DECIDERS` set, spelled the same way, as `permission_ledger`, `goal_contract` and `first_action` |
| `not_accepted` | a reject or a defer being read as approval. `approve` is deliberately **not** in the human set — the inbox's verbs are `accept` and `edit`, and a second looser vocabulary here would weaken the most sensitive record in the product |
| `fingerprint_mismatch` | content edited between the card and the adoption, so the approval was given for a different identity |
| `stale_proposal` | applying over someone else's change, silently reverting them |
| `no_change` (at propose time) | a card that asks the owner to approve nothing, which teaches them to approve without reading |

## The version chain

Versions are append-only, hash-chained, and HMAC-signed with the transparency anchor's
key when one exists. A chain does **not prevent** an edit — nobody can stop someone
with disk access — it makes an edit **visible**, which is the guarantee that can
actually be kept. `verify()` reports the first break and, separately, whether the store
is signed at all: "verified" from an unsigned store would be a stronger claim than the
data supports.

**Rollback is a new version, never a deletion.** Rolling back to version 2 writes
version 5 whose content matches version 2 and whose record says `rolled_back_to: 2`.
Deleting versions 3 and 4 would erase the fact that they were ever adopted — which is
precisely what someone quietly rewriting an identity would want.

## The one-time import

`migrate_from_soul` reads a SOUL file's front matter and produces **version 1**. It is
idempotent: a second run returns `None` rather than adopting again, because an import
that looked like a decision is exactly what this module exists to prevent.

Anything it cannot read becomes a **recorded limitation** on version 1 — an unmapped
key, an unparseable line, a required field the source did not have (which becomes an
explicit `(not imported: …)` placeholder). A manifest that invented a purpose would be
worse than one that admits it does not have one yet.

## Lifecycle

* **Forget** erases it. The purge is KEEP-inverted, and `identity/` is not on the keep
  list — so a forget resets the identity record and the next boot re-imports from SOUL.
  That is the right default: `roles` and `commitments` can name the owner, and a forget
  is the owner erasing themselves.
* **Export** includes it (`data_export.EXPORT_JSON`). It is not owner content in the
  usual sense, but its `commitments` are promises made *to* the owner, and an export
  that omitted them would omit the half of the record that is about them.

## What is deliberately absent

* **No route and no panel.** A surface for editing an identity would be a second path
  to the thing that must only ever have one, and this slice stays route-free on
  purpose. A read-only view is a later, separate decision.
* **No `can_*` that is ever True.** `authority`, `can_act`, `can_authorise` and
  `can_self_amend` are asserted by test. A document describing an identity must not
  become one granting permissions, and that is exactly one careless field away.
* **This is not Howard's persona system.** That is prompt material for an agent. This
  is the record of the product's own identity, and it is deliberately small.
