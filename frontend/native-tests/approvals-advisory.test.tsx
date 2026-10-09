import React from 'react';
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AppearanceProvider } from '../../mobile/src/context/AppearanceContext';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import { ApprovalsScreen } from '../../mobile/src/screens/ApprovalsScreen';
import { records } from './support/storage';

const config = { baseUrl: 'https://first.test', token: 'user', adminToken: 'owner' };
const key = 'jarvis.server.config.v1';
const response = (data: unknown) => ({ ok: true, status: 200, json: async () => data }) as Response;
const queue = (tasks: unknown[]) => ({ pending: tasks, reversible: [], irreversible: tasks, counts: { total: tasks.length, reversible: 0, irreversible: tasks.length } });
const task = { id: 31, title: 'Review payment', kind: 'payment', status: 'blocked', risk_tier: 3 };
let server: ReturnType<typeof useServer>;
function Capture() { server = useServer(); return null; }
function mount() { return render(<ServerProvider><AppearanceProvider><Capture/><ApprovalsScreen onGoToSettings={() => {}}/></AppearanceProvider></ServerProvider>); }

beforeEach(() => {
  records.clear();
  records.set(key, JSON.stringify({ version: 2, config, appearance: null, chatScope: 'first-scope' }));
  vi.useRealTimers();
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it('renders an opinion with score, identity, rationale and warnings while leaving the owner buttons available', async () => {
  global.fetch = vi.fn(async url => response(String(url).endsWith('/autonomy/approvals') ? queue([{
    ...task, judge: { score: 82, rationale: 'Possible duplicate transfer', flags: ['prompt injection'], truncated: true,
      advisory: true, judge: { provider: 'ollama', model: 'qwen', local: true } },
  }]) : { roles: [], reachable: null }));
  const view = mount();
  await waitFor(() => expect(view.getByText(/Possible duplicate transfer/)).toBeTruthy());
  expect(view.getByText(/advisory only/i)).toBeTruthy();
  expect(view.getByText(/82\/100.*ollama.*qwen.*local/)).toBeTruthy();
  expect(view.getByText(/shortened copy/)).toBeTruthy();
  expect(view.getByText(/prompt injection/)).toBeTruthy();
  expect(view.getByText('Approve')).toBeTruthy();
  expect(view.getByText('Reject')).toBeTruthy();
  expect(view.getByText('Defer')).toBeTruthy();
});

it('keeps an ordinary card actionable with no judge and labels pending opinions as optional', async () => {
  global.fetch = vi.fn(async url => response(String(url).endsWith('/autonomy/approvals') ? queue([
    task, { ...task, id: 32, title: 'Review document', judge_pending: true },
  ]) : { roles: [], reachable: null }));
  const view = mount();
  await waitFor(() => expect(view.getByText('Review document')).toBeTruthy());
  expect(view.queryByText(/Risk score/)).toBeNull();
  expect(view.getByText(/opinion pending.*you can decide now/i)).toBeTruthy();
  expect(view.getAllByText('Approve')).toHaveLength(2);
});

it('shows model role configuration without claiming connectivity or changing it', async () => {
  global.fetch = vi.fn(async url => response(String(url).endsWith('/api/llm/roles') ? {
    roles: [{ role: 'approval_judge', configured: true, provider: 'ollama', model: 'qwen', local: true }], reachable: null,
  } : queue([])));
  const view = mount();
  await waitFor(() => expect(view.getByText(/approval_judge/)).toBeTruthy());
  expect(view.getByText(/configuration only/i)).toBeTruthy();
  expect(view.getByText(/Connectivity has not been checked/)).toBeTruthy();
  expect(view.queryByText(/connected|reachable|online/i)).toBeNull();
  expect((fetch as ReturnType<typeof vi.fn>).mock.calls.some(([url, init]) => String(url).endsWith('/api/llm/roles') && init.method === 'GET')).toBe(true);
});

it('discards old hub role responses after credentials change', async () => {
  let finishRoles!: (value: Response) => void;
  global.fetch = vi.fn(async url => {
    if (String(url).startsWith('https://first.test/api/llm/roles')) return new Promise<Response>(resolve => { finishRoles = resolve; });
    return response(String(url).endsWith('/api/llm/roles') ? { roles: [], reachable: null } : queue([]));
  });
  const view = mount();
  await waitFor(() => expect(finishRoles).toBeDefined());
  await act(async () => server.updateConfig({ ...config, baseUrl: 'https://second.test' }));
  await act(async () => { finishRoles(response({ roles: [{ role: 'old role', configured: true }], reachable: null })); });
  expect(view.queryByText('old role')).toBeNull();
});

it('leaves the owner decision action and payload unchanged when an opinion is present', async () => {
  global.fetch = vi.fn(async url => response(String(url).endsWith('/autonomy/approvals') ? queue([{
    ...task, judge: { score: 99, rationale: 'High risk', judge: { provider: 'ollama', model: 'qwen', local: true } },
  }]) : { roles: [], reachable: null }));
  const view = mount();
  await waitFor(() => expect(view.getByText('Review payment')).toBeTruthy());
  await act(async () => fireEvent.click(view.getByText('Approve')));
  expect(fetch).toHaveBeenCalledWith('https://first.test/autonomy/tasks/31/decision', expect.objectContaining({
    method: 'POST', body: JSON.stringify({ action: 'accept' }),
    headers: expect.objectContaining({ 'X-Admin-Token': 'owner' }),
  }));
});

it('keeps the owner card usable when opinion fields have invalid runtime shapes', async () => {
  global.fetch = vi.fn(async url => response(String(url).endsWith('/autonomy/approvals') ? queue([{
    ...task, judge: { score: Infinity, rationale: { injected: 'object' }, flags: [{ malicious: true }],
      judge: { provider: { bad: true }, model: ['bad'], local: 'maybe' } },
  }]) : { roles: [], reachable: null }));
  const view = mount();
  await waitFor(() => expect(view.getByText('Review payment')).toBeTruthy());
  expect(view.getByText(/Risk score unavailable/)).toBeTruthy();
  expect(view.getByText('No rationale supplied.')).toBeTruthy();
  expect(view.queryByText(/\[object Object\]/)).toBeNull();
  expect(view.getByText('Approve')).toBeTruthy();
  expect(view.getByText('Reject')).toBeTruthy();
});

it('shows loading and a true empty roles state, then refreshes on demand', async () => {
  let finish!: (value: Response) => void;
  const fetcher = vi.fn(async url => String(url).endsWith('/api/llm/roles')
    ? new Promise<Response>(resolve => { finish = resolve; }) : response(queue([])));
  global.fetch = fetcher;
  const view = mount();
  await waitFor(() => expect(view.getByText(/Loading model roles/)).toBeTruthy());
  await act(async () => finish(response({ roles: [], reachable: null })));
  expect(view.getByText(/No model roles configured/)).toBeTruthy();
  fireEvent.click(view.getByText('Refresh roles'));
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith('/api/llm/roles'))).toHaveLength(2));
});

it('offers retry after a malformed roles response and clears the old failure on success', async () => {
  let reads = 0;
  global.fetch = vi.fn(async url => response(String(url).endsWith('/api/llm/roles')
    ? ++reads === 1 ? { bad: true } : { roles: [{ role: 'approval_judge', configured: false, reason: 'unset' }], reachable: null }
    : queue([])));
  const view = mount();
  await waitFor(() => expect(view.getByText(/Invalid model roles response/)).toBeTruthy());
  fireEvent.click(view.getByText('Retry roles'));
  await waitFor(() => expect(view.getByText(/approval_judge/)).toBeTruthy());
  expect(view.queryByText(/Invalid model roles response/)).toBeNull();
});

it('does not render a role response that arrives after unmount', async () => {
  let finish!: (value: Response) => void;
  global.fetch = vi.fn(async url => String(url).endsWith('/api/llm/roles')
    ? new Promise<Response>(resolve => { finish = resolve; }) : response(queue([])));
  const view = mount();
  await waitFor(() => expect(finish).toBeDefined());
  view.unmount();
  await act(async () => finish(response({ roles: [{ role: 'late', configured: true }], reachable: null })));
  expect(view.container.textContent).toBe('');
});
