import { useEffect, useMemo, useState, type DragEvent, type FormEvent } from 'react';
import { createTask, patchTask } from './api';
import { columnHelp, columnLabel, useKanban } from './i18n';
import { columnMeta, type BoardMeta, type KanbanBoard, type KanbanProfile, type KanbanTask, type OrchestrationSettings } from './types';
import { errText, isLockedTarget } from './KanbanView';

export const shortId = (id: string) => id.replace(/^t_/, '').slice(0, 6);
export const ago = (seconds?: number | null): string => {
  if (!seconds) return '';
  const elapsed = Math.max(0, Math.floor(Date.now() / 1000 - seconds));
  if (elapsed < 60) return `${elapsed}s ago`;
  if (elapsed < 3600) return `${Math.floor(elapsed / 60)}m ago`;
  if (elapsed < 86400) return `${Math.floor(elapsed / 3600)}h ago`;
  return `${Math.floor(elapsed / 86400)}d ago`;
};
export function arcState(task: KanbanTask, fallbackAssignee = ''): 'running' | 'stale' | 'queued' | null {
  if (task.status === 'running') {
    return task.last_heartbeat_at && Date.now() / 1000 - task.last_heartbeat_at > 120 ? 'stale' : 'running';
  }
  if (task.status === 'triage' || task.status === 'review' || (task.status === 'ready' && (task.assignee || fallbackAssignee))) return 'queued';
  return null;
}
function RunClock({ task }: { task: KanbanTask }) {
  const k = useKanban();
  const [, tick] = useState(0);
  useEffect(() => { const timer = setInterval(() => tick(v => v + 1), 1000); return () => clearInterval(timer); }, []);
  const start = task.current_run_started_at ?? task.started_at;
  if (!start) return null;
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - start));
  const elapsed = seconds < 60 ? `${seconds}s` : seconds < 3600 ? `${Math.floor(seconds / 60)}m ${seconds % 60}s` : `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m`;
  return <span className="kb-running-clock">{k.working} · {elapsed}</span>;
}
function Card({ task, selected, onOpen, onSelect, onDelete, onMove, columns, fallbackAssignee }: {
  task: KanbanTask; selected: boolean; onOpen: (id: string) => void; onSelect: (id: string) => void;
  onDelete: (id: string) => void; onMove: (id: string, status: string) => void; columns: string[]; fallbackAssignee: string;
}) {
  const k = useKanban();
  const [menu, setMenu] = useState(false);
  const [dragging, setDragging] = useState(false);
  const arc = arcState(task, fallbackAssignee);
  const attached = task.assignee || (task.status === 'ready' ? fallbackAssignee : '');
  const summary = task.latest_summary || task.body;
  return <article className={`kb-card${selected ? ' kb-card--selected' : ''}${dragging ? ' kb-card--dragging' : ''}`} style={{ borderLeftColor: columnMeta(task.status).tone }} draggable
    onDragStart={e => { e.dataTransfer.setData('text/plain', task.id); e.dataTransfer.effectAllowed = 'move'; setDragging(true); }} onDragEnd={() => setDragging(false)}
    onClick={e => (e.metaKey || e.ctrlKey) ? onSelect(task.id) : onOpen(task.id)}
    onContextMenu={e => { e.preventDefault(); setMenu(v => !v); }} tabIndex={0}
    onKeyDown={e => { if (e.key === 'Enter') onOpen(task.id); if (e.key === ' ') { e.preventDefault(); onSelect(task.id); } }}>
    {arc === 'running' || arc === 'stale' ? <span className={`kb-arc kb-arc--${arc}`} aria-label={arc === 'stale' ? k.noHeartbeat : k.arcRunning} /> : null}
    <div className="kb-card-title">{task.title || task.id}</div>
    {summary && <div className="kb-card-summary">{summary}</div>}
    <div className="kb-card-meta">
      {task.assignee && <span className="kb-avatar" title={task.assignee}>{task.assignee.slice(0, 1).toUpperCase()}</span>}
      {arc === 'queued' && attached && <span title={k.attachedTip(attached)}>{task.assignee ? attached : `→ ${attached}`}</span>}
      {arc === 'running' && <RunClock task={task} />}
      {task.status === 'ready' && !attached && <span className="kb-warning">{k.wontRun}</span>}
      {typeof task.priority === 'number' && task.priority > 0 && <span title={k.priority}>↑{task.priority}</span>}
      {!!task.progress?.total && <span>{task.progress.done}/{task.progress.total}</span>}
      {!!task.comment_count && <span>◌ {task.comment_count}</span>}
      {!!task.warnings?.count && <span className="kb-warning">⚠ {task.warnings.count}</span>}
      <span className="kb-card-age">{ago(task.created_at)}</span><span className="kb-id">{shortId(task.id)}</span>
    </div>
    {menu && <div className="kb-card-menu" onClick={e => e.stopPropagation()}>
      <button type="button" onClick={() => { setMenu(false); onOpen(task.id); }}>{k.open}</button>
      <button type="button" onClick={() => { setMenu(false); onSelect(task.id); }}>{selected ? k.deselect : k.select('⌘/Ctrl')}</button>
      {columns.filter(c => c !== task.status && !isLockedTarget(c)).map(c => <button key={c} type="button" onClick={() => { setMenu(false); onMove(task.id, c); }}>{k.moveTo(columnLabel(k, c))}</button>)}
      <button type="button" onClick={() => { setMenu(false); onDelete(task.id); }}>{k.delete}</button>
    </div>}
  </article>;
}
function Column({ name, tasks, columns, selected, collapsed, onToggle, onAdd, onOpen, onSelect, onMove, onDelete, fallbackAssignee }: {
  name: string; tasks: KanbanTask[]; columns: string[]; selected: Set<string>; collapsed: boolean; onToggle: () => void;
  onAdd: (status: string) => void; onOpen: (id: string) => void; onSelect: (id: string) => void; onMove: (id: string, status: string) => void; onDelete: (id: string) => void; fallbackAssignee: string;
}) {
  const k = useKanban(); const [over, setOver] = useState(false);
  const label = columnLabel(k, name); const tone = columnMeta(name).tone; const locked = isLockedTarget(name);
  const dragHandlers = { onDragOver: (e: DragEvent<HTMLElement>) => { if (locked) { e.dataTransfer.dropEffect = 'none'; return; } e.preventDefault(); e.dataTransfer.dropEffect = 'move'; setOver(true); },
    onDragLeave: () => setOver(false), onDrop: (e: DragEvent<HTMLElement>) => { e.preventDefault(); setOver(false); if (!locked) { const id = e.dataTransfer.getData('text/plain'); if (id) onMove(id, name); } } };
  if (collapsed) return <div className={`kb-lane kb-lane--collapsed${over ? ' kb-lane--over' : ''}`} data-testid={`lane-${name}`} {...dragHandlers}>
    <button type="button" aria-label={k.expand(label)} onClick={onToggle}><span style={{ background: tone }} className="kb-dot" />{label} <small>{tasks.length}</small></button>
  </div>;
  return <section className={`kb-lane${over ? ' kb-lane--over' : ''}`} data-testid={`lane-${name}`} {...dragHandlers}>
    <div className="kb-lane-header"><span className="kb-dot" style={{ background: tone }} /><button type="button" title={columnHelp(k, name)} onClick={onToggle} aria-label={k.collapse(label)}>{label} <small>{tasks.length}</small></button>
      {!locked && <button type="button" aria-label={`New task in ${label}`} onClick={() => onAdd(name)}>＋</button>}</div>
    <div className="kb-lane-cards">{tasks.length ? tasks.map(task => <Card key={task.id} task={task} selected={selected.has(task.id)} onOpen={onOpen} onSelect={onSelect} onDelete={onDelete} onMove={onMove} columns={columns} fallbackAssignee={fallbackAssignee} />) : <span className="kb-empty">{k.empty}</span>}</div>
  </section>;
}
export function BoardCanvas({ board, meta, profiles, orchestration, auxiliaryError, selected, onSelect, onOpen, onAdd, onMove, onDelete, onBulk, onBulkDelete, onDispatch, archived, onArchived }: {
  board: KanbanBoard | null; meta?: BoardMeta; profiles: KanbanProfile[]; orchestration: OrchestrationSettings | null; auxiliaryError: string;
  selected: Set<string>; onSelect: (ids: Set<string>) => void; onOpen: (id: string) => void; onAdd: (status: string) => void;
  onMove: (id: string, status: string) => void; onDelete: (id: string) => void; onBulk: (patch: Record<string, unknown>) => void; onBulkDelete: () => void; onDispatch: () => void;
  archived: boolean; onArchived: (v: boolean) => void;
}) {
  const k = useKanban();
  const [search, setSearch] = useState(''); const [assignee, setAssignee] = useState(''); const [tenant, setTenant] = useState('');
  const [groupRunning, setGroupRunning] = useState(false); const [showFilters, setShowFilters] = useState(false); const [showOrchestration, setShowOrchestration] = useState(false);
  const [introDismissed, setIntroDismissed] = useState(() => { try { return localStorage.getItem('nerva.kanban.intro') === 'dismissed'; } catch { return false; } });
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(() => { try { return JSON.parse(localStorage.getItem('nerva.kanban.collapsed') || '{}'); } catch { return {}; } });
  const names = board?.columns.map(c => c.name) || [];
  const filtered = useMemo(() => board?.columns.map(c => ({ ...c, tasks: c.tasks.filter(t => {
    const q = search.trim().toLowerCase();
    return (!q || [t.title, t.body, t.id].some(v => v?.toLowerCase().includes(q))) && (!assignee || t.assignee === assignee) && (!tenant || t.tenant === tenant);
  }) })) || [], [board, search, assignee, tenant]);
  const select = (id: string) => { const next = new Set(selected); if (!next.delete(id)) next.add(id); onSelect(next); };
  useEffect(() => { if (!board) return; const alive = new Set(board.columns.flatMap(c => c.tasks.map(t => t.id))); if ([...selected].some(id => !alive.has(id))) onSelect(new Set([...selected].filter(id => alive.has(id)))); }, [board]);
  useEffect(() => { const key = (e: KeyboardEvent) => { if (e.key === 'Escape' && selected.size) onSelect(new Set()); }; window.addEventListener('keydown', key); return () => window.removeEventListener('keydown', key); }, [selected]);
  const toggleCollapse = (name: string) => { const next = { ...collapsed, [name]: !(collapsed[name] ?? (filtered.find(c => c.name === name)?.tasks.length === 0)) }; setCollapsed(next); try { localStorage.setItem('nerva.kanban.collapsed', JSON.stringify(next)); } catch { /* storage disabled */ } };
  return <>
    <div className="kb-toolbar"><span title={k.countTip(board?.columns.find(c => c.name === 'running')?.tasks.length || 0, board?.columns.find(c => c.name === 'ready')?.tasks.length || 0)}>{board?.columns.reduce((n, c) => n + c.tasks.length, 0) || 0} tasks</span>
      <input aria-label="Search tasks" placeholder={k.filterCards} value={search} onChange={e => setSearch(e.target.value)} />
      <button type="button" onClick={() => setShowFilters(v => !v)}>{k.filters}</button>
      <button type="button" onClick={() => setShowOrchestration(v => !v)}>Orchestration</button>
      <button type="button" onClick={onDispatch}>Request dispatch</button>
    </div>
    {showFilters && <div className="kb-filters">
      <label>Assignee <select value={assignee} onChange={e => setAssignee(e.target.value)}><option value="">{k.allProfiles}</option>{board?.assignees.map(a => <option key={a}>{a}</option>)}</select></label>
      <label>Tenant <select value={tenant} onChange={e => setTenant(e.target.value)}><option value="">{k.allTenants}</option>{board?.tenants.map(t => <option key={t}>{t}</option>)}</select></label>
      <label><input type="checkbox" checked={archived} onChange={e => onArchived(e.target.checked)} />{k.showArchived}</label>
      <label><input type="checkbox" checked={groupRunning} onChange={e => setGroupRunning(e.target.checked)} />{k.groupRunning}</label>
    </div>}
    {showOrchestration && <div className="kb-orchestration" aria-label="Orchestration settings"><h3>Orchestration settings</h3><p className="kb-muted">{auxiliaryError || 'Configuration changes require a Nerva adapter.'}</p><label>Orchestrator profile<select disabled value={orchestration?.orchestrator_profile || ''} onChange={() => {}}><option value={orchestration?.orchestrator_profile || ''}>{orchestration?.resolved_orchestrator_profile || 'Unavailable'}</option></select></label><label>Default assignee<select disabled value={orchestration?.default_assignee || ''} onChange={() => {}}><option value={orchestration?.default_assignee || ''}>{orchestration?.resolved_default_assignee || 'Unavailable'}</option></select></label><label><input type="checkbox" aria-label="Auto decompose" checked={Boolean(orchestration?.auto_decompose)} disabled />Auto decompose</label><h4>Profile descriptions</h4>{profiles.length ? profiles.map(p => <label key={p.name}>{p.name}<input disabled value={p.description || ''} readOnly /></label>) : <span className="kb-muted">Profile adapter unavailable</span>}</div>}
    {auxiliaryError && !showOrchestration && <div className="kb-muted" role="status">Orchestration/profile options unavailable: {auxiliaryError}</div>}
    {board && !introDismissed && <div className="kb-intro"><p>{k.introBody}</p><button type="button" onClick={() => { setIntroDismissed(true); try { localStorage.setItem('nerva.kanban.intro', 'dismissed'); } catch { /* storage disabled */ } }}>{k.introGotIt}</button></div>}
    {!board ? <div className="kb-loading" role="status">Loading Kanban board…</div> : <div className="kb-lanes" aria-label="Kanban board">
      {filtered.map(c => groupRunning && c.name === 'running' && c.tasks.length ? <div className="kb-running-groups" key={c.name}>{[...new Set(c.tasks.map(t => t.assignee || k.unassigned))].sort().map(name => <div key={name}><h4 className="kb-profile-heading">{name}</h4><Column name={c.name} tasks={c.tasks.filter(t => (t.assignee || k.unassigned) === name)} columns={names} selected={selected} collapsed={false} onToggle={() => setGroupRunning(false)} onAdd={onAdd} onOpen={onOpen} onSelect={select} onMove={onMove} onDelete={onDelete} fallbackAssignee={orchestration?.resolved_default_assignee || ''} /></div>)}</div> :
        <Column key={c.name} name={c.name} tasks={c.tasks} columns={names} selected={selected} collapsed={collapsed[c.name] ?? (board.columns.some(col => col.tasks.length > 0) && c.tasks.length === 0)} onToggle={() => toggleCollapse(c.name)} onAdd={onAdd} onOpen={onOpen} onSelect={select} onMove={onMove} onDelete={onDelete} fallbackAssignee={orchestration?.resolved_default_assignee || ''} />)}
    </div>}
    {selected.size > 0 && <div className="kb-selection" role="toolbar" aria-label="Selected tasks"><strong>{k.nSelected(selected.size)}</strong>
      <select aria-label="Move selected" defaultValue="" onChange={e => { if (e.target.value) onBulk({status: e.target.value}); }}><option value="">{k.moveToShort}</option>{names.filter(n => !isLockedTarget(n)).map(n => <option key={n} value={n}>{columnLabel(k, n)}</option>)}</select>
      <select aria-label="Assign selected" defaultValue="" onChange={e => onBulk({assignee: e.target.value === '__unassign__' ? '' : e.target.value})}><option value="">{k.assign}</option>{profiles.map(p => <option key={p.name}>{p.name}</option>)}<option value="__unassign__">{k.unassignAction}</option></select>
      <button type="button" onClick={() => onBulk({archive: true})}>{k.archive}</button><button type="button" aria-label="Delete selected" onClick={onBulkDelete}>{k.delete}</button><button type="button" aria-label={k.clearSelection} onClick={() => onSelect(new Set())}>×</button>
    </div>}
    {meta?.default_workdir && <div className="kb-board-workspace">Board workspace: {meta.default_workdir}</div>}
    {orchestration && <div className="kb-board-workspace">Default assignee: {orchestration.resolved_default_assignee || 'none'}</div>}
  </>;
}

