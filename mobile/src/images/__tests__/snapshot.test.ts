import { beforeEach, expect, jest, test } from '@jest/globals';
import { snapshotImage, type SelectedSnapshot } from '../snapshot';
import * as Crypto from 'expo-crypto';

jest.mock('expo-crypto', () => ({ CryptoDigestAlgorithm: { SHA256: 'SHA-256' }, digestStringAsync: jest.fn() }));
const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB';
const asset = { type: 'image', base64: png, width: 1, height: 1, mimeType: 'image/jpeg', fileSize: 9999999 };
beforeEach(() => { jest.clearAllMocks(); jest.mocked(Crypto.digestStringAsync).mockResolvedValue('a'.repeat(64)); });

test('freezes picker-exported bytes and hashes exact data URI; source MIME and size are not authority', async () => {
  const image: SelectedSnapshot = await snapshotImage(asset);
  expect(image.dataUri).toBe(`data:image/png;base64,${png}`);
  expect(image.digest).toBe('a'.repeat(64));
  expect(Crypto.digestStringAsync).toHaveBeenCalledWith(Crypto.CryptoDigestAlgorithm.SHA256, image.dataUri);
  expect(image.byteCount).toBe((png.length / 4) * 3);
});

test.each([
  { ...asset, base64: 'x' }, { ...asset, base64: png + '\n' }, { ...asset, base64: '' },
  { ...asset, type: 'video' }, { ...asset, width: 8193 }, { ...asset, height: 16000001 },
  { ...asset, base64: 'R0lGODlhAQABAIAA' },
])('rejects unsupported, malformed or out-of-bounds exported images', async bad => {
  await expect(snapshotImage(bad)).rejects.toThrow('Selected image is unsupported');
  expect(Crypto.digestStringAsync).not.toHaveBeenCalled();
});
