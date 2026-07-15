import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import {
  ApiError,
  decideApproval,
  fetchApprovals,
  type ApprovalAction,
  type ApprovalTask,
  type ApprovalsResponse,
} from '../api/client';
import { useServer } from '../context/ServerContext';
import { theme } from '../theme';
import { approvalPolicy } from './approvalPolicy';

type Busy = { id: number; action: ApprovalAction } | null;

function riskColor(task: ApprovalTask): string {
  if (task.reversible === false || (task.risk_tier ?? 0) >= 3) return theme.danger;
  if ((task.risk_tier ?? 0) >= 2) return theme.warn;
  return theme.ok;
}

function riskLabel(task: ApprovalTask): string {
  if (task.tier_name) return task.tier_name.toLowerCase().replace(/_/g, ' ');
  if (typeof task.risk_tier === 'number') return `tier ${task.risk_tier}`;
  return task.reversibility || 'queued';
}

function payloadPreview(task: ApprovalTask): string | null {
  if (!task.payload || Object.keys(task.payload).length === 0) return null;
  try {
    const text = JSON.stringify(task.payload);
    return text.length > 180 ? text.slice(0, 177) + '...' : text;
  } catch {
    return null;
  }
}

function CountPill({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <View style={[styles.pill, { borderColor: color }]}>
      <Text style={[styles.pillValue, { color }]}>{value}</Text>
      <Text style={styles.pillLabel}>{label}</Text>
    </View>
  );
}

function EmptyState({ onGoToSettings, missingAdmin }: { onGoToSettings: () => void; missingAdmin?: boolean }) {
  return (
    <View style={styles.empty}>
      <Text style={styles.emptyTitle}>{missingAdmin ? 'Admin token needed' : 'No hub connected'}</Text>
      <Text style={styles.emptyBody}>
        {missingAdmin
          ? 'Approvals are admin-gated by the hub.'
          : 'Connect this phone to your Jarvis hub before reviewing approvals.'}
      </Text>
      <Pressable style={styles.cta} onPress={onGoToSettings}>
        <Text style={styles.ctaText}>Open Settings</Text>
      </Pressable>
    </View>
  );
}

function ApprovalCard({
  task,
  busy,
  onDecision,
}: {
  task: ApprovalTask;
  busy: Busy;
  onDecision: (task: ApprovalTask, action: ApprovalAction) => void;
}) {
  const policy = approvalPolicy(task);
  const color = riskColor(task);
  const preview = policy.showPayload ? payloadPreview(task) : null;
  const active = busy?.id === task.id;

  const button = (action: ApprovalAction, label: string, style: object, textStyle?: object) => (
    <Pressable
      style={[styles.actionBtn, style, active && styles.actionDisabled]}
      disabled={active}
      onPress={() => onDecision(task, action)}
    >
      <Text style={[styles.actionText, textStyle]}>{active && busy?.action === action ? '...' : label}</Text>
    </Pressable>
  );

  return (
    <View style={styles.card}>
      <View style={styles.cardTop}>
        <View style={[styles.riskDot, { backgroundColor: color }]} />
        <View style={styles.cardTitleWrap}>
          <Text style={styles.cardTitle}>{task.title || task.kind || `Task ${task.id}`}</Text>
          <Text style={styles.meta}>
            {task.agent || 'jarvis'} · {task.kind || 'task'} · {task.status || 'pending'}
          </Text>
        </View>
        <Text style={[styles.riskText, { color }]}>{riskLabel(task)}</Text>
      </View>

      {preview && <Text style={styles.payload}>{preview}</Text>}

      {!policy.canApprove && (
        <Text style={styles.approvalBoundary}>Approval unavailable in mobile app · continue in Owner HUD</Text>
      )}

      {task.rollback && (
        <View style={styles.rollbackBox}>
          <Text style={styles.rollbackTitle}>Rollback · {task.rollback.mode.replace(/_/g, ' ')}</Text>
          <Text style={styles.rollbackText}>{task.rollback.description}</Text>
          {!!task.rollback.limitations && <Text style={styles.rollbackLimit}>{task.rollback.limitations}</Text>}
        </View>
      )}

      <View style={styles.actions}>
        {policy.canApprove && button('accept', 'Approve', styles.approveBtn)}
        {policy.canReject && button('reject', 'Reject', styles.rejectBtn)}
        {policy.canDefer && button('defer', 'Defer', styles.deferBtn, styles.deferText)}
      </View>
    </View>
  );
}

