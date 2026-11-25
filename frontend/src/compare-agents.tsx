import React, { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { apiFetchOnce, getAdminToken, getToken } from './api/client';
import { isNetworkedOrigin, loadOwnerSession, onOwnerSession, ownerSession, requireSignIn } from './api/owner-session';
import { ObsidianChatNote, type NoteReceipt, type NoteSubmission, type Target } from './obsidian-chat-note';
import { obsidianOpenUri } from '../../apps/jarvis-os/public/js/obsidian-source.js';
import './chat-task-dialog.css';
import './compare-agents.css';

type Agent = { id: string; name?: string; role?: string };
type Opinion = { agent: string; ok: boolean; text?: string; model?: string; route?: string; reason?: string };
type Result = { run: number; credential: string; question: string; ids: [string, string]; names: [string, string];
  roles: [string, string]; opinions: Opinion[] };
const credentials = () => JSON.stringify([getToken(), getAdminToken(), ownerSession()?.signed_in || false,
  ownerSession()?.signed_in ? ownerSession()?.csrf || '' : '']);
function noteTitle(agent: string, question: string): string {
  const clean = `${agent} — ${question.trim().split(/\r?\n/, 1)[0]}`
    .replace(/[<>:"/\\|?*\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim();
  return Array.from(clean).slice(0, 120).join('').replace(/[. ]+$/, '') || 'Agent answer';
}

const copy = {
  en: {
    title: 'Compare two agents', question: 'Question', first: 'First agent', second: 'Second agent',
    limit: 'Up to 4,096 characters. Only this text is sent; chat history and attachments are excluded. Supported local models receive a direct-answer request.',
    cloud: 'Allow approved cloud models for this question', cloudHint: 'This can send the question to an approved remote provider.',
    compare: 'Compare answers', comparing: 'Comparing…', close: 'Close', noAgent: 'Choose two different available agents.',
    waiting: 'Waiting for both agents. A local model can take up to two minutes to answer.',
    noQuestion: 'Enter a question to compare.', tooLong: 'Shorten the question to 4,096 characters.',
    failed: 'The comparison could not be confirmed. Review the question and try again.',
    running: 'A comparison is already running. Wait for it to finish, then submit again.',
    auth: 'Owner access changed. Sign in and submit again when ready.',
    established: 'Owner access is ready. Review the question and submit again.',
    missing: 'No answer returned.', answer: 'Answer', unavailable: 'Unavailable',
    cloudDisabled: 'Cloud use is off for this question.', modelUnavailable: 'No eligible model is available.',
    agentUnavailable: 'This agent is unavailable.',
    timedOut: 'This agent ran out of time.', generationFailed: 'This agent could not return an answer.',
    routeUnavailable: 'No eligible route is available.',
    reported: 'Reported model and route', noReported: 'Model and route were not reported.',
    saveNote: 'Save to Obsidian', savedNote: 'Saved to Obsidian', openNote: 'Open in Obsidian',
    noteQuestion: 'Question', noteAgent: 'Answer by', noteModel: 'Reported model', noteRoute: 'Reported route', noteAnswer: 'Answer',
  },
  ro: {
    title: 'Compară doi agenți', question: 'Întrebare', first: 'Primul agent', second: 'Al doilea agent',
    limit: 'Cel mult 4.096 de caractere. Se trimite doar acest text; istoricul și atașamentele sunt excluse. Modelelor locale compatibile li se cere un răspuns direct.',
    cloud: 'Permite modele cloud aprobate pentru această întrebare', cloudHint: 'Întrebarea poate fi trimisă unui furnizor la distanță aprobat.',
    compare: 'Compară răspunsurile', comparing: 'Se compară…', close: 'Închide', noAgent: 'Alege doi agenți disponibili diferiți.',
    waiting: 'Aștept răspunsurile ambilor agenți. Un model local poate avea nevoie de până la două minute.',
    noQuestion: 'Scrie o întrebare pentru comparație.', tooLong: 'Scurtează întrebarea la 4.096 de caractere.',
    failed: 'Comparația nu a putut fi confirmată. Verifică întrebarea și încearcă din nou.',
    running: 'O comparație este deja în curs. Așteaptă să se termine, apoi trimite din nou.',
    auth: 'Accesul proprietarului s-a schimbat. Autentifică-te și trimite din nou când ești pregătit.',
    established: 'Accesul proprietarului este pregătit. Verifică întrebarea și trimite din nou.',
    missing: 'Nu a fost returnat un răspuns.', answer: 'Răspuns', unavailable: 'Indisponibil',
    cloudDisabled: 'Utilizarea cloud este dezactivată pentru această întrebare.', modelUnavailable: 'Nu există un model eligibil disponibil.',
    agentUnavailable: 'Acest agent este indisponibil.',
    timedOut: 'Acest agent a depășit timpul disponibil.', generationFailed: 'Acest agent nu a putut returna un răspuns.',
    routeUnavailable: 'Nu există o rută eligibilă disponibilă.',
    reported: 'Modelul și ruta raportate', noReported: 'Modelul și ruta nu au fost raportate.',
    saveNote: 'Salvează în Obsidian', savedNote: 'Salvat în Obsidian', openNote: 'Deschide în Obsidian',
    noteQuestion: 'Întrebare', noteAgent: 'Răspuns de la', noteModel: 'Model raportat', noteRoute: 'Rută raportată', noteAnswer: 'Răspuns',
  },
};

type Labels = typeof copy.en;
function OpinionCard({ result, id, index, k, lang, isCurrent }: {
  result: Result; id: string; index: number; k: Labels; lang: string; isCurrent: () => boolean;
}) {
  const item = result.opinions.find(opinion => opinion.agent === id);
  const name = result.names[index];
  const role = result.roles[index];
  const saveButton = useRef<HTMLButtonElement>(null);
  const [review, setReview] = useState(false);
  const wasReview = useRef(false);
  const [pendingNote, setPendingNote] = useState<NoteSubmission | null>(null);
  const [savedNote, setSavedNote] = useState<{ receipt: NoteReceipt; target: Target } | null>(null);
  const uri = savedNote?.receipt.source ? obsidianOpenUri(savedNote.receipt.source) : null;
  const usable = !!item?.ok && !!item.text?.trim();
  const content = usable ? [
    `${k.noteQuestion}\n${result.question}`,
    `${k.noteAgent}\n${name} (${id})`,
    ...(item.model ? [`${k.noteModel}\n${item.model}`] : []),
    ...(item.route ? [`${k.noteRoute}\n${item.route}`] : []),
    `${k.noteAnswer}\n${item.text}`,
  ].join('\n\n') : '';
  const reasons: Record<string, string> = {
    cloud_disabled: k.cloudDisabled, model_unavailable: k.modelUnavailable, agent_unavailable: k.agentUnavailable,
    timed_out: k.timedOut, generation_failed: k.generationFailed, route_unavailable: k.routeUnavailable,
  };
  const sameTarget = (a: Target, b: Target | null) => !!b && a.id === b.id && a.vault === b.vault && a.inbox === b.inbox;

  useLayoutEffect(() => {
    if (wasReview.current && !review) saveButton.current?.focus();
    wasReview.current = review;
  }, [review]);

  return <article>
    <h3>{name} <span>({item?.agent || id})</span></h3>
    {role && <p className="compare-agents-route">{role}</p>}
    <p className="compare-agents-route">{k.reported}: {item && (item.model || item.route)
      ? [item.model, item.route].filter(Boolean).join(' · ') : k.noReported}</p>
    <strong>{item?.ok ? k.answer : k.unavailable}</strong>
    <div className="compare-agents-answer">{item?.ok ? item.text || k.missing
      : item?.reason ? reasons[item.reason] || item.reason : k.missing}</div>
    {usable && <button ref={saveButton} type="button" className="compare-agents-save"
      aria-disabled={!!savedNote} onClick={() => { if (!savedNote && isCurrent()) setReview(true); }}>
      {savedNote ? k.savedNote : k.saveNote}</button>}
    {savedNote && !review && <p role="status" className="compare-agents-note-receipt">{k.savedNote}: {savedNote.receipt.relPath}
      {uri && <> · <a href={uri}>{k.openNote}</a></>}</p>}
    {review && usable && saveButton.current && isCurrent() && <ObsidianChatNote text={content}
      initialTitle={noteTitle(name, result.question)} lang={lang} opener={saveButton.current}
      onClose={() => setReview(false)} isCurrent={isCurrent} initialSubmission={pendingNote}
      onTarget={target => {
        setSavedNote(previous => previous && sameTarget(previous.target, target) ? previous : null);
        if (target) setPendingNote(previous => previous && sameTarget(previous.target, target) ? previous : null);
      }}
      onSubmitted={submission => { if (isCurrent()) setPendingNote(submission); }}
      onSaved={(receipt, target) => { if (isCurrent()) setSavedNote({ receipt, target }); }} />}
  </article>;
}

export function CompareAgentsDialog({ question, agent, agents, lang, opener, onClose }: {
  question: string; agent: string; agents: readonly Agent[]; lang: string;
  opener: HTMLElement | null; onClose: () => void;
}) {
  const k = lang === 'ro' ? copy.ro : copy.en;
  const dialog = useRef<HTMLDialogElement>(null);
  const mounted = useRef(true);
  const pending = useRef<AbortController | null>(null);
  const activeResult = useRef<Result | null>(null);
  const run = useRef(0);
  const submitting = useRef(false);
  const authVersion = useRef(0);
  const principal = useRef(credentials());
  const initialUnknown = useRef(isNetworkedOrigin() && !getToken() && !getAdminToken() && !ownerSession());
  const titleId = useId();
  const limitId = useId();
  const initialFirst = agents.some(item => item.id === agent) ? agent : agents[0]?.id || '';
  const [draft, setDraft] = useState(question);
  const [first, setFirst] = useState(initialFirst);
  const [second, setSecond] = useState(agents.find(item => item.id !== initialFirst)?.id || '');
  const [allowCloud, setAllowCloud] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [results, setResults] = useState<Result | null>(null);
  const tooLong = Array.from(draft).length > 4096;
  const valid = !!draft.trim() && !tooLong && first !== second
    && agents.some(item => item.id === first) && agents.some(item => item.id === second);

  useEffect(() => {
    const node = dialog.current!;
    mounted.current = true;
    node.showModal();
    node.querySelector<HTMLTextAreaElement>('textarea')?.focus();
    const checkPrincipal = () => {
      const current = credentials();
      if (current === principal.current) return;
      principal.current = current;
      ++authVersion.current;
      pending.current?.abort();
      const establishing = initialUnknown.current && !!ownerSession()?.signed_in;
      initialUnknown.current = false;
      activeResult.current = null;
      setResults(null);
      if (establishing) setError(k.established);
      else { setDraft(''); setAllowCloud(false); setError(k.auth); }
    };
    const unsubscribe = onOwnerSession(checkPrincipal);
    const onStorage = (event: StorageEvent) => {
      if (event.key === null || event.key === 'hud.user_token' || event.key === 'hud.admin_token') checkPrincipal();
    };
    window.addEventListener('storage', onStorage);
    window.addEventListener('focus', checkPrincipal);
    const timer = window.setInterval(checkPrincipal, 250); // localStorage changes in this tab emit no storage event
    return () => {
      mounted.current = false;
      activeResult.current = null;
      pending.current?.abort();
      unsubscribe();
      window.removeEventListener('storage', onStorage);
      window.removeEventListener('focus', checkPrincipal);
      window.clearInterval(timer);
      node.close();
      if (opener?.isConnected) opener.focus();
    };
  }, [opener, k.auth, k.established]);

  function changed() {
    setAllowCloud(false);
    activeResult.current = null;
    setResults(null);
    setError('');
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (submitting.current) return;
    if (!valid) {
      setError(!draft.trim() ? k.noQuestion : tooLong ? k.tooLong : k.noAgent);
      return;
    }
    setError('');
    activeResult.current = null;
    setResults(null);
    submitting.current = true;
    setBusy(true);
    let requestVersion = authVersion.current;
    try {
      if (credentials() !== principal.current) {
        setDraft(''); setAllowCloud(false); setError(k.auth);
        return;
      }
      if (isNetworkedOrigin() && !ownerSession() && !getToken() && !getAdminToken()) {
        await loadOwnerSession();
      }
      if (!mounted.current || credentials() !== principal.current || requestVersion !== authVersion.current) return;
      if (isNetworkedOrigin() && !ownerSession()?.signed_in && !getToken() && !getAdminToken()) {
        requireSignIn();
        if (mounted.current) setError(k.auth);
        return;
      }
      const version = authVersion.current;
      requestVersion = version;
      const requestPrincipal = credentials();
      const controller = new AbortController();
      pending.current = controller;
      const ids: [string, string] = [first, second];
      const names: [string, string] = ids.map(id => agents.find(item => item.id === id)?.name || id) as [string, string];
      const roles: [string, string] = ids.map(id => agents.find(item => item.id === id)?.role || '') as [string, string];
      const submittedQuestion = draft.trim();
      const response = await apiFetchOnce('/api/agents/opinions', { method: 'POST', admin: true,
        body: { question: submittedQuestion, agents: ids, allow_cloud: allowCloud }, signal: controller.signal });
      const body: unknown = await response.json().catch(() => null);
      if (!mounted.current || controller.signal.aborted || version !== authVersion.current
        || requestPrincipal !== credentials()) return;
      if (!response.ok || !body || typeof body !== 'object' || !('opinions' in body)
        || !Array.isArray(body.opinions)) {
        if (response.status === 401 || response.status === 403) {
          if (isNetworkedOrigin()) requireSignIn();
          setError(k.auth);
        } else setError(response.status === 429 ? k.running : k.failed);
        return;
      }
      const opinions = body.opinions.filter((item: unknown): item is Opinion =>
        !!item && typeof item === 'object' && 'agent' in item && typeof item.agent === 'string'
        && 'ok' in item && typeof item.ok === 'boolean').map((item: Opinion) => ({
        agent: item.agent, ok: item.ok,
        ...(typeof item.text === 'string' ? { text: item.text } : {}),
        ...(typeof item.model === 'string' ? { model: item.model } : {}),
        ...(typeof item.route === 'string' ? { route: item.route } : {}),
        ...(typeof item.reason === 'string' ? { reason: item.reason } : {}),
      }));
      const result = { run: ++run.current, credential: requestPrincipal, question: submittedQuestion, ids, names, roles, opinions };
      activeResult.current = result;
      setResults(result);
    } catch {
      if (mounted.current) setError(requestVersion !== authVersion.current ? k.auth : k.failed);
    } finally {
      pending.current = null;
      submitting.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  return <dialog ref={dialog} className="chat-task-dialog compare-agents" aria-modal="true" aria-labelledby={titleId}
    onCancel={event => { event.preventDefault(); onClose(); }}
    onKeyDown={event => { event.stopPropagation(); if (event.key === 'Escape') { event.preventDefault(); onClose(); } }}>
    <h2 id={titleId}>{k.title}</h2>
    <form onSubmit={event => void submit(event)}>
      <label htmlFor={`${limitId}-question`}>{k.question}
        <textarea id={`${limitId}-question`} value={draft} rows={5} disabled={busy}
          aria-describedby={limitId} onChange={event => { setDraft(event.target.value); changed(); }} />
      </label>
      <p id={limitId} className="compare-agents-hint">{k.limit}</p>
      {tooLong && <p role="alert">{k.tooLong}</p>}
      <div className="compare-agents-selectors">
        <label>{k.first}
          <select value={first} disabled={busy} onChange={event => { setFirst(event.target.value); changed(); }}>
            {!agents.some(item => item.id === first) && <option value={first} disabled>{first}</option>}
            {agents.map(item => <option key={item.id} value={item.id} disabled={item.id === second}>{item.name || item.id}{item.role ? ` — ${item.role}` : ''}</option>)}
          </select>
        </label>
        <label>{k.second}
          <select value={second} disabled={busy} onChange={event => { setSecond(event.target.value); changed(); }}>
            {!second && <option value="" disabled>—</option>}
            {agents.map(item => <option key={item.id} value={item.id} disabled={item.id === first}>{item.name || item.id}{item.role ? ` — ${item.role}` : ''}</option>)}
          </select>
        </label>
      </div>
      <label className="compare-agents-cloud"><input type="checkbox" checked={allowCloud} disabled={busy}
        onChange={event => { setAllowCloud(event.target.checked); activeResult.current = null; setResults(null); setError(''); }} />
        <span>{k.cloud}<small>{k.cloudHint}</small></span>
      </label>
      {error && <p role="alert">{error}</p>}
      {busy && <p role="status">{k.waiting}</p>}
      <footer>
        <button type="button" onClick={onClose}>{k.close}</button>
        <button type="submit" disabled={!valid || busy}>{busy ? k.comparing : k.compare}</button>
      </footer>
    </form>
    {results && <section key={results.run} className="compare-agents-results" aria-live="polite">
      {results.ids.map((id, index) => <OpinionCard key={id} result={results} id={id} index={index} k={k} lang={lang}
        isCurrent={() => mounted.current && activeResult.current === results && credentials() === results.credential} />)}
    </section>}
  </dialog>;
}
