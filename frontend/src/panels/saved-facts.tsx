import React, { useEffect, useRef, useState } from 'react';
import { apiDelete, apiGet, apiPatch, apiPost, getAdminToken } from '../api/client';
import { onOwnerSession, ownerSignedIn } from '../api/owner-session';
import { historyOwnerKey, historySourceLabel } from '../chat-history-search';
import { ConfirmAction, RISK_TIER } from '../confirm';
import { inpS, taS } from '../panel-kit';
import { LABEL } from '../theme/type';

type Store = 'memory' | 'user';
type Fact = { entry_id: string; store: Store; value: string; source?: { session_id: string; turn: number; revision: string; role: 'user' | 'assistant' } | null };
type FactResult = { ok: boolean; changed: boolean; entry?: Fact };
const PATH = '/api/dashboard/today/entries';
const label = (store: Store) => store === 'memory' ? 'Agent notes' : 'User profile';
const factLength = (value: string) => Array.from(value.trim()).length;
const patchFact = (entry: Fact, value: string, admin: boolean) =>
  apiPatch<FactResult>(`${PATH}/${encodeURIComponent(entry.entry_id)}`, { value }, { admin });
const reason = (error: unknown) => {
  const e = error as { status?: number; body?: { reason?: unknown; detail?: unknown } };
  const detail = e?.body?.detail || e?.body?.reason;
  return `${e?.status ? ` (${e.status})` : ''}${typeof detail === 'string' ? ` · ${detail.slice(0, 160)}` : ''}`;
};

type MemoryView = {
  busy: boolean;
  canSave: boolean;
  setBusy: (value: boolean) => void;
  setMessage: (value: string) => void;
  onSaved: (entry?: Fact) => void;
};
type ChatState = { draft: string; store: Store; busy: boolean; setDraft: (value: string) => void;
  setStore: (value: Store) => void; setBusy: (value: boolean) => void };
export type RememberSource = { sessionId?: string; text: string; role: 'user' | 'assistant'; agentId?: string };
type SourceInput = { session_id: string; turn: number; revision: string; excerpt: string };
const sourceRevision = /^[0-9a-f]{64}$/;
const sessionIdentifier = /^[A-Za-z0-9_-]{1,128}$/;

async function resolveRememberSource(source: RememberSource): Promise<SourceInput> {
  if (!source.sessionId || !sessionIdentifier.test(source.sessionId) || new TextEncoder().encode(source.text).length > 8000)
    throw new Error('source_unavailable');
  const raw = await apiGet<unknown>(`/sessions/${encodeURIComponent(source.sessionId)}/transcript?references=true`,
    { admin: true, cache: 'no-store', redirect: 'error' });
  const transcript = raw as { schema_version?: unknown; session_id?: unknown; scope?: unknown; redacted?: unknown; turns?: unknown };
  if (transcript?.schema_version !== 1 || transcript.session_id !== source.sessionId
    || transcript.scope !== 'retained_current_history' || transcript.redacted !== true || !Array.isArray(transcript.turns))
    throw new Error('source_unavailable');
  const matches = transcript.turns.filter((turn: unknown) => {
    const row = turn as { turn?: unknown; role?: unknown; agent_id?: unknown; content?: unknown; reference_revision?: unknown };
    return row && row.role === source.role && row.content === source.text
      && (source.role === 'user' || row.agent_id === source.agentId)
      && Number.isSafeInteger(row.turn) && (row.turn as number) >= 0
      && typeof row.reference_revision === 'string' && sourceRevision.test(row.reference_revision);
  }) as { turn: number; reference_revision: string }[];
  if (matches.length !== 1) throw new Error('source_unavailable');
  return { session_id: source.sessionId, turn: matches[0].turn,
    revision: matches[0].reference_revision, excerpt: source.text };
}

