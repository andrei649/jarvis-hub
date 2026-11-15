"""`nerva pets` — H214 + H238 + H590 Petdex, Hatch-a-Pet, terminal sprite renderer & doctor."""

from __future__ import annotations

import argparse
import base64
from pathlib import Path
from urllib.parse import quote

from agents.cli.client import HubUnavailable
from agents.core.pets import PetError, PetStore, render_terminal_protocol

BASE = "/api/pets"


def register_parser(verbs):
    pets = verbs.add_parser("pets", help="Petdex companions, Hatch-a-Pet generator & terminal sprites")
    ops = pets.add_subparsers(dest="operation", required=True)

    ops.add_parser("info", help="active companion, live agent-state reaction, and settings")
    ops.add_parser("gallery", help="list all built-in and hatched/imported Petdex companions")
    ops.add_parser("list", help="list all built-in and hatched/imported Petdex companions")

    show_p = ops.add_parser("show", help="show active or named companion metadata and terminal sprite")
    show_p.add_argument("pet_id", nargs="?", default="", help="companion id (defaults to active)")
    show_p.add_argument("--state", default="idle", choices=["idle", "thinking", "tool", "finishing", "failing"])
    show_p.add_argument("--protocol", default="auto", choices=["auto", "halfblock", "ascii", "kitty", "iterm2"])
    show_p.add_argument("--json", action="store_true")

    meta = ops.add_parser("meta", help="metadata for one companion")
    meta.add_argument("pet_id")

    cells = ops.add_parser("cells", help="8x8 RGB cell matrix for a companion and state")
    cells.add_argument("pet_id")
    cells.add_argument("--state", default="idle", choices=["idle", "thinking", "tool", "finishing", "failing"])
    cells.add_argument("--frame", type=int, default=0)

    thumb = ops.add_parser("thumb", help="SVG thumbnail for a companion")
    thumb.add_argument("pet_id")
    thumb.add_argument("--state", default="idle")

    select = ops.add_parser("select", help="select active companion")
    select.add_argument("pet_id")

    rename = ops.add_parser("rename", help="rename a companion")
    rename.add_argument("pet_id")
    rename.add_argument("name")

    scale = ops.add_parser("scale", help="set companion scale (0.5..3.0)")
    scale.add_argument("factor", type=float)

    ops.add_parser("disable", help="switch companion off")
    ops.add_parser("off", help="switch companion off")
    ops.add_parser("enable", help="switch companion on")
    ops.add_parser("on", help="switch companion on")

    remove = ops.add_parser("remove", help="delete a custom hatched/imported companion")
    remove.add_argument("pet_id")
    remove.add_argument("--confirm", action="store_true", help="confirm permanent deletion")

    export_p = ops.add_parser("export", help="export a companion to a re-importable .pet.zip file")
    export_p.add_argument("pet_id")
    export_p.add_argument("--out", default="", help="optional output path for the .pet.zip archive")

    import_p = ops.add_parser("import", help="import a .pet.zip archive")
    import_p.add_argument("zip_path")

    install_p = ops.add_parser("install", help="install a .pet.zip companion archive")
    install_p.add_argument("zip_path")

    gen = ops.add_parser("generate", help="generate 4 Hatch-a-Pet candidate drafts")
    gen.add_argument("prompt")
    gen.add_argument("--backend", default="", help="procedural-pixel | svg-synth | local-vlm")

    status = ops.add_parser("status", help="check Hatch-a-Pet candidate generation status")
    status.add_argument("job_id")

    cancel = ops.add_parser("cancel", help="cancel a Hatch-a-Pet generation job")
    cancel.add_argument("job_id")

    remix = ops.add_parser("remix", help="remix a candidate draft (requires --confirm)")
    remix.add_argument("job_id")
    remix.add_argument("draft_id")
    remix.add_argument("--instruction", default="")
    remix.add_argument("--confirm", action="store_true")

    hatch = ops.add_parser("hatch", help="hatch and adopt a candidate draft into your Petdex")
    hatch.add_argument("job_id")
    hatch.add_argument("draft_id")
    hatch.add_argument("--name", default="")

    render_p = ops.add_parser("render", help="render companion in terminal (Kitty/iTerm2/half-block)")
    render_p.add_argument("--pet", default="", help="pet_id (defaults to active companion)")
    render_p.add_argument("--state", default="idle", choices=["idle", "thinking", "tool", "finishing", "failing"])
    render_p.add_argument("--protocol", default="auto", choices=["auto", "halfblock", "ascii", "kitty", "iterm2"])

    ops.add_parser("doctor", help="offline + terminal diagnostics for the companion subsystem")
    return pets


def _offline_fallback(op: str, ns: argparse.Namespace) -> dict | None:
    store = PetStore()
    if op in ("gallery", "list"):
        return store.gallery()
    if op == "info":
        return store.info()
    if op == "select":
        return store.select(ns.pet_id)
    if op == "scale":
        return store.set_scale(float(ns.factor))
    if op in ("disable", "off"):
        return store.disable()
    if op in ("enable", "on"):
        return store.enable()
    if op == "remove":
        return store.remove(ns.pet_id, confirm=bool(ns.confirm))
    if op in ("import", "install"):
        return store.import_zip(Path(ns.zip_path).read_bytes())
    return None


