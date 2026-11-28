import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { ApiError } from '../api/client';
import {
  deleteLearnedEntry,
  editLearnedEntry,
  fetchLearnedEntries,
  fetchMemoryGovernance,
  fetchOsStatus,
  fetchOsWorkshopProject,
  fetchOsWorkshopProjects,
  reindexOsVault,
  resetCuratedMemory,
  setMemorySwitch,
  type LearnedEntryItem,
  type MemoryGovernanceStatus,
  type MemoryResetTarget,
  type OsStatusSnapshot,
  type OsWorkshopProjectDetail,
  type OsWorkshopProjectSummary,
} from '../api/ownerControls';
import { useServer } from '../context/ServerContext';
import type { ServerConfig } from '../storage/settings';
import { useThemeStyles, type Theme } from '../theme';
import { Text, TextInput } from './ThemedText';

export function MemoryOwnerPanels({ onGoToSettings }: { onGoToSettings: () => void }) {
  const { config, chatScope, connectionEpoch, ready, configured } = useServer();
  return (
    <ScopedMemoryOwnerPanels
      key={`${chatScope}:${connectionEpoch}`}
      config={config}
      ready={ready}
      configured={configured}
      onGoToSettings={onGoToSettings}
    />
  );
}

type SubTab = 'governance' | 'learned' | 'os';

