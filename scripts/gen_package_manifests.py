#!/usr/bin/env python3
"""gen_package_manifests.py — Homebrew cask, winget manifest, and the release channel.

Package managers are the cheapest distribution there is: `brew install nerva` is a
different product from "clone the repo and read INSTALL.md", and it is the same
build either way. This turns a finished release into the two manifests those
managers read, and decides which channel the release belongs to.

Everything here is built against one specific way of shipping a broken install:

* **The checksum comes from the build, never from a template.** A cask with a
  placeholder or a stale ``sha256`` fails on a *user's* machine, at install time,
  with an error about a corrupt download. That is the worst possible place to
  discover a release-tooling bug, so a missing checksum is a **refusal** here
  rather than an empty string that renders fine and installs nothing.
* **A prerelease never becomes `stable`.** ``v1.1.0-rc1`` goes to ``latest`` and
  only there. Promoting a release candidate because a version regex was loose is
  how a knowingly-unfinished build reaches everyone who typed `brew upgrade`.
* **A version that is not a version is refused**, not coerced. ``v1.1`` and
  ``1.1.0.0`` are not the tags this project cuts, and guessing what someone meant
  produces a manifest pointing at a URL that does not exist.
* **The manifests are release artifacts, not committed files.** A copy in the
  repo is stale the moment a release happens, and a stale cask is a cask that
  installs the previous version while claiming to be current.

Neither manager is published from here: Homebrew needs a tap repository and
winget needs a PR to microsoft/winget-pkgs, and both are the owner's to create.
This produces the exact files those steps consume — see ``docs/OWNER_TASKS.md``.

Usage:
    python scripts/gen_package_manifests.py --dist dist --version 1.1.0 \\
        --repo andrei649/jarvis-hub --out dist/packaging
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# The tags this project cuts: MAJOR.MINOR.PATCH, optionally with a prerelease
# suffix. Deliberately strict — a version that is not one of these is refused
# rather than coerced, because a guess produces a manifest pointing at a URL that
# does not exist.
VERSION_RE = re.compile(r"^(?P<core>\d+\.\d+\.\d+)(?:-(?P<pre>[0-9A-Za-z.\-]+))?$")

STABLE = "stable"
LATEST = "latest"

# Homebrew calls this a cask "token"; it is the package's short name and has
# nothing to do with credentials. Named CASK_NAME here because the Homebrew
# sense of "token" collides with the security one, and a reader (or a SAST
# rule) should not have to work out which is meant.
CASK_NAME = "nerva"
WINGET_ID = "Nerva.Nerva"
PUBLISHER = "Nerva"
DESCRIPTION = "A local-first personal AI that asks before it acts."
HOMEPAGE = "https://github.com/andrei649/jarvis-hub"
LICENSE = "Apache-2.0"

# Schema versions the managers actually validate against. Pinned rather than
# "latest": a manifest written against a schema nobody has published yet is
# rejected on submission, which is a slower, more confusing failure than a
# refusal here would have been.
WINGET_SCHEMA = "1.6.0"


class ManifestError(ValueError):
    """Something the generator will not guess at."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(detail or reason)


def parse_version(raw: str) -> tuple[str, str]:
    """``("1.1.0", "rc1")`` — the core version and the prerelease suffix, if any."""
    text = str(raw or "").strip()
    if text.startswith("v"):
        text = text[1:]
    match = VERSION_RE.match(text)
    if match is None:
        raise ManifestError("invalid_version", f"{raw!r} is not MAJOR.MINOR.PATCH[-pre]")
    return match.group("core"), (match.group("pre") or "")


def channel_for(version: str) -> str:
    """``stable`` only for a plain release. A prerelease is ``latest`` and no more.

    Everything about the split is here rather than in the workflow, so a shell
    conditional cannot quietly disagree with the manifest generator about what
    counts as a release.
    """
    _core, pre = parse_version(version)
    return LATEST if pre else STABLE


def read_checksums(path: str | Path) -> dict[str, str]:
    """Parse a ``SHA256SUMS`` file into ``{filename: sha256}``.

    Tolerates both `sha256sum` (``hash  name``) and BSD `shasum` output, because
    the build script picks whichever the runner has and a parser that only knew
    one would silently return nothing on the other.
    """
    target = Path(path)
    if not target.is_file():
        raise ManifestError("checksums_missing", f"{target} does not exist")
    sums: dict[str, str] = {}
    for line in target.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        digest, name = parts[0], parts[-1].lstrip("*")
        if re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            sums[name] = digest.lower()
    if not sums:
        raise ManifestError("checksums_empty", f"{target} contained no sha256 lines")
    return sums


def _require(sums: dict[str, str], name: str) -> str:
    digest = sums.get(name)
    if not digest:
        # An empty sha256 renders as a perfectly valid-looking manifest and fails
        # on a user's machine with "checksum mismatch". Refuse here instead.
        raise ManifestError("checksum_not_found", f"no sha256 recorded for {name}")
    return digest


def asset_url(repo: str, version: str, filename: str) -> str:
    return f"https://github.com/{repo}/releases/download/v{version}/{filename}"


