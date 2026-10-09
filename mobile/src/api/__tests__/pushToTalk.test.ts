import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { armMobileMic, readMicTrust, releaseMobileMic, transcribeRecording } from '../pushToTalk';

const mockGetInfo = jest.fn<(...args: unknown[]) => Promise<unknown>>();
const mockUpload = jest.fn<() => Promise<unknown>>();
const mockCancel = jest.fn<() => Promise<unknown>>();
const mockCreateUploadTask = jest.fn<(...args: unknown[]) => unknown>();
jest.mock('expo-file-system/legacy', () => ({
  cacheDirectory: 'file:///app/cache/',
  getInfoAsync: (...args: unknown[]) => mockGetInfo(...args),
  createUploadTask: (...args: unknown[]) => mockCreateUploadTask(...args),
  FileSystemUploadType: { BINARY_CONTENT: 0 },
  FileSystemSessionType: { FOREGROUND: 1 },
}));

const config = { baseUrl: 'hub.local/', token: ' user-secret ', adminToken: ' admin-secret ' };
const uri = 'file:///app/cache/recording.m4a';
const fetchMock = jest.fn() as jest.MockedFunction<typeof fetch>;
const reply = (body: unknown, status = 200): Response => ({
  status, ok: status >= 200 && status < 300,
  headers: { get: () => null },
  text: async () => JSON.stringify(body),
} as unknown as Response);
const uploaded = (body: unknown, status = 200) => ({ status, body: JSON.stringify(body), headers: {}, mimeType: 'application/json' });

beforeEach(() => {
  fetchMock.mockReset(); (globalThis as any).fetch = fetchMock;
  mockGetInfo.mockReset().mockResolvedValue({ exists: true, isDirectory: false, size: 1024, uri });
  mockUpload.mockReset().mockResolvedValue(uploaded({ text: ' Salut! ' }));
  mockCancel.mockReset().mockResolvedValue(undefined);
  mockCreateUploadTask.mockReset().mockImplementation(() => ({ uploadAsync: mockUpload, cancelAsync: mockCancel }));
});

