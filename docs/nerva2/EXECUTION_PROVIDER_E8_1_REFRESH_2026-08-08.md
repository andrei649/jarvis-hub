# Nerva E8.1 — Hermes upstream refresh (2026-08-08)

> **Point-in-time snapshot — superseded 2026-08-28.** Every observation below is true *as of
> 2026-08-08* and is kept verbatim as a dated record. Upstream has since released `v2026.8.27`
> (commit `5fc308a70719a83cccdbba4c0e39c23f5a8239d5`); see
> [the v2026.8.27 delta port](../research/2026-08-28-hermes-v2026.8.27-delta-port.md). The
> execution-provider pin deliberately remains `v2026.8.3` / `3c27eb6`.

Status: `discovery / preflight evidence only` · dated 2026-08-08 · **read-only
refresh**. This document re-grounds the authoritative Hermes Agent upstream as of
today and checks the accepted E8.1a / E8.1c pin for drift. It is a refresh of, and
companion to, the accepted discovery map in
[`EXECUTION_PROVIDER_E8_1A.md`](EXECUTION_PROVIDER_E8_1A.md) and the static
preflight in [`EXECUTION_PROVIDER_E8_1C_PREFLIGHT.md`](EXECUTION_PROVIDER_E8_1C_PREFLIGHT.md).

