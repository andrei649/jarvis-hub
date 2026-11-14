# PR #1366 bounded read-only review

Generated 2026-11-14 UTC. Exact delta: `e39d9b659cb740a5ec14a50ff607803c6927b102..155c9150eeb42c279ec1c3ddcecaa86cc57752e5`. Reused `/workspace/scratch/colleague-review-20261114/core-review.md` and `ui-review.md`; their H040/H657/pets/benchmark findings belong to later lots and are not attributed to this delta. Inspected the actual MoA callers, policy checks, adapters, staging control flow and added HUD consumers. No source edits, tests invoking update/restart, service/install actions, provider calls, deployment or remote writes. No CI claims; root owns live CI and combined-main reconciliation.

## Recommendation

Fix the three concrete defects below before integration. H690's real TCC grant persistence remains a separate platform acceptance limitation, not evidence that signing itself fails. The implementation is substantial: real persistent MoA CRUD, concurrent proposers, quorum, aggregation, member model/local/H513 checks, CLI/API/HUD; actual OAuth/subagent/A2A/MCP/jobs/receipts callers exist. Static route counts alone do not certify complete equivalence.

## Concrete defects

### P1 — cloud MoA aggregators fail streaming due to unsupported callback keyword

`agents/core/llm/moa.py:671–679` unconditionally calls aggregator `generate_stream(..., on_activity=on_activity)`, including when the value is None. Production `AnthropicBackend.generate_stream` (`agents/core/llm/anthropic.py:422`) and `GeminiBackend.generate_stream` (`agents/core/llm/gemini.py:620`) accept `on_token` but have neither `on_activity` nor `**kwargs`. Both are selectable by `resolve_member_spec` (`moa.py:338–354`). A valid preset with either aggregator completes proposer work then fails TypeError during streaming synthesis. This affects the advertised normal streaming chat path, although POST `/api/llm/moa/run` calls nonstreaming generate and would pass. Existing `FakeBackend` inherits the base streaming method, which supports on_activity, so its passing streaming test misses real adapter compatibility.

Fix: pass supported callbacks based on the adapter signature, or extend all adapters consistently; add a regression using the real production adapter signatures with transport stubbed, not the permissive base fallback. Static signature/control-flow proof; no live cloud call performed.

### P1 — partial libpython staging failure loses the rollback journal

`agents/core/macos_tcc_anchor.py:169–193` replaces live `.venv/lib/libpython*.dylib` paths during `_stage_libpython`, and records `(dest,backup)` only *after* replacing stage into dest (`:189–192`). Caller initializes `lib_backups=[]` and assigns returned journal only if helper completes (`:259–262`). If stage→dest replacement raises after dest→backup succeeded, or a later library's copy/stat/replace fails after an earlier library committed, the helper never returns its journal. The outer exception handler sees the original empty journal and cannot restore touched libraries. The function returns an innocuous failure while a live library can be missing/replaced and backup stranded. This violates its rollback contract and can break the active venv on ordinary filesystem errors.

Fix: create the journal in the caller/pass it into staging, append each backup before the first destructive replace, and have staging restore its own incomplete operation on error; retain backups if recovery fails. This finding is static only. No fault-injected bootstrap/update/restart or anchor invocation was attempted, respecting the existing platform block. Existing tests cover signing/boot failures after successful library staging, not exceptions inside that staging loop.

### P2 — editing an active MoA preset bypasses the model-selection pin check

`agents/core/routers/moa.py:81` always uses `check_llm_write(selection=False)` for PUT, as does offline CLI set at `agents/cli/moa.py:85`. The active preset's content controls subsequent model/provider routing (`hybrid_router.py:859–868`), and PUT immediately invalidates the router cache. An already active preset can therefore be changed from one committee to another under an administrator selection pin: `selection=False` checks writability/managed lock but does not check `SELECTION_SETTINGS`; explicit activation and deletion of the active preset do check selection. Exact policy semantics are in `managed_scope.py:883–895` and `check_writable:702`: setting pins exist independently of the full managed lock.

Fix: when updating the active preset, enforce the same selection guard as activation/deletion, including offline CLI; avoid a read/check/write race by guarding the active-content mutation in the store transaction/lock. Test pinned selection with an existing active preset: activation, active edit and active deletion must agree. No mutation performed in this review.

## Authority follow-up to settle explicitly

Normal routing checks selected-cloud authority in `HybridRouter._check_selected_cloud_route`, but the new MoA wrapper route is named `hybrid-moa`, so the helper's `route.startswith('cloud')` early return excludes it. `resolve_member_spec` checks selected authority for `compatible:` members, whereas Gemini/Claude members resolve their legacy backend slots directly. `/api/llm/moa/run` also resolves directly. `_authorize_all_members` repeats strict-local/model/H513 checks but not selected-provider routing authority. This is a real inconsistency; whether an owner-defined mixed committee is intentionally allowed to use providers outside the selected main provider needs a documented policy decision. Do not call this a demonstrated credential leak: member H513/guest credential sharing gates are present. If selected-provider-required is a fail-closed floor for every provider call, apply it per member and reject stale/removed selections; add a focused regression. This is kept separate from the three concrete blockers rather than asserting intent not established by code.

## Honest limitations; no additional backlog expansion

- Reconfirmed colleague observation: `moa.py:495–543` waits on gather for every proposer; quorum is a success threshold, not early aggregation. `ensure_resident` precedes wait_for, so timeout does not bound model residency. Qualify latency/timeout claims or fix in bounded follow-up; concurrency and failure tolerance still exist.
- H690 uses staged signing and a boot gate. Linux/static evidence cannot demonstrate macOS Accessibility/Screen Recording grants survive managed Python replacement; the live macOS test is platform-gated. Stable ad-hoc identifier alone is insufficient acceptance evidence. Keep H690 partial until real platform upgrade/TCC acceptance is recorded. This does not authorize running a previously blocked adversarial update/restart action.
- HUD consumers are real; added subagent transcript/result/claim URLs, Nous login/poll/logout/status and A2A outbound calls match source. Older PR prose claiming `/start` or per-spawn `/claim` is stale. MCP elicitation schema metadata enables actual typed controls; jobs/receipt mutations remain backend-authorized. Source reachability is not live provider/device acceptance.
- No new suite run: this is a static bounded review reusing existing reports, with concrete signature and exception-flow findings. Full platform/security certification is not claimed.

Next action: fix streaming compatibility, staging journal preservation, and active-preset selection guard; root reruns relevant focused CI and combined integration checks at the new exact head.
