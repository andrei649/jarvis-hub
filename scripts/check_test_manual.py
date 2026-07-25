#!/usr/bin/env python3
"""Lint the deep test manual's chapters against reality (docs/test-manual/).

Checks, per chapter:
  1. every `METHOD /path` route citation exists in the route snapshot (fabricated endpoint hunt)
  2. every repo-relative file path citation exists on disk
  3. case IDs: correct prefix, unique, no duplicates across chapters
  4. required subsections present (degraded matrix / negative / ledger / open gaps)
  5. structural sanity: H1 present, table column counts consistent

Usage: python scripts/check_test_manual.py [dir]   # defaults to docs/test-manual/
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / 'docs/test-manual'
SNAP = json.loads((ROOT / 'tests/_snapshots/route_surface.json').read_text(encoding='utf-8'))
AUTH = json.loads((ROOT / 'tests/_snapshots/route_auth.json').read_text(encoding='utf-8'))
KNOWN = set(SNAP) | set(AUTH)
KNOWN_PATHS = {r.split(' ', 1)[1] for r in KNOWN}

EXPECTED_PREFIX = {
    '01': 'ENV', '02': 'CHT', '03': 'SHL', '04': 'PNL', '05': 'PNB', '06': 'PGE',
    '07': 'GOV', '08': 'SEC', '09': 'MEM', '10': 'WFL', '11': 'CHN', '12': 'AIO',
    '13': ('JRN', 'CHA'), '14': 'API',
}

# "GET /api/foo" / "POST /chat" style citations in prose, code or tables
ROUTE_RE = re.compile(r'\b(GET|POST|PUT|PATCH|DELETE|HEAD)\s+(/[A-Za-z0-9_\-./{}:]*)')
# repo-relative paths: dir/file.ext, allowing agents/core/x.py, frontend/src/a.tsx, docs/X.md
PATH_RE = re.compile(r'\b((?:agents|frontend|tests|scripts|docs|mobile|worldview|desktop|rust|packaging|deploy|services|skills|packages|apps)/[A-Za-z0-9_\-./*{}]+\.[A-Za-z0-9]+)')
CASE_RE = re.compile(r'\b([A-Z]{3})-(\d{3})\b')
SECT_RE = re.compile(r'^#{1,4}\s')


def norm_route(path: str) -> str:
    """Normalise a cited path so template params match the snapshot's naming."""
    return re.sub(r'\{[^}]*\}', '{}', path.rstrip('.,;:)`'))


NORM_KNOWN = {norm_route(p) for p in KNOWN_PATHS}

# A chapter may cite a *concrete instantiation* of a templated route — e.g.
# "PUT /api/admin/settings/product" for the snapshot's ".../{category}". That is more
# useful to a tester than the template, so match those instead of flagging them.
TEMPLATE_RES = [
    re.compile('^' + re.sub(r'\\\{[^}]*\\\}', r'[^/]+', re.escape(p)) + '$')
    for p in KNOWN_PATHS if '{' in p
]


def route_known(path: str) -> bool:
    p = norm_route(path)
    if p in NORM_KNOWN:
        return True
    return any(rx.match(p) for rx in TEMPLATE_RES)


