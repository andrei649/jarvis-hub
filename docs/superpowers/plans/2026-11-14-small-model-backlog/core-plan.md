# Core stabilization worker plan

Goal: provide bounded implementation instructions for cumulative source `587977b623cf2d1099733d57037e1c056babe1e5`. Production untouched.

Base/head inspected: `587977b623cf2d1099733d57037e1c056babe1e5`. Generated: 2026-11-14 UTC. Changed paths: packets/core.json and core-plan.md. Next action: review ready packets and resolve SM-002/SM-010/SM-011 designs before implementation.

Architecture: CLI help stays stdlib-only; archives use archive_safe; configuration uses central helpers. H040 restores metadata, collects owner skills and stages inbound candidates without installing or enabling them. H429 is mandatory: callback identity compatibility requires an explicit boundary decision. MoA timeout work is separate from confirmed callback CI regressions.

Global constraints: one writer per path; no merge, ready promotion, deploy or schedule resumption; do not weaken tests, scanner scopes, privacy, counts, approvals or registry invariants. Work in private temporary homes, with fake transports. No implementation suites or scanners were executed to write this plan. Run expensive suites serially.

Evidence: coordinator must copy REPORT.md, core-review.md, github-snapshot.json and sync-reproduction.json into this package’s evidence/ directory. References are relative to this package; historical snapshot is not current CI. lot5-bench object bd93bff5caf993bd150828a87d3cd1b4bfd88fa5 is unavailable locally and was not fetched or reviewed.

Scheduling: SM-008 precedes staged collection SM-009. SM-010 and SM-011 are design tasks only. SM-005 shares e2e_sync.py/rooms.py with other workers and must run serially; SM-002 and SM-012 also require serialized ownership if either edits Agent/MoA integration later. SM-006 runs after source edits settle; SM-001 runs after selected implementation tests settle. A dependency on a design packet does not make its implementation ready.

Full contracts, stop conditions and sources are in packets/core.json.

## SM-001 — Refresh measured backend count after all selected tests settle

State: ready; priority: P0; risk: medium. Depends on: SM-002, SM-003, SM-004, SM-005, SM-006, SM-008, SM-009, SM-010, SM-012.

Regenerate tracked backend count from the final selected Linux collection, preserving the independent JUnit mismatch gate. The historical 36700/36699 mismatch is a reproduction clue, never the new expected number.

Owned files: `project-status.json`, `STATUS.md`, `README.md`, `NERVA.md`, `GO_LIVE_PLAN.md`, `tests/test_status_sync.py`.

1. RED: retain/add one-off mismatch fixture in test_status_sync.py; show mismatch using temporary fixtures only.
2. GREEN: after dependent packet tests have landed, run python scripts/status_sync.py --help; use its live backend collection mode with --reuse-js-counts so JS totals are not invented. Commit only artifacts actually emitted; if output paths differ, report scope adjustment.
3. VERIFY: execute final backend suite once with --junitxml=pytest-junit.xml, then verify count from that same file. Do not count skipped jobs as passing tests.

Acceptance:
- `test_final_collection_drives_status` — Given final selected packet branch and clean isolated data home; when collect and regenerate status using the same Python and pytest configuration as CI; then tracked backend count equals measured collection; generated status artifacts agree.
- `test_count_gate_rejects_one_off` — Given synthetic JUnit count differs by one from tracked status; when run --verify-test-count backend; then nonzero exit and actual/expected mismatch; do not change assertion to tolerance.

Planned commands:
- `python -m pytest tests/test_status_sync.py -q` — status parser and negative mismatch regressions pass.
- `python scripts/status_sync.py --reuse-js-counts` — regenerates status using live backend collection, preserving tracked JS counts.
- `python scripts/status_sync.py --verify-test-count backend --test-result pytest-junit.xml` — success only for JUnit from completed suite at the final head.

