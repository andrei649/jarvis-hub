#!/usr/bin/env python3
"""Fail-closed, offline validator for the B2.1 issue movement gate."""
from __future__ import annotations
import argparse, json, re, subprocess, sys
from pathlib import Path

LEGACY_BASE = "843918848c11bbd3f0099f9504d0e0eaaa56b9d6"
MARKER = "<!-- NERVA2:MOVEMENT-ATTESTATION:START -->"
REGISTERED = {"BACKLOG.md", "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json", "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md", "scripts/check_nerva_program_manifest.py", "tests/test_nerva_program_manifest.py", ".github/workflows/nerva-roadmap.yml"}
PATH_RE = re.compile(r"^[^\x00-\x1f\x7f]+$")

class MovementError(ValueError): pass

def strict_json(raw: str, *, max_bytes=65536):
    if len(raw.encode()) > max_bytes: raise MovementError("oversize JSON")
    def hook(pairs):
        out = {}
        for k,v in pairs:
            if k in out: raise MovementError("duplicate key")
            out[k]=v
        return out
    try: return json.loads(raw, object_pairs_hook=hook, parse_constant=lambda x: (_ for _ in ()).throw(MovementError("non-finite")))
    except (json.JSONDecodeError, UnicodeError) as e: raise MovementError("malformed JSON") from e

def parse_diff(raw: bytes):
    if b"\x00" not in raw: raise MovementError("diff is not NUL-delimited")
    parts = raw.split(b"\x00")
    if parts[-1] != b"": raise MovementError("unterminated diff")
    result=[]; i=0
    while i < len(parts)-1:
        rec=parts[i]; i+=1
        fields=rec.split(b"\t",1)
        if len(fields)!=2 or fields[0].decode("ascii", "ignore") not in "AMDRCT": raise MovementError("malformed status")
        try: path=fields[1].decode("utf-8")
        except UnicodeDecodeError as e: raise MovementError("invalid UTF-8 path") from e
        if not PATH_RE.fullmatch(path): raise MovementError("invalid path")
        result.append((fields[0].decode("ascii"), path))
    return result

def classify(branch: str, body: str, paths: list[str], *, manifest_changed=False):
    return branch.startswith("nerva2/") or MARKER in body or manifest_changed or any(p in REGISTERED or p.startswith("docs/nerva2/") for p in paths)

def validate_manifest_gate(manifest: dict, base: str):
    gate=manifest.get("movement_gate")
    if gate is None:
        if base == LEGACY_BASE: return
        raise MovementError("movement_gate required")
    if not isinstance(gate, dict) or gate.get("schema") != "nerva.movement-gate.v1": raise MovementError("invalid movement gate")
    if gate.get("enforcement_state") not in {"required", "safety_disabled"}: raise MovementError("invalid enforcement state")
    registry=gate.get("registry")
    if not isinstance(registry, list) or registry != sorted(set(registry)) or any("*" in str(x) for x in registry): raise MovementError("invalid registry")

def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--event", type=Path, required=True); ap.add_argument("--manifest", type=Path, required=True); ap.add_argument("--base", required=True); ap.add_argument("--diff", type=Path); args=ap.parse_args(argv)
    event=strict_json(args.event.read_text(encoding="utf-8")); manifest=strict_json(args.manifest.read_text(encoding="utf-8")); validate_manifest_gate(manifest,args.base)
    if args.diff: parse_diff(args.diff.read_bytes())
    return 0
if __name__ == "__main__":
    try: raise SystemExit(main())
    except MovementError as e: print(f"movement gate rejected: {e}", file=sys.stderr); raise SystemExit(1)
