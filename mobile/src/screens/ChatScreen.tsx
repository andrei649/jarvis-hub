import React, { useCallback, useRef, useState } from 'react';
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
import { streamChat } from '../api/client';
import { MessageBubble, type ChatMessage } from '../components/MessageBubble';
import { useServer } from '../context/ServerContext';
import { theme } from '../theme';

let idSeq = 0;
const nextId = () => `m${Date.now()}_${idSeq++}`;

export function ChatScreen({ onGoToSettings }: { onGoToSettings: () => void }) {
  const { config, configured } = useServer();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const listRef = useRef<FlatList<ChatMessage>>(null);
  const cancelRef = useRef<(() => void) | null>(null);

  const scrollToEnd = useCallback(() => {
    requestAnimationFrame(() => listRef.current?.scrollToEnd({ animated: true }));
  }, []);

  const patch = useCallback((id: string, updater: (m: ChatMessage) => ChatMessage) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? updater(m) : m)));
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

    cancelRef.current = streamChat(config, text, 'jarvis', {
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
        patch(botId, (m) => ({
          ...m,
          text: m.text || `⚠ ${err}`,
          pending: false,
        }));
        setSending(false);
        cancelRef.current = null;
      },
    });
  }, [config, configured, input, patch, scrollToEnd, sending]);

  const stop = useCallback(() => {
    cancelRef.current?.();
    cancelRef.current = null;
    setSending(false);
  }, []);

  if (!configured) {
    return (
      <View style={styles.empty}>
        <Text style={styles.emptyTitle}>No hub connected</Text>
        <Text style={styles.emptyBody}>
          Add your Jarvis hub address in Settings to start chatting.
        </Text>
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
      <FlatList
        ref={listRef}
        data={messages}
        keyExtractor={(m) => m.id}
        renderItem={({ item }) => <MessageBubble message={item} />}
        contentContainerStyle={styles.listContent}
        onContentSizeChange={scrollToEnd}
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
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
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
  cta: {
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 24,
    backgroundColor: theme.accent,
  },
  ctaText: { color: '#02121b', fontWeight: '700', fontSize: 15 },
});
