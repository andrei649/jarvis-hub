/* MCP servers — the owner's servers, the reviewed catalog, install and sign-in (G9).

   - Servers (`GET /api/admin/mcp`): each one's transport, how it signs in, which of its
     secrets are set (names only), connect / disconnect / remove, and for an HTTP server the
     OAuth sign-in (`…/{name}/oauth/start`, `DELETE …/{name}/oauth`).
   - Catalog (`GET /api/admin/mcp/catalog?q=`): the Hermes manifests Nerva vendored as data
     and re-checks against MANIFEST.json, with a search.
   - Install card (`POST …/catalog/preview`, then `…/catalog/install`): it shows exactly what
     will run — the command line or the HTTPS endpoint, the environment, the secret names —
     and installs only after the owner ticks "I have read what will run". The install carries
     the plan's digest, so the hub writes what was shown or refuses. Secrets typed here go to
     the hub's encrypted store, never into the server config. Nothing starts until "connect".
   - Deep link: `/v2/console/mcp?install=<catalog name>` (or `?link=<name>&config=<base64>`
     for a vendor's server, at most 32 KB) opens the install card. It is inert: it only fills
     the card the owner then reads and confirms.
   - Sign-in: the browser opens the server's sign-in page and returns to the hub's callback.
     When the browser cannot reach the hub's address, the owner pastes the address the
     browser ended on; the panel relays its code and state with the start's binding (H692).
*/
import React, { useEffect, useMemo, useState } from 'react';
import { apiDelete, apiGet, apiPost } from '../api/client';
import { Card, Tag, inpS, mono, refusalReason, useApi } from '../panel-kit';

export const MCP_PATH = '/api/admin/mcp';
export const CATALOG_PATH = '/api/admin/mcp/catalog';

type Plan = {
  name: string; origin: 'catalog' | 'link'; catalog_name: string | null; commit: string | null;
  transport: string; command: string | null; url: string | null; host: string | null;
  env: Record<string, string>; inputs: { name: string; prompt: string; required: boolean; default: string; value: string }[];
  secrets: { name: string; prompt: string; required: boolean; has_default: boolean }[]; needs: string[];
  auth: string; trust: string; tools_allow: string[] | null; tools_deny: string[] | null;
  post_install: string; will_run: string; starts: string; digest: string; name_taken?: boolean;
  http_client_enabled?: boolean;
};
type Request = { name: string; link_config?: string };

const fail = (err: any) => refusalReason(err, String(err?.status || 'error'));

/** The deep link's request, read once from the address: `?install=` or `?link=&config=`. */
export function deepLinkRequest(search: string): Request | null {
  const q = new URLSearchParams(search);
  const install = q.get('install');
  if (install && /^[A-Za-z0-9_-]{1,64}$/.test(install)) return { name: install };
  const link = q.get('link'); const config = q.get('config');
  if (link && config && /^[A-Za-z0-9_-]{1,64}$/.test(link) && config.length <= 32 * 1024) return { name: link, link_config: config };
  return null;
}

