import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { apiFetchOnce, getAdminToken, getToken } from './api/client';
import { onOwnerSession, ownerSession } from './api/owner-session';
import { ObsidianChatNote, type NoteReceipt, type NoteSubmission, type Target } from './obsidian-chat-note';
import { obsidianOpenUri } from '../../apps/jarvis-os/public/js/obsidian-source.js';
import { fetchBoard, fetchBoards, fetchTask } from './panels/kanban/api';
import type { BoardMeta, KanbanTask, KanbanTaskDetail } from './panels/kanban/types';
import './composer-board-result.css';

export type BoardResultRef = { board: string; taskId: string };
export type BoardReference = { board: string; task_id: string; source: 'result' | 'latest_summary'; excerpt: string; sha256: string };
type Reviewed = { board: string; taskId: string; title: string; source: 'result' | 'latest_summary'; body: string; sha256: string; credentials: string };
type Staged = { reviewed: Reviewed; excerpt: string; changed: boolean };
const MAX_BYTES = 64_000;
const MAX_TOTAL_BYTES = 128_000;
const MAX_ITEMS = 8;
const bytes = (text: string) => new TextEncoder().encode(text).length;
const unauthorized = (error: unknown) => (error as { status?: number })?.status === 401 || (error as { status?: number })?.status === 403;
const credentials = () => JSON.stringify([getToken(), getAdminToken(), ownerSession()?.signed_in, ownerSession()?.csrf]);
const sourceOf = (detail: KanbanTaskDetail) => {
  const task = detail.task;
  if (typeof task.result === 'string' && task.result.trim()) return { source: 'result' as const, body: task.result };
  if (typeof task.latest_summary === 'string' && task.latest_summary.trim()) return { source: 'latest_summary' as const, body: task.latest_summary };
  return null;
};
const validDigest = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const doneTasks = (columns: { tasks: KanbanTask[] }[]) => columns.flatMap(column => column.tasks).filter(task => task.status === 'done');
function originalPassage(body: string, start: number, end: number): string {
  let normalized = 0;
  let from = -1;
  let to = -1;
  for (let i = 0; i <= body.length && normalized <= end;) {
    if (normalized === start) from = i;
    if (normalized === end) { to = i; break; }
    if (i === body.length) break;
    i += body[i] === '\r' && body[i + 1] === '\n' ? 2 : 1;
    normalized++;
  }
  return from >= 0 && to > from ? body.slice(from, to) : '';
}

const copy = {
  en: { heading: 'Attach completed task result', board: 'Board', task: 'Completed task', choose: 'Choose a task', loading: 'Loading completed tasks…', emptyBoards: 'No boards available.', emptyTasks: 'No completed tasks on this board.', noResult: 'This task has no recorded result or summary.', unavailable: 'Could not load the task. Retry.', missingRef: 'The requested board or completed task is unavailable. Choose another board or task.', retry: 'Retry', close: 'Close', sourceResult: 'Recorded task result', sourceSummary: 'Latest summary (fallback; no recorded result)', passage: 'Result text to review', select: 'Attach selected passage', all: 'Attach full result', limit: 'Attachment limit: 64,000 UTF-8 bytes per item; 128,000 total across up to 8 items. Select a shorter passage if needed.', selected: 'Exact text for the next chat message', remove: 'Remove', review: 'Review attached task result', destination: 'Destination: the next message in this chat, to', changed: 'The task changed or is no longer complete. Review its current result again.', failed: 'Could not recheck the task. Retry Transmit.', refused: 'The message was not accepted. Your reviewed passages are still attached.', noSelection: 'Select a passage in the result first.', groupLimit: 'The group is full or exceeds 128,000 UTF-8 bytes. Remove an item or choose a shorter passage.', staged: 'Staged task results', add: 'Add another task', reviewItem: 'Review this task again', changedItem: 'Changed or missing; review again or remove before sending.', auth: 'Board access expired. Sign in and review task results again.' },
  ro: { heading: 'Atașează rezultatul unei sarcini finalizate', board: 'Tablou', task: 'Sarcină finalizată', choose: 'Alege o sarcină', loading: 'Se încarcă sarcinile finalizate…', emptyBoards: 'Nu există tablouri disponibile.', emptyTasks: 'Nu există sarcini finalizate în acest tablou.', noResult: 'Sarcina nu are rezultat sau rezumat înregistrat.', unavailable: 'Sarcina nu a putut fi încărcată. Reîncearcă.', missingRef: 'Tabloul sau sarcina finalizată cerută nu este disponibilă. Alege alt tablou sau altă sarcină.', retry: 'Reîncearcă', close: 'Închide', sourceResult: 'Rezultat înregistrat al sarcinii', sourceSummary: 'Ultimul rezumat (alternativă; nu există rezultat înregistrat)', passage: 'Textul rezultatului de revizuit', select: 'Atașează pasajul selectat', all: 'Atașează rezultatul complet', limit: 'Limită: 64.000 de octeți UTF-8 per element, 128.000 în total și maximum 8 elemente. Selectează un pasaj mai scurt dacă este necesar.', selected: 'Textul exact pentru următorul mesaj de chat', remove: 'Elimină', review: 'Revizuiește rezultatul atașat', destination: 'Destinație: următorul mesaj din acest chat, către', changed: 'Sarcina s-a schimbat sau nu mai este finalizată. Revizuiește din nou rezultatul actual.', failed: 'Sarcina nu a putut fi verificată din nou. Reîncearcă trimiterea.', refused: 'Mesajul nu a fost acceptat. Pasajele revizuite rămân atașate.', noSelection: 'Selectează întâi un pasaj din rezultat.', groupLimit: 'Grupul este plin sau depășește 128.000 de octeți UTF-8. Elimină un element sau alege un pasaj mai scurt.', staged: 'Rezultate pregătite', add: 'Adaugă altă sarcină', reviewItem: 'Revizuiește din nou această sarcină', changedItem: 'Modificată sau lipsă; revizuiește din nou sau elimină înainte de trimitere.', auth: 'Accesul la tablou a expirat. Autentifică-te și revizuiește din nou rezultatele.' },
} as const;

