import React, { useEffect, useMemo, useState } from 'react';
import { AccessibilityInfo, AppState, StyleSheet, View } from 'react-native';
import Svg, { Circle, Ellipse, Line } from 'react-native-svg';
import { Text } from './ThemedText';
import { useTheme } from '../theme';
import { buildBriefingField, fieldEnergy, type FieldAgent, type FieldTask, type FieldVoice } from '../voice/briefingField';

type Props = {
  agents: FieldAgent[]; tasks: FieldTask[]; voice: FieldVoice; active?: boolean;
  agentsAvailable?: boolean; tasksAvailable?: boolean;
};
const FRAME_MS = 70; // 14.3 frames/s at most.

export function BriefingField({ agents, tasks, voice, active = true,
  agentsAvailable = true, tasksAvailable = true }: Props) {
  const theme = useTheme();
  const field = useMemo(() => buildBriefingField(agentsAvailable ? agents : [], tasksAvailable ? tasks : []),
    [agents, tasks, agentsAvailable, tasksAvailable]);
  const energy = fieldEnergy(agentsAvailable ? agents : [], tasksAvailable ? tasks : [], voice);
  const sourceLabel = energy.source === 'idle' && (!agentsAvailable || !tasksAvailable)
    ? 'activity evidence incomplete' : energy.source;
  const visualEnergy = field.totalAgents || energy.source.startsWith('voice') || energy.source === 'measured mic level'
    ? energy.level : 0;
  const [reduced, setReduced] = useState(true); // Unknown preference stays frozen.
  const [foreground, setForeground] = useState(AppState.currentState === 'active');
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let mounted = true;
    let eventSeen = false;
    let subscription: { remove: () => void } | null = null;
    try {
      subscription = AccessibilityInfo.addEventListener('reduceMotionChanged', value => {
        eventSeen = true;
        setReduced(value);
      });
    } catch { /* Keep frozen if dynamic preference is unavailable. */ }
    void Promise.resolve().then(() => AccessibilityInfo.isReduceMotionEnabled()).then(value => {
      if (mounted && !eventSeen) setReduced(subscription ? value : true);
    }).catch(() => { if (mounted && !eventSeen) setReduced(true); });
    const appSubscription = AppState.addEventListener('change', state => setForeground(state === 'active'));
    return () => { mounted = false; subscription?.remove(); appSubscription.remove(); };
  }, []);

  useEffect(() => {
    if (!active || !foreground || reduced || visualEnergy <= 0) return;
    const timer = setInterval(() => setTick(previous => previous + 1), FRAME_MS);
    return () => clearInterval(timer);
  }, [active, foreground, reduced, visualEnergy]);

  const points = field.markers.map(marker => {
    const region = field.regions[marker.region];
    const localEnergy = energy.source === 'reported work' && !region.busy && !region.running ? 0 : visualEnergy;
    const sway = Math.sin(tick * 0.45 + marker.phase * Math.PI * 2) * localEnergy * 2.4;
    return { x: marker.x * 320 + sway, y: marker.y * 200 + sway * 0.5, energy: localEnergy };
  });
  const coreEnergy = field.totalAgents === 0 && !energy.source.startsWith('voice') && energy.source !== 'measured mic level'
    ? 0 : visualEnergy;
  const cap = field.totalAgents > field.markers.length
    ? `Showing ${field.markers.length} of ${field.totalAgents} agent markers` : null;
  const agentSummary = agentsAvailable
    ? `${field.totalAgents} reported agent${field.totalAgents === 1 ? '' : 's'}` : 'Agent roster unavailable';
  const taskSummary = tasksAvailable
    ? `${field.runningTasks} running task${field.runningTasks === 1 ? '' : 's'} in feed` : 'Task feed unavailable';
  const summary = `${agentSummary}, ${taskSummary}, ${sourceLabel}`;

  return (
    <View style={styles.wrap} accessible accessibilityRole="image" accessibilityLabel={summary}>
      <Svg width="100%" height={200} viewBox="0 0 320 200" accessible={false}>
        <Ellipse cx={160} cy={100} rx={34 + coreEnergy * 13} ry={15 + coreEnergy * 7}
          fill="#12365a" opacity={field.totalAgents ? 0.17 + coreEnergy * 0.17 : 0.09 + coreEnergy * 0.15} />
        <Circle cx={160} cy={100} r={3 + coreEnergy * 4}
          fill="#cfeeff" opacity={field.totalAgents ? 0.27 + coreEnergy * 0.5 : 0.12 + coreEnergy * 0.4} />
        {field.edges.map((edge, index) => {
          const from = points[edge.from], to = points[edge.to];
          const region = field.regions[field.markers[edge.from].region];
          return <Line key={`edge-${index}`} x1={from.x} y1={from.y} x2={to.x} y2={to.y}
            stroke={region.color} strokeWidth={0.7} opacity={0.14 + Math.max(from.energy, to.energy) * 0.4} />;
        })}
        {field.markers.map((marker, index) => {
          const location = points[index];
          return <Circle key={`marker-${index}`} cx={location.x} cy={location.y}
            r={1.7 + location.energy * 1.4} fill={field.regions[marker.region].color}
            opacity={0.43 + location.energy * 0.46} />;
        })}
      </Svg>
      {!agentsAvailable ? <Text style={[styles.region, { color: theme.textDim }]}>Agent roster unavailable</Text>
        : field.regions.length ? field.regions.map(region => (
        <Text key={region.key} style={[styles.region, { color: region.color }]}>
          {`${region.label} · ${region.count} agent${region.count === 1 ? '' : 's'} · ${region.busy} active/busy · ${tasksAvailable ? `${region.running} running task${region.running === 1 ? '' : 's'} in feed` : 'Task feed unavailable'}`}
        </Text>
      )) : <Text style={[styles.region, { color: theme.textDim }]}>No reported agents</Text>}
      {!tasksAvailable ? <Text style={[styles.detail, { color: theme.textDim }]}>Task feed unavailable</Text> : null}
      {agentsAvailable && tasksAvailable && field.unassignedRunningTasks ? <Text style={[styles.detail, { color: theme.textDim }]}>
        {`${field.unassignedRunningTasks} running task${field.unassignedRunningTasks === 1 ? '' : 's'} in feed without reported agent owner`}
      </Text> : null}
      {cap ? <Text style={[styles.detail, { color: theme.textDim }]}>{cap}</Text> : null}
      <Text style={[styles.detail, { color: theme.textDim }]}>{sourceLabel}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { width: '100%', alignItems: 'center' },
  region: { fontSize: 11, fontWeight: '600', lineHeight: 18 },
  detail: { fontSize: 10, lineHeight: 16 },
});
