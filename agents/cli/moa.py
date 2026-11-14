"""`nerva moa` — Mixture-of-Agents committee presets & resilient hybrid synthesis (H032)."""

from __future__ import annotations

import argparse
from typing import Any
from urllib.parse import quote

BASE = "/api/llm/moa"


def register_parser(verbs) -> argparse.ArgumentParser:
    moa = verbs.add_parser(
        "moa",
        help="manage Mixture-of-Agents committee presets and run parallel quorum synthesis",
    )
    actions = moa.add_subparsers(dest="moa_action", required=True, metavar="action")

    ls = actions.add_parser("list", help="list saved MoA committee presets, active preset, and recent runs")
    ls.add_argument("--offline", action="store_true", help="read presets directly from local data root")
    ls.add_argument("--json", action="store_true")

    put = actions.add_parser("set", help="create or update a named MoA committee preset")
    put.add_argument("name", help="preset identifier (e.g. council)")
    put.add_argument(
        "--proposers",
        required=True,
        help="comma-separated list of 2..6 member model specs (e.g. local,local-deep,gemini)",
    )
    put.add_argument("--aggregator", required=True, help="aggregator model spec (e.g. claude or local-deep)")
    put.add_argument("--description", default="", help="short human description")
    put.add_argument("--min-quorum", type=int, default=None, help="minimum succeeding proposers required")
    put.add_argument("--timeout", type=float, default=45.0, help="per-member timeout in seconds (2..180)")
    put.add_argument("--temperature", type=float, default=0.6, help="proposer sampling temperature (0.0..1.5)")
    put.add_argument("--offline", action="store_true", help="write preset directly to local data root")
    put.add_argument("--json", action="store_true")

    rm = actions.add_parser("delete", help="delete a saved MoA preset")
    rm.add_argument("name", help="preset identifier")
    rm.add_argument("--offline", action="store_true", help="delete preset directly from local data root")
    rm.add_argument("--json", action="store_true")

    act = actions.add_parser("activate", help="activate a saved MoA preset globally, or --clear")
    act.add_argument("name", nargs="?", default=None, help="preset identifier to activate")
    act.add_argument("--clear", action="store_true", help="clear global active MoA preset")
    act.add_argument("--offline", action="store_true", help="update active preset directly in local data root")
    act.add_argument("--json", action="store_true")

    run_p = actions.add_parser("run", help="execute one governed MoA committee turn against the running hub")
    run_p.add_argument("preset", help="preset name or moa:<name>")
    run_p.add_argument("prompt", help="prompt to synthesize across the committee")
    run_p.add_argument("--agent", default="jarvis", help="agent policy context (default: jarvis)")
    run_p.add_argument("--max-tokens", type=int, default=1024, help="maximum synthesis output tokens")
    run_p.add_argument("--json", action="store_true")

    return moa


def _run_offline(ns: argparse.Namespace, ctx) -> int:
    from agents.core.llm.moa import (
        MoAConfigError,
        delete_preset,
        get_active_preset_name,
        list_presets,
        recent_runs,
        save_preset,
        set_active_preset,
        validate_preset,
    )
    from agents.core.managed_scope import ManagedRefused, check_llm_write

    from .nerva import EXIT_FAILED, EXIT_OK, EXIT_USAGE

    action = ns.moa_action
    try:
        if action == "list":
            payload: dict[str, Any] = {
                "presets": [p.to_dict() for p in list_presets()],
                "active": get_active_preset_name(),
                "recent_runs": recent_runs()[:20],
            }
            return _render_list(payload, ns, ctx)

        if action == "set":
            check_llm_write(selection=False)
            proposers = [part.strip() for part in str(ns.proposers).split(",") if part.strip()]
            preset = validate_preset(
                ns.name,
                proposers=proposers,
                aggregator=ns.aggregator,
                description=ns.description,
                min_quorum=ns.min_quorum,
                timeout_s=ns.timeout,
                temperature=ns.temperature,
            )
            saved = save_preset(preset)
            res = {"ok": True, "preset": saved.to_dict()}
            if ns.json:
                ctx.dump(res)
            else:
                ctx.say(
                    f"saved {saved.model_id} · proposers={','.join(saved.proposers)} "
                    f"· aggregator={saved.aggregator} · min_quorum={saved.min_quorum}"
                )
            return EXIT_OK

        if action == "delete":
            was_active = get_active_preset_name() == (ns.name or "").strip()
            check_llm_write(selection=was_active)
            if not delete_preset(ns.name):
                ctx.err.write(f"unknown MoA preset '{ns.name}'\n")
                return EXIT_FAILED
            res = {"ok": True, "deleted": ns.name, "active": get_active_preset_name()}
            if ns.json:
                ctx.dump(res)
            else:
                ctx.say(f"deleted moa:{ns.name}")
            return EXIT_OK

        if action == "activate":
            if ns.clear and ns.name:
                ctx.err.write("pass either a preset name or --clear, not both\n")
                return EXIT_USAGE
            if not ns.clear and not ns.name:
                ctx.err.write("pass a preset name or --clear\n")
                return EXIT_USAGE
            check_llm_write(selection=True)
            selected = set_active_preset(None if ns.clear else ns.name)
            res = {
                "ok": True,
                "active": selected.name if selected is not None else None,
                "preset": selected.to_dict() if selected is not None else None,
            }
            if ns.json:
                ctx.dump(res)
            elif selected is None:
                ctx.say("cleared active MoA preset")
            else:
                ctx.say(f"activated {selected.model_id}")
            return EXIT_OK
    except MoAConfigError as exc:
        ctx.err.write(f"{exc}\n")
        return EXIT_USAGE
    except ManagedRefused as exc:
        ctx.err.write(f"{exc}\n")
        return EXIT_FAILED

    ctx.err.write(f"unsupported offline action: {action}\n")
    return EXIT_USAGE


