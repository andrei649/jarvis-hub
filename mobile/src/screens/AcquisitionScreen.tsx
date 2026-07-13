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
  fetchAcquisitionEvents,
  fetchAcquisitionStatus,
  type AcquisitionEvent,
  type AcquisitionPackage,
} from '../api/client';
import { useServer } from '../context/ServerContext';
import { theme } from '../theme';

function EmptyState({ onGoToSettings }: { onGoToSettings: () => void }) {
  return (
    <View style={styles.empty}>
      <Text style={styles.emptyTitle}>No hub connected</Text>
      <Text style={styles.emptyBody}>Connect this phone to review governed capability acquisition.</Text>
      <Pressable style={styles.primaryButton} onPress={onGoToSettings}>
        <Text style={styles.primaryButtonText}>Open Settings</Text>
      </Pressable>
    </View>
  );
}

function PackageCard({ item }: { item: AcquisitionPackage }) {
  return (
    <View style={styles.card}>
      <View style={styles.row}>
        <View style={styles.grow}>
          <Text style={styles.cardTitle}>{item.name}</Text>
          <Text style={styles.meta}>v{item.version} · sandbox only</Text>
        </View>
        <Text style={styles.badge}>{item.status}</Text>
      </View>
      <Text style={styles.evidence}>{Math.round(item.confidence * 100)}% observed evidence</Text>
    </View>
  );
}

function EventCard({ item }: { item: AcquisitionEvent }) {
  const occurred = new Date(item.occurred_at * 1000).toLocaleString();
  return (
    <View style={styles.eventCard}>
      <View style={styles.row}>
        <Text style={styles.eventType}>#{item.sequence} · {item.event_type}</Text>
        <Text style={styles.badge}>{item.status}</Text>
      </View>
      <Text style={styles.meta}>{item.actor} · {occurred}</Text>
    </View>
  );
}

