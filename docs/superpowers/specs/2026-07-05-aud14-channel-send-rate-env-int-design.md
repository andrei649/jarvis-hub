# AUD-14 Channel Send-Rate Env-Int Design

## Goal

Move the global outbound channel send-rate cap (`JARVIS_CHANNEL_SEND_RATE`) onto the shared `env_config.env_int()` parser so malformed or negative numeric env input cannot crash or silently drift from the AUD-14 convention.

## Non-Goals

- Do not redesign per-channel override syntax in `JARVIS_CHANNEL_SEND_RATES`.
- Do not change the default behavior: unset, zero, malformed, or negative global cap still means unlimited.
- Do not broaden this PR into a repo-wide env sweep.
- Do not change the interactive telegram/web/voice reply path.

## Current Seam

`agents/core/channels/send_rate_limit.py` already treats the limiter as default-off and live-tunable, but it still reads the global cap with direct `int(os.environ.get(...))` in two places. One path catches `ValueError`; the other repeats the parse for `configured_rates()`. Both bypass `env_config.env_int()`, which is now the shared AUD-14 integer env convention.

## Approach

Add a small module helper, `_global_cap()`, that returns `env_int("JARVIS_CHANNEL_SEND_RATE", 0, minimum=0)`. Use that helper in both `limit_for()` and `configured_rates()`.

The helper keeps the behavior aligned:

- unset or blank -> `0` (unlimited);
- malformed -> `0` (unlimited);
- negative -> `0` (unlimited);
- positive int -> that cap.

Per-channel overrides continue to win over the global cap and keep their existing parser.

## Verification

- Red/green tests in `tests/test_channel_send_rate_limit.py` for malformed and negative `JARVIS_CHANNEL_SEND_RATE`.
- Focused send-rate suite.
- AUD-14 env-config ratchet suite.
- Touched-file ruff and py_compile.
- `STATUS.md` sync check and diff whitespace check.
