import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Markdown } from '../../markdown';
import { addComment, deleteTask, downloadAttachment, fetchLog, fetchTask, patchTask, uploadAttachment } from './api';
import { ago, shortId } from './board';
import { columnLabel, useKanban } from './i18n';
import { SEVERITY_TONE, type KanbanAttachment, type KanbanEvent, type KanbanProfile, type KanbanTaskDetail } from './types';
import { errText, isLockedTarget } from './KanbanView';

type Tab = 'comments' | 'activity' | 'runs' | 'log';
function eventText(event: KanbanEvent): string {
  let data: Record<string, unknown> = {};
  if (typeof event.payload === 'string') { try { data = JSON.parse(event.payload); } catch { return `${event.kind.replace(/_/g, ' ')} · ${event.payload}`; } }
  else if (event.payload && typeof event.payload === 'object') data = event.payload as Record<string, unknown>;
  const str = (name: string) => typeof data[name] === 'string' ? data[name] as string : '';
  switch (event.kind) {
    case 'created': return `Created${str('status') ? ` in ${str('status')}` : ''}`;
    case 'status': return `Moved to ${str('status') || '?'}` + (str('reason') ? ` · ${str('reason')}` : '');
    case 'assigned': return str('assignee') ? `Assigned to ${str('assignee')}` : 'Unassigned';
    case 'commented': return `Commented by ${str('author') || 'someone'}`;
    case 'claimed': return 'Worker claimed task';
    case 'spawned': return `Worker started${data.pid ? ` · pid ${data.pid}` : ''}`;
    case 'completed': return 'Completed';
    case 'blocked': return `Blocked${str('reason') ? ` · ${str('reason')}` : ''}`;
    case 'unblocked': return `Unblocked${str('status') ? ` → ${str('status')}` : ''}`;
    case 'reclaimed': return `Reclaimed${str('reason') ? ` · ${str('reason')}` : ''}`;
    case 'specified': return 'Specified';
    case 'promoted': return 'Promoted';
    case 'scheduled': return `Scheduled${str('reason') ? ` · ${str('reason')}` : ''}`;
    case 'archived': return 'Archived';
    case 'reprioritized': return `Priority changed to ${data.priority ?? '?'}`;
    default: return [event.kind.replace(/_/g, ' '), ...Object.entries(data).filter(([, v]) => v != null && typeof v !== 'object').map(([key, v]) => `${key}=${String(v)}`)].join(' · ');
  }
}
function Section({ title, children }: { title: string; children: React.ReactNode }) { return <section className="kb-section"><h4>{title}</h4>{children}</section>; }
function AttachmentList({ slug, taskId, attachments, onUpload, pending, onError }: {
  slug: string; taskId: string; attachments: KanbanAttachment[]; onUpload: (file: File) => void; pending: boolean; onError: (v: string) => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const download = async (attachment: KanbanAttachment) => {
    try {
      const id = Number(attachment.id);
      const blob = await downloadAttachment(slug, id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = attachment.filename; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (e) { onError(errText(e)); }
  };
  return <Section title="Attachments"><ul className="kb-attachments">{attachments.map(a => <li key={a.id}><button type="button" aria-label={`Download ${a.filename}`} onClick={() => void download(a)}>{a.filename}</button>{typeof a.size === 'number' && <small> · {a.size} B</small>}</li>)}</ul>
    <label>Upload attachment<input ref={fileRef} aria-label="Upload attachment" type="file" disabled={pending} onChange={e => { const file = e.target.files?.[0]; if (file) onUpload(file); if (fileRef.current) fileRef.current.value = ''; }} /></label>
  </Section>;
}
export function TaskDrawer({ slug, id, columns, profiles, onOpen, onClose, onChanged }: {
  slug: string; id: string; columns: string[]; profiles: KanbanProfile[]; onOpen: (id: string) => void; onClose: () => void; onChanged: () => Promise<unknown> | void;
}) {
  const k = useKanban();
  const [detail, setDetail] = useState<KanbanTaskDetail | null>(null);
  const [error, setError] = useState(''); const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<Tab>('comments'); const [comment, setComment] = useState(''); const [busy, setBusy] = useState(false);
  const [log, setLog] = useState(''); const [logError, setLogError] = useState('');
  const [editBody, setEditBody] = useState(false); const [bodyDraft, setBodyDraft] = useState('');
  const [actions, setActions] = useState(false);
  const serial = useRef(0);
  const load = async () => {
    const request = ++serial.current; setLoading(true);
    try { const next = await fetchTask(slug, id); if (request === serial.current) { setDetail(next); setBodyDraft(next.task.body || ''); setError(''); } }
    catch (e) { if (request === serial.current) setError(errText(e)); }
    finally { if (request === serial.current) setLoading(false); }
  };
  useEffect(() => {
    void load();
    let live = true;
    fetchLog(slug, id).then(r => { if (live) setLog(r.content || ''); }).catch(e => { if (live) setLogError(errText(e)); });
    const poll = setInterval(() => { void load(); }, 30_000);
    return () => { live = false; serial.current++; clearInterval(poll); };
  }, [slug, id]);
  const task = detail?.task;
  const mutate = async (fn: () => Promise<unknown>, after?: () => void) => {
    setBusy(true); setError('');
    try { await fn(); await Promise.all([load(), Promise.resolve(onChanged())]); after?.(); }
    catch (e) { setError(errText(e)); }
    finally { setBusy(false); }
  };
  const patch = async (fields: Record<string, unknown>): Promise<boolean> => {
    if (!detail) return false;
    const previous = detail;
    setDetail({ ...detail, task: { ...detail.task, ...fields } });
    setBusy(true); setError('');
    try { await patchTask(slug, id, fields); await Promise.all([load(), Promise.resolve(onChanged())]); return true; }
    catch (e) { setDetail(previous); setError(errText(e)); return false; }
    finally { setBusy(false); }
  };
  const postComment = (e: FormEvent) => { e.preventDefault(); if (!comment.trim()) return; const value = comment.trim(); void mutate(() => addComment(slug, id, value), () => setComment('')); };
  const upload = (file: File) => void mutate(() => uploadAttachment(slug, id, file));
  const links = new Map((detail?.link_tasks || []).map(t => [t.id, t.title]));
  return <div className="kb-overlay" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}><div className="kb-dialog kb-drawer" role="dialog" aria-modal="true" aria-label="Task details">
    <header><div><span className="kb-eyebrow">{task ? columnLabel(k, task.status) : shortId(id)} · {shortId(id)}</span><h3>{task?.title || id}</h3></div><button type="button" aria-label="Close task" onClick={onClose}>×</button></header>
    {error && <div className="kb-alert" role="alert">{error}</div>}
    {loading && !detail && <div className="kb-loading">Loading task…</div>}
    {detail && task && <div className="kb-drawer-body">
      <main className="kb-drawer-main">
        {task.status === 'ready' && !task.assignee && <div className="kb-alert">Ready task is unassigned; it will wait for an available assignee.</div>}
        {!!task.diagnostics?.length && <Section title={`Diagnostics · ${task.diagnostics.length}`}>{task.diagnostics.map((d, i) => <article className="kb-diagnostic" key={`${d.kind}-${i}`} style={{borderLeft:`3px solid ${SEVERITY_TONE[d.severity]}`}}><strong>{d.title}</strong><p>{d.detail}</p>{d.actions.map((a,j) => <button key={j} type="button" disabled title="Recovery action requires a Nerva adapter">{a.label} · unavailable</button>)}</article>)}</Section>}
        <Section title="Description">{editBody ? <form onSubmit={e => { e.preventDefault(); void patch({body: bodyDraft}).then(ok => { if (ok) setEditBody(false); }); }}><textarea aria-label="Edit description" value={bodyDraft} onChange={e => setBodyDraft(e.target.value)} /><footer><button type="button" onClick={() => setEditBody(false)}>Cancel</button><button type="submit" disabled={busy}>Save description</button></footer></form> : <><div className="kb-markdown">{task.body ? <Markdown text={task.body} className="md" /> : <span className="kb-muted">No description</span>}</div><button type="button" onClick={() => setEditBody(true)}>Edit description</button></>}</Section>
        {task.result && <Section title="Result"><Markdown text={task.result} className="md kb-markdown" /></Section>}
        {task.latest_summary && <Section title="Latest summary"><Markdown text={task.latest_summary} className="md kb-markdown" /></Section>}
        <Section title="Activity"><div className="kb-tabs" role="tablist">{(['comments','activity','runs','log'] as const).map(x => <button type="button" role="tab" aria-selected={tab === x} key={x} onClick={() => setTab(x)}>{x === 'runs' ? 'Run history' : x[0].toUpperCase() + x.slice(1)}</button>)}</div>
          {tab === 'comments' && <><div className="kb-feed">{detail.comments.map(c => <article key={c.id}><strong>{c.author}</strong> <time>{ago(c.created_at)}</time><Markdown text={c.body} className="md kb-markdown" /></article>)}</div><form onSubmit={postComment}><label>Comment<textarea value={comment} onChange={e => setComment(e.target.value)} /></label><footer><button type="submit" disabled={busy || !comment.trim()}>Post comment</button></footer></form></>}
          {tab === 'activity' && <div className="kb-feed">{detail.events.map(e => <article key={e.id}>{eventText(e)} <time>{ago(e.created_at)}</time></article>)}</div>}
          {tab === 'runs' && <div className="kb-feed">{detail.runs.length ? detail.runs.map(r => <article key={r.id}><strong>{r.profile || 'Worker'} · {r.status}</strong> {r.outcome && <span>{r.outcome}</span>}{r.summary && <p>{r.summary}</p>}{r.error && <p className="kb-warning">{r.error}</p>}</article>) : <span className="kb-muted">No runs recorded</span>}</div>}
          {tab === 'log' && <div className="kb-feed">{logError ? <span className="kb-muted">{logError}</span> : log ? <pre>{log}</pre> : <span className="kb-muted">No worker log</span>}</div>}
        </Section>
      </main>
      <aside className="kb-drawer-aside">
        <Section title="Status"><label>Status<select aria-label="Status" value={task.status} disabled={busy} onChange={e => { if (isLockedTarget(e.target.value)) { setError('That lane is managed by the worker workflow.'); return; } void patch({status:e.target.value}); }}>{columns.map(c => <option key={c} value={c} disabled={isLockedTarget(c) && c !== task.status}>{columnLabel(k,c)}</option>)}</select></label></Section>
        <Section title="Assignee"><div>{task.assignee || 'Unassigned'}</div><select aria-label="Assign profile" value={task.assignee || ''} disabled title="Reassignment requires a Nerva adapter"><option value="">Unassigned</option>{profiles.map(p => <option key={p.name}>{p.name}</option>)}</select></Section>
        <Section title="Priority"><label>Priority<input aria-label="Task priority" type="number" defaultValue={task.priority || 0} onBlur={e => { const n = Number(e.target.value); if (n !== task.priority) void patch({priority:n}); }} /></label></Section>
        {task.tenant && <Section title="Tenant">{task.tenant}</Section>}
        {task.workspace_path && <Section title="Workspace"><span className="kb-chip">{task.workspace_kind || 'dir'}</span><p className="kb-path">{task.workspace_path}</p><button type="button" onClick={() => void navigator.clipboard?.writeText(task.workspace_path || '')}>Copy path</button></Section>}
        <Section title="Model">{task.model_override || 'Inherit profile'}{task.provider_override && <div>Provider: {task.provider_override}</div>}<button type="button" disabled title="Model option inventory requires a Nerva adapter">Change model · unavailable</button></Section>
        {(detail.links.parents.length > 0 || detail.links.children.length > 0) && <Section title="Dependencies">{(['parents','children'] as const).map(side => detail.links[side].length ? <div key={side}><strong>{side === 'parents' ? 'Blocked by' : 'Blocks'}</strong><div>{detail.links[side].map(link => <button type="button" key={link} onClick={() => onOpen(link)}>{links.get(link) || shortId(link)}</button>)}</div></div> : null)}</Section>}
        <Section title="Task metadata"><div>Created by: {task.created_by || 'unknown'}</div><div>Created: {ago(task.created_at)}</div>{task.worker_pid && <div>Worker pid: {task.worker_pid}</div>}</Section>
        <Section title="Worker controls"><button type="button" disabled>Reclaim · unavailable</button><button type="button" disabled>Reassign · unavailable</button><button type="button" disabled>Estimate · unavailable</button></Section>
        {Array.isArray(detail.attachments) && <AttachmentList slug={slug} taskId={id} attachments={detail.attachments} onUpload={upload} pending={busy} onError={setError} />}
        <Section title="Actions"><button type="button" onClick={() => setActions(v => !v)}>Task actions</button>{actions && <div><button type="button" onClick={() => void patch({status:'archived'})}>Archive</button><button type="button" onClick={() => { if (window.confirm('Delete this task?')) void mutate(() => deleteTask(slug,id), onClose); }}>Delete</button></div>}</Section>
      </aside>
    </div>}
  </div></div>;
}
