import { useEffect, useRef, useState, type FormEvent } from 'react';
import * as api from './api';
import { useKanban } from './i18n';
import type { BoardMeta, KanbanProject } from './types';
import { errText } from './KanbanView';

type DialogKind = 'new' | 'settings' | 'rename' | 'archive' | 'export' | 'import' | null;

export function BoardSwitcher({ boards, current, projects, onSwitch, onRefresh, onError, onNotice }: {
  boards: BoardMeta[]; current: string; projects: KanbanProject[]; onSwitch: (slug: string) => void;
  onRefresh: () => Promise<void>; onError: (value: string) => void; onNotice?: (value: string) => void;
}) {
  const k = useKanban();
  const [dialog, setDialog] = useState<DialogKind>(null);
  const currentBoard = boards.find(b => b.slug === current);
  const [name, setName] = useState(''); const [description, setDescription] = useState(''); const [project, setProject] = useState(''); const [workdir, setWorkdir] = useState('');
  const [exportOutput, setExportOutput] = useState(''); const [exportAttachments, setExportAttachments] = useState(true); const [exportLogs, setExportLogs] = useState(false);
  const [importArchive, setImportArchive] = useState(''); const [importSlug, setImportSlug] = useState(''); const [importSwitch, setImportSwitch] = useState(false);
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
    setExportOutput(''); setExportAttachments(true); setExportLogs(false);
    setImportArchive(''); setImportSlug(''); setImportSwitch(false);
  }, [dialog, current]);
  const selectAndPersistBoard = (next: string) => {
    onSwitch(next);
    if ('switchBoard' in api) {
      void api.switchBoard(next).catch(err => onError(errText(err)));
    }
  };
  const pinServerBoard = async () => {
    setShowActions(false);
    try {
      const res = await api.switchBoard(current);
      await onRefresh();
      onNotice?.(`Active server board set to ${res.current || current}.`);
    } catch (err) {
      onError(errText(err));
    }
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault(); if (busy) return; setBusy(true); setError('');
    const startedOn = current;
    try {
      if (dialog === 'new') {
        if (!newSlug) throw new Error('Board name is required');
        const result = await api.createBoard(newSlug, name.trim(), project || undefined);
        if (currentRef.current !== startedOn) return;
        await onRefresh(); selectAndPersistBoard(result.board.slug);
      } else if (dialog === 'settings') {
        await api.updateBoard(current, { description, project_id: project, default_workdir: workdir });
        if (currentRef.current !== startedOn) return;
        await onRefresh();
      } else if (dialog === 'rename') {
        await api.updateBoard(current, { name: name.trim() });
        if (currentRef.current !== startedOn) return;
        await onRefresh();
      } else if (dialog === 'archive') {
        await api.deleteBoard(current);
        if (currentRef.current !== startedOn) return;
        await onRefresh(); selectAndPersistBoard(boards.find(b => b.slug !== current)?.slug || 'default');
      } else if (dialog === 'export') {
        const result = await api.exportBoard(current, { output: exportOutput.trim(), attachments: exportAttachments, logs: exportLogs });
        if (currentRef.current !== startedOn) return;
        onNotice?.(k.boardExported(result.archive));
      } else if (dialog === 'import') {
        if (!importArchive.trim()) throw new Error('Archive path is required');
        const result = await api.importBoard({
          archive: importArchive.trim(),
          ...(importSlug.trim() ? { slug: importSlug.trim() } : {}),
          switch: importSwitch,
        });
        if (currentRef.current !== startedOn) return;
        await onRefresh();
        if (importSwitch && result.board) onSwitch(result.board);
        const warningText = result.warnings?.length ? ` (${result.warnings.join('; ')})` : '';
        onNotice?.((result.renamed ? k.boardImportedAs(result.board) : k.boardImported(result.name || result.board)) + warningText);
      }
      setDialog(null);
    } catch (e) {
      if (currentRef.current === startedOn) {
        const message = errText(e);
        setError(message);
        onError(message);
        setBusy(false);
      }
    }
  };
  const dialogTitle = dialog === 'new' ? 'New board'
    : dialog === 'settings' ? 'Board settings'
    : dialog === 'rename' ? 'Rename board'
    : dialog === 'archive' ? 'Archive board'
    : dialog === 'export' ? 'Export board'
    : 'Import board';
  const submitLabel = dialog === 'new' ? k.createBoard
    : dialog === 'settings' ? 'Save board'
    : dialog === 'rename' ? 'Save name'
    : dialog === 'archive' ? 'Archive board'
    : dialog === 'export' ? 'Export archive'
    : 'Import archive';
  return <div className="kb-switcher">
    <label>Board <select aria-label="Board" value={current} onChange={e => selectAndPersistBoard(e.target.value)}>
      {boards.map(b => <option key={b.slug} value={b.slug}>{b.name || b.slug}{typeof b.total === 'number' ? ` · ${b.total}` : ''}</option>)}
    </select></label>
    <button type="button" onClick={() => setDialog('new')}>{k.newBoard}</button>
    <button type="button" disabled={!currentBoard} onClick={() => setDialog('settings')}>Board settings</button>
    <div className="kb-actions"><button type="button" aria-label="More board actions" onClick={() => setShowActions(v => !v)}>⋯</button>
      {showActions && <div className="kb-actions-menu">
        <button type="button" onClick={() => void pinServerBoard()}>Set active board</button>
        <button type="button" onClick={() => { setDialog('rename'); setShowActions(false); }}>Rename board</button>
        <button type="button" onClick={() => { setDialog('archive'); setShowActions(false); }} disabled={current === 'default'}>Archive board</button>
        <button type="button" onClick={() => { setDialog('export'); setShowActions(false); }}>Export board</button>
        <button type="button" onClick={() => { setDialog('import'); setShowActions(false); }}>Import board</button>
      </div>}
    </div>
    {dialog && <div className="kb-overlay" onMouseDown={e => { if (e.target === e.currentTarget) setDialog(null); }}><div role="dialog" aria-modal="true" aria-label={dialogTitle} className="kb-dialog">
      <header><h3>{dialog === 'new' ? k.newBoard : dialogTitle}</h3><button type="button" aria-label="Close" onClick={() => setDialog(null)}>×</button></header>
      <form onSubmit={submit}>
        {dialog === 'archive' ? <p>Archive {currentBoard?.name || current}? This board can be recovered from archived board data.</p>
          : dialog === 'export' ? <>
            <label>Export output path<input value={exportOutput} onChange={e => setExportOutput(e.target.value)} placeholder="Default scoped archive path" /></label>
            <label><input type="checkbox" checked={exportAttachments} onChange={e => setExportAttachments(e.target.checked)} />Include attachments</label>
            <label><input type="checkbox" checked={exportLogs} onChange={e => setExportLogs(e.target.checked)} />Include worker logs</label>
          </>
          : dialog === 'import' ? <>
            <label>Archive path<input autoFocus required value={importArchive} onChange={e => setImportArchive(e.target.value)} placeholder="/path/to/board-export.tar.gz" /></label>
            <label>Slug override<input value={importSlug} onChange={e => setImportSlug(e.target.value)} placeholder="Optional board slug" /></label>
            <label><input type="checkbox" checked={importSwitch} onChange={e => setImportSwitch(e.target.checked)} />Switch after import</label>
          </>
          : <>
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
        <footer><button type="button" onClick={() => setDialog(null)}>{k.cancel}</button><button type="submit" disabled={busy || (dialog === 'new' && !newSlug) || (dialog === 'rename' && !name.trim()) || (dialog === 'import' && !importArchive.trim())}>
          {submitLabel}
        </button></footer>
      </form>
    </div></div>}
  </div>;
}
