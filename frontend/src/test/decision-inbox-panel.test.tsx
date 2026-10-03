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
