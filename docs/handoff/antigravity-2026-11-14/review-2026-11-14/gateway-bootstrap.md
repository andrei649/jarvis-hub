# PR review: #1359 and #1360

Base inspected: `1338833d5a344d277c43828a9d9314e10af792f1`.
Heads inspected: #1359 `686fcbf4f25ebfbb416b3a35dff29045163cffbd`; #1360 `d97f48c7f2a7fad7181f0bdfcd4ecdc6c69c6ff6`.
Read-only source review using git show/diff; no checkout, publication, merge, service, dependency install, or previously blocked update/restart adversarial check was attempted. CI green at these heads is supplied by the coordinator, not independently queried here.

## Finding

**P2 — #1359: preserve literal script output at the adapter gate.**
`agents/core/channels/base.py:29` unconditionally returns True without calling the transport when the message is `[SILENT]`. The new `__init_subclass__` wrapper applies this to every production adapter. A no-agent script that prints exactly this token therefore produces no notification, although `JobRunner._send` reports `delivered to <channel>` and delivery tracking records success. This violates the existing no-agent literal-output contract (`tests/test_job_gates.py:109`) and is introduced relative to the inspected main, which has no such adapter wrapper. The final commit removes the duplicate job-level check but leaves this adapter-level check. `tests/test_h069_outbound_safety.py:279` exercises a plain fake rather than a ChannelAdapter subclass, so its delivery assertion bypasses the new gate. Preserve source/context through delivery or handle silence only where agent provenance is known, and cover a real/wrapped adapter in the regression test.

Evidence: a lightweight in-memory execution of the unchanged source `_outbound_safe` wrapper and exact source `is_silence` function returned `True` with zero underlying-send calls for `[SILENT]`. No network or transport ran.

## Recommendations

- **#1359: hold pending the P2 correction.** Inspected the changed outbound-safety implementation and integration, service installation/refusal handling, channel policy, command parsing, and associated tests. No additional concrete blocker identified in this pass. This is not a full security audit or native service-manager validation.
- **#1360: merge acceptable.** No concrete blocker found in the scoped lock-selection and smoke-success changes. Default dependencies remain hash-required; missing or non-file locks no longer silently select loose requirements; explicit `--unlocked` remains available; smoke success now requires boolean true. Tests cover the changed failure modes and documentation accurately distinguishes unreadable-file pip failure. Existing JSON-object parser assumptions are unchanged and are not a new regression. No local suite rerun was necessary for this static review; exact-head CI verification remains the coordinator's responsibility.
