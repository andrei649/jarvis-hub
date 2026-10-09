import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AccessibilityInfo, AppState, StyleSheet, View } from 'react-native';
import Svg, { Circle, Ellipse, Line } from 'react-native-svg';
import { Text } from './ThemedText';
import { useTheme } from '../theme';
import { buildOrbGeometry, clampOrbSize, projectOrb } from '../voice/orbGeometry';
import { orbVisual, type OrbStatus, type OrbVisual } from '../voice/orbVisual';

const GEOMETRY = buildOrbGeometry(72);

export function VoiceOrb({ status = 'off', level, size = 180, motion = 'lively' }:
  { status?: OrbStatus; level?: number; size?: number; motion?: string }) {
  const latestLevel = useRef(level);
  latestLevel.current = level;
  const [sampledLevel, setSampledLevel] = useState(level);
  const [reduced, setReduced] = useState(true); // Unknown preference freezes motion.
  const [active, setActive] = useState(AppState.currentState === 'active');
  const [tick, setTick] = useState(0);
  const measured = status === 'listening' && typeof level === 'number' && Number.isFinite(level);
  const displayLevel = reduced || !active ? level : sampledLevel;
  const visual = useMemo(() => orbVisual({ status, level: measured ? displayLevel : 0, motion }), [status, measured, displayLevel, motion]);
  const source = visual.status === 'listening'
    ? measured ? 'measured mic level' : 'no measured mic level'
    : 'state animation';
  const dimension = clampOrbSize(size);
  const theme = useTheme();

  useEffect(() => {
    let mounted = true;
    let eventSeen = false;
    let motionSubscription: { remove: () => void } | null = null;
    try {
      motionSubscription = AccessibilityInfo.addEventListener('reduceMotionChanged', value => {
        eventSeen = true;
        setReduced(value);
      });
    } catch { /* Without dynamic preference support, keep motion frozen. */ }
    void Promise.resolve().then(() => AccessibilityInfo.isReduceMotionEnabled()).then(value => {
      if (mounted && !eventSeen) setReduced(motionSubscription ? value : true);
    }).catch(() => {
      if (mounted && !eventSeen) setReduced(true);
    });
    const appSubscription = AppState.addEventListener('change', state => setActive(state === 'active'));
    return () => {
      mounted = false;
      motionSubscription?.remove();
      appSubscription.remove();
    };
  }, []);

  useEffect(() => {
    if (reduced || !active) return;
    const interval = setInterval(() => {
      setSampledLevel(latestLevel.current);
      setTick(previous => previous + 1);
    }, 50);
    return () => clearInterval(interval);
  }, [reduced, active]);

  return (
    <View style={[styles.wrap, { width: dimension }]} accessible accessibilityRole="image"
      accessibilityLabel={`${visual.label}, ${source}`}>
      <OrbScene visual={visual} dimension={dimension} tick={tick} />
      <Text style={[styles.label, { color: visual.color }]}>{visual.label}</Text>
      <Text style={[styles.source, { color: theme.textDim }]}>{source}</Text>
    </View>
  );
}

const OrbScene = React.memo(function OrbScene({ visual, dimension, tick }:
  { visual: OrbVisual; dimension: number; tick: number }) {
  const yaw = tick * 0.05 * visual.spin;
  const projected = useMemo(() => projectOrb(GEOMETRY, dimension, yaw, visual.energy), [dimension, yaw, visual.energy]);
  const center = dimension / 2;
  const radius = dimension * 0.3;
  return (
    <Svg width={dimension} height={dimension} viewBox={`0 0 ${dimension} ${dimension}`} accessible={false}>
        {visual.linked ? GEOMETRY.links.map(([from, to], index) => (
          <Line key={`link-${index}`} x1={projected[from].x} y1={projected[from].y}
            x2={projected[to].x} y2={projected[to].y} stroke={visual.color}
            strokeWidth={0.6} opacity={Math.min(projected[from].depth, projected[to].depth) * visual.energy * 0.26} />
        )) : null}
        {projected.map((point, index) => (
          <Circle key={`point-${index}`} cx={point.x} cy={point.y}
            r={0.5 + point.depth * 1.3 + visual.energy * 0.5}
            fill={point.depth > 0.78 ? '#eaf6ff' : visual.color}
            opacity={0.14 + point.depth * 0.72} />
        ))}
        <Ellipse cx={center} cy={center} rx={radius * 1.12} ry={radius * 0.28}
          transform={`rotate(${yaw * 45} ${center} ${center})`}
          stroke={visual.color} strokeWidth={1} opacity={0.3 + visual.energy * 0.35} fill="none" />
        <Ellipse cx={center} cy={center} rx={radius * 1.34} ry={radius * 0.45}
          transform={`rotate(${-yaw * 34} ${center} ${center})`}
          stroke={visual.color} strokeWidth={0.8} opacity={0.24 + visual.energy * 0.28} fill="none" />
        <Circle cx={center} cy={center} r={Math.max(1.2, radius * (0.06 + visual.energy * 0.05))}
          fill="#eaf6ff" opacity={0.55 + visual.energy * 0.45} />
    </Svg>
  );
});

const styles = StyleSheet.create({
  wrap: { alignItems: 'center' },
  label: { fontSize: 12, fontWeight: '700' },
  source: { fontSize: 10 },
});
