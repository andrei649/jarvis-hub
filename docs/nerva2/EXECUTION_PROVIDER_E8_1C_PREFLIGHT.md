# Nerva E8.1c — Hermes invocation and supply-chain preflight

> Generated from `EXECUTION_PROVIDER_E8_1C_PREFLIGHT.json`; do not edit by hand.

Status: `preflight_evidence_only` · adapter `blocked` · E8.1 `building` · release ready `no`.

This is static, public-source preflight evidence only. No Hermes package or OCI image/layer was downloaded, installed, imported or executed; only public source and metadata payloads were inspected. It proves no compatibility, safety, benchmark benefit or authority.

## Immutable upstream snapshot

| Field | Value |
|---|---|
| Observed | 2026-08-06T17:17:01Z |
| Repository | NousResearch/hermes-agent |
| Release | v2026.8.3 |
| Tag object | 7de39e700d2c329e15d32eb0b96e2f7cdd9fbdb2 (valid_ssh_metadata) |
| Commit | 3c27eb6234bf91b8ceee9e9071591b31e9b148cb (unsigned) |
| Tree | b217767ccb994605dad522e693fa1b4cdbc2f352 |
| Default-branch drift at 2026-08-06T23:40:22Z | main is 300 ahead / 0 behind the pin |

### Bound source files

| Path | Git blob | SHA-256 | Bytes |
|---|---|---|---:|
| .github/workflows/docker.yml | 7e47b1db693b68d8b4c68f1d5611c3055c365543 | c32901e3327877c14eb57cd9a5d7c4c56a95a5587c09de6aa42d6008d93d2ecc | 11839 |
| Dockerfile | 2de6192715ed9a839c257b1f34f98d0832797159 | a11fc9fc39eadcaffd99377d831b5ec2458f1e09a5f5d5312fd8adcec362b7fc | 25687 |
| LICENSE | 75410e73319c72cd3e991a501c5455eb78f38375 | 821556e6336796450ab852d375117b48a4887e71d255794fd6318d99982a5ab6 | 1070 |
| docker/entrypoint-dispatch.sh | 927ed032f6d821e5bc9d047aed10e37f125d5a6a | d6f8e569fd2bfbf8d1f45619243681b9a1390c5bd3c9c584532692893b1d4fcd | 1123 |
| docker/hermes-exec-shim.sh | 7f4c5c3c0a0e9216b262e6ecf7b96cf868f0a4ce | 57637e73c8db76aa84a38e4a2edb1b155bfd86a2e89a8d4c38c4546ee1175985 | 3711 |
| docker/stage2-hook.sh | 899c8e86ac989735a27d67cb3b11df88762bbb9b | 942cc3c8c9df4168c58c30dc961b43e322c6d3cfb007e1a56f2c9ede48c710a7 | 28558 |
| hermes_bootstrap.py | c0622bb0d96162b825be102896e4c01af6eb5062 | 225112594c045e57b9413c3054948da865febeba589c0c4d1b5c9c1bda0b5d28 | 10514 |
| hermes_cli/_early_recovery.py | 7a19167eca04bcd3755fac521fead07529f5e4ef | 3215692e4d5e1ab9bf255fd25c5c35f82afe6525bb430c50f9de10e4ad1a7ff4 | 10716 |
| hermes_cli/_parser.py | b5098f6c98d6891d090db73a66d03d3ac6c51ff7 | 30621be86ee4d30322e106b318b211c7a7ffe1f271688436849a4b80bb3f4d2c | 17625 |
| hermes_cli/main.py | cd9966cf8cff6b3a93d5a24d61b2a84a9b7d49d8 | f27fcee078bc3696d4c37fa98d04972e214d53b01bd6075f12e988ef69d6c241 | 504355 |
| hermes_cli/oneshot.py | f13fe64029d5cde2acab4584968275a62fa1319a | dab3aea137b5c8f19c0835c7393a729ff982f16c18ded3e155aa549fc087e8c2 | 21819 |
| pyproject.toml | b9578f3fc53e701c2c9966d7aa5b7eeae574a2db | 64d1085ee1c23caf0ae0d9e65c73e280f466362ed43fdda1531f18f3af1d9869 | 23044 |
| run_agent.py | e2bc5f8660bd6bfd101175cf55131a7c9e253a31 | 7d22f38b5eac3b2951fa28aec5b2b06ec007bc96d88e5d35278481bf2ab52122 | 364804 |
| setup.py | fac7fe88161e7aae1033f163fb9bf0705b825b73 | b81382e9c4d1bc10694c42177edec65fdab9afe6511dd4c43b2279440b6ad13e | 2920 |
| skills/productivity/docx/LICENSE.txt | c55ab42224874608473643de0a85736b7fec0730 | 79f6d8f5b427252fa3b1c11ecdbdb6bf610b944f7530b4de78f770f38741cfaa | 1467 |
| skills/productivity/pdf/LICENSE.txt | c55ab42224874608473643de0a85736b7fec0730 | 79f6d8f5b427252fa3b1c11ecdbdb6bf610b944f7530b4de78f770f38741cfaa | 1467 |
| skills/productivity/powerpoint/LICENSE.txt | c55ab42224874608473643de0a85736b7fec0730 | 79f6d8f5b427252fa3b1c11ecdbdb6bf610b944f7530b4de78f770f38741cfaa | 1467 |
| skills/productivity/xlsx/LICENSE.txt | c55ab42224874608473643de0a85736b7fec0730 | 79f6d8f5b427252fa3b1c11ecdbdb6bf610b944f7530b4de78f770f38741cfaa | 1467 |
| toolsets.py | f4bb3c3343a99e3100abfa5e9d8ed10c33fe2efc | 35658a881a40913ea3bd54b9bb0b5a355ae0cf18abb2e249b48833218be572b3 | 36388 |
| uv.lock | 592d5db2612fc0e306a42e8eccabf9b7856cd3c4 | aab3c83f71b683507a590b6315b23bdc0abd6b63b76b2349eae15bf00dfbaf2b | 715301 |

