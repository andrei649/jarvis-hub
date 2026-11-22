import React, { useLayoutEffect, useRef, useState } from 'react';
import { apiFetchOnce } from './api/client';
import { appUrl } from './base-path';
import { fetchWorkshopContext, WorkshopProjects } from './workshop-projects';
import { obsidianOpenUri } from '../../apps/jarvis-os/public/js/obsidian-source.js';
import './composer-vault.css';

export type VaultExcerpt = { name: string; text: string };
type VaultSource = { vault: string; file: string; readable: boolean };
type VaultResult = VaultExcerpt & { source?: VaultSource };
type Passage = { source: VaultSource; body: string; text: string };
const canChoosePassage = (source?: VaultSource) => !!source?.readable && Array.from(source.file).length <= 200;
const displayedNote = (body: string) => body.replace(/\r\n?/g, '\n');

async function findNotes(question: string, signal: AbortSignal): Promise<VaultResult[]> {
  const response = await apiFetchOnce('/api/os/brain/retrieve?q=' + encodeURIComponent(question), { signal });
  if (!response.ok) throw new Error('Vault lookup failed');
  const { ok, attachments, sources } = await response.json();
  if (ok !== true || !Array.isArray(attachments) || attachments.length > 4) throw new Error('Invalid vault response');
  const names = new Set<string>();
  return attachments.map(item => {
    if (typeof item?.name !== 'string' || !item.name || Array.from(item.name).length > 200 ||
        typeof item.text !== 'string' || !item.text.trim() || Array.from(item.text).length > 1500 ||
        names.has(item.name)) throw new Error('Invalid note excerpt');
    names.add(item.name);
    const source = sources && Object.prototype.hasOwnProperty.call(sources, item.name) ? sources[item.name] : undefined;
    return { name: item.name, text: item.text,
      ...(source && obsidianOpenUri(source) ? { source } : {}) };
  });
}

async function readNote(source: VaultSource, signal: AbortSignal): Promise<string> {
  const response = await apiFetchOnce('/api/os/brain/note?relPath=' + encodeURIComponent(source.file), { signal });
  if (!response.ok) throw new Error('Note unavailable');
  const note = await response.json();
  if (note.ok !== true || typeof note.body !== 'string') throw new Error('Invalid note');
  return note.body;
}

