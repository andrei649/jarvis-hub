/* HUD v2 · ARTIFACTS — saved-response workspace over the governed Agent Canvas
   (H12.18 backend). The cockpit gets a third center tab that lists Canvas
   elements from GET /api/canvas and lets the owner pin/unpin/delete them, plus
   an explicit per-message save control that posts a completed assistant reply
   as a `markdown` element through the unchanged POST /api/canvas/post contract.

   Safety posture (the whole point of the governed canvas):
   - every type renders through React text nodes — no dangerouslySetInnerHTML,
     no iframes, no script/HTML pass-through; unknown markup stays literal text;
   - same-origin images (single leading '/', never '//' or '/\') render
     directly; remote http(s) images sit behind an explicit consent click and
     load with referrerPolicy="no-referrer";
   - nothing here auto-saves — a reply is persisted only on a user click. */
import React, { useCallback, useEffect, useState } from 'react';
import { apiGet, apiPost, apiDelete } from './api/client';

/* Canvas bounds Markdown bodies to 4,000 chars (agents/core/canvas.py). Send no
   more than the backend keeps, and disclose visibly when the copy was cut. */
export const MARKDOWN_LIMIT = 4000;

const I18N = {
  en: {
    tab: 'Artifacts',
    loading: 'Loading artifacts…',
    empty: 'No artifacts yet — save an assistant reply from the conversation, or let an agent post to the canvas.',
    loadError: 'Couldn’t load artifacts.',
    retry: 'retry',
    refresh: 'refresh',
    pin: 'pin', unpin: 'unpin', del: 'delete',
    pinError: '⚠ pin change failed — the element may have been removed; refresh and try again.',
    delError: '⚠ delete failed — refresh and try again.',
    loadRemote: 'Remote image — click to load',
    save: '⬒ save', saving: 'saving…', saved: '✓ saved',
    savedTrunc: '✓ saved · truncated to 4,000 chars',
    saveError: '⚠ save failed — retry',
    saveTitle: 'save to artifacts',
  },
  ro: {
    tab: 'Artefacte',
    loading: 'Se încarcă artefactele…',
    empty: 'Niciun artefact încă — salvează un răspuns al asistentului din conversație, sau lasă un agent să posteze pe canvas.',
    loadError: 'Artefactele nu au putut fi încărcate.',
    retry: 'reîncearcă',
    refresh: 'reîmprospătează',
    pin: 'fixează', unpin: 'defixează', del: 'șterge',
    pinError: '⚠ fixarea a eșuat — elementul poate a fost șters; reîmprospătează și reîncearcă.',
    delError: '⚠ ștergerea a eșuat — reîmprospătează și reîncearcă.',
    loadRemote: 'Imagine externă — clic pentru a o încărca',
    save: '⬒ salvează', saving: 'se salvează…', saved: '✓ salvat',
    savedTrunc: '✓ salvat · trunchiat la 4.000 caractere',
    saveError: '⚠ salvarea a eșuat — reîncearcă',
    saveTitle: 'save to artifacts',
  },
};
const labels = (lang) => I18N[lang === 'ro' ? 'ro' : 'en'];
export function artifactsTabLabel(lang) { return labels(lang).tab; }

/* ── URL classification (mirrors the backend _safe_url discipline) ──────────
   Browsers strip ASCII TAB/LF/CR from a URL before parsing, so "/<TAB>/host"
   resolves to "//host" (protocol-relative, cross-origin). Normalize the same
   way before classifying AND before rendering, so a control-char URL can't be
   smuggled past the same-origin branch into an ungated <img>/<a>. New backend
   data is already clean; this also covers elements posted before the fix. */
