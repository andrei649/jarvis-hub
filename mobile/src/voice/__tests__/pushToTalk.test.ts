import { afterEach, beforeEach, describe, expect, it, jest } from '@jest/globals';
import { isMicrophoneBusy, PushToTalkController, waitForMicrophoneIdle, type PushToTalkDeps, type DictationState } from '../pushToTalk';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function fixture() {
  let recording = false;
  let metering: number | undefined = -20;
  const states: DictationState[] = [];
  const output: string[] = [];
  const recorder = {
    prepare: jest.fn(async () => {}),
    record: jest.fn((_options: { forDuration: number }) => { recording = true; }),
    stop: jest.fn(async () => { recording = false; return 'file:///clip.m4a'; }),
    release: jest.fn(),
    status: jest.fn(() => ({ isRecording: recording, metering, url: 'file:///clip.m4a' })),
  };
  const deps: PushToTalkDeps = {
    requestPermission: jest.fn(async () => true), checkPermission: jest.fn(async () => true),
    checkTrust: jest.fn(async (_signal: AbortSignal) => {}), arm: jest.fn(async (_signal: AbortSignal) => {}),
    releaseLease: jest.fn(async () => {}), transcribe: jest.fn(async (_uri: string, _signal: AbortSignal) => 'Salut'),
    deleteRecording: jest.fn(async (_uri: string) => {}), recorder,
    onState: state => states.push(state), onTranscript: text => output.push(text), onNoSpeech: jest.fn(),
    onStart: jest.fn(),
  };
  const controller = new PushToTalkController(deps);
  return { controller, deps, recorder, states, output, setRecording: (value: boolean) => { recording = value; },
    setMetering: (value: number | undefined) => { metering = value; } };
}

async function flush() { for (let index = 0; index < 80; index++) await Promise.resolve(); }

beforeEach(() => { jest.useFakeTimers(); });
afterEach(() => { jest.useRealTimers(); });

