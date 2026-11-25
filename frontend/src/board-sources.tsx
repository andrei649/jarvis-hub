import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { onOwnerSession } from './api/owner-session';
import { fetchTask } from './panels/kanban/api';
import './composer-board-result.css';

export type BoardSource = { board: string; task_id: string; source: 'result' | 'latest_summary'; sha256: string };

export function boardSources(value: unknown): BoardSource[] {
  if (!Array.isArray(value) || !value.length || value.length > 8) return [];
  const rows = value.filter((item): item is BoardSource => item &&
    typeof item === 'object' && Object.keys(item).sort().join(',') === 'board,sha256,source,task_id' &&
    typeof item.board === 'string' && /^[a-z0-9][a-z0-9_-]{0,63}$/.test(item.board) &&
    typeof item.task_id === 'string' && /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(item.task_id) &&
    (item.source === 'result' || item.source === 'latest_summary') &&
    typeof item.sha256 === 'string' && /^[a-f0-9]{64}$/.test(item.sha256));
  return rows.length === value.length && new Set(rows.map(item => `${item.board}\0${item.task_id}`)).size === rows.length ? rows : [];
}

export function BoardSources({ sources, lang = 'en' }: { sources: BoardSource[]; lang?: string }) {
  const [selected, setSelected] = useState<BoardSource | null>(null);
  const [visible, setVisible] = useState(true);
  const [body, setBody] = useState('');
  const [title, setTitle] = useState('');
  const [currentSource, setCurrentSource] = useState<'result' | 'latest_summary'>('result');
  const [state, setState] = useState<'loading' | 'original' | 'changed' | 'missing' | 'unavailable'>('loading');
  const dialog = useRef<HTMLDialogElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const opener = useRef<HTMLButtonElement | null>(null);
  const serial = useRef(0);
  const ro = lang === 'ro';
  useEffect(() => onOwnerSession(() => { serial.current++; setSelected(null); setBody(''); setVisible(false); }), []);
  useEffect(() => setVisible(true), [sources]);
  useEffect(() => {
    if (!selected) return;
    dialog.current?.showModal(); close.current?.focus();
    return () => dialog.current?.close();
  }, [selected]);
  const dismiss = () => { serial.current++; setSelected(null); setBody(''); opener.current?.focus(); };
  const open = async (source: BoardSource, button: HTMLButtonElement) => {
    const request = ++serial.current;
    opener.current = button; setSelected(source); setBody(''); setTitle(''); setState('loading');
    try {
      const detail = await fetchTask(source.board, source.task_id);
      if (request !== serial.current) return;
      if (detail.task.id !== source.task_id || detail.task.status !== 'done') { setState('missing'); return; }
      const effectiveSource = typeof detail.task.result === 'string' && detail.task.result.trim() ? 'result' : 'latest_summary';
      const current = detail.task[effectiveSource];
      if (typeof current !== 'string' || !current.trim()) { setState('missing'); return; }
      setTitle(detail.task.title); setBody(current); setCurrentSource(effectiveSource);
      setState(effectiveSource === source.source && detail.task.board_source_sha256 === source.sha256 ? 'original' :
        typeof detail.task.board_source_sha256 === 'string' && /^[a-f0-9]{64}$/.test(detail.task.board_source_sha256) ? 'changed' : 'unavailable');
    } catch (error) {
      if (request === serial.current) setState((error as { status?: number })?.status === 404 ? 'missing' : 'unavailable');
    }
  };
  const sourceName = (source: BoardSource) => source.source === 'result'
    ? (ro ? 'Rezultat înregistrat' : 'Recorded result') : (ro ? 'Ultimul rezumat' : 'Latest summary');
  if (!visible) return null;
  return <>
    <ul className="board-source-links" aria-label={ro ? 'Surse din tablouri' : 'Board sources'}>
      {sources.map((source, index) => <li key={`${source.board}/${source.task_id}/${index}`}>
        <button type="button" className="tool-btn" onClick={event => void open(source, event.currentTarget)}>
          {sourceName(source)} · {source.board}/{source.task_id}
        </button>
      </li>)}
    </ul>
    {selected && createPortal(<dialog ref={dialog} className="board-result-review board-source-dialog" aria-modal="true"
      aria-label={`${sourceName(selected)} · ${selected.board}/${selected.task_id}`}
      onCancel={event => { event.preventDefault(); dismiss(); }} onKeyDown={event => event.stopPropagation()}>
      <header><strong>{sourceName(selected)} · {selected.board}/{selected.task_id}</strong>
        <button ref={close} type="button" className="tool-btn" onClick={dismiss}>{ro ? 'Închide' : 'Close'}</button></header>
      {state === 'loading' && <p role="status">{ro ? 'Se încarcă sursa…' : 'Loading source…'}</p>}
      {state === 'missing' && <p role="status">{ro ? 'Sarcina sau sursa nu mai este disponibilă.' : 'This task or source is no longer available.'}</p>}
      {state === 'unavailable' && <p role="status">{ro ? 'Sursa nu poate fi verificată. Accesul poate fi expirat.' : 'Source verification is unavailable. Access may have expired.'}</p>}
      {(state === 'original' || state === 'changed') && <>
        <p role="status">{state === 'original' ? (ro ? 'Sursa originală' : 'Original source') :
          (ro ? 'Sursa actuală s-a schimbat față de cea trimisă.' : 'Current source changed since it was sent.')}</p>
        <p>{title} · {ro ? 'Sursă actuală:' : 'Current source:'} {sourceName({ ...selected, source: currentSource })}</p>
        <pre className="board-source-text">{body}</pre>
      </>}
    </dialog>, document.body)}
  </>;
}
