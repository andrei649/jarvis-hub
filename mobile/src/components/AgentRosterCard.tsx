import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { ApiError } from '../api/client';
import {
  createRosterAgent,
  fetchAgentRoster,
  renameRosterAgent,
  restoreRosterAgent,
  retireRosterAgent,
  type AgentRosterView,
} from '../api/ownerControls';
import { useServer } from '../context/ServerContext';
import type { ServerConfig } from '../storage/settings';
import { useThemeStyles, type Theme } from '../theme';
import { Text, TextInput } from './ThemedText';

export function AgentRosterCard({ onGoToSettings }: { onGoToSettings: () => void }) {
  const { config, chatScope, connectionEpoch, ready, configured } = useServer();
  return (
    <ScopedAgentRosterCard
      key={`${chatScope}:${connectionEpoch}`}
      config={config}
      ready={ready}
      configured={configured}
      onGoToSettings={onGoToSettings}
    />
  );
}

function ScopedAgentRosterCard({
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
  const [roster, setRoster] = useState<AgentRosterView | null>(null);
  const [newName, setNewName] = useState('');
  const [newTemplate, setNewTemplate] = useState('blank');
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [retireId, setRetireId] = useState<string | null>(null);
  const [retireConfirm, setRetireConfirm] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const sequence = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const hasAdmin = Boolean(config.adminToken.trim());

  const load = useCallback(() => {
    if (!ready || !configured || !hasAdmin) return;
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    const reqId = ++sequence.current;
    setError(null);
    void fetchAgentRoster(config, abort.signal).then(
      view => {
        if (sequence.current === reqId && !abort.signal.aborted) setRoster(view);
      },
      err => {
        if (sequence.current === reqId && !abort.signal.aborted) {
          setError(err instanceof ApiError ? err.message : 'Agent roster unavailable');
        }
      },
    );
  }, [config, configured, hasAdmin, ready]);

  useEffect(() => {
    if (open && ready && configured && hasAdmin) load();
  }, [open, ready, configured, hasAdmin, load]);

  useEffect(
    () => () => {
      ++sequence.current;
      controller.current?.abort();
    },
    [],
  );

  const handleCreate = async () => {
    if (busy || !newName.trim()) return;
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      const created = await createRosterAgent(config, { name: newName, template: newTemplate });
      setNewName('');
      setNotice(`Created agent "${created.name}" (${created.id}).`);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create agent');
    } finally {
      setBusy(false);
    }
  };

  const handleRename = async (id: string) => {
    if (busy || !renameValue.trim()) return;
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      const updated = await renameRosterAgent(config, id, renameValue);
      setRenameId(null);
      setRenameValue('');
      setNotice(`Renamed ${id} to "${updated.name}".`);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Rename failed');
    } finally {
      setBusy(false);
    }
  };

  const handleRetire = async (id: string) => {
    if (busy) return;
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      await retireRosterAgent(config, id, retireConfirm);
      setRetireId(null);
      setRetireConfirm('');
      setNotice(`Retired agent "${id}". Persona and history remain preserved.`);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Retire failed');
    } finally {
      setBusy(false);
    }
  };

  const handleRestore = async (id: string) => {
    if (busy) return;
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      const restored = await restoreRosterAgent(config, id);
      setNotice(`Restored agent "${restored.name}" (${restored.id}).`);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Restore failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.card} accessibilityLabel="Agent roster management">
      <View style={styles.headerRow}>
        <Text style={styles.title}>Agent Roster</Text>
        <Pressable
          style={styles.button}
          accessibilityRole="button"
          accessibilityLabel={open ? 'Close agent roster' : 'Open agent roster'}
          onPress={() => setOpen(v => !v)}
        >
          <Text style={styles.buttonText}>{open ? 'Close' : 'Open roster'}</Text>
        </Pressable>
      </View>

      {open ? (
        !hasAdmin ? (
          <View style={styles.section}>
            <Text style={styles.dim}>Admin token required in Settings to manage the owner agent roster.</Text>
            <Pressable style={styles.button} onPress={onGoToSettings}>
              <Text style={styles.buttonText}>Open Settings</Text>
            </Pressable>
          </View>
        ) : (
          <View style={styles.section}>
            {error ? <Text style={[styles.line, { color: theme.danger }]}>{error}</Text> : null}
            {notice ? <Text style={[styles.line, { color: theme.ok }]}>{notice}</Text> : null}

            {roster ? (
              <>
                <View style={styles.agentRow}>
                  <Text style={styles.dim}>CREATE AGENT (NO PLUGINS GRANTED BY DEFAULT)</Text>
                  <View style={styles.actionsRow}>
                    <TextInput
                      value={newName}
                      onChangeText={setNewName}
                      placeholder="Display name"
                      placeholderTextColor={theme.textDim}
                      style={styles.input}
                    />
                    <TextInput
                      value={newTemplate}
                      onChangeText={setNewTemplate}
                      placeholder="Template (blank)"
                      placeholderTextColor={theme.textDim}
                      style={styles.input}
                    />
                    <Pressable
                      style={styles.button}
                      disabled={busy || !newName.trim()}
                      onPress={() => void handleCreate()}
                    >
                      <Text style={styles.buttonText}>Create</Text>
                    </Pressable>
                  </View>
                </View>

                {roster.agents.map(a => (
                  <View key={a.id} style={styles.agentRow}>
                    <Text style={styles.line}>
                      {a.name} ({a.id}) · {a.status.toUpperCase()}
                      {a.protected ? ' · protected' : ''}
                    </Text>
                    <View style={styles.actionsRow}>
                      {a.status === 'retired' ? (
                        <Pressable style={styles.button} disabled={busy} onPress={() => void handleRestore(a.id)}>
                          <Text style={styles.buttonText}>Restore</Text>
                        </Pressable>
                      ) : (
                        <>
                          <Pressable
                            style={styles.button}
                            onPress={() => {
                              setRenameId(a.id);
                              setRenameValue(a.name);
                            }}
                          >
                            <Text style={styles.buttonText}>Rename</Text>
                          </Pressable>
                          {!a.protected ? (
                            <Pressable
                              style={styles.dangerBtn}
                              onPress={() => {
                                setRetireId(a.id);
                                setRetireConfirm('');
                              }}
                            >
                              <Text style={styles.dangerBtnText}>Retire</Text>
                            </Pressable>
                          ) : null}
                        </>
                      )}
                    </View>

                    {renameId === a.id ? (
                      <View style={styles.actionsRow}>
                        <TextInput
                          value={renameValue}
                          onChangeText={setRenameValue}
                          style={styles.input}
                        />
                        <Pressable style={styles.button} onPress={() => void handleRename(a.id)}>
                          <Text style={styles.buttonText}>Save name</Text>
                        </Pressable>
                      </View>
                    ) : null}

                    {retireId === a.id ? (
                      <View style={styles.actionsRow}>
                        <TextInput
                          value={retireConfirm}
                          onChangeText={setRetireConfirm}
                          placeholder={`Type ${a.id} to confirm`}
                          placeholderTextColor={theme.textDim}
                          autoCapitalize="none"
                          style={styles.input}
                        />
                        <Pressable
                          style={styles.dangerBtn}
                          disabled={busy || retireConfirm.trim().toLowerCase() !== a.id}
                          onPress={() => void handleRetire(a.id)}
                        >
                          <Text style={styles.dangerBtnText}>Confirm retire</Text>
                        </Pressable>
                      </View>
                    ) : null}
                  </View>
                ))}
              </>
            ) : (
              <Text style={styles.dim}>Loading agent roster…</Text>
            )}
          </View>
        )
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
    title: { color: theme.accent, fontSize: 12, fontWeight: '700', letterSpacing: 1.2, textTransform: 'uppercase' },
    section: { marginTop: 10, gap: 8 },
    agentRow: {
      borderTopWidth: 1,
      borderTopColor: theme.border,
      paddingTop: 8,
      gap: 6,
    },
    actionsRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, alignItems: 'center' },
    line: { color: theme.text, fontSize: 13, fontWeight: '600' },
    dim: { color: theme.textDim, fontSize: 12, lineHeight: 17 },
    button: {
      borderColor: theme.border,
      borderWidth: 1,
      borderRadius: 8,
      paddingHorizontal: 11,
      paddingVertical: 6,
    },
    buttonText: { color: theme.accent, fontSize: 12, fontWeight: '700' },
    dangerBtn: {
      borderColor: theme.danger,
      borderWidth: 1,
      borderRadius: 8,
      paddingHorizontal: 11,
      paddingVertical: 6,
    },
    dangerBtnText: { color: theme.danger, fontSize: 12, fontWeight: '700' },
    input: {
      flex: 1,
      minWidth: 110,
      backgroundColor: theme.surfaceAlt,
      borderColor: theme.border,
      borderWidth: 1,
      borderRadius: 8,
      color: theme.text,
      fontSize: 13,
      paddingHorizontal: 9,
      paddingVertical: 6,
    },
  });
