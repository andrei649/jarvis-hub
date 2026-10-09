import React, { useEffect, useRef, useState } from 'react';
import { Image, Pressable, StyleSheet, View } from 'react-native';
import * as FileSystem from 'expo-file-system/legacy';
import { Text, TextInput } from '../components/ThemedText';
import {
  fetchGeneratedImageStatus, fetchGeneratedPng, fetchGeneratedTask, proposeGeneratedImage,
  type ImageStatus, type ImageTask,
} from '../api/generatedImages';
import { useServer } from '../context/ServerContext';
import { loadGeneratedImageTask, saveGeneratedImageTask, type GeneratedImageRecord } from '../storage/generatedImageTask';
import { useThemeStyles, type Theme } from '../theme';

const STATE_LABEL: Record<ImageTask['state'], string> = {
  awaiting_approval: 'awaiting approval', queued: 'queued', generating: 'generating',
  ready: 'ready', failed: 'provider response failed', rejected: 'rejected by owner', deferred: 'deferred',
  refused: 'refused by guard', uncertain: 'uncertain — execution result could not be verified',
};
let imageFileSequence = 0;

export function GeneratedImages({ onGoToApprovals }: { onGoToApprovals: () => void }) {
  const { chatScope } = useServer();
  return <ScopedGeneratedImages key={chatScope} onGoToApprovals={onGoToApprovals} />;
}

