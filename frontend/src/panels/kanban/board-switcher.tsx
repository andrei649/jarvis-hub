import { useEffect, useRef, useState, type FormEvent } from 'react';
import { createBoard, deleteBoard, updateBoard } from './api';
import { useKanban } from './i18n';
import type { BoardMeta, KanbanProject } from './types';
import { errText } from './KanbanView';

export function BoardSwitcher({ boards, current, projects, onSwitch, onRefresh, onError }: {
  boards: BoardMeta[]; current: string; projects: KanbanProject[]; onSwitch: (slug: string) => void; onRefresh: () => Promise<void>; onError: (value: string) => void;
}) {
  const k = useKanban();
  const [dialog, setDialog] = useState<'new' | 'settings' | 'rename' | 'archive' | null>(null);
  const currentBoard = boards.find(b => b.slug === current);
  const [name, setName] = useState(''); const [description, setDescription] = useState(''); const [project, setProject] = useState(''); const [workdir, setWorkdir] = useState('');
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const [showActions, setShowActions] = useState(false);
  const currentRef = useRef(current);
  const previousCurrent = useRef(current);
  currentRef.current = current;
  useEffect(() => {
    if (previousCurrent.current !== current) setDialog(null);
    previousCurrent.current = current;
  }, [current]);
  const newSlug = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  useEffect(() => {
    if (!dialog) return;
    setError(''); setBusy(false);
    setName(dialog === 'new' ? '' : currentBoard?.name || current);
    setDescription(dialog === 'new' ? '' : currentBoard?.description || '');
    setProject(dialog === 'new' ? '' : currentBoard?.project_id || '');
    setWorkdir(dialog === 'new' ? '' : currentBoard?.default_workdir || '');
  }, [dialog, current]);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); if (busy) return; setBusy(true); setError('');
    const startedOn = current;
    try {
      if (dialog === 'new') {
        if (!newSlug) throw new Error('Board name is required');
        const result = await createBoard(newSlug, name.trim(), project || undefined);
        if (currentRef.current !== startedOn) return;
        await onRefresh(); onSwitch(result.board.slug);
      } else if (dialog === 'settings') {
        await updateBoard(current, { description, project_id: project, default_workdir: workdir });
        if (currentRef.current !== startedOn) return;
        await onRefresh();
      } else if (dialog === 'rename') {
        await updateBoard(current, { name: name.trim() });
        if (currentRef.current !== startedOn) return;
        await onRefresh();
      } else if (dialog === 'archive') {
        await deleteBoard(current);
        if (currentRef.current !== startedOn) return;
        await onRefresh(); onSwitch(boards.find(b => b.slug !== current)?.slug || 'default');
      }
      setDialog(null);
    } catch (e) { if (currentRef.current === startedOn) { const message = errText(e); setError(message); onError(message); setBusy(false); } }
  };
  return <div className="kb-switcher">
    <label>Board <select aria-label="Board" value={current} onChange={e => onSwitch(e.target.value)}>
      {boards.map(b => <option key={b.slug} value={b.slug}>{b.name || b.slug}{typeof b.total === 'number' ? ` · ${b.total}` : ''}</option>)}
    </select></label>
    <button type="button" onClick={() => setDialog('new')}>{k.newBoard}</button>
    <button type="button" disabled={!currentBoard} onClick={() => setDialog('settings')}>Board settings</button>
    <div className="kb-actions"><button type="button" aria-label="More board actions" onClick={() => setShowActions(v => !v)}>⋯</button>
      {showActions && <div className="kb-actions-menu">
        <button type="button" onClick={() => { setDialog('rename'); setShowActions(false); }}>Rename board</button>
        <button type="button" onClick={() => { setDialog('archive'); setShowActions(false); }} disabled={current === 'default'}>Archive board</button>
        <span title="Board transfer requires a Nerva adapter">Export board · unavailable</span>
        <span title="Board transfer requires a Nerva adapter">Import board · unavailable</span>
      </div>}
    </div>
    {dialog && <div className="kb-overlay" onMouseDown={e => { if (e.target === e.currentTarget) setDialog(null); }}><div role="dialog" aria-modal="true" aria-label={dialog === 'new' ? 'New board' : dialog === 'settings' ? 'Board settings' : dialog === 'rename' ? 'Rename board' : 'Archive board'} className="kb-dialog">
      <header><h3>{dialog === 'new' ? k.newBoard : dialog === 'settings' ? 'Board settings' : dialog === 'rename' ? 'Rename board' : 'Archive board'}</h3><button type="button" aria-label="Close" onClick={() => setDialog(null)}>×</button></header>
      <form onSubmit={submit}>
        {dialog === 'archive' ? <p>Archive {currentBoard?.name || current}? This board can be recovered from archived board data.</p> : <>
          {dialog !== 'settings' && <label>Name<input autoFocus value={name} onChange={e => setName(e.target.value)} required /></label>}
          {dialog === 'new' && <span className="kb-muted">Slug: {newSlug || '—'}</span>}
          {dialog === 'settings' && <><label>Description<textarea value={description} onChange={e => setDescription(e.target.value)} /></label>
            <label>Default workdir<input value={workdir} onChange={e => setWorkdir(e.target.value)} placeholder="Inherit project primary path" /></label></>}
          {(dialog === 'new' || dialog === 'settings') && <label>Project<select value={project} onChange={e => setProject(e.target.value)}>
            <option value="">No project</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select></label>}
          {dialog === 'settings' && <p className="kb-muted">The project and workdir become this board’s default workspace only after the server accepts the update.</p>}
        </>}
        {error && <div role="alert" className="kb-alert">{error}</div>}
        <footer><button type="button" onClick={() => setDialog(null)}>{k.cancel}</button><button type="submit" disabled={busy || (dialog === 'new' && !newSlug) || (dialog === 'rename' && !name.trim())}>
          {dialog === 'new' ? k.createBoard : dialog === 'settings' ? 'Save board' : dialog === 'rename' ? 'Save name' : 'Archive board'}
        </button></footer>
      </form>
    </div></div>}
  </div>;
}
