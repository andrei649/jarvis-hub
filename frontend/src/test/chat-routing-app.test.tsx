import React from 'react';
import { webcrypto } from 'node:crypto';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import App from '../app';

const sent = vi.hoisted(() => [] as Array<{ message: string; agent: string; board_references?: any[]; attachments?: any[]; allow_board_cloud?: boolean; _admin?: boolean }>);
const refusal = vi.hoisted(() => ({ enabled: false, attachmentLimit: false }));
const historyTurns = vi.hoisted(() => [] as Array<{ role: string; content: string; agent_id?: string }>);
const roster = [
  { id: 'jarvis', name: 'Jarvis', rosterSource: 'api', chat_routing: 'orchestrated', enabled: true },
  { id: 'frigga', name: 'Frigga', rosterSource: 'api', chat_routing: 'local', enabled: true },
];
const liveRoster = vi.hoisted(() => ({ agents: [] as any[], refresh: null as null | (() => Promise<void>) }));
const savedCredential = () => JSON.parse(sessionStorage.getItem('nerva.chat.recipient') || 'null')?.credential;
vi.mock('../voice', () => ({ useVoice: () => ({ active: false, toggle: () => {} }) }));
vi.mock('../mesh', () => ({ NeuralMesh: () => null, isExecutingAgent: () => false }));
vi.mock('../analytics', () => ({ initAnalytics: () => {}, trackPageview: () => {} }));
vi.mock('../gap', () => ({ FirstRunGate: () => null }));
vi.mock('../api/live', () => ({ PREVIEW_MODE_LIVE_KEYS: {}, useLiveModes: () => ({ live: {} }) }));
vi.mock('../api/loaders', () => ({
  loadJarvisData: async (demo: boolean) => ({
    agents: demo ? [] : liveRoster.agents, ticker: [], tasks: [], calendar: [], heartbeat: [], weather: null,
    sys: null, live: !demo, serverUp: true, sources: { agents: !demo, tasks: false, trust: false },
    llm: { state: 'unknown', model: null, residents: [] }, trust: { mic: 'on', strict_local: false },
  }),
  createLatestRefreshRunner: ({ loadData, commitData }: any) => {
    const refresh = async () => commitData(await loadData());
    liveRoster.refresh = refresh;
    return { refresh, stop: () => {} };
  },
}));
vi.mock('../api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiGet: async (path: string, options: any) => path === '/memory' ? { turns: historyTurns } : path.startsWith('/api/kanban') ? actual.apiGet(path, options) : {}, postStream: async (_url: string, body: any, event: (frame: any) => void, options: any) => {
    sent.push({ ...body, _admin: options?.admin });
    if (refusal.attachmentLimit) throw { body: { detail: 'attachment_limit' }, status: 413 };
    if (refusal.enabled) throw { body: { detail: 'chat_agent_unavailable' }, status: 409 };
    event({ type: 'end', text: 'Done', agent: body.agent,
      ...(body.board_references ? { board_sources: body.board_references.map(({ board, task_id, source, sha256 }: any) => ({ board, task_id, source, sha256 })) } : {}) });
  } };
});

beforeEach(() => {
  vi.stubGlobal('crypto', webcrypto);
  localStorage.clear();
  sessionStorage.clear();
  liveRoster.agents = roster;
  liveRoster.refresh = null;
  history.replaceState(null, '', '/v2/chat');
  sent.length = 0;
  historyTurns.length = 0;
  refusal.enabled = false;
  refusal.attachmentLimit = false;
});

