# H277 explicit OpenRouter vision checkpoint

Generated 2026-10-02. Goal: advance full parity with pinned Hermes
`59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e` without claiming an unfinished capability.
Base main: `9dbc0e2e518cc68d7aa54d919059133f4d4f3281` (merged PR1228).
Source commit: `b05195b6`; tested head: `cf02fe36c0d734a592471d856ad03712a52c7846`.
Branch: `codex/h277-provider-discovery-20261002`. These new commits are local.
The handoff itself is a subsequent documentation-only change.

## Delivered behavior

The actual composer supports an explicitly configured OpenRouter vision role,
required model and scoped key. Ambient credentials are usable only at the
canonical HTTPS origin. The live six-field provider routing block defaults to
data collection deny and is bound to the approved destination. Settings,
credentials and exact typed routing controls are checked again at the last HTTP
hook, including when empty-output recovery is disabled. Malformed settings,
duplicate JSON keys and boolean/number substitutions refuse before transport.

Data collection allow is disclosed as possible training and retains the separate
training acknowledgment requirement. Remote acknowledgment cannot clear that
requirement. Local-only image description, screen analysis and Telegram image
reading cannot become remote through this role. Inherited signed video refuses
OpenRouter until its dedicated signed adapter exists. No live settings were enabled.

Source paths: `agents/core/llm/vision_openrouter.py`, `model_roles.py`, `vlm.py`,
`vision_policy.py`, and `agents/core/routers/composer_vision.py`.
The two `tests/test_h277_openrouter_vision_*.py` files exercise resolution and the
real composer with synthetic HTTPX transports. Configuration, backlog, HUD/mobile
gaps and the three affected current Hermes assessments were updated. Previously
stale H139/H313/H504/H691 evidence was not indiscriminately refreshed.

## Verification

- Red-first composer tests: 14 failures before integration. A later disclosure
  regression failed before the data-collection policy correction.
- Integration union: 454 passed. Final adapter suite: 51 passed, including direct
  refusal by all three local-only consumers.
- Full frozen backend: 20,797 passed, 34 skipped, one expected failure, 64 warnings;
  20,832 collected. All 4,339 tracked regular files and HEAD remained unchanged.
- Documentation/status guards: 92 passed; full Ruff and diff checks passed.
- Strict index secret scan: 21 changed paths, zero findings before the full run.
- Independent Sol High read-only review found no concrete blocker. Its sole test
  coverage gap was closed by the three local-only consumer cases above.
- Frontend source is byte-identical to verified candidate
  `9cffba3d75aff21e9c63599736536eb92d338efc`: reuse its 1,847 passing tests,
  typecheck and build. No new frontend run or browser E2E execution is claimed.
- Graft graph was explicitly rebuilt and checked; its local cache is uncommitted.

The [verification receipt](evidence/h277-openrouter-vision-verification-2026-10-02.json)
records the frozen SHA, source fingerprint and artifact hashes. Temporary log and
XML paths are local evidence locations, not portable tracked artifacts.
No new mutation campaign or live provider calls were performed for this adapter.

## Remaining scope and next action

H277 remains partial; the accepted 697-row inventory still has 172 equivalent,
254 partial, 64 missing and207 requiring review, with zero excluded rows.
Explicit OpenRouter is a prerequisite, not automatic discovery. Nous profile
OAuth/tier/native adapters, DeepInfra vision catalog discovery, actual selected
main-context integration, SDK recovery and larger Gemini video lifecycle remain.

Next: define per-turn audited composer training/cost acknowledgments before using
the pinned free OpenRouter default in automatic selection. Preserve separate
remote disclosure, identity invalidation and strict-local consumers. Then implement
real opt-in discovery in the pinned order, with unavailable adapters reported
honestly, and extend signed video in its own rollback unit. Never copy rotating
Hermes credentials or enable paid routes as a side effect of discovery.

GitHub had zero open PRs at this checkpoint. Existing published work was already
merged; no publication, deployment or CI acceptance is claimed for this adapter.
Rollback: revert this branch's explicit-adapter source and accompanying records.
No persisted settings or credentials require migration.
