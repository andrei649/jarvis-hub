import { beforeEach, expect, jest, test } from '@jest/globals';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { loadConversation, saveConversation } from '../chat';

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
