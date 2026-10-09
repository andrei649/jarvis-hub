/** One explicitly held microphone request. This module has no native or React imports. */
export type DictationState = {
  status: 'off' | 'idle' | 'listening' | 'stopping' | 'transcribing' | 'error';
  level?: number;
  reason?: 'stop_unconfirmed';
};
export type DictationRecorder = {
  prepare(): Promise<void>;
  record(options: { forDuration: number }): void;
  stop(): Promise<string | null>;
  status(): { isRecording: boolean; metering?: number; url?: string | null };
  release?(): void;
};
export type PushToTalkDeps = {
  requestPermission(): Promise<boolean>;
  checkPermission(): Promise<boolean>;
  checkTrust(signal: AbortSignal): Promise<void>;
  arm(signal: AbortSignal, client: string): Promise<void>;
  releaseLease(client: string): Promise<void>;
  transcribe(uri: string, signal: AbortSignal): Promise<string>;
  deleteRecording(uri: string): Promise<void>;
  recorder: DictationRecorder;
  onState(state: DictationState): void;
  onTranscript(text: string): void;
  onNoSpeech(): void;
  onStart?(): void;
};

const SETUP_MS = 10_000;
const GUARD_MS = 3_000;
const RECORD_MS = 15_000;
const START_MS = 1_500;
const STOP_RECOVERY_MS = 16_000;
const CLEANUP_WATCH_MS = 3_000;
const CANCELLED = Symbol('cancelled');
let hardwareTail: Promise<void> = Promise.resolve();
let hardwareReservations = 0;
export function isMicrophoneBusy(): boolean { return hardwareReservations > 0; }
/** Wait for the native recorder and its audio-mode cleanup across keyed screens. */
export async function waitForMicrophoneIdle(): Promise<void> {
  for (;;) {
    const tail = hardwareTail;
    await tail;
    if (tail === hardwareTail) return;
  }
}
let clientSequence = 0;
function nextClient(): string {
  return `mobile-ptt-${Date.now().toString(36)}-${(++clientSequence).toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

type Phase = 'setup' | 'starting' | 'recording' | 'finishing' | 'transcribing';
type Session = {
  generation: number;
  client: string;
  phase: Phase;
  held: boolean;
  abort: AbortController;
  setupTimer: ReturnType<typeof setTimeout> | null;
  startTimer: ReturnType<typeof setTimeout> | null;
  pollTimer: ReturnType<typeof setInterval> | null;
  guardTimer: ReturnType<typeof setInterval> | null;
  recordTimer: ReturnType<typeof setTimeout> | null;
  startedAt: number;
  prepared: boolean;
  preparePromise: Promise<void> | null;
  unlock: (() => void) | null;
  cleanupPromise: Promise<void> | null;
  cleanupWatch: ReturnType<typeof setTimeout> | null;
  stopPromise: Promise<string | null> | null;
  finishPromise: Promise<void> | null;
  file: string | null;
  nativeReleased: boolean;
  stopped: boolean;
  guardBusy: boolean;
  retiredGeneration: number;
  retiredStatus: 'off' | 'error';
};

function levelFromDb(db: number | undefined): number | undefined {
  if (typeof db !== 'number' || !Number.isFinite(db)) return undefined;
  return Math.max(0, Math.min(1, 10 ** (db / 20)));
}

function bounded<T>(operation: Promise<T>, ms: number, signal: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (result: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal.removeEventListener('abort', aborted);
      result();
    };
    const aborted = () => finish(() => reject(new Error('Dictation cancelled')));
    const timer = setTimeout(() => finish(() => reject(new Error('Dictation timed out'))), ms);
    signal.addEventListener('abort', aborted, { once: true });
    if (signal.aborted) aborted();
    operation.then(value => finish(() => resolve(value)), error => finish(() => reject(error)));
  });
}

export class PushToTalkController {
  private state: DictationState = { status: 'off' };
  private generation = 0;
  private current: Session | null = null;
  private disposed = false;

  constructor(private readonly deps: PushToTalkDeps) {}

  getState(): DictationState { return this.state; }

  private publish(status: DictationState['status'], level?: number, reason?: DictationState['reason']) {
    if (this.state.status === status && this.state.level === level && this.state.reason === reason) return;
    this.state = { status, ...(level === undefined ? {} : { level }), ...(reason ? { reason } : {}) };
    this.deps.onState(this.state);
  }

  private owns(session: Session) {
    return this.current === session && this.generation === session.generation && !session.abort.signal.aborted;
  }

  private clearTimers(session: Session) {
    if (session.setupTimer) clearTimeout(session.setupTimer);
    if (session.startTimer) clearTimeout(session.startTimer);
    if (session.pollTimer) clearInterval(session.pollTimer);
    if (session.guardTimer) clearInterval(session.guardTimer);
    if (session.recordTimer) clearTimeout(session.recordTimer);
    session.setupTimer = session.startTimer = session.recordTimer = null;
    session.pollTimer = session.guardTimer = null;
  }

  /** Stop and delete a native recording before releasing this module-wide mic slot. */
  private cleanup(session: Session): Promise<void> {
    if (session.cleanupPromise) return session.cleanupPromise;
    session.cleanupPromise = (async () => {
      if (session.nativeReleased) {
        if (session.file) await this.deps.deleteRecording(session.file).catch(() => {});
        return;
      }
      let confirmed = !session.unlock;
      try {
        if (session.preparePromise) {
          const prepared = await session.preparePromise.then(() => true, () => false);
          if (prepared) session.prepared = true;
        }
        if (!session.prepared) confirmed = true;
        if (session.prepared && !session.stopped) {
          session.stopped = true;
          session.stopPromise = this.deps.recorder.stop();
        }
        if (session.stopPromise) {
          try { session.file ??= await session.stopPromise; } catch { /* inspect any native URI below */ }
        }
        const recoveryDeadline = Date.now() + STOP_RECOVERY_MS;
        let retries = 0;
        while (session.prepared) {
          let recording = true;
          try { recording = this.deps.recorder.status().isRecording; } catch { /* fail closed */ }
          if (!recording) { confirmed = true; break; }
          if (this.generation === session.retiredGeneration && !this.current) {
            this.publish('error', undefined, 'stop_unconfirmed');
          }
          if (retries < 2) {
            retries++;
            session.stopPromise = this.deps.recorder.stop();
            try { session.file ??= await session.stopPromise; } catch { /* keep the slot */ }
          }
          if (Date.now() >= recoveryDeadline) break;
          await new Promise<void>(resolve => setTimeout(resolve, 250));
        }
        if (session.prepared) session.file ??= this.deps.recorder.status().url ?? null;
      } catch {
        // Capture any partial file while its native object is still owned.
        try { session.file ??= this.deps.recorder.status().url ?? null; } catch { /* unknown */ }
      }
      finally {
        if (confirmed) {
          if (session.cleanupWatch) clearTimeout(session.cleanupWatch);
          session.cleanupWatch = null;
          session.nativeReleased = true;
          try { this.deps.recorder.release?.(); } catch { /* best effort native release */ }
          session.unlock?.(); session.unlock = null;
          if (this.generation === session.retiredGeneration && !this.current) {
            this.publish(session.retiredStatus);
          }
        }
      }
      if (confirmed && session.file) await this.deps.deleteRecording(session.file).catch(() => {});
    })();
    return session.cleanupPromise;
  }

  private terminate(session: Session, status: 'off' | 'error') {
    if (!this.owns(session)) return;
    this.generation++;
    session.retiredGeneration = this.generation;
    session.retiredStatus = status;
    this.current = null;
    session.abort.abort();
    this.clearTimers(session);
    this.publish(session.unlock ? 'stopping' : status);
    if (session.unlock) {
      session.cleanupWatch = setTimeout(() => {
        if (session.unlock && this.generation === session.retiredGeneration && !this.current) {
          this.publish('error', undefined, 'stop_unconfirmed');
        }
      }, CLEANUP_WATCH_MS);
    }
    void this.cleanup(session);
    void this.deps.releaseLease(session.client).catch(() => {});
  }

  private async acquireHardware(session: Session) {
    const previous = hardwareTail;
    hardwareReservations++;
    let release = () => {};
    hardwareTail = new Promise<void>(resolve => {
      let released = false;
      release = () => {
        if (released) return;
        released = true;
        hardwareReservations--;
        resolve();
      };
    });
    await previous;
    session.unlock = release;
    if (!this.owns(session)) { release(); session.unlock = null; return false; }
    return true;
  }

  private async guard(session: Session, includePermission: boolean) {
    if (includePermission && !await bounded(this.deps.checkPermission(), GUARD_MS, session.abort.signal)) {
      throw new Error('Microphone permission removed');
    }
    await bounded(this.deps.checkTrust(session.abort.signal), GUARD_MS, session.abort.signal);
    if (!this.owns(session)) throw new Error('Dictation cancelled');
    const armed = this.deps.arm(session.abort.signal, session.client);
    void armed.then(() => {
      if (!this.owns(session)) void this.deps.releaseLease(session.client).catch(() => {});
    }, () => {});
    await bounded(armed, GUARD_MS, session.abort.signal);
  }

  press(): void {
    if (this.disposed || this.current || this.state.status === 'stopping' || this.state.reason === 'stop_unconfirmed') return;
    this.deps.onStart?.();
    const session: Session = {
      generation: ++this.generation, client: nextClient(), phase: 'setup', held: true, abort: new AbortController(),
      setupTimer: null, startTimer: null, pollTimer: null, guardTimer: null, recordTimer: null,
      startedAt: 0, prepared: false, preparePromise: null, unlock: null, cleanupPromise: null,
      stopPromise: null, cleanupWatch: null, finishPromise: null, file: null,
      nativeReleased: false, stopped: false, guardBusy: false,
      retiredGeneration: 0, retiredStatus: 'off',
    };
    this.current = session;
    this.publish('idle');
    session.setupTimer = setTimeout(() => this.terminate(session, 'error'), SETUP_MS);
    void this.setup(session);
  }

  private async setup(session: Session) {
    try {
      const permitted = await bounded(this.deps.requestPermission(), SETUP_MS, session.abort.signal);
      if (!this.owns(session)) return;
      if (!permitted) throw new Error('Microphone permission denied');
      await this.guard(session, false);
      if (!this.owns(session)) return;
      if (!await this.acquireHardware(session)) return;
      session.preparePromise = this.deps.recorder.prepare();
      await bounded(session.preparePromise, SETUP_MS, session.abort.signal);
      session.prepared = true;
      if (!this.owns(session)) return;
      await this.guard(session, true); // preparation may have outlived the initial trust result
      if (!this.owns(session) || !session.held) return;
      session.startedAt = Date.now();
      this.deps.recorder.record({ forDuration: 15 });
      session.phase = 'starting';
      session.setupTimer && clearTimeout(session.setupTimer);
      session.setupTimer = null;
      session.startTimer = setTimeout(() => {
        if (this.owns(session) && session.phase === 'starting') this.terminate(session, 'error');
      }, START_MS);
      session.pollTimer = setInterval(() => this.sample(session), 100);
      this.sample(session);
    } catch {
      this.terminate(session, 'error');
    }
  }

  private sample(session: Session) {
    if (!this.owns(session) || (session.phase !== 'starting' && session.phase !== 'recording')) return;
    let status: ReturnType<DictationRecorder['status']>;
    try { status = this.deps.recorder.status(); }
    catch { this.terminate(session, 'error'); return; }
    if (!status.isRecording) {
      if (session.phase === 'recording') {
        if (Date.now() - session.startedAt >= RECORD_MS - 100) void this.finish(session);
        else this.terminate(session, 'error');
      }
      return;
    }
    if (session.phase === 'starting') {
      session.phase = 'recording';
      if (session.startTimer) clearTimeout(session.startTimer);
      session.startTimer = null;
      session.guardTimer = setInterval(() => {
        if (!this.owns(session) || session.phase !== 'recording' || session.guardBusy) return;
        session.guardBusy = true;
        void this.guard(session, true).catch(() => this.terminate(session, 'error'))
          .finally(() => { session.guardBusy = false; });
      }, 2000);
      session.recordTimer = setTimeout(() => { if (this.owns(session)) void this.finish(session); },
        Math.max(0, RECORD_MS - (Date.now() - session.startedAt)));
    }
    this.publish('listening', levelFromDb(status.metering));
  }

  release(): Promise<void> {
    const session = this.current;
    if (!session) return Promise.resolve();
    session.held = false;
    if (session.phase !== 'recording') {
      if (session.phase === 'finishing' || session.phase === 'transcribing') return session.finishPromise ?? Promise.resolve();
      this.terminate(session, 'off');
      return Promise.resolve();
    }
    return this.finish(session);
  }

  private finish(session: Session): Promise<void> {
    if (session.finishPromise) return session.finishPromise;
    session.phase = 'finishing';
    this.clearTimers(session);
    this.publish('stopping');
    session.finishPromise = (async () => {
      try {
        session.stopped = true;
        session.stopPromise = this.deps.recorder.stop();
        session.file = await bounded(session.stopPromise, GUARD_MS, session.abort.signal);
        if (!this.owns(session)) return;
        const finalStatus = this.deps.recorder.status();
        if (finalStatus.isRecording) throw new Error('Native recorder still active');
        session.file ??= finalStatus.url ?? null;
        session.nativeReleased = true;
        try { this.deps.recorder.release?.(); } catch { /* stop is confirmed */ }
        session.unlock?.(); session.unlock = null;
        if (!session.file) throw new Error('No recording file');
        await this.guard(session, true);
        if (!this.owns(session)) return;
        session.phase = 'transcribing';
        this.publish('transcribing');
        const transcript = await bounded(this.deps.transcribe(session.file, session.abort.signal), 60_000, session.abort.signal);
        if (!this.owns(session)) return;
        this.generation++;
        this.current = null;
        session.abort.abort();
        this.publish('idle');
        const text = transcript.trim();
        if (text) this.deps.onTranscript(text);
        else this.deps.onNoSpeech();
      } catch {
        this.terminate(session, 'error');
      } finally {
        if (!session.cleanupPromise) {
          if (session.file) await this.deps.deleteRecording(session.file).catch(() => {});
          session.unlock?.(); session.unlock = null;
        }
        void this.deps.releaseLease(session.client).catch(() => {});
      }
    })();
    return session.finishPromise;
  }

  cancel(): Promise<void> {
    const session = this.current;
    if (session) this.terminate(session, 'off');
    else if (this.state.status !== 'stopping' && this.state.reason !== 'stop_unconfirmed') this.publish('off');
    return Promise.resolve();
  }

  dispose(): void {
    this.disposed = true;
    void this.cancel();
  }
}
