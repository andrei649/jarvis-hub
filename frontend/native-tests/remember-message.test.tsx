import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import { ChatScreen } from '../../mobile/src/screens/ChatScreen';
import { records, storage } from './support/storage';

const config = { baseUrl: 'https://hub.test', token: ' user ', adminToken: ' owner ' };
const entryPath = '/api/dashboard/today/entries';
const id1 = 'memory:user:0123456789abcdef';
const id2 = 'memory:user:fedcba9876543210';
const id3 = 'memory:user:aaaaaaaaaaaaaaaa';
let server: ReturnType<typeof useServer>;
function Probe() { server = useServer(); return <ChatScreen onGoToSettings={() => {}} />; }
const mount = () => render(<ServerProvider><Probe /></ServerProvider>);
const response = (body: unknown, status = 200) => ({ ok: status >= 200 && status < 300, status,
  json: async () => body });
let fetchMock: ReturnType<typeof vi.fn>;

async function open() {
  await screen.findByText('Original question');
  fireEvent.click(screen.getByLabelText('Remember message'));
  expect(screen.getByLabelText('Fact to save')).toBeTruthy();
  return screen.getByLabelText('Fact to save') as HTMLTextAreaElement;
}

beforeEach(() => {
  records.clear();
  records.set('jarvis.server.config.v1', JSON.stringify({ version: 2, config,
    appearance: null, chatScope: 'one' }));
  records.set('jarvis.chat.conversation.v2', JSON.stringify({ version: 2, scope: 'one', sessionId: 'saved',
    messages: [{ id: 'original', role: 'user', text: 'Original question' }] }));
  fetchMock = vi.fn(async (url: string) => url.endsWith('/api/agents')
    ? response({ agents: [{ id: 'jarvis', name: 'Jarvis' }, { id: 'athena', name: 'Athena' }] })
    : url.includes('/sessions/page?') ? response({ sessions: [{ id: 'older', title: 'Older session' }], next_cursor: null })
      : url.endsWith('/sessions/resume') ? response({ ok: true, session: 'older', turns: [{ role: 'user', content: 'Older question' }] })
        : response({ ok: true, changed: true, entry: { entry_id: 'memory:memory:0123456789abcdef', store: 'memory', value: 'Edited fact' } }));
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('keeps an editor opened as the retained conversation finishes hydrating', async () => {
  const cached = records.get('jarvis.chat.conversation.v2')!;
  const getItem = storage.getItem;
  let release!: (value: string | null) => void;
  vi.spyOn(storage, 'getItem').mockImplementation(key => key === 'jarvis.chat.conversation.v2'
    ? new Promise(resolve => { release = resolve; }) : getItem(key));
  mount();
  await waitFor(() => expect(release).toBeDefined());
  release(cached);
  await open();
  await act(async () => Promise.resolve());
  expect(screen.getByLabelText('Fact to save')).toBeTruthy();
});

it('saves an edited copy only on tap, then corrects the confirmed rotating entry ID in the selected store', async () => {
  mount();
  const input = await open();
  expect(input.value).toBe('Original question');
  expect(fetchMock.mock.calls.filter(([url]) => String(url).includes(entryPath))).toHaveLength(0);
  expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('/api/memory/core/facts'))).toHaveLength(0);
  fireEvent.click(screen.getByLabelText('User profile'));
  fireEvent.change(input, { target: { value: ' Edited fact ' } });
  fetchMock.mockImplementation(async (url: string) => String(url).includes(entryPath)
    ? response({ ok: true, changed: true, entry: { entry_id: id1, store: 'user', value: 'Edited fact' } })
    : response({ agents: [] }));
  fireEvent.click(screen.getByLabelText('Save fact'));
  await screen.findByText(/Saved fact in User profile/);
  expect(fetchMock.mock.calls.filter(([url]) => String(url).includes(entryPath))).toHaveLength(1);
  const [postUrl, postInit] = fetchMock.mock.calls.find(([url]) => String(url).includes(entryPath))!;
  expect(postUrl).toBe(`https://hub.test${entryPath}`);
  expect(postInit.method).toBe('POST');
  expect(postInit.headers).toMatchObject({ 'X-User-Token': 'user', 'X-Admin-Token': 'owner' });
  expect(JSON.parse(postInit.body)).toEqual({ store: 'user', value: 'Edited fact' });
  expect(screen.getByText('Original question')).toBeTruthy();
  expect((screen.getByLabelText('User profile') as HTMLButtonElement).disabled).toBe(true);
  let corrections = 0;
  fetchMock.mockImplementation(async (url: string) => String(url).includes(entryPath)
    ? ++corrections === 1
      ? response({ ok: true, changed: true, previous_id: id1,
        entry: { entry_id: id2, store: 'user', value: 'Corrected fact' } })
      : response({ ok: true, changed: true, previous_id: id2,
        entry: { entry_id: id3, store: 'user', value: 'One more correction' } })
    : response({ agents: [] }));
  fireEvent.change(input, { target: { value: 'Corrected fact' } });
  fireEvent.click(screen.getByLabelText('Save correction'));
  await screen.findByText(/Corrected fact in User profile/);
  const [patchUrl, patchInit] = fetchMock.mock.calls.filter(([url]) => String(url).includes(entryPath)).at(-1)!;
  expect(patchUrl).toBe(`https://hub.test${entryPath}/${id1}`);
  expect(patchInit.method).toBe('PATCH');
  expect(JSON.parse(patchInit.body)).toEqual({ value: 'Corrected fact' });
  fireEvent.change(input, { target: { value: 'One more correction' } });
  fireEvent.click(screen.getByLabelText('Save correction'));
  await waitFor(() => expect(fetchMock.mock.calls.at(-1)?.[0]).toBe(`https://hub.test${entryPath}/${id2}`));
});