Stop conditions:
- Stop if the supplied base or owned-file contract differs; report the difference before changing scope
- Do not assert full-suite success when JUnit was only collected or produced by a focused run. Regeneration may reveal more generated paths: get coordinator ownership before editing them.

Rollback: Revert this packet commit only; retain private runtime data and do not reset other workers’ changes.

## SM-002 — Resolve legacy callback semantics against mandatory H429 streaming scrubber

State: needs_design; priority: P0; risk: high. Depends on: none.

Resolve the confirmed callback CI regressions in Agent, where is-not-None wrapping turns a falsey callable truthy and changes backend callback identity. Mandatory H429 egress scrubbing must remain intact. This packet requires a deliberate compatibility architecture decision before implementation; MoA adapter behavior is not the confirmed CI defect.

Owned files: `agents/core/agent.py`, `tests/test_agent_runtime_v2.py`, `tests/test_lot4_hermes_equivalents.py`.

1. RED: reproduce the three named existing test_agent_runtime_v2 cases without changing their assertions; inspect exact call path and H429 regression coverage.
2. DESIGN: preserve falsey semantics by evaluating original callback truthiness before wrapping or stream selection. Separately decide how mandatory H429 scrubbing can coexist with unchanged callback identity: either move scrubber to a mandatory lower egress boundary covering every backend, or explicitly retire identity compatibility with documented migration and owner/coordinator review. No design choice is implied approved.
3. DESIGN: document every streaming path and flush/cancellation responsibility; demonstrate no output bypass if any legacy wrapper moves. Do not dispatch implementation while this boundary remains unresolved.
4. VERIFY AFTER DESIGN: red→green tests retain falsey and H429 guarantees; identity expectation changes only following the explicit architecture decision.

Acceptance:
- `test_agent_generate_response_disabled_preserves_stream_callback_identity` — Given disabled tool runtime and legacy streaming backend from existing test; when Agent.generate_response receives emitted.append; then current callback identity assertion exposes wrapping; design explicitly decides whether identity remains supported and locates mandatory scrubbing before approving implementation.
- `test_agent_disabled_mode_preserves_falsey_callback_legacy_behavior` — Given _FalseyAsyncSink and disabled runtime; when generate_response runs; then generate called once, generate_stream never called, falsey sink receives nothing; do not promote falsey callback through wrapping.
- `test_streamed_orchestrator_preserves_falsey_callback_for_blank_legacy_answer` — Given falsey callback and blank legacy answer; when orchestrator fallback runs; then callback remains undelivered per established semantics; response/fallback contract unchanged.
- `test_h429_scrubbing_survives_legacy_compatibility` — Given split memory fences and unterminated untrusted span in streamed output; when legacy and runtime paths emit; then no fence contents or unterminated span leak, for synchronous and async callbacks.

Planned commands:
- `python -m pytest tests/test_agent_runtime_v2.py -q` — planned: reproduce named regressions, then pass after approved boundary design; not run by this planning task.
- `python -m pytest tests/test_lot4_hermes_equivalents.py -q` — H429 split-fence and unterminated-span protections retained.

Stop conditions:
- No implementation until callback identity versus mandatory scrubber boundary is explicitly resolved
- Never bypass H429 to satisfy legacy identity test

Rollback: Revert this packet commit only; retain private runtime data and do not reset other workers’ changes.

## SM-003 — Keep CLI help usable without optional YAML dependency

State: ready; priority: P0; risk: medium. Depends on: none.

Move the eager agents.core.skins import in CLI skins into execution scope so argparse help never imports PyYAML. Keep real skin validation strict.

Owned files: `agents/cli/skins.py`, `tests/test_nerva_cli.py`.

1. RED: subprocess sys.executable -S scripts/nerva.py --help and skin --help.
2. GREEN: lazy import runtime skins symbols inside run (and any execution-only helpers); keep parser declarations stdlib-only. Verify actual run signature before moving symbols.
3. VERIFY: run CLI and skins suites with available dependencies; separately run -S subprocess tests.

