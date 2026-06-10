"""
Export the entire repository into a single structured text file,
suitable for pasting into any LLM context window.
"""

import os
from datetime import datetime

VALID_EXTENSIONS = (
    ".py", ".md", ".yaml", ".yml", ".json",
    ".toml", ".txt", ".sh", ".html", ".env.example",
)

IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules",
    ".venv", "venv", "env", ".idea", ".vscode",
    "tmp", "memory_logs", "training", "dist", "build",
    "design_handoff_jarvis_hub", ".opencode",  # scratch/handoff — ruff excludes them too
}

IGNORE_FILES = {
    "export_repo.py",
    "repo_export.txt",      # own output — including it makes each run snowball
    "package-lock.json",    # lockfiles: ~1.1MB of resolver noise across 4 workspaces
}

# --core: only the Python hub + docs (fits a 1M-token context with headroom;
# the full export is ~1.1M tokens — see docs/AI_CONTEXT.md).
CORE_EXTRA_IGNORE_DIRS = {"tests", "worldview", "mobile", "desktop", "rust"}


def build_tree(root: str) -> list[str]:
    lines = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in IGNORE_DIRS)
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
            dirs[:] = sorted(d for d in dirs if d not in IGNORE_DIRS)
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
    export()
