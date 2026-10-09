import { beforeEach, expect, jest, test } from '@jest/globals';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { loadServerRecord, reconfigureServer, saveServerRecord } from '../settings';

jest.mock('@react-native-async-storage/async-storage', () => ({
  __esModule: true, default: { getItem: jest.fn(), setItem: jest.fn() },
}));
const config = { baseUrl: 'http://hub', token: 'user-secret', adminToken: 'admin-secret' };

beforeEach(() => { jest.clearAllMocks(); jest.mocked(AsyncStorage.setItem).mockResolvedValue(); });

test('old server records receive an opaque chat scope that survives a save and restart', async () => {
  jest.mocked(AsyncStorage.getItem).mockResolvedValueOnce(JSON.stringify(config));
  const record = await loadServerRecord();
  expect(record.chatScope).toEqual(expect.any(String));
  expect(record.chatScope).not.toContain('secret');
  await saveServerRecord(() => record);
  jest.mocked(AsyncStorage.getItem).mockResolvedValueOnce(jest.mocked(AsyncStorage.setItem).mock.calls[0][1]);
  expect((await loadServerRecord()).chatScope).toBe(record.chatScope);
});

test('hub or credentials change rotates the scope; saving identical settings keeps it', async () => {
  jest.mocked(AsyncStorage.getItem).mockResolvedValueOnce(JSON.stringify(config));
  const record = await loadServerRecord();
  expect(reconfigureServer(record, { ...config }).chatScope).toBe(record.chatScope);
  for (const next of [{ ...config, token: 'other' }, { ...config, baseUrl: 'http://other' },
    { ...config, adminToken: 'other' }]) {
    expect(reconfigureServer(record, next).chatScope).not.toBe(record.chatScope);
  }
});