Acceptance:
- `test_help_without_site_packages` — Given Python -S and temporary isolated home; when run scripts/nerva.py --help and skin --help; then exit zero with help, no yaml import error and no created settings.
- `test_skin_execution_missing_yaml` — Given yaml import unavailable; when execute a skin action requiring runtime backend; then existing CLI sanitized dependency error contract applies; no unsafe fallback YAML parser.
- `test_skin_help_preserves_verbs` — Given normal environment; when render help; then list/use/set/show/render and existing options remain.

Planned commands:
- `python -S scripts/nerva.py --help` — exit 0 without site-packages.
- `python -S scripts/nerva.py skin --help` — exit 0 without YAML.
- `python -m pytest tests/test_nerva_cli.py -q` — CLI regressions pass.

Stop conditions:
- Stop if the supplied base or owned-file contract differs; report the difference before changing scope

Rollback: Revert this packet commit only; retain private runtime data and do not reset other workers’ changes.

## SM-004 — Read pet ZIPs through archive_safe

State: ready; priority: P0; risk: medium. Depends on: none.

Replace the direct ZIP read path with bounded archive_safe extraction into a private temporary directory. Preserve pet format validation and current HTTP error meanings; do not add pets to archive-reader exemptions.

Owned files: `agents/core/pets.py`, `tests/test_h214_h238_h590_pets.py`, `tests/test_archive_safe.py`.

1. RED: use real import_zip entry with malicious member fixtures and assert no persistent save.
2. GREEN: use tempfile.TemporaryDirectory plus extract_zip_bytes with _MAX_ZIP_BYTES and _MAX_ZIP_ENTRIES, read only required regular JSON files after validation; map ArchiveRejected to existing PetError categories without leaking filesystem paths. Preserve ZIP writer for export only.
3. VERIFY: archive adoption gate and pet suite; use existing tests/test_h214_h238_h590_pets.py fixtures and assert no filesystem escape.

Acceptance:
- `test_pet_zip_roundtrip` — Given valid exported pet zip; when import through temporary extraction; then equivalent validated frames/name and one saved pet.
- `test_pet_zip_unsafe_members` — Given zip with traversal, absolute member, symlink, duplicate normalized name, or oversized inflated content; when import; then reject before persistent pet mutation; no outside files; temp directory cleaned.
- `test_pet_import_corrupt_zip` — Given truncated bytes or malformed JSON; when import; then PetError with 400, no partial pet.

Planned commands:
- `python -m pytest tests/test_archive_safe.py -q` — reader inventory rejects direct ZipFile reads and safety regressions pass.
- `python -m pytest tests/test_h214_h238_h590_pets.py -q` — pet archive roundtrip and rejection regressions pass; confirm suite filename first.

Stop conditions:
- Stop if the supplied base or owned-file contract differs; report the difference before changing scope
- ArchiveRejected mappings must preserve bounds and prevent saved pet records on failure.

Rollback: Revert this packet commit only; retain private runtime data and do not reset other workers’ changes.

## SM-005 — Register new hub environment aliases without raising the raw-read ratchet

State: ready; priority: P0; risk: medium. Depends on: none.

Register the five observed missing suffixes DEVICE_LABEL, E2E_SYNC_DIR, HOST_ID, ROOM_FENCING_SECRET and BROWSER_BROKER_ALLOW_LOOPBACK_HTTP; migrate new raw reads in owned sync/room modules through central helpers without raising MAX_RAW_ENV_READS. Resolve deliberate NERVA_HOME alias reads in existing CLI/tool-profile paths through a narrowly reviewed inventory classification, preserving canonical HOME behavior. Four production files are an intentional shared registry-contract exception to the preferred three-file limit.

