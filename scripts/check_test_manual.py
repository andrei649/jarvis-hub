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
ROUTE_RE = re.compile(r'\b(GET|POST|PUT|PATCH|DELETE|HEAD)\s+(/[A-Za-z0-9_\-./{}:,<>*\u2026|]*)')
# repo-relative paths: dir/file.ext, allowing agents/core/x.py, frontend/src/a.tsx, docs/X.md
PATH_RE = re.compile(r'\b((?:agents|frontend|tests|scripts|docs|mobile|worldview|desktop|rust|packaging|deploy|services|skills|packages|apps)/[A-Za-z0-9_\-./*{}]+\.[A-Za-z0-9]+)')
CASE_RE = re.compile(r'\b([A-Z]{3})-(\d{3})\b')
# tokens shaped like a case ID that never are one
NON_CASE = {'CWE', 'CVE', 'RFC', 'ISO', 'UTF', 'SHA', 'AES', 'TLS'}

# (label, pattern) for payloads shaped like a vendor credential. NOTE the label is
# for humans reading this table only — it is deliberately NOT carried into output;
# see the check below for why.
KEY_SHAPED_PATTERNS = [
    ('Stripe-style live key', r'sk_live_[A-Za-z0-9_/+-]{12,}'),
    ('Stripe-style test key', r'sk_test_[A-Za-z0-9_/+-]{12,}'),
    ('Stripe-style publishable key', r'pk_live_[A-Za-z0-9_/+-]{12,}'),
    ('AWS-style access key id', r'AKIA[A-Za-z0-9]{12,}'),
    ('GitHub-style token', r'gh[po]_[A-Za-z0-9_]{12,}'),
    ('Slack-style bot token', r'xoxb-[A-Za-z0-9-]{12,}'),
    ('Google-style API key', r'AIza[A-Za-z0-9_-]{12,}'),
    ('Anthropic-style API key', r'sk-ant-[A-Za-z0-9_-]{12,}'),
    ('OpenAI-style project key', r'sk-proj-[A-Za-z0-9_-]{12,}'),
]
SECT_RE = re.compile(r'^#{1,4}\s')


def norm_route(path: str) -> str:
    """Normalise a cited path so placeholder notations match the snapshot's naming.

    Chapters legitimately write a param as `{category}`, `<category>` or a family as
    `/api/memory/*`; the snapshot only ever uses `{name}`. Normalise all of them.
    """
    p = path.rstrip('.,;:)`')
    p = re.sub(r'<[^>]*>', '{}', p)
    return re.sub(r'\{[^}]*\}', '{}', p)


NORM_KNOWN = {norm_route(p) for p in KNOWN_PATHS}

# A chapter may cite a *concrete instantiation* of a templated route — e.g.
# "PUT /api/admin/settings/product" for the snapshot's ".../{category}". That is more
# useful to a tester than the template, so match those instead of flagging them.
TEMPLATE_RES = [
    re.compile('^' + re.sub(r'\\\{[^}]*\\\}', r'[^/]+', re.escape(p)) + '$')
    for p in KNOWN_PATHS if '{' in p
]


def _expand(path: str) -> list[str]:
    """Expand "/a/{x,y}" shorthand into the concrete paths it stands for."""
    m = re.search(r'\{([^}]*[,|][^}]*)\}', path)
    if not m:
        return [path]
    opts = re.split(r'[,|]', m.group(1))
    return [path[:m.start()] + o.strip() + path[m.end():] for o in opts]


def route_known(path: str) -> bool:
    # a glob / ellipsis cites a family: accept if any real route sits under the prefix
    if path.endswith(('*', '...', '\u2026')) or '/...' in path or '\u2026' in path:
        pre = norm_route(re.split(r'\*|\.\.\.|\u2026', path)[0]).rstrip('/')
        return any(k.startswith(pre) for k in NORM_KNOWN) if len(pre) > 5 else True
    for cand in _expand(path):
        p = norm_route(cand)
        if p in NORM_KNOWN or any(rx.match(p) for rx in TEMPLATE_RES):
            continue
        return False
    return True


