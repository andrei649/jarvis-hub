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
  fetchHouseState,
  type HouseDevice,
  type HousePresence,
  type HouseRoom,
} from '../api/client';
import { useServer } from '../context/ServerContext';
import { theme } from '../theme';

const SECURITY_DOMAINS = new Set(['lock', 'alarm_control_panel', 'cover']);

function EmptyState({ onGoToSettings }: { onGoToSettings: () => void }) {
  return (
    <View style={styles.empty}>
      <Text style={styles.emptyTitle}>No hub connected</Text>
      <Text style={styles.emptyBody}>Connect this phone to see your home state.</Text>
      <Pressable style={styles.primaryButton} onPress={onGoToSettings}>
        <Text style={styles.primaryButtonText}>Open Settings</Text>
      </Pressable>
    </View>
  );
}

function RoomCard({ room }: { room: HouseRoom }) {
  return (
    <View style={styles.card}>
      <Text style={styles.cardTitle}>{room.name}</Text>
      <Text style={styles.meta}>{room.room_id}</Text>
    </View>
  );
}

function DeviceCard({ device }: { device: HouseDevice }) {
  const security = SECURITY_DOMAINS.has(device.domain);
  return (
    <View style={styles.card}>
      <View style={styles.row}>
        <View style={styles.grow}>
          <Text style={styles.cardTitle}>{device.entity_id}</Text>
          <Text style={styles.meta}>{device.room_id || 'no room'} · {device.domain}</Text>
        </View>
        <Text style={[styles.badge, security && styles.securityBadge]}>{device.state}</Text>
      </View>
      {security ? <Text style={styles.securityNote}>Strong confirmation required on the owner HUD</Text> : null}
    </View>
  );
}

function PresenceCard({ presence }: { presence: HousePresence }) {
  return (
    <View style={styles.card}>
      <View style={styles.row}>
        <View style={styles.grow}>
          <Text style={styles.cardTitle}>…{presence.occupant_id.slice(-8)}</Text>
          <Text style={styles.meta}>{presence.room_id || 'location withheld'} · {presence.privacy}</Text>
        </View>
        <Text style={styles.badge}>{presence.status}</Text>
      </View>
    </View>
  );
}

