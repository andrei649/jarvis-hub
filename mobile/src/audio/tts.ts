import { createAudioPlayer, setAudioModeAsync, type AudioPlayer } from 'expo-audio';
import * as FileSystem from 'expo-file-system/legacy';
import { ttsFetchBase64 } from '../api/client';
import type { ServerConfig } from '../storage/settings';

export type SpeechState = { status: 'off' | 'preparing' | 'speaking' | 'error' };

const CANCELLED = Symbol('speech cancelled');
const PREPARATION_TIMEOUT_MS = 35_000;
const PLAYBACK_START_TIMEOUT_MS = 15_000;
const listeners = new Set<() => void>();
let snapshot: SpeechState = { status: 'off' };
let epoch = 0;
let fileSequence = 0;

type Session = {
  epoch: number;
  uri: string | null;
  player: AudioPlayer | null;
  subscription: { remove(): void } | null;
  startupTimer: ReturnType<typeof setTimeout> | null;
  retired: boolean;
  cancel: () => void;
  cancelled: Promise<typeof CANCELLED>;
};
let active: Session | null = null;

export function getSpeechState(): SpeechState { return snapshot; }

export function subscribeSpeech(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

function publish(status: SpeechState['status']) {
  if (snapshot.status === status) return;
  snapshot = { status };
  for (const listener of listeners) listener();
}

function deleteFile(uri: string) {
  try { void FileSystem.deleteAsync(uri, { idempotent: true }).catch(() => {}); }
  catch { /* best effort cache cleanup */ }
}

function retire(session: Session, status: SpeechState['status']) {
  if (session.retired) return;
  session.retired = true;
  session.cancel();
  if (session.startupTimer) clearTimeout(session.startupTimer);
  try { session.subscription?.remove(); } catch { /* already removed */ }
  try { session.player?.remove(); } catch { /* already released */ }
  if (session.uri) deleteFile(session.uri);
  if (active === session) {
    active = null;
    publish(status);
  }
}

function isCurrent(session: Session) {
  return active === session && !session.retired && session.epoch === epoch;
}

/** Fetch, cache and play one hub-synthesized utterance. The returned promise
 * covers preparation; playback completion is delivered through onEnd and state. */
export async function speak(
  config: ServerConfig,
  text: string,
  lang = 'ro',
  onEnd?: () => void,
): Promise<void> {
  epoch++;
  if (active) retire(active, 'off');
  if (!text.trim()) { publish('off'); onEnd?.(); return; }

  let cancel = () => {};
  const cancelled = new Promise<typeof CANCELLED>((resolve) => { cancel = () => resolve(CANCELLED); });
  const session: Session = {
    epoch, uri: null, player: null, subscription: null, startupTimer: null,
    retired: false, cancel, cancelled,
  };
  active = session;
  publish('preparing');

  let timeout: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_, reject) => {
    timeout = setTimeout(() => reject(new Error('Speech preparation timed out')), PREPARATION_TIMEOUT_MS);
  });
  const wait = <T>(operation: Promise<T>): Promise<T | typeof CANCELLED> =>
    Promise.race([operation, cancelled, deadline]);

  try {
    const base64 = await wait(ttsFetchBase64(config, text, lang));
    if (base64 === CANCELLED || !isCurrent(session)) return;
    if (!base64) {
      retire(session, 'off');
      onEnd?.();
      return;
    }

    const directory = FileSystem.cacheDirectory;
    if (!directory) throw new Error('Speech cache is unavailable');
    const uri = `${directory}jarvis-tts-${Date.now()}-${++fileSequence}.mp3`;
    session.uri = uri;
    const writing = FileSystem.writeAsStringAsync(uri, base64, { encoding: FileSystem.EncodingType.Base64 });
    // A native write can finish after stop, replacement, or timeout. Delete again
    // then so a late partial/completed file cannot remain in the cache.
    void writing.then(() => { if (session.retired) deleteFile(uri); }, () => { if (session.retired) deleteFile(uri); });
    const wrote = await wait(writing);
    if (wrote === CANCELLED || !isCurrent(session)) return;

    // Fall back to the default audio session when silent-mode configuration fails.
    const mode = setAudioModeAsync({ playsInSilentMode: true }).catch(() => {});
    const prepared = await wait(mode);
    if (prepared === CANCELLED || !isCurrent(session)) return;

    const player = createAudioPlayer({ uri });
    session.player = player;
    let started = false;
    session.subscription = player.addListener('playbackStatusUpdate', (status) => {
      if (!isCurrent(session)) return;
      if (status.error) { retire(session, 'error'); onEnd?.(); return; }
      if (status.didJustFinish) { retire(session, 'off'); onEnd?.(); return; }
      if (status.playing === true && status.isBuffering !== true) {
        started = true;
        if (session.startupTimer) clearTimeout(session.startupTimer);
        session.startupTimer = null;
      }
      publish(status.playing === true && status.isBuffering !== true
        ? 'speaking' : status.isBuffering === true ? 'preparing' : 'off');
    });
    if (!isCurrent(session)) return;
    player.play();
    if (isCurrent(session) && !started) {
      session.startupTimer = setTimeout(() => {
        if (isCurrent(session) && !started) { retire(session, 'error'); onEnd?.(); }
      }, PLAYBACK_START_TIMEOUT_MS);
    }
  } catch (error) {
    if (isCurrent(session)) { retire(session, 'error'); throw error; }
  } finally {
    if (timeout) clearTimeout(timeout);
  }
}

export function stopSpeaking(): void {
  epoch++;
  if (active) retire(active, 'off');
  else publish('off');
}
