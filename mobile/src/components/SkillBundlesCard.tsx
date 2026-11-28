import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { ApiError } from '../api/client';
import {
  deleteSkillBundle,
  fetchSkillBundles,
  saveSkillBundle,
  switchSkillBundle,
  type SkillBundleItem,
} from '../api/ownerControls';
import { useServer } from '../context/ServerContext';
import type { ServerConfig } from '../storage/settings';
import { useThemeStyles, type Theme } from '../theme';
import { Text, TextInput } from './ThemedText';

export function SkillBundlesCard({ onGoToSettings }: { onGoToSettings: () => void }) {
  const { config, chatScope, connectionEpoch, ready, configured } = useServer();
  return (
    <ScopedSkillBundlesCard
      key={`${chatScope}:${connectionEpoch}`}
      config={config}
      ready={ready}
      configured={configured}
      onGoToSettings={onGoToSettings}
    />
  );
}

function ScopedSkillBundlesCard({
  config,
  ready,
  configured,
  onGoToSettings,
}: {
  config: ServerConfig;
  ready: boolean;
  configured: boolean;
  onGoToSettings: () => void;
}) {
  const { theme, styles } = useThemeStyles(makeStyles);
  const [open, setOpen] = useState(false);
  const [bundles, setBundles] = useState<SkillBundleItem[]>([]);
  const [nameDraft, setNameDraft] = useState('');
  const [skillsDraft, setSkillsDraft] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const sequence = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const hasAdmin = Boolean(config.adminToken.trim());

  const load = useCallback(() => {
    if (!ready || !configured) return;
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    const reqId = ++sequence.current;
    setError(null);
    void fetchSkillBundles(config, abort.signal).then(
      out => {
        if (sequence.current === reqId && !abort.signal.aborted) setBundles(out.bundles);
      },
      err => {
        if (sequence.current === reqId && !abort.signal.aborted) {
          setError(err instanceof ApiError ? err.message : 'Skill bundles unavailable');
        }
      },
    );
  }, [config, configured, ready]);

  useEffect(() => {
    if (open && ready && configured) load();
  }, [open, ready, configured, load]);

  useEffect(
    () => () => {
      ++sequence.current;
      controller.current?.abort();
    },
    [],
  );

  const handleSave = async () => {
    if (busy) return;
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      const skills = skillsDraft
        .split(',')
        .map(s => s.trim())
        .filter(Boolean);
      const saved = await saveSkillBundle(config, { name: nameDraft, skills, overwrite: true });
      setNameDraft('');
      setSkillsDraft('');
      setNotice(`Saved bundle "${saved.name}" (${saved.skills.length} skill(s)).`);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save bundle');
    } finally {
      setBusy(false);
    }
  };

  const handleSwitch = async (bundleName: string, enabled: boolean) => {
    if (busy) return;
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      const out = await switchSkillBundle(config, bundleName, enabled);
      setNotice(
        out.status === 'pending'
          ? `Enable requested for "${bundleName}" — awaiting owner approval (${out.taskId ?? 'inbox'}).`
          : `Disabled installed skills in "${bundleName}".`,
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Bundle switch failed');
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (bundleName: string) => {
    if (busy) return;
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      await deleteSkillBundle(config, bundleName);
      setNotice(`Deleted bundle "${bundleName}".`);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not delete bundle');
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.card} accessibilityLabel="Skill bundles">
      <View style={styles.headerRow}>
        <Text style={styles.title}>Skill Bundles</Text>
        <Pressable
          style={styles.button}
          accessibilityRole="button"
          accessibilityLabel={open ? 'Close skill bundles' : 'Open skill bundles'}
          onPress={() => setOpen(v => !v)}
        >
          <Text style={styles.buttonText}>{open ? 'Close' : 'Open bundles'}</Text>
        </Pressable>
      </View>

      {open ? (
        <View style={styles.section}>
          {error ? <Text style={[styles.line, { color: theme.danger }]}>{error}</Text> : null}
          {notice ? <Text style={[styles.line, { color: theme.ok }]}>{notice}</Text> : null}

          {bundles.length === 0 ? (
            <Text style={styles.dim}>No skill bundles defined on this hub.</Text>
          ) : (
            bundles.map(b => (
              <View key={b.slug} style={styles.bundleRow}>
                <Text style={styles.line}>
                  {b.name} · {b.installed.length}/{b.skills.length} installed
                </Text>
                {b.description ? <Text style={styles.dim}>{b.description}</Text> : null}
                {hasAdmin ? (
                  <View style={styles.actionsRow}>
                    <Pressable style={styles.button} disabled={busy} onPress={() => void handleSwitch(b.name, true)}>
                      <Text style={styles.buttonText}>Enable (approval)</Text>
                    </Pressable>
                    <Pressable style={styles.button} disabled={busy} onPress={() => void handleSwitch(b.name, false)}>
                      <Text style={styles.buttonText}>Disable</Text>
                    </Pressable>
                    <Pressable style={styles.dangerBtn} disabled={busy} onPress={() => void handleDelete(b.name)}>
                      <Text style={styles.dangerBtnText}>Delete</Text>
                    </Pressable>
                  </View>
                ) : null}
              </View>
            ))
          )}

          {hasAdmin ? (
            <View style={styles.bundleRow}>
              <Text style={styles.dim}>SAVE OR UPDATE BUNDLE</Text>
              <TextInput
                value={nameDraft}
                onChangeText={setNameDraft}
                placeholder="Bundle name"
                placeholderTextColor={theme.textDim}
                style={styles.input}
              />
              <TextInput
                value={skillsDraft}
                onChangeText={setSkillsDraft}
                placeholder="Installed skill names (comma-separated)"
                placeholderTextColor={theme.textDim}
                style={styles.input}
              />
              <Pressable
                style={styles.button}
                disabled={busy || !nameDraft.trim() || !skillsDraft.trim()}
                onPress={() => void handleSave()}
              >
                <Text style={styles.buttonText}>Save bundle</Text>
              </Pressable>
            </View>
          ) : (
            <Pressable style={styles.button} onPress={onGoToSettings}>
              <Text style={styles.buttonText}>Add admin token in Settings to manage bundles</Text>
            </Pressable>
          )}
        </View>
      ) : null}
    </View>
  );
}

