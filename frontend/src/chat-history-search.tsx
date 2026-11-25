import React, { useEffect, useId, useRef, useState } from 'react';
import { apiGet, apiPost, getAdminToken, getToken } from './api/client';
import { csrfToken, isNetworkedOrigin, onOwnerSession, ownerSession } from './api/owner-session';
import { isLocalOnlyAgent } from './signals/agents-policy';
import './chat-history-search.css';

type Hit = { session_id: string; turn: number; role: 'user' | 'assistant'; timestamp: string | null;
  agent_id: string | null; snippet: string; injection_flagged?: boolean };
type Search = { hits: Hit[]; truncated: boolean; stopped_by: string | null };
type Turn = { turn: number; role: 'user' | 'assistant'; timestamp: string; agent_id: string | null; content: string; reference_revision?: string };
type Transcript = { schema_version: 1; session_id: string; scope: 'retained_current_history';
  redacted: true; turns: Turn[] };
export type HistoryReference = { session_id: string; turn: number; revision: string; excerpt: string; allow_cloud: boolean };
export const historyOwnerKey = () => JSON.stringify([getToken(), getAdminToken(), csrfToken()]);
export function historySourceLabel(source: unknown): string | null {
  const row = source as { session_id?: unknown; turn?: unknown; role?: unknown; revision?: unknown } | null;
  return row && typeof row.session_id === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(row.session_id)
    && Number.isSafeInteger(row.turn) && (row.turn as number) >= 0
    && (row.role === 'user' || row.role === 'assistant')
    && typeof row.revision === 'string' && /^[0-9a-f]{64}$/.test(row.revision)
    ? `Chat source: ${row.session_id} · message ${(row.turn as number) + 1} · ${row.role}` : null;
}
const excerptBytes = (text: string) => new TextEncoder().encode(text).length;

const copy = {
  en: { title: 'Search chat history', query: 'Search saved message text', search: 'Search', close: 'Close',
    hint: 'Searches saved conversation turns. Open a result to review its current, redacted source.',
    searching: 'Searching…', reviewing: 'Opening source…', continuing: 'Reopening conversation…',
    empty: 'No saved messages match.', review: 'Review source', continue: 'Continue this conversation',
    changed: 'This saved turn changed or cannot be verified. Search again.',
    failed: 'Could not search saved messages. Try again.', sourceFailed: 'Could not verify the saved turn. Search again.',
    resumeFailed: 'Could not reopen this conversation. Try again.',
    ownerOnly: 'Only the owner can search saved conversations. Sign in as the owner and try again.',
    activeTurn: 'Finish or stop the current reply before continuing another conversation.',
    draft: 'Your typed message will stay in the composer after reopening this conversation.',
    attachment: 'Send or remove the current attachment before continuing. Search and review still work.',
    agent: 'The agent selected for the current conversation may need to be chosen again.',
    use: 'Use in this chat', selection: 'Select exact text from the verified message', full: 'Use full message',
    useUnavailable: 'This saved message cannot be cited in another chat. You can still review or continue it.',
    tooLong: 'Select a passage of at most 8,000 UTF-8 bytes.', noSelection: 'Select a passage first.',
    cloud: 'Allow the selected agent to receive this passage if it uses a cloud model',
    disclosure: 'The selected agent receives only the passage you choose when you send your next message. The current conversation stays open.',
    local: 'This selected agent is strictly local.', staged: 'The passage is attached to your current draft. Review it before sending.',
    limited: 'Results are limited; this is not a complete archive search.',
  },
  ro: { title: 'Caută în conversații', query: 'Caută în mesajele salvate', search: 'Caută', close: 'Închide',
    hint: 'Caută în mesajele salvate. Deschide un rezultat pentru a vedea sursa actuală, cu datele sensibile mascate.',
    searching: 'Se caută…', reviewing: 'Se deschide sursa…', continuing: 'Se redeschide conversația…',
    empty: 'Niciun mesaj salvat nu corespunde.', review: 'Vezi sursa', continue: 'Continuă această conversație',
    changed: 'Acest mesaj s-a schimbat sau nu poate fi verificat. Caută din nou.',
    failed: 'Nu am putut căuta în mesajele salvate. Încearcă din nou.', sourceFailed: 'Nu am putut verifica mesajul salvat. Caută din nou.',
    resumeFailed: 'Nu am putut redeschide conversația. Încearcă din nou.',
    ownerOnly: 'Doar proprietarul poate căuta în conversațiile salvate. Autentifică-te ca proprietar și încearcă din nou.',
    activeTurn: 'Așteaptă răspunsul curent sau oprește-l înainte să continui altă conversație.',
    draft: 'Textul scris va rămâne în câmpul de mesaj după redeschiderea conversației.',
    attachment: 'Trimite sau elimină atașamentul înainte de continuare. Poți căuta și verifica sursa.',
    agent: 'Este posibil să fie nevoie să alegi din nou agentul pentru această conversație.',
    limited: 'Rezultatele sunt limitate; aceasta nu este o căutare completă în arhivă.',
    use: 'Folosește în acest chat', selection: 'Selectează textul exact din mesajul verificat', full: 'Folosește mesajul complet',
    useUnavailable: 'Acest mesaj nu poate fi citat în alt chat. Îl poți vedea sau continua.',
    tooLong: 'Selectează un pasaj de cel mult 8.000 de octeți UTF-8.', noSelection: 'Selectează mai întâi un pasaj.',
    cloud: 'Permite agentului selectat să primească pasajul dacă folosește un model cloud',
    disclosure: 'Agentul selectat primește doar pasajul ales când trimiți următorul mesaj. Conversația curentă rămâne deschisă.',
    local: 'Agentul selectat rulează strict local.', staged: 'Pasajul este atașat la ciorna curentă. Verifică-l înainte de trimitere.',
  },
};

