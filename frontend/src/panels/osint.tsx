/* OSINT — the P2 investigator pack (agents/core/routers/osint.py). Both routes shipped
   user-reachable with no client that ever called them.

   What this panel is NOT allowed to imply, checked against the handlers:

   1. /api/osint/correlate and /api/osint/brief FETCH NOTHING. They are pure functions of
      the body (correlate.py:143 / :196) — no network, no store, no action. Live collection
      (SpiderFoot, news feeds) is owner-gated wiring, not reachable from
      here, and nothing survives a reload. So the evidence editor is the real, designed input:
      `_TRUSTED_EVIDENCE_SOURCES = {"manual", "operator"}` (correlate.py:33) are labels that
      exist ONLY for a human typing evidence — no agent path posts to these HTTP routes.
   2. Trust is exact, not fuzzy: `_is_untrusted_evidence_source` (correlate.py:41) taints
      anything whose label is not literally "manual" or "operator", and a blank source is
      rewritten to "osint:unknown" (correlate.py:36) and therefore tainted. The panel names
      those two labels and no others.
   3. `untrusted_ingestion: true` is a flag on a READ. writeback_payload / the kernel's
      GRANT→QUEUE escalation live on other call paths (correlate.py:217) — nothing here is
      queued, escalated, gated or written back, and the panel never says otherwise.
   4. `top` is the brief size. /api/osint/correlate declares it and never uses it
      (osint.py:39-43 ignores body.top), so the input says so instead of implying it applies.
   5. The correlator SILENTLY DROPS rows whose kind or value is empty after trim
      (_coerce, correlate.py:99) — pydantic has no min_length, so there is no 422 and no
      error. The only trace is counts.evidence < rows sent, which is why this panel sends
      only complete rows and still compares the two numbers.
   6. Every `headline` on screen is the backend's own string, printed verbatim. There is no
      client-composed headline and no fallback prose.
   7. Both routes are user-tier (user_guard) — nothing here is admin.

   apiPost throws on 4xx and carries the parsed body, so both POST buttons pass onErr and the
   refusal is rendered from the backend's own body (422 detail array, 401/403 detail string,
   429 error, 500 message) — never collapsed into one invented sentence, and never left
   sitting beside a stale success drawer. */
import React, { useState } from 'react';
import { arr, mono, note, asLive, Card, Row, Tag, act, inpS, taS, Json } from '../panel-kit';
import { LABEL } from '../theme/type';

const CORRELATE_PATH = '/api/osint/correlate';
const BRIEF_PATH = '/api/osint/brief';
/* pydantic max_length per EvidenceItem field (osint.py:24-30). Enforced on the inputs so a
   422 is designed out instead of being explained after the fact. */
const CAP = { source: 64, kind: 32, value: 512, observed_at: 40, url: 1024, detail: 2000 };
const MAX_ROWS = 2000;   // CorrelateBody.evidence max_length (osint.py:34)

const blankRow = () => ({ source: '', kind: '', value: '', observed_at: '', url: '', detail: '' });

const clampInt = (v, lo, hi, dflt) => {
  const n = Number(v);
  if (!Number.isFinite(n)) return dflt;
  return Math.min(hi, Math.max(lo, Math.trunc(n)));
};
const num = (v) => (Number.isFinite(Number(v)) ? String(Number(v)) : '—');

/* The refusal, straight from the wire. `detail` is a string for 401/403 and an array of
   {loc,msg,type} objects for a 422; `error` carries the rate limit, `message` the generic
   500. Whatever the body holds is shown as-is; nothing is mapped, renamed or merged. */
