import React, { useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { ApiError, fetchStatus, normalizeBaseUrl } from '../api/client';
import { useServer } from '../context/ServerContext';
import { theme } from '../theme';

type TestState =
  | { kind: 'idle' }
  | { kind: 'testing' }
  | { kind: 'ok'; detail: string }
  | { kind: 'fail'; detail: string };

export function SettingsScreen() {
  const { config, updateConfig } = useServer();
  const [baseUrl, setBaseUrl] = useState(config.baseUrl);
  const [token, setToken] = useState(config.token);
  const [saved, setSaved] = useState(false);
  const [test, setTest] = useState<TestState>({ kind: 'idle' });

  const onSave = async () => {
    await updateConfig({ baseUrl, token });
    setBaseUrl(normalizeBaseUrl(baseUrl));
    setSaved(true);
    setTimeout(() => setSaved(false), 1800);
  };

  const onTest = async () => {
    setTest({ kind: 'testing' });
    try {
      const status = await fetchStatus({ baseUrl: normalizeBaseUrl(baseUrl), token: token.trim() });
      const model = status.loaded_model || status.active_model || status.llm_backend || 'connected';
      setTest({ kind: 'ok', detail: `Connected · ${model}` });
    } catch (e) {
      setTest({ kind: 'fail', detail: e instanceof ApiError ? e.message : 'Connection failed' });
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <Text style={styles.label}>Hub URL</Text>
        <TextInput
          style={styles.input}
          value={baseUrl}
          onChangeText={setBaseUrl}
          placeholder="192.168.1.20:8000"
          placeholderTextColor={theme.textDim}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          inputMode="url"
        />
        <Text style={styles.help}>The address of your Jarvis hub. http:// is added automatically.</Text>

        <Text style={styles.label}>User token</Text>
        <TextInput
          style={styles.input}
          value={token}
          onChangeText={setToken}
          placeholder="Optional — JARVIS_USER_TOKEN"
          placeholderTextColor={theme.textDim}
          autoCapitalize="none"
          autoCorrect={false}
          secureTextEntry
        />
        <Text style={styles.help}>
          Sent as the X-User-Token header. Leave blank for an unsecured local hub.
        </Text>

        <View style={styles.buttons}>
          <Pressable style={[styles.btn, styles.primary]} onPress={onSave}>
            <Text style={styles.primaryText}>{saved ? 'Saved ✓' : 'Save'}</Text>
          </Pressable>
          <Pressable
            style={[styles.btn, styles.secondary]}
            onPress={onTest}
            disabled={test.kind === 'testing' || !baseUrl.trim()}
          >
            {test.kind === 'testing' ? (
              <ActivityIndicator color={theme.accent} />
            ) : (
              <Text style={styles.secondaryText}>Test connection</Text>
            )}
          </Pressable>
        </View>

        {test.kind === 'ok' && <Text style={[styles.result, { color: theme.ok }]}>{test.detail}</Text>}
        {test.kind === 'fail' && <Text style={[styles.result, { color: theme.danger }]}>{test.detail}</Text>}

        <View style={styles.footer}>
          <Text style={styles.footerText}>Jarvis mobile · companion for the Jarvis hub</Text>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { padding: 16 },
  label: {
    color: theme.accent,
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 1,
    textTransform: 'uppercase',
    marginBottom: 8,
    marginTop: 8,
  },
  input: {
    color: theme.text,
    fontSize: 16,
    paddingHorizontal: 14,
    paddingVertical: 12,
    backgroundColor: theme.surface,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: theme.border,
  },
  help: { color: theme.textDim, fontSize: 13, marginTop: 6, marginBottom: 8 },
  buttons: { flexDirection: 'row', gap: 12, marginTop: 20 },
  btn: {
    flex: 1,
    height: 48,
    borderRadius: 24,
    alignItems: 'center',
    justifyContent: 'center',
  },
  primary: { backgroundColor: theme.accent },
  primaryText: { color: '#02121b', fontWeight: '700', fontSize: 16 },
  secondary: { backgroundColor: theme.surface, borderWidth: 1, borderColor: theme.accent },
  secondaryText: { color: theme.accent, fontWeight: '700', fontSize: 16 },
  result: { marginTop: 16, fontSize: 14, textAlign: 'center' },
  footer: { marginTop: 40, alignItems: 'center' },
  footerText: { color: theme.textDim, fontSize: 12 },
});