## Distribution and invocation decision

Pinned source reports `hermes-agent` `0.20.0` with Python `>=3.11,<3.14`. The selected future distribution route is `dockerhub_oci_index_candidate_not_pulled` at OCI index `sha256:16788311e2fa3035456bdc1bafb8ec2b1777db64ebf020af9bb7eb73c3712c9e`.

PyPI still reports `0.19.0` and therefore does not distribute the selected `0.20.0` source commit. Its 45448-byte response is content-bound in the canonical artifact; no package artifact was downloaded.

OCI provenance metadata was observed for 2 platform manifests, but authenticity is not independently verified, no signature is present, BuildKit material completeness is false and the registry returned 0 referrers.

| Surface | Mapping / selector | Decision | Result contract |
|---|---|---|---|
| hermes-agent | run_agent:main; none | rejected | human_text_no_typed_envelope |
| hermes-oneshot | hermes_cli.main:main -> hermes_cli.oneshot:run_oneshot; -z/--oneshot | candidate_not_executed | final_text_plus_optional_usage_json |

`hermes-agent = run_agent:main` is rejected as a programmatic seam. `hermes -z/--oneshot` is only a candidate for a later isolated fixture. The chat-only `--safe-mode` flag cannot be passed to one-shot; a later fixture must set `HERMES_SAFE_MODE=1` before process start, and that environment setting is still insufficient isolation. Nothing was accepted or executed.

## Statically observed side effects

