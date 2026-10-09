import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { BoardCanvas, NewTaskDialog } from './board';
import { BoardSwitcher } from './board-switcher';
import { TaskDrawer } from './drawer';
import { createKanbanSocket, fetchBoard, fetchBoards, fetchOrchestration, fetchProfiles, fetchProjects, patchTask, bulkTasks, deleteTask, dispatch } from './api';
import type { BoardMeta, BoardsResponse, KanbanBoard, KanbanProfile, KanbanProject, OrchestrationSettings } from './types';
import './kanban.css';

const selectedKey = 'nerva.kanban.board';
const POLL_MS = 60_000;
const RECONNECT_MS = 3_000;
export const LOCKED_COLUMNS = ['running', 'scheduled', 'review'];
export const isLockedTarget = (name: string) => LOCKED_COLUMNS.includes(name);
export function errText(error: unknown): string {
  if (error instanceof Error) {
    const body = (error as Error & {body?: {detail?: unknown}}).body;
    const detail = body?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail.map(item => typeof item?.msg === 'string' ? item.msg : JSON.stringify(item)).join('; ');
    if (detail && typeof detail === 'object') return JSON.stringify(detail);
    return error.message;
  }
  return String(error);
}
function initialSlug(): string { try { return localStorage.getItem(selectedKey) || ''; } catch { return ''; } }
function saveSlug(slug: string): void { try { localStorage.setItem(selectedKey, slug); } catch { /* storage may be disabled */ } }
function moveCard(board: KanbanBoard, id: string, status: string): KanbanBoard {
  let moved = board.columns.flatMap(c => c.tasks).find(t => t.id === id);
  if (!moved) return board;
  moved = { ...moved, status };
  return { ...board, columns: board.columns.map(c => ({ ...c, tasks: c.name === status ? [moved!, ...c.tasks.filter(t => t.id !== id)] : c.tasks.filter(t => t.id !== id) })) };
}

