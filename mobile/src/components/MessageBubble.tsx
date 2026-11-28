import { Text } from './ThemedText';
import React from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';
import type { ChatMessage, SaveState } from '../chat/types';
import { recallLines } from '../chat/turnOutcome';
import { Markdown } from '../markdown/Markdown';
import { useThemeStyles, type Theme } from '../theme';

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
  onSaveNote,
  savedNotePath,
  onRemember,
}: {
  message: ChatMessage;
  onSpeak?: (text: string) => void;
  speaking?: boolean;
  onSave?: () => void;
  saveState?: SaveState;
  onSaveNote?: () => void;
  savedNotePath?: string;
  onRemember?: () => void;
}) {
  const { theme, styles } = useThemeStyles(makeStyles);
  const isUser = message.role === 'user';
  const empty = message.pending && message.text.length === 0;
  const canSpeak = !isUser && !message.pending && message.text.length > 0 && !!onSpeak;
  // Explicit save-to-artifacts: only completed, non-error assistant replies,
  // never while streaming, and only when the screen opts in — never automatic.
  const canSave = !isUser && !message.pending && !message.error && message.text.length > 0 && !!onSave;
  const canRemember = isUser && !message.pending && !message.error && !!message.text.trim() && !!onRemember;
  const canSaveNote = !isUser && message.completed === true && !message.pending && !message.error
    && !!message.text.trim() && !!onSaveNote;
  const modelCalls = !isUser && !message.pending && !message.error && message.text.length > 0
    ? message.modelCalls : undefined;
  const activity = !isUser && message.completed && !message.pending && !message.error ? message.toolActivity : undefined;
  const recalls = !isUser && message.completed && !message.pending && !message.error && message.recall?.length
    ? recallLines(message.recall) : [];

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
        {isUser && message.historySource && <Text style={styles.modelCall}>
          {`Chat source: ${message.historySource.session_id} · message ${message.historySource.turn + 1} · ${message.historySource.role}`}
        </Text>}
        {recalls.length > 0 && (
          <View style={styles.recallList} accessibilityLabel="Memory recall">
            {recalls.map((line, idx) => (
              <Text key={`${idx}-${line}`} style={styles.modelCall}>{line}</Text>
            ))}
          </View>
        )}
        {activity && <Text style={styles.modelCall}>
          Agent tool calls recorded: {activity.executed ?? 'unknown'}
          {activity.proposed > 0 ? ` · Proposed: ${activity.proposed}` : ''}
          {activity.queued > 0 ? ` · Queued: ${activity.queued}` : ''}
          {activity.failures === null ? ' · Failures: unknown' : activity.failures > 0 ? ` · Failed: ${activity.failures}` : ''}
        </Text>}
        {modelCalls?.length ? (
          <View style={styles.modelCalls}>
            <Text style={styles.modelCallsTitle}>Models called</Text>
            {modelCalls.map(call => (
              <Text key={JSON.stringify([call.provider, call.model])} style={styles.modelCall}
                accessibilityLabel={`Provider ${call.provider}, model ${call.model}`}>
                {call.provider} · {call.model}
              </Text>
            ))}
          </View>
        ) : null}
        {(canSpeak || canSave || canRemember || canSaveNote) && (
          <View style={styles.actions}>
            {canRemember && (
              <Pressable style={[styles.savePill, styles.rememberPill]} onPress={onRemember} hitSlop={8}
                accessibilityRole="button" accessibilityLabel="Remember message">
                <Text style={styles.saveText}>Remember message</Text>
              </Pressable>
            )}
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
            {canSaveNote && (
              <Pressable style={[styles.savePill, styles.rememberPill]} onPress={onSaveNote} hitSlop={8}
                accessibilityRole="button" accessibilityLabel={savedNotePath ? 'Open saved Obsidian note' : 'Save to Obsidian'}>
                <Text style={styles.saveText}>{savedNotePath ? 'Open saved note' : 'Save to Obsidian'}</Text>
              </Pressable>
            )}
          </View>
        )}
      </View>
    </View>
  );
}

const makeStyles = (theme: Theme) => StyleSheet.create({
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
  recallList: { marginTop: 6, gap: 2 },
  modelCalls: { borderTopWidth: 1, borderTopColor: theme.border, marginTop: 10, paddingTop: 7, gap: 3 },
  modelCallsTitle: { color: theme.textDim, fontSize: 11, fontWeight: '600' },
  modelCall: { color: theme.textDim, fontSize: 12, lineHeight: 17, flexShrink: 1 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 12, marginTop: 6 },
  speak: { alignSelf: 'flex-start' },
  speakIcon: { fontSize: 14, color: theme.textDim },
  savePill: {
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 10,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  rememberPill: { minHeight: 44, justifyContent: 'center' },
  saveText: { fontSize: 11, color: theme.textDim },
  saveOk: { color: theme.ok },
  saveErr: { color: theme.warn },
});
