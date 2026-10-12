/* H206 — the edit and delete dialogs of the memory graph explorer.
   Both write only through the mediated knowledge-graph routes (POST/DELETE
   /api/kg/entities); a refusal stays on screen in the dialog, the node is left alone. */
import React, { useEffect, useRef, useState } from 'react';
import { SAFE_PROPERTY_KEY, SAFE_TYPE, loadEntity, removeEntity, saveEntity } from '../api/memory-graph';
import { inpS } from '../panel-kit';

/** One sentence for any refusal, in the server's own words where it gave some. */
export function describeError(error: any, action: string): string {
  const detail = typeof error?.detail === 'string' ? error.detail : '';
  switch (error?.code) {
    case 'denied': return `Refused: ${detail || 'denied by the action kernel'}. Nothing was changed.`;
    case 'invalid': return `Not accepted: ${detail || 'invalid request'}. Nothing was changed.`;
    case 'auth': return 'Memory access requires your current user credentials. Nothing was changed.';
    case 'admin': return `${action} needs the admin token. Nothing was changed.`;
    case 'unaddressable': return 'This name is a dot segment (. or ..), which a URL path cannot carry, so it cannot be edited or deleted here. Nothing was changed.';
    case 'padded': return 'This name starts or ends with whitespace, so it cannot be edited here: the server would store a different, trimmed name. Delete still works. Nothing was changed.';
    case 'notfound': return 'Not found: nothing was deleted. It may already be gone. Refresh the map to see what is stored now.';
    case 'unknown': return `The result is unknown: the reply did not arrive${detail ? ' (' + detail + ')' : ''}, so the change may have been applied. The map is reloading; check it before trying again.`;
    default: return `Memory graph unavailable${detail ? ': ' + detail : ''}. Nothing was changed.`;
  }
}

const KERNEL_NOTE = 'This goes through the kernel-mediated knowledge-graph route. The action kernel is off by default; '
  + 'when it is on, a halt or a missing capability refuses it and the reason is shown here.';
const PERSIST_NOTE = 'On the default in-memory graph an edit or a deletion lasts until the hub restarts; with the Neo4j backend it is stored. '
  + 'Built-in starter entities are only added when missing, so they never overwrite an edit.';
const TYPE_RULE = 'Type must start with a letter and use only letters, digits and underscores (max 64).';

