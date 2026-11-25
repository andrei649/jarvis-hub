import { Text, TextInput } from './ThemedText';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Modal, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import * as FileSystem from 'expo-file-system/legacy';
import { historyRequiresCloudConsent, projectSessionTranscript, validHistoryReference, type HistorySelection } from '../api/sessionTranscript';
import { ApiError, fetchSessionTranscript, fetchSessions, fetchSessionsPage, resumeSession, resumeTarget, searchSessionMessages, verifiedSessionTurn, type HistoryTurn, type SessionInfo, type SessionMessageHit, type SessionTranscript } from '../api/client';
import { useServer } from '../context/ServerContext';
import { useThemeStyles, type Theme } from '../theme';

/** Lists the hub's recent sessions and resumes one into the chat thread. */
export function SessionsModal({
  visible,
  onClose,
  onResumed,
  resumeBlockReason,
  hasDraft,
  recipient,
  onUseSource,
  sourceBlockReason,
  startInMessages = false,
}: {
  visible: boolean;
  onClose: () => void;
  onResumed: (sessionId: string, turns: HistoryTurn[]) => void;
  resumeBlockReason?: () => string | null;
  hasDraft?: boolean;
  recipient?: string;
  onUseSource?: (selection: HistorySelection) => boolean;
  sourceBlockReason?: () => string | null;
  startInMessages?: boolean;
}) {
  const { theme, styles } = useThemeStyles(makeStyles);
  const { config, connectionEpoch } = useServer();
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<'sessions' | 'messages'>(startInMessages ? 'messages' : 'sessions');
  const [messageQuery, setMessageQuery] = useState('');
  const [messageResults, setMessageResults] = useState<{ hits: SessionMessageHit[]; truncated: boolean; stopped_by: string | null; request: number } | null>(null);
  const [reviewed, setReviewed] = useState<{ hit: SessionMessageHit; turn: SessionTranscript['turns'][number]; request: number } | null>(null);
  const [messageBusy, setMessageBusy] = useState<'search' | 'review' | 'continue' | 'stage' | null>(null);
  const [messageError, setMessageError] = useState<string | null>(null);
  const [passage, setPassage] = useState('');
  const [cloudAllowed, setCloudAllowed] = useState(false);
  const [agentFilter, setAgentFilter] = useState<string | null>(null);
  const [dateFilter, setDateFilter] = useState('All dates');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [recentOnly, setRecentOnly] = useState(false);
  const [preview, setPreview] = useState<{ document: SessionTranscript; request: number } | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [transcriptError, setTranscriptError] = useState<string | null>(null);
  const [saveNote, setSaveNote] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const transcriptEpoch = useRef(0);
  const transcriptScope = useRef({ config, connectionEpoch });
  const saveBusy = useRef(false);
  const fileSequence = useRef(0);
  const epoch = useRef(0);
  const listBusy = useRef(false);
  const olderBusy = useRef(false);
  const resumeBusy = useRef(false);
  const messageEpoch = useRef(0);
  const messageBusyRef = useRef(false);
  const messageScope = useRef({ config, connectionEpoch });
  const seenCursors = useRef(new Set<string>());
  const scope = useRef({ config, connectionEpoch, visible, recipient });
  scope.current = { config, connectionEpoch, visible, recipient };

  const isCurrent = useCallback((request: number) => epoch.current === request
    && scope.current.visible && scope.current.config === config
    && scope.current.connectionEpoch === connectionEpoch, [config, connectionEpoch]);

  const clearTranscript = useCallback(() => {
    ++transcriptEpoch.current;
    saveBusy.current = false;
    setPreview(null);
    setPreviewId(null);
    setTranscriptError(null);
    setSaveNote(null);
    setSaving(false);
  }, []);

  const transcriptCurrent = useCallback((request: number) => transcriptEpoch.current === request
    && transcriptScope.current.config === config && transcriptScope.current.connectionEpoch === connectionEpoch
    && scope.current.visible && scope.current.config === config
    && scope.current.connectionEpoch === connectionEpoch, [config, connectionEpoch]);

  const messageCurrent = useCallback((request: number) => messageEpoch.current === request
    && messageScope.current.config === config && messageScope.current.connectionEpoch === connectionEpoch
    && scope.current.visible && scope.current.config === config
    && scope.current.connectionEpoch === connectionEpoch && scope.current.recipient === recipient,
    [config, connectionEpoch, recipient]);

  const clearMessageSearch = useCallback(() => {
    ++messageEpoch.current;
    messageBusyRef.current = false;
    setMessageResults(null);
    setReviewed(null);
    setPassage('');
    setCloudAllowed(false);
    setMessageBusy(null);
    setMessageError(null);
  }, []);

  const close = useCallback(() => {
    clearTranscript();
    clearMessageSearch();
    ++epoch.current;
    listBusy.current = false;
    olderBusy.current = false;
    resumeBusy.current = false;
    onClose();
  }, [onClose, clearTranscript, clearMessageSearch]);

  const load = useCallback(async () => {
    if (resumeBusy.current || !scope.current.visible) return;
    clearTranscript();
    const request = ++epoch.current;
    listBusy.current = true;
    olderBusy.current = false;
    seenCursors.current.clear();
    setNextCursor(null);
    setRecentOnly(false);
    setLoadingOlder(false);
    setLoading(true);
    setError(null);
    try {
      try {
        const result = await fetchSessionsPage(config);
        if (!isCurrent(request)) return;
        if (result.next_cursor !== null) seenCursors.current.add(result.next_cursor);
        setSessions(result.sessions);
        setNextCursor(result.next_cursor);
      } catch (e) {
        if (!isCurrent(request)) return;
        if (!(e instanceof ApiError) || ![401, 403, 404, 405].includes(e.status ?? 0)) throw e;
        // The legacy endpoint independently authorizes this request.
        const result = await fetchSessions(config);
        if (!isCurrent(request)) return;
        setSessions(result);
        setRecentOnly(true);
      }
    } catch (e) {
      if (isCurrent(request)) setError(e instanceof ApiError ? e.message : 'Failed to load sessions');
    } finally {
      if (isCurrent(request)) {
        listBusy.current = false;
        setLoading(false);
      }
    }
  }, [config, isCurrent, clearTranscript]);

  const loadOlder = useCallback(async () => {
    if (!nextCursor || listBusy.current || olderBusy.current || resumeBusy.current || !scope.current.visible) return;
    clearTranscript();
    olderBusy.current = true;
    const request = ++epoch.current;
    setLoadingOlder(true);
    setError(null);
    try {
      const result = await fetchSessionsPage(config, nextCursor);
      if (!isCurrent(request)) return;
      if (result.next_cursor !== null && seenCursors.current.has(result.next_cursor)) {
        throw new ApiError('The hub returned a repeated session cursor. Try loading older sessions again.');
      }
      if (result.next_cursor !== null) seenCursors.current.add(result.next_cursor);
      setSessions((loaded) => {
        const ids = new Set(loaded.map((session) => session.id));
        return [...loaded, ...result.sessions.filter((session) => {
          if (ids.has(session.id)) return false;
          ids.add(session.id);
          return true;
        })];
      });
      setNextCursor(result.next_cursor);
    } catch (e) {
      if (isCurrent(request)) setError(e instanceof ApiError ? e.message : 'Failed to load older sessions');
    } finally {
      if (isCurrent(request)) {
        olderBusy.current = false;
        setLoadingOlder(false);
      }
    }
  }, [config, isCurrent, nextCursor, clearTranscript]);

  useEffect(() => {
    clearTranscript();
    clearMessageSearch();
    ++epoch.current;
    listBusy.current = false;
    olderBusy.current = false;
    resumeBusy.current = false;
    seenCursors.current.clear();
    setSessions([]);
    setBusyId(null);
    setQuery('');
    setMode(startInMessages ? 'messages' : 'sessions');
    setMessageQuery('');
    setAgentFilter(null);
    setDateFilter('All dates');
    setNextCursor(null);
    setRecentOnly(false);
    setLoading(false);
    setLoadingOlder(false);
    setError(null);
    if (visible) load();
    return () => { ++epoch.current; ++transcriptEpoch.current; ++messageEpoch.current; };
  }, [visible, load, connectionEpoch, recipient, startInMessages, clearTranscript, clearMessageSearch]);

  const normalizedQuery = query.trim().toLowerCase();
  const filtersActive = agentFilter !== null || dateFilter !== 'All dates';
  // Keep exact agent ids separate from the All/Unassigned choices, including reserved labels.
  const agents = [...new Set(sessions.map((session) => session.agent_id).filter(
    (agent): agent is string => typeof agent === 'string' && agent.length > 0,
  ))];
  if (agentFilter && !agents.includes(agentFilter)) agents.push(agentFilter);
  const now = Date.now();
  const visibleSessions = sessions.filter((session) => {
    if (agentFilter !== null && (agentFilter === ''
      ? !!session.agent_id : session.agent_id !== agentFilter)) return false;
    const started = startedAt(session.started_at);
    if (dateFilter === 'Unknown date' && Number.isFinite(started)) return false;
    if (dateFilter === 'Last 7 days' || dateFilter === 'Last 30 days') {
      const days = dateFilter === 'Last 7 days' ? 7 : 30;
      if (!Number.isFinite(started) || started > now || started < now - days * 86400000) return false;
    }
    return !normalizedQuery || [session.title, session.summary, session.id, session.agent_id, session.resume_id]
      .some((value) => typeof value === 'string' && value.toLowerCase().includes(normalizedQuery));
  });

  const resume = useCallback(
    async (id: string, verify?: () => Promise<boolean>, searchRequest?: number) => {
      if (resumeBusy.current || (listBusy.current && !verify) || !scope.current.visible
        || scope.current.config !== config || scope.current.connectionEpoch !== connectionEpoch) return;
      const blocked = resumeBlockReason?.();
      if (blocked) { if (verify) setMessageError(blocked); else setError(blocked); return; }
      clearTranscript();
      resumeBusy.current = true;
      listBusy.current = false;
      olderBusy.current = false;
      const request = ++epoch.current;
      setLoading(false);
      setLoadingOlder(false);
      setBusyId(id);
      setError(null);
      if (verify) setMessageBusy('continue');
      try {
        if (verify) {
          if (!await verify() || !isCurrent(request) || !messageCurrent(searchRequest!)) return;
          const afterReadBlock = resumeBlockReason?.();
          if (afterReadBlock) { setMessageError(afterReadBlock); return; }
        }
        const res = await resumeSession(config, id);
        if (!isCurrent(request) || (searchRequest !== undefined && !messageCurrent(searchRequest))) return;
        if (!res.ok || res.session !== id || !Array.isArray(res.turns)) {
          throw new ApiError('The hub did not resume the selected session');
        }
        onResumed(res.session || id, res.turns || []);
        close();
      } catch (e) {
        if (isCurrent(request)) {
          if (verify) setMessageError('Could not reopen this conversation. Try again.');
          else setError(e instanceof ApiError ? e.message : 'Failed to resume session');
        }
      } finally {
        if (isCurrent(request)) {
          resumeBusy.current = false;
          setBusyId(null);
          if (verify) setMessageBusy(null);
        }
      }
    },
    [config, connectionEpoch, onResumed, close, isCurrent, clearTranscript, messageCurrent, resumeBlockReason],
  );

  const switchMode = (next: 'sessions' | 'messages') => {
    if (next === mode) return;
    clearTranscript();
    clearMessageSearch();
    setMessageQuery('');
    setMode(next);
  };

  const changeMessageQuery = (value: string) => {
    clearMessageSearch();
    messageScope.current = { config, connectionEpoch };
    setMessageQuery(value);
  };

  const searchMessages = async () => {
    const submitted = messageQuery.trim();
    if (!submitted || messageBusyRef.current || resumeBusy.current || mode !== 'messages'
      || !scope.current.visible || scope.current.config !== config || scope.current.connectionEpoch !== connectionEpoch
      || messageScope.current.config !== config || messageScope.current.connectionEpoch !== connectionEpoch) return;
    const request = ++messageEpoch.current;
    messageScope.current = { config, connectionEpoch };
    messageBusyRef.current = true;
    setMessageBusy('search');
    setMessageResults(null);
    setReviewed(null);
    setMessageError(null);
    try {
      const result = await searchSessionMessages(config, submitted);
      if (messageCurrent(request)) setMessageResults({ ...result, request });
    } catch (e) {
      if (messageCurrent(request)) setMessageError(e instanceof ApiError ? e.message : 'Could not search saved messages. Try again.');
    } finally {
      if (messageCurrent(request)) { messageBusyRef.current = false; setMessageBusy(null); }
    }
  };

  const reviewMessage = async (hit: SessionMessageHit, resultRequest: number) => {
    if (messageBusyRef.current || resumeBusy.current || !messageCurrent(resultRequest)) return;
    const request = ++messageEpoch.current;
    messageBusyRef.current = true;
    setMessageBusy('review');
    setReviewed(null);
    setPassage('');
    setCloudAllowed(false);
    setMessageError(null);
    try {
      const transcript = await fetchSessionTranscript(config, hit.session_id, !!onUseSource);
      if (!messageCurrent(request)) return;
      const turn = verifiedSessionTurn(transcript, hit, !!onUseSource);
      if (!turn) { setMessageResults(null); setMessageError('This saved turn changed or cannot be verified. Search again.'); return; }
      setMessageResults(previous => previous ? { ...previous, request } : null);
      setReviewed({ hit, turn, request });
    } catch {
      if (messageCurrent(request)) setMessageError('Could not verify the saved turn. Search again.');
    } finally {
      if (messageCurrent(request)) { messageBusyRef.current = false; setMessageBusy(null); }
    }
  };

  const stageSource = async (review: NonNullable<typeof reviewed>) => {
    if (!onUseSource || !recipient || messageBusyRef.current || resumeBusy.current || !messageCurrent(review.request)) return;
    const blocked = sourceBlockReason?.();
    if (blocked) { setMessageError(blocked); return; }
    const reference = { session_id: review.hit.session_id, turn: review.hit.turn,
      revision: review.turn.reference_revision || '', excerpt: passage, allow_cloud: cloudAllowed };
    if (!validHistoryReference(reference) || !review.turn.content.includes(passage)) {
      setMessageError('Choose an exact passage from this message (up to 8,000 UTF-8 bytes).'); return;
    }
    const requiresConsent = historyRequiresCloudConsent(recipient);
    if (requiresConsent && !cloudAllowed) { setMessageError(`Allow this passage for ${recipient} before using it.`); return; }
    messageBusyRef.current = true;
    setMessageBusy('stage');
    setMessageError(null);
    try {
      const current = await fetchSessionTranscript(config, review.hit.session_id, true);
      if (!messageCurrent(review.request) || scope.current.recipient !== recipient) return;
      const turn = verifiedSessionTurn(current, review.hit, true);
      if (!turn || turn.reference_revision !== reference.revision || turn.content !== review.turn.content) {
        setReviewed(null); setMessageResults(null);
        setMessageError('This saved turn changed or cannot be verified. Search again.'); return;
      }
      const afterReadBlock = sourceBlockReason?.();
      if (afterReadBlock) { setMessageError(afterReadBlock); return; }
      if (!onUseSource({ reference: { ...reference, allow_cloud: requiresConsent && cloudAllowed }, role: turn.role })) {
        setMessageError('Could not stage this passage. Try again.'); return;
      }
      close();
    } catch {
      if (messageCurrent(review.request)) setMessageError('Could not verify the saved turn. Search again.');
    } finally {
      if (messageCurrent(review.request)) { messageBusyRef.current = false; setMessageBusy(null); }
    }
  };

  const continueMessage = (hit: SessionMessageHit, reviewedTurn: SessionTranscript['turns'][number], request: number) => {
    if (messageBusyRef.current || resumeBusy.current || !messageCurrent(request)) return;
    setMessageError(null);
    void resume(hit.session_id, async () => {
      try {
        const transcript = await fetchSessionTranscript(config, hit.session_id);
        if (!messageCurrent(request)) return false;
        const latestTurn = verifiedSessionTurn(transcript, hit);
        if (!latestTurn || latestTurn.content !== reviewedTurn.content) {
          setReviewed(null);
          setMessageResults(null);
          setMessageError('This saved turn changed or cannot be verified. Search again.');
          return false;
        }
        return true;
      } catch {
        if (messageCurrent(request)) setMessageError('Could not verify the saved turn. Search again.');
        return false;
      }
    }, request);
  };

  const previewTranscript = useCallback(async (id: string) => {
    if (resumeBusy.current || listBusy.current || !scope.current.visible
      || scope.current.config !== config || scope.current.connectionEpoch !== connectionEpoch) return;
    clearTranscript();
    const request = transcriptEpoch.current;
    transcriptScope.current = { config, connectionEpoch };
    setPreviewId(id);
    try {
      const document = await fetchSessionTranscript(config, id);
      if (!transcriptCurrent(request)) return;
      setPreview({ document: projectSessionTranscript(document, id), request });
    } catch {
      if (!transcriptCurrent(request)) return;
      clearTranscript();
      setTranscriptError('Could not load retained session transcript.');
    } finally {
      if (transcriptCurrent(request)) setPreviewId(null);
    }
  }, [config, connectionEpoch, clearTranscript, transcriptCurrent]);

  const exportTranscript = useCallback(async () => {
    if (!preview || saveBusy.current || !transcriptCurrent(preview.request)) return;
    saveBusy.current = true;
    setSaving(true);
    setTranscriptError(null);
    setSaveNote(null);
    try {
      const document = projectSessionTranscript(preview.document, preview.document.session_id);
      const dir = FileSystem.documentDirectory;
      if (!dir) {
        clearTranscript();
        setTranscriptError('This device exposes no writable app folder.');
        return;
      }
      const suffix = `${Date.now()}-${++fileSequence.current}-${Math.random().toString(36).slice(2, 10)}`;
      const filename = `session-${document.session_id}-transcript-${suffix}.json`;
      if (!transcriptCurrent(preview.request)) return;
      await FileSystem.writeAsStringAsync(`${dir}${filename}`, JSON.stringify(document));
      if (transcriptCurrent(preview.request)) setSaveNote(`Saved to app folder: ${filename}`);
    } catch {
      if (!transcriptCurrent(preview.request)) return;
      clearTranscript();
      setTranscriptError('Could not save transcript to the app folder.');
    } finally {
      if (transcriptCurrent(preview.request)) {
        saveBusy.current = false;
        setSaving(false);
      }
    }
  }, [preview, transcriptCurrent, clearTranscript]);

  const changeQuery = (value: string) => { clearTranscript(); setQuery(value); };
  const changeAgentFilter = (value: string | null) => { clearTranscript(); setAgentFilter(value); };
  const changeDateFilter = (value: string) => { clearTranscript(); setDateFilter(value); };
  const resetFilters = () => { clearTranscript(); setAgentFilter(null); setDateFilter('All dates'); };
  const currentPreview = preview && transcriptCurrent(preview.request) ? preview.document : null;
  const currentMessageResults = messageResults && messageCurrent(messageResults.request) ? messageResults : null;
  const currentReview = reviewed && messageCurrent(reviewed.request) ? reviewed : null;
  const messageTitle = (id: string) => sessions.find((session) => session.id === id)?.title?.trim() || 'Saved message';

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={close}>
      <Pressable style={styles.backdrop} onPress={close}>
        <Pressable style={styles.sheet} onPress={() => {}}>
          <View style={styles.header}>
            <Text style={styles.title}>History</Text>
            {mode === 'sessions' && <Pressable onPress={load} hitSlop={8} disabled={!!busyId}
              accessibilityRole="button" accessibilityLabel="Refresh recent sessions">
              <Text style={styles.refresh}>↻</Text>
            </Pressable>}
            <Pressable onPress={close} style={styles.historyClose} accessibilityRole="button" accessibilityLabel="Close history">
              <Text style={styles.clear}>Close</Text>
            </Pressable>
          </View>
          {!(mode === 'messages' && currentReview) && <View style={styles.modeRow} accessibilityLabel="History mode">
            <Pressable onPress={() => switchMode('sessions')} accessibilityRole="button"
              accessibilityLabel="Browse sessions" accessibilityState={{ selected: mode === 'sessions' }}
              style={[styles.filterChip, mode === 'sessions' && styles.selectedChip]}>
              <Text style={styles.clear}>Browse sessions</Text>
            </Pressable>
            <Pressable onPress={() => switchMode('messages')} accessibilityRole="button"
              accessibilityLabel="Search messages" accessibilityState={{ selected: mode === 'messages' }}
              style={[styles.filterChip, styles.messageMode, mode === 'messages' && styles.selectedChip]}>
              <Text style={styles.clear}>Search messages</Text>
            </Pressable>
          </View>}

          {mode === 'sessions' ? <>

          <TextInput
            value={query}
            onChangeText={changeQuery}
            placeholder="Search loaded recent sessions"
            placeholderTextColor={theme.textDim}
            accessibilityLabel="Search loaded recent sessions"
            maxLength={256}
            autoCapitalize="none"
            autoCorrect={false}
            style={styles.search}
          />
          <View style={styles.searchHelp}>
            <Text style={styles.helper}>Searches session details on all loaded pages, not message text.</Text>
            {query.length > 0 ? (
              <Pressable onPress={() => changeQuery('')} hitSlop={8} accessibilityRole="button"
                accessibilityLabel="Clear session search">
                <Text style={styles.clear}>Clear</Text>
              </Pressable>
            ) : null}
          </View>

          <Text style={styles.helper}>Agent and date filters apply to loaded pages only.</Text>
          <ScrollView horizontal style={styles.filterScroll}>
            <Pressable onPress={() => changeAgentFilter(null)} accessibilityRole="button"
              accessibilityLabel="All agents" accessibilityState={{ selected: agentFilter === null }}
              style={[styles.filterChip, agentFilter === null && styles.selectedChip]}>
              <Text style={styles.clear}>All agents</Text>
            </Pressable>
            {agents.map((agent) => <Pressable key={agent} onPress={() => changeAgentFilter(agent)}
              accessibilityRole="button" accessibilityLabel={`Filter agent: ${agent}`}
              accessibilityState={{ selected: agentFilter === agent }}
              style={[styles.filterChip, agentFilter === agent && styles.selectedChip]}>
              <Text style={styles.clear}>Agent: {agent}</Text>
            </Pressable>)}
            <Pressable onPress={() => changeAgentFilter('')} accessibilityRole="button"
              accessibilityLabel="Unassigned" accessibilityState={{ selected: agentFilter === '' }}
              style={[styles.filterChip, agentFilter === '' && styles.selectedChip]}>
              <Text style={styles.clear}>Unassigned</Text>
            </Pressable>
          </ScrollView>
          <View style={styles.filterRow}>
            {['All dates', 'Last 7 days', 'Last 30 days', 'Unknown date'].map((date) => (
              <Pressable key={date} onPress={() => changeDateFilter(date)} accessibilityRole="button"
                accessibilityLabel={date} accessibilityState={{ selected: dateFilter === date }}
                style={[styles.filterChip, dateFilter === date && styles.selectedChip]}>
                <Text style={styles.clear}>{date}</Text>
              </Pressable>
            ))}
            <Pressable onPress={resetFilters} accessibilityRole="button" accessibilityLabel="Reset session filters">
              <Text style={styles.clear}>Reset filters</Text>
            </Pressable>
          </View>

          {loading && <ActivityIndicator color={theme.accent} style={styles.spinner} />}
          {recentOnly && <Text style={styles.recentOnly}>Recent sessions only. Older history is unavailable on this connection.</Text>}
          {error && <Text style={styles.error}>{error}</Text>}

          <FlatList
            data={visibleSessions}
            keyExtractor={(s) => s.id}
            style={styles.list}
            renderItem={({ item, index }) => (
              <View>
              {index === 0 || dateGroup(item.started_at) !== dateGroup(visibleSessions[index - 1].started_at) ? (
                <Text style={styles.dateGroup} accessibilityRole="header"
                  accessibilityLabel={`Session date group: ${dateGroup(item.started_at)}`}>{dateGroup(item.started_at)}</Text>
              ) : null}
              // H440: one row per conversation; a resume opens the newest member of its lineage.
              <View style={styles.option}>
                <Pressable style={styles.resumeOption} onPress={() => resume(resumeTarget(item))}
                  disabled={!!busyId || loading} accessibilityRole="button"
                  accessibilityLabel={`Resume session ${item.id}`}>
                <View style={styles.optInfo}>
                  <Text style={styles.optTitle} numberOfLines={1}>
                    {item.title?.trim() || item.summary?.trim() || item.id}
                  </Text>
                  <Text style={styles.optMeta} numberOfLines={1}>
                    {[
                      item.agent_id,
                      item.turn_count != null ? `${item.turn_count} turns` : null,
                      item.continuations ? `+${item.continuations} other in this conversation` : null,
                      formatDate(item.started_at),
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </Text>
                </View>
                {busyId === resumeTarget(item) && <ActivityIndicator color={theme.accent} size="small" />}
                </Pressable>
                <Pressable onPress={() => previewTranscript(item.id)} disabled={!!busyId || loading}
                  accessibilityRole="button" accessibilityLabel={`Preview transcript for ${item.id}`}>
                  <Text style={styles.clear}>Preview transcript</Text>
                </Pressable>
              </View>
              </View>
            )}
            ListEmptyComponent={
              !loading && !error ? <Text style={styles.empty}>
                {filtersActive ? 'No loaded sessions match these filters' : sessions.length > 0 && normalizedQuery
                  ? 'No recent sessions match this search' : 'No saved sessions'}
              </Text> : undefined
            }
          />
          {previewId && (
            <View style={styles.header}>
              <ActivityIndicator color={theme.accent} accessibilityLabel="Loading transcript preview" />
              <Pressable onPress={clearTranscript} accessibilityRole="button" accessibilityLabel="Close transcript preview">
                <Text style={styles.clear}>Close preview</Text>
              </Pressable>
            </View>
          )}
          {transcriptError && <Text style={styles.error}>{transcriptError}</Text>}
          {currentPreview && (
            <View style={styles.preview}>
              <View style={styles.header}>
                <Text style={styles.title}>Retained transcript</Text>
                <Pressable onPress={clearTranscript} accessibilityRole="button" accessibilityLabel="Close transcript preview">
                  <Text style={styles.clear}>Close</Text>
                </Pressable>
              </View>
              <Text style={styles.helper}>Retained current history only · automatically redacted. Full archive, compacted history, and training data are excluded.</Text>
              <ScrollView style={styles.transcriptScroll} nestedScrollEnabled>
                {currentPreview.turns.length === 0 ? <Text style={styles.optMeta}>No retained turns.</Text>
                  : currentPreview.turns.map((turn, index) => (
                    <View key={index} style={styles.transcriptTurn}>
                      <Text style={styles.optMeta}>{turn.role} · {turn.timestamp}{turn.agent_id ? ` · ${turn.agent_id}` : ''}</Text>
                      <Text selectable style={styles.transcriptText}>{turn.content}</Text>
                    </View>
                  ))}
              </ScrollView>
              <Pressable onPress={exportTranscript} disabled={saving} accessibilityRole="button"
                accessibilityLabel="Export transcript JSON">
                <Text style={styles.clear}>{saving ? 'Saving…' : 'Export transcript JSON'}</Text>
              </Pressable>
            </View>
          )}
          {saveNote && <Text style={styles.helper}>{saveNote}</Text>}
          {nextCursor !== null && (
            <Pressable onPress={loadOlder} disabled={loadingOlder || loading || !!busyId}
              accessibilityRole="button" accessibilityLabel="Load older sessions" style={styles.loadOlder}>
              <Text style={styles.clear}>{loadingOlder ? 'Loading older…' : 'Load older'}</Text>
            </Pressable>
          )}
          </> : <>
            {!currentReview && <>
            <Text style={styles.helper}>Searches saved message text. Review a result to see its current redacted source.</Text>
            <TextInput value={messageScope.current.config === config && messageScope.current.connectionEpoch === connectionEpoch ? messageQuery : ''} onChangeText={changeMessageQuery}
              onSubmitEditing={searchMessages} returnKeyType="search"
              placeholder="Search saved message text" placeholderTextColor={theme.textDim}
              accessibilityLabel="Search saved message text" maxLength={256}
              autoCapitalize="none" autoCorrect={false} style={styles.search} />
            <Pressable onPress={searchMessages} disabled={!messageQuery.trim() || !!messageBusy || !!busyId
              || messageScope.current.config !== config || messageScope.current.connectionEpoch !== connectionEpoch}
              style={styles.messageAction} accessibilityRole="button" accessibilityLabel="Submit message search">
              <Text style={styles.clear}>{messageBusy === 'search' ? 'Searching…' : 'Search messages'}</Text>
            </Pressable>
            </>}
            {messageError && <Text style={styles.error} accessibilityRole="alert">{messageError}</Text>}
            {messageBusy === 'review' && <Text style={styles.helper}>Opening saved turn…</Text>}
            {messageBusy === 'continue' && <Text style={styles.helper}>Reopening conversation…</Text>}
            <ScrollView style={styles.messageScroll} nestedScrollEnabled accessibilityLabel="Message search results">
              {currentReview ? <View accessibilityLabel="Verified saved turn">
                <Pressable onPress={() => { setReviewed(null); setPassage(''); setCloudAllowed(false); }} disabled={!!messageBusy || !!busyId}
                  style={styles.messageAction} accessibilityRole="button" accessibilityLabel="Back to message results">
                  <Text style={styles.clear}>Back to results</Text>
                </Pressable>
                <Text style={styles.title}>{messageTitle(currentReview.hit.session_id)}</Text>
                <Text selectable style={styles.provenance}>Session {currentReview.hit.session_id}</Text>
                <Text style={styles.optMeta}>Message {currentReview.hit.turn + 1} · {currentReview.turn.role} · {currentReview.turn.agent_id || 'Unassigned'} · {formatDate(currentReview.turn.timestamp) || 'Unknown time'}</Text>
                {passage !== currentReview.turn.content &&
                  <Text selectable style={styles.messageContent}>{currentReview.turn.content}</Text>}
                {onUseSource && recipient && !currentReview.turn.reference_revision &&
                  <Text style={styles.optMeta}>Source staging is unavailable because this message has no verified reference. You can still review or continue.</Text>}
                {onUseSource && recipient && currentReview.turn.reference_revision && <>
                  <Text style={styles.optMeta}>Use a passage from this saved message in your next message to {recipient}. This only stages the source.</Text>
                  <Pressable onPress={() => {
                    const whole = { session_id: currentReview.hit.session_id, turn: currentReview.hit.turn,
                      revision: currentReview.turn.reference_revision!, excerpt: currentReview.turn.content, allow_cloud: false };
                    if (!validHistoryReference(whole)) {
                      setMessageError('Whole message exceeds 8,000 UTF-8 bytes. Choose an exact passage.'); return;
                    }
                    setPassage(currentReview.turn.content); setMessageError(null);
                  }}
                    disabled={!!messageBusy} style={styles.messageAction} accessibilityRole="button" accessibilityLabel="Use entire message">
                    <Text style={styles.clear}>Use entire message</Text>
                  </Pressable>
                  <TextInput value={passage} editable={!messageBusy} onChangeText={(value) => { setPassage(value); setMessageError(null); }}
                    multiline maxLength={8000} style={styles.passageInput} placeholder="Type or paste an exact passage"
                    placeholderTextColor={theme.textDim} accessibilityLabel="Exact passage" />
                  {historyRequiresCloudConsent(recipient) &&
                    <Pressable onPress={() => setCloudAllowed(value => !value)} disabled={!!messageBusy} style={styles.messageAction}
                      accessibilityRole="checkbox" accessibilityState={{ checked: cloudAllowed }} aria-checked={cloudAllowed}
                      accessibilityLabel={`Allow this passage for ${recipient}`}>
                      <Text style={styles.clear}>{cloudAllowed ? '☑' : '☐'} Allow this passage for {recipient}</Text>
                    </Pressable>}
                  <Pressable onPress={() => { void stageSource(currentReview); }} disabled={!!messageBusy || !!busyId}
                    style={styles.messageContinue} accessibilityRole="button" accessibilityLabel="Use passage in next message">
                    <Text style={styles.continueText}>{messageBusy === 'stage' ? 'Verifying passage…' : 'Use passage in next message'}</Text>
                  </Pressable>
                </>}
                {hasDraft && <Text style={styles.optMeta}>Your typed message will stay in the composer.</Text>}
                <Pressable onPress={() => continueMessage(currentReview.hit, currentReview.turn, currentReview.request)}
                  disabled={!!messageBusy || !!busyId} style={styles.messageContinue} accessibilityRole="button"
                  accessibilityLabel={`Continue session ${currentReview.hit.session_id}`}>
                  <Text style={styles.continueText}>Continue this conversation</Text>
                </Pressable>
              </View> : <>
              {currentMessageResults?.truncated && <Text style={styles.helper}>Results are limited; this is not a complete archive search.</Text>}
              {currentMessageResults?.stopped_by && <Text style={styles.helper}>Search stopped: {currentMessageResults.stopped_by}</Text>}
              {currentMessageResults?.hits.length === 0 && <Text style={styles.empty}>No saved messages match.</Text>}
              {currentMessageResults?.hits.map((hit) => <View key={`${hit.session_id}:${hit.turn}`} style={styles.messageHit}>
                <Text style={styles.optTitle}>{messageTitle(hit.session_id)}</Text>
                <Text style={styles.optMeta}>Message {hit.turn + 1} · {hit.role} · {hit.agent_id || 'Unassigned'} · {formatDate(hit.timestamp || undefined) || 'Unknown time'}</Text>
                <Text selectable style={styles.provenance}>Session {hit.session_id}</Text>
                <Text style={styles.transcriptText}>{hit.snippet}</Text>
                <Pressable onPress={() => reviewMessage(hit, currentMessageResults.request)}
                  disabled={!!messageBusy || !!busyId} style={styles.messageAction} accessibilityRole="button"
                  accessibilityLabel={`Review saved turn ${hit.turn + 1} in session ${hit.session_id}`}>
                  <Text style={styles.clear}>Review source</Text>
                </Pressable>
              </View>)}
              </>}
            </ScrollView>
          </>}
        </Pressable>
      </Pressable>
    </Modal>
  );
}

/** Date.parse normalizes impossible calendar dates, so validate ISO components first. */
function startedAt(value?: string): number {
  if (typeof value !== 'string') return NaN;
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(?:Z|[+-](\d{2}):(\d{2}))?)?$/.exec(value);
  if (!match) return NaN;
  const [, year, month, day, hour, minute, second, offsetHour, offsetMinute] = match;
  const y = Number(year), m = Number(month), d = Number(day);
  const days = [31, y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (m < 1 || m > 12 || d < 1 || d > days[m - 1]
    || Number(hour || 0) > 23 || Number(minute || 0) > 59 || Number(second || 0) > 59
    || Number(offsetHour || 0) > 23 || Number(offsetMinute || 0) > 59) return NaN;
  return Date.parse(value);
}

function dateGroup(iso?: string): string {
  const timestamp = startedAt(iso);
  return Number.isFinite(timestamp)
    ? new Date(timestamp).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' }) : 'Unknown date';
}

function formatDate(iso?: string): string | null {
  const timestamp = startedAt(iso);
  return Number.isFinite(timestamp) ? new Date(timestamp).toLocaleString() : null;
}

const makeStyles = (theme: Theme) => StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: '#000a', justifyContent: 'center', padding: 24 },
  sheet: {
    backgroundColor: theme.surfaceAlt,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: theme.border,
    padding: 16,
    maxHeight: '80%',
  },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  title: { color: theme.text, fontSize: 16, fontWeight: '700' },
  refresh: { color: theme.accent, fontSize: 20 },
  search: { color: theme.text, backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1,
    borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, fontSize: 14 },
  searchHelp: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: 30 },
  helper: { color: theme.textDim, fontSize: 11, flex: 1, paddingRight: 8 },
  filterScroll: { flexGrow: 0, flexShrink: 0, marginTop: 8 },
  filterRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', marginTop: 4 },
  modeRow: { flexDirection: 'row', marginBottom: 8 },
  messageMode: { minHeight: 44, justifyContent: 'center' },
  historyClose: { minHeight: 44, minWidth: 64, alignItems: 'center', justifyContent: 'center' },
  filterChip: { paddingHorizontal: 8, marginRight: 6, marginBottom: 4, borderRadius: 8, borderWidth: 1, borderColor: theme.border },
  selectedChip: { borderColor: theme.accent, backgroundColor: theme.surface },
  dateGroup: { color: theme.textDim, fontSize: 12, fontWeight: '600', marginTop: 12 },
  recentOnly: { color: theme.textDim, fontSize: 12, paddingVertical: 8 },
  clear: { color: theme.accent, fontSize: 12, fontWeight: '600', paddingVertical: 6 },
  spinner: { marginVertical: 16 },
  error: { color: theme.danger, fontSize: 13, marginVertical: 8 },
  list: { flexGrow: 0, flexShrink: 1 },
  messageScroll: { flexShrink: 1, minHeight: 0, maxHeight: 360, marginTop: 8 },
  messageHit: { paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: theme.border },
  messageAction: { minHeight: 44, justifyContent: 'center', alignItems: 'center', paddingHorizontal: 12,
    borderWidth: 1, borderColor: theme.border, borderRadius: 8, marginTop: 8 },
  messageContinue: { minHeight: 44, justifyContent: 'center', alignItems: 'center', paddingHorizontal: 12,
    backgroundColor: theme.accentDim, borderWidth: 1, borderColor: theme.accent, borderRadius: 8, marginTop: 12 },
  continueText: { color: theme.text, fontSize: 14, fontWeight: '700' },
  provenance: { color: theme.textDim, fontSize: 11, marginTop: 2 },
  messageContent: { color: theme.text, fontSize: 14, lineHeight: 20, marginVertical: 12 },
  passageInput: { color: theme.text, borderWidth: 1, borderColor: theme.border, borderRadius: 8,
    minHeight: 88, maxHeight: 160, padding: 12, marginTop: 8, textAlignVertical: 'top' },
  loadOlder: { alignItems: 'center', paddingVertical: 8 },
  option: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
  },
  resumeOption: { flex: 1, flexDirection: 'row', alignItems: 'center' },
  preview: { borderWidth: 1, borderColor: theme.border, borderRadius: 8, padding: 10, marginTop: 8, flexShrink: 1 },
  transcriptScroll: { maxHeight: 220, flexShrink: 1, marginVertical: 8 },
  transcriptTurn: { paddingVertical: 8 },
  transcriptText: { color: theme.text, fontSize: 13 },
  optInfo: { flex: 1, paddingRight: 10 },
  optTitle: { color: theme.text, fontSize: 15, fontWeight: '600' },
  optMeta: { color: theme.textDim, fontSize: 12, marginTop: 2 },
  empty: { color: theme.textDim, fontSize: 14, textAlign: 'center', paddingVertical: 24 },
});
