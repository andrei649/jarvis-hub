import { createAudioPlayer, setAudioModeAsync, type AudioPlayer } from 'expo-audio';
import * as FileSystem from 'expo-file-system/legacy';
import { ttsFetchBase64 } from '../api/client';
import type { ServerConfig } from '../storage/settings';

/**
 * Speak text via the hub's /tts endpoint: fetch MP3 bytes, cache them, play
 * with expo-audio. Only one utterance plays at a time. Failures bubble up so
 * the UI can surface them; callers should catch.
 */

let current: AudioPlayer | null = null;

export async function speak(
  config: ServerConfig,
  text: string,
  lang = 'ro',
  onEnd?: () => void,
): Promise<void> {
  stopSpeaking();

  const base64 = await ttsFetchBase64(config, text, lang);
  const uri = `${FileSystem.cacheDirectory ?? ''}jarvis-tts-${Date.now()}.mp3`;
  await FileSystem.writeAsStringAsync(uri, base64, { encoding: FileSystem.EncodingType.Base64 });

  // Play even when the iOS ringer switch is silenced.
  try {
    await setAudioModeAsync({ playsInSilentMode: true });
  } catch {
    // Non-fatal — fall back to default audio session.
  }

  const player = createAudioPlayer({ uri });
  current = player;
  const sub = player.addListener('playbackStatusUpdate', (status) => {
    if (status.didJustFinish) {
      try {
        sub.remove();
      } catch {
        // ignore
      }
      stopSpeaking();
      onEnd?.();
    }
  });
  player.play();
}

export function stopSpeaking(): void {
  if (current) {
    try {
      current.remove();
    } catch {
      // ignore — already released
    }
    current = null;
  }
}
