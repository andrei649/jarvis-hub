#!/usr/bin/env python3
"""
Creates a clean, self-contained Windows/cross-platform export zip:
  Andrei-OS-JARVIS-Windows-Bundle.zip
Includes:
  - App code (`server.py`, `START.bat`, `GEMINI.md`, `README.md`, `config.example.json`, `public/`)
  - Portable copy of `~/Documents/Andrei OS Obsidian` under `vault/Andrei OS Obsidian/`
    (skipped when that folder does not exist on this machine)
Excludes:
  - `config.json` (never exports API keys or secrets)
"""

import os
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VAULT_SRC = Path.home() / "Documents" / "Andrei OS Obsidian"
OUT_ZIP = ROOT / "Andrei-OS-JARVIS-Windows-Bundle.zip"

APP_FILES = [
    "server.py",
    "START.bat",
    "GEMINI.md",
    "README.md",
    "config.example.json",
    "export_for_windows.py",
]


def build_bundle() -> Path:
    with zipfile.ZipFile(OUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in APP_FILES:
            p = ROOT / rel
            if p.exists():
                zf.write(p, f"Andrei-OS-JARVIS/{rel}")

        pub = ROOT / "public"
        for root, dirs, files in os.walk(pub):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fn in sorted(files):
                if fn.startswith("."):
                    continue
                fp = Path(root) / fn
                arc = "Andrei-OS-JARVIS/" + str(fp.relative_to(ROOT)).replace("\\", "/")
                zf.write(fp, arc)

        SF_DATALESS = 0x40000000
        if VAULT_SRC.exists():
            for root, dirs, files in os.walk(VAULT_SRC):
                dirs[:] = [d for d in dirs if d != ".DS_Store"]
                for fn in sorted(files):
                    if fn == ".DS_Store":
                        continue
                    fp = Path(root) / fn
                    st = os.stat(fp, follow_symlinks=False)
                    if getattr(st, "st_flags", 0) & SF_DATALESS:
                        continue
                    arc = "Andrei-OS-JARVIS/vault/Andrei OS Obsidian/" + str(fp.relative_to(VAULT_SRC)).replace("\\", "/")
                    zf.write(fp, arc)
        else:
            print(f"Vault not found at {VAULT_SRC} - bundling the app only (no vault/).")

    return OUT_ZIP


if __name__ == "__main__":
    out = build_bundle()
    size_kb = out.stat().st_size / 1024
    print(f"Created portable bundle: {out} ({size_kb:.1f} KB)")
