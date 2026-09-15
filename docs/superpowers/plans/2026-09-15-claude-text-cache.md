# Claude text and streaming cache breakpoints

Goal: request the existing ephemeral system-prefix cache on ordinary Claude text and streaming calls, as tool turns already do.
Base: d3caec901103217b667d1fd745b167de5ce590ca. Generated: 2026-09-15. Head: delivery commit containing this plan. Next: independent review and parent integration.

Scope: agents/core/llm/anthropic.py, tests/test_claude_text_cache.py and this plan. Reuse cache_marked_system only for nonempty system strings. Preserve empty string serialization, exact text, messages, headers/version, TTL, auth retry policy, reasoning/sampling shaping and usage pricing. No SDK, dependency, provider, live call, global metadata or assets. H363 remains partial for the explicitly named Responses path; H364 invocation-only reasoning is separate.

- [x] RED text/stream mocked HTTP request bodies currently lack cache_control.
- [x] Reuse existing nonempty system helper in the two builders.
- [x] Verify stable bodies across existing text auth retry, empty systems, reasoning/refusal and sampling, streaming callbacks, cache read/write accounting, errors/incomplete streams.
- [x] Run focused provider/auth/reasoning/usage guards, whole Ruff, baseline Bandit1.9.4, scoped Graft freshness; commit for independent review.

Rollback: revert the two payload expressions and associated tests/plan. No live cache-hit percentage or actual bill is claimed. Tests retain normal socket/timeout guards and use injected MockTransport only.

## Verification evidence

The two actual text/stream HTTP-body cases failed before implementation because system remained a string (/tmp/nerva-claude-cache-red.log), then passed with the existing helper. The production diff is exactly two payload expressions. New tests add12 cases;318 focused cases pass with no skips/failures/errors in /tmp/nerva-claude-cache-focused.xml and .log.

Guarded command: TMPDIR=/private/tmp /usr/bin/python3 /tmp/nerva-run-isolated.py /Users/andrei649/Projects/nerva-worktrees/claude-text-cache /usr/bin/env TMPDIR=/private/tmp NERVA_PUBLIC_PROFILE=0 /Users/andrei649/Projects/nerva-hub/.venv/bin/python3.12 -m pytest -q tests/test_claude_text_cache.py tests/test_cloud_tool_turns.py tests/test_h12_20_auth_rotation.py tests/test_cloud_token_usage.py tests/test_stream_token_usage.py tests/test_reasoning_effort_ladder.py tests/test_reasoning_no_escalation.py tests/test_reasoning_empty_contract.py --junitxml=/tmp/nerva-claude-cache-focused.xml.

Whole Ruff and baseline Bandit1.9.4 pass (/tmp/nerva-claude-cache-ruff.log and -bandit.log). Scoped Graft wiring indexes only anthropic.py/tool_dialects.py; check is fresh (/tmp/nerva-claude-cache-graft.log), no semantic calls/hooks. Full backend, live provider/cache hits, billing, frontend and global status were deliberately not rerun or changed in this source unit.

## Integrated validation

Reviewed source rebased onto residency at16f229ceba3a9a6c2c0226942d0767a9967a79c4. Full guarded backend collected11,636:11,612 passed,23 skipped,one expected failure,zero unexpected failures in256.50 seconds. /tmp/nerva-claude-cache-full.log and .xml; backend count verification passes at /tmp/nerva-claude-cache-count.log. Existing58 warnings include socket-blocked Telegram test attempts and deprecations; no socket/addopts/timeout guard was disabled.81 metadata tests and whole Ruff/baselineBandit1.9.4 pass after rebase; scoped Graft remains fresh.

Full command: PATH=/tmp/nerva-fish-runtime/fish/4.9.3/bin:/Users/andrei649/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin TMPDIR=/private/tmp /usr/bin/python3 /tmp/nerva-run-isolated.py /Users/andrei649/Projects/nerva-worktrees/claude-text-cache /usr/bin/env TMPDIR=/private/tmp NERVA_PUBLIC_PROFILE=0 /Users/andrei649/Projects/nerva-hub/.venv/bin/python3.12 -m pytest --junitxml=/tmp/nerva-claude-cache-full.xml. Node resolves through the retained .local/bin runtime; fish4.9.3 is task-local. Frontend1326/mobile140/routes501 remain tracked, not rerun here. Hermes121 equivalent/327 partial/94 missing/107 excluded/48 review unchanged. H363/H364 remain partial with explicit source-backed remaining requirements.
