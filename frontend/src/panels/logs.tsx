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
import { Card, State, arr, inpS, mono, useApi } from '../panel-kit';

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
  if (level === 'DEBUG') return 'var(--ink-3)';
  return 'var(--ink)';
}

function Segmented({ label, options, value, onChange }: { label: string; options: any[]; value: any; onChange: (v: any) => void }) {
  return (
    <div role="group" aria-label={label} style={{ display: 'flex', gap: 2, alignItems: 'center' }}>
      <span style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', marginRight: 4 }}>{label}</span>
      {options.map((opt) => (
        <button key={String(opt)} className="tool-btn" aria-pressed={opt === value}
          onClick={() => onChange(opt)}
          style={{ padding: '2px 6px', opacity: opt === value ? 1 : 0.55 }}>{String(opt)}</button>
      ))}
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
        <label style={{ ...mono, fontSize: 10, color: 'var(--ink-3)' }}>
          File{' '}
          <select aria-label="File" value={file || d?.file || ''} style={inpS}
            onChange={(ev) => setFile(ev.target.value)} disabled={!files.length}>
            {files.map((f: any) => <option key={f.name} value={f.name}>{f.name}</option>)}
          </select>
        </label>
        <Segmented label="Level" options={LOG_LEVELS} value={level} onChange={setLevel} />
        <label style={{ ...mono, fontSize: 10, color: 'var(--ink-3)' }}>
          Component{' '}
          <select aria-label="Component" value={component} style={inpS}
            onChange={(ev) => setComponent(ev.target.value)}>
            <option value="">all</option>
            {componentOptions.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <Segmented label="Lines" options={LOG_LINES} value={lines} onChange={setLines} />
        <label style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', display: 'flex', gap: 4, alignItems: 'center' }}>
          <input type="checkbox" aria-label="Auto-refresh every 5 s" checked={live}
            onChange={(ev) => setLive(ev.target.checked)} />
          auto-refresh 5 s
        </label>
      </div>
      {refused && <div style={{ color: 'var(--amber)', fontSize: 12 }}>The log needs the admin token (Settings → admin token).</div>}
      {!refused && status === 400 && <div style={{ color: 'var(--amber)', fontSize: 12 }}>The hub refused the filter: {reason || e}</div>}
      {!refused && status !== 400 && <State e={e} loading={loading && !d} n={entries.length} />}
      {d?.note && <div role="note" style={{ fontSize: 12, color: d.enabled ? 'var(--ink-2)' : 'var(--amber)', margin: '6px 0' }}>{d.note}</div>}
      {d && !status && !d.note && !entries.length && <div style={{ fontSize: 12, color: 'var(--ink-2)' }}>No records match these filters.</div>}
      {!status && d?.truncated && (
        <div style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', margin: '4px 0' }}>
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
    </Card>
  );
}
