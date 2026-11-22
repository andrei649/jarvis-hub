import { Text, TextInput } from './ThemedText';
import React, { useEffect, useRef, useState } from 'react';
import { KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import * as Crypto from 'expo-crypto';
import { ChatNoteTitleConflict, fetchChatNoteTarget, saveChatNote,
  type ChatNoteDraft, type ChatNoteReceipt, type ChatNoteTarget } from '../api/chatNote';
import type { ServerConfig } from '../storage/settings';
import { useThemeStyles, type Theme } from '../theme';

const sameTarget = (a: ChatNoteTarget, b: ChatNoteTarget) =>
  a.id === b.id && a.vault === b.vault && a.inbox === b.inbox;

type ChatNoteEditorProps = {
  text: string;
  initialTitle?: string;
  config: ServerConfig;
  initialSubmission: ChatNoteDraft | null;
  onSubmitted: (draft: ChatNoteDraft | null) => void;
  onSaved: (receipt: ChatNoteReceipt, target: ChatNoteTarget) => void;
  onClose: () => void;
};

export function SaveChatNote(props: ChatNoteEditorProps) {
  return <Modal visible transparent animationType="fade" onRequestClose={props.onClose}>
    <ChatNoteEditor {...props} />
  </Modal>;
}

export function ChatNoteEditor({ text, config, initialTitle, initialSubmission, onSubmitted, onSaved, onClose }: ChatNoteEditorProps) {
  const { theme, styles } = useThemeStyles(makeStyles);
  const [target, setTarget] = useState<ChatNoteTarget | null>(initialSubmission?.target ?? null);
  const [title, setTitle] = useState(() => initialSubmission?.title ??
    Array.from(initialTitle ?? text.trim().split(/\r?\n/, 1)[0]).slice(0, 120).join(''));
  const [content, setContent] = useState(initialSubmission?.content ?? text);
  const [submitted, setSubmitted] = useState<ChatNoteDraft | null>(initialSubmission);
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(true);
  const [notice, setNotice] = useState('Checking destination…');
  const [conflictedTitle, setConflictedTitle] = useState('');
  const [saved, setSaved] = useState<ChatNoteReceipt | null>(null);
  const live = useRef(true);
  const busyRef = useRef(false);

  useEffect(() => {
    live.current = true;
    void fetchChatNoteTarget(config).then(found => {
      if (!live.current) return;
      setTarget(found);
      setChecking(false);
      if (submitted && found && !sameTarget(submitted.target, found)) {
        setSubmitted(null); onSubmitted(null);
        setNotice('Destination changed. Review it before starting a new save. The previous result may still be uncertain.');
      } else setNotice(found ? (submitted ? 'Previous save is unconfirmed. Retry the same request.' : '')
        : 'No Obsidian inbox is available on this hub. Your draft is still here.');
    }).catch(() => {
      if (live.current) { setChecking(false); setTarget(null); setNotice('Destination could not be checked. Your draft is still here.'); }
    });
    return () => { live.current = false; };
  }, [config]);

  const refresh = async () => {
    if (busyRef.current || checking) return;
    setChecking(true);
    setNotice('Checking destination…');
    try {
      const found = await fetchChatNoteTarget(config);
      if (!live.current) return;
      setTarget(found);
      if (submitted && found && !sameTarget(submitted.target, found)) {
        setSubmitted(null); onSubmitted(null);
        setNotice('Destination changed. Review it before starting a new save. The previous result may still be uncertain.');
      } else setNotice(found ? (submitted ? 'Previous save is unconfirmed. Retry the same request.' : '')
        : 'No Obsidian inbox is available on this hub. Your draft is still here.');
    } catch {
      if (live.current) { setTarget(null); setNotice('Destination could not be checked. Your draft is still here.'); }
    } finally { if (live.current) setChecking(false); }
  };

  const valid = !!target && !busy && !checking && !saved && !!title.trim() && !!content.trim()
    && Array.from(title).length <= 120 && Array.from(content).length <= 100_000
    && (!conflictedTitle || title !== conflictedTitle);

  const save = async () => {
    if (!valid || busyRef.current || !target) return;
    let draft = submitted;
    if (!draft) {
      try { draft = { target, title, content, requestId: Crypto.randomUUID() }; }
      catch { setNotice('Secure request ID unavailable. Your draft is still here.'); return; }
    }
    const priorSubmission = submitted;
    let postAttempted = false;
    busyRef.current = true;
    setBusy(true);
    setNotice('Checking destination…');
    try {
      const fresh = await fetchChatNoteTarget(config);
      if (!live.current) return;
      if (!fresh || !sameTarget(draft.target, fresh)) {
        setTarget(fresh);
        if (fresh) { setSubmitted(null); onSubmitted(null); }
        setNotice(fresh
          ? priorSubmission ? 'Destination changed. Review it before starting a new save. The previous result may still be uncertain.'
            : 'Destination changed. Review it before saving.'
          : priorSubmission ? 'Destination is unavailable. Your draft and request ID are retained for retry.'
            : 'Destination is unavailable. Your editable draft is still here.');
        return;
      }
      setSubmitted(draft);
      onSubmitted(draft);
      postAttempted = true;
      setNotice('Saving…');
      const receipt = await saveChatNote(config, draft);
      if (!live.current) return;
      setSaved(receipt);
      setSubmitted(null);
      onSubmitted(null);
      onSaved(receipt, draft.target);
      setNotice(`Saved: ${receipt.relPath}`);
    } catch (error) {
      if (!live.current) return;
      if (error instanceof ChatNoteTitleConflict) {
        setSubmitted(null);
        onSubmitted(null);
        setConflictedTitle(draft.title);
        setNotice('A note already uses this title. Change the title and save again.');
      } else setNotice(postAttempted || priorSubmission
        ? 'Save could not be confirmed. Retry the same request.'
        : 'Destination could not be checked. Your editable draft is still here.');
    } finally {
      busyRef.current = false;
      if (live.current) setBusy(false);
    }
  };

  return <KeyboardAvoidingView style={styles.backdrop} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
      <View style={styles.sheet} accessibilityViewIsModal>
        <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.content}>
          <View style={styles.header}>
            <Text style={styles.heading} accessibilityRole="header">Save to Obsidian</Text>
            <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="Close Save to Obsidian" hitSlop={8}>
              <Text style={styles.close}>Close</Text>
            </Pressable>
          </View>
          <Text style={styles.explanation}>Review the reply and destination before saving.</Text>
          <Text style={styles.label}>Vault on this hub</Text>
          <Text style={styles.value} selectable>{target?.vault ?? 'Unavailable'}</Text>
          <Text style={styles.label}>Inbox</Text>
          <Text style={styles.value} selectable>{target?.inbox ?? 'Unavailable'}</Text>
          <Text style={styles.label}>Title</Text>
          <TextInput style={styles.title} value={title} onChangeText={setTitle} editable={!submitted && !busy}
            accessibilityLabel="Note title" placeholder="Note title" placeholderTextColor={theme.textDim} />
          <Text style={styles.label}>Note</Text>
          <TextInput style={styles.note} value={content} onChangeText={setContent} editable={!submitted && !busy}
            accessibilityLabel="Note content" multiline textAlignVertical="top" placeholderTextColor={theme.textDim} />
          {Array.from(title).length > 120 ? <Text style={styles.warning} accessibilityRole="alert">Title exceeds 120 characters.</Text> : null}
          {Array.from(content).length > 100_000 ? <Text style={styles.warning} accessibilityRole="alert">Note exceeds 100,000 characters.</Text> : null}
          {notice ? <Text style={styles.notice} accessibilityRole="alert" selectable>{notice}</Text> : null}
          <View style={styles.actions}>
            {!target && <Pressable style={styles.secondary} onPress={() => void refresh()} disabled={checking || busy}
              accessibilityRole="button" accessibilityLabel="Check Obsidian destination">
              <Text style={styles.secondaryText}>Check destination</Text>
            </Pressable>}
            <Pressable style={[styles.save, !valid && styles.disabled]} onPress={() => void save()} disabled={!valid}
              accessibilityRole="button" accessibilityLabel={submitted ? 'Retry save note' : 'Save note'}>
              <Text style={styles.saveText}>{busy ? 'Saving…' : submitted ? 'Retry save' : 'Save note'}</Text>
            </Pressable>
          </View>
        </ScrollView>
      </View>
    </KeyboardAvoidingView>;
}

