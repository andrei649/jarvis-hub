import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { ApiError } from '../api/client';
import {
  fetchExtensionInspection,
  type ExtensionInspectionReport,
  type ExtensionInspectionRow,
} from '../api/extensions';
import { useServer } from '../context/ServerContext';
import type { ServerConfig } from '../storage/settings';
import { useThemeStyles, type Theme } from '../theme';
import { Text } from './ThemedText';

const REPORT_REASON: Record<string, string> = {
  acquisition_unavailable: 'Acquisition inspection is unavailable.',
  acquisition_disabled: 'Acquisition is disabled.',
  acquisition_not_composed: 'The acquisition runtime is not composed.',
  extension_capacity: 'The extension inspection capacity was reached.',
  sdk_dispatch_unavailable: 'SDK dispatch is unavailable.',
  activated: 'An activation is present; callable surfaces are listed per extension.',
  acquisition_inspection_unavailable: 'The extension inspection could not read its current state.',
};

const ROW_REASON: Record<string, string> = {
  activated: 'Activated',
  acquired_inactive: 'Inactive',
  acquired_integrity_unverified: 'Integrity not verified',
  sdk_dispatch_unavailable: 'No callable surface',
};

/** A hub change remounts this closed, discarding the previous connection's metadata. */
export function ExtensionInspection() {
  const { config, chatScope, connectionEpoch, ready, configured } = useServer();
  return <ScopedExtensionInspection key={`${chatScope}:${connectionEpoch}`} config={config}
    ready={ready} configured={configured} />;
}

function ScopedExtensionInspection({ config, ready, configured }: {
  config: ServerConfig; ready: boolean; configured: boolean;
}) {
  const { styles } = useThemeStyles(makeStyles);
  const [open, setOpen] = useState(false);
  const [report, setReport] = useState<ExtensionInspectionReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const sequence = useRef(0);
  const controller = useRef<AbortController | null>(null);

  const load = useCallback(() => {
    if (!ready || !configured) return;
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    const request = ++sequence.current;
    setReport(null);
    setMessage(null);
    setLoading(true);
    void fetchExtensionInspection(config, abort.signal).then(value => {
      if (sequence.current === request && !abort.signal.aborted) {
        setReport(value);
        setLoading(false);
      }
    }, error => {
      if (sequence.current === request && !abort.signal.aborted) {
        const status = error instanceof ApiError ? error.status : undefined;
        setMessage(status === 401 ? 'Sign in to inspect extensions.'
          : status === 403 ? 'This account cannot inspect extensions.'
            : status === 503 ? 'The extension inspection service is unavailable.'
              : error instanceof ApiError && error.message === 'Invalid extension inspection'
                ? 'Extension inspection returned invalid data.'
                : 'Extension inspection unavailable.');
        setLoading(false);
      }
    });
  }, [config, configured, ready]);

  const close = useCallback(() => {
    ++sequence.current;
    controller.current?.abort();
    controller.current = null;
    setOpen(false);
    setReport(null);
    setMessage(null);
    setLoading(false);
  }, []);

  useEffect(() => () => {
    ++sequence.current;
    controller.current?.abort();
  }, []);

  useEffect(() => {
    if (open && ready && configured) load();
  }, [open, ready, configured, load]);

  const openDisclosure = () => {
    setOpen(true);
  };

  return (
    <View style={styles.card} accessibilityLabel="Extension inspection">
      <Text style={styles.title}>Extensions</Text>
      {!open ? (
        <Pressable style={styles.button} accessibilityRole="button"
          accessibilityLabel="Open extension inspection" onPress={openDisclosure}>
          <Text style={styles.action}>Open extensions</Text>
        </Pressable>
      ) : (
        <>
          <Text style={styles.note}>Read-only snapshot of declared and currently callable surfaces.</Text>
          <View style={styles.actions}>
            {ready && configured ? (
              <Pressable style={styles.button} accessibilityRole="button"
                accessibilityLabel="Refresh extension inspection" onPress={load}>
                <Text style={styles.action}>Refresh</Text>
              </Pressable>
            ) : null}
            <Pressable style={styles.button} accessibilityRole="button"
              accessibilityLabel="Close extension inspection" onPress={close}>
              <Text style={styles.action}>Close</Text>
            </Pressable>
          </View>
          {!ready ? <Text style={styles.note}>Loading connection settings…</Text>
            : !configured ? <Text style={styles.note}>Connect a hub in Settings to inspect extensions.</Text>
              : null}
          {loading ? <Text style={styles.note}>Checking extension state…</Text> : null}
          {message ? <Text style={styles.error} accessibilityRole="alert">{message}</Text> : null}
          {report ? <ReportView report={report} styles={styles} /> : null}
        </>
      )}
    </View>
  );
}

