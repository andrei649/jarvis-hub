import React, { useCallback, useEffect, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import {
  ApiError,
  commandCenterModelLabel,
  fetchCapabilities,
  fetchCommandCenter,
  type AutonomyBriefResponse,
  fetchAutonomyBrief,
  fetchDashboard,
  fetchSecurityGovernance,
  fetchSecurityKillSwitch,
  fetchSecurityLoopBreaker,
  fetchSecurityPosture,
  fetchStatus,
  fetchTicker,
  type CapabilitiesResponse,
  type CommandCenterResponse,
  type DashboardResponse,
  type SecurityGovernanceResponse,
  type SecurityKillSwitchResponse,
  type SecurityLoopBreakerResponse,
  type SecurityPostureResponse,
  type StatusResponse,
  type TickerResponse,
} from '../api/client';
import { speak, stopSpeaking } from '../audio/tts';
import { useServer } from '../context/ServerContext';
import { theme } from '../theme';

function Row({ label, value }: { label: string; value: string | number | undefined | null }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue}>{value === undefined || value === null || value === '' ? '—' : String(value)}</Text>
    </View>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.card}>
      <Text style={styles.cardTitle}>{title}</Text>
      {children}
    </View>
  );
}

const STATE_COLOR: Record<string, string> = {
  ready: theme.ok,
  no_model: theme.warn,
  offline: theme.danger,
};

const TICKER_COLOR: Record<string, string> = {
  high: theme.danger,
  critical: theme.danger,
  mid: theme.warn,
  elevated: theme.warn,
  low: theme.ok,
};

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

function scoreLabel(value: number | undefined): string {
  if (value === undefined) return '—';
  return `${Math.round(value * 100)}%`;
}