export function InstallCard({ request, onDone, onCancel }: { request: Request; onDone: (msg: string) => void; onCancel: () => void }) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [serverName, setServerName] = useState('');
  const [read, setRead] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const body = () => ({ ...request, ...(serverName.trim() ? { server_name: serverName.trim() } : {}),
    ...(Object.keys(inputs).length ? { inputs } : {}) });
  const preview = () => {
    setBusy(true); setMsg(null); setRead(false);
    apiPost('/api/admin/mcp/catalog/preview', body(), { admin: true })
      .then((r: any) => setPlan(r.plan))
      .catch((err: any) => { setPlan(null); setMsg(`cannot install · ${fail(err)}`); })
      .finally(() => setBusy(false));
  };
  useEffect(preview, [request.name, request.link_config]);  // eslint-disable-line react-hooks/exhaustive-deps

  const install = () => {
    if (!plan) return;
    setBusy(true); setMsg(null);
    const typed = Object.fromEntries(Object.entries(secrets).filter(([, v]) => v.trim()));
    apiPost('/api/admin/mcp/catalog/install', { ...body(), confirm: plan.digest, ...(Object.keys(typed).length ? { secrets: typed } : {}) }, { admin: true })
      .then((r: any) => { setSecrets({}); onDone(String(r?.message || 'installed')); })
      .catch((err: any) => {
        setSecrets({});
        if (err?.status === 409 && err?.body?.error === 'plan_changed') { setPlan(err.body.plan); setRead(false); setMsg('what would run changed; read it again'); return; }
        setMsg(`not installed · ${fail(err)}`);
      })
      .finally(() => setBusy(false));
  };

  const titleId = `install-${request.name}`;
  return (
    <div role="dialog" aria-labelledby={titleId} style={{ margin: '8px 0', padding: 8, border: '1px solid var(--amber)', borderRadius: 4, background: 'var(--surface)' }}>
      <div id={titleId} style={{ ...mono, fontSize: 10.5, color: 'var(--amber)', marginBottom: 4 }}>
        install MCP server {request.name}{request.link_config ? ' · from a link, not in the reviewed catalog' : ''}
      </div>
      {!plan && busy && <div role="status" style={{ fontSize: 11 }}>reading the plan…</div>}
      {plan && (
        <>
          <dl style={{ margin: 0, fontSize: 11, display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '2px 8px' }}>
            <dt>Will run</dt><dd data-testid="will-run" style={{ margin: 0, ...mono }}>{plan.will_run}</dd>
            <dt>Source</dt><dd style={{ margin: 0 }}>{plan.origin === 'catalog' ? `Hermes catalog @${(plan.commit || '').slice(0, 8)}` : 'a link (unreviewed)'}</dd>
            <dt>Starts</dt><dd style={{ margin: 0 }}>{plan.starts}</dd>
            <dt>Trust</dt><dd style={{ margin: 0 }}>{plan.trust} (only tools the server marks read-only can be called)</dd>
            {Object.entries(plan.env).map(([k, v]) => <React.Fragment key={k}><dt>env</dt><dd style={{ margin: 0, ...mono }}>{k}={v}</dd></React.Fragment>)}
            {plan.auth === 'oauth' && <><dt>Sign-in</dt><dd style={{ margin: 0 }}>OAuth in your browser after install; the token is sent only to {plan.host || 'this server'}</dd></>}
          </dl>
          {plan.inputs.map((s) => (
            <div key={s.name} style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 4 }}>
              <label htmlFor={`in-${s.name}`} style={{ fontSize: 10.5 }}>{s.prompt}</label>
              <input id={`in-${s.name}`} value={inputs[s.name] ?? s.value} onChange={(ev) => setInputs({ ...inputs, [s.name]: ev.target.value })} style={{ ...inpS, minWidth: 220 }} />
            </div>
          ))}
          {plan.inputs.length > 0 && <button className="tool-btn" style={{ marginTop: 4 }} disabled={busy} onClick={preview}>show the plan with these values</button>}
          {plan.secrets.map((s) => (
            <div key={s.name} style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 4 }}>
              <label htmlFor={`sec-${s.name}`} style={{ fontSize: 10.5 }}>{s.prompt} <span style={mono}>({s.name})</span>{s.required ? '' : ' · optional'}</label>
              <input id={`sec-${s.name}`} type="password" autoComplete="off" spellCheck={false} value={secrets[s.name] || ''}
                onChange={(ev) => setSecrets({ ...secrets, [s.name]: ev.target.value })} style={{ ...inpS, minWidth: 180 }} />
            </div>
          ))}
          {plan.secrets.length > 0 && <div style={{ fontSize: 10.5, color: 'var(--ink-2)' }}>Secrets are stored encrypted by Nerva and given only to this server; they are never shown again.</div>}
          {plan.name_taken && (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 4, fontSize: 10.5 }}>
              <span>A server named {plan.name} exists and is never overwritten.</span>
              <label htmlFor="mcp-server-name">Install as</label>
              <input id="mcp-server-name" value={serverName} onChange={(ev) => setServerName(ev.target.value)} style={inpS} />
              <button className="tool-btn" disabled={busy || !serverName.trim()} onClick={preview}>check</button>
            </div>
          )}
          {plan.post_install && <details style={{ fontSize: 10.5, marginTop: 4 }}><summary>vendor notes</summary><pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{plan.post_install}</pre></details>}
          {plan.http_client_enabled === false && plan.transport === 'streamable-http' && (
            <div style={{ fontSize: 10.5, color: 'var(--amber)' }}>HTTP servers connect only once JARVIS_MCP_HTTP_CLIENT=1 is set on the hub.</div>
          )}
          <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 11, marginTop: 6 }}>
            <input type="checkbox" checked={read} onChange={(ev) => setRead(ev.target.checked)} /> I have read what will run
          </label>
        </>
      )}
      {msg && <div role="status" style={{ fontSize: 10.5, marginTop: 4, color: 'var(--amber)' }}>{msg}</div>}
      <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
        <button className="tool-btn" disabled={busy || !plan || !read || plan.needs.length > 0 || (!!plan.name_taken && !serverName.trim())} onClick={install}>Install</button>
        <button className="tool-btn" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

