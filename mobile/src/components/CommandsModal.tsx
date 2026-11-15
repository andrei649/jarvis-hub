import { Text } from './ThemedText';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Modal, Pressable, StyleSheet, View } from 'react-native';
import { ApiError } from '../api/client';
import { fetchCommands, type CommandSummary, type ShortcutSummary } from '../api/commands';
import { useServer } from '../context/ServerContext';
import { useThemeStyles, type Theme } from '../theme';

type CatalogState = { scope: string; status: 'loading' | 'available' | 'unavailable' | 'error';
  commands: CommandSummary[]; shortcuts: ShortcutSummary[]; truncated: boolean;
  shortcutsUnavailable: boolean; error?: string };
const emptyCatalog = { commands: [], shortcuts: [], truncated: false, shortcutsUnavailable: false };

export function CommandsModal({ visible, onClose, onChoose }: {
  visible: boolean;
  onClose: () => void;
  onChoose: (command: string) => void;
}) {
  const { theme, styles } = useThemeStyles(makeStyles);
  const { config, chatScope } = useServer();
  const [catalog, setCatalog] = useState<CatalogState>({ scope: '', status: 'loading', ...emptyCatalog });
  const epoch = useRef(0);
  const controller = useRef<AbortController | null>(null);

  const load = useCallback(() => {
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    const request = ++epoch.current;
    setCatalog({ scope: chatScope, status: 'loading', ...emptyCatalog });
    void fetchCommands(config, abort.signal).then(result => {
      if (epoch.current === request && !abort.signal.aborted) {
        setCatalog({ scope: chatScope, status: result.status, commands: result.commands,
          shortcuts: result.status === 'available' ? result.shortcuts : [],
          truncated: result.status === 'available' && result.truncated,
          shortcutsUnavailable: result.status === 'available' && result.shortcutsUnavailable });
      }
    }).catch(error => {
      if (epoch.current === request && !abort.signal.aborted) {
        setCatalog({ scope: chatScope, status: 'error', ...emptyCatalog,
          error: error instanceof ApiError ? error.message : 'Failed to load commands' });
      }
    });
  }, [config, chatScope]);

  useEffect(() => {
    if (visible) load();
    return () => { ++epoch.current; controller.current?.abort(); controller.current = null; };
  }, [visible, load]);

  const close = useCallback(() => {
    ++epoch.current;
    controller.current?.abort();
    controller.current = null;
    setCatalog({ scope: '', status: 'loading', ...emptyCatalog });
    onClose();
  }, [onClose]);

  const current: CatalogState = catalog.scope === chatScope ? catalog
    : { scope: chatScope, status: 'loading', ...emptyCatalog };
  const rows: Array<{ kind: 'command'; item: CommandSummary } | { kind: 'shortcut'; item: ShortcutSummary }> = [
    ...current.commands.map(item => ({ kind: 'command' as const, item })),
    ...current.shortcuts.map(item => ({ kind: 'shortcut' as const, item })),
  ];
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={close}>
      <View style={styles.backdrop}>
        <Pressable style={styles.dismissLayer} onPress={close} accessibilityLabel="Dismiss command catalog" />
        <View style={styles.sheet}>
          <View style={styles.header}>
            <Text style={styles.title}>Chat commands</Text>
            <Pressable onPress={close} accessibilityLabel="Close commands" hitSlop={8}>
              <Text style={styles.close}>Close commands</Text>
            </Pressable>
          </View>
          {current.status === 'loading' && <View style={styles.status}>
            <ActivityIndicator color={theme.accent} />
            <Text style={styles.muted}>Loading commands…</Text>
          </View>}
          {current.status === 'unavailable' && <Text style={styles.muted}>Commands unavailable on this hub.</Text>}
          {current.status === 'error' && <Text style={styles.error}>Could not load commands: {current.error}</Text>}
          {current.status === 'available' && rows.length === 0 &&
            <Text style={styles.muted}>No commands available for this account.</Text>}
          {current.status === 'available' && current.truncated &&
            <Text style={styles.muted}>Command catalog is truncated. Some choices are not shown.</Text>}
          {current.status === 'available' && current.shortcutsUnavailable &&
            <Text style={styles.muted}>Some shortcuts are unavailable right now.</Text>}
          {current.status === 'available' && rows.length > 0 && <FlatList
            data={rows}
            keyExtractor={row => `${row.kind}:${row.kind === 'shortcut' ? `${row.item.kind}:` : ''}${row.item.name}`}
            style={styles.list}
            renderItem={({ item: row }) => <Pressable style={styles.option}
              accessibilityLabel={`Insert ${row.item.command} in message`}
              onPress={() => { onChoose(row.item.command); close(); }}>
              <View style={styles.optionHeader}>
                <Text style={styles.command}>{row.item.command}</Text>
                <Text style={styles.tier}>{row.kind === 'shortcut'
                  ? `${({ quick: 'Quick command', skill: 'Skill', bundle: 'Bundle' })[row.item.kind]} · Owner`
                  : row.item.tier === 'admin' ? 'Owner' : 'User'}</Text>
              </View>
              <Text style={styles.usage}>{row.item.usage}</Text>
              <Text style={styles.description}>{row.item.description}</Text>
            </Pressable>}
          />}
          {current.status !== 'loading' && <Pressable style={styles.retry} onPress={load} accessibilityLabel="Retry commands">
            <Text style={styles.retryText}>Retry</Text>
          </Pressable>}
        </View>
      </View>
    </Modal>
  );
}

const makeStyles = (theme: Theme) => StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: '#000a', justifyContent: 'center', padding: 24 },
  dismissLayer: { position: 'absolute', top: 0, bottom: 0, left: 0, right: 0 },
  sheet: { backgroundColor: theme.surfaceAlt, borderRadius: 16, borderWidth: 1,
    borderColor: theme.border, padding: 16, maxHeight: '80%' },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  title: { color: theme.text, fontSize: 16, fontWeight: '700' },
  close: { color: theme.accent, fontSize: 13, fontWeight: '600' },
  status: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 16 },
  muted: { color: theme.textDim, fontSize: 14, paddingVertical: 12 },
  error: { color: theme.danger, fontSize: 13, paddingVertical: 12 },
  list: { flexGrow: 0 },
  option: { paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: theme.border },
  optionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  command: { color: theme.text, fontSize: 15, fontWeight: '700' },
  tier: { color: theme.accent, fontSize: 12 },
  usage: { color: theme.text, fontSize: 13, marginTop: 4 },
  description: { color: theme.textDim, fontSize: 13, marginTop: 4 },
  retry: { alignSelf: 'flex-end', paddingVertical: 8, paddingHorizontal: 10 },
  retryText: { color: theme.accent, fontSize: 13, fontWeight: '600' },
});
