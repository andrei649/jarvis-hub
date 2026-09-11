# External AI tooling shortlist — 7 proposals, 6 rejected

**Date:** 2026-09-11 · **Status:** decided (one item deferred to the owner)

A seven-item list of AI tools was proposed for adoption. Each was verified by
fetching it, then judged against what this repo already has. **Six rejected,
one owner decision.** Nothing was installed.

## Verdicts

| # | Proposal | Verdict | Why |
|---|----------|---------|-----|
| 1 | Graft — `graft.nanodevs.ai` | **reject** | Domain is **NXDOMAIN**; so is `nanodevs.ai`. Real publisher appears to be Nanonets. `graft init` writes SessionStart/UserPromptSubmit/PostToolUse/Stop hooks plus `mcpServers` into tracked `.claude/settings.json` — arbitrary execution inside the loop that authorises unattended merges. Landing page claims "no telemetry"; the tarball reportedly ships a PostHog client and an install-time phone-home. Its value pass sends source off-box, against local-first. |
| 2 | OpenMontage — `openmontage.video` | **reject** | **Already evaluated** on 2026-06-20 (`docs/research/2026-06-20-oss-adoption-perf-velocity.md:62`) and filed under "Low / no value for us". Re-proposed without clearing that finding. Nerva plans video (`creative/video_pipeline.py`) and deliberately leaves the encode/render seam owner-gated. |
| 3 | `codebase-memory-mcp` | **owner decision** | The one real repo. But a trial of this exact tool is **already scaffolded** — `.mcp.json.example`, `docs/dev/codebase-memory-mcp.md`, BACKLOG H22.8 — and unfinished. Its own doc sets the rule: *"if it doesn't earn its keep over `docs/AI_CONTEXT.md` bundles, drop the `.mcp.json` and close H22.8."* Finish or close that before opening a second trial of one idea. |
| 4 | Agency-agents — 232 agents | **reject** | Nerva already runs 21 tuned agents with authored souls. 232 generic personas are prompt content injected into a governed loop — surface, not capability. |
| 5–7 | "OSS agent tools", "Diagram Design", "Scientific Agent Skills" | **reject as listed** | All three point at **one identical URL**, `github.com/ValeriSabev`, which is a GitHub *user profile*, not a repository. Three distinct products behind one profile link means the list is a repost with broken links. Not evaluable as given. Scientific research skills are outside Nerva's mission besides. |

## What this list actually surfaced

Two findings that outlive the proposals:

1. **`.claude/settings.json` and `.claude/hooks/**` are not protected paths.**
   `selfdev-policy.json` has 16 `protected_paths`; none covers them. A change to
   a hook would not classify as control-plane, yet hooks execute on every prompt
   inside the lane that merges unattended. Fixing this needs the owner, because
   `selfdev-policy.json` is itself protected.

2. **H22.8 is an unresolved trial.** It has a written disposal rule and has not
   been applied. Finish the install or drop it.

## The rule going forward

`.claude/skills/evaluate-external-tool/` triggers on any adoption proposal:
check the record first, resolve the URL yourself, ask what Nerva already has,
and treat anything that writes to `.claude/` or `.mcp.json` as an owner
decision. Verdicts land here so they are not re-litigated — which is exactly
what happened to OpenMontage.
