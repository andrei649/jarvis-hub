# Hermes remaining delivery: kernels, agent extensions, desktop overlay

> Archived into the Hermes 697 sprint PR on 2026-09-09. Statements below about
> untracked files describe the original local handoff, not this committed copy.
> Current scope/status: [Hermes sprint](../HERMES_SPRINT.md).

## Latest checkpoint — 2026-09-09T14:10:07Z

This checkpoint supersedes delivery-state claims in the historical 13:17 audit
below; its remaining acceptance requirements are retained. Goal: finish Hermes
capability absorption and the bounded Darwin-inspired memory feature. Verified
main: `efc87a20634d33f2d7950b762d90854812c0a841`; this planning worktree's
HEAD remains `f65cf0ec5e7bb7084c0b7812440858387ea50168`. Changed path: this
untracked planning file only. Lease none; no production or host changes here.

PRs #1061 through #1068 are now merged, each after its reported automated checks
passed. In particular S1 #1065, canonical image approval composition #1067,
image HUD #1066 and the read-only Memory neighborhood #1068 are integrated.
Image `off`/`enforce` composition is covered through the real bridge/queue/worker
with simulated ComfyUI; `hold` intentionally refuses. The prior strict-mediation
implementation gap is closed. Browser evidence is synthetic, and owner ComfyUI,
Slack-account, real-memory and PWA proof are not claimed. Main is clean and its
status check agrees with inventories 9,695 backend / 1,127 frontend / 137 mobile
tests and 479 routes. Inventory counts do not claim full local suite execution.

Next implementation: scope K0 trusted invocation/data grants before any K1
model-facing code exposure. S2/S3 executable extensions/events, persistent K2/K3
sessions, native overlay and channel streaming remain open, as do their separate
real-host evidence and mobile/gallery gaps. Darwin DW-1 absorbs one memory
navigation idea directly in Nerva; it is neither an external Darwin connector
nor completion of every compared Darwin capability. The actual proposed paths
must be reclassified with fresh trusted main policy before subsequent work.

**Separate planning artifact, not part of PR #1063.** This file remains untracked;
do not stage it with P26 evidence. This refresh changes no production source,
tracked file, service, package, ledger or host configuration.

Freshness: refreshed 2026-09-09 13:17:07 UTC. Goal: preserve the remaining Hermes
capability-absorption requirements and distinguish implemented delivery units from
integration and real-host proof. Base SHA (current main inspected):
`8db71a9dbc257b0997c9b2d46d29ce2dc8f7593c`. This planning worktree's HEAD remains
`f65cf0ec5e7bb7084c0b7812440858387ea50168`, branch
`codex/hermes-p26-ollama-stream`; its older runtime is not current main.
Changed path: `docs/plans/2026-09-09-hermes-remaining-delivery.md` only. Lease: none.
Next action: root completes the pending S1 checks/integration and the dependent HUD
integration/status checks, then refreshes main and scopes K0 before any K1 exposure.
The original 12:10 UTC audit used main `d0a729f8`; its remaining requirements below
are retained, while the S1 status and K1-first recommendation are superseded here.

## Delivery status at refresh

- PRs #1061 (Ollama non-streaming), #1062 (Slack Socket Mode), #1063 (real Ollama
  raw-stream evidence) and #1064 (local image backend) are already on inspected main.
- **S1 is implemented in PR #1065**, head
  `0e25d83480cd194b5cfee8b5627d942ca0d05cc4`, but is not yet reported merged.
  At this refresh, root reports its security checks green while the main test and
  HUD build checks are pending. No pending/unreadable check may be called green.
- **The image HUD implementation is complete, with integration pending.** Its
  worktree HEAD at refresh is `537e7b39567d8ef36f40f45f6bfe266477fea57b`; root owns
  integration onto the S1/current-main result and generated-status reconciliation.
  Independent Chromium proof used the built UI with synthetic localhost APIs:
  exact proposal, separate approval, authenticated PNG preview/download and hard
  reload without a duplicate proposal. A subsequent minimal rebuilt-bundle check
  confirmed the link-contrast fix. This is not real ComfyUI/GPU proof or PWA cache proof.
- **HA-4i remains open.** Closing these delivery units does not close persistent
  code sessions, the executable SDK, observation delivery, the native overlay,
  channel streaming or named real-host evidence.

The recent task context, confirmed by root, compared Darwin's features before the
Hermes absorption request. It did not establish an authorized external Darwin
connector. Root has asked the user to choose the intended Darwin scope; do not
invent a process/API integration from that comparison. External Hermes execution
also remains a separate DRA-58/E8.1c requirement with its recorded withheld authority.

