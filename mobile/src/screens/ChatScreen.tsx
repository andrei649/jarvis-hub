import { TextInput, Text } from '../components/ThemedText';
import React, { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import {
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  View,
} from 'react-native';
import { saveCanvasArtifact, type HistoryTurn, type VaultExcerpt } from '../api/client';
import type { HistorySelection } from '../api/sessionTranscript';
import type { ChatNoteDraft, ChatNoteReceipt, ChatNoteTarget } from '../api/chatNote';
import { getSpeechState, speak, stopSpeaking, subscribeSpeech } from '../audio/tts';
import type { ChatMessage, SaveState } from '../chat/types';
import { AgentPicker } from '../components/AgentPicker';
import { CommandsModal } from '../components/CommandsModal';
import { CompareAgents } from '../components/CompareAgents';
import { MessageBubble } from '../components/MessageBubble';
import { RememberMessage } from '../components/RememberMessage';
import { SaveChatNote } from '../components/SaveChatNote';
import { SavedVaultNoteViewer } from '../components/SavedVaultNoteViewer';
import { VaultNoteReview } from '../components/VaultNoteReview';
import { SessionsModal } from '../components/SessionsModal';
import { VoiceOrb } from '../components/VoiceOrb';
import { PushToTalk } from '../components/PushToTalk';
import { SelectedImages } from '../components/SelectedImages';
import { useServer } from '../context/ServerContext';
import { Conversation, type ConversationState } from '../chat/conversation';
import { DEFAULT_PREFS, loadPrefs, savePrefs } from '../storage/prefs';
import { useThemeStyles, type Theme } from '../theme';
import { waitForMicrophoneIdle, type DictationState } from '../voice/pushToTalk';
import { BriefingWall } from './BriefingWall';

const EMPTY_CONVERSATION: ConversationState = { sessionId: null, messages: [], ready: false, sending: false,
  turnOutcome: null, missingSessionId: null, recoveryPrompt: null };

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

function withoutPickedSkill(draft: string, command: string): string | null {
  const typed = draft.trimStart();
  if (typed !== command && !(typed.startsWith(command) && /\s/.test(typed.charAt(command.length)))) return null;
  return draft.slice(0, draft.length - typed.length) + typed.slice(command.length + 1);
}

export function ChatScreen({ onGoToSettings }: { onGoToSettings: () => void }) {
  const { theme, styles } = useThemeStyles(makeStyles);
  const { config, configured, ready, chatScope, connectionEpoch } = useServer();
  const [snapshot, setSnapshot] = useState({ scope: '', connectionEpoch: -1, state: EMPTY_CONVERSATION });
  const conversation = useRef<{ scope: string; connectionEpoch: number; chat: Conversation } | null>(null);
  const state = snapshot.scope === chatScope && snapshot.connectionEpoch === connectionEpoch
    ? snapshot.state : EMPTY_CONVERSATION;
  const { messages, sending } = state;
  const missingCurrentSession = Boolean(state.missingSessionId && state.missingSessionId === state.sessionId);
  const pendingRecoveryPrompt = Boolean(state.recoveryPrompt);
  const [input, setInput] = useState('');
  const blockedBySavedPrompt = pendingRecoveryPrompt && !['/new', '/reset', '/undo'].includes(input.trim());
  const inputValue = useRef('');
  const draftScope = useRef(chatScope);
  const selectedSkill = useRef<{ context: string; command: string } | null>(null);
  const updateInput = (value: string | ((previous: string) => string), scope = chatScope) => {
    const next = typeof value === 'function' ? value(inputValue.current) : value;
    const picked = selectedSkill.current;
    if (picked && withoutPickedSkill(next, picked.command) === null) {
      selectedSkill.current = null;
    }
    inputValue.current = next;
    draftScope.current = scope;
    setInput(next);
  };
  const draftVersion = useRef(0);
  const commandsOpenVersion = useRef(0);
  const commandsOpenContext = useRef('');
  const commandsOpenChat = useRef<Conversation | null>(null);
  const commandsOpenRevision = useRef(0);
  const [agent, setAgent] = useState(DEFAULT_PREFS.agent);
  const recipient = agent === 'jarvis' ? 'Jarvis' : `@${agent}`;
  const agentRef = useRef(DEFAULT_PREFS.agent);
  const [speakingId, setSpeakingId] = useState<string | null>(null);
  const speech = useSyncExternalStore(subscribeSpeech, getSpeechState, getSpeechState);
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [commandsOpen, setCommandsOpen] = useState(false);
  const [selectedOpen, setSelectedOpen] = useState(false);
  const imageDraftPending = useRef<(() => boolean) | null>(null);
  const [interactionEpoch, setInteractionEpoch] = useState(0);
  const [briefing, setBriefing] = useState({ open: false, epoch: 0 });
  const [dictatedLine, setDictatedLine] = useState<{ context: string; text: string | null }>({ context: '', text: null });
  const speechGeneration = useRef(0);
  const dictationContext = JSON.stringify([chatScope, connectionEpoch, state.sessionId, agent,
    briefing.epoch, briefing.open, interactionEpoch, commandsOpen, selectedOpen]);
  const currentDictationContext = useRef(dictationContext);
  currentDictationContext.current = dictationContext;
  const commandContext = JSON.stringify([chatScope, connectionEpoch, state.sessionId, agent]);
  const currentCommandContext = useRef(commandContext);
  currentCommandContext.current = commandContext;
  const [comparison, setComparison] = useState<{ context: string; question: string } | null>(null);
  const currentComparison = comparison?.context === commandContext ? comparison : null;
  const [history, setHistory] = useState<{ context: string; selection: HistorySelection; needsReview: boolean } | null>(null);
  const staged = history?.context === commandContext ? history : null;
  const sourceBlocksSend = Boolean(staged && (staged.needsReview || input.trimStart().startsWith('/')));
  useEffect(() => { setHistory(previous => previous?.context === commandContext ? previous : null); }, [commandContext]);
  const pickedArgs = selectedSkill.current?.context === commandContext ? withoutPickedSkill(input, selectedSkill.current.command) : null;
  const skillDraftTooLong = pickedArgs !== null
    && (Array.from(pickedArgs.trim()).length > 2000
      || Array.from(input.trim()).length > 4096);
  useEffect(() => {
    const picked = selectedSkill.current;
    if (!picked || picked.context === commandContext) return;
    const remaining = withoutPickedSkill(inputValue.current, picked.command);
    selectedSkill.current = null;
    if (remaining !== null) {
      ++draftVersion.current;
      updateInput(remaining, draftScope.current);
    }
  }, [commandContext]);
  const noteContextRef = useRef(commandContext);
  noteContextRef.current = commandContext;
  const [noteReview, setNoteReview] = useState<{ context: string; id: string; text: string } | null>(null);
  const [noteViewer, setNoteViewer] = useState<{ context: string; receipt: ChatNoteReceipt; target: ChatNoteTarget } | null>(null);
  const [notes, setNotes] = useState<{ context: string; drafts: Record<string, ChatNoteDraft> }>({
    context: '', drafts: {},
  });
  useEffect(() => {
    setComparison(previous => previous?.context === commandContext ? previous : null);
    setNoteReview(previous => previous?.context === commandContext ? previous : null);
    setNoteViewer(previous => previous?.context === commandContext ? previous : null);
    setNotes(previous => previous.context === commandContext ? previous : { context: commandContext, drafts: {} });
  }, [commandContext]);
  const noteDrafts = notes.context === commandContext ? notes.drafts : {};
  const currentNote = noteReview?.context === commandContext
    && messages.some(message => message.id === noteReview.id && message.role === 'assistant'
      && message.completed === true && !message.pending && !message.error && message.text === noteReview.text)
    ? noteReview : null;
  const currentViewer = noteViewer?.context === commandContext ? noteViewer : null;
  const openNote = (message: ChatMessage) => {
    if (message.role !== 'assistant' || message.completed !== true || message.pending || message.error
      || !message.text.trim()) return;
    const saved = message.savedNote;
    if (saved) setNoteViewer({ context: commandContext, ...saved });
    else setNoteReview({ context: commandContext, id: message.id, text: message.text });
  };
  const updateNoteDraft = (context: string, id: string, draft: ChatNoteDraft | null) => {
    if (context !== noteContextRef.current) return;
    setNotes(previous => {
      const current = previous.context === context ? previous : { context, drafts: {} };
      const drafts = { ...current.drafts };
      if (draft) drafts[id] = draft;
      else delete drafts[id];
      return { ...current, drafts };
    });
  };
  const saveNoteReceipt = (context: string, id: string, text: string, receipt: ChatNoteReceipt, target: ChatNoteTarget) => {
    if (context !== noteContextRef.current) return;
    if (conversation.current?.chat.attachSavedNote(id, text, { receipt, target })) updateNoteDraft(context, id, null);
  };
  const [remember, setRemember] = useState<{ context: string; id: string; text: string } | null>(null);
  const currentRemember = remember?.context === commandContext
    && messages.some(message => message.id === remember.id && message.role === 'user'
      && !message.pending && !message.error && message.text === remember.text) ? remember : null;
  const [vaultReview, setVaultReview] = useState<{
    context: string; version: number; question: string; chat: Conversation; revision: number; generation: number;
  } | null>(null);
  const vaultGeneration = useRef(0);
  const vaultContext = JSON.stringify([chatScope, connectionEpoch, state.sessionId, agent, state.ready,
    sending, sessionsOpen, commandsOpen, selectedOpen, briefing.open, Boolean(currentRemember),
    Boolean(state.recoveryPrompt), Boolean(state.missingSessionId), Boolean(dictatedLine.text)]);
  const currentVaultContext = useRef(vaultContext);
  currentVaultContext.current = vaultContext;
  const vaultCurrent = (review: NonNullable<typeof vaultReview>) =>
    currentVaultContext.current === review.context && draftVersion.current === review.version
    && inputValue.current === review.question && conversation.current?.chat === review.chat
    && review.chat.revision === review.revision && vaultGeneration.current === review.generation;
  const closeVault = () => { ++vaultGeneration.current; setVaultReview(null); };
  const openVault = () => {
    const owner = conversation.current;
    const question = inputValue.current;
    if (!configured || !owner || owner.scope !== chatScope || owner.connectionEpoch !== connectionEpoch
      || !state.ready || sending || sessionsOpen || commandsOpen || selectedOpen || briefing.open || currentRemember || staged
      || state.recoveryPrompt || state.missingSessionId || !question.trim() || question.trimStart().startsWith('/')
      || dictationRef.current.active) return;
    revokeDictation();
    setVaultReview({ context: vaultContext, version: draftVersion.current, question,
      chat: owner.chat, revision: owner.chat.revision, generation: ++vaultGeneration.current });
  };
  const sendWithVault = (review: NonNullable<typeof vaultReview>, notes: VaultExcerpt[]) => {
    if (!configured || !vaultCurrent(review) || !notes.length) return false;
    const sent = review.chat.send(review.question, agent, undefined, notes);
    if (sent) { ++draftVersion.current; updateInput(''); closeVault(); }
    return sent;
  };
  useEffect(() => { setRemember(previous => previous?.context === commandContext ? previous : null); }, [commandContext]);
  const dictationDisabled = sending || !state.ready || sessionsOpen || commandsOpen || selectedOpen
    || Boolean(currentComparison) || Boolean(vaultReview && vaultCurrent(vaultReview)) || speakingId !== null;
  const canAcceptDictation = useRef(false);
  canAcceptDictation.current = !dictationDisabled;
  const revokeDictation = useCallback(() => {
    // Fence callbacks synchronously, before React commits a mode change.
    currentDictationContext.current = '';
    canAcceptDictation.current = false;
    setInteractionEpoch(value => value + 1);
  }, []);
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
    updateInput(previous => previous ? `${previous}\n${text}` : text);
    setDictatedLine({ context: dictationContext, text });
  }, [dictationContext]);
  const listRef = useRef<FlatList<ChatMessage>>(null);
  // A connection owns its controller. Cleanup revokes old callbacks before a new hub hydrates.
  useEffect(() => {
    if (!ready) return;
    const chat = new Conversation(config, chatScope, next => setSnapshot({ scope: chatScope, connectionEpoch, state: next }));
    conversation.current = { scope: chatScope, connectionEpoch, chat };
    setSnapshot({ scope: chatScope, connectionEpoch, state: chat.state });
    setSessionsOpen(false);
    setCommandsOpen(false);
    setSelectedOpen(false);
    setSpeakingId(null);
    void chat.hydrate();
    return () => {
      speechGeneration.current++;
      chat.dispose();
      if (conversation.current?.chat === chat) conversation.current = null;
      stopSpeaking();
    };
  }, [ready, config, chatScope, connectionEpoch]);

  useEffect(() => {
    let active = true;
    void loadPrefs().then(p => {
      if (!active) return;
      if (p.agent !== agentRef.current) {
        agentRef.current = p.agent;
        conversation.current?.chat.clearTurnOutcome();
      }
      setAgent(p.agent);
    });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    setBriefing(previous => previous.open ? { open: false, epoch: previous.epoch + 1 } : previous);
  }, [chatScope, connectionEpoch]);

  const changeBriefing = useCallback((open: boolean) => {
    closeVault();
    revokeDictation();
    commandsOpenContext.current = '';
    speechGeneration.current++;
    stopSpeaking();
    setSpeakingId(null);
    setSessionsOpen(false);
    setCommandsOpen(false);
    setSelectedOpen(false);
    setDictatedLine({ context: '', text: null });
    setBriefing(previous => ({ open, epoch: previous.epoch + 1 }));
  }, [revokeDictation]);

  const scrollToEnd = useCallback(() => {
    requestAnimationFrame(() => listRef.current?.scrollToEnd({ animated: true }));
  }, []);
  useEffect(scrollToEnd, [messages, scrollToEnd]);

  const changeAgent = useCallback((id: string) => {
    closeVault();
    if (id !== agentRef.current) {
      agentRef.current = id;
      if (conversation.current?.scope === chatScope && conversation.current.connectionEpoch === connectionEpoch) {
        conversation.current.chat.clearTurnOutcome();
      }
    }
    revokeDictation();
    commandsOpenContext.current = '';
    speechGeneration.current++;
    stopSpeaking();
    setSpeakingId(null);
    setCommandsOpen(false);
    setSelectedOpen(false);
    setAgent(id);
    savePrefs({ agent: id });
  }, [chatScope, connectionEpoch, revokeDictation]);

  const openCommands = useCallback(() => {
    closeVault();
    revokeDictation();
    speechGeneration.current++;
    stopSpeaking();
    setSpeakingId(null);
    setSelectedOpen(false);
    commandsOpenVersion.current = draftVersion.current;
    commandsOpenContext.current = commandContext;
    commandsOpenChat.current = conversation.current?.chat ?? null;
    commandsOpenRevision.current = commandsOpenChat.current?.revision ?? 0;
    setCommandsOpen(true);
  }, [commandContext, revokeDictation]);
  const openComparison = () => {
    closeVault();
    revokeDictation();
    speechGeneration.current++;
    stopSpeaking();
    setSpeakingId(null);
    setComparison({ context: commandContext, question: draftScope.current === chatScope ? inputValue.current : '' });
  };
  const closeCommands = useCallback(() => {
    revokeDictation();
    commandsOpenContext.current = '';
    setCommandsOpen(false);
  }, [revokeDictation]);
  const toggleImages = useCallback(() => {
    closeVault();
    revokeDictation();
    commandsOpenContext.current = '';
    speechGeneration.current++;
    stopSpeaking();
    setSpeakingId(null);
    setCommandsOpen(false);
    setSelectedOpen(value => !value);
  }, [revokeDictation]);
  const closeImages = useCallback(() => {
    revokeDictation();
    setSelectedOpen(false);
  }, [revokeDictation]);
  const chooseCommand = useCallback((command: string, kind?: 'skill'): false | string | void => {
    // A user can still edit the composer while a modal is open. Keep that newer draft.
    const owner = conversation.current;
    const current = commandContext === commandsOpenContext.current
      && commandContext === currentCommandContext.current
      && draftVersion.current === commandsOpenVersion.current
      && owner?.chat === commandsOpenChat.current && owner.chat.revision === commandsOpenRevision.current
      && owner.chat.state.sessionId === state.sessionId && agentRef.current === agent;
    if (!current) return kind === 'skill' ? false : undefined;
    if (kind === 'skill') {
      const draft = inputValue.current;
      if (draft.trimStart().startsWith('/')) return 'Your draft already contains a slash command. Send or clear it before choosing a skill.';
      if (Array.from(draft.trim()).length > 2000) return 'Shorten the skill instructions to 2,000 characters, then choose the skill again.';
      const composed = draft.trim() ? `${command} ${draft}` : command;
      if (Array.from(composed.trim()).length > 4096) return 'Shorten the full message to 4,096 characters, then choose the skill again.';
      ++draftVersion.current;
      updateInput(composed);
      selectedSkill.current = { context: commandContext, command };
      return;
    }
    ++draftVersion.current;
    updateInput(command);
  }, [commandContext]);

  const send = useCallback((reasoning?: 'none') => {
    if (!configured || sessionsOpen || conversation.current?.scope !== chatScope
      || conversation.current.connectionEpoch !== connectionEpoch
      || conversation.current.chat.state.sessionId !== state.sessionId || agentRef.current !== agent
      || skillDraftTooLong || (selectedSkill.current && selectedSkill.current.context !== commandContext)) return;
    if (staged) {
      const owner = conversation.current;
      if (owner.chat.state.sending || !input.trim() || sourceBlocksSend) return;
      const version = draftVersion.current;
      const settled = (accepted: boolean) => {
        if (owner !== conversation.current || agentRef.current !== agent) return;
        const freshDestination = accepted && state.sessionId === null && owner.chat.state.sessionId !== null
          && currentCommandContext.current === JSON.stringify([chatScope, connectionEpoch, owner.chat.state.sessionId, agent]);
        if (currentCommandContext.current !== commandContext && !freshDestination) return;
        if (!accepted) {
          setHistory(current => current === staged ? { ...current, needsReview: true } : current);
          return;
        }
        setHistory(current => current === staged ? null : current);
        if (draftVersion.current === version) { ++draftVersion.current; updateInput(''); }
      };
      owner.chat.send(input, agent, reasoning, undefined, staged.selection, settled);
      return;
    }
    if (conversation.current.chat.send(input, agent, reasoning)) { ++draftVersion.current; updateInput(''); }
  }, [agent, configured, input, chatScope, connectionEpoch, commandContext, state.sessionId, skillDraftTooLong, sessionsOpen, staged, sourceBlocksSend]);

  const stop = useCallback(() => {
    if (conversation.current?.scope === chatScope) conversation.current.chat.stop();
  }, [chatScope]);

  const newChat = useCallback(() => {
    closeVault();
    const owner = conversation.current;
    if (!configured || owner?.scope !== chatScope || owner.connectionEpoch !== connectionEpoch
      || owner.chat.state.sessionId !== state.sessionId) return;
    revokeDictation();
    commandsOpenContext.current = '';
    speechGeneration.current++;
    stopSpeaking();
    setSpeakingId(null);
    setCommandsOpen(false);
    setSelectedOpen(false);
    // A deleted selected session must be escaped with an unbound /new request.
    // The failed message remains a recoverable draft and is never resent here.
    if (state.missingSessionId === state.sessionId && state.missingSessionId) {
      if (owner.chat.state.missingSessionId !== state.missingSessionId) return;
      owner.chat.recoverWithNewSession(agent);
      return;
    }
    // Only a successful governed /new response changes the transcript and session.
    owner.chat.send('/new', agent);
  }, [agent, configured, chatScope, connectionEpoch, revokeDictation, state.missingSessionId, state.sessionId]);

  const addRecoveryPromptToDraft = useCallback(() => {
    const owner = conversation.current;
    const prompt = state.recoveryPrompt;
    if (!configured || !prompt?.trim() || !owner || owner.scope !== chatScope
      || owner.connectionEpoch !== connectionEpoch || owner.chat.state.recoveryPrompt !== prompt
      || snapshot.scope !== chatScope || snapshot.connectionEpoch !== connectionEpoch) return;
    // The functional update appends to the latest composer value, preserving any
    // newer typed or dictated draft. This action never invokes send().
    ++draftVersion.current;
    const latestDraft = inputValue.current;
    updateInput(latestDraft.trim() ? `${latestDraft}\n${prompt}` : prompt);
    owner.chat.dismissRecoveryPrompt();
  }, [configured, chatScope, connectionEpoch, snapshot.connectionEpoch, snapshot.scope, state.recoveryPrompt]);

  const dismissRecoveryPrompt = useCallback(() => {
    const owner = conversation.current;
    if (!owner || owner.scope !== chatScope || owner.connectionEpoch !== connectionEpoch
      || owner.chat.state.recoveryPrompt !== state.recoveryPrompt) return;
    owner.chat.dismissRecoveryPrompt();
  }, [chatScope, connectionEpoch, state.recoveryPrompt]);

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

  const openHistory = () => {
    closeVault();
    revokeDictation();
    setSessionsOpen(true);
  };
  const resumeBlockReason = useCallback((replacingPassage = false) => {
    const owner = conversation.current;
    if (owner?.scope !== chatScope || owner.connectionEpoch !== connectionEpoch || !owner.chat.state.ready)
      return 'Wait for this connection to finish restoring before switching conversations.';
    if (owner.chat.state.sending) return 'Finish or stop the current reply before switching conversations.';
    if (imageDraftPending.current?.()) return 'Finish or close the image draft before switching conversations.';
    if (selectedSkill.current) return 'Send or remove the selected skill before switching conversations.';
    if (staged && !replacingPassage) return 'Send or remove the passage before switching conversations.';
    return null;
  }, [chatScope, connectionEpoch, staged]);
  const sourceBlockReason = () => {
    if (commandContext !== currentCommandContext.current || agent !== agentRef.current) return 'Choose a passage for the current agent.';
    if (state.missingSessionId || state.recoveryPrompt || selectedOpen || selectedSkill.current
      || inputValue.current.trimStart().startsWith('/')) return 'Use a text draft in an available conversation to attach a passage.';
    return resumeBlockReason(staged?.needsReview === true);
  };
  const onResumed = useCallback((sid: string, turns: HistoryTurn[]) => {
    const owner = conversation.current;
    if (!owner || resumeBlockReason()) return;
    closeVault();
    setNoteReview(null);
    setNoteViewer(null);
    setNotes({ context: commandContext, drafts: {} });
    revokeDictation();
    commandsOpenContext.current = '';
    speechGeneration.current++;
    stopSpeaking();
    setSpeakingId(null);
    setCommandsOpen(false);
    setSelectedOpen(false);
    owner.chat.resume(sid, turns);
  }, [resumeBlockReason, commandContext, revokeDictation]);

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
        <AgentPicker key={`${chatScope}:${connectionEpoch}`} value={agent} onChange={changeAgent} />
        <View style={styles.toolbarActions}>
          <Pressable style={styles.toolBtn} onPress={openComparison} disabled={!state.ready || sending}
            accessibilityRole="button" accessibilityLabel="Compare agents" hitSlop={6}>
            <Text style={[styles.toolBtnText, (!state.ready || sending) && styles.toolBtnDisabled]}>Compare agents</Text>
          </Pressable>
          <Pressable style={styles.toolBtn} onPress={() => changeBriefing(true)} hitSlop={6} disabled={!state.ready || sending}>
            <Text style={styles.toolBtnText}>Briefing</Text>
          </Pressable>
          <Pressable style={styles.toolBtn} onPress={openCommands} hitSlop={6}
            disabled={!state.ready || sending || !!staged} accessibilityLabel="Browse chat commands">
            <Text style={[styles.toolBtnText, (!state.ready || sending || staged) && styles.toolBtnDisabled]}>Commands</Text>
          </Pressable>
          <Pressable style={styles.toolBtn} onPress={toggleImages}
            disabled={!state.ready || sending || !!staged} accessibilityLabel="Selected images" hitSlop={6}>
            <Text style={[styles.toolBtnText, (!state.ready || sending || staged) && styles.toolBtnDisabled]}>Images</Text>
          </Pressable>
          <Pressable style={styles.toolBtn} onPress={openHistory} accessibilityRole="button" hitSlop={6}>
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

      {missingCurrentSession || state.recoveryPrompt ? (
        <View style={styles.recoveryCard} accessibilityLabel="Unsent message recovery">
          <Text style={styles.recoveryTitle}>
            {state.missingSessionId === state.sessionId && state.missingSessionId
              ? 'This chat session is unavailable.' : 'Your unsent message is saved.'}
          </Text>
          <Text style={styles.recoveryBody}>
            {state.missingSessionId === state.sessionId && state.missingSessionId
              ? 'Start a new chat, then add this message to your draft when you are ready. It will not be sent automatically.'
              : 'Add this message to your draft when you are ready. It will not be sent automatically.'}
          </Text>
          {state.recoveryPrompt ? (
            <Text style={styles.recoveryPrompt} numberOfLines={4} ellipsizeMode="tail">
              {state.recoveryPrompt}
            </Text>
          ) : null}
          {state.missingSessionId === state.sessionId && state.missingSessionId ? (
            <Pressable style={styles.recoveryAction} onPress={newChat} disabled={sending || !state.ready}
              accessibilityRole="button" accessibilityLabel="Start new chat">
              <Text style={styles.recoveryActionText}>Start new chat</Text>
            </Pressable>
          ) : null}
          {state.recoveryPrompt ? (
            <View style={styles.recoveryActions}>
              <Pressable style={styles.recoveryAction} onPress={addRecoveryPromptToDraft}
                accessibilityRole="button" accessibilityLabel="Add unsent message to draft">
                <Text style={styles.recoveryActionText}>Add to draft</Text>
              </Pressable>
              <Pressable style={styles.recoveryDismiss} onPress={dismissRecoveryPrompt}
                accessibilityRole="button" accessibilityLabel="Dismiss saved message">
                <Text style={styles.recoveryDismissText}>Dismiss</Text>
              </Pressable>
            </View>
          ) : null}
        </View>
      ) : null}

      <FlatList
        ref={listRef}
        data={messages}
        keyExtractor={(m) => m.id}
        renderItem={({ item }) => (
          <MessageBubble message={item} onSpeak={dictation?.active ? undefined : () => handleSpeak(item)} speaking={speakingId === item.id}
            onSave={() => handleSave(item)} saveState={saveStates[item.id]}
            onSaveNote={item.completed === true ? () => openNote(item) : undefined}
            savedNotePath={item.savedNote?.receipt.relPath}
            onRemember={() => { closeVault(); setRemember({ context: commandContext, id: item.id, text: item.text }); }} />
        )}
        contentContainerStyle={styles.listContent}
        onContentSizeChange={scrollToEnd}
        keyboardShouldPersistTaps="handled"
        ListEmptyComponent={
          <View style={styles.hint}>
            <Text style={styles.hintText}>Say hello to {recipient}.</Text>
          </View>
        }
      />

      {!sending && typeof state.turnOutcome?.latency_ms === 'number' && Number.isSafeInteger(state.turnOutcome.latency_ms)
        && state.turnOutcome.latency_ms >= 0 ? (
        <Text accessibilityLabel={`Turn duration: ${state.turnOutcome.latency_ms} ms`} style={styles.turnDuration}>
          Turn duration: {state.turnOutcome.latency_ms} ms
        </Text>
      ) : null}

      {missingCurrentSession ? (
        <Text style={styles.recoverySendNote} accessibilityLabel="Choose recovery before sending">
          Start a new chat or choose a saved conversation before sending.
        </Text>
      ) : pendingRecoveryPrompt ? (
        <Text style={styles.recoverySendNote} accessibilityLabel="Review saved message before sending">
          Add or dismiss your saved message before sending another message.
        </Text>
      ) : null}
      {skillDraftTooLong && <Text style={styles.recoverySendNote} accessibilityLabel="Skill draft too long">
        Shorten the skill instructions to 2,000 characters and the full message to 4,096 characters before sending.
      </Text>}
      {staged && <View style={styles.sourceCard}>
        <View style={styles.sourceHeading}>
          <Text style={styles.recoveryTitle}>Passage for {recipient}</Text>
          <Pressable style={styles.sourceButton} onPress={() => setHistory(null)} disabled={sending}
            accessibilityRole="button" accessibilityLabel="Remove passage">
            <Text style={styles.toolBtnText}>Remove passage</Text>
          </Pressable>
        </View>
        <ScrollView style={styles.sourceExcerpt} nestedScrollEnabled>
          <Text selectable style={styles.recoveryPrompt}>{staged.selection.reference.excerpt}</Text>
        </ScrollView>
        {staged.needsReview ? <>
          <Text accessibilityLiveRegion="polite" style={styles.recoveryBody}>The hub did not confirm this send. Your draft and passage are here.</Text>
          <Pressable style={styles.sourceButton} onPress={openHistory} accessibilityRole="button">
            <Text style={styles.toolBtnText}>Review again</Text>
          </Pressable>
        </> : sourceBlocksSend && <Text style={styles.recoveryBody}>Remove the passage before sending a command.</Text>}
      </View>}

      {selectedOpen && conversation.current?.scope === chatScope ? <SelectedImages
        key={`${chatScope}:${connectionEpoch}:${state.sessionId ?? 'none'}:${agent}`}
        config={config} scope={chatScope} connectionEpoch={connectionEpoch} sessionId={state.sessionId}
        agent={agent} chat={conversation.current.chat} sending={sending}
        onClose={closeImages} onInspectHistory={openHistory} draftPendingRef={imageDraftPending} /> : null}

      {state.ready && !sending && !selectedOpen && !sessionsOpen && !commandsOpen && !currentRemember
        && !dictation?.active && !missingCurrentSession && !blockedBySavedPrompt
        && input.trim() && !input.trimStart().startsWith('/') ? (
        <View style={styles.composerActions}>
          <Pressable style={styles.directReply} disabled={sourceBlocksSend} accessibilityRole="button"
            accessibilityHint="Ask supported models to skip extended thinking for this message."
            onPress={() => send('none')}>
            <Text style={styles.toolBtnText}>Send direct reply</Text>
          </Pressable>
          {!staged && <Pressable style={styles.directReply} accessibilityRole="button"
            accessibilityLabel="Obsidian notes" accessibilityHint="Review vault excerpts before sending this question."
            onPress={openVault}>
            <Text style={styles.toolBtnText}>Obsidian notes</Text>
          </Pressable>}
        </View>
      ) : null}
      <View style={styles.inputBar}>
        <TextInput
          style={styles.input}
          value={input}
          onChangeText={text => { ++draftVersion.current; updateInput(text); }}
          placeholder={state.ready ? `Message ${recipient}…` : 'Restoring conversation…'}
          placeholderTextColor={theme.textDim}
          multiline
          editable={!sending && state.ready}
          onSubmitEditing={() => send()}
          returnKeyType="send"
        />
        {sending ? (
          <Pressable style={[styles.sendBtn, styles.stopBtn]} onPress={stop}>
            <Text style={styles.sendText}>Stop</Text>
          </Pressable>
        ) : (
          <Pressable
            style={[styles.sendBtn, (!input.trim() || !state.ready || missingCurrentSession || blockedBySavedPrompt || skillDraftTooLong || sourceBlocksSend) && styles.sendBtnDisabled]}
            onPress={() => send()}
            disabled={!input.trim() || !state.ready || missingCurrentSession || blockedBySavedPrompt || skillDraftTooLong || sourceBlocksSend}
          >
            <Text style={styles.sendText}>Send</Text>
          </Pressable>
        )}
      </View>

      {dictationControl}

      <SessionsModal key={commandContext} visible={sessionsOpen} onClose={() => setSessionsOpen(false)} onResumed={onResumed}
        recipient={agent} startInMessages={staged?.needsReview === true} sourceBlockReason={sourceBlockReason} onUseSource={selection => {
          if (sourceBlockReason()) return false;
          setHistory({ context: commandContext, selection, needsReview: false });
          return true;
        }} resumeBlockReason={resumeBlockReason} hasDraft={input.length > 0} />
      <CommandsModal visible={commandsOpen} agent={agent} onClose={closeCommands} onChoose={chooseCommand} />
      {currentComparison && <CompareAgents key={commandContext} config={config} initialAgent={agent}
        initialQuestion={currentComparison.question} onClose={() => setComparison(null)} />}
      {currentRemember && <RememberMessage key={`${currentRemember.context}:${currentRemember.id}`}
        text={currentRemember.text} config={config} onClose={() => setRemember(null)} />}
      {currentNote && <SaveChatNote key={`${currentNote.context}:${currentNote.id}`}
        text={currentNote.text} config={config} initialSubmission={noteDrafts[currentNote.id] ?? null}
        onSubmitted={draft => updateNoteDraft(currentNote.context, currentNote.id, draft)}
        onSaved={(receipt, target) => saveNoteReceipt(currentNote.context, currentNote.id, currentNote.text, receipt, target)}
        onClose={() => setNoteReview(null)} />}
      {currentViewer && <SavedVaultNoteViewer config={config} receipt={currentViewer.receipt}
        target={currentViewer.target} onClose={() => setNoteViewer(null)} />}
      {vaultReview && vaultCurrent(vaultReview) && <VaultNoteReview
        key={vaultReview.generation} config={config} question={vaultReview.question}
        current={() => vaultCurrent(vaultReview)} onSend={notes => sendWithVault(vaultReview, notes)} onClose={closeVault} />}
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
  toolbarActions: { flexDirection: 'row', flexWrap: 'wrap', flexShrink: 1, alignItems: 'center', gap: 8 },
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
  recoveryCard: {
    marginHorizontal: 12,
    marginTop: 8,
    padding: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.surfaceAlt,
    gap: 8,
  },
  recoveryTitle: { color: theme.text, fontSize: 14, fontWeight: '700' },
  sourceCard: { marginHorizontal: 12, marginVertical: 4, paddingHorizontal: 12, paddingVertical: 6, gap: 4,
    backgroundColor: theme.surfaceAlt, borderLeftColor: theme.accent, borderLeftWidth: 3, borderRadius: 8 },
  sourceHeading: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' },
  sourceButton: { minHeight: 44, justifyContent: 'center', alignSelf: 'flex-start', paddingHorizontal: 6 },
  sourceExcerpt: { maxHeight: 85 },
  recoveryBody: { color: theme.textDim, fontSize: 13, lineHeight: 18 },
  recoveryPrompt: { color: theme.text, fontSize: 14, lineHeight: 19 },
  recoveryActions: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  recoveryAction: {
    alignSelf: 'flex-start',
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: 16,
    backgroundColor: theme.accent,
  },
  recoveryActionText: { color: '#02121b', fontSize: 13, fontWeight: '700' },
  recoveryDismiss: { paddingHorizontal: 10, paddingVertical: 7 },
  recoveryDismissText: { color: theme.textDim, fontSize: 13, fontWeight: '600' },
  turnDuration: { color: theme.textDim, fontSize: 12, paddingHorizontal: 12, paddingVertical: 6 },
  recoverySendNote: { color: theme.textDim, fontSize: 12, paddingHorizontal: 12, paddingBottom: 4 },
  hint: { alignItems: 'center', marginTop: 48 },
  hintText: { color: theme.textDim, fontSize: 14 },
  composerActions: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'flex-end', paddingHorizontal: 8 },
  directReply: { alignSelf: 'flex-end', minHeight: 44, paddingHorizontal: 14, justifyContent: 'center' },
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
