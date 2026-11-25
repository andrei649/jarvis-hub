import { Text } from './ThemedText';
import React, { useEffect, useRef, useState } from 'react';
import { KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { fetchVaultExcerpts, type VaultExcerpt } from '../api/client';
import type { ServerConfig } from '../storage/settings';
import { useThemeStyles, type Theme } from '../theme';

export function VaultNoteReview({ config, question, current, onSend, onClose }: {
  config: ServerConfig;
  question: string;
  current: () => boolean;
  onSend: (notes: VaultExcerpt[]) => boolean;
  onClose: () => void;
}) {
  const { styles } = useThemeStyles(makeStyles);
  const [notes, setNotes] = useState<VaultExcerpt[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(true);
  const [notice, setNotice] = useState('Searching notes…');
  const pending = useRef<AbortController | null>(null);
  const live = useRef(true);

  useEffect(() => {
    live.current = true;
    const controller = new AbortController();
    pending.current = controller;
    void fetchVaultExcerpts(config, question, controller.signal).then(found => {
      if (!live.current || !current() || controller.signal.aborted) return;
      setNotes(found);
      setNotice(found.length ? '' : 'No matching notes. Try different words.');
    }).catch(() => {
      if (live.current && current() && !controller.signal.aborted) setNotice('The vault could not be searched. Try again.');
    }).finally(() => {
      if (live.current && pending.current === controller) { pending.current = null; setBusy(false); }
    });
    return () => { live.current = false; controller.abort(); pending.current?.abort(); pending.current = null; };
  }, [config, question]);

  const toggle = (name: string) => {
    if (busy || !current()) return;
    setSelected(previous => previous.includes(name) ? previous.filter(item => item !== name) : [...previous, name]);
  };

  const send = async () => {
    if (pending.current || !selected.length || !current()) return;
    const chosen = notes.filter(note => selected.includes(note.name));
    if (chosen.length !== selected.length) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setNotice('Checking selected notes…');
    try {
      const found = await fetchVaultExcerpts(config, question, controller.signal);
      if (!live.current || !current() || controller.signal.aborted) return;
      if (chosen.some(note => !found.some(fresh => fresh.name === note.name && fresh.text === note.text))) {
        setNotes(found);
        setSelected([]);
        setNotice('A selected note changed or disappeared. Review the results again.');
        return;
      }
      if (!onSend(chosen)) setNotice('The message was not sent. Your draft is still here.');
    } catch {
      if (live.current && current() && !controller.signal.aborted) {
        setSelected([]);
        setNotice('The notes could not be checked. Review and select them again.');
      }
    } finally {
      if (live.current && pending.current === controller) { pending.current = null; setBusy(false); }
    }
  };

  return <Modal visible transparent animationType="fade" onRequestClose={onClose}>
    <KeyboardAvoidingView style={styles.backdrop} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
      <View style={styles.sheet} accessibilityViewIsModal>
        <View style={styles.header}>
          <Text style={styles.title} accessibilityRole="header">Obsidian notes</Text>
          <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="Close Obsidian notes" hitSlop={8}>
            <Text style={styles.close}>Close</Text>
          </Pressable>
        </View>
        <ScrollView style={styles.scroll} keyboardShouldPersistTaps="handled" contentContainerStyle={styles.content}>
          <Text style={styles.explanation}>Your agent’s model (local or cloud) receives the selected text. Chat history keeps your original question.</Text>
          {notice ? <Text style={styles.notice} accessibilityRole="alert">{notice}</Text> : null}
          {notes.map(note => <Pressable key={note.name}
            style={[styles.note, selected.includes(note.name) && styles.noteSelected]} onPress={() => toggle(note.name)}
            disabled={busy} accessibilityRole={Platform.OS === 'web' ? 'button' : 'checkbox'}
            accessibilityState={{ checked: selected.includes(note.name), disabled: busy }}
            aria-pressed={Platform.OS === 'web' ? selected.includes(note.name) : undefined}
            aria-checked={Platform.OS === 'web' ? undefined : selected.includes(note.name)} aria-disabled={busy}
            accessibilityLabel={`Select note ${note.name}`}>
            <Text style={styles.name}>{selected.includes(note.name) ? '☑' : '☐'} {note.name}</Text>
            <Text style={styles.excerpt} selectable>{note.text}</Text>
          </Pressable>)}
        </ScrollView>
        <View style={styles.footer}>
          {selected.length ? <Text style={styles.count}>{selected.length} selected</Text> : <View />}
          <Pressable style={[styles.send, (!selected.length || busy) && styles.disabled]} onPress={() => void send()}
            disabled={!selected.length || busy} accessibilityRole="button" accessibilityLabel="Send with notes"
            aria-disabled={!selected.length || busy}>
            <Text style={styles.sendText}>{busy && selected.length ? 'Checking…' : 'Send with notes'}</Text>
          </Pressable>
        </View>
      </View>
    </KeyboardAvoidingView>
  </Modal>;
}

const makeStyles = (theme: Theme) => StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: '#000a', justifyContent: 'center', padding: 12 },
  sheet: { maxHeight: '90%', width: '100%', backgroundColor: theme.surfaceAlt, borderColor: theme.border,
    borderWidth: 1, borderRadius: 16 },
  scroll: { flexShrink: 1 },
  content: { paddingHorizontal: 16, gap: 12 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12,
    padding: 16 },
  title: { color: theme.text, fontSize: 18, fontWeight: '700', flexShrink: 1 },
  close: { color: theme.accent, fontSize: 14, fontWeight: '600', paddingVertical: 12 },
  explanation: { color: theme.textDim, fontSize: 13, lineHeight: 19 },
  notice: { color: theme.text, fontSize: 13 },
  note: { borderWidth: 1, borderColor: theme.border, borderRadius: 12, backgroundColor: theme.surface,
    padding: 12, gap: 8 },
  noteSelected: { borderColor: theme.accent, backgroundColor: theme.userBubble },
  name: { color: theme.text, fontSize: 14, fontWeight: '700' },
  excerpt: { color: theme.text, fontSize: 14, lineHeight: 20 },
  footer: { padding: 16, flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center',
    justifyContent: 'space-between', gap: 8 },
  count: { color: theme.textDim, fontSize: 13 },
  send: { alignSelf: 'flex-end', backgroundColor: theme.accent, borderRadius: 20,
    minHeight: 44, justifyContent: 'center', paddingHorizontal: 18 },
  disabled: { opacity: 0.5 },
  sendText: { color: '#02121b', fontSize: 14, fontWeight: '700' },
});