describe('push-to-talk native transport', () => {
  it('requires exact on trust status and includes both configured token headers', async () => {
    fetchMock.mockResolvedValueOnce(reply({ mic: 'on' }));
    await expect(readMicTrust(config, new AbortController().signal)).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith('http://hub.local/api/trust/status', expect.objectContaining({
      method: 'GET', headers: expect.objectContaining({ 'X-User-Token': 'user-secret', 'X-Admin-Token': 'admin-secret' }),
    }));
    for (const value of ['off', 'unknown', true, undefined]) {
      fetchMock.mockResolvedValueOnce(reply({ mic: value }));
      await expect(readMicTrust(config, new AbortController().signal)).rejects.toThrow('Microphone unavailable.');
    }
    fetchMock.mockResolvedValueOnce(reply({ mic: 'on', error: 'internal error' }));
    await expect(readMicTrust(config, new AbortController().signal)).rejects.toThrow('Microphone unavailable.');
  });

  it('sends no take-over and accepts only its own armed mobile lease', async () => {
    const client = 'phone-abc';
    const lease = { surface: 'mobile:phone-abc', device: 'mobile:phone-abc', kind: 'mobile', client, state: 'armed' };
    fetchMock.mockResolvedValueOnce(reply({ ok: true, lease }));
    await expect(armMobileMic(config, client, new AbortController().signal)).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith('http://hub.local/api/voice/mic/arm', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ surface: 'mobile', client, take_over: false }),
    }));
    fetchMock.mockResolvedValueOnce(reply({ ok: true, lease: { ...lease, device: 'host' } }));
    await expect(armMobileMic(config, client, new AbortController().signal)).rejects.toThrow('Microphone lease unavailable.');
    fetchMock.mockResolvedValueOnce(reply({ error: 'owner refused', token: 'user-secret' }, 403));
    await expect(armMobileMic(config, client, new AbortController().signal)).rejects.toThrow('Microphone lease unavailable.');
  });

  it('releases its own surface best effort within three seconds', async () => {
    fetchMock.mockResolvedValueOnce(reply({ ok: true, stopped: true }));
    await expect(releaseMobileMic(config, 'phone-abc')).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith('http://hub.local/api/voice/mic/stop', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ surface: 'mobile:phone-abc' }),
    }));
    jest.useFakeTimers();
    try {
      fetchMock.mockImplementationOnce(() => new Promise<Response>(() => {}));
      const pending = releaseMobileMic(config, 'phone-abc');
      const done = expect(pending).resolves.toBeUndefined();
      await jest.advanceTimersByTimeAsync(3001);
      await done;
    } finally { jest.useRealTimers(); }
  });

  it('uploads a checked cache file as foreground raw audio and returns exact speech', async () => {
    await expect(transcribeRecording(config, uri, new AbortController().signal)).resolves.toBe(' Salut! ');
    expect(mockGetInfo).toHaveBeenCalledWith(uri);
    expect(mockCreateUploadTask).toHaveBeenCalledWith('http://hub.local/api/voice/stt?lang=ro', uri, expect.objectContaining({
      httpMethod: 'POST', uploadType: 0, sessionType: 1,
      headers: expect.objectContaining({ 'Content-Type': 'audio/mp4', 'X-User-Token': 'user-secret', 'X-Admin-Token': 'admin-secret' }),
    }));
    expect(mockUpload).toHaveBeenCalledTimes(1);
  });

  it('refuses non-cache or oversized recordings before upload', async () => {
    await expect(transcribeRecording(config, 'file:///other/recording.m4a', new AbortController().signal)).rejects.toThrow('Recording unavailable.');
    await expect(transcribeRecording(config, 'file:///app/cache/../other/recording.m4a', new AbortController().signal)).rejects.toThrow('Recording unavailable.');
    expect(mockGetInfo).not.toHaveBeenCalled();
    mockGetInfo.mockResolvedValueOnce({ exists: true, isDirectory: false, size: 2 * 1024 * 1024 + 1, uri });
    await expect(transcribeRecording(config, uri, new AbortController().signal)).rejects.toThrow('Recording unavailable.');
    expect(mockCreateUploadTask).not.toHaveBeenCalled();
  });

  it('dispatches nothing for a pre-aborted signal and cancels a hung native upload', async () => {
    const preAborted = new AbortController(); preAborted.abort();
    await expect(readMicTrust(config, preAborted.signal)).rejects.toThrow('Microphone request cancelled.');
    await expect(transcribeRecording(config, uri, preAborted.signal)).rejects.toThrow('Microphone request cancelled.');
    expect(fetchMock).not.toHaveBeenCalled();
    expect(mockGetInfo).not.toHaveBeenCalled();
    mockUpload.mockImplementationOnce(() => new Promise(() => {}));
    mockCancel.mockImplementationOnce(() => new Promise(() => {}));
    const controller = new AbortController();
    const pending = transcribeRecording(config, uri, controller.signal);
    await Promise.resolve(); await Promise.resolve();
    controller.abort();
    await expect(pending).rejects.toThrow('Microphone request cancelled.');
    expect(mockCancel).toHaveBeenCalledTimes(1);
  });

  it('bounds a native getInfo hang and never uploads after its deadline', async () => {
    jest.useFakeTimers();
    try {
      mockGetInfo.mockImplementationOnce(() => new Promise(() => {}));
      const pending = transcribeRecording(config, uri, new AbortController().signal);
      const assertion = expect(pending).rejects.toThrow('Recording could not be transcribed.');
      await jest.advanceTimersByTimeAsync(60001);
      await assertion;
      expect(mockCreateUploadTask).not.toHaveBeenCalled();
    } finally { jest.useRealTimers(); }
  });

  it('times out an ignored native upload and cancels it without waiting for cancelAsync', async () => {
    jest.useFakeTimers();
    try {
      mockUpload.mockImplementationOnce(() => new Promise(() => {}));
      mockCancel.mockImplementationOnce(() => new Promise(() => {}));
      const pending = transcribeRecording(config, uri, new AbortController().signal);
      const assertion = expect(pending).rejects.toThrow('Recording could not be transcribed.');
      await jest.advanceTimersByTimeAsync(60001);
      await assertion;
      expect(mockCancel).toHaveBeenCalledTimes(1);
    } finally { jest.useRealTimers(); }
  });

  it('bounds response JSON and distinguishes sentinels from other bracketed speech', async () => {
    for (const text of ['', '[silence]']) {
      mockUpload.mockResolvedValueOnce(uploaded({ text }));
      await expect(transcribeRecording(config, uri, new AbortController().signal)).resolves.toBe('');
    }
    mockUpload.mockResolvedValueOnce(uploaded({ text: '[door closes]' }));
    await expect(transcribeRecording(config, uri, new AbortController().signal)).resolves.toBe('[door closes]');
    for (const text of ['[STT error: bad]', '[STT unavailable]']) {
      mockUpload.mockResolvedValueOnce(uploaded({ text }));
      await expect(transcribeRecording(config, uri, new AbortController().signal)).rejects.toThrow('Recording could not be transcribed.');
    }
    mockUpload.mockResolvedValueOnce(uploaded({ text: 'x'.repeat(4001), token: 'user-secret' }));
    await expect(transcribeRecording(config, uri, new AbortController().signal)).rejects.toThrow('Recording could not be transcribed.');
    mockUpload.mockResolvedValueOnce({ status: 200, body: 'x'.repeat(65537), headers: {}, mimeType: 'application/json' });
    await expect(transcribeRecording(config, uri, new AbortController().signal)).rejects.toThrow('Recording could not be transcribed.');
  });
});