## What exists and what does not

| Area | Implementation at refresh | Missing implementation | Host proof limit |
|---|---|---|---|
| Code execution | `agents/core/tool_rpc_runtime.py:104` services bounded file-RPC; `agents/core/routers/skills.py:76` exposes a DEV_MODE/user-guarded Python pipeline; the SandboxPanel has the governed-tools checkbox. | K0 trusted invocation/data-scope contract is missing. No model-callable `execute_code` or resident interpreter/session-kernel manager. A surviving work directory is not surviving Python variables/imports. | Earlier probe found docker.exe but an unavailable Docker DesktopLinuxEngine pipe; wasmtime was absent from PATH. These are historical observations, not refreshed post-restart availability. No isolated live backend is proven usable. |
| Agent extensions | Existing built-ins and signed acquisition remain. S1 in PR #1065 adds strict declarative manifests, dependency/collision validation, offline doctor and a user-guarded inspection projection without candidate imports. Integration is pending. | S2 constrained registration/dispatch and S3 event delivery remain unwritten. `CommandRegistry.register` currently overwrites duplicate names, so it cannot be directly exposed to extensions. S1 registers no handlers. | Manifest/doctor tests require no new host dependency. External execution depends on the real pinned isolated runtime; inspection and a valid signature do not prove approval or runtime availability. |
| Local images | PR #1064 supplies the governed fixed ComfyUI workflow, durable one-attempt approval and guarded artifact lookup. The completed HUD adds exact-prompt proposal, existing Inbox approval, bounded owner task projection, preview/download and manual task resumption; integration is pending. | Dedicated persistent image history/gallery and native mobile presentation (H18.27) remain separate. Strict queue mediation still needs canonical-kind integration. | No real ComfyUI generation has been proven. Browser evidence uses synthetic APIs and PNG bytes; configured status means unprobed. |
| Native overlay | Five tracked files under `desktop/`: Tauri manifest/config, build script, short main, README. One main window is configured. | No second overlay window, compact native chat, geometry/monitor recovery, capability reporting or tray-menu handlers. `setup()` is empty. Referenced icon and frontend dist are not tracked. | Earlier probe found cargo/rustc absent from PATH; no post-restart toolchain inventory is claimed. The native source has not been compiled or exercised here. Missing tools do not explain away the missing overlay code. |

The existing isolated sandbox is fail-closed by default: `allow_subprocess=False`.
Its Docker path uses a disposable `docker run --rm` and kills the named container
on timeout/cancellation (`sandbox.py:312`). Do not enable its host fallback to make
a persistent-kernel demo pass. `acquisition/runtime.py` requires an image pinned
by digest before promotion is available; Docker availability alone is insufficient.

## Ledger decisions that must remain visible

Queried with `scripts/ledger.py show`, not a whole-ledger read:

- **“Let the model write a script that orchestrates many tool calls”**: update;
  correctly names both the missing model-facing door and persistent state.
  The related docs-features row is **keep** because it rates the existing governed
  pipeline design. That does not prove either missing feature.
- **“Write, install and validate a third-party extension”**: copy/XL; requires the
  signed, quarantined, approved acquisition substrate, not full-trust imports.
- **“Lifecycle hooks …”**: copy, narrowed so extensions can observe/propose but
  cannot bypass pairing or grant an action the kernel refused.
- There is a real inventory conflict: **“Run user-authored shell scripts on agent
  lifecycle events, with a consent record”** is skip, while **“Run custom logic at
  a lifecycle event, in Python or in any language”** says copy shell hooks first.
  Preserve the explicit skip and do not implement the conflicting raw-shell path
  as an incidental SDK feature. A future governed hook design needs its own
  reconciled product decision; this audit does not edit that decision.
- Native third-party UI injection, install-from-Git UI plugins, dashboard route
  overrides and hot-loaded terminal widgets remain **skip**. They are not “done”,
  and the agent SDK below does not reopen them.

## Delivery units and acceptance

Each unit gets its own branch/PR and revert decision. For unimplemented units,
proposed files and listed tests are acceptance targets, not claimed delivery or
test runs. S1 records its actual implemented scope separately below.

### K0 — bind trusted invocation and data scope before exposing code

