#!/usr/bin/env bash
# build_release.sh — build reproducible Jarvis Hub release artifacts (H23.13).
#
# Produces, into OUT_DIR (default ./dist):
#   jarvis-<ver>.tar.gz, jarvis-<ver>.zip   source bundles — git-tracked files only,
#                                            so .env/data/.venv/node_modules/memory_logs
#                                            are excluded by .gitignore automatically.
#   SBOM.json                                CycloneDX SBOM (from requirements-beta.txt)
#   NOTICE                                   third-party dependency list
#   SHA256SUMS                               checksums for all of the above
#
# Jarvis runs from source (it is intentionally NOT pip-installed — see pyproject.toml /
# CONTRIBUTING.md), so the release artifact is a source bundle, not a wheel. The build
# is deterministic: `git archive` is reproducible for a commit and the SBOM/NOTICE
# derive from the (name-sorted) requirements file.
#
# Usage: scripts/build_release.sh [OUT_DIR] [GIT_REF]
set -euo pipefail
cd "$(dirname "$0")/.."

OUT_DIR="${1:-dist}"
GIT_REF="${2:-HEAD}"

VERSION="$(python3 - <<'PY'
import re
src = open("agents/__init__.py", encoding="utf-8").read()
m = re.search(r'__version__\s*=\s*"([^"]+)"', src)
print(m.group(1) if m else "0.0.0")
PY
)"
PREFIX="jarvis-${VERSION}"

mkdir -p "$OUT_DIR"
echo "[release] version ${VERSION} -> ${OUT_DIR}/"

git archive --format=tar.gz --prefix="${PREFIX}/" -o "${OUT_DIR}/${PREFIX}.tar.gz" "$GIT_REF"
git archive --format=zip    --prefix="${PREFIX}/" -o "${OUT_DIR}/${PREFIX}.zip"    "$GIT_REF"
echo "[release] bundled source -> ${PREFIX}.tar.gz, ${PREFIX}.zip"

python3 scripts/gen_sbom.py requirements-beta.txt "${OUT_DIR}/SBOM.json" "${OUT_DIR}/NOTICE" "$VERSION"

# Checksums (portable: sha256sum on Linux, shasum -a 256 on macOS).
if command -v sha256sum >/dev/null 2>&1; then SHA=(sha256sum); else SHA=(shasum -a 256); fi
( cd "$OUT_DIR" && "${SHA[@]}" "${PREFIX}.tar.gz" "${PREFIX}.zip" SBOM.json NOTICE > SHA256SUMS )
echo "[release] checksums -> SHA256SUMS"

echo "[release] done:"
ls -1 "$OUT_DIR"
