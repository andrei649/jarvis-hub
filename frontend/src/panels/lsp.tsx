/* LANGUAGE SERVERS — H055/H564/H597 (agents/core/codeintel/lsp, routers/codeintel.py).

   A section of the Code Intel panel: which servers Nerva knows, where each was found
   (Nerva's own tools directory or the owner's PATH), what is running for which workspace,
   what is broken, and the isolation in force. Install never downloads anything from here:
   it queues an `lsp.install` approval card and says so. Start/stop are admin writes; a
   refusal shows the backend's own code verbatim. */
import React, { useState } from 'react';
import { useApi, arr, mono, Row, Tag, State, actA, inpS } from '../panel-kit';
import { apiDelete } from '../api/client';

const STATUS_PATH = '/api/codeintel/lsp/status';
const INSTALL_PATH = '/api/codeintel/lsp/install';
const START_PATH = '/api/codeintel/lsp/start';
const STOP_PATH = '/api/codeintel/lsp/stop';
const TRUST_PATH = '/api/codeintel/lsp/trust';

const refusalText = (err) => {
  const b = err && err.body;
  const cause = (b && (b.error || b.detail || b.message)) || (err && err.message) || 'refused';
  const detail = b && b.error && b.detail ? ` · ${b.detail}` : '';
  return `refused · ${(err && err.status) || '?'} · ${cause}${detail}`;
};