**New prerequisite from the 12:48 UTC authority audit; not implemented.** The
current sandbox bridge calls `ToolRPCServer.handle` without the outer actor or
resolved offered-tool profile. Its intended `frigga`/`[echo]` invocation can queue
a synthetic gated tool as default actor `jarvis`; the gated handler executes zero
times. A separate synthetic session-search probe returns both temporary sessions
because DataSpaces has no authoritative session-to-source binding in that path.
This is a missing contract, not proof of bypassing an implemented session ACL.

Preserved local audit, replay and original evidence are in the sibling worktree:
[`2026-09-09-hermes-execute-code.md`](2026-09-09-hermes-execute-code.md),
[`probe.py`](2026-09-09-hermes-execute-code-probe.py),
[`evidence.json`](2026-09-09-hermes-execute-code-evidence.json).
Their inspected base is `a5b8b496f319447f0233b1baf4a0f54cb8551c06`; the saved probe
was captured at 12:38:11 UTC and reproduced at 12:46:49 UTC with matching source
hashes. Ninety existing offline tests passed; those tests do not prove the future
K0 contract. No sandbox or generated code was run for the probe.

Acceptance: server-resolved principal, agent, session, origin and canonical data
grants; immutable invocation/lifetime binding; inner calls intersect the outer
offered set with the current registry/profile/data grants. Reject missing, forged,
expired or revoked authority before reads and queue writes. Preserve monotonic
taint and shared budgets; recheck revocation between calls and before queued
effects. A copied ContextVar or actor string is insufficient. Isolation remains
fail-closed without host fallback and has its own live proof requirement.
Classify the concrete file set against trusted current main before implementation;
protected authority work, if needed, stays a separate control-plane dependency.
Rollback withdraws the new consumer without broadening read access. K1 must remain
unregistered until this contract and its required isolation proof are satisfied.

### K1 — let the model use the existing one-shot governed pipeline

Status: not implemented; depends on K0 above. The original recommendation to
start K1 immediately is withdrawn by the authority audit.

Paths: new `agents/core/code_tools.py`; registration in
`agents/core/autonomy_coordinator.py`; `tool_rpc_runtime.py`, `tool_profiles.py`,
and the relevant profile snapshot. Reuse the existing HTTP/console pipeline.
Offer `execute_code` only when a real isolated backend is usable. It must carry
the current principal, session/data-space boundary and intersected tool profile;
the inner RPC cannot expose tools hidden from the outer turn. Exclude recursive
`execute_code`, preserve per-call budgets, and fence output as untrusted data.

Acceptance: a real `AgentToolRuntime` selects code, calls a permitted read tool,
filters its result, and receives bounded stdout. Guest/internal restrictions hold
inside code; an unknown/hidden tool is refused; a gated call only enqueues and
does not execute; no backend means named unavailability and zero host process.
Extend `test_tool_rpc_runtime.py`, `test_sandbox_tool_rpc_pipeline.py`,
`test_tool_profiles.py`; new `test_code_tools.py` for model-to-RPC behavior.
No new kernel kind is assumed: the existing `tool.rpc` path must remain the
authority boundary. If it cannot cover the change, split that boundary work out.
Rollback: remove the offered tool; existing sandbox UI behavior stays available.

### K2 — a bounded isolated interpreter per authorized session

Paths: new `agents/core/session_kernels.py` and an isolated kernel worker/backend;
`sandbox.py`, `tool_rpc_runtime.py`, `code_tools.py`, session reset/close lifecycle.
First backend: Docker, with an explicitly pinned existing image; unsupported
WASM/host modes report unavailable. Key ownership to principal + data space +
session, never a model-supplied global id. Use one serialized cell at a time,
finite idle TTL, process/memory/output limits, bounded kernel count, and fresh
per-cell RPC authorization. A retained variable must not retain stale permission.

Acceptance: cell 1 sets/imports, cell 2 reads the same state; a different session
cannot; reset/expiry/crash creates named loss of state; concurrent cells serialize;
timeout/cancel/e-stop kills the real container and cannot silently continue a cell;
revocation between cells prevents the next tool effect. Existing sandbox isolation,
output-cap, child-env and cancellation tests plus new `test_session_kernels.py`.
Depends on K1 and a usable Docker daemon/image for real proof. Unit tests can be
built now; live kernel completion remains blocked by that host capability.
Rollback: disable persistent mode, destroy owned kernels, retain K1 one-shot mode.

### K3 — operator controls and host evidence for persistent sessions

