import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import {
  ApiError,
  fetchAmbientMonitors,
  type AmbientMonitor,
  type AmbientMonitorsResponse,
  type AmbientRung,
} from '../api/client';
import { useServer } from '../context/ServerContext';
import { theme } from '../theme';

const RUNGS: AmbientRung[] = ['ignore', 'remember', 'monitor', 'act_silently', 'ask', 'interrupt'];

function EmptyState({ onGoToSettings }: { onGoToSettings: () => void }) {
  return (
    <View style={styles.empty}>
      <Text style={styles.emptyTitle}>No hub connected</Text>
      <Text style={styles.emptyBody}>Connect this phone to inspect the redacted ambient monitor board.</Text>
      <Pressable style={styles.primaryButton} onPress={onGoToSettings}>
        <Text style={styles.primaryButtonText}>Open Settings</Text>
      </Pressable>
    </View>
  );
}

function MonitorCard({ monitor }: { monitor: AmbientMonitor }) {
  const decision = monitor.last_decision;
  return (
    <View style={styles.card}>
      <View style={styles.row}>
        <View style={styles.grow}>
          <Text style={styles.cardTitle}>{monitor.monitor_id}</Text>
          <Text style={styles.meta}>{monitor.source} · {monitor.schema} · v{monitor.version}</Text>
        </View>
        <Text style={styles.badge}>{monitor.state}</Text>
      </View>
      <Text style={styles.rule}>alert → {monitor.alert_rung} · recovery → {monitor.recovery_rung}</Text>
      {decision ? (
        <Text style={styles.decision}>
          Last: {decision.transition} → {decision.rung} · {decision.policy_reason.split('_').join(' ')}
        </Text>
      ) : <Text style={styles.meta}>Waiting for the first decision.</Text>}
    </View>
  );
}

