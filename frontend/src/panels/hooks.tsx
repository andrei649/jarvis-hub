/* Hooks — the owner's event hooks (G17 · H163, H021, H514, H408).

   A hook is a program the owner names that the hub runs on an agent event. The hub decides
   everything that matters (agents/core/hooks/): which commands are allowed (an absolute
   program, no launcher, a shell or interpreter only with a script file), what reaches the
   program (the event as JSON on stdin, never on its command line), and when it may run.

   - Adding a hook, or turning one back on, only queues an approval card that shows the
     exact command and the files' digests; it runs after the owner accepts it there.
   - Switching a hook off and removing it apply at once.
   - A tool.before hook may block a call; it can never allow one. A guard fails closed. */
import React, { useState } from 'react';
import { apiDelete, apiPost } from '../api/client';
import { Card, Tag, inpS, mono, refusalReason, useApi } from '../panel-kit';

export const HOOKS_PATH = '/api/hooks';

type Hook = {
  id: string; name: string; event: string; command: string; matcher: string | null; guard: boolean;
  timeout_s: number; status: 'pending' | 'active' | 'disabled'; task_id: number | null;
  binding_current: boolean | null; last_run: Run | null; pending_card: boolean;
};
type Run = { at: number; hook: string; event: string; outcome: string; reason: string | null;
  blocked: boolean; fail_open: boolean; ignored: string | null; duration_ms: number; test: boolean };
type EventSpec = { event: string; blocking: boolean; hermes: string; matcher: boolean; doc: string };
type Listing = { hooks: Hook[]; events: EventSpec[]; runs: Run[];
  status: { ready: boolean; blockers: string[]; max_timeout_s: number } };

const why = (err: any) => {
  const body = err?.body;
  if (body && typeof body === 'object' && typeof body.detail === 'string') return `${body.error}: ${body.detail}`;
  return refusalReason(err, String(err?.status || 'error'));
};

const BLOCKERS: Record<string, string> = {
  admin_credential_required: 'set an admin token first: without one any local program is trusted as the owner',
  safe_mode: 'safe mode is on: no hook runs',
  hooks_switched_off: 'JARVIS_HOOKS is off: no hook runs',
};

/** Split a typed command line into argv (quotes group words; nothing is ever run by a shell). */
export function splitArgv(line: string): string[] {
  const out: string[] = [];
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(line)) !== null) out.push(m[1] ?? m[2] ?? m[3]);
  return out;
}