function ReportView({ report, styles }: {
  report: ExtensionInspectionReport;
  styles: ReturnType<typeof makeStyles>;
}) {
  return (
    <>
      <Text style={styles.note} accessibilityRole="text">
        {REPORT_REASON[report.reason] || 'Extension inspection returned an unknown status.'}
      </Text>
      {report.extensions.length > 0 ? (
        <Text style={styles.note}>
          Signature verification, owner approval, and current callability are separate facts.
        </Text>
      ) : null}
      {report.extensions.length === 0 ? (
        <Text style={styles.line}>No extensions reported in this inspection.</Text>
      ) : report.extensions.map(row => <ExtensionRowView key={row.id} row={row} styles={styles} />)}
    </>
  );
}

function ExtensionRowView({ row, styles }: {
  row: ExtensionInspectionRow;
  styles: ReturnType<typeof makeStyles>;
}) {
  return (
    <View style={styles.row} accessibilityLabel={`Extension ${row.id}`}>
      <View style={styles.heading}>
        <Text style={styles.name}>{row.id}</Text>
        <Text style={styles.badge}>{row.version}</Text>
        <Text style={styles.badge}>{ROW_REASON[row.reason] || 'Status unavailable'}</Text>
      </View>
      <Text style={styles.note}>Signature {row.signatureVerified ? 'verified' : 'not verified'}</Text>
      <Text style={styles.note}>Owner approval {row.approvalVerified ? 'verified' : 'not verified'}</Text>
      <Text style={styles.note}>Quarantine not checked</Text>
      <Text style={styles.note}>Execution {row.executionAvailable ? 'available' : 'unavailable'}</Text>
      <Values label="Declared tools" items={row.declaredTools} styles={styles} />
      <Values label="Currently callable tools" items={row.callableTools}
        emptyLabel="none currently callable" styles={styles} />
      <Values label="Declared commands" items={row.declaredCommands}
        requiresArgs={row.commandRequiresArgs} styles={styles} />
      <Values label="Currently callable commands" items={row.callableCommands}
        requiresArgs={row.commandRequiresArgs} emptyLabel="none currently callable" styles={styles} />
      <Values label="Declared events" items={row.declaredEvents} styles={styles} />
    </View>
  );
}

function Values({ label, items, requiresArgs = [], emptyLabel = 'none declared', styles }: {
  label: string; items: string[]; requiresArgs?: string[]; emptyLabel?: string;
  styles: ReturnType<typeof makeStyles>;
}) {
  return (
    <View style={styles.values} accessibilityLabel={label}>
      <Text style={styles.valueLabel}>{label}</Text>
      {items.length ? items.map(item => (
        <Text key={item} style={styles.line}>
          {item}{requiresArgs.includes(item) ? ' · requires arguments' : ''}
        </Text>
      )) : <Text style={styles.note}>{emptyLabel}</Text>}
    </View>
  );
}

const makeStyles = (theme: Theme) => StyleSheet.create({
  card: { backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1,
    borderRadius: 12, padding: 16, gap: 7 },
  title: { color: theme.text, fontSize: 16, fontWeight: '700' },
  note: { color: theme.textDim, fontSize: 12, lineHeight: 17, marginTop: 3 },
  error: { color: theme.warn, fontSize: 13, lineHeight: 18 },
  line: { color: theme.text, fontSize: 13, lineHeight: 18 },
  actions: { flexDirection: 'row', gap: 8 },
  button: { borderColor: theme.border, borderWidth: 1, borderRadius: 8,
    paddingHorizontal: 12, paddingVertical: 7, minHeight: 36, justifyContent: 'center' },
  action: { color: theme.accent, fontSize: 13, fontWeight: '600' },
  row: { borderTopColor: theme.border, borderTopWidth: 1, paddingTop: 9, marginTop: 8, gap: 3 },
  heading: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 6 },
  name: { color: theme.accent, fontSize: 13, fontWeight: '700' },
  badge: { color: theme.text, borderColor: theme.border, borderWidth: 1,
    borderRadius: 6, paddingHorizontal: 6, paddingVertical: 2, fontSize: 11 },
  values: { gap: 2, marginTop: 3 },
  valueLabel: { color: theme.textDim, fontSize: 11, fontWeight: '600', marginBottom: 2 },
});
