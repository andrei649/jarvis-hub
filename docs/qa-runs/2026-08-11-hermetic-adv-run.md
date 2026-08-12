# QA run — hermetic ADV pass (chapter 15 §15.1 + §15.2)

> **Scope:** the two ⭐ no-hardware adversarial-audit cases only — the audit chain (§15.1) and
> forget/erase (§15.2). This is **not** a full `docs/MANUAL_TESTING.md` pass and does **not** clear
> the §0 sign-off or the A1/⭐B0 gate: those require the RTX box, a local model, and the S1–S6
> regressions. This run exists so the two cases that "need no hardware and no keys" (TEST_MANUAL §2.3)
> have a recorded verdict, executed against the tree in a Max run rather than deferred to the box.
> **Agent:** claude-fable-5, Max run «nimble-beacon». **Sandbox:** hermetic CI-topology host, no GPU,
> no cloud keys, no owner data.

- **Build SHA:** `9d0a7c78` (branch `claude/nerva-max-consolidation-4jkuwy`)
- **Python:** 3.11.15 (COMPATIBILITY.md declares a 3.12 floor nothing enforces; noted, not a finding here)
- **Probe tool:** `python scripts/qa_audit_probes.py --json` — **all nine claims CLOSED** on this build.
  The ninth, `reality`/ADV-087, is closed by a **separate successor PR** (the reality-harness fix), so
  the "all nine CLOSED" statement here holds once that successor is on `main`; this evidence document
  itself carries no runtime or security code (owner integrator split of #894).

Verdict vocabulary per §15.0.2. Every case carries the mandatory `CROSS:` line — a probe verdict is a
lead, not a fact, so each verdict below is backed by a second, independent reproduction.

---

## §15.1 — The audit chain (ADV-001 … ADV-014)

### ADV-001 — full-table sha256 downgrade with a key configured
- **Verdict:** **FIXED-SINCE** (audit commit → `9d0a7c78`). My severity: n/a (closed); audit's: High/BLOCKER if open.
- **Reproduction (by hand, `sqlite3` + `hashlib` only, key set):** built a keyed `AuditLogger`,
  logged three events (`verify_chain() == (True, None)`, all rows `hmac-sha256`), then rewrote every
  `content_preview`, recomputed each `row_hash` as plain sha256, re-linked `prev_hash`, set
  `hash_algo='sha256'`, committed, re-opened with a keyed logger:
  ```
  baseline verify_chain: (True, None)  algos: ['hmac-sha256','hmac-sha256','hmac-sha256']
  verify_after_full_downgrade: (False, 1)
  ```
  The forged chain is rejected at row 1 — the FAIL signature in the chapter (`(True, None)` after the
  rewrite) does **not** reproduce.
- **CROSS:** `scripts/qa_audit_probes.py chain` reports **CLOSED**, agreeing with the hand
  reproduction. Two independent sources, same verdict.
- **Why closed:** the AUDIT-1 fix (BACKLOG, 2026): `verify_chain` treats a post-legacy `sha256` row as
  tampering when a key is configured, rather than trusting the row's own `hash_algo`. A legitimate
  legacy sha256 *prefix* still verifies (ADV-005 mixed-algo case), so the fix is scoped correctly, not
  a blanket "reject all sha256".

### ADV-003 / ADV-014 — the regression that must carry the fix
- **Verdict:** **CONFIRMED present.** `tests/test_audit_hardening.py` is green *and* the full-table
  rewrite is now caught (not only the single-row `WHERE id=2` case the audit flagged as too narrow).
  The "green suite + OPEN probe" contradiction the chapter predicts no longer holds here — suite green,
  probe CLOSED, hand-repro closed: three-way agreement.
- **CROSS:** the probe's `chain` verdict + the hand reproduction above.

*ADV-002, 004, 006–013 are downstream of ADV-001: with the full-table forgery rejected at row 1, the
"key never read" escalation (ADV-002) and the `hardened.enforce()`-reports-clean-while-forgeable
concern (ADV-004) are moot on this build. Recorded NOT-REPRODUCIBLE-AS-A-BREAK: the precondition
(a verifying forgery) does not exist. ADV-009/010 (live verify endpoint + route tiers) are owner-host
/ live-app cases — NOT-REPRODUCIBLE in this hermetic sandbox, deferred to the RTX run.*

---

## §15.2 — Forget does not erase (ADV-015 … ADV-024)

### ADV-015 — user-content stores survive a forget (the KEEP-allowlist inversion)
- **Verdict:** **FIXED-SINCE.** My severity: n/a (closed); audit's: High.
- **Reproduction:** `scripts/qa_audit_probes.py purge` seeds **12** user-content stores under a
  throwaway data root, runs a real purge, and re-reads every store:
  ```
  stores_seeded: 12
  still_readable_after_forget: {}          ← nothing seeded survived the purge
  keep_dirs: ["security"]  keep_files: ["marketplace.db","settings.db"]
  ```
  The purge now works from a **KEEP allowlist** (delete-by-default), so a newly-added user store is
  erased unless explicitly kept — the inversion the audit asked for. `security/` (the audit chain
  itself) and non-personal config (`marketplace.db`, `settings.db`) are the only deliberate survivors.
- **CROSS:** probe verdict **CLOSED** + the empty `still_readable_after_forget` map. The probe lists
  stores and re-reads them; it never deletes the real install.
- **Nuance worth carrying (not a finding, a gap-ledger note):** `named_in_export_not_in_purge_dbs:
  ["notes.db"]` — `notes.db` appears in the export manifest but is not among the purge KEEP files,
  which is *correct* (it is purged, delete-by-default), but the export/purge lists are maintained
  separately. A future divergence would be silent. Recommend a test asserting `export_manifest ⊆
  (purged ∪ KEEP)` so the two lists cannot drift apart. Logged as an open gap, not a regression.

*ADV-016–024 (the vector/KG `clear()` dead-code half, the pre-forget archive location/encryption) are
partly backend-dependent (qdrant/neo4j) and partly destructive (§15.2 DESTROYS DATA and needs a
throwaway `JARVIS_HOME`). The file-half is proven CLOSED above; the live vector/KG wipe and the
archive-move are **NOT-REPRODUCIBLE** in this sandbox — deferred to the RTX run with `/tmp/nerva-adv`.*

---

## Summary

| Case | Chapter's expectation (if broken) | This build |
|------|-----------------------------------|-----------|
| ADV-001 audit-chain full-table forgery | verifies `(True, None)` | **FIXED-SINCE** — rejected at row 1 |
| ADV-003/014 regression coverage | green suite hides the break | **CONFIRMED** — suite green *and* break caught |
| ADV-015 forget/erase file-half | 12 stores survive | **FIXED-SINCE** — 0 survive |

Both ⭐ hermetic cases are **closed on this build**, each confirmed by two independent sources
(probe + hand/seeded reproduction). One non-blocking gap logged (export/purge list drift). Nothing
here clears the owner-host A1/⭐B0 gate; the live-endpoint (ADV-009/010) and destructive backend
(ADV-016–024) cases remain **NOT-REPRODUCIBLE** in a hermetic sandbox and are the RTX run's job.
