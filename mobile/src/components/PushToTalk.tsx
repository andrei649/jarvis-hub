import React, { useEffect, useRef, useState } from 'react';
import { AppState, Platform, Pressable, StyleSheet, View } from 'react-native';
import {
  AudioModule, getRecordingPermissionsAsync, RecordingPresets, requestRecordingPermissionsAsync,
  setAudioModeAsync, type AudioRecorder,
} from 'expo-audio';
import * as FileSystem from 'expo-file-system/legacy';
import { armMobileMic, readMicTrust, releaseMobileMic, transcribeRecording } from '../api/pushToTalk';
import { useServer } from '../context/ServerContext';
import { isMicrophoneBusy, PushToTalkController, waitForMicrophoneIdle, type DictationState } from '../voice/pushToTalk';
import { Text } from './ThemedText';
import { useThemeStyles, type Theme } from '../theme';

type Props = {
  contextKey: string;
  disabled: boolean;
  onTranscript: (text: string) => void;
  onState: (state: DictationState) => void;
  onStart?: () => void;
};

/** Changing conversation, agent, or hub remounts the controller and revokes old output. */
export function PushToTalk(props: Props) {
  const { chatScope, connectionEpoch } = useServer();
  return <ScopedPushToTalk key={JSON.stringify([chatScope, connectionEpoch, props.contextKey])} {...props} />;
}

