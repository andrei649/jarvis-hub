# H277 image-turn selection confirmations

Generated 2026-10-02. Goal: make governed OpenRouter image turns usable when the
selected model requires the existing training or cost confirmation. This is a
dependency of complete Hermes vision discovery, not a reduction of that goal.
Base/head before work: `68e68b311e2487821eab8d9d010bad8edee40c30`.
Branch: `codex/h277-provider-discovery-20261002`. Work stays local.

## Contract decided before implementation

Composer status optionally returns `selection_requirements`, an array of at most
eight objects containing `needs` and `message`. Known needs are
`acknowledge_training` and `confirm_expensive`; each occurs at most once. Messages
are nonempty bounded plain text (500 characters). No findings preserves the old
status shape. Unknown, malformed or unreadable requirements refuse safely.

The existing destination revision also binds the complete canonical guard
findings, including prices and threshold. Model, destination, routing, credential
or guard-detail drift invalidates previous disclosure. No raw credential enters
status or audit. POST adds two strict boolean fields defaulting to false:
`acknowledge_training` and `confirm_expensive`. Neither clears `remote_ack`.
Only current findings cleared by these flags can proceed. Record through the
existing selection-guard audit before creating a client: required training audit
failure refuses; cost auditing retains its existing best-effort semantics.

The composer physical scope receives immutable, explicitly cleared findings for
this call. Every request, retry and cleanup still evaluates current requirements;
new or changed findings cannot inherit the earlier confirmation. No approval is
stored as a reusable role/provider grant or passed to local/unattended consumers.
The final request hook must cover confirmed selections even without empty retry.

HUD displays each requirement and an unchecked per-draft checkbox, disables send
until all needed confirmations are checked, and submits only the literal flags
actually required and checked. Refresh, binding change and clearing/replacing the
image draft reset confirmations. Malformed/unknown status requirements cannot
silently enable send. Keep existing remote disclosure and retry notice.

CLI uses explicit `--acknowledge-training` and `--confirm-expensive` options for
the image turn, prints bounded requirements, and refuses missing flags before
POST. It never converts remote confirmation or a general yes option into either
flag. Old servers without requirements retain the old body unless a new flag was
explicitly provided. No live provider call or paid route is activated by this work.

## Ownership, verification and rollback

Backend writer: `agents/core/llm/vision_policy.py`,
`agents/core/routers/composer_vision.py`, and new backend consent tests.
Frontend writer: `frontend/src/composer-images.tsx` and its focused tests.
Coordinator: CLI and its tests, integration review, generated frontend artifacts,
documentation and evidence. Shared wire contract is fixed above before delegation.

Run red-first real-consumer tests, then targeted backend/UI/CLI suites. Include
missing/partial confirmations, literal boolean validation, audit failure, changed
price/threshold/config at preparation and final HTTP hook, retry/cleanup, no
grant leakage, UI reset and malformed disclosures. Run one full backend and
frontend verification at the coherent milestone, refresh only genuinely reviewed
evidence, and retain the broader H277 partial status. Revert this confirmation
increment and its records to roll back; no credential or settings migration.

Next action: delegate the two independent writers and implement the CLI against
the same status/POST contract. Keep provider discovery and Nous/DeepInfra in scope
for subsequent implementation; do not count this dependency as their completion.