It adds no code, dependency, provider contract, adapter, manifest enrolment,
installation, import, execution or authority change. It **proves no provider
compatibility and no execution**: every measured-relevant claim below is
`not_measured`, and provider-specific E9 evidence (#767) and release readiness
remain open.

## 1. Upstream facts re-verified today — primary sources

All facts below were re-checked on **2026-08-08** against primary sources
(GitHub repository/tags/releases/commit/compare APIs, the raw `pyproject.toml`
at the pinned tag, and the PyPI project page), read-only, with no install,
execution or credentials.

| Fact | Value verified 2026-08-08 | Primary source |
|---|---|---|
| Upstream owner / repository | `NousResearch/hermes-agent` | GitHub repo API |
| Visibility / archive state | public, not archived, not disabled | GitHub repo API |
| License | MIT (SPDX `MIT`) | GitHub repo API + `LICENSE` |
| Default branch | `main` | GitHub repo API |
| Activity | `pushed_at` 2026-08-08T16:52:42Z | GitHub repo API |
| Scale | 227,407 stars · 44,524 forks · 29,730 open issues | GitHub repo API |
| Latest release | `v2026.8.3` — "Hermes Agent v0.20.0 (2026.8.3)", published 2026-08-03 | `releases/tag/v2026.8.3` |
| Tag commit | `3c27eb6234bf91b8ceee9e9071591b31e9b148cb` — **still the newest release, and the pinned commit** | tags API + compare API |
| Commit tree | `b217767ccb994605dad522e693fa1b4cdbc2f352` (unchanged) | compare API |
| Tag signature | signed (SSH, verified — teknium1/Teknium) | tags page |
| Commit signature | **unsigned** | compare API (verification `unsigned`) |
| Package version at tag | `0.20.0` | `pyproject.toml` at `v2026.8.3`, read today |
| Interpreter range | `>=3.11,<3.14` | `pyproject.toml` at `v2026.8.3`, read today |
| PyPI package `hermes-agent` | **`0.19.0`** (released 2026-07-20, provenance commit `3ef6bbd` = `v2026.7.20`) | PyPI project page |
| Release cadence | ~weekly date-based tags: `v2026.6.5`, `v2026.6.19`, `v2026.7.1`, `v2026.7.7`, `v2026.7.7.2`, `v2026.7.20`, `v2026.7.30`, `v2026.8.3` | tags page |

**Answer to the refresh question: no newer release exists.** `v2026.8.3` is
still the newest tag and release as of 2026-08-08, and the pinned commit
`3c27eb6` / tree `b217767` is still the exact tip of that release — the E8.1a /
E8.1c pin is **current, not stale**. The `v2026.8.3` tag itself was re-verified
signed (SSH), and its commit re-verified unsigned, consistent with the accepted
discovery.

## 2. Drift note vs the pinned discovery

| Property | Pinned discovery (E8.1a §1.1 / E8.1c, 2026-08-06) | Observed today (2026-08-08) |
|---|---|---|
| Pin | `v2026.8.3` / `3c27eb6` / `b217767` / `0.20.0` | unchanged — still the latest release |
| Default-branch drift | `main` was 300 ahead / 0 behind the pin | `main` is **667 ahead / 0 behind** (tip `31cedb4`) |
| Package channel | PyPI `0.19.0`, lagging source by one release | PyPI still `0.19.0` — the lag **persists** |
| OCI route (E8.1c) | `dockerhub_oci_index_candidate_not_pulled` at `sha256:16788311…3712c9e` | unchanged; still not pulled |

`main` moved fast: ~200 commits in the two days after the E8.1c preflight and
667 commits in the five days since `v2026.8.3`. New top-level surfaces observed
on `main` that are **not** in the pinned tree (main-only, non-authoritative for
the map): `gateway/`, `acp_adapter/`, `providers/`, `plugins/`, `ui-tui/`,
`tui_gateway/`, `web/`, `website/`, `apps/`, `nix/`, `cron/`, `optional-skills/`,
`optional-mcps/`, `native/fts5_cjk/`, `mcp-research-data/`, `locales/`,
`datagen-config-examples/`, plus top-level modules such as `batch_runner.py`,
`mini_swe_runner.py`, `model_tools.py`, `toolset_distributions.py`,
`trajectory_compressor.py`, `mcp_serve.py`, `hermes_state*.py` and the `hermes`
launcher binary.

The E8.1a §5 point-in-time observation that the tag and `main` file sets were
identical is **superseded**: they are no longer identical. That is exactly why
E8.1a targeted the tag and never `main` — the refresh confirms that decision and
leaves the pin untouched. No pin movement is proposed.

## 3. Pinned `pyproject.toml` re-read today — unchanged

Reading `pyproject.toml` at `v2026.8.3` again today:

- `name = "hermes-agent"`, `version = "0.20.0"`, `license = "MIT"`,
  `requires-python = ">=3.11,<3.14"`, `authors = [Nous Research]`.
- Direct runtime dependencies remain **exact-pinned** (`==`) for nearly every
  entry (e.g. `openai==2.24.0`, `pydantic==2.13.4`, `cryptography==48.0.1`,
  `httpx[socks]==0.28.1`, `requests==2.33.0`), consistent with E8.1a §4.1.
- **45 optional-dependency extras** at the tag, verbatim the list in E8.1a §5.1.
  PyPI `0.19.0` advertises 42 (no `vercel`, `wake`, `otlp`), which confirms the
  extras surface is version-specific and the two channels still diverge.
- Console scripts at the tag: `hermes`, `hermes-agent`, and `hermes-acp`
  (`acp_adapter.entry:main`).
- Upstream's own dependency comments reference patched CVE floors for direct
  deps (e.g. `requests` CVE-2026-25645, `PyJWT` PYSEC-2026-175/177/178/179,
  `urllib3` GHSA-mf9v-mfxr-j63j / GHSA-qccp-gfcp-xxvc, `cryptography`
  CVE-2026-39892 / CVE-2026-34073 / GHSA-537c-gmf6-5ccf, `anthropic`
  CVE-2026-34450/34452, `aiohttp` CVE-2026-34513…34525 + 34993/47265,
  `starlette` CVE-2026-48710), consistent with the fail-closed E8.1c posture.
  **No fresh OSV query was run in this refresh**; the transitive license
  closure and complete CVE posture remain open, as recorded in E8.1c.

## 4. Reusable surfaces relevant to Nerva pillars — refreshed

Classification vocabulary and rows are unchanged from E8.1a §5. Every row still
carries the E8.1a stability caveat: upstream publishes **no documented public
API contract**, so all module surfaces remain `internal/unstable`. The table
below lists the pillars in this refresh's scope, the upstream evidence (tag-era
plus, where noted, main-era release-note evidence), and the **unchanged** class.

