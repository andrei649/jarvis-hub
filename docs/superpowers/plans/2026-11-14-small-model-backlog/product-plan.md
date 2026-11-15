# Product and native delivery Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This document authorizes planning only; implementation and remote publication require the active coordinator’s execution scope. Do not spawn subagents from a packet.

**Goal:** Turn confirmed product claim gaps and remaining native workflows into bounded, verifiable deliveries without silently adopting paused WIP.

**Architecture:** Keep existing FastAPI guards, store interfaces, mobile transport and mounted HUD panels. Each packet is one independent rollback unit; immutable paused donor commits are evidence, not permission to overwrite their branches. External acceptance and unresolved router authority stay explicit states.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, Pillow already in requirements, React/TypeScript/Vitest, React Native/Expo/Jest.

**Spec:** [packets/product.json](packets/product.json) is the implementation contract; read that packet’s exact interfaces, acceptance, stop conditions and source references before changing code.

**Freshness:** Generated 2026-11-14 UTC. Base/head inspected: `587977b623cf2d1099733d57037e1c056babe1e5`. Changes in this planning task: only this document and `packets/product.json`. Next action: coordinator validates dependency graph and assigns one ready packet on a fresh branch. No application tests or acceptance suites were run to produce this plan; commands below are future verification, not passing evidence.

## Global Constraints

- No merge, ready-for-review promotion, deploy, paid activation or overwrite of existing open PR branches. No source implementation during planning.
- Read BACKLOG via targeted queries; H18.34–37 were inspected using `tables list --open-only`, `tables show` and only the relevant source rows. Counts do not close delivery.
- Existing strict-local agents, cloud opt-in, signed provider selection, admin guards, Action Kernel decisions and data preservation remain binding.
- `ready` means bounded implementation or bounded triage is specified, not that software has passed. `external` and `needs_design` block product acceptance and implementation respectively.
- At most three production files per implementation packet here; tests and explicit evidence/parity documents are separate. Do not regenerate unrelated bundles or status ledgers.
- Shared mobile `client.ts` writes serialize SM-019 → SM-023 → SM-024 → SM-026; SM-025 owns separate chat paths. Schedule parity-document edits serially as well.
- WIP core/gateway packets create review records only; no wholesale cherry-pick, promoted equivalence or inferred authority. Donor objects must be inspected at exact SHA before any future adoption.
- Red/green outcomes below are expected assertions. Record actual command, revision and outcome at execution; skipped, pending, unavailable and failed never count as passed.

## Review Focus

- Legacy pet preferences and malformed image encodings must preserve adopted assets and fail predictably (SM-013/014).
- Synthetic benchmark baselines must never acquire competitor product names or real-cost/failover claims (SM-015/022).
- Paused donor patches must not overwrite existing branches or import unrelated authority changes (SM-016–018).
- Late mobile responses and token/hub changes must not show prior owner data or replay mutations (SM-019/023/024/026).
- Recall metadata must remain ephemeral and silent, while manual failover and TCC retain honest external limits (SM-020/021/025).

---

### SM-013: Make pet backend selection truthful

**State:** `ready` · **Priority:** P1 · **Risk:** medium.

**Goal:** Owners see procedural generation accurately; unsupported model backends cannot silently generate procedural sprites.

**Files:**
- Modify: `agents/core/pets.py`
- Modify: `frontend/src/panels/pets.tsx`
- Modify: `tests/test_h214_h238_h590_pets.py`
- Modify: `frontend/src/panels/pets.test.tsx`

**Interfaces:**
- Existing IMAGE_BACKENDS, PetStore.update_preferences and hatch generation in agents/core/pets.py; GET /api/pets exposes image_backends and current image_backend.
- Keep procedural-pixel as the only offered backend. Reject explicit svg-synth/local-vlm with PetError unsupported_backend HTTP 400; do not implement a model adapter.
- Legacy stored unsupported preference resolves to procedural-pixel at load; preserve pets/gallery/archives. Label selector Procedural pixel sprites; remove local VLM quality claims.

**Dependencies:** None; recheck base freshness.

**Red → green → verify:** Named cases below are required additions to the declared test paths; run them before production changes and confirm the behavioral assertion fails. Then implement only the specified interface and rerun the same cases plus the focused suites.

- [ ] `test_unsupported_pet_backend_never_generates` — Given local-vlm or svg-synth in explicit generate/preference request; when request is submitted; assert HTTP 400 unsupported_backend; no job/candidate created.
- [ ] `test_legacy_pet_backend_load_is_truthful` — Given stored local-vlm preference and an adopted pet; when store reloads; assert procedural-pixel offered/selected; adopted pet unchanged.
- [ ] `procedural backend selector` — Given mounted PetsPanel; when owner opens hatch flow; assert only procedural pixel sprites offered and 4 procedural candidates still work.

- [ ] Add named backend and reload regression cases to existing Python suite and mounted selector case to existing Vitest suite.
- [ ] Run named new cases and confirm red on the pinned base.
- [ ] Restrict offered backends and explicit requests; migrate only unsupported preference in memory/load path.
- [ ] Run focused suites, verify existing adoption/export behavior; record mobile gap without claiming native companion.

**Verification:**

- `python -m pytest tests/test_h214_h238_h590_pets.py -q` — Expected: All pet tests pass including explicit unsupported backend and legacy preference cases.
- `cd frontend && npm test -- src/panels/pets.test.tsx` — Expected: Mounted selector/adoption tests pass; no unavailable backend offered.

**Stop:** Stop on a changed base/interface or overlapping writer; inspect and reconcile without overwrite. If preserving legacy archive metadata requires archive schema changes, split a design packet first.

**Rollback:** Revert only this packet’s isolated change; preserve user data and other branches. No automatic runtime rollback or data deletion.

### SM-014: Extract pet reference color from real pixels

**State:** `ready` · **Priority:** P1 · **Risk:** medium.

**Goal:** An owner’s solid-color reference image yields that color independent of image encoding.

**Files:**
- Modify: `agents/core/pets.py`
- Modify: `tests/test_h214_h238_h590_pets.py`

