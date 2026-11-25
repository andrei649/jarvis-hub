import React, { useEffect, useId, useRef, useState } from 'react';
import { createTask, fetchBoards } from './panels/kanban/api';
import type { BoardMeta, KanbanTask } from './panels/kanban/types';
import './chat-task-dialog.css';

const copy = {
  en: { heading: 'Create triage task', board: 'Board', title: 'Title', description: 'Description',
    create: 'Create task', creating: 'Creating…', cancel: 'Cancel', close: 'Close', loading: 'Loading boards…',
    noBoards: 'No boards available.', loadFailed: 'Could not load boards.', saveFailed: 'Could not confirm task creation.',
    retry: 'Retry', created: 'Created in', retryHint: 'Retry checks the same task request.' },
  ro: { heading: 'Creează sarcină de triere', board: 'Tablou', title: 'Titlu', description: 'Descriere',
    create: 'Creează sarcina', creating: 'Se creează…', cancel: 'Anulează', close: 'Închide', loading: 'Se încarcă tablourile…',
    noBoards: 'Nu există tablouri disponibile.', loadFailed: 'Nu s-au putut încărca tablourile.', saveFailed: 'Crearea sarcinii nu a putut fi confirmată.',
    retry: 'Reîncearcă', created: 'Creată în', retryHint: 'Reîncercarea verifică aceeași cerere de creare.' },
};

export function ChatTaskDialog({ text, opener, onClose, lang }: {
  text: string; opener: HTMLElement; onClose: () => void; lang: string;
}) {
  const k = lang === 'ro' ? copy.ro : copy.en;
  const ref = useRef<HTMLDialogElement>(null);
  const inFlight = useRef(false);
  const requestKey = useRef<string | null>(null);
  const headingId = useId();
  const [title, setTitle] = useState(text.split(/\r?\n/).find(line => line.trim())?.trim() || '');
  const [body, setBody] = useState(text);
  const [boards, setBoards] = useState<BoardMeta[] | null>(null);
  const [board, setBoard] = useState('');
  const [loadError, setLoadError] = useState('');
  const [saveError, setSaveError] = useState('');
  const [busy, setBusy] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [saved, setSaved] = useState<{ task: KanbanTask; board: BoardMeta } | null>(null);

  async function loadBoards() {
    setLoadError('');
    try {
      const result = await fetchBoards();
      const listed = result.boards.filter(item => item.slug?.trim());
      setBoards(listed);
      setBoard(listed.some(item => item.slug === result.current) ? result.current : listed[0]?.slug || '');
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : k.loadFailed);
    }
  }

  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    dialog.querySelector<HTMLInputElement>('input')?.focus();
    void loadBoards();
    return () => { dialog.close(); if (opener.isConnected) opener.focus(); };
  }, [opener]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const chosen = boards?.find(item => item.slug === board);
    if (!chosen || !title.trim() || inFlight.current || saved) return;
    inFlight.current = true;
    requestKey.current ||= Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
    setBusy(true);
    setAttempted(true);
    setSaveError('');
    try {
      const result = await createTask(chosen.slug, { title: title.trim(), body, triage: true, idempotency_key: requestKey.current });
      setSaved({ task: result.task, board: chosen });
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : k.saveFailed);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return <dialog className="chat-task-dialog" ref={ref} aria-labelledby={headingId} aria-modal="true"
    style={{ width: 'min(520px, calc(100vw - 32px))' }}
    onCancel={event => { event.preventDefault(); if (!inFlight.current) onClose(); }}
    onKeyDown={event => { event.stopPropagation(); if (event.key === 'Escape') { event.preventDefault(); if (!inFlight.current) onClose(); } }}>
    <h2 id={headingId}>{k.heading}</h2>
    {saved ? <div role="status">{k.created} {saved.board.name || saved.board.slug}: {saved.task.title} ({saved.task.id})</div> :
      <form onSubmit={event => void submit(event)}>
        {boards === null && !loadError && <p role="status">{k.loading}</p>}
        {loadError && <p role="alert">{k.loadFailed} {loadError} <button type="button" onClick={() => void loadBoards()}>{k.retry}</button></p>}
        {boards?.length === 0 && <p role="alert">{k.noBoards}</p>}
        <label>{k.board}<select value={board} onChange={event => setBoard(event.target.value)} disabled={!boards?.length || attempted} required>
          {boards?.map(item => <option key={item.slug} value={item.slug}>{item.name || item.slug}</option>)}
        </select></label>
        <label>{k.title}<input required value={title} onChange={event => setTitle(event.target.value)} disabled={attempted} /></label>
        <label>{k.description}<textarea value={body} onChange={event => setBody(event.target.value)} disabled={attempted} rows={6} /></label>
        {saveError && <p role="alert">{k.saveFailed} {saveError} {k.retryHint}</p>}
        <footer>
          <button type="button" onClick={onClose} disabled={busy}>{k.cancel}</button>
          <button type="submit" disabled={!boards?.some(item => item.slug === board) || !title.trim() || busy}>{busy ? k.creating : saveError ? k.retry : k.create}</button>
        </footer>
      </form>}
    {saved && <button type="button" onClick={onClose}>{k.close}</button>}
  </dialog>;
}