Owned files: `agents/core/env_config.py`, `agents/core/e2e_sync.py`, `agents/core/rooms.py`, `agents/core/browser_broker.py`, `tests/test_rb2_env_alias_inventory.py`, `tests/test_o26_p2_env_config.py`.

1. RED: capture exact missing five suffixes and actual NERVA_HOME collision locations using existing inventory; add paired-spelling behavior tests for owned readers.
2. GREEN: add those exact suffixes to HUB_ENV_SUFFIXES. Migrate E2ESync and RoomStore new raw reads to env_str, retaining precedence and defaults; browser flag already uses env_flag and only needs registration. Do not touch MoA in this packet.
3. GREEN: classify the three intentional HOME alias reads with file-and-name-specific evidence in the native-name inventory, asserting both-spelling fallback semantics. Do not place NERVA_HOME in a global all-files exception. No changing paths.py data-home precedence.
4. VERIFY: full RB-2/O26 suites must pass from these owned changes; if other unrelated raw reads exceed cap, stop and assign separate repair instead of raising cap.

Acceptance:
- `test_five_missing_hub_aliases_registered` — Given each of the five suffixes configured through NERVA spelling then JARVIS spelling in isolated environment; when E2ESync, RoomStore and browser loopback helper execute after alias normalization; then same configured values and managed precedence; ROOM_FENCING_SECRET never printed or exported.
- `test_home_alias_callsite_classification_is_exact` — Given deliberate NERVA_HOME reads in agents/cli/import_cmd.py, agents/cli/skins.py and agents/core/tool_profiles.py; when native-name collision inventory runs; then reviewed alias reads classified by exact file/name callsites with matching canonical JARVIS_HOME fallback; a new independent NERVA_HOME reader outside those sites still fails.
- `test_inventory_and_ratchet_preserved` — Given full tracked-file scan and existing cap 110; when RB-2 and O26 tests run; then no unknown suffix, stale entry, unreviewed collision or cap increase; boolean raw-read guard unchanged.

Planned commands:
- `python -m pytest tests/test_rb2_env_alias_inventory.py tests/test_rb2_env_alias.py tests/test_o26_p2_env_config.py -q` — inventory and ratchet pass without inflated caps.

Stop conditions:
- If another module requires mutation, acquire coordinator ownership rather than exempting it
- Do not print ROOM_FENCING_SECRET in diagnostics

Rollback: Revert this packet commit only; retain private runtime data and do not reset other workers’ changes.

## SM-006 — Reconcile binding callsites and capability readiness from observed runtime

State: ready; priority: P0; risk: medium. Depends on: none.

Refresh exact binding locations only after inspecting actual AST writers, and regenerate readiness snapshot from real boot discovery without fabricating VERIFIED status or extending escape sets to hide broken boot.

Owned files: `agents/core/orchestrator_bindings.py`, `tests/_snapshots/capability_readiness.json`, `tests/test_capability_readiness_matrix.py`.

1. RED: run inventory and matrix to record specific drift.
2. GREEN: update only reviewed coordinates and actual deterministic state rows. Use documented matrix --update command; never edit state strings from desired claims. If a component fails boot, repair in separate packet instead of reclassifying it away.
3. VERIFY: rerun writer hostile fixtures and full readiness matrix. Schedule after source changes which shift inventoried writer lines.

Acceptance:
- `test_binding_inventory_exact_after_source_shift` — Given actual production bind calls moved by prior packets; when run exact inventory gate; then same authorized writer names with actual locations; duplicates/unlisted writers still rejected.
- `test_capability_snapshot_matches_boot` — Given isolated data home and real Orchestrator construction; when generate and compare readiness snapshot; then added/removed/state deltas explained individually; VERIFIED still requires harness_id.
- `test_forged_writer_still_refused` — Given unlisted or aliased hostile binding writer fixture; when run AST test; then fails closed as before.

