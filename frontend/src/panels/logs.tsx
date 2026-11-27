/* H145 — the hub's own log, read from the cockpit.

   When something misbehaves (a channel adapter crash-looping, a provider refusing
   every call), the audit chain says what Nerva decided and the traces say how it
   routed; neither is the process log, and reading it used to need a shell on the box.
   This panel tails it through the admin-only GET /api/admin/logs: the log file or one
   of its rotations, newest records first, filtered by File, Level (a floor: WARNING
   shows WARNING, ERROR and CRITICAL), Component (a logger and its children) and Lines.

   The hub reads the file backwards within a byte budget, returns at most 500 records,
   keeps a traceback with its error and masks secrets again as it reads, so what is
   shown here is what the redactor lets through. Auto-refresh re-reads every 5 s while
   it is on and the page is visible (a tick is skipped while a read is in flight), with the
   card's LIVE badge while the hub is writing its file. When file logging is off (the
   default) the panel says how to turn it on instead of showing an empty log. */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { apiGet } from '../api/client';
import { Card, Row, State, Tag, arr, inpS, mono, note, refusalReason, useApi } from '../panel-kit';
import { LABEL } from '../theme/type';

export const LOG_LEVELS = ['ALL', 'INFO', 'WARNING', 'ERROR'];
export const LOG_LINES = [100, 200, 500];
export const REFRESH_MS = 5000;

/** The query the panel sends: only the filters that narrow something. */
export function logsPath(f: { file?: string; level?: string; component?: string; lines?: number }): string {
  const q = new URLSearchParams();
  if (f.file) q.set('file', f.file);
  if (f.level && f.level !== 'ALL') q.set('level', f.level);
  if (f.component) q.set('component', f.component);
  q.set('lines', String(f.lines || 200));
  return `/api/admin/logs?${q.toString()}`;
}

/** A record's colour by its level; a line with no level is plain. */
export function levelColor(level: string): string {
  if (level === 'ERROR' || level === 'CRITICAL') return 'var(--red)';
  if (level === 'WARNING') return 'var(--amber)';
  if (level === 'DEBUG') return 'var(--ink-2)';
  return 'var(--ink)';
}

function Segmented({ label, options, value, onChange }: { label: string; options: any[]; value: any; onChange: (v: any) => void }) {
  return (
    <div role="group" aria-label={label} style={{ display: 'flex', gap: 2, alignItems: 'center' }}>
      <span style={{ ...LABEL, fontSize: 'var(--n-fs-meta)', color: 'var(--ink-2)', marginRight: 4 }}>{label}</span>
      {options.map((opt) => (
        <button key={String(opt)} className={'tool-btn' + (opt === value ? ' on' : '')} aria-pressed={opt === value}
          onClick={() => onChange(opt)}
          style={{ padding: '2px 6px' }}>{String(opt)}</button>
      ))}
    </div>
  );
}

