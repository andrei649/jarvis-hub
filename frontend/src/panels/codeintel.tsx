/* CODE INTEL — the 0.31 read-only AST symbol index (agents/core/routers/codeintel.py),
   which shipped with three user-reachable routes and no client that ever called them.

   Four honesty problems this panel exists to NOT reproduce:

   1. `count` is len(results) AFTER the limit slice (search_payload, codeintel.py:35), so
      "50" can mean "exactly 50" or "the first 50 of thousands" and the API cannot tell you
      which. When count === the requested limit we say "showing first N · capped" instead
      of "N matches".
   2. An empty `q` returns count:0 BY CONSTRUCTION (index.py:100 returns [] for a falsy
      query). That is a not-asked state, not a negative result — so no request is issued
      until a query is committed, and the panel says "enter a symbol substring".
   3. `_SKIP_DIRS` (index.py:22) skips ".venv"/"venv"/"env" but not this repo's actual
      virtualenv dir ".venv312", so most of the index is third-party site-packages.
      `symbol_count` is therefore NOT a project-size number and is never labelled one.
   4. The index is one level deep. `_symbols_in_source` (index.py:44-59) iterates `tree.body`
      only, plus one pass over each module-level class body, so nested defs, closures, defs
      inside a module-level if/try/with and classes nested in classes are never indexed —
      measured on agents/ alone, 267 of 6,007 defs are missing, and searching one of them
      (e.g. a closure defined inside a factory function) returns count:0. A zero-result search
      is therefore NOT evidence that a name is absent from the repo, and the panel must never
      render the shared bare "nothing yet" for it.

   There is NO component guard and NO 503 anywhere in this router: the only non-200s are
   401/403 (auth), 429 (rate limit), 422 (limit outside [1,500] — unreachable here, the
   selector offers in-range values only) and the generic 500. So this panel never renders
   an "index unavailable" state — the backend cannot produce one. apiGet throws WITHOUT a
   body, so a failed read shows the verbatim `GET <path> -> <status>` and nothing more:
   the panel literally cannot see the backend's detail string on a GET and must not guess.
   apiPost DOES carry the refusal body, so reindex renders err.body verbatim. */
import React, { useState } from 'react';
import { useApi, arr, mono, asLive, Card, State, Row, Tag, actA, inpS } from '../panel-kit';

const STATS_PATH = '/api/codeintel/stats';
const SEARCH_PATH = '/api/codeintel/search';
const REINDEX_PATH = '/api/codeintel/reindex';

const LIMITS = [25, 50, 100, 200, 500];
/* Locale-independent thousands separator — no Intl dependency, same string everywhere. */
const fmt = (n) => (Number.isFinite(Number(n)) ? String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ',') : '—');
/* A hit is vendored when it lives under a dot-dir at the repo root (".venv312/…") or in a
   site-packages tree. It is TAGGED, never hidden: hiding rows while showing the backend's
   unfiltered `count` would misstate the result set. */
const isVendored = (f) => typeof f === 'string' && (f.startsWith('.') || f.includes('site-packages/'));