| ID | Phase | Evidence | Risk |
|---|---|---|---|
| container_default_root_entrypoint | startup_static | Dockerfile L298-L312, L378-L393, L395-L422, L424-L456: The published image selects USER root, HERMES_HOME=/opt/data, a persistent /opt/data volume and /opt/hermes/docker/entrypoint-dispatch.sh as its default entrypoint. | The default root and persistent-data startup path is not an acceptable narrow fixture and must be bypassed explicitly rather than treated as container isolation. |
| container_dispatches_via_s6_stage2 | startup_static | docker/entrypoint-dispatch.sh L18-L25: The default dispatcher executes /init as PID 1 and otherwise runs the stage2 hook before the main wrapper. | Default invocation traverses supervised initialization and state preparation before Hermes, expanding the side-effect surface. |
| container_narrow_shim_candidate | startup_static | docker/hermes-exec-shim.sh L43-L87: The /opt/hermes/bin/hermes shim executes the real venv CLI directly for non-root callers and otherwise attempts a privilege drop or refuses unsafe root execution. | A later fixture may override the image entrypoint to this shim as user 10000:10000, but that path remains unexecuted and does not prove zero tools, network denial or state isolation. |
| container_stage2_mutation | startup_static | docker/stage2-hook.sh L2-L4, L76-L86, L228-L252, L381-L466: The root stage2 hook creates and chowns HERMES_HOME trees, seeds configuration and credential files, migrates state and synchronizes startup content. | Running stage2 can mutate persistent data before the candidate task begins; the narrow fixture must bypass it and use new disposable storage. |
| import_bootstrap_mutation | import_static | hermes_bootstrap.py L229-L239: Applies environment, stdio, platform and sys.path bootstrap changes during import. | An in-process import can mutate the trusted host before a provider policy is bound. |
| import_dotenv_loading | import_static | hermes_cli/main.py L690-L697: Loads the project .env before argparse processes safe-mode flags. | Host configuration or credentials could enter the child before CLI controls apply. |
| import_early_recovery | import_static | hermes_cli/_early_recovery.py L190-L268: Recovery markers can trigger ensurepip and force-reinstall operations. | Import-time recovery can mutate a Python environment; the future route must isolate and make the image immutable. |
| oneshot_auto_approvals | runtime_static | hermes_cli/oneshot.py L219-L231, L437-L448: Sets HERMES_YOLO_MODE and HERMES_ACCEPT_HOOKS and documents dangerous-command and hook approval bypass. | Hermes approval semantics cannot be trusted as a Nerva authority boundary. |
| oneshot_cwd_context | runtime_static | hermes_cli/oneshot.py L1-L20: Uses normal rules, memory, AGENTS.md, preloaded skills and the caller working directory. | Safe-mode does not prove context or memory suppression; empty disposable CWD and HERMES_HOME are mandatory. |
| oneshot_hard_exit | shutdown_static | hermes_cli/main.py L105-L221: Runs best-effort global cleanup and terminates with os._exit, skipping normal finalizers. | The parent must own timeout, cancellation, process-tree cleanup and partial-effect evidence. |
| oneshot_model_network | runtime_static | hermes_cli/oneshot.py L324-L389, L424-L458: Resolves configured provider credentials and invokes a model-backed AIAgent conversation. | Network, credential and retention boundaries require an external allowlist and synthetic endpoint. |
| oneshot_plugin_mcp_hook_discovery | startup_static | hermes_cli/main.py L10733-L10815, L12470-L12491: Agent startup can prepare plugins, MCP and hooks before dispatching one-shot mode. | HERMES_SAFE_MODE must be set before process start and still is not a complete isolation proof. |
| oneshot_session_database | runtime_static | hermes_cli/oneshot.py L297-L319, L412-L483: Creates and closes a SessionDB and constructs an agent with memory lifecycle hooks. | State writes and retention must be confined to a disposable mount and externally verified. |
| oneshot_toolset_inheritance | runtime_static | hermes_cli/oneshot.py L391-L410: Omitted toolsets inherit configured CLI tools and the path starts MCP discovery. | There is no proven zero-tool invocation; tool access must remain an explicit blocker. |
| oneshot_usage_file | runtime_static | hermes_cli/oneshot.py L127-L167: An optional usage path creates parent directories and writes best-effort JSON. | The result is not a typed Nerva evidence envelope and the path must stay inside disposable storage. |
| run_agent_import_graph | import_static | run_agent.py L23-L223: Imports agent, terminal, browser, memory, provider, tool and trajectory internals before main runs. | The deep unstable import graph is not a narrow programmatic contract. |
| safe_toolset_not_offline | startup_static | toolsets.py L364-L368: The built-in safe toolset includes web, vision and image generation. | The name safe cannot be treated as no-tools or no-network evidence. |

## Supply-chain state

| Evidence | State | Result |
|---|---|---|
| Direct requirements | verified_static | 32 requirements; not all exact-pinned |
| Optional groups | verified_static | 45 groups; none selected here |
| Upstream lock | verified_static | 250 records / 249 names; zero license fields |
| Upstream license | verified_static | MIT |
| Bundled license findings | verified_static; complete=no; accepted=no | The repository root is MIT, but four bundled productivity skill subtrees carry separate restrictive Anthropic terms; redistribution and use compatibility remain unresolved pending owner or legal acceptance. |
| Transitive license closure | not_verified | The lock has no license fields, four bundled productivity skill subtrees carry separate restrictive Anthropic terms and a complete installed-image license inventory is absent. |
| Vulnerability review | recorded_metadata; complete=no; 6 CVE groups | Advisory alias, affected-range and fixed-version metadata conflict for part of the cryptography findings, so ambiguous records remain fail-closed as affected or unknown; OSV exact-version queries covered PyPI-backed lock records, but not OS packages, npm packages, container base layers or configuration-dependent lazy installs; The scan is a point-in-time metadata query and is not a signed or complete vulnerability attestation for the OCI image |
| SBOM | not_verified; complete=no | No SBOM descriptor, document or field was observed in the inspected provenance or registry referrers, and no complete source, Python, OS, npm or image-layer SBOM was verified. |