function SignIn({ name, oauth, onChanged }: { name: string; oauth: any; onChanged: () => void }) {
  const [start, setStart] = useState<any>(null);
  const [pasted, setPasted] = useState('');
  const [msg, setMsg] = useState<string | null>(null);
  const begin = () => {
    setMsg(null);
    apiPost(`/api/admin/mcp/${encodeURIComponent(name)}/oauth/start`, { redirect: 'hub' }, { admin: true })
      .then((r: any) => { setStart(r); try { window.open(r.authorization_url, '_blank', 'noopener'); } catch { /* the link is shown */ } })
      .catch((err: any) => setMsg(`sign-in not started · ${fail(err)}`));
  };
  const relay = () => {
    let url: URL;
    try { url = new URL(pasted.trim()); } catch { setMsg('paste the whole address from the browser'); return; }
    const state = url.searchParams.get('state') || ''; const code = url.searchParams.get('code') || '';
    const error = url.searchParams.get('error') || '';
    const iss = url.searchParams.get('iss');
    apiPost(`/api/admin/mcp/${encodeURIComponent(name)}/oauth/callback`,
      { state, binding: start.binding, ...(code ? { code } : {}), ...(error ? { error } : {}), ...(iss !== null ? { iss } : {}) }, { admin: true })
      .then(() => { setStart(null); setPasted(''); setMsg('signed in · press connect'); onChanged(); })
      .catch((err: any) => setMsg(`not signed in · ${fail(err)}`));
  };
  // While a sign-in waits, ask the hub every few seconds whether the browser came back.
  useEffect(() => {
    if (!start) return undefined;
    const until = Date.now() + 5 * 60 * 1000;
    const t = setInterval(() => {
      if (Date.now() > until) { clearInterval(t); setStart(null); setMsg('the sign-in expired; start again'); return; }
      apiGet(`/api/admin/mcp/${encodeURIComponent(name)}/oauth`, { admin: true })
        .then((r: any) => { if (r?.signed_in) { clearInterval(t); setStart(null); setMsg('signed in · press connect'); onChanged(); } })
        .catch(() => { /* keep waiting */ });
    }, 3000);
    return () => clearInterval(t);
  }, [start, name]);  // eslint-disable-line react-hooks/exhaustive-deps
  const signOut = () => apiDelete(`/api/admin/mcp/${encodeURIComponent(name)}/oauth`, { admin: true })
    .then(() => { setMsg('signed out · tokens revoked and deleted'); onChanged(); })
    .catch((err: any) => setMsg(`not signed out · ${fail(err)}`));
  return (
    <div style={{ fontSize: 10.5, marginTop: 4 }}>
      {oauth?.signed_in
        ? <>signed in at <span style={mono}>{oauth.as_host}</span>{oauth.expires_at ? ` · until ${new Date(oauth.expires_at * 1000).toLocaleString()}` : ''}
            <button className="tool-btn" style={{ marginLeft: 6 }} onClick={() => void signOut()}>sign out</button></>
        : <button className="tool-btn" onClick={begin}>sign in</button>}
      {start && (
        <div style={{ marginTop: 4 }}>
          Your browser opens <span style={mono}>{start.authorize_host || start.as_host}</span> (authorization server <span style={mono}>{start.as_host}</span>) (<a href={start.authorization_url} target="_blank" rel="noopener noreferrer">open</a>). The token is sent only to <span style={mono}>{start.server_origin}</span>.
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 4 }}>
            <label htmlFor={`paste-${name}`}>Browser could not reach the hub? Paste the address it ended on</label>
            <input id={`paste-${name}`} value={pasted} onChange={(ev) => setPasted(ev.target.value)} style={{ ...inpS, minWidth: 200 }} />
            <button className="tool-btn" disabled={!pasted.trim()} onClick={relay}>finish sign-in</button>
          </div>
        </div>
      )}
      {msg && <div role="status" style={{ color: 'var(--ink-2)' }}>{msg}</div>}
    </div>
  );
}

