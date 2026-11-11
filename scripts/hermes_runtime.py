#!/usr/bin/env python3
"""Prepare the pinned Hermes source and its private upstream-managed runtime."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.core.hermes_runtime.distribution import (
    load_pin,
    prepare_source,
    provision_runtime,
    validate_python,
    verify_source,
)  # noqa: E402
from agents.core.paths import data_path  # noqa: E402

DATA_ROOT = data_path("hermes-runtime")


def _write_descriptor(root: Path, source: Path, home: Path, python: Path) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    pin = load_pin()
    document = {
        "source": str(source), "home": str(home), "python": str(python),
        "commit": pin["commit"], "tree_sha1": pin["tree_sha1"],
        "source_sha256": pin["source_sha256"],
    }
    path = root / "runtime.json"
    descriptor, temporary = tempfile.mkstemp(prefix=".runtime-", suffix=".json", dir=root)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(document, output, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def _set_aside_stale_source(source: Path) -> Path | None:
    """After a pin bump the old tree no longer verifies. Keep it beside the new one
    (never delete: it may be inspected) and let prepare download the pinned tree."""
    if not (source.exists() or source.is_symlink()):
        return None
    try:
        verify_source(source)
        return None
    except ValueError:
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        aside = source.with_name(f"{source.name}.stale-{stamp}")
        source.rename(aside)
        return aside


def main() -> int:
    if sys.argv[1:2] == ["bump"]:
        # Maintainer step: move the pin. See scripts/hermes_runtime_bump.py.
        from scripts.hermes_runtime_bump import main as bump_main

        return bump_main(sys.argv[2:])
    parser = argparse.ArgumentParser(description=__doc__ + " Use `bump --commit <sha>` to move the pin.")
    parser.add_argument("command", choices=("prepare", "install", "status"))
    args = parser.parse_args()
    source, home = DATA_ROOT / "source", DATA_ROOT / "home"
    if args.command in {"prepare", "install"}:
        aside = _set_aside_stale_source(source)
        if aside:
            print(json.dumps({"stale_source_moved_to": str(aside)}), file=sys.stderr)
    if args.command == "prepare":
        prepare_source(source)
        print(json.dumps({"source": str(source), "identity": verify_source(source)}))
    elif args.command == "install":
        prepare_source(source)
        python = provision_runtime(source, home)
        _write_descriptor(DATA_ROOT, source, home, python)
        print(json.dumps({"source": str(source), "python": str(python), "ready": True}))
    else:
        try:
            descriptor = json.loads((DATA_ROOT / "runtime.json").read_text(encoding="utf-8"))
            if descriptor["source"] != str(source) or descriptor["home"] != str(home):
                raise ValueError("Hermes runtime descriptor names unexpected paths")
            pin = load_pin()
            if any(descriptor.get(key) != pin[key] for key in ("commit", "tree_sha1", "source_sha256")):
                raise ValueError("Hermes runtime descriptor has stale source identity")
            identity = verify_source(source)
            from hashlib import sha256

            key = sha256(str(source.resolve()).encode()).hexdigest()[:16]
            facts = json.loads((home / "installs" / key / "facts.json").read_text(encoding="utf-8"))
            environment = Path(facts["packages"]["venv"]["environment"])
            python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            if descriptor["python"] != str(python):
                raise ValueError("Hermes runtime descriptor names unexpected Python")
            validate_python(python, source, home)
            print(json.dumps({"source": str(source), "python": str(python), "ready": True, "identity": identity}))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({"ready": False, "reason": str(exc)}))
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
