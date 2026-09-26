/* SCHEDULED JOBS — the owner's own recurring jobs (Hermes absorption, wave 2b).

   Reads GET /api/jobs and GET /api/jobs/blueprints; arms with POST /api/jobs; edits an
   existing one with PATCH /api/jobs/{id}; drives one with POST /api/jobs/{id}/run, /pause, /resume;
   removes one with DELETE /api/jobs/{id}; and lists a job's attempts from GET /api/jobs/{id}/runs. Every route is admin-guarded on the backend
   — arming autonomous work is the owner's decision — so every call here carries the admin
   token, and a refusal is printed in the backend's own words (refusalReason), never
   swallowed.

   Honesty contract:
   · `scheduler.alive:false` is rendered as an amber warning that nothing will fire; a list
     of jobs under a green chip while the scheduler is down would be a lie about the future.
   · a job that paused itself shows its `paused_reason` verbatim — "3 consecutive failures;
     last: …" is the owner's diagnosis, not a label to hide.
   · `run` shows the recorded run's status and summary, including `skipped` and its reason
     (emergency stop, paused); a forced run that was skipped is not a success.
   · a `task` job never executes here: the backend enqueues it for the autonomy policy, and
     the summary says so.

   NOTE: never spell a route path in this comment unless the panel calls it —
   tests/test_hud_v2_parity.py:_has_caller matches comment text as a caller. */
import React, { useEffect, useState } from 'react';
import { OptionsEditor, ScheduleBuilder, JobOptions } from './job-builder';
import { JobCreateDialog } from './job-create-dialog';
import { apiDelete, apiGet, apiPatch, apiPut } from '../api/client';
import { useApi, arr, mono, asLive, Card, State, Row, Tag, actA, refusalReason, inpS } from '../panel-kit';

