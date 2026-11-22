import React, { useEffect, useState } from 'react';
import { apiDelete, apiGet, apiPatch, apiPost } from '../api/client';
import { ConfirmAction, RISK_TIER } from '../confirm';
import { inpS, taS } from '../panel-kit';

type Store = 'memory' | 'user';
type Fact = { entry_id: string; store: Store; value: string };
const PATH = '/api/dashboard/today/entries';
const label = (store: Store) => store === 'memory' ? 'Agent notes' : 'User profile';
const factLength = (value: string) => Array.from(value.trim()).length;
const reason = (error: unknown) => {
  const e = error as { status?: number; body?: { reason?: unknown; detail?: unknown } };
  const detail = e?.body?.detail || e?.body?.reason;
  return `${e?.status ? ` (${e.status})` : ''}${typeof detail === 'string' ? ` · ${detail.slice(0, 160)}` : ''}`;
};

/** Owner-selected, curated facts. This list never reads skills or the broader search index. */
export function SavedFacts() {
  const [facts, setFacts] = useState<Fact[]>([]);
  const [injected, setInjected] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [readError, setReadError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [store, setStore] = useState<Store>('memory');
  const [draft, setDraft] = useState('');
  const [editing, setEditing] = useState<Fact | null>(null);
  const [correction, setCorrection] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [undo, setUndo] = useState<string | null>(null);
  const draftLength = factLength(draft);
  const correctionLength = factLength(correction);

  useEffect(() => {
    let live = true;
    setLoading(true);
    Promise.all([
      apiGet<{ injected?: boolean }>('/api/memory'),
      apiGet<{ entries: Fact[] }>(`${PATH}?store=memory`),
      apiGet<{ entries: Fact[] }>(`${PATH}?store=user`),
    ]).then(([status, notes, profile]) => {
      if (!live) return;
      if (!Array.isArray(notes?.entries) || !Array.isArray(profile?.entries)) throw new Error('invalid fact list');
      setInjected(status?.injected === true);
      setFacts([...notes.entries, ...profile.entries]);
      setReadError(false);
    }).catch(() => { if (live) setReadError(true); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [refresh]);

  const save = async () => {
    const value = draft.trim();
    if (!value || draftLength > 300 || injected === false || busy) return;
    setBusy(true); setMessage('');
    try {
      const result = await apiPost<{ ok: boolean; changed: boolean; entry?: Fact }>(PATH, { store, value }, { admin: true });
      if (!result?.ok || !result.changed || !result.entry?.entry_id) {
        setMessage(result?.ok && !result.changed ? 'Fact already saved; nothing changed.' : 'Fact was not saved.');
        if (result?.ok && !result.changed) setRefresh(n => n + 1);
        return;
      }
      setFacts(current => [...current.filter(f => f.entry_id !== result.entry!.entry_id), result.entry!]);
      setUndo(null);
      setDraft('');
      setMessage(`Saved fact in ${label(result.entry.store)}. New conversations can include it when automatic memory is on.`);
    } catch (error) { setMessage(`Save refused${reason(error)}. The draft is still here.`); }
    finally { setBusy(false); }
  };

  const correct = async (fact: Fact) => {
    const value = correction.trim();
    if (!value || correctionLength > 300 || busy) return;
    setBusy(true); setMessage('');
    try {
      const result = await apiPatch<{ ok: boolean; changed: boolean; entry?: Fact }>(
        `${PATH}/${encodeURIComponent(fact.entry_id)}`, { value }, { admin: true });
      if (!result?.ok || !result.changed || !result.entry?.entry_id) {
        setMessage(result?.ok && !result.changed ? 'No change to the saved fact.' : 'Fact was not corrected.');
        return;
      }
      setFacts(current => current.map(f => f.entry_id === fact.entry_id ? result.entry! : f));
      setUndo(null);
      setEditing(null); setCorrection('');
      setMessage(`Corrected fact in ${label(result.entry.store)}. New conversations can include it when automatic memory is on.`);
    } catch (error) {
      setMessage(`Correction refused${reason(error)}. The correction is still here.`);
      if ([404, 409].includes((error as { status?: number })?.status || 0)) setRefresh(n => n + 1);
    } finally { setBusy(false); }
  };

  const forget = async (fact: Fact): Promise<boolean> => {
    if (busy) return false;
    setBusy(true); setMessage('');
    try {
      const result = await apiDelete<{ ok: boolean; deleted?: string; undo_ref?: string }>(
        `${PATH}/${encodeURIComponent(fact.entry_id)}`, { admin: true });
      if (result?.ok !== true || result.deleted !== fact.entry_id) {
        setMessage('Forget not confirmed by the hub. The list was not changed here.');
        setRefresh(n => n + 1);
        return false;
      }
      setFacts(current => current.filter(f => f.entry_id !== fact.entry_id));
      setEditing(current => current?.entry_id === fact.entry_id ? null : current);
      setUndo(result.undo_ref || null);
      setMessage(`Removed this ${label(fact.store)} fact. Existing chats and this session may still contain it.${result.undo_ref ? '' : ' Undo is unavailable.'}`);
      setRefresh(n => n + 1);
      return true;
    } catch (error) {
      setMessage(`Forget refused${reason(error)}. The fact was not removed here.`);
      if ([404, 409].includes((error as { status?: number })?.status || 0)) setRefresh(n => n + 1);
      return false;
    } finally { setBusy(false); }
  };

  const undoForget = async () => {
    if (!undo || busy) return;
    const selected = undo;
    setBusy(true); setMessage('');
    try {
      const result = await apiPost<{ ok: boolean }>('/api/memory/core/undo', { ref: selected }, { admin: true });
      if (result?.ok !== true) {
        setMessage('Undo was not confirmed by the hub.');
        return;
      }
      setUndo(null);
      setMessage('Forgotten fact restored. New conversations can include it when automatic memory is on.');
      setRefresh(n => n + 1);
    } catch (error) { setMessage(`Undo refused${reason(error)}. Check saved facts before trying again.`); }
    finally { setBusy(false); }
  };

  return <section aria-label="Saved facts" style={{ border: '1px solid var(--panel-line)', borderRadius: 'var(--radius)', padding: 14, background: 'var(--surface-2)', marginBottom: 'var(--gap)' }}>
    <div className="dl" style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '.12em', textTransform: 'uppercase', color: 'var(--ink-2)', marginBottom: 8 }}>Saved facts</div>
    <p style={{ fontSize: 12, margin: '0 0 8px' }}>Saved facts can enter new owner chats on the selected local or cloud model.</p>
    {injected === false && <p role="status" style={{ fontSize: 12, color: 'var(--amber)', margin: '0 0 8px' }}>Automatic memory is off; new saves are unavailable. Existing facts remain stored.</p>}
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'end' }}>
      <label style={{ fontSize: 11, flex: '1 1 120px' }}>Save in
        <select aria-label="Save in" value={store} disabled={busy} tabIndex={0} onChange={e => setStore(e.target.value as Store)} style={{ ...inpS, display: 'block', width: '100%', minWidth: 0, boxSizing: 'border-box' }}>
          <option value="memory">Agent notes</option><option value="user">User profile</option>
        </select>
      </label>
      <label style={{ fontSize: 11, flex: '3 1 220px', minWidth: 0 }}>Fact to save
        <textarea aria-label="Fact to save" value={draft} disabled={busy} tabIndex={0} onChange={e => setDraft(e.target.value)} rows={2} style={{ ...taS, display: 'block', width: '100%', boxSizing: 'border-box', resize: 'vertical' }} />
      </label>
      <button className="tool-btn" disabled={busy || loading || injected === false || draftLength === 0 || draftLength > 300} onClick={save}>Save fact</button>
    </div>
    {draftLength > 300 && <div role="status">{draftLength}/300 characters · shorten the fact to save.</div>}
    {message && <p role="status" style={{ fontSize: 11, color: /refused|not saved|not corrected/i.test(message) ? 'var(--amber)' : 'var(--accent-light)' }}>{message}</p>}
    {undo && <button className="tool-btn" disabled={busy} aria-label="Undo forgotten fact" onClick={undoForget}>Undo forgotten fact</button>}
    <div style={{ marginTop: 12, fontSize: 11, color: 'var(--ink-2)' }}>{loading ? 'Loading saved facts…' : readError ? 'Saved facts unavailable. Try again.' : facts.length ? `${facts.length} saved fact${facts.length === 1 ? '' : 's'}` : 'No saved facts.'}</div>
    {readError && <button className="tool-btn" onClick={() => setRefresh(n => n + 1)}>Retry</button>}
    {!readError && facts.map(fact => <div key={fact.entry_id} style={{ borderTop: '1px solid var(--panel-line)', padding: '8px 0', overflowWrap: 'anywhere' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'start' }}>
        <span style={{ flex: '1 1 200px', minWidth: 0, fontSize: 12 }}>{fact.value}</span>
        <button className="tool-btn" disabled={busy} aria-label={`Correct fact: ${fact.value}`} onClick={() => { setEditing(fact); setCorrection(fact.value); setMessage(''); }}>Correct fact</button>
        <ConfirmAction tier={RISK_TIER.REVERSIBLE} label="Forget fact" armedLabel="Confirm forget"
          ariaLabel={`Forget fact: ${fact.value}`} disabled={busy}
          prompt="Remove this entry from saved facts for future chats? Existing chats and this session are unchanged."
          onConfirm={() => forget(fact)} />
      </div>
      <div style={{ fontSize: 10, color: 'var(--ink-2)' }}>Source: saved fact · {label(fact.store)}</div>
      {editing?.entry_id === fact.entry_id && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 6 }}>
        <input aria-label="Corrected fact" value={correction} disabled={busy} onChange={e => setCorrection(e.target.value)} style={{ ...inpS, flex: '1 1 220px', minWidth: 0 }} />
        <button className="tool-btn" disabled={busy || correctionLength === 0 || correctionLength > 300 || editing.value !== fact.value} onClick={() => correct(fact)}>Save correction</button>
        <button className="tool-btn" disabled={busy} onClick={() => setEditing(null)}>Cancel</button>
        {correctionLength > 300 && <span role="status">{correctionLength}/300 characters · shorten the correction to save.</span>}
        {editing.value !== fact.value && <span role="status">This fact changed elsewhere. Review the current value, then select Correct fact again.</span>}
      </div>}
    </div>)}
    {editing && !facts.some(fact => fact.entry_id === editing.entry_id) && <div role="status" style={{ borderTop: '1px solid var(--panel-line)', paddingTop: 8 }}>
      This fact is no longer in the saved list. Your correction draft is below; copy it or select another fact.
      <input aria-label="Corrected fact" value={correction} readOnly style={{ ...inpS, display: 'block', width: '100%', boxSizing: 'border-box', marginTop: 6 }} />
      <button className="tool-btn" onClick={() => setEditing(null)}>Close draft</button>
    </div>}
  </section>;
}
