import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { ApiError, fetchSessions, resumeSession, type HistoryTurn, type SessionInfo } from '../api/client';
import { useServer } from '../context/ServerContext';
import { theme } from '../theme';

/** Lists the hub's recent sessions and resumes one into the chat thread. */
export function SessionsModal({
  visible,
  onClose,
  onResumed,
}: {
  visible: boolean;
  onClose: () => void;
  onResumed: (sessionId: string, turns: HistoryTurn[]) => void;
}) {
  const { config } = useServer();
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSessions(await fetchSessions(config));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load sessions');
    } finally {
      setLoading(false);
    }
  }, [config]);

  useEffect(() => {
    if (visible) load();
  }, [visible, load]);

  const resume = useCallback(
    async (id: string) => {
      setBusyId(id);
      setError(null);
      try {
        const res = await resumeSession(config, id);
        onResumed(res.session || id, res.turns || []);
        onClose();
      } catch (e) {
        setError(e instanceof ApiError ? e.message : 'Failed to resume session');
      } finally {
        setBusyId(null);
      }
    },
    [config, onResumed, onClose],
  );

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose}>
        <Pressable style={styles.sheet} onPress={() => {}}>
          <View style={styles.header}>
            <Text style={styles.title}>Resume session</Text>
            <Pressable onPress={load} hitSlop={8}>
              <Text style={styles.refresh}>↻</Text>
            </Pressable>
          </View>

          {loading && <ActivityIndicator color={theme.accent} style={styles.spinner} />}
          {error && <Text style={styles.error}>{error}</Text>}

          <FlatList
            data={sessions}
            keyExtractor={(s) => s.id}
            style={styles.list}
            renderItem={({ item }) => (
              <Pressable style={styles.option} onPress={() => resume(item.id)} disabled={!!busyId}>
                <View style={styles.optInfo}>
                  <Text style={styles.optTitle} numberOfLines={1}>
                    {item.summary?.trim() || item.id}
                  </Text>
                  <Text style={styles.optMeta} numberOfLines={1}>
                    {[
                      item.agent_id,
                      item.turn_count != null ? `${item.turn_count} turns` : null,
                      formatDate(item.started_at),
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </Text>
                </View>
                {busyId === item.id && <ActivityIndicator color={theme.accent} size="small" />}
              </Pressable>
            )}
            ListEmptyComponent={
              !loading && !error ? <Text style={styles.empty}>No saved sessions</Text> : null
            }
          />
        </Pressable>
      </Pressable>
    </Modal>
  );
}

function formatDate(iso?: string): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  return d.toLocaleString();
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: '#000a', justifyContent: 'center', padding: 24 },
  sheet: {
    backgroundColor: theme.surfaceAlt,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: theme.border,
    padding: 16,
    maxHeight: '80%',
  },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  title: { color: theme.text, fontSize: 16, fontWeight: '700' },
  refresh: { color: theme.accent, fontSize: 20 },
  spinner: { marginVertical: 16 },
  error: { color: theme.danger, fontSize: 13, marginVertical: 8 },
  list: { flexGrow: 0 },
  option: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
  },
  optInfo: { flex: 1, paddingRight: 10 },
  optTitle: { color: theme.text, fontSize: 15, fontWeight: '600' },
  optMeta: { color: theme.textDim, fontSize: 12, marginTop: 2 },
  empty: { color: theme.textDim, fontSize: 14, textAlign: 'center', paddingVertical: 24 },
});
