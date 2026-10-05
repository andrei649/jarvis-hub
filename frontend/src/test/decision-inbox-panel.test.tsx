// @ts-nocheck
/* HUD-v3 B1 (the north-star) — the Console Decision Inbox reads the blocked autonomy
   queue (/autonomy/tasks?status=blocked) and resolves a decision via
   POST /autonomy/tasks/{id}/decision {action}. fetch is mocked, like
   kernel-safety-panels.test.tsx. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, act, cleanup } from '@testing-library/react';
import { DecisionInboxPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });
afterEach(() => { cleanup(); vi.useRealTimers(); });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

it.each([true, false])('previews complete pending questions or explains a lost binding: %s', async available => {
  const text = 'Full question ' + 'x'.repeat(17000);
  mockFetch({ tasks: [{ id: 75, title: 'Native question', kind: 'channel.reply', status: 'blocked' }],
    prompt: available ? { available: true, text, choices: ['First option', '<script>plain text</script>'] }
      : { available: false } });
  render(<DecisionInboxPanel />);
  fireEvent.click(await screen.findByTitle('dry-run preview'));
  if (available) {
    const content = await screen.findByLabelText('Complete pending question');
    expect(content.textContent).toBe(text);
    expect(screen.getByText('First option')).toBeTruthy();
    expect(screen.getByText('<script>plain text</script>')).toBeTruthy();
    expect(document.querySelector('script')).toBeNull();
  } else {
    expect(await screen.findByText('This question has expired or its live delivery is unavailable.')).toBeTruthy();
    expect(screen.queryByLabelText('Complete pending question')).toBeNull();
  }
});

it('shows reusable terminal choices and sends only the exact offer revision', async () => {
  const revision = 'a'.repeat(64);
  const fn = mockFetch({ tasks: [{ id: 73, title: 'Reviewed terminal request',
    kind: 'toolrpc.terminal_run', status: 'blocked', consent_offer: {
      revision, count: 2, choices: ['session', 'always', 'deny'],
      categories: [{ description: 'git reset destroys uncommitted changes', permanent: true }],
    },
  }] });
  localStorage.setItem('hud.admin_token', 'synthetic-owner');
  render(<DecisionInboxPanel />);
  await screen.findByText('git reset destroys uncommitted changes');
  expect(screen.getByText('Applies to 2 matching requests.')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Your decision reason for Reviewed terminal request'),
    { target: { value: 'Use the synthetic workspace' } });
  fireEvent.click(screen.getByRole('button', { name: 'Allow this session' }));
  await waitFor(() => expect(fn.mock.calls.some(([url, init]) =>
    url === '/autonomy/tasks/73/consent' && JSON.stringify(JSON.parse(init?.body || '{}'))
      === JSON.stringify({ choice: 'session', revision, reason: 'Use the synthetic workspace' })
  )).toBe(true));
  const post = fn.mock.calls.find(([url]) => url === '/autonomy/tasks/73/consent');
  expect(post[1].headers['X-Admin-Token']).toBe('synthetic-owner');
  expect(screen.getByTitle('accept')).toBeTruthy();
});

it.each([undefined, { revision: 'stale', count: 1, choices: ['always'], categories: [] }])(
  'keeps ordinary once controls when a reusable offer is absent or malformed', async consent_offer => {
    mockFetch({ tasks: [{ id: 74, title: 'Ordinary terminal request',
      kind: 'toolrpc.terminal_run', status: 'blocked', consent_offer }] });
    render(<DecisionInboxPanel />);
    await screen.findByText('Ordinary terminal request');
    expect(screen.queryByRole('button', { name: 'Allow this session' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Allow always' })).toBeNull();
    expect(screen.getByTitle('accept').disabled).toBe(false);
  },
);

it('shows the current request deadline without changing its single-use decision', async () => {
  const deadline = '2030-01-02T03:04:05.000000+00:00';
  const fn = mockFetch({ tasks: [
    { id: 71, title: 'Timed request', kind: 'test', status: 'blocked', approval_deadline_at: deadline },
  ] });
  render(<DecisionInboxPanel />);
  const label = await screen.findByLabelText('Approval deadline for Timed request');
  expect(label.querySelector('time')?.getAttribute('datetime')).toBe(deadline);
  expect(label.textContent).toContain('Expires without a response');
  fireEvent.click(screen.getByTitle('accept'));
  await waitFor(() => expect(fn.mock.calls.some(([url, init]) => url === '/autonomy/tasks/71/decision'
    && init?.body === JSON.stringify({ action: 'accept' }))).toBe(true));
});

it.each([undefined, 'invalid-date'])('keeps legacy or unreadable deadlines out of the card: %s', async deadline => {
  mockFetch({ tasks: [
    { id: 72, title: 'Ordinary request', kind: 'test', status: 'blocked', approval_deadline_at: deadline },
  ] });
  render(<DecisionInboxPanel />);
  await screen.findByText('Ordinary request');
  expect(screen.queryByLabelText('Approval deadline for Ordinary request')).toBeNull();
  expect(screen.queryByText('Invalid Date')).toBeNull();
  expect(screen.getByTitle('accept').disabled).toBe(false);
});

it('sends the human reason only with the matching decision and preserves blank requests', async () => {
  const fn = mockFetch({ tasks: [
    { id: 31, title: 'First action', kind: 'test', status: 'blocked' },
    { id: 32, title: 'Second action', kind: 'test', status: 'blocked' },
  ] });
  render(<DecisionInboxPanel />);
  const reason = await screen.findByLabelText('Your decision reason for First action');
  expect(reason.maxLength).toBe(280);
  fireEvent.change(reason, { target: { value: 'Use the staging address' } });
  fireEvent.click(screen.getAllByTitle('reject')[1]);
  await waitFor(() => expect(fn.mock.calls.some(([url, init]) => url === '/autonomy/tasks/32/decision'
    && init?.body === JSON.stringify({ action: 'reject' }))).toBe(true));
  fireEvent.click(screen.getAllByTitle('reject')[0]);
  await waitFor(() => expect(fn.mock.calls.some(([url, init]) => url === '/autonomy/tasks/31/decision'
    && JSON.parse(init?.body || '{}').reason === 'Use the staging address')).toBe(true));
});

describe('DecisionInboxPanel — independent grouped approvals', () => {
  const tasks = [41, 42].map(id => ({ id, title: 'Same governed task', kind: 'delete_file', status: 'blocked' }));
  const group = { id: 'task-group', leader_id: 41, count: 2, member_ids: [41, 42], snapshot: 'current-members' };

  it('shows one card, accepts only the leader and then shows its still-pending follower', async () => {
    let accepted = false;
    const fn = vi.fn(async (url, options) => {
      if (url === '/autonomy/tasks/41/decision' && options?.method === 'POST') accepted = true;
      return { ok: true, status: 200, json: async () => ({
        tasks: accepted ? tasks.slice(1) : tasks, groups: accepted ? [] : [group],
      }) };
    });
    global.fetch = fn;
    render(<DecisionInboxPanel />);
    await screen.findByText(/2 matching requests/);
    expect(screen.getAllByTitle('accept')).toHaveLength(1);
    fireEvent.click(screen.getByTitle('accept'));
    await waitFor(() => expect(screen.queryByText(/2 matching requests/)).toBeNull());
    expect(screen.getByText('Same governed task')).toBeTruthy();
    expect(fn.mock.calls.filter(([, init]) => init?.method === 'POST').map(([url]) => url))
      .toEqual(['/autonomy/tasks/41/decision']);
    fireEvent.click(screen.getByTitle('accept'));
    await waitFor(() => expect(fn.mock.calls.some(([url]) => url === '/autonomy/tasks/42/decision')).toBe(true));
  });

  it('rejects only the displayed exact group and carries the leader reason', async () => {
    const fn = mockFetch({ tasks, groups: [group] });
    render(<DecisionInboxPanel />);
    const reason = await screen.findByLabelText('Your decision reason for Same governed task');
    fireEvent.change(reason, { target: { value: 'Use staging' } });
    fireEvent.click(screen.getByRole('button', { name: 'reject group' }));
    await waitFor(() => expect(fn.mock.calls.some(([url, init]) =>
      url === '/autonomy/tasks/groups/task-group/reject'
      && JSON.stringify(JSON.parse(init?.body || '{}')) === JSON.stringify({
        snapshot: 'current-members', member_ids: [41, 42], reason: 'Use staging',
      }))).toBe(true));
  });

  it('does not hide cards behind a missing leader or malformed membership', async () => {
    mockFetch({ tasks, groups: [{ ...group, leader_id: 99 }] });
    render(<DecisionInboxPanel />);
    await waitFor(() => expect(screen.getAllByTitle('accept')).toHaveLength(2));
    expect(screen.queryByRole('button', { name: 'reject group' })).toBeNull();
  });
});

describe('DecisionInboxPanel — the north-star resolve action is live', () => {
  it('GETs the blocked queue and shows a decision with its risk tier', async () => {
    const fn = mockFetch({ tasks: [
      { id: 5, title: 'Send the follow-up email', kind: 'call.outbound', risk_tier: 2, status: 'blocked' },
    ], total: 1 });
    render(<DecisionInboxPanel />);
    await waitFor(() => expect(screen.getByText('Send the follow-up email')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/autonomy/tasks') && String(c[0]).includes('status=blocked'))).toBe(true);
    expect(screen.getByText('tier 2')).toBeTruthy();
  });

  it('shows the rollback story before approval', async () => {
    mockFetch({ tasks: [{
      id: 6, title: 'Pay invoice', kind: 'payment', risk_tier: 3, status: 'blocked',
      rollback: {
        mode: 'cancel', automatic: false,
        description: 'Cancel before settlement.',
        limitations: 'A settled payment cannot be undone.',
      },
    }], total: 1 });
    render(<DecisionInboxPanel />);
    await waitFor(() => expect(screen.getByText(/rollback ·/i)).toBeTruthy());
    expect(screen.getByText(/cancel before settlement/i)).toBeTruthy();
    expect(screen.getByText(/settled payment cannot be undone/i)).toBeTruthy();
  });

  it('accepts a decision (POST {action:"accept"}) when ✓ is clicked', async () => {
    const fn = mockFetch({ tasks: [{ id: 5, title: 'X', kind: 'k', risk_tier: 1, status: 'blocked' }], total: 1 });
    render(<DecisionInboxPanel />);
    await waitFor(() => expect(screen.getByTitle('accept')).toBeTruthy());
    fireEvent.click(screen.getByTitle('accept'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/autonomy/tasks/5/decision')
        && c[1]?.method === 'POST' && String(c[1]?.body).includes('"action":"accept"'))
    ).toBe(true));
  });

  it('rejects a decision (POST {action:"reject"}) when ✕ is clicked', async () => {
    const fn = mockFetch({ tasks: [{ id: 9, title: 'Y', kind: 'k', risk_tier: 3, status: 'blocked' }], total: 1 });
    render(<DecisionInboxPanel />);
    await waitFor(() => expect(screen.getByTitle('reject')).toBeTruthy());
    fireEvent.click(screen.getByTitle('reject'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/autonomy/tasks/9/decision')
        && c[1]?.method === 'POST' && String(c[1]?.body).includes('"action":"reject"'))
    ).toBe(true));
  });

  it('shows the honest all-clear state when nothing is blocked', async () => {
    mockFetch({ tasks: [], total: 0 });
    render(<DecisionInboxPanel />);
    await waitFor(() => expect(screen.getByText(/all clear/)).toBeTruthy());
  });

  it('edit reveals the payload as JSON and saves an edited decision (POST {action:"edit",payload})', async () => {
    const fn = mockFetch({ tasks: [
      { id: 7, title: 'Wire $200', kind: 'payment', risk_tier: 3, status: 'blocked', payload: { amount: 200 } },
    ], total: 1 });
    render(<DecisionInboxPanel />);
    await waitFor(() => expect(screen.getByTitle('edit')).toBeTruthy());
    fireEvent.click(screen.getByTitle('edit'));
    // the textarea is pre-filled with the task's payload
    const ta = await screen.findByDisplayValue(/"amount": 200/);
    fireEvent.change(ta, { target: { value: '{"amount": 50}' } });
    fireEvent.click(screen.getByText('save & approve'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/autonomy/tasks/7/decision')
        && c[1]?.method === 'POST'
        && String(c[1]?.body).includes('"action":"edit"')
        && String(c[1]?.body).includes('"amount":50'))
    ).toBe(true));
  });

  it('does NOT POST an edit when the payload JSON is invalid', async () => {
    const fn = mockFetch({ tasks: [
      { id: 8, title: 'X', kind: 'k', risk_tier: 1, status: 'blocked', payload: {} },
    ], total: 1 });
    render(<DecisionInboxPanel />);
    await waitFor(() => expect(screen.getByTitle('edit')).toBeTruthy());
    fireEvent.click(screen.getByTitle('edit'));
    const ta = await screen.findByDisplayValue('{}');
    fireEvent.change(ta, { target: { value: '{not valid json' } });
    fireEvent.click(screen.getByText('save & approve'));
    // invalid JSON is swallowed by the try/catch — no decision POST should fire
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/decision') && c[1]?.method === 'POST')).toBe(false);
  });

  it('preview GETs the dry-run and shows the consequences (effects + irreversible + would-execute)', async () => {
    const fn = mockFetch({
      // GET blocked queue AND the dry-run share one mock payload
      tasks: [{ id: 5, title: 'Wire $200', kind: 'payment', risk_tier: 3, status: 'blocked' }],
      summary: 'Send $200 to ACME', irreversible: true, would_execute: false,
      effects: ['debit 200', 'notify payee'],
    });
    render(<DecisionInboxPanel />);
    await waitFor(() => expect(screen.getByTitle('dry-run preview')).toBeTruthy());
    fireEvent.click(screen.getByTitle('dry-run preview'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/api/autonomy/tasks/5/preview'))
    ).toBe(true));
    await waitFor(() => expect(screen.getByText('Send $200 to ACME')).toBeTruthy());
    expect(screen.getByText('irreversible')).toBeTruthy();
    expect(screen.getByText('would queue')).toBeTruthy();   // would_execute:false
    expect(screen.getByText('debit 200')).toBeTruthy();
  });

  it('shows the interrupt budget (used/per_day) in the header — calm by the numbers', async () => {
    // one payload serves both GETs: /autonomy/tasks?status=blocked AND /autonomy/interrupts
    mockFetch({
      tasks: [{ id: 1, title: 'x', kind: 'k', risk_tier: 1, status: 'blocked' }],
      remaining: 3, per_day: 4, used: 1,
    });
    render(<DecisionInboxPanel />);
    await waitFor(() => expect(screen.getByText(/1\/4 interrupts today/)).toBeTruthy());
  });

  it.each(['toolrpc.image_generate', 'tool.rpc'])('shows an image prompt for %s without exposing approval internals or editing its bound JSON', async kind => {
    const fn = mockFetch({ tasks: [{ id: 17, kind, title: 'Local image',
      risk_tier: 2, status: 'blocked', payload: { tool: 'image_generate', target: 'image_generate', args: {
        prompt: 'A rain-soaked tree', width: 512, height: 512, steps: 20,
        _binding: { nonce: 'PRIVATE', head: 'PRIVATE' }, url: 'https://evil.invalid/PRIVATE',
      } } }] });
    render(<DecisionInboxPanel />);
    await screen.findByText('A rain-soaked tree');
    expect(screen.getByText(/Changes require a fresh proposal/)).toBeTruthy();
    expect(screen.queryByTitle('edit')).toBeNull();
    expect(screen.queryByTitle('dry-run preview')).toBeNull();
    expect(document.body.textContent).not.toContain('PRIVATE');
    fireEvent.click(screen.getByTitle('accept'));
    await waitFor(() => expect(fn.mock.calls.some(c => c[0] === '/autonomy/tasks/17/decision'
      && c[1].body === '{"action":"accept"}')).toBe(true));
  });

  it('keeps ordinary canonical tool requests editable and does not treat their payload as an image', async () => {
    mockFetch({ tasks: [{ id: 18, kind: 'tool.rpc', title: 'Other tool', risk_tier: 2,
      status: 'blocked', payload: { tool: 'other', target: 'other', args: { prompt: 'Not an image' } } }] });
    render(<DecisionInboxPanel />);
    await screen.findByText('Other tool');
    expect(screen.getByTitle('edit')).toBeTruthy();
    expect(screen.getByTitle('dry-run preview')).toBeTruthy();
    expect(screen.queryByText(/Changes require a fresh proposal/)).toBeNull();
  });
});

it('shows exact paid cloud proposal and immutable task return link',async()=>{
  window.__NERVA_BASE_PATH__='/nerva';
  try {
    mockFetch({tasks:[{id:17,kind:'plugin.egress',title:'Paid image',payload:{plugin:'cloud-image',method:'POST',url:'https://api.openai.com/v1/images/generations',image:{body:{model:'gpt-image-1.5',prompt:'exact cloud prompt',size:'1536x1024',quality:'high'}}}}]});
    render(<DecisionInboxPanel/>);await screen.findByText('exact cloud prompt');
    expect(screen.getByText(/OpenAI.*gpt-image-1.5.*1536x1024.*high/)).toBeTruthy();
    expect(screen.queryByTitle('edit')).toBeNull();expect(screen.queryByTitle('dry-run preview')).toBeNull();
    expect(screen.getByRole('link',{name:'Watch image task'}).getAttribute('href')).toBe('/nerva/v2/console/images?image_task=17');
    expect(screen.getByTitle('accept')).toBeTruthy();expect(screen.getByTitle('reject')).toBeTruthy();expect(screen.getByTitle('defer')).toBeTruthy();
  } finally {window.__NERVA_BASE_PATH__='';}
});

it.each([
  ['cloud-image-fal', 'https://fal.run/fal-ai/flux-2/klein/9b/edit', 'FAL', 'fal-ai/flux-2/klein/9b', {endpoint:'fal-ai/flux-2/klein/9b/edit',references:['https://fal.media/input.png']}],
  ['cloud-image-codex', 'https://chatgpt.com/backend-api/codex/images/edits', 'Codex OAuth', 'gpt-image-2-medium', {references:['a'.repeat(32)]}],
  ['cloud-image', 'https://api.openai.com/v1/images/edits', 'OpenAI', 'gpt-image-2', {selected_model:'gpt-image-2-high',quality:'high',references:['a'.repeat(32)]}],
])('shows %s generation/edit as an immutable image approval with its actual provider and references',async(plugin,url,label,model,extra)=>{
  window.__NERVA_BASE_PATH__='';
  mockFetch({tasks:[{id:19,kind:'plugin.egress',title:'Image edit',payload:{plugin,method:'POST',url,
    image:{body:{model,prompt:'exact provider edit',size:'1024x1024',...extra},generation:'PRIVATE',nonce:'PRIVATE'}}}]});
  render(<DecisionInboxPanel/>);
  await screen.findByText('exact provider edit');
  expect(screen.getByText(new RegExp(label+'.*'+(extra.selected_model||model)))).toBeTruthy();
  expect(screen.getByText(new RegExp(extra.references[0].replace(/[.*+?^${}()|[\]\\]/g,'\\$&')))).toBeTruthy();
  expect(screen.queryByTitle('edit')).toBeNull();
  expect(screen.queryByTitle('dry-run preview')).toBeNull();
  expect(document.body.textContent).not.toContain('PRIVATE');
  expect(screen.getByRole('link',{name:'Watch image task'}).getAttribute('href')).toBe('/v2/console/images?image_task=19');
});

it.each([
  ['cloud-image-openrouter', 'https://openrouter.ai/api/v1/chat/completions', 'OpenRouter', 'openai/gpt-5.4-image-2'],
  ['cloud-image-openrouter', 'https://openrouter.ai/api/v1/images', 'OpenRouter', 'openai/gpt-image-2'],
])('recognizes only the fixed %s surface and shows its immutable artifact reference', async(plugin,url,label,model) => {
  mockFetch({tasks:[{id:21,kind:'plugin.egress',title:'Image',payload:{plugin,method:'POST',url,
    image:{body:{model,prompt:'exact OpenRouter prompt',size:'1024x1024',references:['a'.repeat(32)]},nonce:'PRIVATE'}}}]});
  render(<DecisionInboxPanel/>);
  await screen.findByText('exact OpenRouter prompt');
  expect(screen.getByText(new RegExp(label+'.*'+model.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')))).toBeTruthy();
  expect(screen.getByText(/References.*a{32}/)).toBeTruthy();
  expect(screen.queryByTitle('edit')).toBeNull();
  expect(document.body.textContent).not.toContain('PRIVATE');
  expect(screen.getByRole('link',{name:'Watch image task'})).toBeTruthy();
});

it('shows Krea style-guided URLs and strengths from the canonical bound JSON without offering edit or Enhance', async()=>{
  mockFetch({tasks:[{id:22,kind:'plugin.egress',title:'Style-guided image',payload:{plugin:'cloud-image-krea',method:'POST',
    url:'https://api.krea.ai/generate/image/krea/krea-2/medium',image:{body:{model:'krea-2-medium',prompt:'exact Krea prompt',
      size:'1536x1024',creativity:'high',modality:'style_guided_generation',
      style_references_json:'[{"url":"https://images.example.com/style.png","strength":0.6}]'},nonce:'PRIVATE'}}}]});
  render(<DecisionInboxPanel/>);
  await screen.findByText('exact Krea prompt');
  expect(screen.getByText(/Krea.*krea-2-medium.*1536x1024/)).toBeTruthy();
  expect(screen.getByText(/Style-guided generation/)).toBeTruthy();
  expect(screen.getByText(/https:\/\/images.example.com\/style.png.*0.6/)).toBeTruthy();
  expect(screen.queryByTitle('edit')).toBeNull();
  expect(document.body.textContent).not.toContain('PRIVATE');
});

it('shows the exact Krea Enhance source and warning as an immutable paid approval',async()=>{
  mockFetch({tasks:[{id:31,kind:'plugin.egress',title:'Krea Enhance',payload:{plugin:'cloud-image-krea',method:'POST',
    url:'https://api.krea.ai/generate/enhance/krea/enhance',image:{body:{model:'krea-2-medium',prompt:'source prompt',
      size:'1024x1024',operation:'enhance',image_url:'https://images.example.com/source.png',image_scaling_factor:2},
      enhance:{task_id:17,nonce:'a'.repeat(32),binding:'b'.repeat(64),artifact_id:'c'.repeat(32),sha256:'d'.repeat(64)}}}}]});
  render(<DecisionInboxPanel/>);
  await screen.findByText('source prompt');
  expect(screen.getByText(/Krea.*krea-2-medium.*1024x1024/)).toBeTruthy();
  expect(screen.getByText(/Enhance 2× may alter detail/)).toBeTruthy();
  expect(screen.getByText(/Source image task 17.*c{32}/)).toBeTruthy();
  expect(screen.getByText(/https:\/\/images.example.com\/source.png/)).toBeTruthy();
  expect(screen.queryByTitle('edit')).toBeNull();
  expect(screen.queryByTitle('dry-run preview')).toBeNull();
  expect(document.body.textContent).not.toContain('b'.repeat(64));
  expect(screen.getByRole('link',{name:'Watch image task'}).getAttribute('href')).toBe('/v2/console/images?image_task=31');
});

it('keeps a resumed Enhance job tied to its source and rejects an unrelated Enhance origin',async()=>{
  const body={model:'krea-2-large',prompt:'bound source prompt',size:'1536x1024',operation:'enhance',
    image_url:'https://images.example.com/bound.png',image_scaling_factor:2};
  const enhance={task_id:41,nonce:'a'.repeat(32),binding:'b'.repeat(64),artifact_id:'c'.repeat(32),sha256:'d'.repeat(64)};
  mockFetch({tasks:[
    {id:42,kind:'plugin.egress',title:'Enhance continuation',payload:{plugin:'cloud-image-krea',method:'GET',
      url:'https://api.krea.ai/jobs/job_42',image:{body,enhance,resume:{task_id:41,nonce:'e'.repeat(32),job_id:'job_42',binding:'f'.repeat(64)}}}},
    {id:43,kind:'plugin.egress',title:'Wrong Enhance origin',payload:{plugin:'cloud-image-krea',method:'POST',
      url:'https://evil.invalid/generate/enhance/krea/enhance',image:{body,enhance}}},
  ]});
  render(<DecisionInboxPanel/>);
  await screen.findByText('bound source prompt');
  expect(screen.getByText(/Enhance 2× may alter detail/)).toBeTruthy();
  expect(screen.getByText(/Source image task 41.*c{32}/)).toBeTruthy();
  expect(screen.getAllByRole('link',{name:'Watch image task'})).toHaveLength(1);
  expect(screen.getByTitle('edit')).toBeTruthy();
});

it.each([[1024,true],[1025,false]])('recognizes Krea Enhance only within the provider image URL cap (%s chars)',async(length,recognized)=>{
  const prefix='https://gen.krea.ai/images/';
  const imageUrl=prefix+'a'.repeat(length-prefix.length);
  expect(imageUrl).toHaveLength(length);
  mockFetch({tasks:[{id:44,kind:'plugin.egress',title:'Bound Krea Enhance',payload:{plugin:'cloud-image-krea',method:'POST',
    url:'https://api.krea.ai/generate/enhance/krea/enhance',image:{body:{model:'krea-2-medium',prompt:'bound prompt',
      size:'1024x1024',operation:'enhance',image_url:imageUrl,image_scaling_factor:2},
      enhance:{task_id:17,nonce:'a'.repeat(32),binding:'b'.repeat(64),artifact_id:'c'.repeat(32),sha256:'d'.repeat(64)}}}}]});
  render(<DecisionInboxPanel/>);
  await screen.findByText('Bound Krea Enhance');
  expect(screen.queryByRole('link',{name:'Watch image task'})!==null).toBe(recognized);
  expect(screen.queryByTitle('edit')!==null).toBe(!recognized);
});

it('shows fixed xAI and DeepInfra generation surfaces as immutable approvals',async()=>{
  mockFetch({tasks:[
    {id:27,kind:'plugin.egress',title:'xAI edit',payload:{plugin:'cloud-image-xai',method:'POST',url:'https://api.x.ai/v1/images/edits',
      image:{body:{model:'grok-imagine-image-2.0',prompt:'xAI exact prompt',size:'1024x1024',quality:'medium',references:['a'.repeat(32)]}}}},
    {id:28,kind:'plugin.egress',title:'DeepInfra image',payload:{plugin:'cloud-image-deepinfra',method:'POST',url:'https://api.deepinfra.com/v1/openai/images/generations',
      image:{body:{model:'owner/model',prompt:'DeepInfra exact prompt',size:'1024x1024'}}}},
  ]});
  render(<DecisionInboxPanel/>);
  await screen.findByText('xAI exact prompt');
  expect(screen.getByText(/xAI.*grok-imagine-image-2.0.*medium/)).toBeTruthy();
  expect(screen.getByText(/DeepInfra.*owner\/model/)).toBeTruthy();
  expect(screen.queryByTitle('edit')).toBeNull();
  expect(screen.queryByTitle('dry-run preview')).toBeNull();
});

it('distinguishes a bound Krea job GET from generation and a DeepInfra catalog GET from an image task',async()=>{
  mockFetch({tasks:[
    {id:29,kind:'plugin.egress',title:'Krea continuation',payload:{plugin:'cloud-image-krea',method:'GET',url:'https://api.krea.ai/jobs/job_23',
      image:{body:{model:'krea-2-medium',prompt:'original Krea prompt',size:'1024x1024',modality:'style_guided_generation',
        style_references_json:'[{"url":"https://images.example.com/style.png","strength":0.6}]'},
        resume:{task_id:22,nonce:'SECRET_NONCE',job_id:'job_23',binding:'SECRET_BINDING'}}}},
    {id:30,kind:'plugin.egress',title:'DeepInfra refresh',payload:{plugin:'cloud-image-deepinfra',method:'GET',
      url:'https://api.deepinfra.com/v1/openai/models?filter=true&sort_by=hermes',image:{body:{operation:'catalog_refresh',prompt:''}}}},
  ]});
  render(<DecisionInboxPanel/>);
  await screen.findByText('original Krea prompt');
  expect(screen.getByText(/Resume saved Krea job job_23 from image task 22/)).toBeTruthy();
  expect(screen.getByText(/saved job status GET after approval; no generation POST/)).toBeTruthy();
  expect(screen.getByText(/DeepInfra catalog refresh.*GET/)).toBeTruthy();
  expect(screen.getByText(/does not submit paid image generation/)).toBeTruthy();
  expect(screen.getAllByRole('link',{name:'Watch image task'})).toHaveLength(1);
  expect(document.body.textContent).not.toContain('SECRET_NONCE');
  expect(document.body.textContent).not.toContain('SECRET_BINDING');
  expect(screen.queryByTitle('edit')).toBeNull();
});

it('does not recognize arbitrary OpenRouter or Krea egress origins as image approvals', async()=>{
  mockFetch({tasks:[{id:23,kind:'plugin.egress',title:'Other egress',payload:{plugin:'cloud-image-krea',method:'POST',
    url:'https://evil.invalid/generate/image/krea/krea-2/medium',image:{body:{prompt:'untrusted target',model:'krea-2-medium'}}}}]});
  render(<DecisionInboxPanel/>);await screen.findByText('Other egress');
  expect(screen.queryByRole('link',{name:'Watch image task'})).toBeNull();
  expect(screen.getByTitle('edit')).toBeTruthy();
});

it('does not recognize an arbitrary token-bearing egress URL as a Codex image proposal',async()=>{
  mockFetch({tasks:[{id:20,kind:'plugin.egress',title:'Other egress',payload:{plugin:'cloud-image-codex',method:'POST',url:'https://evil.invalid/images/generations',image:{body:{prompt:'untrusted target',model:'gpt-image-2-medium'}}}}]});
  render(<DecisionInboxPanel/>);await screen.findByText('Other egress');
  expect(screen.queryByRole('link',{name:'Watch image task'})).toBeNull();
  expect(screen.getByTitle('edit')).toBeTruthy();
});

it('keeps a visible image return link after accepted task leaves inbox',async()=>{
  const task={id:17,kind:'plugin.egress',title:'Paid image',payload:{plugin:'cloud-image',method:'POST',url:'https://api.openai.com/v1/images/generations',image:{body:{prompt:'return me',model:'gpt-image-1.5',size:'1024x1024',quality:'low'}}}};
  let decided=false;
  global.fetch=vi.fn().mockImplementation(async(url,options)=>{
    if(options?.method==='POST') decided=true;
    return {ok:true,status:200,json:async()=>({tasks:decided?[]:[task]})};
  });
  render(<DecisionInboxPanel/>);await screen.findByText('return me');
  fireEvent.click(screen.getByTitle('accept'));
  await waitFor(()=>expect(screen.queryByText('return me')).toBeNull());
  expect(screen.getByRole('link',{name:'Watch decided image task'}).getAttribute('href')).toBe('/v2/console/images?image_task=17');
});

describe('H277 Decision Inbox advisory judge', () => {
  const task = { id: 31, title: 'Review transfer', kind: 'payment', risk_tier: 3, status: 'blocked' };
  const opinion = {
    score: 82, rationale: '<img src=x onerror=alert(1)> Check recipient.',
    flags: ['recipient_unverified', '<script>bad()</script>'], truncated: true,
    advisory: true, judge: { provider: 'ollama', model: 'qwen3', local: true }, at: '2026-09-27T12:00:00Z',
  };
  function queueFetch(read) {
    const fn = vi.fn(async url => ({ ok: true, status: 200,
      json: async () => String(url).includes('/autonomy/tasks?') ? read() : {} }));
    global.fetch = fn;
    return () => fn.mock.calls.filter(c => String(c[0]).includes('/autonomy/tasks?')).length;
  }
  async function mount() { await act(async () => { render(<DecisionInboxPanel />); }); }
  async function advance(ms) { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); }

  it.each(['deny', 'escalate'])('shows the smart %s verdict without a fabricated advisory risk score', async decision => {
    queueFetch(() => ({ tasks: [{ ...task, kind: 'toolrpc.terminal_run', judge: {
      decision, advisory: false, judge: { provider: 'lm-studio', model: 'guardian', local: true },
    } }] }));
    await mount();
    expect(screen.getByLabelText('Guardian terminal verdict')).toBeTruthy();
    expect(screen.getByText(decision === 'deny' ? /Guardian denied this command/ : /Guardian escalated this command/)).toBeTruthy();
    expect(screen.getByText(/lm-studio.*guardian.*local/)).toBeTruthy();
    expect(screen.queryByText(/Risk score/)).toBeNull();
    expect(screen.queryByText(/advisory only/)).toBeNull();
    expect(screen.getByText(/approval applies once/)).toBeTruthy();
    for (const title of ['accept', 'reject', 'defer', 'edit']) {
      expect(screen.getByTitle(title).disabled).toBe(false);
    }
  });

  it('labels an opted-in pending terminal review as guardian work', async () => {
    queueFetch(() => ({ tasks: [{ ...task, kind: 'toolrpc.terminal_run', judge_pending: true, judge_mode: 'smart' }] }));
    await mount();
    expect(screen.getByText(/Guardian review pending/)).toBeTruthy();
    expect(screen.queryByText(/Advisory model opinion pending/)).toBeNull();
    expect(screen.getByTitle('accept').disabled).toBe(false);
  });

  it('renders an escaped, attributed risk opinion as advisory while keeping decisions available', async () => {
    queueFetch(() => ({ tasks: [{ ...task, judge: opinion }], judge: { configured: true, timeout: 20 } }));
    await mount();
    expect(screen.getByText(/advisory.*you decide/i)).toBeTruthy();
    expect(screen.getByText(/risk score.*82\/100/i)).toBeTruthy();
    expect(screen.getByText(/ollama.*qwen3.*local/i)).toBeTruthy();
    expect(screen.getByText(opinion.rationale)).toBeTruthy();
    expect(screen.getByText('recipient_unverified')).toBeTruthy();
    expect(screen.getByText('<script>bad()</script>')).toBeTruthy();
    expect(screen.getByText(/shortened/i)).toBeTruthy();
    expect(document.querySelector('#decision-inbox img, #decision-inbox script')).toBeNull();
    for (const title of ['accept', 'reject', 'defer', 'edit', 'dry-run preview']) {
      expect(screen.getByTitle(title).disabled).toBe(false);
    }
  });

  it('polls a pending card for a late opinion then stops once it arrives', async () => {
    vi.useFakeTimers();
    let ready = false;
    const calls = queueFetch(() => ({ tasks: [{ ...task, judge_pending: !ready, ...(ready ? { judge: opinion } : {}) }], judge: { configured: true, timeout: 1 } }));
    await mount();
    expect(screen.getByText(/advisory.*pending/i)).toBeTruthy();
    expect(screen.getByTitle('accept').disabled).toBe(false);
    ready = true;
    await advance(3000);
    expect(screen.getByText(opinion.rationale)).toBeTruthy();
    const done = calls();
    await advance(12000);
    expect(calls()).toBe(done);
  });

  it('does not poll merely because judge is configured or a task lacks an opinion', async () => {
    vi.useFakeTimers();
    const calls = queueFetch(() => ({ tasks: [task], judge: { configured: true, timeout: 1 } }));
    await mount();
    await advance(30000);
    expect(calls()).toBe(1);
    expect(screen.queryByText(/advisory.*pending/i)).toBeNull();
  });

  it('keeps a per-card wall deadline across unrelated refresh and still displays a later opinion', async () => {
    vi.useFakeTimers();
    let ready = false;
    const calls = queueFetch(() => ({ tasks: [{ ...task, judge_pending: !ready, ...(ready ? { judge: opinion } : {}) }], judge: { configured: true, timeout: 1 } }));
    await mount();
    await advance(18000);
    await act(async () => { window.dispatchEvent(new Event('nerva:image-proposed')); });
    await advance(6000);
    const expired = calls();
    await advance(30000);
    expect(calls()).toBe(expired);
    expect(screen.getByText(/advisory.*taking longer/i)).toBeTruthy();
    ready = true;
    await act(async () => { window.dispatchEvent(new Event('nerva:image-proposed')); });
    expect(screen.getByText(opinion.rationale)).toBeTruthy();
  });

  it('gives a newly arriving pending card its own budget after an earlier card expires', async () => {
    vi.useFakeTimers();
    let later = false;
    let ready = false;
    const calls = queueFetch(() => ({ tasks: [
      { ...task, judge_pending: true },
      ...(later ? [{ ...task, id: 32, title: 'Later transfer', judge_pending: !ready, ...(ready ? { judge: { ...opinion, rationale: 'Later opinion' } } : {}) }] : []),
    ], judge: { configured: true, timeout: 1 } }));
    await mount();
    await advance(24000);
    later = true;
    await act(async () => { window.dispatchEvent(new Event('nerva:image-proposed')); });
    const before = calls();
    ready = true;
    await advance(3000);
    expect(calls()).toBe(before + 1);
    expect(screen.getByText('Later opinion')).toBeTruthy();
    await advance(30000);
    expect(calls()).toBe(before + 1);
  });

  it('uses the default timeout when server metadata is missing and cleans up on unmount', async () => {
    vi.useFakeTimers();
    const calls = queueFetch(() => ({ tasks: [{ ...task, judge_pending: true }] }));
    await mount();
    await advance(24000);
    expect(calls()).toBeGreaterThan(1);
    cleanup();
    const stopped = calls();
    await advance(60000);
    expect(calls()).toBe(stopped);
  });

  it('never sends a judge read after a browser-delayed timer exceeds the wall cap', async () => {
    vi.useFakeTimers();
    const calls = queueFetch(() => ({ tasks: [{ ...task, judge_pending: true }], judge: { configured: true, timeout: 1 } }));
    await mount();
    vi.setSystemTime(Date.now() + 60000);
    await advance(3000);
    expect(calls()).toBe(1);
    expect(screen.getByText(/advisory.*taking longer/i)).toBeTruthy();
  });

  it('keeps approval payload unchanged despite a high-risk advisory opinion', async () => {
    const fn = mockFetch({ tasks: [{ ...task, judge: opinion, judge_pending: true }], judge: { configured: true, timeout: 1 } });
    await mount();
    fireEvent.click(screen.getByTitle('accept'));
    await waitFor(() => expect(fn.mock.calls.some(c => c[0] === '/autonomy/tasks/31/decision'
      && c[1]?.method === 'POST' && c[1]?.body === '{"action":"accept"}')).toBe(true));
  });

  it('stops polling when pending clears without an opinion and resumes within the original budget', async () => {
    vi.useFakeTimers();
    let pending = true;
    const calls = queueFetch(() => ({ tasks: [{ ...task, judge_pending: pending }], judge: { configured: true, timeout: 1 } }));
    await mount();
    await advance(15000);
    pending = false;
    await act(async () => { window.dispatchEvent(new Event('nerva:image-proposed')); });
    const stopped = calls();
    await advance(3000);
    expect(calls()).toBe(stopped);
    pending = true;
    await act(async () => { window.dispatchEvent(new Event('nerva:image-proposed')); });
    await advance(6000);
    const expired = calls();
    await advance(30000);
    expect(calls()).toBe(expired);
    expect(screen.getByText(/advisory.*taking longer/i)).toBeTruthy();
  });
});
