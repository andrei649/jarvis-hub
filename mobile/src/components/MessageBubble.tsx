import React from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { theme } from '../theme';

export type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  /** assistant message still streaming */
  pending?: boolean;
};

export function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user';
  const empty = message.pending && message.text.length === 0;
  return (
    <View style={[styles.row, isUser ? styles.rowUser : styles.rowAssistant]}>
      <View style={[styles.bubble, isUser ? styles.user : styles.assistant]}>
        {empty ? (
          <ActivityIndicator color={theme.accent} size="small" />
        ) : (
          <Text style={styles.text}>{message.text}</Text>
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
    maxWidth: '85%',
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
  text: { color: theme.text, fontSize: 15, lineHeight: 21 },
});
