import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ChatScreen } from '../../mobile/src/screens/ChatScreen';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import { compareAgents, type AgentOpinion } from '../../mobile/src/api/agentOpinions';
import { records } from './support/storage';

vi.mock('../../mobile/src/api/agentOpinions', () => ({ compareAgents: vi.fn() }));

const config = { baseUrl: 'https://hub.test', token: 'reader', adminToken: 'owner' };
const agents = [{ id: 'jarvis', name: 'Jarvis' }, { id: 'frigga', name: 'Frigga' }];
const target = { id: 'v1-' + 'a'.repeat(64), vault: 'Studio', inbox: 'Inbox' };
const compare = vi.mocked(compareAgents);
const reply = (data: unknown, status = 200) => ({ ok: status === 200, status, json: async () => data });
const writes: Record<string, string>[] = [];
let saveStatus = 200;
let server: ReturnType<typeof useServer>;
function ConnectedChat() {
  server = useServer();
  return <ChatScreen onGoToSettings={() => {}} />;
}
async function openComparison() {
  render(<ServerProvider><ConnectedChat /></ServerProvider>);
  await screen.findByText('A previous private message');
  fireEvent.change(screen.getByPlaceholderText(/Message /), { target: { value: 'My unsent draft' } });
  fireEvent.click(screen.getByLabelText('Compare agents'));
  const question = await screen.findByLabelText('Comparison question') as HTMLTextAreaElement;
  expect(question.value).toBe('My unsent draft');
  await waitFor(() => expect((screen.getByLabelText('Compare answers') as HTMLButtonElement).disabled).toBe(false));
  expect(compare).not.toHaveBeenCalled();
  return question;
}
beforeEach(() => {
  writes.length = 0;
  saveStatus = 200;
  compare.mockReset();
  records.clear();
  records.set('jarvis.server.config.v1', JSON.stringify({ version: 2, config, appearance: null, chatScope: 'one' }));
  records.set('jarvis.chat.conversation.v2', JSON.stringify({ version: 2, scope: 'one', sessionId: 'thread',
    messages: [{ id: 'old', role: 'user', text: 'A previous private message' }] }));
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    if (String(url).endsWith('/api/os/status')) return reply({ ok: true, captureTarget: target });
    if (String(url).includes('/api/os/brain/note?')) {
      const params = new URL(url).searchParams;
      expect(params.get('relPath')).toBe('Inbox/Reviewed.md');
      expect(params.get('targetId')).toBe(target.id);
      return reply({ ok: true, targetId: target.id, relPath: 'Inbox/Reviewed.md', body: 'Later edit in Obsidian' });
    }
    if (String(url).endsWith('/api/os/brain/chat-note')) {
      writes.push(JSON.parse(String(init.body)));
      return reply({ ok: true, relPath: 'Inbox/Reviewed.md', source: null }, saveStatus);
    }
    return reply({ agents });
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('compares only the reviewed question and saves one attributed answer without changing the draft', async () => {
  compare.mockResolvedValue([{ agent: 'jarvis', ok: true, text: 'First finding', model: 'model-A', route: 'local' },
    { agent: 'frigga', ok: true, text: 'Separate finding', model: 'model-B', route: 'local' }]);
  const question = await openComparison();
  fireEvent.change(question, { target: { value: 'Reviewed question' } });
  fireEvent.click(screen.getByLabelText('Compare answers'));
  await screen.findByText('Separate finding');
  expect(compare).toHaveBeenCalledTimes(1);
  expect(compare.mock.calls[0].slice(0, 4)).toEqual([config, 'Reviewed question', ['jarvis', 'frigga'], false]);
  fireEvent.click(screen.getByLabelText('Save Jarvis answer to Obsidian'));
  await screen.findByText('Studio');
  expect((screen.getByLabelText('Note title') as HTMLInputElement).value).toContain('Jarvis');
  const note = screen.getByLabelText('Note content') as HTMLTextAreaElement;
  for (const text of ['Reviewed question', 'Jarvis', 'model-A', 'local', 'First finding']) expect(note.value).toContain(text);
  for (const text of ['Separate finding', 'model-B', 'A previous private message', 'My unsent draft']) expect(note.value).not.toContain(text);
  fireEvent.change(note, { target: { value: 'My edited note' } });
  fireEvent.click(screen.getByLabelText('Save note'));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0].content).toBe('My edited note');
  await screen.findByText('Saved: Inbox/Reviewed.md');
  fireEvent.click(screen.getByLabelText('Close Save to Obsidian'));
  fireEvent.click(await screen.findByLabelText('Open Jarvis saved note'));
  await screen.findByText('Later edit in Obsidian');
  fireEvent.click(screen.getByLabelText('Close saved note'));
  fireEvent.click(await screen.findByLabelText('Close comparison'));
  expect((screen.getByPlaceholderText(/Message /) as HTMLTextAreaElement).value).toBe('My unsent draft');
  expect(screen.getByText('A previous private message')).toBeTruthy();
  expect(screen.queryByText('First finding')).toBeNull();
  expect(writes).toHaveLength(1);
  expect(compare).toHaveBeenCalledTimes(1);
});

