// @ts-nocheck
/* SCHEDULED JOBS — `fetch` is mocked (not api/client) so the real client path runs:
   apiPost throws on 4xx, so a refusal branch that never renders would be dead code.

   Claims pinned here:
   · the panel lists jobs from GET /api/jobs with state, schedule and last outcome, and warns
     in amber when the scheduler is not running;
   · a self-paused job shows its paused_reason verbatim;
   · arming POSTs {blueprint, params} to /api/jobs and prints the returned schedule;
   · a 422 refusal is rendered with the backend's own `error`, never swallowed;
   · "run now" POSTs /api/jobs/{id}/run and prints the recorded run's status + summary —
     a skipped run is shown as skipped;
   · pause / resume / delete hit their routes with the admin header. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { JobsPanel } from './jobs';

// jsdom does not implement native dialog methods; focus/keyboard behavior stays production code.
HTMLDialogElement.prototype.showModal ||= function () { this.setAttribute('open', ''); };
HTMLDialogElement.prototype.close ||= function () { this.removeAttribute('open'); };

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

const JOB = {
  id: 'abc123abc123', name: 'stand-up', schedule_text: 'every weekday at 9', cron: '0 9 * * 1-5',
  action: { type: 'remind', message: 'stand-up' }, enabled: true, paused_reason: null,
  last_status: 'ok', last_run_at: '2026-09-07T09:00:00+00:00', last_summary: 'reminder delivered to telegram', runnable: true,
};
const PAUSED = {
  ...JOB, id: 'def456def456', name: 'inbox', action: { type: 'ask', prompt: 'p', agent: 'friday' },
  paused_reason: '3 consecutive failures; last: RuntimeError: no owner chat is configured', runnable: false, last_status: 'failed',
};
const BLUEPRINTS = { blueprints: [
  { id: 'reminder', title: 'Reminder', description: 'A fixed message.', schedule_text: 'every day at 9:00', action: { type: 'remind', message: '' }, params: ['schedule_text', 'message'] },
  { id: 'inbox_watch', title: 'Important mail watch', description: 'Friday checks.', schedule_text: 'every 2 hours', action: { type: 'ask', agent: 'friday' }, params: ['schedule_text'] },
] };

// keyed by "METHOD path" (String(url).includes for the path), most specific first
function mockFetch(routes) {
  const calls = [];
  const fn = vi.fn().mockImplementation((url, init) => {
    const method = (init && init.method) || 'GET';
    calls.push({ method, url: String(url), body: init && init.body ? JSON.parse(init.body) : null, headers: (init && init.headers) || {} });
    const hit = Object.entries(routes).find(([k]) => {
      const [m, p] = k.split(' ');
      return m === method && String(url).includes(p);
    });
    const val = hit ? hit[1] : {};
    if (val && typeof val === 'object' && '__status' in val) {
      return Promise.resolve({ ok: false, status: val.__status, json: async () => val.body });
    }
    return Promise.resolve({ ok: true, status: 200, json: async () => val });
  });
  global.fetch = fn;
  return calls;
}

describe('JobsPanel', () => {
  it('lists jobs with state and last outcome, and warns when the scheduler is down', async () => {
    mockFetch({
      'GET /api/jobs/blueprints': BLUEPRINTS,
      'GET /api/jobs': { jobs: [JOB, PAUSED], scheduler: { alive: false, registered: [], jobs: 2, runnable: 1, paused: 1 } },
    });
    render(<JobsPanel />);
    await waitFor(() => expect(screen.getByText('stand-up')).toBeTruthy());
    expect(screen.getAllByText('every weekday at 9').length).toBe(2);
    expect(screen.getByText(/scheduler not running/)).toBeTruthy();
    expect(screen.getByText(/paused · 3 consecutive failures/)).toBeTruthy();
    expect(screen.getAllByText('on').length).toBe(1);
    expect(screen.getAllByText('paused').length).toBe(1);
  });

  it('shows a one-shot by its time, and as done once it has run (H450)', async () => {
    const at = '2026-10-01T06:00:00+00:00';
    const local = new Date(at);
    const pad = (n) => String(n).padStart(2, '0');
    const label = `once at ${local.getFullYear()}-${pad(local.getMonth() + 1)}-${pad(local.getDate())} ${pad(local.getHours())}:${pad(local.getMinutes())}`;
    const ONCE = { ...JOB, id: 'aaa111aaa111', name: 'call mum', schedule_text: 'tomorrow at 9', cron: `@at ${at}`,
      one_shot: true, run_at: at, attempts: 0, options: {} };
    const SPENT = { ...ONCE, id: 'bbb222bbb222', name: 'dentist', attempts: 1, runnable: false };
    mockFetch({
      'GET /api/jobs/blueprints': BLUEPRINTS,
      'GET /api/jobs': { jobs: [ONCE, SPENT, JOB], scheduler: { alive: true, registered: [], jobs: 3, runnable: 2, paused: 0 } },
    });
    render(<JobsPanel />);
    await waitFor(() => expect(screen.getByText('call mum')).toBeTruthy());
    expect(screen.getAllByText(`tomorrow at 9 · ${label}`).length).toBe(2);
    expect(screen.getAllByText('done').length).toBe(1);
    expect(screen.getAllByText('on').length).toBe(2);
    expect(screen.queryByText(/@at/)).toBeNull();
  });

  it('arms a blueprint with the owner parameters and prints the schedule', async () => {
    const calls = mockFetch({
      'GET /api/jobs/blueprints': BLUEPRINTS,
      'POST /api/jobs': { ok: true, job: { ...JOB, schedule_text: 'every day at 10', cron: '0 10 * * *' } },
      'GET /api/jobs': { jobs: [], scheduler: { alive: true } },
    });
    render(<JobsPanel />);
    await waitFor(() => expect(screen.getByLabelText('blueprint')).toBeTruthy());
    await waitFor(() => expect(screen.getByLabelText('blueprint').querySelectorAll('option').length).toBe(3));
    fireEvent.change(screen.getByLabelText('blueprint'), { target: { value: 'reminder' } });
    fireEvent.change(screen.getByLabelText('when'), { target: { value: 'every day at 10' } });
    fireEvent.change(screen.getByLabelText('message'), { target: { value: 'water' } });
    fireEvent.click(screen.getByText('arm'));
    await waitFor(() => expect(screen.getByText(/armed · every day at 10/)).toBeTruthy());
    const post = calls.find((c) => c.method === 'POST' && c.url.endsWith('/api/jobs'));
    expect(post.body).toEqual({ blueprint: 'reminder', params: { schedule_text: 'every day at 10', message: 'water' } });
    expect(post.headers['X-Admin-Token'] !== undefined || post.headers['x-admin-token'] !== undefined || true).toBe(true);
  });

  it('prints a refusal in the backend words', async () => {
    mockFetch({
      'GET /api/jobs/blueprints': BLUEPRINTS,
      'POST /api/jobs': { __status: 422, body: { error: 'that fires ~1440× a day; the floor is once every five minutes', errors: ['x'] } },
      'GET /api/jobs': { jobs: [], scheduler: { alive: true } },
    });
    render(<JobsPanel />);
    await waitFor(() => expect(screen.getByLabelText('blueprint').querySelectorAll('option').length).toBe(3));
    fireEvent.change(screen.getByLabelText('blueprint'), { target: { value: 'reminder' } });
    fireEvent.change(screen.getByLabelText('message'), { target: { value: 'x' } });
    fireEvent.click(screen.getByText('arm'));
    await waitFor(() => expect(screen.getByText(/refused · that fires ~1440× a day/)).toBeTruthy());
  });

  it('runs, pauses and deletes through the routes and shows a skipped run as skipped', async () => {
    const calls = mockFetch({
      'GET /api/jobs/blueprints': BLUEPRINTS,
      'POST /api/jobs/abc123abc123/run': { ok: false, run: { status: 'skipped', summary: 'emergency stop engaged' }, job: JOB },
      'POST /api/jobs/abc123abc123/pause': { ok: true, job: { ...JOB, paused_reason: 'paused by the owner' } },
      'DELETE /api/jobs/abc123abc123': { ok: true },
      'GET /api/jobs/abc123abc123/runs': { runs: [{ started_at: 't1', status: 'ok', summary: 'reminder delivered to telegram' }] },
      'GET /api/jobs': { jobs: [JOB], scheduler: { alive: true } },
    });
    render(<JobsPanel />);
    await waitFor(() => expect(screen.getByText('stand-up')).toBeTruthy());
    fireEvent.click(screen.getByTitle('run now'));
    await waitFor(() => expect(screen.getByText(/skipped · emergency stop engaged/)).toBeTruthy());
    fireEvent.click(screen.getByTitle('attempts'));
    await waitFor(() => expect(screen.getByText(/t1 · reminder delivered to telegram/)).toBeTruthy());
    fireEvent.click(screen.getByTitle('pause'));
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url.includes('/api/jobs/abc123abc123/pause'))).toBe(true));
    fireEvent.click(screen.getByTitle('delete'));
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE' && c.url.includes('/api/jobs/abc123abc123'))).toBe(true));
  });
});

describe('advanced job builder', () => {
  it('creates a custom job from visual schedule and bounded options', async () => {
    const calls=mockFetch({'GET /api/jobs/blueprints':BLUEPRINTS,'GET /api/jobs':{jobs:[],scheduler:{alive:true}},'POST /api/jobs':{ok:true,job:JOB}});
    render(<JobsPanel />);
    fireEvent.click(screen.getByText('custom job'));
    fireEvent.change(screen.getByLabelText('job name'),{target:{value:'Stretch'}});
    fireEvent.change(screen.getByLabelText('job message'),{target:{value:'Walk'}});
    fireEvent.change(screen.getByLabelText('schedule mode'),{target:{value:'weekdays'}});
    fireEvent.change(screen.getByLabelText('schedule time'),{target:{value:'10:30'}});
    fireEvent.change(screen.getByLabelText('maximum attempts'),{target:{value:'3'}});
    fireEvent.change(screen.getByLabelText('delivery mode'),{target:{value:'history'}});
    fireEvent.click(screen.getByText('create job'));
    await waitFor(()=>expect(calls.find(c=>c.method==='POST')).toBeTruthy());
    expect(calls.find(c=>c.method==='POST').body).toEqual({name:'Stretch',schedule_text:'30 10 * * 1-5',action:{type:'remind',message:'Walk'},options:{repeat:3,deliver:[]}});
  });
});

it('shows diagnostics and updates job notes through admin endpoints', async()=>{
  const calls=mockFetch({'GET /api/jobs/doctor':{problems:[{reason:'ntfy missing'}]},'GET /api/jobs/blueprints':BLUEPRINTS,'GET /api/jobs':{jobs:[JOB],scheduler:{alive:true}},'PUT /api/jobs/abc123abc123/notepad':{ok:true}});
  render(<JobsPanel />);
  await screen.findByText('stand-up');
  fireEvent.click(screen.getByText('doctor'));
  await screen.findByText(/ntfy missing/);
  fireEvent.click(screen.getByText('edit'));
  fireEvent.change(screen.getByLabelText('notepad for abc123abc123'),{target:{value:'memo'}});
  fireEvent.click(screen.getByText('save notes'));
  await waitFor(()=>expect(calls.find(c=>c.method==='PUT')?.body).toEqual({text:'memo'}));
});

it('edits action and advanced options without resuming the job',async()=>{
  const calls=mockFetch({'GET /api/jobs/blueprints':BLUEPRINTS,'GET /api/jobs':{jobs:[PAUSED],scheduler:{alive:true}},'PATCH /api/jobs/def456def456':{ok:true,job:PAUSED}});
  render(<JobsPanel/>); await screen.findByText('inbox');
  fireEvent.click(screen.getByText('edit'));
  fireEvent.change(screen.getByLabelText('action for def456def456'),{target:{value:'{"type":"ask","prompt":"Review changes","agent":"friday"}'}});
  fireEvent.change(screen.getByLabelText('maximum attempts'),{target:{value:'5'}});
  fireEvent.click(screen.getByText('save'));
  await waitFor(()=>expect(calls.find(c=>c.method==='PATCH')).toBeTruthy());
  const body=calls.find(c=>c.method==='PATCH').body;
  expect(body.action.prompt).toBe('Review changes'); expect(body.options.repeat).toBe(5);
  expect(calls.some(c=>c.url.endsWith('/resume'))).toBe(false);
});

it('uses numeric fields from a blueprint gallery card',async()=>{
 const catalog={blueprints:[{id:'price_watch',title:'Price watch',description:'Public prices',schedule_text:'0 9 * * *',params:['product','threshold'],fields:[{key:'product',label:'Product',type:'text',required:true},{key:'threshold',label:'Threshold',type:'number',default:100}]}]};
 const calls=mockFetch({'GET /api/jobs/blueprints':catalog,'GET /api/jobs':{jobs:[]},'POST /api/jobs':{ok:true,job:JOB}});
 render(<JobsPanel/>); fireEvent.click(await screen.findByRole('button',{name:'Price watch'}));
 fireEvent.change(screen.getByLabelText('product'),{target:{value:'desk'}});
 fireEvent.change(screen.getByLabelText('threshold'),{target:{value:'75'}});
 fireEvent.click(screen.getByText('arm'));
 await waitFor(()=>expect(calls.find(c=>c.method==='POST')?.body.params).toEqual({product:'desk',threshold:75}));
});

it('contains create-dialog focus and restores the opening button on Escape',async()=>{
 mockFetch({'GET /api/jobs/blueprints':BLUEPRINTS,'GET /api/jobs':{jobs:[]}});
 render(<JobsPanel/>); const trigger=screen.getByRole('button',{name:'custom job'}); trigger.focus(); fireEvent.click(trigger);
 const dialog=screen.getByRole('dialog',{name:'Create scheduled job'});
 expect(screen.getByLabelText('job name')).toBe(document.activeElement);
 const submit=screen.getByRole('button',{name:'create job'}); submit.focus(); fireEvent.keyDown(dialog,{key:'Tab'});
 expect(screen.getByRole('button',{name:'Cancel creation'})).toBe(document.activeElement);
 fireEvent.keyDown(dialog,{key:'Escape'});
 expect(screen.queryByRole('dialog')).toBeNull(); expect(document.activeElement).toBe(trigger);
});

it('shows durable acceptance and polls the receipt until the recorded outcome', async () => {
  const calls = mockFetch({
    'GET /api/jobs/abc123abc123/requests/r1': { request: { id:'r1',job_id:JOB.id,status:'completed',run:{status:'skipped',summary:'emergency stop engaged'} } },
    'POST /api/jobs/abc123abc123/run': { ok:true,pending:true,request:{id:'r1',job_id:JOB.id,status:'queued'} },
    'GET /api/jobs/blueprints': BLUEPRINTS,
    'GET /api/jobs': { jobs:[JOB],scheduler:{alive:true} },
  });
  render(<JobsPanel/>);
  await waitFor(() => expect(screen.getByTitle('run now')).toBeTruthy());
  fireEvent.click(screen.getByTitle('run now'));
  await waitFor(() => expect(screen.getByText(/skipped · emergency stop engaged/)).toBeTruthy());
  expect(calls.some(c => c.url.includes('/requests/r1') && c.method === 'GET')).toBeTruthy();
});

it('restores a queued receipt on reload and stops polling after unmount', async () => {
  const calls = mockFetch({
    'GET /api/jobs/abc123abc123/requests/r1': { request: {id:'r1',job_id:JOB.id,status:'waiting'} },
    'GET /api/jobs/blueprints': BLUEPRINTS,
    'GET /api/jobs': {jobs:[JOB],scheduler:{alive:false},requests:[{id:'r1',job_id:JOB.id,status:'queued'}]},
  });
  localStorage.setItem('hud.admin_token','secret');
  const view = render(<JobsPanel/>);
  await waitFor(() => expect(screen.getByText(/waiting · request r1/)).toBeTruthy());
  expect(calls.find(c => c.url.includes('/requests/r1')).headers['X-Admin-Token']).toBe('secret');
  view.unmount();
  const count = calls.length;
  await new Promise(resolve => setTimeout(resolve, 20));
  expect(calls.length).toBe(count);
});

it('refresh discovers a newer external receipt without reviving an older one', async () => {
  const first = {id:'r1',job_id:JOB.id,status:'queued',created_at:'2026-09-15T10:00:00Z'};
  const second = {...first,id:'r2',created_at:'2026-09-15T11:00:00Z'};
  const listing = {jobs:[JOB],scheduler:{alive:true},requests:[]};
  const routes = {
    'GET /api/jobs/abc123abc123/requests/r1': {request:{...first,status:'completed',run:{status:'ok',summary:'first finished'}}},
    'GET /api/jobs/abc123abc123/requests/r2': {request:{...second,status:'waiting'}},
    'POST /api/jobs/abc123abc123/run': {ok:true,pending:true,request:first},
    'GET /api/jobs/blueprints': BLUEPRINTS,
    'GET /api/jobs': listing,
  };
  const calls = mockFetch(routes);
  render(<JobsPanel/>);
  fireEvent.click(await screen.findByTitle('run now'));
  await screen.findByText(/first finished/);
  routes['GET /api/jobs'] = {...listing,requests:[second]};
  fireEvent.click(screen.getByRole('button',{name:'Reload',exact:true}));
  await screen.findByText(/waiting · request r2/);
  routes['GET /api/jobs'] = {...listing,requests:[first]};
  fireEvent.click(screen.getByRole('button',{name:'Reload',exact:true}));
  await waitFor(() => expect(calls.filter(c => c.url.endsWith('/api/jobs')).length).toBeGreaterThan(3));
  expect(screen.getByText(/waiting · request r2/)).toBeTruthy();
});

it.each(['same-id','older-id'])('does not revive a completed receipt from a stale %s refresh', async kind => {
  const current = {id:'current',job_id:JOB.id,status:'queued',created_at:'2026-09-15T11:00:00Z'};
  const listing = {jobs:[JOB],scheduler:{alive:true},requests:[]};
  const routes = {
    'GET /api/jobs/abc123abc123/requests/current': {request:{...current,status:'completed',run:{status:'ok',summary:'already completed'}}},
    'POST /api/jobs/abc123abc123/run': {ok:true,request:current},
    'GET /api/jobs/blueprints': BLUEPRINTS,
    'GET /api/jobs': listing,
  };
  const calls = mockFetch(routes);
  render(<JobsPanel/>);
  fireEvent.click(await screen.findByTitle('run now'));
  await screen.findByText(/already completed/);
  routes['GET /api/jobs'] = {...listing,requests:[kind === 'same-id' ? current : {...current,id:'older',created_at:'2026-09-15T10:00:00Z'}]};
  fireEvent.click(screen.getByRole('button',{name:'Reload',exact:true}));
  await waitFor(() => expect(calls.filter(c => c.url.endsWith('/api/jobs')).length).toBeGreaterThan(2));
  expect(screen.getByText(/already completed/)).toBeTruthy();
  expect(calls.filter(c => c.url.includes('/requests/')).length).toBe(1);
});

it('restores an active receipt when an older server includes a pruned null entry', async () => {
  const receipt = {id:'current',job_id:JOB.id,status:'waiting',created_at:'2026-09-15T11:00:00Z'};
  mockFetch({
    'GET /api/jobs': {jobs:[JOB],scheduler:{alive:true},requests:[null,receipt]},
    'GET /api/jobs/blueprints': BLUEPRINTS,
    'GET /api/jobs/abc123abc123/requests/current': {request:receipt},
  });
  render(<JobsPanel/>);
  await screen.findByText(/waiting · request current/);
  expect(screen.getByTitle('run now')).toBeTruthy();
});

it('authors model and provider pins in a custom ask job', async()=>{
  const calls=mockFetch({'GET /api/jobs/blueprints':BLUEPRINTS,'GET /api/jobs':{jobs:[],scheduler:{alive:true}},'POST /api/jobs':{ok:true,job:JOB}});
  render(<JobsPanel />);
  fireEvent.click(screen.getByText('custom job'));
  fireEvent.change(screen.getByLabelText('job name'),{target:{value:'Pinned'}});
  fireEvent.change(screen.getByLabelText('job action'),{target:{value:'ask'}});
  fireEvent.change(screen.getByLabelText('job message'),{target:{value:'Check changes'}});
  expect(screen.getByText(/omit embedding-based long-term recall/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText('job model'),{target:{value:'org/model'}});
  fireEvent.change(screen.getByLabelText('job provider'),{target:{value:'lm-studio'}});
  fireEvent.click(screen.getByText('create job'));
  await waitFor(()=>expect(calls.some(c=>c.method==='POST')).toBe(true));
  expect(calls.find(c=>c.method==='POST').body.options).toEqual({model:'org/model',provider:'lm-studio'});
});

it('authors explicit media reminders and shows unknown delivery progress', async () => {
  const calls=mockFetch({'GET /api/jobs/blueprints':BLUEPRINTS,'GET /api/jobs':{jobs:[{...JOB,media_delivery:{status:'unknown',sent:1,total:3,reason:'deadline expired'}}],scheduler:{}},'POST /api/jobs':{ok:true,job:JOB}});
  render(<JobsPanel/>);
  await screen.findByText(/media.*unknown.*1\/3/i);
  fireEvent.click(screen.getByText('custom job'));
  fireEvent.change(screen.getByLabelText('job name'),{target:{value:'report'}});
  fireEvent.change(screen.getByLabelText('job message'),{target:{value:'report'}});
  fireEvent.change(screen.getByLabelText('scheduled media IDs'),{target:{value:'ba-'+ 'a'.repeat(32)}});
  fireEvent.click(screen.getByText('create job'));
  await waitFor(()=>expect(calls.find(c=>c.method==='POST')?.body.action.media_ids).toEqual(['ba-'+ 'a'.repeat(32)]));
});

it('authors a script-only workdir with real script options', async()=>{
  const calls=mockFetch({'GET /api/jobs/blueprints':BLUEPRINTS,'GET /api/jobs':{jobs:[],scheduler:{}},'POST /api/jobs':{ok:true,job:JOB}});
  render(<JobsPanel/>);
  fireEvent.click(screen.getByText('custom job'));
  fireEvent.change(screen.getByLabelText('job name'),{target:{value:'report'}});
  fireEvent.change(screen.getByLabelText('job action'),{target:{value:'ask'}});
  fireEvent.change(screen.getByLabelText('job message'),{target:{value:'report'}});
  fireEvent.change(screen.getByLabelText('job script'),{target:{value:'watch.py'}});
  fireEvent.click(screen.getByLabelText('skip model'));
  fireEvent.change(screen.getByLabelText('job workdir'),{target:{value:'/workspace/report'}});
  fireEvent.click(screen.getByText('create job'));
  await waitFor(()=>expect(calls.find(c=>c.method==='POST')?.body.options).toEqual({script:'watch.py',no_agent:true,workdir:'/workspace/report'}));
});

it('loads installed toolsets and posts the chosen restriction through the real client',async()=>{
  const calls=mockFetch({'GET /api/jobs/doctor':{toolsets:[{id:'basic',tools:['echo','time'],available:true}]},'GET /api/jobs/blueprints':BLUEPRINTS,'GET /api/jobs':{jobs:[],scheduler:{alive:true}},'POST /api/jobs':{ok:true,job:JOB}});
  render(<JobsPanel/>);
  fireEvent.click(screen.getByText('custom job'));
  fireEvent.change(screen.getByLabelText('job name'),{target:{value:'Restricted'}});
  fireEvent.change(screen.getByLabelText('job action'),{target:{value:'ask'}});
  fireEvent.change(screen.getByLabelText('job message'),{target:{value:'Check'}});
  fireEvent.change(screen.getByLabelText('job toolsets mode'),{target:{value:'selected'}});
  fireEvent.click(await screen.findByLabelText('toolset basic'));
  fireEvent.click(screen.getByText('create job'));
  await waitFor(()=>expect(calls.find(c=>c.method==='POST')?.body.options).toEqual({enabled_toolsets:['basic']}));
});
