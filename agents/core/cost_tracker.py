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


def reset():
    """Reset all counters (for testing)."""
    with _lock:
        _usage.clear()
