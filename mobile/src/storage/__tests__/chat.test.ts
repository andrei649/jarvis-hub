import { beforeEach, expect, jest, test } from '@jest/globals';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { loadConversation, loadHistory, saveConversation, saveHistory } from '../chat';

jest.mock('@react-native-async-storage/async-storage', () => ({
  __esModule: true, default: { getItem: jest.fn(), setItem: jest.fn(), removeItem: jest.fn() },
}));

beforeEach(() => { jest.clearAllMocks(); jest.mocked(AsyncStorage.setItem).mockResolvedValue(); });

test('session and settled transcript are written in one bounded credential-free record', async () => {
  const messages = Array.from({ length: 205 }, (_, i) => ({ id: String(i), role: 'user' as const, text: String(i) }));
  await saveConversation('opaque-connection', { sessionId: 'session-a', messages: [...messages,
    { id: 'pending', role: 'assistant', text: 'partial', pending: true }] });
  const raw = jest.mocked(AsyncStorage.setItem).mock.calls.at(-1)![1];
  const stored = JSON.parse(raw);
  expect(stored).toMatchObject({ scope: 'opaque-connection', sessionId: 'session-a' });
  expect(stored.messages).toHaveLength(200);
  expect(stored.messages[0].id).toBe('5');
  jest.mocked(AsyncStorage.getItem).mockResolvedValueOnce(raw);
  expect(await loadConversation('opaque-connection')).toEqual({ sessionId: 'session-a', messages: messages.slice(-200) });
});

test('a different hub or credential identity never inherits the cached conversation', async () => {
  jest.mocked(AsyncStorage.getItem).mockResolvedValueOnce(JSON.stringify({ version: 2, scope: 'old',
    sessionId: 'private-session', messages: [{ id: '1', role: 'user', text: 'private' }] }));
  expect(await loadConversation('new')).toEqual({ sessionId: null, messages: [] });
});

test('history source cache keeps only validated metadata within its connection scope', async () => {
  const source = { session_id: 'source', turn: 3, revision: 'a'.repeat(64), role: 'user' as const };
  await saveConversation('owner', { sessionId: 'destination', messages: [
    { id: 'u', role: 'user', text: 'Follow up', historySource: { ...source,
      excerpt: 'private source text' } } as any,
    { id: 'bad', role: 'user', text: 'Other', historySource: { ...source, revision: 'invalid' } },
    { id: 'foreign', role: 'user', text: 'Imported', foreign_origin: 'other', historySource: source } as any,
  ] });
  const raw = jest.mocked(AsyncStorage.setItem).mock.calls.at(-1)![1];
  expect(raw).not.toContain('private source text');
  jest.mocked(AsyncStorage.getItem).mockResolvedValueOnce(raw);
  expect((await loadConversation('owner')).messages.map(m => m.historySource)).toEqual([source, undefined, undefined]);
  jest.mocked(AsyncStorage.getItem).mockResolvedValueOnce(raw);
  expect((await loadConversation('other')).messages).toEqual([]);
});

test('scoped storage restores bounded agent activity for completed native replies only', async () => {
  const tools = { proposed: 2, queued: 1, executed: 1, failures: null, basis: 'unknown' as const };
  const reply = { id: 'a', role: 'assistant' as const, completed: true as const, text: 'Draft', toolActivity: tools };
  await saveConversation('owner', { sessionId: 'chat', messages: [
    reply, { ...reply, id: 'b', completed: undefined }, { ...reply, id: 'c', role: 'user' },
    { ...reply, id: 'd', foreign_origin: 'codex' } as any,
    { ...reply, id: 'e', toolActivity: { ...tools, args: 'private argument' } } as any,
  ] });
  const raw = jest.mocked(AsyncStorage.setItem).mock.calls.at(-1)![1];
  expect(raw).not.toContain('private argument');
  jest.mocked(AsyncStorage.getItem).mockResolvedValueOnce(raw);
  expect((await loadConversation('owner')).messages.map(m => m.toolActivity))
    .toEqual([tools, undefined, undefined, undefined, undefined]);
});

test('scoped storage retains only validated assistant receipts', async () => {
  const calls = [{ provider: 'ollama', model: 'qwen3/8b' }];
  await saveConversation('same', { sessionId: 'saved', messages: [
    { id: 'u', role: 'user', text: 'question', modelCalls: calls } as any,
    { id: 'a', role: 'assistant', text: 'measured', modelCalls: calls },
    { id: 'bad', role: 'assistant', text: 'invalid', modelCalls: [{ ...calls[0], location: 'local' }] } as any,
    { id: 'foreign', role: 'assistant', text: 'imported', foreign_origin: 'codex', modelCalls: calls } as any,
    { id: 'tainted', role: 'assistant', text: 'unsafe', tainted: true, modelCalls: calls } as any,
  ] });
  const raw = jest.mocked(AsyncStorage.setItem).mock.calls.at(-1)![1];
  expect(JSON.parse(raw).messages.map((m: any) => m.modelCalls)).toEqual([undefined, calls, undefined, undefined, undefined]);
  jest.mocked(AsyncStorage.getItem).mockResolvedValueOnce(raw);
  expect((await loadConversation('same')).messages.map(m => m.modelCalls)).toEqual([undefined, calls, undefined, undefined, undefined]);
});