def render_cask(*, version: str, repo: str, sha256: str, filename: str) -> str:
    """A Homebrew cask for the source bundle.

    A cask rather than a formula: Nerva runs from source with its own bootstrap
    (it is deliberately not pip-installed), so there is nothing for a formula's
    build phase to do, and pretending otherwise would produce a formula that
    fails Homebrew's audit.
    """
    core, pre = parse_version(version)
    display = f"{core}-{pre}" if pre else core
    return f'''cask "{CASK_NAME}" do
  version "{display}"
  sha256 "{sha256}"

  url "{asset_url(repo, display, filename)}",
      verified: "github.com/{repo}/"
  name "Nerva"
  desc "{DESCRIPTION}"
  homepage "{HOMEPAGE}"

  # Nerva runs from source and installs its own virtualenv on first launch, so
  # the cask stages the bundle and the bootstrap does the rest. Nothing here
  # writes outside the staging prefix or asks for elevated rights.
  stage_only true

  caveats <<~EOS
    Finish setting up with:
      cd #{{staged_path}} && ./install.sh
    Nerva binds to 127.0.0.1 and asks before it acts. See docs/INSTALL.md.
  EOS
end
'''


def render_winget(*, version: str, repo: str, sha256: str, filename: str) -> dict[str, Any]:
    """The three winget manifest documents, as ``{suffix: parsed yaml}``.

    Returned as data rather than text so a test can assert on fields instead of
    on formatting, and so the caller decides how to serialise.
    """
    core, pre = parse_version(version)
    display = f"{core}-{pre}" if pre else core
    common = {
        "PackageIdentifier": WINGET_ID,
        "PackageVersion": display,
        "ManifestType": "",
        "ManifestVersion": WINGET_SCHEMA,
    }
    return {
        "installer": {
            **common,
            "ManifestType": "installer",
            "InstallerType": "zip",
            "Installers": [
                {
                    "Architecture": "x64",
                    "InstallerUrl": asset_url(repo, display, filename),
                    "InstallerSha256": sha256.upper(),
                    "NestedInstallerType": "portable",
                    "NestedInstallerFiles": [
                        {"RelativeFilePath": "INSTALL.bat", "PortableCommandAlias": "nerva"}
                    ],
                }
            ],
        },
        "locale.en-US": {
            **common,
            "ManifestType": "defaultLocale",
            "PackageLocale": "en-US",
            "Publisher": PUBLISHER,
            "PackageName": "Nerva",
            "License": LICENSE,
            "ShortDescription": DESCRIPTION,
            "PackageUrl": HOMEPAGE,
        },
        "version": {
            **common,
            "ManifestType": "version",
            "DefaultLocale": "en-US",
        },
    }


def _yaml(document: Any, indent: int = 0) -> str:
    """A tiny YAML writer for the flat/list shapes winget manifests use.

    Hand-rolled rather than importing PyYAML: this script runs in the release
    workflow before any project dependency is installed, and a release step that
    can fail on a missing import is a release step that fails at the worst time.
    """
    pad = " " * indent
    lines: list[str] = []
    if isinstance(document, dict):
        for key, value in document.items():
            if isinstance(value, (dict, list)):
                lines.append(f"{pad}{key}:")
                lines.append(_yaml(value, indent + 2))
            else:
                lines.append(f"{pad}{key}: {_scalar(value)}")
    elif isinstance(document, list):
        for item in document:
            if isinstance(item, dict):
                rendered = _yaml(item, indent + 2).lstrip()
                lines.append(f"{pad}- {rendered}")
            else:
                lines.append(f"{pad}- {_scalar(item)}")
    return "\n".join(line for line in lines if line.strip())


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if text == "" or any(c in text for c in ":#{}[]," ) or text != text.strip():
        return json.dumps(text)
    return text


def write_manifests(
    *,
    dist: str | Path,
    version: str,
    repo: str,
    out: str | Path,
) -> dict[str, Any]:
    """Generate every manifest for one built release. Returns what it wrote."""
    core, pre = parse_version(version)
    display = f"{core}-{pre}" if pre else core
    sums = read_checksums(Path(dist) / "SHA256SUMS")

    tarball = f"jarvis-{display}.tar.gz"
    zipball = f"jarvis-{display}.zip"
    tar_sha = _require(sums, tarball)
    zip_sha = _require(sums, zipball)

    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)

    cask = render_cask(version=display, repo=repo, sha256=tar_sha, filename=tarball)
    (out_dir / f"{CASK_NAME}.rb").write_text(cask, encoding="utf-8")

    winget = render_winget(version=display, repo=repo, sha256=zip_sha, filename=zipball)
    written = [f"{CASK_NAME}.rb"]
    for suffix, document in winget.items():
        name = f"{WINGET_ID}.{suffix}.yaml"
        (out_dir / name).write_text(_yaml(document) + "\n", encoding="utf-8")
        written.append(name)

    channel = channel_for(display)
    summary = {
        "version": display,
        "channel": channel,
        "prerelease": bool(pre),
        "cask_sha256": tar_sha,
        "winget_sha256": zip_sha.upper(),
        "files": written,
    }
    (out_dir / "channel.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", default="dist", help="directory holding SHA256SUMS")
    parser.add_argument("--version", required=True, help="release version (with or without v)")
    parser.add_argument("--repo", default="andrei649/jarvis-hub")
    parser.add_argument("--out", default="dist/packaging")
    args = parser.parse_args(argv)
    try:
        summary = write_manifests(
            dist=args.dist, version=args.version, repo=args.repo, out=args.out
        )
    except ManifestError as exc:
        print(f"::error::{exc.reason}: {exc.detail}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