function cleanUrl(u) { return String(u || '').replace(/[\t\n\r]/g, ''); }
function isSameOriginPath(u) {
  const s = cleanUrl(u);
  return s.startsWith('/') && !s.startsWith('//') && !s.startsWith('/\\');
}
function isRemoteHttp(u) { return /^https?:\/\//i.test(cleanUrl(u)); }

/* ── tiny React-only Markdown renderer (headings, bold, inline code, lists) ──
   Anything else — raw HTML included — stays literal text, which is the safety
   property the tests pin. */
function renderInline(text) {
  const parts = String(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((p, i) =>
    p.startsWith('**') && p.endsWith('**') && p.length > 4
      ? <b key={i}>{p.slice(2, -2)}</b>
      : p.startsWith('`') && p.endsWith('`') && p.length > 2
        ? <code key={i}>{p.slice(1, -1)}</code>
        : p);
}
function MarkdownBody({ body }) {
  const out = [];
  let list = [];
  const flush = (k) => {
    if (!list.length) return;
    out.push(<ul key={'ul' + k}>{list.map((it, j) => <li key={j}>{renderInline(it)}</li>)}</ul>);
    list = [];
  };
  String(body || '').split(/\r?\n/).forEach((ln, i) => {
    const li = ln.match(/^\s*[-*]\s+(.*)$/);
    if (li) { list.push(li[1]); return; }
    flush(i);
    const h = ln.match(/^(#{1,3})\s+(.*)$/);
    if (h) out.push(<div key={i} className={'art-h art-h' + h[1].length}>{renderInline(h[2])}</div>);
    else if (ln.trim()) out.push(<div key={i} className="art-line">{renderInline(ln)}</div>);
  });
  flush('end');
  return <div className="art-md">{out}</div>;
}

/* Remote images stay behind an explicit consent click; loading uses
   no-referrer so the page URL never leaks to the remote host. */
function ImageRefBody({ payload, L }) {
  const [consented, setConsented] = useState(false);
  const src = cleanUrl(payload.src);
  const alt = String(payload.alt || payload.title || 'artifact image');
  if (isSameOriginPath(src)) return <img className="art-img" src={src} alt={alt} loading="lazy" />;
  if (!isRemoteHttp(src)) return <div className="art-plain">{src}</div>;  // inert (e.g. //host)
  if (!consented) {
    let host = ''; try { host = new URL(src).host; } catch { /* keep empty */ }
    return (
      <button className="art-consent" onClick={() => setConsented(true)}>
        {L.loadRemote}{host ? ` (${host})` : ''}
      </button>
    );
  }
  return <img className="art-img" src={src} alt={alt} referrerPolicy="no-referrer" loading="lazy" />;
}

function LinkBody({ payload }) {
  const url = cleanUrl(payload.url);
  const label = String(payload.label || payload.title || url);
  if (!isSameOriginPath(url) && !isRemoteHttp(url)) {
    return <div className="art-plain">{label}{label !== url ? ` · ${url}` : ''}</div>;
  }
  return <a className="art-link" href={url} target="_blank" rel="noopener noreferrer">{label} ↗</a>;
}

function ArtifactBody({ el, L }) {
  const p = el.payload || {};
  switch (el.type) {
    case 'text':
      return (<>
        {p.title && <div className="art-title">{p.title}</div>}
        <div className="art-plain">{p.body}</div>
      </>);
    case 'markdown':
      return (<>
        {p.title && <div className="art-title">{p.title}</div>}
        <MarkdownBody body={p.body} />
      </>);
    case 'list':
      return (<>
        {p.title && <div className="art-title">{p.title}</div>}
        <ul className="art-md">{(p.items || []).map((it, i) => <li key={i}>{String(it)}</li>)}</ul>
      </>);
    case 'link':
      return <LinkBody payload={p} />;
    case 'metric':
      return (
        <div className="art-metric">
          <span className="art-mlabel">{p.label}</span>
          <span className="art-mvalue">{p.value}</span>
          {p.delta && <span className="art-mdelta">{p.delta}</span>}
        </div>
      );
    case 'table':
      return (<>
        {p.title && <div className="art-title">{p.title}</div>}
        <div className="art-table-wrap">
          <table className="art-table">
            {Array.isArray(p.columns) && p.columns.length > 0 && (
              <thead><tr>{p.columns.map((c, i) => <th key={i}>{String(c)}</th>)}</tr></thead>
            )}
            <tbody>
              {(p.rows || []).map((r, i) => (
                <tr key={i}>{(Array.isArray(r) ? r : []).map((c, j) => <td key={j}>{String(c)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      </>);
    case 'image_ref':
      return (<>
        {p.title && <div className="art-title">{p.title}</div>}
        <ImageRefBody payload={p} L={L} />
      </>);
    default:
      // future/unknown types stay inert: a JSON snapshot as plain text
      return <div className="art-plain">{JSON.stringify(p)}</div>;
  }
}

function fmtWhen(ts) {
  const n = Number(ts);
  if (!isFinite(n) || n <= 0) return '—';
  try { return new Date(n * 1000).toLocaleString(); } catch { return '—'; }
}

function ArtifactCard({ el, L, onPin, onDelete }) {
  return (
    <div className="art-card" data-type={el.type}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="art-head">
        <span className="art-agent">{String(el.agent || 'agent').toUpperCase()}</span>
        <span className="art-type">{el.type}</span>
        {el.pinned && <span className="art-pin-badge">◆ pinned</span>}
        <span className="art-ts">{fmtWhen(el.created_at)}</span>
      </div>
      <div className="art-body"><ArtifactBody el={el} L={L} /></div>
      <div className="art-actions">
        <button className="tool-btn" onClick={() => onPin(el)}>{el.pinned ? L.unpin : L.pin}</button>
        <button className="tool-btn danger" onClick={() => onDelete(el)}>{L.del}</button>
      </div>
    </div>
  );
}

/* ── the Artifacts center-tab panel ──────────────────────────────────────── */
function ArtifactsPanel({ refreshKey = 0, lang }: { refreshKey?: number; lang?: string }) {
  const L = labels(lang);
  const [els, setEls] = useState<any[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true); setLoadErr(null); setActionErr(null);
    apiGet('/api/canvas')
      .then((r: any) => { setEls(Array.isArray(r?.elements) ? r.elements : []); setLoading(false); })
      .catch(() => { setLoadErr(L.loadError); setLoading(false); });
  }, [L.loadError]);
  useEffect(() => { load(); }, [load, refreshKey]);

  const togglePin = (el) => {
    const want = !el.pinned;
    apiPost(`/api/canvas/${encodeURIComponent(el.id)}/pin?pinned=${want}`)
      .then((updated: any) => {
        setActionErr(null);
        const pinned = updated && typeof updated.pinned === 'boolean' ? updated.pinned : want;
        setEls((cur) => (cur || []).map((e) => (e.id === el.id ? { ...e, pinned } : e)));
      })
      .catch(() => setActionErr(L.pinError));
  };
  const remove = (el) => {
    apiDelete(`/api/canvas/${encodeURIComponent(el.id)}`)
      .then(() => { setActionErr(null); setEls((cur) => (cur || []).filter((e) => e.id !== el.id)); })
      .catch(() => setActionErr(L.delError));
  };

  return (
    <div className="artifacts">
      <div className="art-toolbar">
        <span className="art-count">
          {els !== null && !loading && !loadErr ? `${els.length} artifact${els.length === 1 ? '' : 's'}` : ''}
        </span>
        <button className="tool-btn" onClick={load} title="refresh artifacts">↻ {L.refresh}</button>
      </div>
      {actionErr && <div className="art-note err" role="alert">{actionErr}</div>}
      {loading ? (
        <div className="art-note">{L.loading}</div>
      ) : loadErr ? (
        <div className="art-note err" role="alert">
          {loadErr} <button className="tool-btn" onClick={load}>{L.retry}</button>
        </div>
      ) : !els || els.length === 0 ? (
        <div className="art-note">{L.empty}</div>
      ) : (
        <div className="art-list">
          {els.map((el) => <ArtifactCard key={el.id} el={el} L={L} onPin={togglePin} onDelete={remove} />)}
        </div>
      )}
    </div>
  );
}

/* ── explicit save-response control (rendered per completed assistant reply) ──
   Never auto-fires: state machine idle → saving (click-locked) → saved /
   saved·truncated / error (retryable). Posts the exact unchanged canvas
   contract with the ACTUAL responding agent. */
function SaveArtifactButton({ message, onSaved, lang }: { message: any; onSaved?: () => void; lang?: string }) {
  const L = labels(lang);
  const [state, setState] = useState('idle'); // idle | saving | saved | saved-trunc | error

  const save = () => {
    if (state === 'saving' || state === 'saved' || state === 'saved-trunc') return;
    const full = String((message && message.text) || '');
    if (!full) return;
    // Truncate on a code-point boundary so an astral char at the limit is never
    // split into a lone UTF-16 surrogate (which would poison the canvas store on
    // its UTF-8 write). Matches the backend's code-point [:4000] bound.
    const cps = Array.from(full);
    const truncated = cps.length > MARKDOWN_LIMIT;
    const body = truncated ? cps.slice(0, MARKDOWN_LIMIT).join('') : full;
    setState('saving');
    apiPost('/api/canvas/post', {
      agent: String((message && message.who) || 'jarvis'),
      type: 'markdown',
      payload: { title: 'Saved response', body },
      pinned: false,
    }).then(() => {
      setState(truncated ? 'saved-trunc' : 'saved');
      if (onSaved) onSaved();
    }).catch(() => setState('error'));
  };

  const label = state === 'saving' ? L.saving
    : state === 'saved' ? L.saved
    : state === 'saved-trunc' ? L.savedTrunc
    : state === 'error' ? L.saveError
    : L.save;
  const cls = 'art-save' + (state === 'saved' || state === 'saved-trunc' ? ' ok' : state === 'error' ? ' err' : '');
  return (
    <button className={cls} onClick={save} disabled={state === 'saving'}
      title={L.saveTitle} aria-label={L.saveTitle}>
      {label}
    </button>
  );
}

export { ArtifactsPanel, SaveArtifactButton };
