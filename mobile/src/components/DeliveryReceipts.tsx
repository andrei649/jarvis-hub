import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { ApiError } from '../api/client';
import { DELIVERY_STATES, fetchDeliveries, type DeliverySnapshot, type DeliveryState } from '../api/deliveries';
import { useServer } from '../context/ServerContext';
import type { ServerConfig } from '../storage/settings';
import { useThemeStyles, type Theme } from '../theme';
import { Text } from './ThemedText';

const EXPLANATION: Record<DeliveryState, string> = {
  sent: 'Platform acknowledged all parts; recipient reading is not confirmed.',
  failed: 'Platform refused the send, or transport never started.',
  partial: 'Some parts may have been accepted.',
  unknown: 'May have arrived; automatic resend is off.',
  pending: 'Recorded before sending; later status may be unavailable.',
  attempting: 'Attempt recorded; delivery may be in progress or uncertain.',
  skipped: 'No send for this row: a duplicate, dead target, or exhausted attempts.',
};

function duration(seconds: number): string {
  if (seconds % 86_400 === 0) return `${seconds / 86_400} day${seconds === 86_400 ? '' : 's'}`;
  if (seconds % 3_600 === 0) return `${seconds / 3_600} hour${seconds === 3_600 ? '' : 's'}`;
  return `${seconds} seconds`;
}

/** A connection or credential save remounts the disclosure closed, without cached owner rows. */
export function DeliveryReceipts() {
  const { config, chatScope, connectionEpoch } = useServer();
  return <ScopedDeliveryReceipts key={`${chatScope}:${connectionEpoch}`} config={config} />;
}

function ScopedDeliveryReceipts({ config }: { config: ServerConfig }) {
  const { styles } = useThemeStyles(makeStyles);
  const [open, setOpen] = useState(false);
  const [snapshot, setSnapshot] = useState<DeliverySnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const sequence = useRef(0);
  const controller = useRef<AbortController | null>(null);

  const load = useCallback(() => {
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    const request = ++sequence.current;
    setSnapshot(null);
    setMessage(null);
    setLoading(true);
    void fetchDeliveries(config, abort.signal).then(value => {
      if (sequence.current === request && !abort.signal.aborted) {
        setSnapshot(value);
        setLoading(false);
      }
    }, error => {
      if (sequence.current === request && !abort.signal.aborted) {
        const status = error instanceof ApiError ? error.status : undefined;
        setMessage(status === 401 || status === 403 ? 'Owner access required.'
          : status === 503 ? 'Delivery ledger unavailable.'
            : error instanceof ApiError && error.message === 'Invalid delivery receipts'
              ? 'Delivery receipts could not be checked from this response.'
              : 'Delivery receipts unavailable.');
        setLoading(false);
      }
    });
  }, [config]);

  const close = useCallback(() => {
    ++sequence.current;
    controller.current?.abort();
    controller.current = null;
    setOpen(false);
    setSnapshot(null);
    setMessage(null);
    setLoading(false);
  }, []);

  useEffect(() => () => { ++sequence.current; controller.current?.abort(); }, []);

  return (
    <View style={styles.card} accessibilityLabel="Delivery receipts">
      <Text style={styles.title}>Delivery receipts</Text>
      {!open ? <Pressable style={styles.button} accessibilityRole="button" accessibilityLabel="Open delivery receipts"
        onPress={() => { setOpen(true); load(); }}><Text style={styles.action}>Open receipts</Text></Pressable> : <>
        <View style={styles.actions}>
          <Pressable style={styles.button} accessibilityRole="button" accessibilityLabel="Refresh delivery receipts"
            onPress={load}><Text style={styles.action}>Refresh receipts</Text></Pressable>
          <Pressable style={styles.button} accessibilityRole="button" accessibilityLabel="Close delivery receipts"
            onPress={close}><Text style={styles.action}>Close receipts</Text></Pressable>
        </View>
        {loading ? <Text style={styles.note}>Checking delivery receipts…</Text> : null}
        {message ? <Text style={styles.note}>{message}</Text> : null}
        {snapshot ? <>
          <Text style={styles.note}>Recent 50 receipt rows only; counts describe retained rows, not all sends.
            {' '}Duplicate protection records: {snapshot.retention.protectedCount} of {snapshot.retention.protectedLimit} occupied;
            {' '}when full, new sends requiring protection are withheld. The ordinary row budget is
            {' '}{snapshot.retention.ordinaryRowLimit}; protected and open attempts can extend the total.
            {' '}Ordinary retention is {duration(snapshot.retention.retentionSeconds)}; keyed duplicate protection lasts
            {' '}{duration(snapshot.retention.windowSeconds)}. Records can expire or be refused at capacity.
            {' '}No message bodies are stored here.</Text>
          {DELIVERY_STATES.map(state => <Text key={state} style={styles.line}>
            {state} {snapshot.stats.byState[state]} · {EXPLANATION[state]}
          </Text>)}
          <Text style={styles.note}>{snapshot.stats.deadTargets} dead targets
            {snapshot.deadTargetsTruncated ? ' (server list truncated)' : ''}. Receipts never trigger automatic redelivery.</Text>
          {snapshot.deliveries.length === 0 ? <Text style={styles.line}>No receipt rows returned for this read.</Text>
            : snapshot.deliveries.map(row => <Text key={row.id} style={styles.line}>
              {row.id} · {row.channel} → {row.target} · {row.state} · attempt {row.attempt}
              {' · '}{row.chars} characters · {new Date(row.updated * 1000).toLocaleString()}
            </Text>)}
        </> : null}
      </>}
    </View>
  );
}

const makeStyles = (theme: Theme) => StyleSheet.create({
  card: { backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1,
    borderRadius: 12, padding: 16, gap: 7 },
  title: { color: theme.text, fontSize: 16, fontWeight: '700' },
  line: { color: theme.text, fontSize: 13, lineHeight: 19 },
  note: { color: theme.textDim, fontSize: 12, lineHeight: 17, marginTop: 4 },
  actions: { flexDirection: 'row', gap: 8 },
  button: { borderColor: theme.border, borderWidth: 1, borderRadius: 8,
    paddingHorizontal: 12, paddingVertical: 7, minHeight: 36, justifyContent: 'center' },
  action: { color: theme.accent, fontSize: 13, fontWeight: '600' },
});