Planned commands:
- `python -m pytest tests/test_orchestrator_bindings.py tests/test_capability_readiness_matrix.py -q` — exact inventory and honest state invariants pass.
- `python tests/test_capability_readiness_matrix.py --update` — writes real boot snapshot; review diff before accepting.

Stop conditions:
- Stop if the supplied base or owned-file contract differs; report the difference before changing scope

Rollback: Revert this packet commit only; retain private runtime data and do not reset other workers’ changes.

## SM-007 — Triage real security scan results and replace synthetic credential strings narrowly

State: ready; priority: P0; risk: high. Depends on: none.

Capture exact rule/file/function findings under actual workflow scopes; replace only benchmark pseudo credentials that trigger detectors with non-secret benchcred markers while preserving secret-stripping tests. Classify every new Bandit finding including low severity; do not baseline unknown findings.

Owned files: `scripts/bench_nerva_differentiators.py`, `docs/superpowers/plans/2026-11-14-small-model-backlog/security-triage.md`.

1. RED: collect redacted scanner reports to ignored/temp artifacts; never print credential material.
2. GREEN: replace only explicitly synthetic triggering benchmark values with descriptive benchcred values; leave secret settings keys and credential-shaped URL test meaningful. Write triage table with exact findings and source-level remediation proposals.
3. VERIFY: run benchmark focused tests, exact security commands, and report nonzero tools honestly. For real findings requiring production edits, create a separate bounded remediation packet after triage, not blanket nosec.

Acceptance:
- `test_synthetic_markers_still_exercise_stripping` — Given four seeded secret settings and credential-shaped URL fixture; when run benchmark sync scenario with benchcred marker values; then all seeded secret-key values removed from exported envelope and URL redaction still exercised.
- `test_scans_use_workflow_scope` — Given pinned tool versions from security.yml; when run Bandit agents+scripts and gitleaks entire tree; then record every new finding with rule, location, severity, disposition; no agents-only Bandit shortcut.
- `test_no_blanket_suppression` — Given a genuinely secret-shaped value outside fixtures; when run detector negative fixture via temp dir; then still detected; no scripts-wide allowlist or baseline regeneration.

Planned commands:
- `python -m bandit -r agents scripts -q -b .bandit-baseline.json` — every new issue captured; exit zero only after actual fixes.
- `gitleaks dir . --config .gitleaks.toml --redact --no-banner --verbose` — synthetic markers no longer trigger; real scan scope unchanged.
- `python -m pytest tests/test_bench_nerva_differentiators.py -q` — secret-stripping assertions retained; confirm test filename first.

Stop conditions:
- Stop if the supplied base or owned-file contract differs; report the difference before changing scope
- A genuine credential or unsafe production behavior is found: preserve redacted evidence and ask coordinator for a distinct remediation scope.
- Unavailable pinned scanner is unverified, not passing.

Rollback: Revert this packet commit only; retain private runtime data and do not reset other workers’ changes.

## SM-008 — Restore H040 metadata on default constructor restart

State: ready; priority: P0; risk: medium. Depends on: none.

Load metadata from the resolved default state path as well as explicit paths, before crypto setup. Preserve peers, disabled sync policies, labels and timestamps in ordinary production restart.

Owned files: `agents/core/e2e_sync.py`, `tests/test_h040_device_sync.py`.

1. RED: reproduce sync-reproduction.json scenario through default constructor in tmp_path; patch crypto only if isolating metadata.
2. GREEN: call _load_state() against _resolved_state_path() regardless of explicit argument; retain current missing/malformed file guards and explicit label precedence.
3. VERIFY: peer/policy roundtrip with real crypto when installed and metadata-only no-crypto test.

Acceptance:
- `test_default_restart_preserves_peer_and_optout` — Given patched data_path temporary home; default constructor saved peer plus disabled skill; when construct second E2ESync() without state_path; then peer and disabled policy restored; no plaintext secret added to state.
- `test_explicit_state_path_still_isolated` — Given separate explicit state file; when construct with path; then uses explicit file only.
- `test_missing_or_malformed_state_is_safe` — Given missing or invalid JSON and crypto unavailable; when construct default instance; then no constructor crash or secret exposure; reading does not overwrite malformed file.

