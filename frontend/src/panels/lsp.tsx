/* LANGUAGE SERVERS — H055/H564/H597 (agents/core/codeintel/lsp, routers/codeintel.py).

   A section of the Code Intel panel: which servers Nerva knows, where each was found
   (Nerva's own tools directory or the owner's PATH), what is running for which workspace,
   what is broken, and the isolation in force. Install never downloads anything from here:
   it queues an `lsp.install` approval card and says so. Start/stop are admin writes; a
   refusal shows the backend's own code verbatim. */
import React, { useState } from 'react';
import { useApi, arr, mono, Row, Tag, State, actA } from '../panel-kit';

const STATUS_PATH = '/api/codeintel/lsp/status';
const INSTALL_PATH = '/api/codeintel/lsp/install';
const START_PATH = '/api/codeintel/lsp/start';
const STOP_PATH = '/api/codeintel/lsp/stop';

const refusalText = (err) => {
  const b = err && err.body;
  const cause = (b && (b.error || b.detail || b.message)) || (err && err.message) || 'refused';
  const detail = b && b.error && b.detail ? ` · ${b.detail}` : '';
  return `refused · ${(err && err.status) || '?'} · ${cause}${detail}`;
};

export function LspSection() {
  const status = useApi(STATUS_PATH);
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

  const servers = arr(s, 'servers');
  const running = arr(s, 'running');
  const broken = arr(s, 'broken');

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
          no namespace sandbox on this host — servers run with resource limits and a scrubbed
          environment only
        </div>
      )}
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
              {install && install.status && <Tag c={install.status === 'failed' ? 'var(--red)' : undefined}>install {install.status}</Tag>}
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
        After the agent writes a file, the running server's diagnostics are compared before and after
        the edit, and only the errors the edit introduced go back to the agent (bounded, fenced as
        third-party text). Servers are confined to their workspace with no network, bounded in memory
        and CPU, and killed when idle. Install queues an approval card for a pinned package from one
        registry; nothing is downloaded until a person accepts it.
      </div>
    </div>
  );
}
