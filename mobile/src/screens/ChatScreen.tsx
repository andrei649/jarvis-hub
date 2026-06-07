import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { streamChat, type HistoryTurn } from '../api/client';
import { speak, stopSpeaking } from '../audio/tts';
import type { ChatMessage } from '../chat/types';
import { AgentPicker } from '../components/AgentPicker';
import { MessageBubble } from '../components/MessageBubble';
import { SessionsModal } from '../components/SessionsModal';
import { useServer } from '../context/ServerContext';
import { clearHistory, loadHistory, saveHistory } from '../storage/chat';
import { DEFAULT_PREFS, loadPrefs, savePrefs } from '../storage/prefs';
import { theme } from '../theme';

let idSeq = 0;
const nextId = () => `m${Date.now()}_${idSeq++}`;

/** Flatten Markdown to plain text so TTS doesn't read syntax characters aloud. */
function toPlain(md: string): string {
  return md
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/\*\*?|__?/g, '')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^\s*>\s?/gm, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .trim();
}

export function ChatScreen({ onGoToSettings }: { onGoToSettings: () => void }) {
  const { config, configured } = useServer();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [agent, setAgent] = useState(DEFAULT_PREFS.agent);
  const [speakingId, setSpeakingId] = useState<string | null>(null);
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const listRef = useRef<FlatList<ChatMessage>>(null);
  const cancelRef = useRef<(() => void) | null>(null);

  // Restore persisted thread + agent preference once.
  useEffect(() => {
    loadHistory().then((h) => h.length && setMessages(h));
    loadPrefs().then((p) => setAgent(p.agent));
  }, []);

  // Persist the thread whenever it settles (never mid-stream).
  useEffect(() => {
    if (!sending) saveHistory(messages);
  }, [messages, sending]);

  // Stop any audio when leaving the screen.
  useEffect(() => () => stopSpeaking(), []);

  const scrollToEnd = useCallback(() => {
    requestAnimationFrame(() => listRef.current?.scrollToEnd({ animated: true }));
  }, []);

  const patch = useCallback((id: string, updater: (m: ChatMessage) => ChatMessage) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? updater(m) : m)));
  }, []);

  const changeAgent = useCallback((id: string) => {
    setAgent(id);
    savePrefs({ agent: id });
  }, []);

  const send = useCallback(() => {
    const text = input.trim();
    if (!text || sending || !configured) return;

    const userMsg: ChatMessage = { id: nextId(), role: 'user', text };
    const botId = nextId();
    const botMsg: ChatMessage = { id: botId, role: 'assistant', text: '', pending: true };
    setMessages((prev) => [...prev, userMsg, botMsg]);
    setInput('');
    setSending(true);
    scrollToEnd();

    cancelRef.current = streamChat(config, text, agent, {
      onToken: (t) => {
        patch(botId, (m) => ({ ...m, text: m.text + t, pending: true }));
        scrollToEnd();
      },
      onDone: (full) => {
        patch(botId, (m) => ({ ...m, text: full || m.text, pending: false }));
        setSending(false);
        cancelRef.current = null;
        scrollToEnd();
      },
      onError: (err) => {
        patch(botId, (m) => ({ ...m, text: m.text || `⚠ ${err}`, pending: false }));
        setSending(false);
        cancelRef.current = null;
      },
    });
  }, [agent, config, configured, input, patch, scrollToEnd, sending]);

  const stop = useCallback(() => {
    cancelRef.current?.();
    cancelRef.current = null;
    setSending(false);
  }, []);

  const newChat = useCallback(() => {
    stop();
    stopSpeaking();
    setSpeakingId(null);
    setMessages([]);
    clearHistory();
  }, [stop]);

  const handleSpeak = useCallback(
    (m: ChatMessage) => {
      if (speakingId === m.id) {
        stopSpeaking();
        setSpeakingId(null);
        return;
      }
      setSpeakingId(m.id);
      speak(config, toPlain(m.text), 'ro', () => setSpeakingId(null)).catch(() => setSpeakingId(null));
    },
    [config, speakingId],
  );

  const onResumed = useCallback(
    (_sid: string, turns: HistoryTurn[]) => {
      stop();
      const msgs: ChatMessage[] = turns.map((t) => ({
        id: nextId(),
        role: t.role === 'user' ? 'user' : 'assistant',
        text: t.content,
      }));
      setMessages(msgs);
      scrollToEnd();
    },
    [scrollToEnd, stop],
  );

  if (!configured) {
    return (
      <View style={styles.empty}>
        <Text style={styles.emptyTitle}>No hub connected</Text>
        <Text style={styles.emptyBody}>Add your Jarvis hub address in Settings to start chatting.</Text>
        <Pressable style={styles.cta} onPress={onGoToSettings}>
          <Text style={styles.ctaText}>Open Settings</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={Platform.OS === 'ios' ? 88 : 0}
    >
      <View style={styles.toolbar}>
        <AgentPicker value={agent} onChange={changeAgent} />
        <View style={styles.toolbarActions}>
          <Pressable style={styles.toolBtn} onPress={() => setSessionsOpen(true)} hitSlop={6}>
            <Text style={styles.toolBtnText}>History</Text>
          </Pressable>
          <Pressable style={styles.toolBtn} onPress={newChat} hitSlop={6} disabled={!messages.length}>
            <Text style={[styles.toolBtnText, !messages.length && styles.toolBtnDisabled]}>New</Text>
          </Pressable>
        </View>
      </View>

      <FlatList
        ref={listRef}
        data={messages}
        keyExtractor={(m) => m.id}
        renderItem={({ item }) => (
          <MessageBubble message={item} onSpeak={() => handleSpeak(item)} speaking={speakingId === item.id} />
        )}
        contentContainerStyle={styles.listContent}
        onContentSizeChange={scrollToEnd}
        keyboardShouldPersistTaps="handled"
        ListEmptyComponent={
          <View style={styles.hint}>
            <Text style={styles.hintText}>Say hello to Jarvis.</Text>
          </View>
        }
      />

      <View style={styles.inputBar}>
        <TextInput
          style={styles.input}
          value={input}
          onChangeText={setInput}
          placeholder="Message Jarvis…"
          placeholderTextColor={theme.textDim}
          multiline
          editable={!sending}
          onSubmitEditing={send}
          returnKeyType="send"
        />
        {sending ? (
          <Pressable style={[styles.sendBtn, styles.stopBtn]} onPress={stop}>
            <Text style={styles.sendText}>Stop</Text>
          </Pressable>
        ) : (
          <Pressable
            style={[styles.sendBtn, !input.trim() && styles.sendBtnDisabled]}
            onPress={send}
            disabled={!input.trim()}
          >
            <Text style={styles.sendText}>Send</Text>
          </Pressable>
        )}
      </View>

      <SessionsModal visible={sessionsOpen} onClose={() => setSessionsOpen(false)} onResumed={onResumed} />
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  toolbar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
  },
  toolbarActions: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  toolBtn: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.surface,
  },
  toolBtnText: { color: theme.text, fontSize: 13, fontWeight: '600' },
  toolBtnDisabled: { color: theme.textDim },
  listContent: { padding: 12, paddingBottom: 16 },
  hint: { alignItems: 'center', marginTop: 48 },
  hintText: { color: theme.textDim, fontSize: 14 },
  inputBar: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderTopWidth: 1,
    borderTopColor: theme.border,
    backgroundColor: theme.surfaceAlt,
  },
  input: {
    flex: 1,
    color: theme.text,
    fontSize: 15,
    maxHeight: 120,
    paddingHorizontal: 14,
    paddingVertical: 10,
    backgroundColor: theme.surface,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: theme.border,
  },
  sendBtn: {
    marginLeft: 8,
    paddingHorizontal: 18,
    height: 42,
    borderRadius: 21,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: theme.accent,
  },
  sendBtnDisabled: { backgroundColor: theme.accentDim, opacity: 0.6 },
  stopBtn: { backgroundColor: theme.danger },
  sendText: { color: '#02121b', fontWeight: '700', fontSize: 15 },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  emptyTitle: { color: theme.text, fontSize: 20, fontWeight: '700', marginBottom: 8 },
  emptyBody: { color: theme.textDim, fontSize: 15, textAlign: 'center', marginBottom: 24 },
  cta: { paddingHorizontal: 24, paddingVertical: 12, borderRadius: 24, backgroundColor: theme.accent },
  ctaText: { color: '#02121b', fontWeight: '700', fontSize: 15 },
});
