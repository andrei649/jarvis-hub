"""Token cost tracker — accumulates usage per agent, estimates USD cost."""
import threading
from collections import defaultdict

# Price per 1M tokens (input/output) — update as needed
MODEL_PRICES = {
    "default":         {"input": 3.00,  "output": 15.00},
    "claude-haiku":    {"input": 0.25,  "output": 1.25},
    "claude-sonnet":   {"input": 3.00,  "output": 15.00},
    "claude-opus":     {"input": 15.00, "output": 75.00},
    "gpt-4o":          {"input": 5.00,  "output": 15.00},
    "gpt-4o-mini":     {"input": 0.15,  "output": 0.60},
    "gemini-pro":      {"input": 1.25,  "output": 5.00},
    "local":           {"input": 0.00,  "output": 0.00},
}

_lock = threading.Lock()
_usage: dict[str, dict] = defaultdict(lambda: {"input_tokens": 0, "output_tokens": 0, "calls": 0, "model": "default"})


def record(agent_name: str, input_tokens: int, output_tokens: int, model: str = "default"):
    """Record token usage for an agent."""
    with _lock:
        entry = _usage[agent_name]
        entry["input_tokens"] += input_tokens
        entry["output_tokens"] += output_tokens
        entry["calls"] += 1
        entry["model"] = model


def get_summary() -> dict:
    """Return per-agent usage + cost estimates."""
    with _lock:
        result = {}
        total_cost = 0.0
        for agent, data in _usage.items():
            key = data["model"].lower()
            price = MODEL_PRICES.get(key) or MODEL_PRICES.get(
                next((k for k in MODEL_PRICES if k in key), "default"),
                MODEL_PRICES["default"]
            )
            input_cost = data["input_tokens"] / 1_000_000 * price["input"]
            output_cost = data["output_tokens"] / 1_000_000 * price["output"]
            cost = round(input_cost + output_cost, 6)
            total_cost += cost
            result[agent] = {**data, "cost_usd": cost}
        return {"agents": result, "total_cost_usd": round(total_cost, 6)}


def apm_summary() -> dict:
    """H10.16 — org-wide APM rollup: totals + per-agent + per-model breakdown.

    Built on get_summary() (per-agent tokens + $). Adds organization totals and
    a per-model aggregation for the Admin APM dashboard.
    """
    summary = get_summary()
    agents = summary["agents"]

    totals = {"runs": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    by_model: dict[str, dict] = {}
    by_agent = []

    for agent, data in agents.items():
        runs = data.get("calls", 0)
        in_tok = data.get("input_tokens", 0)
        out_tok = data.get("output_tokens", 0)
        cost = data.get("cost_usd", 0.0)
        model = data.get("model", "default")

        totals["runs"] += runs
        totals["input_tokens"] += in_tok
        totals["output_tokens"] += out_tok
        totals["cost_usd"] = round(totals["cost_usd"] + cost, 6)

        by_agent.append({
            "agent": agent, "model": model, "runs": runs,
            "input_tokens": in_tok, "output_tokens": out_tok, "cost_usd": cost,
        })

        m = by_model.setdefault(
            model, {"model": model, "runs": 0, "input_tokens": 0,
                    "output_tokens": 0, "cost_usd": 0.0},
        )
        m["runs"] += runs
        m["input_tokens"] += in_tok
        m["output_tokens"] += out_tok
        m["cost_usd"] = round(m["cost_usd"] + cost, 6)

    by_agent.sort(key=lambda r: r["cost_usd"], reverse=True)
    by_model_list = sorted(by_model.values(), key=lambda r: r["cost_usd"], reverse=True)
    return {"totals": totals, "by_agent": by_agent, "by_model": by_model_list}


def reset():
    """Reset all counters (for testing)."""
    with _lock:
        _usage.clear()