def run(ns: argparse.Namespace, ctx) -> int:
    op = ns.operation

    # Offline-capable local verbs: `render`, `show`, and `doctor` work directly on local PetStore + env.
    if op == "render":
        store = PetStore()
        cell_doc = store.cells(ns.pet or None, state=ns.state, frame=0)
        rendered = render_terminal_protocol(
            cell_doc["cells"], protocol=ns.protocol, env=ctx.environ
        )
        ctx.out.write(rendered["rendered"] + "\n")
        return 0
    if op == "show":
        store = PetStore()
        try:
            info = store.info()
            pet_id = ns.pet_id or info["active_id"]
            meta = store.meta(pet_id)["pet"]
            cell_doc = store.cells(pet_id, state=ns.state, frame=0)
            rendered = render_terminal_protocol(
                cell_doc["cells"], protocol=ns.protocol, env=ctx.environ
            )
        except PetError as exc:
            ctx.err.write(f"{exc.detail}\n")
            return 1
        if getattr(ns, "json", False):
            ctx.dump(
                {
                    "ok": True,
                    "pet": meta,
                    "enabled": info["enabled"],
                    "scale": info["scale"],
                    "protocol": rendered["protocol"],
                    "rendered": rendered["rendered"],
                }
            )
            return 0
        ctx.say(
            f"{meta['name']} ({meta['id']}) · {meta['rarity']} · {meta['vibe']} · "
            f"enabled={info['enabled']} · scale={info['scale']}"
        )
        ctx.out.write(rendered["rendered"] + "\n")
        return 0
    if op == "doctor":
        store = PetStore()
        ctx.dump(store.doctor(env=ctx.environ))
        return 0

    method, path, body = "GET", BASE, None
    if op in ("gallery", "list"):
        method, path = "GET", f"{BASE}/gallery"
    elif op == "meta":
        method, path = "GET", f"{BASE}/{quote(ns.pet_id, safe='')}/meta"
    elif op == "cells":
        pid = quote(ns.pet_id, safe="")
        method, path = "GET", f"{BASE}/{pid}/cells?state={quote(ns.state, safe='')}&frame={int(ns.frame)}"
    elif op == "thumb":
        pid = quote(ns.pet_id, safe="")
        method, path = "GET", f"{BASE}/{pid}/thumb?state={quote(ns.state, safe='')}"
    elif op == "select":
        method, path, body = "POST", f"{BASE}/select", {"pet_id": ns.pet_id}
    elif op == "rename":
        pid = quote(ns.pet_id, safe="")
        method, path, body = "POST", f"{BASE}/{pid}/rename", {"name": ns.name}
    elif op == "scale":
        method, path, body = "PUT", f"{BASE}/preferences", {"scale": float(ns.factor)}
    elif op in ("disable", "off"):
        method, path, body = "PUT", f"{BASE}/preferences", {"enabled": False}
    elif op in ("enable", "on"):
        method, path, body = "PUT", f"{BASE}/preferences", {"enabled": True}
    elif op == "remove":
        pid = quote(ns.pet_id, safe="")
        confirm_str = "true" if ns.confirm else "false"
        method, path = "DELETE", f"{BASE}/{pid}?confirm={confirm_str}"
    elif op == "export":
        pid = quote(ns.pet_id, safe="")
        reply = ctx.client().request("GET", f"{BASE}/{pid}/export", None)
        if ns.out and isinstance(reply, dict) and reply.get("zip_base64"):
            out_path = Path(ns.out)
            out_path.write_bytes(base64.b64decode(reply["zip_base64"]))
            reply = {**reply, "written_to": str(out_path)}
        ctx.dump(reply)
        return 0
    elif op in ("import", "install"):
        raw = Path(ns.zip_path).read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        method, path, body = "POST", f"{BASE}/import", {"zip_base64": b64}
    elif op == "generate":
        method, path = "POST", f"{BASE}/hatch/generate"
        body = {"prompt": ns.prompt, "image_backend": ns.backend}
    elif op == "status":
        jid = quote(ns.job_id, safe="")
        method, path = "GET", f"{BASE}/hatch/jobs/{jid}"
    elif op == "cancel":
        jid = quote(ns.job_id, safe="")
        method, path, body = "POST", f"{BASE}/hatch/jobs/{jid}/cancel", {}
    elif op == "remix":
        jid = quote(ns.job_id, safe="")
        method, path = "POST", f"{BASE}/hatch/jobs/{jid}/remix"
        body = {"draft_id": ns.draft_id, "instruction": ns.instruction, "confirm": bool(ns.confirm)}
    elif op == "hatch":
        jid = quote(ns.job_id, safe="")
        method, path = "POST", f"{BASE}/hatch/jobs/{jid}/adopt"
        body = {"draft_id": ns.draft_id, "name": ns.name}
    elif op != "info":
        raise argparse.ArgumentTypeError("unknown pets operation")

    try:
        ctx.dump(ctx.client().request(method, path, body))
        return 0
    except HubUnavailable:
        try:
            fallback = _offline_fallback(op, ns)
        except PetError as exc:
            ctx.err.write(f"{exc.detail}\n")
            return 1
        if fallback is None:
            raise
        ctx.dump(fallback)
        return 0
