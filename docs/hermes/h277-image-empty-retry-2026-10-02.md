# H277 governed image empty-result recovery

Generated 2026-10-02. Base `9313fe0c9b2d918579b0dda64f11fad59bedc9c2`, branch
`codex/h277-image-empty-retry-20261002`. Reference Hermes
`59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`.
The [design](h277-image-empty-retry-design-2026-10-02.md) records the selected
contract, owner autonomy, verification and rollback.

## Delivered behavior

The default-zero `JARVIS_ROLE_VISION_EMPTY_RETRIES` setting permits one extra call
after a structurally valid empty image response. Recovery runs through five real
governed consumers: composer (including acknowledged remote use), local describe,
screen reflex, unattended Telegram images and camera descriptions. Prepared images,
prompt, model, token cap and temperature remain fixed. Both sends share one
180-second generation deadline and existing tighter caller limits; streamed replies
are capped at 512,000 bytes. Clients keep their existing owners and cleanup checks.

The enabled policy changes the frozen destination binding, invalidating old
composer confirmations and unattended role grants. HUD and terminal composer show
the extra budget before sending; malformed disclosure metadata sends nothing.
The local panels and role notes retain budget and privacy information. No native
mobile control or acceptance is claimed.

The active recovery scope pins the exact backend/model and rejects inherited late
use. Every physical send retains H513 selection, destination, authorization and
direct-transport checks. An exact prepared-body digest and per-attempt send latch
are revalidated by the last HTTPX request hook. This closes the reproduced case
where a later hook altered bytes after the earlier recorder had checked them.
Responses close before retry; revocation during response/client cleanup suppresses
retry or publication. Unguarded/direct, text-only and injected fake adapters gain
no retry. No source download, provider/credential switch or transport retry is added.

A shared pure predicate retains the existing video empty classification. Only raw
blank/null content in one explicit stopped successful choice can recover. Malformed,
blocked, truncated, error-bearing, meaningful reasoning-only and thought-stripped
blank output cannot. Two valid empty responses use the existing consumer failure
path. Other nonempty normalization and default-zero identity/output shapes remain.

## Verification boundary

Red-first actual producer and late-hook tests each reproduced the missing behavior.
The CLI had 13 expected new failures before disclosure/validation was added.
Backend integration passed 582 cases, including 40 new runtime and 14 new CLI
cases; a separate 117-case CLI/image-review selection passed. The full frontend
suite passed 1,847 cases, including nine added cases; focused component tests,
TypeScript and E2E TypeScript compilation, generated production build and Ruff pass.
Browser E2E execution was not run. Bounded independent source review found no
remaining blocker and ran no tests itself. Full frozen backend and mutation
results are separate evidence, not implied by this focused report.

Coordinator plus two Sol High writers handled backend and frontend ownership;
the coordinator added CLI coverage found during independent review. No live provider,
paid route, native device or coverage-percentage proof was run. H277 remains partial:
other adapters/native fast paths, broader output normalization, SDK/credential and
parameter recovery, discovery/cache, progress recovery, larger video uploads and
live acceptance remain in the full goal. This increment stays local.
