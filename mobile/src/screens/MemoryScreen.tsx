import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { ApiError, fetchMemory, fetchNotes, type MemoryResponse, type MemoryTurn, type NotesResponse } from '../api/client';
import { useServer } from '../context/ServerContext';
import { theme } from '../theme';

function EmptyState({ onGoToSettings }: { onGoToSettings: () => void }) {
  return (
    <View style={styles.empty}>
      <Text style={styles.emptyTitle}>No hub connected</Text>
      <Text style={styles.emptyBody}>Connect this phone to your Jarvis hub before viewing memory and notes.</Text>
      <Pressable style={styles.cta} onPress={onGoToSettings}>
        <Text style={styles.ctaText}>Open Settings</Text>
      </Pressable>
    </View>
  );
}

function timeLabel(value?: unknown): string {
  if (!value) return '';
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function roleColor(role: string): string {
  const key = role.toLowerCase();
  if (key === 'user') return theme.accent;
  if (key === 'assistant') return theme.ok;
  if (key === 'system') return theme.warn;
  return theme.textDim;
}

function SummaryCell({ label, value }: { label: string; value: string | number }) {
  return (
    <View style={styles.summaryCell}>
      <Text style={styles.summaryValue}>{value}</Text>
      <Text style={styles.summaryLabel}>{label}</Text>
    </View>
  );
}

function TurnCard({ turn }: { turn: MemoryTurn }) {
  const stamp = timeLabel(turn.timestamp);
  const role = turn.role || 'turn';
  return (
    <View style={styles.card}>
      <View style={styles.cardTop}>
        <Text style={[styles.role, { color: roleColor(role) }]}>{role}</Text>
        {turn.agent_id ? <Text style={styles.agent}>{turn.agent_id}</Text> : null}
        {stamp ? <Text style={styles.stamp}>{stamp}</Text> : null}
      </View>
      <Text style={styles.contentText} numberOfLines={5}>
        {turn.content || 'Empty turn'}
      </Text>
    </View>
  );
}

function NotesCard({ notes }: { notes: NotesResponse | null }) {
  const content = notes?.content?.trim() ?? '';
  return (
    <View style={styles.card}>
      <View style={styles.cardTop}>
        <Text style={styles.sectionTitle}>Session Notes</Text>
        {notes?.session ? <Text style={styles.stamp}>{notes.session}</Text> : null}
      </View>
      {content ? (
        <Text style={styles.contentText}>{content}</Text>
      ) : (
        <Text style={styles.emptyText}>No session notes returned by the hub.</Text>
      )}
    </View>
  );
}

export function MemoryScreen({ onGoToSettings }: { onGoToSettings: () => void }) {
  const { config, configured } = useServer();
  const [memory, setMemory] = useState<MemoryResponse | null>(null);
  const [notes, setNotes] = useState<NotesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!configured) return;
    setLoading(true);
    setError(null);
    try {
      const [memoryResult, notesResult] = await Promise.allSettled([fetchMemory(config), fetchNotes(config)]);
      if (memoryResult.status === 'fulfilled') {
        setMemory(memoryResult.value);
      } else {
        const err = memoryResult.reason;
        setMemory({ turns: [] });
        setError(err instanceof ApiError ? err.message : 'Failed to load memory');
      }
      setNotes(notesResult.status === 'fulfilled' ? notesResult.value : { content: '' });
    } finally {
      setLoading(false);
    }
  }, [config, configured]);

  useEffect(() => {
    load();
  }, [load]);

  const turns = memory?.turns ?? [];
  const summary = useMemo(() => {
    const noteChars = notes?.content?.length ?? 0;
    const session = memory?.session || notes?.session || 'current';
    return { noteChars, session };
  }, [memory?.session, notes?.content, notes?.session]);

  if (!configured) return <EmptyState onGoToSettings={onGoToSettings} />;

  return (
    <ScrollView
      style={styles.flex}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.accent} />}
    >
      <View style={styles.summary}>
        <SummaryCell label="turns" value={turns.length} />
        <SummaryCell label="notes chars" value={summary.noteChars} />
        <SummaryCell label="session" value={summary.session.slice(0, 10)} />
      </View>

      {error && (
        <View style={styles.errorBox}>
          <Text style={styles.errorText}>{error}</Text>
        </View>
      )}

      {loading && turns.length === 0 && (
        <View style={styles.loading}>
          <ActivityIndicator color={theme.accent} />
        </View>
      )}

      <NotesCard notes={notes} />

      <View style={styles.sectionHeader}>
        <Text style={styles.sectionTitle}>Recent Turns</Text>
      </View>

      {turns.map((turn, index) => (
        <TurnCard key={`${turn.role}-${turn.timestamp || index}`} turn={turn} />
      ))}

      {!loading && turns.length === 0 && !error && (
        <View style={styles.clearBox}>
          <Text style={styles.clearTitle}>No recent turns</Text>
          <Text style={styles.clearText}>The hub returned an empty memory history for this session.</Text>
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
    gap: 8,
    marginBottom: 12,
  },
  summaryCell: {
    flex: 1,
    backgroundColor: theme.surface,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: theme.border,
    paddingHorizontal: 10,
    paddingVertical: 10,
  },
  summaryValue: { color: theme.accent, fontSize: 16, fontWeight: '800' },
  summaryLabel: { color: theme.textDim, fontSize: 10, marginTop: 2, textTransform: 'uppercase' },
  sectionHeader: { paddingHorizontal: 2, paddingVertical: 8 },
  sectionTitle: { color: theme.accent, fontSize: 12, fontWeight: '800', textTransform: 'uppercase' },
  card: {
    backgroundColor: theme.surface,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: theme.border,
    padding: 14,
    marginBottom: 12,
  },
  cardTop: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 8 },
  role: { fontSize: 12, fontWeight: '800', textTransform: 'uppercase' },
  agent: { color: theme.textDim, fontSize: 12, fontWeight: '700' },
  stamp: { color: theme.textDim, fontSize: 11, marginLeft: 'auto', maxWidth: 140, textAlign: 'right' },
  contentText: { color: theme.text, fontSize: 14, lineHeight: 20 },
  emptyText: { color: theme.textDim, fontSize: 14, lineHeight: 20 },
  errorBox: {
    backgroundColor: '#2a0d16',
    borderColor: theme.danger,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
  },
  errorText: { color: theme.danger, fontSize: 14 },
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