/** A chat save uses the current chat credentials and never reads the shared rings. */
export function SaveFactForm({ initialDraft = '', memoryView, chatState, chatSource }: { initialDraft?: string; memoryView?: MemoryView; chatState?: ChatState; chatSource?: RememberSource }) {
  const [localStore, setLocalStore] = useState<Store>('memory');
  const [localDraft, setLocalDraft] = useState(initialDraft);
  const [saved, setSaved] = useState<Fact | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState('');
  const [manual, setManual] = useState(false);
  const [sourceFailed, setSourceFailed] = useState(false);
  const live = useRef(true);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  const store = chatState?.store ?? localStore;
  const draft = chatState?.draft ?? localDraft;
  const setStore = chatState?.setStore ?? setLocalStore;
  const setDraft = chatState?.setDraft ?? setLocalDraft;
  const draftLength = factLength(draft);
  const busy = memoryView?.busy ?? chatState?.busy ?? saving;
  const setBusy = memoryView?.setBusy ?? chatState?.setBusy ?? setSaving;
  const setMessage = memoryView?.setMessage ?? setNotice;
  const canSubmit = !busy && (memoryView?.canSave ?? true) && draftLength > 0 && draftLength <= 300 && draft.trim() !== saved?.value;

  const save = async () => {
    if (!canSubmit) return;
    setBusy(true); setMessage('');
    let attemptingSource = false;
    try {
      const value = draft.trim();
      let source: SourceInput | undefined;
      if (!saved && chatSource && !manual) {
        const owner = historyOwnerKey();
        try {
          source = await resolveRememberSource(chatSource);
          if (!live.current || owner !== historyOwnerKey()) return;
        } catch {
          if (!live.current) return;
          setSourceFailed(true);
          setMessage('Could not verify the selected chat message. Your draft is unchanged. Choose manual save without chat source if you still want this fact.');
          return;
        }
      }
      attemptingSource = !!source;
      const result = saved ? await patchFact(saved, value, false) :
        await apiPost<FactResult>(PATH, { store, value, ...(source ? { source } : {}) }, { admin: memoryView !== undefined || !!source });
      if (!live.current) return;
      if (result?.ok === true && result.changed === false) {
        setMessage(saved ? 'No change to the saved fact.' : 'Fact already saved; nothing changed.');
        memoryView?.onSaved();
        return;
      }
      const entry = result?.entry;
      if (result?.ok !== true || result.changed !== true || !entry?.entry_id || entry.store !== store || typeof entry.value !== 'string') {
        setMessage(saved ? 'Fact was not corrected.' : 'Fact was not saved.');
        return;
      }
      memoryView?.onSaved(entry);
      if (!memoryView) setSaved(entry);
      setDraft(memoryView ? '' : entry.value);
      const linked = source && entry.source?.session_id === source.session_id && entry.source.turn === source.turn
        && entry.source.revision === source.revision && entry.source.role === chatSource?.role;
      setMessage(source && !linked ? 'Fact saved, but its chat source receipt could not be verified. Check Saved Facts.'
        : `${saved ? 'Corrected' : 'Saved'} fact in ${label(entry.store)}. New conversations can include it when automatic memory is on.`);
    } catch (error) {
      if (attemptingSource) setSourceFailed(true);
      setMessage(`${saved ? 'Correction' : 'Save'} refused${reason(error)}. The draft is still here.${attemptingSource ? ' Choose manual save without chat source if you still want this fact.' : ''}`);
    }
    finally { setBusy(false); }
  };

  return <>
    <p style={{ fontSize: 'var(--n-fs-label)', margin: '0 0 8px' }}>Saved facts are shared across agents. With automatic memory on, new owner chats can include them on the selected local or cloud model.</p>
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'end' }}>
      <label style={{ fontSize: 'var(--n-fs-meta)', flex: '1 1 120px' }}>Save in
        <select aria-label="Save in" value={store} disabled={busy || !!saved} tabIndex={0} onChange={e => setStore(e.target.value as Store)} style={{ ...inpS, display: 'block', width: '100%', minWidth: 0, boxSizing: 'border-box' }}>
          <option value="memory">Agent notes</option><option value="user">User profile</option>
        </select>
      </label>
      <label style={{ fontSize: 'var(--n-fs-meta)', flex: '3 1 220px', minWidth: 0 }}>Fact to save
        <textarea aria-label="Fact to save" value={draft} disabled={busy} tabIndex={0} onChange={e => setDraft(e.target.value)} rows={2} style={{ ...taS, display: 'block', width: '100%', boxSizing: 'border-box', resize: 'vertical' }} />
      </label>
      <button className="tool-btn" disabled={!canSubmit} onClick={save}>{saved ? 'Save correction' : 'Save fact'}</button>
    </div>
    {draftLength > 300 && <div role="status">{draftLength}/300 characters · shorten the fact to save.</div>}
    {chatSource && sourceFailed && !saved && !manual && <button type="button" className="tool-btn" disabled={busy}
      onClick={() => { setManual(true); setNotice('Manual save selected. This fact will have no chat source.'); }}>Choose manual save without chat source</button>}
    {chatSource && manual && !saved && <p role="status">Manual save selected. This fact will have no chat source.</p>}
    {notice && <p role="status" style={{ fontSize: 'var(--n-fs-label)', overflowWrap: 'anywhere' }}>{notice}</p>}
  </>;
}


