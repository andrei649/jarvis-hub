#!/usr/bin/env python3
"""Assemble hermes_inv/sections/*.md into docs/research/hermes-inventory-v2026.8.31/ (README index + per-shard files + i18n coverage appendix)."""
import json, re, glob, os, sys, datetime
INV = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
ORDER = ['cli-a','cli-b','cli-c','cli-d','cli-e','cli-f','gw-slash','gw-core','platform-telegram','platforms-a','platforms-b',
         'web-shell','web-a','web-b','web-c','desktop-main','desktop-a','desktop-b','desktop-settings','tui',
         'config-a','config-b','env-vars','tools','skills-core','optional','providers','agent-core-a','agent-core-b','memory',
         'automation','security','media','acp-mcp-dev','docs-features','docs-rest','delta-27-31']
files = {os.path.basename(p)[:-3]: p for p in glob.glob(INV + '/sections/*.md')}
gap = sorted(k for k in files if k.startswith('gapfill-'))
other = sorted(k for k in files if k not in ORDER and k not in gap)
seq = [k for k in ORDER if k in files] + other + gap
def title_of(p):
    for line in open(p, encoding='utf-8'):
        if line.startswith('# '): return line[2:].strip()
    return os.path.basename(p)
def entries_of(p):
    return re.findall(r'^### (.+?)\s+`id: ([^`]+)`', open(p, encoding='utf-8').read(), re.M)
# copy sections
matrix = []; toc = []
for i, k in enumerate(seq, 1):
    src = files[k]; dst = f'{OUT}/{i:02d}-{k}.md'
    body = open(src, encoding='utf-8').read()
    open(dst, 'w', encoding='utf-8').write(body if body.endswith('\n') else body + '\n')
    ents = entries_of(src)
    matrix.append((i, k, title_of(src), len(ents), os.path.getsize(src)))
    toc.append((i, k, title_of(src), [(n, eid) for n, eid in ents]))
# i18n coverage appendix
def norm(s):
    s = re.sub(r'\{\{?[^}]*\}\}?', ' ', s); s = re.sub(r'<[^<>\n]{1,80}>', ' ', s); s = s.lower()
    s = re.sub(r'[^a-z0-9\u00c0-\u024f\u0400-\u04ff\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af ]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()
sec_norm = {}; sec_raw = {}
for k in seq:
    t = open(files[k], encoding='utf-8').read(); sec_raw[k] = t; sec_norm[k] = norm(t)
def where(key, text):
    n = norm(text); hits = []
    for k in seq:
        if key and key in sec_raw[k]: hits.append(k); continue
        if n and len(n) >= 4 and n in sec_norm[k]: hits.append(k); continue
        if n and len(n) < 4 and re.search(r'(^| )' + re.escape(n) + r'( |$)', sec_norm[k]): hits.append(k)
    return hits
cov_lines = []; totals = {}
for cp in sorted(glob.glob(INV + '/strings_chunks/*_[0-9][0-9].json')):
    cat = re.sub(r'_\d+\.json$', '', os.path.basename(cp))
    for it in json.load(open(cp, encoding='utf-8')):
        txt = it['text'] if isinstance(it['text'], str) else json.dumps(it['text'], ensure_ascii=False)
        hits = where(it['key'], txt)
        t = totals.setdefault(cat, [0, 0]); t[0] += 1; t[1] += bool(hits)
        safe = txt.replace('|', '\\|').replace(chr(10), ' ')[:120]
        cover = ', '.join(hits[:3]) if hits else '**MISSING**'
        cov_lines.append('| `' + cat + '` | `' + it['key'] + '` | ' + safe + ' | ' + cover + ' |')
with open(f'{OUT}/appendix-i18n-coverage.md', 'w', encoding='utf-8') as f:
    f.write('# Appendix — every UI string mapped to the inventory section that covers it\n\n')
    f.write('Generated mechanically by `check_strings.py` logic: a string is covered when its i18n key appears in a section, or its normalised text appears (substring ≥4 chars / whole word <4).\n\n')
    f.write('| Catalog | Strings | Covered |\n|---|---:|---:|\n')
    for c, (n, cv) in totals.items(): f.write(f'| {c} | {n} | {cv} ({cv*100//max(n,1)}%) |\n')
    f.write('\n| Catalog | Key | Text | Covered by |\n|---|---|---|---|\n' + '\n'.join(cov_lines) + '\n')
# README index
summary = open(INV + '/summary_ro.md', encoding='utf-8').read() if os.path.exists(INV + '/summary_ro.md') else '_(summary pending)_\n'
live = open(INV + '/live_tests.md', encoding='utf-8').read() if os.path.exists(INV + '/live_tests.md') else ''
with open(f'{OUT}/README.md', 'w', encoding='utf-8') as f:
    f.write('# Hermes Agent v2026.8.31 — exhaustive feature & UI inventory (reverse-engineering reference)\n\n')
    f.write(f'> Generated 2026-09-05/06 from a live install of `NousResearch/hermes-agent` at tag `v2026.8.31` (package `hermes-agent` 0.21.0, MIT). Evidence and method below. Total entries: **{sum(m[3] for m in matrix)}** across {len(matrix)} sections.\n\n')
    f.write(summary + '\n')
    f.write('## Coverage matrix\n\n| # | Section | Title | Entries | Size |\n|---:|---|---|---:|---:|\n')
    for i, k, t, n, sz in matrix: f.write(f'| {i} | [{k}]({i:02d}-{k}.md) | {t} | {n} | {sz//1024} KB |\n')
    f.write('\n### UI-string coverage (mechanical)\n\n| Catalog | Strings | Covered |\n|---|---:|---:|\n')
    for c, (n, cv) in totals.items(): f.write(f'| {c} | {n} | {cv} ({cv*100//max(n,1)}%) |\n')
    f.write('\nFull per-string mapping: [appendix-i18n-coverage.md](appendix-i18n-coverage.md).\n\n')
    f.write(live + '\n')
    f.write('## Table of contents (every entry)\n\n')
    for i, k, t, ents in toc:
        f.write(f'### {i:02d} · {t}\n\n')
        for n, eid in ents: f.write(f'- {n} — `{eid}`\n')
        f.write('\n')
print(json.dumps({'sections': len(seq), 'entries': sum(m[3] for m in matrix), 'totals': totals}, indent=1))
