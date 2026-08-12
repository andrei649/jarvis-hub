---
status: superseded
instructional: false
superseded_by: .github/ai-development-policy.json
last_reviewed: 2026-08-10
---

# Archived OpenCode development methodology

This file is retained only to prevent older OpenCode sessions and links from failing closed into
invented instructions. It is **not an active plan** and must not be used as current repository
policy.

The former methodology contained stale assumptions about `master`, push-per-microtask behavior,
vendor-owned files, and local locks. Those rules are superseded by:

- [the canonical AI development policy](../../.github/ai-development-policy.json);
- [`AGENTS.md`](../../AGENTS.md), the concise contributor entrypoint;
- [`docs/AGENT_WORKFLOW.md`](../../docs/AGENT_WORKFLOW.md), the derived human guide;
- [`PARALLEL_WORKFLOW.md`](../../PARALLEL_WORKFLOW.md), the derived coordination playbook.

Run `python scripts/check_ai_workflow_policy.py` from the repository root before treating workflow
changes as valid. Historical content remains available in Git history.