const noteCopy = {
  en: { save: 'Save results to Obsidian', saved: 'Saved to Obsidian',
    failed: 'Could not preview the note. Your reviewed results are still attached.',
    invalid: 'The note preview was invalid. Nothing was saved.',
    stale: 'One or more sources changed. Review the staged results again before saving.' },
  ro: { save: 'Salvează rezultatele în Obsidian', saved: 'Salvat în Obsidian',
    failed: 'Nota nu a putut fi previzualizată. Rezultatele revizuite sunt încă atașate.',
    invalid: 'Previzualizarea notei este invalidă. Nu s-a salvat nimic.',
    stale: 'Una sau mai multe surse s-au schimbat. Revizuiește din nou rezultatele pregătite înainte de salvare.' },
} as const;

export function useBoardResult(agent: string, session: string, enabled: boolean, lang: string) {
  const labels = copy[lang === 'ro' ? 'ro' : 'en'];
  const [reviewing, setReviewing] = useState(false);
  const [boards, setBoards] = useState<BoardMeta[] | null>(null);
  const [board, setBoard] = useState('');
  const [tasks, setTasks] = useState<KanbanTask[]>([]);
  const [taskId, setTaskId] = useState('');
  const [reviewed, setReviewed] = useState<Reviewed | null>(null);
  const [staged, setStaged] = useState<Staged[]>([]);
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const [notePreview, setNotePreview] = useState<{ title: string; content: string } | null>(null);
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteSubmission, setNoteSubmission] = useState<NoteSubmission | null>(null);
  const [noteSaved, setNoteSaved] = useState<{ receipt: NoteReceipt; target: Target } | null>(null);
  const [noteStale, setNoteStale] = useState(false);
  const noteTrigger = useRef<HTMLButtonElement>(null);
  const passage = useRef<HTMLTextAreaElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const serial = useRef(0);
  const inFlight = useRef(false);
  const renderSerial = serial.current;
  const noteScope = useRef('');
  noteScope.current = JSON.stringify([agent, session, credentials()]);

  function clearNote() {
    setNotePreview(null); setNoteOpen(false); setNoteSubmission(null); setNoteSaved(null);
    setNoteStale(false);
  }

  function clear() {
    serial.current++;
    inFlight.current = false;
    setReviewing(false); setBoards(null); setBoard(''); setTasks([]); setTaskId('');
    setReviewed(null); setStaged([]); setStatus(''); setBusy(false);
    clearNote();
  }
  useLayoutEffect(() => { clear(); return () => { serial.current++; }; }, [agent, session, enabled]);
  const currentCredentials = useRef(credentials());
  useEffect(() => onOwnerSession(() => {
    const next = credentials();
    if (next !== currentCredentials.current) { currentCredentials.current = next; clear(); }
  }), []);

  async function loadTask(slug: string, id: string) {
    const request = ++serial.current;
    const identity = credentials();
    setTaskId(id); setReviewed(null); setStatus('');
    if (!id) return;
    setBusy(true);
    try {
      const detail = await fetchTask(slug, id);
      if (request !== serial.current) return;
      if (identity !== credentials()) { clear(); return; }
      if (detail.task.id !== id || detail.task.status !== 'done') { setStatus(labels.changed); return; }
      const source = sourceOf(detail);
      if (!source) { setStatus(labels.noResult); return; }
      if (!validDigest(detail.task.board_source_sha256)) {
        setStatus(`${labels.unavailable} ${lang === 'ro' ? 'Serverul nu oferă amprenta sursei. Nu putem verifica acest rezultat.' :
          'The server did not provide a source digest, so this result cannot be verified.'}`);
        return;
      }
      setReviewed({ board: slug, taskId: id, title: detail.task.title, ...source, sha256: detail.task.board_source_sha256, credentials: identity });
    } catch (error) {
      if (request === serial.current) {
        if (identity !== credentials() || unauthorized(error)) { clear(); setStatus(labels.auth); }
        else setStatus(labels.unavailable);
      }
    } finally {
      if (request === serial.current) setBusy(false);
    }
  }

  async function loadBoard(slug: string, preferred = '') {
    const request = ++serial.current;
    const identity = credentials();
    setBoard(slug); setTasks([]); setTaskId(''); setReviewed(null); setStatus('');
    if (!slug) return;
    setBusy(true);
    try {
      const response = await fetchBoard(slug);
      if (request !== serial.current) return;
      if (identity !== credentials()) { clear(); return; }
      const done = doneTasks(response.columns);
      setTasks(done.map(({ id, title, status }) => ({ id, title, status })));
      if (preferred && done.some(task => task.id === preferred)) await loadTask(slug, preferred);
      else if (preferred) setStatus(labels.missingRef);
    } catch (error) {
      if (request === serial.current) {
        if (identity !== credentials() || unauthorized(error)) { clear(); setStatus(labels.auth); }
        else setStatus(labels.unavailable);
      }
    } finally {
      if (request === serial.current) setBusy(false);
    }
  }

  async function open(ref?: BoardResultRef) {
    if (!enabled || inFlight.current) return;
    const request = ++serial.current;
    const identity = credentials();
    setReviewing(true); setBusy(true); setStatus(''); setReviewed(null);
    setBoards(null); setBoard(''); setTasks([]); setTaskId('');
    try {
      const result = await fetchBoards();
      if (request !== serial.current) return;
      if (identity !== credentials()) { clear(); return; }
      const available = result.boards.filter(item => !!item.slug?.trim());
      setBoards(available);
      if (ref && !available.some(item => item.slug === ref.board)) { setStatus(labels.missingRef); return; }
      const slug = ref?.board || (available.some(item => item.slug === result.current) ? result.current : available[0]?.slug || '');
      if (slug) await loadBoard(slug, slug === ref?.board ? ref.taskId : '');
    } catch (error) {
      if (request === serial.current) {
        if (identity !== credentials() || unauthorized(error)) { clear(); setStatus(labels.auth); }
        else setStatus(labels.unavailable);
      }
    } finally {
      if (request === serial.current) setBusy(false);
    }
  }

  function choose(text: string) {
    if (reviewed && reviewed.credentials !== credentials()) { clear(); return; }
    if (!text.trim()) { setStatus(labels.noSelection); return; }
    if (!reviewed || bytes(text) > MAX_BYTES ||
        !reviewed.body.includes(text)) {
      setStatus(labels.limit); return;
    }
    const index = staged.findIndex(item => item.reviewed.board === reviewed.board && item.reviewed.taskId === reviewed.taskId);
    if ((index < 0 && staged.length >= MAX_ITEMS) ||
        staged.reduce((total, item, i) => total + (i === index ? 0 : bytes(item.excerpt)), bytes(text)) > MAX_TOTAL_BYTES) {
      setStatus(labels.groupLimit); return;
    }
    const next = { reviewed, excerpt: text, changed: false };
    serial.current++;
    clearNote();
    setStaged(index < 0 ? [...staged, next] : staged.map((item, i) => i === index ? next : item));
    setStatus('');
    setReviewing(false);
    trigger.current?.focus();
  }

  async function send(fn: (references: BoardReference[]) => boolean | Promise<boolean>): Promise<boolean> {
    if (staged.some(item => item.reviewed.credentials !== credentials())) { clear(); return false; }
    if (!enabled || !staged.length || inFlight.current || renderSerial !== serial.current || staged.some(item => item.changed ||
        !validDigest(item.reviewed.sha256) || !item.reviewed.body.includes(item.excerpt) || bytes(item.excerpt) > MAX_BYTES) ||
        staged.reduce((total, item) => total + bytes(item.excerpt), 0) > MAX_TOTAL_BYTES) return false;
    const request = ++serial.current;
    const identity = credentials();
    inFlight.current = true;
    setBusy(true); setStatus('');
    try {
      const details = await Promise.allSettled(staged.map(item => fetchTask(item.reviewed.board, item.reviewed.taskId)));
      if (request !== serial.current) return false;
      if (identity !== credentials()) { clear(); return false; }
      if (details.some(read => read.status === 'rejected' && unauthorized(read.reason))) { clear(); setStatus(labels.auth); return false; }
      const changed = staged.filter((item, index) => {
        const read = details[index];
        if (read.status === 'rejected') return (read.reason as { status?: number })?.status === 404;
        const detail = read.value;
        const current = sourceOf(detail);
        return detail.task.id !== item.reviewed.taskId || detail.task.status !== 'done' ||
          detail.task.title !== item.reviewed.title || current?.source !== item.reviewed.source || current?.body !== item.reviewed.body ||
          detail.task.board_source_sha256 !== item.reviewed.sha256;
      });
      if (changed.length) {
        setStaged(items => items.map(item => changed.includes(item) ? { ...item, changed: true } : item));
        setStatus(`${labels.changed} ${changed.map(item => `${item.reviewed.board}/${item.reviewed.taskId}`).join(', ')}`);
        return false;
      }
      if (details.some(read => read.status === 'rejected')) { setStatus(labels.failed); return false; }
      let accepted = false;
      try { accepted = await fn(staged.map(item => ({ board: item.reviewed.board, task_id: item.reviewed.taskId,
        source: item.reviewed.source, excerpt: item.excerpt, sha256: item.reviewed.sha256 }))); }
      catch { if (request === serial.current && identity === credentials()) setStatus(labels.refused); return false; }
      if (request !== serial.current) return false;
      if (identity !== credentials()) { clear(); return false; }
      if (!accepted) { setStatus(labels.refused); return false; }
      clear();
      return true;
    } catch {
      if (request === serial.current && identity === credentials()) setStatus(labels.failed);
      return false;
    } finally {
      if (request === serial.current) { inFlight.current = false; setBusy(false); }
    }
  }

  async function previewNote() {
    if (!enabled || !staged.length || inFlight.current || noteStale || staged.some(item => item.changed)) return;
    if (noteSubmission && notePreview) { setNoteOpen(true); return; }
    const request = ++serial.current;
    const identity = credentials();
    const scope = noteScope.current;
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 15_000);
    inFlight.current = true; setBusy(true); setStatus('');
    try {
      const references = staged.map(item => ({ board: item.reviewed.board, task_id: item.reviewed.taskId,
        source: item.reviewed.source, excerpt: item.excerpt, sha256: item.reviewed.sha256 }));
      const response = await apiFetchOnce('/api/kanban/board-note/preview', {
        method: 'POST', body: { references }, admin: false, signal: controller.signal,
      });
      if (controller.signal.aborted) throw new Error('preview timed out');
      if (identity !== credentials()) { clear(); setStatus(labels.auth); return; }
      if (request !== serial.current || scope !== noteScope.current) return;
      if (response.status === 401 || response.status === 403) { clear(); setStatus(labels.auth); return; }
      if (response.status === 409) {
        setNoteStale(true);
        setStatus(noteCopy[lang === 'ro' ? 'ro' : 'en'].stale);
        return;
      }
      if (!response.ok) throw new Error('preview failed');
      const body: unknown = await response.json();
      if (controller.signal.aborted) throw new Error('preview timed out');
      if (identity !== credentials()) { clear(); setStatus(labels.auth); return; }
      if (request !== serial.current || scope !== noteScope.current) return;
      if (!body || typeof body !== 'object' ||
          typeof (body as { title?: unknown }).title !== 'string' ||
          typeof (body as { content?: unknown }).content !== 'string') {
        setStatus(noteCopy[lang === 'ro' ? 'ro' : 'en'].invalid); return;
      }
      const { title, content } = body as { title: string; content: string };
      if (!title.trim() || !content.trim() || Array.from(title).length > 120 || Array.from(content).length > 100_000) {
        setStatus(noteCopy[lang === 'ro' ? 'ro' : 'en'].invalid); return;
      }
      setNotePreview({ title, content }); setNoteOpen(true);
    } catch {
      if (identity !== credentials()) { clear(); setStatus(labels.auth); }
      else if (request === serial.current && scope === noteScope.current)
        setStatus(noteCopy[lang === 'ro' ? 'ro' : 'en'].failed);
    } finally {
      window.clearTimeout(timer);
      if (request === serial.current) { inFlight.current = false; setBusy(false); }
    }
  }

  return { active: staged.length > 0, count: staged.length, staged, reviewing, busy, boards, board, tasks, taskId, reviewed, status, agent, lang,
    passage, trigger, labels, noteLabels: noteCopy[lang === 'ro' ? 'ro' : 'en'], notePreview, noteOpen, noteSubmission,
    noteSaved, noteStale, noteTrigger, noteScope, noteIsCurrent: () => noteScope.current === JSON.stringify([agent, session, credentials()]),
    previewNote, setNoteSubmission, setNoteSaved, setNoteOpen, open, clear, send, loadBoard, loadTask, choose,
    useSelection: () => { const area = passage.current; choose(area && reviewed ? originalPassage(reviewed.body, area.selectionStart, area.selectionEnd) : ''); },
    useAll: () => choose(reviewed?.body || ''),
    reopen: () => setReviewing(true),
    cancel: () => { if (inFlight.current) return; serial.current++; setReviewing(false); setBusy(false); setReviewed(null); setStatus(''); trigger.current?.focus(); },
    remove: (item: Staged) => { if (inFlight.current) return; serial.current++; clearNote(); setStaged(items => items.filter(entry => entry !== item)); setStatus(''); },
    retry: () => { if (board && taskId) void loadTask(board, taskId); else void open(); },
  };
}