| Nerva need | Concrete upstream surface | Class (unchanged) | Refresh note |
|---|---|---|---|
| Terminal / command execution | `tools/terminal_tool.py`, `read_terminal_tool.py`, `close_terminal_tool.py`, `focus_pane_tool.py`, `terminal_hints.py`, `daemon_pool.py`, `process_registry.py` (tag); `!command` shell mode and truncated-output spill (v0.20.0 notes) | `thin_adapter` | Seven terminal backends on `main` (Vercel Sandbox modernized); six at the tag-era README |
| Sandboxed code execution | `code_execution_tool.py`, `tools/environments/` (tag) | `thin_adapter` | unchanged |
| Browser automation | `browser_tool.py`, `browser_cdp_tool.py`, `browser_camofox*.py`, `browser_dialog_tool.py`, `browser_supervisor.py` (tag); Browser Use cloud browser via Nous Portal (main README) | `thin_adapter` | unchanged |
| Desktop / computer use | `computer_use_tool.py`, `tools/computer_use/` (cua-driver via MCP stdio), `desktop_ui.py` (tag); desktop drives the shell + inspects the app, SSH remote-backend mode (v0.20.0 notes); `computer-use-linux` community MCP (README) | `thin_adapter` | highest risk; visual control stays a fallback route, never default |
| Home Assistant control | `homeassistant_tool.py` (tag); `homeassistant` extra (`aiohttp==3.14.1`); Home Assistant listed as a gateway platform (main README) | `thin_adapter` | governed actuation only |
| Secret sources | pluggable `SecretSource` (Bitwarden / 1Password) (v0.19.0); command-helper secret source, `${env:VAR}` SecretRef parity, encrypted break-glass cache (v0.20.0) | `thin_adapter` / `reuse` as *reference* | reinforces E8.1b `secret_refs` — credentials stay Nerva-side references |
| Completion contracts | `hermes-oneshot` candidate seam (E8.1c); A2A v1.0 bundled plugin; **signed outbound webhooks (HMAC)** for session/turn/tool lifecycle events (v0.20.0); durable delivery + delegation ledgers (v0.19.0) | `thin_adapter` / `reuse` as *reference* | never a Nerva completion or authority; Verification Fabric stays canonical |
| Action-level audit / approval | `approval.py`, `path_security.py`, `threat_patterns.py`, `tirith_security.py`, `url_safety.py`, `osv_check.py` (tag); `hermes approvals suggest`, smart-policy, consecutive-denial circuit breaker, docker/podman approval gate (v0.20.0) | **`reject` as authority**, `reuse` as *reference* | Ultron / `nerva.action.v1` remains sole authority |
| Verification | agent self-verification (v0.18.0); grounded-citations skill with fact-checking, strict redaction at compaction (v0.20.0) | `reuse` as *reference* | Nerva Verification Fabric + `nerva.benchmark.v1` stay canonical |
| Delegation / subagents | `delegate_tool.py`, `async_delegation.py` (tag); async subagents, `execute_code` in subagents, public subagent lifecycle API (v0.20.0) | `native_fallback` | `subagents.py` already carries the adapted blocked-tool policy |
| Memory / user model | `memory_tool.py`, `hermes_state*.py` (main) | `reject` | Atlas and Episodes are canonical |
| Budgets | `budget_config.py` | `native_fallback` | `iteration_budget.py` already ported |
| MCP client surface | `mcp_tool.py`, `mcp_oauth*.py`, `mcp_schema_cache.py`, `mcp_stdio_watchdog.py` (tag) | `thin_adapter` | credentials stay Nerva-side references |
| Scheduling / gateway | `managed_tool_gateway.py`, `clarify_gateway.py`, `cronjob_tools.py` (tag) | `thin_adapter` | provider supplies runtime, never session authority |
| Checkpoint / resume | `checkpoint_manager.py` | `thin_adapter` | maps to `nerva.work-run.v1` checkpoint semantics |
| Planning / cognition | — | `reject` | Cortex owns decisions |
| Identity | — | `reject` | must not merge with Nerva or Howard identity |

All other E8.1a §5 rows (skills/plugins, security controls, memory, budgets,
planning, identity) are unchanged and remain as recorded in the accepted map.

## 5. Classification impact — no change

**Nothing in this refresh materially changes the E8.1a classification.** The
reasons, stated explicitly:

- The pinned tag is unchanged and still current (§1), so every E8.1a row that
  rests on the tag stands as accepted.