**Interfaces:**
- Existing _extract_reference_color(reference_image_b64: str) -> str | None; retain empty-input None and 1 MiB decoded-byte cap.
- Use installed Pillow, local byte decode only. Decode PNG/JPEG/WebP; reject other/invalid formats as invalid_reference_image 400. Cap decoded width*height at 4,194,304 before load; oversized dimensions -> reference_image_too_large 413.
- Define representative color as alpha-weighted arithmetic mean of original RGB pixels, rounded with floor(x+0.5); fully transparent -> None. Output lowercase #rrggbb. No network/file URLs or EXIF metadata use.

**Dependencies:** SM-013

**Red → green → verify:** Named cases below are required additions to the declared test paths; run them before production changes and confirm the behavioral assertion fails. Then implement only the specified interface and rerun the same cases plus the focused suites.

- [ ] `test_reference_color_uses_visible_pixels` — Given solid red PNG and lossless WebP encodings; when _extract_reference_color called; assert both equal #ff0000.
- [ ] `test_reference_color_alpha_and_bounds` — Given opaque blue plus transparent red; fully transparent image; oversized header; when decoded; assert blue is #0000ff; transparent returns None; oversized raises 413 before full decode.
- [ ] `test_invalid_reference_has_no_hash_color` — Given base64 of arbitrary bytes; when hatch requested; assert invalid_reference_image 400; no job created.

- [ ] Add fixtures generated in memory with Pillow, named pixel/alpha/bounds cases.
- [ ] Run new cases red, confirming current hash output violates exact expected colors.
- [ ] Replace hashing with bounded pixel decoding and specified alpha-weighted mean.
- [ ] Run complete pet suite; verify same reference works through hatch and remix.

**Verification:**

- `python -m pytest tests/test_h214_h238_h590_pets.py -q` — Expected: Pixel, malformed/decompression and existing hatch/remix/archive regressions pass.

**Stop:** Stop on a changed base/interface or overlapping writer; inspect and reconcile without overwrite. Stop if Pillow is unavailable in the supported runtime; do not add a custom decoder.

**Rollback:** Revert only this packet’s isolated change; preserve user data and other branches. No automatic runtime rollback or data deletion.

### SM-015: Correct benchmark claims and define honest competitor comparison

**State:** `ready` · **Priority:** P1 · **Risk:** low.

**Goal:** Users can distinguish hermetic Nerva invariant results from unmeasured Hermes/OpenClaw product comparisons.

**Files:**
- Modify: `scripts/bench_nerva_differentiators.py`
- Modify: `tests/test_bench_nerva_differentiators.py`
- Modify: `docs/benchmarks/nerva-vs-hermes-openclaw-2026-11-14.md`
- Modify: `docs/benchmarks/nerva-vs-hermes-openclaw-2026-11-14.json`

**Interfaces:**
- Existing render_markdown_report, run_all_benchmarks and --json-out/--md-out/--check CLI remain compatible.
- Report scope explicitly: synthetic backends, live_network_llm_calls=0, no competitor executable run, baseline is a synthetic pattern. Replace Hermes / OpenClaw Default and Why Nerva wins headings.
- Methodology section requires actual product/version/commit, configuration, models, hardware, network, task fixtures, repetitions, raw timings/errors, prices and confidence/variance before any competitor win claim. Missing measurements render not measured, never numeric zero.
- B1 currently gathers every proposer and loading is outside generate timeout: describe those limits; B3 explicitly requires old-owner demotion; B5 helper ordering is harness-only at pinned base.

**Dependencies:** None; recheck base freshness.

**Red → green → verify:** Named cases below are required additions to the declared test paths; run them before production changes and confirm the behavioral assertion fails. Then implement only the specified interface and rerun the same cases plus the focused suites.

- [ ] `test_report_cannot_claim_unrun_competitor_win` — Given hermetic run without competitor records; when markdown rendered; assert synthetic baseline labelled; competitor not measured; no product-win conclusion.
- [ ] `test_report_discloses_quorum_and_fencing_limits` — Given B1/B3/B5 results; when report rendered; assert no early-quorum bound, transparent failover or production LWW attributed without production evidence.

- [ ] Add named report assertions before changing copy/schema.
- [ ] Run focused suite red on misleading headings/claims.
- [ ] Change generated report text and metadata, preserve invariant checks and all raw values.
- [ ] Regenerate the two artifacts using runner; run --check and tests. Record no competitor measured; real comparison remains external.

**Verification:**

- `python -m pytest tests/test_bench_nerva_differentiators.py -q` — Expected: Regression tests pass and actual invariants retain their meaning.
- `python scripts/bench_nerva_differentiators.py` — Expected: Regenerates only declared artifacts with synthetic scope and no competitor win.
- `python scripts/bench_nerva_differentiators.py --check` — Expected: Reproducibility & link integrity check: OK; never described as real competitor acceptance.

**Stop:** Stop on a changed base/interface or overlapping writer; inspect and reconcile without overwrite. Do not install/run paid competitors or providers in this correction.

**Rollback:** Revert only this packet’s isolated change; preserve user data and other branches. No automatic runtime rollback or data deletion.

### SM-016: Recover Lot5 Kanban dispatch on a separate integration branch

**State:** `ready` · **Priority:** P1 · **Risk:** medium.

**Goal:** Owners can submit governed board dispatch from the HUD with visible refusal and pending states, without overwriting paused work.

**Files:**
- Modify: `frontend/src/panels/autonomy-legacy.tsx`
- Modify: `frontend/src/panels/autonomy-legacy.test.tsx`
- Modify: `tests/test_hud_v2_parity.py`
- Modify: `docs/design/HUD_V2_REMAINING.md`
- Modify: `docs/handoff/antigravity-2026-11-14/CONTINUATION_LEDGER.md`

**Interfaces:**
- Donor antigravity/lot5-kanban frozen SHA 37a3a5615b220e8bacc1fcee16580b746b19205a; verify object/ref and actual changed paths before adoption.
- Existing POST /api/autonomy/kanban/dispatch admin_guard; KanbanDispatchBody extra=forbid, board ^[a-z0-9][a-z0-9_-]{0,63}$ default default, strict limit integer 1..16 default 4.
- 503 governed_worker_unavailable, 409 conflict, 422 invalid body remain visible; successful intake is not completed worker execution. No backend flag enablement.

