import React, { useEffect, useId, useRef, useState } from 'react';
import { apiGet, getAdminToken, getToken } from '../../api/client';
import { onOwnerSession, ownerSignedIn } from '../../api/owner-session';
import { historyOwnerKey, historySourceLabel } from '../../chat-history-search';
import { talkStrings } from './strings';

type Store = 'memory' | 'user';
type Source = { session_id: string; turn: number; role: 'user' | 'assistant'; revision: string };
type Fact = { entry_id: string; store: Store; value: string; source?: Source | null };

export function mayFindSavedSource(): boolean {
  if (getAdminToken()) return true;
  if (getToken()) return false;
  return ownerSignedIn();
}

const normalized = (value: string) => value.normalize('NFKC').toLocaleLowerCase();
const isFact = (value: unknown, store: Store): value is Fact => {
  const row = value as Partial<Fact> | null;
  return !!row && typeof row.entry_id === 'string' && row.store === store && typeof row.value === 'string';
};

export function RecalledFactSourceDialog({ reply, lang, opener, onClose }: {
  reply: string; lang: string; opener: HTMLElement; onClose: () => void;
}) {
  const s = talkStrings(lang);
  const title = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const phraseInput = useRef<HTMLInputElement>(null);
  const generation = useRef(0);
  const owner = useRef(historyOwnerKey());
  const [phrase, setPhrase] = useState(reply);
  const [facts, setFacts] = useState<Fact[]>([]);
  const [loading, setLoading] = useState(true);
  const [readError, setReadError] = useState(false);
  const [opened, setOpened] = useState<{ key: string; content: string } | null>(null);
  const [sourceError, setSourceError] = useState('');
  const [opening, setOpening] = useState(false);
  const validPhrase = !!phrase.trim() && reply.includes(phrase);
  const matches = validPhrase ? facts.filter(fact => normalized(fact.value).includes(normalized(phrase))) : [];

  useEffect(() => {
    const node = dialog.current!;
    node.showModal();
    phraseInput.current?.focus();
    const invalidate = () => {
      if (!mayFindSavedSource() || owner.current !== historyOwnerKey()) closeRef.current();
    };
    const off = onOwnerSession(invalidate);
    window.addEventListener('storage', invalidate);
    return () => { ++generation.current; off(); window.removeEventListener('storage', invalidate); node.close(); opener.focus(); };
  }, [opener]);

  useEffect(() => {
    const current = ++generation.current;
    if (!mayFindSavedSource()) { closeRef.current(); return; }
    const path = (store: Store) => `/api/dashboard/today/entries?store=${store}&references=true`;
    void Promise.all([
      apiGet<unknown>(path('memory'), { admin: true, cache: 'no-store', redirect: 'error' }),
      apiGet<unknown>(path('user'), { admin: true, cache: 'no-store', redirect: 'error' }),
    ]).then(([notes, profile]) => {
      if (current !== generation.current || owner.current !== historyOwnerKey() || !mayFindSavedSource()) return;
      const read = (payload: unknown, store: Store) => {
        const entries = (payload as { entries?: unknown })?.entries;
        if (!Array.isArray(entries) || !entries.every(value => isFact(value, store))) throw new Error('invalid facts');
        return entries as Fact[];
      };
      setFacts([...read(notes, 'memory'), ...read(profile, 'user')]);
      setReadError(false);
    }).catch(() => { if (current === generation.current && owner.current === historyOwnerKey()) setReadError(true); })
      .finally(() => { if (current === generation.current) setLoading(false); });
  }, []);

  const openOriginal = async (fact: Fact, key: string) => {
    const source = fact.source;
    if (!source || !historySourceLabel(source) || opening) return;
    const current = ++generation.current;
    setOpening(true); setSourceError(''); setOpened(null);
    try {
      const raw = await apiGet<unknown>(`/sessions/${encodeURIComponent(source.session_id)}/transcript?references=true`,
        { admin: true, cache: 'no-store', redirect: 'error' });
      if (current !== generation.current || owner.current !== historyOwnerKey() || !mayFindSavedSource()) return;
      const transcript = raw as { schema_version?: unknown; session_id?: unknown; scope?: unknown; redacted?: unknown; turns?: unknown };
      if (transcript?.schema_version !== 1 || transcript.session_id !== source.session_id
        || transcript.scope !== 'retained_current_history' || transcript.redacted !== true
        || !Array.isArray(transcript.turns) || transcript.turns.length > 100) throw new Error('changed');
      const turn = transcript.turns.find(row => row?.turn === source.turn && row?.role === source.role
        && row?.reference_revision === source.revision && typeof row?.content === 'string'
        && row.content.length <= 2 * 1024 * 1024);
      if (!turn) throw new Error('changed');
      setOpened({ key, content: turn.content });
    } catch (error) {
      if (current === generation.current) setSourceError((error as Error)?.message === 'changed' ? s.sourceChanged : s.sourceReadError);
    } finally { if (current === generation.current) setOpening(false); }
  };

  return <dialog ref={dialog} className="job-create-dialog" aria-modal="true" aria-labelledby={title}
    onCancel={event => { event.preventDefault(); closeRef.current(); }}
    onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); closeRef.current(); } }}>
    <div style={{ display: 'grid', gap: 12, maxWidth: 640, minWidth: 'min(84vw, 420px)', padding: 16 }}>
      <h2 id={title} style={{ margin: 0 }}>{s.findSavedSource}</h2>
      <p style={{ margin: 0 }}>{s.sourceCaveat}</p>
      <label style={{ display: 'grid', gap: 5 }}>{s.sourcePhrase}
        <input ref={phraseInput} aria-label={s.sourcePhrase} value={phrase} onChange={event => { setPhrase(event.target.value); setOpened(null); setSourceError(''); }} />
      </label>
      {!validPhrase ? <p role="status">{s.sourcePhraseInvalid}</p>
        : loading ? <p role="status">{s.sourceLoading}</p>
        : readError ? <p role="alert">{s.sourceUnavailable}</p>
        : matches.length ? <section aria-label={s.sourceMatching}><h3>{s.sourceMatching}</h3>
          <ul style={{ display: 'grid', gap: 12, paddingLeft: 20 }}>{matches.map((fact, index) => {
            const key = `${fact.store}:${fact.entry_id}:${index}`;
            const sourceLabel = historySourceLabel(fact.source);
            const store = fact.store === 'memory' ? s.sourceNotes : s.sourceProfile;
            return <li key={key}><div>{fact.value}</div>
              <small>{sourceLabel ?? s.sourceManual.replace('{store}', store)}</small>
              {sourceLabel && <div><button type="button" disabled={opening} onClick={() => { void openOriginal(fact, key); }}>{s.sourceOpen}</button></div>}
              {opened?.key === key && <div><strong>{s.sourceOriginal}</strong><p style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{opened.content}</p></div>}
            </li>;
          })}</ul></section>
        : <p role="status">{s.sourceNone}</p>}
      {opening && <p role="status">{s.sourceOpening}</p>}
      {sourceError && <p role="alert">{sourceError}</p>}
      <button type="button" onClick={() => closeRef.current()}>{s.sourceClose}</button>
    </div>
  </dialog>;
}