const makeStyles = (theme: Theme) =>
  StyleSheet.create({
    card: {
      backgroundColor: theme.surface,
      borderRadius: 14,
      borderWidth: 1,
      borderColor: theme.border,
      padding: 14,
      marginBottom: 12,
    },
    headerRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 8 },
    title: { color: theme.accent, fontSize: 13, fontWeight: '800', textTransform: 'uppercase' },
    section: { marginTop: 10, gap: 8 },
    bundleRow: {
      borderTopWidth: 1,
      borderTopColor: theme.border,
      paddingTop: 8,
      gap: 6,
    },
    actionsRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
    line: { color: theme.text, fontSize: 13, fontWeight: '700' },
    dim: { color: theme.textDim, fontSize: 12, lineHeight: 17 },
    button: {
      borderColor: theme.border,
      borderWidth: 1,
      borderRadius: 10,
      paddingHorizontal: 11,
      paddingVertical: 6,
      alignSelf: 'flex-start',
    },
    buttonText: { color: theme.accent, fontSize: 12, fontWeight: '700' },
    dangerBtn: {
      borderColor: theme.danger,
      borderWidth: 1,
      borderRadius: 10,
      paddingHorizontal: 11,
      paddingVertical: 6,
    },
    dangerBtnText: { color: theme.danger, fontSize: 12, fontWeight: '700' },
    input: {
      backgroundColor: theme.surfaceAlt,
      borderColor: theme.border,
      borderWidth: 1,
      borderRadius: 10,
      color: theme.text,
      fontSize: 13,
      paddingHorizontal: 10,
      paddingVertical: 6,
    },
  });
