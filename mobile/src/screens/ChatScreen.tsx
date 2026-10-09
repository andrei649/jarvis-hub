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
import { CommandsModal } from '../components/CommandsModal';
import { MessageBubble } from '../components/MessageBubble';
import { SessionsModal } from '../components/SessionsModal';
import { VoiceOrb } from '../components/VoiceOrb';
import { PushToTalk } from '../components/PushToTalk';
import { useServer } from '../context/ServerContext';
import { Conversation, type ConversationState } from '../chat/conversation';
import { DEFAULT_PREFS, loadPrefs, savePrefs } from '../storage/prefs';
import { useThemeStyles, type Theme } from '../theme';
import { waitForMicrophoneIdle, type DictationState } from '../voice/pushToTalk';
import { BriefingWall } from './BriefingWall';

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
  const { config, configured, ready, chatScope, connectionEpoch } = useServer();
  const [snapshot, setSnapshot] = useState({ scope: '', state: EMPTY_CONVERSATION });
  const conversation = useRef<{ scope: string; chat: Conversation } | null>(null);
  const state = snapshot.scope === chatScope ? snapshot.state : EMPTY_CONVERSATION;
  const { messages, sending } = state;
  const [input, setInput] = useState('');
  const draftVersion = useRef(0);
  const commandsOpenVersion = useRef(0);
  const commandsOpenContext = useRef('');
  const [agent, setAgent] = useState(DEFAULT_PREFS.agent);
  const [speakingId, setSpeakingId] = useState<string | null>(null);
  const speech = useSyncExternalStore(subscribeSpeech, getSpeechState, getSpeechState);
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [commandsOpen, setCommandsOpen] = useState(false);
  const [briefing, setBriefing] = useState({ open: false, epoch: 0 });
  const [dictatedLine, setDictatedLine] = useState<{ context: string; text: string | null }>({ context: '', text: null });
  const speechGeneration = useRef(0);
  const dictationContext = JSON.stringify([chatScope, connectionEpoch, state.sessionId, agent, briefing.epoch, briefing.open]);
  const currentDictationContext = useRef(dictationContext);
  currentDictationContext.current = dictationContext;
  const commandContext = JSON.stringify([chatScope, connectionEpoch, state.sessionId, agent]);
  const dictationDisabled = sending || !state.ready || sessionsOpen || commandsOpen || speakingId !== null;
  const canAcceptDictation = useRef(false);
  canAcceptDictation.current = !dictationDisabled;
  const [dictationSnapshot, setDictationSnapshot] = useState({ context: '', state: { status: 'off' } as DictationState, active: false });
  const dictationRef = useRef(dictationSnapshot);
  const dictation = dictationSnapshot.context === dictationContext ? dictationSnapshot : null;
  const onDictationState = useCallback((next: DictationState) => {
    if (currentDictationContext.current !== dictationContext) return;
    const previous = dictationRef.current.context === dictationContext ? dictationRef.current : null;
    const terminal = next.status === 'off' || next.status === 'error' ||
      (next.status === 'idle' && previous?.state.status === 'transcribing');
    const snapshot = { context: dictationContext, state: next, active: !terminal };
    dictationRef.current = snapshot;
    setDictationSnapshot(snapshot);
  }, [dictationContext]);
  const onDictationStart = useCallback(() => {
    if (currentDictationContext.current !== dictationContext) return;
    speechGeneration.current++;
    stopSpeaking();
    setSpeakingId(null);
    onDictationState({ status: 'idle' });
  }, [dictationContext, onDictationState]);
  const onTranscript = useCallback((text: string) => {
    if (currentDictationContext.current !== dictationContext || !canAcceptDictation.current || !text.trim()) return;
    ++draftVersion.current;
    setInput(previous => previous ? `${previous}\n${text}` : text);
    setDictatedLine({ context: dictationContext, text });
  }, [dictationContext]);
  const listRef = useRef<FlatList<ChatMessage>>(null);
  // A connection owns its controller. Cleanup revokes old callbacks before a new hub hydrates.
  useEffect(() => {
    if (!ready) return;
    const chat = new Conversation(config, chatScope, next => setSnapshot({ scope: chatScope, state: next }));
    conversation.current = { scope: chatScope, chat };
    setSnapshot({ scope: chatScope, state: chat.state });
    setSessionsOpen(false);
    setCommandsOpen(false);
    setSpeakingId(null);
    void chat.hydrate();
    return () => {
      speechGeneration.current++;
      chat.dispose();
      if (conversation.current?.chat === chat) conversation.current = null;
      stopSpeaking();
    };
  }, [ready, config, chatScope]);

  useEffect(() => { void loadPrefs().then(p => setAgent(p.agent)); }, []);
  useEffect(() => {
    setBriefing(previous => previous.open ? { open: false, epoch: previous.epoch + 1 } : previous);
  }, [chatScope, connectionEpoch]);

  const changeBriefing = useCallback((open: boolean) => {
    speechGeneration.current++;
    stopSpeaking();
    setSpeakingId(null);
    setSessionsOpen(false);
    setCommandsOpen(false);
    setDictatedLine({ context: '', text: null });
    setBriefing(previous => ({ open, epoch: previous.epoch + 1 }));
  }, []);

  const scrollToEnd = useCallback(() => {
    requestAnimationFrame(() => listRef.current?.scrollToEnd({ animated: true }));
  }, []);
  useEffect(scrollToEnd, [messages, scrollToEnd]);

  const changeAgent = useCallback((id: string) => {
    speechGeneration.current++;
    stopSpeaking();
    setSpeakingId(null);
    setCommandsOpen(false);
    setAgent(id);
    savePrefs({ agent: id });
  }, []);

  const openCommands = useCallback(() => {
    commandsOpenVersion.current = draftVersion.current;
    commandsOpenContext.current = commandContext;
    setCommandsOpen(true);
  }, [commandContext]);
  const chooseCommand = useCallback((command: string) => {
    // A user can still edit the composer while a modal is open. Keep that newer draft.
    if (commandContext === commandsOpenContext.current && draftVersion.current === commandsOpenVersion.current) {
      ++draftVersion.current;
      setInput(command);
    }
  }, [commandContext]);

  const send = useCallback(() => {
    if (!configured || conversation.current?.scope !== chatScope) return;
    if (conversation.current.chat.send(input, agent)) { ++draftVersion.current; setInput(''); }
  }, [agent, configured, input, chatScope]);

  const stop = useCallback(() => {
    if (conversation.current?.scope === chatScope) conversation.current.chat.stop();
  }, [chatScope]);

  const newChat = useCallback(() => {
    if (!configured || conversation.current?.scope !== chatScope) return;
    speechGeneration.current++;
    stopSpeaking();
    setSpeakingId(null);
    setCommandsOpen(false);
    // Only a successful governed /new response changes the transcript and session.
    conversation.current.chat.send('/new', agent);
  }, [agent, configured, chatScope]);

  const handleSpeak = useCallback(
    (m: ChatMessage) => {
      if (dictationRef.current.context === currentDictationContext.current && dictationRef.current.active) return;
      const generation = ++speechGeneration.current;
      if (speakingId === m.id) {
        stopSpeaking();
        setSpeakingId(null);
        return;
      }
      setSpeakingId(m.id);
      const context = currentDictationContext.current;
      const current = () => generation === speechGeneration.current && context === currentDictationContext.current;
      void waitForMicrophoneIdle().then(async () => {
        if (!current()) return;
        await speak(config, toPlain(m.text), 'ro', () => { if (current()) setSpeakingId(null); });
      }).catch(() => { if (current()) setSpeakingId(null); });
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
    speechGeneration.current++;
    stopSpeaking();
    setSpeakingId(null);
    setCommandsOpen(false);
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

  const dictationControl = <PushToTalk contextKey={dictationContext} disabled={dictationDisabled}
    onStart={onDictationStart} onState={onDictationState} onTranscript={onTranscript} />;
  if (briefing.open) {
    const status = dictation?.active || dictation?.state.status === 'error'
      ? dictation.state.status : speech.status === 'preparing' ? 'idle' : speech.status;
    return <BriefingWall contextKey={dictationContext}
      voice={{ status, error: status === 'error', level: dictation?.state.status === 'listening' ? dictation.state.level : undefined }}
      transcript={dictatedLine.context === dictationContext ? dictatedLine.text : null}
      onExit={() => changeBriefing(false)}>{dictationControl}</BriefingWall>;
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
          <Pressable style={styles.toolBtn} onPress={() => changeBriefing(true)} hitSlop={6} disabled={!state.ready || sending}>
            <Text style={styles.toolBtnText}>Briefing</Text>
          </Pressable>
          <Pressable style={styles.toolBtn} onPress={openCommands} hitSlop={6}
            disabled={!state.ready || sending || !!dictation?.active} accessibilityLabel="Browse chat commands">
            <Text style={[styles.toolBtnText, (!state.ready || sending || !!dictation?.active) && styles.toolBtnDisabled]}>Commands</Text>
          </Pressable>
          <Pressable style={styles.toolBtn} onPress={() => setSessionsOpen(true)} hitSlop={6}>
            <Text style={styles.toolBtnText}>History</Text>
          </Pressable>
          <Pressable style={styles.toolBtn} onPress={newChat} hitSlop={6} disabled={!messages.length || sending || !state.ready}>
            <Text style={[styles.toolBtnText, (!messages.length || sending || !state.ready) && styles.toolBtnDisabled]}>New</Text>
          </Pressable>
        </View>
      </View>

      <View style={styles.speechStatus}>
        <VoiceOrb status={dictation?.active || dictation?.state.status === 'error'
          ? dictation.state.status === 'stopping' ? 'idle' : dictation.state.status
          : speech.status === 'preparing' ? 'idle' : speech.status}
          level={dictation?.state.status === 'listening' ? dictation.state.level : undefined} size={80} />
        <View style={styles.speechCopy}>
          <Text style={styles.speechTitle}>Voice</Text>
          {!dictation?.active && speech.status === 'preparing' ? <Text style={styles.speechNote}>Preparing speech…</Text> : null}
          {!dictation?.active && speech.status === 'error' ? <Text style={styles.speechNote}>Speech playback unavailable. Try speaking again.</Text> : null}
        </View>
      </View>

      <FlatList
        ref={listRef}
        data={messages}
        keyExtractor={(m) => m.id}
        renderItem={({ item }) => (
          <MessageBubble message={item} onSpeak={dictation?.active ? undefined : () => handleSpeak(item)} speaking={speakingId === item.id}
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
          onChangeText={text => { ++draftVersion.current; setInput(text); }}
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

      {dictationControl}

      <SessionsModal visible={sessionsOpen} onClose={() => setSessionsOpen(false)} onResumed={onResumed} />
      <CommandsModal visible={commandsOpen} onClose={() => setCommandsOpen(false)} onChoose={chooseCommand} />
    </KeyboardAvoidingView>
  );
}

const makeStyles = (theme: Theme) => StyleSheet.create({
  flex: { flex: 1 },
  toolbar: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    rowGap: 8,
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
