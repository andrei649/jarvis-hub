# Image intake composition repair

Freshness: 2026-09-09 13:46 UTC; base/current pre-commit head
`652f6cf3a2f645be202f0ab7840ed69f4a498155`; branch
`codex/hermes-image-composition`; lease none. Root owns concurrent image HUD work
in a separate branch; no HUD source/projection edits belong here. Next action:
root integration from the clean repair commit. No push, merge or
service startup. The repair commit is identified in the final handoff; this
capsule does not authorize remote mutation.

Goal: make one local image proposal work through the actual bound
MediationKernelBridge and existing signed queue, preserving exact human approval,
provenance, effect-time kernel checks and one-attempt replay protection. Current
ToolRPC authorizes `tool.rpc`/args_keys but queues a different kind/title/full args;
the bridge correctly rejects this mismatch, including with queue mediation off.

Design: preserve model tool name and logical ToolRPC contract; use a server-owned
gated intake callback for image alone, producing a single canonical `tool.rpc`
action/task tuple with full normalized payload, identical title and origin. It
calls the existing bound authorizer and governed enqueue; the bridge remains exact.
The canonical executor is image-only, never a generic dispatch alias. Under enforce,
the image guard revalidates the persisted B7 receipt/fingerprint in addition to every
existing approval/proposal/config check. Hold remains a refusal. No new kernel kind,
registry alias, signature format, worker permit or policy weakening is needed.

Paths: `agents/core/{tool_rpc,image_generation_runtime,autonomy_coordinator}.py`,
the matching line inventory in `agents/core/orchestrator_bindings.py`,
focused image/ToolRPC composition tests, scoped setup/Hermes/BACKLOG notes and this
plan. Trusted main classifier reports autonomous_merge=true for these paths and
no protected hits. Kernel registry/binding alternatives would be protected and are
not used. Generated global status and root HUD changes remain root-owned.

Non-goals: all-toolrpc migration, cloud media, new backend installation, live ComfyUI
generation, persistent kernels, UI changes, control-plane edits and existing queue
receipt migration. Previous image requests bind old runtime/ComfyUI adapter
hashes and need fresh approval when either module changes; this is not a whole
Git revision fingerprint. No stale proposal is silently upgraded.

Tests: real kernel + bind_mediation bridge + signer/head + governed queue + human
approval + guarded executor + mocked ComfyUI, off/enforce success and inbound taint;
hold, malformed canonical tool/payload, absent/tampered receipt, revoked decision,
effect-time denial/config/payload changes, concurrent attempt/restart refusal.
Ordinary ToolRPC behavior, B7 hostile evidence, kernel binding/action auth, relevant
route/lifespan guards, Ruff, baselined Bandit and diff checks. No real GPU/network.
Rollback: revert this one coherent repair; image integration returns to its existing
explicit refusal, and unrelated ToolRPC and durable acquired state stay untouched.
Dependencies: existing Action Kernel, signing/head store, queue and local-image
runtime; no external service or package installation.

Source accounting: this repairs Nerva's existing HA-4i image integration using
its own bridge, queue and ComfyUI adapter. No external source, dependency,
workflow or new Hermes capability is imported. HA-4i remains open for the
separate persistent-kernel/full-extension/client work recorded in BACKLOG.

Verification record: before source edits, both off/enforce production-bridge
proposal regressions failed with `enqueue_failed`, no task/backend request.
The final focused image/ToolRPC packet passes 186 tests, including 65 actual
bridge composition tests and six registration/contract tests. Existing image
timeout/cancel and ambiguous-result tests retain their assertions; only their
executor kind/handler registration changed. Actual authenticated HTTP proposal,
admin decision, worker and PNG retrieval are proved in off/enforce with only
ComfyUI HTTP simulated. Real GPU/model generation remains unproven.

The first adjacent pass had 345 successes and one line-inventory mismatch after
coordinator insertions; the nine offsets were synchronized. The complete adjacent
rerun passes 346 tests (one warning), covering B7 receipt/head integrity, kernel
authorization/bindings, action origin/auth matrix, component/lifespan guards and
tool profiles/pipelines. The binding-only rerun passes 50 tests. Ruff passes.
Independent read-only review found no actionable source findings and replayed
all 186 focused tests successfully, including the final hostile/restart cases.
On Windows, the literal repository-baselined Bandit command returns 103 existing
findings because baseline filenames use POSIX separators. The full scan passes
with an external temporary baseline copy preserving all 109 entries and changing
only filename separators; `.bandit-baseline.json` is unchanged. Diagnostics live
outside the repository in `AppData/Local/Temp/nerva-image-composition-20260909`.