export function BoardResultReview({ draft }: { draft: ReturnType<typeof useBoardResult> }) {
  const closeButton = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (!draft.reviewing) return;
    dialog.current?.showModal();
    closeButton.current?.focus();
    return () => dialog.current?.close();
  }, [draft.reviewing]);
  const list = draft.staged.length > 0 && <div className="board-result-selected" role="region" aria-label={draft.labels.staged} tabIndex={0}>
    <strong>{draft.labels.staged} ({draft.count})</strong>
    <ol>{draft.staged.map(item => <li key={`${item.reviewed.board}/${item.reviewed.taskId}`}>
      <strong>{item.reviewed.title}</strong> · {item.reviewed.board}/{item.reviewed.taskId} · {item.reviewed.source === 'result' ? draft.labels.sourceResult : draft.labels.sourceSummary}
      {item.changed && <p role="alert">{draft.labels.changedItem}</p>}
      <details><summary>{draft.labels.selected}</summary><pre>{item.excerpt}</pre></details>
      <button type="button" className="tool-btn" aria-label={`${draft.labels.reviewItem}: ${item.reviewed.board}/${item.reviewed.taskId}`}
        disabled={draft.busy} onClick={() => void draft.open({ board: item.reviewed.board, taskId: item.reviewed.taskId })}>
        {draft.labels.reviewItem.split(' ')[0]}</button>
      <button type="button" className="tool-btn" aria-label={`${draft.labels.remove}: ${item.reviewed.board}/${item.reviewed.taskId}`}
        disabled={draft.busy} onClick={() => draft.remove(item)}>{draft.labels.remove}</button>
    </li>)}</ol>
  </div>;
  if (!draft.reviewing) return draft.active ? <div className="board-result-attached">
    <p>{draft.labels.destination} {draft.agent}.</p>
    {draft.status && <p role="alert">{draft.status}</p>}
    {list}
    <button type="button" className="tool-btn" disabled={draft.busy} onClick={() => void draft.open()}>{draft.labels.add}</button>
    <button ref={draft.noteTrigger} type="button" className="tool-btn"
      disabled={draft.busy || !!draft.noteSaved || draft.noteStale || draft.staged.some(item => item.changed)} onClick={() => void draft.previewNote()}>
      {draft.noteSaved ? draft.noteLabels.saved : draft.noteLabels.save}</button>
    {draft.noteSaved && <p role="status">{draft.noteLabels.saved}: {draft.noteSaved.receipt.relPath}
      {draft.noteSaved.receipt.source && <> · <a href={obsidianOpenUri(draft.noteSaved.receipt.source) || undefined}>
        {draft.noteLabels.saved}</a></>}</p>}
    {draft.noteOpen && draft.notePreview && draft.noteTrigger.current && <ObsidianChatNote
      text={draft.notePreview.content} initialTitle={draft.notePreview.title} lang={draft.lang} opener={draft.noteTrigger.current}
      isCurrent={draft.noteIsCurrent} initialSubmission={draft.noteSubmission}
      onClose={() => draft.setNoteOpen(false)} onSubmitted={draft.setNoteSubmission}
      onSaved={(receipt, target) => draft.setNoteSaved({ receipt, target })}
      onTarget={target => draft.setNoteSaved(previous => previous && target &&
        previous.target.id === target.id && previous.target.vault === target.vault && previous.target.inbox === target.inbox
        ? previous : null)} />}
  </div> : draft.status ? <p role="alert">{draft.status}</p> : null;
  return createPortal(<dialog ref={dialog} aria-modal="true" aria-label={draft.labels.heading} className="board-result-review"
    onCancel={event => { event.preventDefault(); draft.cancel(); }}
    onKeyDown={event => event.stopPropagation()}>
    <header><strong>{draft.labels.heading}</strong><button ref={closeButton} type="button" className="tool-btn" aria-label={draft.labels.close} onClick={draft.cancel}>×</button></header>
    <p>{draft.labels.destination} {draft.agent}.</p>
    {draft.status && <p role="alert">{draft.status}</p>}
    {list}
    {draft.boards === null && !draft.status && <p role="status">{draft.labels.loading}</p>}
    {draft.boards?.length === 0 && <p>{draft.labels.emptyBoards}</p>}
    {!!draft.boards?.length && <><label>{draft.labels.board}<select value={draft.board} disabled={draft.busy} onChange={event => void draft.loadBoard(event.target.value)}>
      {!draft.board && <option value="" disabled>—</option>}
      {draft.boards.map(item => <option key={item.slug} value={item.slug}>{item.name || item.slug}</option>)}</select></label>
      <label>{draft.labels.task}<select value={draft.taskId} disabled={draft.busy} onChange={event => void draft.loadTask(draft.board, event.target.value)}>
        <option value="">{draft.labels.choose}</option>
        {draft.tasks.map(item => <option key={item.id} value={item.id}>{item.title} ({item.id})</option>)}</select></label>
      {!draft.busy && !draft.tasks.length && <p>{draft.labels.emptyTasks}</p>}</>}
    {draft.reviewed && <><p><strong>{draft.reviewed.source === 'result' ? draft.labels.sourceResult : draft.labels.sourceSummary}</strong> · {draft.reviewed.title} ({draft.reviewed.taskId})</p>
      <label>{draft.labels.passage}<textarea ref={draft.passage} readOnly rows={9} value={draft.reviewed.body}/></label>
      <p>{draft.labels.limit}</p>
      <div className="board-result-actions"><button type="button" className="tool-btn" disabled={draft.busy} onClick={draft.useSelection}>{draft.labels.select}</button>
        <button type="button" className="tool-btn" disabled={draft.busy || bytes(draft.reviewed.body) > MAX_BYTES} onClick={draft.useAll}>{draft.labels.all}</button></div>
    </>}
    {(draft.status.startsWith(draft.labels.unavailable) || draft.status === draft.labels.changed) &&
      <button type="button" className="tool-btn" onClick={draft.retry}>{draft.labels.retry}</button>}
  </dialog>, document.body);
}
