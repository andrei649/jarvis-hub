import React from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import type { ChatMessage, SaveState } from '../chat/types';
import { Markdown } from '../markdown/Markdown';
import { theme } from '../theme';

export type { ChatMessage };

const SAVE_LABELS: Record<SaveState, string> = {
  saving: 'saving…',
  saved: '✓ saved',
  'saved-trunc': '✓ saved · truncated at 4,000',
  error: '⚠ save failed — retry',
};

export function MessageBubble({
  message,
  onSpeak,
  speaking,
  onSave,
  saveState,
}: {
  message: ChatMessage;
  onSpeak?: (text: string) => void;
  speaking?: boolean;
  onSave?: () => void;
  saveState?: SaveState;
}) {
  const isUser = message.role === 'user';
  const empty = message.pending && message.text.length === 0;
  const canSpeak = !isUser && !message.pending && message.text.length > 0 && !!onSpeak;
  // Explicit save-to-artifacts: only completed, non-error assistant replies,
  // never while streaming, and only when the screen opts in — never automatic.
  const canSave = !isUser && !message.pending && !message.error && message.text.length > 0 && !!onSave;

  return (
    <View style={[styles.row, isUser ? styles.rowUser : styles.rowAssistant]}>
      <View style={[styles.bubble, isUser ? styles.user : styles.assistant]}>
        {empty ? (
          <ActivityIndicator color={theme.accent} size="small" />
        ) : isUser ? (
          <Text style={styles.userText}>{message.text}</Text>
        ) : (
          <Markdown text={message.text} />
        )}
        {(canSpeak || canSave) && (
          <View style={styles.actions}>
            {canSpeak && (
              <Pressable
                style={styles.speak}
                onPress={() => onSpeak?.(message.text)}
                hitSlop={8}
                accessibilityLabel={speaking ? 'Stop speaking' : 'Speak message'}
              >
                <Text style={styles.speakIcon}>{speaking ? '◼' : '🔊'}</Text>
              </Pressable>
            )}
            {canSave && (
              <Pressable
                style={styles.savePill}
                onPress={onSave}
                disabled={saveState === 'saving' || saveState === 'saved' || saveState === 'saved-trunc'}
                hitSlop={8}
                accessibilityLabel="Save to artifacts"
              >
                <Text
                  style={[
                    styles.saveText,
                    (saveState === 'saved' || saveState === 'saved-trunc') && styles.saveOk,
                    saveState === 'error' && styles.saveErr,
                  ]}
                >
                  {saveState ? SAVE_LABELS[saveState] : '⬒ save'}
                </Text>
              </Pressable>
            )}
          </View>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { width: '100%', marginVertical: 4, flexDirection: 'row' },
  rowUser: { justifyContent: 'flex-end' },
  rowAssistant: { justifyContent: 'flex-start' },
  bubble: {
    maxWidth: '88%',
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderRadius: 16,
    borderWidth: 1,
  },
  user: {
    backgroundColor: theme.userBubble,
    borderColor: theme.accentDim,
    borderBottomRightRadius: 4,
  },
  assistant: {
    backgroundColor: theme.surface,
    borderColor: theme.border,
    borderBottomLeftRadius: 4,
  },
  userText: { color: theme.text, fontSize: 15, lineHeight: 21 },
  actions: { flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 6 },
  speak: { alignSelf: 'flex-start' },
  speakIcon: { fontSize: 14, color: theme.textDim },
  savePill: {
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 10,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  saveText: { fontSize: 11, color: theme.textDim },
  saveOk: { color: theme.ok },
  saveErr: { color: theme.warn },
});
