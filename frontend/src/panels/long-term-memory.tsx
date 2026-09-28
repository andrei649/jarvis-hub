/* H314 — the long-term memory the model writes with its `memory` tool, and the owner's
   undo. `GET /api/memory/core` lists both rings (the agent's notes and the user profile)
   and the newest writes that can still be undone; each undo posts its ref to the
   admin-only `POST /api/memory/core/undo`, which the hub refuses once the rings changed
   after that write. A refusal is shown, never read as success, and the list is re-read
   whatever the hub answered. */
import React, { useState } from 'react';
import { Card, Row, State, Tag, actA, arr, asLive, mono, refusalReason, useApi } from '../panel-kit';

export const CORE_PATH = '/api/memory/core';
export const UNDO_PATH = '/api/memory/core/undo';

function Facts({ title, facts }: { title: string; facts: string[] }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ ...mono, fontSize: 9.5, color: 'var(--ink-3)', letterSpacing: '.08em' }}>{title} · {facts.length}</div>
      {facts.length === 0
        ? <div style={{ fontSize: 11, color: 'var(--ink-3)' }}>nothing saved</div>
        : facts.map((fact, i) => <Row key={i}><span style={{ fontSize: 12 }}>{fact}</span></Row>)}
    </div>
  );
}

export function LongTermMemoryPanel() {
  const { d, e, loading, reload } = useApi(CORE_PATH);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const enabled = d?.enabled === true;
  const undoable = arr(d, 'undoable');
  const undo = (ref: string) => {
    setBusy(ref);
    setMsg(null);
    actA(UNDO_PATH, { ref },
      () => { setMsg(`undone · ${ref}`); setBusy(null); reload(); },
      (err) => { setMsg(`not undone · ${refusalReason(err, String(err?.status || 'error'))}`); setBusy(null); reload(); });
  };
  return (
    <Card title="LONG-TERM MEMORY" live={asLive(d, enabled)} sub={d ? (enabled ? `${undoable.length} undoable` : 'off') : null} onReload={reload}>
      <State e={e} loading={loading} n={d ? 1 : 0} />
      {d && !enabled && (
        <div style={{ fontSize: 11, color: 'var(--ink-3)' }}>
          Memory is switched off (cognition.enabled and cognition.memory_enabled).
        </div>
      )}
      {enabled && (
        <>
          <Facts title="AGENT NOTES" facts={arr(d, 'memory')} />
          <Facts title="USER PROFILE" facts={arr(d, 'user')} />
          <div style={{ ...mono, fontSize: 9.5, color: 'var(--ink-3)', letterSpacing: '.08em', marginTop: 6 }}>RECENT WRITES</div>
          {undoable.length === 0 && <div style={{ fontSize: 11, color: 'var(--ink-3)' }}>none to undo</div>}
          {undoable.map((w: any) => (
            <Row key={w.ref}>
              <span style={{ ...mono }}>{w.ref}</span>
              {arr(w, 'targets').map((t: string) => <Tag key={t}>{t}</Tag>)}
              <button className="tool-btn" style={{ marginLeft: 'auto' }} disabled={busy === w.ref}
                aria-label={`undo ${w.ref}`} onClick={() => undo(w.ref)}>undo</button>
            </Row>
          ))}
        </>
      )}
      {msg && <div role="status" style={{ fontSize: 10, color: 'var(--accent-light)', marginTop: 6 }}>{msg}</div>}
    </Card>
  );
}
