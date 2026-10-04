# H487 native reusable-consent denial integration

Generated 2026-10-04. Goal: all697 Hermes capabilities, exact-card Telegram `/deny [reason]` dependency. Base/head before integration: `06812d4e36c8a5a6380b464e3a26503b80a25f4e`. Root is sole checkout writer.

## Scope and design

Integrate the reviewed three-path prototype (patch SHA-256 0ebb76d63cd37ea1f823474ef06ea8710118c181e27a2d1bc6f5cc4d3192799a): original direct reply to one delivered card supplies owner/chat/message identity; the private prompt supplies offer/source/turn/generation/deadline. Dispatch outside the occupied originating chat lane. Independent monotonic page arrival and current CAS-time deadline are both required. The existing worker/queue denial CAS is the only decision path. Text supplies only optional bounded reason metadata.

Owned paths: agents/core/channels/telegram.py, agents/core/autonomy/consent_prompts.py, tests/test_h487_telegram_consent_denial.py, this plan and its progress receipt. No accepted claim/proof/grant or queue/coordinator edits. Owner-once free-text denial remains the next dependency; no H487 equivalence credit or provider/live acceptance.

## Steps and verification

1. Rehash all owned baselines and patch, inspect source/test delta and independent review.
2. Add new tests alone; run actual occupied-lane regression in both mediation modes, expect behavior failure.
3. Apply two production deltas; run all56 new cases and the existing adjacent consent/reason/owner-once suites.
4. Ruff, baseline-aware Bandit, exact selected-index secret scan; record actual XML counts/hashes and separate local commit.
5. Reconcile shared claim-specific evidence, source citations/counts and architecture; run combined/full verification at a frozen milestone.

Rollback: reverse only this unit's scoped diff, retaining neighboring work. No push, merge, deploy, provider activation or real device/terminal effect. Next action: root test-only RED, then source GREEN.
