import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { createAudioPlayer, setAudioModeAsync } from 'expo-audio';
import * as FileSystem from 'expo-file-system/legacy';
import { ttsFetchBase64 } from '../../api/client';
import { getSpeechState, speak, stopSpeaking, subscribeSpeech } from '../tts';

jest.mock('expo-audio', () => ({ createAudioPlayer: jest.fn(), setAudioModeAsync: jest.fn() }));
jest.mock('expo-file-system/legacy', () => ({
  cacheDirectory: 'file:///cache/', EncodingType: { Base64: 'base64' },
  writeAsStringAsync: jest.fn(), deleteAsync: jest.fn(),
}));
jest.mock('../../api/client', () => ({ ttsFetchBase64: jest.fn() }));

const config = { baseUrl: 'https://hub.test', token: 'user', adminToken: '' };
const fetchMp3 = ttsFetchBase64 as jest.MockedFunction<typeof ttsFetchBase64>;
const write = FileSystem.writeAsStringAsync as jest.MockedFunction<typeof FileSystem.writeAsStringAsync>;
const removeFile = FileSystem.deleteAsync as jest.MockedFunction<typeof FileSystem.deleteAsync>;
const audioMode = setAudioModeAsync as jest.MockedFunction<typeof setAudioModeAsync>;
const makePlayer = createAudioPlayer as jest.MockedFunction<typeof createAudioPlayer>;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

async function untilCalled(mock: { mock: { calls: unknown[][] } }) {
  for (let attempt = 0; attempt < 10 && mock.mock.calls.length === 0; attempt++) await Promise.resolve();
  expect(mock.mock.calls.length).toBeGreaterThan(0);
}

function player() {
  let status: (value: any) => void = () => {};
  const sub = { remove: jest.fn() };
  const instance = {
    play: jest.fn(), remove: jest.fn(),
    addListener: jest.fn((_event: string, listener: (value: any) => void) => { status = listener; return sub; }),
  };
  makePlayer.mockReturnValueOnce(instance as any);
  return { instance, sub, emit: (value: object) => status(value) };
}

beforeEach(() => {
  stopSpeaking();
  fetchMp3.mockReset(); write.mockReset(); removeFile.mockReset(); audioMode.mockReset(); makePlayer.mockReset();
  write.mockResolvedValue(undefined); removeFile.mockResolvedValue(undefined); audioMode.mockResolvedValue(undefined);
});

