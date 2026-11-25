import { Text, TextInput } from './ThemedText';
import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { fetchAgents, selectableChatAgents, type AgentInfo } from '../api/client';
import { compareAgents, type AgentOpinion } from '../api/agentOpinions';
import type { ChatNoteDraft, ChatNoteReceipt, ChatNoteTarget } from '../api/chatNote';
import type { ServerConfig } from '../storage/settings';
import { useThemeStyles, type Theme } from '../theme';
import { ChatNoteEditor } from './SaveChatNote';
import { SavedVaultNoteContent } from './SavedVaultNoteViewer';

type Result = { question: string; ids: [string, string]; names: [string, string]; opinions: AgentOpinion[] };
type NoteState = { draft: ChatNoteDraft | null; saved: { receipt: ChatNoteReceipt; target: ChatNoteTarget } | null };
const emptyNote = (): NoteState => ({ draft: null, saved: null });
const reasons: Record<string, string> = {
  cloud_disabled: 'Cloud use is off for this question.', model_unavailable: 'No eligible model is available.',
  agent_unavailable: 'This agent is unavailable.', timed_out: 'This agent ran out of time.',
  generation_failed: 'This agent could not return an answer.', route_unavailable: 'No eligible route is available.',
};

function noteTitle(agent: string, question: string): string {
  const clean = `${agent} — ${question.trim().split(/\r?\n/, 1)[0]}`
    .replace(/[<>:"/\\|?*\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim();
  return Array.from(clean).slice(0, 120).join('').replace(/[. ]+$/, '') || 'Agent answer';
}

function noteText(result: Result, agent: string, opinion: AgentOpinion): string {
  return [`Question\n${result.question}`, `Answer by\n${agent} (${opinion.agent})`,
    ...(opinion.model ? [`Reported model\n${opinion.model}`] : []),
    ...(opinion.route ? [`Reported route\n${opinion.route}`] : []),
    `Answer\n${opinion.text}`].join('\n\n');
}

export function CompareAgents({ config, initialQuestion = '', initialAgent = '', onClose }: {
  config: ServerConfig; initialQuestion?: string; initialAgent?: string; onClose: () => void;
}) {
  const { theme, styles } = useThemeStyles(makeStyles);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [rosterBusy, setRosterBusy] = useState(true);
  const [rosterError, setRosterError] = useState(false);
  const [question, setQuestion] = useState(initialQuestion);
  const [first, setFirst] = useState(initialAgent);
  const [second, setSecond] = useState('');
  const [expandedSlot, setExpandedSlot] = useState<'first' | 'second' | null>(null);
  const [allowCloud, setAllowCloud] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<Result | null>(null);
  const [notes, setNotes] = useState<Record<string, NoteState>>({});
  const [activeNote, setActiveNote] = useState<string | null>(null);
  const [activeViewer, setActiveViewer] = useState<string | null>(null);
  const mounted = useRef(true);
  const rosterEpoch = useRef(0);
  const compareEpoch = useRef(0);
  const comparing = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const identity = JSON.stringify([config.baseUrl, config.token, config.adminToken]);
  const currentIdentity = useRef(identity);
  currentIdentity.current = identity;

  useEffect(() => {
    mounted.current = true;
    const request = ++rosterEpoch.current;
    ++compareEpoch.current;
    controller.current?.abort();
    comparing.current = false;
    setBusy(false); setResult(null); setNotes({}); setRosterBusy(true); setRosterError(false);
    setAllowCloud(false);
    setExpandedSlot(null); setActiveNote(null); setActiveViewer(null);
    void fetchAgents(config).then(roster => {
      if (!mounted.current || request !== rosterEpoch.current || currentIdentity.current !== identity) return;
      const available = selectableChatAgents(roster);
      setAgents(available);
      const selected = available.some(item => item.id === initialAgent) ? initialAgent : available[0]?.id || '';
      setFirst(selected);
      setSecond(available.find(item => item.id !== selected)?.id || '');
    }).catch(() => {
      if (mounted.current && request === rosterEpoch.current && currentIdentity.current === identity) {
        setAgents([]); setFirst(''); setSecond(''); setRosterError(true);
      }
    }).finally(() => {
      if (mounted.current && request === rosterEpoch.current && currentIdentity.current === identity) setRosterBusy(false);
    });
    return () => { ++rosterEpoch.current; ++compareEpoch.current; controller.current?.abort(); mounted.current = false; };
  }, [identity, initialAgent]);

  function resetResult() {
    ++compareEpoch.current;
    controller.current?.abort();
    comparing.current = false;
    setBusy(false); setError(''); setResult(null); setNotes({}); setAllowCloud(false);
  }

  function close() {
    ++rosterEpoch.current; ++compareEpoch.current;
    controller.current?.abort();
    onClose();
  }

  async function submit() {
    if (comparing.current) return;
    const text = question.trim();
    if (!text || Array.from(text).length > 4096 || first === second ||
        !agents.some(item => item.id === first) || !agents.some(item => item.id === second)) {
      setError(!text ? 'Enter a question to compare.' : Array.from(text).length > 4096
        ? 'Shorten the question to 4,096 characters.' : 'Choose two different available agents.');
      return;
    }
    const request = ++compareEpoch.current;
    const submittedIdentity = identity;
    const ids: [string, string] = [first, second];
    const names: [string, string] = ids.map(id => agents.find(item => item.id === id)?.name || id) as [string, string];
    const consent = allowCloud;
    const abort = new AbortController();
    controller.current = abort;
    comparing.current = true;
    setBusy(true); setError(''); setResult(null); setNotes({}); setAllowCloud(false);
    try {
      const opinions = await compareAgents(config, text, ids, consent, abort.signal);
      if (!mounted.current || abort.signal.aborted || request !== compareEpoch.current ||
          submittedIdentity !== currentIdentity.current) return;
      setResult({ question: text, ids, names, opinions });
    } catch (failure) {
      if (mounted.current && request === compareEpoch.current && submittedIdentity === currentIdentity.current &&
          !abort.signal.aborted) {
        const status = (failure as { status?: number })?.status;
        setError(status === 401 || status === 403 || (failure as Error)?.message === 'Owner token required'
          ? 'Owner access is required. Check your owner token in Settings, then try again.'
          : status === 429 ? 'A comparison is already running. Wait for it to finish, then submit again.'
            : 'The comparison could not be confirmed. Review the question and try again.');
      }
    } finally {
      if (request === compareEpoch.current) { comparing.current = false; setBusy(false); controller.current = null; }
    }
  }

  function openNote(id: string) {
    if (!result || notes[id]?.saved || activeNote) return;
    setActiveNote(id);
  }

  const selectedOpinion = activeNote && result?.opinions.find(item => item.agent === activeNote && item.ok && item.text?.trim());
  const selectedName = activeNote && result ? result.names[result.ids.indexOf(activeNote)] : '';
  const viewedNote = activeViewer ? notes[activeViewer]?.saved : null;
  const valid = !!question.trim() && Array.from(question.trim()).length <= 4096 && first !== second &&
    agents.some(item => item.id === first) && agents.some(item => item.id === second);

  return <>
    <Modal visible transparent animationType="fade"
      onRequestClose={activeViewer ? () => setActiveViewer(null) : activeNote ? () => setActiveNote(null) : close}>
      {viewedNote ? <SavedVaultNoteContent key={activeViewer} config={config}
        target={viewedNote.target} receipt={viewedNote.receipt} onClose={() => setActiveViewer(null)} />
      : result && activeNote && selectedOpinion ? <ChatNoteEditor key={activeNote} config={config}
        text={noteText(result, selectedName || activeNote, selectedOpinion)}
        initialTitle={noteTitle(selectedName || activeNote, result.question)}
        initialSubmission={notes[activeNote]?.draft || null}
        onSubmitted={draft => setNotes(previous => ({ ...previous,
          [activeNote]: { ...(previous[activeNote] || emptyNote()), draft } }))}
        onSaved={(receipt, target) => setNotes(previous => ({ ...previous,
          [activeNote]: { draft: null, saved: { receipt, target } } }))}
        onClose={() => setActiveNote(null)} /> :
      <KeyboardAvoidingView style={styles.backdrop} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
        <View style={styles.sheet} accessibilityViewIsModal>
          <View style={styles.header}>
            <Text style={styles.heading} accessibilityRole="header">Compare two agents</Text>
            <Pressable onPress={close} accessibilityRole="button" accessibilityLabel="Close comparison" hitSlop={8}>
              <Text style={styles.link}>Close</Text>
            </Pressable>
          </View>
          <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.content}>
            <Text style={styles.hint}>Only this question is sent. Chat history and attachments are excluded.</Text>
            <TextInput accessibilityLabel="Comparison question" value={question} onChangeText={value => { setQuestion(value); resetResult(); }}
              multiline style={styles.question} placeholder="Question" placeholderTextColor={theme.textDim}/>
            <Text style={styles.hint}>Up to 4,096 characters.</Text>
            {Array.from(question.trim()).length > 4096 &&
              <Text style={styles.error} accessibilityRole="alert">Shorten the question to 4,096 characters.</Text>}
            {(['first', 'second'] as const).map(slot => {
              const chosen = slot === 'first' ? first : second;
              const label = slot === 'first' ? 'First' : 'Second';
              return <View key={slot}>
                <Pressable accessibilityRole="button" accessibilityState={{ expanded: expandedSlot === slot, disabled: rosterBusy || busy }}
                  accessibilityLabel={`${label} agent: ${agents.find(agent => agent.id === chosen)?.name || chosen || 'Select an agent'}`}
                  disabled={rosterBusy || busy} style={styles.selector}
                  onPress={() => setExpandedSlot(previous => previous === slot ? null : slot)}>
                  <Text style={styles.choiceName}>{agents.find(agent => agent.id === chosen)?.name || chosen || 'Select an agent'}</Text>
                  <Text style={styles.choiceRole}>{expandedSlot === slot ? '▲' : '▼'}</Text>
                </Pressable>
                {expandedSlot === slot && <View style={styles.choices} accessibilityRole="radiogroup">{agents.map(agent => <Pressable key={agent.id}
                  accessibilityRole="radio" accessibilityState={{ selected: chosen === agent.id, disabled: rosterBusy || busy }}
                  accessibilityLabel={`Choose ${agent.name || agent.id} as ${slot} agent`}
                  disabled={rosterBusy || busy}
                  style={[styles.choice, chosen === agent.id && styles.chosen]}
                  onPress={() => {
                    if (slot === 'first') {
                      if (agent.id === second) setSecond(first);
                      setFirst(agent.id);
                    } else {
                      if (agent.id === first) setFirst(second);
                      setSecond(agent.id);
                    }
                    setExpandedSlot(null);
                    resetResult();
                  }}>
                  <Text style={styles.choiceName}>{agent.name || agent.id}</Text>
                  {!!agent.role && <Text style={styles.choiceRole}>{agent.role}</Text>}
                </Pressable>)}</View>}
              </View>;
            })}
            {rosterBusy && <ActivityIndicator color={theme.accent} accessibilityLabel="Loading comparison agents" />}
            {rosterError && <Text style={styles.error} accessibilityRole="alert">Could not load agents. Close and try again.</Text>}
            {!rosterBusy && !rosterError && agents.length < 2 &&
              <Text style={styles.error} accessibilityRole="alert">Two available agents are required.</Text>}
            <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: allowCloud, disabled: busy }}
              accessibilityLabel="Allow approved cloud models for this question" disabled={busy}
              style={styles.cloud} onPress={() => { resetResult(); setAllowCloud(!allowCloud); }}>
              <Text style={styles.cloudMark}>{allowCloud ? '☑' : '☐'}</Text>
              <View style={styles.cloudText}><Text style={styles.label}>Allow approved cloud models for this question</Text>
                <Text style={styles.hint}>This can send the question to an approved remote provider.</Text></View>
            </Pressable>
            {error ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : null}
            {busy && <Text style={styles.hint} accessibilityLiveRegion="polite">Waiting for both agents…</Text>}
            <Pressable accessibilityRole="button" accessibilityLabel="Compare answers" disabled={!valid || busy || rosterBusy}
              style={[styles.primary, (!valid || busy || rosterBusy) && styles.disabled]} onPress={() => void submit()}>
              <Text style={styles.primaryText}>{busy ? 'Comparing…' : 'Compare answers'}</Text>
            </Pressable>
            {result && result.ids.map((id, index) => {
              const item = result.opinions.find(opinion => opinion.agent === id);
              const name = result.names[index];
              const usable = !!item?.ok && !!item.text?.trim();
              const saved = notes[id]?.saved;
              return <View key={id} style={styles.answerCard} accessibilityLabel={`Answer from ${name}`}>
                <Text style={styles.answerName} accessibilityRole="header">{name} ({id})</Text>
                <Text style={styles.hint}>Reported model and route: {item?.model || item?.route
                  ? [item?.model, item?.route].filter(Boolean).join(' · ') : 'Not reported'}</Text>
                <Text style={usable ? styles.answer : styles.error} selectable>{usable ? item!.text
                  : item?.reason ? reasons[item.reason] || item.reason : 'No answer returned.'}</Text>
                {usable && <Pressable accessibilityRole="button" accessibilityLabel={`Save ${name} answer to Obsidian`}
                  disabled={!!saved} style={[styles.secondary, !!saved && styles.disabled]} onPress={() => openNote(id)}>
                  <Text style={styles.link}>{saved ? 'Saved to Obsidian' : 'Save to Obsidian'}</Text>
                </Pressable>}
                {saved && <Text style={styles.hint} accessibilityLiveRegion="polite" selectable>Saved: {saved.receipt.relPath}</Text>}
                {saved && <Pressable accessibilityRole="button" accessibilityLabel={`Open ${name} saved note`}
                  style={styles.secondary} onPress={() => setActiveViewer(id)}>
                  <Text style={styles.link}>Open saved note</Text>
                </Pressable>}
              </View>;
            })}
          </ScrollView>
        </View>
      </KeyboardAvoidingView>}
    </Modal>
  </>;
}