export function KanbanView() {
  const [slug, setSlugState] = useState(initialSlug);
  const [boards, setBoards] = useState<BoardsResponse | null>(null);
  const [board, setBoard] = useState<KanbanBoard | null>(null);
  const [profiles, setProfiles] = useState<KanbanProfile[]>([]);
  const [projects, setProjects] = useState<KanbanProject[]>([]);
  const [orchestration, setOrchestration] = useState<OrchestrationSettings | null>(null);
  const [auxiliaryError, setAuxiliaryError] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [archived, setArchived] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [addStatus, setAddStatus] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const generation = useRef(0);
  const boardRef = useRef<KanbanBoard | null>(null);
  const cursorRef = useRef(0);
  const socketRef = useRef<{close: () => void} | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const slugRef = useRef(slug);
  slugRef.current = slug;
  boardRef.current = board;
  const setSlug = (next: string) => { slugRef.current = next; saveSlug(next); setSlugState(next); setBoard(null); setSelected(new Set()); setOpenId(null); setAddStatus(null); setError(''); setNotice(''); };
  const sameScope = (forSlug: string, forGeneration: number) =>
    slugRef.current === forSlug && generation.current === forGeneration;

  const reloadBoards = useCallback(async () => {
    const result = await fetchBoards();
    setBoards(result);
    return result;
  }, []);
  useEffect(() => {
    let live = true;
    reloadBoards().then(result => {
      if (!live) return;
      if (!slug || !result.boards.some(b => b.slug === slug)) setSlug(result.current || result.boards[0]?.slug || 'default');
    }).catch(e => live && setError(errText(e)));
    fetchProjects().then(r => { if (live) setProjects(r.projects || []); }).catch(e => { if (live) setAuxiliaryError(errText(e)); });
    fetchProfiles().then(r => { if (live) setProfiles(r.profiles || []); }).catch(e => { if (live) setAuxiliaryError(errText(e)); });
    fetchOrchestration().then(r => { if (live) setOrchestration(r); }).catch(e => { if (live) setAuxiliaryError(errText(e)); });
    return () => { live = false; };
  // Initial metadata; board refreshes below.
  }, []);

  const loadBoard = useCallback(async (forSlug = slugRef.current, includeArchived = archived) => {
    const requestGeneration = generation.current;
    try {
      const result = await fetchBoard(forSlug, includeArchived);
      if (requestGeneration !== generation.current || forSlug !== slugRef.current) return null;
      setBoard(result);
      cursorRef.current = Math.max(cursorRef.current, result.latest_event_id || 0);
      setError('');
      return result;
    } catch (e) {
      if (requestGeneration === generation.current && forSlug === slugRef.current) setError(errText(e));
      return null;
    }
  }, [archived]);

  useEffect(() => {
    if (!slug) return;
    const currentGeneration = ++generation.current;
    cursorRef.current = 0;
    if (reconnectRef.current) clearTimeout(reconnectRef.current);
    socketRef.current?.close(); socketRef.current = null;
    let cancelled = false;
    const openSocket = (cursor: number) => {
      if (cancelled || generation.current !== currentGeneration) return;
      socketRef.current = createKanbanSocket(slug, cursor, frame => {
        if (cancelled || generation.current !== currentGeneration || slugRef.current !== slug) return;
        if (typeof frame.cursor === 'number') cursorRef.current = Math.max(cursorRef.current, frame.cursor);
        if (frame.events?.length) void loadBoard(slug, archived);
      }, () => {
        if (cancelled || generation.current !== currentGeneration) return;
        reconnectRef.current = setTimeout(() => openSocket(cursorRef.current), RECONNECT_MS);
      });
    };
    void fetchBoard(slug, archived).then(result => {
      if (cancelled || generation.current !== currentGeneration || slugRef.current !== slug) return;
      setBoard(result); setError('');
      cursorRef.current = result.latest_event_id || 0;
      openSocket(cursorRef.current);
    }).catch(e => { if (!cancelled && generation.current === currentGeneration) setError(errText(e)); });
    const poll = setInterval(() => { void loadBoard(slug, archived); }, POLL_MS);
    return () => { cancelled = true; generation.current++; clearInterval(poll); if (reconnectRef.current) clearTimeout(reconnectRef.current); socketRef.current?.close(); socketRef.current = null; };
  }, [slug, archived]);

  const activeSlug = slug || boards?.current || 'default';
  const activeMeta: BoardMeta | undefined = boards?.boards.find(b => b.slug === activeSlug);
  const columns = useMemo(() => board?.columns.map(c => c.name) || ['triage', 'todo', 'ready', 'running', 'blocked', 'review', 'done'], [board]);
  const allTasks = useMemo(() => board?.columns.flatMap(c => c.tasks) || [], [board]);
  const refresh = async () => { await Promise.all([reloadBoards().catch(e => setError(errText(e))), loadBoard(activeSlug)]); };
  const onMove = async (id: string, status: string) => {
    if (!boardRef.current || isLockedTarget(status)) { setError('That lane is managed by the worker workflow.'); return; }
    const operationGeneration = generation.current;
    const previous = boardRef.current; setBoard(moveCard(previous, id, status));
    try { await patchTask(activeSlug, id, {status}); if (sameScope(activeSlug, operationGeneration)) await loadBoard(activeSlug); }
    catch (e) { if (sameScope(activeSlug, operationGeneration)) { setBoard(previous); setError(errText(e)); } }
  };
  const onDelete = async (id: string) => {
    if (!window.confirm('Delete this task?')) return;
    const operationGeneration = generation.current;
    try { await deleteTask(activeSlug, id); if (sameScope(activeSlug, operationGeneration)) { setOpenId(current => current === id ? null : current); await loadBoard(activeSlug); } }
    catch (e) { if (sameScope(activeSlug, operationGeneration)) setError(errText(e)); }
  };
  const onBulk = async (patch: Record<string, unknown>) => {
    const ids = [...selected];
    const operationGeneration = generation.current;
    try {
      const result = await bulkTasks(activeSlug, ids, patch);
      if (!sameScope(activeSlug, operationGeneration)) return;
      const failed = result.results.filter(r => !r.ok);
      await loadBoard(activeSlug);
      if (!sameScope(activeSlug, operationGeneration)) return;
      if (failed.length) { setSelected(new Set(failed.map(r => r.id))); setError(`${failed.length} of ${ids.length} tasks refused: ${failed.map(r => r.error).filter(Boolean).join('; ')}`); }
      else { setSelected(new Set()); setError(''); }
    } catch (e) { if (sameScope(activeSlug, operationGeneration)) setError(errText(e)); }
  };
  const onBulkDelete = async () => {
    const ids = [...selected];
    if (!ids.length || !window.confirm(`Delete ${ids.length} selected tasks?`)) return;
    const operationGeneration = generation.current;
    const outcomes = await Promise.allSettled(ids.map(id => deleteTask(activeSlug, id)));
    if (!sameScope(activeSlug, operationGeneration)) return;
    const failed = ids.flatMap((id, i) => outcomes[i].status === 'rejected' ? [{ id, error: errText((outcomes[i] as PromiseRejectedResult).reason) }] : []);
    await loadBoard(activeSlug);
    if (!sameScope(activeSlug, operationGeneration)) return;
    setSelected(new Set(failed.map(item => item.id)));
    setError(failed.length ? `${failed.length} of ${ids.length} tasks refused: ${failed.map(item => item.error).join('; ')}` : '');
  };
  const onDispatch = async () => {
    const operationGeneration = generation.current;
    try {
      const result = await dispatch(activeSlug);
      if (!sameScope(activeSlug, operationGeneration)) return;
      if (!result.ok || result.status === 'refused') {
        setNotice(''); setError(`Dispatch refused: ${result.reason || 'the server did not accept the request'}`);
      } else if (result.status === 'busy') {
        setError(''); setNotice('Dispatch is busy; no new request was queued.');
      } else if (result.status === 'queued' && Array.isArray(result.queued) && result.queued.length === 0) {
        setError(''); setNotice('No eligible tasks were queued.');
      } else if (result.status === 'queued' && Array.isArray(result.queued) && result.queued.length > 0) {
        const requests = result.queued.map(item => `queue ${item.queue_id} (${item.status})`).join(', ');
        setError(''); setNotice(`${result.queued.length} signed request${result.queued.length === 1 ? '' : 's'} queued · ${requests}. Worker completion has not been observed.`);
      } else {
        setNotice(''); setError(`Unexpected dispatch response: ${result.status || 'missing status'}`);
      }
    }
    catch (e) { if (sameScope(activeSlug, operationGeneration)) setError(errText(e)); }
  };
  const viewGeneration = generation.current;
  return <section className="nerva-kanban" aria-label="Kanban">
    <div className="kb-header">
      <div><span className="kb-eyebrow">NERVA · KANBAN</span><h2>Kanban</h2></div>
      <BoardSwitcher boards={boards?.boards || []} current={activeSlug} projects={projects} onSwitch={setSlug} onRefresh={refresh} onError={setError} />
      <button type="button" onClick={() => setAddStatus('triage')}>New task</button>
    </div>
    {error && <div className="kb-alert" role="alert">{error}<button type="button" aria-label="Dismiss error" onClick={() => setError('')}>×</button></div>}
    {notice && <div className="kb-notice" role="status">{notice}</div>}
    <BoardCanvas board={board} meta={activeMeta} profiles={profiles} orchestration={orchestration} auxiliaryError={auxiliaryError} selected={selected} onSelect={setSelected} onOpen={setOpenId} onAdd={setAddStatus} onMove={onMove} onDelete={onDelete} onBulk={onBulk} onBulkDelete={onBulkDelete} onDispatch={onDispatch} archived={archived} onArchived={setArchived} />
    {addStatus && <NewTaskDialog target={addStatus} board={activeMeta} slug={activeSlug} profiles={profiles} orchestration={orchestration} parents={allTasks} onClose={() => { if (sameScope(activeSlug, viewGeneration)) setAddStatus(null); }} onCreated={async () => { if (sameScope(activeSlug, viewGeneration)) { setAddStatus(null); await loadBoard(activeSlug); } }} />}
    {openId && <TaskDrawer slug={activeSlug} id={openId} columns={columns} profiles={profiles} onOpen={id => { if (sameScope(activeSlug, viewGeneration)) setOpenId(id); }} onClose={() => { if (sameScope(activeSlug, viewGeneration)) setOpenId(current => current === openId ? null : current); }} onChanged={() => sameScope(activeSlug, viewGeneration) ? loadBoard(activeSlug) : undefined} />}
  </section>;
}
export default KanbanView;