export function HouseScreen({
  onGoToSettings,
  onGoToApprovals,
}: {
  onGoToSettings: () => void;
  onGoToApprovals: () => void;
}) {
  const { config, configured } = useServer();
  const [rooms, setRooms] = useState<HouseRoom[]>([]);
  const [devices, setDevices] = useState<HouseDevice[]>([]);
  const [presence, setPresence] = useState<HousePresence[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [status, setStatus] = useState('disabled');
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!configured) return;
    setRefreshing(true);
    setError(null);
    try {
      const result = await fetchHouseState(config);
      setEnabled(result.enabled);
      setStatus(result.status);
      setReason(result.reason);
      setRooms(result.rooms);
      setDevices(result.devices);
      setPresence(result.presence);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load House Brain');
      setEnabled(false);
      setRooms([]);
      setDevices([]);
      setPresence([]);
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
        <Text style={styles.heroTitle}>Your home, at a glance</Text>
        <Text style={styles.heroBody}>Private identities stay hidden. This phone shows state and sends you to the governed approval inbox.</Text>
      </View>
      {error ? <View style={styles.errorBox}><Text style={styles.errorText}>{error}</Text></View> : null}
      {!loaded ? <ActivityIndicator style={styles.loading} color={theme.accent} /> : null}
      {loaded && !enabled && !error ? (
        <View style={styles.disabledBox}>
          <Text style={styles.disabledTitle}>House Brain is off</Text>
          <Text style={styles.disabledText}>{reason || 'Owner opt-in is required on the hub.'}</Text>
        </View>
      ) : null}
      {enabled && status !== 'live' ? (
        <View style={styles.warningBox}>
          <Text style={styles.warningTitle}>Live home state is unavailable</Text>
          <Text style={styles.disabledText}>{reason || 'Home Assistant is offline.'}</Text>
        </View>
      ) : null}
      {enabled ? (
        <>
          <Text style={styles.sectionTitle}>Rooms</Text>
          {rooms.map((room) => <RoomCard key={room.room_id} room={room} />)}
          {!rooms.length ? <Text style={styles.emptyInline}>No rooms reported.</Text> : null}

          <Text style={styles.sectionTitle}>Devices</Text>
          {devices.map((device) => <DeviceCard key={device.entity_id} device={device} />)}
          {!devices.length ? <Text style={styles.emptyInline}>No devices reported.</Text> : null}

          <Text style={styles.sectionTitle}>Presence</Text>
          {presence.map((item) => <PresenceCard key={item.occupant_id} presence={item} />)}
          {!presence.length ? <Text style={styles.emptyInline}>No consented presence state available.</Text> : null}

          <View style={styles.approvalCard}>
            <Text style={styles.approvalTitle}>Governed actions</Text>
            <Text style={styles.approvalBody}>Review queued home proposals in Approvals. Strong confirmation stays on the owner HUD.</Text>
            <Pressable accessibilityRole="button" style={styles.primaryButton} onPress={onGoToApprovals}>
              <Text style={styles.primaryButtonText}>Open Approvals</Text>
            </Pressable>
          </View>
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
  sectionTitle: { color: theme.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 1, marginTop: 14, marginBottom: 7, textTransform: 'uppercase' },
  card: { backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, borderRadius: 14, padding: 13, marginBottom: 8 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  grow: { flex: 1 },
  cardTitle: { color: theme.text, fontSize: 15, fontWeight: '700' },
  meta: { color: theme.textDim, fontSize: 11, marginTop: 3 },
  badge: { color: theme.accent, borderColor: theme.accentDim, borderWidth: 1, borderRadius: 10, paddingHorizontal: 7, paddingVertical: 3, fontSize: 10 },
  securityBadge: { color: theme.warn, borderColor: theme.warn },
  securityNote: { color: theme.warn, fontSize: 11, marginTop: 8 },
  approvalCard: { backgroundColor: theme.surfaceAlt, borderColor: theme.accentDim, borderWidth: 1, borderRadius: 14, padding: 16, marginTop: 16 },
  approvalTitle: { color: theme.text, fontSize: 16, fontWeight: '800' },
  approvalBody: { color: theme.textDim, fontSize: 13, lineHeight: 18, marginTop: 5 },
  primaryButton: { minHeight: 44, borderRadius: 22, backgroundColor: theme.accent, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 18, marginTop: 12 },
  primaryButtonText: { color: '#02121b', fontSize: 14, fontWeight: '800' },
  errorBox: { backgroundColor: '#2a0d16', borderColor: theme.danger, borderWidth: 1, borderRadius: 12, padding: 12, marginBottom: 12 },
  errorText: { color: theme.danger, fontSize: 13 },
  disabledBox: { backgroundColor: theme.surface, borderColor: theme.warn, borderWidth: 1, borderRadius: 14, padding: 18 },
  warningBox: { backgroundColor: theme.surface, borderColor: theme.warn, borderWidth: 1, borderRadius: 14, padding: 16, marginBottom: 12 },
  disabledTitle: { color: theme.warn, fontSize: 16, fontWeight: '800' },
  warningTitle: { color: theme.warn, fontSize: 15, fontWeight: '800' },
  disabledText: { color: theme.textDim, fontSize: 13, marginTop: 5, lineHeight: 18 },
  emptyInline: { color: theme.textDim, fontSize: 13, backgroundColor: theme.surface, borderRadius: 12, padding: 14 },
  loading: { marginVertical: 28 },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  emptyTitle: { color: theme.text, fontSize: 20, fontWeight: '700', marginBottom: 8 },
  emptyBody: { color: theme.textDim, fontSize: 15, textAlign: 'center', marginBottom: 24 },
});