export function LspSection() {
  const status = useApi(STATUS_PATH, true, true);   // admin: it names absolute paths
  const [root, setRoot] = useState('');
  const s = status.d;
  const [note, setNote] = useState(null);
  const [busy, setBusy] = useState('');

  const act = (key, path, body, ok) => {
    if (busy) return;
    setBusy(key);
    setNote(null);
    actA(path, body,
      (r) => { setBusy(''); setNote({ kind: 'ok', text: ok(r) }); status.reload(); },
      (err) => { setBusy(''); setNote({ kind: 'err', text: refusalText(err) }); status.reload(); });
  };

  const clearInstall = (id) => {
    if (busy) return;
    setBusy('c:' + id);
    setNote(null);
    apiDelete(INSTALL_PATH + '/' + encodeURIComponent(id), { admin: true })
      .then(() => { setBusy(''); setNote({ kind: 'ok', text: `install record for ${id} cleared` }); status.reload(); })
      .catch((err) => { setBusy(''); setNote({ kind: 'err', text: refusalText(err) }); status.reload(); });
  };

  const servers = arr(s, 'servers');
  const running = arr(s, 'running');
  const broken = arr(s, 'broken');
  const trusted = arr(s, 'trusted_workspaces');

  return (
    <div style={{ marginTop: 10, borderTop: '1px solid var(--line, #333)', paddingTop: 8 }}>
      <Row>
        <span style={{ ...mono, color: 'var(--ink-2)' }}>language servers</span>
        {s && (
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, flexWrap: 'wrap' }}>
            <Tag c={s.enabled ? undefined : 'var(--amber)'}>{s.enabled ? 'diagnostics on write' : 'off (JARVIS_LSP=0)'}</Tag>
            <Tag c={s.isolation === 'bwrap' ? undefined : 'var(--amber)'}>isolation {s.isolation}</Tag>
            <Tag>idle kill {s.idle_seconds}s</Tag>
          </span>
        )}
      </Row>
      <State e={status.e} loading={status.loading} n={s ? 1 : 0} />
      {s && s.isolation !== 'bwrap' && (
        <div style={{ fontSize: 10, color: 'var(--amber)' }}>
          {s.can_start === false
            ? 'no namespace sandbox on this host, and one is required — no language server will start (JARVIS_LSP_REQUIRE_SANDBOX=0 runs them with limits only)'
            : 'no namespace sandbox on this host — servers run with resource limits and a scrubbed environment only'}
        </div>
      )}
      <Row>
        <span style={{ fontSize: 10, color: 'var(--ink-2)' }}>trusted workspaces</span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, flexWrap: 'wrap' }}>
          {trusted.length === 0 && <Tag c="var(--ink-2)">none — no server starts anywhere</Tag>}
          {trusted.map((t) => (
            <span key={t.root} style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
              <Tag>{t.root}</Tag>
              <button className="tool-btn" disabled={!!busy}
                onClick={() => act('u:' + t.root, TRUST_PATH, { root: t.root, trusted: false },
                  (r) => `${r && r.root} no longer trusted · stopped ${r && r.stopped} server(s)`)}
              >untrust</button>
            </span>
          ))}
        </span>
      </Row>
      <Row>
        <input value={root} onChange={(ev) => setRoot(ev.target.value)}
          placeholder="git workspace to trust (absolute path inside the file roots)"
          style={{ ...inpS, flex: 1, minWidth: 120 }} />
        <button className="tool-btn" disabled={!!busy || !root.trim()}
          onClick={() => act('t:' + root, TRUST_PATH, { root: root.trim(), trusted: true },
            (r) => `language servers may start in ${r && r.root}`)}
        >trust</button>
      </Row>
      {servers.map((row) => {
        const recipe = (row && row.recipe) || {};
        const install = row && row.install;
        return (
          <Row key={row.id}>
            <span style={{ ...mono, color: 'var(--accent-light)' }}>{row.id}</span>
            <span style={{ fontSize: 10, color: 'var(--ink-2)' }}>{arr(row, 'languages').join(' · ')}</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
              {row.available
                ? <Tag>found · {row.source}</Tag>
                : <Tag c="var(--ink-2)">not installed</Tag>}
              {install && install.status && <Tag c={install.status === 'failed' ? 'var(--red)' : undefined}>install {install.status}{install.error ? ` · ${install.error}` : ''}</Tag>}
              {install && install.status === 'failed' && (
                <button className="tool-btn" disabled={!!busy} onClick={() => clearInstall(row.id)}>clear</button>
              )}
              {!row.available && row.installable && (
                <button className="tool-btn" disabled={!!busy}
                  title={`queue an approval card: ${arr(recipe, 'packages').join(', ')} via ${recipe.kind}`}
                  onClick={() => act('i:' + row.id, INSTALL_PATH, { server: row.id },
                    (r) => `approval card #${r && r.task_id} queued — accept it in the approval queue to install ${arr(r, 'packages').join(', ')}`)}
                >install…</button>
              )}
              {!row.available && !row.installable && recipe.hint && (
                <span style={{ fontSize: 10, color: 'var(--ink-2)' }}>{recipe.hint}</span>
              )}
              {row.available && s.enabled && (
                <button className="tool-btn" disabled={!!busy}
                  onClick={() => act('s:' + row.id, START_PATH, { server: row.id },
                    (r) => `${row.id} running · pid ${r && r.running && r.running.pid}`)}
                >start</button>
              )}
            </span>
          </Row>
        );
      })}
      {running.map((row) => (
        <Row key={`${row.server}:${row.root}`}>
          <Tag c="var(--green)">running</Tag>
          <span style={{ ...mono }}>{row.server}</span>
          <span style={{ ...mono, color: 'var(--ink-2)' }}>{row.root}</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
            <Tag>pid {row.pid}</Tag>
            <Tag>{row.diagnostics_served} checks</Tag>
            <button className="tool-btn" disabled={!!busy}
              onClick={() => act('x:' + row.server, STOP_PATH, { server: row.server, root: row.root },
                (r) => `stopped ${r && r.stopped} server(s)`)}
            >stop</button>
          </span>
        </Row>
      ))}
      {broken.map((row) => (
        <Row key={`b:${row.server}:${row.root}`}>
          <Tag c="var(--amber)">broken</Tag>
          <span style={{ ...mono }}>{row.server}</span>
          <span style={{ ...mono, color: 'var(--ink-2)' }}>{row.reason} · retry in {row.retry_in}s</span>
        </Row>
      ))}
      {note && (
        <div role="alert" style={{ ...mono, marginTop: 6, color: note.kind === 'err' ? 'var(--red)' : 'var(--green)' }}>
          {note.text}
        </div>
      )}
      <div style={{ fontSize: 10, color: 'var(--ink-2)', marginTop: 6 }}>
        Servers start only in a git workspace you trusted here, because a server reads — and some can
        be led to run — what the workspace ships. After the agent writes a file, the running server's
        diagnostics are compared before and after
        the edit, and only the errors the edit introduced go back to the agent (bounded, fenced as
        third-party text). Servers are confined to their workspace with no network, bounded in memory
        and CPU, and killed when idle. Install queues an approval card for a pinned package from one
        registry; nothing is downloaded until a person accepts it.
      </div>
    </div>
  );
}
