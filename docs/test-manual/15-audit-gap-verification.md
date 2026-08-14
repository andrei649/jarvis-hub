# 15. Adversarial-audit verification & gap ledger — ID prefix **ADV**

> **Scope.** A third pass, run *in addition to* everything chapters 01–14 already cover and to the two
> live Cowork runs (`docs/qa-runs/`). Those chapters ask *"does the product work and does it tell the
> truth?"*. This one asks a different question: **"is the evidence the product's own status reports
> rest on actually load-bearing — and where is there no code at all?"** Its input is the 2026-07-25
> adversarial audit (26 agents · six lenses · a hostile skeptic against every finding · a completeness
> critic against the whole audit): 18 findings tested, **2 confirmed as written, 10 corrected down to
> PARTIAL, 6 refuted outright, 3 new from the critic**. Every case below re-measures one of those on
> the machine under test and produces a verdict of its own.
>
> **What this chapter is not.** It is not a re-run of chapter 08 (security surface behaviour) or 07
> (governance mechanics) — those test the rails. This tests **the gates that grade the rails**, the
> documented promises the code does not keep, and the surfaces no lens ever touched. Where a case
> overlaps a sibling, it cites it rather than repeating it: audit-tamper drill and auth-tier probes →
> **§08**; approval queue, Decision Inbox, `ungoverned_actions` → **§07**; reality packs as a *gate* →
> **§12**; the H32 acquisition loop as a *workflow* → **§10**; the raw route/tier sweep → **§14**.
>
> **Prereqs.** A build at or past the commit under test with `GET /status` → `ok`; both tokens
> exported (`X-User-Token`, `X-Admin-Token`) or every call made from localhost; `export
> B=http://127.0.0.1:8080`; a Python shell in the repo venv (many cases here are source-level, and
> that is the point — a missing feature has no UI to click). A local model backend for §15.4–15.5. A
> **throwaway data root** for §15.2 (`JARVIS_HOME=/tmp/nerva-adv` or equivalent) — 15.2 is the only
> section that destroys data, and it must never be pointed at the owner's real install.
>
> **Time.** 5–7 h for §15.1–15.11 with no hardware. §15.12 (never-measured surfaces) is open-ended
> exploratory work — budget a half-day and stop when you stop finding things, recording where you
> stopped. The probe tool (below) collapses the nine source-level reproductions to about 30 seconds.

---

## 15.0 How to run this chapter

### 15.0.1 The rule that governs every case here

The audit states its own limit, and it is the operating instruction for this chapter:

> **"Single-source audit output is a lead, not a fact."**

It earned that warning honestly. One of its own auditors stubbed `PermissionGate.check_call` to
return `True` and reported the resulting Gmail fan-out as production behaviour — with the real gate,
15 of 17 probes fire nothing. Another counted only `ast.Assign` nodes and concluded that 21
orchestrator attributes were declared nowhere; 15 of them were `AnnAssign` lines in the same class.
Both errors survived into a first draft that read as confident as the true findings did.

So: **nothing in this chapter is a finding until you have reproduced it here.** Every case carries a
mandatory `CROSS:` line for the same reason chapter 02 does — one source cannot catch an error in
that source.

### 15.0.2 Verdict vocabulary (use these words, not "pass/fail")

A test-manual case normally passes or fails. These do not, because the thing under test is a *claim
about this codebase*, and it can be right, wrong, or right-about-a-mechanism-and-wrong-about-the-blast-radius.

| Verdict | Meaning | What you write in the report |
|---|---|---|
| **CONFIRMED** | Reproduced as described, at the described severity | the reproduction, verbatim |
| **PARTIAL** | The mechanism reproduces; the consequence does not, or needs preconditions the audit missed | mechanism ✅ + **what actually gates it** |
| **REFUTED** | Does not reproduce on this build | the counter-evidence, so nobody re-files it |
| **NOT-REPRODUCIBLE** | Could not be measured here (no key, no host, no backend) | *why* — never infer a verdict from a skipped probe |
| **FIXED-SINCE** | Reproduced at the audit's commit, does not at yours | the commit that closed it |

`NOT-REPRODUCIBLE` is a real answer and must be used. A probe that could not run is not a
CLOSED finding, and writing it up as one is the same defect class the whole manual exists to catch.

### 15.0.3 Re-grade every severity yourself

The audit says this outright: *"the verifier severities are not fully deterministic. Re-running the
same skeptics produced different corrected severities on several findings."* Treat every severity
label in this chapter as the audit's estimate, and record your own using `docs/TEST_MANUAL.md` §1.2.
Where your grade differs, say so and why — a disagreement about severity is data.

### 15.0.4 The probe tool — run this first

Nine of the source-level reproductions are packaged so you do not retype them:

```
python scripts/qa_audit_probes.py            # all nine, table + detail
python scripts/qa_audit_probes.py --json     # machine-readable, paste into the report
python scripts/qa_audit_probes.py --list     # what each one measures
```

Each probe prints `OPEN` (the mechanism still reproduces here), `CLOSED` (it does not) or `N/A`.
**A probe reports; it never asserts** — fixing a finding flips OPEN to CLOSED and nothing breaks.
It is read-only against the live install: the chain probe forges rows in a `tempfile` database and
never opens `<data_root>/security/audit.db`; the purge probe lists stores and never deletes; the
signing probe reports *whether* a key is configured and never any part of one.

**An OPEN verdict is still only a lead.** Every case below that has a probe also has a live
cross-check, and the live cross-check is what you file.

### 15.0.5 Order

Run **15.1 first** — it is the only fully confirmed, uncorrected, no-preconditions break in the
audit, and every other governance claim in the product is ultimately backed by the log it breaks.
Then **15.2**, the one finding that hurts a person rather than a claim. Then the rest in order;
**15.11** (the refuted claims) is deliberately cheap and late; **15.12** is open-ended and last.

### 15.0.6 Per-case record

| Field | Value |
|---|---|
| Case (ADV-id) | |
| Verdict (15.0.2) | |
| Your severity + the audit's | |
| Build SHA + `GET /status` version | |
| Reproduction (command / steps, verbatim) | |
| Observed output (paste, do not paraphrase) | |
| `CROSS:` — the second source | |
| Preconditions the audit did not name | |

---

## 15.1 ⭐ The audit chain is forgeable in hardened mode — the one new break

**Audit verdict: CONFIRMED · High · `agents/core/security/audit.py`.** The only finding in the whole
document that survived the skeptic unmodified and needs no preconditions beyond the ones a hardened
install is *supposed* to have. `verify_chain` recomputes each row using **the row's own `hash_algo`
column**, and `_digest` demands the key only when that column says `hmac-sha256`. Downgrade every row
to `sha256` and the chain re-links cleanly. The shipped regression passes because it downgrades one
row, so the break surfaces at the next row whose `prev_hash` is still an HMAC.

Do this section first. `docs/THREAT_MODEL.md` T5 sells this chain as the mitigation for audit
tampering, and `GET /api/metrics/kernel` plus every "ungoverned actions == 0" claim in the product
ultimately rests on it.

#### ADV-001 — Reproduce the full-table downgrade with a key configured  🔑
- **Surface:** `agents/core/security/audit.py` · `agents/core/security/hardened.py` · **Auto:** ⚠️tests/test_audit_hardening.py (single-row only — that is the finding)
- **Why it matters:** "an attacker with DB write access cannot forge the chain without it" is the literal justification `hardened.enforce()` gives for requiring `JARVIS_AUDIT_KEY`. If a full-table rewrite verifies, that guarantee is void and nothing else in the governance story has a substrate.
- **Steps:** `python scripts/qa_audit_probes.py chain`. Read the four detail lines. Then re-derive it by hand at least once (do not trust one script either): open a Python shell with `JARVIS_AUDIT_KEY` set to any value, build an `AuditLogger` on a temp path, log three events, confirm `verify_chain() == (True, None)` and all three rows say `hmac-sha256`; then with `sqlite3` + `hashlib` **only**, rewrite every `content_preview`, recompute each `row_hash` as plain sha256 over `prev|ts|type|findings|preview|action`, re-link `prev_hash`, set `hash_algo='sha256'`, commit, and re-verify.
- **Expected (the FAIL signature — this is what a broken build prints):**
  ```
  baseline verify_chain: [True, None]      row algos: ['hmac-sha256', 'hmac-sha256', 'hmac-sha256']
  verify_after_full_downgrade: [True, None]
  content_after: ['attacker rewrote row 1', 'attacker rewrote row 2', 'attacker rewrote row 3']
  ```
  A **fixed** build returns `[False, 1]` (or any row id) after the rewrite, and the probe prints `CLOSED`.
- **FAIL if:** verification passes over a fully rewritten table → **BLOCKER**. Record it as CONFIRMED regardless of what the shipped test suite says — that is the whole point of this case.
- **CROSS:** the probe's verdict **and** your hand reproduction **and** `GET /api/security/audit/verify` on a live install (15.0.4 covers only the first).
- **Evidence:** the probe's `--json` block plus your shell transcript.

#### ADV-002 — The key is never read during the forgery  🔑
- **Surface:** the same reproduction
- **Why it matters:** distinguishes "attacker who stole the key" (out of scope) from "attacker who never needed it" (the finding).
- **Steps:** re-run ADV-001's hand reproduction in a process where `JARVIS_AUDIT_KEY` is **unset**, against the DB written by a keyed process.
- **Expected:** the forgery still verifies when re-opened by a keyed logger. The attacker's toolkit is `sqlite3` + `hashlib`.
- **FAIL if:** it succeeds → confirms the finding's severity. It failing would *downgrade* the finding, which is a result worth having.
- **CROSS:** compare against `tests/test_audit_hardening.py::test_keyed_chain_unverifiable_without_key`, which proves the *intended* behaviour for a legitimate reader.
- **Evidence:** both transcripts side by side.

#### ADV-003 — Why the shipped regression misses it  ⏱
- **Surface:** `tests/test_audit_hardening.py`
- **Why it matters:** a green test suite that cannot see the attack it is named for is the chapter's thesis in one file. This case is about the *test*, not the product.
- **Steps:** read `test_attacker_recompute_with_sha256_still_fails`. Note it rewrites `WHERE id=2` only, and asserts `first_bad == 3`. Then run the full suite: `python -m pytest tests/test_audit_hardening.py -q`.
- **Expected:** all green, while ADV-001 reproduces. Both statements are true simultaneously — the test asserts something real (a *partial* downgrade is caught) that is narrower than its docstring implies.
- **FAIL if:** the suite is red → different problem, stop and report that instead.
- **CROSS:** ADV-001's result. Green suite + OPEN probe = the finding.
- **Evidence:** the test source excerpt and the pytest line.

#### ADV-004 — `hardened.enforce()` returns clean while the chain is forgeable  🔑
- **Surface:** `agents/core/security/hardened.py`
- **Why it matters:** the posture check is what an owner reads to believe hardening took.
- **Steps:** with `JARVIS_HARDENED=1` and `JARVIS_AUDIT_KEY` set, call `hardened.enforce()`.
- **Expected:** `[]` — no violations. It only checks the key is *present*, never that rows are keyed.
- **FAIL if:** it returns `[]` while ADV-001 is OPEN → the posture surface is reporting a guarantee it does not verify. **MAJOR** on its own.
- **CROSS:** `GET /api/security/posture` (tier **admin**) — does it distinguish an unkeyed digest from a keyed signature anywhere?
- **Evidence:** both outputs.

#### ADV-005 — A mixed-algorithm chain is legitimate, so the fix cannot be "reject all sha256"  ⏱
- **Surface:** `tests/test_audit_hardening.py::test_mixed_algo_chain_verifies_across_key_introduction` · `agents/core/persistence/migrations.py`
- **Why it matters:** this case protects the *fix* from being wrong. A legacy install that adopts a key mid-stream has a real prefix of sha256 rows.
- **Steps:** run that test; read `_v2_hash_algo` in `agents/core/security/audit.py`.
- **Expected:** green. A legitimate sha256 prefix must keep verifying.
- **FAIL if:** any proposed remediation breaks it — note that in your report so the fix is scoped as "reject a **post-legacy** sha256 row when a key is configured", which is the fail-closed shape the blank-row guard already uses.
- **CROSS:** the blank-`row_hash` handling comment in `verify_chain` — same shape, already correct.
- **Evidence:** the test result.

#### ADV-006 — The blank-row guard (the July fix) still holds  ⏱
- **Surface:** `agents/core/security/audit.py` · **Auto:** ✅tests/test_audit_hardening.py
- **Why it matters:** the audit says the previous fix is "subtle-correct". Confirm you are not about to regress a good fix while fixing a bad one.
- **Steps:** inject a row with an empty `row_hash` after the chain has started; verify.
- **Expected:** `(False, <rid>)` — fails closed.
- **FAIL if:** it skips the row → a second forgery path; **BLOCKER**.
- **CROSS:** the SEC-A2 entry in `BACKLOG.md` claims this delivered — does the code match the claim?
- **Evidence:** the verify tuple.

#### ADV-007 — Is there a compensating control? The transparency anchor  🔑
- **Surface:** `POST /api/security/audit/anchor` (admin) · `GET /api/security/audit/anchors` (open) · `agents/core/security/anchor.py`
- **Why it matters:** the audit says the anchor cannot save you: one caller (a manual POST), unkeyed sha256, a local JSON file, and it never compares its root against the chain tail.
- **Steps:** POST an anchor, GET the list, then grep for callers of `TransparencyAnchor.anchor(` across `agents/`.
- **Expected:** the anchor records a root but nothing periodically compares it to `audit.tail_hash()`, and nothing off-box witnesses it. Anchors written *after* a forgery are anchors of the forged state.
- **FAIL if:** you find no automatic anchoring and no comparison → the finding has no compensating control. Record as CONFIRMED.
- **CROSS:** `GET /api/security/audit/intent` (open) — does the intent log independently record the same events, and would a chain rewrite disagree with it?
- **Evidence:** the anchors payload and your grep output.

#### ADV-008 — Does the intent log catch the rewrite?  🔑
- **Surface:** `GET /api/security/audit/intent` (open) · `agents/core/security/anchor.py`
- **Why it matters:** an independent second record would downgrade the finding from "no trace" to "detectable". Worth 15 minutes to know.
- **Steps:** generate a few real security events; snapshot the intent log; run the ADV-001 forgery against a copy of the chain; compare.
- **Expected:** determine and record whether they overlap enough to cross-check. Do not assume either way.
- **FAIL if:** they overlap and nothing compares them → a cheap detection is available and unbuilt (a **gap**, log it in the ledger, not a bug).
- **CROSS:** `GET /api/admin/audit` (admin) — same rows, different reader.
- **Evidence:** both payloads.

#### ADV-009 — Live: `GET /api/security/audit/verify` on the real chain  🔑
- **Surface:** `GET /api/security/audit/verify` (open)
- **Why it matters:** everything above is a temp-DB reproduction. This is the endpoint an operator actually reads.
- **Steps:** `curl -s "$B/api/security/audit/verify"`. **Do not modify the real chain.**
- **Expected:** an honest verdict about the live chain. Note whether the response distinguishes *keyed* from *unkeyed* verification — an unkeyed "valid" is integrity-only, not tamper-evidence, and the response should say which one you got.
- **FAIL if:** it reports "valid" with no indication that the chain is unkeyed on this host → **MAJOR** (a true statement that reads as a stronger one).
- **CROSS:** `GET /api/security/posture` (admin) → does the posture agree about key presence?
- **Evidence:** both bodies.

#### ADV-010 — Route-tier check on the audit surfaces  🌐
- **Surface:** `GET /api/security/audit/verify` (open) · `GET /api/security/audit/anchors` (open) · `GET /api/admin/audit` (admin)
- **Why it matters:** an open verify endpoint is defensible (it returns a boolean); an open *reader* of chain contents is not. Confirm which is which.
- **Steps:** call all three with no token, then with a user token, then admin. Cross-reference `tests/_snapshots/route_auth.json`.
- **Expected:** the snapshot's tiers hold exactly; content-bearing reads are admin.
- **FAIL if:** any content-bearing audit read answers an unauthenticated caller → **BLOCKER**, and file it into §08 as well.
- **CROSS:** the §14 sweep's row for each route.
- **Evidence:** three status codes per route.

#### ADV-011 — Does anything *else* trust `hash_algo` from the row?  ⏱
- **Surface:** `agents/core/security/audit.py`
- **Why it matters:** `prune_before` also recomputes "with each row's own algorithm". Same trust, different function — check whether it is a second instance.
- **Steps:** read `prune_before`; note the guard that refuses to prune HMAC rows without a key. Grep for every other read of `hash_algo`.
- **Expected:** enumerate every site. Report whether the prune path is safe (it appears to fail closed) or a second forgery surface.
- **FAIL if:** a second site takes the algorithm from the data without a fail-closed guard → widen the finding.
- **CROSS:** run the retention/prune tests and read what they assert.
- **Evidence:** the grep, annotated.

#### ADV-012 — The root cause, not the instance: unkeyed hash presented as a signature  ⏱
- **Surface:** `agents/core/security/audit.py` · `agents/core/skills/signing.py`
- **Why it matters:** the audit's central structural point. These are two subsystems making the same mistake, flagged separately in July (`BACKLOG.md` SEC-B2 names both), and never recognised as one.
- **Steps:** put `_digest` and `compute_digest` side by side. In both, a missing key silently downgrades to a plain digest that the verifier then accepts as proof of origin.
- **Expected:** you can state the shared rule in one sentence: *a digest computed without a secret proves integrity against accident, never authorship against an adversary.*
- **FAIL if:** you find a third instance — search for any other "verify" that reads its own algorithm or key-presence from the artefact it is checking. That is the highest-value thing this case can produce.
- **CROSS:** §15.3 tests the skill-signing half; they should reach the same conclusion independently.
- **Evidence:** the paired code excerpts and any third instance.

#### ADV-013 — Owner-facing: what would an operator actually see?  👁
- **Surface:** Console → Trust → audit/verify surfaces · `frontend/src/gap.tsx`
- **Why it matters:** a break nobody can observe is worse than one that shows up somewhere.
- **Steps:** with the forged temp DB *not* in play, walk the HUD's trust surfaces and write down every place the audit chain's health is displayed.
- **Expected:** an inventory. For each, note whether it would have shown anything different after a rewrite.
- **FAIL if:** the answer is "nothing anywhere would change" → record as a **gap**: there is no operator-visible integrity signal.
- **CROSS:** the API bodies from ADV-009.
- **Evidence:** screenshots of each surface plus your inventory.