Restrictive bundled-license paths: `skills/productivity/docx/LICENSE.txt`, `skills/productivity/pdf/LICENSE.txt`, `skills/productivity/powerpoint/LICENSE.txt`, `skills/productivity/xlsx/LICENSE.txt`.

OSV-identified lock versions (six CVE groups after alias de-duplication): `aiohttp 3.14.1`: `CVE-2026-59881`, `CVE-2026-69243`, `CVE-2026-69244`; `cryptography 48.0.1`: `CVE-2026-69247`, `CVE-2026-69248`, `CVE-2026-69249`. Advisory-range conflicts remain fail-closed; this is not an exploitability determination.

## Later compatibility and isolation fixture

Fixture state: `not_executed`. Isolation state: `blocked` on B7/#818.

- bounded CPU memory time and output
- deny-by-default filesystem mounts
- deny-by-default network egress
- empty isolated working directory
- explicit /opt/hermes/bin/hermes entrypoint override that bypasses /init dispatcher and stage2
- explicit provider model and reviewed toolset
- external verification and native rollback
- immutable OCI index and platform-manifest digests
- new writable tmpfs /opt/data owned uid=10000,gid=10000,mode=0700 as empty disposable HERMES_HOME
- non-root 10000:10000 process identity
- parent-owned cancellation and process-tree kill
- read-only image root filesystem
- scrubbed environment with HERMES_SAFE_MODE=1 set before import
- trusted Nerva-side kernel context resolved by B7

### Required assertions for the unexecuted fixture

- Bind the OCI index and selected platform manifest by digest and verify the embedded source revision before start.
- Cap time, CPU, memory, stdout, stderr, artifacts and usage output and kill the complete process tree on cancellation.
- Capture exit status, final text, usage JSON, filesystem diff, network attempts and child-process evidence without promoting the result.
- Deny filesystem and network access externally except an explicitly bounded synthetic model endpoint.
- Mount a new disposable tmpfs at /opt/data with uid=10000,gid=10000,mode=0700 or an equivalent freshly created writable mount, keep HERMES_HOME=/opt/data and discard it after every outcome.
- Override the default entrypoint with /opt/hermes/bin/hermes and do not invoke /init, the entrypoint dispatcher or the stage2 hook.
- Provide a separate new empty CWD with no host rules, memory, profiles, plugins, skills or credentials.
- Require an external Nerva verifier and demonstrate native no-provider rollback after every outcome.
- Require explicit provider, model and reviewed toolset inputs; keep zero-tool mode blocked until proven.
- Scrub the child environment and set HERMES_SAFE_MODE=1 before process start without treating it as sufficient isolation; do not pass the chat-only --safe-mode flag to one-shot.
- Start as user 10000:10000 with a read-only root filesystem and no privilege escalation.

## E9 and authority

All provider-specific E9 dimensions remain `not_measured`: quality, latency, cost, reliability, privacy.

Every authority and repository-effect flag is `false`. The preflight cannot install, import, execute, register, route, authorize, approve, mark complete, promote or claim release readiness. Ultron / `nerva.action.v1` remains the sole privileged-action authority.

## Remaining blockers

- No image layer or PyPI artifact was pulled or executed; only registry manifest, config and provenance metadata payloads were fetched, and their authenticity was not independently verified.
- PyPI exposes 0.19.0, not the selected 0.20.0 source revision, and cannot be used as the exact distribution route.
- Repository guards inspect the nine canonical declarative Python dependency manifests and the third-party manifest only; absence of runtime or executable changes is established by this bounded branch diff, not by those dependency scans.
- Static source inspection does not prove runtime behavior, compatibility, containment, privacy, reliability or safety.
- The existing agents/core/skills/hermes_pin_v1.json is a prior non-executable exact-fetch evidence inventory and is intentionally not classified as dependency or updater enrolment.
- The root MIT license does not establish transitive or bundled-content license closure.
- The transitive import graph and configuration-dependent lazy installation paths were not exhaustively inspected.
- The upstream workflow tests one build and rebuilds the pushed images, so a successful workflow does not prove that the exact published bytes were the bytes tested.
- Vulnerability queries are a time-bounded advisory snapshot, not a complete direct, transitive, OS-package, npm-package or container-layer assessment.
- Windows and Linux behavior, process-tree cancellation, output framing, state retention and credential exposure remain unexecuted and unknown.

Completion of this preflight would not complete E8.1c or E8.1. A Hermes-executing adapter, manifest enrolment, supply-chain closure, trusted Nerva kernel context, compatibility runs and E9 comparison remain separate reviewed packages.
