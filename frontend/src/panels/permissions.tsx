/* PERMISSIONS — the consent ledger (GET /api/permissions, POST /api/permissions/{id}/revoke;
   both user-guarded).

   What Nerva may touch, per app / site / OS-input / file-root / terminal-target, with the
   scopes once · session · always · never. This panel READS the ledger and NARROWS it — a
   revoke needs no approval. It deliberately has no "grant" control: widening what Nerva may
   touch is a privileged effect that only the owner can decide from the decision inbox (the
   ledger enqueues a `permission.grant` task at ask; the grant is applied from that task's
   execution and from nowhere else). A textbox here that minted grants would be the exact
   self-authorization the kernel exists to prevent.

   Honesty contract:
   · `enabled:false` (the JARVIS_PERMISSION_LEDGER flag is off) is said plainly: legacy
     callers are ALLOWED and nothing is recorded — an empty list under a green chip would
     read as "nothing granted", which is the opposite of the truth.
   · `never` rows (the default-deny list and owner denials) are immutable; they carry a lock
     and no revoke button. The default-deny list is rendered as a count + categories, not as
     rows that look revocable.
   · A refused revoke renders as a refusal carrying the backend's own reason (onErr is
     mandatory for a governance control — panel-kit.tsx explains why). */
import React, { useState } from 'react';
import { useApi, arr, mono, asLive, Card, State, Row, Tag, act } from '../panel-kit';

const LEDGER_PATH = '/api/permissions';

const SCOPE_COLOR = {
  once: 'var(--accent-light)',
  session: 'var(--accent)',
  always: 'var(--green)',
  never: 'var(--red)',
};

const STATUS_COLOR = {
  active: 'var(--green)',
  never: 'var(--red)',
  consumed: 'var(--ink-2)',
  revoked: 'var(--amber)',
  expired: 'var(--ink-2)',
};

const stamp = (v) => (typeof v === 'number' && isFinite(v) ? new Date(v * 1000).toLocaleString() : '—');

function refusalText(err) {
  const body = (err && err.body) || null;
  const reason = body && (body.reason || (typeof body.detail === 'string' ? body.detail : null));
  const status = err && err.status;
  if (status === 403) return 'refused · 403 · kernel denied';
  return `refused · ${status || 'error'}${reason ? ' · ' + reason : ''}`;
}

export function PermissionsPanel() {
  const { d, e, loading, reload } = useApi(LEDGER_PATH);
  const grants = arr(d, 'grants');
  const denyRules = arr(d, 'default_deny');
  const enabled = !!(d && d.enabled);
  const [showInactive, setShowInactive] = useState(false);
  const [note, setNote] = useState(null);

  const visible = grants.filter((g) => showInactive || g.status === 'active' || g.status === 'never');
  const categories = Array.from(new Set(denyRules.map((r) => r.category).filter(Boolean)));

  // Narrowing only. onErr is mandatory: a refused revoke must be visible, never a silent
  // "still active" row under a success-looking panel.
  const revoke = (g) => act(
    LEDGER_PATH + '/' + encodeURIComponent(g.id) + '/revoke',
    {},
    () => { setNote('revoked · ' + g.surface + ' ' + g.key); reload(); },
    (err) => setNote(refusalText(err)),
  );

  return (
    <Card
      title="Permissions"
      live={asLive(d, enabled)}
      sub={d ? `${d.active ?? 0} active · ${denyRules.length} default-deny` : null}
      onReload={reload}
    >
      <State e={e} loading={loading} n={d ? 1 : 0} />
      {d && !enabled && (
        <div role="status" style={{ fontSize: 11, color: 'var(--amber)', marginTop: 6 }}>
          ledger off ({d.flag || 'JARVIS_PERMISSION_LEDGER'}) — legacy callers are allowed and nothing is recorded
        </div>
      )}
      {d && (
        <div style={{ ...mono, fontSize: 10, color: 'var(--ink-2)', marginTop: 6 }}>
          default-deny: {denyRules.length} rules · {categories.join(' · ') || '—'} · immutable
        </div>
      )}
      {d && grants.length > 0 && (
        <label style={{ ...mono, fontSize: 10, color: 'var(--ink-2)', display: 'flex', gap: 6, alignItems: 'center', marginTop: 6 }}>
          <input type="checkbox" checked={showInactive} onChange={(ev) => setShowInactive(ev.target.checked)} />
          show consumed / revoked / expired
        </label>
      )}
      {d && grants.length === 0 && (
        <div style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 6 }}>
          no grants recorded — a first contact asks; the owner decides in the decision inbox
        </div>
      )}
      {visible.slice(0, 40).map((g) => (
        <Row key={g.id}>
          <Tag>{g.surface}</Tag>
          <span
            title={g.key}
            style={{ color: 'var(--accent-light)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', ...mono }}
          >
            {g.key}
          </span>
          <Tag c={SCOPE_COLOR[g.scope]}>{g.scope}</Tag>
          <Tag c={STATUS_COLOR[g.status] || 'var(--ink-2)'}>{g.status}</Tag>
          <span title={'granted by ' + (g.granted_by || '—') + ' · ' + stamp(g.created_at)} style={{ ...mono, fontSize: 9.5, color: 'var(--ink-2)' }}>
            {g.granted_by || '—'}
          </span>
          {g.immutable ? (
            <span title="never entries are immutable" aria-label="immutable" style={{ ...mono, fontSize: 10, color: 'var(--ink-2)' }}>locked</span>
          ) : g.status === 'active' ? (
            <button className="tool-btn" onClick={() => revoke(g)}>revoke</button>
          ) : null}
        </Row>
      ))}
      {note && (
        <div role="alert" style={{ fontSize: 10, color: note.startsWith('refused') ? 'var(--amber)' : 'var(--ink-2)', marginTop: 6 }}>
          {note}
        </div>
      )}
    </Card>
  );
}