export function McpPanel() {
  const servers = useApi(MCP_PATH, true, true);
  const [q, setQ] = useState('');
  const catalog = useApi(`${CATALOG_PATH}${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ''}`, true, true);
  const [installing, setInstalling] = useState<Request | null>(() =>
    typeof window !== 'undefined' ? deepLinkRequest(window.location.search) : null);
  const [note, setNote] = useState<string | null>(null);
  const rows: any[] = Array.isArray((servers.d as any)?.servers) ? (servers.d as any).servers : [];
  const entries: any[] = Array.isArray((catalog.d as any)?.entries) ? (catalog.d as any).entries : [];
  const reloadAll = () => { servers.reload(); catalog.reload(); };
  const act = (p: Promise<any>, done: string) => p.then((r) => { setNote(r?.message || done); reloadAll(); })
    .catch((err: any) => setNote(`not done · ${fail(err)}`));
  const commit = useMemo(() => String((catalog.d as any)?.commit || '').slice(0, 8), [catalog.d]);

  return (
    <Card title="MCP SERVERS" live={servers.d ? 'live' : undefined} onReload={reloadAll}
      sub={servers.d ? `${rows.length} configured · catalog ${(catalog.d as any)?.total ?? '…'}${commit ? ` @${commit}` : ''}` : null}>
      {servers.e && <div role="status" style={{ color: 'var(--amber)', fontSize: 11 }}>not loaded · {String(servers.e)}</div>}
      {note && <div role="status" style={{ fontSize: 10.5, color: 'var(--ink-2)' }}>{note}</div>}
      {installing && <InstallCard request={installing} onCancel={() => setInstalling(null)}
        onDone={(m) => { setInstalling(null); setNote(m); reloadAll(); }} />}
      <ul aria-label="your MCP servers" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {rows.map((s) => (
          <li key={s.name} style={{ padding: '5px 0', borderBottom: '1px solid var(--panel-line)', fontSize: 11 }}>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
              <b>{s.name}</b><Tag>{s.transport}</Tag>{s.auth && s.auth !== 'none' && <Tag>{s.auth}</Tag>}
              {s.origin?.catalog && <Tag>catalog</Tag>}
              <Tag c={s.connected || s.health?.connected ? 'var(--green)' : 'var(--ink-2)'}>{s.connected || s.health?.connected ? 'connected' : 'not connected'}</Tag>
              <span style={{ ...mono, color: 'var(--ink-2)' }}>{s.url || s.command}</span>
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
                <button className="tool-btn" onClick={() => void act(apiPost(`/api/admin/mcp/${encodeURIComponent(s.name)}/connect`, {}, { admin: true }), 'connected')}>connect</button>
                <button className="tool-btn" onClick={() => void act(apiPost(`/api/admin/mcp/${encodeURIComponent(s.name)}/disconnect`, {}, { admin: true }), 'disconnected')}>disconnect</button>
                <button className="tool-btn" onClick={() => void act(apiDelete(`/api/admin/mcp/${encodeURIComponent(s.name)}`, { admin: true }), 'removed')}>remove</button>
              </span>
            </div>
            {Array.isArray(s.secrets) && s.secrets.length > 0 && (
              <div style={{ fontSize: 10.5, color: 'var(--ink-2)' }}>secrets: {s.secrets.map((x: any) => `${x.name} ${x.set ? 'set' : 'not set'}`).join(' · ')}</div>
            )}
            {s.transport === 'streamable-http' && <SignIn name={s.name} oauth={s.oauth} onChanged={reloadAll} />}
          </li>
        ))}
        {servers.d && rows.length === 0 && <li style={{ fontSize: 11, color: 'var(--ink-2)' }}>No MCP servers yet.</li>}
      </ul>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', margin: '10px 0 4px' }}>
        <span style={{ ...mono, fontSize: 10.5 }}>CATALOG</span>
        <label htmlFor="mcp-catalog-search" style={{ fontSize: 10.5 }}>Find</label>
        <input id="mcp-catalog-search" value={q} onChange={(ev) => setQ(ev.target.value)} style={{ ...inpS, minWidth: 140 }} />
      </div>
      {catalog.e && <div role="status" style={{ color: 'var(--amber)', fontSize: 11 }}>catalog not loaded · {String(catalog.e)}</div>}
      <ul aria-label="MCP catalog" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {entries.map((c) => (
          <li key={c.name} style={{ display: 'flex', gap: 6, alignItems: 'center', padding: '4px 0', borderBottom: '1px solid var(--panel-line)', fontSize: 11 }}>
            <b>{c.name}</b><Tag>{c.auth === 'oauth' ? 'sign-in' : c.auth === 'none' ? 'no account' : c.auth}</Tag>
            <span style={{ color: 'var(--ink-2)' }}>{c.description}</span>
            {c.installed ? <Tag c="var(--green)">installed</Tag>
              : c.status === 'ok' ? <button className="tool-btn" style={{ marginLeft: 'auto' }} onClick={() => setInstalling({ name: c.name })} aria-label={`install ${c.name}`}>install…</button>
              : <Tag c="var(--red)">{c.status}</Tag>}
          </li>
        ))}
      </ul>
    </Card>
  );
}