**Dependencies:** None; recheck base freshness.

**Red → green → verify:** Named cases below are required additions to the declared test paths; run them before production changes and confirm the behavioral assertion fails. Then implement only the specified interface and rerun the same cases plus the focused suites.

- [ ] `lot5_dispatch_refusals` — Given owner enters valid board and limit; when server returns 503/409/422; assert alert shows refusal and no completed-task badge.
- [ ] `lot5_dispatch_invalid_body` — Given negative/fractional limit or bad board; when owner submits; assert client blocks request; backend contract unchanged.
- [ ] `lot5_donor_safety` — Given donor and target both available; when integration prepared; assert new branch based on verified repaired base; donor and existing PR refs unchanged; duplicate patch not reapplied.

- [ ] Inspect clean status, base and donor ancestry/diff; record exact SHAs. Create a new isolated integration branch; never reset donor or #1359–#1368 branches.
- [ ] Inspect whether donor patch already exists using ancestry and content; adopt only missing owned changes; stop on unrelated donor paths/conflicts.
- [ ] Run named new UI cases red if wiring absent; port smallest verified implementation.
- [ ] Run frontend focused suite, typecheck and parity checks on combined head. Only update counts after an actual fresh count; do not claim 8 uncalled routes before integration.
- [ ] Record exact head and actual tests in handoff. Publication, if separately authorized, is draft only and requires exact-head CI inspection; no merge/deploy.

**Verification:**

- `git show --stat 37a3a5615b220e8bacc1fcee16580b746b19205a` — Expected: Donor object exists and changed paths match intended dispatch slice; otherwise stop.
- `cd frontend && npm test -- src/panels/autonomy-legacy.test.tsx` — Expected: Mounted dispatch success/refusal/validation cases pass.
- `cd frontend && npm run typecheck` — Expected: Exit 0 on combined branch.
- `python -m pytest tests/test_hud_v2_parity.py tests/test_hermes_kanban_dispatch_wiring.py tests/test_doc_reference_integrity.py -q` — Expected: Combined route caller, dispatch authorization and document references pass.

**Stop:** Stop on a changed base/interface or overlapping writer; inspect and reconcile without overwrite. Missing donor objects or changed donor ref: read-only inspect first; never invent patch from handoff prose. Combined base CI regressions remain blockers to claiming integration complete.

**Rollback:** Revert only this packet’s isolated change; preserve user data and other branches. No automatic runtime rollback or data deletion.

### SM-017: Triage Lot5 core WIP with bounded tests before adoption

**State:** `ready` · **Priority:** P1 · **Risk:** high.

**Goal:** Produce a reviewable decision for one core WIP behavior so untested policy/env changes are not silently shipped.

**Files:**
- Create (new): `docs/superpowers/plans/2026-11-14-small-model-backlog/evidence/lot5-core-triage.md`

**Interfaces:**
- Donor cc7aba9a8301251884b1770425313b0a9cd21e2f is explicitly UNVERIFIED; 16 files span CLI, env, profiles, approvals and compaction. agents/core/profiles.py is donor-only at this base; inspect with git show, not a nonexistent working-tree path.
- Deliverable is a decision record with exact donor/base, hunk map, one behavior selected, test names/assertions, authority/data impact and adopt/reject/needs_design verdict. No production patch adoption in this packet.
- New evidence file declared above; proposed tests must use isolated temp env/profile state and fake side effects. Privilege/env-write semantics require explicit contract review.

**Dependencies:** None; recheck base freshness.

**Gate:** Produce the specified review/design/evidence record. Do not fabricate red/green results or adopt source while this gate remains unresolved.

- [ ] `core_triage_has_bounded_contract` — Given 16-file WIP donor; when triage completes; assert every file categorized; one bounded follow-on change specifies owned paths, exact failing regression and rollback.
- [ ] `core_triage_never_certifies_unrun` — Given no donor suite was previously run; when record written; assert historical unverified status retained; executed checks separated from planned red/green tests.

- [ ] Inspect donor with git show --stat and diff only its 16 paths against donor parent; do not cherry-pick whole WIP.
- [ ] Select one behavior (profile env precedence or compaction boundary); map existing signatures and test fixtures.
- [ ] Specify one named red test and expected old/new results; run existing focused baseline suites only, record failures without changing them.
- [ ] Write adopt/reject/needs_design decision; any implementation needs a fresh packet capped at three production files and a real red-green cycle.

**Verification:**

- `git show --stat cc7aba9a8301251884b1770425313b0a9cd21e2f` — Expected: 16-file unverified core donor identifiable; mismatch stops triage.
- `python -m pytest tests/test_h595_code_env.py tests/test_h391_turn_compaction.py tests/test_h689b_profile_env.py -q` — Expected: Record actual baseline outcomes; failures are not waived or reported as passing.

**Stop:** Stop on a changed base/interface or overlapping writer; inspect and reconcile without overwrite. Donor absent: record unavailable object and no adoption. Any unstated env precedence or authority expansion -> needs_design; small model must not infer policy.

**Rollback:** Revert only this packet’s isolated change; preserve user data and other branches. No automatic runtime rollback or data deletion.

### SM-018: Triage Lot5 gateway WIP at identity and token boundaries

**State:** `ready` · **Priority:** P1 · **Risk:** high.

**Goal:** Produce bounded adoption decisions for gateway WIP while protecting group identity, webhook delivery and OAuth tokens.

**Files:**
- Create (new): `docs/superpowers/plans/2026-11-14-small-model-backlog/evidence/lot5-gateway-triage.md`

**Interfaces:**
- Donor 207eda49bc5d39cada27b58f1f58e9eba9cef017: six files, UNVERIFIED; agents/core/channels/slack_ai_surfaces.py is donor-only at this base (inspect via git show). Do not import a 2,244-line patch as a single delivery.
- New triage evidence maps each changed externally visible signature, actor binding, retry/cancellation behavior, token persistence and matching current tests. Select one independent contract for a follow-on packet.
- No live Slack/webhook/OAuth requests; fake transports, clocks and temp credential storage only.

