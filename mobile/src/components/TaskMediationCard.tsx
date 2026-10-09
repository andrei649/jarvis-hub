import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { fetchTaskMediationStatus, type TaskMediationStatus } from '../api/client';
import { useServer } from '../context/ServerContext';
import { type ServerConfig } from '../storage/settings';
import { useThemeStyles, type Theme } from '../theme';
import { Text } from './ThemedText';

type Props = { onGoToSettings: () => void; refreshKey?: number };
type ReadState = { kind: 'loading' | 'unavailable' } | { kind: 'ready'; value: TaskMediationStatus };

const COUNTS = [
  ['authorized_enqueue', 'Authorized enqueue events'],
  ['governed', 'Governed events'],
  ['refused_unmediated', 'Refused unmediated events'],
  ['ungoverned_detected', 'Ungoverned events detected'],
] as const;

/** A connection save (or parent pull refresh) mounts a fresh state before effects run. */
export function TaskMediationCard({ onGoToSettings, refreshKey = 0 }: Props) {
  const { config, configured, ready, connectionEpoch } = useServer();
  return <ScopedTaskMediationCard key={`${connectionEpoch}:${refreshKey}`} config={config}
    configured={configured} ready={ready} onGoToSettings={onGoToSettings} />;
}

function ScopedTaskMediationCard({ config, configured, ready, onGoToSettings }: Props & {
  config: ServerConfig; configured: boolean; ready: boolean;
}) {
  const { theme, styles } = useThemeStyles(makeStyles);
  const [read, setRead] = useState<ReadState>({ kind: 'loading' });
  const sequence = useRef(0);
  const mounted = useRef(false);
  const canRead = ready && configured && !!config.adminToken.trim();

  const load = useCallback(() => {
    if (!canRead) return;
    const current = ++sequence.current;
    setRead({ kind: 'loading' });
    void fetchTaskMediationStatus(config).then(
      value => { if (mounted.current && current === sequence.current) setRead({ kind: 'ready', value }); },
      () => { if (mounted.current && current === sequence.current) setRead({ kind: 'unavailable' }); },
    );
  }, [canRead, config]);

  useEffect(() => {
    mounted.current = true;
    load();
    return () => { mounted.current = false; ++sequence.current; };
  }, [load]);

  const snapshot = canRead && read.kind === 'ready' ? read.value : null;
  const stats = snapshot?.valid ? snapshot.stats : null;
  const message = !ready ? 'Loading connection settings…'
    : !configured ? 'Connect a hub in Settings to view task mediation status.'
      : !config.adminToken.trim() ? 'Admin token required. Add one in Settings to view task mediation status.'
        : read.kind === 'loading' ? 'Loading task mediation status…'
          : read.kind === 'unavailable' ? 'Task mediation status unavailable.' : null;

  return (
    <View style={styles.card} accessibilityLabel="Task mediation">
      <Text style={styles.title}>Task mediation</Text>
      {message ? <Text style={styles.message}>{message}</Text> : null}
      {snapshot ? (
        <>
          <Text style={styles.line}>Effective mode: {snapshot.mode}</Text>
          <Text style={[styles.line, { color: snapshot.valid ? theme.ok : theme.warn }]}>
            Evidence: {snapshot.valid ? 'verified' : 'unavailable or invalid'}
          </Text>
          {stats ? COUNTS.map(([key, label]) => (
            <Text key={key} style={styles.line}>{label}: {stats[key]}</Text>
          )) : null}
        </>
      ) : null}
      <Text style={styles.note}>Counts cover verified recorded events, not every task or proof that mediation is ready for use.</Text>
      <View style={styles.actions}>
        {canRead ? (
          <Pressable style={styles.button} onPress={load} accessibilityRole="button"
            accessibilityLabel={read.kind === 'unavailable' ? 'Retry task mediation status' : 'Refresh task mediation status'}>
            <Text style={styles.buttonText}>{read.kind === 'unavailable' ? 'Retry' : 'Refresh'}</Text>
          </Pressable>
        ) : null}
        <Pressable style={styles.button} onPress={onGoToSettings} accessibilityRole="button"
          accessibilityLabel="Open Settings">
          <Text style={styles.buttonText}>Settings</Text>
        </Pressable>
      </View>
    </View>
  );
}

const makeStyles = (theme: Theme) => StyleSheet.create({
  card: { backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, borderRadius: 12,
    padding: 16, gap: 7 },
  title: { color: theme.text, fontSize: 16, fontWeight: '700' },
  line: { color: theme.text, fontSize: 13 },
  message: { color: theme.textDim, fontSize: 13 },
  note: { color: theme.textDim, fontSize: 12, lineHeight: 17, marginTop: 4 },
  actions: { flexDirection: 'row', gap: 8, marginTop: 6 },
  button: { borderColor: theme.border, borderWidth: 1, borderRadius: 8, paddingHorizontal: 12,
    paddingVertical: 7, minHeight: 36, justifyContent: 'center' },
  buttonText: { color: theme.accent, fontSize: 13, fontWeight: '600' },
});