- New upstream features since the pin (SecretSource, A2A, signed webhooks,
  self-verification, approval mining) map to **already-classified rows** and to
  boundaries E8.1a/E8.1b already drew (`grants_authority=false`,
  `secret_refs` only, external verification mandatory). They add evidence for
  existing classifications; none flips `reuse` → `reject` or `reject` → adapter.
- Main-era surfaces are drift, and E8.1a already ruled `main` non-authoritative.

The refreshed classification therefore remains, verbatim in spirit:
`reuse` (already-ported skills/patterns) · `thin_adapter` (terminal, browser,
computer-use, Home Assistant, MCP, scheduling, checkpoint, secrets-as-reference)
· `native_fallback` (delegation, budgets) · `reject` as authority (approval,
memory, planning, identity). Still **discovery / preflight evidence only**.

## 6. Risks surfaced or reinforced since the last discovery

| Risk | Refresh observation | Required control (unchanged) |
|---|---|---|
| Upstream velocity | 667 commits in 5 days; 29,730 open issues; weekly releases | pin discipline is load-bearing; watch **both** the GitHub tag feed and the PyPI feed (still divergent) |
| Supply chain | pinned tag exact-pins direct deps and carries patched CVE floors; E8.1c recorded 6 OSV CVE groups | no install/execution; transitive license + complete CVE closure remain open gates |
| Network / retention | new **signed outbound webhooks** and A2A plugin are upstream egress surfaces | deny-by-default network; declared retention; external verifier mandatory |
| Secrets | upstream SecretSource vault integrations (Bitwarden/1Password) process real credentials | `{{secret:name}}` references only; values never cross into the provider |
| Filesystem | root-MIT repo plus bundled restrictive productivity-skill licenses (recorded in E8.1c) | read-only image root; disposable tmpfs; license closure unresolved |
| Sandbox | default container root entrypoint + stage2 mutations (E8.1c) unchanged | fixture still blocked on B7/#818; zero-tool mode unproven |
| Authority | upstream approval/smart-policy is a tool, not a Nerva gate | `grants_authority=false` immutable; Ultron remains sole authority |

## 7. What this refresh could NOT verify (still open)

- **Provider compatibility and execution** — nothing is proven; every
  compatibility/reliability dimension stays `not_measured`. Provider-specific
  E9 evidence (#767) and release readiness remain **open**.
- No fresh OSV/CVE query, no OCI layer pull, no Sigstore bundle
  cryptographically verified, no function/class signature read — this refresh
  is a release-grounding check, not a new supply-chain audit.
- Transitive license closure and the four bundled productivity-skill licenses
  remain unresolved (E8.1c §Supply-chain state).
- Behavior on Windows/Linux, process-tree cancellation, state retention and
  credential exposure remain unexecuted and unknown.

## 8. Linkage

- Refresh of: [`EXECUTION_PROVIDER_E8_1A.md`](EXECUTION_PROVIDER_E8_1A.md)
  (accepted discovery + compatibility map, E8.1a).
- Consistent with: [`EXECUTION_PROVIDER_E8_1C_PREFLIGHT.md`](EXECUTION_PROVIDER_E8_1C_PREFLIGHT.md)
  (static preflight; its immutable snapshot is unchanged).
- Contract untouched: [`EXECUTION_PROVIDER_E8_1B.md`](EXECUTION_PROVIDER_E8_1B.md)
  (inert provider-neutral `nerva.execution-provider.v1`).
- Catalogue: the Hermes Agent finding in
  [`INTEGRATION_CATALOGUE_RFC.md`](INTEGRATION_CATALOGUE_RFC.md) §2 is
  re-verified by this refresh (marked `PARKED` / secondary-or-better as there).
- Benchmark conventions if a comparison is ever run:
  [`RESEARCH_LAB_E9_0.md`](RESEARCH_LAB_E9_0.md) (`nerva.benchmark.v1`).

## 9. Bottom line

As of **2026-08-08**: upstream owner `NousResearch`, license MIT, latest
release `v2026.8.3` (`0.20.0`) published 2026-08-03, pinned commit `3c27eb6` /
tree `b217767` **still current and reachable**, PyPI still lagging at `0.19.0`,
`main` 667 commits ahead of the pin. No classification change, no pin movement,
no authority change, no compatibility or execution claim. E8.1 remains BUILDING;
provider-specific E9 (#767) and release readiness remain open.
