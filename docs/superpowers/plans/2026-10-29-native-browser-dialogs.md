# Native Browser Dialogs Implementation Plan

> **For agentic workers:** Execute this plan task by task with test-driven development. One assigned implementation author owns the listed files; do not delegate.

**Goal:** Supervise one native Chromium dialog observed during an exact governed browser operation and resolve it only through a separate human-approved `browser_dialog` task.

**Architecture:** The original worker task keeps the approved opening Playwright call and its exact `browser.step` receipt. A retained empty-context child observes a paired Playwright/CDP main-frame dialog, privately claims a distinct human-approved response row through the same worker, obtains its own `browser.dialog` Kernel receipt, and calls the native dialog method at most once. Model-facing pending discovery and proposal are separate from the owner decision; raw prompt values are sealed before generic persistence.

**Tech stack:** Python 3.12, FastAPI, SQLite-mediated autonomy queue, Action Kernel, Playwright Chromium/CDP, React Operator HUD.

**Spec:** `.superpowers/sdd/2026-10-28-local-completion/task-37-dialog-plan.md`, `task-37-controller-rulings.md`, `task-37-dialog-refinement.md` (the last document's addendum supersedes its owner-only proposal wording).

**Freshness:** Base `93498f9a8daa9630934ae94fabad0e032a56a034`; branch `codex/native-dialog-supervision-20261029`; generated 2026-10-29 Europe/Bucharest. This plan is the first changed path. Next action: synthetic RED probes, then implementation, actual local Chrome and focused verification. Head SHA will be recorded in `task-37-report.md` after commits.

## Global constraints

- Default off; installed Chrome uses a fresh temporary profile and generated loopback fixture only. No owner profile, external site, cloud, paid provider, new production dependency or production activation.
- One pending dialog, 60 seconds from capture within the existing 120-second plan and 600-second session. No-dialog steps retain 15 seconds. No policy or general worker-concurrency relaxation.
- The opener's `browser.step` receipt remains bound to its exact asyncio task. The response child starts with an empty Context, uses only a new exact `browser.dialog` scope, and is cancelled/joined before opener completion.
- Main-frame CDP `frameId`/loader/document and Playwright dialog/page must pair; same-URL child/OOPIF, missing evidence and unarmed events refuse. Frame attribution does not certify script cause.
- Model proposal is never a physical grant. Human approves the exact signed response row; a private same-worker CAS writes a one-use durable attempt before `Dialog.accept/dismiss`.
- Owner-entered prompt text enters only the private owner route. Model-suggested text may already exist in the upstream model/tool-call transcript; after ToolRPC sealing, no raw text enters task/receipt/Action/audit/log/generic result.
- Root owns generated API/schema/assets/status/claim metadata and publication. This author owns only the source/tests listed below and the ignored `task-37-report.md`.

## Review focus

- A modal during `start` appears before the model receives a session id: discovery by prior opener task id must work while the worker/session lock is occupied (Task 4 test).
- A second cancellation during dialog or Chrome close must retain uncertain ownership and fail readiness, never leave an untracked child (Tasks 2 and 5 tests).
- A model prompt suggestion may leak through dedup argument previews or exception logs despite sanitized queue payload (Task 4 test).
- Main and child frames may have identical URLs/messages: CDP frame id, not URL equality, decides admission (Task 1 test).
- Native response may be sent before cancellation/settlement failure: durable attempt makes the result unknown and blocks retry (Task 3 test).

---

### Task 1: Native observation and frame identity

**Files:** `agents/core/browser_playwright.py`, `agents/core/browser_session.py`, optional new `agents/core/browser_dialogs.py`; `tests/test_browser_dialogs.py`, `tests/test_browser_chromium_runtime.py`.

**Interface:** A driver-owned dialog observer captures one Playwright `Dialog` object and a matching internal CDP `Page.javascriptDialogOpening` event. An in-memory episode exposes a bounded, immutable pending snapshot; it never performs a response. Main-frame id/loader/document/page identity and one active operation bind the snapshot.

- [ ] Add synthetic RED tests for alert/confirm/prompt/beforeunload capture, same-URL main versus child frame, missing/duplicate CDP frame event, changed loader/document, wrong page, second/unarmed dialog and listener teardown.
- [ ] Run the exact new test nodes and retain their failure output in `task-37-report.md`.
- [ ] Implement the smallest observer and one-slot frame/episode state. Do not call `Page.handleJavaScriptDialog`, raw JS or arbitrary CDP.
- [ ] Run the focused nodes GREEN and verify an installed-Chrome capability probe with generated loopback pages.

### Task 2: Original-task opener and supervised child lifetime

**Files:** `agents/core/browser_runtime.py`, `agents/core/browser_kernel.py`, `agents/core/browser_session.py`; `tests/test_browser_dialogs.py`, `tests/test_browser_chromium_runtime.py`.

**Interface:** The original worker invokes the physical opening call under the existing exact task scope. A parent-owned empty-context child awaits the dialog and an approved response notification. The parent signals physical opening completion **inside the parent before TaskGroup exit**, then joins/cancels an idle child; it never waits for `Task.done()` from inside that child.

- [ ] Add RED exact-task seal, blocked-click/no-second-worker, modal 60-second versus no-modal 15-second, first/second cancel and retained cleanup tests.
- [ ] Run RED, implement supervised lifetime and deadline handoff, then run GREEN.
- [ ] Prove close, kill, registration/config change and expiry invalidate the episode before any long lock await.

### Task 3: Distinct response authority and one-use attempt

**Files:** `agents/core/autonomy/queue.py`, `agents/core/autonomy/worker.py`, `agents/core/autonomy_coordinator.py`, `agents/core/browser_kernel.py`, `agents/core/kernel/registry.py`, `agents/core/kernel/__init__.py`, `agents/core/capability_manifests.py`; focused queue/worker/Kernel/browser tests.

**Interface:** `toolrpc.browser_dialog` classifies as `browser.dialog` and is held by the generic worker loop. The retained child alone may present its current opener/response identities to a narrow worker CAS; queue verifies signed mediated approval and exact human decision, atomically claims the distinct row, and writes one durable response-attempt marker. Kernel exact full Action and approval check mint a child-task-only physical response scope.

- [ ] Add RED real-kernel/queue tests for explicit human accept, policy/auto/QUEUE/DENY, wrong owner/agent, changed fingerprint, direct generic dispatch, copied ContextVar, one-use replay, cancel/settlement failure and process restart.
- [ ] Run RED, implement sealed response Action, private CAS and guarded Playwright method, then run GREEN.
- [ ] Check one physical response or zero before denial, no duplicate dispatch/accounting, and unknown outcome after possible send.

### Task 4: Model-facing discovery/proposal, prompt sealing and owner card

**Files:** `agents/core/tool_rpc.py`, `agents/core/browser_runtime.py`, `agents/core/autonomy_coordinator.py`, `agents/core/job_toolsets.py`, `agents/core/agent_runtime.py` (narrow preview redaction), `agents/core/routers/browser.py`, Operator panel and its focused test; ToolRPC/route/worker/privacy tests.

**Interface:** `browser_dialog_pending(opener_task_id)` is a bounded read-only untrusted observation without `session.lock`. Gated `browser_dialog(opener_task_id,dialog_id,choice,prompt_text|prompt_ref)` proposes a separate tier-3 ask row; `gated_seal` converts raw text to a process-local one-use value before generic ToolRPC preflight/persistence. An authenticated owner sees exact choice/text on a private card, approves a finalized row, or enters private text through the owner route. Generic Task/Action/audit carries only reference, keyed digest and length.

- [ ] Add RED initial-start pending discovery, stale/wrong-agent lookup, model proposal versus human approval and owner/user-token route tests.
- [ ] Add RED marker-leak tests through ToolRPC refusal/enqueue/exception paths, task SQLite/receipt/Action/audit/log/generic output, event sink and dedup preview. State explicitly that upstream model tool-call transcript can retain a model suggestion; owner text must not enter it.
- [ ] Run RED, implement server-selected seal with wipe-on-all-failures and sanitized durable intake; run GREEN.
- [ ] Verify tool offer/job restriction and the owner card's exact escaped choice/text without granting execution.

### Task 5: End-to-end loopback Chrome and UI regression

**Files:** Focused `tests/test_browser_dialogs.py`, `tests/test_browser_chromium_runtime.py`, browser Kernel/ToolRPC/worker/route tests, Operator test. Product edits only in Task 1–4 owned paths.

- [ ] Run real local Chrome with temporary generated loopback pages for positive alert, confirm, prompt and beforeunload after exact approved main-frame operations; assert native DOM outcome once and exact owner text.
- [ ] Run same-URL child-frame, background/unarmed, missing `frameId`, loader change, denial, expiry and cancellation cases; assert no native response and actual owned Chrome/profile/journal cleanup.
- [ ] Run focused backend, route, ToolRPC, Kernel and Operator suites, Ruff, `git diff --check`, frontend `node_modules/.bin/tsc`; record exact commands/counts/limits in ignored `task-37-report.md`.
- [ ] Commit only owned source/tests with a clean worktree and hand off exact commit(s) for independent review. Keep advanced vision/JS/CDP passthrough/other engines/owner profiles/recording/spill requirements open.

**Rollback:** Remove the new default-off dialog registrations and close/reap any active fresh-profile dialog sessions. Keep prior `browser_run` behavior and all native uncertainty journals; never erase a possibly applied response attempt.
