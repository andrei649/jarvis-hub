import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import {
  ApiError,
  fetchChannelInbox,
  fetchChannelThread,
  sendChannelReply,
  type ChannelInboxMessage,
  type ChannelInboxThread,
} from '../api/client';
import { useServer } from '../context/ServerContext';
import { theme } from '../theme';

function timeLabel(ts?: number): string {
  if (!ts) return '';
  const date = new Date(ts * 1000);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function threadTitle(thread: ChannelInboxThread): string {
  return thread.from || thread.sender || thread.channel || 'channel';
}

function threadMeta(thread: ChannelInboxThread): string {
  const parts = [thread.channel || 'channel', `${thread.count ?? 0} msg`];
  const stamp = timeLabel(thread.ts);
  if (stamp) parts.push(stamp);
  return parts.join(' · ');
}

function messageAuthor(message: ChannelInboxMessage): string {
  if (message.direction === 'out') return 'Jarvis';
  return message.sender || message.channel || 'Sender';
}

function EmptyState({ onGoToSettings }: { onGoToSettings: () => void }) {
  return (
    <View style={styles.empty}>
      <Text style={styles.emptyTitle}>No hub connected</Text>
      <Text style={styles.emptyBody}>Connect this phone to your Jarvis hub before reading live channel threads.</Text>
      <Pressable style={styles.cta} onPress={onGoToSettings}>
        <Text style={styles.ctaText}>Open Settings</Text>
      </Pressable>
    </View>
  );
}

function ThreadRow({
  thread,
  selected,
  onPress,
}: {
  thread: ChannelInboxThread;
  selected: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable style={[styles.threadRow, selected && styles.threadRowSelected]} onPress={onPress}>
      <View style={styles.threadTop}>
        <Text style={styles.threadTitle} numberOfLines={1}>
          {threadTitle(thread)}
        </Text>
        {thread.unread && <View style={styles.unreadDot} />}
      </View>
      <Text style={styles.threadMeta} numberOfLines={1}>
        {threadMeta(thread)}
      </Text>
      <Text style={styles.preview} numberOfLines={2}>
        {thread.preview || 'No preview'}
      </Text>
    </Pressable>
  );
}

function MessageRow({ message }: { message: ChannelInboxMessage }) {
  const outbound = message.direction === 'out';
  return (
    <View style={[styles.messageRow, outbound && styles.messageRowOut]}>
      <View style={[styles.messageBubble, outbound && styles.messageBubbleOut]}>
        <Text style={styles.messageMeta}>
          {messageAuthor(message)}
          {timeLabel(message.ts) ? ` · ${timeLabel(message.ts)}` : ''}
        </Text>
        <Text style={styles.messageText}>{message.text || message.preview || ''}</Text>
      </View>
    </View>
  );
}

export function CommsScreen({ onGoToSettings }: { onGoToSettings: () => void }) {
  const { config, configured } = useServer();
  const [threads, setThreads] = useState<ChannelInboxThread[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedThread, setSelectedThread] = useState<ChannelInboxThread | undefined>();
  const [messages, setMessages] = useState<ChannelInboxMessage[]>([]);
  const [reply, setReply] = useState('');
  const [loadingInbox, setLoadingInbox] = useState(false);
  const [loadingThread, setLoadingThread] = useState(false);
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadInbox = useCallback(async () => {
    if (!configured) return;
    setLoadingInbox(true);
    setError(null);
    try {
      const inbox = await fetchChannelInbox(config);
      setThreads(inbox.threads);
      setSelectedId((current) => {
        if (current && inbox.threads.some((thread) => thread.thread_id === current)) return current;
        return inbox.threads[0]?.thread_id ?? null;
      });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load channel inbox');
      setThreads([]);
      setSelectedId(null);
    } finally {
      setLoadingInbox(false);
    }
  }, [config, configured]);

  const loadThread = useCallback(
    async (threadId: string) => {
      if (!configured) return;
      setLoadingThread(true);
      setError(null);
      try {
        const out = await fetchChannelThread(config, threadId);
        setSelectedThread(out.thread);
        setMessages(out.messages);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : 'Failed to load channel thread');
        setSelectedThread(undefined);
        setMessages([]);
      } finally {
        setLoadingThread(false);
      }
    },
    [config, configured],
  );

  useEffect(() => {
    loadInbox();
  }, [loadInbox]);

  useEffect(() => {
    if (selectedId) {
      loadThread(selectedId);
    } else {
      setSelectedThread(undefined);
      setMessages([]);
    }
  }, [loadThread, selectedId]);

  const sendReply = useCallback(async () => {
    const text = reply.trim();
    if (!selectedId || !text || sending) return;
    setSending(true);
    setError(null);
    setNotice(null);
    try {
      const result = await sendChannelReply(config, selectedId, text);
      if (result.ok && result.queued) {
        setNotice(`Queued for approval${result.task_id ? ` #${result.task_id}` : ''}`);
      } else if (result.ok) {
        setNotice('Reply request accepted');
      } else {
        setNotice(result.reason || result.error || 'Reply was not queued');
      }
      setReply('');
      await loadThread(selectedId);
      await loadInbox();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to queue reply');
    } finally {
      setSending(false);
    }
  }, [config, loadInbox, loadThread, reply, selectedId, sending]);

  if (!configured) return <EmptyState onGoToSettings={onGoToSettings} />;

  return (
    <ScrollView
      style={styles.flex}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={loadingInbox} onRefresh={loadInbox} tintColor={theme.accent} />}
    >
      <View style={styles.summary}>
        <Text style={styles.summaryValue}>{threads.length}</Text>
        <Text style={styles.summaryLabel}>live threads</Text>
      </View>

      {error && (
        <View style={styles.errorBox}>
          <Text style={styles.errorText}>{error}</Text>
        </View>
      )}

      {notice && (
        <View style={styles.noticeBox}>
          <Text style={styles.noticeText}>{notice}</Text>
        </View>
      )}

      {loadingInbox && threads.length === 0 && (
        <View style={styles.loading}>
          <ActivityIndicator color={theme.accent} />
        </View>
      )}

      {threads.map((thread) => (
        <ThreadRow
          key={thread.thread_id}
          thread={thread}
          selected={thread.thread_id === selectedId}
          onPress={() => setSelectedId(thread.thread_id)}
        />
      ))}

      {!loadingInbox && threads.length === 0 && !error && (
        <View style={styles.clearBox}>
          <Text style={styles.clearTitle}>No live inbox yet</Text>
          <Text style={styles.clearText}>Telegram and web messages appear here after sender pairing allows them.</Text>
        </View>
      )}

      {selectedId && (
        <View style={styles.threadPanel}>
          <View style={styles.panelTop}>
            <View style={styles.panelTitleWrap}>
              <Text style={styles.panelTitle}>{selectedThread ? threadTitle(selectedThread) : 'Thread'}</Text>
              <Text style={styles.panelMeta}>{selectedThread ? threadMeta(selectedThread) : selectedId}</Text>
            </View>
            {loadingThread && <ActivityIndicator color={theme.accent} />}
          </View>

          {messages.map((message) => (
            <MessageRow key={message.id} message={message} />
          ))}

          {!loadingThread && messages.length === 0 && (
            <Text style={styles.noMessages}>No messages loaded for this thread.</Text>
          )}

          <TextInput
            style={styles.replyInput}
            value={reply}
            onChangeText={setReply}
            placeholder="Draft a governed reply"
            placeholderTextColor={theme.textDim}
            multiline
            maxLength={4000}
          />
          <Pressable
            style={[styles.sendButton, (!reply.trim() || sending) && styles.sendButtonDisabled]}
            disabled={!reply.trim() || sending}
            onPress={sendReply}
          >
            <Text style={styles.sendButtonText}>{sending ? 'Queueing...' : 'Queue Reply'}</Text>
          </Pressable>
        </View>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { padding: 12, paddingBottom: 24 },
  summary: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 8,
    marginBottom: 12,
  },
  summaryValue: { color: theme.accent, fontSize: 28, fontWeight: '800' },
  summaryLabel: { color: theme.textDim, fontSize: 13, fontWeight: '700', textTransform: 'uppercase' },
  threadRow: {
    backgroundColor: theme.surface,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: theme.border,
    padding: 14,
    marginBottom: 10,
  },
  threadRowSelected: {
    borderColor: theme.accent,
    backgroundColor: theme.surfaceAlt,
  },
  threadTop: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  threadTitle: { flex: 1, color: theme.text, fontSize: 16, fontWeight: '800' },
  unreadDot: { width: 9, height: 9, borderRadius: 5, backgroundColor: theme.accent },
  threadMeta: { color: theme.textDim, fontSize: 12, marginTop: 4 },
  preview: { color: theme.text, fontSize: 14, lineHeight: 19, marginTop: 8 },
  threadPanel: {
    marginTop: 4,
    backgroundColor: theme.surface,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: theme.border,
    padding: 14,
  },
  panelTop: { flexDirection: 'row', alignItems: 'center', gap: 12, marginBottom: 12 },
  panelTitleWrap: { flex: 1 },
  panelTitle: { color: theme.accent, fontSize: 16, fontWeight: '800' },
  panelMeta: { color: theme.textDim, fontSize: 12, marginTop: 3 },
  messageRow: { alignItems: 'flex-start', marginBottom: 10 },
  messageRowOut: { alignItems: 'flex-end' },
  messageBubble: {
    maxWidth: '88%',
    backgroundColor: theme.surfaceAlt,
    borderRadius: 13,
    borderWidth: 1,
    borderColor: theme.border,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  messageBubbleOut: {
    backgroundColor: theme.userBubble,
    borderColor: theme.accentDim,
  },
  messageMeta: { color: theme.textDim, fontSize: 11, marginBottom: 4 },
  messageText: { color: theme.text, fontSize: 14, lineHeight: 20 },
  noMessages: { color: theme.textDim, fontSize: 13, marginBottom: 12 },
  replyInput: {
    minHeight: 86,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.surfaceAlt,
    color: theme.text,
    fontSize: 15,
    lineHeight: 21,
    paddingHorizontal: 12,
    paddingVertical: 10,
    textAlignVertical: 'top',
  },
  sendButton: {
    marginTop: 10,
    minHeight: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: theme.accent,
  },
  sendButtonDisabled: { opacity: 0.45 },
  sendButtonText: { color: '#02121b', fontSize: 15, fontWeight: '800' },
  errorBox: {
    backgroundColor: '#2a0d16',
    borderColor: theme.danger,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
  },
  errorText: { color: theme.danger, fontSize: 14 },
  noticeBox: {
    backgroundColor: '#06291d',
    borderColor: theme.ok,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
  },
  noticeText: { color: theme.ok, fontSize: 14, fontWeight: '700' },
  loading: { alignItems: 'center', padding: 24 },
  clearBox: {
    alignItems: 'center',
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 14,
    padding: 28,
    backgroundColor: theme.surface,
  },
  clearTitle: { color: theme.ok, fontSize: 20, fontWeight: '800', marginBottom: 6 },
  clearText: { color: theme.textDim, fontSize: 14, textAlign: 'center' },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  emptyTitle: { color: theme.text, fontSize: 20, fontWeight: '700', marginBottom: 8 },
  emptyBody: { color: theme.textDim, fontSize: 15, textAlign: 'center', marginBottom: 24 },
  cta: { paddingHorizontal: 24, paddingVertical: 12, borderRadius: 24, backgroundColor: theme.accent },
  ctaText: { color: '#02121b', fontWeight: '700', fontSize: 15 },
});
