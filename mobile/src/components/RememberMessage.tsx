import { Text, TextInput } from './ThemedText';
import React, { useEffect, useRef, useState } from 'react';
import { KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { listChatFacts, saveChatFact, type CuratedFact, type FactStore } from '../api/client';
import type { ServerConfig } from '../storage/settings';
import { useThemeStyles, type Theme } from '../theme';

const label = (store: FactStore) => store === 'memory' ? 'Agent notes' : 'User profile';

export function RememberMessage({ text, config, onClose }: {
  text: string;
  config: ServerConfig;
  onClose: () => void;
}) {
  const { theme, styles } = useThemeStyles(makeStyles);
  const [store, setStore] = useState<FactStore>('memory');
  const [draft, setDraft] = useState(text);
  const [saved, setSaved] = useState<CuratedFact | null>(null);
  const [replacing, setReplacing] = useState(false);
  const [entries, setEntries] = useState<CuratedFact[]>([]);
  const [selected, setSelected] = useState<CuratedFact | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState('');
  const busyRef = useRef(false);
  const aliveRef = useRef(true);
  useEffect(() => { aliveRef.current = true; return () => { aliveRef.current = false; }; }, []);
  const value = draft.trim();
  const length = Array.from(value).length;
  const target = saved ?? selected;
  const normalized = value.replace(/[\s\u0085\u001c-\u001f]+/gu, ' ').trim();
  const duplicate = replacing && entries.some(entry => entry.entry_id !== target?.entry_id && entry.value === normalized);
  const canSave = !busy && (!replacing || !!target) && length > 0 && length <= 300
    && !!normalized && normalized !== target?.value && !duplicate;

  const refresh = async (selectedStore = store) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setLoading(true);
    setReplacing(true);
    setSelected(null);
    setEntries([]);
    setNotice('');
    try {
      const facts = await listChatFacts(config, selectedStore);
      if (aliveRef.current) setEntries(facts);
    } catch (error) {
      if (aliveRef.current) {
        setEntries([]);
        setNotice(error instanceof Error ? error.message : 'Could not load saved facts.');
      }
    } finally {
      busyRef.current = false;
      if (aliveRef.current) { setBusy(false); setLoading(false); }
    }
  };

  const save = async () => {
    if (!canSave || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setNotice('');
    try {
      const result = await saveChatFact(config, store, value, target?.entry_id);
      if (!aliveRef.current) return;
      if (result.changed === false) {
        setNotice(target ? 'No change to the saved fact.' : 'Fact already saved; nothing changed.');
        return;
      }
      const entry = result.entry;
      setSaved(entry);
      setEntries(current => current.map(item => item.entry_id === target?.entry_id ? entry : item));
      setDraft(entry.value);
      setNotice(`${target ? 'Corrected' : 'Saved'} fact in ${label(entry.store)}. New conversations can include it when automatic memory is on.`);
    } catch (error) {
      if (!aliveRef.current) return;
      const status = (error as { status?: number })?.status;
      const reason = status === 401 ? 'Owner access is required.'
        : error instanceof Error ? error.message : 'Try again.';
      if (target && (status === 404 || status === 409)) {
        setSelected(null);
        setSaved(null);
        setEntries([]);
        setReplacing(true);
      }
      setNotice(`${target ? 'Correction' : 'Save'} refused: ${reason} The draft is still here.${target && (status === 404 || status === 409) ? ' Refresh saved facts and choose the current entry.' : ''}`);
    } finally {
      busyRef.current = false;
      if (aliveRef.current) setBusy(false);
    }
  };

  return <Modal visible transparent animationType="fade" onRequestClose={onClose}>
    <KeyboardAvoidingView style={styles.backdrop} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
      <View style={styles.sheet} accessibilityViewIsModal>
        <ScrollView style={styles.body} keyboardShouldPersistTaps="handled" contentContainerStyle={styles.content}>
          <View style={styles.header}>
            <Text style={styles.title} accessibilityRole="header">Remember message</Text>
            <Pressable onPress={onClose} hitSlop={8} accessibilityRole="button" accessibilityLabel="Close remember message">
              <Text style={styles.close}>Close</Text>
            </Pressable>
          </View>
          <Text style={styles.explanation}>{replacing
            ? 'Replace one saved fact. Your chat message stays unchanged.'
            : 'Edit the fact before saving it for future chats. Saved facts are shared across agents. With automatic memory on, new owner chats can include them on the selected local or cloud model.'}</Text>
          <Text style={styles.fieldLabel}>Save in</Text>
          <View style={styles.stores}>
            {(['memory', 'user'] as FactStore[]).map(option => <Pressable key={option}
              style={[styles.store, store === option && styles.storeSelected]}
              disabled={busy || !!saved} onPress={() => {
                if (store === option) return;
                setStore(option);
                if (replacing) void refresh(option);
              }} accessibilityRole="radio"
              accessibilityState={{ checked: store === option, disabled: busy || !!saved }}
              accessibilityLabel={label(option)}>
              <Text style={styles.storeText}>{label(option)}</Text>
            </Pressable>)}
          </View>
          {!saved && !replacing && <Pressable onPress={() => void refresh()} disabled={busy}
            accessibilityRole="button" accessibilityLabel="Replace a saved fact">
            <Text style={styles.link}>Replace a saved fact in {label(store)}</Text>
          </Pressable>}
          {replacing && !saved && <>
            <View style={styles.actions}>
              <Pressable onPress={() => selected ? setSelected(null) : void refresh()} disabled={busy}
                accessibilityRole="button" accessibilityLabel={selected ? 'Choose another fact' : 'Refresh saved facts'}>
                <Text style={styles.link}>{selected ? 'Choose another fact' : 'Refresh saved facts'}</Text>
              </Pressable>
              <Pressable onPress={() => { setReplacing(false); setSelected(null); setEntries([]); setNotice(''); }}
                disabled={busy} accessibilityRole="button" accessibilityLabel="Save as new fact">
                <Text style={styles.link}>Save as new fact</Text>
              </Pressable>
            </View>
            {selected ? <>
              <Text style={styles.fieldLabel}>Original saved fact</Text>
              <ScrollView style={styles.original} contentContainerStyle={styles.originalContent} nestedScrollEnabled>
                <Text style={styles.storeText}>{selected.value}</Text>
              </ScrollView>
            </> : loading ? <Text style={styles.notice}>Loading saved facts…</Text> : entries.length === 0
              ? <Text style={styles.notice}>No saved facts available in {label(store)}.</Text>
              : entries.map(entry => <Pressable key={entry.entry_id} onPress={() => { setSelected(entry); setNotice(''); }}
                accessibilityRole="radio" accessibilityState={{ checked: false }}
                accessibilityLabel={`Replace: ${entry.value}`} style={styles.choice}>
                <Text style={styles.storeText}>{entry.value}</Text>
              </Pressable>)}
            {duplicate && <Text style={styles.warning}>That fact is already saved in this store.</Text>}
          </>}
          <Text style={styles.fieldLabel}>{replacing ? 'Replacement fact' : 'Fact to save'}</Text>
          <TextInput style={styles.input} value={draft} onChangeText={setDraft} multiline
            editable={!busy} textAlignVertical="top" placeholder="A short fact for future chats"
            placeholderTextColor={theme.textDim} accessibilityLabel={replacing ? 'Replacement fact' : 'Fact to save'} />
          <Text style={[styles.count, length > 300 && styles.warning]} accessibilityLiveRegion="polite">
            {length}/300 characters{length > 300 ? ' · shorten the fact to save.' : ''}
          </Text>
          {notice ? <Text style={styles.notice} accessibilityRole="alert">{notice}</Text> : null}
        </ScrollView>
        <View style={styles.footer}>
          <Pressable style={[styles.button, !canSave && styles.buttonDisabled]}
            onPress={() => void save()} disabled={!canSave} accessibilityRole="button"
            accessibilityLabel={target ? 'Save correction' : replacing ? 'Choose a saved fact first' : 'Save fact'}>
            <Text style={styles.buttonText}>{loading ? 'Loading…' : busy ? 'Saving…' : target ? 'Save correction' : replacing ? 'Choose a saved fact' : 'Save fact'}</Text>
          </Pressable>
        </View>
      </View>
    </KeyboardAvoidingView>
  </Modal>;
}

const makeStyles = (theme: Theme) => StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: '#000a', justifyContent: 'center', padding: 12 },
  sheet: { backgroundColor: theme.surfaceAlt, borderColor: theme.border, borderWidth: 1,
    borderRadius: 16, maxHeight: '90%', width: '100%' },
  body: { flexShrink: 1 },
  content: { padding: 16, gap: 10 },
  footer: { borderTopColor: theme.border, borderTopWidth: 1, padding: 12, alignItems: 'flex-end' },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  title: { color: theme.text, fontSize: 18, fontWeight: '700', flexShrink: 1 },
  close: { color: theme.accent, fontSize: 14, fontWeight: '600', paddingVertical: 8 },
  explanation: { color: theme.textDim, fontSize: 13, lineHeight: 19 },
  warning: { color: theme.warn, fontSize: 13 },
  fieldLabel: { color: theme.text, fontSize: 13, fontWeight: '600', marginTop: 2 },
  stores: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  store: { borderColor: theme.border, borderWidth: 1, borderRadius: 12, paddingHorizontal: 12, paddingVertical: 9 },
  storeSelected: { borderColor: theme.accent, backgroundColor: theme.userBubble },
  storeText: { color: theme.text, fontSize: 13 },
  link: { color: theme.accent, fontSize: 14, fontWeight: '600', minHeight: 44, textAlignVertical: 'center' },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 16 },
  choice: { borderColor: theme.border, borderWidth: 1, borderRadius: 12, padding: 12, minHeight: 44 },
  original: { maxHeight: 140, borderColor: theme.border, borderWidth: 1, borderRadius: 12,
    backgroundColor: theme.surface },
  originalContent: { padding: 12 },
  input: { minHeight: 90, maxHeight: 180, borderRadius: 12, borderWidth: 1, borderColor: theme.border,
    backgroundColor: theme.surface, color: theme.text, fontSize: 15, padding: 12 },
  count: { color: theme.textDim, fontSize: 12 },
  notice: { color: theme.text, fontSize: 13, lineHeight: 18 },
  button: { alignSelf: 'flex-end', backgroundColor: theme.accent, borderRadius: 20,
    minHeight: 44, justifyContent: 'center', paddingHorizontal: 18 },
  buttonDisabled: { backgroundColor: theme.accentDim, opacity: 0.6 },
  buttonText: { color: '#02121b', fontSize: 14, fontWeight: '700' },
});