it('selects a legacy saved fact before PATCH, without sending a duplicate POST or changing the chat message', async () => {
  mount(); const input = await open();
  fireEvent.click(screen.getByLabelText('User profile'));
  const old = 'Legacy '.repeat(300);
  fetchMock.mockImplementation(async (url: string) => String(url).includes('/api/memory/core/facts')
    ? response({ entries: [{ entry_id: id1, store: 'user', value: old }] })
    : String(url).includes(entryPath)
      ? response({ ok: true, changed: true, previous_id: id1,
        entry: { entry_id: id2, store: 'user', value: 'Updated preference' } })
      : response({ agents: [] }));
  fireEvent.click(screen.getByLabelText('Replace a saved fact'));
  await screen.findByLabelText(/^Replace: Legacy /);
  const [listUrl, listInit] = fetchMock.mock.calls.find(([url]) => String(url).includes('/api/memory/core/facts'))!;
  expect(listUrl).toBe('https://hub.test/api/memory/core/facts?store=user');
  expect(listInit).toMatchObject({ method: 'GET', cache: 'no-store', redirect: 'error', credentials: 'omit' });
  expect(listInit.headers).toMatchObject({ 'X-User-Token': 'user', 'X-Admin-Token': 'owner' });
  expect((screen.getByLabelText('Choose a saved fact first') as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByLabelText(/^Replace: Legacy /));
  expect(screen.getByText('Original saved fact in User profile')).toBeTruthy();
  expect(screen.getByText(/^Legacy /)).toBeTruthy();
  expect(screen.queryByLabelText(/^Replace: Legacy /)).toBeNull();
  expect(screen.getByLabelText('Replacement fact')).toBeTruthy();
  fireEvent.change(input, { target: { value: 'Updated preference' } });
  fireEvent.click(screen.getByLabelText('Save correction'));
  await screen.findByText(/Corrected fact in User profile/);
  expect(fetchMock.mock.calls.filter(([url]) => String(url).includes(entryPath))).toHaveLength(1);
  const [patchUrl, patchInit] = fetchMock.mock.calls.find(([url]) => String(url).includes(entryPath))!;
  expect(patchUrl).toBe(`https://hub.test${entryPath}/${id1}`);
  expect(patchInit.method).toBe('PATCH');
  expect(JSON.parse(patchInit.body)).toEqual({ value: 'Updated preference' });
  expect(screen.getByText('Original question')).toBeTruthy();
});

it('clears a stale choice, keeps the draft, and requires refresh and a new exact selection', async () => {
  mount(); const input = await open();
  fireEvent.click(screen.getByLabelText('User profile'));
  let currentId = id1;
  let patchCount = 0;
  fetchMock.mockImplementation(async (url: string) => String(url).includes('/api/memory/core/facts')
    ? response({ entries: [{ entry_id: currentId, store: 'user', value: 'Old preference' }] })
    : String(url).includes(entryPath)
      ? ++patchCount === 1 ? response({ reason: 'memory_no_match' }, 404)
        : response({ ok: true, changed: true, previous_id: id2,
          entry: { entry_id: id1, store: 'user', value: 'New preference' } })
      : response({ agents: [] }));
  fireEvent.click(screen.getByLabelText('Replace a saved fact'));
  fireEvent.click(await screen.findByLabelText('Replace: Old preference'));
  fireEvent.change(input, { target: { value: 'New preference' } });
  fireEvent.click(screen.getByLabelText('Save correction'));
  await screen.findByText(/Refresh saved facts and choose the current entry/);
  expect(input.value).toBe('New preference');
  expect(screen.queryByLabelText('Replace: Old preference')).toBeNull();
  expect((screen.getByLabelText('Choose a saved fact first') as HTMLButtonElement).disabled).toBe(true);
  currentId = id2;
  fireEvent.click(screen.getByLabelText('Refresh saved facts'));
  fireEvent.click(await screen.findByLabelText('Replace: Old preference'));
  fireEvent.click(screen.getByLabelText('Save correction'));
  await screen.findByText(/Corrected fact in User profile/);
  expect(fetchMock.mock.calls.filter(([url]) => String(url).includes(entryPath)).map(([url]) => url))
    .toEqual([`https://hub.test${entryPath}/${id1}`, `https://hub.test${entryPath}/${id2}`]);
});

it('prevents replacement with another selected-store fact and does not PATCH', async () => {
  mount(); const input = await open();
  fireEvent.click(screen.getByLabelText('User profile'));
  fetchMock.mockImplementation(async (url: string) => String(url).includes('/api/memory/core/facts')
    ? response({ entries: [{ entry_id: id1, store: 'user', value: 'Old preference' },
      { entry_id: id2, store: 'user', value: 'Other preference' }] })
    : response({ agents: [] }));
  fireEvent.click(screen.getByLabelText('Replace a saved fact'));
  fireEvent.click(await screen.findByLabelText('Replace: Old preference'));
  expect(screen.getByText('Original saved fact in User profile')).toBeTruthy();
  fireEvent.click(screen.getByLabelText('Choose another fact'));
  expect(screen.getByLabelText('Replace: Other preference')).toBeTruthy();
  expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('/api/memory/core/facts'))).toHaveLength(1);
  fireEvent.click(screen.getByLabelText('Replace: Other preference'));
  expect(screen.getByText('Original saved fact in User profile')).toBeTruthy();
  fireEvent.click(screen.getByLabelText('Choose another fact'));
  fireEvent.click(screen.getByLabelText('Replace: Old preference'));
  fireEvent.change(input, { target: { value: 'Other\u0085preference' } });
  expect(screen.getByText('That fact is already saved in this store.')).toBeTruthy();
  expect((screen.getByLabelText('Save correction') as HTMLButtonElement).disabled).toBe(true);
  expect(fetchMock.mock.calls.filter(([url]) => String(url).includes(entryPath))).toHaveLength(0);
});

