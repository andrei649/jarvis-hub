import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import {
  ApiError,
  fetchCameraEvents,
  fetchCameraStatus,
  searchCameraEvents,
  type CameraEvent,
} from '../api/client';
import { useServer } from '../context/ServerContext';
import { theme } from '../theme';

function EmptyState({ onGoToSettings }: { onGoToSettings: () => void }) {
  return (
    <View style={styles.empty}>
      <Text style={styles.emptyTitle}>No hub connected</Text>
      <Text style={styles.emptyBody}>Connect this phone to review local camera events.</Text>
      <Pressable style={styles.primaryButton} onPress={onGoToSettings}>
        <Text style={styles.primaryButtonText}>Open Settings</Text>
      </Pressable>
    </View>
  );
}

function EventCard({ event }: { event: CameraEvent }) {
  const confidence = Math.round(event.confidence * 100);
  const occurred = new Date(event.occurred_at * 1000).toLocaleString();
  return (
    <View style={styles.card}>
      <View style={styles.row}>
        <View style={styles.grow}>
          <Text style={styles.cardTitle}>{event.camera_id}</Text>
          <Text style={styles.meta}>{occurred} · {event.zone || event.room_id || 'no zone'}</Text>
        </View>
        <Text style={styles.badge}>{event.label} · {confidence}%</Text>
      </View>
      {event.description ? <Text style={styles.description}>{event.description}</Text> : null}
      {event.description_provenance ? (
        <Text style={styles.provenance}>{event.description_provenance.split('_').join(' ')}</Text>
      ) : null}
    </View>
  );
}

export function CameraScreen({ onGoToSettings }: { onGoToSettings: () => void }) {
  const { config, configured } = useServer();
  const [events, setEvents] = useState<CameraEvent[]>([]);
  const [enabled, setEnabled] = useState(false);
  const [status, setStatus] = useState('disabled');
  const [reason, setReason] = useState('');
  const [sourceStatus, setSourceStatus] = useState('unavailable');
  const [query, setQuery] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [searching, setSearching] = useState(false);
  const [searchMode, setSearchMode] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!configured) return;
    setRefreshing(true);
    setError(null);
    try {
      const [health, recent] = await Promise.all([
        fetchCameraStatus(config),
        fetchCameraEvents(config),
      ]);
      setEnabled(health.enabled);
      setStatus(health.status);
      setReason(health.reason);
      setSourceStatus(health.source?.status || 'unavailable');
      setEvents(recent.events);
      setSearchMode(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load camera events');
      setEnabled(false);
      setEvents([]);
    } finally {
      setLoaded(true);
      setRefreshing(false);
    }
  }, [config, configured]);

  useEffect(() => {
    load();
  }, [load]);

  const search = useCallback(async () => {
    const text = query.trim();
    if (!text || searching) return;
    setSearching(true);
    setError(null);
    try {
      const result = await searchCameraEvents(config, text, 100);
      setEvents(result.events);
      setSearchMode(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Camera search failed');
    } finally {
      setSearching(false);
    }
  }, [config, query, searching]);

  if (!configured) return <EmptyState onGoToSettings={onGoToSettings} />;

  return (
    <ScrollView
      style={styles.flex}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} tintColor={theme.accent} />}
    >
      <View style={styles.hero}>
        <Text style={styles.heroTitle}>Private events, not a live feed</Text>
        <Text style={styles.heroBody}>Only bounded redacted metadata leaves the hub. People remain anonymous.</Text>
      </View>
      {error ? <View style={styles.errorBox}><Text style={styles.errorText}>{error}</Text></View> : null}
      {!loaded ? <ActivityIndicator style={styles.loading} color={theme.accent} /> : null}
      {loaded && !enabled && !error ? (
        <View style={styles.disabledBox}>
          <Text style={styles.disabledTitle}>Camera Intelligence is off</Text>
          <Text style={styles.disabledText}>{reason || 'Owner opt-in and household consent are required on the hub.'}</Text>
        </View>
      ) : null}
      {enabled ? (
        <>
          <View style={styles.statusRow}>
            <Text style={styles.statusText}>{status}</Text>
            <Text style={styles.statusText}>source · {sourceStatus}</Text>
          </View>
          <View style={styles.searchRow}>
            <TextInput
              accessibilityLabel="camera search"
              value={query}
              onChangeText={setQuery}
              maxLength={256}
              placeholder="courier yesterday"
              placeholderTextColor={theme.textDim}
              style={styles.searchInput}
              returnKeyType="search"
              onSubmitEditing={search}
            />
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Search events"
              disabled={!query.trim() || searching}
              onPress={search}
              style={[styles.searchButton, (!query.trim() || searching) && styles.buttonDisabled]}
            >
              <Text style={styles.searchButtonText}>{searching ? 'Searching…' : 'Search events'}</Text>
            </Pressable>
          </View>
          <Text style={styles.sectionTitle}>{searchMode ? 'Search results' : 'Recent events'}</Text>
          {events.map((event) => <EventCard key={`${event.camera_id}:${event.event_id}`} event={event} />)}
          {!events.length ? <Text style={styles.emptyInline}>No matching camera events.</Text> : null}
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
  statusRow: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 10 },
  statusText: { color: theme.textDim, fontSize: 11, fontWeight: '700', textTransform: 'uppercase' },
  searchRow: { flexDirection: 'row', gap: 8, marginBottom: 12 },
  searchInput: { flex: 1, minHeight: 44, color: theme.text, backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, borderRadius: 12, paddingHorizontal: 12 },
  searchButton: { minHeight: 44, borderRadius: 12, backgroundColor: theme.accent, justifyContent: 'center', paddingHorizontal: 14 },
  searchButtonText: { color: '#02121b', fontSize: 12, fontWeight: '800' },
  buttonDisabled: { opacity: 0.45 },
  sectionTitle: { color: theme.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 1, marginTop: 8, marginBottom: 7, textTransform: 'uppercase' },
  card: { backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, borderRadius: 14, padding: 13, marginBottom: 8 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  grow: { flex: 1 },
  cardTitle: { color: theme.text, fontSize: 15, fontWeight: '700' },
  meta: { color: theme.textDim, fontSize: 11, marginTop: 3 },
  badge: { color: theme.accent, borderColor: theme.accentDim, borderWidth: 1, borderRadius: 10, paddingHorizontal: 7, paddingVertical: 3, fontSize: 10 },
  description: { color: theme.text, fontSize: 13, lineHeight: 18, marginTop: 9 },
  provenance: { color: theme.textDim, fontSize: 10, marginTop: 4 },
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
