import React, { useCallback, useEffect, useMemo, useState } from 'react';
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
  fetchMediaDevices,
  fetchMediaSessions,
  presentMedia,
  registerMediaDevice,
  removeMediaDevice,
  restoreMedia,
  type MediaActionOutcome,
  type MediaContentType,
  type MediaDevice,
  type MediaMode,
  type MediaPresentBody,
  type MediaPrivacy,
  type MediaSession,
  type MediaUrgency,
} from '../api/client';
import { useServer } from '../context/ServerContext';
import { theme } from '../theme';

const CONTENT_TYPES: MediaContentType[] = ['url', 'local', 'catalog', 'query'];
const MODES: MediaMode[] = ['play', 'show', 'announce'];
const PRIVACY: MediaPrivacy[] = ['ambient', 'household', 'private'];
const URGENCY: MediaUrgency[] = ['low', 'normal', 'high'];
const DEVICE_KINDS = ['chromecast', 'spotify_connect', 'browser_tab', 'local', 'speaker', 'tv'];

type Busy = 'present' | 'restore' | 'register' | 'remove' | null;

function Choice<T extends string>({
  label,
  values,
  value,
  onChange,
}: {
  label: string;
  values: readonly T[];
  value: T;
  onChange: (next: T) => void;
}) {
  return (
    <View style={styles.choiceGroup} accessibilityLabel={label}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <View style={styles.choiceRow}>
        {values.map((item) => (
          <Pressable
            key={item}
            accessibilityRole="button"
            accessibilityState={{ selected: value === item }}
            style={[styles.choice, value === item && styles.choiceActive]}
            onPress={() => onChange(item)}
          >
            <Text style={[styles.choiceText, value === item && styles.choiceTextActive]}>{item}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

function Outcome({ value }: { value: MediaActionOutcome | null }) {
  if (!value) return null;
  const message =
    value.kind === 'verified'
      ? `verified success · ${value.deviceId || 'device'} · ${value.state || 'verified'}`
      : value.kind === 'unverified'
        ? 'unverified · success not claimed'
        : value.kind === 'queued'
          ? `queued for approval · ${value.reason || 'approval_required'}`
          : value.kind === 'refused'
            ? `refused · ${value.reason || 'media_action_failed'}`
            : value.kind === 'disabled'
              ? `disabled · ${value.reason || 'owner opt-in required'}`
              : `unknown outcome · ${value.reason || value.status || 'no status'}`;
  const color = value.kind === 'verified' ? theme.ok : value.kind === 'queued' || value.kind === 'unverified' ? theme.warn : theme.danger;
  return (
    <View style={[styles.outcome, { borderColor: color }]} accessibilityRole="alert">
      <Text style={[styles.outcomeText, { color }]}>{message}</Text>
    </View>
  );
}

function EmptyState({ onGoToSettings }: { onGoToSettings: () => void }) {
  return (
    <View style={styles.empty}>
      <Text style={styles.emptyTitle}>No hub connected</Text>
      <Text style={styles.emptyBody}>Connect this phone before opening the governed Media Director.</Text>
      <Pressable style={styles.primaryButton} onPress={onGoToSettings}>
        <Text style={styles.primaryButtonText}>Open Settings</Text>
      </Pressable>
    </View>
  );
}

function DeviceCard({ device, selected, onSelect }: { device: MediaDevice; selected: boolean; onSelect: () => void }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected }}
      style={[styles.card, selected && styles.selectedCard]}
      onPress={onSelect}
    >
      <View style={styles.row}>
        <View style={styles.grow}>
          <Text style={styles.cardTitle}>{device.name}</Text>
          <Text style={styles.meta}>{device.id}</Text>
        </View>
        <Text style={styles.badge}>{device.kind}</Text>
      </View>
      <Text style={styles.meta}>{device.room || 'no room'} · {device.supports.join(', ') || 'no supported mode'}</Text>
    </Pressable>
  );
}

function SessionCard({ session, busy, onRestore }: { session: MediaSession; busy: boolean; onRestore: () => void }) {
  return (
    <View style={styles.card}>
      <View style={styles.row}>
        <View style={styles.grow}>
          <Text style={styles.cardTitle}>{session.device_id}</Text>
          <Text style={styles.meta}>{session.state || 'unknown'} · {session.mode || 'unknown mode'}</Text>
        </View>
        <Pressable
          accessibilityLabel={`Restore ${session.device_id}`}
          accessibilityRole="button"
          disabled={busy}
          style={[styles.smallButton, busy && styles.disabled]}
          onPress={onRestore}
        >
          <Text style={styles.smallButtonText}>{busy ? 'restoring…' : 'restore'}</Text>
        </Pressable>
      </View>
      <Text style={styles.contentRef} numberOfLines={2}>
        {session.content.type}:{session.content.value}
      </Text>
      {session.duration_seconds ? <Text style={styles.meta}>{session.duration_seconds}s duration</Text> : null}
    </View>
  );
}

export function MediaScreen({ onGoToSettings }: { onGoToSettings: () => void }) {
  const { config, configured } = useServer();
  const [devices, setDevices] = useState<MediaDevice[]>([]);
  const [sessions, setSessions] = useState<MediaSession[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [hint, setHint] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const [outcome, setOutcome] = useState<MediaActionOutcome | null>(null);

  const [contentType, setContentType] = useState<MediaContentType>('url');
  const [contentValue, setContentValue] = useState('');
  const [target, setTarget] = useState('');
  const [mode, setMode] = useState<MediaMode>('play');
  const [privacy, setPrivacy] = useState<MediaPrivacy>('household');
  const [urgency, setUrgency] = useState<MediaUrgency>('normal');
  const [duration, setDuration] = useState('');

  const [deviceId, setDeviceId] = useState('');
  const [deviceName, setDeviceName] = useState('');
  const [deviceKind, setDeviceKind] = useState('local');
  const [deviceRoom, setDeviceRoom] = useState('');
  const [deviceSupports, setDeviceSupports] = useState('play');
  const [adminMessage, setAdminMessage] = useState('');

  const load = useCallback(async () => {
    if (!configured) return;
    setRefreshing(true);
    setError(null);
    try {
      const [deviceResult, sessionResult] = await Promise.all([
        fetchMediaDevices(config),
        fetchMediaSessions(config),
      ]);
      const nextEnabled = deviceResult.enabled && sessionResult.enabled;
      setDevices(nextEnabled ? deviceResult.devices : []);
      setSessions(nextEnabled ? sessionResult.sessions : []);
      setEnabled(nextEnabled);
      setHint(deviceResult.hint || sessionResult.hint);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load Media Director');
      setDevices([]);
      setSessions([]);
      setEnabled(false);
    } finally {
      setLoaded(true);
      setRefreshing(false);
    }
  }, [config, configured]);

  useEffect(() => {
    load();
  }, [load]);

  const selectedDevice = useMemo(() => devices.find((device) => device.id === target), [devices, target]);
  const availableModes = useMemo(
    () => (selectedDevice ? selectedDevice.supports.filter((item) => MODES.includes(item)) : MODES),
    [selectedDevice],
  );
  const contentLimit = contentType === 'query' ? 256 : 2048;
  const parsedDuration = duration.trim() ? Number(duration) : undefined;
  const durationValid = parsedDuration === undefined || (Number.isFinite(parsedDuration) && parsedDuration >= 1 && parsedDuration <= 86400);
  const canPresent =
    enabled &&
    !!contentValue.trim() &&
    !!selectedDevice &&
    availableModes.includes(mode) &&
    durationValid &&
    busy === null;

  const chooseTarget = (device: MediaDevice) => {
    setTarget(device.id);
    const nextModes = device.supports.filter((item) => MODES.includes(item));
    if (!nextModes.includes(mode)) setMode(nextModes[0] || 'play');
  };

  const present = async () => {
    if (!canPresent) return;
    const body: MediaPresentBody = {
      content: { type: contentType, value: contentValue.trim() },
      target,
      mode,
      privacy,
      urgency,
      ...(parsedDuration === undefined ? {} : { duration_seconds: parsedDuration }),
    };
    setBusy('present');
    setError(null);
    setOutcome(null);
    try {
      setOutcome(await presentMedia(config, body));
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Media presentation failed');
    } finally {
      setBusy(null);
    }
  };

  const restore = async (deviceIdToRestore: string) => {
    if (busy !== null) return;
    setBusy('restore');
    setError(null);
    setOutcome(null);
    try {
      setOutcome(await restoreMedia(config, deviceIdToRestore));
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Media restore failed');
    } finally {
      setBusy(null);
    }
  };

  const register = async () => {
    if (!config.adminToken.trim() || !deviceId.trim() || !deviceName.trim() || busy !== null) return;
    const supports = Array.from(
      new Set(
        deviceSupports
          .split(',')
          .map((item) => item.trim())
          .filter((item): item is MediaMode => MODES.includes(item as MediaMode)),
      ),
    ).slice(0, 16);
    if (!supports.length) {
      setAdminMessage('Add at least one supported mode: play, show, or announce.');
      return;
    }
    setBusy('register');
    setAdminMessage('');
    try {
      const result = await registerMediaDevice(config, {
        id: deviceId.trim(),
        name: deviceName.trim(),
        kind: deviceKind,
        room: deviceRoom.trim(),
        supports,
      });
      setAdminMessage(result.enabled && result.device ? 'Device registered.' : result.error || result.hint || 'Registration refused.');
      await load();
    } catch (e) {
      setAdminMessage(e instanceof ApiError ? e.message : 'Device registration failed');
    } finally {
      setBusy(null);
    }
  };

  const remove = async (id: string) => {
    if (!config.adminToken.trim() || busy !== null) return;
    setBusy('remove');
    setAdminMessage('');
    try {
      const result = await removeMediaDevice(config, id);
      setAdminMessage(result.removed ? `Removed ${result.removed}.` : result.error || result.hint || 'Removal refused.');
      await load();
    } catch (e) {
      setAdminMessage(e instanceof ApiError ? e.message : 'Device removal failed');
    } finally {
      setBusy(null);
    }
  };

  if (!configured) return <EmptyState onGoToSettings={onGoToSettings} />;

  return (
    <ScrollView
      style={styles.flex}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} tintColor={theme.accent} />}
    >
      <View style={styles.hero}>
        <Text style={styles.heroTitle}>Governed presentation</Text>
        <Text style={styles.heroBody}>Metadata only. Every present and restore is an explicit, kernel-mediated action.</Text>
      </View>

      {error ? (
        <View style={styles.errorBox}><Text style={styles.errorText}>{error}</Text></View>
      ) : null}
      {!loaded ? <ActivityIndicator style={styles.loading} color={theme.accent} /> : null}
      {loaded && !enabled && !error && !refreshing ? (
        <View style={styles.disabledBox}>
          <Text style={styles.disabledTitle}>Media Director is off</Text>
          <Text style={styles.disabledText}>{hint || 'Owner opt-in is required on the hub.'}</Text>
        </View>
      ) : null}

      {enabled ? (
        <>
          <Text style={styles.sectionTitle}>Devices</Text>
          {devices.map((device) => (
            <DeviceCard key={device.id} device={device} selected={target === device.id} onSelect={() => chooseTarget(device)} />
          ))}
          {!devices.length ? <Text style={styles.emptyInline}>No owner-curated devices are registered.</Text> : null}

          <Text style={styles.sectionTitle}>Present</Text>
          <View style={styles.formCard}>
            <Choice label="Content type" values={CONTENT_TYPES} value={contentType} onChange={(next) => { setContentType(next); setContentValue(''); }} />
            <Text style={styles.fieldLabel}>Content reference</Text>
            <TextInput
              accessibilityLabel="Content reference"
              style={styles.input}
              value={contentValue}
              maxLength={contentLimit}
              autoCapitalize="none"
              placeholder="URL, local path, catalog id, or query"
              placeholderTextColor={theme.textDim}
              onChangeText={setContentValue}
            />
            <Choice label="Mode" values={availableModes} value={mode} onChange={setMode} />
            <Choice label="Privacy" values={PRIVACY} value={privacy} onChange={setPrivacy} />
            <Choice label="Urgency" values={URGENCY} value={urgency} onChange={setUrgency} />
            <Text style={styles.fieldLabel}>Duration seconds · optional, 1–86400</Text>
            <TextInput
              accessibilityLabel="Duration seconds"
              style={[styles.input, !durationValid && styles.invalidInput]}
              value={duration}
              maxLength={5}
              keyboardType="number-pad"
              placeholder="optional"
              placeholderTextColor={theme.textDim}
              onChangeText={setDuration}
            />
            <Pressable
              accessibilityLabel="Present media"
              accessibilityRole="button"
              disabled={!canPresent}
              style={[styles.primaryButton, !canPresent && styles.disabled]}
              onPress={present}
            >
              <Text style={styles.primaryButtonText}>{busy === 'present' ? 'presenting…' : 'present'}</Text>
            </Pressable>
          </View>
          <Outcome value={outcome} />

          <Text style={styles.sectionTitle}>Sessions</Text>
          {sessions.map((session) => (
            <SessionCard
              key={session.device_id}
              session={session}
              busy={busy !== null}
              onRestore={() => restore(session.device_id)}
            />
          ))}
          {!sessions.length ? <Text style={styles.emptyInline}>No active media sessions.</Text> : null}

          <Text style={styles.sectionTitle}>Admin · device registry</Text>
          {!config.adminToken.trim() ? (
            <View style={styles.adminNotice}>
              <Text style={styles.disabledTitle}>Admin token required</Text>
              <Text style={styles.disabledText}>Add the hub admin token in Settings to register or remove devices.</Text>
              <Pressable style={styles.secondaryButton} onPress={onGoToSettings}>
                <Text style={styles.secondaryButtonText}>Open Settings</Text>
              </Pressable>
            </View>
          ) : (
            <View style={styles.formCard}>
              {devices.map((device) => (
                <View style={styles.adminDevice} key={`admin:${device.id}`}>
                  <View style={styles.grow}><Text style={styles.cardTitle}>{device.name}</Text><Text style={styles.meta}>{device.id}</Text></View>
                  <Pressable
                    accessibilityLabel={`Remove ${device.id}`}
                    disabled={busy !== null}
                    style={[styles.dangerButton, busy !== null && styles.disabled]}
                    onPress={() => remove(device.id)}
                  >
                    <Text style={styles.dangerButtonText}>remove</Text>
                  </Pressable>
                </View>
              ))}
              <Text style={styles.fieldLabel}>Device id</Text>
              <TextInput style={styles.input} value={deviceId} maxLength={64} autoCapitalize="none" onChangeText={setDeviceId} />
              <Text style={styles.fieldLabel}>Display name</Text>
              <TextInput style={styles.input} value={deviceName} maxLength={120} onChangeText={setDeviceName} />
              <Choice label="Device kind" values={DEVICE_KINDS} value={deviceKind} onChange={setDeviceKind} />
              <Text style={styles.fieldLabel}>Room · optional</Text>
              <TextInput style={styles.input} value={deviceRoom} maxLength={64} onChangeText={setDeviceRoom} />
              <Text style={styles.fieldLabel}>Supported modes · comma separated</Text>
              <TextInput style={styles.input} value={deviceSupports} maxLength={128} autoCapitalize="none" onChangeText={setDeviceSupports} />
              <Pressable
                accessibilityLabel="Register media device"
                disabled={!deviceId.trim() || !deviceName.trim() || busy !== null}
                style={[styles.primaryButton, (!deviceId.trim() || !deviceName.trim() || busy !== null) && styles.disabled]}
                onPress={register}
              >
                <Text style={styles.primaryButtonText}>{busy === 'register' ? 'registering…' : 'register device'}</Text>
              </Pressable>
              {adminMessage ? <Text style={styles.adminMessage}>{adminMessage}</Text> : null}
            </View>
          )}
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
  selectedCard: { borderColor: theme.accent },
  formCard: { backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, borderRadius: 14, padding: 13, gap: 8 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  grow: { flex: 1 },
  cardTitle: { color: theme.text, fontSize: 15, fontWeight: '700' },
  meta: { color: theme.textDim, fontSize: 11, marginTop: 3 },
  badge: { color: theme.accent, borderColor: theme.accentDim, borderWidth: 1, borderRadius: 10, paddingHorizontal: 7, paddingVertical: 3, fontSize: 10 },
  contentRef: { color: theme.text, backgroundColor: theme.surfaceAlt, borderRadius: 8, padding: 8, marginTop: 9, fontSize: 12 },
  fieldLabel: { color: theme.textDim, fontSize: 11, fontWeight: '700', marginTop: 3, textTransform: 'uppercase' },
  input: { color: theme.text, backgroundColor: theme.surfaceAlt, borderColor: theme.border, borderWidth: 1, borderRadius: 10, minHeight: 43, paddingHorizontal: 11, paddingVertical: 8 },
  invalidInput: { borderColor: theme.danger },
  choiceGroup: { gap: 5 },
  choiceRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  choice: { borderColor: theme.border, borderWidth: 1, borderRadius: 16, paddingHorizontal: 10, paddingVertical: 7, backgroundColor: theme.surfaceAlt },
  choiceActive: { borderColor: theme.accent, backgroundColor: theme.userBubble },
  choiceText: { color: theme.textDim, fontSize: 11, fontWeight: '700' },
  choiceTextActive: { color: theme.accent },
  primaryButton: { minHeight: 44, borderRadius: 22, backgroundColor: theme.accent, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 18, marginTop: 4 },
  primaryButtonText: { color: '#02121b', fontSize: 14, fontWeight: '800' },
  secondaryButton: { minHeight: 40, borderRadius: 20, borderColor: theme.border, borderWidth: 1, alignItems: 'center', justifyContent: 'center', marginTop: 10 },
  secondaryButtonText: { color: theme.text, fontWeight: '700' },
  smallButton: { borderRadius: 16, borderColor: theme.accentDim, borderWidth: 1, paddingHorizontal: 12, paddingVertical: 7 },
  smallButtonText: { color: theme.accent, fontSize: 11, fontWeight: '800' },
  disabled: { opacity: 0.4 },
  outcome: { borderWidth: 1, borderRadius: 12, padding: 11, marginTop: 10 },
  outcomeText: { fontSize: 12, fontWeight: '700' },
  errorBox: { backgroundColor: '#2a0d16', borderColor: theme.danger, borderWidth: 1, borderRadius: 12, padding: 12, marginBottom: 12 },
  errorText: { color: theme.danger, fontSize: 13 },
  disabledBox: { backgroundColor: theme.surface, borderColor: theme.warn, borderWidth: 1, borderRadius: 14, padding: 18 },
  adminNotice: { backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, borderRadius: 14, padding: 16 },
  disabledTitle: { color: theme.warn, fontSize: 16, fontWeight: '800' },
  disabledText: { color: theme.textDim, fontSize: 13, marginTop: 5, lineHeight: 18 },
  emptyInline: { color: theme.textDim, fontSize: 13, backgroundColor: theme.surface, borderRadius: 12, padding: 14 },
  loading: { marginVertical: 28 },
  adminDevice: { flexDirection: 'row', alignItems: 'center', borderBottomColor: theme.border, borderBottomWidth: 1, paddingBottom: 9, marginBottom: 2 },
  dangerButton: { borderColor: theme.danger, borderWidth: 1, borderRadius: 16, paddingHorizontal: 10, paddingVertical: 6 },
  dangerButtonText: { color: theme.danger, fontSize: 11, fontWeight: '800' },
  adminMessage: { color: theme.textDim, fontSize: 12, marginTop: 4 },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  emptyTitle: { color: theme.text, fontSize: 20, fontWeight: '700', marginBottom: 8 },
  emptyBody: { color: theme.textDim, fontSize: 15, textAlign: 'center', marginBottom: 24 },
});