export function AmbientScreen({ onGoToSettings }: { onGoToSettings: () => void }) {
  const { config, configured } = useServer();
  const [data, setData] = useState<AmbientMonitorsResponse | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!configured) return;
    setRefreshing(true);
    setError(null);
    try {
      setData(await fetchAmbientMonitors(config));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load ambient monitors');
      setData(null);
    } finally {
      setLoaded(true);
      setRefreshing(false);
    }
  }, [config, configured]);

  useEffect(() => { load(); }, [load]);

  if (!configured) return <EmptyState onGoToSettings={onGoToSettings} />;

  return (
    <ScrollView
      style={styles.flex}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} tintColor={theme.accent} />}
    >
      <View style={styles.hero}>
        <Text style={styles.heroTitle}>What Jarvis is watching</Text>
        <Text style={styles.heroBody}>Monitor state and policy choices only. Subjects, predicates, event content, and recipients remain on the hub.</Text>
      </View>
      {error ? <View style={styles.errorBox}><Text style={styles.errorText}>{error}</Text></View> : null}
      {!loaded ? <ActivityIndicator style={styles.loading} color={theme.accent} /> : null}
      {data && !data.enabled ? (
        <View style={styles.disabledBox}>
          <Text style={styles.disabledTitle}>{data.status === 'degraded' ? 'Ambient runtime degraded' : 'Ambient intelligence is off'}</Text>
          <Text style={styles.disabledText}>{data.reason || 'Owner opt-in is required on the hub.'}</Text>
        </View>
      ) : null}
      {data?.enabled ? (
        <>
          <View style={styles.budget}>
            <View>
              <Text style={styles.sectionTitle}>Global attention</Text>
              <Text style={styles.budgetValue}>{data.attention.remaining} / {data.attention.limit} left</Text>
            </View>
            <Text style={[styles.health, data.attention.status === 'ready' ? styles.ok : styles.warn]}>{data.attention.status}</Text>
          </View>
          <View style={styles.rungs}>
            {RUNGS.map((rung) => <Text key={rung} style={styles.rung}>{rung} · {data.rung_counts[rung]}</Text>)}
          </View>
          <Text style={styles.sectionTitle}>Sources</Text>
          {data.sources.map((source) => (
            <View key={source.source} style={styles.sourceRow}>
              <Text style={styles.sourceName}>{source.source}</Text>
              <Text style={source.status === 'live' ? styles.ok : styles.warn}>{source.status}</Text>
            </View>
          ))}
          <Text style={styles.sectionTitle}>Monitors</Text>
          {data.monitors.map((monitor) => <MonitorCard key={monitor.monitor_id} monitor={monitor} />)}
          {!data.monitors.length ? <Text style={styles.emptyInline}>No owner-defined monitors yet.</Text> : null}
        </>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { padding: 12, paddingBottom: 30 },
  hero: { backgroundColor: theme.surfaceAlt, borderColor: theme.border, borderWidth: 1, borderRadius: 14, padding: 16, marginBottom: 12 },
  heroTitle: { color: theme.accent, fontSize: 19, fontWeight: '800' },
  heroBody: { color: theme.textDim, fontSize: 13, lineHeight: 19, marginTop: 5 },
  budget: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, borderRadius: 14, padding: 14, marginBottom: 10 },
  budgetValue: { color: theme.text, fontSize: 22, fontWeight: '800', marginTop: 3 },
  health: { textTransform: 'uppercase', fontSize: 11, fontWeight: '800' },
  ok: { color: theme.ok },
  warn: { color: theme.warn },
  rungs: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: 12 },
  rung: { color: theme.textDim, borderColor: theme.border, borderWidth: 1, borderRadius: 10, paddingHorizontal: 7, paddingVertical: 4, fontSize: 10 },
  sectionTitle: { color: theme.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 1, marginTop: 8, marginBottom: 7, textTransform: 'uppercase' },
  sourceRow: { flexDirection: 'row', justifyContent: 'space-between', backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, borderRadius: 11, padding: 11, marginBottom: 6 },
  sourceName: { color: theme.text, fontSize: 13, fontWeight: '700' },
  card: { backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, borderRadius: 14, padding: 13, marginBottom: 8 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  grow: { flex: 1 },
  cardTitle: { color: theme.text, fontSize: 15, fontWeight: '700' },
  meta: { color: theme.textDim, fontSize: 11, marginTop: 3 },
  badge: { color: theme.accent, borderColor: theme.accentDim, borderWidth: 1, borderRadius: 10, paddingHorizontal: 7, paddingVertical: 3, fontSize: 10 },
  rule: { color: theme.textDim, fontSize: 11, marginTop: 9 },
  decision: { color: theme.text, fontSize: 12, lineHeight: 17, marginTop: 6 },
  errorBox: { backgroundColor: '#2a0d16', borderColor: theme.danger, borderWidth: 1, borderRadius: 12, padding: 12, marginBottom: 12 },
  errorText: { color: theme.danger, fontSize: 13 },
  disabledBox: { backgroundColor: theme.surface, borderColor: theme.warn, borderWidth: 1, borderRadius: 14, padding: 18 },
  disabledTitle: { color: theme.warn, fontSize: 16, fontWeight: '800' },
  disabledText: { color: theme.textDim, fontSize: 13, marginTop: 5, lineHeight: 18 },
  emptyInline: { color: theme.textDim, fontSize: 13, backgroundColor: theme.surface, borderRadius: 12, padding: 14 },
  loading: { marginVertical: 28 },
  primaryButton: { minHeight: 44, borderRadius: 22, backgroundColor: theme.accent, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 18, marginTop: 12 },
  primaryButtonText: { color: '#02121b', fontSize: 14, fontWeight: '800' },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  emptyTitle: { color: theme.text, fontSize: 20, fontWeight: '700', marginBottom: 8 },
  emptyBody: { color: theme.textDim, fontSize: 15, textAlign: 'center', marginBottom: 24 },
});