describe('native speech lifecycle', () => {
  it('publishes a stable snapshot and reports speaking only from real playing status', async () => {
    const snapshots: string[] = [];
    const listener = jest.fn(() => snapshots.push(getSpeechState().status));
    const unsubscribe = subscribeSpeech(listener);
    expect(getSpeechState()).toBe(getSpeechState());
    const native = player();
    fetchMp3.mockResolvedValue('mp3');
    await speak(config, 'Salut');
    expect(native.instance.play).toHaveBeenCalledTimes(1);
    expect(getSpeechState().status).toBe('preparing');
    native.emit({ playing: false, isBuffering: true, isLoaded: true });
    expect(getSpeechState().status).toBe('preparing');
    native.emit({ playing: true, isBuffering: false, isLoaded: true });
    expect(getSpeechState().status).toBe('speaking');
    native.emit({ playing: false, isBuffering: false, isLoaded: true });
    expect(getSpeechState().status).toBe('off');
    expect(snapshots).toContain('speaking');
    unsubscribe();
    const count = listener.mock.calls.length;
    stopSpeaking();
    expect(listener).toHaveBeenCalledTimes(count);
  });

  it('fences a synthesis result after stop and never creates a late player', async () => {
    const pending = deferred<string>();
    fetchMp3.mockReturnValue(pending.promise);
    const done = jest.fn();
    const operation = speak(config, 'Old', 'ro', done);
    expect(getSpeechState().status).toBe('preparing');
    stopSpeaking();
    pending.resolve('mp3');
    await operation;
    expect(makePlayer).not.toHaveBeenCalled();
    expect(write).not.toHaveBeenCalled();
    expect(done).not.toHaveBeenCalled();
    expect(getSpeechState().status).toBe('off');
  });

  it('cleans a partial write after cancellation and ignores its late completion', async () => {
    const pending = deferred<void>();
    fetchMp3.mockResolvedValue('mp3'); write.mockReturnValueOnce(pending.promise);
    const operation = speak(config, 'Old');
    await untilCalled(write);
    const uri = write.mock.calls[0][0];
    stopSpeaking();
    pending.resolve(undefined);
    await operation;
    expect(makePlayer).not.toHaveBeenCalled();
    expect(removeFile).toHaveBeenCalledWith(uri, { idempotent: true });
    expect(getSpeechState().status).toBe('off');
  });

  it('does not create a player after a late audio-mode completion', async () => {
    const pending = deferred<void>();
    fetchMp3.mockResolvedValue('mp3'); audioMode.mockReturnValueOnce(pending.promise);
    const operation = speak(config, 'Old');
    await untilCalled(audioMode);
    stopSpeaking();
    pending.resolve(undefined);
    await operation;
    expect(makePlayer).not.toHaveBeenCalled();
    expect(removeFile).toHaveBeenCalledTimes(1);
  });

  it('ignores an old finish callback while a newer utterance plays', async () => {
    const old = player(); const next = player();
    fetchMp3.mockResolvedValue('mp3');
    const oldDone = jest.fn(); const nextDone = jest.fn();
    await speak(config, 'Old', 'ro', oldDone);
    old.emit({ playing: true, isBuffering: false });
    await speak(config, 'New', 'ro', nextDone);
    next.emit({ playing: true, isBuffering: false });
    old.emit({ didJustFinish: true, playing: false });
    expect(next.instance.remove).not.toHaveBeenCalled();
    expect(oldDone).not.toHaveBeenCalled();
    expect(getSpeechState().status).toBe('speaking');
    next.emit({ didJustFinish: true, playing: false });
    expect(nextDone).toHaveBeenCalledTimes(1);
    expect(next.sub.remove).toHaveBeenCalledTimes(1);
    expect(next.instance.remove).toHaveBeenCalledTimes(1);
    expect(getSpeechState().status).toBe('off');
    expect(removeFile).toHaveBeenCalledTimes(2);
  });

  it('reports native errors and releases the player, subscription, and mp3', async () => {
    const native = player(); fetchMp3.mockResolvedValue('mp3');
    const done = jest.fn();
    await speak(config, 'Broken', 'ro', done);
    native.emit({ playing: false, error: 'decoder failed' });
    expect(getSpeechState().status).toBe('error');
    expect(done).toHaveBeenCalledTimes(1);
    expect(native.sub.remove).toHaveBeenCalledTimes(1);
    expect(native.instance.remove).toHaveBeenCalledTimes(1);
    expect(removeFile).toHaveBeenCalledTimes(1);
  });

  it('ends startup with an error if native playback never starts', async () => {
    jest.useFakeTimers();
    try {
      const native = player(); fetchMp3.mockResolvedValue('mp3');
      const done = jest.fn();
      await speak(config, 'No status', 'ro', done);
      expect(getSpeechState().status).toBe('preparing');
      await jest.advanceTimersByTimeAsync(35000);
      expect(getSpeechState().status).toBe('error');
      expect(done).toHaveBeenCalledTimes(1);
      expect(native.instance.remove).toHaveBeenCalledTimes(1);
    } finally { stopSpeaking(); jest.useRealTimers(); }
  });

  it('settles playback when best-effort cache deletion throws immediately', async () => {
    const native = player(); fetchMp3.mockResolvedValue('mp3');
    removeFile.mockImplementationOnce(() => { throw new Error('native file API unavailable'); });
    const done = jest.fn();
    await speak(config, 'Finish', 'ro', done);
    native.emit({ didJustFinish: true, playing: false });
    expect(getSpeechState().status).toBe('off');
    expect(done).toHaveBeenCalledTimes(1);
  });

  it('ends empty speech without creating audio and creates unique cache names', async () => {
    const done = jest.fn();
    fetchMp3.mockResolvedValueOnce('').mockResolvedValue('mp3');
    await speak(config, '  ', 'ro', done);
    expect(fetchMp3).not.toHaveBeenCalled();
    await speak(config, 'Only code', 'ro', done);
    expect(done).toHaveBeenCalledTimes(2);
    expect(getSpeechState().status).toBe('off');
    expect(write).not.toHaveBeenCalled();
    player(); await speak(config, 'First');
    player(); await speak(config, 'Second');
    expect(write.mock.calls[0][0]).not.toBe(write.mock.calls[1][0]);
  });

  it('bounds preparation when synthesis hangs', async () => {
    jest.useFakeTimers();
    try {
      fetchMp3.mockReturnValue(new Promise<string>(() => {}));
      const operation = speak(config, 'Timeout');
      const assertion = expect(operation).rejects.toThrow();
      await jest.advanceTimersByTimeAsync(45000);
      await assertion;
      expect(getSpeechState().status).toBe('error');
      expect(makePlayer).not.toHaveBeenCalled();
    } finally { stopSpeaking(); jest.useRealTimers(); }
  });
});