Paths: additive status/reset on existing `routers/skills.py` sandbox surface,
`frontend/src/gap.tsx` SandboxPanel, and lifecycle wiring. Publish the selected
mode, availability reason, state age, reset result and actual kernel loss. Update
mobile parity/HUD route records in this implementation PR as appropriate.
Acceptance: reset requires the same owner/session authority; another session
cannot inspect/reset; disabled backend is shown honestly; UI timeout is distinct
from reset success. Route/auth/parity guards and frontend behavior tests, then
actual two-cell/restart/cancel proof on the isolated host. Depends on K2.
Rollback: remove these additive controls; K2 retains bounded automatic cleanup.

### S1 — declarative extension package and authoring/inspection contract

**Implemented in PR #1065; automated checks/merge pending at this refresh.** Actual
source paths are `agents/core/extensions/{manifest,doctor}.py`,
`agents/core/routers/plugins.py` and `agents/cli/nerva.py`, with tests/docs/schema
and status updates. The existing acquisition package/signing/quarantine/promotion
controls are consumed for inspection, not changed to admit new authority.

The implementation versions manifest/API independently, validates declarations,
rejects unknown capabilities, duplicate/core collisions, malformed/deep/duplicate
JSON and cycles, orders exact dependencies and reads distribution metadata without
candidate imports or installation. `nerva extensions doctor` is offline;
`extensions list` reads a user-guarded projection of already-composed acquisition.
Invalid inspection/integrity states produce a failing CLI exit code. Signature
verification is not approval: approval remains unverified, quarantine is not
inspected, SDK dispatch is unavailable and callable tools/commands remain empty.

Independent review closed the erroneous-success CLI finding with regressions and
verified 48 focused tests at its reviewed snapshot; root owns final-head CI.
No external handler has been registered or run. Remaining dedicated inspection UI,
S2 dispatch and S3 delivery cannot be inferred from the declarative names.
Rollback reverts this standalone inspection unit; existing acquired capabilities
retain their lifecycle. This is a substrate, not a completed executable SDK.

### S2 — constrained SDK registration and mediated extension execution

Paths: new `agents/core/extensions/context.py` and runtime proxy;
`plugin_manager.py`, `plugin_gate.py`, `commands.py`, `acquisition/promotion.py`,
`acquisition/acquired_runner.py`, and CLI/plugin inspection surfaces.
Expose declarative registration plus host-mediated dispatch, never `orch`, raw
drivers, ambient credentials or a Python module imported into the host. Tool and
command handlers run through the approved isolated acquired-package path; each
effect still crosses its existing action kind. Revocation unregisters handlers.

Acceptance: one signed approved example registers a tool and noncolliding command,
runs in isolation, and disappears on disable/revoke; a forged capability, stale
package hash, hidden tool or attempted raw network effect fails closed. Crashing
one extension cannot stop the manager; user code cannot replace core commands or
forge an admin principal. Extend acquisition/runtime and command/profile tests.
Depends on S1 and live pinned-sandbox proof for third-party execution. In-tree
fixtures alone are insufficient to close the SDK row. Rollback unregisters the
extension proxies; existing built-ins continue unchanged.

### S3 — observation-only lifecycle events through that SDK

Paths: new `agents/core/extensions/events.py`; bounded emission in `commands.py`,
`agent_runtime.py`, session lifecycle and the normalized channel event seam.
Start with command completed, session start/end, and tool completed; immutable,
allowlisted metadata, explicit correlation ids, bounded delivery/timeout. An
observer cannot rewrite inbound identity/content, admit an unpaired sender,
veto kernel decisions, or return extra prompt text. Third-party observers execute
through S2's sandbox proxy, not arbitrary host callbacks.

Acceptance: correct once-per-event delivery/correlation; unknown event refused;
slow/crashed observer cannot wedge chat; no secrets/message bodies in default
payload; mutation attempts cannot alter actual command or authorization; disable
stops subsequent delivery. New event tests plus commands, turn lease and tool-loop
regressions. Depends on S2 for external hooks. Rollback removes subscriptions and
emission only. Broader blocking/transform hooks remain a separate design, never
an implicit expansion of this observation contract.

### O1 — a buildable local desktop shell

Paths: `desktop/src-tauri/{Cargo.toml,tauri.conf.json,src/main.rs}`, icon/build
assets and `desktop/README.md`. Resolve missing referenced assets and the frontend
distribution path; wire real open/hide/quit tray items and restore window geometry
within available displays. Keep the local HUD's existing authenticated transport;
no new renderer privilege or token-bearing raw RPC bridge.
Acceptance: real Tauri build, launch with hub available/unavailable, tray reopen,
quit, restart geometry and offscreen recovery. No source-text test can substitute
for launch. Requires Rust/Tauri/OS prerequisites not verified usable here; can prepare code,
but cannot claim the native host deliverable verified. Signed distributable
installers are a separate release task, not a prerequisite for a developer test.
Rollback restores the old wrapper and removes added window state.

