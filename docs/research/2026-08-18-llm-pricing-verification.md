# LLM pricing verification — 2026-08-18

> Independent re-verification of `agents/core/llm/cost_estimator.py::MODELS`
> against each vendor's own live pricing page, one day after the table's own
> `PRICES_VERIFIED = "2026-08-17"` stamp (set by #920). Every figure below was
> fetched live — none answered from memory.

## Result

**No pricing changes needed.** All 55 vendor-priced rows in `MODELS` match the
vendors' official pricing pages exactly as retrieved today. `PRICES_VERIFIED`
is bumped to `2026-08-18` to record the re-check; no `MODELS` value changed.

`MODELS` holds 62 total entries; 7 are self-hosted/local models correctly
priced at `$0` (`local`, `qwen3:7b`, `howard-lora-qwen-14b`,
`deepseek-r1-distill-qwen-32b`, `google/gemma-4-31b-a4b`,
`google/gemma-4-26b-a4b`, `google/gemma-4-12b`) — no vendor pricing page
exists for them, so they're excluded from vendor verification. The 55
vendor-priced rows below are the complete set.

## Verified table

| Model ID (repo key) | Input $/M | Output $/M | Cached Input $/M | Source | Retrieved |
|---|---|---|---|---|---|
| claude-fable-5 | 10.00 | 50.00 | 1.00 | [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) | 2026-08-18 |
| claude-mythos-5 | 10.00 | 50.00 | 1.00 | Anthropic pricing | 2026-08-18 |
| claude-opus-5 | 5.00 | 25.00 | 0.50 | Anthropic pricing | 2026-08-18 |
| claude-opus-4-8 | 5.00 | 25.00 | 0.50 | Anthropic pricing | 2026-08-18 |
| claude-opus-4-7 | 5.00 | 25.00 | 0.50 | Anthropic pricing | 2026-08-18 |
| claude-opus-4-6 | 5.00 | 25.00 | 0.50 | Anthropic pricing | 2026-08-18 |
| claude-opus-4-5 | 5.00 | 25.00 | 0.50 | Anthropic pricing | 2026-08-18 |
| claude-opus-4-5-20251101 | 5.00 | 25.00 | 0.50 | Anthropic pricing | 2026-08-18 |
| claude-opus-4-1-20250805 *(retired; Bedrock/Vertex only)* | 15.00 | 75.00 | 1.50 | Anthropic pricing | 2026-08-18 |
| claude-opus-4-20250514 *(retired; Vertex only)* | 15.00 | 75.00 | 1.50 | Anthropic pricing | 2026-08-18 |
| claude-sonnet-5 | 2.00 | 10.00 | 0.20 | Anthropic pricing | 2026-08-18 |
| claude-sonnet-4-5 | 3.00 | 15.00 | 0.30 | Anthropic pricing | 2026-08-18 |
| claude-sonnet-4-5-20250929 | 3.00 | 15.00 | 0.30 | Anthropic pricing | 2026-08-18 |
| claude-haiku-4-5 | 1.00 | 5.00 | 0.10 | Anthropic pricing | 2026-08-18 |
| claude-haiku-4-5-20251001 | 1.00 | 5.00 | 0.10 | Anthropic pricing | 2026-08-18 |
| claude-3-5-haiku-20241022 *(retired, "Claude Haiku 3.5")* | 0.80 | 4.00 | 0.08 | Anthropic pricing | 2026-08-18 |
| claude-sonnet-4-6 *(via `DEFAULT_CLAUDE_MODEL`)* | 3.00 | 15.00 | 0.30 | Anthropic pricing | 2026-08-18 |
| claude-sonnet-4-20250514 *(via `RETIRED_CLAUDE_DEFAULT`, retired)* | 3.00 | 15.00 | 0.30 | Anthropic pricing | 2026-08-18 |
| gemini-3.7-flash *(promo through 2026-12-31)* | 0.75 | 3.75 | 0.075 | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) | 2026-08-18 |
| gemini-3.6-flash *(promo through 2026-12-31)* | 0.75 | 3.75 | 0.075 | Gemini pricing | 2026-08-18 |
| gemini-3.5-flash | 1.50 | 9.00 | 0.15 | Gemini pricing | 2026-08-18 |
| gemini-3.5-flash-lite | 0.30 | 2.50 | — | Gemini pricing | 2026-08-18 |
| gemini-3.1-pro-preview | 2.00 | 12.00 | 0.20 | Gemini pricing | 2026-08-18 |
| gemini-3.1-pro *(no standalone vendor id — priced at the preview rate; see note)* | 2.00 | 12.00 | — | n/a | 2026-08-18 |
| gemini-3.1-flash-lite | 0.25 | 1.50 | 0.025 | Gemini pricing | 2026-08-18 |
| gemini-2.5-pro | 1.25 | 10.00 | 0.125 | Gemini pricing | 2026-08-18 |
| gemini-2.5-flash | 0.30 | 2.50 | 0.03 | Gemini pricing | 2026-08-18 |
| gemini-2.5-flash-lite | 0.10 | 0.40 | 0.01 | Gemini pricing | 2026-08-18 |
| gpt-5.6-sol | 5.00 | 30.00 | 0.50 | [OpenAI pricing](https://developers.openai.com/api/docs/pricing) | 2026-08-18 |
| gpt-5.6-terra | 2.00 | 12.00 | 0.20 | OpenAI pricing | 2026-08-18 |
| gpt-5.6-luna | 0.20 | 1.20 | 0.02 | OpenAI pricing | 2026-08-18 |
| gpt-5.5 | 5.00 | 30.00 | 0.50 | OpenAI pricing | 2026-08-18 |
| gpt-5.5-pro | 30.00 | 180.00 | — | OpenAI pricing | 2026-08-18 |
| gpt-5.4 | 2.50 | 15.00 | 0.25 | OpenAI pricing | 2026-08-18 |
| gpt-5.4-mini | 0.75 | 4.50 | 0.075 | OpenAI pricing | 2026-08-18 |
| gpt-5.4-nano | 0.20 | 1.25 | 0.02 | OpenAI pricing | 2026-08-18 |
| gpt-5.4-pro | 30.00 | 180.00 | — | OpenAI pricing | 2026-08-18 |
| gpt-5.3-codex | 1.75 | 14.00 | 0.175 | OpenAI pricing | 2026-08-18 |
| gpt-5.2 | 1.75 | 14.00 | 0.175 | OpenAI pricing | 2026-08-18 |
| gpt-5.2-pro | 21.00 | 168.00 | — | OpenAI pricing | 2026-08-18 |
| gpt-5.1 | 1.25 | 10.00 | 0.125 | OpenAI pricing | 2026-08-18 |
| gpt-5 | 1.25 | 10.00 | 0.125 | OpenAI pricing | 2026-08-18 |
| gpt-5-mini | 0.25 | 2.00 | 0.025 | OpenAI pricing | 2026-08-18 |
| gpt-5-nano | 0.05 | 0.40 | 0.005 | OpenAI pricing | 2026-08-18 |
| gpt-5-pro | 15.00 | 120.00 | — | OpenAI pricing | 2026-08-18 |
| gpt-4.1 | 2.00 | 8.00 | 0.50 | OpenAI pricing | 2026-08-18 |
| gpt-4.1-mini | 0.40 | 1.60 | 0.10 | OpenAI pricing | 2026-08-18 |
| gpt-4.1-nano | 0.10 | 0.40 | 0.025 | OpenAI pricing | 2026-08-18 |
| gpt-4o | 2.50 | 10.00 | 1.25 | OpenAI pricing | 2026-08-18 |
| gpt-4o-2024-05-13 | 5.00 | 15.00 | — | OpenAI pricing | 2026-08-18 |
| gpt-4o-mini | 0.15 | 0.60 | 0.075 | OpenAI pricing | 2026-08-18 |
| o3 | 2.00 | 8.00 | 0.50 | OpenAI pricing | 2026-08-18 |
| o3-pro | 20.00 | 80.00 | — | OpenAI pricing | 2026-08-18 |
| o3-mini | 1.10 | 4.40 | 0.55 | OpenAI pricing | 2026-08-18 |
| o4-mini | 1.10 | 4.40 | 0.275 | OpenAI pricing | 2026-08-18 |

## Notes (not discrepancies)

- **`gemini-3.1-pro`** is not an id Google publishes standalone — only
  `gemini-3.1-pro-preview` appears on the pricing page. The repo already
  documents this and deliberately prices it at the preview rate because it's
  offered in the settings picker; this pass confirms that's still the only
  reasonable choice, not an error.
- **Cached-input pricing isn't tracked in the repo's schema** — `MODELS[model]`
  only has `input`/`output` keys. The `Cached Input $/M` column above is
  supplied for a future schema addition, not something currently reconciled
  against in-repo.
- Gemini 2.5 Pro and 3.1 Pro Preview's >200k-token tiered pricing (roughly 2x
  past the threshold) is not modelled by the flat table — already disclosed in
  the module docstring, not a new finding.
- No newly retired/renamed models turned up beyond what the repo's own
  comments already flag (Opus 4.1, Opus 4, Sonnet 4, Haiku 3.5 — all
  Bedrock/Vertex-only per Anthropic's page, matching existing retirement
  notes).

## Method

Verified live via WebFetch against each vendor's own pricing page on
2026-08-18: `platform.claude.com/docs/en/about-claude/pricing` (Anthropic),
`ai.google.dev/gemini-api/docs/pricing` (Gemini), and
`developers.openai.com/api/docs/pricing` (OpenAI). No figure was taken from
training-data memory.