const makeStyles = (theme: Theme) => StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: '#000a', justifyContent: 'center', padding: 12 },
  sheet: { maxHeight: '90%', width: '100%', backgroundColor: theme.surfaceAlt,
    borderColor: theme.border, borderWidth: 1, borderRadius: 16 },
  content: { padding: 16, gap: 8 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  heading: { color: theme.text, fontSize: 18, fontWeight: '700', flexShrink: 1 },
  close: { color: theme.accent, fontSize: 14, fontWeight: '600', paddingVertical: 8 },
  explanation: { color: theme.textDim, fontSize: 13, lineHeight: 19 },
  label: { color: theme.text, fontSize: 13, fontWeight: '600', marginTop: 4 },
  value: { color: theme.text, fontSize: 14 },
  title: { borderRadius: 12, borderWidth: 1, borderColor: theme.border, backgroundColor: theme.surface,
    color: theme.text, fontSize: 15, padding: 12 },
  note: { minHeight: 140, maxHeight: 260, borderRadius: 12, borderWidth: 1, borderColor: theme.border,
    backgroundColor: theme.surface, color: theme.text, fontSize: 15, padding: 12 },
  warning: { color: theme.warn, fontSize: 13 },
  notice: { color: theme.text, fontSize: 13, lineHeight: 18 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'flex-end', alignItems: 'center', gap: 10 },
  secondary: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 12 },
  secondaryText: { color: theme.accent, fontSize: 14, fontWeight: '600' },
  save: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 18, borderRadius: 20,
    backgroundColor: theme.accent },
  disabled: { opacity: 0.5 },
  saveText: { color: '#02121b', fontSize: 14, fontWeight: '700' },
});
