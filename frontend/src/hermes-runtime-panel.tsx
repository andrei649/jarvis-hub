import React, { useEffect, useState } from 'react';

import { apiFetchOnce, getAdminToken } from './api/client';
import { appUrl } from './base-path';

type RuntimeStatus = {
  enabled: boolean;
  ready: boolean;
  source_sha?: string;
  generation?: string;
  pid?: number;
  reason?: string | null;
};

type Method = { name: string; summary?: string; risk_tier?: string; params?: unknown };
type Catalog = { source_sha?: string; methods?: Method[] };
type Frame = Record<string, unknown>;
type ServerRequest = Frame & { id: string | number; method: string };
type ApprovalTask = {
  task_id: number;
  status: string;
  disposition?: string;
  operation?: string;
  target?: string;
  arguments?: unknown;
  risk_tier?: string;
  created_at?: string;
  expires_at?: string;
  result?: unknown;
  error?: unknown;
};
type ApprovalList = { tasks: ApprovalTask[]; total: number };

function decisionReady(task: ApprovalTask): boolean {
  return task.status === 'blocked' && task.disposition === 'queued';
}

const PROTOCOL = 'hermes-runtime-v1';
const MAX_LOG = 50;

async function readJson<T>(path: string, method: 'GET' | 'POST' = 'GET', body?: unknown): Promise<T> {
  const response = await apiFetchOnce(path, { method, body, admin: true });
  if (!response.ok) {
    let reason = '';
    try {
      const payload = await response.json();
      const detail = payload?.detail;
      reason = String(detail?.error || detail || payload?.error || '');
      if (typeof detail?.task_id === 'number') reason += ` · task ${detail.task_id}`;
      if (typeof detail?.disposition === 'string') reason += ` (${detail.disposition})`;
    } catch { /* non-JSON errors stay generic */ }
    throw new Error(reason || `Hermes request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

function parseObject(value: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value);
  if (parsed === null || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new Error('Arguments must be a JSON object');
  }
  return parsed as Record<string, unknown>;
}

function asSessions(value: unknown): Array<Record<string, unknown>> {
  const rows = Array.isArray(value) ? value : value && typeof value === 'object' && 'sessions' in value
    ? (value as { sessions?: unknown }).sessions : [];
  return Array.isArray(rows) ? rows.filter((row): row is Record<string, unknown> =>
    row !== null && typeof row === 'object' && !Array.isArray(row)) : [];
}

export function HermesRuntimePanel() {
  const [status, setStatus] = useState<RuntimeStatus | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [sessions, setSessions] = useState<Array<Record<string, unknown>>>([]);
  const [sessionsLoaded, setSessionsLoaded] = useState(false);
  const [method, setMethod] = useState('session.list');
  const [argumentsText, setArgumentsText] = useState('{}');
  const [result, setResult] = useState<unknown>(null);
  const [events, setEvents] = useState<Frame[]>([]);
  const [requests, setRequests] = useState<ServerRequest[]>([]);
  const [replyText, setReplyText] = useState('{}');
  const [replyKind, setReplyKind] = useState<'result' | 'error'>('result');
  const [socket, setSocket] = useState<WebSocket | null>(null);
  const [streamState, setStreamState] = useState('offline');
  const [streamRetry, setStreamRetry] = useState(0);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [approvals, setApprovals] = useState<ApprovalTask[]>([]);
  const [approvalsLoaded, setApprovalsLoaded] = useState(false);
  const [approvalBusy, setApprovalBusy] = useState<number | null>(null);
  const [approvalNotice, setApprovalNotice] = useState('');

  useEffect(() => {
    let alive = true;
    readJson<RuntimeStatus>('/api/hermes/status')
      .then((nextStatus) => { if (alive) setStatus(nextStatus); })
      .catch((exc: unknown) => { if (alive) setError(String(exc)); });
    readJson<Catalog>('/api/hermes/catalog')
      .then((nextCatalog) => {
        if (!alive) return;
        setCatalog(nextCatalog);
        if (nextCatalog.methods?.length) setMethod(nextCatalog.methods[0].name);
      })
      .catch((exc: unknown) => { if (alive) setError(String(exc)); });
    readJson<ApprovalList>('/api/hermes/approvals')
      .then((next) => {
        if (!alive) return;
        setApprovals(Array.isArray(next.tasks) ? next.tasks : []);
        setApprovalsLoaded(true);
      })
      .catch((exc: unknown) => { if (alive) setError(String(exc)); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!status?.ready || typeof WebSocket === 'undefined') return;
    let disposed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    const endpoint = new URL(appUrl('/api/hermes/ws'), window.location.href);
    endpoint.protocol = endpoint.protocol === 'https:' ? 'wss:' : 'ws:';
    const token = getAdminToken();
    const protocols = [PROTOCOL];
    if (token && /^[A-Za-z0-9._~-]{1,4096}$/.test(token)) protocols.push(`nerva-admin.${token}`);
    let ws: WebSocket;
    try { ws = new WebSocket(endpoint.toString(), protocols); }
    catch {
      setStreamState('connection failed');
      return;
    }
    setSocket(ws);
    setStreamState('connecting');
    ws.onopen = () => setStreamState('live');
    ws.onmessage = (message) => {
      try {
        const frame: unknown = JSON.parse(String(message.data));
        if (!frame || typeof frame !== 'object' || Array.isArray(frame)) return;
        const typed = frame as Frame;
        setEvents((previous) => [...previous, typed].slice(-MAX_LOG));
        if ('method' in typed && (typeof typed.id === 'string' || typeof typed.id === 'number')) {
          setRequests((previous) => {
            const repeated = previous.some((item) => item.id === typed.id
              && item.generation === typed.generation);
            return repeated ? previous : [...previous, typed as ServerRequest].slice(-MAX_LOG);
          });
        }
      } catch { /* malformed event is not presented as a real Hermes event */ }
    };
    ws.onerror = () => {
      setStreamState('connection failed');
      ws.close();
    };
    ws.onclose = () => {
      setSocket(null);
      setStreamState('disconnected');
      if (!disposed) reconnectTimer = setTimeout(() => setStreamRetry((value) => value + 1), 3000);
    };
    return () => {
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws.onclose = null;
      ws.close();
      setSocket(null);
    };
  }, [status?.ready, streamRetry]);

  useEffect(() => {
    if (!status?.ready) setRequests([]);
  }, [status?.ready]);

  async function refreshStatus() {
    setStatus(await readJson<RuntimeStatus>('/api/hermes/status'));
  }

  async function refreshApprovals() {
    const next = await readJson<ApprovalList>('/api/hermes/approvals');
    setApprovals(Array.isArray(next.tasks) ? next.tasks : []);
    setApprovalsLoaded(true);
  }

  async function decide(task: ApprovalTask, approved: boolean) {
    if (approvalBusy !== null || !decisionReady(task)) return;
    setApprovalBusy(task.task_id);
    setError('');
    setApprovalNotice('');
    try {
      const updated = await readJson<ApprovalTask>(
        `/api/hermes/approvals/${task.task_id}/decision`, 'POST', { approved },
      );
      setApprovals((previous) => previous.map((item) =>
        item.task_id === task.task_id ? updated : item));
      setApprovalNotice(`Task ${task.task_id}: ${updated.status}. Refresh to inspect execution outcome.`);
      await refreshApprovals();
    } catch (exc) { setError(String(exc)); }
    finally { setApprovalBusy(null); }
  }

  async function control(action: 'start' | 'stop') {
    if (busy) return;
    setBusy(action);
    setError('');
    try {
      const next = await readJson<RuntimeStatus>(`/api/hermes/${action}`, 'POST');
      setStatus(next);
    } catch (exc) { setError(String(exc)); }
    finally { setBusy(''); }
  }

  async function call(methodName = method, raw = argumentsText) {
    if (busy || !status?.ready) return;
    let params: Record<string, unknown>;
    try { params = parseObject(raw); }
    catch (exc) { setError(String(exc)); return; }
    setBusy(methodName);
    setError('');
    try {
      const response = await readJson<{ result: unknown }>('/api/hermes/rpc', 'POST',
        { method: methodName, params });
      setResult(response.result);
      if (methodName === 'session.list' || methodName === 'session.create') {
        const list = methodName === 'session.list'
          ? response.result
          : (await readJson<{ result: unknown }>('/api/hermes/rpc', 'POST',
            { method: 'session.list', params: {} })).result;
        setSessions(asSessions(list));
        setSessionsLoaded(true);
      }
      await refreshStatus();
    } catch (exc) {
      setError(String(exc));
      try { await refreshApprovals(); } catch { /* preserve the original RPC refusal */ }
    }
    finally { setBusy(''); }
  }

  function reply(request: ServerRequest) {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      setError('Hermes event stream is disconnected');
      return;
    }
    let payload: unknown;
    try { payload = JSON.parse(replyText); }
    catch { setError('Server response must be valid JSON'); return; }
    if (replyKind === 'error' && (!payload || typeof payload !== 'object' || Array.isArray(payload))) {
      setError('Server error must be a JSON object');
      return;
    }
    if (typeof request.generation !== 'string') {
      setError('Server request has no runtime generation');
      return;
    }
    socket.send(JSON.stringify({ jsonrpc: '2.0', id: request.id,
      generation: request.generation, [replyKind]: payload }));
    setRequests((previous) => previous.filter((item) => item !== request));
    setError('');
  }

  const selected = catalog?.methods?.find((item) => item.name === method);
  const configured = Boolean(status?.enabled);
  const ready = Boolean(status?.ready);

  return (
    <section className="hermes-runtime" aria-label="Hermes runtime" style={{ border: '1px solid var(--panel-line)', borderRadius: 4, padding: 12, marginTop: 16 }}>
      <div className="sub-h">HERMES RUNTIME · PINNED UPSTREAM</div>
      {status === null ? <p role="status">{error ? 'Runtime status unavailable.' : 'Checking runtime readiness…'}</p> : (
        <>
          <p role="status">
            {ready ? 'Ready' : configured ? 'Stopped' : 'Disabled'}
            {status.reason ? ` · ${status.reason}` : ''}
          </p>
          {!configured && <p>Set up the pinned Hermes runtime with the server CLI, then enable it in the Hub configuration.</p>}
          {status.source_sha && <p>Source: {status.source_sha}</p>}
          <div style={{ display: 'flex', gap: 8 }}>
            <button type="button" disabled={!!busy || !configured || ready} onClick={() => void control('start')}>
              {busy === 'start' ? 'Starting…' : 'Start'}
            </button>
            <button type="button" disabled={!!busy || !ready} onClick={() => void control('stop')}>
              {busy === 'stop' ? 'Stopping…' : 'Stop'}
            </button>
          </div>
        </>
      )}
      {error && <p role="alert">{error}</p>}
      <div style={{ marginTop: 16 }}>
        <div className="sub-h">ACTION APPROVALS</div>
        <p>Review the exact queued operation before deciding. This controls Hub tasks; provider and server request replies are separate.</p>
        <button type="button" disabled={approvalBusy !== null} onClick={() => {
          setError('');
          void refreshApprovals().catch((exc: unknown) => setError(String(exc)));
        }}>Refresh approvals</button>
        {approvalNotice && <p role="status">{approvalNotice}</p>}
        {approvals.length ? <ul aria-label="Hermes approval tasks">{approvals.map((task) => (
          <li key={task.task_id}>
            <strong>Task {task.task_id}</strong> · {task.status}
            {task.disposition ? ` · ${task.disposition}` : ''}
            {task.risk_tier ? ` · risk: ${task.risk_tier}` : ''}
            <div>Operation: {task.operation || 'unknown'}</div>
            <div>Target: <code>{task.target || 'unknown'}</code></div>
            <pre aria-label={`Arguments for task ${task.task_id}`}>{JSON.stringify(task.arguments ?? {}, null, 2)}</pre>
            {(task.result !== undefined || task.error !== undefined) && (
              <pre aria-label={`Outcome for task ${task.task_id}`}>
                {JSON.stringify({ result: task.result, error: task.error }, null, 2)}
              </pre>
            )}
            {task.disposition === 'consumed_outcome_unknown' &&
              <p>Execution outcome is unknown. Inspect the target before issuing a new operation.</p>}
            {task.expires_at && <div>Expires: {task.expires_at}</div>}
            <button type="button" disabled={!decisionReady(task) || approvalBusy !== null}
              onClick={() => void decide(task, true)}>Approve task {task.task_id}</button>
            <button type="button" disabled={!decisionReady(task) || approvalBusy !== null}
              onClick={() => void decide(task, false)}>Deny task {task.task_id}</button>
          </li>
        ))}</ul> : <p>{approvalsLoaded ? 'No approval tasks reported.' : 'Checking approval tasks…'}</p>}
      </div>
      <div style={{ marginTop: 16 }}>
        <div className="sub-h">SESSIONS</div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button type="button" disabled={!ready || !!busy} onClick={() => void call('session.list', '{}')}>Refresh sessions</button>
          <button type="button" disabled={!ready || !!busy} onClick={() => void call('session.create', argumentsText)}>Create session</button>
        </div>
        {sessions.length ? <ul>{sessions.map((session, index) => (
          <li key={String(session.id ?? index)}>{String(session.id ?? session.session_id ?? 'session')} · {String(session.status ?? 'unknown')}</li>
        ))}</ul> : <p>{sessionsLoaded ? 'No sessions reported.' : 'Refresh sessions to inspect the runtime.'}</p>}
      </div>
      <div style={{ marginTop: 16 }}>
        <div className="sub-h">UPSTREAM RPC CATALOG · {catalog?.methods?.length ?? 0} METHODS</div>
        <label htmlFor="hermes-method">Method</label>
        <select id="hermes-method" value={method} onChange={(event) => setMethod(event.target.value)}>
          {(catalog?.methods ?? []).map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
        </select>
        {selected && <p>{selected.summary || 'Upstream method'}{selected.risk_tier ? ` · risk: ${selected.risk_tier}` : ''}</p>}
        <label htmlFor="hermes-arguments">JSON arguments</label>
        <textarea id="hermes-arguments" rows={5} value={argumentsText}
          onChange={(event) => setArgumentsText(event.target.value)} />
        <button type="button" disabled={!ready || !!busy || !method} onClick={() => void call()}>
          {busy === method ? 'Sending…' : 'Send RPC'}
        </button>
        {result !== null && <pre aria-label="Hermes RPC result">{JSON.stringify(result, null, 2)}</pre>}
      </div>
      <div style={{ marginTop: 16 }}>
        <div className="sub-h">EVENT STREAM · {streamState}</div>
        {requests.length > 0 && (
          <div>
            <p>Server request pending: {requests[0].method} ({String(requests[0].id)})</p>
            <label htmlFor="hermes-reply-kind">Response type</label>
            <select id="hermes-reply-kind" value={replyKind}
              onChange={(event) => setReplyKind(event.target.value as 'result' | 'error')}>
              <option value="result">result</option>
              <option value="error">error</option>
            </select>
            <label htmlFor="hermes-reply">JSON response</label>
            <textarea id="hermes-reply" rows={3} value={replyText}
              onChange={(event) => setReplyText(event.target.value)} />
            <button type="button" onClick={() => reply(requests[0])}>Reply to server request</button>
          </div>
        )}
        <ol aria-label="Hermes event log">
          {events.map((event, index) => <li key={index}><code>{JSON.stringify(event)}</code></li>)}
        </ol>
      </div>
    </section>
  );
}