**Dependencies:** None; recheck base freshness.

**Gate:** Produce the specified review/design/evidence record. Do not fabricate red/green results or adopt source while this gate remains unresolved.

- [ ] `gateway_triage_preserves_identity` — Given six-file donor; when review written; assert actor/session pairing and token boundaries are explicit for every hunk; ambiguous authority remains needs_design.
- [ ] `gateway_triage_has_red_first_follow_on` — Given one behavior selected; when next slice proposed; assert named regression proves duplicate delivery, cross-principal or cancellation invariant before adoption; remaining WIP stays untouched.

- [ ] Read donor stat then diffs separately by gateway/group, Slack, webhook and OAuth.
- [ ] Map each behavior to current tests; choose one bounded regression contract, do not alter all six files.
- [ ] Run existing three baseline suites and record exact outcomes.
- [ ] Write triage decision, precise follow-on test name/expected denial, overlap and rollback. Do not promote Hermes equivalence.

**Verification:**

- `git show --stat 207eda49bc5d39cada27b58f1f58e9eba9cef017` — Expected: Six-file unverified donor available; absent object -> blocked evidence only.
- `python -m pytest tests/test_h083_slack_claims.py tests/test_h153b_webhook_delivery.py tests/test_h16_1_mcp_oauth.py -q` — Expected: Actual baseline reported with no live external requests.

**Stop:** Stop on a changed base/interface or overlapping writer; inspect and reconcile without overwrite. Unclear delivery replay or credential ownership semantics -> needs_design before code adoption.

**Rollback:** Revert only this packet’s isolated change; preserve user data and other branches. No automatic runtime rollback or data deletion.

### SM-019: Expose provider selection status natively without expanding authority

**State:** `ready` · **Priority:** P2 · **Risk:** medium.

**Goal:** A mobile owner can inspect the real admitted provider selection and understand unavailable or stale state.

**Files:**
- Modify: `mobile/src/api/client.ts`
- Modify: `mobile/src/screens/StatusScreen.tsx`
- Create (new): `mobile/src/api/__tests__/providerSelection.test.ts`
- Create (new): `mobile/src/screens/__tests__/providerSelectionStatus.test.ts`
- Modify: `mobile/PARITY.md`

**Interfaces:**
- NEW export fetchProviderSelectionStatus(config: ServerConfig): Promise<Record<string, unknown>> in existing client.ts uses GET /api/admin/llm/provider-selection with admin:true and no mutation.
- selection_status in providers/install_service.py returns {status: unselected}, or {status: selected|stale, provider, model, package_hash, revision, credential_generation}. StatusScreen projects only status/provider/model/revision after validating known status, bounded strings and nonnegative safe revision. Strip package_hash and credential_generation. Unselected, stale and unavailable are distinct.
- PUT SelectBody/ClearBody expected_revision CAS, signed package_hash, explicit consent and credential lifecycle remain exclusively existing HUD/backend; mobile view supplies no decisions or keys. New tests declared in owned_files.

**Dependencies:** None; recheck base freshness.

**Red → green → verify:** Named cases below are required additions to the declared test paths; run them before production changes and confirm the behavioral assertion fails. Then implement only the specified interface and rerun the same cases plus the focused suites.

- [ ] `providerSelection_read_is_admin_scoped` — Given configured admin token; when Status is opened; assert GET uses X-Admin-Token; UI contains no rotate/promote/select controls or credentials.
- [ ] `providerSelection_stale_result_is_hidden` — Given old connection request is pending; when connection/token changes then old reply arrives; assert old provider/model is not rendered.
- [ ] `providerSelection_refusal` — Given 401/403/409/503 or malformed result; when read completes; assert unavailable/error shown; no success badge or fallback provider fabricated.

- [ ] Read exact GET response shape and existing mobile request/error/connection-epoch patterns.
- [ ] Add new API and mounted status tests, run red for missing section/export.
- [ ] Add bounded read projection and mounted status panel; link Settings when admin token missing; invalidate on refresh and connection changes.
- [ ] Run new tests plus existing provider HUD tests; add native read-only row to PARITY, keep provider management/native mutations open.

**Verification:**

- `cd mobile && npm test -- --runInBand src/api/__tests__/providerSelection.test.ts src/screens/__tests__/providerSelectionStatus.test.ts` — Expected: Admin auth, malformed/no-selection, refusals and stale connection tests pass.
- `cd mobile && npx tsc --noEmit` — Expected: Exit 0.
- `cd frontend && npm test -- src/panels/provider-packages.test.tsx` — Expected: Existing explicit-consent, credential clearing and CAS refusal tests remain green.

**Stop:** Stop on a changed base/interface or overlapping writer; inspect and reconcile without overwrite. If current GET includes secret material or authority is unclear, stop and write design before mobile exposure.

**Rollback:** Revert only this packet’s isolated change; preserve user data and other branches. No automatic runtime rollback or data deletion.

### SM-020: Make manual room failover admission explicit

**State:** `ready` · **Priority:** P1 · **Risk:** medium.

**Goal:** An owner promoting a room replica explicitly acknowledges that the old host can still write until manually demoted.

**Files:**
- Modify: `agents/core/routers/rooms.py`
- Modify: `agents/cli/rooms.py`
- Modify: `frontend/src/gap.tsx`
- Modify: `tests/test_h657_room_failover.py`
- Modify: `frontend/src/test/gap-panels.test.tsx`
- Create (new): `docs/superpowers/plans/2026-11-14-small-model-backlog/evidence/manual-room-failover.md`

