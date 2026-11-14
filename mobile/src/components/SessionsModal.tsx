import { Text } from './ThemedText';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Modal, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { ApiError, fetchSessionTranscript, fetchSessions, resumeSession, resumeTarget, type HistoryTurn, type SessionInfo, type SessionTranscript } from '../api/client';
import { projectSessionTranscript } from '../api/sessionTranscript';
import { useServer } from '../context/ServerContext';
import { useThemeStyles, type Theme } from '../theme';

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
  const { theme, styles } = useThemeStyles(makeStyles);
  const { config, connectionEpoch } = useServer();
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const epoch = useRef(0);

  const [preview, setPreview] = useState<{ document: SessionTranscript; request: number } | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [transcriptError, setTranscriptError] = useState<string | null>(null);
  const transcriptEpoch = useRef(0);
  const transcriptScope = useRef({ config, connectionEpoch });
  const scope = useRef({ config, connectionEpoch, visible });
  scope.current = { config, connectionEpoch, visible };
  const clearTranscript = useCallback(() => {
    ++transcriptEpoch.current;
    setPreview(null);
    setPreviewId(null);
    setTranscriptError(null);
  }, []);
  const transcriptCurrent = useCallback((request: number) => transcriptEpoch.current === request
    && transcriptScope.current.config === config && transcriptScope.current.connectionEpoch === connectionEpoch
    && scope.current.visible && scope.current.config === config
    && scope.current.connectionEpoch === connectionEpoch, [config, connectionEpoch]);
  const close = useCallback(() => { clearTranscript(); ++epoch.current; onClose(); }, [clearTranscript, onClose]);

  const previewTranscript = useCallback(async (id: string) => {
    if (!visible || busyId || loading || scope.current.config !== config
      || scope.current.connectionEpoch !== connectionEpoch) return;
    clearTranscript();
    const request = transcriptEpoch.current;
    transcriptScope.current = { config, connectionEpoch };
    setPreviewId(id);
    try {
      const document = await fetchSessionTranscript(config, id);
      if (!transcriptCurrent(request)) return;
      setPreview({ document: projectSessionTranscript(document, id), request });
    } catch {
      if (!transcriptCurrent(request)) return;
      clearTranscript();
      setTranscriptError('Could not load retained session transcript.');
    } finally {
      if (transcriptCurrent(request)) setPreviewId(null);
    }
  }, [config, connectionEpoch, visible, busyId, loading, clearTranscript, transcriptCurrent]);

  const load = useCallback(async () => {
    clearTranscript();
    const request = ++epoch.current;
    setLoading(true);
    setError(null);
    try {
      const result = await fetchSessions(config);
      if (epoch.current === request) setSessions(result);
    } catch (e) {
      if (epoch.current === request) setError(e instanceof ApiError ? e.message : 'Failed to load sessions');
    } finally {
      if (epoch.current === request) setLoading(false);
    }
  }, [config, clearTranscript]);

  useEffect(() => {
    clearTranscript();
    setSessions([]);
    setBusyId(null);
    if (visible) load();
    return () => { ++epoch.current; ++transcriptEpoch.current; };
  }, [visible, load, connectionEpoch, clearTranscript]);

  const resume = useCallback(
    async (id: string) => {
      clearTranscript();
      const request = ++epoch.current;
      setBusyId(id);
      setError(null);
      try {
        const res = await resumeSession(config, id);
        if (epoch.current !== request) return;
        if (!res.ok || res.session !== id || !Array.isArray(res.turns)) {
          throw new ApiError('The hub did not resume the selected session');
        }
        onResumed(res.session || id, res.turns || []);
        close();
      } catch (e) {
        if (epoch.current === request) setError(e instanceof ApiError ? e.message : 'Failed to resume session');
      } finally {
        if (epoch.current === request) setBusyId(null);
      }
    },
    [config, onResumed, close, clearTranscript],
  );

  const currentPreview = preview && transcriptCurrent(preview.request) ? preview.document : null;

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={close}>
      <Pressable style={styles.backdrop} onPress={close}>
        <Pressable style={styles.sheet} onPress={() => {}}>
          <View style={styles.header}>
            <Text style={styles.title}>Resume session</Text>
            <Pressable onPress={load} hitSlop={8} disabled={!!busyId} accessibilityRole="button" accessibilityLabel="Refresh recent sessions">
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
              // H440: one row per conversation; a resume opens the newest member of its lineage.
              <View style={styles.option}><Pressable style={styles.optInfo} onPress={() => resume(resumeTarget(item))} disabled={!!busyId || loading}>
                <View>
                  <Text style={styles.optTitle} numberOfLines={1}>
                    {item.title?.trim() || item.summary?.trim() || item.id}
                  </Text>
                  <Text style={styles.optMeta} numberOfLines={1}>
                    {[
                      item.agent_id,
                      item.turn_count != null ? `${item.turn_count} turns` : null,
                      item.continuations ? `+${item.continuations} other in this conversation` : null,
                      formatDate(item.started_at),
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </Text>
                </View>
                {busyId === resumeTarget(item) && <ActivityIndicator color={theme.accent} size="small" />}
              </Pressable>
                <Pressable onPress={() => previewTranscript(item.id)} disabled={!!busyId || loading}
                  accessibilityRole="button" accessibilityLabel={`Preview transcript for ${item.id}`}>
                  <Text style={styles.previewAction}>Preview transcript</Text>
                </Pressable>
              </View>
            )}
            ListEmptyComponent={
              !loading && !error ? <Text style={styles.empty}>No saved sessions</Text> : undefined
            }
          />
          {previewId && <View>
            <ActivityIndicator color={theme.accent} accessibilityLabel="Loading transcript preview" />
            <Pressable onPress={clearTranscript} accessibilityRole="button" accessibilityLabel="Close transcript preview">
              <Text style={styles.previewAction}>Close preview</Text>
            </Pressable>
          </View>}
          {transcriptError && <Text style={styles.error}>{transcriptError}</Text>}
          {currentPreview && <View>
            <View style={styles.header}>
              <Text style={styles.title}>Retained transcript</Text>
              <Pressable onPress={clearTranscript} accessibilityRole="button" accessibilityLabel="Close transcript preview">
                <Text style={styles.previewAction}>Close preview</Text>
              </Pressable>
            </View>
            <Text style={styles.optMeta}>Current retained user and assistant text only; automatic secret redaction applied. Compacted archives, tool results, media and system messages are excluded. This is not a complete conversation archive.</Text>
            <ScrollView style={styles.transcriptScroll} nestedScrollEnabled>
              {currentPreview.turns.length === 0 ? <Text style={styles.optMeta}>No retained text turns.</Text>
                : currentPreview.turns.map((turn, index) => <View key={index} style={styles.transcriptTurn}>
                  <Text style={styles.optMeta}>{turn.role}{turn.agent_id ? ` · ${turn.agent_id}` : ''}{turn.timestamp ? ` · ${turn.timestamp}` : ''}</Text>
                  <Text selectable style={styles.transcriptText}>{turn.content}</Text>
                </View>)}
            </ScrollView>
          </View>}
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

const makeStyles = (theme: Theme) => StyleSheet.create({
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
  previewAction: { color: theme.accent, fontSize: 12, padding: 6 },
  transcriptScroll: { maxHeight: 220, flexShrink: 1, marginVertical: 8 },
  transcriptTurn: { paddingVertical: 8 },
  transcriptText: { color: theme.text, fontSize: 13 },
  empty: { color: theme.textDim, fontSize: 14, textAlign: 'center', paddingVertical: 24 },
});