export function NewTaskDialog({ target, board, slug, profiles, orchestration, parents, onClose, onCreated }: {
  target: string; board?: BoardMeta; slug: string; profiles: KanbanProfile[]; orchestration: OrchestrationSettings | null; parents: KanbanTask[];
  onClose: () => void; onCreated: () => void;
}) {
  const k = useKanban();
  const [title, setTitle] = useState(''); const [body, setBody] = useState(''); const [priority, setPriority] = useState('0');
  const [workspaceKind, setWorkspaceKind] = useState(board?.default_workspace_kind || 'scratch'); const [workspacePath, setWorkspacePath] = useState('');
  const [assignee, setAssignee] = useState(''); const [skills, setSkills] = useState(''); const [parent, setParent] = useState('');
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const submit = async (event: FormEvent) => {
    event.preventDefault(); if (!title.trim() || busy) return; setBusy(true); setError('');
    try {
      const result = await createTask(slug, { title: title.trim(), body: body.trim() || undefined, priority: Number(priority) || 0,
        triage: target === 'triage', assignee: assignee === '__parked__' ? undefined : assignee || orchestration?.resolved_default_assignee || undefined,
        parents: parent ? [parent] : undefined, skills: skills.split(',').map(s => s.trim()).filter(Boolean),
        workspace_kind: workspaceKind, workspace_path: workspaceKind !== 'scratch' && workspacePath.trim() ? workspacePath.trim() : undefined,
      });
      if (result.task && result.task.status !== target) await patchTask(slug, result.task.id, {status: target});
      onCreated();
    } catch (e) { setError(errText(e)); setBusy(false); }
  };
  return <div className="kb-overlay" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}><div role="dialog" aria-modal="true" aria-label="New task" className="kb-dialog kb-task-create">
    <header><h3>{k.newTaskIn(columnLabel(k, target))}</h3><button type="button" aria-label={k.close} onClick={onClose}>×</button></header>
    <form onSubmit={submit}>
      <label>Title<input autoFocus required value={title} onChange={e => setTitle(e.target.value)} placeholder={target === 'triage' ? k.titlePlaceholderTriage : k.titlePlaceholder} /></label>
      <label>Description<textarea value={body} onChange={e => setBody(e.target.value)} placeholder={k.descPlaceholder} /></label>
      <div className="kb-grid-two"><label>Priority<input type="number" value={priority} onChange={e => setPriority(e.target.value)} /></label>
      <label>Workspace<select value={workspaceKind} onChange={e => setWorkspaceKind(e.target.value)}><option value="scratch">scratch</option><option value="dir">dir</option><option value="worktree">worktree</option></select></label></div>
      {workspaceKind !== 'scratch' && <label>Workspace override<input value={workspacePath} onChange={e => setWorkspacePath(e.target.value)} placeholder={board?.default_workdir || k.workspaceInherit} /></label>}
      <label>Assignee<select value={assignee} onChange={e => setAssignee(e.target.value)}><option value="">Default {orchestration?.resolved_default_assignee || 'assignee'}</option>{profiles.map(p => <option key={p.name} value={p.name}>{p.name}</option>)}<option value="__parked__">Park unassigned</option></select></label>
      <label>Skills<input value={skills} onChange={e => setSkills(e.target.value)} placeholder={k.skillsPlaceholder} /></label>
      {parents.length > 0 && <label>Parent<select value={parent} onChange={e => setParent(e.target.value)}><option value="">{k.noParent}</option>{parents.map(p => <option key={p.id} value={p.id}>{p.title}</option>)}</select></label>}
      <details><summary>Model overrides · unavailable</summary><p className="kb-muted">Provider and model inventory require a Nerva adapter. Existing task overrides remain visible in task details.</p></details>
      <label className="kb-disabled"><input type="checkbox" disabled />Goal mode — adapter unavailable</label>
      {error && <div role="alert" className="kb-alert">{error}</div>}
      <footer><button type="button" onClick={onClose}>{k.cancel}</button><button type="submit" disabled={!title.trim() || busy}>{busy ? k.creating : k.createTask}</button></footer>
    </form>
  </div></div>;
}
