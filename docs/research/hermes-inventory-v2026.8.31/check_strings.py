#!/usr/bin/env python3
"""Mechanical coverage check: is every i18n string of a chunk present in hermes_inv/sections/*.md?
Usage: check_strings.py <chunk.json> [--all]  -> JSON {chunk, checked, covered, uncovered:[{key,text,catalog}]}
A string is covered if its i18n key appears verbatim in any section file, or its normalised text
(placeholders/tags stripped, lowercase, punctuation→space) appears as a substring (len>=4) / whole word (len<4)."""
import json, re, sys, glob, os
INV = os.path.dirname(os.path.abspath(__file__))
def norm(s):
    s = re.sub(r'\{\{?[^}]*\}\}?', ' ', s); s = re.sub(r'<[^<>\n]{1,80}>', ' ', s); s = s.lower()
    s = re.sub(r'[^a-z0-9À-ɏЀ-ӿ一-鿿぀-ヿ가-힯 ]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()
raw = ''
for f in sorted(glob.glob(INV + '/sections/*.md')):
    raw += '\n' + open(f, encoding='utf-8').read()
union = norm(raw)
def check(chunk_path):
    chunk = json.load(open(chunk_path, encoding='utf-8'))
    cat = re.sub(r'_\d+\.json$', '', os.path.basename(chunk_path))
    unc = []
    for it in chunk:
        k = it['key']; txt = it['text'] if isinstance(it['text'], str) else json.dumps(it['text'], ensure_ascii=False)
        n = norm(txt)
        if k and k in raw: continue
        if not n: continue
        if len(n) >= 4 and n in union: continue
        if len(n) < 4 and re.search(r'(^| )' + re.escape(n) + r'( |$)', union): continue
        unc.append({'key': k, 'text': txt[:300], 'catalog': cat})
    return {'chunk': os.path.basename(chunk_path), 'checked': len(chunk), 'covered': len(chunk) - len(unc), 'uncovered': unc}
if '--all' in sys.argv:
    res = [check(p) for p in sorted(glob.glob(INV + '/strings_chunks/*_[0-9][0-9].json'))]
    tot = sum(r['checked'] for r in res); cov = sum(r['covered'] for r in res)
    print(json.dumps({'total': tot, 'covered': cov, 'uncovered_total': tot - cov, 'per_chunk': [{k: v for k, v in r.items() if k != 'uncovered'} for r in res]}, indent=1))
else:
    print(json.dumps(check(sys.argv[1]), ensure_ascii=False, indent=1))