it('does not claim ownership of a duplicate or use its returned ID for a correction', async () => {
  mount(); const input = await open();
  fetchMock.mockImplementation(async (url: string) => String(url).includes(entryPath)
    ? response({ ok: true, changed: false, entry: { entry_id: 'memory:memory:aaaaaaaaaaaaaaaa', store: 'memory', value: 'Original question' } })
    : response({ agents: [] }));
  fireEvent.click(screen.getByLabelText('Save fact'));
  await screen.findByText('Fact already saved; nothing changed.');
  expect(input.value).toBe('Original question');
  fireEvent.change(input, { target: { value: 'Different fact' } });
  fireEvent.click(screen.getByLabelText('Save fact'));
  await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url).includes(entryPath))).toHaveLength(2));
  expect(fetchMock.mock.calls.at(-1)?.[0]).toBe(`https://hub.test${entryPath}`);
});

it('locks a submitted save against a second tap until the result arrives', async () => {
  mount(); await open();
  let release!: (value: ReturnType<typeof response>) => void;
  fetchMock.mockImplementation((url: string) => String(url).includes(entryPath)
    ? new Promise(resolve => { release = resolve; }) : Promise.resolve(response({ agents: [] })));
  fireEvent.click(screen.getByLabelText('Save fact'));
  fireEvent.click(screen.getByLabelText('Save fact'));
  expect(fetchMock.mock.calls.filter(([url]) => String(url).includes(entryPath))).toHaveLength(1);
  await act(async () => release(response({ ok: true, changed: true, entry: {
    entry_id: 'memory:memory:0123456789abcdef', store: 'memory', value: 'Original question' } })));
  expect(await screen.findByText(/Saved fact in Agent notes/)).toBeTruthy();
});