export function useVaultNotes(question: string, agent: string, session: string, live: boolean) {
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState<VaultResult[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [passages, setPassages] = useState<Record<string, Passage>>({});
  const [choosing, setChoosing] = useState<{ name: string; body: string } | null>(null);
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const pending = useRef<AbortController | null>(null);
  const sendingQuestion = useRef<string | null>(null);
  const projectPath = useRef('');

  function clear() {
    pending.current?.abort();
    pending.current = null;
    sendingQuestion.current = null;
    projectPath.current = '';
    setOpen(false); setResults([]); setSelected([]); setPassages({}); setChoosing(null); setStatus(''); setBusy(false);
  }
  useLayoutEffect(() => {
    clear();
    return () => pending.current?.abort();
  }, [agent, session, live]);
  useLayoutEffect(() => {
    if (!projectPath.current || question.startsWith('/')) clear();
    else if (sendingQuestion.current !== null && question !== sendingQuestion.current) {
      pending.current?.abort(); pending.current = null; sendingQuestion.current = null;
      setBusy(false); setStatus('Message edited. Send again when ready.');
    }
  }, [question]);

  async function lookup(send?: (notes: VaultExcerpt[]) => boolean, path = projectPath.current) {
    if (pending.current || !live || (!question && !path) || question.startsWith('/') || (send && !question)) return;
    const controller = new AbortController();
    pending.current = controller;
    sendingQuestion.current = send ? question : null;
    setOpen(true); setBusy(true);
    setStatus(send ? 'Checking selected excerpts…' : 'Searching notes…');
    try {
      let found: VaultResult[];
      if (path) {
        const item = await fetchWorkshopContext(path, controller.signal);
        const name = Array.from(path).length <= 200 ? path : item.title;
        const text = [item.title, item.summary, JSON.stringify(item.project)].join('\n');
        if (Array.from(text).length > 1500) throw new Error('Project exceeds attachment size');
        found = [{ name, text }];
      } else {
        found = await findNotes(question, controller.signal);
      }
      if (controller.signal.aborted) return;
      const checked = results.filter(item => selected.includes(item.name));
      if (send && checked.length && checked.every(item => found.some(current =>
        current.name === item.name && current.text === item.text &&
        (!item.source || (current.source?.vault === item.source.vault &&
          current.source?.file === item.source.file && current.source?.readable === item.source.readable))))) {
        try {
          const outgoing = await Promise.all(checked.map(async item => {
            const passage = passages[item.name];
            if (!passage) return { name: item.name, text: item.text };
            if (await readNote(passage.source, controller.signal) !== passage.body) throw new Error('Note changed');
            return { name: passage.source.file, text: passage.text };
          }));
          if (controller.signal.aborted) return;
          if (new Set(outgoing.map(item => item.name)).size !== outgoing.length) throw new Error('Ambiguous source');
          if (send(outgoing)) clear();
          else setStatus('Your draft is ready. Try sending again.');
          return;
        } catch {
          if (controller.signal.aborted) return;
        }
      }
      setResults(found); setSelected([]); setPassages({}); setChoosing(null);
      setStatus(send ? 'A selected note changed or became unavailable. Review the results again.'
        : found.length ? '' : 'No matching notes. Check your vault or try different words.');
    } catch {
      if (controller.signal.aborted) return;
      setResults([]); setSelected([]); setPassages({}); setChoosing(null);
      setStatus(path ? 'The saved project could not be read. Open it from the list to try again.'
        : 'The vault could not be searched. Check the connection and try again.');
    } finally {
      if (pending.current === controller) { pending.current = null; sendingQuestion.current = null; setBusy(false); }
    }
  }

  function toggle(name: string) {
    setSelected(names => names.includes(name) ? names.filter(n => n !== name) : [...names, name]);
  }
  async function choosePassage(name: string) {
    const source = results.find(item => item.name === name)?.source;
    if (!canChoosePassage(source) || pending.current) return;
    const controller = new AbortController();
    pending.current = controller; setBusy(true); setStatus('Opening note…'); setChoosing(null);
    try {
      const body = await readNote(source, controller.signal);
      if (!controller.signal.aborted) { setChoosing({ name, body }); setStatus(''); }
    } catch {
      if (!controller.signal.aborted) { setStatus('The note could not be read. Search again before choosing a passage.'); setSelected(names => names.filter(n => n !== name)); setPassages(current => { const next = { ...current }; delete next[name]; return next; }); }
    } finally {
      if (pending.current === controller) { pending.current = null; setBusy(false); }
    }
  }
  function confirmPassage(name: string, start: number, end: number) {
    const source = results.find(item => item.name === name)?.source;
    if (!canChoosePassage(source) || choosing?.name !== name) return;
    if (start >= end) { setStatus('Highlight the passage you want to send.'); return; }
    const text = displayedNote(choosing.body).slice(start, end);
    if (!text.trim() || Array.from(text).length > 1500) { setStatus('Select up to 1,500 characters of note text.'); return; }
    setPassages(current => ({ ...current, [name]: { source, body: choosing.body, text } }));
    setSelected(names => names.includes(name) ? names : [...names, name]);
    setChoosing(null); setStatus('Passage selected. Review it before sending.');
  }
  function reviewProject(path: string) {
    clear();
    projectPath.current = path;
    void lookup(undefined, path);
  }
  return { open, results, selected, passages, choosing, status, busy, lookup, reviewProject, toggle, choosePassage, confirmPassage, clear };
}

export function VaultNoteReview({ draft }: { draft: ReturnType<typeof useVaultNotes> }) {
  const passageInput = useRef<HTMLTextAreaElement>(null);
  if (!draft.open) return null;
  return <section className="vault-review" aria-label="Obsidian note excerpts">
    <div className="vault-review-head"><strong>Obsidian notes</strong>
      <a href={appUrl('/os/')} target="_blank" rel="noreferrer">Open vault ↗</a>
      <button type="button" className="tool-btn" onClick={draft.clear} aria-label="Close vault notes">Close</button>
    </div>
    <WorkshopProjects actionLabel="Review in chat" onChoose={project => draft.reviewProject(project.path)}/>
    {draft.results.length > 0 && <p>Check a found excerpt or choose a passage to send with this message.</p>}
    {draft.status && <p role="status">{draft.status}</p>}
    {draft.results.map(note => <div className="vault-review-note" key={note.name}>
      <label><input type="checkbox" checked={draft.selected.includes(note.name)} disabled={draft.busy}
        onChange={() => draft.toggle(note.name)}/><span>{note.name}</span></label>
      <details><summary>Found excerpt or summary</summary><p>{note.text}</p></details>
      {note.source && <div className="vault-review-actions">
        <a href={obsidianOpenUri(note.source) || undefined}>Open in Obsidian</a>
        {canChoosePassage(note.source) && <button type="button" className="tool-btn" disabled={draft.busy}
          onClick={() => void draft.choosePassage(note.name)}>Choose passage</button>}
      </div>}
      {draft.choosing?.name === note.name && <div className="vault-passage-picker">
        <label htmlFor="vault-passage-text">Select text from this note{Array.from(draft.choosing.body).length >= 6000
          ? ' (first 6,000 characters)' : ''}</label>
        <textarea id="vault-passage-text" ref={passageInput} readOnly value={displayedNote(draft.choosing.body)} rows={8}/>
        <button type="button" className="tool-btn" onClick={() => draft.confirmPassage(note.name,
          passageInput.current?.selectionStart ?? 0, passageInput.current?.selectionEnd ?? 0)}>Use selected passage</button>
      </div>}
      {draft.passages[note.name] && <div className="vault-passage-preview">
        <strong>Passage to send from {draft.passages[note.name].source.file}</strong>
        <p>{draft.passages[note.name].text}</p>
      </div>}
    </div>)}
  </section>;
}