#### ADV-014 — Regression the fix must carry  ⏱
- **Surface:** `tests/test_audit_hardening.py`
- **Why it matters:** the audit is explicit that the single-row test is what let this sit, and that the full-table rewrite belongs in the same commit as the fix.
- **Steps:** write (do not merge) the test you would require: a full-table downgrade with a key configured must fail verification. Confirm it is **red** on the current build.
- **Expected:** red now, green after the fix. A test that is green before the fix is testing the wrong thing.
- **FAIL if:** your new test passes on the current build → your reproduction is wrong; go back to ADV-001.
- **CROSS:** the probe's `chain` verdict must be OPEN at the same commit.
- **Evidence:** the test source and its failure output.

---

## 15.2 ⭐ Forget does not erase — it copies

**Audit verdict: CONFIRMED · High · `agents/core/data_purge.py`.** Found by the completeness critic
in the one area no lens had looked. `docs/PRIVACY.md` says forget *"erases memory, transcripts,
vectors, and the knowledge graph at rest"*; `BACKLOG.md` records purge completeness as done (AUD-2).
Three independent failures: twelve user-content stores survive the allowlist, the vector/KG wipe is
dead code behind a `hasattr` guard, and the safety net leaves a plaintext archive **inside the folder
it just purged**.

> **⚠ This is the only destructive section in the chapter.** Point `JARVIS_HOME` at a throwaway data
> root and seed it yourself. Never run `POST /api/admin/forget` against the owner's real install for
> a test. If you cannot isolate a data root, do §15.2 read-only (ADV-015…ADV-022 are all static) and
> record the live cases as NOT-REPRODUCIBLE.

#### ADV-015 — Enumerate what the purge allowlists do not cover  ⏱
- **Surface:** `agents/core/data_purge.py` · `agents/core/data_export.py` · **Auto:** ❌
- **Why it matters:** the shape of the bug is an allowlist that must be updated every time anyone adds a store, in a repo that adds stores often.
- **Steps:** `python scripts/qa_audit_probes.py purge`. Then independently: list every `data_path("…")` default under `agents/` and subtract `PURGE_DBS ∪ PURGE_JSON ∪ PURGE_MEMORY_FILES`.
- **Expected:** `PURGE_DBS` is three databases, `PURGE_JSON` is two files, and the probe names the survivors it knows about, each with the module that owns it. Your independent sweep should find at least those and may find more — **more is the interesting result**, so report your list, not the probe's.
- **FAIL if:** any store holding user text/content survives → **BLOCKER** against the `docs/PRIVACY.md` promise. Grade per store: message bodies and prompts are worse than counters.
- **CROSS:** your `data_path` sweep vs the probe's list vs an actual before/after directory diff (ADV-023).
- **Evidence:** both lists, and the diff of the two.

#### ADV-016 — `run_history.json` survives, and it holds input/output previews  ⏱
- **Surface:** `agents/core/run_history.py` · `agents/core/data_purge.py`
- **Why it matters:** the audit names this as one of the two worst survivors. Previews are user content.
- **Steps:** read what `RunHistory` persists per run. Confirm the file is outside every purge set.
- **Expected:** per-agent input and output previews persist across a forget.
- **FAIL if:** confirmed → **BLOCKER**. Note the exact preview length so severity is arguable on facts.
- **CROSS:** `GET /api/metrics/north-star` reads `RunHistory.locality()` from the same store — so a "forgotten" user still moves the north-star meter.
- **Evidence:** the store's contents before/after (redact the previews themselves).

#### ADV-017 — `channel_inbox.json` survives, and it holds full message bodies  ⏱
- **Surface:** `agents/core/channel_inbox.py` · `agents/core/data_purge.py`
- **Why it matters:** the other worst survivor — inbound messages from real people, not just the owner.
- **Steps:** read the store's persisted shape and any per-message length cap.
- **Expected:** message bodies persist through a forget.
- **FAIL if:** confirmed → **BLOCKER**, and note that this is third-party personal data, which raises it above the owner's own content.
- **CROSS:** `GET /api/channels/inbox` (see §11) after a purge on the throwaway root — do threads still list?
- **Evidence:** the store path, the cap, and the post-purge listing (redact bodies).

#### ADV-018 — Two survivors are on a denylist that guarantees nothing ever deletes them  ⏱
- **Surface:** `agents/core/session_files.py` · `agents/core/data_purge.py`
- **Why it matters:** `NON_SESSION_STEMS` exists so a data file is never mistaken for a transcript. Correct — but it also means the session-purge path skips them, and the allowlist never names them, so **no path deletes them at all**.
- **Steps:** read `NON_SESSION_STEMS`; intersect with your ADV-015 survivor list.
- **Expected:** identify each store that is both denied-as-session and absent from the allowlist.
- **FAIL if:** any such store holds user content → this is the sharpest single articulation of the bug; quote it verbatim in the report.
- **CROSS:** the retention path — does TTL pruning reach them? (`docs/PRIVACY.md` claims retention "prunes old transcripts/audit rows", so probably not.)
- **Evidence:** the intersection, named.

#### ADV-019 — `notes.db` is exported but never purged  ⏱
- **Surface:** `agents/core/data_export.py` · `agents/core/data_purge.py`
- **Why it matters:** the module's own docstring says the export and purge allowlists "should be reconciled". They still are not — and the asymmetry runs the wrong way: the system will hand a user a copy of data it cannot delete.
- **Steps:** compare `EXPORT_DBS` with `PURGE_DBS`. The probe prints this as `exported_but_never_purged`.
- **Expected:** at least one database is exportable and unpurgeable.
- **FAIL if:** confirmed → **MAJOR**, and it is the cheapest fix in this section: one tuple.
- **CROSS:** `POST /api/admin/export` then `POST /api/admin/forget` then export again on the throwaway root — the same rows should not appear twice.
- **Evidence:** the two export bundles.

#### ADV-020 — Purge everything-except is the fix shape; test that framing  ⏱
- **Surface:** `agents/core/data_purge.py`
- **Why it matters:** this case exists to make the report actionable rather than a list of twelve filenames that will be thirteen next month.
- **Steps:** write down what a `KEEP` allowlist would have to contain (config, the audit chain, settings/secrets, system stores) and check each against the code's current exclusions, which are already documented in the module docstring.
- **Expected:** a short, closed list — which is why the inversion is tractable.
- **FAIL if:** the KEEP list is not enumerable, say so; that would make the inversion harder than the audit assumes and is worth knowing before someone starts.
- **CROSS:** the module docstring's "Excluded by design" paragraph.
- **Evidence:** your KEEP list.

#### ADV-021 — Retention does not compensate  ⏱
- **Surface:** `docs/PRIVACY.md` · `agents/core/data_purge.py`
- **Why it matters:** "TTLs prune old transcripts/audit rows automatically" could plausibly cover the survivors. Check rather than assume.
- **Steps:** identify what retention actually prunes and whether it is on by default (`docs/PRIVACY.md` says off by default).
- **Expected:** transcripts and audit rows only, off by default.
- **FAIL if:** confirmed → the survivors have no second removal path at all.
- **CROSS:** the retention settings in `agents/core/settings_db.py`.
- **Evidence:** the setting defaults.

#### ADV-022 — The vector/KG wipe is dead code  ⏱
- **Surface:** `agents/core/data_purge.py` · `agents/core/memory/store.py` · `agents/core/memory/graph.py` · `agents/core/memory/qdrant_store.py`
- **Why it matters:** `clear_live_memory` calls `store.clear()` behind `if hasattr(...)`. The audit reports that none of the four store/graph implementations defines `clear()`, so the call never happens and the purge still reports `ok: true`.
- **Steps:** `python scripts/qa_audit_probes.py clear`. Then check `VectorStore` and `KnowledgeGraph` yourself: which methods are `@abstractmethod`, and is `clear` among them?
- **Expected:** the probe lists the implementations with no `clear()`. The base classes declare several abstract methods and **not** `clear` — which is why a missing implementation is silent instead of an import error.
- **FAIL if:** confirmed → at in-memory defaults the exposure is bounded by process lifetime, but **under the documented `qdrant`/`neo4j` backends every embedding and every KG triple survives a forget permanently, with no code path that could remove them**. Grade the backend you are actually running, and say which one that was.
- **CROSS:** the purge's own JSON response — does it claim success for a step that did not run? That mismatch is the reportable part.
- **Evidence:** the probe output, the abstract-method list, and the purge response.

#### ADV-023 — Live: directory diff across a real forget (throwaway root)  🖥
- **Surface:** `POST /api/admin/forget` (admin)
- **Why it matters:** everything above is static. This is the measurement.
- **Steps:** on a throwaway `JARVIS_HOME`: seed it by using the product (a few chats, a note, a workflow run, an inbound channel message if you can). Snapshot the tree with sizes and hashes. Call `POST /api/admin/forget`. Snapshot again. Diff.
- **Expected:** a precise list of what changed, what did not, and what appeared.
- **FAIL if:** any file holding user content is byte-identical after the forget → **BLOCKER**, with the diff as evidence.
- **CROSS:** ADV-015's static prediction. If the diff and the prediction disagree, the *disagreement* is the finding — investigate before filing either.
- **Evidence:** both trees (names + sizes; redact contents).

#### ADV-024 — The pre-forget archive lands inside the data root  🖥
- **Surface:** `agents/core/backup.py` · `agents/core/routers/backup.py`
- **Why it matters:** `default_backup_dir()` is `<data_root>/backups`, and the forget route hardcodes `backup_first=True`. So a forget concentrates what was scattered into one archive, and leaves it in the folder it just purged.
- **Steps:** after ADV-023, list `<data_root>/backups`. Extract the archive to a scratch dir.
- **Expected:** an archive exists; it is encrypted only if a backup key is configured.
- **FAIL if:** the archive is plaintext and recoverable → **BLOCKER**. Count how many of your seeded markers you can recover, and say so numerically.
- **CROSS:** the forget response body — does it mention the archive at all? An undisclosed copy is worse than a disclosed one.
- **Evidence:** the file listing (never attach the archive).

#### ADV-025 — There is no API equivalent of `--no-backup`  ⏱
- **Surface:** `agents/core/routers/backup.py` · `agents/core/data_purge.py`
- **Why it matters:** the CLI can skip the archive; the route cannot. A user who wants deletion cannot get deletion through the product.
- **Steps:** read the route handler; check the request model for any `backup_first` field. Try passing one.
- **Expected:** hardcoded `True`; an extra field is either ignored or 422 (check which — a silently-dropped field is its own finding, see the RUN-2 `session_id` case in §02).
- **FAIL if:** ignored silently → **MAJOR** on top of the purge finding.
- **CROSS:** the CLI's `--no-backup` path in `agents/core/data_purge.py`.
- **Evidence:** the request/response pair.

#### ADV-026 — Nothing prunes the pre-forget archives  ⏱
- **Surface:** `agents/core/backup.py`
- **Why it matters:** each forget adds an archive. Ten forgets, ten complete copies.
- **Steps:** run forget twice on the throwaway root; count archives.
- **Expected:** two. Retention covers transcripts and audit rows, not backups.
- **FAIL if:** confirmed → **MAJOR**; the surface grows monotonically with the number of deletion requests.
- **CROSS:** the retention settings from ADV-021.
- **Evidence:** the directory listing.

#### ADV-027 — The forget response says `ok` regardless  🖥
- **Surface:** `POST /api/admin/forget` (admin)
- **Why it matters:** this is an F5 shape from `docs/TEST_MANUAL.md` §1.1 — a claimed completed action that did not complete. Grade it on that scale.
- **Steps:** compare the response body against ADV-023's diff.
- **Expected:** the response should be able to say what it *could not* clear. Record whether it can.
- **FAIL if:** it reports unqualified success while stores survive → **BLOCKER (F5)**.
- **CROSS:** the diff. This is the case where the two-source rule does the most work.
- **Evidence:** the body and the diff, adjacent.

#### ADV-028 — `docs/PRIVACY.md` overstates what forget does  ⏱
- **Surface:** `docs/PRIVACY.md`
- **Why it matters:** a documented promise is a commitment to a user, not a comment.
- **Steps:** quote the sentence; list which of its four nouns (memory, transcripts, vectors, knowledge graph) are actually erased on your build and backend.
- **Expected:** a four-row table with your evidence per row.
- **FAIL if:** any row is false → the doc must change in the same PR as the code, and the report should say which.
- **CROSS:** ADV-022 and ADV-023.
- **Evidence:** the table.

#### ADV-029 — `BACKLOG.md` records purge completeness as done  ⏱
- **Surface:** `BACKLOG.md`
- **Why it matters:** the ticked checkbox is why nobody looked again. That is the audit's systemic thesis, instantiated.
- **Steps:** find the AUD-2 purge-completeness entry; read what it claims.
- **Expected:** a claim broader than the code supports.
- **FAIL if:** confirmed → propose the corrected wording in your report (do **not** edit `BACKLOG.md` yourself; `docs/TEST_MANUAL.md` §6 reserves triage for the owner).
- **CROSS:** the code.
- **Evidence:** the quoted line.

#### ADV-030 — The craftsmanship is real; do not report it as sloppy  ⏱
- **Surface:** `agents/core/data_purge.py` · `agents/core/backup.py`
- **Why it matters:** the audit is explicit that the bug is the allowlist, not the engineering, and a report that misses this will be discounted wholesale.
- **Steps:** verify each: the snapshot is `verify_backup`-ed before a single delete; archives use the SQLite online-backup API rather than copying live WAL files; extraction has a Zip-Slip guard; table names come from `sqlite_master`.
- **Expected:** all four hold.
- **FAIL if:** any does **not** hold → that is a *new* finding and more urgent than the allowlist.
- **CROSS:** the backup tests in `tests/`.
- **Evidence:** the four confirmations, stated in the report as such.

#### ADV-031 — Live memory clear runs before the on-disk purge  🖥
- **Surface:** `agents/core/data_purge.py` · `agents/core/routers/backup.py`
- **Why it matters:** ordering matters — a running orchestrator that re-persists after the delete would undo the purge even if the allowlist were right.
- **Steps:** confirm the route awaits `clear_live_memory(orch)` before `purge_data`. Then, on the throwaway root, keep the server running across a forget and check nothing rewrites the deleted files within a minute.
- **Expected:** the order is correct in code; verify it empirically anyway.
- **FAIL if:** any purged file reappears → **BLOCKER** independent of the allowlist.
- **CROSS:** the directory diff from ADV-023, re-taken 60 s later.
- **Evidence:** the two post-purge listings.

#### ADV-032 — Session transcripts: confirmed-only deletion  🖥
- **Surface:** `agents/core/data_purge.py` · `agents/core/session_files.py`
- **Why it matters:** transcripts are deleted only for *confirmed* sessions (a payload declaring `session_id` + `turns`), never by glob. That is a deliberate, good decision — verify it does not leave orphans.
- **Steps:** seed a transcript, corrupt its shape (remove `turns`), run forget.
- **Expected:** the malformed file is **not** deleted — content confirmation failed, so it is treated as not-a-session.
- **FAIL if:** it survives holding real conversation text → a legitimate design choice with a data-retention consequence. Grade **MAJOR** and describe it as a trade-off, not a mistake.
- **CROSS:** `is_valid_session_id` and the `NON_SESSION_STEMS` denylist.
- **Evidence:** before/after for that file.

#### ADV-033 — Repeat the forget with a vector backend selected  🔑 🖥
- **Surface:** `agents/core/memory/qdrant_store.py`
- **Why it matters:** severity turns entirely on the backend. In-memory is bounded by process lifetime; Qdrant is permanent.
- **Steps:** if Qdrant is reachable, point the throwaway install at it, write embeddings, forget, then query Qdrant directly.
- **Expected:** record what actually remains.
- **FAIL if:** embeddings survive → **BLOCKER** and the highest-severity instance of ADV-022. If Qdrant is unavailable, mark **NOT-REPRODUCIBLE** and say so — do not infer.
- **CROSS:** the purge response's per-step report.
- **Evidence:** the Qdrant collection count before/after.

#### ADV-034 — The user-facing question: can a design partner get their data deleted?  👁
- **Surface:** end-to-end
- **Why it matters:** the audit's framing — *"a design partner asked to delete their data before shipping the box back currently cannot"* — and it lands on the A1/A7 gate the release depends on.
- **Steps:** role-play it. Using only the product's surfaces (no shell), delete everything. Time it. Write down every step.
- **Expected:** either a clean path exists, or you can state exactly what is left and where.
- **FAIL if:** the honest answer is "you would have to delete the data directory by hand" → **BLOCKER** for the design-partner gate specifically; say that in the first line of your report.
- **CROSS:** ADV-023's diff — it is the ground truth for "what is left".
- **Evidence:** the walkthrough, timed.

---

## 15.3 Unkeyed hash as signature — the skill-signing half

**Audit verdict: PARTIAL · High → scoped · `agents/core/skills/signing.py`.** The skeptic corrected
this one hard, and the corrections change what you should do. With
`JARVIS_REQUIRE_SIGNED_SKILLS=1` and no key set, a forged zip loads as trusted and executes at import.
But: (1) the signature forgery is **not** what grants code execution — at the shipped default with the
flag unset, a package with no signature at all installs and executes identically, so the exec
primitive is the thing to fix; (2) "zero protection" is too strong — under `=1` all bundled skills
were correctly refused against *unsigned* content; (3) the crypto weakness therefore costs only the
owner who did harden.

> **Safety.** Every skill you build for this section must be inert: a module-level `print()`, never a
> shell command, never a network call, never a file write outside its own directory. You are proving
> that *arbitrary* code runs, and `print()` proves that as well as anything dangerous does.

