"""cost_estimator.py — Token-based cost estimation for LLM calls.

Exact per-model list prices for every provider this hub can route to (Anthropic,
Google Gemini, OpenAI via OpenRouter / an OpenAI-compatible base URL) plus the local
models, which are free. All prices are USD per 1M tokens.

This table is looked up by **exact model id**; `agents/core/cost_tracker.py` holds the
coarse *family* table that the running meter uses. Keep the two in step — a test pins
each family row here to its newest member (`test_price_tables_do_not_drift`).

Prices re-verified 2026-08-18 against the providers' own pricing pages — all 55
vendor-priced rows confirmed unchanged from the 2026-08-17 pass; see
docs/research/2026-08-18-llm-pricing-verification.md for the row-by-row evidence:
  Anthropic  https://platform.claude.com/docs/en/about-claude/pricing
  Gemini     https://ai.google.dev/gemini-api/docs/pricing
  OpenAI     https://developers.openai.com/api/docs/pricing

Each row carries three rates: `input`, `output` and `cached` — the discounted rate the
vendor charges for a cache *read*, taken from the `Cached Input $/M` column of
docs/research/2026-08-18-llm-pricing-verification.md. `cached: None` means the vendor
publishes no cache-read rate for that model; those tokens are then billed at the FULL
input rate and the reported saving is 0.0. Cached reads are never free (DRA-24): before
this the estimator charged $0 for them and counted the whole input rate as a saving, so
the bill was under-reported and the saving over-reported on every cached token.

Two limits are deliberate. Prices are flat per model: Gemini's >200k-token tiers and
the promotional rates noted below are not modelled, so a long-context Gemini call is
under-estimated; and the eight rows with no published cache-read rate bill cache hits at
the full input rate, which over-states those calls rather than inventing a discount. And
retired models keep their rows — persisted run history references them by id, so deleting
one would silently unprice past runs rather than correct them.
"""

from .model_config import DEFAULT_CLAUDE_MODEL, RETIRED_CLAUDE_DEFAULT

PRICES_VERIFIED = "2026-08-18"

