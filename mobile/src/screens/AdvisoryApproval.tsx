import React, { useEffect, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { Text } from '../components/ThemedText';
import type { ApprovalTask } from '../api/client';
import { ApiError } from '../api/client';
import { fetchModelRoles, type ModelRoles } from '../api/advisory';
import { useServer } from '../context/ServerContext';
import { useThemeStyles, type Theme } from '../theme';

type OpinionTask = ApprovalTask & { judge?: unknown; judge_pending?: unknown };
const shortText = (value: unknown, limit = 240): string | null => {
  if (typeof value !== 'string') return null;
  const bounded = value.slice(0, limit);
  return bounded.trim() ? bounded : null;
};
const object = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;

/** This is presentation only; the owner controls on the card remain authoritative. */
export function AdvisoryOpinion({ task }: { task: ApprovalTask }) {
  const { styles } = useThemeStyles(makeStyles);
  const raw = task as OpinionTask;
  const judge = object(raw.judge);
  const pending = raw.judge_pending;
  if (!judge && pending !== true) return null;
  if (!judge) return <Text style={styles.pending}>Advisory model opinion pending · you can decide now. Pull to refresh to check again.</Text>;
  const identity = object(judge.judge);
  const score = typeof judge.score === 'number' && Number.isFinite(judge.score) && judge.score >= 0 && judge.score <= 100
    ? `${judge.score}/100` : 'unavailable';
  const flags = Array.isArray(judge.flags) ? judge.flags.slice(0, 8).filter((flag): flag is string => typeof flag === 'string' && !!flag.slice(0, 160).trim()) : [];
  return <View style={styles.opinion}>
    <Text style={styles.title}>Model opinion · advisory only · you decide</Text>
    <Text style={styles.body}>Risk score {score} · {shortText(identity?.provider, 80) || 'unknown provider'} · {shortText(identity?.model, 120) || 'unknown model'} · {identity?.local === true ? 'local' : identity?.local === false ? 'remote' : 'locality unknown'}</Text>
    {judge.truncated === true && <Text style={styles.warning}>Judged on a shortened copy of the task.</Text>}
    {flags.length > 0 && <>
      <Text style={styles.warning}>Flagged arguments may have manipulated this model opinion.</Text>
      {flags.map((flag, index) => <Text key={index} style={styles.warning}>{flag.slice(0, 160)}</Text>)}
    </>}
    <Text style={styles.body}>{shortText(judge.rationale, 2000) || 'No rationale supplied.'}</Text>
  </View>;
}

/** Read-only hub configuration; reachable:null has no connectivity meaning. */
export function ModelRolesView() {
  const { styles } = useThemeStyles(makeStyles);
  const { config, configured, ready, chatScope } = useServer();
  const [snapshot, setSnapshot] = useState<{ scope: string; status: 'loading' | 'loaded' | 'error'; roles?: ModelRoles; error?: string } | null>(null);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    if (!ready || !configured || !config.adminToken.trim()) return;
    const controller = new AbortController();
    setSnapshot({ scope: chatScope, status: 'loading' });
    void fetchModelRoles(config, controller.signal).then(roles => {
      if (!controller.signal.aborted) setSnapshot({ scope: chatScope, status: 'loaded', roles });
    }).catch(error => {
      if (!controller.signal.aborted) setSnapshot({ scope: chatScope, status: 'error',
        error: error instanceof ApiError ? error.message : 'Model roles unavailable' });
    });
    return () => controller.abort();
  }, [config, configured, ready, chatScope, refresh]);
  const current = snapshot?.scope === chatScope ? snapshot : null;
  return <View style={styles.roles}>
    <Text style={styles.title}>Model roles · configuration only</Text>
    <Text style={styles.muted}>Connectivity has not been checked.</Text>
    {(!current || current.status === 'loading') && <Text style={styles.muted}>Loading model roles…</Text>}
    {current?.status === 'error' && <Text style={styles.warning}>{current.error}</Text>}
    {current?.status === 'loaded' && current.roles?.roles.length === 0 && <Text style={styles.muted}>No model roles configured.</Text>}
    {current?.status === 'loaded' && current.roles?.roles.map(role => <View key={role.role} style={styles.role}>
      <Text style={styles.body}>{role.role} · {role.configured
        ? `${role.provider || 'router'} · ${role.model || 'router selected'} · ${role.local === true ? 'local' : role.local === false ? 'remote' : 'locality unknown'}`
        : `Not configured: ${role.reason || 'unset'}`}</Text>
      {!!role.note && <Text style={styles.muted}>{role.note}</Text>}
      {role.error && <Text style={styles.warning}>{role.detail || role.reason || 'Configuration error'}</Text>}
    </View>)}
    <Pressable disabled={!current || current.status === 'loading'} onPress={() => setRefresh(value => value + 1)} style={styles.refresh}>
      <Text style={styles.refreshText}>{current?.status === 'error' ? 'Retry roles' : 'Refresh roles'}</Text>
    </Pressable>
  </View>;
}

const makeStyles = (theme: Theme) => StyleSheet.create({
  opinion: { marginTop: 10, padding: 10, borderRadius: 10, borderWidth: 1, borderColor: theme.border, backgroundColor: theme.surfaceAlt },
  pending: { color: theme.textDim, fontSize: 12, marginTop: 10 },
  title: { color: theme.accent, fontSize: 12, fontWeight: '800' },
  body: { color: theme.text, fontSize: 12, marginTop: 4 },
  warning: { color: theme.warn, fontSize: 12, marginTop: 4 },
  roles: { backgroundColor: theme.surface, borderRadius: 14, borderWidth: 1, borderColor: theme.border, padding: 14, marginBottom: 12 },
  role: { marginTop: 8 },
  muted: { color: theme.textDim, fontSize: 12, marginTop: 4 },
  refresh: { alignSelf: 'flex-start', marginTop: 10, paddingVertical: 6, paddingHorizontal: 10, borderWidth: 1, borderColor: theme.border, borderRadius: 8 },
  refreshText: { color: theme.accent, fontSize: 12, fontWeight: '700' },
});
