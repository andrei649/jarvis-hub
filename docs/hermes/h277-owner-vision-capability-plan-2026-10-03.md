# H277 owner-declared selected-model vision capability

Pinned Hermes: `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`.
Nerva base: `d2da13ea`. Hermes reads exact per-model `supports_vision`
declarations before probing model catalogs. Nerva's selected image route only
has a local runtime snapshot, so an owner cannot mark a known text-only cloud
model and have automatic image routing skip it.

Generation: 2026-10-03, local branch
`codex/h277-provider-discovery-20261002`; head at planning was `d2da13ea`.
Non-goals: general text/vision provider discovery, SDK credential recovery,
live paid-provider calls, mobile image ingestion, and any parity promotion.
Dependencies: the existing selected-turn adapter and review/physical-request
guard. Rollback: revert this capability-setting slice as one unit; the prior
local metadata and selected-main routing remain the baseline.

Add an admin-owned `llm.vision_model_capabilities` JSON setting. Each row binds
an exact supported image adapter, its full safe base URL, exact model ID and a real
boolean verdict. A missing row leaves current behavior unchanged. A negative
row skips only that selected main route, allowing the already reviewed vision
fallback; a positive row permits the matching main adapter. A declaration for
one endpoint/model must not affect another, especially `custom` endpoints.
Malformed writes are rejected. An unreadable or malformed persisted setting
refuses selected auto-image preparation, rather than silently treating an
explicit negative declaration as absent. The owner setting precedes local
metadata, matching Hermes's override order.

The composer reads this setting at review preparation and again at the final
physical-request guard. A changed declaration that changes destination
invalidates the review before image bytes leave. The setting has no effect on
ordinary text, explicit vision roles, or provider discovery. No provider call
is needed to test it.

Red-first tests: strict setting shape; exact provider, endpoint and model
matching; false main suppression, true override, unknown behavior, and
review-time configuration drift. Then implement the minimum resolver seam,
run focused H277/settings tests, full suites, Graft freshness and status gates.
Keep H277 partial: this does not complete provider discovery or live acceptance.

## Verified local checkpoint

Changed source: `agents/core/llm/vision_capability.py`,
`agents/core/routers/composer_vision.py`, `agents/core/settings_db.py`; matching
tests: `tests/test_h277_owner_vision_capability.py` and
`tests/test_h277_selected_composer.py`. The targeted owner/selected-composer
suite passed 41 cases, including persisted settings and a declaration change
after review consumption but before physical send. The broader H277/settings
union passed. Ruff and Graft wiring freshness passed. The full backend run
reached completion with one failure: generated Hermes status drift caused by
these source edits. The records were updated only for reviews that were valid
at the base, their cited lines remapped to unchanged source lines, and the
48-case Hermes status suite plus `hermes_status.py check` passed afterward.
The ledger remains 182/697 equivalent, H277 partial. No new frontend code or
live provider acceptance was tested. Next action: continue the outstanding
H277 discovery/adapters with a distinct scoped design and live acceptance
when an authorized provider is available.
