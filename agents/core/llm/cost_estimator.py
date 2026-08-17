"""cost_estimator.py — Token-based cost estimation for LLM calls.
Supports Gemini, Claude, and local models. All prices per 1M tokens in USD.
"""

from .model_config import DEFAULT_CLAUDE_MODEL, RETIRED_CLAUDE_DEFAULT

MODELS = {
    "gemini-2.5-flash":    {"input": 0.15,  "output": 0.60},
    "gemini-2.5-pro":      {"input": 2.00,  "output": 10.00},
    "gemini-3.1-pro":      {"input": 2.00,  "output": 12.00},
    "gemini-3.5-flash":    {"input": 1.50,  "output": 9.00},
    "gemini-3-flash":      {"input": 0.50,  "output": 3.00},
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50},
    # Anthropic list prices per 1M tokens, verified 2026-08-17. Current generation is
    # listed explicitly so a run on any of these is priced instead of falling through to
    # `priced: False`. The 4.x entries stay: those models are still served, and persisted
    # history references them by id, so removing a row would silently unprice past runs.
    "claude-fable-5":          {"input": 10.00, "output": 50.00},
    "claude-opus-5":           {"input": 5.00, "output": 25.00},
    "claude-opus-4-8":         {"input": 5.00, "output": 25.00},
    "claude-sonnet-5":         {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5":        {"input": 1.00, "output": 5.00},
    DEFAULT_CLAUDE_MODEL:      {"input": 3.00, "output": 15.00},
    RETIRED_CLAUDE_DEFAULT:    {"input": 3.00, "output": 15.00},
    "local":               {"input": 0,     "output": 0},
    "qwen3:7b":            {"input": 0,     "output": 0},
    "google/gemma-4-31b-a4b": {"input": 0, "output": 0},
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
    non_cached_input = max(0, input_tokens - cached_tokens)
    input_cost = non_cached_input / 1_000_000 * pricing["input"]
    output_cost = output_tokens / 1_000_000 * pricing["output"]
    savings = cached_tokens / 1_000_000 * pricing["input"]
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
