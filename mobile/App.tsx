import { Text } from './src/components/ThemedText';
import { StatusBar } from 'expo-status-bar';
import React, { useState } from 'react';
import { Modal, Platform, Pressable, SafeAreaView, ScrollView, StyleSheet, View } from 'react-native';
import { AppearanceProvider } from './src/context/AppearanceContext';
import { ServerProvider } from './src/context/ServerContext';
import { ApprovalsScreen } from './src/screens/ApprovalsScreen';
import { AmbientScreen } from './src/screens/AmbientScreen';
import { AcquisitionScreen } from './src/screens/AcquisitionScreen';
import { ChatScreen } from './src/screens/ChatScreen';
import { CommsScreen } from './src/screens/CommsScreen';
import { CameraScreen } from './src/screens/CameraScreen';
import { CaptureScreen } from './src/screens/CaptureScreen';
import { HouseScreen } from './src/screens/HouseScreen';
import { MemoryScreen } from './src/screens/MemoryScreen';
import { MediaScreen } from './src/screens/MediaScreen';
import { SettingsScreen } from './src/screens/SettingsScreen';
import { SkillsScreen } from './src/screens/SkillsScreen';
import { StatusScreen } from './src/screens/StatusScreen';
import { TasksScreen } from './src/screens/TasksScreen';
import { useThemeStyles, type Theme } from './src/theme';

type Tab = 'chat' | 'memory' | 'approvals' | 'tasks' | 'ambient' | 'capture' | 'house' | 'cameras' | 'media' | 'acquisition' | 'comms' | 'skills' | 'status' | 'settings';

const TABS: { key: Tab; label: string; icon: string }[] = [
  { key: 'chat', label: 'Chat', icon: '◉' },
  { key: 'memory', label: 'Memory', icon: '◎' },
  { key: 'approvals', label: 'Approve', icon: '✓' },
  { key: 'tasks', label: 'Tasks', icon: '▦' },
  { key: 'ambient', label: 'Watch', icon: '◉' },
  { key: 'capture', label: 'Capture', icon: '⎘' },
  { key: 'house', label: 'Home', icon: '⌂' },
  { key: 'cameras', label: 'Cameras', icon: '◫' },
  { key: 'media', label: 'Media', icon: '▷' },
  { key: 'acquisition', label: 'Acquire', icon: '⬡' },
  { key: 'comms', label: 'Comms', icon: '✉' },
  { key: 'skills', label: 'Skills', icon: '◇' },
  { key: 'status', label: 'Status', icon: '▤' },
  { key: 'settings', label: 'Settings', icon: '⚙' },
];
const PRIMARY_TABS: Tab[] = ['chat', 'tasks', 'skills'];

const TITLES: Record<Tab, string> = {
  chat: 'Jarvis',
  memory: 'Memory',
  approvals: 'Approvals',
  tasks: 'Tasks',
  ambient: 'Ambient Watch',
  capture: 'Capture Inbox',
  house: 'House Brain',
  cameras: 'Camera Intelligence',
  media: 'Media Director',
  acquisition: 'Capability Acquisition',
  comms: 'Comms',
  skills: 'Skills',
  status: 'Status',
  settings: 'Settings',
};