/** H450 — a one-shot's time, in the viewer's clock: "once at 2026-10-01 09:00". */
export function onceAt(job: any): string {
  const when = job?.run_at ? new Date(job.run_at) : null;
  if (!when || Number.isNaN(when.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `once at ${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())} ${pad(when.getHours())}:${pad(when.getMinutes())}`;
}

/** H687 — what happens next, as the hub reports it: a first run now, or the wait for the cadence. */
export function armNote(reply: any): string {
  const job = reply?.job || {};
  const cadence = `${job.schedule_text || ''} (${job.one_shot ? onceAt(job) : job.cron || ''})`;
  if (typeof reply?.confirmation === 'string' && reply.confirmation) return `armed · ${reply.confirmation}`;
  if (job.one_shot) return `armed · ${cadence}`;   // H450: no cadence and never a first run
  return reply?.first_run ? `armed · first run now, then ${cadence}` : `armed · ${cadence}, on its cadence`;
}

const JOBS_PATH = '/api/jobs';
const BLUEPRINTS_PATH = '/api/jobs/blueprints';

type RunReceipt = {id:string; job_id:string; status:string; created_at?:string; reason?:string; run?:{status:string; summary:string}|null};
const pendingReceipt = (r:RunReceipt) => ['queued','running','waiting'].includes(r.status);
const receiptText = (r:RunReceipt) => r.status === 'completed' && r.run
  ? `${r.run.status} · ${r.run.summary}`
  : `${r.status === 'queued' ? 'accepted · queued' : r.status} · ${r.reason || `request ${r.id}`}`;
const EM = '—';

const Note = ({ c, children }: { c?: any; children?: any }) => (
  <div style={{ fontSize: 10, lineHeight: 1.5, color: c || 'var(--ink-2)', padding: '3px 0 5px' }}>{children}</div>
);

const stateOf = (job: any): { label: string; color: string } => {
  if (job?.options?.repeat && job.attempts >= job.options.repeat) return { label: 'complete', color: 'var(--ink-3)' };
  if (job?.one_shot && job.attempts >= 1) return { label: 'done', color: 'var(--ink-3)' };   // H450: ran its one time
  if (job?.paused_reason) return { label: 'paused', color: 'var(--amber)' };
  if (job?.enabled === false) return { label: 'off', color: 'var(--ink-3)' };
  return { label: 'on', color: 'var(--green)' };
};

const STATUS_COLOR: Record<string, string> = {
  ok: 'var(--green)',
  failed: 'var(--red)',
  skipped: 'var(--amber)',
};

export function JobsPanel() {
  const { d, e, loading, reload } = useApi(JOBS_PATH, true, true);
  const bp = useApi(BLUEPRINTS_PATH, true, true);
  const toolCatalog = useApi('/api/jobs/doctor', true, true);
  const jobs: any[] = arr(d, 'jobs');
  const scheduler: any = (d && (d as any).scheduler) || null;
  const blueprints: any[] = arr(bp.d, 'blueprints');

  const [diagnostic,setDiagnostic] = useState('');
  const [notes,setNotes] = useState<Record<string,string>>({});
  const [custom,setCustom] = useState(false);
  const [typed,setTyped] = useState<Record<string, string | number>>({});
  const [options,setOptions] = useState<JobOptions>({});
  const [blueprint, setBlueprint] = useState('');
  const [when, setWhen] = useState('');
  const [message, setMessage] = useState('');
  const [prompt, setPrompt] = useState('');
  const [agent, setAgent] = useState('');
  const [note, setNote] = useState<string | null>(null);
  const [runNote, setRunNote] = useState<Record<string, string>>({});
  const [receipts,setReceipts] = useState<Record<string,RunReceipt>>({});
  useEffect(() => {
    const restored = arr(d, 'requests') as RunReceipt[];
    if (restored.length) setReceipts(old => {
      const next = {...old};
      for (const receipt of restored) {
        if (!receipt) continue;
        const prior = next[receipt.job_id];
        if (!prior || (prior.id !== receipt.id && !pendingReceipt(prior) && pendingReceipt(receipt)
          && Date.parse(receipt.created_at || '') > Date.parse(prior.created_at || ''))) {
          next[receipt.job_id] = receipt;
        }
      }
      return next;
    });
  }, [d]);
  const pollKey = JSON.stringify(Object.values(receipts).map(r => [r.id,pendingReceipt(r)]));
  useEffect(() => {
    let closed = false;
    let polling = false;
    const active = Object.values(receipts).filter(pendingReceipt);
    const poll = async () => {
      if (closed || polling) return;
      polling = true;
      for (const receipt of active) {
        try {
          const reply = await apiGet(`${JOBS_PATH}/${encodeURIComponent(receipt.job_id)}/requests/${encodeURIComponent(receipt.id)}`, {admin:true}) as {request:RunReceipt};
          if (!closed && reply.request) setReceipts(old => old[receipt.job_id]?.id === receipt.id
            ? {...old,[receipt.job_id]:reply.request} : old);
        } catch (error) {
          if (!closed) setRunNote(old => ({...old,[receipt.job_id]:`status unavailable · ${refusalReason(error)}`}));
        }
      }
      polling = false;
    };
    if (active.length) void poll();
    const timer = active.length ? window.setInterval(() => void poll(), 2500) : undefined;
    return () => {closed = true; if (timer !== undefined) window.clearInterval(timer);};
  }, [pollKey]);
  useEffect(() => {
    setRunNote(old => ({...old,...Object.fromEntries(Object.values(receipts).map(r => [r.job_id,receiptText(r)]))}));
  }, [receipts]);
  const [runs, setRuns] = useState<Record<string, any[] | null>>({});
  const [editing, setEditing] = useState<Record<string, { name: string; when: string; action: string; options: JobOptions } | null>>({});

  const chosen = blueprints.find((b) => b.id === blueprint) || null;
  const params: string[] = (chosen && chosen.params) || [];

  const arm = () => {
    if (!chosen) { setNote('pick a blueprint first'); return; }
    const p: Record<string, string | number> = { ...typed };
    if (when.trim()) p.schedule_text = when.trim();
    if (params.includes('message') && message.trim()) p.message = message.trim();
    if (params.includes('prompt') && prompt.trim()) p.prompt = prompt.trim();
    if (params.includes('agent') && agent.trim()) p.agent = agent.trim();
    setNote(null);
    // Governed effect on the owner's behalf: MUST carry onErr so a 422 (a schedule that fires
    // too often, a blueprint missing its message) is printed, not swallowed.
    actA(JOBS_PATH, { blueprint: chosen.id, params: p, ...(Object.keys(options).length ? {options} : {}) },
      (r: any) => { setNote(armNote(r)); setMessage(''); setPrompt(''); reload(); },
      (err: any) => setNote(`refused · ${refusalReason(err, 'could not arm the job')}`));
  };

  const drive = (id: string, op: 'run' | 'pause' | 'resume') =>
    actA(`${JOBS_PATH}/${encodeURIComponent(id)}/${op}`, {},
      (r: any) => {
        if (op === 'run') {
          if (r?.request) setReceipts(old => ({...old,[id]:r.request}));
          const run = r?.run || {};
          if (!r?.request) setRunNote((m) => ({ ...m, [id]: `${run.status || '?'} · ${run.summary || ''}` }));
        }
        reload();
      },
      (err: any) => setRunNote((m) => ({ ...m, [id]: `refused · ${refusalReason(err)}` })));

  const remove = (id: string) =>
    apiDelete(`${JOBS_PATH}/${encodeURIComponent(id)}`, { admin: true })
      .then(() => reload())
      .catch((err: any) => setRunNote((m) => ({ ...m, [id]: `refused · ${refusalReason(err)}` })));

  // An edit is only real once the scheduler re-arms, which the backend does; the panel
  // re-reads afterwards so the row shows the cron the job will actually fire on, never the
  // text the owner just typed.
  const openEdit = (job: any) => {
    const id = String(job.id);
    setNotes(m=>({...m,[id]:job.notepad || ''}));
    setEditing((m) => ({ ...m, [id]: m[id] ? null : { name: job.name || '', when: job.schedule_text || '', action: JSON.stringify(job.action, null, 2), options: job.options || {} } }));
  };

  const saveEdit = (id: string) => {
    const draft = editing[id];
    if (!draft) return;
    const body: Record<string, unknown> = {options:draft.options};
    try { body.action=JSON.parse(draft.action); } catch { setRunNote(m=>({...m,[id]:'refused · invalid action JSON'})); return; }
    if (draft.name.trim()) body.name = draft.name.trim();
    if (draft.when.trim()) body.schedule_text = draft.when.trim();
    if (!Object.keys(body).length) { setRunNote((m) => ({ ...m, [id]: 'nothing to change' })); return; }
    apiPatch(`${JOBS_PATH}/${encodeURIComponent(id)}`, body, { admin: true })
      .then((r: any) => {
        setEditing((m) => ({ ...m, [id]: null }));
        setRunNote((m) => ({ ...m, [id]: `edited · ${r?.job?.schedule_text || ''} (${r?.job?.one_shot ? onceAt(r.job) : r?.job?.cron || ''})` }));
        reload();
      })
      .catch((err: any) => setRunNote((m) => ({ ...m, [id]: `refused · ${refusalReason(err, 'could not edit the job')}` })));
  };

  const showRuns = (id: string) => {
    if (runs[id]) { setRuns((m) => ({ ...m, [id]: null })); return; }
    apiGet(`${JOBS_PATH}/${encodeURIComponent(id)}/runs?limit=5`, { admin: true })
      .then((r: any) => setRuns((m) => ({ ...m, [id]: arr(r, 'runs') })))
      .catch((err: any) => setRunNote((m) => ({ ...m, [id]: `refused · ${refusalReason(err)}` })));
  };

  const alive = scheduler ? scheduler.alive === true : null;

  return (
    <Card title="SCHEDULED JOBS" live={asLive(d)} sub={jobs.length} onReload={reload}>
      <State e={e} loading={loading} n={jobs.length} />
      <div style={{display:'flex',gap:6}}>
        <button className="tool-btn" onClick={()=>apiGet('/api/jobs/doctor',{admin:true}).then(r=>setDiagnostic(JSON.stringify(r,null,2))).catch(e=>setDiagnostic(refusalReason(e)))}>doctor</button>
        <button className="tool-btn" onClick={()=>apiGet('/api/jobs/incidents',{admin:true}).then(r=>setDiagnostic(JSON.stringify(r,null,2))).catch(e=>setDiagnostic(refusalReason(e)))}>incidents</button>
        {alive===false && <button className="tool-btn" onClick={()=>actA('/api/jobs/tick',{},r=>{setDiagnostic(JSON.stringify(r,null,2));reload();},e=>setDiagnostic(refusalReason(e)))}>tick due jobs ({scheduler?.timezone || 'hub time'})</button>}
      </div>
      {diagnostic && <pre style={{fontSize:10,whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{diagnostic}</pre>}
      {scheduler && alive === false && (
        <Note c="var(--amber)">scheduler not running — nothing will fire until the hub restarts its heartbeat scheduler</Note>
      )}
      {d && jobs.length === 0 && !e && <Note>no jobs armed — pick a blueprint below, or say <span style={mono}>/remind every weekday at 7 | stand-up</span> in chat</Note>}

      {jobs.map((job: any) => {
        const st = stateOf(job);
        const id = String(job.id);
        return (
          <div key={id}>
            <Row>
              <span style={mono}>{job.name || EM}</span>
              <Tag c={st.color}>{st.label}</Tag>
              <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>{job.schedule_text || job.cron || ''}{job.one_shot ? ` · ${onceAt(job)}` : ''}</span>
              <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>{job.action?.type || ''}</span>
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
                <button className="tool-btn" title="run now" onClick={() => drive(id, 'run')}>▶ now</button>
                {job.paused_reason
                  ? <button className="tool-btn" title="resume" onClick={() => drive(id, 'resume')}>⏵</button>
                  : <button className="tool-btn" title="pause" onClick={() => drive(id, 'pause')}>⏸</button>}
                <button className="tool-btn" title="edit name or schedule" onClick={() => openEdit(job)}>edit</button>
                <button className="tool-btn" title="attempts" onClick={() => showRuns(id)}>runs</button>
                <button className="tool-btn" title="delete" onClick={() => remove(id)}>✕</button>
              </span>
            </Row>
            {job.options?.workdir && <div>Script workdir: {job.options.workdir} · approval required per run</div>}
            {job.media_delivery && <Note c={['unknown','partial'].includes(job.media_delivery.status)?'var(--red)':undefined}>Media · {job.media_delivery.status} · {job.media_delivery.sent}/{job.media_delivery.total} acknowledged · {job.media_delivery.reason}{['unknown','partial'].includes(job.media_delivery.status) && ' Review the Telegram channel, explicitly re-save the reminder action to authorize future sends, then resume. Do not assume an unknown item was unsent.'}</Note>}
            {editing[id] && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 5, padding: '4px 0 6px' }}>
                <input aria-label={`name for ${id}`} value={editing[id]!.name}
                  onChange={(ev) => setEditing((m) => ({ ...m, [id]: { ...m[id]!, name: ev.target.value } }))}
                  placeholder="name" style={{ ...inpS, width: '100%' }} />
                <input aria-label={`when for ${id}`} value={editing[id]!.when}
                  onChange={(ev) => setEditing((m) => ({ ...m, [id]: { ...m[id]!, when: ev.target.value } }))}
                  placeholder="when — plain words or a five-field cron" style={{ ...inpS, width: '100%' }} />
                <ScheduleBuilder onChange={when=>setEditing(m=>({...m,[id]:{...m[id]!,when}}))}/>
                <label>Action JSON<textarea aria-label={`action for ${id}`} value={editing[id]!.action} style={{...inpS,width:'100%'}} onChange={ev=>setEditing(m=>({...m,[id]:{...m[id]!,action:ev.target.value}}))}/></label>
                <label>Notes<textarea aria-label={`notepad for ${id}`} maxLength={4096} style={{...inpS,width:'100%'}} value={notes[id] || ''} onChange={e=>setNotes(m=>({...m,[id]:e.target.value}))}/></label>
                <button className="tool-btn" onClick={()=>apiPut(`/api/jobs/${encodeURIComponent(id)}/notepad`,{text:notes[id] || ''},{admin:true}).then(()=>{setRunNote(m=>({...m,[id]:'notes saved'}));reload();}).catch(e=>setRunNote(m=>({...m,[id]:refusalReason(e)})))}>save notes</button>
                <OptionsEditor toolsets={arr(toolCatalog.d, 'toolsets')} value={editing[id]!.options} onChange={options=>setEditing(m=>({...m,[id]:{...m[id]!,options}}))}/>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button className="tool-btn" onClick={() => saveEdit(id)}>save</button>
                  <button className="tool-btn" onClick={() => setEditing((m) => ({ ...m, [id]: null }))}>cancel</button>
                  <span style={{ fontSize: 10, color: 'var(--ink-3)', alignSelf: 'center' }}>
                    editing a paused job leaves it paused
                  </span>
                </div>
              </div>
            )}
            {job.paused_reason && <Note c="var(--amber)">paused · {String(job.paused_reason)}</Note>}
            {job.last_status && (
              <Note>
                last <span style={{ color: STATUS_COLOR[job.last_status] || 'var(--ink-2)' }}>{job.last_status}</span>
                {job.last_run_at ? ` · ${job.last_run_at}` : ''}{job.last_summary ? ` · ${String(job.last_summary).slice(0, 140)}` : ''}
              </Note>
            )}
            {runNote[id] && <Note c={runNote[id].startsWith('refused') ? 'var(--red)' : 'var(--accent-light)'}>{runNote[id]}</Note>}
            {runs[id] && runs[id]!.map((r: any, i: number) => (
              <Note key={i}>
                <span style={{ color: STATUS_COLOR[r.status] || 'var(--ink-2)' }}>{r.status}</span> · {r.started_at} · {String(r.summary || r.error || '').slice(0, 140)}
              </Note>
            ))}
            {runs[id] && runs[id]!.length === 0 && <Note>no attempts recorded yet</Note>}
          </div>
        );
      })}

      <div style={{ marginTop: 10, borderTop: '1px solid var(--panel-line)', paddingTop: 8 }}>
        <div style={{ ...mono, fontSize: 10, letterSpacing: '.08em', color: 'var(--ink-2)', marginBottom: 4 }}>ARM A JOB</div>
        <select aria-label="blueprint" value={blueprint} onChange={(ev) => {setBlueprint(ev.target.value);setTyped({});}} style={{ ...inpS, width: '100%' }}>
          <option value="">blueprint…</option>
          {blueprints.map((b: any) => <option key={b.id} value={b.id}>{b.title} — {b.description}</option>)}
        </select>
        <div aria-label="Automation blueprint gallery" style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(140px,1fr))',gap:6,marginTop:8}}>
          {blueprints.map((b:any)=><button key={b.id} className="tool-btn" title={b.description} aria-pressed={blueprint===b.id} onClick={()=>{setBlueprint(b.id);setTyped({});}}>{b.title}</button>)}
        </div>
        {chosen && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5, marginTop: 5 }}>
            <input aria-label="when" value={when} onChange={(ev) => setWhen(ev.target.value)} placeholder={`when (default: ${chosen.schedule_text})`} style={{ ...inpS, width: '100%' }} />
            {params.includes('message') && <input aria-label="message" value={message} onChange={(ev) => setMessage(ev.target.value)} placeholder="message" style={{ ...inpS, width: '100%' }} />}
            {params.includes('prompt') && <input aria-label="prompt" value={prompt} onChange={(ev) => setPrompt(ev.target.value)} placeholder="prompt for the agent" style={{ ...inpS, width: '100%' }} />}
            {params.includes('agent') && <input aria-label="agent" value={agent} onChange={(ev) => setAgent(ev.target.value)} placeholder={`agent (default: ${chosen.action?.agent || 'jarvis'})`} style={{ ...inpS, width: '100%' }} />}
            {(chosen.fields || []).filter((f:any)=>!['schedule_text','message','prompt','agent'].includes(f.key)).map((f:any)=><label key={f.key}>{f.label}<input aria-label={f.key} type={f.type === 'number' ? 'number' : 'text'} min={f.minimum} required={f.required} style={inpS} value={typed[f.key] ?? f.default ?? ''} onChange={ev=>setTyped(p=>({...p,[f.key]:f.type==='number'?Number(ev.target.value):ev.target.value}))}/></label>)}
            <ScheduleBuilder onChange={setWhen}/>
            <OptionsEditor toolsets={arr(toolCatalog.d, 'toolsets')} value={options} onChange={setOptions}/>
            <div style={{ display: 'flex', gap: 6 }}>
              <button className="tool-btn" onClick={arm}>arm</button>
              <span style={{ fontSize: 10, color: 'var(--ink-3)', alignSelf: 'center' }}>a task-type job still crosses the approval queue; a reminder never touches the model</span>
            </div>
          </div>
        )}
        <button className="tool-btn" onClick={()=>{setNote(null);setCustom(true);}}>custom job</button>
        {custom && <JobCreateDialog toolsets={arr(toolCatalog.d, 'toolsets')} onClose={()=>setCustom(false)} error={note} onSave={body=>actA(JOBS_PATH,body,(r:any)=>{setNote(armNote(r));setCustom(false);reload();},(err:any)=>setNote(`refused · ${refusalReason(err)}`))}/>}
        {note && !custom && <Note c={note.startsWith('refused') ? 'var(--red)' : 'var(--accent-light)'}>{note}</Note>}
      </div>
    </Card>
  );
}


/** A full-width home for jobs, usable even before other Autonomy telemetry is connected. */
export function JobsWorkspace() {
  return <section aria-label="Scheduled automations" style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '16px 24px' }}>
    <header style={{ marginBottom: 20 }}>
      <h1 style={{ margin: '0 0 8px' }}>Scheduled automations</h1>
      <p style={{ margin: 0, color: 'var(--ink-2)' }}>Manage recurring work, review runs, or start from one of sixteen blueprints.</p>
    </header>
    <JobsPanel />
  </section>;
}
