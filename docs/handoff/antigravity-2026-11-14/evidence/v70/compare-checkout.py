"""Read-only comparison of a checkout to the V69/main/gateway hash inventory."""
import argparse
import collections
import hashlib
import json
import subprocess
from pathlib import Path, PurePosixPath

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("repository", type=Path)
parser.add_argument("manifest", type=Path)
args = parser.parse_args()
root = args.repository.resolve()
manifest = json.loads(args.manifest.read_text(encoding="utf-8"))

def git(*arguments):
    result = subprocess.run(["git", "--no-optional-locks", "-C", str(root), *arguments],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    return result.stdout.strip() if result.returncode == 0 else None

results = {}
for relative, expected in manifest["files"].items():
    parts = PurePosixPath(relative).parts
    if not parts or PurePosixPath(relative).is_absolute() or any(p in ("..", ".") or "\\" in p or ":" in p for p in parts):
        raise ValueError("invalid manifest path")
    path = root.joinpath(*parts)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root and root in parent.parents):
        results[relative] = {"status": "symlink_not_read"}
        continue
    if path.exists() and not path.is_file():
        results[relative] = {"status": "non_regular_not_read"}
        continue
    raw = path.read_bytes() if path.is_file() else None
    digest = hashlib.sha256(raw).hexdigest() if raw is not None else None
    matching = [label for label, value in expected.items() if value == digest]
    status = "matches_candidate" if "candidate" in matching else "matches_known_base" if matching else "divergent_or_missing"
    record = {"status": status, "sha256": digest, "matches": matching}
    if not matching and raw is not None and b"\0" not in raw:
        try:
            raw.decode("utf-8")
        except UnicodeError:
            pass
        else:
            normalized = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
            aliases = [label for label, value in expected.items() if value == normalized]
            if aliases:
                record.update(status="line_endings_differ", lf_normalized_matches=aliases)
    results[relative] = record

print(json.dumps({"schema_version": 1, "read_only": True,
                  "head": git("rev-parse", "HEAD"), "branch": git("branch", "--show-current"),
                  "status_porcelain": git("status", "--porcelain=v1"),
                  "expected_main": manifest["main"], "expected_gateway_head": manifest["gateway_head"],
                  "summary": dict(collections.Counter(row["status"] for row in results.values())),
                  "paths": results,
                  "limits": "Hash inventory only; divergence needs review and is not proof of a merge conflict."},
                 indent=2))