**Interfaces:**
- Existing RoomStore.promote(room_id, *, confirm=False, new_host=None, reason="") and demote(room_id, *, proof: dict) remain manual local primitives.
- Extend HTTP RoomPromoteBody with StrictBool acknowledge_manual_demotion=False. POST /api/rooms/{room_id}/promote refuses absent/false ack with 409 manual_demotion_ack_required before store mutation; still require existing confirm=True.
- Successful HTTP response adds failover_mode=manual and old_owner_demotion_required=True; never asserts demotion completed. Existing /replica-state, /replicate and /demote routes retain auth/proof validation.
- Verified current class is RoomStore(JsonStore), not RoomsStore. Current router RoomPromoteBody fields are confirm: bool=False, new_host max_length=80, reason max_length=300. Do not change RoomStore.promote signature or store proof fields.
- Existing CLI agents/cli/rooms.py promote parser and execute promote branch currently serialize {confirm: bool(ns.confirm), new_host: ns.host, reason: ns.reason}. Add --acknowledge-manual-demotion action=store_true default false, with help: The old owner can still write until manually demoted. Serialize acknowledge_manual_demotion: bool(ns.acknowledge_manual_demotion) alongside existing fields. Both --confirm and this flag required for HTTP success; no automatic true value or interactive prompt in scripts.
- Existing HUD is RoomsPanel in frontend/src/gap.tsx; promoteRoom currently posts {confirm: confirmPromote}. Add independent unchecked acknowledgement checkbox labelled I understand the old owner can still write until I manually demote or isolate it. Disable promotion unless both checkboxes are checked; POST {confirm: confirmPromote, acknowledge_manual_demotion: acknowledgeManualDemotion}, admin:true. Clear acknowledgement on selected-room change and after every submit outcome, including refusal; never infer it from confirmPromote.
- Existing tests/test_h657_room_failover.py::test_h657_http_router_and_cli_round_trip must supply the new explicit acknowledgement in successful HTTP and CLI examples; add absent/false cases that remain 409 without changing epoch. Existing frontend/src/test/gap-panels.test.tsx imports RoomsPanel: extend it with mounted checkbox, exact request body, selection-change reset and 409 refusal cases. All caller changes ship in the same packet.

**Dependencies:** None; recheck base freshness.

**Red → green → verify:** Named cases below are required additions to the declared test paths; run them before production changes and confirm the behavioral assertion fails. Then implement only the specified interface and rerun the same cases plus the focused suites.

- [ ] `test_http_promotion_requires_manual_demotion_ack` — Given replica with prior owner; when POST confirm true without ack; assert 409 manual_demotion_ack_required, epoch/role unchanged.
- [ ] `test_manual_ack_does_not_fence_uncontacted_owner` — Given two replicated stores; when promote with confirm+ack; assert new host active; old host still writable before explicit valid proof demotion; reply warns manual demotion required.
- [ ] `test_demotion_proof_blocks_old_owner_writes` — Given valid signed promotion proof; when old owner receives demote; assert stale write refused; tampered proof rejected.
- [ ] `test_cli_manual_demotion_ack_serialized` — Given rooms promote with --confirm and explicit --acknowledge-manual-demotion; when CLI builds HTTP request; assert both booleans true are sent with unchanged host/reason; missing flag sends false and cannot succeed.
- [ ] `RoomsPanel manual failover acknowledgement` — Given mounted RoomsPanel with selected replica; when owner checks both confirmations and submits; assert one admin POST includes both true flags; checkbox reset after submit/error/room change; no implicit acknowledgement.

- [ ] Add named HTTP admission and two-host tests alongside existing split-brain case; run red.
- [ ] Implement request-boundary ack and truthful additive response fields, no consensus algorithm or distributed lock.
- [ ] Update existing CLI promote parser/payload and RoomsPanel checkbox/payload together with router guard. Extend existing HTTP/CLI round-trip and mounted gap-panel tests before changing callers; confirm all three surfaces red first, then green together.
- [ ] Run room suite; write two-host operator sequence including old-host isolation when unreachable, proof transfer, demotion verification and rollback limits.

**Verification:**

- `python -m pytest tests/test_h657_room_failover.py -q` — Expected: Admission has no pre-ack mutation; explicit demotion fencing and forged-proof rejection pass.
- `cd frontend && npm test -- src/test/gap-panels.test.tsx` — Expected: RoomsPanel requires both explicit confirmations, serializes acknowledgement, clears it on room changes/errors and surfaces refusal.
- `cd frontend && npm run typecheck` — Expected: Exit 0 with complete router/CLI/HUD caller contract.

**Stop:** Stop on a changed base/interface or overlapping writer; inspect and reconcile without overwrite. Do not claim automatic safe failover or invent distributed consensus. Any additional promotion caller discovered must be mapped and migrated in this same delivery; otherwise set needs_design and do not land the server guard alone.

**Rollback:** Revert only this packet’s isolated change; preserve user data and other branches. No automatic runtime rollback or data deletion.

### SM-021: Run real macOS TCC upgrade acceptance as external matrix

**State:** `external` · **Priority:** P1 · **Risk:** high.

**Goal:** Provide evidence whether real macOS permission grants survive managed Python update, separately from simulated codesign tests.

**Files:**
- Create (new): `docs/superpowers/plans/2026-11-14-small-model-backlog/evidence/macos-tcc-matrix.md`

**Interfaces:**
- Existing anchor_venv_interpreter entry point and test_live_macos_venv_codesign_and_boot_gate_end_to_end; platform skip is unavailable evidence, not pass.
- External matrix: macOS version/arch, managed Python source/version before+after, codesign identity/path/hash, launch identity (terminal vs installed app), actual permissions exercised, before/after grant behavior, refusal result and rollback outcome. At least supported Apple Silicon host; Intel only if advertised supported.
- No tccutil reset, TCC DB editing, disabled SIP or fabricated grant state. Update/permission actions require an authorized real test device and owner interaction where macOS requests it.

**Dependencies:** None; recheck base freshness.

**Gate:** Produce the specified review/design/evidence record. Do not fabricate red/green results or adopt source while this gate remains unresolved.

- [ ] `mac_tcc_grant_survives_real_upgrade` — Given real host with an explicitly granted supported permission; when managed Python upgrade under same launch identity; assert actual permitted operation works afterward without unexplained regrant, with before/after evidence; otherwise fail.
- [ ] `mac_tcc_denial_stays_denied` — Given permission explicitly denied; when upgrade then operation retried; assert operation remains denied; no bypass or self-granted permission.
- [ ] `mac_tcc_external_unavailable` — Given Linux or unmanaged host; when test is skipped; assert matrix cell unavailable; H690 remains unaccepted live.

