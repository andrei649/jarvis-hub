import React, { useEffect, useState } from 'react';
import { Linking, Modal, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { readSavedChatNote, type ChatNoteReceipt, type ChatNoteTarget } from '../api/chatNote';
import { ApiError } from '../api/client';
import { Markdown } from '../markdown/Markdown';
import type { ServerConfig } from '../storage/settings';
import { useThemeStyles, type Theme } from '../theme';
import { Text } from './ThemedText';

type SavedVaultNoteProps = {
  config: ServerConfig; target: ChatNoteTarget; receipt: ChatNoteReceipt; onClose: () => void;
};

export function SavedVaultNoteViewer(props: SavedVaultNoteProps) {
  return <Modal visible transparent animationType="fade" onRequestClose={props.onClose}>
    <SavedVaultNoteContent {...props} />
  </Modal>;
}

export function SavedVaultNoteContent({ config, target, receipt, onClose }: SavedVaultNoteProps) {
  const { styles } = useThemeStyles(makeStyles);
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{ config: ServerConfig; target: ChatNoteTarget; receipt: ChatNoteReceipt;
    attempt: number; body?: string; error?: string } | null>(null);
  const [openError, setOpenError] = useState(false);
  const [showSource, setShowSource] = useState(false);
  const current = result?.config === config && result.target === target && result.receipt === receipt
    && result.attempt === attempt ? result : null;

  useEffect(() => {
    let active = true;
    setOpenError(false);
    setShowSource(false);
    void readSavedChatNote(config, target, receipt).then(body => {
      if (active) setResult({ config, target, receipt, attempt, body });
    }).catch(error => {
      if (!active) return;
      const status = error instanceof ApiError ? error.status : undefined;
      const message = status === 404 || status === 409 ? 'This note is unavailable in the original vault inbox.'
        : status === 413 ? 'This note is too large for the chat reader.'
        : status === 401 || status === 403 ? 'Check your hub credentials to read this note.'
        : 'Could not read the note from the hub.';
      setResult({ config, target, receipt, attempt, error: message });
    });
    return () => { active = false; };
  }, [config, target, receipt, attempt]);

  const source = receipt.source;
  const body = current?.body;
  // Very long notes stay selectable without building a native view per Markdown span.
  const canFormat = !!body && body.length <= 12_000;
  return <View style={styles.backdrop}>
      <View style={styles.sheet} accessibilityViewIsModal>
        <View style={styles.header}>
          <Text style={styles.title} accessibilityRole="header">{receipt.relPath.split('/').pop()?.slice(0, -3)}</Text>
          <Pressable accessibilityRole="button" accessibilityLabel="Close saved note" onPress={onClose} style={styles.action}>
            <Text style={styles.link}>Close</Text>
          </Pressable>
        </View>
        <Text style={styles.path} selectable>{target.vault} / {receipt.relPath}</Text>
        <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
          {body !== undefined
            ? canFormat && !showSource ? <Markdown text={body} interactiveLinks={false} />
              : <Text selectable style={styles.body}>{body || 'This note is empty.'}</Text>
            : <Text accessibilityLiveRegion="polite" style={styles.body}>{current?.error || 'Reading from the hub…'}</Text>}
        </ScrollView>
        {current?.error && <Pressable accessibilityRole="button" style={styles.action} onPress={() => setAttempt(n => n + 1)}>
          <Text style={styles.link}>Try again</Text>
        </Pressable>}
        {canFormat && <Pressable accessibilityRole="button" style={styles.action} onPress={() => setShowSource(value => !value)}>
          <Text style={styles.link}>{showSource ? 'Show formatted note' : 'Show Markdown'}</Text>
        </Pressable>}
        {body !== undefined && source && <Pressable accessibilityRole="button" style={styles.action}
          onPress={() => { setOpenError(false); void Linking.openURL('obsidian://open?vault=' + encodeURIComponent(source.vault)
            + '&file=' + encodeURIComponent(source.file)).catch(() => setOpenError(true)); }}>
          <Text style={styles.link}>Open in Obsidian on this device</Text>
        </Pressable>}
        {openError && <Text accessibilityRole="alert" style={styles.path}>Obsidian could not open this link on this device.</Text>}
      </View>
  </View>;
}

const makeStyles = (theme: Theme) => StyleSheet.create({
  backdrop: { flex: 1, justifyContent: 'center', backgroundColor: '#000a', padding: 12 },
  sheet: { backgroundColor: theme.surfaceAlt, borderColor: theme.border, borderWidth: 1, borderRadius: 16,
    maxHeight: '90%', width: '100%', padding: 16, gap: 8 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  title: { color: theme.text, fontSize: 18, fontWeight: '700', flexShrink: 1 },
  path: { color: theme.textDim, fontSize: 13, lineHeight: 18 },
  scroll: { flexShrink: 1 },
  content: { paddingVertical: 8 },
  body: { color: theme.text, fontSize: 16, lineHeight: 24 },
  action: { minHeight: 44, justifyContent: 'center', alignSelf: 'flex-start' },
  link: { color: theme.accent, fontSize: 15, fontWeight: '600' },
});
