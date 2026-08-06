# Nerva E8.1a — Hermes discovery and skill-fetch integrity boundary

Status: accepted read-only discovery evidence from #819 plus the bounded,
review-pending skill-fetch integrity package for issue #830 in draft PR #834.
This document contains no provider contract, adapter, dependency, manifest
enrolment or capability claim.
It does not assert that any Hermes interface has been tested against Nerva.

## Scope and method

The original E8.1a discovery slice was documentation-only. The draft PR #834 package for issue #830
changes only the existing skill importer, its tests, this document and a compact
pin record. No Hermes runtime, dependency or upstream
skill is copied into the repository, installed or executed. Pin generation used
a temporary, read-only fetch of exact Git objects outside the repository;
reproducibility was then checked against exact-commit raw URLs without importing
the returned content.
Every claim below is either:

- **verified in this repository** — with a stable repository path and symbol,
  where one exists;
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
| Upstream repository | `NousResearch/hermes-agent` | `agents/core/skills/importer.py` (`HERMES_REPO`); `LICENSES/hermes-agent-MIT.txt` |
| Upstream URL | `https://github.com/NousResearch/hermes-agent` | `LICENSES/hermes-agent-MIT.txt` |
| License | MIT | `LICENSES/hermes-agent-MIT.txt` |
| Copyright holder | Nous Research (2025) | `LICENSES/hermes-agent-MIT.txt` |
| License mirrored in-repo | yes | `LICENSES/hermes-agent-MIT.txt` |

MIT is compatible with reuse, adaptation and redistribution provided the notice
is retained. The notice **is** retained, and the mirror additionally records
which files were adapted — a stronger practice than the license requires.

### 1.1 Release scheme and the pin — verified at primary source

Initially inspected on 2026-08-04 and revalidated through the public GitHub API
and exact Git objects on 2026-08-06 (no install, execution or credentials):

| Fact | Value | Primary artifact inspected |
|---|---|---|
| Release scheme | date-based tags, `vYYYY.M.D[.N]` | `github.com/NousResearch/hermes-agent/tags` |
| Recent tags (newest first) | `v2026.8.3`, `v2026.7.30`, `v2026.7.20`, `v2026.7.7.2`, `v2026.7.7`, `v2026.7.1`, `v2026.6.19`, `v2026.6.5` | same |
| Latest release | `v2026.8.3` — "Hermes Agent v0.20.0 (2026.8.3)", published 2026-08-03 | `releases/tag/v2026.8.3` |
| Commit for `v2026.8.3` | `3c27eb6234bf91b8ceee9e9071591b31e9b148cb` | `releases/tag/v2026.8.3` |
| Commit tree | `b217767ccb994605dad522e693fa1b4cdbc2f352` | GitHub commit API |
| Annotated tag verification | valid SSH signature; tag object `7de39e700d2c329e15d32eb0b96e2f7cdd9fbdb2` points to the commit above | GitHub tag API |
| Commit verification | **unsigned** | GitHub commit API |
| Package version at that tag | `0.20.0` | `raw.githubusercontent.com/.../v2026.8.3/pyproject.toml` |
| Package version on `main` | `0.20.0` | `raw.githubusercontent.com/.../main/pyproject.toml` |
| Interpreter range | `>=3.11,<3.14` | both `pyproject.toml` reads |

**Recommended compatibility target: tag `v2026.8.3`, commit
`3c27eb6234bf91b8ceee9e9071591b31e9b148cb`, package `0.20.0`.**

Rationale, and an explicit correction: a `v2026.7.7.2` / `0.18.2` candidate was
proposed during review. That tag is real but is now **three releases behind** — exactly
`v2026.7.20`, `v2026.7.30` and `v2026.8.3` followed it. Pinning a superseded
release would start E8.1b already stale, so the latest *release* is the correct
target. `main` is deliberately **not** the target: it is mutable, and although it
currently reports the same `0.20.0` version as the tag, that equality is a
coincidence of timing, not a guarantee.

### 1.2 Distribution channels — there are two, not one

An earlier revision of this document claimed GitHub releases/tags were the only
channel. That was **wrong**. Hermes Agent is also published to PyPI, and the two
channels are not in lockstep:

| Channel | Latest observed | Verified at |
|---|---|---|
| GitHub source tag | `v2026.8.3` → package version `0.20.0` | `releases/tag/v2026.8.3`, `pyproject.toml` at that tag |
| PyPI package `hermes-agent` | **`0.19.0`**, released 2026-07-20 | `pypi.org/project/hermes-agent/` |