- [ ] Prepare matrix and isolate host/app/permission requirements; record all unrun cells unavailable.
- [ ] On authorized macOS host run existing live codesign/boot gate and record exact revision/output.
- [ ] Perform manual permission operation before and after genuine supported upgrade; record prompts and refusal without sensitive content.
- [ ] Test supported rollback on disposable venv; retain grants/data; publish evidence only after actual run.

**Verification:**

- `python -m pytest tests/test_h690_macos_tcc_anchor.py -q` — Expected: Record actual passed/skipped count; Linux skips provide no TCC persistence proof.

**Stop:** Stop on a changed base/interface or overlapping writer; inspect and reconcile without overwrite. No authorized macOS host: deliver matrix only, keep external. Platform refusal stops this cell; no workaround retry.

**Rollback:** Revert only this packet’s isolated change; preserve user data and other branches. No automatic runtime rollback or data deletion.

### SM-022: Design cost cascade authority before HybridRouter integration

**State:** `needs_design` · **Priority:** P2 · **Risk:** high.

**Goal:** Determine whether an optional cost cascade can route safely without cloud-policy, physical-request accounting or model-selection regressions.

**Files:**
- Create (new): `docs/superpowers/plans/2026-11-14-small-model-backlog/evidence/cost-cascade-design.md`

**Interfaces:**
- Lot5-bench donor bd93bff5caf993bd150828a87d3cd1b4bfd88fa5 adds agents/core/llm/cost_cascade.py; this file is ABSENT at pinned base. Inspect donor before defining any class/function signature.
- Required design output: actual AdaptiveCostCascade signature, HybridRouter insertion point, chosen model authority, strict-local exclusions frigga/ultron/howard, cloud-only athena, opt-in flag default false, physical_request_scope ownership and budget atomicity.
- No production router/cascade modification authorized by this packet. Estimated B6 savings are hermetic estimates, not billed live cost.

**Dependencies:** None; recheck base freshness.

**Gate:** Produce the specified review/design/evidence record. Do not fabricate red/green results or adopt source while this gate remains unresolved.

- [ ] `cascade_design_preserves_model_authority` — Given actual donor inspected; when integration contract proposed; assert selection, fallback, price-unknown, cancellation and budget owner explicit; no bypass of data-handling policy.
- [ ] `cascade_design_bounds_physical_requests` — Given retry/stream/error cases; when test plan written; assert every physical attempt accounted exactly once; no cloud request for strict-local agents; no spend cap overrun claimed from unrun tests.

- [ ] Read exact donor cascade and current router signatures using git show; record absent object as blocker.
- [ ] Map request lifecycle, retry/streaming, physical_request_scope and policy admission; identify whether cascade or router owns each step.
- [ ] Specify deterministic fake-backend red tests and default-off rollout; list unresolved semantics instead of implementing a guess.
- [ ] Finish needs_design until coordinator accepts exact interface/authority. New implementation packet must cap production paths and include rollback flag.

**Verification:**

- `git show bd93bff5caf993bd150828a87d3cd1b4bfd88fa5:agents/core/llm/cost_cascade.py` — Expected: Inspect actual donor API without installing it; missing object means design blocked.

**Stop:** Stop on a changed base/interface or overlapping writer; inspect and reconcile without overwrite. Unresolved authority, unknown prices or scope ownership: no production integration.

**Rollback:** Revert only this packet’s isolated change; preserve user data and other branches. No automatic runtime rollback or data deletion.

### SM-023: Deliver native Kanban board and explicit governed dispatch

**State:** `ready` · **Priority:** P2 · **Risk:** medium.

**Goal:** Phone owners can inspect a durable board and request governed dispatch while seeing approval/run states accurately.

**Files:**
- Modify: `mobile/src/api/client.ts`
- Modify: `mobile/src/screens/TasksScreen.tsx`
- Create (new): `mobile/src/api/__tests__/kanban.test.ts`
- Create (new): `mobile/src/screens/__tests__/kanbanControls.test.ts`
- Modify: `mobile/PARITY.md`

**Interfaces:**
- NEW client.ts exports fetchKanbanBoards(config), fetchKanbanBoard(config, slug), dispatchKanban(config, {board,limit}); derive read types from current dashboard_api + frontend types, not display-string guesses.
- GET /api/kanban/boards, GET /api/kanban/board?board=<encoded>, POST /api/autonomy/kanban/dispatch all admin:true. Dispatch retries=0; strict board/limit bounds exactly SM-016 contract.
- TasksScreen board section separate from existing tasks. Request dispatch only on explicit tap; pending approval remains pending and links existing Approvals tab if available. No new approval API or execute button.
- NEW types in existing client.ts: NativeBoardMeta={slug:string; name?:string|null; is_current?:boolean; total?:number}; NativeBoardsResponse={boards:NativeBoardMeta[]; current:string}; NativeKanbanTask={id:string; title:string; status:string}; NativeKanbanBoard={columns:{name:string; tasks:NativeKanbanTask[]}[]; latest_event_id:number; now:number}. Project only these existing dashboard fields; validate bounded identifiers, strings and nonnegative safe integer counters, throw ApiError on malformed required fields.
- NEW NativeKanbanDispatch={ok:boolean; status:queued|busy|refused; reason?:string; queued:{task_id:string; queue_id:string; status:string}[]}, with status represented as a TypeScript string-literal union. Exact async signatures: fetchKanbanBoards(config:ServerConfig):Promise<NativeBoardsResponse>; fetchKanbanBoard(config:ServerConfig, slug:string):Promise<NativeKanbanBoard>; dispatchKanban(config:ServerConfig, body:{board:string;limit:number}):Promise<NativeKanbanDispatch>. Current dispatcher.request returns queued/busy/refused; queue status is server supplied, never reinterpret it as completion.

**Dependencies:** SM-016, SM-019

**Red → green → verify:** Named cases below are required additions to the declared test paths; run them before production changes and confirm the behavioral assertion fails. Then implement only the specified interface and rerun the same cases plus the focused suites.

