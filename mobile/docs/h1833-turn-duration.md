# H18.33 native current-turn duration — local candidate

Generated 2026-10-09 UTC. Base `ecc50430a62fd91e87585a4dfda09cfca112ce1a`;
branch `codex/native-turn-duration-20261009`. Delivery remains local. PR #1247
contains the earlier mobile-session publication, not this change.

Native Chat shows one duration beside the composer after an explicit SSE end
contains the server-selected `outcome.latency_ms`. The interval is the public
orchestrator invocation through cleanup, as defined by H686; it is not network
round-trip or model-only time. A normal command or refusal can have a duration.
The value does not prove execution success. Backend `display.status_bar_fields`
selection remains authoritative, with no additional native settings request.

The API accepts only an own nonnegative safe-integer `latency_ms`, including
zero, and projects away extra properties. Missing, null, malformed, fractional,
negative and unsafe values yield no metric. Only a validated explicit end adds
an optional third `onDone` argument. The exact two-argument callback remains for
absence and EOF without an end; session IDs, text settlement, cancellation,
timeouts and credential handling retain their previous behavior.

`Conversation.turnOutcome` is ephemeral and separate from messages. Accepted
text or selected-image work, stop, error, history resume and disposal clear it.
First ordinary session adoption may show duration; actual `/new`, `/reset` and
`/undo` rollovers suppress it, while refusals in the same session may show it.
Changing agents clears the metric and revokes an already-running turn's metric
generation, including A-to-B-to-A, while preserving that reply's text and session
settlement. Changed asynchronous agent preferences apply the same fence.
Screen snapshots also match the connection epoch, so same-identity reconnection
hides old duration before the replacement controller's passive effect runs.

The themed strip's accessible name includes the number and `ms` unit. The
controller saves only `{sessionId, messages}`; existing storage projection and
remount checks prove no outcome or duration field enters history. Selected-image
turns clear prior metrics but do not acquire invented timing from their separate
POST path. No backend, storage schema, dependency or per-message field changes.

## Verification

- Tests-only RED on unchanged production: core 6 expected feature failures and
  22 controls passing; mounted native 5 feature failures and 2 controls passing.
  Root verified all six existing production hashes before implementation release.
- Final API/controller focused suite: **31/31**, 1.018 s. Covers strict values,
  inherited-property rejection, exact callback arity, trailing frames, EOF,
  first-session adoption, lifecycle clears, rollover/refusal and persistence.
- Final mounted native suite: **12/12**, 1.61 s. Uses real ChatScreen,
  ServerProvider, Conversation, API/XHR and storage with host-native adapters.
  It includes real transport error, idle and pending agent changes, delayed
  preference restoration, history selection, connection replacement, an epoch
  layout-effect observation, storage bytes and remount. The image-control stub
  invokes the real Conversation image lock; it is not a physical picker test.
- Independent review found the first static accessibility label omitted the
  number. A targeted regression failed on the actual label before the dynamic
  label fix; all 12 mounted cases then passed. Two test weaknesses were also
  corrected: an ignored synthetic SSE error became a real XHR failure, and an
  incidental numeric persistence assertion became field-specific.
- Complete mobile Jest: **316/316**, 53 modules, no skips/failures, 2.995 s.
  Native and app TypeScript checks pass; the E2E TypeScript check also passes.
  Complete frontend/native integration: **2039/2039**, 227 modules, no
  skips/failures; **1862 HUD +177 native** cases.
- Offline Android and iOS Metro/Hermes exports pass, with `CI=1`,
  `EXPO_OFFLINE=1`, `EXPO_NO_TELEMETRY=1` and two workers. Their output is at
  `/workspace/scratch/h1833-export-{android,ios}`. The existing React Native
  private feature-flags export warning remains; no dependency or bundler
  workaround was added. This proves compilation, not physical device behavior.
- Route/OpenAPI/HUD parity, client protocol and project/Hermes status regression
  modules: **109/109**, no skips/failures/errors. Generated status, both actual
  client-result count guards, Hermes projection and diff checks pass. Canonical
  counts are 21678 backend, 2039 frontend/native and 316 mobile tests; 555 routes
  and 18 agents are unchanged.
- Backend source is unchanged. Reuse the prior full backend result on
  `43fba70bc7d7592d2d4b6646107666b22c7068a0`: **21641 passed and 37 JUnit-skipped**
  out of 21678. Those entries are 36 guarded skips and one xfail, not all
  environment blockers. A separate clean-base opt-in Docker run executed nine
  of the previously guarded cases plus two controls: **11/11 passed**, 30.50 s,
  using the cached digest-pinned Python image, without a pull. No containers
  remained afterward. This does not rewrite the historical full-suite result.

Physical Android/iOS layout, screen-reader operation and live-Hub timing/setting
acceptance have not run. Host-native rendering and offline compilation do not
replace these checks. H18.33 remains a local candidate; broader H686 token speed,
context, cache, compression and typed accounting metrics remain open.

Artifacts: `/workspace/scratch/h1833-*` holds RED/green and complete client
results, source hashes, pin inventory and independent review. Supplemental
Docker evidence is `/workspace/scratch/post-h686-docker-opt-in.*`.
Implementation and cross-review used two gpt-6-sol/high agents; the narrow
read-only inventory used gpt-6-luna/medium. Root owned the contract, RED release,
integration, metadata and git. Maximum four active agents; no nested delegation.

The H526 native TTS path was reviewed unchanged and its one base-fresh client
pin refreshed; the preexisting stale H135 screen pin stays unchanged. Nine native
source/test/storage pins extend H686 evidence without changing any review status
or inventory identity. Rollback is this coherent native source/test/docs unit;
there is no stored-data migration, backend authority change or remote deployment.
