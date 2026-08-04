# Nerva E8.1a — Hermes upstream discovery and compatibility map

Status: read-only discovery evidence for #804 / #766. This document contains no
provider contract, no adapter, no dependency and no capability claim. It does not
assert that any Hermes interface has been tested against Nerva.

## Scope and method

E8.1a is documentation-only. Nothing here was installed, executed, cloned or
copied. Every claim below is either:

- **verified in this repository** — with the exact file and line it comes from; or
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
  "pinned_version": "<upstream tag or commit — must be verified by the owner>",
  "license": "LICENSES/hermes-agent-MIT.txt",
  "track_drift": true,
  "update_doc": "docs/nerva2/EXECUTION_PROVIDER_E8_1A.md"
}
```

`pinned_version` is left as a placeholder **on purpose**. Inventing a version
here would be exactly the fabricated evidence the program forbids.

## 5. Compatibility map — classification

Classifications are about the **execution-provider boundary**, and each is a
proposal for review, not a tested result.

| Surface | Class | Rationale |
|---|---|---|
| Terminal / sandbox execution | `thin_adapter` | Nerva already owns a sandbox and Action Kernel; a provider may execute inside declared bounds only, never authorize. |
| Browser / computer use | `thin_adapter` | Highest-value reuse per the strategy docs; also the highest risk, so it must sit behind Ultron and Verification. |
| Skills / `SKILL.md` convention | `reuse` (already) | Already implemented natively in `skills/importer.py`, `loader.py`. Needs pinning, not an adapter. |
| Delegation / subagents | `native_fallback` | `agents/core/subagents.py` already carries the adapted blocked-tool policy; re-importing would duplicate policy across the boundary. |
| Scheduling / gateways | `thin_adapter` | `channels/session.py` is a Hermes-style session layer already; a provider may supply the runtime, not the session authority. |
| Execution trajectories / evidence | `thin_adapter` | Must map onto `nerva.benchmark.v1` and Verification Fabric evidence; the provider returns evidence, never a completion claim. |
| Memory / user model | `reject` | Nerva's Atlas and Episodes are canonical. A provider memory model must never become Nerva truth. |
| Planning / cognition | `reject` | Cortex owns decisions. Importing provider cognition is the architecture drift the strategy forbids. |
| Authorization / approval | `reject` | Ultron / `nerva.action.v1` is the sole privileged-action authority. |
| Identity | `reject` | Provider identity must not merge with Nerva or Howard identity. |

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

- **the current upstream release/version scheme** — no tag, branch policy or
  release cadence was fetched or confirmed;
- **the current upstream API surface** for terminal, browser, gateway or
  trajectory interfaces — the interface names in §5 are role descriptions from
  the existing research docs, *not* verified upstream module signatures;
- **whether the six adapted files still match upstream** — no upstream commit is
  recorded anywhere in this repository, so drift is unmeasurable today;
- **upstream dependency tree, transitive licenses and supply-chain posture**;
- **any performance, reliability, cost or privacy property** of Hermes. Nothing
  has been measured. E9 must measure before any promotion.

Consequence: **E8.1b cannot begin with a pinned version until the owner or a
follow-up discovery slice records an exact upstream commit or tag.** That is the
single hard blocker this discovery surfaces.

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

E8.1b (`nerva.execution-provider.v1`) remains blocked until an exact upstream
commit or tag is recorded. The smallest unblocking movements, in order:

1. Owner or a bounded follow-up records the exact upstream pin.
2. Add the §4 manifest entry so drift is tracked like every other third-party source.
3. Only then define the provider contract, with `grants_authority=false` immutable.
