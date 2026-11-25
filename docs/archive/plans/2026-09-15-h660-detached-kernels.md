# H660 bounded implementation plan

Generated 2026-09-15; base/head f75d7c326dfd378a22edc53564cdbdb6f17cc1fa.
Goal: preserve session state over detached Docker CLI calls and retain complete cell
streams through existing bounded ToolResultStore spills. Existing per-cell invocation,
broker and stop/lifecycle authority remains mandatory.

Design: bounded stream frames replace worker StringIO; the host retains head/tail
previews while forwarding all chunks to optional sinks. A detached Docker worker
uses a fixed private /tmp mailbox inside its size-limited tmpfs, accessed only by
fixed docker exec Python helpers. One response packet at a time applies backpressure.
Random kernel/cell tokens reject stale responses; safe opens reject symlinks and
oversized files. Liveness is asynchronous; synchronous status reads cached state.
Only a proved pre-dispatch startup failure permits the existing isolated one-shot
path, with explicit fallback metadata. Cancellation kills the whole kernel.

Non-goals: generic SSH/Modal provisioning, host model-code execution, VM installation,
workflow changes, default-on sessions, new model-controlled paths or argv.
Paths: session_kernels.py, detached_kernel.py, code_tools.py, coordinator wiring;
scoped kernel/code tools/isolation tests and delivery/parity/Hermes ledgers.
Tests: red regressions for complete streams, cancel cleanup, mailbox protocol,
startup fallback versus ambiguous execution; existing authority/owner/RPC/lifecycle
suites; route/OpenAPI/lifespan guards. Docker integration cases run only in existing
opt-in CI lane; local fixed interpreters do not prove container isolation.
Rollback: revert this coherent feature unit. Dependencies: existing pinned Docker
image, FileRPCStore and ToolResultStore; no new packages.
Implementation notes: a regression reproduced the pre-existing session RPC response
symlink overwrite. SessionRPCStore now pins an opened directory and uses no-follow
request reads and exclusive random temporary response files, leaving the shared
one-shot FileRPCStore unchanged. Cell mailbox directories are unpredictable.
Framing nonces detect stale/cross-cell responses, not hostile Python introspection
inside the same interpreter; the host broker remains the authority boundary.
Next action: finish focused verification, generated counts and controller review.


Independent review follow-up (2026-09-15, base c2d1ed63): retain unconfirmed
startup/teardown handles as quarantined records until confirmed removal or daemon
absence, reject new cells and expose retryable reset in existing operator controls.
Recheck e-stop/expiry and current authorization inside fallback dispatch. Separate
broker service from the stop/deadline monitor, cancel it without blocking teardown,
and fence late responses. Cleanup targets the original record so a reset race cannot
destroy its replacement. Validate stream label types before lookup. New routes and
protected control-plane edits are out of scope. Regression-first verification includes
core/authority suites, full frontend tests/build, and metadata/route guards. Next
action: independent recheck of the completed follow-up commit.