export function CodeIntelPanel() {
  const [draft, setDraft] = useState('');
  const [submitted, setSubmitted] = useState('');   // committed query — '' means "not asked"
  const [kind, setKind] = useState('');             // '' = no filter (backend echoes null)
  const [limit, setLimit] = useState(50);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);

  const stats = useApi(STATS_PATH);                 // user tier
  const s = stats.d;

  /* useApi refires whenever `path` changes, so a path built from `draft` would launch a
     full 53k-symbol scan per keystroke. The query is committed into `submitted` first, and
     auto stays false until then — changing kind/limit afterwards refires, which is right. */
  const searchPath = SEARCH_PATH
    + '?q=' + encodeURIComponent(submitted)
    + '&kind=' + encodeURIComponent(kind)
    + '&limit=' + limit;
  const hits = useApi(searchPath, submitted !== '');
  const h = submitted !== '' ? hits.d : null;
  const results = arr(h, 'results');

  /* by_kind OMITS kinds with zero symbols — iterate its own entries, never a fixed table. */
  const kinds = s && s.by_kind && typeof s.by_kind === 'object'
    ? (Object.entries(s.by_kind) as [string, any][]).sort((a, b) => Number(b[1]) - Number(a[1]))
    : [];
  const errs = arr(s, 'errors');
  const capped = !!h && Number(h.count) === Number(limit);
  const vendored = results.filter((r) => isVendored(r && r.file)).length;

  const commit = () => {
    const q = draft.trim();
    if (!q) return;
    if (q === submitted) hits.reload();   // same query → path unchanged, so refire by hand
    else setSubmitted(q);
  };

  const reloadAll = () => { stats.reload(); if (submitted) hits.reload(); };

  /* Admin write. `ok` in the response is a hardcoded literal `true` (codeintel.py:60), so
     branching on it would make the refused branch dead code — a 401/403 would render as a
     silent success. The refusal arrives through onErr instead, and its four distinct causes
     (admin-token 401 detail / network-disabled 403 detail / 429 error / 500 message) are
     printed verbatim, never collapsed into one sentence. */
  const reindex = () => {
    if (busy) return;
    const prev = s ? { files_indexed: s.files_indexed, symbol_count: s.symbol_count } : null;
    setBusy(true);
    setNote(null);
    actA(REINDEX_PATH, {},
      (r) => {
        setBusy(false);
        setNote({ kind: 'ok', text: prev
          ? `reindexed · files ${fmt(prev.files_indexed)} → ${fmt(r && r.files_indexed)} · symbols ${fmt(prev.symbol_count)} → ${fmt(r && r.symbol_count)}`
          : `reindexed · ${fmt(r && r.files_indexed)} files · ${fmt(r && r.symbol_count)} symbols` });
        stats.reload();               // reindex returns only 2 of the 4 stats keys
        if (submitted) hits.reload();  // else post-reindex counts would sit beside pre-reindex rows
      },
      (err) => {
        setBusy(false);
        const b = err && err.body;
        const cause = (b && (b.detail || b.message || b.error)) || (err && err.message) || 'reindex failed';
        setNote({ kind: 'err', text: `refused · ${(err && err.status) || '?'} · ${cause}` });
      });
  };

  return (
    <Card
      title="CODE INTEL"
      live={asLive(s)}
      sub={s ? `${fmt(s.files_indexed)} files · ${fmt(s.symbol_count)} symbols indexed` : null}
      onReload={reloadAll}
    >
      {/* apiGet throws without a body — this message is all the panel can honestly know. */}
      <State e={stats.e} loading={stats.loading} n={s ? 1 : 0} />

      {s && (
        <>
          <Row>
            <span style={{ ...mono, color: 'var(--ink-2)' }}>index</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap' }}>
              <Tag>{fmt(s.files_indexed)} files</Tag>
              <Tag>{fmt(s.symbol_count)} symbols</Tag>
              {kinds.map(([k, v]) => <Tag key={k}>{k} {fmt(v)}</Tag>)}
            </span>
          </Row>

          {/* Non-empty `errors` is the signal that matters: those files' symbols are absent
              from the index, so every search under-reports. Hidden when errors is []. */}
          {errs.length > 0 && (
            <>
              <Row>
                <span style={{ ...mono, color: 'var(--amber)' }}>
                  {errs.length} file(s) failed to parse — their symbols are MISSING from the index, so search under-reports
                </span>
              </Row>
              {errs.slice(0, 8).map((er, i) => (
                <Row key={(er && er.file) || i}>
                  <span style={{ ...mono, color: 'var(--ink-3)' }}>{er && er.file}</span>
                  <span style={{ marginLeft: 'auto' }}><Tag c="var(--amber)">{er && er.error}</Tag></span>
                </Row>
              ))}
              {errs.length > 8 && (
                <div style={{ fontSize: 10, color: 'var(--ink-3)' }}>+{errs.length - 8} more not shown</div>
              )}
            </>
          )}
        </>
      )}

      <div style={{ fontSize: 10, color: 'var(--ink-3)', margin: '6px 0' }}>
        <div>
          <b>Directory scope</b> — every *.py under the repo root except .git/.hg/.svn/__pycache__/
          .venv/venv/env/node_modules/.mypy_cache/.pytest_cache/.ruff_cache/build/dist
          (agents/core/codeintel/index.py:22). This repo's virtualenv is <b>.venv312</b>, which is NOT on
          that skip list — measured 2026-09-01, 37,220 of 53,641 indexed symbols came from .venv312
          site-packages. So these counts are "*.py under the repo root", not the size of Nerva's own
          code. Every hit shows its path.
        </div>
        {/* The scope that actually bites on this repo. The directory caveat above INFLATES the
            counts; this one DEFLATES them, and unlike the parse-error warning (errors was [] when
            measured) it fires on every search. */}
        <div style={{ marginTop: 4 }}>
          <b>Symbol scope</b> — the indexer reads only the top level of each file
          (agents/core/codeintel/index.py:44-59): module-level functions and classes, plus the methods
          written directly in a module-level class body. Anything nested deeper is absent from the index
          and can never be found here — inner functions and closures, defs inside a module-level
          if/try/with, classes nested in classes. Measured 2026-09-01 over this repo's own agents/ tree:
          6,007 function/async defs exist, 5,740 are indexed — 267 are invisible to this search.
        </div>
      </div>

      <Row>
        <input
          value={draft}
          onChange={(ev) => setDraft(ev.target.value)}
          onKeyDown={(ev) => { if (ev.key === 'Enter') commit(); }}
          placeholder="symbol substring (e.g. build_index)"
          style={{ ...inpS, flex: 1, minWidth: 120 }}
        />
        <select value={kind} onChange={(ev) => setKind(ev.target.value)} style={inpS} title="kind filter">
          <option value="">all kinds</option>
          {kinds.map(([k, v]) => <option key={k} value={k}>{k} ({fmt(v)})</option>)}
        </select>
        <select value={limit} onChange={(ev) => setLimit(Number(ev.target.value))} style={inpS} title="result limit">
          {LIMITS.map((n) => <option key={n} value={n}>limit {n}</option>)}
        </select>
        <button className="tool-btn" onClick={commit} disabled={!draft.trim()}>search</button>
      </Row>

      {submitted === '' ? (
        <div style={{ fontSize: 12, color: 'var(--ink-3)', padding: '5px 0' }}>
          enter a symbol substring to search — nothing has been asked yet
        </div>
      ) : (
        <>
          {/* The shared zero-state reads "nothing yet", which an operator takes as "no such
              symbol in this repo". For THIS index that is not what zero means (see Symbol scope),
              so the empty case is rendered below with its caveat instead of through State. */}
          <State e={hits.e} loading={hits.loading} n={h && results.length > 0 ? results.length : null} />
          {h && results.length === 0 && (
            <div style={{ fontSize: 12, color: 'var(--amber)', padding: '5px 0' }}>
              0 indexed symbols matched — that is not proof the name is absent from the repo. The index
              holds only module-level functions/classes and the methods directly in a class body, so a
              nested def or a closure with this name would match nothing here even though it exists.
            </div>
          )}
          {h && (
            <Row>
              {/* Labelled with the ECHOED query, so a stale render can never claim results
                  belong to a query they don't. */}
              <span style={{ ...mono, color: 'var(--ink-2)' }}>
                results for "{String(h.query)}"{h.kind ? ` · kind ${h.kind}` : ''}
              </span>
              <span style={{ marginLeft: 'auto' }}>
                {capped
                  ? <Tag c="var(--amber)">showing first {fmt(h.count)} · capped at limit {limit}, more matches may exist</Tag>
                  : <Tag>{fmt(h.count)} match(es)</Tag>}
              </span>
            </Row>
          )}
          {h && vendored > 0 && (
            <div style={{ fontSize: 10, color: 'var(--ink-3)' }}>
              {vendored} of {results.length} shown are vendored third-party code — tagged, not hidden,
              so this list always matches the count above.
            </div>
          )}
          {results.map((r, i) => (
            <Row key={`${r && r.file}:${r && r.lineno}:${r && r.qualname}:${i}`}>
              <span style={{ ...mono, color: 'var(--accent-light)' }}>{r && r.qualname}</span>
              <Tag>{r && r.kind}</Tag>
              <span style={{ ...mono, color: 'var(--ink-3)' }}>{r && r.file}:{r && r.lineno}</span>
              {r && r.doc
                ? <span style={{ fontSize: 10, color: 'var(--ink-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.doc}</span>
                : null}
              {isVendored(r && r.file) && <span style={{ marginLeft: 'auto' }}><Tag>vendored</Tag></span>}
            </Row>
          ))}
        </>
      )}

      <Row>
        <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>
          rebuild this process's cached index (full repo walk — 3.4k files)
        </span>
        <button
          className="tool-btn" style={{ marginLeft: 'auto' }} onClick={reindex} disabled={busy}
          title="reindex (admin)"
        >{busy ? 'reindexing…' : 'reindex (admin)'}</button>
      </Row>
      {note && (
        <div role="alert" style={{ ...mono, marginTop: 6, color: note.kind === 'err' ? 'var(--red)' : 'var(--green)' }}>
          {note.text}
        </div>
      )}

      <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>
        Reads are user-tier (X-User-Token); reindex is admin-tier (X-Admin-Token). Reindex reassigns
        one in-process cache — nothing is persisted, nothing propagates to another worker, and a
        restart rebuilds it lazily on first use. The index is not watching the filesystem: it is only
        as fresh as the last reindex or restart. It returns structure only — names, kinds, paths,
        line numbers and one docstring line — never file contents.
      </div>
    </Card>
  );
}