**Finding: the package channel lags the source tag by one release.** `0.20.0` is
tagged in git but the latest published wheel/sdist is `0.19.0`. A source pin and a
package pin are therefore *different artifacts pointing at different code*, and
tracking GitHub tags alone would not have revealed this.

PyPI metadata verified on the same page: license MIT, `Requires-Python >=3.11,<3.14`
— both consistent with the source tag. The project publishes with **GitHub Actions
Trusted Publishing**, and the release carries **Sigstore attestation bundles with
in-toto statements** for both the sdist and the wheel.

**Policy consequence for E8.1b:** pin **source**, not the package, for the
compatibility map and any adapter that reads upstream interfaces — the adapter
targets modules, and modules live in the repository. If a runtime dependency on
the published package is ever introduced, it needs its own pin *and* attestation
verification, because Trusted Publishing provenance is only meaningful if
something actually checks it. Drift policy must therefore watch **both** the tag
feed and the PyPI release feed, and treat divergence between them as a signal
rather than noise.

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

- `agents/core/tool_rpc.py` — "zero-context-cost pipelines" module boundary;
- `agents/core/context_compressor.py` (`ContextCompressor`, `SUMMARY_PROMPT`) —
  Phase 2 summary template;
- `agents/core/channels/session.py` (`SessionSource`, `DeliveryRouter`) —
  "Hermes-style gateway session layer";
- `agents/core/orchestrator.py` (`Orchestrator._living_core_memory_block`) —
  frozen-snapshot discipline;
- `agents/core/skills/importer.py`, `loader.py` — the `SKILL.md` convention.

**Consequence for E8.1b:** these surfaces are already native Nerva code. A
provider contract must not re-import them through an adapter, or the same logic
would exist on both sides of the boundary.

## 3. Runtime skill-fetch integrity — issue #830 implementation in draft PR #834

Before draft PR #834 implemented issue #830, `agents/core/skills/importer.py`
listed and fetched Hermes skills from mutable `main/skills` and retained no
source revision or content digest. The route was already `DEV_MODE`-only,
user-guarded and protected by `_safe_slug`; those controls limited callers and
filesystem paths but did not bind the remote bytes.

The draft PR #834 technical package for issue #830 replaces only the
`source=hermes` path:

| Bound field | Accepted value |
|---|---|
| Repository | `NousResearch/hermes-agent` |
| Release provenance | `v2026.8.3` |
| Fetch ref | exact commit `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`, never tag or `main` |
| Commit tree provenance | `b217767ccb994605dad522e693fa1b4cdbc2f352` |
| Allowlist | 71 unique slug/path records covering every `skills/**/SKILL.md` blob in the non-truncated tree |
| Pin artifact | `agents/core/skills/hermes_pin_v1.json`, 13,950 bytes, SHA-256 `ae44e31a537fba2269550c321a025c2c726e8a84402d32bbb9f1b0854a35e33d` |

The pin loader accepts exact known fields only; it rejects malformed schema,
repository or pinned release/commit/tree substitution, mutable or malformed tag
labels, non-canonical commit/tree IDs, empty/duplicate/non-deterministic
identities, unsafe paths, slug/path drift and malformed content digests before a
network call or skill directory write.

For one import, the importer selects only the requested allowlisted slug and
fetches its exact path at the pinned commit. It rejects redirects or response
URL changes, unavailable content, non-byte bodies, SHA-256 mismatch and invalid
UTF-8 or a frontmatter-name/slug mismatch before changing the target. The
verified raw bytes are retained exactly, and the sidecar records repository,
release tag, commit, tree, upstream path and content SHA-256.

Hermes bulk and category sync iterate the local allowlist, not a GitHub tree.
Every selected response is fetched and verified in memory before the first
write, so an integrity failure cannot leave a prefix of a bulk import behind.
The 2026-08-06 reproducibility run fetched all 71 exact-commit raw URLs without
importing or executing them: 71/71 digests matched over 842,142 bytes.

Generic GitHub and OpenClaw import/list behavior remains on its existing path.
The pin proves that returned content matches the locally accepted bytes. It does
**not** prove that upstream content is safe, compatible or trustworthy. After
an explicit successful import, the existing API still calls skill discovery, so
the verified instruction file becomes discoverable; that is availability, not a
new trust approval, authority grant or execution-provider promotion.

## 4. Pinning and drift — verified gap

The repository already owns the machinery E8.1a asks for:

- `.github/third-party-manifest.json` — pins third-party sources;
- `scripts/check_thirdparty_drift.py` — detects drift and files a tracking issue;
- `scripts/update_thirdparty.py` — re-vendors and bumps a pin for review;
- `.github/workflows/thirdparty-drift.yml`, `thirdparty-autoupdate.yml`.