export function HooksPanel() {
  const api = useApi(HOOKS_PATH, true, true);
  const data = api.d as Listing | null;
  const hooks: Hook[] = Array.isArray(data?.hooks) ? data!.hooks : [];
  const events: EventSpec[] = Array.isArray(data?.events) ? data!.events : [];
  const runs: Run[] = Array.isArray(data?.runs) ? data!.runs : [];
  const [event, setEvent] = useState('tool.before');
  const [command, setCommand] = useState('');
  const [matcher, setMatcher] = useState('');
  const [guard, setGuard] = useState(false);
  const [timeout, setTimeoutS] = useState('10');
  const [name, setName] = useState('');
  const [note, setNote] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const spec = events.find((e) => e.event === event);

  const done = (text: string) => { setErr(null); setNote(text); api.reload(); };
  const fail = (e: any) => { setNote(null); setErr(why(e)); };

  const add = () => {
    const argv = splitArgv(command.trim());
    if (!argv.length) return;
    const body: Record<string, unknown> = { event, argv, guard: spec?.blocking ? guard : false, name: name.trim() };
    if (spec?.matcher && matcher.trim()) body.matcher = matcher.trim();
    const t = Number(timeout);
    if (Number.isInteger(t) && t > 0) body.timeout_s = t;
    apiPost<any>(HOOKS_PATH, body, { admin: true })
      .then((r) => { setCommand(''); done(`approval card ${r.task_id} queued: accept it in the decision inbox to run this hook`); })
      .catch(fail);
  };
  const disable = (h: Hook) => apiPost(`/api/hooks/${h.id}/disable`, {}, { admin: true }).then(() => done(`${h.id} switched off`)).catch(fail);
  const enable = (h: Hook) => apiPost<any>(`/api/hooks/${h.id}/enable`, {}, { admin: true })
    .then((r) => done(`approval card ${r.task_id} queued to turn ${h.id} back on`)).catch(fail);
  const remove = (h: Hook) => apiDelete(`/api/hooks/${h.id}`, { admin: true }).then(() => done(`${h.id} removed`)).catch(fail);
  const test = (h: Hook) => apiPost<any>(`/api/hooks/${h.id}/test`, {}, { admin: true })
    .then((r) => done(`test run: ${r.run?.outcome}${r.run?.blocked ? ' · would block' : ''}${r.run?.reason ? ` · ${r.run.reason}` : ''}`))
    .catch(fail);

  const blockers = data?.status?.blockers || [];
  return (
    <Card title="HOOKS" sub="programs that run on agent events, each behind an approval card"
      live={data ? 'live' : undefined} onReload={api.reload}>
      {blockers.length > 0 && (
        <div role="alert" style={{ ...mono, color: 'var(--amber)', marginBottom: 6 }}>
          hooks cannot run here: {blockers.map((b) => BLOCKERS[b] || b).join(' · ')}
        </div>
      )}
      {err && <div role="alert" style={{ ...mono, color: 'var(--red)' }}>{err}</div>}
      {note && <div style={{ ...mono, color: 'var(--ink-2)' }}>{note}</div>}
      <div style={{ display: 'grid', gap: 4, margin: '6px 0' }}>
        {hooks.length === 0 && <div style={{ ...mono, color: 'var(--ink-2)' }}>no hooks</div>}
        {hooks.map((h) => (
          <div key={h.id} style={{ ...mono, borderTop: '1px solid var(--panel-line)', paddingTop: 4 }}>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
              <b>{h.name || h.id}</b><Tag>{h.event}</Tag>
              <Tag c={h.status === 'active' ? 'var(--green)' : 'var(--ink-2)'}>{h.status}</Tag>
              {h.guard && <Tag c="var(--amber)">guard · fails closed</Tag>}
              {h.matcher && <Tag>tools {h.matcher}</Tag>}
              {h.binding_current === false && <Tag c="var(--red)">files changed since approval · not running</Tag>}
              {h.pending_card && <Tag>card {h.task_id} waiting</Tag>}
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
                {h.status === 'active' && <button className="tool-btn" onClick={() => test(h)}>test</button>}
                {h.status === 'active' && <button className="tool-btn" onClick={() => disable(h)}>switch off</button>}
                {h.status === 'disabled' && <button className="tool-btn" onClick={() => enable(h)}>turn on…</button>}
                <button className="tool-btn" onClick={() => remove(h)} aria-label={`remove ${h.id}`}>remove</button>
              </span>
            </div>
            <div style={{ color: 'var(--ink-2)', wordBreak: 'break-all' }}>{h.command}</div>
            {h.last_run && <div style={{ color: 'var(--ink-2)' }}>last run: {h.last_run.outcome}{h.last_run.reason ? ` (${h.last_run.reason})` : ''}</div>}
          </div>
        ))}
      </div>
      <div style={{ display: 'grid', gap: 4, borderTop: '1px solid var(--panel-line)', paddingTop: 6 }}>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          <select aria-label="event" value={event} onChange={(e) => setEvent(e.target.value)} style={inpS}>
            {(events.length ? events : [{ event: 'tool.before' } as EventSpec]).map((e) => <option key={e.event} value={e.event}>{e.event}</option>)}
          </select>
          <input aria-label="name" placeholder="name" value={name} onChange={(e) => setName(e.target.value)} style={inpS} />
          {spec?.matcher && <input aria-label="tool matcher" placeholder="tools (glob, optional)" value={matcher}
            onChange={(e) => setMatcher(e.target.value)} style={inpS} />}
          <input aria-label="timeout seconds" value={timeout} onChange={(e) => setTimeoutS(e.target.value)} style={{ ...inpS, width: 50 }} />
          {spec?.blocking && <label style={mono}><input type="checkbox" checked={guard} onChange={(e) => setGuard(e.target.checked)} /> guard (block if it fails)</label>}
        </div>
        {spec && <div style={{ ...mono, color: 'var(--ink-2)' }}>{spec.doc} (Hermes: {spec.hermes})</div>}
        <div style={{ display: 'flex', gap: 4 }}>
          <input aria-label="command" placeholder="/usr/bin/python3 /home/me/hooks/guard.py" value={command}
            onChange={(e) => setCommand(e.target.value)} style={{ ...inpS, flex: 1 }} />
          <button className="tool-btn" onClick={add} disabled={!command.trim()}>ask to add</button>
        </div>
      </div>
      {runs.length > 0 && (
        <div style={{ marginTop: 6 }}>
          <div style={{ ...mono, color: 'var(--ink-2)' }}>recent runs</div>
          {runs.slice(-10).reverse().map((r, i) => (
            <div key={i} style={{ ...mono, color: 'var(--ink-2)' }}>
              {new Date(r.at * 1000).toLocaleTimeString()} · {r.hook} · {r.event} · {r.outcome}
              {r.blocked ? ' · blocked' : ''}{r.fail_open ? ' · failed open' : ''}{r.reason ? ` · ${r.reason}` : ''}{r.test ? ' · test' : ''}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
