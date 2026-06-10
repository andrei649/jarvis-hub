"""
Export the entire repository into a single structured text file,
suitable for pasting into any LLM context window.
"""

import os
from datetime import datetime

VALID_EXTENSIONS = (
    ".py", ".md", ".yaml", ".yml", ".json",
    ".toml", ".txt", ".sh", ".html", ".env.example",
    ".ts", ".tsx",   # HUD v2 + WorldView source (CSS excluded — tokens documented in BRAND_BOOK)
)

IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules",
    ".venv", "venv", "env", ".idea", ".vscode",
    "tmp", "memory_logs", "training", "dist", "build", ".next",
    "design_handoff_jarvis_hub", ".opencode",  # scratch/handoff — ruff excludes them too
    "internal",  # docs/internal — archived scratch, provenance only (see its README)
}

# Path-prefix ignores (relative to repo root) for dirs whose basename is too
# generic for IGNORE_DIRS: agents/web/ is the legacy v1 HUD + the committed
# v2 build output — the HUD source of truth is frontend/src.
IGNORE_REL_PREFIXES = ("agents/web/",)

IGNORE_FILES = {
    "export_repo.py",
    "repo_export.txt",      # own output — including it makes each run snowball
    "package-lock.json",    # lockfiles: ~1.1MB of resolver noise across 4 workspaces
}

# Profiles (see docs/AI_CONTEXT.md for measured sizes):
#   --research: the whole hub product without junk or provenance — code + HUD
#               source + tests + current docs. Excludes the standalone stacks
#               (worldview/mobile/desktop/rust) and historical spec/research
#               archives. Target: fits 1M tokens with headroom.
#   --core:     --research minus tests (smallest useful code+docs bundle).
RESEARCH_EXTRA_IGNORE_DIRS = {
    "worldview", "mobile", "desktop", "rust",   # separate stacks — load on demand
    "superpowers", "research",                  # docs provenance (dated, immutable)
}
CORE_EXTRA_IGNORE_DIRS = RESEARCH_EXTRA_IGNORE_DIRS | {"tests"}


def _keep_dir(dirpath: str, d: str, root: str) -> bool:
    if d in IGNORE_DIRS:
        return False
    rel = os.path.relpath(os.path.join(dirpath, d), root).replace(os.sep, "/") + "/"
    return not any(rel.startswith(p) for p in IGNORE_REL_PREFIXES)


def build_tree(root: str) -> list[str]:
    lines = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if _keep_dir(dirpath, d, root))
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        indent = "    " * depth
        folder_name = os.path.basename(dirpath) if rel != "." else os.path.basename(root)
        lines.append(f"{indent}{folder_name}/")
        for f in sorted(files):
            if _should_include(f):
                lines.append(f"{indent}    {f}")
    return lines


def _should_include(filename: str) -> bool:
    if filename in IGNORE_FILES:
        return False
    # match full name (e.g. ".env.example") or extension
    return filename.endswith(VALID_EXTENSIONS)


def export(output_filename: str = "repo_export.txt") -> None:
    root = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(root, output_filename)

    file_count = 0
    total_bytes = 0

    with open(output_path, "w", encoding="utf-8") as out:
        # ── Header ──────────────────────────────────────────────────────────
        out.write("=" * 72 + "\n")
        out.write(f"  REPOSITORY EXPORT — {os.path.basename(root)}\n")
        out.write(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        out.write("=" * 72 + "\n\n")

        # ── Directory tree ───────────────────────────────────────────────────
        out.write("DIRECTORY STRUCTURE\n")
        out.write("-" * 72 + "\n")
        for line in build_tree(root):
            out.write(line + "\n")
        out.write("\n")

        # ── File contents ────────────────────────────────────────────────────
        out.write("FILE CONTENTS\n")
        out.write("=" * 72 + "\n")

        for dirpath, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if _keep_dir(dirpath, d, root))
            for filename in sorted(files):
                if not _should_include(filename):
                    continue
                filepath = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(filepath, root)

                out.write(f"\n\n--- FILE: {rel_path} ---\n")
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                    out.write(content)
                    file_count += 1
                    total_bytes += len(content.encode("utf-8"))
                except Exception as exc:
                    out.write(f"[Read error: {exc}]\n")

        # ── Footer ───────────────────────────────────────────────────────────
        out.write("\n\n" + "=" * 72 + "\n")
        out.write(f"  END OF EXPORT  |  {file_count} files  |  {total_bytes / 1024:.1f} KB\n")
        out.write("=" * 72 + "\n")

    print(f"Export complete: {output_filename}  ({file_count} files, {total_bytes / 1024:.1f} KB)")


if __name__ == "__main__":
    import sys

    if "--core" in sys.argv:
        IGNORE_DIRS |= CORE_EXTRA_IGNORE_DIRS
    elif "--research" in sys.argv:
        IGNORE_DIRS |= RESEARCH_EXTRA_IGNORE_DIRS
    export()
