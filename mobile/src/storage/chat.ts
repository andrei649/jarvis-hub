import AsyncStorage from '@react-native-async-storage/async-storage';
import type { ChatMessage } from '../chat/types';

/** Local persistence of the chat thread so conversations survive app restarts. */

const KEY = 'jarvis.chat.history.v1';
const MAX_MESSAGES = 200;

export async function loadHistory(): Promise<ChatMessage[]> {
  try {
    const raw = await AsyncStorage.getItem(KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed as ChatMessage[];
    }
  } catch {
    // Corrupt/unavailable storage — start fresh.
  }
  return [];
}

export async function saveHistory(messages: ChatMessage[]): Promise<void> {
  // Never persist in-flight (streaming) messages, and cap the stored thread.
  const settled = messages.filter((m) => !m.pending).slice(-MAX_MESSAGES);
  try {
    await AsyncStorage.setItem(KEY, JSON.stringify(settled));
  } catch {
    // Best-effort — losing history is acceptable, crashing is not.
  }
}

export async function clearHistory(): Promise<void> {
  try {
    await AsyncStorage.removeItem(KEY);
  } catch {
    // ignore
  }
}