it('keeps a reviewed Office passage and the question after a size refusal and sends them on explicit retry', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => String(url).includes('/office-preview')
    ? Response.json({ kind: 'docx', total_segments: 1, segments: [{ label: 'Document', text: 'Private neighbor. Approved cost: 93.', truncated: false }] })
    : Response.json({})));
  render(<App />);
  await screen.findByRole('combobox', { name: 'Selected agent' });
  const input = document.querySelector<HTMLInputElement>('[data-composer="1"]')!;
  fireEvent.change(input, { target: { value: 'What did we approve?' } });
  fireEvent.change(document.querySelector('input.office-file-input')!, {
    target: { files: [new File(['sample'], 'Approval.docx')] },
  });
  const area = await screen.findByRole('textbox', { name: 'Select a passage' }) as HTMLTextAreaElement;
  area.setSelectionRange(area.value.indexOf('Approved'), area.value.length);
  fireEvent.click(screen.getByRole('button', { name: 'Attach selected text' }));
  fireEvent.click(screen.getByRole('button', { name: 'Done reviewing' }));
  refusal.attachmentLimit = true;
  fireEvent.keyDown(input, { key: 'Enter' });
  const limit = await screen.findByText(/attachment limit/i);
  expect(limit).toBeTruthy();
  expect(input.value).toBe('What did we approve?');
  expect(sent[0]).toMatchObject({ message: input.value, require_full_attachments: true,
    attachments: [{ name: 'Approval.docx', text: 'Approved cost: 93.' }] });
  refusal.attachmentLimit = false;
  fireEvent.keyDown(input, { key: 'Enter' });
  await waitFor(() => expect(input.value).toBe(''));
  expect(sent).toHaveLength(2);
  expect(sent[1]).toEqual(sent[0]);
});

it('only offers to teach from restored assistant turns with a recorded author', async () => {
  sessionStorage.removeItem('nerva.chat.session_id');
  historyTurns.push({ role: 'system', agent_id: 'jarvis', content: 'Session notice' },
    { role: 'assistant', content: 'Legacy turn' }, { role: 'assistant', agent_id: 'frigga', content: 'Check the printed proofs' });
  render(<App />);
  await screen.findByText('Legacy turn');
  const teach = screen.getAllByRole('button', { name: 'Teach skill' });
  expect(teach).toHaveLength(1);
  expect(teach[0].closest('.msg')?.textContent).toContain('Check the printed proofs');
});

