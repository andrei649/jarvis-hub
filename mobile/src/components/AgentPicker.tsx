import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { ApiError, fetchAgents, type AgentInfo } from '../api/client';
import { useServer } from '../context/ServerContext';
import { theme } from '../theme';

/** Compact dropdown for choosing the active agent. Pure JS (no native picker). */
export function AgentPicker({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  const { config, configured } = useServer();
  const [open, setOpen] = useState(false);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!configured) return;
    setLoading(true);
    setError(null);
    try {
      setAgents(await fetchAgents(config));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load agents');
    } finally {
      setLoading(false);
    }
  }, [config, configured]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const current = agents.find((a) => a.id === value);
  const label = current?.name || value;

  return (
    <>
      <Pressable style={styles.chip} onPress={() => setOpen(true)}>
        <Text style={styles.chipText} numberOfLines={1}>
          {label}
        </Text>
        <Text style={styles.caret}>▾</Text>
      </Pressable>

      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <Pressable style={styles.backdrop} onPress={() => setOpen(false)}>
          <Pressable style={styles.sheet} onPress={() => {}}>
            <Text style={styles.title}>Choose agent</Text>
            {loading && <ActivityIndicator color={theme.accent} style={styles.spinner} />}
            {error && <Text style={styles.error}>{error}</Text>}
            <FlatList
              data={agents}
              keyExtractor={(a) => a.id}
              style={styles.list}
              renderItem={({ item }) => (
                <Pressable
                  style={styles.option}
                  onPress={() => {
                    onChange(item.id);
                    setOpen(false);
                  }}
                >
                  <View style={styles.optInfo}>
                    <Text style={styles.optName}>{item.name}</Text>
                    {!!item.role && (
                      <Text style={styles.optRole} numberOfLines={1}>
                        {item.role}
                      </Text>
                    )}
                  </View>
                  {item.id === value && <Text style={styles.check}>✓</Text>}
                </Pressable>
              )}
              ListEmptyComponent={
                !loading && !error ? <Text style={styles.empty}>No agents available</Text> : null
              }
            />
          </Pressable>
        </Pressable>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    maxWidth: 160,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.surface,
  },
  chipText: { color: theme.accent, fontSize: 13, fontWeight: '700', flexShrink: 1 },
  caret: { color: theme.textDim, fontSize: 12, marginLeft: 6 },
  backdrop: { flex: 1, backgroundColor: '#000a', justifyContent: 'center', padding: 28 },
  sheet: {
    backgroundColor: theme.surfaceAlt,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: theme.border,
    padding: 16,
  },
  title: {
    color: theme.text,
    fontSize: 16,
    fontWeight: '700',
    marginBottom: 8,
  },
  spinner: { marginVertical: 16 },
  error: { color: theme.danger, fontSize: 13, marginVertical: 8 },
  list: { maxHeight: 360 },
  option: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
  },
  optInfo: { flex: 1 },
  optName: { color: theme.text, fontSize: 15, fontWeight: '600' },
  optRole: { color: theme.textDim, fontSize: 12, marginTop: 2 },
  check: { color: theme.accent, fontSize: 18, marginLeft: 12 },
  empty: { color: theme.textDim, fontSize: 14, textAlign: 'center', paddingVertical: 24 },
});
