import React, { useCallback, useEffect, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { ApiError, fetchStatus, type StatusResponse } from '../api/client';
import { useServer } from '../context/ServerContext';
import { theme } from '../theme';

function Row({ label, value }: { label: string; value: string | number | undefined | null }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue}>{value === undefined || value === null || value === '' ? '—' : String(value)}</Text>
    </View>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.card}>
      <Text style={styles.cardTitle}>{title}</Text>
      {children}
    </View>
  );
}

const STATE_COLOR: Record<string, string> = {
  ready: theme.ok,
  no_model: theme.warn,
  offline: theme.danger,
};

export function StatusScreen({ onGoToSettings }: { onGoToSettings: () => void }) {
  const { config, configured } = useServer();
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!configured) return;
    setLoading(true);
    setError(null);
    try {
      setStatus(await fetchStatus(config));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load status');
      setStatus(null);
    } finally {
      setLoading(false);
    }
  }, [config, configured]);

  useEffect(() => {
    load();
  }, [load]);

  if (!configured) {
    return (
      <View style={styles.empty}>
        <Text style={styles.emptyTitle}>No hub connected</Text>
        <Pressable style={styles.cta} onPress={onGoToSettings}>
          <Text style={styles.ctaText}>Open Settings</Text>
        </Pressable>
      </View>
    );
  }

  const sys = status?.sys;
  const stateColor = STATE_COLOR[status?.model_state ?? ''] ?? theme.textDim;

  return (
    <ScrollView
      style={styles.flex}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.accent} />}
    >
      {error && (
        <View style={styles.errorBox}>
          <Text style={styles.errorText}>{error}</Text>
        </View>
      )}

      <Card title="Model">
        <View style={styles.stateRow}>
          <View style={[styles.dot, { backgroundColor: stateColor }]} />
          <Text style={[styles.stateText, { color: stateColor }]}>
            {(status?.model_state ?? 'unknown').toUpperCase()}
          </Text>
        </View>
        <Row label="Backend" value={status?.llm_backend} />
        <Row label="Loaded" value={status?.loaded_model} />
        <Row label="Configured" value={status?.active_model} />
        <Row label="Reachable" value={status?.lm_online ? 'yes' : 'no'} />
      </Card>

      <Card title="Agents">
        <Row label="Online" value={status?.agents_online} />
        <Row label="Total" value={status?.agents_total} />
      </Card>

      {sys && (
        <Card title="System">
          <Row label="Host" value={sys.host} />
          <Row label="CPU" value={sys.cpu} />
          <Row label="RAM" value={`${sys.ram_used} / ${sys.ram_total} GB`} />
          <Row label="GPU" value={sys.gpu} />
          <Row label="VRAM" value={`${sys.vram_used} / ${sys.vram_total} GB`} />
          <Row label="GPU load" value={`${sys.gpu_load}%`} />
          <Row label="Uptime" value={sys.uptime} />
          <Row label="Sessions" value={sys.sessions} />
        </Card>
      )}

      <Card title="Hub">
        <Row label="Version" value={status?.version} />
        <Row label="URL" value={config.baseUrl} />
      </Card>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { padding: 12 },
  card: {
    backgroundColor: theme.surface,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: theme.border,
    padding: 14,
    marginBottom: 12,
  },
  cardTitle: {
    color: theme.accent,
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 1.2,
    textTransform: 'uppercase',
    marginBottom: 10,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 5,
    gap: 12,
  },
  rowLabel: { color: theme.textDim, fontSize: 14 },
  rowValue: { color: theme.text, fontSize: 14, flexShrink: 1, textAlign: 'right' },
  stateRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 8 },
  dot: { width: 10, height: 10, borderRadius: 5, marginRight: 8 },
  stateText: { fontSize: 16, fontWeight: '700', letterSpacing: 1 },
  errorBox: {
    backgroundColor: '#2a0d16',
    borderColor: theme.danger,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
  },
  errorText: { color: theme.danger, fontSize: 14 },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  emptyTitle: { color: theme.text, fontSize: 20, fontWeight: '700', marginBottom: 20 },
  cta: { paddingHorizontal: 24, paddingVertical: 12, borderRadius: 24, backgroundColor: theme.accent },
  ctaText: { color: '#02121b', fontWeight: '700', fontSize: 15 },
});