it('keeps the draft on owner refusal and validates 300 Unicode code points before submitting', async () => {
  mount(); const input = await open();
  fireEvent.change(input, { target: { value: '😀'.repeat(301) } });
  expect((screen.getByLabelText('Save fact') as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/301\/300 characters/)).toBeTruthy();
  fireEvent.change(input, { target: { value: '😀'.repeat(300) } });
  expect((screen.getByLabelText('Save fact') as HTMLButtonElement).disabled).toBe(false);
  fetchMock.mockImplementation(async (url: string) => String(url).includes(entryPath)
    ? response({ detail: 'owner only' }, 401) : response({ agents: [] }));
  fireEvent.click(screen.getByLabelText('Save fact'));
  await screen.findByText(/Save refused: Owner access is required/);
  expect(input.value).toBe('😀'.repeat(300));
  expect(screen.getByText('Original question')).toBeTruthy();
});

it('forgets only the selected fact after a second confirmation, while cancel keeps the unsent draft', async () => {
  mount(); const input = await open();
  fireEvent.change(input, { target: { value: 'My unsent draft' } });
  fireEvent.click(screen.getByLabelText('User profile'));
  fetchMock.mockImplementation(async (url: string) => String(url).includes('/api/memory/core/facts')
    ? response({ entries: [{ entry_id: id1, store: 'user', value: 'Exact saved preference' },
      { entry_id: id2, store: 'user', value: 'Other preference' }] })
    : String(url).includes(entryPath)
      ? response({ ok: true, deleted: id1, store: 'user', undo_ref: '0123456789abcdef' })
      : response({ agents: [] }));
  fireEvent.click(screen.getByLabelText('Forget a saved fact'));
  expect(await screen.findByLabelText('Forget: Exact saved preference')).toBeTruthy();
  expect(fetchMock.mock.calls.filter(([url]) => String(url).includes(entryPath))).toHaveLength(0);
  fireEvent.click(screen.getByLabelText('Forget: Exact saved preference'));
  expect(screen.getByText('Original saved fact in User profile')).toBeTruthy();
  expect(screen.getByText('Exact saved preference')).toBeTruthy();
  fireEvent.click(screen.getByLabelText('Forget selected fact'));
  expect(screen.getByText(/Remove this exact fact from User profile/)).toBeTruthy();
  expect(fetchMock.mock.calls.filter(([url]) => String(url).includes(entryPath))).toHaveLength(0);
  fireEvent.click(screen.getByLabelText('Cancel forget'));
  expect(fetchMock.mock.calls.filter(([url]) => String(url).includes(entryPath))).toHaveLength(0);
  fireEvent.click(screen.getByLabelText('Forget selected fact'));
  fireEvent.click(screen.getByLabelText('Confirm forget'));
  await screen.findByText(/Removed from User profile for new chats/);
  const writes = fetchMock.mock.calls.filter(([url]) => String(url).includes(entryPath));
  expect(writes).toHaveLength(1);
  expect(writes[0][0]).toBe(`https://hub.test${entryPath}/${id1}`);
  expect(writes[0][1]).toMatchObject({ method: 'DELETE', redirect: 'error', credentials: 'omit',
    headers: { Accept: 'application/json', 'X-User-Token': 'user', 'X-Admin-Token': 'owner' } });
  expect(writes[0][1].body).toBeUndefined();
  expect(screen.getByText('Original question')).toBeTruthy();
  fireEvent.click(screen.getByLabelText('Save as new fact'));
  expect((screen.getByLabelText('Fact to save') as HTMLTextAreaElement).value).toBe('My unsent draft');
});

