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

Audit 2026-09-18: both halves of that fix were wrong about *which* model ran. The
orchestrator passed the agent's **configured** model, and `AgentConfig.model` defaults to
a local id no agents.yaml entry overrides, so every cloud turn priced at $0.00 — the meter
was fed and still read zero. And an id this table did not recognise fell through to the
`default` $3/$15 row, so the other failure mode invented money nobody could tell from a
measurement. The record site now carries the routed model (see ``_last_models`` in
``orchestrator.py``), and an unrecognised id is reported ``priced: False`` rather than
billed — the same distinction `llm/cost_estimator.py` already draws.
"""
import json
import logging
import threading
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("jarvis.cost")

# What a caller records when it cannot name the model that ran. Deliberately NOT a price
# row: it matches no family here, so `_price_for` returns None and the call is counted in
# tokens but left out of the dollar figure. "The router never told us" and "it was free"
# are different answers, and only one of them is honest about a cloud turn.
UNPRICED_MODEL = "unknown"

# Price per 1M tokens (input/output), USD. These are *family* keys: `_price_for` falls
# back to the longest matching substring, so "claude-opus-5" and "claude-opus-4-8" both
# resolve to the "claude-opus" row without an entry per released model, while the more
# specific "gpt-4o-mini" still beats "gpt-4o". Exact per-model figures — and the
# provider source URLs — live in `agents/core/llm/cost_estimator.py`; a test pins each
# row below to that table's newest member so the two cannot drift apart silently.
#
# The `cached` rate on each row is the vendor's cache-read price, mirroring
# `cost_estimator.MODELS` so `test_price_tables_do_not_drift` still compares whole rows;
# `None` means the vendor publishes no cache-read rate. `_price_for` reads only
# input/output — this meter bills every token at the uncached rate — so the key is inert
# here and exists purely to keep the two tables shaped alike.
#
# Prices verified 2026-08-17. Three rows were priced for models retired months earlier:
# Haiku was on Haiku 3's $0.25/$1.25 (~4x under), Opus on Opus 3/4's $15/$75 (3x over),
# and gpt-4o on the superseded 2024-05-13 snapshot's $5/$15 (2x over). This meter is not
# cosmetic: `record()` feeds `spend_today_usd()`, which backs the
# `llm.daily_cost_cap_usd` check in the router.
MODEL_PRICES = {
    # A placeholder mid-tier rate for a caller that asks for it by name. It is NOT the
    # fallback for an id this table does not know — that fallback is what let an
    # unrecognised model invoice $3/$15 it had never been quoted (see `_price_for`).
    "default":         {"input": 3.00,  "output": 15.00, "cached": 0.3},
    # Anthropic
    "claude-fable":    {"input": 10.00, "output": 50.00, "cached": 1.0},
    "claude-mythos":   {"input": 10.00, "output": 50.00, "cached": 1.0},
    "claude-opus":     {"input": 5.00,  "output": 25.00, "cached": 0.5},
    "claude-sonnet":   {"input": 2.00,  "output": 10.00, "cached": 0.2},
    "claude-haiku":    {"input": 1.00,  "output": 5.00, "cached": 0.1},
    # Google Gemini. "gemini-pro" is the legacy catch-all and tracks 2.5 Pro.
    "gemini-pro":      {"input": 1.25,  "output": 10.00, "cached": 0.125},
    "gemini-2.5-pro":  {"input": 1.25,  "output": 10.00, "cached": 0.125},
    "gemini-3.1-pro":  {"input": 2.00,  "output": 12.00, "cached": None},
    "gemini-flash-lite": {"input": 0.25, "output": 1.50, "cached": 0.025},
    "gemini-flash":    {"input": 0.30,  "output": 2.50, "cached": 0.03},
    # OpenAI, via OpenRouter or an OpenAI-compatible base URL.
    "gpt-5-nano":      {"input": 0.05,  "output": 0.40, "cached": 0.005},
    "gpt-5-mini":      {"input": 0.25,  "output": 2.00, "cached": 0.025},
    "gpt-5-pro":       {"input": 15.00, "output": 120.00, "cached": None},
    "gpt-5":           {"input": 1.25,  "output": 10.00, "cached": 0.125},
    "gpt-4.1-nano":    {"input": 0.10,  "output": 0.40, "cached": 0.025},
    "gpt-4.1-mini":    {"input": 0.40,  "output": 1.60, "cached": 0.1},
    "gpt-4.1":         {"input": 2.00,  "output": 8.00, "cached": 0.5},
    "gpt-4o-mini":     {"input": 0.15,  "output": 0.60, "cached": 0.075},
    "gpt-4o":          {"input": 2.50,  "output": 10.00, "cached": 1.25},
    # Local backends bill nothing. Named explicitly because a local id such as
    # "google/gemma-4-31b-a4b" matches no family, and a measured $0.00 is the right
    # answer for it — what the caller in `orchestrator.py` documents ("A local route
    # prices at zero"). Without these rows it would now read *unpriced* instead, which
    # is true of an unknown cloud model but a needless caveat over a local one.
    "local":           {"input": 0.00,  "output": 0.00, "cached": 0.0},
    "gemma":           {"input": 0.00,  "output": 0.00, "cached": 0.0},
    "qwen":            {"input": 0.00,  "output": 0.00, "cached": 0.0},
    "deepseek":        {"input": 0.00,  "output": 0.00, "cached": 0.0},
    "llama":           {"input": 0.00,  "output": 0.00, "cached": 0.0},
    "mistral":         {"input": 0.00,  "output": 0.00, "cached": 0.0},
    "phi":             {"input": 0.00,  "output": 0.00, "cached": 0.0},
}

_lock = threading.RLock()
_usage: dict[str, dict] = defaultdict(
    # `unpriced_calls` counts the calls whose model this table could not price. It is a
    # counter rather than a flag because one agent mixes models across a session, and an
    # agent's `cost_usd` has to be readable as "the priced part of this, and N calls it
    # does not cover". An older rollup on disk simply has no key here and starts at 0 —
    # `_load_unlocked` only restores keys the entry already declares.
    lambda: {"input_tokens": 0, "output_tokens": 0, "calls": 0, "model": "default",
             "cost_usd": 0.0, "unpriced_calls": 0}
)
# Spend per UTC day, so a daily cap has something to read and last month is answerable.
_daily: dict[str, float] = defaultdict(float)
# Mutable holder rather than a bare module boolean rebound from two functions via
# `global`. Same behaviour, one place that owns the flag, no rebinding — and it drops a
# CodeQL py/unused-global-variable alert on the old pattern. (The old variable WAS read;
# the alert was a false positive on the rebind, but the container reads better anyway.)
_state: dict[str, bool] = {"loaded": False}
# Bounded: ~13 months of daily rows. The file is a rollup, not a log — it must not grow
# without limit on a box that runs for years.
_MAX_DAYS = 400


def _store_path() -> Path:
    from agents.core.paths import data_path
    return Path(data_path("cost_usage.json"))


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _load_unlocked() -> None:
    if _state["loaded"]:
        return
    # Set BEFORE reading: a corrupt or unreadable rollup must not be re-parsed on every
    # single record() call for the life of the process.
    _state["loaded"] = True
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


def _exact_prices() -> dict:
    """The per-model table from `llm/cost_estimator.py`, imported lazily.

    Lazy because `cost_tracker` is imported very early (the orchestrator pulls it in at
    turn time) and the LLM package drags in env/config; deferring keeps import order the
    same as before this table was consulted.
    """
    try:
        from agents.core.llm.cost_estimator import MODELS
    except Exception:  # pragma: no cover - defensive; family table still prices the call
        logger.debug("exact price table unavailable", exc_info=True)
        return {}
    return MODELS


def _price_for(model: str) -> dict | None:
    """Price row for a model id, most specific source first — or ``None`` if unpriced.

    1. an exact row in this module's family table (covers "default", "local");
    2. an exact row in the per-model table — **version-aware**, and the reason a
       generation-specific price is never flattened by its family;
    3. the **longest** matching family substring.

    Steps 2 and 3 both matter. A single coarse family row cannot price two live
    generations at once: Sonnet 5 is $2/$10 while Sonnet 4.5/4.6 remain $3/$15, so
    resolving "claude-sonnet-4-6" through the `claude-sonnet` row would under-bill it by
    a third. The exact table settles those; the family row only catches ids nobody has
    priced yet, so an unrecognised "claude-sonnet-*" still meters as *something*.

    Longest-match on step 3, not first-match: the old `next(...)` took whichever family
    happened to be inserted first, so "gpt-4o-mini-2024-07-18" billed at the `gpt-4o`
    rate purely because that row sat higher in the literal. The more specific family is
    always the longer string ("gpt-4o-mini" > "gpt-4o").

    There is deliberately no step 4. An id that matches no provider family is not a
    $3/$15 model — it is a model nobody here has priced, and `default` as a last resort
    turned that into a confident invoice figure an owner could not distinguish from a
    measured one. `record()` counts those calls and leaves them out of the dollars; the
    `default` row survives only for a caller that asks for it BY NAME, which is a
    request for a placeholder rate, not a failed lookup. An empty/missing model id is a
    failed lookup, not a request, so it resolves to `UNPRICED_MODEL`.
    """
    key = (model or UNPRICED_MODEL).lower()
    exact = MODEL_PRICES.get(key)
    if exact is not None:
        return exact
    per_model = _exact_prices().get(key)
    if per_model is not None:
        return per_model
    matches = [k for k in MODEL_PRICES if k != "default" and k in key]
    if not matches:
        return None
    return MODEL_PRICES[max(matches, key=len)]


def record(agent_name: str, input_tokens: int, output_tokens: int,
           model: str = UNPRICED_MODEL):
    """Record token usage for an agent, pricing each call at its own model.

    Cost is accumulated per call so mixed local+cloud usage is priced correctly.
    Previously only the last model was retained and get_summary() re-priced the
    agent's whole cumulative token count at that one model's rate — a single
    cloud call would re-bill millions of prior local (free) tokens at cloud rates.

    `model` must be the model that ACTUALLY ran, not the agent's configured one and not
    a route name: a route name ("cloud", "cloud-flash") matches no family row, and
    pricing one through this table used to land on `default` — $3/$15 for a Flash call
    that really costs $0.75/$3.75. A caller that cannot name the model passes
    ``UNPRICED_MODEL``, which is also this argument's default: saying nothing is not a
    request for the placeholder rate the way naming "default" is, and it used to bill
    $3/$15 all the same. Either way the tokens are still counted; only the dollars are
    withheld.
    """
    with _lock:
        _load_unlocked()
        entry = _usage[agent_name]
        entry["input_tokens"] += input_tokens
        entry["output_tokens"] += output_tokens
        entry["calls"] += 1
        entry["model"] = model
        price = _price_for(model)
        if price is None:
            logger.debug("unpriced model %r — counted in tokens, not in dollars", model)
            entry["unpriced_calls"] += 1
            call_cost = 0.0
        else:
            call_cost = (input_tokens / 1_000_000 * price["input"]
                         + output_tokens / 1_000_000 * price["output"])
        entry["cost_usd"] = round(entry["cost_usd"] + call_cost, 6)
        if call_cost:
            _daily[_today()] = round(_daily[_today()] + call_cost, 6)
        _save_unlocked()


def get_summary() -> dict:
    """Return per-agent usage + cost estimates (cost accumulated at record time).

    Each agent carries `priced`, mirroring `llm/cost_estimator.estimate_cost`: False
    means at least one of this agent's calls ran on a model nobody here has priced, so
    its `cost_usd` covers less than its tokens. `unpriced_calls` at the top level is how
    many such calls the whole figure is missing — a surface that prints a currency
    amount has to be able to say "plus N turns we cannot price".
    """
    with _lock:
        result = {}
        total_cost = 0.0
        total_unpriced = 0
        for agent, data in _usage.items():
            cost = round(data["cost_usd"], 6)
            unpriced = int(data.get("unpriced_calls", 0))
            total_cost += cost
            total_unpriced += unpriced
            result[agent] = {**data, "cost_usd": cost, "priced": unpriced == 0}
        return {"agents": result, "total_cost_usd": round(total_cost, 6),
                "unpriced_calls": total_unpriced}


def apm_summary() -> dict:
    """H10.16 — org-wide APM rollup: totals + per-agent + per-model breakdown.

    Built on get_summary() (per-agent tokens + $). Adds organization totals and
    a per-model aggregation for the Admin APM dashboard.

    `unpriced_calls` rides along at every level for the reason get_summary() gives: the
    dashboard renders a dollar figure, and it must be able to say how many runs that
    figure does not cover. On the per-model breakdown it also localises the gap — the
    row that cannot be priced is the row naming the model to add to the table.
    """
    summary = get_summary()
    agents = summary["agents"]

    totals = {"runs": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
              "unpriced_calls": 0}
    by_model: dict[str, dict] = {}
    by_agent = []

    for agent, data in agents.items():
        runs = data.get("calls", 0)
        in_tok = data.get("input_tokens", 0)
        out_tok = data.get("output_tokens", 0)
        cost = data.get("cost_usd", 0.0)
        model = data.get("model", "default")
        unpriced = int(data.get("unpriced_calls", 0))

        totals["runs"] += runs
        totals["input_tokens"] += in_tok
        totals["output_tokens"] += out_tok
        totals["cost_usd"] = round(totals["cost_usd"] + cost, 6)
        totals["unpriced_calls"] += unpriced

        by_agent.append({
            "agent": agent, "model": model, "runs": runs,
            "input_tokens": in_tok, "output_tokens": out_tok, "cost_usd": cost,
            "unpriced_calls": unpriced, "priced": unpriced == 0,
        })

        m = by_model.setdefault(
            model, {"model": model, "runs": 0, "input_tokens": 0,
                    "output_tokens": 0, "cost_usd": 0.0, "unpriced_calls": 0},
        )
        m["runs"] += runs
        m["input_tokens"] += in_tok
        m["output_tokens"] += out_tok
        m["cost_usd"] = round(m["cost_usd"] + cost, 6)
        m["unpriced_calls"] += unpriced

    by_agent.sort(key=lambda r: r["cost_usd"], reverse=True)
    by_model_list = sorted(by_model.values(), key=lambda r: r["cost_usd"], reverse=True)
    return {"totals": totals, "by_agent": by_agent, "by_model": by_model_list}


def reset():
    """Reset all counters (for testing)."""
    with _lock:
        _usage.clear()
        _daily.clear()
        # Do not re-read the on-disk rollup after an explicit reset — an isolated test
        # that resets and then records must not inherit another run's spend.
        _state["loaded"] = True
