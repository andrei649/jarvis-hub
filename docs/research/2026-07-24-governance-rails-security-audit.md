# Governance-rails security audit — 2026-07-24

> Adversarial review of the invariants Jarvis stakes its identity on ("cannot silently act
> beyond the authority you grant it"). Eight parallel reviewers, one per invariant, each
> required to trace the actual enforcement code and construct a concrete bypass before
> reporting. Feeds the existing security-correctness plan
> (`docs/superpowers/plans/2026-07-16-security-correctness-wave.md`).

**Method.** One reviewer per rail: Action-Kernel bypass, taint laundering, approval-queue
integrity, strict-local enforcement, secret/audit crypto, SSRF/egress, skill signing/quarantine,
router auth guards. Findings below were cross-checked against source; the two highest-severity
(Frigga synthesis leak, audit empty-hash skip) were independently re-verified line-by-line.

## Headline: the core action-governance invariant HOLDS

With `JARVIS_ACTION_KERNEL` at its default (OFF), no consequential action family
(payment / social / call / host-desktop control / MCP write / channel send) can reach execution
ungoverned: brokers stay `autonomy_level="ask"`, `worker.govern_enqueue` takes the strictest
level, payments are always-pending, the capability API returns `disabled`, and the risk
classifier **fails closed** on unknown kinds (`policy._base_tier → IRREVERSIBLE_OR_MONEY`). Two
owner-scoped latent fragilities were noted (kernel `authorize()` doesn't strip a payload-supplied
`risk_tier`; `worker.submit()` has no requested-level floor) — neither reachable by an
agent/injection path today; both admin-gated. The holes are elsewhere: **data exposure**, the
**Frigga cloud path**, and **integrity labels that over-promise**.

## Four systemic themes

- **A — Unkeyed hash sold as a signature.** The audit chain (#3) and skill signing (#9) both
  present integrity guarantees that only hold when an optional key env var is set
  (`JARVIS_AUDIT_KEY` / `JARVIS_SKILL_SIGNING_KEY`), yet the control reports itself active. One
  fix pattern: fail closed, or label an unkeyed digest as integrity-only, never "signed".
- **B — Guarded writes, unguarded reads.** On KG (#5), memory (#6), actions (#7) and traces (#8),
  every *write* is behind a guard but the matching *read* was left open — a copy-paste asymmetry.
  The route-auth gate (`test_route_auth_matrix.py`) only *requires* a guard on **mutating**
  routes, so unguarded personal-data reads passed CI silently. **Fixed in this PR.**
- **C — Enforcement keyed on declared identity, not on data.** The strict-local floor keys on the
  *responding* agent, so the jarvis synthesis pass re-processes a strict-local agent's output
  under a cloud-eligible identity (#1). Taint keys on *origin*, so a payload rebuilt outside an
  inbound turn goes taint-blind (#13). The deepest theme; needs design work, not a one-liner.
- **D — SSRF checker sound, not universally applied.** `SSRFProtector` resolves-then-checks
  correctly (all encoding tricks caught), but the Playwright path (#11) and the central plugin
  HTTP client (#12) don't route through it with IP pinning.

## Findings

| # | Finding | Severity | Precondition | Status |
|---|---------|----------|--------------|--------|
| 1 | **Frigga family data → cloud** — `Agent.synthesize` runs under jarvis's cloud-eligible policy (`select_backend(self.id=…"jarvis")`, `agent.py:340`) and embeds a strict-local agent's raw output (`agent.py:308-312,333-337`); a direct-to-Frigga turn triggers synthesis (`orchestrator.py:1071`) | **Critical** | cloud configured + (`cloud_fallback=always` or prompt > `LOCAL_MAX_TOKENS`) | **Deferred** — needs synthesis to inherit strictest contributor policy |
| 2 | **`verify_chain` skips empty-hash rows** — `if not stored_hash: continue` (`audit.py`) neither verifies nor breaks the chain, so a forged/injected row with a blank `row_hash` passes **even in HMAC mode**, and tail-truncation is undetectable | **High** | attacker can write `audit.db` | **✅ Fixed** (legacy-prefix-safe) + 3 regression tests |
| 3 | **Audit chain unkeyed by default** — no HMAC unless `JARVIS_AUDIT_KEY` set, so a DB writer can recompute the whole chain and pass `verify_chain` | Medium (partly documented) | attacker can write `audit.db`, no key set | Deferred — posture decision |
| 4 | **Telegram approval unauthenticated** — callback handler has no owner binding when constructed without `allowed_user_ids` (the production wiring, `web.py:331`); sequential task ids + unauthenticated `callback_data` | High | non-owner receives a card (group/multi-recipient chat) | Deferred — implement the 2-factor callback owner check the plan already specifies |
| 5 | **`GET /api/kg/*` reads unguarded** — entire personal knowledge graph (entities, relations, bi-temporal facts) readable; writes on the same surface are guarded | High | hub network-exposed | **✅ Fixed** (added `user_guard`) |
| 6 | **`GET /memory/{agent_id}` unguarded** — per-agent memory context readable; sibling `GET /memory` is guarded | High | network-exposed | **✅ Fixed** |
| 7 | **`GET /api/actions[/pending]` world-readable** — pending tool-call queue (tool, args, preview); `request`/`decide` are guarded | Medium | network-exposed | **✅ Fixed** |
| 8 | **`GET /api/traces`, `/api/traces/{id}`, `/api/cost` unguarded** — per-request traces likely contain prompts/responses; `traces/clear` is admin-guarded | Medium | network-exposed | **✅ Fixed** |
| 9 | **`REQUIRE_SIGNED_SKILLS` false assurance** — unkeyed `sha256:` "signature" the attacker recomputes; `require_signed()` never checks a key exists | High | can place a skill on disk (marketplace/import/dir write) | Deferred — fail closed w/o key; label unkeyed as integrity-only |
| 10 | **Skill `main.py` executes at import** (`exec_module` in `_load_skill`), so `handle()` isn't the exec gate — module top-level runs during `discover()` | Medium | can place a skill on disk | Deferred (quarantine of *generated* skills holds; this is the import/marketplace path) |
| 11 | **Playwright SSRF DNS-rebinding TOCTOU** — `check_ssrf` resolves once, no IP pinning; Chromium re-resolves and connects | Medium | Playwright host add-on installed + rebinding host on egress allowlist | Deferred |
| 12 | **Plugin HTTP client not on SSRF path** — `_enforce_egress` does static string allowlisting, no DNS resolution/pinning; some fetchers use raw `httpx` w/ `follow_redirects` | Medium | allowlisted/config host resolves to private IP | Deferred |
| 13 | **Proactive web content → auto-approved action** — `tech_scout` submits web-search findings with `source="websearch"` but the taint gate keys on origin/flag, not content provenance, so no ASK escalation | Medium (READ_ONLY-bounded) | proactive/background context | Deferred |
| 14 | **Recall/ambient taint laundering** — stored-then-recalled or ambient content rebuilt as a fresh payload drops ingress taint | Low (self-documented deferred) | background context | Known — the code documents it as "the deliberately deferred hard part" |

## What this PR changes

**Theme B (data-exposure reads) + finding #2** — the confident, low-risk subset:

- Added `dependencies=[Depends(user_guard)]` to the 10 unguarded personal-data / assistant-internal
  **read** routes (#5, #6, #7, #8). Sibling writes on each surface were already guarded; this closes
  the read/write asymmetry. Local HUD is unaffected (guard allows localhost; the HUD already
  authenticates for the guarded `/memory` route).
- `verify_chain` now fails closed on a blank `row_hash` that appears **after** the chain has
  started, while still tolerating a legitimate legacy pre-Merkle prefix (the v1 migration backfills
  `row_hash DEFAULT ''`). Three regression tests cover: blank-row-after-chain fails, blank forgery
  fails even with `JARVIS_AUDIT_KEY` set, and legacy prefix still verifies.
- Re-seeded `tests/_snapshots/route_auth.json` (10 routes `open → user`).

**Deferred to a focused follow-up** (architectural or posture decisions, tracked below):
findings #1, #3, #4, #9, #10, #11, #12, #13.

## Recommended next actions (for BACKLOG / the security-correctness wave)

1. **#1 Frigga synthesis leak (Critical).** Make `Orchestrator._synthesize` / `Agent.synthesize`
   inherit the strictest policy of any contributing agent: if any responder is in
   `LOCAL_ONLY_AGENTS`, pin synthesis to a local backend (or skip LLM synthesis and concatenate,
   which the `LocalBackendUnavailableError` branch already does). Add a test asserting a
   frigga-containing `responses` never selects a cloud backend.
2. **Theme A fail-closed (#3, #9).** `require_signed()` and the audit "tamper-evident" claim should
   treat an unkeyed digest as integrity-only, not authenticated; surface the distinction in
   `/api/security/posture`.
3. **#4 Telegram owner binding.** Implement the 2-factor callback check (owner `chat_id` + static
   owner `user_id`, fail closed on empty allowlist) the security-wave plan already specifies, and
   populate `allowed_user_ids` at construction.
4. **Theme D (#11, #12).** Route the Playwright guard and `PluginHTTPClient` through
   `resolve_and_validate` with IP pinning (the pattern `websearch.fetch_page` already implements).
5. **Gate hardening.** Extend `test_route_auth_matrix.py` to also require classification of
   **read** routes that touch personal data (KG/memory/traces), so theme-B reads can't regress open.
