# Nerva E8.1a — Hermes upstream discovery and compatibility map

Status: read-only discovery evidence for #804 / #766. This document contains no
provider contract, no adapter, no dependency and no capability claim. It does not
assert that any Hermes interface has been tested against Nerva.

## Scope and method

E8.1a is documentation-only. Nothing here was installed, executed, cloned or
copied. Every claim below is either:

- **verified in this repository** — with the exact file and line it comes from;
- **verified at public upstream primary source** — with the exact artifact URL
  inspected, read-only, on 2026-08-04; or
- **explicitly unverified** — listed in [§8](#8-what-this-discovery-could-not-verify)
  rather than guessed.

The repository already contains four Hermes research documents. This map does not
repeat them; it cites them and adds the one thing they do not cover — the
compatibility and security boundary for an *execution provider*:

- [`docs/research/2026-06-07-hermes-agent.md`](../research/2026-06-07-hermes-agent.md)
- [`docs/research/2026-07-06-hermes-agent-migration-plan.md`](../research/2026-07-06-hermes-agent-migration-plan.md)
- [`docs/research/2026-07-11-ai-os-vision-and-hermes-strategy.md`](../research/2026-07-11-ai-os-vision-and-hermes-strategy.md)
- [`docs/research/2026-07-25-nerva-vs-hermes-honest-gap-analysis.md`](../research/2026-07-25-nerva-vs-hermes-honest-gap-analysis.md)

## 1. Upstream identity and license — verified

| Fact | Value | Verified in |
|---|---|---|
| Upstream repository | `NousResearch/hermes-agent` | `agents/core/skills/importer.py:39`; `LICENSES/hermes-agent-MIT.txt:1` |
| Upstream URL | `https://github.com/NousResearch/hermes-agent` | `LICENSES/hermes-agent-MIT.txt:1` |
| License | MIT | `LICENSES/hermes-agent-MIT.txt` |
| Copyright holder | Nous Research (2025) | `LICENSES/hermes-agent-MIT.txt` |
| License mirrored in-repo | yes | `LICENSES/hermes-agent-MIT.txt` |

MIT is compatible with reuse, adaptation and redistribution provided the notice
is retained. The notice **is** retained, and the mirror additionally records
which files were adapted — a stronger practice than the license requires.

### 1.1 Release scheme and the pin — verified at primary source

Inspected on 2026-08-04 via the public repository (no clone, no install, no
credentials):

| Fact | Value | Primary artifact inspected |
|---|---|---|
| Release scheme | date-based tags, `vYYYY.M.D[.N]` | `github.com/NousResearch/hermes-agent/tags` |
| Recent tags (newest first) | `v2026.8.3`, `v2026.7.30`, `v2026.7.20`, `v2026.7.7.2`, `v2026.7.7`, `v2026.7.1`, `v2026.6.19`, `v2026.6.5` | same |
| Latest release | `v2026.8.3` — "Hermes Agent v0.20.0 (2026.8.3)", published 2026-08-03 | `releases/tag/v2026.8.3` |
| Commit for `v2026.8.3` | `3c27eb6234bf91b8ceee9e9071591b31e9b148cb` | `releases/tag/v2026.8.3` |
| Package version at that tag | `0.20.0` | `raw.githubusercontent.com/.../v2026.8.3/pyproject.toml` |
| Package version on `main` | `0.20.0` | `raw.githubusercontent.com/.../main/pyproject.toml` |
| Interpreter range | `>=3.11,<3.14` | both `pyproject.toml` reads |

**Recommended compatibility target: tag `v2026.8.3`, commit
`3c27eb6234bf91b8ceee9e9071591b31e9b148cb`, package `0.20.0`.**

Rationale, and an explicit correction: a `v2026.7.7.2` / `0.18.2` candidate was
proposed during review. That tag is real but is now **four releases behind**
(`v2026.7.20`, `v2026.7.30`, `v2026.8.3` followed it). Pinning a superseded
release would start E8.1b already stale, so the latest *release* is the correct
target. `main` is deliberately **not** the target: it is mutable, and although it
currently reports the same `0.20.0` version as the tag, that equality is a
coincidence of timing, not a guarantee.

Update mechanism: GitHub releases/tags. There is no separate distribution
channel to track, so the repository's existing tag-based drift checker is
sufficient.

## 2. What Nerva already reuses — verified

The license mirror records six adapted surfaces. Each was **ported or adapted**,
not linked against, so none of them is an execution-provider boundary today:

| Nerva file | Adapted from | Nature |
|---|---|---|
| `agents/core/iteration_budget.py` | `agent/iteration_budget.py` | ported logic |
| `agents/core/subagents.py` (blocked set) | `tools/delegate_tool.py` | adapted constant/policy |
| `agents/core/learning/background_review.py` | `agent/background_review.py` | prompts + anti-capture rules |
| `agents/core/learning/core_block.py` | `tools/memory_tool.py` | frozen snapshot + BLOCKED placeholder |
| `agents/core/skills/usage.py` | `tools/skill_usage.py` | ported logic |
| `agents/core/skills/curator.py` | `agent/curator.py` | ported logic |

Further Hermes-derived patterns are documented in code comments but are *not*
listed in the license mirror:

- `agents/core/tool_rpc.py:7` — "zero-context-cost pipelines";
- `agents/core/context_compressor.py:2,11-14` — Phase 2 summary template;
- `agents/core/channels/session.py:3` — "Hermes-style gateway session layer";
- `agents/core/orchestrator.py:1690` — frozen-snapshot discipline;
- `agents/core/skills/importer.py`, `loader.py` — the `SKILL.md` convention.

**Consequence for E8.1b:** these surfaces are already native Nerva code. A
provider contract must not re-import them through an adapter, or the same logic
would exist on both sides of the boundary.

## 3. Live runtime coupling — verified, and a security finding

`agents/core/skills/importer.py` fetches Hermes skills **at runtime** from the
upstream default branch:

```python
HERMES_REPO = "NousResearch/hermes-agent"   # importer.py:39
HERMES_SKILLS_PATH = "main/skills"          # importer.py:40
GITHUB_RAW = "https://raw.githubusercontent.com"
GITHUB_API = "https://api.github.com"
```

The listing call is `GET {GITHUB_API}/repos/{repo}/git/trees/main?recursive=1`.

Properties of this path, as implemented today:

- it tracks **`main`**, not a tag or commit — content can change under us;
- there is **no integrity check** on the fetched `SKILL.md` — no digest, no signature;
- the route is guarded (`DEV_MODE`-only, user-guarded) and the importer already
  hardens the skill name against path traversal via `_SLUG_RE`
  (`importer.py:_safe_slug`), which is a real mitigation for the *filesystem*
  risk but not for the *content* risk.

This is the concrete supply-chain surface E8.1b must address. It is a genuine
finding, not a hypothetical.

## 4. Pinning and drift — verified gap

The repository already owns the machinery E8.1a asks for:

- `.github/third-party-manifest.json` — pins third-party sources;
- `scripts/check_thirdparty_drift.py` — detects drift and files a tracking issue;
- `scripts/update_thirdparty.py` — re-vendors and bumps a pin for review;
- `.github/workflows/thirdparty-drift.yml`, `thirdparty-autoupdate.yml`.

**`hermes-agent` appears in neither `sources` nor `untracked`** in that manifest.
Verified: the manifest lists `superpowers` and `codebase-memory-mcp` under
`sources`, and `axon` under `untracked`. `check_thirdparty_drift.py:112` iterates
`manifest["sources"]` only and requires `track_drift` plus `repo`.

So today Hermes is:

| Property | superpowers | axon | **hermes-agent** |
|---|---|---|---|
| License mirrored | ✅ | ✅ | ✅ |
| Listed in manifest | ✅ `sources` | ✅ `untracked` | ❌ **absent** |
| Version pinned | ✅ `6.1.1` | n/a (declared) | ❌ **none** |
| Drift tracked | ✅ | explicitly not | ❌ **never checked** |

The license mirror lists adapted files but records **no upstream commit or tag**,
so there is currently no way to tell whether the six adapted files still
correspond to anything upstream.

### Proposed manifest entry — deliberately NOT applied here

E8.1a is documentation-only, so this PR does not modify the manifest. The
proposal below is the recommended E8.1b (or owner) action:

```jsonc
{
  "name": "hermes-agent",
  "repo": "NousResearch/hermes-agent",
  "kind": "adapted (not vendored verbatim) + runtime skill source",
  "path": "LICENSES/hermes-agent-MIT.txt",
  "pinned_version": "v2026.8.3",
  "license": "LICENSES/hermes-agent-MIT.txt",
  "track_drift": true,
  "update_doc": "docs/nerva2/EXECUTION_PROVIDER_E8_1A.md"
}
```

`pinned_version` is the verified latest release from §1.1, resolving to commit
`3c27eb6234bf91b8ceee9e9071591b31e9b148cb`.

**Operationally, once that entry lands:**

| Question | Answer |
|---|---|
| What enters the manifest | `v2026.8.3` |
| What the drift checker observes | new tags on `NousResearch/hermes-agent` via the existing `check_thirdparty_drift.py` tag lookup |
| What triggers compatibility tests | the drift issue / update PR opened by `thirdparty-drift.yml` and `thirdparty-autoupdate.yml` |
| How updates are reviewed | manually, on the auto-opened PR — `update_thirdparty.py` bumps the pin, it never promotes |
| How the mutable runtime fetch is fixed | replace `HERMES_SKILLS_PATH = "main/skills"` with the pinned tag, and record a content digest per imported `SKILL.md` |
| Native fallback | unchanged — Nerva executes natively when no provider is registered |

The runtime-fetch change and the manifest entry are both **E8.1b work**; this
slice deliberately changes no code or configuration.

## 4.1 Dependency and license surface — inspected

From `pyproject.toml` at `main` and at `v2026.8.3` (both read, both `0.20.0`):

- **Lock mechanism:** direct runtime dependencies are **exact-pinned** (`==`) for
  almost all entries — for example `openai==2.24.0`, `pydantic==2.13.4`,
  `cryptography==48.0.1`, `httpx[socks]==0.28.1`, `pyyaml==6.0.3`,
  `Pillow==12.3.0`. A few use bounded ranges: `urllib3>=2.7.0,<3`,
  `fastapi>=0.104.0,<1`, `uvicorn[standard]>=0.24.0,<1`,
  `python-multipart>=0.0.9,<1`, `nemo-relay>=0.6.0,<0.7`, plus platform-conditional
  `ptyprocess`, `pywinpty`, `pywin32`, `tzdata`, `concurrent-log-handler`.
- **Assessment:** exact pinning upstream is a favourable supply-chain property —
  it makes a Nerva-side pin reproducible rather than nominal.
- **Optional extras** are listed in §5.1. Several pull heavyweight or
  network-bound stacks (`computer-use`, `vision`, `voice`, `daytona`, `modal`,
  `bedrock`, `vertex`). E8.1b must install **no extras by default**.
- **Not verified:** the transitive license closure. Only the direct dependency
  list was read. A full transitive license and CVE review is required E8.1b work
  and is not claimed here.

## 5. Concrete upstream interfaces — inventoried at `main/tools`

Module names below are **verbatim from the public directory listing** of
`github.com/NousResearch/hermes-agent/tree/main/tools`, inspected 2026-08-04.

Stability caveat, stated up front: this project publishes **no documented public
API contract** that was found during this inspection. Everything in `tools/` is
therefore classified `internal/unstable` — importable in practice, but with no
compatibility promise. That is itself a finding, and it is the main argument for
a thin adapter over deep coupling.

| Nerva need | Concrete upstream modules | Stability | Class | Boundary it must cross |
|---|---|---|---|---|
| Terminal execution | `terminal_tool.py`, `read_terminal_tool.py`, `close_terminal_tool.py`, `focus_pane_tool.py`, `terminal_hints.py`, `daemon_pool.py`, `process_registry.py` | internal/unstable | `thin_adapter` | ToolRPC + existing sandbox; effects via Ultron |
| Sandboxed code execution | `code_execution_tool.py`, `tools/environments/` | internal/unstable | `thin_adapter` | sandbox; declared bounds only |
| Browser automation | `browser_tool.py`, `browser_cdp_tool.py`, `browser_camofox.py`, `browser_camofox_state.py`, `browser_dialog_tool.py`, `browser_supervisor.py` | internal/unstable | `thin_adapter` | Ultron authorization + Verification |
| Computer / desktop use | `computer_use_tool.py`, `tools/computer_use/`, `desktop_ui.py` | internal/unstable | `thin_adapter` | highest risk; visual control is a fallback route, never default |
| Skills / plugins | `skills_tool.py`, `skill_manager_tool.py`, `skills_hub.py`, `skills_sync.py`, `skills_sync_client.py`, `skill_provenance.py`, `skills_guard.py`, `skills_ast_audit.py`, `skill_usage.py` | internal/unstable | `reuse` (already partly ported) | `nerva.capability.v1`; needs pinning, not an adapter |
| Delegation / subagents | `delegate_tool.py`, `async_delegation.py`, `delegation_live_log.py` | internal/unstable | `native_fallback` | `subagents.py` already carries the adapted blocked-tool policy |
| Scheduling / gateway | `managed_tool_gateway.py`, `clarify_gateway.py`, `cronjob_tools.py` | internal/unstable | `thin_adapter` | provider supplies runtime, never session authority |
| MCP client surface | `mcp_tool.py`, `mcp_oauth.py`, `mcp_oauth_manager.py`, `mcp_dashboard_oauth.py`, `mcp_schema_cache.py`, `mcp_stdio_watchdog.py` | internal/unstable | `thin_adapter` | credentials stay Nerva-side as references |
| Checkpoint / resume | `checkpoint_manager.py` | internal/unstable | `thin_adapter` | maps to `nerva.work-run.v1` checkpoint semantics |
| Approval / security controls | `approval.py`, `path_security.py`, `threat_patterns.py`, `tirith_security.py`, `url_safety.py`, `osv_check.py` | internal/unstable | **`reject` as authority**, `reuse` as *reference* | Ultron remains sole authority; these may inform Nerva policy but never decide |
| Memory / user model | `memory_tool.py` | internal/unstable | `reject` | Atlas and Episodes are canonical |
| Budgets | `budget_config.py` | internal/unstable | `native_fallback` | `iteration_budget.py` is already ported |
| Home Assistant | `homeassistant_tool.py` | internal/unstable | `thin_adapter` | governed actuation only |
| Planning / cognition | — | — | `reject` | Cortex owns decisions |
| Identity | — | — | `reject` | must not merge with Nerva or Howard identity |

**Not verified:** function and class signatures. This is a *file-level*
inventory from a directory listing. No upstream source was read, so no signature,
argument or return-type claim is made anywhere in this document.

### 5.1 Declared capability surface — from `pyproject.toml` extras

The optional-dependency extras are a useful, verifiable statement of what
upstream already integrates. Verbatim group names at `main`:

`anthropic`, `exa`, `firecrawl`, `parallel-web`, `fal`, `edge-tts`, `modal`,
`daytona`, `vercel`, `hindsight`, `dev`, `messaging`, `cron`, `slack`, `matrix`,
`wecom`, `cli`, `tts-premium`, `voice`, `wake`, `honcho`, `supermemory`, `mem0`,
`vision`, `pty`, `mcp`, `nemo-relay`, `homeassistant`, `sms`, `teams`,
`computer-use`, `acp`, `mistral`, `otlp`, `bedrock`, `vertex`, `azure-identity`,
`termux`, `termux-all`, `dingtalk`, `feishu`, `google`, `youtube`, `web`, `all`.

Directly relevant to Nerva's pillars: `computer-use`, `homeassistant`, `mcp`,
`voice`, `wake`, `vision`, `pty`, `cron`, `daytona`, `modal`.

## 6. Nerva boundary mapping

Where each provider surface must land, using accepted contracts:

```text
provider capability declaration → nerva.capability.v1 (Synapse, description_only)
provider invocation             → ToolRPC + existing sandbox
privileged effect               → Ultron / nerva.action.v1 (unchanged)
returned evidence               → Verification Fabric + nerva.benchmark.v1
comparison vs native            → E9 lanes (E9.0 accepted, E9.1 in review)
```

`grants_authority=false` must be immutable on the provider record, mirroring the
`init=False` authority-ceiling pattern already used by `nerva.decision.v1`,
`nerva.lesson.v1` and `nerva.benchmark.report.v1`.

## 7. Threat model for E8.1b

| Risk | Why it matters here | Required control |
|---|---|---|
| Unpinned upstream content | §3: skills fetched from `main` with no digest | pin + integrity check before any adapter |
| Skill/plugin supply chain | a malicious `SKILL.md` becomes agent instructions | review gate, no auto-import into production |
| Subprocess escape | provider runtimes execute code | existing sandbox, declared bounds, no host escalation |
| Hidden network / retention | provider may call out or retain data | deny-by-default network, declared retention |
| Secret exposure | provider needs credentials to be useful | secret *references* only, never inline values |
| Provenance loss | evidence crossing the adapter loses its source | evidence must carry provider identity and version |
| Authority leakage | provider result read as approval | `grants_authority=false`, external verification mandatory |
| API churn | upstream is a moving target | pinned version + compatibility tests + manual update review |
| Architecture drift | provider concepts leak into Cortex/Synapse | provider vocabulary confined to the adapter |

## 8. What this discovery could NOT verify

Stated plainly, because inventing any of it would be worse than leaving it open:

- **upstream function/class signatures** — §5 is a file-level inventory from a
  public directory listing. No upstream source file was read, so no signature,
  argument or return-type claim appears anywhere in this document;
- **whether any upstream module is API-stable** — no public API contract was
  found, which is why every surface is classified `internal/unstable`;
- **whether the six already-adapted files still match upstream** — the license
  mirror records no upstream commit, so historical drift remains unmeasurable.
  Going forward the §4 pin fixes this for new work, but it does not retroactively
  tell us what those six files were adapted from;
- **the transitive license closure and CVE posture** — only the direct dependency
  list was read (§4.1);
- **any performance, reliability, cost or privacy property** of Hermes. Nothing
  has been measured, and nothing is estimated. E9 must measure before promotion.

**Unblock statement — corrected.** An earlier revision of this document claimed
the pin required owner input. That was wrong: the upstream is public and the pin
was obtainable by ordinary read-only inspection, which §1.1 now records. No owner
decision and no credentials are needed for E8.1a. E8.1b remains blocked only
until this completed map is independently accepted.

## 9. Evidence E9 must produce before any adapter promotion

Per #804 and the accepted E9 contracts, before a shadow adapter may be promoted:

- a pinned Hermes version compared against the **native baseline** on quality,
  latency, cost, reliability and privacy, with unmeasured dimensions left
  `not_measured` rather than estimated;
- negative and failed runs retained and visible;
- cancellation, timeout, partial failure and rollback exercised;
- `ungoverned_actions == 0` across the adapter seam;
- a demonstrated native/no-provider rollback.

## 10. Exclusions honored by this slice

No fork, no vendored subsystem, no dependency, no adapter code, no provider
contract, no installation, no execution of upstream source, no credential use, no
manifest or workflow change, and no capability claim. Rollback is the revert of
this single document.

## Next coherent package

E8.1b (`nerva.execution-provider.v1`) is blocked only on independent acceptance
of this map. The smallest movements after acceptance, in order:

1. Add the §4 manifest entry pinning `v2026.8.3` so drift is tracked like every
   other third-party source.
2. Replace the mutable `main/skills` runtime fetch with the pinned tag plus a
   content digest per imported `SKILL.md`.
3. Only then define the provider contract, with `grants_authority=false`
   immutable, and a transitive license/CVE review of the direct dependencies in
   §4.1.
