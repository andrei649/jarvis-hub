import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import * as FileSystem from 'expo-file-system/legacy';
import {
  ApiError,
  CAPTURE_SURFACES,
  clearCapture,
  fetchCaptureExport,
  fetchCaptureRecords,
  fetchCaptureStatus,
  forgetCaptureRecord,
  type CaptureRecord,
  type CaptureStatus,
  type CaptureSurface,
} from '../api/client';
import {
  captureState,
  captureStateLabel,
  describeExport,
  exportFileName,
  surfaceCaveat,
} from './capturePolicy';
import { useServer } from '../context/ServerContext';
import { theme } from '../theme';

/* T-0.26 — the Capture inbox on the phone.
 *
 * What this screen can do: see every captured record, delete one, clear the lot, and
 * take a portable export off the box. That is the whole privacy promise of H12.7 —
 * *inspectable and forgettable* — made reachable from the device someone actually has
 * in their hand, instead of only from the owner HUD.
 *
 * What it deliberately cannot do: **turn capture on**. `POST /api/capture/surfaces`
 * and `POST /api/capture/ingest` exist and are user-guarded, and they are still not
 * here. Enabling a surface is arming an ambient recorder on a machine you are not
 * sitting at; a phone that can do that turns a lost or borrowed handset into a way to
 * start recording someone else's desk. Deleting, by contrast, is safe in the direction
 * that matters — the worst case is losing a record you wanted, never gaining one you
 * did not consent to. So the destructive half is here and the arming half is not, and
 * that asymmetry is the design rather than an omission.
 */

function EmptyState({ onGoToSettings }: { onGoToSettings: () => void }) {
  return (
    <View style={styles.empty}>
      <Text style={styles.emptyTitle}>No hub connected</Text>
      <Text style={styles.emptyBody}>Connect this phone to inspect and erase what the hub captured.</Text>
      <Pressable style={styles.primaryButton} onPress={onGoToSettings}>
        <Text style={styles.primaryButtonText}>Open Settings</Text>
      </Pressable>
    </View>
  );
}

function RecordCard({ item, onForget }: { item: CaptureRecord; onForget: (id: string) => void }) {
  const when = item.created_at === null ? 'no timestamp' : new Date(item.created_at * 1000).toLocaleString();
  return (
    <View style={styles.card}>
      <View style={styles.row}>
        <Text style={styles.cardTitle}>{item.surface || 'unknown surface'}</Text>
        {item.redacted ? <Text style={styles.badge}>redacted</Text> : null}
      </View>
      <Text style={styles.preview}>{item.preview || '(empty preview)'}</Text>
      <Text style={styles.meta}>
        {when}
        {item.source ? ` · ${item.source}` : ''}
        {item.triples ? ` · ${item.triples} facts` : ''}
      </Text>
      <Pressable style={styles.forgetButton} onPress={() => onForget(item.id)}>
        <Text style={styles.forgetButtonText}>Forget this</Text>
      </Pressable>
    </View>
  );
}