- [ ] `kanban_dispatch_not_execution` — Given valid selected board; when dispatch returns intake/pending approval; assert UI says requested/pending; does not mark completed.
- [ ] `kanban_unavailable_does_not_enable_flags` — Given Kanban or worker disabled, or absent admin token; when screen loads/dispatch tapped; assert 503/unavailable or Settings guidance; no setting mutation.
- [ ] `kanban_late_dispatch_is_not_replayed` — Given dispatch times out or owner changes board/connection; when request completes late; assert no auto retry; old response cannot alter new board; manual refresh allowed.

- [ ] Write new API/mounted cases for board, strict limit, 401/403/409/422/503 and stale context; run red.
- [ ] Add typed read/dispatch helpers in existing client using existing auth transport; preserve retries=0 on POST.
- [ ] Mount board selection and explicit dispatch in TasksScreen; render actual task states and safe pending labels.
- [ ] Run focused tests/typecheck; update partial H18.34 parity row, retain physical device/provider acceptance open.

**Verification:**

- `cd mobile && npm test -- --runInBand src/api/__tests__/kanban.test.ts src/screens/__tests__/kanbanControls.test.ts` — Expected: Board selection, guarded one-shot dispatch and refusal/stale-context cases pass.
- `cd mobile && npx tsc --noEmit` — Expected: Exit 0.

**Stop:** Stop on a changed base/interface or overlapping writer; inspect and reconcile without overwrite. If existing navigation cannot reach approvals, display pending with instruction; do not invent approval authority.

**Rollback:** Revert only this packet’s isolated change; preserve user data and other branches. No automatic runtime rollback or data deletion.

### SM-024: Deliver native memory budgets and owner switch

**State:** `ready` · **Priority:** P2 · **Risk:** medium.

**Goal:** Phone owners see true curated-memory ring budgets and can explicitly switch memory without deleting their stores.

**Files:**
- Modify: `mobile/src/api/client.ts`
- Modify: `mobile/src/screens/MemoryScreen.tsx`
- Create (new): `mobile/src/api/__tests__/memoryControls.test.ts`
- Create (new): `mobile/src/screens/__tests__/memoryControls.test.ts`
- Modify: `mobile/PARITY.md`

**Interfaces:**
- NEW fetchMemoryStatus(config) uses GET /api/memory (distinct from existing fetchMemory GET /memory transcript). NEW setMemorySwitch(config, enabled:boolean) uses POST /api/memory/switch {enabled} admin:true retries:0.
- Project current GET body available/enabled/switch/cognition/stores and block_max_chars from _memory_status_body; stores[target] contains the ring bytes/entries/chars and char_budget, shown, omitted, blocked and rendered_chars fields (flat in each store, not nested core_block); never coerce absence to zero. Set result is authoritative only after refresh of current GET.
- Keep transcript/notes UI intact. Explicit owner toggle only; no reset/delete, bundle editor or goals form in this slice. H18.35 remains open for those remaining controls.
- Exact current ring keys verified in core_block_usage/_sections: entries, chars, char_budget, shown, omitted, blocked, rendered_chars, merged with store_sizes bytes. Display chars/char_budget, not a nonexistent nested core_block object. New helper signatures fetchMemoryStatus(config:ServerConfig):Promise<Record<string,unknown>> and setMemorySwitch(config:ServerConfig,enabled:boolean):Promise<Record<string,unknown>> preserve raw responses only until bounded projection at screen boundary.

**Dependencies:** SM-023

**Red → green → verify:** Named cases below are required additions to the declared test paths; run them before production changes and confirm the behavioral assertion fails. Then implement only the specified interface and rerun the same cases plus the focused suites.

- [ ] `memory_status_is_not_transcript` — Given transcript endpoint returns turns; when memory budget section loads; assert also GET /api/memory; ring sizes never inferred from turns.
- [ ] `memory_switch_saved_but_not_applied` — Given POST returns ok false/503 or runtime old value; when owner toggles; assert UI shows refusal/actual GET state; never optimistic enabled success.
- [ ] `memory_control_stale_context` — Given pending switch/read; when hub/token changes; assert old result ignored and no automatic switch on new hub.

- [ ] Add named status-vs-transcript, explicit switch and stale response cases; run red.
- [ ] Implement separate status projection/helper and switch; reuse existing admin transport with zero mutation retries.
- [ ] Mount ring size/budget and switch status in MemoryScreen; missing admin leads to Settings.
- [ ] Run new and existing memory tests/typecheck; record delivered subset in PARITY without closing bundle/goal/reset work.

**Verification:**

- `cd mobile && npm test -- --runInBand src/api/__tests__/memoryControls.test.ts src/screens/__tests__/memoryControls.test.ts src/api/__tests__/memoryNotes.test.ts` — Expected: Budget projection, truthful switch and existing transcript behavior pass.
- `cd mobile && npx tsc --noEmit` — Expected: Exit 0.

**Stop:** Stop on a changed base/interface or overlapping writer; inspect and reconcile without overwrite. Unexpected runtime status schema: stop, inspect route; do not reinterpret turns as memory stats.

**Rollback:** Revert only this packet’s isolated change; preserve user data and other branches. No automatic runtime rollback or data deletion.

### SM-025: Render native per-turn recall without speech or persistence

**State:** `ready` · **Priority:** P2 · **Risk:** low.

**Goal:** Native chat shows the server’s current-turn recall explanation under the reply while keeping it out of spoken and stored text.

**Files:**
- Modify: `mobile/src/chat/turnOutcome.ts`
- Modify: `mobile/src/screens/ChatScreen.tsx`
- Create (new): `mobile/src/chat/__tests__/turnOutcomeRecall.test.ts`
- Modify: `mobile/src/chat/__tests__/conversation.test.ts`
- Create (new): `mobile/src/screens/__tests__/recallLine.test.ts`
- Modify: `mobile/PARITY.md`

