# H277 shared local auxiliary routing — implementation evidence

Base `614602123902391ccb5b30ba21c4ce900147b9c6`; pinned Hermes
`59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`. Local implementation only: no
publication, deployment, live/provider calls, credentials import or paid spend.
The [design](h277-local-auxiliary-design-2026-10-02.md) defines this increment.

## Delivered behavior

The actual orchestrator consumers for session titles, recall rewriting,
conversation review and context compression now call one shared local invocation
helper. Each can select its own model using the documented `JARVIS_AUX_*_MODEL`
setting while leaving the conversation's active model and other tasks unchanged.
Values are read at invocation time, validated without echoing them, and retained
as opaque printable Unicode model IDs. Unset/blank values keep prior defaults.

The helper uses only the existing local-backend accessor, rejects job-model pins,
and passes the same captured model to H513 authorization and generation. It holds
the existing physical-request scope for the entire await, including streamed
compression. No new provider, URL, credentials, fallback or retry selection exists.
Title/rewrite Qwen suffixes and budgets remain distinct from review and compression;
compression continues through the existing activity, inactivity, cancellation and
offline-digest behavior. No settings editor or model-list API was added.

## Focused verification

One Sol High implementer owned the helper, four producer methods and new tests.
Four real-producer regressions first failed because the configured per-task model
was ignored in favor of `active-local`; these were assertion failures, not module
collection failures. The required focused integration selection then passed
**513 tests**, including **54 new auxiliary cases**, with two reported warnings.
Scoped Ruff and source diff checks passed. A bounded independent source/spec
review verified the three source hashes and found no load-bearing blocker; it did
not rerun tests. The new concurrency case explicitly
holds both requests before releasing them; physical request tests use the real
HTTPX policy hook with offline MockTransport.

Coverage includes independent overrides/defaults, invocation-time updates, Unicode
IDs, invalid/oversized/control input, job pins, absence of a local backend, selected
model-specific Qwen behavior, concurrent model/guard isolation, policy change before
a physical send and denial of a compression child's send after scope cancellation.
Existing title, recall, review, H513, role and compression regressions remain in the
selection. The complete backend and final record checks are milestone evidence,
reported separately rather than inferred from this focused result.

Source fingerprints for the focused implementation:

- `agents/core/llm/auxiliary_text.py`: `2a041ff9cb1ffd8dfa6abfb1d9072c33df16347ef3a0f99c1131a82e97fc1e57`
- `agents/core/orchestrator.py`: `35278e6c4410450f47ffb9cebc0482ca8ed694ee2bd0ec57b3652102d3097c94`
- `tests/test_h277_local_auxiliary.py`: `759f02ed6fc1513552ad4a47e4be380b6400ef349c4555c98edcb60830226340`

## Remaining scope

H277 remains partial. Task-aware routing beyond these four consumers, including
acquisition and presence explanation, broader providers/adapters, automatic
discovery, SDK/credential recovery and other already-recorded video recovery/upload
gaps remain in the full goal. No installed-model availability, provider entitlement,
live output quality, native mobile acceptance or new mutation campaign is claimed.
Earlier mutation results retain their own recorded source snapshots.