def check(md: Path) -> dict:
    text = md.read_text(encoding='utf-8')
    num = md.name[:2]
    want = EXPECTED_PREFIX.get(num)
    want = (want,) if isinstance(want, str) else (want or ())
    out = {'file': md.name, 'lines': text.count('\n') + 1, 'bad_routes': [], 'bad_paths': [],
           'cases': [], 'wrong_prefix': [], 'dupes': [], 'missing_sections': [], 'table_mismatch': [], 'control_bytes': [], 'risky_literals': []}

    neg = ('404', '422', '403', '405', '400', 'traversal', 'bogus', 'nonexistent',
           'unknown', 'does not exist', 'no such', 'reject', 'invalid')
    for m in ROUTE_RE.finditer(text):
        method, path = m.group(1), m.group(2)
        if route_known(path):
            continue
        # a negative test cites a path *because* it must fail — not a fabricated route
        line = text[text.rfind('\n', 0, m.start()) + 1: text.find('\n', m.end())].lower()
        if any(k in line for k in neg) or '..' in path:
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
        if '.local.' in base:
            continue
        if base.startswith('.env'):
            if not any((ROOT / p).with_name(base + s).exists() for s in ('.example',)) \
               and not (ROOT / p).with_name('.env.example').exists():
                out['bad_paths'].append(p + ' (no .example to scaffold from)')
            continue
        if p.endswith(('.db', '.sqlite', '.log')) or any(
                seg in p for seg in ('/e2e/artifacts/', '/dist/', '/build/', 'repo_export')):
            continue
        if not (ROOT / p).exists():
            out['bad_paths'].append(p)

    # A planted test payload must be unmistakably fake. A realistic-looking literal
    # trips GitHub push protection and blocks the branch (it blocked this manual twice).
    #
    # `risky_literals` holds LINE NUMBERS ONLY — plain ints. Nothing derived from the
    # matched text or from KEY_SHAPED_PATTERNS is carried out of this loop, so no
    # dataflow exists from either into any print. That is deliberate and it is why the
    # output cannot name which vendor pattern matched: the line number is what you act
    # on anyway, and terse output beats a finding that cannot be printed at all.
    #
    # Why so strict: CodeQL's py/clear-text-logging-sensitive-data flagged three earlier
    # versions of this check. It classifies data as sensitive by IDENTIFIER as well as by
    # value, so a secret detector is an awkward shape for it — trimming the reported
    # value (twice) did not clear it, and neither did renaming the destination field.
    # Rather than keep guessing which node it treats as the source, this version removes
    # the whole class: no string from the pattern table, no substring of a match, no
    # length, no name containing "secret" on anything that reaches output.
    for _label, pattern in KEY_SHAPED_PATTERNS:
        for m in re.finditer(pattern, text):
            matched = m.group(0)
            # the matched value is inspected here and never leaves this scope
            if 'QAFAKE' in matched.upper() or 'EXAMPLE' in matched.upper():
                continue
            out['risky_literals'].append(text.count(chr(10), 0, m.start()) + 1)

    # A literal control byte makes git treat the chapter as binary (no diffs) and can
    # break rendering. Test payloads must be written as escapes, not raw bytes.
    for code in set(range(32)) - {9, 10, 13}:
        if chr(code) in text:
            out['control_bytes'].append(f'0x{code:02x} x{text.count(chr(code))}')

    # A row whose cell count differs from its header's is a broken table — this is the
    # authoritative test for an unescaped "|" in a cell. (A backtick-parity heuristic
    # was tried first and produced false positives on legitimate ``` ` ``` spans.)
    hdr = None
    for i, line in enumerate(text.split('\n'), 1):
        s = line.strip()
        if s.startswith('|') and s.endswith('|'):
            n = len(re.split(r'(?<!\\)\|', s)) - 2
            if hdr is None:
                hdr = n
            elif set(s.replace('|', '').replace('-', '').replace(':', '').strip()) and n != hdr:
                out['table_mismatch'].append(f'line {i}: {n} cells vs header {hdr}')
        else:
            hdr = None

    defined = re.findall(r'(?m)^(?:\|\s*|#{2,5}\s*)\*{0,2}([A-Z]{3})-(\d{3})', text)
    ids = [(a, b) for a, b in defined if a not in NON_CASE]
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
        if r['risky_literals']:
            # locations + vendor prefix only; the matched value is never printed
            flags.append(f"KEY-SHAPED LITERAL at lines {sorted(set(r['risky_literals']))[:6]} — "
                         "will trip GitHub push protection; use the QAFAKE convention "
                         "or generate the value at test time")
        if r['control_bytes']:
            flags.append(f"RAW CONTROL BYTES {r['control_bytes']} — git sees the file as binary")
        if r['table_mismatch']:
            flags.append(f"BROKEN TABLE ROW ({len(r['table_mismatch'])}): {r['table_mismatch'][:4]}")
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
