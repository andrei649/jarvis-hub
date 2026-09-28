# H517 speech authority prerequisite review

Generated 2026-09-27. Base/head bd2bb70ead1b493043a335e77713fc42c47d4013
plus preserved local work. Goal: repair the existing speech registration and
execution authority before adding multiple named providers. Implementation, integration and final whole-suite verification complete.
Final backend: 19,412 passed, 35 skipped, zero failures/errors (19,447 total;
250.534 seconds). The 771-test capability/registry group also passes. Frontend
source is unchanged; its prior 1,829-test result was not rerun. No commit, push, deployment or live/paid
provider request was made.

## Delivered behavior

`settings.voice_command` is now an exact kernel-mediated action with a matching
product capability manifest. Strict intake persists signed evidence and retains
the tier-three human approval floor even if the kernel returns GRANT. Only the
recorded, unedited request can install the approved command. Hold, missing
authority and invalid decisions refuse. The real guarded worker validates the
receipt/current policy/scope/global halt before installation. No settings wildcard
or retention registration was added.

The existing bounded TTS/STT runner now retains a detached snapshot of the
original approval and file identities. After waiting for a process slot, identical
argv alone is insufficient: a replacement approval or approved executable/script
replacement refuses the old invocation. A fresh invocation under the replacement
approval succeeds. Unchanged legacy records remain usable without migration.

The integration tests join actual strict signed registration, human acceptance,
worker execution and real synthetic speech programs. Ordinary voice registrations
have no approval group metadata. Settings, doctor and the existing HUD wiring were
also reviewed against current shared source; no frontend source changes were needed.

## Review and correction record

Two Sol High implementers owned disjoint files; the coordinator reviewed interfaces
and integration. Luna Medium performed bounded compatibility and final reviews.
Initial regressions reproduced the strict-registration refusal and six same-argv
approval replacement races. Focused implementation and joined execution tests passed.

The first full backend run found two failures because the new action lacked its
product capability manifest. The correction adds the real handler, required
recorded inputs, human approval and truthful future-only manual revocation, with
confidence zero. The second full run found three companion inventory failures:
executable-case counts and the readiness snapshot needed the new action. Those
records now include only the actual wired action; no fabricated VERIFIED state
or relaxed escape set was introduced. The complete capability/registry group and
subsequent full backend run pass. Full failed runs are retained as evidence.

Ruling: preserve the existing signed-decision execution contract instead of
adding another authorization path in the settings handler. Changing an injected
kernel callback alone does not revoke an existing signed approval. Revocation uses
the existing receipt/policy/scope/halt mechanisms, tested through the real worker.

Ruling: the old H613 limited-scope equivalence does not satisfy the owner's full
provider-matrix objective. Its current record is partial, with wider providers
and voice behavior explicitly open. H517 also remains partial. H334/H409 were
checked only for the exact registry addition, preserving their existing partial
gaps; H513 was checked for the voice-only FLAGS documentation addition. Other
stale evidence was not refreshed indiscriminately.

## Changed paths in this prerequisite

- agents/core/kernel/registry.py — exact action classification and broker inventory.
- agents/core/capability_manifests.py — matching product metadata and rollback limits.
- agents/core/voice/local_providers.py — detached original approval/file binding.
- agents/core/voice/command_settings.py — current strict-mode documentation/error detail.
- agents/core/autonomy/irreversible.py — distinguish speech from unregistered retention.
- tests/test_h517_voice_kernel.py — actual signed approval and execution boundaries.
- tests/test_h517_voice_revision.py — real bounded-run replacement/revocation races.
- tests/test_h517_voice_authority_integration.py — strict approval-to-speech integration.
- tests/test_action_auth_matrix.py and tests/_snapshots/action_auth.json — action coverage.
- tests/test_h27_capability_verification.py and tests/_snapshots/capability_readiness.json — intentional capability inventory addition.
- docs/ARCHITECTURE.md, docs/FLAGS.md, docs/design/HUD_V2_REMAINING.md and mobile/PARITY.md — behavior and native configuration gap.
- docs/hermes/build-queue.md and docs/hermes/assessment.json — truthful partial scope and reviewed evidence.
- docs/hermes/h517-voice-authority-plan.md, this review, docs/hermes/h517-named-provider-next.md and docs/hermes/evidence/h517-voice-authority-2026-09-27.json — plan, limitations, next contract and verification records.
- HERMES_STATUS.md, NERVA.md, README.md, STATUS.md, project-status.json and BACKLOG.md — generated/current delivery and test-count synchronization.

## Remaining work and rollback

Multiple named speech providers and the common media/provider registry remain next;
the draft contract is in h517-named-provider-next.md. Wider TTS/STT/video/browser/web/
terminal adapters, setup hooks and native/live acceptance are still open. Commands
are owner-trusted programs; libraries they load are not pinned or sandboxed. Clearing
prevents future calls but does not stop an already running process or undo its effects.
An otherwise identical legacy record without approval metadata cannot distinguish
an intervening identical restoration.

Rollback only these localized hunks. Operationally, disable JARVIS_VOICE_COMMANDS
or clear a configured command; retain approval/audit data and existing user work.
