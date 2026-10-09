import React, { useEffect, useRef, useState } from 'react';
import { AppState, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { readBriefingWall, type WallSnapshot, type WallSource } from '../api/briefingWall';
import { BriefingField } from '../components/BriefingField';
import { Text } from '../components/ThemedText';
import { useServer } from '../context/ServerContext';
import { useThemeStyles, type Theme } from '../theme';
import type { FieldVoice } from '../voice/briefingField';
import { wallState } from '../voice/wallState';

type Props = {
  contextKey: string;
  voice: FieldVoice;
  transcript: string | null;
  onExit: () => void;
  children?: React.ReactNode;
};
const valueOf = <T,>(source: WallSource<T> | undefined): T | null => source?.status === 'available' ? source.value : null;

/** Every room visit has its own evidence, visibility choice and in-flight reads. */
export function BriefingWall(props: Props) {
  const { chatScope, connectionEpoch } = useServer();
  return <ScopedBriefingWall key={JSON.stringify([chatScope, connectionEpoch, props.contextKey])} {...props} />;
}

function ScopedBriefingWall({ voice, transcript, onExit, children }: Props) {
  const { config, configured, ready } = useServer();
  const { theme, styles } = useThemeStyles(makeStyles);
  const [snapshot, setSnapshot] = useState<WallSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(AppState.currentState === 'active');
  const [shown, setShown] = useState(false);
  const refresh = useRef<(() => void) | null>(null);

  useEffect(() => {
    let mounted = true;
    let generation = 0;
    let request: AbortController | null = null;
    let poll: ReturnType<typeof setTimeout> | null = null;
    const cancel = () => {
      generation++;
      request?.abort(); request = null;
      if (poll) clearTimeout(poll);
      poll = null;
    };
    const load = async () => {
      cancel();
      setSnapshot(null);
      if (!configured || !ready || AppState.currentState !== 'active') { setLoading(false); return; }
      const turn = generation;
      const controller = new AbortController(); request = controller;
      setLoading(true);
      const current = () => mounted && generation === turn && !controller.signal.aborted && AppState.currentState === 'active';
      try {
        const result = await readBriefingWall(config, controller.signal);
        if (current()) setSnapshot(result);
      } catch { /* Missing evidence remains unknown, including an aggregate cancellation. */ }
      finally {
        if (current()) {
          request = null;
          setLoading(false);
          poll = setTimeout(() => { void load(); }, 15_000);
        }
      }
    };
    refresh.current = () => { void load(); };
    void load();
    const subscription = AppState.addEventListener('change', next => {
      const foreground = next === 'active';
      setActive(foreground);
      setShown(false);
      if (foreground) void load();
      else { cancel(); setSnapshot(null); setLoading(false); }
    });
    return () => { mounted = false; cancel(); refresh.current = null; subscription.remove(); };
  }, [config, configured, ready]);

  const agents = valueOf(snapshot?.agents);
  const tasks = valueOf(snapshot?.tasks);
  const health = valueOf(snapshot?.health);
  const trust = valueOf(snapshot?.trust);
  const locality = valueOf(snapshot?.locality);
  const executing = agents?.filter(agent => ['busy', 'active'].includes(agent.status.trim().toLowerCase())).length;
  const state = wallState({ agents: agents ?? [], tasks: tasks ?? [], voice, serverUp: health?.up === true });
  const stateWord = voice.status === 'stopping' ? 'stopping microphone'
    : state.word === 'offline' ? loading ? 'checking hub' : 'status unavailable'
    : state.word === 'standing by' && (agents === null || tasks === null) ? 'activity unknown' : state.word;
  const sourceLabel = (source: WallSource<unknown> | undefined) => !active ? 'paused'
    : loading ? 'refreshing' : source?.status === 'available' ? 'reported' : 'unavailable';
  const lastChecked = snapshot ? Math.max(...Object.values(snapshot).map(source => source.checkedAt)) : null;
  const statusColor = state.tone === 'live' ? theme.ok : state.tone === 'work' ? theme.accent
    : state.tone === 'bad' ? theme.warn : theme.textDim;

  const row = (label: string, value: string | number | boolean | null | undefined, note?: string) => (
    <View key={label} style={styles.metric}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={styles.metricValue} accessibilityLabel={`${label}: ${value ?? 'unavailable'}`}>
        {value == null ? '—' : String(value)}
      </Text>
      {note ? <Text style={styles.note}>{note}</Text> : null}
    </View>
  );

  return (
    <ScrollView style={styles.flex} contentContainerStyle={styles.content}>
      <View style={styles.top}>
        <View style={styles.heading}>
          <Text style={styles.brand}>N.E.R.V.A.</Text>
          <Text style={styles.subtitle}>Briefing · local-first cabinet</Text>
        </View>
        <Pressable accessibilityLabel="Close briefing and review draft" onPress={onExit} style={styles.button}>
          <Text style={styles.buttonText}>Review draft</Text>
        </Pressable>
      </View>
      <Text accessibilityRole="header" style={[styles.state, { color: statusColor }]}>{active ? stateWord : 'briefing paused'}</Text>
      <Text style={styles.note}>{loading ? 'Refreshing source evidence…' : !active ? 'Updates paused in background.'
        : lastChecked ? `Checked ${new Date(lastChecked).toLocaleTimeString()}` : 'No current source evidence.'}</Text>

      <View style={styles.chips}>
        <View style={styles.chip}>{row('Agent ops · running in feed', tasks?.length)}</View>
        <View style={styles.chip}>{row('Cabinet · roster', agents?.length)}</View>
      </View>
      <BriefingField agents={agents ?? []} tasks={tasks ?? []} voice={voice} active={active}
        agentsAvailable={agents !== null} tasksAvailable={tasks !== null} />

      <View style={styles.cards}>
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Cabinet · reported activity</Text>
          {row('Agents in roster', agents?.length, sourceLabel(snapshot?.agents))}
          {row('Reported active', executing, 'Agent status reports; not a hardware measurement.')}
          {row('Running in task feed', tasks?.length, 'Running entries among the latest 30 tasks.')}
        </View>
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Recorded routing</Text>
          {row('Served locally', locality?.percent == null ? null : `${locality.percent}%`, 'Measured across recorded routed runs, not this conversation.')}
          {row('Local / cloud runs', locality ? `${locality.local} / ${locality.cloud}` : null)}
          {row('Unknown routes', locality?.unknown, 'Excluded from the percentage.')}
        </View>
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Subsystem status</Text>
          {row('Hub liveness', health ? 'reachable' : null)}
          {row('Mic trust', trust ? trust.mic === 'on' ? 'on' : 'muted' : null, 'Dictation checks permission and trust again before recording.')}
          {row('Strict-local policy', trust ? trust.strictLocal ? 'on' : 'off' : null, 'Reported policy; not a locality measurement.')}
          {row('Cloud configured', trust ? trust.cloudAvailable ? 'reported' : 'none reported' : null)}
        </View>
      </View>

      <View style={styles.voice}>
        <Text style={styles.cardTitle}>Dictate to draft</Text>
        <Text style={styles.note}>Review the draft in Chat before sending.</Text>
        {children}
        {shown && transcript ? <Text style={styles.transcript}>{transcript}</Text>
          : <Text style={styles.note}>{shown ? 'No dictated line in this visit.' : 'Transcript hidden · room mode'}</Text>}
        <Pressable style={styles.button} disabled={!active} onPress={() => setShown(value => !value)}
          accessibilityLabel={shown ? 'Hide room transcript' : 'Show room transcript'}>
          <Text style={styles.buttonText}>{shown ? 'Hide transcript' : 'Show transcript'}</Text>
        </Pressable>
      </View>
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Source evidence</Text>
        {(['health', 'agents', 'tasks', 'trust', 'locality'] as const).map(source => row(source, sourceLabel(snapshot?.[source])))}
        <Text style={styles.note}>Read-only updates every 15 seconds after the previous refresh finishes.</Text>
        <Pressable style={styles.button} disabled={loading || !active || !configured || !ready}
          accessibilityLabel="Refresh briefing" onPress={() => refresh.current?.()}>
          <Text style={styles.buttonText}>Refresh now</Text>
        </Pressable>
      </View>
    </ScrollView>
  );
}

const makeStyles = (theme: Theme) => StyleSheet.create({
  flex: { flex: 1 }, content: { padding: 14, gap: 14, paddingBottom: 24 },
  top: { flexDirection: 'row', alignItems: 'center', gap: 10, justifyContent: 'space-between' },
  heading: { flex: 1 }, brand: { color: theme.accent, fontSize: 22, fontWeight: '800', letterSpacing: 2 },
  subtitle: { color: theme.textDim, fontSize: 12, marginTop: 4 },
  state: { fontSize: 24, fontWeight: '700' }, note: { color: theme.textDim, fontSize: 12, lineHeight: 18 },
  chips: { flexDirection: 'row', gap: 10, flexWrap: 'wrap' },
  chip: { flex: 1, minWidth: 140, borderLeftWidth: 3, borderLeftColor: theme.accent, paddingLeft: 10 },
  cards: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  card: { flexGrow: 1, flexBasis: 260, borderRadius: 16, padding: 14, gap: 10, borderWidth: 1, borderColor: theme.border, backgroundColor: theme.surface },
  cardTitle: { color: theme.text, fontSize: 14, fontWeight: '700' },
  metric: { gap: 3 }, metricLabel: { color: theme.textDim, fontSize: 12 },
  metricValue: { color: theme.text, fontSize: 19, fontWeight: '600' },
  voice: { borderRadius: 16, padding: 14, gap: 12, backgroundColor: theme.surfaceAlt, borderColor: theme.border, borderWidth: 1 },
  transcript: { color: theme.text, fontSize: 16, lineHeight: 24 },
  button: { alignSelf: 'flex-start', paddingVertical: 9, paddingHorizontal: 12, borderRadius: 14, borderWidth: 1, borderColor: theme.accentDim },
  buttonText: { color: theme.accent, fontSize: 13, fontWeight: '600' },
});