### O2 — floating compact chat with safe handoff

Paths: new desktop overlay module/window, new compact frontend component reusing
`frontend/src/cockpit.tsx` chat behavior and existing authenticated SSE transport.
Add frameless/always-on-top mode with close/return-to-main, draggable safe areas,
keyboard focus, and session-preserving handoff. A browser-only compact component
is useful progress but does not close native overlay delivery.
Acceptance: only one conversation submission, no lost/duplicated transcript on
handoff, streaming/abort works, hidden overlay is reachable, input does not leak
to the window underneath; actual Windows focus/topmost/close checks plus frontend
chat/abort tests. Depends on O1 and the existing hub, not a new WebSocket server.
Rollback disables overlay and restores main-window chat for the same session.

### O3 — compositor/monitor capability and recovery depth

Paths: desktop capability adapter and geometry model, overlay controls/tests.
One capability object reports support/absence for transparency, click-through,
cross-monitor movement, zoom and related effects. Implement reset-layout and
move-to-pointer with a reliable way out of click-through. Unsupported platforms
say unsupported; no inferred parity from platform names. Acceptance includes
mixed DPI, removed monitor, taskbar/topmost, shortcut/focus recovery and restart
on each claimed OS/compositor. Depends on O2 and those hosts for proof. Rollback
turns off enhanced behaviors, retaining O2. Reading the window below is excluded:
it is screen capture and needs its own existing `desktop.step` permission path.

## Remaining gates beyond the implemented image/inspection paths

- **Image host proof:** configuration/activation and one real approved ComfyUI
  generation are not supplied by the protocol fixtures or synthetic browser run.
  The queue's `hold`/`enforce` modes still refuse the unmapped canonical
  `toolrpc.image_generate` kind. Its protected registry integration is separate;
  do not lower mediation or mint a substitute receipt. Persistent gallery and
  native mobile H18.27 are open but are not dependencies of the implemented
  one-image proposal/approval/preview/download path.
- **Slack/Discord:** actual workspace connectivity and delivery remain unproven.
  Live token edits remain open because approval currently covers a complete known
  message, not unknown future output. Rendering a completed approved message as
  an animation would not close the live-stream requirement.
- **P26:** the real Ollama raw-stream limb is closed by PR #1063, with seven NDJSON
  records, no visible reasoning leak and no model left resident. Raw LM Studio
  SSE, long real reasoning latency, later memory recall and cloud-window proof
  remain open; the inline-`<think>` serving-layer limitation is unchanged.
- **Full depth:** K0/K1/K2/K3, S2/S3 and O1/O2/O3 remain real implementation/evidence
  requirements. No additional small runtime wrapper is required to complete the
  already implemented bounded image or S1 inspection paths; those larger units
  must not be silently counted as finished by the new UI or descriptor schema.
- **Separate external adapters:** DRA-58/E8.1c and the Hermes head-to-head retain
  their recorded authorization/preflight dependencies. The recent Darwin feature
  comparison is not authorization for an external Darwin connector or process.

## Authority boundary and recommended order

The original audit's trusted classifier reported no protected hits for the listed
sandbox/runtime, commands, acquisition/promotion, plugin_gate or desktop main
paths. Reclassify every concrete future change against fresh trusted main; that
historical path eligibility is not evidence that an implementation is secure. Any new
`agents/core/kernel/**` kind/binding, `agents/core/security/**` policy machinery,
`.github/workflows/**` native CI, or selfdev-policy edits are protected and must
be separate units with the applicable authority; do not bundle them into these
routine PRs or weaken classification to admit them.

Recommended order: finish S1's pending machine checks/merge and root's HUD
integration first; refresh the exact resulting main and delivery state. Then
design and verify **K0 before K1**. S2 can be scoped independently from K1 but
requires the implemented S1 substrate and an authorized isolated execution
contract; its live completion, like K2, requires pinned-backend host proof. S3
follows S2. O1 is a parallel lane once native build capability exists, followed by
O2/O3. K3 closes the persistent-session operator experience. For each code unit,
synchronize its specific HA-4i BACKLOG/evidence status and any changed route/HUD/
mobile parity in that PR, preserving named host gaps. This plan itself changes
none of those ledgers, and no pending integration is represented as merged.