def _render_list(payload: dict[str, Any], ns: argparse.Namespace, ctx) -> int:
    from .nerva import EXIT_OK

    if ns.json:
        ctx.dump(payload)
        return EXIT_OK
    active = payload.get("active")
    presets = payload.get("presets") if isinstance(payload.get("presets"), list) else []
    if not presets:
        ctx.say("no MoA presets configured")
        return EXIT_OK
    for row in presets:
        if not isinstance(row, dict):
            continue
        mark = "* " if row.get("name") == active else "  "
        locality = "local-only" if row.get("pure_local") else "hybrid"
        props = ",".join(str(x) for x in (row.get("proposers") or []))
        ctx.say(
            f"{mark}{row.get('model_id')} ({locality}) · proposers=[{props}] "
            f"-> {row.get('aggregator')} · quorum={row.get('min_quorum')}/{len(row.get('proposers') or [])}"
        )
    return EXIT_OK


def run(ns: argparse.Namespace, ctx) -> int:
    from .nerva import EXIT_OK, EXIT_USAGE

    action = ns.moa_action
    if getattr(ns, "offline", False):
        return _run_offline(ns, ctx)

    if action == "list":
        reply = ctx.client().request("GET", f"{BASE}/presets")
        return _render_list(reply if isinstance(reply, dict) else {}, ns, ctx)

    if action == "set":
        proposers = [part.strip() for part in str(ns.proposers).split(",") if part.strip()]
        body: dict[str, Any] = {
            "proposers": proposers,
            "aggregator": ns.aggregator,
            "description": ns.description,
            "timeout_s": ns.timeout,
            "temperature": ns.temperature,
        }
        if ns.min_quorum is not None:
            body["min_quorum"] = ns.min_quorum
        reply = ctx.client().request("PUT", f"{BASE}/presets/{quote(ns.name, safe='')}", body)
        if ns.json:
            ctx.dump(reply)
        else:
            preset = (reply or {}).get("preset") or {}
            ctx.say(
                f"saved {preset.get('model_id', 'moa:' + ns.name)} "
                f"· aggregator={preset.get('aggregator', ns.aggregator)}"
            )
        return EXIT_OK

    if action == "delete":
        reply = ctx.client().request("DELETE", f"{BASE}/presets/{quote(ns.name, safe='')}")
        if ns.json:
            ctx.dump(reply)
        else:
            ctx.say(f"deleted moa:{ns.name}")
        return EXIT_OK

    if action == "activate":
        if ns.clear and ns.name:
            ctx.err.write("pass either a preset name or --clear, not both\n")
            return EXIT_USAGE
        if not ns.clear and not ns.name:
            ctx.err.write("pass a preset name or --clear\n")
            return EXIT_USAGE
        reply = ctx.client().request("POST", f"{BASE}/active", {"name": None if ns.clear else ns.name})
        if ns.json:
            ctx.dump(reply)
        elif ns.clear:
            ctx.say("cleared active MoA preset")
        else:
            ctx.say(f"activated moa:{(reply or {}).get('active') or ns.name}")
        return EXIT_OK

    if action == "run":
        reply = ctx.client().request(
            "POST",
            f"{BASE}/run",
            {
                "preset": ns.preset,
                "prompt": ns.prompt,
                "agent": ns.agent,
                "max_tokens": ns.max_tokens,
            },
        )
        if ns.json:
            ctx.dump(reply)
        else:
            ans = (reply or {}).get("answer") or ""
            tel = (reply or {}).get("telemetry") or {}
            ctx.say(str(ans))
            if isinstance(tel, dict) and tel:
                ctx.say(
                    f"[{reply.get('model')} · {reply.get('route')} · "
                    f"quorum {tel.get('succeeded')}/{tel.get('total_proposers')} · "
                    f"speedup {tel.get('parallel_speedup')}x · {tel.get('total_ms')} ms]"
                )
        return EXIT_OK

    raise argparse.ArgumentTypeError(f"unknown moa action: {action}")