function Refusal({ err, path }: { err: any; path: string }) {
  const b = (err && err.body) || null;
  const line =
    b && typeof b.detail === 'string' ? b.detail
    : b && typeof b.message === 'string' ? b.message
    : b && typeof b.error === 'string' ? b.error
    : null;
  const structured =
    b && b.detail != null && typeof b.detail !== 'string' ? b.detail
    : (b && line == null ? b : null);
  return (
    <div role="alert" style={{ marginTop: 6, padding: 6, border: '1px solid var(--amber)', borderRadius: 4 }}>
      <div style={{ ...note, color: 'var(--amber)' }}>
        refused · HTTP {(err && err.status) || '?'} · POST {path}
      </div>
      {line != null && <div style={{ ...note, color: 'var(--ink-2)', marginTop: 4 }}>{line}</div>}
      {structured != null && <Json v={structured} />}
      {line == null && structured == null && (
        <div style={{ ...note, color: 'var(--ink-2)', marginTop: 4 }}>
          {(err && err.message) || 'request failed'} (the response carried no readable body)
        </div>
      )}
    </div>
  );
}

export function OsintPanel() {
  /* ── Card A state: the evidence drawer ─────────────────────────────────── */
  const [rows, setRows] = useState([blankRow()]);
  const [detailOpen, setDetailOpen] = useState<number | null>(null);
  const [top, setTop] = useState(8);
  const [busy, setBusy] = useState<string | null>(null);
  const [out, setOut] = useState<any>(null);
  const [openF, setOpenF] = useState<number | null>(null);

  const setRow = (i, k, v) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const addRow = () => setRows((rs) => (rs.length >= MAX_ROWS ? rs : [...rs, blankRow()]));
  const dropRow = (i) => setRows((rs) => (rs.length <= 1 ? [blankRow()] : rs.filter((_, j) => j !== i)));

  /* Rows missing kind or value are not sent: the correlator would drop them with no error
     at all (_coerce), so they would vanish into a lower counts.evidence and look like data. */
  const sendable = rows
    .map((r) => ({ ...r, kind: r.kind.trim(), value: r.value.trim() }))
    .filter((r) => r.kind !== '' && r.value !== '');
  /* An untouched row is not a mistake — only a row carrying content that still lacks
     kind or value is worth flagging, because that one WOULD have vanished server-side. */
  const touched = rows.filter((r) => Object.keys(r).some((k) => String(r[k]).trim() !== ''));
  const incomplete = touched.length - sendable.length;

  const run = (path, view) => {
    if (busy || sendable.length === 0) return;
    setBusy(view);
    setOut(null);          // a refusal must never sit next to the previous success
    setOpenF(null);
    act(path, { evidence: sendable, top },
      (r) => { setBusy(null); setOut({ view, path, d: r, sent: sendable.length, err: null }); },
      (err) => { setBusy(null); setOut({ view, path, d: null, sent: sendable.length, err }); });
  };

  const d = out && out.d;
  const counts = d && d.counts && typeof d.counts === 'object' ? d.counts : null;
  const findings = out ? (out.view === 'brief' ? arr(d, 'top') : arr(d, 'findings')) : [];
  const dropped = out && counts && Number.isFinite(Number(counts.evidence))
    ? out.sent - Number(counts.evidence) : 0;

  return (
    <>
      <Card
        title="OSINT"
        live={asLive(d)}
        sub={out ? (out.err ? 'refused' : `${out.view} · ${sendable.length} row(s) sent`) : 'offline correlator — correlates what you type'}
      >
        <div style={{ fontSize: 'var(--n-fs-meta)', color: 'var(--ink-2)', marginBottom: 6 }}>
          Evidence drawer. Each row is one observation; rows sharing a kind + value correlate into one
          finding with its provenance chain and a corroboration score. kind and value are required —
          a row missing either is dropped by the correlator with no error, so it is not sent.
        </div>

        {rows.map((r, i) => (
          <div key={i} style={{ borderBottom: '1px solid var(--panel-line)', padding: '5px 0' }}>
            <div style={{ display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap' }}>
              <input
                style={{ ...inpS, width: 96 }} value={r.source} maxLength={CAP.source}
                placeholder="source" aria-label={`source ${i + 1}`}
                onChange={(e) => setRow(i, 'source', e.target.value)}
              />
              <input
                style={{ ...inpS, width: 78 }} value={r.kind} maxLength={CAP.kind}
                placeholder="kind *" aria-label={`kind ${i + 1}`}
                onChange={(e) => setRow(i, 'kind', e.target.value)}
              />
              <input
                style={{ ...inpS, flex: 1, minWidth: 120 }} value={r.value} maxLength={CAP.value}
                placeholder="value *" aria-label={`value ${i + 1}`}
                onChange={(e) => setRow(i, 'value', e.target.value)}
              />
              <input
                style={{ ...inpS, width: 96 }} value={r.observed_at} maxLength={CAP.observed_at}
                placeholder="observed_at" aria-label={`observed_at ${i + 1}`}
                onChange={(e) => setRow(i, 'observed_at', e.target.value)}
              />
              <input
                style={{ ...inpS, width: 120 }} value={r.url} maxLength={CAP.url}
                placeholder="url" aria-label={`url ${i + 1}`}
                onChange={(e) => setRow(i, 'url', e.target.value)}
              />
              <button
                className="tool-btn" style={{ fontSize: 'var(--n-fs-meta)', padding: '1px 5px' }}
                title="detail" onClick={() => setDetailOpen(detailOpen === i ? null : i)}
              >detail</button>
              <button
                className="tool-btn" style={{ fontSize: 'var(--n-fs-meta)', padding: '1px 5px' }}
                title="remove row" onClick={() => dropRow(i)}
              >×</button>
            </div>
            {detailOpen === i && (
              <textarea
                style={{ ...taS, minHeight: 46, marginTop: 4 }} value={r.detail} maxLength={CAP.detail}
                placeholder="detail (free text, max 2000)" aria-label={`detail ${i + 1}`}
                onChange={(e) => setRow(i, 'detail', e.target.value)}
              />
            )}
          </div>
        ))}

        <Row>
          <button className="tool-btn" onClick={addRow} disabled={rows.length >= MAX_ROWS}>+ row</button>
          <span style={{ ...note, color: 'var(--ink-2)' }}>{sendable.length} sendable</span>
          {incomplete > 0 && (
            <span style={{ ...note, color: 'var(--amber)' }}>
              {incomplete} row(s) with content but no kind/value — not sent (the correlator drops
              those without an error)
            </span>
          )}
        </Row>

        <div style={{ fontSize: 'var(--n-fs-meta)', color: 'var(--ink-2)', margin: '6px 0' }}>
          Trust rule, verbatim from the backend: only the source label "manual" or "operator" is
          trusted. Every other label is tainted at ingestion, and a blank source is rewritten to
          "osint:unknown" and is tainted too. No other label is neutral.
        </div>

        <Row>
          <span style={{ ...LABEL, fontSize: 'var(--n-fs-meta)', color: 'var(--ink-2)' }}>top</span>
          <input
            type="number" min={1} max={100} value={top} aria-label="brief size"
            style={{ ...inpS, width: 64 }}
            onChange={(e) => setTop(clampInt(e.target.value, 1, 100, 8))}
          />
          <span style={{ fontSize: 'var(--n-fs-meta)', color: 'var(--ink-2)' }}>
            brief size (1–100) — used by {BRIEF_PATH} only; {CORRELATE_PATH} declares this field and ignores it
          </span>
        </Row>

        <Row>
          <button
            className="tool-btn" disabled={!!busy || sendable.length === 0}
            title={CORRELATE_PATH}
            onClick={() => run(CORRELATE_PATH, 'correlate')}
          >{busy === 'correlate' ? 'correlating…' : 'correlate'}</button>
          <button
            className="tool-btn" disabled={!!busy || sendable.length === 0}
            title={BRIEF_PATH}
            onClick={() => run(BRIEF_PATH, 'brief')}
          >{busy === 'brief' ? 'briefing…' : 'brief (top-N)'}</button>
          {sendable.length === 0 && (
            <span style={{ fontSize: 'var(--n-fs-meta)', color: 'var(--ink-2)', marginLeft: 'auto' }}>
              fill kind and value on at least one row
            </span>
          )}
        </Row>

        {out && out.err && <Refusal err={out.err} path={out.path} />}

        {out && d && (
          <>
            <Row>
              <Tag c="var(--accent-light)">{out.view === 'brief' ? 'view: brief' : 'view: correlate'}</Tag>
              <span style={{ ...mono, color: 'var(--ink-2)' }}>{out.path}</span>
              {d.untrusted_ingestion === true && (
                <span style={{ marginLeft: 'auto' }}><Tag c="var(--amber)">UNTRUSTED INGESTION</Tag></span>
              )}
            </Row>

            {/* The backend's own headline. /api/osint/correlate emits none, so none is shown there. */}
            {out.view === 'brief' && typeof d.headline === 'string' && (
              <div style={{ ...note, color: 'var(--ink)', margin: '6px 0' }}>{d.headline}</div>
            )}

            {counts && (
              <Row>
                <span style={{ ...note, color: 'var(--ink-2)' }}>
                  evidence {num(counts.evidence)} · findings {num(counts.findings)} ·
                  {' '}corroborated {num(counts.corroborated)} · tainted {num(counts.tainted)}
                </span>
              </Row>
            )}

            {dropped > 0 && (
              <div style={{ ...note, color: 'var(--amber)', marginTop: 4 }}>
                {dropped} of {out.sent} row(s) sent were dropped by the correlator (kind or value empty
                after trim) — it reports no error for this, counts.evidence is the only trace
              </div>
            )}

            {d.untrusted_ingestion === true && (
              <div style={{ fontSize: 'var(--n-fs-meta)', color: 'var(--ink-2)', marginTop: 4 }}>
                at least one finding is backed by a source that is not "manual"/"operator". This is a
                flag on this read only — this route stores nothing, submits nothing and actions nothing.
              </div>
            )}

            {findings.length === 0
              ? <div style={{ ...note, color: 'var(--ink-2)', marginTop: 6 }}>0 findings returned</div>
              : findings.map((f, i) => (
                <div key={`${f && f.kind}:${f && f.value}:${i}`}>
                  <Row>
                    <button
                      className="tool-btn" style={{ fontSize: 'var(--n-fs-meta)', padding: '1px 5px' }}
                      title="provenance" onClick={() => setOpenF(openF === i ? null : i)}
                    >{openF === i ? '−' : '+'}</button>
                    <span style={{ ...mono, color: 'var(--accent-light)' }}>{f && f.kind}:{f && f.value}</span>
                    <Tag>conf {num(f && f.confidence)}</Tag>
                    <Tag>×{num(f && f.count)}</Tag>
                    {f && f.tainted === true && <Tag c="var(--amber)">TAINTED</Tag>}
                    {f && Array.isArray(f.sources) && f.sources.length > 1 && <Tag c="var(--green)">corroborated</Tag>}
                    <span style={{ ...mono, color: 'var(--ink-2)', marginLeft: 'auto' }}>
                      {(f && Array.isArray(f.sources) ? f.sources : []).join(', ') || '—'}
                    </span>
                  </Row>
                  {openF === i && <Json v={f && f.provenance} />}
                </div>
              ))}

            {out.view === 'brief' && counts && Number(counts.findings) > findings.length && (
              <div style={{ ...note, color: 'var(--ink-2)', marginTop: 4 }}>
                showing top {findings.length} of {num(counts.findings)} indicator(s)
              </div>
            )}
          </>
        )}

        <div style={{ fontSize: 'var(--n-fs-meta)', color: 'var(--ink-2)', marginTop: 6 }}>
          User-tier POST (X-User-Token), not admin. {CORRELATE_PATH} and {BRIEF_PATH} correlate only the
          evidence typed above: they never fetch, never store and never act, so nothing survives a reload
          and nothing here is queued, escalated or written back. Live collection (SpiderFoot, news feeds) is owner-gated wiring and is not reachable from this panel. The brief view calls
          the correlator internally, so its counts are the same numbers over the same drawer — only the
          headline and the top-N truncation are new.
        </div>
      </Card>
    </>
  );
}
