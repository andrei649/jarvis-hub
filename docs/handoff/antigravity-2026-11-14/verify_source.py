"""Read-only verification of the transferred source and documented handoff overlay."""

import argparse
import hashlib
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[3])
    args = parser.parse_args()
    root = args.root.resolve()
    package = root / 'docs/handoff/antigravity-2026-11-14'
    baseline = json.loads((package / 'manifests/cumulative-source.json').read_text())
    overlay = json.loads((package / 'manifests/handoff-overlay.json').read_text())
    expected = dict(baseline['files'])
    expected.update(overlay['files'])
    errors = []
    for name, info in expected.items():
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            errors.append({'path': name, 'error': 'unsafe path'})
        elif not path.is_file():
            errors.append({'path': name, 'error': 'missing'})
        elif hashlib.sha256(path.read_bytes()).hexdigest() != info['sha256']:
            errors.append({'path': name, 'error': 'sha256 mismatch'})
    for name in baseline.get('deleted_paths', []):
        if (root / name).exists():
            errors.append({'path': name, 'error': 'deleted path restored'})
    print(json.dumps({'ok': not errors, 'checked_files': len(expected),
                      'baseline_files': len(baseline['files']),
                      'overlay_files': len(overlay['files']), 'errors': errors}, indent=2))
    return bool(errors)


if __name__ == '__main__':
    sys.exit(main())