function AppShell() {
  const { theme, styles } = useThemeStyles(makeStyles);
  const [tab, setTab] = useState<Tab>('chat');
  const [moreOpen, setMoreOpen] = useState(false);

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
        {tab === 'ambient' && <AmbientScreen onGoToSettings={() => setTab('settings')} />}
        {tab === 'capture' && <CaptureScreen onGoToSettings={() => setTab('settings')} />}
        {tab === 'house' && <HouseScreen onGoToSettings={() => setTab('settings')} onGoToApprovals={() => setTab('approvals')} />}
        {tab === 'cameras' && <CameraScreen onGoToSettings={() => setTab('settings')} />}
        {tab === 'media' && <MediaScreen onGoToSettings={() => setTab('settings')} onGoToApprovals={() => setTab('approvals')} />}
        {tab === 'acquisition' && <AcquisitionScreen onGoToSettings={() => setTab('settings')} />}
        {tab === 'comms' && <CommsScreen onGoToSettings={() => setTab('settings')} />}
        {tab === 'skills' && <SkillsScreen onGoToSettings={() => setTab('settings')} />}
        {tab === 'status' && <StatusScreen onGoToSettings={() => setTab('settings')} />}
        {tab === 'settings' && <SettingsScreen />}
      </View>

      <View style={styles.tabBar}>
        {TABS.filter(t => PRIMARY_TABS.includes(t.key)).map((t) => {
          const active = t.key === tab;
          return (
            <Pressable key={t.key} style={styles.tab} onPress={() => setTab(t.key)}
              accessibilityRole="tab" accessibilityLabel={`${t.label} tab`} accessibilityState={{ selected: active }}>
              <Text style={[styles.tabIcon, active && styles.tabActive]}>{t.icon}</Text>
              <Text style={[styles.tabLabel, active && styles.tabActive]}>{t.label}</Text>
            </Pressable>
          );
        })}
        <Pressable style={styles.tab} onPress={() => setMoreOpen(true)} accessibilityRole="tab"
          accessibilityLabel="More destinations" accessibilityState={{ selected: !PRIMARY_TABS.includes(tab) }}>
          <Text style={[styles.tabIcon, !PRIMARY_TABS.includes(tab) && styles.tabActive]}>⋯</Text>
          <Text style={[styles.tabLabel, !PRIMARY_TABS.includes(tab) && styles.tabActive]}>More</Text>
        </Pressable>
      </View>
      <Modal visible={moreOpen} transparent animationType="fade" onRequestClose={() => setMoreOpen(false)}>
        <View style={styles.menuBackdrop}>
          <Pressable style={styles.dismissLayer} onPress={() => setMoreOpen(false)} accessibilityLabel="Dismiss More menu" />
          <View style={styles.menuSheet}>
            <View style={styles.menuHeader}>
              <Text style={styles.menuTitle}>More destinations</Text>
              <Pressable onPress={() => setMoreOpen(false)} accessibilityLabel="Close More menu" style={styles.menuClose}>
                <Text style={styles.menuCloseText}>Close</Text>
              </Pressable>
            </View>
            <ScrollView style={styles.menuList}>
              {TABS.filter(t => !PRIMARY_TABS.includes(t.key)).map(t => {
                const active = t.key === tab;
                return <Pressable key={t.key} style={[styles.menuItem, active && styles.menuItemActive]}
                  onPress={() => { setTab(t.key); setMoreOpen(false); }} accessibilityRole="button"
                  accessibilityLabel={`Open ${TITLES[t.key]}${active ? ', current destination' : ''}`}
                  accessibilityState={{ selected: active }}>
                  <Text style={[styles.menuItemText, active && styles.tabActive]}>{t.icon}  {TITLES[t.key]}</Text>
                  {active && <Text style={styles.tabActive}>✓</Text>}
                </Pressable>;
              })}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

export default function App() {
  return (
    <ServerProvider><AppearanceProvider>
      <StatusBar style="light" />
      <AppShell />
    </AppearanceProvider></ServerProvider>
  );
}

const makeStyles = (theme: Theme) => StyleSheet.create({
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
  tab: { flex: 1, minHeight: 48, alignItems: 'center', justifyContent: 'center', paddingVertical: 4 },
  tabIcon: { color: theme.textDim, fontSize: 18, marginBottom: 2 },
  tabLabel: { color: theme.textDim, fontSize: 12, fontWeight: '600' },
  tabActive: { color: theme.accent },
  menuBackdrop: { flex: 1, backgroundColor: '#000a', justifyContent: 'flex-end', padding: 16 },
  dismissLayer: { position: 'absolute', top: 0, bottom: 0, left: 0, right: 0 },
  menuSheet: { backgroundColor: theme.surfaceAlt, borderColor: theme.border, borderWidth: 1,
    borderRadius: 16, padding: 12, maxHeight: '75%' },
  menuHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 8 },
  menuTitle: { color: theme.text, fontSize: 17, fontWeight: '700' },
  menuClose: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 8 },
  menuCloseText: { color: theme.accent, fontSize: 14, fontWeight: '600' },
  menuList: { flexShrink: 1 },
  menuItem: { minHeight: 48, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    borderBottomWidth: 1, borderBottomColor: theme.border, paddingHorizontal: 12 },
  menuItemActive: { backgroundColor: theme.surface },
  menuItemText: { color: theme.text, fontSize: 15, flexShrink: 1 },
});