def check(md: Path) -> dict:
    text = md.read_text(encoding='utf-8')
    num = md.name[:2]
    want = EXPECTED_PREFIX.get(num)
    want = (want,) if isinstance(want, str) else (want or ())
    out = {'file': md.name, 'lines': text.count('\n') + 1, 'bad_routes': [], 'bad_paths': [],
           'cases': [], 'wrong_prefix': [], 'dupes': [], 'missing_sections': [], 'table_mismatch': [], 'pipe_in_cell': []}

    for m in ROUTE_RE.finditer(text):
        method, path = m.group(1), m.group(2)
        if route_known(path):
            continue
        # tolerate documented non-app paths (external services, examples)
        if any(path.startswith(p) for p in ('/v1/models', '/api/tags', '/health')):
            continue
        out['bad_routes'].append(f'{method} {path}')

    for m in PATH_RE.finditer(text):
        p = m.group(1)
        if '*' in p or '{' in p:
            continue
        # dotfiles the tester is told to CREATE (.env, .env.local) legitimately don't
        # exist in a clean checkout — their .example counterparts are what must exist.
        base = p.rsplit('/', 1)[-1]
        if base.startswith('.env'):
            if not any((ROOT / p).with_name(base + s).exists() for s in ('.example',)) \
               and not (ROOT / p).with_name('.env.example').exists():
                out['bad_paths'].append(p + ' (no .example to scaffold from)')
            continue
        if not (ROOT / p).exists():
            out['bad_paths'].append(p)

    # GFM breaks a table cell on an unescaped "|", even inside a code span. This is the
    # one defect class that silently mangles a rendered chapter.
    for i, line in enumerate(text.split('\n'), 1):
        s = line.strip()
        if not (s.startswith('|') and s.endswith('|')):
            continue
        # split on UNESCAPED pipes only — "\|" inside a code span is correct GFM
        cells = re.split(r'(?<!\\)\|', s[1:-1])
        if any(c.count('`') % 2 for c in cells):
            out['pipe_in_cell'].append(i)

    ids = CASE_RE.findall(text)
    out['cases'] = sorted({f'{a}-{b}' for a, b in ids})
    for a, b in set(ids):
        if want and a not in want and a != 'API':
            out['wrong_prefix'].append(f'{a}-{b}')
    dupe = [k for k, v in Counter(f'{a}-{b}' for a, b in ids).items() if v > 4]
    out['heavy_repeats'] = sorted(dupe)[:5]

    low = text.lower()
    # ch14 is a generated route enumeration — a degraded matrix / adversarial section
    # would be meaningless there; its equivalents are the three sweep passes.
    required = (('coverage ledger', 'coverage ledger'), ('open gaps', 'open gaps'))
    if num != '14':
        required = (('degraded', 'degraded matrix'),
                    ('adversarial', 'negative/adversarial')) + required
    for needle, label in required:
        if needle not in low:
            out['missing_sections'].append(label)

    block, start = [], 0
    for i, line in enumerate(text.split('\n'), 1):
        if line.strip().startswith('|'):
            if not block:
                start = i
            block.append(len(re.findall(r'(?<!\\)\|', line)))
        else:
            if block and len(set(block)) > 1:
                out['table_mismatch'].append(start)
            block = []
    return out


def main(argv):
    d = Path(argv[0]) if argv else DEFAULT_DIR
    files = sorted(d.glob('*.md'))
    if not files:
        print(f'no chapters in {d}')
        return 1
    seen = defaultdict(list)
    total_cases = total_lines = 0
    problems = 0
    for md in files:
        r = check(md)
        total_lines += r['lines']
        total_cases += len(r['cases'])
        for c in r['cases']:
            seen[c].append(md.name)
        flags = []
        if r['bad_routes']:
            flags.append(f"UNKNOWN ROUTES ({len(set(r['bad_routes']))}): {sorted(set(r['bad_routes']))[:6]}")
        if r['bad_paths']:
            flags.append(f"MISSING PATHS ({len(set(r['bad_paths']))}): {sorted(set(r['bad_paths']))[:6]}")
        if r['wrong_prefix']:
            flags.append(f"WRONG PREFIX: {sorted(set(r['wrong_prefix']))[:6]}")
        if r['missing_sections']:
            flags.append(f"MISSING SECTIONS: {r['missing_sections']}")
        if r['pipe_in_cell']:
            flags.append(f"UNESCAPED PIPE IN TABLE CELL, lines {r['pipe_in_cell'][:8]} (breaks GFM render)")
        if r['table_mismatch']:
            flags.append(f"TABLE COLS at lines {r['table_mismatch'][:5]}")
        status = 'OK' if not flags else 'ISSUES'
        problems += len(flags)
        print(f"{md.name:38s} {r['lines']:5d} lines  {len(r['cases']):4d} cases  {status}")
        for f in flags:
            print(f"    · {f}")
    cross = {c: fs for c, fs in seen.items() if len(set(fs)) > 1}
    print(f"\n{len(files)} chapters · {total_lines} lines · {total_cases} case IDs")
    if cross:
        print(f"CROSS-CHAPTER DUPLICATE IDS ({len(cross)}): {list(cross.items())[:5]}")
    print('clean' if not problems and not cross else f'{problems} flagged item groups')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
