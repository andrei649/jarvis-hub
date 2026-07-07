import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { ApiError, fetchSkills, type HubSkill } from '../api/client';
import { useServer } from '../context/ServerContext';
import { theme } from '../theme';

function EmptyState({ onGoToSettings }: { onGoToSettings: () => void }) {
  return (
    <View style={styles.empty}>
      <Text style={styles.emptyTitle}>No hub connected</Text>
      <Text style={styles.emptyBody}>Connect this phone to your Jarvis hub before viewing the skills catalog.</Text>
      <Pressable style={styles.cta} onPress={onGoToSettings}>
        <Text style={styles.ctaText}>Open Settings</Text>
      </Pressable>
    </View>
  );
}

function SkillCard({ skill }: { skill: HubSkill }) {
  const commandCount = skill.commands.length;
  const agents = skill.agents.length ? skill.agents.join(', ') : 'No assigned agents';
  return (
    <View style={styles.card}>
      <View style={styles.cardTop}>
        <View style={styles.cardTitleWrap}>
          <Text style={styles.cardTitle}>{skill.name}</Text>
          <Text style={styles.meta}>{agents}</Text>
        </View>
        {skill.version ? <Text style={styles.version}>v{skill.version}</Text> : null}
      </View>
      {skill.description ? <Text style={styles.description}>{skill.description}</Text> : null}
      <View style={styles.footer}>
        <Text style={styles.footerText}>{commandCount} command{commandCount === 1 ? '' : 's'}</Text>
        <Text style={styles.footerText}>read-only</Text>
      </View>
    </View>
  );
}

export function SkillsScreen({ onGoToSettings }: { onGoToSettings: () => void }) {
  const { config, configured } = useServer();
  const [skills, setSkills] = useState<HubSkill[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!configured) return;
    setLoading(true);
    setError(null);
    try {
      const out = await fetchSkills(config);
      setSkills(out.skills);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load skills');
      setSkills([]);
    } finally {
      setLoading(false);
    }
  }, [config, configured]);

  useEffect(() => {
    load();
  }, [load]);

  const summary = useMemo(() => {
    const commands = skills.reduce((total, skill) => total + skill.commands.length, 0);
    const agents = new Set(skills.flatMap((skill) => skill.agents)).size;
    return { commands, agents };
  }, [skills]);

  if (!configured) return <EmptyState onGoToSettings={onGoToSettings} />;

  return (
    <ScrollView
      style={styles.flex}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.accent} />}
    >
      <View style={styles.summary}>
        <View style={styles.summaryCell}>
          <Text style={styles.summaryValue}>{skills.length}</Text>
          <Text style={styles.summaryLabel}>skills</Text>
        </View>
        <View style={styles.summaryCell}>
          <Text style={styles.summaryValue}>{summary.commands}</Text>
          <Text style={styles.summaryLabel}>commands</Text>
        </View>
        <View style={styles.summaryCell}>
          <Text style={styles.summaryValue}>{summary.agents}</Text>
          <Text style={styles.summaryLabel}>agents</Text>
        </View>
      </View>

      {error && (
        <View style={styles.errorBox}>
          <Text style={styles.errorText}>{error}</Text>
        </View>
      )}

      {loading && skills.length === 0 && (
        <View style={styles.loading}>
          <ActivityIndicator color={theme.accent} />
        </View>
      )}

      {skills.map((skill) => (
        <SkillCard key={skill.key} skill={skill} />
      ))}

      {!loading && skills.length === 0 && !error && (
        <View style={styles.clearBox}>
          <Text style={styles.clearTitle}>No skills returned</Text>
          <Text style={styles.clearText}>The hub returned an empty skills catalog.</Text>
        </View>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { padding: 12, paddingBottom: 24 },
  summary: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 12,
  },
  summaryCell: {
    flex: 1,
    backgroundColor: theme.surface,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: theme.border,
    paddingHorizontal: 10,
    paddingVertical: 10,
  },
  summaryValue: { color: theme.accent, fontSize: 20, fontWeight: '800' },
  summaryLabel: { color: theme.textDim, fontSize: 11, marginTop: 2, textTransform: 'uppercase' },
  card: {
    backgroundColor: theme.surface,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: theme.border,
    padding: 14,
    marginBottom: 12,
  },
  cardTop: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  cardTitleWrap: { flex: 1 },
  cardTitle: { color: theme.text, fontSize: 16, fontWeight: '800' },
  meta: { color: theme.textDim, fontSize: 12, marginTop: 3 },
  version: {
    color: theme.accent,
    fontSize: 12,
    fontWeight: '800',
    maxWidth: 96,
    textAlign: 'right',
  },
  description: { color: theme.textDim, fontSize: 14, lineHeight: 20, marginTop: 10 },
  footer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    borderTopWidth: 1,
    borderTopColor: theme.border,
    paddingTop: 10,
    marginTop: 12,
  },
  footerText: { color: theme.textDim, fontSize: 12, fontWeight: '700', textTransform: 'uppercase' },
  errorBox: {
    backgroundColor: '#2a0d16',
    borderColor: theme.danger,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
  },
  errorText: { color: theme.danger, fontSize: 14 },
  loading: { alignItems: 'center', padding: 24 },
  clearBox: {
    alignItems: 'center',
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 14,
    padding: 28,
    backgroundColor: theme.surface,
  },
  clearTitle: { color: theme.ok, fontSize: 20, fontWeight: '800', marginBottom: 6 },
  clearText: { color: theme.textDim, fontSize: 14, textAlign: 'center' },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  emptyTitle: { color: theme.text, fontSize: 20, fontWeight: '700', marginBottom: 8 },
  emptyBody: { color: theme.textDim, fontSize: 15, textAlign: 'center', marginBottom: 24 },
  cta: { paddingHorizontal: 24, paddingVertical: 12, borderRadius: 24, backgroundColor: theme.accent },
  ctaText: { color: '#02121b', fontWeight: '700', fontSize: 15 },
});
