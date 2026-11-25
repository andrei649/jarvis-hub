import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import { ChatScreen } from '../../mobile/src/screens/ChatScreen';
import { fetchChatNoteTarget } from '../../mobile/src/api/chatNote';
import { records } from './support/storage';

const config = { baseUrl: 'https://hub.test', token: 'user', adminToken: 'owner' };
const target = { id: `v1-${'a'.repeat(64)}`, vault: 'Andrei OS', inbox: '08 Inbox' };
const relPath = '08 Inbox/Edited.md';
const answer = 'Reply text\nsecond line';
const response = (body: unknown, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
let server: ReturnType<typeof useServer>;
let fetchMock: ReturnType<typeof vi.fn>;
function Probe() { server = useServer(); return <ChatScreen onGoToSettings={() => {}} />; }
const mount = () => render(<ServerProvider><Probe /></ServerProvider>);
const posts = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/api/os/brain/chat-note'));

beforeEach(() => {
  records.clear();
  records.set('jarvis.server.config.v1', JSON.stringify({ version: 2, config, appearance: null, chatScope: 'one' }));
  records.set('jarvis.chat.conversation.v2', JSON.stringify({ version: 2, scope: 'one', sessionId: 'saved',
    messages: [
      { id: 'q', role: 'user', text: 'Question' },
      { id: 'a', role: 'assistant', text: answer, completed: true, agent: 'jarvis' },
      { id: 'partial', role: 'assistant', text: 'Partial' },
      { id: 'failed', role: 'assistant', text: 'Failed', error: true },
      { id: 'old', role: 'assistant', text: 'Unknown legacy reply' },
    ] }));
  fetchMock = vi.fn(async (url: string) => String(url).endsWith('/api/os/status')
    ? response({ ok: true, captureTarget: target })
    : String(url).endsWith('/api/os/brain/chat-note')
      ? response({ ok: true, relPath, source: null })
      : String(url).includes('/api/os/brain/note?')
        ? response({ ok: true, targetId: target.id, relPath, body: '# Edited\nSaved body' })
        : response({ agents: [{ id: 'jarvis', name: 'Jarvis' }, { id: 'athena', name: 'Athena' }] }));
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('offers an explicit reviewed save only for a confirmed reply, then opens its saved body on the phone', async () => {
  expect(await fetchChatNoteTarget(config)).toEqual(target);
  const first = mount();
  await screen.findByLabelText('Save to Obsidian');
  expect(screen.getAllByLabelText('Save to Obsidian')).toHaveLength(1);
  expect(posts()).toHaveLength(0);
  fireEvent.click(screen.getByLabelText('Save to Obsidian'));
  await screen.findByText(target.vault);
  expect((screen.getByLabelText('Note content') as HTMLTextAreaElement).value).toBe(answer);
  expect((screen.getByLabelText('Note title') as HTMLInputElement).value).toBe('Reply text');
  fireEvent.change(screen.getByLabelText('Note title'), { target: { value: 'Edited' } });
  fireEvent.click(screen.getByLabelText('Save note'));
  await screen.findByText(`Saved: ${relPath}`);
  expect(posts()).toHaveLength(1);
  expect(JSON.parse(posts()[0][1].body)).toEqual({ targetId: target.id, requestId: expect.any(String),
    title: 'Edited', content: answer });
  fireEvent.click(screen.getByLabelText('Close Save to Obsidian'));
  fireEvent.click(screen.getByLabelText('Open saved Obsidian note'));
  expect(await screen.findByText('Saved body')).toBeTruthy();
  fireEvent.click(screen.getByText('Show Markdown'));
  expect(screen.getByText(/^# Edited\s+Saved body$/)).toBeTruthy();
  expect(screen.getByText(`${target.vault} / ${relPath}`)).toBeTruthy();
  await waitFor(() => expect(JSON.parse(records.get('jarvis.chat.conversation.v2')!).messages[1].savedNote)
    .toEqual({ target, receipt: { relPath, source: null } }));
  fireEvent.click(screen.getByLabelText('Close saved note'));
  first.unmount();
  mount();
  await screen.findByLabelText('Open saved Obsidian note');
  fireEvent.click(screen.getByLabelText('Open saved Obsidian note'));
  expect(await screen.findByText('Saved body')).toBeTruthy();
  fireEvent.click(screen.getByText('Show Markdown'));
  expect(screen.getByText(/^# Edited\s+Saved body$/)).toBeTruthy();
});

it('keeps one submitted request through an uncertain response, closing and retrying', async () => {
  fetchMock.mockImplementation(async (url: string) => String(url).endsWith('/api/os/status')
    ? response({ ok: true, captureTarget: target })
    : String(url).endsWith('/api/os/brain/chat-note')
      ? posts().length === 1 ? response({ ok: false }, 503) : response({ ok: true, relPath, source: null })
      : response({ agents: [{ id: 'jarvis', name: 'Jarvis' }, { id: 'athena', name: 'Athena' }] }));
  mount();
  await screen.findByLabelText('Save to Obsidian');
  fireEvent.click(screen.getByLabelText('Save to Obsidian'));
  await screen.findByText(target.vault);
  fireEvent.click(screen.getByLabelText('Save note'));
  await screen.findByText('Save could not be confirmed. Retry the same request.');
  expect(screen.getByLabelText('Retry save note')).toBeTruthy();
  fireEvent.click(screen.getByLabelText('Close Save to Obsidian'));
  fireEvent.click(screen.getByLabelText('Save to Obsidian'));
  await screen.findByText('Previous save is unconfirmed. Retry the same request.');
  fireEvent.click(screen.getByLabelText('Retry save note'));
  await screen.findByText(`Saved: ${relPath}`);
  expect(posts()).toHaveLength(2);
  expect(JSON.parse(posts()[1][1].body)).toEqual(JSON.parse(posts()[0][1].body));
});

it('holds the draft while the destination is offline and only rotates the ID after a typed title conflict', async () => {
  let checks = 0;
  fetchMock.mockImplementation(async (url: string) => {
    if (String(url).endsWith('/api/os/status')) {
      checks++;
      return checks === 2 ? response({ ok: true, captureTarget: null }) : response({ ok: true, captureTarget: target });
    }
    if (String(url).endsWith('/api/os/brain/chat-note')) return posts().length === 1
      ? response({ ok: false, code: 'title_conflict' }, 409)
      : response({ ok: true, relPath, source: null });
    return response({ agents: [{ id: 'jarvis', name: 'Jarvis' }, { id: 'athena', name: 'Athena' }] });
  });
  mount();
  await screen.findByLabelText('Save to Obsidian');
  fireEvent.click(screen.getByLabelText('Save to Obsidian'));
  await screen.findByText(target.vault);
  fireEvent.click(screen.getByLabelText('Save note'));
  await screen.findByText('Destination is unavailable. Your editable draft is still here.');
  expect(posts()).toHaveLength(0);
  expect((screen.getByLabelText('Note title') as HTMLInputElement).value).toBe('Reply text');
  fireEvent.change(screen.getByLabelText('Note title'), { target: { value: 'Before retry' } });
  fireEvent.click(screen.getByLabelText('Check Obsidian destination'));
  await screen.findByText(target.vault);
  fireEvent.click(screen.getByLabelText('Save note'));
  await screen.findByText('A note already uses this title. Change the title and save again.');
  expect((screen.getByLabelText('Save note') as HTMLButtonElement).disabled).toBe(true);
  const first = JSON.parse(posts()[0][1].body);
  expect(first.title).toBe('Before retry');
  fireEvent.change(screen.getByLabelText('Note title'), { target: { value: 'Edited' } });
  fireEvent.click(screen.getByLabelText('Save note'));
  await screen.findByText(`Saved: ${relPath}`);
  const second = JSON.parse(posts()[1][1].body);
  expect(second.requestId).not.toBe(first.requestId);
  expect(second.title).toBe('Edited');
});

it('invalidates an opened note on agent or connection change', async () => {
  mount();
  await screen.findByLabelText('Save to Obsidian');
  fireEvent.click(screen.getByLabelText('Save to Obsidian'));
  await screen.findByText(target.vault);
  fireEvent.click(screen.getByLabelText(/Choose agent, current recipient/));
  fireEvent.click(await screen.findByText('Athena'));
  expect(screen.queryByLabelText('Note content')).toBeNull();
  fireEvent.click(screen.getByLabelText(/Choose agent, current recipient/));
  fireEvent.click(await screen.findByText('Jarvis'));
  expect(screen.queryByLabelText('Note content')).toBeNull();
  await act(async () => server.updateConfig({ ...config, baseUrl: 'https://other.test' }));
  await waitFor(() => expect(screen.queryByLabelText('Save to Obsidian')).toBeNull());
  expect(posts()).toHaveLength(0);
});

it('never restores the saved note from another connection scope', async () => {
  const old = JSON.parse(records.get('jarvis.chat.conversation.v2')!);
  old.messages[1].savedNote = { target, receipt: { relPath, source: null } };
  records.set('jarvis.chat.conversation.v2', JSON.stringify(old));
  const current = JSON.parse(records.get('jarvis.server.config.v1')!);
  current.chatScope = 'other-connection';
  records.set('jarvis.server.config.v1', JSON.stringify(current));
  mount();
  await screen.findByText('Say hello to Jarvis.');
  expect(screen.queryByLabelText('Open saved Obsidian note')).toBeNull();
  expect(screen.queryByText(answer)).toBeNull();
});
