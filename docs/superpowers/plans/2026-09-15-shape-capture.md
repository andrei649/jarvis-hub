# Preserve complete streams after shape truncation

Plan recorded before implementation. Base: 61c657c2f4c629ebd0b022dc33bedf60522f1532.

H298 reassessment reproduced loss of recoverable stdout when a 2,001-character
line is shortened: the omission notice makes the preview longer than the original,
so the current byte comparison discards the complete captured stream.

1. Add actual code-tool regressions for stdout and stderr in one-shot and session
   execution. Assert the missing middle, complete persisted bytes, size and digest.
2. Preserve a complete capture when either shape truncation occurred or captured
   bytes exceed the returned preview. Keep the existing upstream byte-truncation
   behavior and discard captures whose output genuinely fits.
3. Run code-tool, session, output-limit and store tests after the localized change;
   obtain independent review before integrating with the effective-window repair.

Scope: code_tools.py, its tests and this plan. No sandbox authority, truncation
threshold, retention or cancellation-policy change. The existing tests use real
subprocesses with simulated isolation and do not prove container isolation.

Four actual tool regressions first failed with missing stdout/stderr file receipts
in both one-shot and session execution. After the repair, all 165 code-tool,
session-kernel, store and output-limit tests passed. The existing upstream
byte-truncation and small-output cleanup cases passed as well. Scoped Ruff passed.
Independent review and integrated effective-window verification remain pending.

## Integrated verification

Root integration on the scheduled-media baseline passed the full backend suite: 11,460 collected, 11,436 passed, 23 skipped, one expected failure, no unexpected failures (`/tmp/nerva-window-integrated-full.xml`, 271.290 seconds). Independent review passed 151 effective-window cases and 53 code-tool cases. The combined changes add 32 backend cases; frontend and native sources are unchanged by this unit. No live provider calls or production deployment. H298 reassessment covers both reviewed repairs and retains explicit unknown-capacity and filesystem limitations in its contract summary.