Planned commands:
- `python -m pytest tests/test_h040_device_sync.py -q` — default and explicit-path persistence regressions pass.

Stop conditions:
- Stop if the supplied base or owned-file contract differs; report the difference before changing scope

Rollback: Revert this packet commit only; retain private runtime data and do not reset other workers’ changes.

## SM-009 — Collect real user skills and truthfully report pending staged downloads

State: ready; priority: P1; risk: high. Depends on: SM-008.

Collect outbound skills from the real owner user-skills root and keep inbound sync candidates staged with truthful pending-install status. No executable discovery root or installation API changes are part of this ready packet.

Owned files: `agents/core/e2e_sync.py`, `tests/test_h040_device_sync.py`, `frontend/src/panels/device-sync.tsx`, `frontend/src/panels/device-sync.test.tsx`.

1. RED: use real default directory resolution and SkillLoader.discover; test owner skill collection, staged download and opt-out.
2. GREEN: separate default outbound user_skills_dir from inbound staging; no bundled fallback. Add the exact pending-install response schema and preserve the specified legacy alias. Update DeviceSyncPanel receipt and focused frontend tests in the same packet.
3. VERIFY: staged candidates never enter executable discovery roots, load-set declarations or approval store. A same-slug owner skill retains bytes. Defer name-collision resolution, explicit installation consent and staging replay/conflict semantics to their separate design packets; do not claim these solved.

Interfaces:
- E2ESync.collect_sync_artefacts(), apply_synced_artefacts()
- paths.user_skills_dir()
- SkillLoader.discover() as read-only integration check
- apply_synced_artefacts returns existing fields unchanged and adds skills_pending_install: list[{slug: str, sha256: str, source_device_hint: str, state: literal pending_install}]. sha256 is computed from staged UTF-8 SKILL.md bytes. source_device_hint copies the record device_id only if it is a string; otherwise empty; it is untrusted display metadata, never authenticated identity or an approval.
- Retain skills_applied as a deprecated list[str] compatibility alias for successful staging writes, equal in order to pending entries slugs. Do not remove/rename it or treat it as installed. Skipped/quarantined entries appear in neither list. No local filesystem path or secret enters the response.
- A slug already present under owner user_skills_dir stays untouched. Its candidate may be written only under the distinct inbound staging root and is still pending_install. No collision-resolution or install API is introduced; owner-name/slug conflict resolution belongs to a separately reviewed installation design.
- DeviceSyncPanel pull receipt renders N skill candidates staged; installation pending, using skills_pending_install length with skills_applied length fallback for older servers. It never labels these candidates installed or enabled.
- The existing explicit skills_dir test override keeps its collection/staging behavior for isolated fixtures; production defaults collect only user_skills_dir when present and stage under data_path(synced_skills). No bundled-skill fallback.

Acceptance:
- `test_sync_collects_real_user_skill` — Given temporary user skills root has opted-in skill; bundled tree has another; when collect with default E2ESync; then collect owner skill only, honor sync opt-out; bundled skills not exported.
- `test_download_is_staged_not_enabled` — Given authenticated encrypted peer artefact with benign SKILL.md; when pull and run actual SkillLoader.discover; then candidate exists in staging, no command registered/executed and no approval/load-set grants created.
- `test_collision_never_overwrites_owner_skill` — Given same slug exists in owner user_skills_dir with different bytes; when sync candidate; then owner bytes unchanged; candidate written only in distinct staging root and returned as pending_install, with no grant or registration.
- `test_staged_response_compatibility` — Given one valid skill, one disabled and one quarantined candidate; when apply_synced_artefacts returns; then only valid entry appears in both ordered pending metadata and legacy slug alias; hash matches bytes; untrusted source hint is not used for authority.
- `device-sync staged receipt` — Given new response with pending metadata and older response with only skills_applied; when user pulls in DeviceSyncPanel; then both show staged candidate count and installation pending, never installation success.

