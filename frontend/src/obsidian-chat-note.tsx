import React, { useLayoutEffect, useId, useRef, useState } from 'react';
import { apiFetchOnce, getToken } from './api/client';
import { csrfToken, onOwnerSession } from './api/owner-session';
import { obsidianOpenUri } from '../../apps/jarvis-os/public/js/obsidian-source.js';
import './obsidian-chat-note.css';

export type Target = { id: string; vault: string; inbox: string };
export type NoteReceipt = { relPath: string; source: { vault: string; file: string; readable: boolean } | null };
export type NoteSubmission = { target: Target; title: string; content: string; requestId: string };
export const noteCredential = () => `${getToken()}\u0000${csrfToken()}`;
function requestId(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = globalThis.crypto?.getRandomValues?.(new Uint8Array(16));
  if (!bytes) throw new Error('Secure random unavailable');
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
const validTarget = (value: any): value is Target =>
  typeof value?.id === 'string' && !!value.id && typeof value.vault === 'string' && !!value.vault &&
  typeof value.inbox === 'string' && !!value.inbox && !value.inbox.startsWith('/') &&
  value.inbox.split('/').every((part: string) => !!part && part !== '.' && part !== '..');
const sameTarget = (a: Target, b: Target) => a.id === b.id && a.vault === b.vault && a.inbox === b.inbox;

async function captureTarget(): Promise<Target | null> {
  const response = await apiFetchOnce('/api/os/status');
  if (!response.ok) throw new Error(`Vault status failed (${response.status})`);
  const body = await response.json();
  if (body?.ok !== true || !Object.prototype.hasOwnProperty.call(body, 'captureTarget') ||
      (body.captureTarget !== null && !validTarget(body.captureTarget))) throw new Error('Invalid vault status');
  return body.captureTarget;
}

function readReceipt(body: any, target: Target): NoteReceipt {
  const path = body?.relPath;
  if (body?.ok !== true || typeof path !== 'string' || path.length > 4096 ||
      !path.startsWith(`${target.inbox}/`) || path.endsWith('/') || path.includes('\\') ||
      path.split('/').some(part => !part || part === '.' || part === '..') ||
      !path.toLowerCase().endsWith('.md') ||
      (body.source !== null && (!body.source || body.source.vault !== target.vault ||
       body.source.file !== path || !obsidianOpenUri(body.source)))) throw new Error('Invalid save receipt');
  return { relPath: path, source: body.source };
}

export function ObsidianChatNote({ text, initialTitle, isCurrent, lang, opener, onClose, onSaved, onTarget, initialSubmission, onSubmitted }: {
  text: string; lang?: string; opener: HTMLElement; onClose: () => void; onSaved: (receipt: NoteReceipt, target: Target) => void;
  initialTitle?: string; isCurrent?: () => boolean;
  onTarget?: (target: Target | null) => void;
  initialSubmission?: NoteSubmission | null; onSubmitted?: (submission: NoteSubmission | null) => void;
}) {
  const ro = lang === 'ro';
  const titleId = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const live = useRef(true);
  const sending = useRef(false);
  const initialCredential = useRef(noteCredential());
  const [target, setTarget] = useState<Target | null>(null);
  const [title, setTitle] = useState(() => initialSubmission?.title ?? initialTitle ?? Array.from(text.trim().split(/\r?\n/, 1)[0]).slice(0, 120).join(''));
  const [content, setContent] = useState(initialSubmission?.content ?? text);
  const [state, setState] = useState<'loading' | 'ready' | 'unavailable' | 'uncertain' | 'conflict' | 'saved'>('loading');
  const [error, setError] = useState('');
  const [conflictedTitle, setConflictedTitle] = useState('');
  const [submitted, setSubmitted] = useState<NoteSubmission | null>(initialSubmission || null);
  const [receipt, setReceipt] = useState<NoteReceipt | null>(null);

  function canReview() {
    if (!live.current) return false;
    if (noteCredential() === initialCredential.current && (isCurrent?.() ?? true)) return true;
    setTitle(''); setContent(''); setSubmitted(null);
    setTarget(null); setReceipt(null); setState('unavailable');
    setError(ro ? 'Sesiunea s-a schimbat. Închide și redeschide.' : 'Session changed. Close and reopen.');
    return false;
  }

  useLayoutEffect(() => {
    let active = true;
    live.current = true;
    const node = dialog.current;
    node?.showModal();
    const unsubscribe = onOwnerSession(() => { canReview(); });
    if (canReview()) void captureTarget().then(value => {
      if (!active || !canReview()) return;
      setTarget(value); onTarget?.(value);
      if (submitted && value && !sameTarget(submitted.target, value)) {
        setState('unavailable'); setError(ro ? 'Destinația s-a schimbat. Închide și redeschide.' : 'Destination changed. Close and reopen.');
        onSubmitted?.(null);
      } else setState(value ? (submitted ? 'uncertain' : 'ready') : 'unavailable');
    }).catch(() => {
      if (!active || !canReview()) return;
      setState('unavailable'); setError(ro ? 'Destinația nu poate fi verificată.' : 'Destination could not be verified.');
    });
    return () => { active = false; live.current = false; unsubscribe(); node?.close(); if (opener.isConnected) opener.focus(); };
  }, [opener, ro]);

  async function save() {
    if (sending.current || !target || !title.trim() || Array.from(title).length > 120 || !content.trim() || Array.from(content).length > 100_000 ||
        (state === 'conflict' && title === conflictedTitle) ||
        state === 'saved' || !canReview()) return;
    let draft = submitted;
    if (!draft) {
      try { draft = { target, title, content, requestId: requestId() }; }
      catch { setState('unavailable'); setError(ro ? 'Nu se poate genera un identificator sigur.' : 'Secure request ID unavailable.'); return; }
    }
    sending.current = true;
    setError('');
    setSubmitted(draft);
    onSubmitted?.(draft);
    setState('loading');
    try {
      const current = await captureTarget();
      if (!canReview()) return;
      if (!current || !sameTarget(draft.target, current)) {
        setTarget(null); setState('unavailable');
        onTarget?.(current);
        if (current) onSubmitted?.(null);
        setError(ro ? 'Destinația sau sesiunea s-a schimbat. Închide și redeschide.' : 'Destination or session changed. Close and reopen.');
        return;
      }
      const response = await apiFetchOnce('/api/os/brain/chat-note', { method: 'POST', body: {
        targetId: draft.target.id, requestId: draft.requestId, title: draft.title, content: draft.content,
      } });
      if (response.status === 409) {
        const failure = await response.json();
        if (failure?.ok === false && failure.code === 'title_conflict') {
          if (!canReview()) return;
          setSubmitted(null); onSubmitted?.(null); setConflictedTitle(draft.title); setState('conflict');
          setError(ro ? 'Există deja o notă cu acest titlu. Schimbă titlul și salvează din nou.'
            : 'A note already uses this title. Change the title and save again.');
          return;
        }
      }
      if (!response.ok) throw new Error(`Save failed (${response.status})`);
      const saved = readReceipt(await response.json(), draft.target);
      if (!canReview()) return;
      setReceipt(saved); setState('saved'); onSubmitted?.(null); onSaved(saved, draft.target);
    } catch {
      if (!canReview()) return;
      setState('uncertain');
      setError(ro ? 'Salvarea nu a putut fi confirmată. Reîncearcă aceeași cerere.' : 'Save could not be confirmed. Retry the same request.');
    } finally { sending.current = false; }
  }

  const locked = !!submitted;
  const uri = receipt?.source && target?.vault === receipt.source.vault ? obsidianOpenUri(receipt.source) : null;
  return <dialog ref={dialog} className="obsidian-chat-note" aria-labelledby={titleId} aria-modal="true"
    onCancel={event => { event.preventDefault(); event.stopPropagation(); if (!sending.current) onClose(); }}
    onKeyDown={event => { event.stopPropagation(); if (event.key === 'Escape') { event.preventDefault(); if (!sending.current) onClose(); } }}>
    <header><h2 id={titleId}>{ro ? 'Salvează în Obsidian' : 'Save to Obsidian'}</h2>
      <button type="button" className="tool-btn" onClick={onClose} disabled={sending.current}>{ro ? 'Închide' : 'Close'}</button></header>
    <p>{ro ? 'Revizuiește nota și destinația înainte de salvare.' : 'Review the note and destination before saving.'}</p>
    <dl><div><dt>{ro ? 'Vault' : 'Vault'}</dt><dd>{target?.vault || '—'}</dd></div>
      <div><dt>Inbox</dt><dd>{target?.inbox || '—'}</dd></div></dl>
    <form onSubmit={event => { event.preventDefault(); void save(); }}>
      <label>{ro ? 'Titlu' : 'Title'}<input value={title} disabled={locked} required
        onChange={event => setTitle(event.target.value)} /></label>
      <label>{ro ? 'Notă' : 'Note'}<textarea value={content} disabled={locked} required
        onChange={event => setContent(event.target.value)} /></label>
      {error && <div role="alert">{error}</div>}
      {Array.from(title).length > 120 && <div role="alert">{ro ? 'Titlul depășește 120 de caractere.' : 'Title exceeds 120 characters.'}</div>}
      {Array.from(content).length > 100_000 && <div role="alert">{ro ? 'Nota depășește 100.000 de caractere.' : 'Note exceeds 100,000 characters.'}</div>}
      {state === 'uncertain' && !error && <div role="status">{ro ? 'Salvarea anterioară nu e confirmată. Reîncearcă aceeași cerere.' : 'Previous save is unconfirmed. Retry the same request.'}</div>}
      {state === 'unavailable' && !error && <div role="status">{ro ? 'Destinație indisponibilă.' : 'Destination unavailable.'}</div>}
      {state === 'saved' && receipt && <div role="status">{ro ? 'Salvat: ' : 'Saved: '}{receipt.relPath}
        {uri && <> · <a href={uri}>{ro ? 'Deschide în Obsidian' : 'Open in Obsidian'}</a></>}</div>}
      <div className="obsidian-chat-note-actions"><button className="tool-btn" type="button" onClick={onClose} disabled={sending.current}>{ro ? 'Anulează' : 'Cancel'}</button>
        <button className="tool-btn" type="submit" disabled={!target || state === 'loading' || state === 'unavailable' || state === 'saved' ||
          (state === 'conflict' && title === conflictedTitle) || !title.trim() || !content.trim() ||
          Array.from(title).length > 120 || Array.from(content).length > 100_000}>
          {state === 'loading' ? (ro ? 'Se verifică…' : 'Checking…') : state === 'uncertain' ? (ro ? 'Reîncearcă salvarea' : 'Retry save') : (ro ? 'Salvează nota' : 'Save note')}</button></div>
    </form>
  </dialog>;
}