describe('explicit native push to talk', () => {
  it('never records after release while OS permission is pending', async () => {
    const f = fixture();
    const pending = deferred<boolean>();
    (f.deps.requestPermission as jest.Mock).mockReturnValue(pending.promise);
    f.controller.press();
    expect(f.deps.onStart).toHaveBeenCalledTimes(1);
    await f.controller.release();
    pending.resolve(true);
    await flush();
    expect(f.recorder.prepare).not.toHaveBeenCalled();
    expect(f.recorder.record).not.toHaveBeenCalled();
    expect(f.deps.checkTrust).not.toHaveBeenCalled();
    expect(f.controller.getState().status).toBe('off');
  });

  it('only reports listening after actual native recording and transcribes once after release', async () => {
    const f = fixture();
    f.controller.press();
    await flush();
    expect(f.recorder.record).toHaveBeenCalledWith({ forDuration: 15 });
    expect(f.controller.getState()).toEqual({ status: 'listening', level: 0.1 });
    f.setMetering(Infinity);
    await jest.advanceTimersByTimeAsync(100);
    expect(f.controller.getState()).toEqual({ status: 'listening' });
    await f.controller.release();
    expect(f.recorder.stop).toHaveBeenCalledTimes(1);
    expect(f.deps.checkTrust).toHaveBeenCalledTimes(3); // setup, before record, before STT
    expect(f.deps.transcribe).toHaveBeenCalledWith('file:///clip.m4a', expect.anything());
    expect(f.output).toEqual(['Salut']);
    expect(f.deps.deleteRecording).toHaveBeenCalledWith('file:///clip.m4a');
    expect(f.deps.releaseLease).toHaveBeenCalledTimes(1);
    expect(f.controller.getState().status).toBe('idle');
  });

  it('does not claim listening when record() did not start hardware', async () => {
    const f = fixture();
    f.recorder.record.mockImplementationOnce(() => {});
    f.controller.press(); await flush();
    expect(f.states.some(state => state.status === 'listening')).toBe(false);
    expect(f.deps.transcribe).not.toHaveBeenCalled();
    await jest.advanceTimersByTimeAsync(1500);
    expect(f.controller.getState().status).toBe('error');
  });

  it('discards audio if the recurring trust guard fails and never overlaps checks', async () => {
    const f = fixture();
    f.controller.press(); await flush();
    const pending = deferred<void>();
    (f.deps.checkTrust as jest.Mock).mockReturnValueOnce(pending.promise);
    await jest.advanceTimersByTimeAsync(2000);
    await jest.advanceTimersByTimeAsync(2000);
    expect(f.deps.checkTrust).toHaveBeenCalledTimes(3);
    pending.reject(new Error('trust off'));
    await flush();
    expect(f.recorder.stop).toHaveBeenCalledTimes(1);
    expect(f.deps.transcribe).not.toHaveBeenCalled();
    expect(f.controller.getState().status).toBe('error');
  });

  it('aborts STT and discards a late transcript after context cancellation', async () => {
    const f = fixture();
    const pending = deferred<string>();
    (f.deps.transcribe as jest.Mock).mockReturnValue(pending.promise);
    f.controller.press(); await flush();
    const finish = f.controller.release();
    await flush();
    expect(f.controller.getState().status).toBe('transcribing');
    await f.controller.cancel();
    pending.resolve('stale words');
    await finish;
    expect(f.output).toEqual([]);
    expect(f.deps.deleteRecording).toHaveBeenCalledWith('file:///clip.m4a');
    expect(f.controller.getState().status).toBe('off');
  });

  it('old STT cleanup cannot release a new recording on the same controller', async () => {
    const f = fixture();
    const pendingStt = deferred<string>();
    const pendingDelete = deferred<void>();
    (f.deps.transcribe as jest.Mock).mockReturnValueOnce(pendingStt.promise);
    f.controller.press(); await flush();
    const oldFinish = f.controller.release(); await flush();
    expect(f.recorder.release).toHaveBeenCalledTimes(1);
    (f.deps.deleteRecording as jest.Mock).mockReturnValueOnce(pendingDelete.promise);
    await f.controller.cancel();
    f.controller.press(); await flush();
    expect(f.controller.getState().status).toBe('listening');
    pendingStt.resolve('late words'); await oldFinish;
    pendingDelete.resolve(undefined); await flush();
    expect(f.recorder.stop).toHaveBeenCalledTimes(1);
    expect(f.recorder.release).toHaveBeenCalledTimes(1);
    expect(f.controller.getState().status).toBe('listening');
    await f.controller.cancel();
  });

  it('deduplicates repeated release and reports empty transcription without draft text', async () => {
    const f = fixture();
    (f.deps.transcribe as jest.MockedFunction<PushToTalkDeps['transcribe']>).mockResolvedValue('');
    f.controller.press(); await flush();
    await Promise.all([f.controller.release(), f.controller.release()]);
    expect(f.recorder.stop).toHaveBeenCalledTimes(1);
    expect(f.deps.transcribe).toHaveBeenCalledTimes(1);
    expect(f.output).toEqual([]);
    expect(f.deps.onNoSpeech).toHaveBeenCalledTimes(1);
  });

  it('times out setup and fences a late permission approval', async () => {
    const f = fixture();
    const pending = deferred<boolean>();
    (f.deps.requestPermission as jest.Mock).mockReturnValue(pending.promise);
    f.controller.press();
    await jest.advanceTimersByTimeAsync(12000);
    expect(f.controller.getState().status).toBe('error');
    pending.resolve(true); await flush();
    expect(f.recorder.record).not.toHaveBeenCalled();
  });

  it('stops a late prepared recorder before another keyed controller can prepare', async () => {
    const old = fixture();
    const latePrepare = deferred<void>();
    old.recorder.prepare.mockReturnValueOnce(latePrepare.promise);
    old.controller.press(); await flush();
    await old.controller.cancel();
    const next = fixture();
    next.controller.press(); await flush();
    expect(next.recorder.prepare).not.toHaveBeenCalled();
    latePrepare.resolve(undefined); await flush();
    expect(old.recorder.stop).toHaveBeenCalledTimes(1);
    expect(next.recorder.prepare).toHaveBeenCalledTimes(1);
    await next.controller.cancel();
  });

  it('retries a failed native stop before releasing hardware to a new controller', async () => {
    const old = fixture();
    old.controller.press(); await flush();
    old.recorder.stop.mockRejectedValueOnce(new Error('native stop failed'));
    await old.controller.release();
    await flush();
    expect(old.recorder.stop).toHaveBeenCalledTimes(2);
    await jest.advanceTimersByTimeAsync(250);
    await waitForMicrophoneIdle();
    const next = fixture(); next.controller.press(); await flush();
    expect(next.recorder.prepare).toHaveBeenCalledTimes(1);
    await next.controller.cancel();
  });

  it('holds the hardware slot if native stop still reports recording', async () => {
    const old = fixture();
    old.controller.press(); await flush();
    old.recorder.stop.mockRejectedValue(new Error('still recording'));
    await old.controller.release();
    await flush();
    expect(old.controller.getState()).toEqual({ status: 'error', reason: 'stop_unconfirmed' });
    const next = fixture(); next.controller.press(); await flush();
    expect(next.recorder.prepare).not.toHaveBeenCalled();
    old.setRecording(false);
    await jest.advanceTimersByTimeAsync(250);
    await flush();
    expect(next.recorder.prepare).toHaveBeenCalledTimes(1);
    await next.controller.cancel();
  });

  it('reports stopping until cancellation confirms native stop', async () => {
    const f = fixture();
    f.controller.press(); await flush();
    const pending = deferred<string>();
    f.recorder.stop.mockReturnValueOnce(pending.promise);
    await f.controller.cancel();
    expect(f.controller.getState().status).toBe('stopping');
    await f.controller.cancel();
    expect(f.controller.getState().status).toBe('stopping');
    f.setRecording(false);
    pending.resolve('file:///clip.m4a'); await flush();
    expect(f.controller.getState().status).toBe('off');
  });

  it('reports unconfirmed stop after a native stop promise hangs', async () => {
    const f = fixture();
    f.controller.press(); await flush();
    const pending = deferred<string>();
    f.recorder.stop.mockReturnValueOnce(pending.promise);
    await f.controller.cancel();
    await jest.advanceTimersByTimeAsync(2999);
    expect(f.controller.getState().status).toBe('stopping');
    await jest.advanceTimersByTimeAsync(1);
    expect(f.controller.getState()).toEqual({ status: 'error', reason: 'stop_unconfirmed' });
    expect(isMicrophoneBusy()).toBe(true);
    f.setRecording(false); pending.resolve('file:///clip.m4a'); await flush();
    expect(isMicrophoneBusy()).toBe(false);
  });

  it('reports unconfirmed cleanup after a late native prepare hangs', async () => {
    const f = fixture();
    const pending = deferred<void>();
    f.recorder.prepare.mockReturnValueOnce(pending.promise);
    f.controller.press(); await flush();
    await f.controller.cancel();
    await jest.advanceTimersByTimeAsync(3000);
    expect(f.controller.getState()).toEqual({ status: 'error', reason: 'stop_unconfirmed' });
    expect(f.recorder.record).not.toHaveBeenCalled();
    expect(isMicrophoneBusy()).toBe(true);
    pending.resolve(undefined); await flush();
    expect(f.recorder.stop).toHaveBeenCalledTimes(1);
    expect(isMicrophoneBusy()).toBe(false);
  });

  it('releases confirmed native hardware before a slow cache deletion', async () => {
    const old = fixture();
    const pendingDelete = deferred<void>();
    (old.deps.deleteRecording as jest.Mock).mockReturnValueOnce(pendingDelete.promise);
    old.controller.press(); await flush();
    await old.controller.cancel(); await flush();
    const next = fixture(); next.controller.press(); await flush();
    expect(next.recorder.prepare).toHaveBeenCalledTimes(1);
    expect(old.recorder.release).toHaveBeenCalledTimes(1);
    pendingDelete.resolve(undefined);
    await next.controller.cancel();
  });

  it('discards unexpected native stop and auto-finishes at the 15 second cap', async () => {
    const unexpected = fixture();
    unexpected.controller.press(); await flush();
    unexpected.setRecording(false);
    await jest.advanceTimersByTimeAsync(100);
    expect(unexpected.controller.getState().status).toBe('error');
    expect(unexpected.deps.transcribe).not.toHaveBeenCalled();

    const capped = fixture();
    capped.controller.press(); await flush();
    await jest.advanceTimersByTimeAsync(15000);
    expect(capped.deps.transcribe).toHaveBeenCalledTimes(1);
    expect(capped.output).toEqual(['Salut']);
  });
});