function validHit(value: any): value is Hit {
  return value && typeof value.session_id === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(value.session_id)
    && Number.isSafeInteger(value.turn) && value.turn >= 0 && (value.role === 'user' || value.role === 'assistant')
    && (value.timestamp === null || typeof value.timestamp === 'string')
    && (value.agent_id === null || typeof value.agent_id === 'string')
    && typeof value.snippet === 'string' && value.snippet.length <= 484
    && Array.from(value.snippet).length <= 242;
}

function sourceTurn(value: any, hit: Hit): Turn | null {
  if (value?.schema_version !== 1 || value.session_id !== hit.session_id || value.scope !== 'retained_current_history'
    || value.redacted !== true || !Array.isArray(value.turns) || value.turns.length > 100 || hit.injection_flagged) return null;
  const turn = (value as Transcript).turns.find(row => row?.turn === hit.turn);
  const snippet = hit.snippet.replace(/^…/, '').replace(/…$/, '');
  return turn && turn.role === hit.role && turn.timestamp === hit.timestamp && turn.agent_id === hit.agent_id
    && typeof turn.content === 'string' && turn.content.length <= 2 * 1024 * 1024
    && !!snippet && turn.content.includes(snippet) ? turn : null;
}

export function ChatHistorySearch({ lang, opener, onClose, hasDraft, hasAttachment, turnActive, canContinue, onUse, canUse, recipient }: {
  lang: string; opener: HTMLElement | null; onClose: () => void; hasDraft: boolean; hasAttachment: boolean;
  turnActive?: boolean; canContinue?: () => boolean; onUse?: (reference: HistoryReference, role: 'user' | 'assistant') => boolean;
  canUse?: () => boolean; recipient?: string;
}) {
  const k = lang === 'ro' ? copy.ro : copy.en;
  const dialog = useRef<HTMLDialogElement>(null);
  const generation = useRef(0);
  const busy = useRef(false);
  const initialOwnerDiscovery = useRef(isNetworkedOrigin() && !getToken() && !getAdminToken() && !ownerSession());
  const titleId = useId();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Search | null>(null);
  const [review, setReview] = useState<{ hit: Hit; turn: Turn } | null>(null);
  const [state, setState] = useState<'idle' | 'search' | 'review' | 'continue' | 'use'>('idle');
  const [error, setError] = useState('');
  const [allowCloud, setAllowCloud] = useState(false);
  const passage = useRef<HTMLTextAreaElement>(null);
  const [chosen, setChosen] = useState('');
  // The hub's strictly local agents (signals/agents-policy.ts, LOCAL_ONLY_AGENTS, hestia included)
  // never pass a passage to a cloud model, so they need no cloud consent.
  const localRecipient = isLocalOnlyAgent(recipient);

  useEffect(() => {
    const node = dialog.current!;
    node.showModal();
    node.querySelector<HTMLInputElement>('input')?.focus();
    const off = onOwnerSession(session => {
      if (initialOwnerDiscovery.current && session?.signed_in) { initialOwnerDiscovery.current = false; return; }
      initialOwnerDiscovery.current = false;
      ++generation.current; busy.current = false; setQuery(''); setResults(null); setReview(null); setChosen(''); setAllowCloud(false);
      setError(session?.signed_in ? '' : k.ownerOnly); setState('idle');
    });
    return () => { ++generation.current; off(); node.close(); opener?.focus(); };
  }, [opener]);

  const change = (value: string) => {
    ++generation.current; busy.current = false;
    setQuery(value); setResults(null); setReview(null); setChosen(''); setAllowCloud(false); setError(''); setState('idle');
  };
  const search = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!query.trim() || busy.current) return;
    const current = ++generation.current;
    busy.current = true; setState('search'); setError(''); setResults(null); setReview(null);
    try {
      const data: any = await apiPost('/sessions/search', { query: query.trim(), limit: 20 }, { admin: true });
      if (current !== generation.current) return;
      if (!data || !Array.isArray(data.hits) || data.hits.length > 20 || !data.hits.every(validHit)) throw Error('invalid_search');
      setResults({ hits: data.hits, truncated: data.truncated === true, stopped_by: typeof data.stopped_by === 'string' ? data.stopped_by : null });
    } catch (error: any) { if (current === generation.current) setError([401, 403].includes(error?.status) ? k.ownerOnly : k.failed); }
    finally { if (current === generation.current) { busy.current = false; setState('idle'); } }
  };
  const verify = async (hit: Hit, action: 'review' | 'continue' | 'use') => {
    if (busy.current) return;
    if (action === 'continue' && (hasAttachment || turnActive || (canContinue && !canContinue()))) { setError(k.activeTurn); return; }
    if (action === 'use' && (hasAttachment || turnActive || (canUse && !canUse()) || !chosen.trim() || excerptBytes(chosen) > 8000)) {
      setError(!chosen.trim() ? k.noSelection : excerptBytes(chosen) > 8000 ? k.tooLong : k.activeTurn); return;
    }
    const current = ++generation.current;
    const owner = historyOwnerKey();
    busy.current = true; setState(action); setError('');
    if (action === 'review') setReview(null);
    try {
      const data = await apiGet(`/sessions/${encodeURIComponent(hit.session_id)}/transcript?references=true`, { admin: true });
      if (current !== generation.current || owner !== historyOwnerKey()) return;
      const turn = sourceTurn(data, hit);
      if (!turn) { setReview(null); setResults(null); setError(k.changed); return; }
      if (action === 'review') { setReview({ hit, turn }); setChosen(''); setAllowCloud(false); return; }
      if (review?.hit !== hit || review.turn.content !== turn.content) {
        setReview(null); setResults(null); setError(k.changed); return;
      }
      if (action === 'use') {
        if (!onUse || (canUse && !canUse()) || !turn.reference_revision || !/^[0-9a-f]{64}$/.test(turn.reference_revision)
          || turn.reference_revision !== review.turn.reference_revision
          || !turn.content.includes(chosen) || (!localRecipient && !allowCloud)) {
          setError(!turn.reference_revision ? k.useUnavailable : k.changed); return;
        }
        if (onUse({ session_id: hit.session_id, turn: hit.turn, revision: turn.reference_revision,
          excerpt: chosen, allow_cloud: !localRecipient && allowCloud }, turn.role)) onClose();
        else setError(k.activeTurn);
        return;
      }
      if (turnActive || (canContinue && !canContinue())) { setError(k.activeTurn); return; }
      const resumed: any = await apiPost('/sessions/resume', { session_id: hit.session_id }, { admin: true });
      if (current !== generation.current) return;
      if (resumed?.session !== hit.session_id || !Array.isArray(resumed.turns)) throw Error('invalid_resume');
      window.dispatchEvent(new CustomEvent('nerva:session-selected', {
        detail: { sessionId: hit.session_id, turns: resumed.turns },
      }));
      onClose();
    } catch (error: any) { if (current === generation.current) setError([401, 403].includes(error?.status)
      ? k.ownerOnly : action === 'review' ? k.sourceFailed : k.resumeFailed); }
    finally { if (current === generation.current) { busy.current = false; setState('idle'); } }
  };

  return <dialog ref={dialog} className="chat-history-dialog" aria-labelledby={titleId}
    onCancel={event => { event.preventDefault(); onClose(); }}>
    <div className="chat-history-head"><h2 id={titleId}>{k.title}</h2><button type="button" onClick={onClose}>{k.close}</button></div>
    <p>{k.hint}</p>
    <form onSubmit={search}>
      <label htmlFor={`${titleId}-query`}>{k.query}</label>
      <div className="chat-history-form"><input id={`${titleId}-query`} type="search" maxLength={256} value={query}
        onChange={event => change(event.target.value)} />
        <button type="submit" disabled={!query.trim() || state !== 'idle'}>{state === 'search' ? k.searching : k.search}</button></div>
    </form>
    {error && <p role="alert">{error}</p>}
    {results && <div className="chat-history-results" role="region" aria-label={k.title}>
      {results.hits.length === 0 && <p role="status">{k.empty}</p>}
      {results.truncated && <p role="status">{k.limited}</p>}
      <ol>{results.hits.map(hit => <li key={`${hit.session_id}:${hit.turn}`}>
        <div className="chat-history-meta">{hit.role} · {hit.agent_id || hit.session_id} · {hit.timestamp || ''}</div>
        <div className="chat-history-text">{hit.snippet}</div>
        <button type="button" disabled={state !== 'idle'} onClick={() => void verify(hit, 'review')}>{k.review}</button>
      </li>)}</ol>
    </div>}
    {state === 'review' && <p role="status">{k.reviewing}</p>}
    {state === 'continue' && <p role="status">{k.continuing}</p>}
      {review && <section className="chat-history-source" aria-label={k.review}>
      <div className="chat-history-meta">{review.turn.role} · {review.turn.agent_id || review.hit.session_id} · {review.turn.timestamp}</div>
      {(!review.turn.reference_revision || !/^[0-9a-f]{64}$/.test(review.turn.reference_revision) || !onUse)
        && <div className="chat-history-text">{review.turn.content}</div>}
      {review.turn.reference_revision && /^[0-9a-f]{64}$/.test(review.turn.reference_revision) && onUse ? <div className="chat-history-use">
        <p>{k.disclosure} {localRecipient ? k.local : ''}</p>
        <label htmlFor={`${titleId}-passage`}>{k.selection}</label>
        <textarea id={`${titleId}-passage`} ref={passage} aria-readonly="true" value={review.turn.content} rows={6}
          onBeforeInput={event => event.preventDefault()} onChange={() => {}} onPaste={event => event.preventDefault()}
          onDrop={event => event.preventDefault()} />
        <div className="chat-history-form"><button type="button" disabled={state !== 'idle'} onClick={() => {
          const area = passage.current; const text = area ? review.turn.content.slice(area.selectionStart, area.selectionEnd) : '';
          setChosen(text); setError(text && excerptBytes(text) > 8000 ? k.tooLong : '');
        }}>{k.selection}</button>
          <button type="button" disabled={state !== 'idle' || excerptBytes(review.turn.content) > 8000}
            onClick={() => { setChosen(review.turn.content); setError(''); }}>{k.full}</button></div>
        {chosen && <div className="chat-history-selected"><strong>{k.staged}</strong><pre>{chosen}</pre></div>}
        {!localRecipient && <label className="chat-history-consent"><input type="checkbox" checked={allowCloud}
          onChange={event => setAllowCloud(event.target.checked)} /> {recipient || 'Agent'}: {k.cloud}</label>}
        <button type="button" disabled={state !== 'idle' || hasAttachment || turnActive || !chosen.trim()
          || excerptBytes(chosen) > 8000 || (!localRecipient && !allowCloud)} onClick={() => void verify(review.hit, 'use')}>{k.use}</button>
      </div> : <p>{k.useUnavailable}</p>}
      {hasDraft && <p>{k.draft}</p>}
      <p>{hasAttachment ? k.attachment : turnActive ? k.activeTurn : k.agent}</p>
      <button type="button" disabled={state !== 'idle' || hasAttachment || turnActive} onClick={() => void verify(review.hit, 'continue')}>{k.continue}</button>
    </section>}
  </dialog>;
}
