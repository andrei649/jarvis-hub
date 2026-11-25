# H517 next implementation boundary

Draft for the next implementation, not shipped functionality. Continue from the
voice authority prerequisite; do not build another library-only registry.

Target: register two independent named TTS providers and two independent named
STT providers through the existing admin command request, separately approve,
select them in actual speech dispatch and manage them in Settings -> Voice.
Preserve the legacy single command per side and legacy command:suffix behavior.

Candidate public contract: optional provider_id on the existing admin request;
omission selects the legacy slot. Exact lowercase bounded names; reserve native
provider IDs. GET adds named entries without changing the existing sides shape.
TTS uses a distinct provider:<id> selector; STT keeps auto/whisper/command policy
and has a separate selected command-provider ID. A missing explicit provider must
not silently execute the legacy command. Local-only TTS still refuses arbitrary
commands because their egress is unknown.

Storage/authority must be settled before edits: independent per-name durable
revisions, compare-and-swap application and tombstones for clear/recreate prevent
one approval overwriting another or accepting stale empty-state authority. Record
provider identity and expected revision in the exact approval payload. Revoking
one name must not revoke or overwrite another. The new runtime snapshot includes
that identity/revision in the initial and post-slot approval binding.

Common typed provider metadata/registry must be consumed by real image/speech
selection, with cheap no-network/no-spawn catalog reads. No config-driven Python
import or bypass of the acquired-extension sandbox. A common API does not grant
execution permission. Wider video/browser/web/terminal providers, arbitrary Python
adapters and install/setup hooks remain in the full H517 objective.

Acceptance: separate real approved records, selection through HTTP and engines,
concurrent writes, clear/recreate, same-name replacement while waiting, old single
provider compatibility, exact sentinels/fallbacks, generic-settings write refusal,
HUD controls and route/schema parity. Keep two Sol High writers with disjoint
storage/approval vs dispatch/tests ownership after interfaces are fixed; parent
owns registry interface/HUD/integration. No live or paid provider calls.