#### ADV-035 — `require_signed()` does not fail closed without a key  ⏱
- **Surface:** `agents/core/skills/signing.py` · **Auto:** ❌
- **Why it matters:** the whole finding in one function.
- **Steps:** `python scripts/qa_audit_probes.py signing`. Then read `require_signed()` yourself — it reads one env flag and consults nothing else.
- **Expected:** `require_signed_consults_a_key: False`, and `compute_digest` returns the `sha256` label on a keyless host.
- **FAIL if:** confirmed → **MAJOR** for a hardened install, **not** for a default one. Say which you graded.
- **CROSS:** `GET /api/security/posture` (admin) — does it surface the unkeyed/keyed distinction anywhere? `BACKLOG.md` SEC-B2 says it should.
- **Evidence:** the probe detail and the function source.

#### ADV-036 — A forged signature is accepted when no key is configured  ⏱
- **Surface:** `agents/core/skills/signing.py`
- **Why it matters:** proves the gate is bypassable by an attacker who ships their own `SKILL.sig`, not merely weak.
- **Steps:** build a throwaway skill directory with an inert module; call `sign_skill()` on it with **no** key configured; call `verify_skill()`.
- **Expected:** `(True, "signed")` — because the attacker can compute the same digest you can.
- **FAIL if:** confirmed. Note the honest framing: this is not "signatures are broken", it is "an unkeyed digest is not a signature".
- **CROSS:** repeat with a key configured — the same forged sig must now fail. That contrast is the evidence.
- **Evidence:** both verify tuples.

#### ADV-037 — The gate does work against unsigned content  ⏱
- **Surface:** `agents/core/skills/signing.py` · `agents/core/skills/loader.py`
- **Why it matters:** the skeptic's correction. A report that says "zero protection" will be dismissed, correctly.
- **Steps:** with `JARVIS_REQUIRE_SIGNED_SKILLS=1`, attempt to load the bundled skills (which ship unsigned).
- **Expected:** all refused in-process. The gate stops honest unsigned content.
- **FAIL if:** any unsigned skill loads under `=1` → a *worse* finding than the one being tested; escalate.
- **CROSS:** `GET /skills` (open) — what does the listing say about each one's trust state?
- **Evidence:** the refusal list and the listing.

#### ADV-038 — The real primitive: `exec_module` at load time  ⏱ ✅
- **Surface:** `agents/core/skills/loader.py`
- **Why it matters:** the audit is unambiguous that this, not the hash, is the execution boundary. `_load_skill` may execute module top-level code.
- **Steps:** read `_load_skill` around the `spec.loader.exec_module(mod)` call. Then install an external inert skill whose module body writes a marker, at the **shipped default** (`JARVIS_REQUIRE_SIGNED_SKILLS` unset, no signature at all). Repeat with a repository-bundled skill and with a keyed HMAC signature.
- **Expected:** the unsigned external marker does not appear; the skill remains visible with `sandboxed=true` and no loaded module. Repository-bundled behavior is unchanged, and a keyed external skill may load in-process. Marketplace extraction stamps external provenance and discards any package-supplied owner-approval marker.
- **FAIL if:** unsigned owner/imported/marketplace code reaches `exec_module`, or if the boundary disables repository-bundled skills. Treat either result as a **BLOCKER**.
- **CROSS:** `POST /api/skills/marketplace/install-zip` (admin) — does the HTTP path reach the same loader? Check before claiming remote reachability.
- **Evidence:** [`2026-08-12 ADV-038 execution-boundary run`](../qa-runs/2026-08-12-hermetic-adv-exec-boundary.md).

#### ADV-039 — What tier can reach the installer?  🌐
- **Surface:** `POST /api/skills/marketplace/install-zip` (admin) · `POST /skills/import` (user) · `POST /api/skills/{name}/approve` (admin)
- **Why it matters:** severity depends entirely on who can trigger the exec.
- **Steps:** probe each with no token / user / admin. Cross-check `tests/_snapshots/route_auth.json`.
- **Expected:** the snapshot's tiers hold. Note carefully which import paths are **user** rather than admin.
- **FAIL if:** any user-tier route reaches `exec_module` → escalate ADV-038 to the top of the report.
- **CROSS:** trace the user-tier import path in `agents/core/skills/loader.py` to see whether it loads or only stages.
- **Evidence:** the status codes plus the traced path.

#### ADV-040 — Is there a sandbox, and does it engage by default?  ⏱
- **Surface:** `agents/core/skills/loader.py`
- **Why it matters:** the forged package reported `sandboxed: False`. Find out what would have made it `True`.
- **Steps:** grep for the sandbox flag and every branch that sets it.
- **Expected:** an enumerated set of conditions.
- **FAIL if:** no branch can make it `True` for an installed skill → the field is decorative; report it as such.
- **CROSS:** `GET /skills` (open) and `GET /skills/imported` (open) — what do they report per skill?
- **Evidence:** the branches and the listings.

#### ADV-041 — Trust labels in the listing vs reality  👁
- **Surface:** `GET /skills` (open) · `GET /api/skills/pending` (admin)
- **Why it matters:** the owner reads a label, not the code.
- **Steps:** install your inert unsigned skill; read every trust/signed/sandboxed field the listings expose.
- **Expected:** an honest label for an unsigned skill.
- **FAIL if:** an unsigned skill reads as `trusted` → **MAJOR** (F3 from §1.1 — unlabelled).
- **CROSS:** `verify_skill()` called directly on the same directory.
- **Evidence:** the listing rows and the verify tuple.

#### ADV-042 — Only `_SIGNED_FILES` are covered by the digest  ⏱
- **Surface:** `agents/core/skills/signing.py`
- **Why it matters:** anything outside that tuple can change without invalidating the signature.
- **Steps:** read `_SIGNED_FILES`. Sign a skill, add a file not on the list, re-verify.
- **Expected:** still `signed`.
- **FAIL if:** a file the loader can import is outside the signed set → a second bypass that survives even a keyed signature. That would be a genuinely **new** finding; escalate.
- **CROSS:** what `_load_skill` is capable of importing.
- **Evidence:** the tuple, the added file, the verify tuple.

#### ADV-043 — Rollback and uninstall actually remove the code  🖥
- **Surface:** `POST /api/skills/marketplace/uninstall` (admin) · `POST /api/skills/marketplace/{name}/rollback` (admin)
- **Why it matters:** if install executes code, uninstall must remove it — and this chapter has already found one "delete" that copies.
- **Steps:** install the inert skill, uninstall it, check the directory and the registry, restart, check again.
- **Expected:** gone from both, and it does not reappear at boot.
- **FAIL if:** files or registry entries survive → **MAJOR**, and cross-file it against §15.2's theme.
- **CROSS:** the directory listing and `GET /skills` after restart.
- **Evidence:** all four states.

#### ADV-044 — The published/marketplace path uses the same verification  ⏱
- **Surface:** `POST /api/skills/marketplace/publish` (admin) · `POST /api/skills/marketplace/review` (admin)
- **Why it matters:** a second entry point with different checks would be a separate finding.
- **Steps:** trace both handlers to whatever they call for trust.
- **Expected:** a single shared verification path.
- **FAIL if:** they diverge → report the weaker one.
- **CROSS:** the loader source.
- **Evidence:** the traced call chains.

#### ADV-045 — What the fix must not break  ⏱
- **Surface:** `agents/core/skills/signing.py`
- **Why it matters:** `require_signed()` failing closed with no key will refuse **every** skill on a hardened host — including the 11 bundled ones. That is correct behaviour, but it is a breaking change and the report should say so.
- **Steps:** enumerate what would stop loading under the proposed fix.
- **Expected:** a concrete list plus the migration (ship signatures, or configure a key).
- **FAIL if:** the list is larger than expected — that is worth knowing before the fix, not after.
- **CROSS:** the bundled skills directory.
- **Evidence:** the list.

#### ADV-046 — Confirm the audit's priority ordering for yourself  ⏱
- **Surface:** §15.3 as a whole
- **Why it matters:** the audit's instruction is "prioritise the import-time exec, not the hash". Test that this ordering is right *on this build* rather than accepting it.
- **Steps:** ask: at the shipped default, which of the two is reachable and which is not? Write one paragraph.
- **Expected:** exec is reachable at the default; the hash weakness bites only after hardening. So the ordering holds.
- **FAIL if:** your build reverses this (e.g. hardening is on by default here) → say so; the priority flips.
- **CROSS:** `.env.example` and whatever the install script sets.
- **Evidence:** the paragraph plus the default config.

---

## 15.4 The strict-local guarantee at the synthesis seam

