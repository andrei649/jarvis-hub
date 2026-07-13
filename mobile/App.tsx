import { StatusBar } from 'expo-status-bar';
import React, { useState } from 'react';
import { Platform, Pressable, SafeAreaView, StyleSheet, Text, View } from 'react-native';
import { ServerProvider } from './src/context/ServerContext';
import { ApprovalsScreen } from './src/screens/ApprovalsScreen';
import { ChatScreen } from './src/screens/ChatScreen';
import { CommsScreen } from './src/screens/CommsScreen';
import { MemoryScreen } from './src/screens/MemoryScreen';
import { MediaScreen } from './src/screens/MediaScreen';
import { SettingsScreen } from './src/screens/SettingsScreen';
import { SkillsScreen } from './src/screens/SkillsScreen';
import { StatusScreen } from './src/screens/StatusScreen';
import { TasksScreen } from './src/screens/TasksScreen';
import { theme } from './src/theme';

type Tab = 'chat' | 'memory' | 'approvals' | 'tasks' | 'media' | 'comms' | 'skills' | 'status' | 'settings';

const TABS: { key: Tab; label: string; icon: string }[] = [
  { key: 'chat', label: 'Chat', icon: '◉' },
  { key: 'memory', label: 'Memory', icon: '◎' },
  { key: 'approvals', label: 'Approve', icon: '✓' },
  { key: 'tasks', label: 'Tasks', icon: '▦' },
  { key: 'media', label: 'Media', icon: '▷' },
  { key: 'comms', label: 'Comms', icon: '✉' },
  { key: 'skills', label: 'Skills', icon: '◇' },
  { key: 'status', label: 'Status', icon: '▤' },
  { key: 'settings', label: 'Settings', icon: '⚙' },
];

const TITLES: Record<Tab, string> = {
  chat: 'Jarvis',
  memory: 'Memory',
  approvals: 'Approvals',
  tasks: 'Tasks',
  media: 'Media Director',
  comms: 'Comms',
  skills: 'Skills',
  status: 'Status',
  settings: 'Settings',
};

function AppShell() {
  const [tab, setTab] = useState<Tab>('chat');

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>{TITLES[tab]}</Text>
      </View>

      <View style={styles.body}>
        {tab === 'chat' && <ChatScreen onGoToSettings={() => setTab('settings')} />}
        {tab === 'memory' && <MemoryScreen onGoToSettings={() => setTab('settings')} />}
        {tab === 'approvals' && <ApprovalsScreen onGoToSettings={() => setTab('settings')} />}
        {tab === 'tasks' && <TasksScreen onGoToSettings={() => setTab('settings')} />}
        {tab === 'media' && <MediaScreen onGoToSettings={() => setTab('settings')} />}
        {tab === 'comms' && <CommsScreen onGoToSettings={() => setTab('settings')} />}
        {tab === 'skills' && <SkillsScreen onGoToSettings={() => setTab('settings')} />}
        {tab === 'status' && <StatusScreen onGoToSettings={() => setTab('settings')} />}
        {tab === 'settings' && <SettingsScreen />}
      </View>

      <View style={styles.tabBar}>
        {TABS.map((t) => {
          const active = t.key === tab;
          return (
            <Pressable key={t.key} style={styles.tab} onPress={() => setTab(t.key)}>
              <Text style={[styles.tabIcon, active && styles.tabActive]}>{t.icon}</Text>
              <Text style={[styles.tabLabel, active && styles.tabActive]}>{t.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </SafeAreaView>
  );
}

export default function App() {
  return (
    <ServerProvider>
      <StatusBar style="light" />
      <AppShell />
    </ServerProvider>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: theme.bg,
    paddingTop: Platform.OS === 'android' ? 24 : 0,
  },
  header: {
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
    backgroundColor: theme.surfaceAlt,
  },
  headerTitle: {
    color: theme.text,
    fontSize: 20,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  body: { flex: 1 },
  tabBar: {
    flexDirection: 'row',
    borderTopWidth: 1,
    borderTopColor: theme.border,
    backgroundColor: theme.surfaceAlt,
    paddingBottom: Platform.OS === 'ios' ? 18 : 6,
    paddingTop: 6,
  },
  tab: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingVertical: 4 },
  tabIcon: { color: theme.textDim, fontSize: 18, marginBottom: 2 },
  tabLabel: { color: theme.textDim, fontSize: 10, fontWeight: '600' },
  tabActive: { color: theme.accent },
});
