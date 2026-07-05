import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { ApiError, fetchTasks, type HubTask } from '../api/client';
import { useServer } from '../context/ServerContext';
import { theme } from '../theme';

function taskState(task: HubTask): string {
  return String(task.state || task.status || 'done').toLowerCase();
}

function stateColor(state: string): string {
  if (state === 'running' || state === 'active') return theme.accent;
  if (['blocked', 'held', 'pending', 'proposed', 'approved'].includes(state)) return theme.warn;
  if (['error', 'failed', 'denied'].includes(state)) return theme.danger;
  return theme.ok;
}

function taskTitle(task: HubTask): string {
  return String(task.label || task.title || task.kind || `Task ${task.id ?? ''}`).trim();
}

function taskOwner(task: HubTask): string {
  return String(task.owner || task.agent_id || task.agent || 'jarvis');
}

function taskProject(task: HubTask): string {
  return String(task.project || task.kind || 'Autonomy');
}

function timeLabel(value?: unknown): string {
  if (!value) return '';
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function CountPill({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <View style={[styles.pill, { borderColor: color }]}>
      <Text style={[styles.pillValue, { color }]}>{value}</Text>
      <Text style={styles.pillLabel}>{label}</Text>
    </View>
  );
}

function EmptyState({ onGoToSettings }: { onGoToSettings: () => void }) {
  return (
    <View style={styles.empty}>
      <Text style={styles.emptyTitle}>No hub connected</Text>
      <Text style={styles.emptyBody}>Connect this phone to your Jarvis hub before viewing the live task board.</Text>
      <Pressable style={styles.cta} onPress={onGoToSettings}>
        <Text style={styles.ctaText}>Open Settings</Text>
      </Pressable>
    </View>
  );
}

function TaskCard({ task }: { task: HubTask }) {
  const state = taskState(task);
  const stamp = timeLabel(task.updated_at || task.created_at);
  return (
    <View style={styles.card}>
      <View style={styles.cardTop}>
        <View style={[styles.stateDot, { backgroundColor: stateColor(state) }]} />
        <View style={styles.cardTitleWrap}>
          <Text style={styles.cardTitle}>{taskTitle(task)}</Text>
          <Text style={styles.meta}>
            {taskOwner(task)} · {taskProject(task)}
          </Text>
        </View>
        <Text style={[styles.stateText, { color: stateColor(state) }]}>{state}</Text>
      </View>
      {stamp ? <Text style={styles.timestamp}>{stamp}</Text> : null}
    </View>
  );
}

export function TasksScreen({ onGoToSettings }: { onGoToSettings: () => void }) {
  const { config, configured } = useServer();
  const [tasks, setTasks] = useState<HubTask[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!configured) return;
    setLoading(true);
    setError(null);
    try {
      const out = await fetchTasks(config);
      setTasks(out.tasks);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load tasks');
      setTasks([]);
    } finally {
      setLoading(false);
    }
  }, [config, configured]);

  useEffect(() => {
    load();
  }, [load]);

  const counts = useMemo(() => {
    const active = tasks.filter((task) => ['running', 'active'].includes(taskState(task))).length;
    const waiting = tasks.filter((task) =>
      ['blocked', 'held', 'pending', 'proposed', 'approved'].includes(taskState(task)),
    ).length;
    const done = tasks.filter((task) => ['done', 'completed', 'success'].includes(taskState(task))).length;
    return { active, waiting, done };
  }, [tasks]);

  if (!configured) return <EmptyState onGoToSettings={onGoToSettings} />;

  return (
    <ScrollView
      style={styles.flex}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.accent} />}
    >
      <View style={styles.summary}>
        <CountPill label="active" value={counts.active} color={theme.accent} />
        <CountPill label="waiting" value={counts.waiting} color={theme.warn} />
        <CountPill label="done" value={counts.done} color={theme.ok} />
      </View>

      {error && (
        <View style={styles.errorBox}>
          <Text style={styles.errorText}>{error}</Text>
        </View>
      )}

      {loading && tasks.length === 0 && (
        <View style={styles.loading}>
          <ActivityIndicator color={theme.accent} />
        </View>
      )}

      {tasks.map((task, index) => (
        <TaskCard key={String(task.id ?? `${taskTitle(task)}-${index}`)} task={task} />
      ))}

      {!loading && tasks.length === 0 && !error && (
        <View style={styles.clearBox}>
          <Text style={styles.clearTitle}>No tasks right now</Text>
          <Text style={styles.clearText}>The hub returns an empty task board when there is no live autonomy work.</Text>
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
  pill: {
    flex: 1,
    backgroundColor: theme.surface,
    borderRadius: 14,
    borderWidth: 1,
    paddingHorizontal: 10,
    paddingVertical: 10,
  },
  pillValue: { fontSize: 20, fontWeight: '800' },
  pillLabel: { color: theme.textDim, fontSize: 11, marginTop: 2, textTransform: 'uppercase' },
  card: {
    backgroundColor: theme.surface,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: theme.border,
    padding: 14,
    marginBottom: 12,
  },
  cardTop: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  stateDot: { width: 10, height: 10, borderRadius: 5, marginTop: 5 },
  cardTitleWrap: { flex: 1 },
  cardTitle: { color: theme.text, fontSize: 16, fontWeight: '800' },
  meta: { color: theme.textDim, fontSize: 12, marginTop: 3 },
  stateText: {
    fontSize: 11,
    fontWeight: '800',
    textTransform: 'uppercase',
    maxWidth: 100,
    textAlign: 'right',
  },
  timestamp: { color: theme.textDim, fontSize: 12, marginTop: 10 },
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
