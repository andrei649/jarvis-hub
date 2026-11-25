# H517 provider registration: design checkpoint

Generated 2026-09-27; base/head bd2bb70ead1b493043a335e77713fc42c47d4013
plus local work. Goal: let an operator add a media backend without modifying
Nerva core, preserving the existing approval and artifact boundaries. Next action:
settle the initial local-image provider protocol and ownership before code changes.
This is a read-only design checkpoint, not an implemented feature or execution GO.

**Superseded for the first production slice:** the coordinator selected a
data-only protocol registry in [the implementation plan](h517-local-provider-plan.md).
Compatible local services need no host Python plugin loading or separate host-code
trust mechanism. The proposal below remains historical design input for future
arbitrary adapters; it is not the implemented registration contract.

## Verified current state

The frozen H517 row requests a shared provider abstraction/registry and has no
dependency on H516. Video generation can later consume the seam. The actual local
image runtime constructs a ComfyUI callback and supplies it directly to
`MediaGenManager`; a registry added only to library tests would not close this gap.
`PluginManager.build()` statically imports built-ins. Acquired `ExtensionRuntime`
code runs in a network-disabled container and must not be silently imported into
the host process to create an HTTP provider.

## Proposed initial production slice

Use separately named operator-installed Python image providers. Discover a finite
entry-point group through installed distribution metadata and read a packaged,
bounded manifest without loading executable entry points. The manifest declares
the provider ID, protocol version and supported model/options contract. Metadata
availability means configured/enabled with `reachable: null`; no network probing,
client construction or plugin import in status requests.

Enablement requires explicit local operator acknowledgment of host-code trust
against the installed distribution's version and actual code/manifest fingerprint.
This is separate from sandboxed acquired-extension consent. Changed code requires
renewed acknowledgment and restart. No package installation or live provider call
is authorized by implementing this feature.

Only acknowledged matching providers load during bootstrap, before image runtime
construction. Freeze the live registry afterward. Preserve pending approvals over
an unchanged restart through stable provider/configuration fingerprints; do not
bind existing ComfyUI tasks to a gratuitous random boot nonce. Hot replacement or
code/configuration drift must refuse stale authority.

The selected provider must be used through real `image_generate` intake, durable
approval and worker execution. Core retains the task/receipt/kernel checks,
single-attempt marker, strict loopback transport and artifact ingestion. Providers
describe requests; they do not supply trusted artifact paths or URLs. Core validates
bounded image bytes, format/dimensions and output ownership before cataloging.
Remote providers must not enter this initial local path or bypass the existing
signed cloud-image path.

## Decisions required before implementation

Specify the smallest useful core-owned transport protocol (request shape, response
parsing, reference-image handling, timeouts/size limits and physical-request hooks).
Identify bounded distribution-file fingerprinting and the concrete local operator
enable/revoke command. Confirm source ownership for registry/bootstrap/consent,
image runtime, status/schema, CLI and integration tests. Avoid a generic arbitrary
HTTP interpreter or a second ungoverned plugin execution path.

Acceptance must run installed-provider discovery, acknowledgment, real ToolRPC
intake, independent signed approval, execution and validated artifact publication
under offline fixtures. Cover changed code/configuration, disabled/unacknowledged
zero-I/O behavior, remote refusal, malformed output and unchanged restart.

This would be a partial local-image slice of H517. Video, TTS/STT and other media
subsystems remain in the accepted overall objective. The old rationale of an
excluded inventory row is never a new scope exclusion: all 107 historical skips
have been reopened explicitly.