MODELS = {
    # ── Anthropic ────────────────────────────────────────────────────────────────
    "claude-fable-5":            {"input": 10.00, "output": 50.00, "cached": 1.0},
    "claude-mythos-5":           {"input": 10.00, "output": 50.00, "cached": 1.0},
    "claude-opus-5":             {"input": 5.00,  "output": 25.00, "cached": 0.5},
    "claude-opus-4-8":           {"input": 5.00,  "output": 25.00, "cached": 0.5},
    "claude-opus-4-7":           {"input": 5.00,  "output": 25.00, "cached": 0.5},
    "claude-opus-4-6":           {"input": 5.00,  "output": 25.00, "cached": 0.5},
    "claude-opus-4-5":           {"input": 5.00,  "output": 25.00, "cached": 0.5},
    "claude-opus-4-5-20251101":  {"input": 5.00,  "output": 25.00, "cached": 0.5},
    # Retired 2026-08-05 / 2026-06-15; priced so historical runs stay answerable.
    "claude-opus-4-1-20250805":  {"input": 15.00, "output": 75.00, "cached": 1.5},
    "claude-opus-4-20250514":    {"input": 15.00, "output": 75.00, "cached": 1.5},
    # Sonnet 5's $2/$10 launch rate became the standard price — the increase to $3/$15
    # scheduled for 2026-09-01 was cancelled.
    "claude-sonnet-5":           {"input": 2.00,  "output": 10.00, "cached": 0.2},
    "claude-sonnet-4-5":         {"input": 3.00,  "output": 15.00, "cached": 0.3},
    "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00, "cached": 0.3},
    "claude-haiku-4-5":          {"input": 1.00,  "output": 5.00, "cached": 0.1},
    "claude-haiku-4-5-20251001": {"input": 1.00,  "output": 5.00, "cached": 0.1},
    "claude-3-5-haiku-20241022": {"input": 0.80,  "output": 4.00, "cached": 0.08},   # retired 2026-02-19
    # `claude-sonnet-4-6` and the retired `claude-sonnet-4-20250514`, via model_config so
    # the operational default is single-sourced. Do not also add them as literals — a
    # duplicate key would silently win here.
    DEFAULT_CLAUDE_MODEL:        {"input": 3.00,  "output": 15.00, "cached": 0.3},
    RETIRED_CLAUDE_DEFAULT:      {"input": 3.00,  "output": 15.00, "cached": 0.3},

    # ── Google Gemini ────────────────────────────────────────────────────────────
    # Pro tiers and 3.1-pro-preview are the ≤200k-token rate; above 200k Google charges
    # roughly double, which this flat table does not express.
    "gemini-3.7-flash":          {"input": 0.75,  "output": 3.75, "cached": 0.075},   # promo to 2026-12-31
    "gemini-3.6-flash":          {"input": 0.75,  "output": 3.75, "cached": 0.075},   # promo to 2026-12-31
    "gemini-3.5-flash":          {"input": 1.50,  "output": 9.00, "cached": 0.15},
    "gemini-3.5-flash-lite":     {"input": 0.30,  "output": 2.50, "cached": None},
    "gemini-3.1-pro-preview":    {"input": 2.00,  "output": 12.00, "cached": 0.2},
    # `gemini-3.1-pro` is not a published id, but it is offered in the settings picker
    # (`settings_db.py` → `gemini_model` opts), so it is priced at the preview rate
    # rather than left to read $0.00.
    "gemini-3.1-pro":            {"input": 2.00,  "output": 12.00, "cached": None},
    "gemini-3.1-flash-lite":     {"input": 0.25,  "output": 1.50, "cached": 0.025},
    "gemini-2.5-pro":            {"input": 1.25,  "output": 10.00, "cached": 0.125},
    "gemini-2.5-flash":          {"input": 0.30,  "output": 2.50, "cached": 0.03},
    "gemini-2.5-flash-lite":     {"input": 0.10,  "output": 0.40, "cached": 0.01},

    # ── OpenAI (reachable via OpenRouter / an OpenAI-compatible base URL) ─────────
    "gpt-5.6-sol":               {"input": 5.00,  "output": 30.00, "cached": 0.5},
    "gpt-5.6-terra":             {"input": 2.00,  "output": 12.00, "cached": 0.2},
    "gpt-5.6-luna":              {"input": 0.20,  "output": 1.20, "cached": 0.02},
    "gpt-5.5":                   {"input": 5.00,  "output": 30.00, "cached": 0.5},
    "gpt-5.5-pro":               {"input": 30.00, "output": 180.00, "cached": None},
    "gpt-5.4":                   {"input": 2.50,  "output": 15.00, "cached": 0.25},
    "gpt-5.4-mini":              {"input": 0.75,  "output": 4.50, "cached": 0.075},
    "gpt-5.4-nano":              {"input": 0.20,  "output": 1.25, "cached": 0.02},
    "gpt-5.4-pro":               {"input": 30.00, "output": 180.00, "cached": None},
    "gpt-5.3-codex":             {"input": 1.75,  "output": 14.00, "cached": 0.175},
    "gpt-5.2":                   {"input": 1.75,  "output": 14.00, "cached": 0.175},
    "gpt-5.2-pro":               {"input": 21.00, "output": 168.00, "cached": None},
    "gpt-5.1":                   {"input": 1.25,  "output": 10.00, "cached": 0.125},
    "gpt-5":                     {"input": 1.25,  "output": 10.00, "cached": 0.125},
    "gpt-5-mini":                {"input": 0.25,  "output": 2.00, "cached": 0.025},
    "gpt-5-nano":                {"input": 0.05,  "output": 0.40, "cached": 0.005},
    "gpt-5-pro":                 {"input": 15.00, "output": 120.00, "cached": None},
    "gpt-4.1":                   {"input": 2.00,  "output": 8.00, "cached": 0.5},
    "gpt-4.1-mini":              {"input": 0.40,  "output": 1.60, "cached": 0.1},
    "gpt-4.1-nano":              {"input": 0.10,  "output": 0.40, "cached": 0.025},
    "gpt-4o":                    {"input": 2.50,  "output": 10.00, "cached": 1.25},
    "gpt-4o-2024-05-13":         {"input": 5.00,  "output": 15.00, "cached": None},
    "gpt-4o-mini":               {"input": 0.15,  "output": 0.60, "cached": 0.075},
    "o3":                        {"input": 2.00,  "output": 8.00, "cached": 0.5},
    "o3-pro":                    {"input": 20.00, "output": 80.00, "cached": None},
    "o3-mini":                   {"input": 1.10,  "output": 4.40, "cached": 0.55},
    "o4-mini":                   {"input": 1.10,  "output": 4.40, "cached": 0.275},

    # ── Local (LM Studio / Ollama) — no metered cost ──────────────────────────────
    "local":                       {"input": 0, "output": 0, "cached": 0},
    "qwen3:7b":                    {"input": 0, "output": 0, "cached": 0},
    "howard-lora-qwen-14b":        {"input": 0, "output": 0, "cached": 0},
    "deepseek-r1-distill-qwen-32b": {"input": 0, "output": 0, "cached": 0},
    "google/gemma-4-31b-a4b":      {"input": 0, "output": 0, "cached": 0},
    "google/gemma-4-26b-a4b":      {"input": 0, "output": 0, "cached": 0},
    "google/gemma-4-12b":          {"input": 0, "output": 0, "cached": 0},
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> dict:
    """Estimate cost for a single LLM call.

    Returns dict with input_cost, output_cost, total, cached_input, savings.
    Raises ValueError on negative token counts. An unknown model returns zero cost with
    ``priced: False`` — a caller that renders a currency figure must check that flag, or
    it reports $0.00 for a model nobody has priced (ADV-078).
    """
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError(f"Negative token counts not allowed: input={input_tokens}, output={output_tokens}")
    # ADV-078: "this model is free" and "nobody priced this model" are different answers,
    # and returning 0.0 for both let dashboards render a confident $0.00 over a model
    # whose real cost is simply unknown. `total` stays numeric so existing arithmetic
    # keeps working; `priced` is what a surface must consult before printing a figure.
    pricing = MODELS.get(model)
    if pricing is None:
        return {"input_cost": 0.0, "output_cost": 0.0, "total": 0.0,
                "cached_input": cached_tokens, "savings": 0.0,
                "priced": False, "model": model}
    if pricing["input"] == 0:
        return {"input_cost": 0.0, "output_cost": 0.0, "total": 0.0,
                "cached_input": cached_tokens, "savings": 0.0,
                "priced": True, "model": model}
    # DRA-24: a cache READ is discounted, not free. `cached: None` means the vendor
    # publishes no cache-read rate for this model — bill those tokens at the full input
    # rate and report no saving, rather than invent a discount nobody quoted.
    cached_rate = pricing.get("cached")
    if cached_rate is None:
        cached_rate = pricing["input"]
    # Clamp keeps the two components summing to exactly `input_tokens`: a caller that
    # over-reports cached_tokens cannot bill negative input or claim a saving on tokens
    # that were never sent.
    billable_cached = min(cached_tokens, input_tokens)
    non_cached_input = input_tokens - billable_cached
    input_cost = (non_cached_input * pricing["input"] + billable_cached * cached_rate) / 1_000_000
    output_cost = output_tokens / 1_000_000 * pricing["output"]
    savings = billable_cached * (pricing["input"] - cached_rate) / 1_000_000
    return {
        "input_cost": round(input_cost, 10),
        "output_cost": round(output_cost, 10),
        "total": round(input_cost + output_cost, 10),
        "cached_input": cached_tokens,
        "savings": round(savings, 10),
        "priced": True,
        "model": model,
    }


def estimate_monthly(records: list[dict]) -> dict:
    """Aggregate cost across multiple interaction records.

    Each record has: model, input_tokens, output_tokens, cached_tokens.
    Returns per-model breakdown and totals.
    """
    total = 0.0
    total_savings = 0.0
    per_model = {}
    for r in records:
        model = r.get("model", "unknown")
        cost = estimate_cost(
            model=model,
            input_tokens=r.get("input_tokens", 0),
            output_tokens=r.get("output_tokens", 0),
            cached_tokens=r.get("cached_tokens", 0),
        )
        total += cost["total"]
        total_savings += cost["savings"]
        if model not in per_model:
            per_model[model] = {"calls": 0, "total": 0.0, "savings": 0.0}
        per_model[model]["calls"] += 1
        per_model[model]["total"] = round(per_model[model]["total"] + cost["total"], 10)
        per_model[model]["savings"] = round(per_model[model]["savings"] + cost["savings"], 10)
    return {
        "total": round(total, 10),
        "total_savings": round(total_savings, 10),
        "total_interactions": len(records),
        "per_model": per_model,
    }