**`hermes-agent` appears in neither `sources` nor `untracked`** in that manifest.
Verified: the manifest lists `superpowers` and `codebase-memory-mcp` under
`sources`, and `axon` under `untracked`. `scripts/check_thirdparty_drift.py`
(`run_checks`) iterates `manifest["sources"]` only and requires `track_drift`
plus `repo`.

So today Hermes is:

| Property | superpowers | axon | **hermes-agent** |
|---|---|---|---|
| License mirrored | ✅ | ✅ | ✅ |
| Listed in manifest | ✅ `sources` | ✅ `untracked` | ❌ **absent** |
| Version pinned | ✅ `6.1.1` | n/a (declared) | ✅ skill-fetch candidate: release + commit + tree + 71 digests; ❌ manifest/dependency |
| Drift tracked | ✅ | explicitly not | ❌ **never checked** |

The license mirror lists adapted files but records **no upstream commit or tag**,
so there is currently no way to tell whether the six adapted files still
correspond to anything upstream.

### Proposed manifest entry — NOT applied; generic policy guard in #824

E8.1a was documentation-only and did not modify the manifest. The E8.1d package
tracked by #824 adds the generic fail-closed policy required before enrolment,
without adding Hermes. The original repository-local hazard remains important
because it explains why an explicit policy is mandatory:

| Verified fact | Where |
|---|---|
| `is_vendored = str(entry.get("kind", "")).startswith("vendored")` — every entry whose `kind` does not start with `vendored` is treated as **doc-pinned** | `scripts/update_thirdparty.py` (`update_entry`) |
| `_bump_doc_version()` regex-replaces the old version token **throughout `update_doc`** on word boundaries | `scripts/update_thirdparty.py` (`_bump_doc_version`) |
| before #824, the scheduled workflow fanned a matrix over **every** `sources` entry whose drift was `DRIFT`, with no manual-only policy | `.github/workflows/thirdparty-autoupdate.yml` before #824 |
| its steps are drift detection → `update_thirdparty.py` → offline manifest consistency → PR creation. **No compatibility, security or E9 test runs.** | same |

**The hazard without the #824 guard.** If Hermes were added to `sources` with
`update_doc` pointing at this evidence map, a future upstream tag could rewrite every
occurrence of `v2026.8.3` in this document — while leaving the pinned commit
`3c27eb62…`, the PyPI facts, the interface inventory, the attestation evidence
and every conclusion untouched. The result would be a document that *claims* to
be verified at a tag it was never verified at: manufactured, internally
inconsistent "verified" evidence. That is worse than no automation.

**Retraction.** An earlier revision of this section claimed the existing
auto-update lane could manage Hermes and that the drift/update PR "triggers
compatibility tests". Both claims are **withdrawn**. The lane performs neither.

**Generic control supplied by #824:** every tracked source must declare a literal
JSON boolean `auto_update`; missing or malformed values fail before a network
lookup or write; `false` remains drift-visible but is rejected by both the
scheduler and direct updater. The two pre-existing sources declare `true`
explicitly. Focused hostile tests preserve a manual-only evidence document and
manifest byte-for-byte.

**Hermes manifest enrolment remains blocked.** Draft PR #834 for issue #830
supplies the compact pin and exact-revision/content-integrity boundary as a
review-pending candidate, but does not enrol it. Remaining gates are:

1. independent acceptance and merge of the exact PR #834 head;
2. the dual GitHub-tag and PyPI drift signal required by §1.2;
3. adapter-specific compatibility, supply-chain and E9 checks before pin movement;
4. a later, explicit manifest-enrolment package after those controls exist.

For reference only, the shape the entry would eventually take:

```jsonc
{
  "name": "hermes-agent",
  "repo": "NousResearch/hermes-agent",
  "kind": "adapted (not vendored verbatim) + runtime skill source",
  "path": "LICENSES/hermes-agent-MIT.txt",
  "pinned_version": "v2026.8.3",
  "license": "LICENSES/hermes-agent-MIT.txt",
  "track_drift": true,
  "auto_update": false        // drift visible; scheduled/direct mutation denied
}
```

**Operationally, under the corrected policy:**