function ScopedMemoryOwnerPanels({
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
  const [tab, setTab] = useState<SubTab>('governance');

  const [gov, setGov] = useState<MemoryGovernanceStatus | null>(null);
  const [resetTarget, setResetTarget] = useState<MemoryResetTarget>('all');
  const [resetConfirm, setResetConfirm] = useState('');

  const [entries, setEntries] = useState<LearnedEntryItem[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingValue, setEditingValue] = useState('');

  const [osStatus, setOsStatus] = useState<OsStatusSnapshot | null>(null);
  const [osProjects, setOsProjects] = useState<OsWorkshopProjectSummary[]>([]);
  const [osDetail, setOsDetail] = useState<OsWorkshopProjectDetail | null>(null);

  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const sequence = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const hasAdmin = Boolean(config.adminToken.trim());

  const loadTab = useCallback(
    (activeTab: SubTab) => {
      if (!ready || !configured) return;
      controller.current?.abort();
      const abort = new AbortController();
      controller.current = abort;
      const reqId = ++sequence.current;
      setError(null);
      if (activeTab === 'governance') {
        void fetchMemoryGovernance(config, abort.signal).then(
          res => {
            if (sequence.current === reqId && !abort.signal.aborted) setGov(res);
          },
          err => {
            if (sequence.current === reqId && !abort.signal.aborted) {
              setError(err instanceof ApiError ? err.message : 'Memory governance unavailable');
            }
          },
        );
      } else if (activeTab === 'learned') {
        void fetchLearnedEntries(config, { limit: 30, signal: abort.signal }).then(
          res => {
            if (sequence.current === reqId && !abort.signal.aborted) setEntries(res.entries);
          },
          err => {
            if (sequence.current === reqId && !abort.signal.aborted) {
              setError(err instanceof ApiError ? err.message : 'Learned entries unavailable');
            }
          },
        );
      } else {
        void Promise.all([
          fetchOsStatus(config, abort.signal),
          fetchOsWorkshopProjects(config, abort.signal).catch(() => []),
        ]).then(
          ([statusOut, projectsOut]) => {
            if (sequence.current === reqId && !abort.signal.aborted) {
              setOsStatus(statusOut);
              setOsProjects(projectsOut);
            }
          },
          err => {
            if (sequence.current === reqId && !abort.signal.aborted) {
              setError(err instanceof ApiError ? err.message : 'ANDREI OS status unavailable');
            }
          },
        );
      }
    },
    [config, configured, ready],
  );

  useEffect(() => {
    if (open && ready && configured) loadTab(tab);
  }, [open, tab, ready, configured, loadTab]);

  useEffect(
    () => () => {
      ++sequence.current;
      controller.current?.abort();
    },
    [],
  );

  const toggleMemorySwitch = async () => {
    if (!gov || busy) return;
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      const next = await setMemorySwitch(config, !gov.enabled);
      setNotice(`Automatic memory ${next.enabled ? 'enabled' : 'disabled'}.`);
      loadTab('governance');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to toggle memory switch');
    } finally {
      setBusy(false);
    }
  };

  const handleReset = async () => {
    if (busy) return;
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      const out = await resetCuratedMemory(config, resetTarget, resetConfirm);
      setResetConfirm('');
      setNotice(`Cleared curated store(s): ${out.cleared.join(', ')}.`);
      loadTab('governance');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Memory reset failed');
    } finally {
      setBusy(false);
    }
  };

  const saveEntryEdit = async (id: string) => {
    if (busy) return;
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      await editLearnedEntry(config, id, editingValue);
      setEditingId(null);
      setEditingValue('');
      setNotice('Learned entry updated.');
      loadTab('learned');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not update entry');
    } finally {
      setBusy(false);
    }
  };

  const removeEntry = async (id: string) => {
    if (busy) return;
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      await deleteLearnedEntry(config, id);
      setNotice('Learned entry forgotten.');
      loadTab('learned');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not forget entry');
    } finally {
      setBusy(false);
    }
  };

  const handleReindex = async () => {
    if (busy) return;
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      const res = await reindexOsVault(config);
      setNotice(`Vault reindexed (${res.indexedNotes} notes).`);
      loadTab('os');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Reindex failed');
    } finally {
      setBusy(false);
    }
  };

  const inspectProject = async (path: string) => {
    setError(null);
    try {
      const detail = await fetchOsWorkshopProject(config, path);
      setOsDetail(detail);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not inspect workshop project');
    }
  };

  return (
    <View style={styles.card} accessibilityLabel="Memory governance, learned entries, and ANDREI OS">
      <View style={styles.headerRow}>
        <Text style={styles.title}>Governance & ANDREI OS</Text>
        <Pressable
          style={styles.button}
          accessibilityRole="button"
          accessibilityLabel={open ? 'Close memory and OS controls' : 'Open memory and OS controls'}
          onPress={() => setOpen(v => !v)}
        >
          <Text style={styles.buttonText}>{open ? 'Close' : 'Open controls'}</Text>
        </Pressable>
      </View>

      {open ? (
        <View style={styles.section}>
          <View style={styles.tabs}>
            {(['governance', 'learned', 'os'] as const).map(key => (
              <Pressable
                key={key}
                style={[styles.tab, tab === key && styles.tabActive]}
                onPress={() => {
                  setNotice(null);
                  setError(null);
                  setTab(key);
                }}
              >
                <Text style={styles.tabText}>
                  {key === 'governance' ? 'Memory' : key === 'learned' ? 'Learned' : 'ANDREI OS'}
                </Text>
              </Pressable>
            ))}
          </View>

          {error ? <Text style={[styles.line, { color: theme.danger }]}>{error}</Text> : null}
          {notice ? <Text style={[styles.line, { color: theme.ok }]}>{notice}</Text> : null}

          {tab === 'governance' ? (
            <View style={styles.box}>
              {gov ? (
                <>
                  <Text style={styles.line}>
                    Curated memory: {gov.enabled ? 'ON' : 'OFF'} · MEMORY.md {gov.memory.chars}/{gov.memory.max_chars} chars ({gov.memory.entries}) · USER.md {gov.user.chars}/{gov.user.max_chars} chars ({gov.user.entries})
                  </Text>
                  {hasAdmin ? (
                    <>
                      <Pressable style={styles.button} disabled={busy} onPress={() => void toggleMemorySwitch()}>
                        <Text style={styles.buttonText}>
                          {gov.enabled ? 'Turn curated memory OFF' : 'Turn curated memory ON'}
                        </Text>
                      </Pressable>
                      <View style={styles.tabs}>
                        {(['all', 'memory', 'user'] as const).map(t => (
                          <Pressable
                            key={t}
                            style={[styles.tab, resetTarget === t && styles.tabActive]}
                            onPress={() => setResetTarget(t)}
                          >
                            <Text style={styles.tabText}>Reset: {t}</Text>
                          </Pressable>
                        ))}
                      </View>
                      <View style={styles.row}>
                        <TextInput
                          value={resetConfirm}
                          onChangeText={setResetConfirm}
                          placeholder='Type RESET to confirm'
                          placeholderTextColor={theme.textDim}
                          autoCapitalize="characters"
                          style={styles.input}
                        />
                        <Pressable
                          style={styles.dangerBtn}
                          disabled={busy || resetConfirm !== 'RESET'}
                          onPress={() => void handleReset()}
                          accessibilityLabel="Confirm curated memory reset"
                        >
                          <Text style={styles.dangerBtnText}>Reset</Text>
                        </Pressable>
                      </View>
                    </>
                  ) : (
                    <Pressable style={styles.button} onPress={onGoToSettings}>
                      <Text style={styles.buttonText}>Add admin token in Settings to switch or reset</Text>
                    </Pressable>
                  )}
                </>
              ) : (
                <Text style={styles.dim}>Loading memory governance…</Text>
              )}
            </View>
          ) : null}

          {tab === 'learned' ? (
            <View style={styles.box}>
              {entries.length === 0 ? (
                <Text style={styles.dim}>No learned entries returned.</Text>
              ) : (
                entries.slice(0, 12).map(item => (
                  <View key={item.id} style={styles.itemRow}>
                    <Text style={styles.dim}>[{item.store}] {item.id}</Text>
                    {editingId === item.id ? (
                      <View style={styles.row}>
                        <TextInput
                          value={editingValue}
                          onChangeText={setEditingValue}
                          style={styles.input}
                        />
                        <Pressable style={styles.button} onPress={() => void saveEntryEdit(item.id)}>
                          <Text style={styles.buttonText}>Save</Text>
                        </Pressable>
                      </View>
                    ) : (
                      <Text style={styles.line} numberOfLines={3}>{item.value}</Text>
                    )}
                    {hasAdmin ? (
                      <View style={styles.row}>
                        <Pressable
                          style={styles.button}
                          onPress={() => {
                            setEditingId(item.id);
                            setEditingValue(item.value);
                          }}
                        >
                          <Text style={styles.buttonText}>Edit</Text>
                        </Pressable>
                        <Pressable style={styles.dangerBtn} onPress={() => void removeEntry(item.id)}>
                          <Text style={styles.dangerBtnText}>Forget</Text>
                        </Pressable>
                      </View>
                    ) : null}
                  </View>
                ))
              )}
            </View>
          ) : null}

          {tab === 'os' ? (
            <View style={styles.box}>
              {osStatus ? (
                <>
                  <Text style={styles.line}>
                    Mode: {osStatus.vaultMode} · Notes: {osStatus.indexedNotes} · Index: {osStatus.indexReady ? 'ready' : 'unavailable'}
                  </Text>
                  <Text style={styles.dim}>
                    Vault: {osStatus.vaultAvailable ? osStatus.vaultPath || 'connected' : 'unavailable'} · Second Brain: {osStatus.copilotConnected ? 'connected' : 'offline'}
                  </Text>
                  <Pressable
                    style={styles.button}
                    disabled={busy || !osStatus.vaultAvailable}
                    onPress={() => void handleReindex()}
                    accessibilityLabel="Reindex ANDREI OS vault"
                  >
                    <Text style={styles.buttonText}>Reindex vault</Text>
                  </Pressable>
                  <Text style={styles.subhead}>WORKSHOP PROJECTS ({osProjects.length})</Text>
                  {osProjects.length === 0 ? (
                    <Text style={styles.dim}>No saved workshop projects.</Text>
                  ) : (
                    osProjects.map(p => (
                      <Pressable
                        key={p.path}
                        style={styles.itemRow}
                        onPress={() => void inspectProject(p.path)}
                      >
                        <Text style={styles.line}>{p.title} ({p.view})</Text>
                        <Text style={styles.dim}>{p.path}</Text>
                      </Pressable>
                    ))
                  )}
                  {osDetail ? (
                    <View style={styles.itemRow}>
                      <Text style={styles.line}>
                        Selected: {osDetail.title} · {osDetail.paramCount} param(s)
                      </Text>
                      {osDetail.summary ? <Text style={styles.dim}>Keys: {osDetail.summary}</Text> : null}
                    </View>
                  ) : null}
                </>
              ) : (
                <Text style={styles.dim}>Loading ANDREI OS status…</Text>
              )}
            </View>
          ) : null}
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
    title: { color: theme.accent, fontSize: 12, fontWeight: '800', textTransform: 'uppercase' },
    subhead: { color: theme.textDim, fontSize: 11, fontWeight: '800', marginTop: 6 },
    section: { marginTop: 10, gap: 8 },
    tabs: { flexDirection: 'row', gap: 6 },
    tab: {
      flex: 1,
      alignItems: 'center',
      borderWidth: 1,
      borderColor: theme.border,
      borderRadius: 10,
      paddingVertical: 6,
    },
    tabActive: { borderColor: theme.accent, backgroundColor: theme.accentDim },
    tabText: { color: theme.text, fontSize: 12, fontWeight: '700' },
    box: { gap: 8 },
    row: { flexDirection: 'row', gap: 8, alignItems: 'center' },
    itemRow: {
      borderTopWidth: 1,
      borderTopColor: theme.border,
      paddingTop: 8,
      gap: 4,
    },
    line: { color: theme.text, fontSize: 13, lineHeight: 18 },
    dim: { color: theme.textDim, fontSize: 12, lineHeight: 17 },
    button: {
      borderColor: theme.border,
      borderWidth: 1,
      borderRadius: 10,
      paddingHorizontal: 11,
      paddingVertical: 6,
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
      flex: 1,
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