it('sends two reviewed board references as structured owner input and renders their recorded source controls', async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
  const digest = 'a'.repeat(64);
  const cards = [
    { id: 't_one', title: 'Same title', status: 'done', result: 'South', board_source_sha256: digest },
    { id: 't_two', title: 'Same title', status: 'done', latest_summary: 'North', board_source_sha256: digest },
  ];
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/api/kanban/boards')) return Response.json({ current: 'alpha', boards: [{ slug: 'alpha', name: 'Alpha' }] });
    if (url.includes('/api/kanban/board?')) return Response.json({ columns: [{ name: 'done', tasks: cards }] });
    const card = cards.find(item => url.includes('/tasks/' + item.id + '?'));
    return Response.json(card ? { task: card } : {});
  }));
  render(<App />);
  const picker = await screen.findByRole('combobox', { name: 'Selected agent' });
  fireEvent.change(picker, { target: { value: 'frigga' } });
  await waitFor(() => expect((screen.getByRole('button', { name: 'Attach board result' }) as HTMLButtonElement).disabled).toBe(false));
  for (const card of cards) {
    fireEvent.click(screen.getByRole('button', { name: 'Attach board result' }));
    const taskPicker = await screen.findByRole('combobox', { name: 'Completed task' });
    await waitFor(() => expect((taskPicker as HTMLSelectElement).disabled).toBe(false));
    fireEvent.change(taskPicker, { target: { value: card.id } });
    fireEvent.click(await screen.findByRole('button', { name: 'Attach full result' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Attach completed task result' })).toBeNull());
  }
  const draft = document.querySelector<HTMLInputElement>('[data-composer="1"]')!;
  fireEvent.change(draft, { target: { value: 'Compare sources' } });
  fireEvent.keyDown(draft, { key: 'Enter' });
  await waitFor(() => expect(sent).toHaveLength(1));
  expect(sent[0]).toMatchObject({ _admin: true, message: 'Compare sources', agent: 'frigga',
    board_references: [
      { board: 'alpha', task_id: 't_one', source: 'result', excerpt: 'South', sha256: digest },
      { board: 'alpha', task_id: 't_two', source: 'latest_summary', excerpt: 'North', sha256: digest },
    ] });
  expect(sent[0].attachments).toBeUndefined();
  expect(sent[0].allow_board_cloud).toBeUndefined();
  expect(await screen.findByRole('button', { name: 'Recorded result · alpha/t_one' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Latest summary · alpha/t_two' })).toBeTruthy();
});

it('shows the specific unavailable-agent refusal with a next action', async () => {
  refusal.enabled = true;
  render(<App />);
  await screen.findByRole('combobox', { name: 'Selected agent' });
  const draft = document.querySelector<HTMLInputElement>('[data-composer="1"]')!;
  fireEvent.change(draft, { target: { value: 'Please help' } });
  fireEvent.keyDown(draft, { key: 'Enter' });
  await waitFor(() => expect(screen.getByText(/selected agent is no longer available/)).toBeTruthy());
  expect(screen.getByText(/choose an enabled agent, and send again/)).toBeTruthy();
  expect(screen.queryByText(/model backend is unreachable/)).toBeNull();
});

it('drops the live picker and policy immediately across Demo and live loading boundaries', async () => {
  render(<App />);
  await screen.findByRole('combobox', { name: 'Selected agent' });
  history.replaceState(null, '', '/v2/chat?demo=1');
  fireEvent.popState(window);
  expect(await screen.findByText('Routing policy · Demo sample')).toBeTruthy();
  expect(screen.queryByRole('combobox', { name: 'Selected agent' })).toBeNull();
  history.replaceState(null, '', '/v2/chat');
  fireEvent.popState(window);
  await waitFor(() => expect(screen.queryByText('Routing policy · Demo sample')).toBeNull());
  await screen.findByRole('combobox', { name: 'Selected agent' });
  expect(screen.getByText('Routing policy · Orchestrated')).toBeTruthy();
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it.each([false, true])('selects an authenticated agent from %s floating Chat and sends to it without losing the draft', async floating => {
  render(<App floating={floating} />);
  const picker = await screen.findByRole('combobox', { name: 'Selected agent' });
  const draft = document.querySelector<HTMLInputElement>('[data-composer="1"]')!;
  fireEvent.change(draft, { target: { value: 'Keep this draft' } });
  fireEvent.change(picker, { target: { value: 'frigga' } });
  expect(draft.value).toBe('Keep this draft');
  expect(screen.getByText('Routing policy · Local')).toBeTruthy();
  expect(screen.queryByRole('dialog', { name: /Frigga/i })).toBeNull();
  fireEvent.keyDown(draft, { key: 'Enter' });
  await waitFor(() => expect(sent).toEqual([expect.objectContaining({ message: 'Keep this draft', agent: 'frigga' })]));
});

it('restores the exact next recipient after a same-tab reload and sends to it', async () => {
  const first = render(<App />);
  fireEvent.change(await screen.findByRole('combobox', { name: 'Selected agent' }), { target: { value: 'frigga' } });
  await waitFor(() => expect(savedCredential()).toHaveLength(64));
  first.unmount();
  render(<App />);
  await waitFor(() => expect((screen.getByRole('combobox', { name: 'Selected agent' }) as HTMLSelectElement).value).toBe('frigga'));
  const draft = document.querySelector<HTMLInputElement>('[data-composer="1"]')!;
  fireEvent.change(draft, { target: { value: 'Continue with Frigga' } });
  fireEvent.keyDown(draft, { key: 'Enter' });
  await waitFor(() => expect(sent[sent.length - 1]?.agent).toBe('frigga'));
});

it('does not reuse a saved recipient across guest credentials', async () => {
  localStorage.setItem('hud.user_token', 'guest-one');
  const first = render(<App />);
  fireEvent.change(await screen.findByRole('combobox', { name: 'Selected agent' }), { target: { value: 'frigga' } });
  await waitFor(() => expect(savedCredential()).toHaveLength(64));
  first.unmount();
  localStorage.setItem('hud.user_token', 'guest-two');
  render(<App />);
  await screen.findByRole('combobox', { name: 'Selected agent' });
  await waitFor(() => expect((screen.getByRole('combobox', { name: 'Selected agent' }) as HTMLSelectElement).value).not.toBe('frigga'));
  expect(localStorage.getItem('nerva.chat.recipient')).toBeNull();
});

it('requires a new choice when a saved recipient leaves the authenticated roster', async () => {
  const first = render(<App />);
  fireEvent.change(await screen.findByRole('combobox', { name: 'Selected agent' }), { target: { value: 'frigga' } });
  await waitFor(() => expect(savedCredential()).toHaveLength(64));
  first.unmount();
  liveRoster.agents = [roster[0]];
  render(<App />);
  const picker = await screen.findByRole('combobox', { name: 'Selected agent' }) as HTMLSelectElement;
  await waitFor(() => expect(picker.value).toBe(''));
  expect(picker.selectedOptions[0].textContent).toContain('Choose an agent before sending');
  const draft = document.querySelector<HTMLInputElement>('[data-composer="1"]')!;
  fireEvent.change(draft, { target: { value: 'Do not silently send' } });
  fireEvent.keyDown(draft, { key: 'Enter' });
  expect(sent).toHaveLength(0);
  fireEvent.change(picker, { target: { value: 'jarvis' } });
  fireEvent.keyDown(draft, { key: 'Enter' });
  await waitFor(() => expect(sent).toEqual([expect.objectContaining({ agent: 'jarvis' })]));
});

it('requires a new choice when guest credentials change in the same tab', async () => {
  localStorage.setItem('hud.user_token', 'guest-one');
  render(<App />);
  const picker = await screen.findByRole('combobox', { name: 'Selected agent' }) as HTMLSelectElement;
  fireEvent.change(picker, { target: { value: 'frigga' } });
  await waitFor(() => expect(savedCredential()).toHaveLength(64));
  localStorage.setItem('hud.user_token', 'guest-two');
  const draft = document.querySelector<HTMLInputElement>('[data-composer="1"]')!;
  fireEvent.change(draft, { target: { value: 'Still here' } });
  fireEvent.keyDown(draft, { key: 'Enter' });
  await waitFor(() => expect(picker.value).toBe(''));
  expect(sent).toHaveLength(0);
  fireEvent.change(picker, { target: { value: 'jarvis' } });
  fireEvent.keyDown(draft, { key: 'Enter' });
  await waitFor(() => expect(sent).toEqual([expect.objectContaining({ agent: 'jarvis' })]));
});

it.each(['/v2/chat', '/v2/cockpit'])('shows pending recipient verification and preserves the draft in %s', async path => {
  const first = render(<App />);
  fireEvent.change(await screen.findByRole('combobox', { name: 'Selected agent' }), { target: { value: 'frigga' } });
  await waitFor(() => expect(savedCredential()).toHaveLength(64));
  first.unmount();
  liveRoster.agents = [];
  history.replaceState(null, '', path);
  render(<App />);
  const draft = document.querySelector<HTMLInputElement>('[data-composer="1"]')!;
  fireEvent.change(draft, { target: { value: 'Keep the draft while checking' } });
  const send = document.querySelector<HTMLButtonElement>('.inputbar .transmit')!;
  expect(send.disabled).toBe(true);
  expect(screen.getByText('Checking the selected agent…')).toBeTruthy();
  expect(send.getAttribute('aria-describedby')).toBe(screen.getByText('Checking the selected agent…').id);
  liveRoster.agents = roster;
  await act(async () => { await liveRoster.refresh?.(); });
  await waitFor(() => expect(send.disabled).toBe(false));
  expect(draft.value).toBe('Keep the draft while checking');
});

it('clears the saved recipient on an explicit conversation switch', async () => {
  const first = render(<App />);
  fireEvent.change(await screen.findByRole('combobox', { name: 'Selected agent' }), { target: { value: 'frigga' } });
  await waitFor(() => expect(savedCredential()).toHaveLength(64));
  act(() => window.dispatchEvent(new CustomEvent('nerva:session-selected', { detail: { sessionId: 'another', turns: [] } })));
  first.unmount();
  render(<App />);
  await waitFor(() => expect((screen.getByRole('combobox', { name: 'Selected agent' }) as HTMLSelectElement).value).not.toBe('frigga'));
});
