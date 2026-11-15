import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { Markdown } from '../../markdown';
import * as api from './api';
import { ago, shortId } from './board';
import { columnLabel, useKanban } from './i18n';
import {
  SEVERITY_TONE,
  type DiagnosticAction,
  type HomeChannelsResponse,
  type KanbanAssignee,
  type KanbanAttachment,
  type KanbanEvent,
  type KanbanModelOptionsResponse,
  type KanbanProfile,
  type KanbanRunDetail,
  type KanbanTask,
  type KanbanTaskDetail,
  type RunProcessInspection,
  type TaskEstimate,
} from './types';
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
function AttachmentList({ slug, attachments, onUpload, pending, onError }: {
  slug: string; taskId: string; attachments: KanbanAttachment[]; onUpload: (file: File) => void; pending: boolean; onError: (v: string) => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const download = async (attachment: KanbanAttachment) => {
    try {
      const id = Number(attachment.id);
      const blob = await api.downloadAttachment(slug, id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = attachment.filename; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (e) { onError(errText(e)); }
  };
  return <Section title="Attachments"><ul className="kb-attachments">{attachments.map(a => <li key={a.id}><button type="button" aria-label={`Download ${a.filename}`} onClick={() => void download(a)}>{a.filename}</button>{typeof a.size === 'number' && <small> · {a.size} B</small>}</li>)}</ul>
    <label>Upload attachment<input ref={fileRef} aria-label="Upload attachment" type="file" disabled={pending} onChange={e => { const file = e.target.files?.[0]; if (file) onUpload(file); if (fileRef.current) fileRef.current.value = ''; }} /></label>
  </Section>;
}
export function TaskDrawer({
  slug, id, columns, profiles, knownAssignees = [], allTasks = [], modelOptions = null, modelOptionsError = '',
  onRefreshModelOptions, onOpen, onClose, onChanged,
}: {
  slug: string; id: string; columns: string[]; profiles: KanbanProfile[]; knownAssignees?: KanbanAssignee[];
  allTasks?: KanbanTask[]; modelOptions?: KanbanModelOptionsResponse | null; modelOptionsError?: string;
  onRefreshModelOptions?: () => Promise<void> | void;
  onOpen: (id: string) => void; onClose: () => void; onChanged: () => Promise<unknown> | void;
}) {
  const k = useKanban();
  const [detail, setDetail] = useState<KanbanTaskDetail | null>(null);
  const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<Tab>('comments'); const [comment, setComment] = useState(''); const [busy, setBusy] = useState(false);
  const [log, setLog] = useState(''); const [logError, setLogError] = useState('');
  const [editBody, setEditBody] = useState(false); const [bodyDraft, setBodyDraft] = useState('');
  const [actions, setActions] = useState(false);
  const [reassignTarget, setReassignTarget] = useState('');
  const [reclaimFirst, setReclaimFirst] = useState(false);
  const [workerReason, setWorkerReason] = useState('');
  const [taskEstimate, setTaskEstimate] = useState<TaskEstimate | null>(null);
  const [linkDir, setLinkDir] = useState<'parent' | 'child'>('parent');
  const [linkTarget, setLinkTarget] = useState('');
  const [selectedRun, setSelectedRun] = useState<KanbanRunDetail | null>(null);
  const [runInspection, setRunInspection] = useState<{ runId: number | string; info: RunProcessInspection } | null>(null);
  const [homeChannels, setHomeChannels] = useState<HomeChannelsResponse | null>(null);
  const [channelsNote, setChannelsNote] = useState('');
  const [channelPlatform, setChannelPlatform] = useState('telegram');
  const serial = useRef(0);
  const load = async () => {
    const request = ++serial.current; setLoading(true);
    try {
      const next = await api.fetchTask(slug, id);
      if (request === serial.current) {
        setDetail(next);
        setBodyDraft(next.task.body || '');
        setReassignTarget(next.task.assignee || '');
        setError('');
      }
    }
    catch (e) { if (request === serial.current) setError(errText(e)); }
    finally { if (request === serial.current) setLoading(false); }
  };
  const loadChannels = async (liveCheck?: () => boolean) => {
    if (!('fetchHomeChannels' in api)) return;
    try {
      const next = await api.fetchHomeChannels(slug, id);
      if (!liveCheck || liveCheck()) { setHomeChannels(next); setChannelsNote(''); }
    } catch (e) {
      if (!liveCheck || liveCheck()) setChannelsNote(errText(e));
    }
  };
  useEffect(() => {
    setSelectedRun(null); setRunInspection(null); setTaskEstimate(null); setNotice('');
    void load();
    let live = true;
    api.fetchLog(slug, id).then(r => { if (live) setLog(r.content || ''); }).catch(e => { if (live) setLogError(errText(e)); });
    void loadChannels(() => live);
    const poll = setInterval(() => { void load(); }, 30_000);
    return () => { live = false; serial.current++; clearInterval(poll); };
  }, [slug, id]);
  const task = detail?.task;
  const assigneeOptions = useMemo(() => {
    const seen = new Set<string>();
    for (const p of profiles) if (p.name) seen.add(p.name);
    for (const a of knownAssignees) if (a.name) seen.add(a.name);
    if (task?.assignee) seen.add(task.assignee);
    return [...seen].sort();
  }, [profiles, knownAssignees, task?.assignee]);
  const channelOptions = useMemo(() => {
    const seen = new Set<string>(['telegram', 'discord', 'slack', 'email']);
    for (const ch of homeChannels?.channels || []) if (ch.platform) seen.add(ch.platform);
    return [...seen];
  }, [homeChannels]);
  const mutate = async (fn: () => Promise<unknown>, after?: () => void) => {
    setBusy(true); setError(''); setNotice('');
    try { await fn(); await Promise.all([load(), Promise.resolve(onChanged())]); after?.(); }
    catch (e) { setError(errText(e)); }
    finally { setBusy(false); }
  };
  const patch = async (fields: Record<string, unknown>): Promise<boolean> => {
    if (!detail) return false;
    const previous = detail;
    setDetail({ ...detail, task: { ...detail.task, ...fields } });
    setBusy(true); setError(''); setNotice('');
    try { await api.patchTask(slug, id, fields); await Promise.all([load(), Promise.resolve(onChanged())]); return true; }
    catch (e) { setDetail(previous); setError(errText(e)); return false; }
    finally { setBusy(false); }
  };
  const postComment = (e: FormEvent) => { e.preventDefault(); if (!comment.trim()) return; const value = comment.trim(); void mutate(() => api.addComment(slug, id, value), () => setComment('')); };
  const upload = (file: File) => void mutate(() => api.uploadAttachment(slug, id, file));
  const submitReassign = (profileValue: string, forceReclaim = reclaimFirst) => {
    void mutate(() => api.reassignTask(slug, id, {
      profile: profileValue || null,
      reclaim_first: forceReclaim,
      ...(workerReason.trim() ? { reason: workerReason.trim() } : {}),
    }), () => setNotice(profileValue ? `Reassigned to ${profileValue}.` : 'Task unassigned.'));
  };
  const runTaskEstimate = async () => {
    setBusy(true); setError(''); setNotice('');
    try {
      const res = await api.estimateTask(slug, id);
      if (!res.ok) setError(res.reason || k.couldNotEstimate);
      else setTaskEstimate(res);
    } catch (e) { setError(errText(e)); }
    finally { setBusy(false); }
  };
  const loadRunDetail = async (runId: number | string) => {
    setBusy(true); setError('');
    try {
      const res = await api.fetchRun(slug, runId);
      setSelectedRun(res.run);
    } catch (e) { setError(errText(e)); }
    finally { setBusy(false); }
  };
  const loadRunInspection = async (runId: number | string) => {
    setBusy(true); setError('');
    try {
      const info = await api.inspectRun(slug, runId);
      setRunInspection({ runId, info });
    } catch (e) { setError(errText(e)); }
    finally { setBusy(false); }
  };
  const handleDiagnosticAction = (action: DiagnosticAction) => {
    if (action.kind === 'reclaim') {
      void mutate(() => api.reclaimTask(slug, id, workerReason.trim() || undefined));
    } else if (action.kind === 'reassign') {
      submitReassign(reassignTarget, Boolean(action.payload?.reclaim_first));
    } else if (action.kind === 'unblock') {
      void patch({ status: 'ready' });
    } else if (action.kind === 'cli_hint' && typeof action.payload?.command === 'string') {
      void navigator.clipboard?.writeText(action.payload.command);
      setNotice(k.commandCopied);
    }
  };
  const submitLink = (e: FormEvent) => {
    e.preventDefault();
    const other = linkTarget.trim();
    if (!other) return;
    const parentId = linkDir === 'parent' ? other : id;
    const childId = linkDir === 'parent' ? id : other;
    void mutate(() => api.addLink(slug, parentId, childId), () => setLinkTarget(''));
  };
  const onSubscribeChannel = async () => {
    setBusy(true); setError(''); setNotice('');
    try {
      await api.subscribeTaskChannel(slug, id, channelPlatform);
      await loadChannels();
      setNotice(`Subscribed ${channelPlatform} notifications.`);
    } catch (e) { setError(errText(e)); }
    finally { setBusy(false); }
  };
  const onUnsubscribeChannel = async () => {
    setBusy(true); setError(''); setNotice('');
    try {
      await api.unsubscribeTaskChannel(slug, id, channelPlatform);
      await loadChannels();
      setNotice(`Unsubscribed ${channelPlatform} notifications.`);
    } catch (e) { setError(errText(e)); }
    finally { setBusy(false); }
  };
  const refreshModels = async () => {
    if (!('fetchModelOptions' in api)) return;
    setBusy(true); setError('');
    try {
      await api.fetchModelOptions();
      await onRefreshModelOptions?.();
    } catch (e) { setError(errText(e)); }
    finally { setBusy(false); }
  };
  const links = new Map((detail?.link_tasks || []).map(t => [t.id, t.title]));
  return <div className="kb-overlay" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}><div className="kb-dialog kb-drawer" role="dialog" aria-modal="true" aria-label="Task details">
    <header><div><span className="kb-eyebrow">{task ? columnLabel(k, task.status) : shortId(id)} · {shortId(id)}</span><h3>{task?.title || id}</h3></div><button type="button" aria-label="Close task" onClick={onClose}>×</button></header>
    {error && <div className="kb-alert" role="alert">{error}</div>}
    {notice && <div className="kb-notice" role="status">{notice}</div>}
    {loading && !detail && <div className="kb-loading">Loading task…</div>}
    {detail && task && <div className="kb-drawer-body">
      <main className="kb-drawer-main">
        {task.status === 'ready' && !task.assignee && <div className="kb-alert">Ready task is unassigned; it will wait for an available assignee.</div>}
        {!!task.diagnostics?.length && <Section title={`Diagnostics · ${task.diagnostics.length}`}>{task.diagnostics.map((d, i) => <article className="kb-diagnostic" key={`${d.kind}-${i}`} style={{borderLeft:`3px solid ${SEVERITY_TONE[d.severity]}`}}><strong>{d.title}</strong><p>{d.detail}</p><div className="kb-inline-actions">{d.actions.map((a, j) => {
          const supported = a.kind === 'reclaim' || a.kind === 'reassign' || a.kind === 'unblock' || a.kind === 'cli_hint';
          return <button key={j} type="button" disabled={busy || !supported} onClick={() => handleDiagnosticAction(a)}>{supported ? a.label : `${a.label} · unavailable`}</button>;
        })}</div></article>)}</Section>}
        <Section title="Description">{editBody ? <form onSubmit={e => { e.preventDefault(); void patch({body: bodyDraft}).then(ok => { if (ok) setEditBody(false); }); }}><textarea aria-label="Edit description" value={bodyDraft} onChange={e => setBodyDraft(e.target.value)} /><footer><button type="button" onClick={() => setEditBody(false)}>Cancel</button><button type="submit" disabled={busy}>Save description</button></footer></form> : <><div className="kb-markdown">{task.body ? <Markdown text={task.body} className="md" /> : <span className="kb-muted">No description</span>}</div><button type="button" onClick={() => setEditBody(true)}>Edit description</button></>}</Section>
        {task.result && <Section title="Result"><Markdown text={task.result} className="md kb-markdown" /></Section>}
        {task.latest_summary && <Section title="Latest summary"><Markdown text={task.latest_summary} className="md kb-markdown" /></Section>}
        <Section title="Activity"><div className="kb-tabs" role="tablist">{(['comments','activity','runs','log'] as const).map(x => <button type="button" role="tab" aria-selected={tab === x} key={x} onClick={() => setTab(x)}>{x === 'runs' ? 'Run history' : x[0].toUpperCase() + x.slice(1)}</button>)}</div>
          {tab === 'comments' && <><div className="kb-feed">{detail.comments.map(c => <article key={c.id}><strong>{c.author}</strong> <time>{ago(c.created_at)}</time><Markdown text={c.body} className="md kb-markdown" /></article>)}</div><form onSubmit={postComment}><label>Comment<textarea value={comment} onChange={e => setComment(e.target.value)} /></label><footer><button type="submit" disabled={busy || !comment.trim()}>Post comment</button></footer></form></>}
          {tab === 'activity' && <div className="kb-feed">{detail.events.map(e => <article key={e.id}>{eventText(e)} <time>{ago(e.created_at)}</time></article>)}</div>}
          {tab === 'runs' && <div className="kb-feed">
            {detail.runs.length ? detail.runs.map(r => <article key={r.id}>
              <strong>{r.profile || 'Worker'} · {r.status}</strong> {r.outcome && <span>{r.outcome}</span>}
              {r.summary && <p>{r.summary}</p>}
              {r.error && <p className="kb-warning">{r.error}</p>}
              <div className="kb-inline-actions">
                <button type="button" disabled={busy} onClick={() => void loadRunDetail(r.id)}>Run details</button>
                <button type="button" disabled={busy} onClick={() => void loadRunInspection(r.id)}>Inspect process</button>
                <button type="button" disabled={busy} onClick={() => void mutate(() => api.terminateRun(slug, r.id, workerReason.trim() || undefined))}>Terminate run</button>
              </div>
              {selectedRun && String(selectedRun.id) === String(r.id) && <div className="kb-run-detail" aria-label={`Run ${r.id} details`}>
                <span>Run #{selectedRun.id}</span>
                {selectedRun.worker_pid != null && <span> · pid {selectedRun.worker_pid}</span>}
                {selectedRun.started_at != null && <span> · started {ago(selectedRun.started_at)}</span>}
                {selectedRun.last_heartbeat_at != null && <span> · heartbeat {ago(selectedRun.last_heartbeat_at)}</span>}
              </div>}
              {runInspection && String(runInspection.runId) === String(r.id) && <div className="kb-run-detail" aria-label={`Run ${r.id} process`}>
                <span>Process: {runInspection.info.state || (runInspection.info.alive ? 'alive' : 'stopped')}</span>
                {runInspection.info.detail && <span> · {runInspection.info.detail}</span>}
              </div>}
            </article>) : <span className="kb-muted">No runs recorded</span>}
          </div>}
          {tab === 'log' && <div className="kb-feed">{logError ? <span className="kb-muted">{logError}</span> : log ? <pre>{log}</pre> : <span className="kb-muted">No worker log</span>}</div>}
        </Section>
      </main>
      <aside className="kb-drawer-aside">
        <Section title="Status"><label>Status<select aria-label="Status" value={task.status} disabled={busy} onChange={e => { if (isLockedTarget(e.target.value)) { setError('That lane is managed by the worker workflow.'); return; } void patch({status:e.target.value}); }}>{columns.map(c => <option key={c} value={c} disabled={isLockedTarget(c) && c !== task.status}>{columnLabel(k,c)}</option>)}</select></label></Section>
        <Section title="Assignee">
          <div>{task.assignee || 'Unassigned'}</div>
          <select aria-label="Assign profile" value={reassignTarget} disabled={busy} onChange={e => { setReassignTarget(e.target.value); submitReassign(e.target.value); }}>
            <option value="">Unassigned</option>
            {assigneeOptions.map(name => <option key={name} value={name}>{name}</option>)}
          </select>
        </Section>
        <Section title="Priority"><label>Priority<input aria-label="Task priority" type="number" defaultValue={task.priority || 0} onBlur={e => { const n = Number(e.target.value); if (n !== task.priority) void patch({priority:n}); }} /></label></Section>
        {task.tenant && <Section title="Tenant">{task.tenant}</Section>}
        {task.workspace_path && <Section title="Workspace"><span className="kb-chip">{task.workspace_kind || 'dir'}</span><p className="kb-path">{task.workspace_path}</p><button type="button" onClick={() => void navigator.clipboard?.writeText(task.workspace_path || '')}>Copy path</button></Section>}
        <Section title="Model">
          <div>{task.model_override || 'Inherit profile'}</div>
          {task.provider_override && <div>Provider: {task.provider_override}</div>}
          {task.reasoning_effort && <div>Effort: {task.reasoning_effort}</div>}
          {modelOptionsError && <div className="kb-muted">{modelOptionsError}</div>}
          {modelOptions?.models?.length ? <select aria-label="Task model override" value={task.model_override || ''} disabled={busy} onChange={e => void patch(e.target.value ? { model_override: e.target.value } : { clear_model_override: true })}>
            <option value="">Inherit profile</option>
            {modelOptions.models.map(m => <option key={m.id} value={m.id}>{m.label || m.id}</option>)}
          </select> : null}
          <div className="kb-inline-actions">
            <button type="button" disabled={busy} onClick={() => void refreshModels()}>Load model options</button>
            {task.model_override && <button type="button" disabled={busy} onClick={() => void patch({ clear_model_override: true })}>{k.modelClear}</button>}
          </div>
        </Section>
        <Section title="Dependencies">
          {(['parents','children'] as const).map(side => detail.links[side].length ? <div key={side}>
            <strong>{side === 'parents' ? 'Blocked by' : 'Blocks'}</strong>
            <div className="kb-inline-actions">{detail.links[side].map(link => <span key={link} className="kb-chip">
              <button type="button" onClick={() => onOpen(link)}>{links.get(link) || shortId(link)}</button>
              <button type="button" aria-label={`Unlink ${link}`} disabled={busy} onClick={() => void mutate(() => api.removeLink(slug, side === 'parents' ? link : id, side === 'parents' ? id : link))}>×</button>
            </span>)}</div>
          </div> : null)}
          <form className="kb-link-form" onSubmit={submitLink}>
            <select aria-label="Dependency direction" value={linkDir} onChange={e => setLinkDir(e.target.value as 'parent' | 'child')}>
              <option value="parent">Blocked by</option>
              <option value="child">Blocks</option>
            </select>
            <input aria-label="Linked task ID" list={`kb-links-${id}`} value={linkTarget} onChange={e => setLinkTarget(e.target.value)} placeholder="Task ID" />
            <datalist id={`kb-links-${id}`}>{allTasks.filter(t => t.id !== id).map(t => <option key={t.id} value={t.id}>{t.title}</option>)}</datalist>
            <button type="submit" disabled={busy || !linkTarget.trim()}>Add link</button>
          </form>
        </Section>
        <Section title="Notifications">
          {channelsNote && <div className="kb-muted">{channelsNote}</div>}
          {!!homeChannels?.subscribed?.length && <div className="kb-muted">Subscribed: {homeChannels.subscribed.join(', ')}</div>}
          <label>Channel
            <select aria-label="Notification channel" value={channelPlatform} onChange={e => setChannelPlatform(e.target.value)}>
              {channelOptions.map(ch => <option key={ch} value={ch}>{ch}</option>)}
            </select>
          </label>
          <div className="kb-inline-actions">
            <button type="button" disabled={busy} onClick={() => void onSubscribeChannel()}>Subscribe channel</button>
            <button type="button" disabled={busy} onClick={() => void onUnsubscribeChannel()}>Unsubscribe channel</button>
          </div>
        </Section>
        <Section title="Task metadata"><div>Created by: {task.created_by || 'unknown'}</div><div>Created: {ago(task.created_at)}</div>{task.worker_pid && <div>Worker pid: {task.worker_pid}</div>}</Section>
        <Section title="Worker controls">
          <input aria-label="Worker action reason" value={workerReason} onChange={e => setWorkerReason(e.target.value)} placeholder="Reason (optional)" />
          {task.status === 'running' && <label><input type="checkbox" checked={reclaimFirst} onChange={e => setReclaimFirst(e.target.checked)} />Reclaim before reassign</label>}
          <div className="kb-inline-actions">
            {task.status === 'running'
              ? <button type="button" disabled={busy} onClick={() => void mutate(() => api.reclaimTask(slug, id, workerReason.trim() || undefined))}>Reclaim</button>
              : <button type="button" disabled title="Only running tasks have an active worker claim">Reclaim · unavailable</button>}
            <button type="button" disabled={busy} onClick={() => submitReassign(reassignTarget)}>Reassign</button>
            <button type="button" disabled={busy} onClick={() => void runTaskEstimate()}>Estimate</button>
            <button type="button" disabled={busy} onClick={() => void mutate(() => api.specifyTask(slug, id))}>Specify</button>
            <button type="button" disabled={busy} onClick={() => void mutate(() => api.decomposeTask(slug, id))}>Decompose</button>
          </div>
          {taskEstimate && <div role="status" className="kb-muted">{taskEstimate.complexity ? `${taskEstimate.complexity} · ` : ''}{typeof taskEstimate.est_tokens === 'number' ? `${taskEstimate.est_tokens} ${k.tokUnit}` : k.roughEstimate}{taskEstimate.rationale ? ` — ${taskEstimate.rationale}` : ''}</div>}
        </Section>
        {Array.isArray(detail.attachments) && <AttachmentList slug={slug} taskId={id} attachments={detail.attachments} onUpload={upload} pending={busy} onError={setError} />}
        <Section title="Actions"><button type="button" onClick={() => setActions(v => !v)}>Task actions</button>{actions && <div><button type="button" onClick={() => void patch({status:'archived'})}>Archive</button><button type="button" onClick={() => { if (window.confirm('Delete this task?')) void mutate(() => api.deleteTask(slug,id), onClose); }}>Delete</button></div>}</Section>
      </aside>
    </div>}
  </div></div>;
}
