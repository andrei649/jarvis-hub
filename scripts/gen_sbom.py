#!/usr/bin/env python3
"""Generate a minimal CycloneDX SBOM + a NOTICE file from a pip requirements file.

Stdlib-only and deterministic (components sorted by name, no timestamps) so the
release artifacts are reproducible. Used by scripts/build_release.sh (H23.13).

Usage: gen_sbom.py <requirements.txt> <out_sbom.json> <out_notice> [project_version]
"""

import json
import re
import sys

# name[extras] (==|>=|~=|<=|<|>) version  — extras/markers handled by the caller.
_REQ = re.compile(
    r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*"
    r"(?:==|>=|~=|<=|<|>|!=)?\s*([0-9][\w.*+!-]*)?"
)


def parse_requirements(text: str):
    """Return a name-sorted list of (name, version) from a requirements file.

    Skips blanks, comments, and pip directives (``-r``/``-e``/``--hash`` …).
    Strips extras (``pkg[extra]``) and environment markers (``; python_version…``).
    """
    comps: dict[str, tuple[str, str]] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        line = line.split(";", 1)[0].strip()  # drop env markers
        m = _REQ.match(line)
        if not m:
            continue
        name, version = m.group(1), (m.group(2) or "")
        comps[name.lower()] = (name, version)
    return [comps[k] for k in sorted(comps)]


def build_sbom(components, project_version: str) -> dict:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "jarvis-hub",
                "version": project_version,
            }
        },
        "components": [
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{name}@{version}" if version else f"pkg:pypi/{name}",
            }
            for name, version in components
        ],
    }


def build_notice(components, project_version: str) -> str:
    lines = [
        f"Jarvis Hub {project_version} — third-party Python dependencies",
        "=" * 60,
        "",
        "This product depends on the following packages, each under its own",
        "license. Run `pip-licenses` in the install venv for full license texts;",
        "this NOTICE lists components and pinned versions (from requirements).",
        "",
    ]
    lines += [f"  {name} {version}".rstrip() for name, version in components]
    lines.append("")
    return "\n".join(lines)


def main(argv) -> int:
    if len(argv) < 4:
        print("usage: gen_sbom.py <requirements> <out_sbom.json> <out_notice> [version]", file=sys.stderr)
        return 2
    req_path, sbom_path, notice_path = argv[1], argv[2], argv[3]
    project_version = argv[4] if len(argv) > 4 else "0.0.0"
    with open(req_path, encoding="utf-8") as f:
        components = parse_requirements(f.read())
    with open(sbom_path, "w", encoding="utf-8") as f:
        json.dump(build_sbom(components, project_version), f, indent=2)
        f.write("\n")
    with open(notice_path, "w", encoding="utf-8") as f:
        f.write(build_notice(components, project_version))
    print(f"SBOM: {len(components)} components -> {sbom_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