| Question | Answer |
|---|---|
| What enters the manifest | nothing yet — enrolment is blocked (above) |
| Generic updater policy | mandatory explicit boolean; `false` is drift-only/manual-review and fails closed at both mutation sinks |
| Drift signal | GitHub tag feed **and** the PyPI release feed (§1.2), as a **proposed manual signal**, not an automated bump |
| What triggers a pin movement | adapter-specific compatibility, supply-chain and E9 checks — **none of which exist today** |
| How updates are reviewed | manually, and only after those checks exist |
| How the mutable runtime fetch is fixed | issue #830 candidate in draft PR #834: allowlisted exact-commit URL, raw-byte digest before decode/write, full source provenance; never fetch by tag or `main` |
| Native fallback | unchanged — Nerva executes natively when no provider is registered |

Only the generic manifest policy, updater guard and scheduler selection change in
#824. No Hermes-specific source, dependency, contract, adapter or promotion path
is added.

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
- **Optional extras** — 45 groups, listed in §5.1. Several pull heavyweight or
  network-bound stacks (`computer-use`, `vision`, `voice`, `daytona`, `modal`,
  `bedrock`, `vertex`). E8.1b must install **no extras by default**.
- **Not verified:** the transitive license closure. Only the direct dependency
  list was read. A full transitive license and CVE review is required E8.1b work
  and is not claimed here.

## 5. Concrete upstream interfaces — inventoried at `v2026.8.3/tools`

Module names below are **verbatim from the public directory listing at the pinned
tag** — `github.com/NousResearch/hermes-agent/tree/v2026.8.3/tools` — inspected
2026-08-04. The map binds the version it inventories.

**Drift note, recorded separately as required:** the same listing was also taken
at mutable `main`. At inspection time the two file sets were **identical** — no
file present at one and absent at the other. That is a point-in-time observation
about `main`, not compatibility evidence for the pin; the classifications below
rest on the tag alone.

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
upstream already integrates. **45** groups, verbatim, at the pinned tag:

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
| Upstream pin movement | draft PR #834 for issue #830 binds current bytes; a future pin change could accept different instructions | explicit reviewed pin update plus exact digest reproduction |
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
  Going forward the §3 pin fixes this for new imports, but it does not retroactively
  tell us what those six files were adapted from;
- **the transitive license closure and CVE posture** — only the direct dependency
  list was read (§4.1);
- **provider compatibility or adapter security** — draft PR #834 for issue #830
  tests the fetch-integrity boundary only; no provider contract, adapter or E9
  lane exists today;
- **the Sigstore attestations themselves** — their presence is recorded from the
  PyPI page (§1.2); no bundle was downloaded or cryptographically verified;
- **any performance, reliability, cost or privacy property** of Hermes. Nothing
  has been measured, and nothing is estimated. E9 must measure before promotion.

**Unblock statement — corrected.** An earlier revision of this document claimed
the pin required owner input. That was wrong: the upstream is public and the pin
was obtainable by ordinary read-only inspection, which §1.1 now records. No owner
decision and no credentials are needed for the pin. The next provider-contract
slice remains blocked until PR #834 is independently accepted and merged;
manifest enrolment and adapter promotion retain the additional gates in §4 and
§9.

## 9. Evidence E9 must produce before any adapter promotion

Per #804 and the accepted E9 contracts, before a shadow adapter may be promoted:

- a pinned Hermes version compared against the **native baseline** on quality,
  latency, cost, reliability and privacy, with unmeasured dimensions left
  `not_measured` rather than estimated;
- negative and failed runs retained and visible;
- cancellation, timeout, partial failure and rollback exercised;
- `ungoverned_actions == 0` across the adapter seam;
- a demonstrated native/no-provider rollback.

## 10. Exclusions honored by these slices

E8.1a added only this discovery document. E8.1d/#824 added only the generic
manifest policy, updater/workflow enforcement and focused tests. Draft PR #834 for issue #830
changes only the skill-fetch boundary, its tests, this document and the compact
pin. There is still no fork, vendored Hermes subsystem,
dependency, adapter code, provider contract, installation, upstream execution,
credential use, Hermes manifest entry or capability claim. Import remains an
existing explicit, guarded action; this package adds no approval, promotion or
execution authority.
The existing loader can discover the imported instruction file, which is why
operator review remains necessary even when every byte matches. Ultron remains
the sole privileged-action authority.

## Next coherent package

E8.1a was independently accepted in PR #819 and #824 supplied the generic
manual-only updater guard. After independent exact-head acceptance and merge of
PR #834, which implements issue #830, the next coherent slice is the
provider-neutral E8.1b (`nerva.execution-provider.v1`). It must keep
`grants_authority=false` immutable and cannot execute or promote Hermes.

Dual GitHub/PyPI drift, explicit manifest enrolment, a Hermes adapter and
adapter-specific compatibility/supply-chain/E9 gates remain separate, later
packages. A shadow adapter remains blocked on all of those controls.
