import { TextInput, Text } from '../components/ThemedText';
import React, { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import {
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  View,
} from 'react-native';
import { saveCanvasArtifact, type HistoryTurn } from '../api/client';
import { getSpeechState, speak, stopSpeaking, subscribeSpeech } from '../audio/tts';
import type { ChatMessage, SaveState } from '../chat/types';
import { AgentPicker } from '../components/AgentPicker';
import { MessageBubble } from '../components/MessageBubble';
import { SessionsModal } from '../components/SessionsModal';
import { VoiceOrb } from '../components/VoiceOrb';
import { useServer } from '../context/ServerContext';
import { Conversation, type ConversationState } from '../chat/conversation';
import { DEFAULT_PREFS, loadPrefs, savePrefs } from '../storage/prefs';
import { useThemeStyles, type Theme } from '../theme';

const EMPTY_CONVERSATION: ConversationState = { sessionId: null, messages: [], ready: false, sending: false };

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
  const { theme, styles } = useThemeStyles(makeStyles);
  const { config, configured, ready, chatScope } = useServer();
  const [snapshot, setSnapshot] = useState({ scope: '', state: EMPTY_CONVERSATION });
  const conversation = useRef<{ scope: string; chat: Conversation } | null>(null);
  const state = snapshot.scope === chatScope ? snapshot.state : EMPTY_CONVERSATION;
  const { messages, sending } = state;
  const [input, setInput] = useState('');
  const [agent, setAgent] = useState(DEFAULT_PREFS.agent);
  const [speakingId, setSpeakingId] = useState<string | null>(null);
  const speech = useSyncExternalStore(subscribeSpeech, getSpeechState, getSpeechState);
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const listRef = useRef<FlatList<ChatMessage>>(null);
  // A connection owns its controller. Cleanup revokes old callbacks before a new hub hydrates.
  useEffect(() => {
    if (!ready) return;
    const chat = new Conversation(config, chatScope, next => setSnapshot({ scope: chatScope, state: next }));
    conversation.current = { scope: chatScope, chat };
    setSnapshot({ scope: chatScope, state: chat.state });
    setSessionsOpen(false);
    setSpeakingId(null);
    void chat.hydrate();
    return () => {
      chat.dispose();
      if (conversation.current?.chat === chat) conversation.current = null;
      stopSpeaking();
    };
  }, [ready, config, chatScope]);

  useEffect(() => { void loadPrefs().then(p => setAgent(p.agent)); }, []);

  const scrollToEnd = useCallback(() => {
    requestAnimationFrame(() => listRef.current?.scrollToEnd({ animated: true }));
  }, []);
  useEffect(scrollToEnd, [messages, scrollToEnd]);

  const changeAgent = useCallback((id: string) => {
    setAgent(id);
    savePrefs({ agent: id });
  }, []);

  const send = useCallback(() => {
    if (!configured || conversation.current?.scope !== chatScope) return;
    if (conversation.current.chat.send(input, agent)) setInput('');
  }, [agent, configured, input, chatScope]);

  const stop = useCallback(() => {
    if (conversation.current?.scope === chatScope) conversation.current.chat.stop();
  }, [chatScope]);

  const newChat = useCallback(() => {
    if (!configured || conversation.current?.scope !== chatScope) return;
    stopSpeaking();
    setSpeakingId(null);
    // Only a successful governed /new response changes the transcript and session.
    conversation.current.chat.send('/new', agent);
  }, [agent, configured, chatScope]);

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

  // Explicit save-to-artifacts (H18.20): idle → saving (click-locked) → saved /
  // saved·truncated / error (retryable). Never fires automatically.
  const [saveStates, setSaveStates] = useState<Record<string, SaveState>>({});
  const saveStatesRef = useRef(saveStates);
  useEffect(() => {
    saveStatesRef.current = saveStates;
  }, [saveStates]);
  const handleSave = useCallback(
    (m: ChatMessage) => {
      const cur = saveStatesRef.current[m.id];
      if (cur === 'saving' || cur === 'saved' || cur === 'saved-trunc') return;
      if (!m.text) return;
      setSaveStates((s) => ({ ...s, [m.id]: 'saving' }));
      saveCanvasArtifact(config, { agent: m.agent || agent, body: m.text })
        .then((r) => setSaveStates((s) => ({ ...s, [m.id]: r.truncated ? 'saved-trunc' : 'saved' })))
        .catch(() => setSaveStates((s) => ({ ...s, [m.id]: 'error' })));
    },
    [agent, config],
  );

  const onResumed = useCallback((sid: string, turns: HistoryTurn[]) => {
    if (conversation.current?.scope !== chatScope) return;
    stopSpeaking();
    setSpeakingId(null);
    conversation.current.chat.resume(sid, turns);
  }, [chatScope]);

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
          <Pressable style={styles.toolBtn} onPress={newChat} hitSlop={6} disabled={!messages.length || sending || !state.ready}>
            <Text style={[styles.toolBtnText, (!messages.length || sending || !state.ready) && styles.toolBtnDisabled]}>New</Text>
          </Pressable>
        </View>
      </View>

      <View style={styles.speechStatus}>
        <VoiceOrb status={speech.status === 'preparing' ? 'idle' : speech.status} size={80} />
        <View style={styles.speechCopy}>
          <Text style={styles.speechTitle}>Speech playback</Text>
          {speech.status === 'preparing' ? <Text style={styles.speechNote}>Preparing speech…</Text> : null}
          {speech.status === 'error' ? <Text style={styles.speechNote}>Speech playback unavailable. Try speaking again.</Text> : null}
        </View>
      </View>

      <FlatList
        ref={listRef}
        data={messages}
        keyExtractor={(m) => m.id}
        renderItem={({ item }) => (
          <MessageBubble message={item} onSpeak={() => handleSpeak(item)} speaking={speakingId === item.id}
            onSave={() => handleSave(item)} saveState={saveStates[item.id]} />
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
          placeholder={state.ready ? 'Message Jarvis…' : 'Restoring conversation…'}
          placeholderTextColor={theme.textDim}
          multiline
          editable={!sending && state.ready}
          onSubmitEditing={send}
          returnKeyType="send"
        />
        {sending ? (
          <Pressable style={[styles.sendBtn, styles.stopBtn]} onPress={stop}>
            <Text style={styles.sendText}>Stop</Text>
          </Pressable>
        ) : (
          <Pressable
            style={[styles.sendBtn, (!input.trim() || !state.ready) && styles.sendBtnDisabled]}
            onPress={send}
            disabled={!input.trim() || !state.ready}
          >
            <Text style={styles.sendText}>Send</Text>
          </Pressable>
        )}
      </View>

      <SessionsModal visible={sessionsOpen} onClose={() => setSessionsOpen(false)} onResumed={onResumed} />
    </KeyboardAvoidingView>
  );
}

const makeStyles = (theme: Theme) => StyleSheet.create({
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
  speechStatus: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 12, gap: 12 },
  speechCopy: { flex: 1 },
  speechTitle: { color: theme.text, fontSize: 13, fontWeight: '600' },
  speechNote: { color: theme.textDim, fontSize: 12, marginTop: 4 },
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