export function ApprovalsScreen({ onGoToSettings }: { onGoToSettings: () => void }) {
  const { config, configured } = useServer();
  const [data, setData] = useState<ApprovalsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<Busy>(null);

  const load = useCallback(async () => {
    if (!configured || !config.adminToken.trim()) return;
    setLoading(true);
    setError(null);
    try {
      setData(await fetchApprovals(config));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load approvals');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [config, configured]);

  useEffect(() => {
    load();
  }, [load]);

  const decide = useCallback(
    async (task: ApprovalTask, action: ApprovalAction) => {
      setBusy({ id: task.id, action });
      setError(null);
      try {
        await decideApproval(config, task.id, action);
        await load();
      } catch (e) {
        setError(e instanceof ApiError ? e.message : 'Decision failed');
      } finally {
        setBusy(null);
      }
    },
    [config, load],
  );

  if (!configured) return <EmptyState onGoToSettings={onGoToSettings} />;
  if (!config.adminToken.trim()) return <EmptyState onGoToSettings={onGoToSettings} missingAdmin />;

  const counts = data?.counts ?? { total: 0, reversible: 0, irreversible: 0 };
  const tasks = data?.pending ?? [];

  return (
    <ScrollView
      style={styles.flex}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.accent} />}
    >
      <View style={styles.summary}>
        <CountPill label="waiting" value={counts.total} color={theme.accent} />
        <CountPill label="reversible" value={counts.reversible} color={theme.ok} />
        <CountPill label="irreversible" value={counts.irreversible} color={theme.warn} />
      </View>

      {error && (
        <View style={styles.errorBox}>
          <Text style={styles.errorText}>{error}</Text>
        </View>
      )}

      {loading && !data && (
        <View style={styles.loading}>
          <ActivityIndicator color={theme.accent} />
        </View>
      )}

      {tasks.map((task) => (
        <ApprovalCard key={String(task.id)} task={task} busy={busy} onDecision={decide} />
      ))}

      {!loading && tasks.length === 0 && !error && (
        <View style={styles.clearBox}>
          <Text style={styles.clearTitle}>All clear</Text>
          <Text style={styles.clearText}>No decisions are waiting on this hub.</Text>
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
  riskDot: { width: 10, height: 10, borderRadius: 5, marginTop: 5 },
  cardTitleWrap: { flex: 1 },
  cardTitle: { color: theme.text, fontSize: 16, fontWeight: '700' },
  meta: { color: theme.textDim, fontSize: 12, marginTop: 3 },
  riskText: {
    fontSize: 11,
    fontWeight: '800',
    textTransform: 'uppercase',
    maxWidth: 110,
    textAlign: 'right',
  },
  payload: {
    color: theme.textDim,
    fontSize: 12,
    marginTop: 10,
    padding: 10,
    borderRadius: 10,
    backgroundColor: theme.surfaceAlt,
  },
  approvalBoundary: {
    color: theme.warn,
    fontSize: 12,
    fontWeight: '700',
    marginTop: 10,
  },
  rollbackBox: {
    marginTop: 10,
    padding: 10,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.surfaceAlt,
  },
  rollbackTitle: { color: theme.accent, fontSize: 11, fontWeight: '800', textTransform: 'uppercase' },
  rollbackText: { color: theme.text, fontSize: 12, marginTop: 4 },
  rollbackLimit: { color: theme.warn, fontSize: 11, marginTop: 4 },
  actions: { flexDirection: 'row', gap: 8, marginTop: 12 },
  actionBtn: {
    flex: 1,
    minHeight: 42,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
  },
  approveBtn: { backgroundColor: theme.ok },
  rejectBtn: { backgroundColor: theme.danger },
  deferBtn: { backgroundColor: theme.surfaceAlt, borderWidth: 1, borderColor: theme.border },
  actionDisabled: { opacity: 0.5 },
  actionText: { color: '#02121b', fontSize: 14, fontWeight: '800' },
  deferText: { color: theme.text },
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