function ScopedGeneratedImages({ onGoToApprovals }: { onGoToApprovals: () => void }) {
  const { theme, styles } = useThemeStyles(makeStyles);
  const { config, configured, ready, chatScope } = useServer();
  const [status, setStatus] = useState<ImageStatus | null>(null);
  const [record, setRecord] = useState<GeneratedImageRecord | null>(null);
  const [task, setTask] = useState<ImageTask | null>(null);
  const [prompt, setPrompt] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState<'status' | 'submit' | 'refresh' | 'preview' | 'save' | null>(null);
  const [message, setMessage] = useState('');
  const [previewUri, setPreviewUri] = useState<string | null>(null);
  const [savedUri, setSavedUri] = useState<string | null>(null);
  const epoch = useRef(0);
  const controllers = useRef(new Set<AbortController>());
  const preview = useRef<string | null>(null);
  const previewArtifact = useRef<string | null>(null);
  const taskReadSequence = useRef(0);

  const alive = (value: number) => epoch.current === value;
  const cancel = () => {
    for (const controller of controllers.current) controller.abort();
    controllers.current.clear();
  };
  const cleanPreview = () => {
    const uri = preview.current;
    preview.current = null;
    previewArtifact.current = null;
    setPreviewUri(null);
    if (uri) void FileSystem.deleteAsync(uri, { idempotent: true }).catch(() => {});
  };
  const controller = () => {
    const next = new AbortController();
    controllers.current.add(next);
    return next;
  };

  async function refreshTask(item: Extract<GeneratedImageRecord, { kind: 'task' }>, current: number) {
    if (!config.adminToken.trim()) return;
    const sequence = ++taskReadSequence.current;
    const request = controller();
    setBusy('refresh');
    try {
      const next = await fetchGeneratedTask(config, item.taskId, request.signal);
      if (alive(current) && taskReadSequence.current === sequence) {
        const nextArtifact = next.state === 'ready' && next.artifact ? `${next.artifact.id}:${next.artifact.bytes}` : null;
        if (previewArtifact.current && previewArtifact.current !== nextArtifact) { cleanPreview(); setSavedUri(null); }
        setTask(next); setMessage('');
      }
    } catch {
      if (alive(current) && taskReadSequence.current === sequence) setMessage('Could not refresh this task. Check your admin token and try Refresh.');
    } finally {
      controllers.current.delete(request);
      if (alive(current) && taskReadSequence.current === sequence) setBusy(null);
    }
  }

  async function refreshStatus(current = epoch.current) {
    const request = controller();
    setBusy('status');
    setStatus(null);
    try {
      const next = await fetchGeneratedImageStatus(config, request.signal);
      if (alive(current)) { setStatus(next); setMessage(''); }
    } catch {
      if (alive(current)) setMessage('Could not read local image configuration.');
    } finally {
      controllers.current.delete(request);
      if (alive(current)) setBusy(null);
    }
  }

  useEffect(() => {
    const current = ++epoch.current;
    cancel();
    cleanPreview();
    setRecord(null); setTask(null); setStatus(null); setPrompt(''); setMessage(''); setBusy(null); setLoaded(false); setSavedUri(null);
    if (ready && configured) {
      const request = controller();
      void (async () => {
        const [saved, live] = await Promise.allSettled([
          loadGeneratedImageTask(chatScope), fetchGeneratedImageStatus(config, request.signal),
        ]);
        controllers.current.delete(request);
        if (!alive(current)) return;
        if (saved.status === 'fulfilled' && saved.value) {
          setRecord(saved.value);
          setPrompt(saved.value.prompt);
          if (saved.value.kind === 'task') void refreshTask(saved.value, current);
        }
        if (live.status === 'fulfilled') setStatus(live.value);
        else setMessage('Could not read local image configuration.');
        setLoaded(true);
      })();
    }
    return () => { epoch.current++; cancel(); cleanPreview(); };
  }, [chatScope, config, configured, ready]);

  async function submit() {
    if (!status?.configured || record || busy || !prompt.trim() || prompt.length > 4000) return;
    const submitted = prompt; // Exact input is the approval handoff; do not trim or rewrite.
    const current = ++epoch.current;
    cancel(); cleanPreview(); setTask(null); setSavedUri(null);
    setBusy('submit'); setMessage('');
    const unknown: GeneratedImageRecord = { kind: 'unknown', prompt: submitted };
    try {
      // The proposal must never leave before storage confirms the unknown marker.
      await saveGeneratedImageTask(chatScope, unknown);
    } catch {
      if (alive(current)) { setBusy(null); setMessage('Could not save request tracking. No proposal was sent.'); }
      return;
    }
    try {
      if (!alive(current)) return;
      setRecord(unknown);
      const request = controller();
      try {
        const result = await proposeGeneratedImage(config, submitted, request.signal);
        if (!alive(current)) return;
        if (result.kind === 'queued') {
          const queued: GeneratedImageRecord = { kind: 'task', taskId: result.taskId, prompt: submitted };
          await saveGeneratedImageTask(chatScope, queued);
          if (!alive(current)) return;
          setRecord(queued);
          setTask({ taskId: result.taskId, state: 'awaiting_approval', artifact: null });
          setMessage('Proposal queued. Review the exact prompt in Approvals.');
          await refreshTask(queued, current);
        } else {
          await saveGeneratedImageTask(chatScope, null);
          if (alive(current)) { setRecord(null); setMessage(`Image proposal refused: ${result.reason}.`); }
        }
      } finally { controllers.current.delete(request); }
    } catch {
      if (alive(current)) {
        setRecord(unknown);
        setMessage('Submission delivery is unknown. Check Approvals before submitting again.');
      }
    } finally { if (alive(current)) setBusy(null); }
  }

  async function startNew() {
    if (busy === 'submit') return;
    const current = ++epoch.current;
    cancel(); cleanPreview(); setTask(null); setSavedUri(null);
    try {
      await saveGeneratedImageTask(chatScope, null);
      if (alive(current)) { setRecord(null); setPrompt(''); setMessage(''); setBusy(null); }
    } catch { if (alive(current)) setMessage('Could not clear task tracking. Try again.'); }
  }

  async function showPreview() {
    if (busy || task?.state !== 'ready' || !task.artifact) return;
    const current = epoch.current;
    const artifact = task.artifact;
    const request = controller();
    let pendingUri: string | null = null;
    setBusy('preview'); setMessage('');
    try {
      const base64 = await fetchGeneratedPng(config, artifact.id, artifact.bytes, request.signal);
      if (!alive(current)) return;
      const directory = FileSystem.cacheDirectory;
      if (!directory) throw new Error('No app cache');
      const uri = `${directory}nerva-image-preview-${chatScope}-${Date.now()}-${++imageFileSequence}.png`;
      pendingUri = uri;
      await FileSystem.writeAsStringAsync(uri, base64, { encoding: FileSystem.EncodingType.Base64 });
      if (!alive(current)) return;
      cleanPreview();
      preview.current = uri;
      previewArtifact.current = `${artifact.id}:${artifact.bytes}`;
      pendingUri = null;
      setPreviewUri(uri);
    } catch { if (alive(current)) setMessage('PNG preview unavailable. Refresh the task or try Preview again.'); }
    finally {
      if (pendingUri) void FileSystem.deleteAsync(pendingUri, { idempotent: true }).catch(() => {});
      controllers.current.delete(request);
      if (alive(current)) setBusy(null);
    }
  }

  async function saveCopy() {
    if (busy || !preview.current || task?.state !== 'ready' || !task.artifact) return;
    const current = epoch.current;
    const directory = FileSystem.documentDirectory;
    if (!directory) { setMessage('App files are unavailable on this device.'); return; }
    const uri = `${directory}nerva-image-${chatScope}-${Date.now()}-${++imageFileSequence}.png`;
    setBusy('save');
    try {
      await FileSystem.copyAsync({ from: preview.current, to: uri });
      if (alive(current)) { setSavedUri(uri); setMessage(''); }
    } catch {
      void FileSystem.deleteAsync(uri, { idempotent: true }).catch(() => {});
      if (alive(current)) setMessage('Could not save a copy in app files.');
    }
    finally { if (alive(current)) setBusy(null); }
  }

  if (!ready || !configured) return null;
  return (
    <View style={styles.card}>
      <Text style={styles.title}>Local generated images</Text>
      {!loaded ? <Text style={styles.info}>Checking hub configuration…</Text> : null}
      {loaded ? <Pressable accessibilityRole="button" disabled={busy !== null} style={styles.secondary} onPress={() => void refreshStatus()}><Text style={styles.info}>Refresh image configuration</Text></Pressable> : null}
      {status && !status.configured ? <Text style={styles.info}>Local image generation is off or unavailable: {status.reason}.</Text> : null}
      {status?.configured ? <Text style={styles.info}>Local image generation is configured, not probed. Approval is required; availability is verified only by a completed task.</Text> : null}
      {(status?.configured || record) ? (
        <>
          <TextInput accessibilityLabel="Image prompt" style={styles.input} multiline maxLength={4000}
            editable={!record} placeholder="Describe an image" placeholderTextColor={theme.textDim}
            value={record ? record.prompt : prompt} onChangeText={record ? () => {} : setPrompt} />
          {!record ? <Pressable accessibilityRole="button" disabled={busy !== null || !prompt.trim()} style={styles.button} onPress={() => void submit()}>
            <Text style={styles.buttonText}>Request approval</Text>
          </Pressable> : null}
        </>
      ) : null}
      {record?.kind === 'unknown' ? <Text style={styles.warning}>Submission delivery is unknown. Check Approvals before submitting again.</Text> : null}
      {record?.kind === 'task' ? (
        <>
          <Text style={styles.info}>Task {record.taskId} · {task ? STATE_LABEL[task.state] : 'status not checked'}</Text>
          {task?.state === 'failed' ? <Text style={styles.warning}>No usable image was verified. Check this task before proposing another.</Text> : null}
          {!config.adminToken.trim() ? <Text style={styles.warning}>Admin token required in Settings to check this task.</Text> : null}
          {config.adminToken.trim() ? <Pressable accessibilityRole="button" disabled={busy !== null} style={styles.secondary} onPress={() => void refreshTask(record, epoch.current)}><Text style={styles.info}>Refresh task</Text></Pressable> : null}
          {task?.state === 'ready' && task.artifact ? (
            <>
              <Pressable accessibilityRole="button" disabled={busy !== null} style={styles.button} onPress={() => void showPreview()}><Text style={styles.buttonText}>Preview PNG</Text></Pressable>
              {previewUri ? <Image accessibilityLabel="Generated PNG preview" source={{ uri: previewUri }} style={styles.preview} onError={() => {
                if (preview.current !== previewUri) return;
                cleanPreview(); setSavedUri(null); setMessage('PNG preview could not be displayed. Try Preview again.');
              }} /> : null}
              {previewUri ? <Pressable accessibilityRole="button" disabled={busy !== null} style={styles.secondary} onPress={() => void saveCopy()}><Text style={styles.info}>Save copy</Text></Pressable> : null}
              {savedUri ? <Text style={styles.info}>Saved in app files.</Text> : null}
            </>
          ) : null}
        </>
      ) : null}
      {record ? <Pressable accessibilityRole="button" disabled={busy === 'submit'} style={styles.secondary} onPress={() => void startNew()}><Text style={styles.info}>Start new request</Text></Pressable> : null}
      {record ? <Pressable accessibilityRole="button" style={styles.secondary} onPress={onGoToApprovals}><Text style={styles.info}>Open Approvals</Text></Pressable> : null}
      {message ? <Text style={styles.warning}>{message}</Text> : null}
    </View>
  );
}

const makeStyles = (theme: Theme) => StyleSheet.create({
  card: { backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, borderRadius: 14, padding: 14, margin: 12, gap: 8 },
  title: { color: theme.accent, fontSize: 17, fontWeight: '800' },
  info: { color: theme.textDim, fontSize: 12, lineHeight: 18 },
  warning: { color: theme.warn, fontSize: 12, lineHeight: 18 },
  input: { color: theme.text, backgroundColor: theme.surfaceAlt, borderColor: theme.border, borderWidth: 1, borderRadius: 9, minHeight: 80, padding: 10 },
  button: { backgroundColor: theme.accent, borderRadius: 20, padding: 11, alignItems: 'center' },
  buttonText: { color: '#02121b', fontWeight: '800' },
  secondary: { borderColor: theme.border, borderWidth: 1, borderRadius: 20, padding: 10, alignItems: 'center' },
  preview: { width: '100%', height: 250, resizeMode: 'contain', backgroundColor: theme.bg },
});