function Modal({ title, role, children, onClose, busy }: { title: string; role: 'dialog' | 'alertdialog'; children: React.ReactNode; onClose: () => void; busy: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.querySelector<HTMLElement>('input, button')?.focus(); }, []);
  return <div role={role} aria-modal="true" aria-label={title} ref={ref}
    onKeyDown={event => { if (event.key === 'Escape' && !busy) { event.stopPropagation(); onClose(); } }}
    style={{ position: 'absolute', inset: 0, zIndex: 30, background: 'rgba(0,0,0,.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 12 }}>
    <div style={{ background: 'var(--void-2, var(--surface))', border: '1px solid var(--panel-line)', borderRadius: 'var(--radius)', padding: 14, width: 'min(420px, 100%)', maxHeight: '100%', overflowY: 'auto', fontSize: 12 }}>
      <h4 style={{ margin: '0 0 8px', fontSize: 13, color: 'var(--accent-light)', overflowWrap: 'anywhere' }}>{title}</h4>
      {children}
    </div>
  </div>;
}

type Row = { key: string; value: string; original: unknown };
const isText = (v: unknown) => typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean';

export function EditEntityDialog({ name, onClose, onSaved, onRefresh }: { name: string; onClose: () => void; onSaved: (name: string) => void; onRefresh?: () => void }) {
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [type, setType] = useState('');
  const [rows, setRows] = useState<Row[]>([]);
  const [kept, setKept] = useState<[string, unknown][]>([]);
  const [adding, setAdding] = useState(false);
  const [newKey, setNewKey] = useState('');
  const [newValue, setNewValue] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    loadEntity(name, controller.signal).then(detail => {
      if (controller.signal.aborted) return;
      setType(detail.type);
      const entries = Object.entries(detail.properties);
      setRows(entries.filter(([, v]) => isText(v)).map(([key, v]) => ({ key, value: String(v), original: v })));
      setKept(entries.filter(([, v]) => !isText(v)));
      setLoading(false);
    }).catch(err => { if (!controller.signal.aborted) { setLoadError(describeError(err, 'Reading this entity')); setLoading(false); } });
    return () => controller.abort();
  }, [name]);

  const save = async () => {
    if (!SAFE_TYPE.test(type.trim())) { setError(TYPE_RULE); return; }
    /* No prototype: a stored property called __proto__ or constructor is data here, not a setter or an inherited member. */
    const properties: Record<string, unknown> = Object.create(null);
    for (const row of rows) properties[row.key] = row.value === String(row.original) ? row.original : row.value;
    for (const [key, value] of kept) properties[key] = value;
    if (adding && newKey.trim()) {
      if (!SAFE_PROPERTY_KEY.test(newKey.trim())) { setError('A property name is letters, digits and underscores, starting with a letter or underscore (max 64).'); return; }
      if (Object.prototype.hasOwnProperty.call(properties, newKey.trim())) { setError(`${newKey.trim()} already exists.`); return; }
      properties[newKey.trim()] = newValue;
    }
    if (Object.keys(properties).length > 50) { setError('At most 50 properties.'); return; }
    setSaving(true); setError('');
    try { await saveEntity(name, type.trim(), properties); onSaved(name); }
    catch (err: any) {
      setError(describeError(err, 'Saving')); setSaving(false);
      if (err?.code === 'unknown') onRefresh?.();
    }
  };

  return <Modal title={`Edit ${name}`} role="dialog" onClose={onClose} busy={saving}>
    {loading && <div role="status">Reading the stored entity…</div>}
    {loadError && <div role="alert" style={{ color: 'var(--amber)' }}>{loadError}</div>}
    {!loading && !loadError && <>
      <label style={{ display: 'block', marginBottom: 8 }}>Type
        <input aria-label="Entity type" value={type} maxLength={64} onChange={event => setType(event.target.value)} style={{ ...inpS, display: 'block', width: '100%', marginTop: 3 }} />
      </label>
      {rows.map(row => <div key={row.key} style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 5 }}>
        <span style={{ minWidth: 70, overflowWrap: 'anywhere' }}>{row.key}</span>
        <input aria-label={`Value of ${row.key}`} value={row.value} maxLength={2000} style={{ ...inpS, flex: 1, minWidth: 0 }}
          onChange={event => setRows(list => list.map(r => (r.key === row.key ? { ...r, value: event.target.value } : r)))} />
        <button className="tool-btn" aria-label={`Remove ${row.key}`} onClick={() => setRows(list => list.filter(r => r.key !== row.key))}>×</button>
      </div>)}
      {kept.length > 0 && <p style={{ color: 'var(--ink-2)', margin: '4px 0' }}>Kept unchanged (structured): {kept.map(([k]) => k).join(', ')}</p>}
      {adding
        ? <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
            <input aria-label="New property name" placeholder="name" value={newKey} maxLength={64} onChange={event => setNewKey(event.target.value)} style={{ ...inpS, width: 110 }} />
            <input aria-label="New property value" placeholder="value" value={newValue} maxLength={2000} onChange={event => setNewValue(event.target.value)} style={{ ...inpS, flex: 1, minWidth: 0 }} />
          </div>
        : <button className="tool-btn" onClick={() => setAdding(true)} style={{ marginBottom: 6 }}>Add property</button>}
      <p style={{ color: 'var(--ink-2)', margin: '6px 0' }}>{KERNEL_NOTE} Saving replaces this entity's type and properties. {PERSIST_NOTE}</p>
      {error && <div role="alert" style={{ color: 'var(--amber)', margin: '6px 0', overflowWrap: 'anywhere' }}>{error}</div>}
    </>}
    <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', marginTop: 8 }}>
      <button className="tool-btn" onClick={onClose} disabled={saving}>Cancel</button>
      {!loading && !loadError && <button className="tool-btn on" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>}
    </div>
  </Modal>;
}

export function DeleteEntityDialog({ name, onClose, onDeleted, onRefresh }: { name: string; onClose: () => void; onDeleted: (name: string, factsRetracted: number, graphDeleted: boolean) => void; onRefresh?: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [gone, setGone] = useState(false);
  const confirm = async () => {
    if (gone) { onRefresh?.(); onClose(); return; }
    setBusy(true); setError('');
    try { const result = await removeEntity(name); onDeleted(name, result.factsRetracted, result.graphDeleted); }
    catch (err: any) {
      /* A 404 means nothing was deleted: say that, never report a deletion that did not happen. */
      setError(describeError(err, 'Deleting')); setBusy(false);
      if (err?.code === 'notfound') setGone(true);
      else if (err?.code === 'unknown') onRefresh?.();
    }
  };
  return <Modal title={`Delete ${name}?`} role="alertdialog" onClose={onClose} busy={busy}>
    <p style={{ margin: '0 0 6px' }}>This removes the entity and its relations from the knowledge graph.</p>
    <p style={{ margin: '0 0 6px', color: 'var(--ink-2)' }}>Its timeline facts are closed from now on; earlier positions of the scrubber still show what was believed then.
      Erasing the history itself is a separate action (the admin forget tool), not this button.
      The conversation history is not edited, so a later mention can create it again.</p>
    <p style={{ margin: '0 0 6px', color: 'var(--ink-2)' }}>{KERNEL_NOTE} {PERSIST_NOTE}</p>
    {error && <div role="alert" style={{ color: 'var(--amber)', margin: '6px 0', overflowWrap: 'anywhere' }}>{error}</div>}
    <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', marginTop: 8 }}>
      <button className="tool-btn" onClick={onClose} disabled={busy}>Cancel</button>
      <button className="tool-btn danger" onClick={confirm} disabled={busy} style={{ color: 'var(--red)', borderColor: 'var(--red)' }}>{busy ? 'Deleting…' : gone ? 'Refresh map' : 'Delete memory'}</button>
    </div>
  </Modal>;
}
