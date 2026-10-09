import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, Image, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import { Text, TextInput } from './ThemedText';
import { listActiveImages, prepareSelectedImages, sendSelectedImages, SelectedImageError,
  type ActiveImage, type ImageCandidate, type SelectedReview } from '../api/selectedImages';
import type { Conversation } from '../chat/conversation';
import { MAX_NEW_BYTES, MAX_NEW_IMAGES, snapshotImage, type SelectedSnapshot } from '../images/snapshot';
import { acknowledgeSelectedOutcome, clearSelectedOutcome, markSelectedOutcomeUnknown,
  selectedOutcomeUnknown } from '../storage/selectedOutcome';
import type { ServerConfig } from '../storage/settings';
import { useThemeStyles, type Theme } from '../theme';

type Review = { proof: SelectedReview; candidate: ImageCandidate; images: SelectedSnapshot[];
  revision: number; generation: number; count: number };
type Turn = NonNullable<ReturnType<Conversation['beginSelectedImage']>>;
type Props = { config: ServerConfig; scope: string; connectionEpoch: number; sessionId: string | null;
  agent: string; chat: Conversation; sending: boolean; onClose: () => void; onInspectHistory: () => void };
const limited = <T,>(operation: Promise<T>, ms: number): Promise<T> => new Promise((resolve, reject) => {
  const timer = setTimeout(() => reject(new Error('Selected image operation timed out')), ms);
  operation.then(value => { clearTimeout(timer); resolve(value); }, error => { clearTimeout(timer); reject(error); });
});
function waitForActive(signal: AbortSignal): Promise<void> {
  if (AppState.currentState === 'active') return Promise.resolve();
  return new Promise((resolve, reject) => {
    let done = false;
    const finish = (error?: Error) => {
      if (done) return;
      done = true; sub.remove(); clearTimeout(timer); signal.removeEventListener('abort', abort);
      if (error) reject(error); else resolve();
    };
    const sub = AppState.addEventListener('change', state => { if (state === 'active') finish(); });
    const timer = setTimeout(() => finish(new Error('Return to app to finish image selection')), 15000);
    const abort = () => finish(new Error('Image selection cancelled'));
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) abort();
  });
}