**Audit verdict: PARTIAL · High · `agents/core/agent.py`.** The audit calls its own correction here
"the most important correction in the audit". Mechanism: `Agent.synthesize` concatenates every
non-jarvis responder's raw text and then calls `select_backend(self.id, prompt)` with `self.id ==
"jarvis"`; `LOCAL_ONLY_AGENTS` is enforced on the *responding* agent, never on the synthesis pass.
And it is not limited to multi-agent turns — `was_synthesized = len(responses) > 1 or "jarvis" not in
responses`, so a single-specialist turn goes through synthesis too.

**Reachability, corrected:** the original default-config demo was an artifact of an oversized stub
reply. Four maxed specialist replies measure under the 8,000-token threshold, and this deployment's
`llm.hybrid_local_max` default is **131072**, which kills the size path entirely. The live
precondition is a cloud key **plus** the `/admin` knob `llm.cloud_fallback = "always"`. So: **a hole
with no compensating guard, not an active leak.** This is `BACKLOG.md` SEC-B1, open since 24 July.

#### ADV-047 — The seam exists: synthesis routes as jarvis  ⏱
- **Surface:** `agents/core/agent.py` · `agents/core/llm/hybrid_router.py` · **Auto:** ❌ (see ADV-055)
- **Why it matters:** the mechanism half of the finding, independent of reachability.
- **Steps:** read `Agent.synthesize`: the `agent_reports` concatenation, then `select_backend(self.id, prompt)`. Confirm `LOCAL_ONLY_AGENTS` in `agents/core/llm/hybrid_router.py` and `agents/core/kernel/capabilities.py` — note there are two definitions and check they agree.
- **Expected:** synthesis asks the router about `jarvis`, not about the contributors.
- **FAIL if:** confirmed → the mechanism is real. Do **not** yet call it a leak.
- **CROSS:** the two `LOCAL_ONLY_AGENTS` definitions; if they diverge, that is its own finding.
- **Evidence:** both excerpts.

#### ADV-048 — Single-specialist turns synthesize too  ⏱
- **Surface:** `agents/core/orchestrator.py`
- **Why it matters:** widens the mechanism beyond the "multi-agent" framing a reader would assume.
- **Steps:** find `was_synthesized = len(responses) > 1 or "jarvis" not in responses` and reason through a Howard-only turn.
- **Expected:** it synthesizes.
- **FAIL if:** confirmed → say so explicitly in the report; it changes the exposure estimate.
- **CROSS:** drive a single-specialist turn through `POST /chat` (user) and read the trace.
- **Evidence:** the source line and the trace.

#### ADV-049 — Measure the real prompt size, do not assume it  🤖
- **Surface:** `agents/core/llm/hybrid_router.py`
- **Why it matters:** the audit's own first pass got this wrong via an oversized stub. Repeat the corrected measurement.
- **Steps:** drive a genuine four-specialist turn on a local model; capture the actual synthesis prompt; count its tokens.
- **Expected:** well under the size threshold. Record the number.
- **FAIL if:** you exceed the threshold on real replies → the size path is live on this deployment, which would be a *stronger* finding than the audit's. Report it as such with the token count.
- **CROSS:** your count vs `llm.hybrid_local_max` from `GET /api/admin/settings/llm` (admin).
- **Evidence:** the prompt (redacted), the count, the setting.

#### ADV-050 — Confirm the live precondition on this host  🔑
- **Surface:** `GET /api/admin/settings/llm` (admin) · `agents/core/settings_db.py`
- **Why it matters:** determines whether this is theoretical or live *here*.
- **Steps:** read `llm.cloud_fallback` and `llm.hybrid_local_max`; check whether any cloud key is configured.
- **Expected:** on a default install, `cloud_fallback` is `on-demand` and `hybrid_local_max` is 131072 → not reachable.
- **FAIL if:** `cloud_fallback` is `always` **and** a cloud key is present → the hole is live on this box. **BLOCKER**, and stop and tell the owner before continuing.
- **CROSS:** the settings API and the router's `set_cloud_fallback_mode`.
- **Evidence:** the settings body (redact keys — presence only).

#### ADV-051 — Force the precondition in a scratch config and observe  🤖 🔑
- **Surface:** `agents/core/agent.py` · `agents/core/observability/egress_monitor.py`
- **Why it matters:** turning the knob deliberately is the only honest way to prove the hole. Do it on a scratch config, never on the owner's.
- **Steps:** on a throwaway data root with `cloud_fallback = "always"` and a **disposable** key, drive a turn that routes to a strict-local agent, and watch the egress monitor.
- **Expected:** determine whether a strict-local agent's raw output reaches a cloud backend through synthesis.
- **FAIL if:** it does → **BLOCKER** for the one rule the documentation calls non-negotiable. If you will not use a real key, mark **NOT-REPRODUCIBLE** and say so; do not infer from the code alone.
- **CROSS:** `GET /api/admin/network/calls` (admin) — the egress monitor is the second source, and it is the right one.
- **Evidence:** the egress rows.

#### ADV-052 — Which agents are strict-local, and does the family agent qualify?  ⏱
- **Surface:** `agents/core/llm/hybrid_router.py` · `agents/core/kernel/capabilities.py`
- **Why it matters:** the severity of SEC-B1 comes from *whose* data it is.
- **Steps:** read both `LOCAL_ONLY_AGENTS` sets and map each id to what it holds.
- **Expected:** the family/personal agents are in the set.
- **FAIL if:** the two sets differ → a policy split-brain; report separately from SEC-B1.
- **CROSS:** `AGENTS.md` — what does the documentation promise about these agents?
- **Evidence:** both sets and the doc line.

#### ADV-053 — Not Claude, either — check the cloud-agent set  ⏱
- **Surface:** `agents/core/llm/hybrid_router.py`
- **Why it matters:** the audit notes jarvis is not in `CLAUDE_AGENTS`, so the exposure is Gemini-shaped specifically. Precision here keeps the report credible.
- **Steps:** read the cloud-agent sets and determine which provider a synthesis pass would actually reach.
- **Expected:** a named provider, not "the cloud".
- **FAIL if:** you cannot determine it → say so rather than generalising.
- **CROSS:** the egress monitor's recorded destination from ADV-051.
- **Evidence:** the set plus the destination.

#### ADV-054 — The proposed fix, tested at the right boundary  ⏱
- **Surface:** `agents/core/agent.py`
- **Why it matters:** the audit says to test at the synthesize boundary, not at `select_backend` — a test at the router can pass while the seam leaks.
- **Steps:** write (do not merge) a test asserting that a response set containing a strict-local contributor never selects cloud for synthesis. Confirm it is red under ADV-051's forced config.
- **Expected:** red now.
- **FAIL if:** green → your test is at the wrong boundary; move it.
- **CROSS:** `_compression_summarizer` already uses the fail-closed `llm_router.local_backend` — that is the pattern the fix should copy.
- **Evidence:** the test and its failure.

#### ADV-055 — `_synthesize` and the handoff path have no coverage  ⏱
- **Surface:** `agents/core/orchestrator.py` · `agents/core/agent.py`
- **Why it matters:** the audit instrumented all 81 orchestrator test files: `_synthesize` is called 0 times, `HANDOFF_PREFIX` appears in no test file, and mutating both leaves ~1,015 tests green. **The untested code is the code with the policy hole.**
- **Steps:** mutate `_synthesize` to return a garbage string and `_detect_handoff` to return `None`; run the orchestrator test files; count failures.
- **Expected:** near-zero failures. Record the exact number.
- **FAIL if:** confirmed → **MAJOR** as a coverage finding, and it explains ADV-047 existing at all.
- **CROSS:** grep the test tree for `HANDOFF_PREFIX` and for `synthesize`.
- **Evidence:** the mutation diff and the pass/fail counts. **Revert the mutation.**

#### ADV-056 — The merge logic itself *is* covered  ⏱
- **Surface:** `agents/core/agent.py`
- **Why it matters:** precision again — `Agent.synthesize`'s merge logic is covered; the glue and the `in_character` branch are not. A report that says "synthesis is untested" is wrong.
- **Steps:** find the tests that do exercise `Agent.synthesize`; check whether any passes `in_character=True`.
- **Expected:** merge covered, `in_character` not.
- **FAIL if:** you cannot find any coverage → widen the finding, with evidence.
- **CROSS:** the mutation result from ADV-055.
- **Evidence:** the test names.

#### ADV-057 — One golden-loop turn would light all of it up  🤖
- **Surface:** end-to-end
- **Why it matters:** the audit's cheapest recommendation: a single turn routed to a specialist exercises `_synthesize`, the `in_character` branch and the whole handoff path.
- **Steps:** drive exactly that turn manually against a local model and confirm all three execute (log statements or a debugger).
- **Expected:** all three run.
- **FAIL if:** any does not → the recommended test would not cover what it claims; say so.
- **CROSS:** the trace for that turn.
- **Evidence:** the trace with the three sites marked.

#### ADV-058 — Cross-check against the RUN-2 language rail  🤖
- **Surface:** `agents/core/orchestrator.py` · **Auto:** ✅tests/test_qa_run2_fabrication_fixes.py
- **Why it matters:** RUN 2 added a shared `_language_block` after finding a cross-cutting rule living in one persona. Synthesis is the other place a cross-cutting rule could be lost.
- **Steps:** drive a Romanian multi-agent turn; check the synthesized reply mirrors the language.
- **Expected:** Romanian in, Romanian out, through synthesis too.
- **FAIL if:** the synthesized reply switches language → the same class as RUN-2's CHT-070 at a second seam. **MAJOR**.
- **CROSS:** §02's CHT-070 case and the shipped test.
- **Evidence:** both turns verbatim.

---

## 15.5 Per-agent identity collapses to a scalar

**Audit verdict: PARTIAL · Medium · `agents/core/orchestrator.py`.** Same root cause as §15.4, in a
second consumer. One `route_name` is computed from `target_agents[0]` and passed through into the
per-agent loop, so **every** agent that answered is recorded with the primary's route. The audit
reproduced it with the real router on a turn targeting two agents where one is pinned to cloud:
`REAL per-agent routes: {'stark': 'local', 'athena': 'cloud'}` vs
`learning.record calls: [('stark','local'), ('athena','local')]` and `locality(): local_pct 100`.

Scope, corrected: the HUD's **streaming** path is unaffected (it selects the backend inside the
per-agent loop). Mis-attribution is confined to `handle_input` callers — Telegram, Discord, voice,
`/chat`, MCP, rooms, webhooks, eval, workflows.

#### ADV-059 — Reproduce the scalar collapse  🤖
- **Surface:** `agents/core/orchestrator.py` · `agents/core/run_history.py`
- **Why it matters:** the privacy dashboard can read 100% local on a turn where half the conversation went to a cloud provider.
- **Steps:** target two agents whose configuration pins them to different backends; drive one turn through `POST /chat` (user); read `RunHistory` and the per-agent records.
- **Expected:** two runs, one route value.
- **FAIL if:** confirmed → **MAJOR**. Record the actual routes vs the recorded ones side by side.
- **CROSS:** the router's real decision (log it) vs what `RunHistory` stored. Two sources, and they will disagree — that disagreement *is* the finding.
- **Evidence:** both mappings.

#### ADV-060 — `local_pct` is wrong on the non-streaming path  🤖
- **Surface:** `GET /api/metrics/north-star` (open) · `agents/core/run_history.py` · `docs/METRICS.md`
- **Why it matters:** `docs/METRICS.md` defines `local_pct` as "% served on-device", and `north_star.py` gates a 50% floor on it. A metric that gates a release must be right.
- **Steps:** after ADV-059, read `GET /api/metrics/north-star` and compare with what you know actually happened.
- **Expected:** the reported percentage overstates local.
- **FAIL if:** confirmed → **MAJOR**, and note that the error is *systematically* in the flattering direction.
- **CROSS:** the egress monitor (`GET /api/admin/network/calls`, admin) — it records real outbound calls and cannot be fooled by the label.
- **Evidence:** the metric, the egress rows, and your ground truth.

#### ADV-061 — The streaming path is genuinely unaffected  🤖 👁
- **Surface:** `POST /chat/stream` (user) · `agents/core/orchestrator.py`
- **Why it matters:** the skeptic's correction. Verify it rather than repeating it.
- **Steps:** drive the same two-agent turn through the HUD (streaming) and re-check the per-agent routes.
- **Expected:** correct per-agent routes.
- **FAIL if:** streaming is *also* wrong → the scope is wider than the audit says; that is a promotion, report it prominently.
- **CROSS:** compare the two `RunHistory` snapshots (streamed vs non-streamed).
- **Evidence:** both snapshots.

#### ADV-062 — Enumerate the affected callers  ⏱
- **Surface:** `agents/core/orchestrator.py`
- **Why it matters:** turns "some callers" into a list the owner can act on.
- **Steps:** grep every caller of `handle_input` (as opposed to `handle_input_stream`).
- **Expected:** a concrete list — the audit names Telegram, Discord, voice, `/chat`, MCP, rooms, webhooks, eval, workflows.
- **FAIL if:** your list is longer → report yours.
- **CROSS:** each caller's module.
- **Evidence:** the grep output.

#### ADV-063 — Does the learning loop mis-train on the bad label?  ⏱
- **Surface:** `agents/core/orchestrator.py`
- **Why it matters:** a wrong dashboard is bad; a wrong *training signal* compounds.
- **Steps:** trace where the per-agent route feeds agent-selection learning; determine whether the collapsed value influences future routing.
- **Expected:** a yes/no with the call chain.
- **FAIL if:** yes → raise severity above the audit's Medium and say why.
- **CROSS:** the learning store's contents after your test turn.
- **Evidence:** the chain and the store.

#### ADV-064 — Unrouted rows are excluded, not guessed  ⏱
- **Surface:** `agents/core/run_history.py`
- **Why it matters:** this is the code doing the *right* thing — "the meter never fabricates a split". Confirm it, both to be fair and because it is the pattern the fix should keep.
- **Steps:** read `locality()`; write rows with an empty route; confirm they land in `unknown` and are excluded from the percentage.
- **Expected:** excluded.
- **FAIL if:** unrouted rows are counted as local → a **third**, worse bug in the same metric.
- **CROSS:** the metric with and without those rows.
- **Evidence:** both computations.

#### ADV-065 — Does `north-star` label its own uncertainty?  ⏱
- **Surface:** `GET /api/metrics/north-star` (open) · `agents/core/observability/north_star.py`
- **Why it matters:** `null` for "no data" is the honest shape and the endpoint reportedly gets it right. Grade it on §1.1.
- **Steps:** on an install with no routed runs, read the endpoint.
- **Expected:** `null`, not `0`, not an invented split. (F1 = PASS.)
- **FAIL if:** it invents a number → **BLOCKER (F4)**, and it would contradict the audit's refutation of the "north star is structurally unreadable" claim.
- **CROSS:** §15.11's re-test of that refutation.
- **Evidence:** the empty-state body.

#### ADV-066 — The fix shape closes two findings at once  ⏱
- **Surface:** `agents/core/orchestrator.py`
- **Why it matters:** the audit's third recommendation — return a `{agent_id: route}` map from `_call_agents_parallel` into `_record_interactions`, and the same per-agent identity discipline closes the §15.4 hole.
- **Steps:** locate both call sites and confirm the map would be available at each.
- **Expected:** a one-paragraph feasibility note.
- **FAIL if:** the map is not reachable at one of them → the "one change fixes both" claim is optimistic; say so.
- **CROSS:** the two functions.
- **Evidence:** the note.

#### ADV-067 — The route label vocabulary  ⏱
- **Surface:** `agents/core/run_history.py`
- **Why it matters:** `locality()` classifies "local unless the route starts with cloud or is a known cloud route". A new backend with an unexpected name would silently count as local.
- **Steps:** enumerate every route name the router can emit; check each against the classifier.
- **Expected:** full coverage.
- **FAIL if:** any cloud-ish route name is not matched → a latent mis-count independent of ADV-059. Report separately.
- **CROSS:** the router's route-name constants.
- **Evidence:** the two lists.

#### ADV-068 — Live: does the privacy dashboard show the same wrong number?  👁
- **Surface:** Console → the privacy/locality surface · `frontend/src/gap.tsx`
- **Why it matters:** the HUD is where the owner forms a belief.
- **Steps:** after ADV-059, look at the locality display.
- **Expected:** it shows whatever the API says.
- **FAIL if:** it shows a confident percentage with no indication that half the turn is unattributed → **MAJOR** (F3 — unlabelled).
- **CROSS:** the API body.
- **Evidence:** the screenshot plus the body.

---

## 15.6 The honesty badge is wrong in both directions

**Audit verdict: CONFIRMED · Medium · `agents/core/plugins/honesty.py`.** A plugin exposing none of
`configured` / `available` / `_configured` falls through to `(True, "loaded")`, and `"loaded"` maps to
*live / no setup required*. The badge was written specifically to stop mock reading as real, and it is
wrong on exactly the plugins it was written for.

The audit found a third false-live beyond the original two: one plugin has no `configured` attribute
(so it badges green) **and** no `degradation_info()` (so there is no amber MOCK chip beside it),
while `honesty.py` itself lists the token it needs. Unlike the other two, that row is a clean green
lie rather than a visible contradiction.

#### ADV-069 — Reproduce the self-contradiction statically  ⏱
- **Surface:** `agents/core/plugins/honesty.py` · `agents/core/routers/plugins.py`
- **Why it matters:** the defensible form of this claim is narrow: a plugin whose id is in `_NEEDS` (the module says it needs a key) *and* whose class exposes no attribute that could ever report `configured=False`. Keyless plugins badging green is correct, not a defect.
- **Steps:** `python scripts/qa_audit_probes.py honesty`. Read `needs_a_key_but_badges_live`, `green_with_no_mock_chip` and `amber_with_an_empty_needs_list`.
- **Expected:** a short list of contradicted plugins, with the specific one that has no MOCK chip called out.
- **FAIL if:** any entry appears → **MAJOR** on §1.1 (F3, unlabelled seed/mock as live). The clean-green one is worse than the ones rendering `[MOCK]` beside the green.
- **CROSS:** a real keyless boot (ADV-070). The probe reads source; the badge is a runtime verdict.
- **Evidence:** the probe JSON.

#### ADV-070 — Live: boot with no keys and read `GET /plugins`  🖥
- **Surface:** `GET /plugins` (open) · `agents/core/routers/plugins.py`
- **Why it matters:** the runtime is the authority; the probe is the lead.
- **Steps:** boot with no plugin keys configured. `curl -s "$B/plugins"` and read each row's `honesty.status`, `configured`, `configuration_source`, `degraded`.
- **Expected:** for each plugin named by ADV-069: `status: live`, `configuration_source: "loaded"`.
- **FAIL if:** confirmed → this is the finding. Paste the rows verbatim.
- **CROSS:** call the plugin and see what it returns. A green badge over a mock return value is the two-source proof.
- **Evidence:** the rows and the call result.

#### ADV-071 — The mock return values are the ground truth  🖥
- **Surface:** the plugins named in ADV-069
- **Why it matters:** "it badges live" is an inference until you see it return a mock.
- **Steps:** trigger each contradicted plugin's primary capability with no key configured; capture the return.
- **Expected:** an obvious mock/placeholder value.
- **FAIL if:** green badge + mock value → **MAJOR** confirmed on two sources.
- **CROSS:** the badge from ADV-070.
- **Evidence:** the returns (redact nothing here — they are fake by construction, which is the point).

#### ADV-072 — The rollup count is a clean misstatement  👁
- **Surface:** `GET /plugins` (open) · `agents/core/routers/plugins.py`
- **Why it matters:** the response computes `live` as a count of `honesty.status == "live"`, so every false-live inflates a headline number the owner reads at a glance.
- **Steps:** read the rollup; subtract the plugins you proved are mock.
- **Expected:** a specific overstatement, expressed as *reported N, actually M*.
- **FAIL if:** confirmed → **MAJOR**, and it is the single most owner-visible instance.
- **CROSS:** your per-row verdicts.
- **Evidence:** the number and your arithmetic.

#### ADV-073 — Amber with an empty `needs` list  👁
- **Surface:** `GET /plugins` (open) · `agents/core/plugins/analytics.py` · `frontend/src/modes3.tsx`
- **Why it matters:** the other direction — the one keyless plugin with a real local capability badges *amber* with nothing actionable in `needs`, because its `available()` reports only an optional cloud mirror.
- **Steps:** read that plugin's row; then read `HonestyBadge` — an amber chip's tooltip is built from `needs`.
- **Expected:** `NEEDS SETUP` with an empty needs list → a tooltip that names nothing.
- **FAIL if:** confirmed → **MINOR/MAJOR** (your call): it tells the owner to configure something and cannot say what.
- **CROSS:** actually use the plugin — it works, which proves the badge wrong in the pessimistic direction.
- **Evidence:** the row, the tooltip, and a successful call.

#### ADV-074 — Where else does the honesty verdict flow?  ⏱
- **Surface:** `agents/core/observability/capability_registry.py` · `GET /api/capabilities` (user) · `GET /api/metrics/capabilities` (open)
- **Why it matters:** the badge is not the only consumer. A wrong verdict propagating into the capability registry is a bigger problem than a wrong chip.
- **Steps:** trace `honesty_for`'s callers; read both capability endpoints for the contradicted plugins.
- **Expected:** an enumerated blast radius.
- **FAIL if:** a false-live verdict reaches a capability/readiness surface → escalate above the audit's Medium.
- **CROSS:** the two endpoints against `GET /plugins`.
- **Evidence:** the three payloads for the same plugin.

#### ADV-075 — The one-line fix the audit proposes  ⏱
- **Surface:** `agents/core/plugins/honesty.py` · `agents/core/routers/plugins.py`
- **Why it matters:** makes the report actionable: let `degradation_info()` override the verdict to `needs_config`; stop treating `"loaded"` as keyless; default unknown plugins to `unknown`.
- **Steps:** confirm each of the three is implementable where the audit says. Note that the override alone does **not** fix the clean-green plugin, which has no `degradation_info()` — that one needs a `configured` attribute.
- **Expected:** two of three fixes are one line; the third is per-plugin.
- **FAIL if:** you conclude the override would fix all of them → re-read; that is the trap this case exists to catch.
- **CROSS:** the probe's `has_degradation_info` flags.
- **Evidence:** your note.

#### ADV-076 — A third status would be more honest than a boolean  ⏱
- **Surface:** `agents/core/plugins/honesty.py`
- **Why it matters:** `live` / `needs_config` cannot express "I do not know", which is the true state for a plugin with no contract.
- **Steps:** enumerate plugins for which neither verdict is true.
- **Expected:** a list. Any non-empty list argues for an `unknown` status.
- **FAIL if:** empty → the binary is sufficient; record that and drop the recommendation.
- **CROSS:** `frontend/src/modes3.tsx` — `HonestyBadge` renders nothing for an unrecognised status today, which is already the honest fallback.
- **Evidence:** the list.

#### ADV-077 — Does the frontend test pin the wrong behaviour?  ⏱
- **Surface:** `frontend/src/test/honesty-badge.test.tsx`
- **Why it matters:** a test asserting the current (wrong) verdict would have to change with the fix — worth knowing in advance.
- **Steps:** read the test; determine whether it pins the mapping or only the rendering.
- **Expected:** rendering only, most likely.
- **FAIL if:** it pins `"loaded" → live` → flag it as a contract change in the report, the way the audit does for the reality-harness test.
- **CROSS:** the component source.
- **Evidence:** the test excerpt.

---

## 15.7 Nothing measures or caps LLM spend

**Audit verdict: CONFIRMED · Medium · `agents/core/cost_tracker.py`.** From the completeness critic.
`cost_tracker.record()` is never called from the router or from a backend's `generate`, and the
tracker is process-memory only, so even a fed meter resets each boot. `estimate_cost` returns `0.0`
for an unpriced model rather than `None`, so dashboards render a confident zero instead of "unknown".
Three cost endpoints are wired and all green-looking.

#### ADV-078 — The meter has no producer  ⏱
- **Surface:** `agents/core/cost_tracker.py` · `agents/core/llm/hybrid_router.py` · **Auto:** ❌
- **Why it matters:** three endpoints read a counter nothing increments.
- **Steps:** `python scripts/qa_audit_probes.py cost`. Then grep independently for any call to the tracker's `record` outside its own module.
- **Expected:** no call sites.
- **FAIL if:** confirmed → **MAJOR** (the audit graded Medium; argue your own — the first design partner cannot answer "what did this cost me last month", and that lands on the A7 gate).
- **CROSS:** drive real LLM traffic, then read `GET /api/cost` (user). Traffic in, zero out, is the two-source proof.
- **Evidence:** the grep, the traffic, the endpoint body.

#### ADV-079 — An unpriced model reports a confident zero  ⏱
- **Surface:** `agents/core/llm/cost_estimator.py`
- **Why it matters:** `0.0` and "unknown" are different claims, and one of them is a fabrication under §1.1.
- **Steps:** call `estimate_cost` with a model name nobody has priced. The probe prints this.
- **Expected:** an all-zero cost dict.
- **FAIL if:** confirmed → grade **F4-adjacent**: an invented specific (a number) where the honest answer is "I do not know". `None` is the correct return.
- **CROSS:** whatever the dashboards render for that model.
- **Evidence:** the dict and the rendered value.

#### ADV-080 — All three cost endpoints are structurally zero  🖥
- **Surface:** `GET /api/cost` (user) · `GET /api/analytics/cost` (open) · `GET /api/admin/apm` (admin)
- **Why it matters:** three surfaces telling the same untrue story is three chances for the owner to believe it.
- **Steps:** drive real traffic; read all three.
- **Expected:** zeros, or an honest "no cost data".
- **FAIL if:** any renders a confident zero **after** real cloud traffic → **MAJOR (F3/F4)** per surface. If one says "no data", that one passes — record the difference.
- **CROSS:** your provider's own usage page if a cloud key is in play, or the request count from the egress monitor.
- **Evidence:** the three bodies plus the traffic count.

#### ADV-081 — `GET /api/analytics/cost` is open-tier  🌐
- **Surface:** `GET /api/analytics/cost` (open)
- **Why it matters:** a cost surface is a usage-pattern surface. Once it has real data, its tier matters.
- **Steps:** call it with no token; cross-check `tests/_snapshots/route_auth.json`.
- **Expected:** open, matching the snapshot.
- **FAIL if:** it will expose spend patterns to an unauthenticated LAN caller once fed → file as a **pre-emptive** finding: harmless today precisely because the meter is empty, which is a poor reason for it to be open.
- **CROSS:** the §14 sweep row and §08's tier rules.
- **Evidence:** the status code and the snapshot line.

#### ADV-082 — The tracker resets every boot  ⏱
- **Surface:** `agents/core/cost_tracker.py`
- **Why it matters:** even after the meter is fed, "last month" remains unanswerable without persistence.
- **Steps:** read the store; restart the server; re-read.
- **Expected:** in-memory only.
- **FAIL if:** confirmed → the fix is two parts (feed it **and** persist it); say both in the report.
- **CROSS:** whether any other store already records per-call model usage that could be summed instead (`RunHistory`? traces?). If one does, the fix is cheaper than it looks — a genuinely useful finding.
- **Evidence:** the pre/post-restart values and your search.

#### ADV-083 — There is no spend cap  ⏱
- **Surface:** `agents/core/llm/hybrid_router.py` · `agents/core/settings_db.py`
- **Why it matters:** an unattended night-shift loop on a cloud key has no ceiling and produces no signal anywhere. That is the actual risk; the dashboard is the symptom.
- **Steps:** search the settings catalogue and the router for any daily/monthly cost limit.
- **Expected:** none.
- **FAIL if:** confirmed → **MAJOR**, and note the audit's proposed shape: `llm.daily_cost_cap_usd` checked in `select_backend` before a cloud route.
- **CROSS:** §07's autonomy budget surfaces — is there a *token* budget that partially compensates? If yes, say so; it changes the severity.
- **Evidence:** the search plus whatever budget does exist.

#### ADV-084 — Kernel budgets are not a cost cap  ⏱
- **Surface:** `agents/core/kernel/` budget seam · `docs/THREAT_MODEL.md` T3
- **Why it matters:** T3 claims a per-task token/wall-time ledger and a circuit breaker. Determine honestly whether that covers spend.
- **Steps:** read what the budget ledger bounds and at what scope.
- **Expected:** per-task, per-loop — not per-day and not in currency.
- **FAIL if:** it does cover spend → ADV-083 is wrong; correct it. That would be a good outcome.
- **CROSS:** `GET /api/metrics/kernel` (open) after real traffic.
- **Evidence:** the ledger scope plus the metric.

#### ADV-085 — Does any HUD surface promise cost tracking?  👁
- **Surface:** the Console cost/APM panels · `frontend/src/gap.tsx`
- **Why it matters:** a panel titled "cost" showing 0.00 is a stronger claim than an empty endpoint.
- **Steps:** find every cost display; screenshot each after real traffic.
- **Expected:** an inventory with each one's honesty grade.
- **FAIL if:** any renders `$0.00` as a fact → **MAJOR (F3)**. "No cost data — the meter is not wired" would be a PASS.
- **CROSS:** the endpoint bodies.
- **Evidence:** the screenshots.

#### ADV-086 — What the fix must produce  ⏱
- **Surface:** §15.7 as a whole
- **Why it matters:** turns four cases into one actionable paragraph.
- **Steps:** state the four parts: call `record()` from the router with the model that actually ran; persist it; return `None` for unpriced models; add a cap checked before a cloud route.
- **Expected:** each maps to a named file.
- **FAIL if:** any part has no obvious home → say so; that is a design question for the owner.
- **CROSS:** the audit's own recommendation.
- **Evidence:** the paragraph.

---

## 15.8 Evidence that grades its own homework

**The audit's systemic finding.** Five of six lenses independently found a gate that checks the
*shape* of a claim rather than its substance. These are not the same bug; they are the same reflex —
build a gate, watch it go green, write the green into `STATUS.md`. This section tests the gates.

#### ADV-087 — The action-capability probe certifies its declared actuator  ⏱ ✅
- **Surface:** `agents/core/observability/reality_harness.py` · `agents/core/capability_manifests.py` · **Auto:** `tests/test_h27_capability_verification.py`
- **Why it matters:** a refusal rail is not proof that the declared actuator exists. The promotable case must resolve `manifest.implementation` before it may certify the capability.
- **Steps:** `python scripts/qa_audit_probes.py reality`. Then run the missing-implementation and implementation-evidence tests in `tests/test_h27_capability_verification.py`.
- **Expected:** the probe reports implementation resolution; a nonexistent actuator fails closed; a green result names the resolved implementation in evidence metadata.
- **FAIL if:** a missing implementation still passes or the green evidence cannot identify what it certified.
- **CROSS:** ADV-088's import-blocking run — that is the empirical half.
- **Evidence:** fixed by PR #897; cross-confirmed in the [ADV-098 coverage run](../qa-runs/2026-08-12-hermetic-adv-reality-coverage.md).

#### ADV-088 — Block the actuator imports; the pack still passes  ⏱
- **Surface:** `agents/core/observability/reality_harness.py`
- **Why it matters:** the skeptic went further than the original finding, and this is the step that makes it undeniable.
- **Steps:** install a `sys.meta_path` blocker that raises on import of the payments, node-mesh, house-actuation, call-broker and desktop-operator modules; run the action reality cases.
- **Expected:** the same pass and promote counts as without the blocker.
- **FAIL if:** confirmed → the criterion measures nothing about actuators. Record the exact counts both ways.
- **CROSS:** ADV-087's static reading. Static + empirical is the two-source rule satisfied.
- **Evidence:** both runs' counts.

#### ADV-089 — But nobody is misled *today* — verify the mitigation  🖥
- **Surface:** `GET /api/capabilities` (user) · `GET /api/metrics/capabilities` (open)
- **Why it matters:** the audit graded this Medium precisely because `run_reality` has no caller under `agents/`, promotion is in-process, and the registry reseeds each boot. Confirm that on a live install before you write "misleading".
- **Steps:** grep for callers of `run_reality` outside `tests/`. Then read both capability endpoints on a running server.
- **Expected:** no product caller; the live board reports zero verified capabilities and every action record as pending/wired.
- **FAIL if:** a live install *does* report verified action capabilities → the finding is live, not latent. **Escalate to MAJOR** and lead the report with it.
- **CROSS:** the grep and the two endpoints.
- **Evidence:** all three.

#### ADV-090 — The real packs are marked not-promotable, and that was the honest call  ⏱
- **Surface:** `agents/core/observability/operator_reality.py` · `agents/core/observability/house_reality.py`
- **Why it matters:** fairness, and it sharpens the finding: the owner refused to let the *real* packs promote while the stub-handler case promotes the same capability ids.
- **Steps:** read the metadata on the real packs — `promotable` and `live_owner_validation`.
- **Expected:** not promotable; live owner validation required.
- **FAIL if:** any real pack is promotable without live validation → a different and worse finding.
- **CROSS:** §12's AIO-003, which asserts the same metadata from the hardware side.
- **Evidence:** the metadata lines.

#### ADV-091 — The H33 ambient safety counters are integer literals  ⏱
- **Surface:** `agents/core/observability/ambient_reality.py` · **Auto:** ✅tests/test_h33_ladder_engine.py (the property *is* covered — see ADV-092)
- **Why it matters:** `STATUS.md` reads "the ambient pack emits no ungoverned action" as evidence. The counter is assigned, not measured.
- **Steps:** `python scripts/qa_audit_probes.py ambient`. Then read the counters dict yourself.
- **Expected:** the safety counters are constants in the returned dict.
- **FAIL if:** confirmed → grade it **evidence honesty**, not an untested safety property, and say why in the same sentence. Also check `STATUS.md` for the overclaim.
- **CROSS:** run `tests/test_h33_ladder_engine.py` — the property has positive and negative cases there, and both fail under the same mutation. That is what keeps this Medium.
- **Evidence:** the literals, the passing ladder tests, and the `STATUS.md` line.

#### ADV-092 — Two tests pin the behaviour a fix would change  ⏱
- **Surface:** `tests/test_reality_harness.py`
- **Why it matters:** the audit flags this explicitly: `test_green_action_case_promotes_only_through_reality_runner` pins the present behaviour, so fixing ADV-087 is a **deliberate contract change**, not a bug fix. A report that omits this sets up a confusing PR.
- **Steps:** read that test and any sibling pinning promotion.
- **Expected:** it asserts the current promotion path.
- **FAIL if:** it asserts something stronger than you thought → adjust the recommendation.
- **CROSS:** the harness source.
- **Evidence:** the test excerpt.

#### ADV-093 — Gutting the proposal sink leaves the ambient pack green  ⏱
- **Surface:** `agents/core/observability/ambient_reality.py`
- **Why it matters:** the empirical half of ADV-091 — proposals drop to zero and the pack stays green.
- **Steps:** temporarily neuter the proposal sink; re-run the pack; compare proposal counts and pass state. **Revert.**
- **Expected:** proposals collapse, pack still passes.
- **FAIL if:** confirmed → this is the crisp demonstration; put the two numbers in the report.
- **CROSS:** the ladder tests, which *do* fail under the same mutation.
- **Evidence:** both counts, both suites.

#### ADV-094 — Degraded no-ops are recorded as ledger successes  ⏱
- **Surface:** `agents/core/autonomy/worker.py` · `agents/core/plugins/degradation.py` · `GET /api/capabilities` (user)
- **Why it matters:** `_record_capability_outcome` skips only a literal `noop` status; `is_degraded()` has no production callers. So a capability that returned a mock records a success, and `success_rate` rises for capabilities that never delivered anything.
- **Steps:** read both functions; grep for `is_degraded` callers outside `tests/`; then drive a degraded (keyless) capability through the autonomy path and read `GET /api/capabilities`.
- **Expected:** no production caller of `is_degraded`; the outcome records as success.
- **FAIL if:** confirmed → **MAJOR** as a misleading dashboard. **Then check the correction below before grading higher.**
- **CROSS:** the capability's actual return value (a mock) vs its recorded outcome.
- **Evidence:** both.

#### ADV-095 — …but the claimed autonomy escalation does not occur  ⏱
- **Surface:** `agents/core/autonomy/worker.py`
- **Why it matters:** the skeptic's correction. Every degraded seam hardcodes `ask`, and the enqueue takes the stricter level, so a rising confidence score does **not** loosen governance. Without this, ADV-094 gets over-graded.
- **Steps:** trace whether rising `success_rate`/confidence can change the autonomy level applied to a real action.
- **Expected:** it cannot — the stricter level wins.
- **FAIL if:** you find a path where it can → **BLOCKER**, and it is a genuinely new finding beyond the audit.
- **CROSS:** §07's autonomy-level cases.
- **Evidence:** the trace.

#### ADV-096 — The parity gate classifies instead of covering  ⏱
- **Surface:** `tests/test_hud_v2_parity.py`
- **Why it matters:** the gate's docstring says it stops a capability being silently dropped from the HUD. It prefix-matches a URL.
- **Steps:** `python scripts/qa_audit_probes.py parity`. Then call `_classify` yourself on a path that does not exist.
- **Expected:** an invented path resolves to a surface and the gate stays green.
- **FAIL if:** confirmed → **MAJOR** as a gate defect (not a product defect — say which).
- **CROSS:** the five per-feature tests in the same file, which **do** assert that specific panels call their routes. That is the pattern the fix should generalise, and mentioning it keeps the report fair.
- **Evidence:** the classification result plus one of the good tests.

#### ADV-097 — Count the routes with no caller in any client  ⏱
- **Surface:** `tests/_snapshots/route_surface.json` · `frontend/src/` · `mobile/`
- **Why it matters:** the audit's corrected figure is roughly 68 of 358 user-facing routes with no caller anywhere in the repo — down from a first-pass 86 of 313, because about 16 were inbound or machine-facing endpoints misclassified by the rules map. Re-measure; do not copy either number.
- **Steps:** for each route in the snapshot, grep the frontend, mobile and any other client for its path. Exclude inbound/webhook/machine-facing routes deliberately, and **list your exclusions**.
- **Expected:** your own number, with the method stated.
- **FAIL if:** your number differs materially from 68 → report yours and say why; that is more useful than agreement.
- **CROSS:** chapter 14's generated sweep, which enumerates the same route set from the same snapshot.
- **Evidence:** the list, the exclusions, and the count.

#### ADV-098 — The capability-readiness matrix's escape set  ⏱ ✅
- **Surface:** `agents/core/observability/reality_harness.py` · `tests/test_capability_readiness_matrix.py`
- **Why it matters:** an empty escape set is meaningful only when computed against the declared proof cases. The matrix must reject missing, duplicate, mismatched, and explicitly non-promotable bindings.
- **Steps:** run the readiness-matrix coverage test and the adversarial binding test in `tests/test_h27_capability_verification.py`; count proof-eligible records and gaps.
- **Expected:** `PENDING_VERIFY` exactly equals the computed gap IDs, with a reason for each. On current `main`: 94 records, 93 proof-eligible, 133 cases, 0 gaps.
- **FAIL if:** the computed gap IDs differ from `PENDING_VERIFY`, or any malformed binding is accepted as coverage.
- **CROSS:** `GET /api/metrics/capabilities` (open).
- **Evidence:** [2026-08-12 hermetic ADV reality-coverage run](../qa-runs/2026-08-12-hermetic-adv-reality-coverage.md).

#### ADV-099 — The route-auth matrix is the counter-example — verify it  ⏱
- **Surface:** `tests/_snapshots/route_auth.json` · `tests/test_hud_v2_parity.py`
- **Why it matters:** the audit calls the route-auth matrix "the best gate in the repo" — it reads each route's resolved FastAPI dependant graph (ground truth, not AST, not a hand-maintained list), pins every guard, and forces every open mutating route into an explicit escape set. Verify that, because it is the template the other gates should copy.
- **Steps:** add a new mutating route with no guard on a scratch branch; run the matrix.
- **Expected:** it fails, naming your route.
- **FAIL if:** it passes → the best gate is not what it claims, which would be the most important finding in this section. **Revert your scratch route** either way.
- **CROSS:** the escape set's contents.
- **Evidence:** the failure output.

#### ADV-100 — Mutation-test the security core  ⏱
- **Surface:** `agents/core/security/` · `agents/core/kernel/`
- **Why it matters:** the audit's positive finding — six independent mutations (admin guard, user guard, taint detection, policy classification, egress enforcement, embedding store) were each killed by multiple tests. Confirm the good news with the same rigour as the bad.
- **Steps:** pick three of the six; mutate each minimally; run the suite; record which tests die. **Revert each.**
- **Expected:** multiple failures per mutation.
- **FAIL if:** any mutation survives → a real coverage hole in the security core, and it outranks most of this chapter.
- **CROSS:** the failing test names.
- **Evidence:** three mutation diffs and their failure lists.

#### ADV-101 — Are there gates whose assertion is a constant?  ⏱
- **Surface:** `tests/` · `agents/core/observability/`
- **Why it matters:** generalises ADV-091 into a sweep. This is the highest-value exploratory case in the chapter.
- **Steps:** search for assertions comparing against a literal that is also *assigned* as a literal nearby — a counter, a rate, a count that never comes from a measurement.
- **Expected:** your own list.
- **FAIL if:** you find any beyond the ambient one → each is a new instance of the systemic finding, and finding a new one is the best possible outcome of this chapter.
- **CROSS:** for each candidate, mutate the thing it claims to measure and see whether the gate notices.
- **Evidence:** the list plus one mutation per candidate.

#### ADV-102 — The 0.7%-assert-nothing figure  ⏱
- **Surface:** `tests/`
- **Why it matters:** the audit tested "5,425 tests is real quality evidence" and found it *largely holds*, with 0.7% of tests asserting nothing. Confirm the order of magnitude; a much larger number would change how you read every other green in this chapter.
- **Steps:** count test functions with no `assert` and no assertion helper. State your method.
- **Expected:** a small percentage.
- **FAIL if:** materially higher than ~1% → report the number and the method; it recalibrates the whole suite.
- **CROSS:** spot-check ten of them by hand — some legitimately assert via a helper or a `pytest.raises`.
- **Evidence:** the count, the method, the ten spot-checks.

---

## 15.9 The Telegram allowlist, narrowed

**Audit verdict: PARTIAL · Medium · `agents/web.py`.** `TelegramChannel(...)` is constructed with no
`allowed_user_ids`, so both `if self.allowed_users and ...` guards are no-ops, and the callback
handler applies a decision with no owner binding. This is `BACKLOG.md` SEC-B3.

**Materially narrowed by the skeptic:** the card sender has one caller and sends only to the
configured owner chat id; the callback path is not wired without that setting; a callback query
cannot be synthesised by someone who cannot see the button. **The genuinely default-on half is
different:** channel pairing is off by default, so any Telegram user who finds the bot reaches the
handler — but that runs in a per-chat isolated session with long-term recall off and inbound taint
forcing ASK. Residual exposure is the LLM budget, a prompt-injection foothold, and a shared rate
limit. **Not memory exfiltration** — do not report it as such.

#### ADV-103 — The allowlist is never populated  ⏱
- **Surface:** `agents/web.py` · `agents/core/channels/telegram.py`
- **Why it matters:** the mechanism.
- **Steps:** read the channel construction in `agents/web.py`; check for any parsing of an allowed-user-ids environment variable anywhere.
- **Expected:** constructed without it; no parsing exists.
- **FAIL if:** confirmed → both guards are dead code. **MAJOR** as dead-safety-code; grade the *exploitability* separately (ADV-104).
- **CROSS:** grep the whole repo for the env var name the security-wave plan specified.
- **Evidence:** the construction line and the grep.

#### ADV-104 — Owner binding on the callback  🔑
- **Surface:** `agents/core/channels/telegram.py`
- **Why it matters:** an approval decision applied without checking who pressed the button is the sharpest form of this.
- **Steps:** read the callback handler: does it use the sender's user id and chat id at all before applying the decision?
- **Expected:** they are discarded.
- **FAIL if:** confirmed → **MAJOR**. State the precondition honestly: exploitation requires the owner-chat setting to point at a group.
- **CROSS:** §07's approval-decision cases — the same decision through the HUD is owner-bound.
- **Evidence:** the handler excerpt.

#### ADV-105 — Only one caller, and it targets the owner chat  ⏱
- **Surface:** `agents/core/channels/telegram.py`
- **Why it matters:** the correction that keeps this Medium.
- **Steps:** grep for callers of the card sender; read the destination.
- **Expected:** one caller, configured owner chat id.
- **FAIL if:** more than one caller, or any that broadcasts → the narrowing does not hold and severity rises.
- **CROSS:** the settings key that supplies the chat id.
- **Evidence:** the grep.

#### ADV-106 — Pairing is off by default  🔑
- **Surface:** `GET /api/channels/pairing` (admin) · `POST /api/channels/pairing/request` (open) · `agents/core/channels/gateway.py`
- **Why it matters:** the genuinely default-on exposure.
- **Steps:** on a default install, read the pairing status. Determine whether an unknown Telegram sender reaches the handler.
- **Expected:** pairing off; unknown senders route through.
- **FAIL if:** confirmed → report the *real* residual (budget consumption, injection foothold, shared rate limit), not memory exfiltration.
- **CROSS:** ADV-107's isolation check — that is what bounds the damage.
- **Evidence:** the pairing status and one traced inbound message.

#### ADV-107 — The compensating isolation actually holds  🔑
- **Surface:** `agents/core/channels/gateway.py` · `agents/core/security/taint.py`
- **Why it matters:** the skeptic's claim that a stranger's turn runs in a per-chat isolated session with long-term recall off and inbound taint forcing ASK. If any part is false, the severity jumps.
- **Steps:** verify each of the three independently: session isolation, recall disabled, taint forcing ASK.
- **Expected:** all three hold.
- **FAIL if:** any fails → **BLOCKER**, and it is a new finding beyond the audit. Lead with it.
- **CROSS:** drive an actual inbound message from a non-owner account if you have one, and inspect the session and the resulting task's autonomy level.
- **Evidence:** the three verifications.

#### ADV-108 — The pairing gate fails open on a store error  ⏱
- **Surface:** `agents/core/channels/gateway.py`
- **Why it matters:** the audit found the exception handler defaults to allow, and that those lines are never executed by any test.
- **Steps:** read the `except` around the pairing gate. Then check coverage for those lines.
- **Expected:** on exception, allowed. Zero coverage.
- **FAIL if:** confirmed → **MINOR/MAJOR**. **Include the disproof:** a *blocked* sender cannot get through this way (that path is in-memory and cannot raise), and corrupt JSON normalises to an empty mapping which fails **closed**. The only reachable fail-open is an unknown first-contact sender during a write failure.
- **CROSS:** try to construct the reachable case; if you cannot, say so.
- **Evidence:** the handler, the coverage report, your attempt.

#### ADV-109 — Rate limiting is shared, so a stranger can crowd the owner out  🔑
- **Surface:** `agents/core/channels/gateway.py`
- **Why it matters:** the residual exposure the skeptic named. Availability, not confidentiality.
- **Steps:** find the rate limit applied to inbound channel traffic; determine whether it is per-sender or global.
- **Expected:** shared.
- **FAIL if:** confirmed → **MINOR**, unless the limit is low enough to be a practical denial, in which case **MAJOR**. Say which and give the number.
- **CROSS:** the configured limit value.
- **Evidence:** the code and the number.

#### ADV-110 — Does the HUD show inbound Telegram provenance?  👁
- **Surface:** `GET /api/channels/inbox` · Console → Comms
- **Why it matters:** an owner who can see "this came from an unpaired stranger" is in a different position from one who cannot.
- **Steps:** look at how an inbound thread from an unknown sender is labelled.
- **Expected:** visible provenance and taint.
- **FAIL if:** a stranger's message is indistinguishable from the owner's → **MAJOR (F3)**.
- **CROSS:** the stored thread's taint fields.
- **Evidence:** the screenshot and the stored record.

---

## 15.10 Documented promises the code does not keep

The audit's "not stale docs — promises with a green checkbox next to them". Each case is a
doc-vs-code diff. **Do not edit the docs yourself** — `docs/TEST_MANUAL.md` §6 reserves triage for
the owner. Propose the corrected wording in the report.

#### ADV-111 — `docs/PRIVACY.md` on forget  ⏱
- **Surface:** `docs/PRIVACY.md`
- **Why it matters:** already tested in §15.2; this case files it as a documentation finding with proposed wording, because that is a separate deliverable.
- **Steps:** write the sentence you would replace it with, given ADV-023's diff.
- **Expected:** a sentence that is true on this build and this backend.
- **FAIL if:** you cannot write a true sentence that is still useful → the feature, not the doc, is what has to change. Say that.
- **CROSS:** ADV-023, ADV-028.
- **Evidence:** old and proposed wording.

#### ADV-112 — `docs/THREAT_MODEL.md` calls the kernel "the single front door"  ⏱
- **Surface:** `docs/THREAT_MODEL.md`
- **Why it matters:** the audit found the README's honesty fix was not propagated here. The kernel is an additional **deny** layer, not the only one — and that is a *better* story than the doc tells.
- **Steps:** read the T2 row. Compare with what the payments path actually does with the kernel off (see ADV-121).
- **Expected:** the phrase overstates.
- **FAIL if:** confirmed → **MINOR** as a doc defect, but note it is the one place the correction was missed, which is a process signal worth a sentence.
- **CROSS:** the README's corrected wording.
- **Evidence:** both lines.

#### ADV-113 — `docs/THREAT_MODEL.md` T5 on audit tampering  ⏱
- **Surface:** `docs/THREAT_MODEL.md` · §15.1
- **Why it matters:** T5 says a forged or edited row fails verification. §15.1 shows a fully rewritten table verifies.
- **Steps:** put the T5 sentence next to ADV-001's output.
- **Expected:** direct contradiction.
- **FAIL if:** confirmed → the doc must change with the fix, in the same PR.
- **CROSS:** ADV-001.
- **Evidence:** both.

#### ADV-114 — `docs/METRICS.md` on `local_pct`  ⏱
- **Surface:** `docs/METRICS.md` · §15.5
- **Why it matters:** the doc defines it as "% served on-device"; on the non-streaming path it is not.
- **Steps:** propose wording that is true, or state that the code should change instead.
- **Expected:** here the *code* is what should change — the metric gates a release.
- **FAIL if:** you propose weakening the doc instead → re-read; a north-star metric should not be redefined to match a bug.
- **CROSS:** ADV-060.
- **Evidence:** the line and your recommendation.

#### ADV-115 — The Wyoming server nothing starts  ⏱
- **Surface:** `agents/core/voice/wyoming.py` · `agents/core/routers/wyoming.py` · `GET /api/voice/wyoming` (open) · `GET /api/satellites` (open)
- **Why it matters:** the critic found a backlog item marked completed that ships a server nothing launches. The voice path was never executed by any lens.
- **Steps:** grep for anything that constructs and starts the server class outside tests. Then read the status endpoint on a running install.
- **Expected:** no starter; the status endpoint reports something.
- **FAIL if:** no starter exists → **MAJOR** as a completion-claim defect. **Then check what the status endpoint says** — if it honestly reports "not running", the runtime is honest even though the backlog is not, and that distinction belongs in the report.
- **CROSS:** the endpoint body vs the grep.
- **Evidence:** both.

#### ADV-116 — Three cost endpoints wired to a meter nothing feeds  ⏱
- **Surface:** §15.7
- **Why it matters:** files §15.7 as a documented-promise defect too, since the endpoints are listed as delivered.
- **Steps:** find where the cost capability is claimed complete.
- **Expected:** a claim broader than the code.
- **FAIL if:** confirmed → propose the corrected status line.
- **CROSS:** ADV-078.
- **Evidence:** the claim and the evidence against it.

#### ADV-117 — `JARVIS_ACTION_KERNEL` is absent from `.env.example`  ⏱
- **Surface:** `.env.example`
- **Why it matters:** the audit's residue on an otherwise refuted finding: the flag that unlocks the governed action plane is not discoverable from the example environment file.
- **Steps:** grep `.env.example` for it and for the other kernel/hardening flags this chapter has used.
- **Expected:** absent.
- **FAIL if:** confirmed → **MINOR**, but it is why the "kernel is off by default" confusion arose in the first place. Worth fixing cheaply.
- **CROSS:** the flags actually read by `agents/core/kernel/` and `agents/core/security/hardened.py`.
- **Evidence:** the grep and the flag list.

#### ADV-118 — Sweep: every "✅" in `STATUS.md` that this chapter touched  ⏱
- **Surface:** `STATUS.md` · `BACKLOG.md`
- **Why it matters:** turns individual doc findings into one reviewable list for the owner.
- **Steps:** for each section of this chapter, find the corresponding status claim and mark it holds / overstates / cannot tell.
- **Expected:** a table.
- **FAIL if:** more than a couple overstate → say so as a single systemic observation rather than N separate findings; that is more useful.
- **CROSS:** your own verdicts from this chapter only. Do not import the audit's.
- **Evidence:** the table.

#### ADV-119 — Counters in prose  ⏱
- **Surface:** `project-status.json` · `docs/TEST_MANUAL.md` §5
- **Why it matters:** RUN 2 found four different backend-test counts in the tree at one commit. This chapter must not add a fifth.
- **Steps:** confirm this chapter cites no hard-coded test/route/agent count, and check whether any doc you touched does.
- **Expected:** every count cited by source, never by value.
- **FAIL if:** you find a stale count anywhere → report it; it is cheap and it compounds.
- **CROSS:** `scripts/status_sync.py`'s output.
- **Evidence:** the offending lines.

#### ADV-120 — The claims that *hold* — record them too  ⏱
- **Surface:** `STATUS.md` · `BACKLOG.md`
- **Why it matters:** the audit verified a long list that holds exactly: the route count, the removal of the import cycle (zero strongly-connected components over the module graph), the env-read consolidation, the empty-hash audit fix, the fully hash-pinned dependency lockfiles with `--require-hashes` in every CI job and a drift gate, and the release gate currently failing on all four user-proof gates. A report that lists only failures is not an audit.
- **Steps:** re-verify at least three of these yourself. The release gate is the cheapest: run it and read the four verdicts.
- **Expected:** they hold.
- **FAIL if:** any does not → that is a bigger finding than most of this chapter, because it was independently verified once already.
- **CROSS:** for the release gate, `docs/OWNER_TASKS.md`'s A1–A8 list.
- **Evidence:** the three verifications.

---

## 15.11 The six refuted claims — keep them refuted

The audit refuted these outright and lists them *"so you do not chase them"*. Each case is cheap and
exists for two reasons: a refutation can rot as code changes, and a tester who has not read the
refutation will re-file the claim. **A REFUTED verdict here is a PASS.**

#### ADV-121 — "The kernel is off by default, so a fresh install is ungoverned" — REFUTED  ⏱
- **Surface:** `agents/core/kernel/` · the payments seam
- **Why it matters:** the audit repeated this to the owner before its own skeptics finished, and it is inverted: with the kernel off, the payment contract still evaluates, the approval queue still runs, the audit log still runs. The kernel is an additional **deny** layer, and enabling the flag *unlocks* autonomy rather than adding safety.
- **Steps:** with the kernel flag unset, execute an over-cap payment and an admissible one through the governed path.
- **Expected:** the over-cap one is refused by the contract; the admissible one goes to pending. **Never move real money** — the payments rail is a no-op by design.
- **FAIL if:** either executes ungoverned → the refutation does not hold on this build → **BLOCKER**.
- **CROSS:** `GET /api/admin/audit` (admin) — both attempts should have rows.
- **Evidence:** both responses and both audit rows.

#### ADV-122 — The "verified only by its own packs" evidence was a grep artifact  ⏱
- **Surface:** `tests/`
- **Why it matters:** the original claim rested on a `grep -v test` that hid 22 test files including a real anti-bypass CI gate. A methodology lesson worth re-proving.
- **Steps:** find the anti-bypass gate and run it.
- **Expected:** it exists and is green.
- **FAIL if:** it does not exist → the refutation was wrong; re-open the claim.
- **CROSS:** the CI workflow that runs it.
- **Evidence:** the test name and result.

#### ADV-123 — "The park freeze was dissolved" — REFUTED, wrong gate  ⏱
- **Surface:** the release gate · the park guard
- **Why it matters:** the park guard was always a PR-diff declaration guard that one line satisfies; it never knew about the A-track items. The real gate is the release gate, and it is alive and refusing.
- **Steps:** run the release gate; read the four user-proof verdicts.
- **Expected:** FAIL on manual sign-off, soak, design partners and partner feedback → NOT READY.
- **FAIL if:** it reports ready → **BLOCKER**; something disabled the gate.
- **CROSS:** the gate's self-protection — CI judges PRs against the base-commit copy of the policy file. Verify that mechanism exists.
- **Evidence:** the gate output.

#### ADV-124 — "The north star is structurally unreadable" — REFUTED, it is empty not broken  ⏱
- **Surface:** `GET /api/metrics/north-star` (open) · `agents/core/observability/north_star.py`
- **Why it matters:** seeded with a real task queue it returns a full funnel; the endpoint says "I have nothing" rather than inventing a fleet, which is a PASS under §1.1.
- **Steps:** seed a queue and read the funnel; then read it empty.
- **Expected:** real numbers when seeded, honest nulls when empty.
- **FAIL if:** it invents anything → **BLOCKER (F4)**.
- **CROSS:** ADV-065 covers the empty case from the other direction.
- **Evidence:** both bodies.

#### ADV-125 — The claimed north-star fixture contamination does not exist  ⏱
- **Surface:** `agents/core/memory/persistence.py` · `scripts/install_smoke.py` · **Auto:** ✅tests/test_qa_run2_fabrication_fixes.py
- **Why it matters:** a subtle one. The audit refuted the *specific* contamination claim it tested — but **RUN 2 independently found a real, different fixture bleed** (`install_smoke` restored as the owner's live session, because the memory root was bound at import before the environment redirect). Both are true. Do not let the refutation of one imply the other.
- **Steps:** confirm the memory root now resolves lazily and that the shipped regression tests pass.
- **Expected:** lazy resolution; tests green.
- **FAIL if:** the import-time binding is back → a regression of a fixed bug; **MAJOR**.
- **CROSS:** run the RUN-2 regression file and check the data root after an install smoke run.
- **Evidence:** the test results and the directory listing.

#### ADV-126 — "Simulators feed fake verdicts into the registry" — REFUTED  ⏱
- **Surface:** `agents/core/observability/`
- **Why it matters:** a forced-promotion run promoted nothing; the packs drive the real adapters through a declared host seam, and mutating the real house adapter drops that pack sharply, so drift is loud. Directory placement only.
- **Steps:** mutate the real house adapter; re-run the house pack; compare pass counts.
- **Expected:** a large drop.
- **FAIL if:** the pack stays green → the refutation fails and this becomes a live finding. **Revert the mutation.**
- **CROSS:** ADV-088 tests the *opposite* property for action capabilities and is expected to reproduce. Both results together are the real picture: the packs drive real adapters, but the action-promotion criterion does not.
- **Evidence:** both counts.

#### ADV-127 — "The plugin gatherer leaks your inbox on unrelated questions" — REFUTED  🔑
- **Surface:** `agents/core/plugin_gate.py`
- **Why it matters:** the repro stubbed the permission gate to return `True`. With the real gate, most natural-language probes fire nothing. **This is the methodology lesson of the whole audit** — reproduce it deliberately so the lesson lands.
- **Steps:** run a set of natural-language probes with the real gate and count how many trigger a mail read. Then stub the gate to return `True` and re-run. Compare.
- **Expected:** a large difference. The stub manufactures the finding.
- **FAIL if:** the real gate also fans out → the refutation fails; **BLOCKER**.
- **CROSS:** `GET /api/admin/network/calls` (admin) for both runs.
- **Evidence:** both counts and both egress logs.

#### ADV-128 — The real residue: a tokenizer stem  ⏱
- **Surface:** the gatherer's keyword matching
- **Why it matters:** the honest remainder of ADV-127 — one Romanian word triggers a message list on compose requests already routed elsewhere, plus a dead stem. A wasted round-trip, not a privacy leak.
- **Steps:** find the stem list; test the specific word.
- **Expected:** an unnecessary call, no data leaving the box.
- **FAIL if:** data leaves → escalate; that would revive ADV-127.
- **CROSS:** the egress monitor.
- **Evidence:** the trace.

#### ADV-129 — "21 orchestrator attributes are declared nowhere" — REFUTED  ⏱
- **Surface:** `agents/core/orchestrator.py`
- **Why it matters:** the measurement counted only `ast.Assign` and dropped annotated assignments. Live instantiation shows most of the attributes exist the moment `__init__` returns.
- **Steps:** instantiate an orchestrator and check which of the disputed attributes exist. Count `AnnAssign` nodes in the class.
- **Expected:** most exist; the rest are written by the autonomy coordinator and the web wiring.
- **FAIL if:** many are genuinely absent → the refutation fails.
- **CROSS:** the AST count both ways (`Assign` only, then `Assign + AnnAssign`) — the difference *is* the lesson.
- **Evidence:** both counts and the live attribute check.

#### ADV-130 — The real residue: silent degradation to a default  ⏱
- **Surface:** `agents/core/orchestrator.py` · `agents/web.py`
- **Why it matters:** the honest remainder of ADV-129 — a handful of attributes are written by other modules, and a missing one degrades to a default rather than failing loudly.
- **Steps:** for each externally-written attribute, remove the writer and see what happens.
- **Expected:** a silent default.
- **FAIL if:** confirmed → **MINOR**; the audit's suggestion (a Protocol) is proportionate. Note it as a gap, not a bug.
- **CROSS:** the writers.
- **Evidence:** the list and one demonstration.

---

## 15.12 Never measured — the surfaces no lens touched

The audit names these so their absence is not mistaken for a clean bill: **the WorldView Node stack
and its bridge contract, the mobile and desktop apps, the voice pipeline, the workflow engine, the
MCP client and server surfaces including the OAuth path, licensing and vendoring, and the CI
workflows themselves.** Two July findings need a live network or a browser host and remain unchecked.
Nothing credential- or hardware-gated could be exercised at all.

This section is **exploratory**. There is no prior claim to verify — you are looking for the first
one. Timebox it, and **record where you stopped**; an honest "I got through three of five and here is
what I did not open" is worth more than a thin pass over all of them.

The audit flags three as most likely to hide something. Do those first.

#### ADV-131 — The ingestion / archive twin (flagged: most likely)  ⏱ ✅
- **Verdict:** **CONFIRMED → CLOSED in the G35 candidate.** The raw drop and derived archive had no shared lifecycle inventory; export and retention omitted both, while forget reached the archive only implicitly through its KEEP-inverted sweep.
- **Canonical roots:** `ingestion/` (raw Facebook/WhatsApp drop) and `archive/` (SQLite, JSONL, stylometry, knowledge, watcher/provenance state and embedding cache), both below the configured runtime data root.
- **Coverage:** `EXPORT_PRIVATE_DIRS == RETENTION_PRIVATE_DIRS == PURGE_PRIVATE_DIRS == PRIVATE_INGESTION_ROOTS`; future nested artifacts export recursively and are forgotten by default.
- **Retention:** `retention.ingestion_ttl_days`, default `0` (keep forever), prunes a root only when its newest artifact is stale; any symlink fails closed.
- **Export safety:** SQLite is dumped structurally, text/JSON/JSONL remains inspectable, binary is base64, and symlinks are refused with `private_ingestion_complete=false`.
- **Upgrade safety:** a non-empty pre-G35 repo-local `data/` stays watched but is reported as outside authority; export and forget cannot claim completion until the owner resolves it.
- **Live retention:** the scheduled path clears both the watcher writer and the distinct shared RAG reader, including raw-text embedding keys.
- **CROSS:** the hermetic proof seeds raw text plus SQLite/JSONL/profile/cache markers, exports every marker, prunes stale roots and verifies a full forget leaves no marker bytes.
- **Evidence:** [`2026-08-13 hermetic ingestion-lifecycle run`](../qa-runs/2026-08-13-hermetic-adv-ingestion-lifecycle.md).

#### ADV-132 — The MCP server surface (flagged: most likely)  🌐 ✅
- **Verdict:** **CONFIRMED → initial candidate HOLD → owner-authorized remediation implemented; fresh independent review required.** The initial G36 candidate closed route-tool and hidden-skill bypasses, but independent review found that the pre-routing LM Studio lifecycle fast-path was still reachable through `ask_*` without MCP-specific identity/kernel/audit mediation. The owner then explicitly authorized governed LM Studio **and Ollama** lifecycle autonomy; the same run now closes that remaining path without weakening review separation.
- **Surface:** `POST /api/mcp/server/rpc` (open) · `GET /api/mcp/server` (open) · `agents/core/mcp/server.py`
- **Inventory:** `GET /api/mcp/server` now returns `tool_inventory` for every exposed `ask_*`, allow-listed read route, and allow-listed mutating route. Each row declares persistent state effects separately from direct route mutation plus identity, audit, retention, kernel and governance posture; names are checked against `tools/list` so no advertised tool is omitted.
- **Agent boundary:** `ask_*` is not non-mutating: the production orchestrator durably stores the user turn before routing and normally stores the assistant turn afterward. That conversation write is transport-authenticated, governed by transcript retention, outside the Action Kernel, and has no mandatory pre-write security-audit row. Parsed direct skill commands are refused. Explicit start/load/unload is restricted to `ask_jarvis`; it additionally requires owner token/verified OAuth identity (or the enforced localhost-only no-token posture), system-control permission, host contract, enabled/bound `host.control` kernel `GRANT`, and durable audit preflight. A direct `handle_input(channel="mcp")` call cannot acquire the server-scoped authority marker.
- **Mutation boundary:** `route_memory_remember` still requires both MCP switches, transport/per-tool identity and the reusable contract. It now additionally requires `JARVIS_ACTION_KERNEL=1`, a bound kernel, verdict `GRANT`, and successful durable `authorized` audit write before invoking the adapter. Disabled/unbound/raising kernel, `DENY`, `QUEUE`, and missing/raising audit sink all refuse without mutation.
- **No-token proof:** default server mode returns 403; enabled mode with a configured user token returns 401 without the token; unset-token non-local access returns 403. Local-dev read/conversation posture remains available, but mutation still cannot cross the kernel requirement.
- **CROSS:** a real bound kernel over the default policy records an `mcp.mutating` `queue` delta while the adapter call count stays zero; production-topology evidence also proves an ordinary `ask_jarvis` call changes the dedicated transcript before/after state exactly as inventoried.
- **Lifecycle CROSS:** hostile tests bind fake controllers behind the production authorization function and prove `kernel → audit → effect` order for LM Studio and Ollama. Missing/wrong identity, non-Jarvis agent, direct MCP context, permission denial, kernel-off/unbound/raising, `DENY`, `QUEUE`, audit failure and invalid model id all leave effect count zero. Ollama start is fixed argv/no-shell; load/unload use only localhost `keep_alive=-1/0`.
- **Evidence:** [`2026-08-13 hermetic MCP RPC governance run`](../qa-runs/2026-08-13-hermetic-mcp-rpc-governance.md).

#### ADV-133 — Upgrade and migration safety (flagged: most likely)  ⏱ 🖥
- **Surface:** `agents/core/persistence/migrations.py` · `agents/core/paths.py`
- **Why it matters:** nobody has run the path where the data root moves and the migration framework runs against a real user's databases.
- **Steps:** on a **copy** of a populated data root, run the upgrade path end to end. Verify every store afterwards.
- **Expected:** a clean migration, or a specific failure.
- **FAIL if:** any data is lost or any store is left unreadable → **BLOCKER** for anyone who already has an install.
- **CROSS:** row counts per table before and after.
- **Evidence:** both counts and any error.

#### ADV-134 — The MCP client and its OAuth path  🔑
- **Surface:** `agents/core/mcp/client.py` · `agents/core/mcp/oauth.py` · `POST /api/admin/mcp` (admin) · `POST /api/mcp/token` (admin)
- **Why it matters:** an OAuth path never exercised by an audit is where token handling bugs live.
- **Steps:** trace token storage, redaction in logs, and what happens on a failed or expired grant.
- **Expected:** encrypted at rest, redacted in logs, honest failure.
- **FAIL if:** a token appears in a log or an error body → **BLOCKER**.
- **CROSS:** grep the logs after a deliberate failure.
- **Evidence:** the failure output with the token field visible only as a redaction marker.

#### ADV-135 — The WorldView bridge contract  ⏱
- **Surface:** `worldview/` · `agents/core/plugins/worldview.py` · `agents/core/mcp/worldview_write.py`
- **Why it matters:** an entire stack with a write path into the core, untouched by every lens.
- **Steps:** identify the bridge's trust boundary. What can the Node side ask the Python side to do, and what validates it?
- **Expected:** a named validator per write.
- **FAIL if:** any write crosses unvalidated → **BLOCKER**; treat the Node side as untrusted input.
- **CROSS:** the taint classification applied to worldview-sourced content.
- **Evidence:** the boundary description and one traced write.

#### ADV-136 — The workflow engine's untested seams  ⏱
- **Surface:** `agents/core/workflows/`
- **Why it matters:** §10 tests it as a product; no lens tested it as an attack surface, and §10's own open-gaps list already names unbounded retries, uncapped loop nesting and an open-tier trace endpoint that echoes prompt content.
- **Steps:** re-read §10's open-gaps list and pick the three with a security shape. Verify each.
- **Expected:** confirmation or refutation of each.
- **FAIL if:** the open-tier trace endpoint echoes anything sensitive → **MAJOR**; cross-file into §08.
- **CROSS:** `GET /api/workflows/traces` (open) after driving a workflow with a marker string in its input.
- **Evidence:** the trace body containing (or not) your marker.

#### ADV-137 — The voice pipeline  🔑 🖥
- **Surface:** `agents/core/voice/` · `POST /api/voice/stt` (open) · `GET /api/voice/capabilities` (open)
- **Why it matters:** never executed by any lens, and it takes audio — the most personal input the system accepts.
- **Steps:** determine where audio is buffered, whether it touches disk, and whether it is covered by purge and retention.
- **Expected:** a clear answer per question.
- **FAIL if:** audio or transcripts persist outside every purge set → same class as §15.2 and grade it the same way.
- **CROSS:** the directory diff from ADV-023 with a voice turn included.
- **Evidence:** the buffer path and the diff.

#### ADV-138 — The mobile app's parity claims  🖥
- **Surface:** `mobile/`
- **Why it matters:** untouched, and it holds tokens on a device that leaves the house.
- **Steps:** determine how the app stores its token, what it caches locally, and whether a forget on the server reaches it.
- **Expected:** answers, not assumptions.
- **FAIL if:** a forget leaves a full local cache on the phone → **MAJOR**, and it extends §15.2 past the box.
- **CROSS:** §11's mobile cases.
- **Evidence:** the storage mechanism and the cache contents.

#### ADV-139 — The desktop app  🖥
- **Surface:** `desktop/`
- **Why it matters:** same reasoning, plus it may hold a privileged local channel.
- **Steps:** what does it store, and what does it trust from the server?
- **Expected:** an inventory.
- **FAIL if:** it trusts server-supplied content into any execution path → **BLOCKER**.
- **CROSS:** §06's desktop cases.
- **Evidence:** the inventory.

#### ADV-140 — The CI workflows themselves  ⏱
- **Surface:** the repository's workflow definitions
- **Why it matters:** every "the gate is green" claim in this chapter depends on the gate actually running. Nobody has audited the runner.
- **Steps:** for each gate this chapter relies on (route-auth matrix, lint, the release gate, the drift gate), confirm it runs on pull requests, is required, and cannot be skipped by a path filter.
- **Expected:** all four run and are required.
- **FAIL if:** any is advisory or path-filtered such that a relevant change skips it → **MAJOR**; a gate that can be skipped is not a gate.
- **CROSS:** an actual recent run's checks list.
- **Evidence:** the workflow conditions and one run.

#### ADV-141 — Licensing and vendoring  ⏱
- **Surface:** the dependency manifests and any vendored source
- **Why it matters:** untouched, and it is the kind of thing that blocks a release late.
- **Steps:** enumerate vendored code and its licences.
- **Expected:** a list.
- **FAIL if:** anything is incompatible with the project's licence → report to the owner directly; this is `docs/OWNER_TASKS.md` territory.
- **CROSS:** the SBOM generator's output.
- **Evidence:** the list.

#### ADV-142 — The two July findings needing a live host  🌐 🖥
- **Surface:** the browser-automation SSRF path and the central plugin HTTP client
- **Why it matters:** `BACKLOG.md` SEC-B4 — the DNS-rebinding TOCTOU on the browser path, and the HTTP client not routing through resolve-and-pin. Neither could be demonstrated without a live network or a browser host.
- **Steps:** if you have both, construct the rebinding case against a host you control. If not, mark **NOT-REPRODUCIBLE** and say exactly what was missing.
- **Expected:** either a demonstration or an honest skip.
- **FAIL if:** demonstrated → **BLOCKER**.
- **CROSS:** the egress monitor.
- **Evidence:** the attempt, either way.

#### ADV-143 — Everything credential-gated  🔑
- **Surface:** every plugin in `honesty._NEEDS`
- **Why it matters:** the audit could exercise none of it. The owner can exercise some of it.
- **Steps:** for each credential you actually hold, drive one real call and grade the honesty of the result. **Never send on a live channel to anyone but yourself.**
- **Expected:** per-plugin verdicts.
- **FAIL if:** any configured plugin still returns a mock while badging live → the §15.6 finding, now with a real key, which is far stronger evidence.
- **CROSS:** the badge from §15.6.
- **Evidence:** the calls and the badges.

#### ADV-144 — Everything hardware-gated  🖥
- **Surface:** §12
- **Why it matters:** the audit explicitly could exercise nothing hardware-gated. §12 exists for exactly this; this case is a pointer so the gap is not double-counted.
- **Steps:** if the hardware is present, run §12 and cross-reference its findings here.
- **Expected:** either §12's results or an honest skip.
- **FAIL if:** skipped, record as `skipped — owner-host gate`, which `docs/TEST_MANUAL.md` §2.3 already permits.
- **CROSS:** §12's coverage ledger.
- **Evidence:** the reference or the skip.

#### ADV-145 — Where did *you* stop?  ⏱
- **Surface:** this section
- **Why it matters:** the audit's own best habit — naming the unmeasured so absence is not read as a clean bill. Repeat it for your run.
- **Steps:** list every surface in §15.12 you did not open and why.
- **Expected:** an explicit list.
- **FAIL if:** you cannot produce one → you were not tracking coverage; start again from the ledger.
- **CROSS:** the coverage ledger below.
- **Evidence:** the list.

#### ADV-146 — Anything new you found that the audit never considered  ⏱
- **Surface:** anywhere
- **Why it matters:** this chapter's whole justification. Six agents found one new security break; a human on the real machine has advantages none of them had.
- **Steps:** file each new finding in the standard format with a `CROSS:` line, most-severe first.
- **Expected:** possibly nothing. Zero new findings, honestly arrived at, is a real and valuable result.
- **FAIL if:** you file something without a cross-check → that is the exact failure mode §15.0.1 exists to prevent.
- **CROSS:** mandatory, per finding.
- **Evidence:** per finding.

---

## 15.Y Negative & adversarial — attack the chapter's own conclusions

Every case above can produce a false positive. These are the counter-cases.

#### ADV-147 — Re-run the probe tool twice and diff  ⏱
- **Surface:** `scripts/qa_audit_probes.py`
- **Why it matters:** a non-deterministic probe is worse than no probe. The audit warns its own severities were not reproducible across runs.
- **Steps:** run `--json` twice; diff.
- **Expected:** byte-identical apart from any host-specific field.
- **FAIL if:** it differs → do not use its verdicts; report the instability first.
- **CROSS:** run it on a clean checkout too.
- **Evidence:** the diff.

#### ADV-148 — Verify the probe never touches the live install  ⏱
- **Surface:** `scripts/qa_audit_probes.py`
- **Why it matters:** a QA tool that mutates the thing it measures is a disaster with a good excuse.
- **Steps:** snapshot the data root, run every probe, snapshot again.
- **Expected:** byte-identical.
- **FAIL if:** anything changed → **BLOCKER** against the tool; fix it before using any result.
- **CROSS:** watch the process's file handles if you can.
- **Evidence:** both snapshots.

#### ADV-149 — The probe must not echo secret material  ⏱
- **Surface:** `scripts/qa_audit_probes.py`
- **Why it matters:** a detector that prints what it detects is the classic own-goal, and this repo has already been bitten by it once (the manual linter's clear-text-logging alerts).
- **Steps:** configure a signing key and an audit key with recognisable values; run every probe; grep the output.
- **Expected:** presence booleans only, never any part of a value.
- **FAIL if:** any fragment appears → **BLOCKER**; fix before the output goes anywhere near a report.
- **CROSS:** the `--json` output as well as the table.
- **Evidence:** the grep result.

#### ADV-150 — A CLOSED verdict must be provable, not merely absent  ⏱
- **Surface:** `scripts/qa_audit_probes.py`
- **Why it matters:** a probe that returns CLOSED because it silently failed is the worst possible output.
- **Steps:** break one probe's precondition deliberately (rename a module it imports) and run it.
- **Expected:** `N/A` with a `probe_error`, never `CLOSED`.
- **FAIL if:** it reports CLOSED → **BLOCKER** against the tool.
- **CROSS:** the `probe_error` field.
- **Evidence:** the output. **Restore the module.**

#### ADV-151 — Try to refute ADV-001 rather than confirm it  ⏱
- **Surface:** §15.1
- **Why it matters:** the audit's own method — every finding went to an agent told to refute it, defaulting to REFUTED when uncertain. Apply it to the finding you are most confident about.
- **Steps:** spend 30 minutes arguing that the chain forgery does not matter: preconditions, mitigations, detection, whether DB write access already implies game over.
- **Expected:** the strongest counter-argument is "an attacker with DB write access has already won" — and the answer is that the *whole point* of an HMAC-keyed chain is to survive exactly that attacker, which is what `hardened.enforce()`'s message says.
- **FAIL if:** you cannot rebut your own counter-argument → downgrade the finding and say so. That is a valid outcome.
- **CROSS:** the enforce() message.
- **Evidence:** both sides, written out.

#### ADV-152 — Try to refute the forget finding  ⏱
- **Surface:** §15.2
- **Why it matters:** same discipline on the second-most-confident finding.
- **Steps:** argue the other side: is the data at rest already protected by disk encryption? Does the owner's threat model include local file access?
- **Expected:** the counter-argument is real for the *owner's* data and weak for a **design partner's** — they are handing the box back, and the promise was made to them.
- **FAIL if:** the counter-argument holds → re-grade honestly.
- **CROSS:** `docs/PRIVACY.md`'s audience.
- **Evidence:** both sides.

#### ADV-153 — Check whether a finding is already fixed at your commit  ⏱
- **Surface:** all
- **Why it matters:** the audit was taken at a specific commit; work has continued. Filing a fixed bug wastes the owner's most expensive resource.
- **Steps:** for every CONFIRMED verdict, check the git log for the relevant file since the audit's date.
- **Expected:** most unchanged.
- **FAIL if:** any is fixed → mark **FIXED-SINCE** with the commit, and say so prominently.
- **CROSS:** the probe verdict at both commits if you can check out the older one.
- **Evidence:** the log lines.

#### ADV-154 — Check whether a finding is a duplicate of `BACKLOG.md`  ⏱
- **Surface:** `BACKLOG.md`
- **Why it matters:** the audit's headline result is that most findings rediscovered the owner's own July deferral list. Do not re-file SEC-B1 through SEC-B6 as new.
- **Steps:** map every verdict in this chapter to an existing backlog row or mark it genuinely new.
- **Expected:** a two-column table: known vs new.
- **FAIL if:** you file a known item as new → the report loses credibility for the genuinely new ones.
- **CROSS:** the SEC-B rows and the deferral list.
- **Evidence:** the table.

#### ADV-155 — Grade the audit itself  ⏱
- **Surface:** this chapter's results
- **Why it matters:** you now have independent data on 18 claims. Say how the audit did.
- **Steps:** tally your verdicts against the audit's: agreements, disagreements, and your own new findings.
- **Expected:** a tally.
- **FAIL if:** you disagree with more than a third → either the audit is weaker than it looks or your reproduction differs systematically. Investigate which before reporting.
- **CROSS:** the audit's own confirmed/partial/refuted counts.
- **Evidence:** the tally.

#### ADV-156 — A green suite proves nothing about an unwritten test  ⏱
- **Surface:** `tests/`
- **Why it matters:** the chapter's thesis in one sentence, and the habit that catches the next one.
- **Steps:** for the three findings you graded most severe, write down the test that *would* have caught each. Check whether it exists.
- **Expected:** it does not — that is why the finding exists.
- **FAIL if:** it does exist and passes → your reproduction is wrong. Go back.
- **CROSS:** the test tree.
- **Evidence:** the three named tests and their absence.

#### ADV-157 — Fabrication check on this chapter's own probes  ⏱
- **Surface:** `scripts/qa_audit_probes.py`
- **Why it matters:** apply §1.1 to the tooling. A probe that says OPEN when it means "I could not tell" is an F4.
- **Steps:** read every verdict assignment in the script and ask whether any can be reached without a measurement.
- **Expected:** each verdict traces to a measured value.
- **FAIL if:** any is reachable without one → fix the probe and re-run everything that depended on it.
- **CROSS:** the `detail` block of each probe — it must contain the evidence for the verdict.
- **Evidence:** your reading.

#### ADV-158 — Adversarial: make a gate go green while the property is false  ⏱
- **Surface:** any gate from §15.8
- **Why it matters:** the direct test of the systemic finding. If you can do it to a second gate, you have generalised the audit.
- **Steps:** pick a gate this chapter has not already broken. Try to satisfy its *shape* while violating its *substance*. **Revert everything.**
- **Expected:** you either succeed (a new instance) or fail (evidence the gate is sound).
- **FAIL if:** you succeed → a new finding, and the most valuable kind.
- **CROSS:** the gate's own docstring — does it claim what you just falsified?
- **Evidence:** the attempt.

#### ADV-159 — Adversarial: is any *fix* from RUN 2 falsifiable the same way?  ⏱
- **Surface:** `tests/test_qa_run2_fabrication_fixes.py` · `frontend/src/test/action-failure-sink.test.tsx`
- **Why it matters:** the RUN-2 fixes are recent and pinned by tests that assert the *shape* of a prompt rail and the *presence* of a sink. Apply this chapter's own lens to them.
- **Steps:** for each, ask whether the test could pass while the property is false. E.g. can a rail be present in the prompt and not reach the model? Can a mutation failure be recorded and never rendered?
- **Expected:** a written answer per test.
- **FAIL if:** any can → report it; a fix that is only shape-verified is the same defect this chapter is about, in code that was written to close it.
- **CROSS:** drive the actual behaviour end to end rather than reading the test.
- **Evidence:** the answers plus one end-to-end demonstration.

#### ADV-160 — Would this chapter catch the next one?  ⏱
- **Surface:** the whole chapter
- **Why it matters:** the closing question. The audit's advice is "make one gate check substance instead of shape and make it the template".
- **Steps:** name the one gate you would rebuild first, and what its substance-checking version asserts.
- **Expected:** one named gate and one sentence.
- **FAIL if:** you cannot name one → the chapter did not do its job; say so in the report.
- **CROSS:** ADV-099's route-auth matrix, which is the existing template.
- **Evidence:** the sentence.

---

## 15.Z Degraded & honest-state matrix

What each surface in this chapter should say when it has nothing, and what it must never say. Grade
every row against `docs/TEST_MANUAL.md` §1.1 — an honest empty is a **PASS**.

| Surface | Honest degraded state (PASS) | The dishonest version (FAIL) | Grade |
|---|---|---|---|
| `GET /api/security/audit/verify` | "valid, unkeyed — integrity only, not tamper-evidence" | "valid" with no key qualifier | MAJOR |
| `GET /api/security/posture` | names which integrity guarantees are unkeyed on this host | reports hardened with no such distinction | MAJOR |
| `POST /api/admin/forget` | reports per-store what it cleared and what it could not | unqualified `ok` while stores survive | BLOCKER (F5) |
| Pre-forget archive | disclosed in the response, encrypted, outside the data root | undisclosed plaintext copy inside the purged root | BLOCKER |
| Vector/KG clear | "no clear() implementation for this backend — not cleared" | silent no-op reported as success | BLOCKER |
| Skill trust label | `unsigned` / `unverified` | `trusted` for an unkeyed digest | MAJOR (F3) |
| `GET /plugins` honesty badge | `needs_config` with the key named, or `unknown` | `live` for a plugin the same module says needs a key | MAJOR (F3) |
| `GET /plugins` live rollup | counts only genuinely live plugins | inflated by false-live rows | MAJOR |
| `GET /api/cost` and siblings | "no cost data — the meter is not wired" | a confident `0.00` after real cloud traffic | MAJOR (F3) |
| `estimate_cost` for an unpriced model | `None` / unknown | `0.0` | F4-adjacent |
| `GET /api/metrics/north-star` `local_pct` | `null` with no routed runs | a confident percentage that counts unattributed agents as local | MAJOR |
| `GET /api/capabilities` verified count | `0` with `harness_pending` | any action capability `verified` with no actuator | BLOCKER |
| Ambient pack counters | measured values, including a non-zero one | a literal `0` presented as a measurement | MAJOR (evidence) |
| HUD parity gate | fails on a route no client calls | green for an invented endpoint | MAJOR (gate) |
| Telegram inbound from a stranger | labelled unpaired + tainted, ASK-forced | indistinguishable from the owner's own message | MAJOR (F3) |
| Wyoming/satellite status | "not running" | "completed" with nothing listening | MAJOR |
| MCP RPC surface | refuses unauthenticated mutation | any mutating tool reachable open-tier | BLOCKER |
| A probe in this chapter | `N/A` with `probe_error` | `CLOSED` after a silent failure | BLOCKER (tooling) |

---

## Gap ledger — missing code, missing features, missing evidence

> **⚠ Most of this ledger was CLOSED after the chapter was written.** The two confirmed
> High findings and eight of the ten corrected-down ones were fixed on the same branch that
> shipped this chapter — see the `Fixed` column. That changes what you are doing here: for a
> `✅` row your job is **verification on real hardware**, not discovery, and the expected
> verdict is `FIXED-SINCE`. If a `✅` row still reproduces on the box, that is a much more
> serious finding than the original, because it means a fix passed CI and did not hold —
> report it first and quote the case id.
>
> `python scripts/qa_audit_probes.py` gives you eight `CLOSED` verdicts in 30 seconds. A
> CLOSED probe is still only a lead (§15.0.1): the live cross-check in each case is what
> you file.

The user-facing half of this chapter: not "what is broken" but **"what is not there"**. Fill the
last two columns during the run. `Kind` is the important distinction — a **BUG** has code that is
wrong, a **GAP** has no code at all, and an **EVIDENCE** item has code that works and a gate that
does not prove it. They get triaged differently.

| # | What is missing | Kind | Where it should live | Audit severity | Fixed | Your verdict | Notes |
|---|---|---|---|---|---|---|---|
| G01 | Chain-algorithm pinning: nothing asserts that a configured key implies a required row algorithm | BUG | `agents/core/security/audit.py` | High · CONFIRMED | ✅ | | §15.1 |
| G02 | A full-table-rewrite regression test | GAP | `tests/test_audit_hardening.py` | High | ✅ | | ADV-014 |
| G03 | Automatic transparency anchoring + a comparison against the chain tail | GAP | `agents/core/security/anchor.py` | — | — | | ADV-007 |
| G04 | An operator-visible audit-integrity signal in the HUD | GAP | `frontend/src/gap.tsx` | — | — | | ADV-013 |
| G05 | Purge as a KEEP-allowlist instead of a PURGE-allowlist | BUG | `agents/core/data_purge.py` | High · CONFIRMED | ✅ | | §15.2 |
| G06 | `clear()` as an abstract method on the store and graph base classes | GAP | `agents/core/memory/store.py`, `agents/core/memory/graph.py` | High | ✅ | | ADV-022 |
| G07 | Any `clear()` implementation for a persistent vector or graph backend | GAP | `agents/core/memory/qdrant_store.py` | High | ✅ | | ADV-022, ADV-033 |
| G08 | Pre-forget archive: outside the data root, encrypted unconditionally, pruned | BUG | `agents/core/backup.py` | High | ✅ | | ADV-024, ADV-026 |
| G09 | `backup_first` exposed on the forget route (the API's `--no-backup`) | GAP | `agents/core/routers/backup.py` | High | ✅ | | ADV-025 |
| G10 | Export/purge allowlist reconciliation the module docstring already promises | BUG | `agents/core/data_purge.py`, `agents/core/data_export.py` | High | ✅ | | ADV-019 |
| G11 | A per-store report in the forget response | GAP | `agents/core/routers/backup.py` | — | ✅ | | ADV-027 |
| G12 | `require_signed()` failing closed when enforcement is on and no key exists | BUG | `agents/core/skills/signing.py` | High → scoped | ✅ | | ADV-035 |
| G13 | Defer `exec_module` for unsigned external skills; preserve bundled behavior | GAP | `agents/core/skills/loader.py` | High (audit: fix first) | ✅ | | ADV-038 |
| G14 | A policy floor over synthesis contributors | BUG | `agents/core/agent.py` | High · PARTIAL | ✅ | | §15.4, SEC-B1 |
| G15 | Any test at the synthesize boundary, and any coverage of the handoff path | GAP | `tests/` | High | ✅ | | ADV-054, ADV-055 |
| G16 | A `{agent_id: route}` map carried into the interaction record | BUG | `agents/core/orchestrator.py` | Medium · PARTIAL | ✅ | | §15.5 |
| G17 | `degradation_info()` overriding the honesty verdict | BUG | `agents/core/plugins/honesty.py` | Medium · CONFIRMED | ✅ | | ADV-075 |
| G18 | A `configured` contract distinct from `available` on the keyless-real plugin | GAP | `agents/core/plugins/analytics.py` | Medium | ✅ | | ADV-073 |
| G19 | An `unknown` honesty status for plugins with no contract | GAP | `agents/core/plugins/honesty.py` | Medium | ✅ | | ADV-076 |
| G20 | `record()` called from the router with the model that actually ran | GAP | `agents/core/cost_tracker.py` | Medium · CONFIRMED | ✅ | | §15.7 |
| G21 | Cost persistence across a restart | GAP | `agents/core/cost_tracker.py` | Medium | ✅ | | ADV-082 |
| G22 | `None` for an unpriced model instead of `0.0` | BUG | `agents/core/llm/cost_estimator.py` | Medium | ✅ | | ADV-079 |
| G23 | A daily spend cap checked before a cloud route | GAP | `agents/core/llm/hybrid_router.py` | Medium | ✅ | | ADV-083 |
| G24 | The action-capability probe resolving `manifest.implementation` | BUG | `agents/core/observability/reality_harness.py` | Medium · PARTIAL | ✅ | | ADV-087, #897 |
| G25 | Measured (not literal) safety counters in the ambient pack | EVIDENCE | `agents/core/observability/ambient_reality.py` | Medium | ✅ | | ADV-091 |
| G26 | A parity gate that greps for a caller instead of classifying a prefix | EVIDENCE | `tests/test_hud_v2_parity.py` | Medium · PARTIAL | ✅ | | ADV-096 |
| G27 | Enforced reality-case coverage for wired capabilities | EVIDENCE | `agents/core/observability/reality_harness.py`, `tests/test_capability_readiness_matrix.py` | Medium | ✅ | | ADV-098 |
| G28 | `is_degraded()` consulted before recording a capability success | BUG | `agents/core/autonomy/worker.py` | Medium | ✅ | | ADV-094 |
| G29 | Telegram allowed-user-id parsing, and owner binding on the callback | GAP | `agents/web.py`, `agents/core/channels/telegram.py` | Medium · PARTIAL | ✅ | | §15.9, SEC-B3 |
| G30 | The pairing gate failing closed on a store error | BUG | `agents/core/channels/gateway.py` | Medium | ✅ | | ADV-108 |
| G31 | Anything that starts the Wyoming server | GAP | `agents/core/voice/wyoming.py` | — · new | ✅ | | ADV-115 |
| G32 | `JARVIS_ACTION_KERNEL` and the hardening flags in the example env | GAP | `.env.example` | Minor | ✅ | | ADV-117 |
| G33 | `docs/THREAT_MODEL.md` "single front door" and T5 corrections | DOC | `docs/THREAT_MODEL.md` | Minor | ✅ | | ADV-112, ADV-113 |
| G34 | `docs/PRIVACY.md` forget wording | DOC | `docs/PRIVACY.md` | High | ✅ | | ADV-111 |
| G35 | The ingestion archive in the purge, retention and export sets | GAP | `agents/core/ingestion/lifecycle.py`, `agents/core/{data_export,retention,data_purge}.py` | High · CONFIRMED → CLOSED | ✅ | | ADV-131 |
| G36 | A governed/ungoverned inventory for the MCP RPC tool surface | GAP | `agents/core/mcp/server.py` | High · CONFIRMED → CLOSED | ✅ | | ADV-132 |
| G37 | Any exercise of the upgrade path against a populated data root | GAP | `agents/core/persistence/migrations.py` | unmeasured | — | | ADV-133 |
| G38 | A protocol for orchestrator attributes written by other modules | GAP | `agents/core/orchestrator.py` | Minor · REFUTED-with-residue | — | | ADV-130 |

---

## Coverage ledger

| § | Cases | Needs | Offline coverage | The payload |
|---|---|---|---|---|
| 15.1 Audit chain | 14 (001–014) | 🔑, python shell | ⚠️ single-row test only | The one new break; run it first — every governance claim rests on this log |
| 15.2 Forget | 20 (015–034) | 🖥 throwaway data root | ❌ | The one finding that hurts a person; ADV-023's diff is the ground truth |
| 15.3 Skill signing | 12 (035–046) | python shell | ❌ | The exec primitive outranks the hash — do not lead with the crypto |
| 15.4 Strict-local synthesis | 12 (047–058) | 🤖 🔑 | ❌ (that is the finding) | A hole with no compensating guard, not an active leak; ADV-055 explains why it exists |
| 15.5 Per-agent identity | 10 (059–068) | 🤖 | ❌ | Streaming is fine; `handle_input` callers are not — a metric that gates a release |
| 15.6 Honesty badge | 9 (069–077) | 🖥 keyless boot | ⚠️ rendering only | Wrong in both directions, on exactly the plugins it was written for |
| 15.7 Cost | 9 (078–086) | 🤖 🔑 | ❌ | The risk is the missing cap; the zero dashboard is the symptom |
| 15.8 Evidence machinery | 16 (087–102) | ⏱ mutation runs | ⚠️ tests pin current behaviour | The systemic finding; ADV-101 is the highest-value exploratory case |
| 15.9 Telegram | 8 (103–110) | 🔑 🌐 | ⚠️ | Heavily narrowed — report the real residue, not memory exfiltration |
| 15.10 Doc promises | 10 (111–120) | ⏱ | ❌ | Includes ADV-120: the claims that hold, which a fair report must carry |
| 15.11 Refuted claims | 10 (121–130) | mixed | ⚠️ | A REFUTED verdict is a PASS; ADV-127 is the methodology lesson |
| 15.12 Never measured | 16 (131–146) | 🌐 🖥 🔑 ⏱ | ❌ | Exploratory; the three flagged surfaces first; record where you stopped |
| 15.Y Negative & adversarial | 14 (147–160) | ⏱ | ❌ | Attacks this chapter's own conclusions, including its tooling |
| **Total** | **160 cases (ADV-001 … ADV-160)** | 🔑 ≈ 16 · 🖥 ≈ 14 · 🤖 ≈ 10 · 🌐 ≈ 7 · ⏱ ≈ 40 | **~9 automated by the probe tool; the rest are live or exploratory** | The offline suite cannot prove any of this, because the offline suite is one of the things under test |

---

## Open gaps found while writing

Observations from reading the source and reproducing the audit. **No product code was changed** —
the only new files are `scripts/qa_audit_probes.py` and its test.

1. **The audit chain forgery reproduces on this checkout.** I ran the full-table downgrade myself
   before writing ADV-001, with `JARVIS_HARDENED=1` and a key set: `hardened.enforce()` returned
   `[]`, all three rows were written as `hmac-sha256`, and after rewriting every row with plain
   sha256 `verify_chain()` returned `(True, None)` with entirely attacker-chosen content. The
   attacker's toolkit was `sqlite3` and `hashlib`; the key was never read. This is not a
   transcription of the audit — it is an independent reproduction, which is why ADV-001 quotes a
   FAIL signature rather than describing one.
2. **`notes.db` is in `EXPORT_DBS` and not in `PURGE_DBS`.** The module docstring in
   `agents/core/data_purge.py` already says the two allow-lists "should be reconciled". They have
   not been. The asymmetry runs the wrong way: the product will hand a user a copy of data it has no
   code path to delete.
3. **None of the four vector-store / knowledge-graph implementations defines `clear()`**, and
   `clear` is not among the abstract methods on either base class — so the `hasattr`-guarded call in
   `clear_live_memory` is unreachable and fails silently. The abstract-method list is the reason it
   is silent rather than loud, which is exactly why the audit's proposed fix targets the base class.
4. **`require_signed()` reads one environment flag and consults nothing else** — not the key, not
   the posture. Confirmed by AST: the function body contains no reference to the signing-key helper.
5. **Three plugin classes are contradicted by their own module.** Their ids appear in
   `honesty._NEEDS` (the module names the key each one requires) while their classes expose none of
   `configured` / `available` / `_configured`, so `plugin_configured` falls through to
   `(True, "loaded")` and `honesty_for` maps that to *live, no setup required*. Two of the three also
   define `degradation_info()`, so the HUD renders `[MOCK]` beside the green chip and the owner sees
   a contradiction; the third defines no `degradation_info()`, so its row is cleanly, silently green.
   A fourth plugin is the inverse case — amber with an empty `needs` list, so the badge tells the
   owner to configure something and cannot say what.
6. **`llm.hybrid_local_max` defaults to 131072 in the settings catalogue**, which is what kills the
   size-based cloud-routing path the audit's first pass mistakenly demonstrated. That default is the
   single most important fact for scoping §15.4, and it lives in one line of
   `agents/core/settings_db.py` — a tester who does not know it will mis-grade the whole section.
7. **`LOCAL_ONLY_AGENTS` is defined twice** (`agents/core/llm/hybrid_router.py` and
   `agents/core/kernel/capabilities.py`) with the same membership today. Two copies of a
   security-relevant set is a divergence waiting to happen; ADV-052 checks them against each other
   for that reason.
8. **`POST /api/mcp/server/rpc` is open-tier in the auth snapshot.** Combined with the audit's own
   note that the MCP server is "the one place a remote client reaches the action layer", and that no
   lens touched it, this is where I would look first for an ungoverned action. ADV-132 is written to
   be run before the rest of §15.12 for that reason.
9. **The `_classify` prefix match accepts an invented admin path**, reproduced directly. The same
   file's five per-feature tests *do* grep for a panel calling its route — the good pattern and the
   weak one live in the same file, which is the clearest available illustration of the audit's
   systemic point.
10. **Nothing outside `agents/core/cost_tracker.py` calls its `record()`** — an empty grep across
    the whole `agents/` tree — and `estimate_cost` for an unknown model returns an all-zero dict
    rather than `None`. Both are one-line observations with a multi-surface consequence.
11. **The audit itself is a source that can rot.** Its findings are pinned to a commit, its
    severities are explicitly non-deterministic across re-runs, and its git checkout was shallow.
    ADV-153 exists because the most likely failure mode of this chapter, six months out, is a tester
    faithfully re-filing something that was fixed in August.
12. **File:line citations.** This chapter deliberately cites **symbols, functions, settings keys,
    route paths and filenames** rather than line numbers, because every line number in the audit had
    already drifted by the time I checked them. Search for the quoted symbol.