it('undoes a confirmed deletion with its exact ref, and hides undo when the hub omits it', async () => {
  mount(); await open();
  fireEvent.click(screen.getByLabelText('User profile'));
  let includeRef = true;
  fetchMock.mockImplementation(async (url: string) => String(url).includes('/api/memory/core/facts')
    ? response({ entries: [{ entry_id: id1, store: 'user', value: 'Recoverable fact' }] })
    : String(url).includes(entryPath)
      ? response({ ok: true, deleted: id1, store: 'user', ...(includeRef ? { undo_ref: '0123456789abcdef' } : {}) })
      : String(url).endsWith('/api/memory/core/undo') ? response({ ok: true, ref: '0123456789abcdef',
        private_memory: 'must not appear' }) : response({ agents: [] }));
  fireEvent.click(screen.getByLabelText('Forget a saved fact'));
  fireEvent.click(await screen.findByLabelText('Forget: Recoverable fact'));
  fireEvent.click(screen.getByLabelText('Forget selected fact'));
  fireEvent.click(screen.getByLabelText('Confirm forget'));
  fireEvent.click(await screen.findByLabelText('Undo forget'));
  await screen.findByText(/Restored to User profile/);
  const [undoUrl, undoInit] = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/api/memory/core/undo'))!;
  expect(undoUrl).toBe('https://hub.test/api/memory/core/undo');
  expect(undoInit).toMatchObject({ method: 'POST', body: JSON.stringify({ ref: '0123456789abcdef' }),
    redirect: 'error', credentials: 'omit' });
  expect(screen.queryByText('must not appear')).toBeNull();
  expect(screen.queryByLabelText('Confirm forget')).toBeNull();
  includeRef = false;
  fireEvent.click(screen.getByLabelText('Forget: Recoverable fact'));
  fireEvent.click(screen.getByLabelText('Forget selected fact'));
  fireEvent.click(screen.getByLabelText('Confirm forget'));
  await screen.findByText(/Undo is unavailable/);
  expect(screen.queryByLabelText('Undo forget')).toBeNull();
});

it('clears undo and the armed confirmation when restoration is stale', async () => {
  mount(); await open();
  fireEvent.click(screen.getByLabelText('User profile'));
  fetchMock.mockImplementation(async (url: string) => String(url).includes('/api/memory/core/facts')
    ? response({ entries: [{ entry_id: id1, store: 'user', value: 'Maybe restored' }] })
    : String(url).includes(entryPath)
      ? response({ ok: true, deleted: id1, store: 'user', undo_ref: '0123456789abcdef' })
      : String(url).endsWith('/api/memory/core/undo') ? response({ reason: 'memory_changed_meanwhile' }, 409)
        : response({ agents: [] }));
  fireEvent.click(screen.getByLabelText('Forget a saved fact'));
  fireEvent.click(await screen.findByLabelText('Forget: Maybe restored'));
  fireEvent.click(screen.getByLabelText('Forget selected fact'));
  fireEvent.click(screen.getByLabelText('Confirm forget'));
  fireEvent.click(await screen.findByLabelText('Undo forget'));
  await screen.findByText(/Undo could not be confirmed. Refresh saved facts/);
  expect(screen.queryByLabelText('Undo forget')).toBeNull();
  expect(screen.queryByLabelText('Confirm forget')).toBeNull();
  expect(screen.queryByLabelText('Forget: Maybe restored')).toBeNull();
  expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/api/memory/core/undo'))).toHaveLength(1);
  fireEvent.click(screen.getByLabelText('Refresh saved facts'));
  expect(await screen.findByLabelText('Forget: Maybe restored')).toBeTruthy();
});