test('only explicit completed real replies retain note eligibility across scoped restore', async () => {
  const target = { id: `v1-${'a'.repeat(64)}`, vault: 'Demo Vault', inbox: '08 Inbox' };
  const receipt = { relPath: '08 Inbox/Edited.md', source: null };
  await saveConversation('same', { sessionId: 'saved', messages: [
    { id: 'done', role: 'assistant', text: 'Answer', completed: true,
      savedNote: { target, receipt, requestId: 'private-id', body: 'private-note-body' } } as any,
    { id: 'partial', role: 'assistant', text: 'Partial' },
    { id: 'error', role: 'assistant', text: 'Failed', completed: true, error: true,
      savedNote: { target, receipt } },
    { id: 'foreign', role: 'assistant', text: 'Imported', completed: true, foreign_origin: 'other' } as any,
  ] });
  const raw = jest.mocked(AsyncStorage.setItem).mock.calls.at(-1)![1];
  expect(raw).not.toContain('private-id');
  expect(raw).not.toContain('private-note-body');
  jest.mocked(AsyncStorage.getItem).mockResolvedValueOnce(raw);
  const restored = (await loadConversation('same')).messages;
  expect(restored.map(m => m.completed)).toEqual([true, undefined, undefined, undefined]);
  expect(restored[0].savedNote).toEqual({ target, receipt });
  expect(restored.slice(1).every(m => m.savedNote === undefined)).toBe(true);
});

test('legacy unscoped history drops receipts on write and read', async () => {
  const message = { id: 'a', role: 'assistant' as const, text: 'answer',
    modelCalls: [{ provider: 'ollama', model: 'qwen3/8b' }] };
  await saveHistory([message]);
  expect(JSON.parse(jest.mocked(AsyncStorage.setItem).mock.calls.at(-1)![1])).toEqual([
    { id: 'a', role: 'assistant', text: 'answer' },
  ]);
  jest.mocked(AsyncStorage.getItem).mockResolvedValueOnce(JSON.stringify([message]));
  expect(await loadHistory()).toEqual([{ id: 'a', role: 'assistant', text: 'answer' }]);
});

test.each(['{', 'null', '[]', '{"version":2,"scope":"same","sessionId":{},"messages":[]}'])
('corrupt or unscoped records start empty: %s', async raw => {
  jest.mocked(AsyncStorage.getItem).mockResolvedValueOnce(raw);
  expect(await loadConversation('same')).toEqual({ sessionId: null, messages: [] });
});

test('malformed cached messages are excluded', async () => {
  jest.mocked(AsyncStorage.getItem).mockResolvedValueOnce(JSON.stringify({ version: 2, scope: 'same',
    sessionId: 'saved', messages: [null, { role: 'system', id: 'x', text: 'secret' },
      { role: 'user', id: 'ok', text: 'hello' }, { role: 'assistant', id: 'pending', text: '', pending: true }] }));
  expect((await loadConversation('same')).messages).toEqual([{ role: 'user', id: 'ok', text: 'hello' }]);
});

test('writes serialize so an older slow write cannot replace the selected session', async () => {
  let release!: () => void;
  jest.mocked(AsyncStorage.setItem).mockImplementationOnce(() => new Promise(r => { release = r; }));
  const first = saveConversation('same', { sessionId: 'old', messages: [] });
  const next = saveConversation('same', { sessionId: 'new', messages: [] });
  await Promise.resolve(); await Promise.resolve();
  expect(AsyncStorage.setItem).toHaveBeenCalledTimes(1);
  release();
  await Promise.all([first, next]);
  expect(JSON.parse(jest.mocked(AsyncStorage.setItem).mock.calls[1][1]).sessionId).toBe('new');
});

test('settled chat persistence allowlists text fields and drops image bytes or handles', async () => {
  await saveConversation('scope', { sessionId: 'session', messages: [{ id: 'm', role: 'user', text: 'Question',
    imageBytes: 'secret-pixels', activeImageHandle: 'opaque-handle' } as any] });
  const raw = jest.mocked(AsyncStorage.setItem).mock.calls.at(-1)![1];
  expect(raw).not.toContain('secret-pixels');
  expect(raw).not.toContain('opaque-handle');
  expect(JSON.parse(raw).messages).toEqual([{ id: 'm', role: 'user', text: 'Question' }]);
});

test('recovery prompt is bounded and scoped, while missing-session authority is never stored', async () => {
  await saveConversation('scope-a', { sessionId: 'session', messages: [], recoveryPrompt: 'Unsent question',
    missingSessionId: 'must-not-persist' } as any);
  const raw = jest.mocked(AsyncStorage.setItem).mock.calls.at(-1)![1];
  const stored = JSON.parse(raw);
  expect(stored.recoveryPrompt).toBe('Unsent question');
  expect(stored).not.toHaveProperty('missingSessionId');
  jest.mocked(AsyncStorage.getItem).mockResolvedValueOnce(raw);
  expect(await loadConversation('scope-a')).toEqual({ sessionId: 'session', messages: [],
    recoveryPrompt: 'Unsent question' });
  jest.mocked(AsyncStorage.getItem).mockResolvedValueOnce(raw);
  expect(await loadConversation('scope-b')).toEqual({ sessionId: null, messages: [] });
});

test('invalid or oversized recovery prompts are omitted without changing the legacy record shape', async () => {
  await saveConversation('scope', { sessionId: null, messages: [], recoveryPrompt: 'x'.repeat(4097) });
  const oversize = JSON.parse(jest.mocked(AsyncStorage.setItem).mock.calls.at(-1)![1]);
  expect(oversize).not.toHaveProperty('recoveryPrompt');
  await saveConversation('scope', { sessionId: null, messages: [] });
  const legacyShape = JSON.parse(jest.mocked(AsyncStorage.setItem).mock.calls.at(-1)![1]);
  expect(legacyShape).not.toHaveProperty('recoveryPrompt');
});