export function StatusScreen({ onGoToSettings }: { onGoToSettings: () => void }) {
  const { config, configured } = useServer();
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [ticker, setTicker] = useState<TickerResponse | null>(null);
  const [governance, setGovernance] = useState<SecurityGovernanceResponse | null>(null);
  const [posture, setPosture] = useState<SecurityPostureResponse | null>(null);
  const [killSwitch, setKillSwitch] = useState<SecurityKillSwitchResponse | null>(null);
  const [loopBreaker, setLoopBreaker] = useState<SecurityLoopBreakerResponse | null>(null);
  const [commandCenter, setCommandCenter] = useState<CommandCenterResponse | null>(null);
  const [capabilities, setCapabilities] = useState<CapabilitiesResponse | null>(null);
  const [brief, setBrief] = useState<AutonomyBriefResponse | null>(null);
  const [speaking, setSpeaking] = useState(false);
  const [briefError, setBriefError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!configured) return;
    setLoading(true);
    setError(null);
    try {
      const [statusOut, dashboardOut, tickerOut] = await Promise.all([
        fetchStatus(config),
        fetchDashboard(config).catch(() => ({ calendar: [], notifications: [] })),
        fetchTicker(config).catch(() => ({ ticker: [] })),
      ]);
      setStatus(statusOut);
      setDashboard(dashboardOut);
      setTicker(tickerOut);
      const [governanceOut, postureOut, killOut, loopOut, ccOut, capsOut] = await Promise.all([
        fetchSecurityGovernance(config).catch(() => null),
        fetchSecurityPosture(config).catch(() => null),
        fetchSecurityKillSwitch(config).catch(() => null),
        fetchSecurityLoopBreaker(config).catch(() => null),
        fetchCommandCenter(config).catch(() => null),
        fetchCapabilities(config).catch(() => null),
      ]);
      const briefOut = await fetchAutonomyBrief(config).catch(() => null);
      setBrief(briefOut);
      setGovernance(governanceOut);
      setPosture(postureOut);
      setKillSwitch(killOut);
      setLoopBreaker(loopOut);
      setCommandCenter(ccOut);
      setCapabilities(capsOut);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load status');
      setStatus(null);
      setDashboard(null);
      setTicker(null);
      setGovernance(null);
      setPosture(null);
      setKillSwitch(null);
      setLoopBreaker(null);
      setCommandCenter(null);
      setCapabilities(null);
      setBrief(null);
    } finally {
      setLoading(false);
    }
  }, [config, configured]);

  useEffect(() => {
    load();
  }, [load]);

  if (!configured) {
    return (
      <View style={styles.empty}>
        <Text style={styles.emptyTitle}>No hub connected</Text>
        <Pressable style={styles.cta} onPress={onGoToSettings}>
          <Text style={styles.ctaText}>Open Settings</Text>
        </Pressable>
      </View>
    );
  }

  const sys = status?.sys;
  const stateColor = STATE_COLOR[status?.model_state ?? ''] ?? theme.textDim;
  const weather = dashboard?.weather;
  const tickerRows = ticker?.ticker ?? [];

  return (
    <ScrollView
      style={styles.flex}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.accent} />}
    >
      {error && (
        <View style={styles.errorBox}>
          <Text style={styles.errorText}>{error}</Text>
        </View>
      )}

      <Card title="Model">
        <View style={styles.stateRow}>
          <View style={[styles.dot, { backgroundColor: stateColor }]} />
          <Text style={[styles.stateText, { color: stateColor }]}>
            {(status?.model_state ?? 'unknown').toUpperCase()}
          </Text>
        </View>
        <Row label="Backend" value={status?.llm_backend} />
        <Row label="Loaded" value={status?.loaded_model} />
        <Row label="Configured" value={status?.active_model} />
        <Row label="Reachable" value={status?.lm_online ? 'yes' : 'no'} />
      </Card>

      <Card title="First-run">
        {commandCenter ? (
          <>
            <Row
              label="Install"
              value={`${commandCenter.install.ready ? 'ready' : 'starting'}${commandCenter.install.version ? ` · v${commandCenter.install.version}` : ''}`}
            />
            <Row
              label="Model"
              value={commandCenterModelLabel(commandCenter.model)}
            />
            <Row
              label="Onboarding"
              value={`${commandCenter.wizard.completed.length}/${commandCenter.wizard.steps.length}${commandCenter.wizard.complete ? ' ✓' : ''}`}
            />
            {commandCenter.wizard.hint ? (
              <Text style={styles.emptyText}>{commandCenter.wizard.hint}</Text>
            ) : null}
            {commandCenter.first_actions.map((a) => (
              <Row key={a.key} label={a.title} value={a.ready ? 'ready' : a.reason || 'held'} />
            ))}
          </>
        ) : (
          <Text style={styles.emptyText}>No first-run data</Text>
        )}
      </Card>

      <Card title="Trust">
        {governance || posture || killSwitch || loopBreaker ? (
          <>
            <View style={styles.stateRow}>
              <View
                style={[
                  styles.dot,
                  { backgroundColor: governance?.pass === false ? theme.danger : theme.ok },
                ]}
              />
              <Text style={[styles.stateText, { color: governance?.pass === false ? theme.danger : theme.ok }]}>
                {governance ? (governance.pass ? 'GATE PASS' : 'GATE REVIEW') : 'TRUST READ'}
              </Text>
            </View>
            <Row label="Score" value={governance ? scoreLabel(governance.overall_score) : undefined} />
            <Row label="Injection" value={governance ? scoreLabel(governance.injection.score) : undefined} />
            <Row label="Harm" value={governance ? scoreLabel(governance.harm.score) : undefined} />
            <Row label="OWASP" value={governance ? scoreLabel(governance.owasp.score) : undefined} />
            <Row label="Secrets" value={posture?.secrets.encrypted_at_rest ? posture.secrets.backend || 'encrypted' : posture ? 'not encrypted' : undefined} />
            <Row
              label="Skills"
              value={posture ? `${posture.skills.trusted}/${posture.skills.total} trusted` : undefined}
            />
            <Row
              label="Sandbox"
              value={posture ? `${posture.sandbox.backend || 'unknown'} · ${posture.sandbox.isolated ? 'isolated' : 'not isolated'}` : undefined}
            />
            <Row label="Guardrails" value={posture?.guardrails.mode} />
            <Row label="Kill-switch" value={killSwitch?.global ? 'engaged' : killSwitch ? 'armed' : undefined} />
            <Row
              label="Loop breaker"
              value={loopBreaker?.tripped ? 'tripped' : loopBreaker ? 'clear' : undefined}
            />
          </>
        ) : (
          <Text style={styles.emptyText}>No trust data</Text>
        )}
      </Card>

      <Card title="Capabilities">
        {capabilities ? (
          <>
            <Row label="Total" value={capabilities.total} />
            <Row label="Seam" value={capabilities.byState.seam ?? 0} />
            <Row label="Wired" value={capabilities.byState.wired ?? 0} />
            <Row label="Verified" value={capabilities.byState.verified ?? 0} />
            <Row label="GA" value={capabilities.byState.ga ?? 0} />
            {capabilities.harnessPending && capabilities.total > 0 && (
              <Text style={styles.emptyText}>harness pending — wired, not yet proven</Text>
            )}
          </>
        ) : (
          <Text style={styles.emptyText}>No capability data</Text>
        )}
      </Card>

      <Card title="Morning brief">
        {brief && brief.text ? (
          <>
            <Text style={styles.briefText} numberOfLines={12}>{brief.text}</Text>
            <Pressable
              style={[styles.cta, speaking && styles.ctaBusy]}
              accessibilityLabel="speak brief"
              onPress={async () => {
                if (speaking) {
                  stopSpeaking();
                  setSpeaking(false);
                  return;
                }
                setBriefError(null);
                setSpeaking(true);
                try {
                  await speak(config, brief.text, 'ro', () => setSpeaking(false));
                } catch {
                  // Server TTS unavailable — stay honest, never fake playback.
                  setBriefError('TTS unavailable on the hub');
                  setSpeaking(false);
                }
              }}
            >
              <Text style={styles.ctaText}>{speaking ? '■ Stop' : '🔊 Speak'}</Text>
            </Pressable>
            {briefError && <Text style={styles.briefErr}>{briefError}</Text>}
          </>
        ) : (
          <Text style={styles.dim}>
            {config.adminToken.trim()
              ? 'No brief available yet.'
              : 'Set the admin token in Settings to read the morning brief.'}
          </Text>
        )}
      </Card>

      <Card title="Today">
        {weather ? (
          <>
            <Row label="Weather" value={[weather.temp, weather.desc].filter(Boolean).join(' · ')} />
            <Row label="City" value={weather.city} />
            <Row label="Wind" value={weather.wind} />
            <Row label="Humidity" value={weather.humidity} />
          </>
        ) : (
          <Text style={styles.emptyText}>No dashboard data</Text>
        )}
        <Row label="Calendar" value={plural(dashboard?.calendar.length ?? 0, 'event')} />
        <Row label="Notifications" value={plural(dashboard?.notifications.length ?? 0, 'item')} />
      </Card>

      <Card title="Ticker">
        {tickerRows.length === 0 ? (
          <Text style={styles.emptyText}>No live ticker items</Text>
        ) : (
          tickerRows.slice(0, 8).map((item, index) => {
            const tone = TICKER_COLOR[item.cls.toLowerCase()] ?? theme.accent;
            return (
              <View style={styles.tickerRow} key={`${item.agent || 'agent'}-${item.verb || 'tick'}-${index}`}>
                <View style={styles.tickerHeader}>
                  <Text style={styles.tickerAgent}>{item.agent || 'jarvis'}</Text>
                  <Text style={[styles.tickerVerb, { color: tone }]}>{item.verb || 'monitoring'}</Text>
                </View>
                <Text style={styles.tickerText}>{item.text || 'Activity update'}</Text>
                <View style={styles.progressTrack}>
                  <View style={[styles.progressFill, { width: `${Math.max(0, Math.min(100, item.bar))}%` }]} />
                </View>
              </View>
            );
          })
        )}
      </Card>

      <Card title="Agents">
        <Row label="Online" value={status?.agents_online} />
        <Row label="Total" value={status?.agents_total} />
      </Card>

      {sys && (
        <Card title="System">
          <Row label="Host" value={sys.host} />
          <Row label="CPU" value={sys.cpu} />
          <Row label="RAM" value={`${sys.ram_used} / ${sys.ram_total} GB`} />
          <Row label="GPU" value={sys.gpu} />
          <Row label="VRAM" value={`${sys.vram_used} / ${sys.vram_total} GB`} />
          <Row label="GPU load" value={`${sys.gpu_load}%`} />
          <Row label="Uptime" value={sys.uptime} />
          <Row label="Sessions" value={sys.sessions} />
        </Card>
      )}

      <Card title="Hub">
        <Row label="Version" value={status?.version} />
        <Row label="URL" value={config.baseUrl} />
      </Card>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { padding: 12 },
  card: {
    backgroundColor: theme.surface,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: theme.border,
    padding: 14,
    marginBottom: 12,
  },
  cardTitle: {
    color: theme.accent,
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 1.2,
    textTransform: 'uppercase',
    marginBottom: 10,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 5,
    gap: 12,
  },
  rowLabel: { color: theme.textDim, fontSize: 14 },
  rowValue: { color: theme.text, fontSize: 14, flexShrink: 1, textAlign: 'right' },
  stateRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 8 },
  dot: { width: 10, height: 10, borderRadius: 5, marginRight: 8 },
  stateText: { fontSize: 16, fontWeight: '700', letterSpacing: 1 },
  emptyText: { color: theme.textDim, fontSize: 14, paddingVertical: 5 },
  tickerRow: {
    borderTopWidth: 1,
    borderTopColor: theme.border,
    paddingTop: 10,
    marginTop: 10,
  },
  tickerHeader: { flexDirection: 'row', justifyContent: 'space-between', gap: 12 },
  tickerAgent: { color: theme.text, fontSize: 13, fontWeight: '700', textTransform: 'uppercase' },
  tickerVerb: { fontSize: 12, fontWeight: '700', textTransform: 'uppercase' },
  tickerText: { color: theme.textDim, fontSize: 13, marginTop: 4 },
  progressTrack: {
    height: 4,
    backgroundColor: theme.surfaceAlt,
    borderRadius: 2,
    overflow: 'hidden',
    marginTop: 8,
  },
  progressFill: { height: 4, backgroundColor: theme.accent },
  errorBox: {
    backgroundColor: '#2a0d16',
    borderColor: theme.danger,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
  },
  errorText: { color: theme.danger, fontSize: 14 },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  emptyTitle: { color: theme.text, fontSize: 20, fontWeight: '700', marginBottom: 20 },
  cta: { paddingHorizontal: 24, paddingVertical: 12, borderRadius: 24, backgroundColor: theme.accent },
  ctaBusy: { backgroundColor: theme.textDim },
  briefText: { color: theme.text, fontSize: 13, lineHeight: 19, marginBottom: 10 },
  briefErr: { color: theme.warn ?? '#e0a63a', fontSize: 12, marginTop: 8 },
  dim: { color: theme.textDim, fontSize: 13 },
  ctaText: { color: '#02121b', fontWeight: '700', fontSize: 15 },
});
