# Hermes HA-5c: name Ollama's exhausted thinking without streaming

- Goal: return the existing degraded `THINKING_EXHAUSTED_REPLY` when an Ollama
  non-stream generation ends at its length limit with separate reasoning but no
  visible answer or tool call.
- Non-goals: continuation/retry, inline `<think>` detection, changes to streaming,
  reasoning exposure, routing, timeouts, HTTP/HUD/mobile surfaces, or owner P26
  live-model evidence. The parent integration task owns BACKLOG/absorption updates.
- Design: retain each caller's current answer filtering and tool-call parsing.
  Inside its existing empty-answer/length branch, recognize native `thinking`
  and the already-supported streaming proxy alias `reasoning_content`. Return
  only the fixed degraded reply; clean stops still discard separate reasoning.
- Paths: `agents/core/llm/base.py`, `tests/test_cloud_tool_turns.py`, this plan.
- Tests: first reproduce both failures through real backend methods over
  `httpx.MockTransport`; cover native/proxy reasoning, no reasoning, visible
  output, normal stops, preserved tool calls, and no reasoning in replies/logs.
  Then run cloud tool turns, exhausted-thinking, thinking-leak, tool-protocol,
  backend degradation, warm-up, and agent-runtime suites; Ruff and diff checks.
- Rollback: revert this one behavior/test unit. No data/config migration.
- Dependencies: existing Ollama response parser, `strip_thinking`, and H23.12's
  degraded-reply contract. No package/model installation or external service.
- API contract checked 2026-09-09: native reasoning is top-level `thinking` for
  [generate](https://docs.ollama.com/api/generate) and `message.thinking` for
  [chat](https://docs.ollama.com/api/chat); `done_reason` is top-level on both.
- Base SHA: `c51f57df5f3fa60406a03155c88a2e618bbdb175`.
- Head SHA at design: `c51f57df5f3fa60406a03155c88a2e618bbdb175`.
- Branch: `codex/hermes-ollama-thinking`; lease: none.
- Changed paths at design: this plan only; implementation not started.
- Next action: add and run failing regression cases before implementation.
- Generated: 2026-09-09 11:31:05 UTC.

## Verification, 2026-09-09

Regression-first run: six intended failures (empty reply instead of named
degradation), twelve preservation cases passing. After the change, 228 tests
passed across cloud tool turns, exhausted thinking, thinking leaks, tool protocol,
backend degradation, warm-up and agent runtime. Ruff and `git diff --check` passed.

Live host proof used existing Ollama at `127.0.0.1:11434` and the already installed
`qwen3.5:0.8b`. No model was resident before the probe. Synthetic prompt:
`Calculate 17 multiplied by 23.`; `think=true`, `stream=false`, `num_predict=8`,
`num_ctx=2048`, `temperature=0`, `keep_alive=0`. Both native endpoints returned
`done_reason=length`, zero answer characters, 25 thinking characters and eight
generated tokens. The patched `generate` and `generate_tool_turn` methods both
returned exactly `THINKING_EXHAUSTED_REPLY`, classified as degraded; no tool calls
were produced. The probe preserved the real server response and only bounded
the request context/lifetime. Reasoning contents were not printed or committed.

This proves the native non-stream condition and adapter behavior, not P26's
raw streaming capture, all model families, or the full running hub. No private
data, cloud provider, model installation or external message was involved.