export function AcquisitionScreen({ onGoToSettings }: { onGoToSettings: () => void }) {
  const { config, configured } = useServer();
  const [enabled, setEnabled] = useState(false);
  const [status, setStatus] = useState('disabled');
  const [reason, setReason] = useState('');
  const [states, setStates] = useState<Record<string, number>>({});
  const [reuse_rate, setReuseRate] = useState(0);
  const [packages, setPackages] = useState<AcquisitionPackage[]>([]);
  const [events, setEvents] = useState<AcquisitionEvent[]>([]);
  const [chain_valid, setChainValid] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!configured) return;
    setRefreshing(true);
    setError(null);
    try {
      const [snapshot, audit] = await Promise.all([
        fetchAcquisitionStatus(config),
        fetchAcquisitionEvents(config),
      ]);
      setEnabled(snapshot.enabled);
      setStatus(snapshot.status);
      setReason(snapshot.reason);
      setStates(snapshot.states);
      setReuseRate(snapshot.reuse.reuse_rate);
      setPackages(snapshot.packages);
      setEvents(audit.events);
      setChainValid(snapshot.audit.chain_valid);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load acquisition state');
      setEnabled(false);
      setPackages([]);
      setEvents([]);
    } finally {
      setLoaded(true);
      setRefreshing(false);
    }
  }, [config, configured]);

  useEffect(() => {
    load();
  }, [load]);

  if (!configured) return <EmptyState onGoToSettings={onGoToSettings} />;

  return (
    <ScrollView
      style={styles.flex}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} tintColor={theme.accent} />}
    >
      <View style={styles.hero}>
        <Text style={styles.heroTitle}>Governed growth, read-only here</Text>
        <Text style={styles.heroBody}>Review lifecycle state and bounded audit metadata. Owner controls stay on the hub.</Text>
      </View>
      {error ? <View style={styles.errorBox}><Text style={styles.errorText}>{error}</Text></View> : null}
      {!loaded ? <ActivityIndicator style={styles.loading} color={theme.accent} /> : null}
      {loaded && !enabled && !error ? (
        <View style={styles.disabledBox}>
          <Text style={styles.disabledTitle}>Capability Acquisition is off</Text>
          <Text style={styles.disabledText}>{reason || 'Owner enablement is required on the hub.'}</Text>
        </View>
      ) : null}
      {enabled ? (
        <>
          <View style={styles.summaryRow}>
            <View style={styles.summaryCell}><Text style={styles.summaryValue}>{status}</Text><Text style={styles.summaryLabel}>state</Text></View>
            <View style={styles.summaryCell}><Text style={styles.summaryValue}>{Math.round(reuse_rate * 100)}%</Text><Text style={styles.summaryLabel}>reuse</Text></View>
            <View style={styles.summaryCell}><Text style={[styles.summaryValue, !chain_valid && styles.danger]}>{chain_valid ? 'valid' : 'degraded'}</Text><Text style={styles.summaryLabel}>audit chain</Text></View>
          </View>
          <View style={styles.chips}>
            {Object.entries(states).map(([name, count]) => <Text key={name} style={styles.chip}>{name} · {count}</Text>)}
          </View>
          <Text style={styles.sectionTitle}>Signed sandbox-only packages</Text>
          {packages.map((item) => <PackageCard key={item.name} item={item} />)}
          {!packages.length ? <Text style={styles.emptyInline}>No promoted packages.</Text> : null}
          <Text style={styles.sectionTitle}>Latest audit metadata</Text>
          {events.map((item) => <EventCard key={`${item.sequence}:${item.event_type}`} item={item} />)}
          {!events.length ? <Text style={styles.emptyInline}>No detailed events retained.</Text> : null}
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
  summaryRow: { flexDirection: 'row', gap: 8, marginBottom: 10 },
  summaryCell: { flex: 1, backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, borderRadius: 12, padding: 10 },
  summaryValue: { color: theme.accent, fontSize: 15, fontWeight: '800' },
  summaryLabel: { color: theme.textDim, fontSize: 9, marginTop: 3, textTransform: 'uppercase' },
  danger: { color: theme.danger },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: 8 },
  chip: { color: theme.textDim, borderColor: theme.border, borderWidth: 1, borderRadius: 10, paddingHorizontal: 7, paddingVertical: 4, fontSize: 10 },
  sectionTitle: { color: theme.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 1, marginTop: 10, marginBottom: 7, textTransform: 'uppercase' },
  card: { backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, borderRadius: 14, padding: 13, marginBottom: 8 },
  eventCard: { backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, borderRadius: 12, padding: 11, marginBottom: 7 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  grow: { flex: 1 },
  cardTitle: { color: theme.text, fontSize: 15, fontWeight: '800' },
  eventType: { color: theme.text, fontSize: 12, fontWeight: '700', flex: 1 },
  meta: { color: theme.textDim, fontSize: 10, marginTop: 3 },
  badge: { color: theme.accent, borderColor: theme.accentDim, borderWidth: 1, borderRadius: 9, paddingHorizontal: 6, paddingVertical: 3, fontSize: 9 },
  evidence: { color: theme.textDim, fontSize: 10, marginTop: 8 },
  emptyInline: { color: theme.textDim, fontSize: 13, backgroundColor: theme.surface, borderRadius: 12, padding: 14 },
  loading: { marginVertical: 28 },
  errorBox: { backgroundColor: '#2a0d16', borderColor: theme.danger, borderWidth: 1, borderRadius: 12, padding: 12, marginBottom: 12 },
  errorText: { color: theme.danger, fontSize: 13 },
  disabledBox: { backgroundColor: theme.surface, borderColor: theme.warn, borderWidth: 1, borderRadius: 14, padding: 18 },
  disabledTitle: { color: theme.warn, fontSize: 16, fontWeight: '800' },
  disabledText: { color: theme.textDim, fontSize: 13, marginTop: 5, lineHeight: 18 },
  primaryButton: { minHeight: 44, borderRadius: 22, backgroundColor: theme.accent, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 18, marginTop: 12 },
  primaryButtonText: { color: '#02121b', fontSize: 14, fontWeight: '800' },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  emptyTitle: { color: theme.text, fontSize: 20, fontWeight: '700', marginBottom: 8 },
  emptyBody: { color: theme.textDim, fontSize: 15, textAlign: 'center', marginBottom: 24 },
});
