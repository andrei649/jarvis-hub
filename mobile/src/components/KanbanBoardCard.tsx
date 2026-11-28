import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { ApiError } from '../api/client';
import {
  dispatchKanbanReady,
  fetchKanbanSnapshot,
  proposeCompanyGoal,
  type KanbanBoardSnapshot,
} from '../api/kanban';
import { useServer } from '../context/ServerContext';
import type { ServerConfig } from '../storage/settings';
import { useThemeStyles, type Theme } from '../theme';
import { Text, TextInput } from './ThemedText';

export function KanbanBoardCard({ onGoToSettings }: { onGoToSettings: () => void }) {
  const { config, chatScope, connectionEpoch, ready, configured } = useServer();
  return (
    <ScopedKanbanBoardCard
      key={`${chatScope}:${connectionEpoch}`}
      config={config}
      ready={ready}
      configured={configured}
      onGoToSettings={onGoToSettings}
    />
  );
}

function ScopedKanbanBoardCard({
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
  const [selectedBoard, setSelectedBoard] = useState('');
  const [snapshot, setSnapshot] = useState<KanbanBoardSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dispatchStatus, setDispatchStatus] = useState<string | null>(null);
  const [goalDraft, setGoalDraft] = useState('');
  const [goalStatus, setGoalStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const sequence = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const hasAdmin = Boolean(config.adminToken.trim());

  const load = useCallback(
    (boardSlug = selectedBoard) => {
      if (!ready || !configured || !hasAdmin) return;
      controller.current?.abort();
      const abort = new AbortController();
      controller.current = abort;
      const reqId = ++sequence.current;
      setLoading(true);
      setError(null);
      void fetchKanbanSnapshot(config, boardSlug, abort.signal).then(
        data => {
          if (sequence.current === reqId && !abort.signal.aborted) {
            setSnapshot(data);
            setSelectedBoard(data.board);
            setLoading(false);
          }
        },
        err => {
          if (sequence.current === reqId && !abort.signal.aborted) {
            setSnapshot(null);
            setError(err instanceof ApiError ? err.message : 'Kanban board unavailable');
            setLoading(false);
          }
        },
      );
    },
    [config, configured, hasAdmin, ready, selectedBoard],
  );

  useEffect(() => {
    if (open && ready && configured && hasAdmin) load(selectedBoard);
  }, [open, ready, configured, hasAdmin, load, selectedBoard]);

  useEffect(
    () => () => {
      ++sequence.current;
      controller.current?.abort();
    },
    [],
  );

  const handleDispatch = async () => {
    if (!snapshot || busy) return;
    setBusy(true);
    setDispatchStatus(null);
    try {
      const out = await dispatchKanbanReady(config, snapshot.board, 4);
      if (!out.ok) {
        setDispatchStatus(`Dispatch refused: ${out.reason ?? out.status}`);
      } else if (out.queued.length > 0) {
        setDispatchStatus(`Queued ${out.queued.length} card(s) to Approvals inbox.`);
        load(snapshot.board);
      } else {
        setDispatchStatus(`No ready cards queued (${out.reason ?? out.status}).`);
      }
    } catch (err) {
      setDispatchStatus(err instanceof ApiError ? err.message : 'Dispatch failed');
    } finally {
      setBusy(false);
    }
  };

  const handleGoalSubmit = async () => {
    if (!goalDraft.trim() || busy) return;
    setBusy(true);
    setGoalStatus(null);
    try {
      const receipt = await proposeCompanyGoal(config, goalDraft);
      setGoalDraft('');
      setGoalStatus(`Goal proposed for approval (${receipt.taskId}): ${receipt.title}`);
    } catch (err) {
      setGoalStatus(err instanceof ApiError ? err.message : 'Could not propose goal');
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.card} accessibilityLabel="Kanban board and company goals">
      <View style={styles.headerRow}>
        <Text style={styles.title}>Kanban & Goals</Text>
        <Pressable
          style={styles.button}
          accessibilityRole="button"
          accessibilityLabel={open ? 'Close Kanban and goals' : 'Open Kanban and goals'}
          onPress={() => setOpen(v => !v)}
        >
          <Text style={styles.buttonText}>{open ? 'Close' : 'Open Kanban & goals'}</Text>
        </Pressable>
      </View>

      {open ? (
        !hasAdmin ? (
          <View style={styles.section}>
            <Text style={styles.dim}>
              Admin token required. Add one in Settings to inspect Kanban boards, active workers, governed dispatch, and company goals.
            </Text>
            <Pressable style={styles.button} onPress={onGoToSettings} accessibilityRole="button">
              <Text style={styles.buttonText}>Open Settings</Text>
            </Pressable>
          </View>
        ) : (
          <View style={styles.section}>
            <View style={styles.actionsRow}>
              <Pressable style={styles.button} onPress={() => load(selectedBoard)} accessibilityRole="button">
                <Text style={styles.buttonText}>{loading ? 'Refreshing…' : 'Refresh board'}</Text>
              </Pressable>
              {snapshot ? (
                <Pressable
                  style={styles.primaryBtn}
                  disabled={busy}
                  onPress={() => void handleDispatch()}
                  accessibilityRole="button"
                  accessibilityLabel="Dispatch ready Kanban tasks"
                >
                  <Text style={styles.primaryBtnText}>Dispatch ready</Text>
                </Pressable>
              ) : null}
            </View>

            {error ? <Text style={[styles.line, { color: theme.danger }]}>{error}</Text> : null}
            {dispatchStatus ? <Text style={styles.dim}>{dispatchStatus}</Text> : null}

            {snapshot ? (
              <>
                {snapshot.boards.length > 1 ? (
                  <View style={styles.actionsRow}>
                    {snapshot.boards.map(b => (
                      <Pressable
                        key={b.slug}
                        style={[styles.chip, b.slug === snapshot.board && styles.chipActive]}
                        onPress={() => {
                          setSelectedBoard(b.slug);
                          load(b.slug);
                        }}
                      >
                        <Text style={styles.chipText}>{b.name}</Text>
                      </Pressable>
                    ))}
                  </View>
                ) : null}

                <Text style={styles.line}>
                  Board: {snapshot.board} · Active workers: {snapshot.activeWorkers.length}
                </Text>

                {snapshot.columns.map(col => (
                  <View key={col.name} style={styles.colBox}>
                    <Text style={styles.colTitle}>
                      {col.name.toUpperCase()} ({col.tasks.length})
                    </Text>
                    {col.tasks.slice(0, 5).map(task => (
                      <Text key={task.id} style={styles.taskLine}>
                        • {task.title}
                        {task.assignee ? ` · ${task.assignee}` : ''}
                        {task.workerPid ? ` · pid ${task.workerPid}` : ''}
                        {task.warningCount > 0 ? ` · ⚠ ${task.warningCount}` : ''}
                      </Text>
                    ))}
                    {col.tasks.length > 5 ? (
                      <Text style={styles.dim}>+{col.tasks.length - 5} more in {col.name}</Text>
                    ) : null}
                  </View>
                ))}
              </>
            ) : null}

            <View style={styles.goalBox}>
              <Text style={styles.colTitle}>PROPOSE COMPANY GOAL (APPROVAL-GATED)</Text>
              <View style={styles.goalRow}>
                <TextInput
                  value={goalDraft}
                  onChangeText={setGoalDraft}
                  placeholder="Describe goal for owner inbox…"
                  placeholderTextColor={theme.textDim}
                  style={styles.input}
                />
                <Pressable
                  style={styles.primaryBtn}
                  disabled={busy || !goalDraft.trim()}
                  onPress={() => void handleGoalSubmit()}
                  accessibilityRole="button"
                  accessibilityLabel="Propose company goal"
                >
                  <Text style={styles.primaryBtnText}>Propose</Text>
                </Pressable>
              </View>
              {goalStatus ? <Text style={styles.dim}>{goalStatus}</Text> : null}
            </View>
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
    headerRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 10 },
    title: { color: theme.accent, fontSize: 13, fontWeight: '800', textTransform: 'uppercase' },
    section: { marginTop: 10, gap: 8 },
    actionsRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
    button: {
      borderColor: theme.border,
      borderWidth: 1,
      borderRadius: 10,
      paddingHorizontal: 12,
      paddingVertical: 7,
    },
    buttonText: { color: theme.accent, fontSize: 12, fontWeight: '700' },
    primaryBtn: {
      backgroundColor: theme.accent,
      borderRadius: 10,
      paddingHorizontal: 12,
      paddingVertical: 8,
      justifyContent: 'center',
    },
    primaryBtnText: { color: '#02121b', fontSize: 12, fontWeight: '800' },
    chip: {
      borderColor: theme.border,
      borderWidth: 1,
      borderRadius: 12,
      paddingHorizontal: 10,
      paddingVertical: 4,
    },
    chipActive: { borderColor: theme.accent, backgroundColor: theme.accentDim },
    chipText: { color: theme.text, fontSize: 12, fontWeight: '600' },
    line: { color: theme.text, fontSize: 13 },
    dim: { color: theme.textDim, fontSize: 12, lineHeight: 17 },
    colBox: {
      borderTopWidth: 1,
      borderTopColor: theme.border,
      paddingTop: 8,
      gap: 3,
    },
    colTitle: { color: theme.textDim, fontSize: 11, fontWeight: '800' },
    taskLine: { color: theme.text, fontSize: 13, lineHeight: 18 },
    goalBox: {
      borderTopWidth: 1,
      borderTopColor: theme.border,
      paddingTop: 10,
      gap: 6,
    },
    goalRow: { flexDirection: 'row', gap: 8 },
    input: {
      flex: 1,
      backgroundColor: theme.surfaceAlt,
      borderColor: theme.border,
      borderWidth: 1,
      borderRadius: 10,
      color: theme.text,
      fontSize: 13,
      paddingHorizontal: 10,
      paddingVertical: 7,
    },
  });