it('requires a fresh selection after a stale DELETE and never retries the old ID', async () => {
  mount(); const input = await open();
  fireEvent.change(input, { target: { value: 'Unsent draft stays' } });
  fireEvent.click(screen.getByLabelText('User profile'));
  let currentId = id1;
  let deletions = 0;
  fetchMock.mockImplementation(async (url: string) => String(url).includes('/api/memory/core/facts')
    ? response({ entries: [{ entry_id: currentId, store: 'user', value: 'Changing fact' }] })
    : String(url).includes(entryPath) ? ++deletions === 1 ? response({ reason: 'memory_no_match' }, 404)
      : response({ ok: true, deleted: id2, store: 'user' }) : response({ agents: [] }));
  fireEvent.click(screen.getByLabelText('Forget a saved fact'));
  fireEvent.click(await screen.findByLabelText('Forget: Changing fact'));
  fireEvent.click(screen.getByLabelText('Forget selected fact'));
  fireEvent.click(screen.getByLabelText('Confirm forget'));
  await screen.findByText(/Refresh saved facts and choose the current entry/);
  expect(fetchMock.mock.calls.filter(([url]) => String(url).includes(entryPath))).toHaveLength(1);
  expect(screen.queryByLabelText('Confirm forget')).toBeNull();
  currentId = id2;
  fireEvent.click(screen.getByLabelText('Refresh saved facts'));
  fireEvent.click(await screen.findByLabelText('Forget: Changing fact'));
  fireEvent.click(screen.getByLabelText('Forget selected fact'));
  fireEvent.click(screen.getByLabelText('Confirm forget'));
  await screen.findByText(/Removed from User profile for new chats/);
  expect(fetchMock.mock.calls.filter(([url]) => String(url).includes(entryPath)).map(([url]) => url))
    .toEqual([`https://hub.test${entryPath}/${id1}`, `https://hub.test${entryPath}/${id2}`]);
  fireEvent.click(screen.getByLabelText('Save as new fact'));
  expect((screen.getByLabelText('Fact to save') as HTMLTextAreaElement).value).toBe('Unsent draft stays');
});

it('ignores a forget receipt that arrives after the chat changes hub', async () => {
  mount(); await open();
  fireEvent.click(screen.getByLabelText('User profile'));
  let release!: (value: ReturnType<typeof response>) => void;
  fetchMock.mockImplementation((url: string) => String(url).includes('/api/memory/core/facts')
    ? Promise.resolve(response({ entries: [{ entry_id: id1, store: 'user', value: 'Old hub fact' }] }))
    : String(url).includes(entryPath) ? new Promise(resolve => { release = resolve; })
      : Promise.resolve(response({ agents: [] })));
  fireEvent.click(screen.getByLabelText('Forget a saved fact'));
  fireEvent.click(await screen.findByLabelText('Forget: Old hub fact'));
  fireEvent.click(screen.getByLabelText('Forget selected fact'));
  fireEvent.click(screen.getByLabelText('Confirm forget'));
  await waitFor(() => expect(release).toBeDefined());
  await act(async () => server.updateConfig({ ...config, baseUrl: 'https://other.test' }));
  expect(screen.queryByLabelText('Undo forget')).toBeNull();
  await act(async () => release(response({ ok: true, deleted: id1, store: 'user', undo_ref: '0123456789abcdef' })));
  expect(screen.queryByText(/Removed from User profile/)).toBeNull();
  expect(screen.queryByLabelText('Undo forget')).toBeNull();
});

it('closes the editor when the agent or session changes, then ignores a save completed on another hub', async () => {
  mount(); await open();
  fireEvent.click(screen.getByLabelText(/Choose agent, current recipient/));
  fireEvent.click(await screen.findByText('Athena'));
  expect(screen.queryByLabelText('Fact to save')).toBeNull();
  await open();
  fireEvent.click(screen.getByText('History'));
  fireEvent.click(await screen.findByText('Older session'));
  await screen.findByText('Older question');
  expect(screen.queryByLabelText('Fact to save')).toBeNull();
  fireEvent.click(screen.getByLabelText('Remember message'));
  let release!: (value: ReturnType<typeof response>) => void;
  fetchMock.mockImplementation((url: string) => String(url).includes(entryPath)
    ? new Promise(resolve => { release = resolve; }) : Promise.resolve(response({ agents: [] })));
  fireEvent.change(screen.getByLabelText('Fact to save'), { target: { value: 'Old hub fact' } });
  fireEvent.click(screen.getByLabelText('Save fact'));
  await waitFor(() => expect(release).toBeDefined());
  await act(async () => server.updateConfig({ ...config, baseUrl: 'https://other.test' }));
  expect(screen.queryByLabelText('Fact to save')).toBeNull();
  await act(async () => release(response({ ok: true, changed: true, entry: {
    entry_id: 'memory:memory:0123456789abcdef', store: 'memory', value: 'Old hub fact' } })));
  expect(screen.queryByText(/Saved fact in Agent notes/)).toBeNull();
});
