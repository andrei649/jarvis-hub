# LLM Price Table Verification — `agents/core/llm/cost_estimator.py`

**Verification date:** 2026-08-18 (table's own `PRICES_VERIFIED` stamp: 2026-08-17).
Every price below was checked against a **live fetch** of the providers' official pricing pages performed on 2026-08-18:

- Anthropic: https://platform.claude.com/docs/en/about-claude/pricing
- Gemini: https://ai.google.dev/gemini-api/docs/pricing
- OpenAI: https://developers.openai.com/api/docs/pricing

**Result: 55 cloud rows verified — 54 MATCH, 0 MISMATCH, 1 RETIRED_UNLISTED, 0 UNVERIFIABLE.**
The 7 local rows (`local`, `qwen3:7b`, `howard-lora-qwen-14b`, `deepseek-r1-distill-qwen-32b`, `google/gemma-4-31b-a4b`, `google/gemma-4-26b-a4b`, `google/gemma-4-12b`) are zero-priced and out of scope. The two symbolic keys were confirmed against `agents/core/llm/model_config.py`: `DEFAULT_CLAUDE_MODEL` → `claude-sonnet-4-6`, `RETIRED_CLAUDE_DEFAULT` → `claude-sonnet-4-20250514`. Prices are the standard/base per-1M-token rate; batch, cache, and >200k/>272k long-context tiers are ignored per the table's documented flat-price design.

## Anthropic (18 rows)

Source for all rows: https://platform.claude.com/docs/en/about-claude/pricing (retrieved 2026-08-18). The page lists model families without date suffixes; dated snapshot ids are priced at the family rate. Retired models are still listed there with prices, annotated "retired, except on Bedrock and Google Cloud" — so they verify as MATCH, not RETIRED_UNLISTED.

| Model | Table $in/$out | Official $in/$out | Verdict | Source | Retrieved | Notes |
|---|---|---|---|---|---|---|
| claude-fable-5 | 10.00 / 50.00 | 10.00 / 50.00 | MATCH | platform.claude.com/docs/en/about-claude/pricing | 2026-08-18 | "Claude Fable 5" row |
| claude-mythos-5 | 10.00 / 50.00 | 10.00 / 50.00 | MATCH | platform.claude.com/docs/en/about-claude/pricing | 2026-08-18 | Listed with a "limited availability" (Project Glasswing) note |
| claude-opus-5 | 5.00 / 25.00 | 5.00 / 25.00 | MATCH | platform.claude.com/docs/en/about-claude/pricing | 2026-08-18 | Fast-mode variant is $10/$50 — not modelled here (opt-in `speed:"fast"` only) |
| claude-opus-4-8 | 5.00 / 25.00 | 5.00 / 25.00 | MATCH | platform.claude.com/docs/en/about-claude/pricing | 2026-08-18 | |
| claude-opus-4-7 | 5.00 / 25.00 | 5.00 / 25.00 | MATCH | platform.claude.com/docs/en/about-claude/pricing | 2026-08-18 | |
| claude-opus-4-6 | 5.00 / 25.00 | 5.00 / 25.00 | MATCH | platform.claude.com/docs/en/about-claude/pricing | 2026-08-18 | |
| claude-opus-4-5 | 5.00 / 25.00 | 5.00 / 25.00 | MATCH | platform.claude.com/docs/en/about-claude/pricing | 2026-08-18 | |
| claude-opus-4-5-20251101 | 5.00 / 25.00 | 5.00 / 25.00 | MATCH | platform.claude.com/docs/en/about-claude/pricing | 2026-08-18 | Dated snapshot; page lists the "Claude Opus 4.5" family row |
| claude-opus-4-1-20250805 | 15.00 / 75.00 | 15.00 / 75.00 | MATCH | platform.claude.com/docs/en/about-claude/pricing | 2026-08-18 | Marked "retired, except on Bedrock and Google Cloud" but still priced on the official page; row kept to price historical runs |
| claude-opus-4-20250514 | 15.00 / 75.00 | 15.00 / 75.00 | MATCH | platform.claude.com/docs/en/about-claude/pricing | 2026-08-18 | Marked "retired, except on Google Cloud" but still priced on the official page; row kept to price historical runs |
| claude-sonnet-5 | 2.00 / 10.00 | 2.00 / 10.00 | MATCH | platform.claude.com/docs/en/about-claude/pricing | 2026-08-18 | Launch $2/$10 is now the standard price; the 2026-09-01 increase to $3/$15 "will not occur" (see Claims checked) |
| claude-sonnet-4-5 | 3.00 / 15.00 | 3.00 / 15.00 | MATCH | platform.claude.com/docs/en/about-claude/pricing | 2026-08-18 | |
| claude-sonnet-4-5-20250929 | 3.00 / 15.00 | 3.00 / 15.00 | MATCH | platform.claude.com/docs/en/about-claude/pricing | 2026-08-18 | Dated snapshot; page lists the "Claude Sonnet 4.5" family row |
| claude-haiku-4-5 | 1.00 / 5.00 | 1.00 / 5.00 | MATCH | platform.claude.com/docs/en/about-claude/pricing | 2026-08-18 | |
| claude-haiku-4-5-20251001 | 1.00 / 5.00 | 1.00 / 5.00 | MATCH | platform.claude.com/docs/en/about-claude/pricing | 2026-08-18 | Dated snapshot; page lists the "Claude Haiku 4.5" family row |
| claude-3-5-haiku-20241022 | 0.80 / 4.00 | 0.80 / 4.00 | MATCH | platform.claude.com/docs/en/about-claude/pricing | 2026-08-18 | Page lists "Claude Haiku 3.5 (retired, except on Bedrock and Google Cloud)"; row kept to price historical runs |
| claude-sonnet-4-6 | 3.00 / 15.00 | 3.00 / 15.00 | MATCH | platform.claude.com/docs/en/about-claude/pricing | 2026-08-18 | Keyed via `DEFAULT_CLAUDE_MODEL` (model_config.py) |
| claude-sonnet-4-20250514 | 3.00 / 15.00 | 3.00 / 15.00 | MATCH | platform.claude.com/docs/en/about-claude/pricing | 2026-08-18 | Keyed via `RETIRED_CLAUDE_DEFAULT`; page lists "Claude Sonnet 4 (retired, except on Bedrock and Google Cloud)"; row kept to price historical runs |

## Google Gemini (10 rows)

Source for all rows: https://ai.google.dev/gemini-api/docs/pricing (retrieved 2026-08-18). Paid-tier text rates; for tiered Pro models the ≤200k-token tier is used, per the file's documented convention.

| Model | Table $in/$out | Official $in/$out | Verdict | Source | Retrieved | Notes |
|---|---|---|---|---|---|---|
| gemini-3.7-flash | 0.75 / 3.75 | 0.75 / 3.75 | MATCH | ai.google.dev/gemini-api/docs/pricing | 2026-08-18 | Promo confirmed live: "$0.75/$3.75 through December 31, 2026. $1.50/$7.50 starting January 1, 2027" — table will need updating for 2027 |
| gemini-3.6-flash | 0.75 / 3.75 | 0.75 / 3.75 | MATCH | ai.google.dev/gemini-api/docs/pricing | 2026-08-18 | Same promo wording and end date (2026-12-31) as 3.7-flash |
| gemini-3.5-flash | 1.50 / 9.00 | 1.50 / 9.00 | MATCH | ai.google.dev/gemini-api/docs/pricing | 2026-08-18 | |
| gemini-3.5-flash-lite | 0.30 / 2.50 | 0.30 / 2.50 | MATCH | ai.google.dev/gemini-api/docs/pricing | 2026-08-18 | |
| gemini-3.1-pro-preview | 2.00 / 12.00 | 2.00 / 12.00 | MATCH | ai.google.dev/gemini-api/docs/pricing | 2026-08-18 | ≤200k-token tier; >200k is $4.00/$18.00 (flat table under-estimates long-context calls, as documented) |
| gemini-3.1-pro | 2.00 / 12.00 | — | RETIRED_UNLISTED | ai.google.dev/gemini-api/docs/pricing | 2026-08-18 | Checked the official Gemini API pricing page: only "Gemini 3.1 Pro Preview" exists; no stable "Gemini 3.1 Pro" id is published anywhere on it. Preview-rate proxy is intentional (id offered in settings picker); keep the row |
| gemini-3.1-flash-lite | 0.25 / 1.50 | 0.25 / 1.50 | MATCH | ai.google.dev/gemini-api/docs/pricing | 2026-08-18 | Text/image/video input $0.25; audio input $0.50 (not modelled) |
| gemini-2.5-pro | 1.25 / 10.00 | 1.25 / 10.00 | MATCH | ai.google.dev/gemini-api/docs/pricing | 2026-08-18 | ≤200k-token tier; >200k is $2.50/$15.00 |
| gemini-2.5-flash | 0.30 / 2.50 | 0.30 / 2.50 | MATCH | ai.google.dev/gemini-api/docs/pricing | 2026-08-18 | |
| gemini-2.5-flash-lite | 0.10 / 0.40 | 0.10 / 0.40 | MATCH | ai.google.dev/gemini-api/docs/pricing | 2026-08-18 | |

## OpenAI (27 rows)

Source for all rows: https://developers.openai.com/api/docs/pricing (retrieved 2026-08-18; fetched twice, second time with a neutral transcription prompt — both passes returned identical numbers). Standard tier, non-batch, non-cached. There is no separate legacy pricing page — legacy and dated-snapshot models (incl. `gpt-4o-2024-05-13`) are listed on this main page.

| Model | Table $in/$out | Official $in/$out | Verdict | Source | Retrieved | Notes |
|---|---|---|---|---|---|---|
| gpt-5.6-sol | 5.00 / 30.00 | 5.00 / 30.00 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | |
| gpt-5.6-terra | 2.00 / 12.00 | 2.00 / 12.00 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | |
| gpt-5.6-luna | 0.20 / 1.20 | 0.20 / 1.20 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | |
| gpt-5.5 | 5.00 / 30.00 | 5.00 / 30.00 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | Rate is for <272K-token context; longer context priced higher (not modelled) |
| gpt-5.5-pro | 30.00 / 180.00 | 30.00 / 180.00 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | <272K-context rate |
| gpt-5.4 | 2.50 / 15.00 | 2.50 / 15.00 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | <272K-context rate |
| gpt-5.4-mini | 0.75 / 4.50 | 0.75 / 4.50 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | |
| gpt-5.4-nano | 0.20 / 1.25 | 0.20 / 1.25 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | |
| gpt-5.4-pro | 30.00 / 180.00 | 30.00 / 180.00 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | <272K-context rate |
| gpt-5.3-codex | 1.75 / 14.00 | 1.75 / 14.00 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | Listed in the "Specialized models" section |
| gpt-5.2 | 1.75 / 14.00 | 1.75 / 14.00 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | |
| gpt-5.2-pro | 21.00 / 168.00 | 21.00 / 168.00 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | |
| gpt-5.1 | 1.25 / 10.00 | 1.25 / 10.00 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | |
| gpt-5 | 1.25 / 10.00 | 1.25 / 10.00 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | |
| gpt-5-mini | 0.25 / 2.00 | 0.25 / 2.00 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | |
| gpt-5-nano | 0.05 / 0.40 | 0.05 / 0.40 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | |
| gpt-5-pro | 15.00 / 120.00 | 15.00 / 120.00 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | |
| gpt-4.1 | 2.00 / 8.00 | 2.00 / 8.00 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | |
| gpt-4.1-mini | 0.40 / 1.60 | 0.40 / 1.60 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | |
| gpt-4.1-nano | 0.10 / 0.40 | 0.10 / 0.40 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | |
| gpt-4o | 2.50 / 10.00 | 2.50 / 10.00 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | |
| gpt-4o-2024-05-13 | 5.00 / 15.00 | 5.00 / 15.00 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | Dated snapshot still listed on the main pricing page (no separate legacy page exists); row kept to price historical runs |
| gpt-4o-mini | 0.15 / 0.60 | 0.15 / 0.60 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | |
| o3 | 2.00 / 8.00 | 2.00 / 8.00 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | |
| o3-pro | 20.00 / 80.00 | 20.00 / 80.00 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | |
| o3-mini | 1.10 / 4.40 | 1.10 / 4.40 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | |
| o4-mini | 1.10 / 4.40 | 1.10 / 4.40 | MATCH | developers.openai.com/api/docs/pricing | 2026-08-18 | |

## Proposed corrections

**None.** All 54 verifiable rows match the official pages exactly; the single non-match (`gemini-3.1-pro`) is an intentional, documented proxy row for an unpublished id and needs no change.

## Claims checked

**1. Sonnet 5 "$2/$10 became standard; 2026-09-01 increase cancelled" (comment at cost_estimator.py lines 39–41).** Confirmed verbatim on the live official page (2026-08-18): *"The $2/$10 per million input/output token pricing for Claude Sonnet 5, announced at launch as introductory pricing through August 31, 2026, is now the standard price. The previously scheduled increase to $3/$15 per million input/output tokens on September 1, 2026 will not occur."* The file's comment is accurate and the $2.00/$10.00 row is correct with no expiry. (Cross-check note: the repo-mandated `claude-api` skill was consulted first; its cached table — dated 2026-06-24 — still showed the pre-decision state of $3/$15 standard with a $2/$10 intro "through 2026-08-31", which the live page supersedes.)

**2. Gemini 3.7/3.6 Flash "promo to 2026-12-31" (lines 56–57).** Confirmed still in effect on the live page (2026-08-18) for both models, verbatim: input *"$0.75 through December 31, 2026. $1.50 starting January 1, 2027"*, output *"$3.75 through December 31, 2026. $7.50 starting January 1, 2027"*. The table's flat $0.75/$3.75 is correct today; on 2027-01-01 both rows double to $1.50/$7.50 — worth a calendar note for the next re-verification.

**3. `gemini-3.1-pro` "not a published id" (lines 61–64).** Confirmed: the official pricing page lists only *Gemini 3.1 Pro Preview* — every "3.1" entry was enumerated (Flash-Lite, Flash Live Preview, Flash Image, Flash Lite Image, Flash TTS Preview, Pro Preview) and no stable "Gemini 3.1 Pro" appears. The row's preview-rate proxy ($2.00/$12.00, ≤200k tier) remains the right intentional choice for the settings-picker id.