Planned commands:
- `python -m pytest tests/test_h040_device_sync.py -q` — default-root collection and staging/consent regressions pass.
- `npm --prefix frontend run test -- --run src/panels/device-sync.test.tsx` — new and legacy server receipts state staging only.

Stop conditions:
- Any request to install, enable or expose a new importer API requires a separate design packet

Rollback: Revert this packet commit only; retain private runtime data and do not reset other workers’ changes.

## SM-010 — Persist replay detection for identical authenticated sync snapshots

State: needs_design; priority: P0; risk: high. Depends on: SM-008.

Design durable replay idempotency with atomic partial-application semantics before production edits. Current settings imports and skill writes do not share a transaction; choosing per-artefact receipts or rejecting mixed batches is an unresolved protocol decision.

Owned files: `docs/superpowers/plans/2026-11-14-small-model-backlog/h040-replay-design.md`.

1. RED DESIGN: specify identical snapshot/restart, forged outer digest, two identical settings records, mixed settings+skills partial failure, crash between local write and receipt, receipt persistence failure, and capacity exhaustion cases.
2. DESIGN QUESTION: can settings_db atomically compare/apply a setting and persist its replay receipt within the same SQLite transaction, and how are filesystem skill writes coordinated with it? Select one complete crash-recovery protocol, not a choice left to the small worker.
3. DESIGN: specify authenticated fingerprint canonicalization byte-for-byte, receipt schema/version, locking across processes, partial-success response semantics and bounded storage policy. Outer peer digest is never sufficient authentication or identity.
4. VERIFY DESIGN: only after a concrete atomicity/recovery protocol is reviewed should a new ready implementation packet be issued. No production replay implementation in this packet.

Acceptance:
- `test_repeated_snapshot_preserves_local_edit` — Given B applied A snapshot successfully, B then edits local setting; when B pulls identical encrypted snapshot again; then zero reapplication and B edit remains.
- `test_replay_survives_restart` — Given same applied snapshot fingerprint persisted; when recreate B and pull again; then snapshot skipped using durable state.
- `test_forged_outer_digest_cannot_hide_new_snapshot` — Given two distinct encrypted entry sequences share caller-supplied digest; when pull; then fingerprint is derived locally from authenticated content/envelope identity; untrusted digest alone never determines replay.
- `test_failed_apply_not_marked_complete` — Given snapshot contains import failure; when pull twice; then second attempt not falsely skipped as fully applied; no partial success falsely acknowledged.

Planned commands:
- `python -m pytest tests/test_h040_device_sync.py -q` — future implementation acceptance only; no production mutation authorized by this design packet.

Stop conditions:
- Do not implement before atomic write/receipt and mixed-batch crash recovery contracts are settled

Rollback: Revert this packet commit only; retain private runtime data and do not reset other workers’ changes.

## SM-011 — Design conservative H040 conflict protocol before integrating lot5 LWW

State: needs_design; priority: P0; risk: high. Depends on: SM-008, SM-010.

Produce the missing conflict contract and adversarial tests before accepting unintegrated LWW. The referenced object is unavailable in this checkout; no lot5 conflict fix is considered reviewed. A design must refuse divergent local/remote writes explicitly and preserve both versions.

Owned files: `docs/superpowers/plans/2026-11-14-small-model-backlog/h040-conflict-design.md`.