it('shows one agent list at a time and lets the owner exchange the two selected agents', async () => {
  compare.mockResolvedValue([{ agent: 'frigga', ok: true, text: 'First result' }, { agent: 'jarvis', ok: false, reason: 'timed_out' }]);
  await openComparison();
  expect(screen.queryByLabelText('Choose Frigga as first agent')).toBeNull();
  fireEvent.click(screen.getByLabelText('First agent: Jarvis'));
  expect(screen.queryByLabelText('Choose Jarvis as second agent')).toBeNull();
  fireEvent.click(screen.getByLabelText('Choose Frigga as first agent'));
  expect(screen.getByLabelText('Second agent: Jarvis')).toBeTruthy();
  expect(screen.queryByLabelText('Choose Frigga as first agent')).toBeNull();
  fireEvent.click(screen.getByLabelText('Allow approved cloud models for this question'));
  fireEvent.click(screen.getByLabelText('Compare answers'));
  await screen.findByText('First result');
  expect(compare.mock.calls[0].slice(1, 4)).toEqual(['My unsent draft', ['frigga', 'jarvis'], true]);
  fireEvent.click(screen.getByLabelText('Compare answers'));
  await waitFor(() => expect(compare).toHaveBeenCalledTimes(2));
  expect(compare.mock.calls[1][3]).toBe(false);
});

it('retries the exact edited note after an uncertain write without re-running either agent', async () => {
  compare.mockResolvedValue([{ agent: 'jarvis', ok: true, text: 'Selected answer' },
    { agent: 'frigga', ok: true, text: 'Other answer' }]);
  await openComparison();
  fireEvent.click(screen.getByLabelText('Compare answers'));
  fireEvent.click(await screen.findByLabelText('Save Jarvis answer to Obsidian'));
  await screen.findByText('Studio');
  fireEvent.change(screen.getByLabelText('Note title'), { target: { value: 'Reviewed' } });
  fireEvent.change(screen.getByLabelText('Note content'), { target: { value: 'My reviewed bytes\n' } });
  saveStatus = 503;
  fireEvent.click(screen.getByLabelText('Save note'));
  await screen.findByLabelText('Retry save note');
  fireEvent.click(screen.getByLabelText('Close Save to Obsidian'));
  fireEvent.click(await screen.findByLabelText('Save Jarvis answer to Obsidian'));
  await screen.findByText('Previous save is unconfirmed. Retry the same request.');
  saveStatus = 200;
  fireEvent.click(screen.getByLabelText('Retry save note'));
  await screen.findByText('Saved: Inbox/Reviewed.md');
  expect(writes).toHaveLength(2);
  expect(writes[1]).toEqual(writes[0]);
  expect(writes[1]).toMatchObject({ title: 'Reviewed', content: 'My reviewed bytes\n' });
  expect(compare).toHaveBeenCalledTimes(1);
});

it('resets cloud permission when the question changes and keeps a partial result usable', async () => {
  compare.mockResolvedValue([{ agent: 'jarvis', ok: false, reason: 'cloud_disabled' },
    { agent: 'frigga', ok: true, text: 'Local answer', model: 'device', route: 'local' }]);
  const question = await openComparison();
  fireEvent.click(screen.getByLabelText('Allow approved cloud models for this question'));
  fireEvent.change(question, { target: { value: 'Different question' } });
  fireEvent.click(screen.getByLabelText('Compare answers'));
  await screen.findByText('Local answer');
  expect(compare.mock.calls[0][3]).toBe(false);
  expect(screen.queryByLabelText('Save Jarvis answer to Obsidian')).toBeNull();
  expect(screen.getByLabelText('Save Frigga answer to Obsidian')).toBeTruthy();
});

it('aborts an in-flight comparison on hub change and discards a late answer', async () => {
  let resolve!: (value: AgentOpinion[]) => void;
  compare.mockReturnValue(new Promise(done => { resolve = done; }));
  await openComparison();
  fireEvent.click(screen.getByLabelText('Compare answers'));
  await waitFor(() => expect(compare).toHaveBeenCalledTimes(1));
  const signal = compare.mock.calls[0][4];
  await act(async () => server.updateConfig({ ...config, baseUrl: 'https://other.test' }));
  expect(signal?.aborted).toBe(true);
  await act(async () => resolve([{ agent: 'jarvis', ok: true, text: 'Previous owner response' }]));
  expect(screen.queryByLabelText('Comparison question')).toBeNull();
  expect(screen.queryByText('Previous owner response')).toBeNull();
  expect(writes).toHaveLength(0);
  expect((screen.getByPlaceholderText(/Message /) as HTMLTextAreaElement).value).toBe('My unsent draft');
  fireEvent.click(screen.getByLabelText('Compare agents'));
  expect((await screen.findByLabelText('Comparison question') as HTMLTextAreaElement).value).toBe('');
  expect(compare).toHaveBeenCalledTimes(1);
});