function ScopedPushToTalk({ disabled, onTranscript, onState, onStart }: Props) {
  const { config, configured, ready } = useServer();
  const blocked = disabled || !ready || !configured;
  const { styles } = useThemeStyles(makeStyles);
  const [state, setState] = useState<DictationState>({ status: isMicrophoneBusy() ? 'stopping' : 'off' });
  const [message, setMessage] = useState('');
  const callbacks = useRef({ onTranscript, onState, onStart });
  callbacks.current = { onTranscript, onState, onStart };
  const mounted = useRef(true);
  const controller = useRef<PushToTalkController | null>(null);

  if (!controller.current) {
    let recorder: AudioRecorder | null = null;
    const recordingOptions = {
      extension: RecordingPresets.HIGH_QUALITY.extension,
      sampleRate: RecordingPresets.HIGH_QUALITY.sampleRate,
      numberOfChannels: RecordingPresets.HIGH_QUALITY.numberOfChannels,
      bitRate: RecordingPresets.HIGH_QUALITY.bitRate,
      isMeteringEnabled: true,
      directory: 'cache' as const,
      ...(Platform.OS === 'ios' ? RecordingPresets.HIGH_QUALITY.ios : RecordingPresets.HIGH_QUALITY.android),
    };
    controller.current = new PushToTalkController({
      requestPermission: async () => (await requestRecordingPermissionsAsync()).granted === true,
      checkPermission: async () => (await getRecordingPermissionsAsync()).granted === true,
      checkTrust: signal => readMicTrust(config, signal),
      arm: (signal, client) => armMobileMic(config, client, signal),
      releaseLease: client => releaseMobileMic(config, client),
      transcribe: (uri, signal) => transcribeRecording(config, uri, signal),
      deleteRecording: async uri => { await FileSystem.deleteAsync(uri, { idempotent: true }); },
      recorder: {
        prepare: async () => {
          try {
            await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
            recorder = new AudioModule.AudioRecorder(recordingOptions);
            await recorder.prepareToRecordAsync();
          }
          catch (error) {
            let partial: string | null = null;
            try { partial = recorder?.uri ?? recorder?.getStatus().url ?? null; } catch { /* no native file */ }
            await setAudioModeAsync({ allowsRecording: false }).catch(() => {});
            try { recorder?.release(); } catch { /* best effort after failed prepare */ }
            recorder = null;
            if (partial) void FileSystem.deleteAsync(partial, { idempotent: true }).catch(() => {});
            throw error;
          }
        },
        record: options => recorder?.record(options),
        stop: async () => {
          if (!recorder) return null;
          try { await recorder.stop(); }
          finally { await setAudioModeAsync({ allowsRecording: false }).catch(() => {}); }
          return recorder.uri ?? recorder.getStatus().url;
        },
        status: () => {
          if (!recorder) return { isRecording: false };
          const current = recorder.getStatus();
          return { isRecording: current.isRecording, metering: current.metering, url: current.url };
        },
        release: () => { try { recorder?.release(); } finally { recorder = null; } },
      },
      onState: next => {
        if (!mounted.current) return;
        setState(next);
        if (next.reason === 'stop_unconfirmed') {
          setMessage('Microphone stop unconfirmed. Close the app if the device microphone indicator remains on.');
        } else if (next.status === 'error') {
          setMessage('Microphone unavailable. Check permission and hub trust.');
        }
        callbacks.current.onState(next);
      },
      onTranscript: text => { if (mounted.current) callbacks.current.onTranscript(text); },
      onNoSpeech: () => { if (mounted.current) setMessage('No speech detected.'); },
      onStart: () => { setMessage(''); callbacks.current.onStart?.(); },
    });
  }

  useEffect(() => {
    if (blocked) void controller.current?.cancel();
  }, [blocked]);

  useEffect(() => {
    if (!isMicrophoneBusy()) return;
    let active = true;
    callbacks.current.onState({ status: 'stopping' });
    const watch = setTimeout(() => {
      if (!active || !mounted.current || !isMicrophoneBusy() || controller.current?.getState().status !== 'off') return;
      const uncertain: DictationState = { status: 'error', reason: 'stop_unconfirmed' };
      setState(uncertain);
      setMessage('Microphone stop unconfirmed. Close the app if the device microphone indicator remains on.');
      callbacks.current.onState(uncertain);
    }, 3000);
    void waitForMicrophoneIdle().then(() => {
      clearTimeout(watch);
      if (active && mounted.current && controller.current?.getState().status === 'off') {
        setState({ status: 'off' });
        setMessage('');
        callbacks.current.onState({ status: 'off' });
      }
    });
    return () => { active = false; clearTimeout(watch); };
  }, []);

  useEffect(() => {
    const subscription = AppState.addEventListener('change', next => {
      if (next !== 'active') void controller.current?.cancel();
    });
    return () => {
      mounted.current = false;
      subscription.remove();
      controller.current?.dispose();
    };
  }, []);

  const press = () => {
    if (blocked || state.status === 'stopping' || !!state.reason || AppState.currentState !== 'active') return;
    controller.current?.press();
  };
  const release = () => { void controller.current?.release(); };
  const alternative = () => {
    if (blocked || state.status === 'stopping' || !!state.reason || AppState.currentState !== 'active') return;
    if (state.status === 'listening') release();
    else if (state.status === 'off' || state.status === 'idle' || state.status === 'error') press();
  };

  return (
    <View style={styles.row}>
      <Pressable accessibilityRole="button" accessibilityLabel="Hold to dictate"
        disabled={blocked || state.status === 'stopping' || !!state.reason}
        onPressIn={press} onPressOut={release} style={styles.button}>
        <Text style={styles.buttonText}>Hold to dictate</Text>
      </Pressable>
      <Pressable accessibilityRole="button"
        accessibilityLabel={state.status === 'listening' ? 'Finish dictation' : 'Start dictation without holding'}
        disabled={blocked || state.status === 'stopping' || state.status === 'transcribing' || !!state.reason}
        onPress={alternative} style={styles.alternative}>
        <Text style={styles.alternativeText}>{state.status === 'listening' ? 'Finish' : 'Tap to dictate'}</Text>
      </Pressable>
      {state.status === 'listening' ? <Text style={styles.status}>Listening…</Text> : null}
      {state.status === 'stopping' ? <Text style={styles.status}>Stopping microphone…</Text> : null}
      {state.status === 'transcribing' ? <Text style={styles.status}>Transcribing…</Text> : null}
      {message ? <Text style={styles.status}>{message}</Text> : null}
    </View>
  );
}

const makeStyles = (theme: Theme) => StyleSheet.create({
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, alignItems: 'center', paddingHorizontal: 12, paddingBottom: 8 },
  button: { backgroundColor: theme.accent, borderRadius: 16, paddingHorizontal: 12, paddingVertical: 8 },
  buttonText: { color: '#02121b', fontSize: 12, fontWeight: '700' },
  alternative: { borderColor: theme.border, borderWidth: 1, borderRadius: 16, paddingHorizontal: 10, paddingVertical: 8 },
  alternativeText: { color: theme.text, fontSize: 12 },
  status: { color: theme.textDim, fontSize: 12 },
});