function ToolEventsDisclosure() {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [refused, setRefused] = useState(false);
  const [query, setQuery] = useState('');
  const [data, setData] = useState<{ events: any[]; counts: Record<string, number> } | null>(null);

  const load = () => {
    setBusy(true);
    setErr(null);
    setRefused(false);
    apiGet<{ events?: any[]; counts?: Record<string, number> }>('/api/admin/tool-events?limit=100', { admin: true })
      .then((res) => {
        setData({
          events: Array.isArray(res?.events) ? res.events : [],
          counts: res?.counts && typeof res.counts === 'object' ? res.counts : {},
        });
        setBusy(false);
      })
      .catch((x: any) => {
        setData(null);
        setBusy(false);
        if (x?.status === 401 || x?.status === 403) {
          setRefused(true);
          return;
        }
        setErr(refusalReason(x, String(x?.message || 'load_failed')));
      });
  };

  const toggle = () => {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    load();
  };

  const needle = query.trim().toLowerCase();
  const rows = (data?.events || []).slice().reverse().filter((ev) => {
    if (!needle) return true;
    const hay = `${ev?.event || ''} ${ev?.tool || ''} ${ev?.status || ''} ${ev?.reason || ''}`.toLowerCase();
    return hay.includes(needle);
  });
  const countEntries = Object.entries(data?.counts || {}).sort(([a], [b]) => a.localeCompare(b));

  return (
    <div style={{ marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--panel-line)' }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <button className="tool-btn" type="button" onClick={toggle}>
          {open ? 'Hide tool trail' : 'Tool loop trail'}
        </button>
        {open && (
          <>
            <button className="tool-btn" type="button" disabled={busy} onClick={load}>
              Refresh trail
            </button>
            <input
              aria-label="Filter tool trail"
              placeholder="filter event or tool…"
              value={query}
              onChange={(ev) => setQuery(ev.target.value)}
              style={{ ...inpS, flex: '1 1 160px', minWidth: 120 }}
            />
          </>
        )}
      </div>
      {open && refused && (
        <div style={{ color: 'var(--amber)', fontSize: 'var(--n-fs-label)', marginTop: 6 }}>
          The tool trail needs the admin token (Settings → admin token).
        </div>
      )}
      {open && !refused && err && (
        <div role="status" style={{ color: 'var(--amber)', fontSize: 'var(--n-fs-label)', marginTop: 6 }}>
          Could not load tool trail: {err}
        </div>
      )}
      {open && !refused && !err && data && (
        <div style={{ marginTop: 6 }}>
          {countEntries.length > 0 && (
            <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginBottom: 6 }}>
              {countEntries.map(([k, v]) => (
                <Tag
                  key={k}
                  c={k === 'tool_failed' || k === 'tool_cap_reached'
                    ? 'var(--red)'
                    : k === 'tool_result_untrusted' || k.startsWith('tool_loop_')
                      ? 'var(--amber)'
                      : 'var(--ink-2)'}
                >
                  {k}: {v}
                </Tag>
              ))}
            </div>
          )}
          {rows.length === 0 ? (
            <div style={{ fontSize: 'var(--n-fs-label)', color: 'var(--ink-2)' }}>
              No tool events recorded since boot.
            </div>
          ) : (
            <div data-testid="tool-trail-records" style={{ maxHeight: 240, overflow: 'auto' }}>
              {rows.slice(0, 50).map((ev: any, idx: number) => (
                <Row key={`${ev.seq ?? idx}`}>
                  <span style={{ ...mono, fontSize: 'var(--n-fs-meta)', color: 'var(--ink-2)' }}>
                    #{ev.seq ?? idx} {ev.event || 'unknown'}{ev.tool ? ` · ${ev.tool}` : ''}
                  </span>
                  <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
                    {ev.status && <Tag c={ev.status === 'error' || ev.status === 'failed' ? 'var(--red)' : 'var(--ink-2)'}>{String(ev.status)}</Tag>}
                    {ev.reason && <span style={{ ...note, fontSize: 'var(--n-fs-meta)', color: 'var(--ink-2)' }}>{String(ev.reason)}</span>}
                  </span>
                </Row>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function LogsPanel() {
  const [file, setFile] = useState('');
  const [level, setLevel] = useState('ALL');
  const [component, setComponent] = useState('');
  const [lines, setLines] = useState(200);
  const [live, setLive] = useState(false);
  const path = useMemo(() => logsPath({ file, level, component, lines }), [file, level, component, lines]);
  const { d, e, status, refusal, loading, reload } = useApi(path, true, true);
  const refused = status === 401 || status === 403;
  const reason = refusal && typeof refusal === 'object' ? (refusal as any).reason : '';

  // A tick is skipped while a read is still in flight, so slow reads never stack, and
  // polling stops while the hub refuses the credential (review-H145 m5, nit 5).
  const busy = useRef(false);
  useEffect(() => { if (!loading) busy.current = false; }, [loading]);
  useEffect(() => {
    if (!live || refused) return undefined;
    const timer = setInterval(() => {
      if (busy.current) return;
      if (typeof document === 'undefined' || !document.hidden) { busy.current = true; reload(); }
    }, REFRESH_MS);
    return () => clearInterval(timer);
  }, [live, refused, reload]);

  // A file the hub no longer lists (a rotation removed) goes back to the current log.
  useEffect(() => {
    if (status === 400 && file && /file/.test(String(reason))) setFile('');
  }, [status, reason, file]);

  const files = arr(d?.files);
  // After a refusal the last answer is another request's: its records are not shown
  // under the new filter (review-H145 m8).
  const entries = status ? [] : arr(d?.entries);
  const components: string[] = arr(d?.components);
  const componentOptions = component && !components.includes(component) ? [component, ...components] : components;
  const showLive = live && !refused && !status && !!d?.enabled;

  return (
    <Card title="Hub log" sub={d?.file ? `${d.file} · newest first` : 'the hub’s own log'}
      live={showLive ? 'live' : undefined} onReload={reload}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', marginBottom: 8 }}>
        <label style={{ ...LABEL, fontSize: 'var(--n-fs-meta)', color: 'var(--ink-2)' }}>
          File{' '}
          <select aria-label="File" value={file || d?.file || ''} style={inpS}
            onChange={(ev) => setFile(ev.target.value)} disabled={!files.length}>
            {files.map((f: any) => <option key={f.name} value={f.name}>{f.name}</option>)}
          </select>
        </label>
        <Segmented label="Level" options={LOG_LEVELS} value={level} onChange={setLevel} />
        <label style={{ ...LABEL, fontSize: 'var(--n-fs-meta)', color: 'var(--ink-2)' }}>
          Component{' '}
          <select aria-label="Component" value={component} style={inpS}
            onChange={(ev) => setComponent(ev.target.value)}>
            <option value="">all</option>
            {componentOptions.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <Segmented label="Lines" options={LOG_LINES} value={lines} onChange={setLines} />
        <label style={{ ...note, fontSize: 'var(--n-fs-meta)', color: 'var(--ink-2)', display: 'flex', gap: 4, alignItems: 'center' }}>
          <input type="checkbox" aria-label="Auto-refresh every 5 s" checked={live}
            onChange={(ev) => setLive(ev.target.checked)} />
          auto-refresh 5 s
        </label>
      </div>
      {refused && <div style={{ color: 'var(--amber)', fontSize: 'var(--n-fs-label)' }}>The log needs the admin token (Settings → admin token).</div>}
      {!refused && status === 400 && <div style={{ color: 'var(--amber)', fontSize: 'var(--n-fs-label)' }}>The hub refused the filter: {reason || e}</div>}
      {!refused && status !== 400 && <State e={e} loading={loading && !d} n={entries.length} />}
      {d?.note && <div role="note" style={{ fontSize: 'var(--n-fs-label)', color: d.enabled ? 'var(--ink-2)' : 'var(--amber)', margin: '6px 0' }}>{d.note}</div>}
      {d && !status && !d.note && !entries.length && <div style={{ fontSize: 'var(--n-fs-label)', color: 'var(--ink-2)' }}>No records match these filters.</div>}
      {!status && d?.truncated && (
        <div style={{ ...note, fontSize: 'var(--n-fs-meta)', color: 'var(--ink-2)', margin: '4px 0' }}>
          only the last {Math.round(Number(d.scanned_bytes || 0) / 1024)} KiB of the file were read
        </div>
      )}
      <div data-testid="log-records" style={{ maxHeight: 520, overflow: 'auto' }}>
        {entries.slice().reverse().map((entry: any, i: number) => (
          <pre key={`${entry.ts}-${i}`} data-level={entry.level || 'NONE'}
            style={{ ...mono, margin: 0, padding: '2px 0', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                     color: levelColor(entry.level), borderBottom: '1px solid var(--panel-line)' }}>
            {entry.text}
          </pre>
        ))}
      </div>
      <ToolEventsDisclosure />
    </Card>
  );
}