/** Owner-only, explicit review/send surface. Exported picker data stays only in mounted memory. */
export function SelectedImages({ config, scope, connectionEpoch, sessionId, agent, chat, sending,
  onClose, onInspectHistory }: Props) {
  const { styles } = useThemeStyles(makeStyles);
  const [prompt, setPrompt] = useState('');
  const [images, setImages] = useState<SelectedSnapshot[]>([]);
  const [activeImages, setActiveImages] = useState<ActiveImage[]>([]);
  const [activeStatus, setActiveStatus] = useState<'loading' | 'available' | 'error'>('loading');
  const [handles, setHandles] = useState<string[]>([]);
  const [review, setReview] = useState<Review | null>(null);
  const [busy, setBusy] = useState<'picker' | 'list' | 'prepare' | 'send' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [unknown, setUnknown] = useState<'loading' | 'clear' | 'submitting' | 'unknown' | 'error'>('loading');
  const [historyOpened, setHistoryOpened] = useState(false);
  const active = useRef(false);
  const generation = useRef(0);
  const listGeneration = useRef(0);
  const abort = useRef<AbortController | null>(null);
  const listAbort = useRef<AbortController | null>(null);
  const pickerOpen = useRef(false);
  const pickerWait = useRef<AbortController | null>(null);
  const turn = useRef<Turn | null>(null);

  const revoke = useCallback((clearImages: boolean) => {
    ++generation.current;
    abort.current?.abort(); abort.current = null;
    turn.current?.cancel(); turn.current = null;
    setReview(null); setBusy(null);
    if (clearImages) { setImages([]); setHandles([]); setActiveImages([]); setActiveStatus('error');
      setUnknown(previous => previous === 'submitting' ? 'unknown' : previous); }
  }, []);
  const changed = useCallback(() => { revoke(false); setError(null); }, [revoke]);
  const current = (stamp: number) => active.current && generation.current === stamp
    && AppState.currentState === 'active';

  useEffect(() => {
    active.current = true;
    const subscription = AppState.addEventListener('change', state => {
      if (state !== 'active' && !pickerOpen.current) {
        revoke(true);
        listAbort.current?.abort();
        setError('Image selection cleared when the app left the foreground. Review again.');
      }
    });
    return () => {
      active.current = false;
      ++generation.current; ++listGeneration.current;
      abort.current?.abort(); listAbort.current?.abort(); pickerWait.current?.abort();
      turn.current?.cancel();
      subscription.remove();
    };
  }, [revoke]);

  useEffect(() => {
    let live = true;
    if (!sessionId) { setUnknown('clear'); return () => { live = false; }; }
    setUnknown('loading');
    void selectedOutcomeUnknown(scope, sessionId, agent).then(value => {
      if (live) setUnknown(value ? 'unknown' : 'clear');
    }).catch(() => { if (live) setUnknown('error'); });
    return () => { live = false; };
  }, [scope, connectionEpoch, sessionId, agent]);

  const refreshActive = useCallback(async () => {
    if (!sessionId || sending || busy === 'send') return;
    listAbort.current?.abort();
    const request = ++listGeneration.current;
    const controller = new AbortController(); listAbort.current = controller;
    setBusy('list'); setActiveStatus('loading'); setError(null);
    try {
      const rows = await listActiveImages(config, sessionId, agent, controller.signal);
      if (active.current && listGeneration.current === request && AppState.currentState === 'active') {
        setActiveImages(rows); setActiveStatus('available'); setHandles([]); setReview(null); ++generation.current;
      }
    } catch {
      if (active.current && listGeneration.current === request) {
        setActiveImages([]); setActiveStatus('error'); setHandles([]); setReview(null);
        setError('Active image history is unavailable. Check owner access or session.');
      }
    } finally {
      if (active.current && listGeneration.current === request) setBusy(null);
    }
  }, [config, sessionId, agent, sending, busy]);
  // Recheck the process-local handles on opening; a manual Refresh remains available.
  useEffect(() => { void refreshActive(); return () => { ++listGeneration.current; listAbort.current?.abort(); }; },
    // This component is keyed by scope/epoch/session/agent; avoid restarting a list on every busy render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [scope, connectionEpoch, sessionId, agent]);

  const pick = useCallback(async () => {
    if (!sessionId || !chat.state.ready || sending || busy || unknown !== 'clear'
      || images.length >= MAX_NEW_IMAGES || AppState.currentState !== 'active' || pickerOpen.current) return;
    changed();
    const stamp = generation.current;
    const revision = chat.revision;
    pickerOpen.current = true;
    const wait = new AbortController(); pickerWait.current = wait;
    setBusy('picker');
    try {
      const result = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'],
        allowsEditing: false, allowsMultipleSelection: false, base64: true, exif: false });
      if (!active.current || generation.current !== stamp || chat.revision !== revision) return;
      if (result.canceled) return;
      await waitForActive(wait.signal);
      if (!current(stamp) || chat.revision !== revision || !Array.isArray(result.assets)
        || result.assets.length !== 1) throw new Error('Selected image is unsupported');
      pickerOpen.current = false;
      const image = await snapshotImage(result.assets[0]);
      if (!current(stamp) || chat.revision !== revision) return;
      const bytes = images.reduce((sum, row) => sum + row.byteCount, image.byteCount);
      if (bytes > MAX_NEW_BYTES) throw new Error('Selected images exceed the mobile size limit');
      setImages([...images, image]);
    } catch {
      if (active.current && generation.current === stamp) setError('Image selection failed or exceeded the mobile limits.');
    } finally {
      pickerOpen.current = false; pickerWait.current = null;
      if (active.current && generation.current === stamp) setBusy(null);
    }
  }, [sessionId, chat, sending, busy, unknown, images, changed]);

  const selectedCount = handles.reduce((count, id) => count + (activeImages.find(row => row.handle === id)?.count ?? 0), 0);
  const prepare = useCallback(async () => {
    if (!sessionId || !chat.state.ready || sending || busy || unknown !== 'clear'
      || !prompt.trim() || prompt.length > 4000 || images.length + selectedCount < 1
      || images.length + selectedCount > 8 || AppState.currentState !== 'active') return;
    changed();
    const stamp = generation.current;
    const revision = chat.revision;
    const selectedImages = [...images];
    const candidate: ImageCandidate = { prompt, agent, sessionId,
      imageDigests: selectedImages.map(image => image.digest), activeImageHandles: [...handles] };
    const controller = new AbortController(); abort.current = controller;
    setBusy('prepare');
    try {
      const proof = await prepareSelectedImages(config, candidate, controller.signal);
      if (!current(stamp) || chat.revision !== revision) return;
      if (proof.activeImageCount !== selectedCount || proof.activeImageCount + selectedImages.length > 8)
        throw new Error('Active image history changed');
      setReview({ proof, candidate, images: selectedImages, revision, generation: stamp,
        count: selectedImages.length + selectedCount });
    } catch {
      if (current(stamp)) setError('Selected Ollama review is unavailable. Refresh the selection and try again.');
    } finally {
      if (current(stamp)) setBusy(null);
    }
  }, [sessionId, chat, sending, busy, unknown, prompt, images, selectedCount, agent, handles, config, changed]);

  useEffect(() => {
    if (!review) return;
    const timer = setTimeout(() => setReview(old => old === review ? null : old), 55000);
    return () => clearTimeout(timer);
  }, [review]);

  const submit = useCallback(async () => {
    if (!review || !sessionId || sending || busy || unknown !== 'clear'
      || review.generation !== generation.current || review.revision !== chat.revision
      || review.candidate.sessionId !== sessionId || AppState.currentState !== 'active') return;
    const pending = chat.beginSelectedImage(sessionId, review.revision);
    if (!pending) return;
    turn.current = pending;
    const stamp = generation.current;
    setBusy('send'); setError(null);
    let attempt: string | null = null;
    let dispatched = false;
    try {
      attempt = await limited(markSelectedOutcomeUnknown(scope, sessionId, agent), 3000);
      if (!pending.current() || !current(stamp)) {
        await limited(clearSelectedOutcome(scope, sessionId, agent, attempt), 3000);
        return;
      }
      setUnknown('submitting');
      dispatched = true;
      const result = await sendSelectedImages(config, { ...review.candidate,
        images: review.images.map(image => image.dataUri), reviewToken: review.proof.reviewToken,
        expectedDestination: review.proof.destination, expectedModel: review.proof.model }, pending.signal);
      if (!pending.current() || !current(stamp) || result.model !== review.proof.model) return;
      if (!pending.commit(review.candidate.prompt, agent, review.count, result.model, result.response)) return;
      await limited(clearSelectedOutcome(scope, sessionId, agent, attempt), 3000);
      if (current(stamp)) { setUnknown('clear'); setReview(null); setImages([]); setHandles([]); setPrompt(''); }
    } catch (cause) {
      if (!active.current || generation.current !== stamp) return;
      if (attempt && dispatched && cause instanceof SelectedImageError && cause.definite && pending.current()) {
        try {
          await limited(clearSelectedOutcome(scope, sessionId, agent, attempt), 3000);
          setUnknown('clear'); setReview(null);
          setError('The Hub refused this review before committing. Review the selection again.');
        } catch { setUnknown('unknown'); setError('Outcome unknown. Inspect History before another attempt.'); }
      } else if (attempt) {
        setUnknown('unknown'); setError('Outcome unknown. Inspect History before another attempt.');
      } else {
        setError('Could not safely record this submission. No image request was sent.');
      }
    } finally {
      pending.release();
      if (turn.current === pending) turn.current = null;
      if (active.current && generation.current === stamp) setBusy(null);
    }
  }, [review, sessionId, sending, busy, unknown, chat, scope, agent, config]);

  const acknowledge = useCallback(async () => {
    if (!sessionId || !historyOpened || unknown !== 'unknown') return;
    setBusy('prepare');
    try { await limited(acknowledgeSelectedOutcome(scope, sessionId, agent), 3000);
      if (active.current) { setUnknown('clear'); setHistoryOpened(false); setError(null); changed(); }
    } catch { if (active.current) setError('Could not clear the safety marker. Try again later.'); }
    finally { if (active.current) setBusy(null); }
  }, [sessionId, historyOpened, unknown, scope, agent, changed]);

  const usableReview = review && review.revision === chat.revision && review.generation === generation.current;
  const canReview = !!sessionId && chat.state.ready && !sending && !busy && unknown === 'clear'
    && !!prompt.trim() && prompt.length <= 4000 && images.length + selectedCount >= 1
    && images.length + selectedCount <= 8;
  return <View style={styles.panel}>
    <View style={styles.row}><Text style={styles.title}>Selected images · local Ollama</Text>
      <Pressable accessibilityLabel="Close selected images" onPress={onClose}><Text style={styles.action}>Close</Text></Pressable></View>
    {!sessionId ? <View><Text style={styles.note}>A concrete conversation is required before selecting images.</Text>
      <Pressable disabled={sending || !chat.state.ready} onPress={() => chat.send('/new', agent)}
        accessibilityLabel="Start image conversation"><Text style={styles.action}>Start image conversation</Text></Pressable></View> : null}
    {sessionId ? <ScrollView style={styles.content} keyboardShouldPersistTaps="handled">
      {unknown === 'loading' ? <Text style={styles.note}>Checking prior submission state…</Text> : null}
      {unknown === 'error' ? <Text style={styles.warning}>Submission safety state unavailable. Sending is paused.</Text> : null}
      {unknown === 'submitting' ? <Text style={styles.note}>Sending reviewed images. Keep this conversation open.</Text> : null}
      {unknown === 'unknown' ? <View><Text style={styles.warning}>Outcome unknown. Inspect History before trying again; do not resend automatically.</Text>
        <Pressable onPress={() => { setHistoryOpened(true); onInspectHistory(); }} accessibilityLabel="Inspect image conversation History"><Text style={styles.action}>Inspect History</Text></Pressable>
        {historyOpened ? <Pressable onPress={() => { void acknowledge(); }} accessibilityLabel="Acknowledge possible duplicate and allow another review">
          <Text style={styles.action}>I checked History and accept the possible duplicate</Text></Pressable> : null}</View> : null}
      <Text style={styles.note}>Current session {sessionId}. Images go only to the selected Ollama on the Hub host.</Text>
      <TextInput style={styles.input} value={prompt} multiline placeholder="Ask about these images" onChangeText={value => { changed(); setPrompt(value); }}
        editable={!sending && !busy} accessibilityLabel="Image question" />
      <View style={styles.row}><Pressable onPress={() => { void pick(); }} disabled={!!busy || sending || unknown !== 'clear' || images.length >= MAX_NEW_IMAGES}
        accessibilityLabel="Add selected image"><Text style={styles.action}>Add image ({images.length}/{MAX_NEW_IMAGES})</Text></Pressable>
        <Pressable onPress={() => { void refreshActive(); }} disabled={!!busy || sending} accessibilityLabel="Refresh active images"><Text style={styles.action}>Refresh active</Text></Pressable></View>
      {images.map((image, index) => <View key={`${image.digest}-${index}`} style={styles.row}>
        <Image source={{ uri: image.dataUri }} style={styles.preview} accessibilityLabel={`Selected image ${index + 1}`} />
        <Text style={styles.note}>{image.mime} · {Math.ceil(image.byteCount / 1024)} KiB</Text>
        <Pressable disabled={!!busy || sending} onPress={() => { changed(); setImages(rows => rows.filter((_, i) => i !== index)); }}
          accessibilityLabel={`Remove selected image ${index + 1}`}><Text style={styles.action}>Remove</Text></Pressable></View>)}
      <Text style={styles.label}>Active images in this session (process-local; no preview)</Text>
      {activeStatus === 'loading' ? <Text style={styles.note}>Checking active image history…</Text> : null}
      {activeStatus === 'error' ? <Text style={styles.warning}>Active image history unavailable; its state is unknown.</Text> : null}
      {activeStatus === 'available' && activeImages.length === 0 ? <Text style={styles.note}>No active image handles available.</Text> : null}
      {activeImages.map(row => <Pressable key={row.handle} disabled={!!busy || sending} onPress={() => {
        changed(); setHandles(old => old.includes(row.handle) ? old.filter(id => id !== row.handle) : [...old, row.handle]);
      }} accessibilityLabel={`${handles.includes(row.handle) ? 'Deselect' : 'Select'} prior image: ${row.question}`}>
        <Text style={styles.action}>{handles.includes(row.handle) ? '☑' : '□'} {row.question || 'Earlier image turn'} · {row.count} image(s)</Text>
      </Pressable>)}
      <Text style={styles.note}>Selected: {images.length + selectedCount}/8 images. Review is required before every send.</Text>
      {error ? <Text style={styles.warning}>{error}</Text> : null}
      <Pressable onPress={() => { void prepare(); }} disabled={!canReview} accessibilityLabel="Review selected Ollama destination">
        <Text style={styles.action}>Review selection</Text></Pressable>
      {usableReview ? <View style={styles.review}><Text style={styles.label}>Review exact selection</Text>
        <Text style={styles.note}>Model: {review.proof.model}</Text><Text style={styles.note}>Destination: {review.proof.destination}</Text>
        <Text style={styles.note}>Local to Hub host · reachability not probed · {review.count} image(s)</Text>
        <Text style={styles.note}>Question: {review.candidate.prompt}</Text>
        <Pressable disabled={!!busy || sending || unknown !== 'clear'} onPress={() => { void submit(); }} accessibilityLabel="Submit reviewed selected images">
          <Text style={styles.action}>Submit reviewed images</Text></Pressable></View> : null}
    </ScrollView> : null}
  </View>;
}

const makeStyles = (theme: Theme) => StyleSheet.create({
  panel: { maxHeight: 440, backgroundColor: theme.surface, borderTopColor: theme.border, borderTopWidth: 1, padding: 12 },
  content: { maxHeight: 390 }, row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginVertical: 5 },
  title: { color: theme.text, fontWeight: '700', fontSize: 16 }, label: { color: theme.text, fontWeight: '600', marginTop: 8 },
  note: { color: theme.textDim, fontSize: 12, flexShrink: 1 }, warning: { color: theme.danger, fontSize: 13, marginVertical: 5 },
  action: { color: theme.accent, fontWeight: '600', paddingVertical: 8 },
  input: { color: theme.text, minHeight: 56, maxHeight: 100, borderWidth: 1, borderColor: theme.border, borderRadius: 8, padding: 8 },
  preview: { width: 48, height: 48, borderRadius: 4 },
  review: { borderWidth: 1, borderColor: theme.accentDim, borderRadius: 8, padding: 10, marginTop: 8 },
});
