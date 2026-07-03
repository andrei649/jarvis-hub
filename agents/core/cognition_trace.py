"""cognition_trace.py — build + persist the per-turn cognition trace (CLN-2).

Extracted from orchestrator.py. `update_cognition(orch, ...)` assembles the
HUD-facing decision/scoring/trace dict (stamped on `orch.last_cognition`) and,
defensively, records the richer tracer row (H9.2) with live quality scoring
(H10.23/10.24/10.25) and the H21.1 anti-sycophancy axis. It reads orchestrator
subsystems off `orch` (tracer, agents, quality, cognition, review_queue) and
never raises — a tracer/quality failure must not break a request.

The orchestrator keeps a thin `_update_cognition` facade so the frozen surface
and call sites are unchanged.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("jarvis.orchestrator")


def update_cognition(orch, text, intent, plugin_data, synthesized,
                     t_classify, t_route, t_plugin, t_synthesize):
    from core.router import INTENT_RULES
    scoring = []
    for kw in intent.context.get("keywords_found", []):
        if kw in INTENT_RULES:
            agents, surfaces, weight = INTENT_RULES[kw]
            scoring.append({
                "keyword": kw,
                "weight": weight,
                "agents": agents,
                "category": kw
            })

    if not scoring:
        scoring = []

    alternatives = []
    for a, s in intent.context.get("scores", {}).items():
        if a not in (intent.target_agents or ["jarvis"]):
            alternatives.append({"agent": a, "score": s})

    alternatives = sorted(alternatives, key=lambda x: -x["score"])

    decision = {
        "source": intent.context.get("source", "keyword_match"),
        "confidence": intent.confidence,
        "agents_selected": intent.target_agents or ["jarvis"],
        "alternatives": alternatives,
        "timing": {
            "classify": t_classify,
            "route": t_route,
            "total": t_classify + t_route
        }
    }

    trace = [
        {"step": "classify", "duration_ms": t_classify, "result": intent.context.get("source", "keyword_match")},
        {"step": "route", "duration_ms": t_route, "agents": intent.target_agents or ["jarvis"]}
    ]
    if plugin_data:
        trace.append({"step": "plugin_data", "duration_ms": t_plugin, "plugins": list(plugin_data.keys())})
    if synthesized:
        trace.append({"step": "synthesize", "duration_ms": t_synthesize, "tokens": len(synthesized) // 4})

    orch.last_cognition = {
        "scoring": scoring,
        "decision": decision,
        "trace": trace
    }

    # H9.2: persist to tracer ring buffer (defensive — never breaks a request)
    try:
        if orch.tracer is not None:
            model = ""
            agents_selected = decision.get("agents_selected", [])
            if agents_selected:
                first_agent = agents_selected[0]
                agent_obj = orch.agents.get(first_agent)
                if agent_obj:
                    model = agent_obj.config.get("model", "")
            from .llm.tokenizer import estimate_tokens as _et
            tokens_in = _et(text or "")
            tokens_out = _et(synthesized or "")
            # H10.24: estimate $ cost for this trace (local models → $0).
            try:
                from .llm.cost_estimator import estimate_cost as _ec
                cost = _ec(model, tokens_in, tokens_out).get("total", 0.0)
            except Exception:
                cost = 0.0
            trace_dict = {
                "channel": getattr(orch, "_last_channel", "unknown"),
                "text_preview": (text or "")[:120],
                # O26-P0.4 (F4): the assistant reply, so response-quality axes
                # (honesty/sycophancy, non-empty, no-error) score the OUTPUT.
                "output_preview": (synthesized or "")[:240],
                "intent": decision.get("source", ""),
                "route": agents_selected[0] if agents_selected else "",
                "agents": agents_selected,
                "model": model,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost": cost,
                "timings": {
                    "classify": t_classify,
                    "route": t_route,
                    "plugin": t_plugin,
                    "synthesize": t_synthesize,
                    "total_ms": t_classify + t_route + t_plugin + t_synthesize,
                },
                "ok": True,
                "scoring": scoring,
                "full_trace": trace,
            }
            # H10.23: score the request live and attach it to the trace.
            if getattr(orch, "quality", None) is not None:
                try:
                    trace_id = orch.tracer.record(trace_dict)
                    trace_dict["id"] = trace_id
                    q = orch.quality.record(trace_dict)
                    trace_dict["quality"] = q
                    # H21.1: anti-sycophancy axis (gated; master OFF = no-op).
                    cog = getattr(orch, "cognition", None)
                    if cog is not None and cog.sub_enabled("honesty_enabled"):
                        hm = cog.module("honesty")
                        if hm is not None:
                            # O26-P0.4 (F4): sycophancy is a property of the REPLY,
                            # not the user's message — score output, pass input as
                            # context. (Was scoring text_preview = the user's text.)
                            _reply = trace_dict.get("output_preview") or ""
                            trace_dict["honesty"] = hm.score_response(
                                _reply,
                                user_msg=trace_dict.get("text_preview", ""),
                                trace_id=trace_dict.get("id", ""),
                            )
                    # H10.25: auto-flag low-scoring traces for human review.
                    if getattr(orch, "review_queue", None) is not None:
                        orch.review_queue.auto_flag(trace_dict, q.get("score"), orch.quality.threshold)
                except Exception:
                    logger.debug("quality scoring skipped", exc_info=True)
            else:
                orch.tracer.record(trace_dict)
    except Exception as _te:
        logger.debug(f"tracer.record skipped: {_te}")