**Interfaces:**
- Extend existing TurnOutcome (currently latency_ms only) with optional validated recall; normalizeTurnOutcome consumes untrusted evt.outcome via existing streamChat onDone. Valid recall must survive even if latency_ms absent/invalid; make latency_ms optional and preserve current duration display guards.
- Mirror closed schema nerva.recall-status.v1 and frontend recallLine/recallLines using shared fixture cases; last prefetch per provider only, no memory content. New helper recallLines(outcome): string[] in turnOutcome.ts.
- Conversation already clears turnOutcome on new work/history/stop/context invalidation; extend tests to recall lifecycle. Render separate accessible Text after reply, never append to assistant content, toPlain TTS or saved messages.

**Dependencies:** None; recheck base freshness.

**Red → green → verify:** Named cases below are required additions to the declared test paths; run them before production changes and confirm the behavioral assertion fails. Then implement only the specified interface and rerun the same cases plus the focused suites.

- [ ] `recall_matches_shared_cases` — Given frontend recall-line-cases.json fixtures; when native recallLines invoked; assert same lines including relevant-memory and malformed omission cases.
- [ ] `recall_without_latency` — Given valid recall with absent/invalid latency_ms; when SSE end processed; assert recall renders; invalid duration omitted.
- [ ] `recall_is_ephemeral_and_silent` — Given reply with recall then new turn/stop/session/agent/hub change; when state transitions or TTS/storage invoked; assert recall clears; spoken and persisted assistant text has no recall footer.

- [ ] Add new shared-fixture projection tests and extend existing conversation tests; add mounted recall/TTS separation test; run red.
- [ ] Extend TurnOutcome projection and helper with exact closed schema; preserve latency safety and do not alter network protocol.
- [ ] Render ephemeral accessible recall lines beneath reply. If optional latency typing exposes callers, adjust only duration guard in owned ChatScreen; stop for broader interface changes.
- [ ] Run focused suites and tsc; update parity row with device accessibility acceptance still open.

**Verification:**

- `cd mobile && npm test -- --runInBand src/chat/__tests__/turnOutcomeRecall.test.ts src/chat/__tests__/conversation.test.ts src/screens/__tests__/recallLine.test.ts src/api/__tests__/streamChat.test.ts` — Expected: Shared recall cases, latency compatibility, lifecycle, TTS and storage boundaries pass.
- `cd mobile && npx tsc --noEmit` — Expected: Exit 0; optional latency callers accounted for.

**Stop:** Stop on a changed base/interface or overlapping writer; inspect and reconcile without overwrite. If TurnOutcome consumers beyond owned paths require changes, negotiate expanded ownership before editing.

**Rollback:** Revert only this packet’s isolated change; preserve user data and other branches. No automatic runtime rollback or data deletion.

### SM-026: Deliver native roster inspection and explicit agent rename

**State:** `ready` · **Priority:** P2 · **Risk:** medium.

**Goal:** A phone owner can inspect the real agent roster and rename one agent through the existing Action Kernel guarded route.

**Files:**
- Modify: `mobile/src/api/client.ts`
- Modify: `mobile/src/screens/SettingsScreen.tsx`
- Create (new): `mobile/src/api/__tests__/agentRoster.test.ts`
- Create (new): `mobile/src/screens/__tests__/agentRoster.test.ts`
- Modify: `mobile/PARITY.md`

**Interfaces:**
- NEW fetchAgentRoster(config) GET /api/admin/agents/roster; NEW renameRosterAgent(config, agentId, name) POST /api/admin/agents/{encoded_agent_id}/rename {name}; admin:true, retries:0.
- Derive name/id constraints and response projection from current AgentRenameBody (name length 1..64, extra forbid)/agent_roster validation. Preserve immutable id; rename changes display name only. No create, retire, restore, persona or learned-entry editor in this slice.
- Mount owner roster section inside existing SettingsScreen; no new navigation route. Preserve server Action Kernel denial, default-off posture and revision/audit handling; caller cannot supply actor authority.

**Dependencies:** SM-024

**Red → green → verify:** Named cases below are required additions to the declared test paths; run them before production changes and confirm the behavioral assertion fails. Then implement only the specified interface and rerun the same cases plus the focused suites.

- [ ] `roster_rename_preserves_id` — Given owner selects existing roster entry; when explicit rename submits; assert one admin POST with encoded immutable id and body name; refresh roster on success.
- [ ] `roster_kernel_refusal_is_visible` — Given 401/403/409/422/503 or kernel denial; when rename submitted; assert no successful rename badge or local roster mutation; entered name retained for correction.
- [ ] `roster_connection_change_invalidates_form` — Given edit pending for hub A; when switch to hub B; assert old target/form/result cleared; no accidental POST to B.

- [ ] Read exact rename request limits and GET response; add API and mounted refusal/connection tests, run red.
- [ ] Add existing-transport helpers and Settings roster form with explicit submit, disabled in flight.
- [ ] Refresh authoritative roster only after success; ignore stale responses and preserve immutable id.
- [ ] Run focused tests/typecheck; add partial native row keeping create/retire/restore and H046 Today work open.

**Verification:**

- `cd mobile && npm test -- --runInBand src/api/__tests__/agentRoster.test.ts src/screens/__tests__/agentRoster.test.ts` — Expected: Admin auth, immutable id, no retries, kernel refusal and stale context tests pass.
- `cd mobile && npx tsc --noEmit` — Expected: Exit 0.

**Stop:** Stop on a changed base/interface or overlapping writer; inspect and reconcile without overwrite. Unknown rename authority/name limits or incompatible Settings mount -> design first; do not guess.

**Rollback:** Revert only this packet’s isolated change; preserve user data and other branches. No automatic runtime rollback or data deletion.

## Completion and integration

- [ ] Confirm only assigned paths changed; reread packet acceptance against the final diff.
- [ ] Record tests actually run, exact head, skipped external cells and remaining backlog subcontrols. No blanket H18 or Hermes closure for a partial slice.
- [ ] Review combined changes sequentially on an isolated integration branch; run applicable route/auth/parity suites and frontend/mobile typechecks. Do not reuse donor CI as combined-head proof.
- [ ] If a later authorized execution publishes a draft, inspect its exact head and each CI result. Preserve draft status; record pending/failure honestly; no merge/deploy.
