import React, { useEffect, useId, useRef, useState } from 'react';
import { apiGet, apiPatch } from './api/client';
import { SaveFactForm } from './panels/saved-facts';
import { inpS, taS } from './panel-kit';

type Store = 'memory' | 'user';
type Fact = { entry_id: string; store: Store; value: string };
const PATH = '/api/dashboard/today/entries';
const idFor = (store: Store) => new RegExp(`^memory:${store}:[0-9a-f]{16}$`);
const normalized = (value: string) => value.trim().replace(/[\s\u0085\u001c-\u001f]+/gu, ' ');

function ReplaceFact({ draft, setDraft, store, setStore, busy, setBusy }: {
  draft: string; setDraft: (value: string) => void; store: Store; setStore: (value: Store) => void;
  busy: boolean; setBusy: (value: boolean) => void;
}) {
  const [facts, setFacts] = useState<Fact[]>([]);
  const [selected, setSelected] = useState('');
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState('');
  const [needsReload, setNeedsReload] = useState(false);
  const [reload, setReload] = useState(0);
  const old = facts.find(fact => fact.entry_id === selected);
  const value = normalized(draft);
  const length = Array.from(draft.trim()).length;
  const duplicate = facts.some(fact => fact.entry_id !== selected && fact.value === value);
  const canSave = !!old && !loading && !busy && !needsReload && length > 0 && length <= 300 && value !== old.value && !duplicate;

  useEffect(() => {
    let live = true;
    setLoading(true);
    setFacts([]);
    setSelected('');
    setNotice('');
    setNeedsReload(false);
    apiGet<unknown>(`/api/memory/core/facts?store=${store}`, { admin: false, cache: 'no-store', redirect: 'error' })
      .then(raw => {
        if (!live) return;
        const entries = (raw as { entries?: unknown })?.entries;
        if (!Array.isArray(entries) || entries.length > 20 || entries.some(f => !f || typeof f !== 'object' || Array.isArray(f)
          || typeof f.entry_id !== 'string' || !idFor(store).test(f.entry_id) || f.store !== store || typeof f.value !== 'string'
          || !f.value.trim())
          || new Set(entries.map(f => f.entry_id)).size !== entries.length) {
          setNotice('Saved facts could not be verified. Reload to try again.');
          setNeedsReload(true);
          return;
        }
        setFacts(entries);
      })
      .catch(cause => {
        if (!live) return;
        setNotice([401, 403].includes(cause?.status) ? 'Owner access is required to view saved facts.' : 'Saved facts could not be loaded. Reload to try again.');
        setNeedsReload(true);
      })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [store, reload]);

  const save = async () => {
    if (!canSave || !old) return;
    setBusy(true);
    setNotice('');
    try {
      const result = await apiPatch<{ ok?: boolean; changed?: boolean; entry?: Fact; previous_id?: string }>(
        `${PATH}/${encodeURIComponent(old.entry_id)}`, { value: draft.trim() }, { admin: false });
      if (result?.ok !== true || typeof result.changed !== 'boolean' || !result.entry || Array.isArray(result.entry)
        || typeof result.entry.entry_id !== 'string' || result.entry.store !== store || !idFor(store).test(result.entry.entry_id)
        || typeof result.entry.value !== 'string' || (result.changed ? result.previous_id !== old.entry_id : result.entry.entry_id !== old.entry_id)
        || result.entry.value !== (result.changed ? value : old.value)) {
        setNotice('Replacement could not be verified. Reload saved facts before trying again.');
        setNeedsReload(true);
        setSelected('');
        return;
      }
      if (!result.changed) {
        setNotice('No change to the saved fact.');
        return;
      }
      setFacts(current => current.map(f => f.entry_id === old.entry_id ? result.entry! : f));
      setSelected(result.entry.entry_id);
      setDraft(result.entry.value);
      setNotice('Replaced saved fact. New conversations can include it when automatic memory is on.');
    } catch (cause) {
      const status = (cause as { status?: number })?.status;
      if (status === 404 || status === 409) {
        setSelected('');
        setNeedsReload(true);
        setNotice('Saved fact changed or is unavailable. Reload saved facts and select the original again. Your draft is still here.');
      } else {
        setNotice('Replacement refused. Your draft is still here.');
      }
    } finally { setBusy(false); }
  };

  return <div style={{ display: 'grid', gap: 14, minWidth: 0, marginTop: 16 }}>
    <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5 }}>Select the exact saved fact to replace. Review the original and replacement before saving.</p>
    <label style={{ display: 'grid', gap: 6, minWidth: 0, fontSize: 12, fontWeight: 600 }}>Saved fact store
      <select aria-label="Saved fact store" value={store} disabled={busy} onChange={e => { setStore(e.target.value as Store); setSelected(''); }} style={{ ...inpS, display: 'block', width: '100%', minWidth: 0, minHeight: 44, boxSizing: 'border-box', fontSize: 13 }}>
        <option value="memory">Agent notes</option><option value="user">User profile</option>
      </select>
    </label>
    <div style={{ display: 'grid', gap: 8, minWidth: 0 }}>
    {loading ? <p role="status" style={{ margin: 0 }}>Loading saved facts…</p> : !facts.length && !needsReload ? <p role="status" style={{ margin: 0 }}>No saved facts in this store.</p> : <label style={{ display: 'grid', gap: 6, minWidth: 0, fontSize: 12, fontWeight: 600 }}>Saved fact to replace
      <select aria-label="Saved fact to replace" value={selected} disabled={busy || !facts.length || needsReload} onChange={e => setSelected(e.target.value)} style={{ ...inpS, display: 'block', width: '100%', minWidth: 0, minHeight: 44, boxSizing: 'border-box', fontSize: 13 }}>
        <option value="">Select a saved fact</option>
        {facts.map(fact => <option key={fact.entry_id} value={fact.entry_id}>{fact.value}</option>)}
      </select>
    </label>}
    <button type="button" className="tool-btn" disabled={busy || loading} onClick={() => { setSelected(''); setReload(n => n + 1); }} style={{ justifySelf: 'start', minHeight: 44 }}>Reload saved facts</button>
    </div>
    {old && <div style={{ minWidth: 0, padding: 12, border: '1px solid var(--panel-line)', borderRadius: 6, background: 'var(--surface-2)' }}>
      <strong style={{ display: 'block', fontSize: 12 }}>Original saved fact</strong>
      <output style={{ display: 'block', marginTop: 6, fontSize: 13, lineHeight: 1.5, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{old.value}</output>
    </div>}
    <label style={{ display: 'grid', gap: 6, minWidth: 0, fontSize: 12, fontWeight: 600 }}>Replacement fact
      <textarea aria-label="Replacement fact" value={draft} disabled={busy} onChange={e => setDraft(e.target.value)} rows={3} style={{ ...taS, display: 'block', width: '100%', minHeight: 96, boxSizing: 'border-box', resize: 'vertical', fontSize: 13, lineHeight: 1.5 }} />
    </label>
    {length > 300 && <p role="status" style={{ margin: 0 }}>{length}/300 characters · shorten the fact to save.</p>}
    {old && duplicate && <p role="status" style={{ margin: 0 }}>That fact is already saved in this store.</p>}
    {notice && <p role="status" style={{ margin: 0, lineHeight: 1.5 }}>{notice}</p>}
    <button type="button" className="tool-btn" disabled={!canSave} onClick={save}
      style={{ minHeight: 44, paddingInline: 16, justifySelf: 'start', background: canSave ? 'var(--accent)' : undefined, color: canSave ? 'var(--void)' : undefined, fontWeight: 700 }}>Save replacement</button>
  </div>;
}

export function RememberMessageDialog({ text, opener, onClose }: { text: string; opener: HTMLElement; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const title = useId();
  const [replacing, setReplacing] = useState(false);
  const [draft, setDraft] = useState(text);
  const [store, setStore] = useState<Store>('memory');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    dialog.querySelector<HTMLTextAreaElement>('textarea')?.focus();
    return () => { dialog.close(); if (opener.isConnected) opener.focus(); };
  }, [opener]);
  return <dialog className="job-create-dialog" ref={ref} aria-labelledby={title} aria-modal="true"
    style={{ width: 'min(520px, calc(100vw - 32px))', maxHeight: '90vh', overflowY: 'auto', boxSizing: 'border-box',
      padding: 20, border: '1px solid var(--panel-line)', borderRadius: 8, background: 'var(--void)', color: 'var(--ink)' }}
    onCancel={e => { e.preventDefault(); onClose(); }}
    onKeyDown={e => {
      e.stopPropagation();
      if (e.key === 'Escape') { e.preventDefault(); onClose(); }
    }}>
    <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
      <h2 id={title} style={{ margin: 0, fontSize: 18 }}>Remember message</h2>
      <button type="button" className="tool-btn" onClick={onClose} style={{ minHeight: 44, minWidth: 44 }}>Close</button>
    </header>
    <button type="button" className="tool-btn" disabled={busy} onClick={() => setReplacing(!replacing)} style={{ minHeight: 44, marginTop: 12 }}>
      {replacing ? 'Save a new fact' : 'Replace a saved fact'}
    </button>
    {replacing ? <ReplaceFact draft={draft} setDraft={setDraft} store={store} setStore={setStore} busy={busy} setBusy={setBusy} /> : <>
      <p style={{ fontSize: 12 }}>Edit the fact before saving it for future chats.</p>
      <SaveFactForm chatState={{ draft, store, busy, setDraft, setStore, setBusy }} />
    </>}
  </dialog>;
}