/** Owner-selected, curated facts. This list never reads skills or the broader search index. */
export function SavedFacts() {
  const [facts, setFacts] = useState<Fact[]>([]);
  const [sourceOwnerKey, setSourceOwnerKey] = useState<string | null>(null);
  const [injected, setInjected] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [readError, setReadError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [editing, setEditing] = useState<Fact | null>(null);
  const [correction, setCorrection] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [undo, setUndo] = useState<string | null>(null);
  const correctionLength = factLength(correction);
  const mayShowSource = !loading && !readError && sourceOwnerKey !== null
    && sourceOwnerKey === historyOwnerKey() && (ownerSignedIn() || !!getAdminToken());
  useEffect(() => {
    const refreshOwner = () => setRefresh(n => n + 1);
    const unsubscribe = onOwnerSession(refreshOwner);
    const credentialChanged = (event: StorageEvent) => {
      if (event.key === 'hud.admin_token' || event.key === 'hud.user_token') refreshOwner();
    };
    window.addEventListener('storage', credentialChanged);
    return () => { unsubscribe(); window.removeEventListener('storage', credentialChanged); };
  }, []);

  useEffect(() => {
    let live = true;
    setLoading(true);
    const references = ownerSignedIn() || !!getAdminToken();
    const ownerKey = historyOwnerKey();
    const factPath = (store: Store) => `${PATH}?store=${store}${references ? '&references=true' : ''}`;
    Promise.all([
      apiGet<{ injected?: boolean }>('/api/memory'),
      apiGet<{ entries: Fact[] }>(factPath('memory'), { admin: references }),
      apiGet<{ entries: Fact[] }>(factPath('user'), { admin: references }),
    ]).then(([status, notes, profile]) => {
      if (!live) return;
      if (!Array.isArray(notes?.entries) || !Array.isArray(profile?.entries)) throw new Error('invalid fact list');
      setInjected(status?.injected === true);
      setFacts([...notes.entries, ...profile.entries]);
      setSourceOwnerKey(references && ownerKey === historyOwnerKey() ? ownerKey : null);
      setReadError(false);
    }).catch(() => { if (live) setReadError(true); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [refresh]);


  const correct = async (fact: Fact) => {
    const value = correction.trim();
    if (!value || correctionLength > 300 || busy) return;
    setBusy(true); setMessage('');
    try {
      const result = await patchFact(fact, value, true);
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
    <div className="dl" style={{ ...LABEL, fontSize: 'var(--n-fs-meta)', color: 'var(--ink-2)', marginBottom: 8 }}>Saved facts</div>
    {injected === false && <p role="status" style={{ fontSize: 'var(--n-fs-label)', color: 'var(--amber)', margin: '0 0 8px' }}>Automatic memory is off; new saves are unavailable. Existing facts remain stored.</p>}
    <SaveFactForm memoryView={{ busy, canSave: !loading && !readError && injected === true, setBusy, setMessage,
      onSaved: entry => {
        if (!entry) { setRefresh(n => n + 1); return; }
        setFacts(current => [...current.filter(f => f.entry_id !== entry.entry_id), entry]);
        setUndo(null);
      } }} />
    {message && <p role="status" style={{ fontSize: 'var(--n-fs-meta)', color: /refused|not saved|not corrected/i.test(message) ? 'var(--amber)' : 'var(--accent-light)' }}>{message}</p>}
    {undo && <button className="tool-btn" disabled={busy} aria-label="Undo forgotten fact" onClick={undoForget}>Undo forgotten fact</button>}
    <div style={{ marginTop: 12, fontSize: 'var(--n-fs-meta)', color: 'var(--ink-2)' }}>{loading ? 'Loading saved facts…' : readError ? 'Saved facts unavailable. Try again.' : facts.length ? `${facts.length} saved fact${facts.length === 1 ? '' : 's'}` : 'No saved facts.'}</div>
    {readError && <button className="tool-btn" onClick={() => setRefresh(n => n + 1)}>Retry</button>}
    {!readError && facts.map(fact => <div key={fact.entry_id} style={{ borderTop: '1px solid var(--panel-line)', padding: '8px 0', overflowWrap: 'anywhere' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'start' }}>
        <span style={{ flex: '1 1 200px', minWidth: 0, fontSize: 'var(--n-fs-label)' }}>{fact.value}</span>
        <button className="tool-btn" disabled={busy} aria-label={`Correct fact: ${fact.value}`} onClick={() => { setEditing(fact); setCorrection(fact.value); setMessage(''); }}>Correct fact</button>
        <ConfirmAction tier={RISK_TIER.REVERSIBLE} label="Forget fact" armedLabel="Confirm forget"
          ariaLabel={`Forget fact: ${fact.value}`} disabled={busy}
          prompt="Remove this entry from saved facts for future chats? Existing chats and this session are unchanged."
          onConfirm={() => forget(fact)} />
      </div>
      <div style={{ fontSize: 'var(--n-fs-meta)', color: 'var(--ink-2)' }}>
        {(mayShowSource ? historySourceLabel(fact.source) : null) ?? `Source: saved fact · ${label(fact.store)}`}
      </div>
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
