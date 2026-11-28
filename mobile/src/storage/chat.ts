import AsyncStorage from '@react-native-async-storage/async-storage';
import type { ChatMessage } from '../chat/types';
import { modelCalls } from '../api/modelCallProvenance';
import { toolActivity, turnRecalls } from '../chat/turnOutcome';
import { projectSavedChatNote } from '../api/chatNote';
import { historySourceReceipt } from '../api/sessionTranscript';

/** Local persistence of the chat thread so conversations survive app restarts. */

const KEY = 'jarvis.chat.history.v1';
const MAX_MESSAGES = 200;
const MAX_RECOVERY_PROMPT = 4096;
const CONVERSATION_KEY = 'jarvis.chat.conversation.v2';
let writes: Promise<void> = Promise.resolve();

export type SavedConversation = {
  sessionId: string | null;
  messages: ChatMessage[];
  recoveryPrompt?: string | null;
};

function validRecoveryPrompt(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0 && value.length <= MAX_RECOVERY_PROMPT;
}

function settledMessages(value: unknown, includeReceipts = false): ChatMessage[] {
  if (!Array.isArray(value)) return [];
  return value.filter((m): m is ChatMessage => m && typeof m === 'object'
    && typeof m.id === 'string' && typeof m.text === 'string'
    && (m.role === 'user' || m.role === 'assistant') && !m.pending).slice(-MAX_MESSAGES)
    .map(m => {
      const nativeReply = includeReceipts && m.role === 'assistant' && m.error !== true
        && !Object.prototype.hasOwnProperty.call(m, 'foreign_origin')
        && !Object.prototype.hasOwnProperty.call(m, 'tainted');
      const completed = nativeReply && m.completed === true && !!m.text.trim();
      const calls = nativeReply ? modelCalls(m.modelCalls) : [];
      const savedNote = completed ? projectSavedChatNote(m.savedNote) : null;
      const activity = completed && m.agent !== 'system' ? toolActivity(m.toolActivity) : undefined;
      const recall = completed && m.agent !== 'system' ? turnRecalls(m.recall) : null;
      const source = includeReceipts && m.role === 'user'
        && !Object.prototype.hasOwnProperty.call(m, 'foreign_origin')
        && !Object.prototype.hasOwnProperty.call(m, 'tainted')
        ? historySourceReceipt(m.historySource) : null;
      return { id: m.id, role: m.role, text: m.text,
        ...(typeof m.agent === 'string' ? { agent: m.agent } : {}),
        ...(m.error === true ? { error: true } : {}),
        ...(completed ? { completed: true as const } : {}),
        ...(activity ? { toolActivity: activity } : {}),
        ...(recall ? { recall } : {}),
        ...(calls.length ? { modelCalls: calls } : {}),
        ...(savedNote ? { savedNote } : {}),
        ...(source ? { historySource: source } : {}) };
    });
}

/** A connection's opaque scope binds history without copying its credentials. */
export async function loadConversation(scope: string): Promise<SavedConversation> {
  try {
    await writes;
    const raw = await AsyncStorage.getItem(CONVERSATION_KEY);
    const record = raw ? JSON.parse(raw) : null;
    if (scope && record?.version === 2 && record.scope === scope
      && (record.sessionId === null || (typeof record.sessionId === 'string'
        && /^[A-Za-z0-9_-]{1,128}$/.test(record.sessionId)))) {
      return { sessionId: record.sessionId, messages: settledMessages(record.messages, true),
        ...(validRecoveryPrompt(record.recoveryPrompt) ? { recoveryPrompt: record.recoveryPrompt } : {}) };
    }
  } catch { /* Unavailable/corrupt storage never chooses another session. */ }
  // The legacy unscoped cache is retained, but never attached to a different hub.
  return { sessionId: null, messages: [] };
}

/** Store the ID and transcript atomically, serializing writes in selection order. */
export function saveConversation(scope: string, conversation: SavedConversation): Promise<void> {
  if (!scope) return Promise.resolve();
  const snapshot = JSON.stringify({ version: 2, scope, sessionId: conversation.sessionId,
    messages: settledMessages(conversation.messages, true),
    ...(validRecoveryPrompt(conversation.recoveryPrompt) ? { recoveryPrompt: conversation.recoveryPrompt } : {}) });
  writes = writes.catch(() => {}).then(() => AsyncStorage.setItem(CONVERSATION_KEY, snapshot)).catch(() => {});
  return writes;
}

export async function loadHistory(): Promise<ChatMessage[]> {
  try {
    const raw = await AsyncStorage.getItem(KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return settledMessages(parsed);
    }
  } catch {
    // Corrupt/unavailable storage — start fresh.
  }
  return [];
}

export async function saveHistory(messages: ChatMessage[]): Promise<void> {
  // Never persist in-flight (streaming) messages, and cap the stored thread.
  const settled = settledMessages(messages);
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