1. RED: specify tests for stale replay, concurrent edits, skewed clocks, equal timestamps, restart and settings/skill partial failure.
2. DESIGN: require persisted per-artefact last-common fingerprint, current-local compare and remote candidate fingerprint. Apply only when local == common or remote == local; otherwise return conflict. With no baseline, nonempty differing local state conflicts. Never wall-clock LWW.
3. DESIGN: decide settings atomic compare-and-apply transaction, conflict storage limits and redaction, explicit revision-bound resolution API and crash recovery. Do not choose undocumented settings transaction semantics.
4. VERIFY: review exact lot5 candidate if coordinator supplies it. Reject LWW that overwrites differing local state; split implementation into <=3-production-file packets after design approval by coordinator.

Acceptance:
- `test_unseen_remote_conflict_is_explicit` — Given local setting/skill differs and no trusted common baseline exists; when receive different peer value; then no overwrite, conflict record contains non-secret identifiers and hashes; encrypted/private candidate retained.
- `test_multi_peer_order_does_not_choose_winner` — Given A and C diverge from last common baseline; when B receives both in all arrival orders; then same explicit unresolved conflict; local value preserved.
- `test_resolution_is_revision_bound` — Given owner chooses candidate from preview; when local bytes/settings change before resolution commit; then resolution rejected stale, no write.
- `test_lot5_candidate_review_required` — Given exact public SHA absent locally; when prepare integration recommendation; then state unreviewed; request source through normal coordinator path, no fetch or cherry-pick in this task.

Planned commands:
- `git cat-file -t bd93bff5caf993bd150828a87d3cd1b4bfd88fa5` — already observed unavailable here; no network mutation authorized for packet.
- `python -m pytest tests/test_h040_device_sync.py -q` — future implementation must pass conflict cases; not executed for this design.

Stop conditions:
- Stop if the supplied base or owned-file contract differs; report the difference before changing scope

Rollback: Revert this packet commit only; retain private runtime data and do not reset other workers’ changes.

## SM-012 — Bound MoA load plus generation with honest all-proposer timeout semantics

State: ready; priority: P1; risk: medium. Depends on: none.

Make timeout_s cover residency plus generation for each proposer and aggregator. Keep current all-proposer gather semantics explicit; this packet does not promise early-quorum aggregation.

Owned files: `agents/core/llm/moa.py`, `tests/test_h032_moa_presets.py`.

1. RED: event-controlled residency fakes; use small timeouts and asyncio events, not long sleeps.
2. GREEN: put ensure_resident and generate inside one wait_for coroutine per proposer; same single-budget wrapper for aggregator generation and streaming. Start aggregate timing before residency, initialize final safely for timeout telemetry, preserve cancellation propagation.
3. VERIFY: both stream/non-stream with legacy callback compatibility. Update module timeout wording to say load+generation, all proposers awaited up to their deadlines; do not label as early quorum.

Acceptance:
- `test_proposer_residency_timeout` — Given one proposer ensure_resident blocks beyond timeout and enough others succeed; when run MoA; then blocked proposer cancelled/awaited, marked timeout, successful quorum synthesizes within member budgets.
- `test_aggregator_residency_timeout` — Given aggregator load never completes; when generate and generate_stream; then TimeoutError within member budget; telemetry marks unsuccessful and no member task remains.
- `test_all_members_governed_before_execution` — Given strict-local or unconsented member exists; when invoke run; then refuse before any load/generate; timeout refactor does not bypass authorization.
- `test_all_proposer_semantics_honest` — Given quorum reached while another proposer still pending within its budget; when run; then current gather may await remaining bounded proposer; docs and telemetry do not claim early-quorum latency.
- `test_cancel_cleans_member_tasks` — Given outer task cancelled during residency; when cancel run; then CancelledError propagates and children are awaited; no background inference survives.

Planned commands:
- `python -m pytest tests/test_h032_moa_presets.py -q` — residency timeout, cancellation, quorum and governance regressions pass.

Stop conditions:
- Stop if the supplied base or owned-file contract differs; report the difference before changing scope

Rollback: Revert this packet commit only; retain private runtime data and do not reset other workers’ changes.
