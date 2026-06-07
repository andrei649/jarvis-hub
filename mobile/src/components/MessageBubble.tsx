import React from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import type { ChatMessage } from '../chat/types';
import { Markdown } from '../markdown/Markdown';
import { theme } from '../theme';

export type { ChatMessage };

export function MessageBubble({
  message,
  onSpeak,
  speaking,
}: {
  message: ChatMessage;
  onSpeak?: (text: string) => void;
  speaking?: boolean;
}) {
  const isUser = message.role === 'user';
  const empty = message.pending && message.text.length === 0;
  const canSpeak = !isUser && !message.pending && message.text.length > 0 && !!onSpeak;

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
  speak: { marginTop: 6, alignSelf: 'flex-start' },
  speakIcon: { fontSize: 14, color: theme.textDim },
});