const makeStyles = (theme: Theme) => StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: '#000a', justifyContent: 'center', padding: 12 },
  sheet: { maxHeight: '94%', width: '100%', backgroundColor: theme.surfaceAlt,
    borderColor: theme.border, borderWidth: 1, borderRadius: 16 },
  header: { minHeight: 48, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    gap: 12, paddingHorizontal: 16, borderBottomColor: theme.border, borderBottomWidth: 1 },
  heading: { color: theme.text, fontSize: 18, fontWeight: '700', flexShrink: 1 },
  content: { padding: 16, gap: 10 },
  hint: { color: theme.textDim, fontSize: 13, lineHeight: 19 },
  label: { color: theme.text, fontSize: 14, fontWeight: '600' },
  question: { color: theme.text, backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1,
    borderRadius: 8, minHeight: 94, padding: 12, fontSize: 16, textAlignVertical: 'top' },
  selector: { minHeight: 48, marginTop: 8, paddingHorizontal: 12, flexDirection: 'row', alignItems: 'center',
    justifyContent: 'space-between', borderColor: theme.border, borderWidth: 1, borderRadius: 8,
    backgroundColor: theme.surface },
  choices: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 8 },
  choice: { minHeight: 48, minWidth: 108, maxWidth: '100%', justifyContent: 'center', padding: 9,
    borderColor: theme.border, borderWidth: 1, borderRadius: 8, backgroundColor: theme.surface },
  chosen: { borderColor: theme.accent, backgroundColor: theme.accentDim },
  choiceName: { color: theme.text, fontSize: 14, fontWeight: '600' },
  choiceRole: { color: theme.textDim, fontSize: 11, marginTop: 2 },
  cloud: { minHeight: 48, flexDirection: 'row', alignItems: 'center', gap: 8 },
  cloudMark: { color: theme.accent, fontSize: 22 },
  cloudText: { flex: 1 },
  error: { color: theme.danger, fontSize: 13, lineHeight: 19 },
  primary: { minHeight: 48, alignItems: 'center', justifyContent: 'center', borderRadius: 8, backgroundColor: theme.accent },
  primaryText: { color: theme.bg, fontSize: 15, fontWeight: '700' },
  secondary: { minHeight: 44, alignSelf: 'flex-start', justifyContent: 'center' },
  link: { color: theme.accent, fontSize: 14, fontWeight: '600' },
  disabled: { opacity: 0.5 },
  answerCard: { gap: 8, borderColor: theme.border, borderWidth: 1, borderRadius: 10,
    padding: 12, backgroundColor: theme.surface },
  answerName: { color: theme.text, fontSize: 16, fontWeight: '700' },
  answer: { color: theme.text, fontSize: 14, lineHeight: 21 },
});
