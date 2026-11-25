# H277 automatic image selection: local checkpoint

Generated 2026-10-02. The pinned Hermes source remains
`59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`. The local branch is
`codex/h277-provider-discovery-20261002`; runtime commit `876c3e2b`, Hermes
record commit `9228c5af`, generated-count commit `1c2900a9`. No push, merge,
deployment, credential copy or live/paid provider request was made.

## Delivered

`JARVIS_ROLE_VISION_PROVIDER=auto` is an opt-in route for the existing image
composer. With no explicit role base it selects OpenRouter, Nous, then DeepInfra
from available credential/model state. The resolver accepts an actual selected
main vision route as its first candidate, but the standalone composer currently
has no selected conversation route to pass; global chat settings are not used as
a substitute. OpenRouter uses the dedicated free vision model when none is
pinned; Nous needs an owned account; DeepInfra needs an explicit or positively
served catalog vision model. An explicit role base is authoritative and scoped.

Status may prepare metadata and displays the chosen provider, model and
destination. The selected source enters the destination binding. Image POST
does no discovery or OAuth refresh; candidate, credential or policy drift
requires a new review before model egress. Existing remote, training and cost
confirmations and final HTTP request guards remain in force. Auto does not
become an inherited signed-video or local-only remote route. Existing explicit
provider choices retain their behavior.

## Verification

The frozen full backend run on `9228c5af` collected **21,100** tests:
**21,065 passed, 34 skipped, 1 expected failure**. The tested HEAD and all
4,377 tracked regular files stayed unchanged. The 16 new auto resolver/consumer
tests and the focused vision/video union passed. Frontend had **1,861 passing**
tests, TypeScript typecheck and production build passed, and six desktop/mobile
Chromium composer cases passed. OpenAPI, route, documentation, Hermes report,
status-sync and Graft freshness checks passed. Strict staged-index scans had
zero findings. [Exact receipt](evidence/h277-vision-auto-verification-2026-10-02.json).

The status-sync default command completed its frontend count but could not run
the local mobile npm test (exit 127). The generated status uses the observed
1,861 frontend count and reuses the unchanged 142-case mobile baseline. The
manual checker flags two pre-existing groups in chapters 06 and 08. All
provider transport was synthetic or mocked; no live OAuth, inference or mobile
device acceptance is claimed.

## Parity and next work

The re-reviewed Hermes register is **175 equivalent, 255 partial, 64 missing,
203 needing review, 0 excluded / 697**, or **25.1% fully equivalent**.
Three restored equivalent rows were stale-evidence recertifications, not three
new features. H277 remains partial. Connect the actual per-turn selected main
route to image analysis before claiming Hermes's full automatic order; then
address SDK recovery, credential/anonymous lifecycle, signed-video breadth,
Nous account UI and the remaining accepted rows. Actual provider acceptance
and a new mutation campaign remain separate evidence work.

The previous [Nous vision checkpoint](h277-nous-vision-handoff-2026-10-02.md)
records the explicit-provider foundation. Rollback of this increment is the
runtime commit plus generated HUD assets, followed by the Hermes/status record
commits; preserve independent explicit-provider and account work.
