# H487 consent revocation and owner integration plan

Goal: full local functional parity for all 697 accepted Hermes capabilities.
Generated 2026-10-03; base/head `bd38d00c816a9c2072892bba4040ce0d4ac9464c`.
Spec: [reusable consent](h487-reusable-consent-design-2026-10-03.md) and
[live producer](h487-consent-producer-plan-2026-10-03.md).
Owner-authorized local engineering; no push, merge, deploy or runtime activation.

## Verified architecture and chosen contract

The adjacent ConsentLedger stores signed grants/decision tombstones but permits
restoring a former valid grant together with its former active decision. The
existing B7 MonotonicHeadAnchor is an injected trusted external latest-head CAS;
its file backend is outside autonomy.db and advances before the SQLite commit.
Reuse the adapter/value shape with a distinct consent purpose and separate file.
Do not share the B7 anchor or weaken its policy/receipt/claim logic.

Add optional `head_anchor: MonotonicHeadAnchor | None = None` to ConsentLedger.
None retains the existing evidence-only storage contract for callers/tests;
future production reusable-consent consumers must require an anchored ledger.
Anchored initialize/grant/revoke/lookup bind a signed versioned local head to a
deterministic digest of every decision/grant row, including signed payloads and
row identities. Merely restoring old signed rows must not match the current head.
The head's revision increments on each successful grant/revocation; it is carried
as MediationHead(version=1,last_sequence=revision,last_event_hash=manifest_digest,
event_count=revision,signature=head_signature), with a distinct signed purpose.

Anchored initialization may bootstrap only a genuinely empty consent store with
no previous state, and a successful external compare-and-swap from None. Never
adopt/re-sign old unanchored authority automatically. Existing nonempty, missing,
corrupt, mismatched or unreadable anchored state grants no lookup authority and
cannot advance new grants. All writes retain caller transaction/savepoint
ownership. Read the anchored state and grant evidence in one consistent SQLite
snapshot. Before releasing successful grant/revoke savepoints, sign the new
manifest/head and advance the external CAS from the verified prior head. CAS or
signing failures roll back the local mutation. SQLite/caller rollback after a
successful external advance conservatively invalidates consent, rather than
restoring revoked authority. Do not silently repair that mismatch; ordinary
explicit task approvals remain available and operator recovery is separate.

## Single writers and fixed interfaces

Writer A, gpt-6-sol High, owns only `agents/core/autonomy/consent_ledger.py` and
`tests/test_h487_consent_ledger.py`. Preserve the public existing APIs and add the
optional constructor anchor. Add only a private own-table `h487_consent_state`.
Use existing DetachedHMACSigner, MediationHead and MonotonicHeadAnchor; the new
head's signed purpose/version must differ from grant/decision and B7 state.
No owner decisions, queue transitions, executor rights or factory wiring here.

Writer B, gpt-6-sol High, owns only new
`agents/core/autonomy/consent_head_store.py` and
`tests/test_h487_consent_head_store.py`.
`make_consent_head_anchor(path: str | Path | None = None) -> MonotonicHeadAnchor`
returns a durable locked monotonic CAS backend. Default path is lazily resolved
`data_path('security', 'h487_consent_head.json')`; explicit paths are trusted
internal/test inputs. Keep the B7 file untouched. Reuse existing file-head shape
and fsync/replace/file-lock conventions. Missing is bootstrap-eligible only under
the caller's fresh-empty-ledger rule; an existing malformed/unreadable file must
never be treated as absent for CAS from None. Reject stale/current revisions,
failed durability, schema errors and callback exceptions. No installed service,
hooks, global flags, key handling, production activation or other-module edits.

Coordinator owns integration/review, new actual-file/ledger integration tests,
then real owner/queue/dispatch work. An anchored primitive alone is not H487.

## Verification steps

- [ ] A proves RED for rollback of old signed grants+decisions and full-DB restore
  while the external head remains newer; then implements anchored checks.
- [ ] A proves empty bootstrap/reopen, row/head substitution, CAS/signing failure,
  catalog AND/session/content constraints, outer rollback without caller commit,
  and no implicit migration/adoption of existing unanchored grants.
- [ ] B proves RED for the absent factory, then actual temp-file persistence,
  default path isolation, two handles/stale CAS, corrupt/unreadable preexisting
  file refusing bootstrap, durable-write failure and independent B7/consent paths.
- [ ] Coordinator integrates both using actual synthetic SQLite snapshots and
  a real separate temp-file anchor, inspects all source, runs guarded regressions,
  scoped scans, fresh Graft and truthful records. Full-suite milestone serially.
- [ ] Connect real owner choices and exact pending followers atomically, with
  each task's own mediated receipt and no new fabricated human attribution.
- [ ] Revalidate registration/policy/target/category and current anchored grant
  at the physical dispatch boundary; retain Smart DENY once/reject, e-stop,
  hardline, taint, budget and kernel floors. Then HTTP/HUD/Telegram/other producers.

Threat scope: the external file protects against consent DB/row rollback, not
rollback of the entire runtime directory or compromise of signer/CAS callbacks.
Deleting the external file with a populated local store fails closed. A crash
after external advance and before SQLite commit sacrifices reusable-consent
availability; it never restores older permission. This must be explicit in the
handover until a reviewed operator recovery path exists.

## Full-backend follow-up at c70e0407

The guarded run executed all 22,093 cases and found one failure: the exact
external-binding writer inventory still lists the coordinator's pre-provenance
line numbers. The focused test reproduces it. AST inspection reports no parse
errors, additions, removals, changed ownership or columns: exactly 14 existing
coordinator callsites moved forward by seven lines. Hypothesis: the seven
terminal-provenance lines added in bd38d00c were not reflected in the literal
inventory. Update only those 14 line coordinates in
`agents/core/orchestrator_bindings.py`; preserve every writer/name/path/column,
the exact AST equality test and alias/undeclared-writer guards. Run the whole
binding test module, then repeat the serial guarded backend on the new frozen
checkpoint. Do not describe the first run as passing or new CI evidence.

Rollback: revert localized consent modules/tests and this continuation. Preserve
existing task/chat/approval records and the separate B7 anchor. New head/state
remain inert without production consumers. No equivalence credit until required
owner/queue/dispatch/channel behavior is implemented and verified.
