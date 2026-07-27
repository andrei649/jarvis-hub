"""Token cost tracker — accumulates usage per agent, estimates USD cost.

Adversarial audit 2026-07-25 (ADV-078): three cost endpoints — GET /api/cost,
GET /api/analytics/cost and GET /api/admin/apm — read this meter, and NOTHING fed it.
``record()`` had no caller anywhere outside this module, so every one of them rendered a
confident 0.00 forever; and the store was process-memory only, so even once fed it would
reset at every boot and "what did this cost me last month" stayed unanswerable. The first
design partner cannot answer that question, and an unattended night-shift loop on a cloud
key had no ceiling and produced no signal anywhere.

Fixed in three parts: the orchestrator now records every agent turn with the model that
actually ran (see ``_record_interactions``); usage persists under the data root and is
kept per UTC day so a cap and a monthly answer are both possible; and
``spend_today_usd()`` backs the ``llm.daily_cost_cap_usd`` check in the router.
"""
import json
import logging
import threading
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("jarvis.cost")

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

_lock = threading.RLock()
_usage: dict[str, dict] = defaultdict(
    lambda: {"input_tokens": 0, "output_tokens": 0, "calls": 0, "model": "default", "cost_usd": 0.0}
)
# Spend per UTC day, so a daily cap has something to read and last month is answerable.
_daily: dict[str, float] = defaultdict(float)
_loaded = False
# Bounded: ~13 months of daily rows. The file is a rollup, not a log — it must not grow
# without limit on a box that runs for years.
_MAX_DAYS = 400


def _store_path() -> Path:
    from agents.core.paths import data_path
    return Path(data_path("cost_usage.json"))


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _load_unlocked() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        raw = json.loads(_store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for agent, data in (raw.get("agents") or {}).items():
        if isinstance(data, dict):
            _usage[agent].update({k: v for k, v in data.items() if k in _usage[agent]})
    for day, spend in (raw.get("daily") or {}).items():
        try:
            _daily[str(day)] = float(spend)
        except (TypeError, ValueError):
            continue


def _save_unlocked() -> None:
    if len(_daily) > _MAX_DAYS:
        for day in sorted(_daily)[:-_MAX_DAYS]:
            _daily.pop(day, None)
    payload = {"agents": dict(_usage), "daily": dict(_daily), "saved_at": time.time()}
    try:
        path = _store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        # Losing a cost row must never break the turn that produced it.
        logger.debug("cost usage not persisted", exc_info=True)


def spend_today_usd() -> float:
    """Cloud spend recorded so far today (UTC). Backs the daily cap."""
    with _lock:
        _load_unlocked()
        return round(_daily.get(_today(), 0.0), 6)


def daily_spend() -> dict[str, float]:
    """Per-UTC-day spend, oldest first — what makes 'last month' answerable."""
    with _lock:
        _load_unlocked()
        return {day: round(v, 6) for day, v in sorted(_daily.items())}


def _price_for(model: str) -> dict:
    key = (model or "default").lower()
    return MODEL_PRICES.get(key) or MODEL_PRICES.get(
        next((k for k in MODEL_PRICES if k in key), "default"),
        MODEL_PRICES["default"],
    )


def record(agent_name: str, input_tokens: int, output_tokens: int, model: str = "default"):
    """Record token usage for an agent, pricing each call at its own model.

    Cost is accumulated per call so mixed local+cloud usage is priced correctly.
    Previously only the last model was retained and get_summary() re-priced the
    agent's whole cumulative token count at that one model's rate — a single
    cloud call would re-bill millions of prior local (free) tokens at cloud rates.
    """
    with _lock:
        _load_unlocked()
        entry = _usage[agent_name]
        entry["input_tokens"] += input_tokens
        entry["output_tokens"] += output_tokens
        entry["calls"] += 1
        entry["model"] = model
        price = _price_for(model)
        call_cost = (input_tokens / 1_000_000 * price["input"]
                     + output_tokens / 1_000_000 * price["output"])
        entry["cost_usd"] = round(entry["cost_usd"] + call_cost, 6)
        if call_cost:
            _daily[_today()] = round(_daily[_today()] + call_cost, 6)
        _save_unlocked()


def get_summary() -> dict:
    """Return per-agent usage + cost estimates (cost accumulated at record time)."""
    with _lock:
        result = {}
        total_cost = 0.0
        for agent, data in _usage.items():
            cost = round(data["cost_usd"], 6)
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
    global _loaded
    with _lock:
        _usage.clear()
        _daily.clear()
        _loaded = True      # do not re-read the on-disk rollup after an explicit reset