export function CaptureScreen({ onGoToSettings }: { onGoToSettings: () => void }) {
  const { config, configured } = useServer();
  const [status, setStatus] = useState<CaptureStatus | null>(null);
  const [records, setRecords] = useState<CaptureRecord[]>([]);
  const [surface, setSurface] = useState<CaptureSurface | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!configured) return;
    setRefreshing(true);
    setError(null);
    try {
      const [snapshot, items] = await Promise.all([
        fetchCaptureStatus(config),
        fetchCaptureRecords(config, surface ?? undefined),
      ]);
      setStatus(snapshot);
      setRecords(items);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load the capture inbox');
      // Not `enabled: false` — a failed fetch is not evidence that capture is off, and
      // rendering it as off would be the most reassuring possible lie. `null` keeps the
      // state `unknown` and the hero says so.
      setStatus(null);
      setRecords([]);
    } finally {
      setLoaded(true);
      setRefreshing(false);
    }
  }, [config, configured, surface]);

  useEffect(() => {
    load();
  }, [load]);

  const state = useMemo(() => captureState(status), [status]);
  const caveat = useMemo(() => surfaceCaveat(status), [status]);

  const forget = useCallback((id: string) => {
    Alert.alert('Forget this record?', 'It is deleted on the hub. This cannot be undone.', [
      { text: 'Keep', style: 'cancel' },
      {
        text: 'Forget',
        style: 'destructive',
        onPress: async () => {
          setBusy(true);
          try {
            const res = await forgetCaptureRecord(config, id);
            // A false here means the hub did not have it; say so rather than
            // optimistically removing the row and looking like it worked.
            setNote(res.forgotten ? 'Record forgotten.' : 'The hub had no such record — nothing was deleted.');
            await load();
          } catch (err) {
            setError(err instanceof ApiError ? err.message : 'Failed to forget the record');
          } finally {
            setBusy(false);
          }
        },
      },
    ]);
  }, [config, load]);

  const clearAll = useCallback(() => {
    const scope = surface ? `every ${surface} record` : 'every captured record';
    Alert.alert('Clear the inbox?', `This deletes ${scope} on the hub. This cannot be undone.`, [
      { text: 'Keep', style: 'cancel' },
      {
        text: 'Clear',
        style: 'destructive',
        onPress: async () => {
          setBusy(true);
          try {
            const res = await clearCapture(config, surface ?? undefined);
            setNote(`${res.removed} record${res.removed === 1 ? '' : 's'} deleted.`);
            await load();
          } catch (err) {
            setError(err instanceof ApiError ? err.message : 'Failed to clear the inbox');
          } finally {
            setBusy(false);
          }
        },
      },
    ]);
  }, [config, load, surface]);

  const exportInbox = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const envelope = await fetchCaptureExport(config, surface ?? undefined);
      const dir = FileSystem.documentDirectory;
      if (!dir) {
        // Say which half worked. "Export failed" would hide that the hub answered.
        setNote(`Exported ${describeExport(envelope)}, but this device exposes no writable folder.`);
        return;
      }
      const uri = `${dir}${exportFileName(envelope)}`;
      await FileSystem.writeAsStringAsync(uri, JSON.stringify(envelope, null, 2));
      setNote(`Saved ${describeExport(envelope)} → ${exportFileName(envelope)}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to export the capture inbox');
    } finally {
      setBusy(false);
    }
  }, [config, surface]);

  if (!configured) return <EmptyState onGoToSettings={onGoToSettings} />;

  return (
    <ScrollView
      style={styles.flex}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} tintColor={theme.accent} />}
    >
      <View style={styles.hero}>
        <Text style={[styles.heroTitle, state === 'recording' && styles.recording]}>
          {captureStateLabel(state)}
        </Text>
        {caveat ? <Text style={styles.heroBody}>{caveat}</Text> : null}
        <Text style={styles.heroBody}>
          Previews are redacted on the hub before they are stored — raw content is never kept.
          Everything here can be deleted, one record or all of them.
        </Text>
      </View>

      {error ? <View style={styles.errorBox}><Text style={styles.errorText}>{error}</Text></View> : null}
      {note ? <View style={styles.noteBox}><Text style={styles.noteText}>{note}</Text></View> : null}
      {!loaded ? <ActivityIndicator style={styles.loading} color={theme.accent} /> : null}

      <View style={styles.chips}>
        <Pressable onPress={() => setSurface(null)}>
          <Text style={[styles.chip, surface === null && styles.chipOn]}>all</Text>
        </Pressable>
        {CAPTURE_SURFACES.map((s) => (
          <Pressable key={s} onPress={() => setSurface(s)}>
            <Text style={[styles.chip, surface === s && styles.chipOn]}>
              {s}{status && status.surfaces[s] ? ' ·' : ''}
            </Text>
          </Pressable>
        ))}
      </View>

      <View style={styles.actions}>
        <Pressable style={[styles.actionButton, busy && styles.actionDisabled]} disabled={busy} onPress={exportInbox}>
          <Text style={styles.actionText}>Export</Text>
        </Pressable>
        <Pressable
          style={[styles.actionButton, styles.dangerButton, (busy || !records.length) && styles.actionDisabled]}
          disabled={busy || !records.length}
          onPress={clearAll}
        >
          <Text style={[styles.actionText, styles.dangerText]}>Clear</Text>
        </Pressable>
      </View>

      <Text style={styles.sectionTitle}>
        {surface ? `${surface} · ` : ''}{records.length} record{records.length === 1 ? '' : 's'}
      </Text>
      {records.map((item) => <RecordCard key={item.id} item={item} onForget={forget} />)}
      {loaded && !records.length && !error ? (
        <Text style={styles.emptyInline}>
          {state === 'recording'
            ? 'Nothing captured yet on this surface.'
            : 'Nothing captured — and nothing is being recorded.'}
        </Text>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { padding: 12, paddingBottom: 30 },
  hero: { backgroundColor: theme.surfaceAlt, borderColor: theme.border, borderWidth: 1, borderRadius: 14, padding: 16, marginBottom: 12 },
  heroTitle: { color: theme.textDim, fontSize: 17, fontWeight: '800' },
  recording: { color: theme.warn },
  heroBody: { color: theme.textDim, fontSize: 13, lineHeight: 19, marginTop: 6 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: 10 },
  chip: { color: theme.textDim, borderColor: theme.border, borderWidth: 1, borderRadius: 10, paddingHorizontal: 9, paddingVertical: 6, fontSize: 11 },
  chipOn: { color: theme.accent, borderColor: theme.accentDim },
  actions: { flexDirection: 'row', gap: 8, marginBottom: 6 },
  actionButton: { flex: 1, minHeight: 44, borderRadius: 12, borderWidth: 1, borderColor: theme.accentDim, alignItems: 'center', justifyContent: 'center' },
  actionDisabled: { opacity: 0.4 },
  actionText: { color: theme.accent, fontSize: 14, fontWeight: '800' },
  dangerButton: { borderColor: theme.danger },
  dangerText: { color: theme.danger },
  sectionTitle: { color: theme.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 1, marginTop: 10, marginBottom: 7, textTransform: 'uppercase' },
  card: { backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, borderRadius: 14, padding: 13, marginBottom: 8 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  cardTitle: { color: theme.text, fontSize: 14, fontWeight: '800', flex: 1 },
  preview: { color: theme.text, fontSize: 13, lineHeight: 18, marginTop: 6 },
  meta: { color: theme.textDim, fontSize: 10, marginTop: 6 },
  badge: { color: theme.accent, borderColor: theme.accentDim, borderWidth: 1, borderRadius: 9, paddingHorizontal: 6, paddingVertical: 3, fontSize: 9 },
  forgetButton: { minHeight: 44, borderRadius: 11, borderWidth: 1, borderColor: theme.danger, alignItems: 'center', justifyContent: 'center', marginTop: 10 },
  forgetButtonText: { color: theme.danger, fontSize: 13, fontWeight: '800' },
  emptyInline: { color: theme.textDim, fontSize: 13, backgroundColor: theme.surface, borderRadius: 12, padding: 14 },
  loading: { marginVertical: 28 },
  errorBox: { backgroundColor: '#2a0d16', borderColor: theme.danger, borderWidth: 1, borderRadius: 12, padding: 12, marginBottom: 12 },
  errorText: { color: theme.danger, fontSize: 13 },
  noteBox: { backgroundColor: theme.surface, borderColor: theme.accentDim, borderWidth: 1, borderRadius: 12, padding: 12, marginBottom: 12 },
  noteText: { color: theme.accent, fontSize: 13 },
  primaryButton: { minHeight: 44, borderRadius: 22, backgroundColor: theme.accent, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 18, marginTop: 12 },
  primaryButtonText: { color: '#02121b', fontSize: 14, fontWeight: '800' },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  emptyTitle: { color: theme.text, fontSize: 20, fontWeight: '700', marginBottom: 8 },
  emptyBody: { color: theme.textDim, fontSize: 15, textAlign: 'center', marginBottom: 24 },
});
