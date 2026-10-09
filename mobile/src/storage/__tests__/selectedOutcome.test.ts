import { beforeEach, expect, jest, test } from '@jest/globals';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { markSelectedOutcomeUnknown, clearSelectedOutcome, selectedOutcomeUnknown } from '../selectedOutcome';

jest.mock('@react-native-async-storage/async-storage', () => ({ __esModule: true,
  default: { getItem: jest.fn(), setItem: jest.fn() } }));
let record: string | null;
beforeEach(() => { jest.clearAllMocks(); record = null;
  jest.mocked(AsyncStorage.getItem).mockImplementation(async () => record);
  jest.mocked(AsyncStorage.setItem).mockImplementation(async (_k, v) => { record = v; });
});

test('durable marker contains only bounded scope/session/agent and is scoped', async () => {
  const attempt = await markSelectedOutcomeUnknown('opaque-scope', 'session-1', 'jarvis');
  expect(record).not.toContain('prompt');
  expect(JSON.parse(record!)).toMatchObject({ version: 1 });
  expect(await selectedOutcomeUnknown('opaque-scope', 'session-1', 'jarvis')).toBe(true);
  expect(await selectedOutcomeUnknown('another-scope', 'session-1', 'jarvis')).toBe(false);
  await clearSelectedOutcome('opaque-scope', 'session-1', 'jarvis', attempt);
  expect(await selectedOutcomeUnknown('opaque-scope', 'session-1', 'jarvis')).toBe(false);
});

test('failed marker persistence refuses selected send', async () => {
  jest.mocked(AsyncStorage.setItem).mockRejectedValueOnce(new Error('storage secret'));
  await expect(markSelectedOutcomeUnknown('scope', 'session', 'jarvis')).rejects.toThrow('Cannot safely track selected image submission');
});

test('full unresolved ledger refuses a ninth marker without evicting any earlier uncertainty', async () => {
  for (let i = 0; i < 8; i++) await markSelectedOutcomeUnknown('scope', `session-${i}`, 'jarvis');
  const before = record;
  await expect(markSelectedOutcomeUnknown('scope', 'session-8', 'jarvis')).rejects.toThrow();
  expect(record).toBe(before);
  expect(await selectedOutcomeUnknown('scope', 'session-0', 'jarvis')).toBe(true);
});

test('missing marker fields are corrupt and cannot silently permit a send', async () => {
  record = JSON.stringify({ version: 1, rows: [{ scope: 'scope', sessionId: 'session' }] });
  await expect(selectedOutcomeUnknown('scope', 'session', 'jarvis')).rejects.toThrow();
  await expect(markSelectedOutcomeUnknown('scope', 'session', 'jarvis')).rejects.toThrow();
});

test('late completion of an old attempt cannot clear a newer unknown submission', async () => {
  const first = await markSelectedOutcomeUnknown('scope', 'session', 'jarvis');
  await clearSelectedOutcome('scope', 'session', 'jarvis', first);
  const second = await markSelectedOutcomeUnknown('scope', 'session', 'jarvis');
  await clearSelectedOutcome('scope', 'session', 'jarvis', first);
  expect(await selectedOutcomeUnknown('scope', 'session', 'jarvis')).toBe(true);
  await clearSelectedOutcome('scope', 'session', 'jarvis', second);
  expect(await selectedOutcomeUnknown('scope', 'session', 'jarvis')).toBe(false);
});
