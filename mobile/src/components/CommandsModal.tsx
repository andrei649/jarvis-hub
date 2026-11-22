import { Text, TextInput } from './ThemedText';
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

export function CommandsModal({ visible, agent, onClose, onChoose }: {
  visible: boolean;
  agent: string;
  onClose: () => void;
  onChoose: (command: string, kind?: 'skill') => boolean | string | void;
}) {
  const { theme, styles } = useThemeStyles(makeStyles);
  const { config, chatScope, connectionEpoch } = useServer();
  const [catalog, setCatalog] = useState<CatalogState>({ scope: '', status: 'loading', ...emptyCatalog });
  const [filter, setFilter] = useState<'all' | 'skills'>('all');
  const [search, setSearch] = useState('');
  const [choiceError, setChoiceError] = useState('');
  const epoch = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const scope = JSON.stringify([chatScope, connectionEpoch, agent]);

  const load = useCallback(() => {
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    const request = ++epoch.current;
    setCatalog({ scope, status: 'loading', ...emptyCatalog });
    setFilter('all');
    setSearch('');
    setChoiceError('');
    if (!agent.trim()) {
      setCatalog({ scope, status: 'error', ...emptyCatalog, error: 'Choose an agent before opening commands.' });
      return;
    }
    void fetchCommands(config, abort.signal, agent).then(result => {
      if (epoch.current === request && !abort.signal.aborted) {
        setCatalog({ scope, status: result.status, commands: result.commands,
          shortcuts: result.status === 'available' ? result.shortcuts : [],
          truncated: result.status === 'available' && result.truncated,
          shortcutsUnavailable: result.status === 'available' && result.shortcutsUnavailable });
      }
    }).catch(error => {
      if (epoch.current === request && !abort.signal.aborted) {
        setCatalog({ scope, status: 'error', ...emptyCatalog,
          error: error instanceof ApiError ? error.message : 'Failed to load commands' });
      }
    });
  }, [config, scope, agent]);

  useEffect(() => {
    if (visible) load();
    return () => { ++epoch.current; controller.current?.abort(); controller.current = null; };
  }, [visible, load]);

  const close = useCallback(() => {
    ++epoch.current;
    controller.current?.abort();
    controller.current = null;
    setCatalog({ scope: '', status: 'loading', ...emptyCatalog });
    setChoiceError('');
    onClose();
  }, [onClose]);

  const current: CatalogState = catalog.scope === scope ? catalog
    : { scope, status: 'loading', ...emptyCatalog };
  const rows: Array<{ kind: 'command'; item: CommandSummary } | { kind: 'shortcut'; item: ShortcutSummary }> = [
    ...current.commands.map(item => ({ kind: 'command' as const, item })),
    ...current.shortcuts.map(item => ({ kind: 'shortcut' as const, item })),
  ];
  const skills = rows.filter(row => row.kind === 'shortcut' && row.item.kind === 'skill');
  const showSkills = Boolean(config.adminToken.trim()) || skills.length > 0;
  const query = search.trim().toLowerCase().replace(/[-_]+/g, ' ');
  const visibleRows = filter === 'skills' && showSkills
    ? skills.filter(row => row.item.name.toLowerCase().replace(/[-_]+/g, ' ').includes(query)) : rows;
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
          <Text style={styles.destination}>Insert into chat with {agent || 'no agent selected'}</Text>
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
          {!!choiceError && <Text style={styles.error} accessibilityLiveRegion="polite">{choiceError}</Text>}
          {current.status === 'available' && showSkills && <View style={styles.filters}>
            <Pressable onPress={() => { setFilter('all'); setSearch(''); }} accessibilityLabel="Show all commands">
              <Text style={filter === 'all' ? styles.activeFilter : styles.filter}>All</Text>
            </Pressable>
            <Pressable onPress={() => { setFilter('skills'); setSearch(''); }} accessibilityLabel="Show skills">
              <Text style={filter === 'skills' ? styles.activeFilter : styles.filter}>Skills</Text>
            </Pressable>
          </View>}
          {current.status === 'available' && filter === 'skills' && skills.length > 1 &&
            <TextInput accessibilityLabel="Search skills" placeholder="Search skills" value={search}
              onChangeText={setSearch} autoCapitalize="none" maxLength={64} style={styles.search} />}
          {current.status === 'available' && filter === 'skills' && skills.length === 0 &&
            <Text style={styles.muted}>This hub listed no skills for {agent}.</Text>}
          {current.status === 'available' && filter === 'skills' && skills.length > 0 && visibleRows.length === 0 &&
            <Text style={styles.muted}>No matching skills.</Text>}
          {current.status === 'available' && rows.length > 0 && <FlatList
            data={visibleRows}
            keyExtractor={row => `${row.kind}:${row.kind === 'shortcut' ? `${row.item.kind}:` : ''}${row.item.name}`}
            style={styles.list}
            renderItem={({ item: row }) => <Pressable style={styles.option}
              accessibilityLabel={`Insert ${row.item.command} in message`}
              onPress={() => {
                const chosen = row.kind === 'shortcut' && row.item.kind === 'skill'
                  ? onChoose(row.item.command, 'skill') : onChoose(row.item.command);
                if (typeof chosen === 'string') setChoiceError(chosen);
                else if (chosen === false) setChoiceError('Selection was not inserted. Your chat destination or draft changed. Close and reopen Commands for the current agent.');
                else close();
              }}>
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
  destination: { color: theme.textDim, fontSize: 13, marginBottom: 8 },
  close: { color: theme.accent, fontSize: 13, fontWeight: '600' },
  status: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 16 },
  muted: { color: theme.textDim, fontSize: 14, paddingVertical: 12 },
  error: { color: theme.danger, fontSize: 13, paddingVertical: 12 },
  filters: { flexDirection: 'row', gap: 16, paddingVertical: 8 },
  filter: { color: theme.textDim, fontSize: 13 },
  activeFilter: { color: theme.accent, fontSize: 13, fontWeight: '700' },
  search: { color: theme.text, backgroundColor: theme.surface, borderColor: theme.border,
    borderWidth: 1, borderRadius: 8, paddingHorizontal: 10, minHeight: 40, marginBottom: 4 },
  list: { flexGrow: 0, flexShrink: 1 },
  option: { paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: theme.border },
  optionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' },
  command: { color: theme.text, fontSize: 15, fontWeight: '700', flexShrink: 1 },
  tier: { color: theme.accent, fontSize: 12, marginLeft: 8 },
  usage: { color: theme.text, fontSize: 13, marginTop: 4 },
  description: { color: theme.textDim, fontSize: 13, marginTop: 4 },
  retry: { alignSelf: 'flex-end', paddingVertical: 8, paddingHorizontal: 10 },
  retryText: { color: theme.accent, fontSize: 13, fontWeight: '600' },
});
