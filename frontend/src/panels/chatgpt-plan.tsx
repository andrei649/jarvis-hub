import React, { useEffect, useRef, useState } from 'react';
import { apiGet, apiPost } from '../api/client';
import { guardFlags, guardRefusal, type GuardFlags, type GuardRefusal } from '../selection-guard';

type Model = { slug: string; display_name: string };
type Status = { connected: boolean; selected_model?: string };

const PATH = '/api/admin/chatgpt-plan';
const AUTH_ORIGIN = 'https://auth.openai.com';
const AUTH_PATH = '/api/accounts/authorize';

function authorizationUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    return url.origin === AUTH_ORIGIN && url.pathname === AUTH_PATH
      && !url.username && !url.password && !url.hash ? value : null;
  } catch { return null; }
}

function useRomanian(): boolean {
  const [romanian, setRomanian] = useState(() => document.documentElement.lang === 'ro');
  useEffect(() => {
    const sync = () => setRomanian(document.documentElement.lang === 'ro');
    const observer = new MutationObserver(sync);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    window.addEventListener('jarvis:locale_changed', sync);
    return () => { observer.disconnect(); window.removeEventListener('jarvis:locale_changed', sync); };
  }, []);
  return romanian;
}

export function ChatGptPlan() {
  const ro = useRomanian();
  const [connected, setConnected] = useState<boolean | null>(null);
  const [selectedModel, setSelectedModel] = useState<string | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [models, setModels] = useState<Model[] | null>(null);
  const [choice, setChoice] = useState<Model | null>(null);
  const [consent, setConsent] = useState<GuardRefusal | null>(null);
  const [choiceError, setChoiceError] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const sequence = useRef(0);
  const choiceTrigger = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    const ticket = ++sequence.current;
    apiGet<Status>(PATH, { admin: true })
      .then(result => { if (ticket === sequence.current) {
        setConnected(result.connected === true);
        setSelectedModel(result.connected && typeof result.selected_model === 'string' ? result.selected_model : null);
      } })
      .catch(() => { if (ticket === sequence.current) setMessage(ro ? 'Starea conexiunii nu este disponibilă.' : 'Connection status unavailable.'); });
    return () => { sequence.current++; };
  // The first status read belongs to this mount; language changes do not repeat it.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refresh = async () => {
    const ticket = ++sequence.current;
    setBusy(true); setMessage('');
    try {
      const result = await apiGet<Status>(PATH, { admin: true });
      if (ticket !== sequence.current) return;
      const nowConnected = result.connected === true;
      setConnected(nowConnected); setUrl(null);
      setSelectedModel(nowConnected && typeof result.selected_model === 'string' ? result.selected_model : null);
      if (!nowConnected) { setModels(null); setChoice(null); setConsent(null); }
    } catch {
      if (ticket === sequence.current) setMessage(ro ? 'Starea conexiunii nu este disponibilă.' : 'Connection status unavailable.');
    } finally { if (ticket === sequence.current) setBusy(false); }
  };

  const connect = async () => {
    const ticket = ++sequence.current;
    setBusy(true); setMessage(''); setUrl(null);
    try {
      const result = await apiPost<{ url: string }>('/api/admin/chatgpt-plan/connect', {}, { admin: true });
      if (ticket !== sequence.current) return;
      const safe = authorizationUrl(result.url);
      if (safe) setUrl(safe);
      else setMessage(ro ? 'Linkul de autentificare nu este disponibil.' : 'Sign-in link unavailable.');
    } catch (error) {
      if (ticket === sequence.current) {
        const detail = (error as { body?: { detail?: unknown } })?.body?.detail;
        const port = window.location.port ? `:${window.location.port}` : '';
        setMessage(detail === 'chatgpt_requires_local_hub'
          ? ro
            ? `Deschide Nerva pe dispozitivul hub la 127.0.0.1${port}, pe același port, apoi încearcă din nou.`
            : `Open Nerva on the hub machine at 127.0.0.1${port}, using this hub's port, then try again.`
          : ro ? 'Autentificarea nu a pornit.' : 'Sign-in could not start.');
      }
    } finally { if (ticket === sequence.current) setBusy(false); }
  };

  const cancel = () => {
    sequence.current++;
    setBusy(false); setUrl(null); setMessage('');
  };

  const showModels = async () => {
    const ticket = ++sequence.current;
    setBusy(true); setMessage(''); setModels(null); setChoice(null); setConsent(null);
    try {
      const result = await apiGet<{ models: Model[] }>('/api/admin/chatgpt-plan/models', { admin: true });
      if (ticket !== sequence.current) return;
      if (!Array.isArray(result.models)) throw new Error('invalid models');
      setModels(result.models.filter(row => typeof row?.slug === 'string' && typeof row?.display_name === 'string'));
    } catch {
      if (ticket === sequence.current) setMessage(ro ? 'Modelele nu sunt disponibile.' : 'Models unavailable.');
    } finally { if (ticket === sequence.current) setBusy(false); }
  };

  const closeChoice = () => {
    sequence.current++;
    setBusy(false); setChoice(null); setConsent(null); setChoiceError('');
    queueMicrotask(() => choiceTrigger.current?.focus());
  };

  const choose = (model: Model, trigger: HTMLButtonElement) => {
    choiceTrigger.current = trigger;
    setChoice(model); setConsent(null); setChoiceError(''); setMessage('');
  };

  const selectForChat = async (flags: GuardFlags = {}) => {
    if (!choice) return;
    const model = choice.slug;
    const ticket = ++sequence.current;
    setBusy(true); setConsent(null); setChoiceError('');
    try {
      const result = await apiPost<{ model: string }>('/api/admin/chatgpt-plan/select', { model, ...flags }, { admin: true });
      if (ticket !== sequence.current) return;
      if (result.model !== model) throw new Error('selection changed');
      setSelectedModel(model); setChoice(null);
      setMessage(ro
        ? `${model} a fost selectat pentru conversații prin planul ChatGPT. Mesajele anterioare cer în continuare acord separat.`
        : `${model} selected for chat through ChatGPT plan. Prior turns still require separate consent.`);
    } catch (error) {
      if (ticket !== sequence.current) return;
      const refusal = guardRefusal(error);
      if (refusal) setConsent(refusal);
      else setChoiceError(ro ? 'Modelul nu a fost selectat. Verifică conexiunea și încearcă din nou.'
        : 'Model not selected. Check the connection and try again.');
    } finally { if (ticket === sequence.current) setBusy(false); }
  };

  const disconnect = async () => {
    const ticket = ++sequence.current;
    setBusy(true); setMessage(''); setUrl(null); setModels(null); setChoice(null); setConsent(null);
    try {
      await apiPost('/api/admin/chatgpt-plan/disconnect', {}, { admin: true });
      if (ticket === sequence.current) {
        setConnected(false);
        setSelectedModel(null);
        setMessage(ro ? 'Conexiunea ChatGPT a fost eliminată local din acest hub.'
          : 'ChatGPT connection removed from this hub locally.');
      }
    } catch {
      if (ticket === sequence.current) setMessage(ro ? 'Deconectarea nu a reușit.' : 'Disconnect failed.');
    } finally { if (ticket === sequence.current) setBusy(false); }
  };

  return (
    <li aria-label={ro ? 'plan ChatGPT, conectare cont' : 'ChatGPT plan account connection'}
      style={{ borderBottom: '1px solid var(--panel-line)', padding: '7px 0' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <strong>{ro ? 'Plan ChatGPT' : 'ChatGPT plan'}</strong>
        <span>{ro ? 'conectare cont · fără cheie API' : 'account connection · no API key'}</span>
        <span>{connected === null ? (ro ? 'se verifică…' : 'checking…')
          : connected ? (ro ? 'conectat' : 'connected') : (ro ? 'neconectat' : 'not connected')}</span>
        {connected && selectedModel && <span>{ro ? `Selectat pentru conversații: ${selectedModel}`
          : `Selected for chat: ${selectedModel}`}</span>}
      </div>
      <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
        {!connected && <button className="tool-btn" disabled={busy && !url} onClick={() => void connect()}>
          {ro ? 'Continuă cu ChatGPT' : 'Continue with ChatGPT'}</button>}
        <button className="tool-btn" disabled={busy} onClick={() => void refresh()}>
          {ro ? 'Actualizează conexiunea' : 'Refresh connection'}</button>
        {connected && <>
          <button className="tool-btn" disabled={busy} onClick={() => void showModels()}>
            {ro ? 'Arată modelele disponibile' : 'Show available models'}</button>
          <button className="tool-btn" onClick={() => void disconnect()}>
            {ro ? 'Deconectează' : 'Disconnect'}</button>
        </>}
        {(url || (busy && !connected)) && <button className="tool-btn" onClick={cancel}>{url
          ? ro ? 'Ascunde linkul de autentificare' : 'Hide sign-in link'
          : ro ? 'Anulează' : 'Cancel'}</button>}
      </div>
      {url && <div style={{ marginTop: 6 }}>
        <a href={url} target="_blank" rel="noopener noreferrer">{ro ? 'Deschide autentificarea ChatGPT' : 'Open ChatGPT sign-in'}</a>
      </div>}
      {models && <ul aria-label={ro ? 'modele disponibile' : 'available models'}>
        {models.map((model, index) => <li key={`${model.slug}-${index}`}><span>{model.display_name} ({model.slug})</span>{' '}
          <button className="tool-btn" onClick={ev => choose(model, ev.currentTarget)}
            aria-label={ro ? `Alege ${model.slug} pentru conversații` : `Choose ${model.slug} for chat`}>
            {ro ? 'Alege' : 'Choose'}</button>
        </li>)}
      </ul>}
      {choice && <div role="dialog" aria-label={ro ? 'Folosește planul ChatGPT pentru conversații' : 'Use ChatGPT plan for chat'}
        tabIndex={-1} ref={node => node?.focus()}
        onKeyDown={ev => { if (ev.key === 'Escape') { ev.preventDefault(); closeChoice(); } }}
        style={{ border: '1px solid var(--amber)', padding: 8, marginTop: 8 }}>
        <div>{ro ? 'Furnizor: plan ChatGPT' : 'Provider: ChatGPT plan'}</div>
        <div>{ro ? `Model: ${choice.slug}` : `Model: ${choice.slug}`}</div>
        <p>{ro
          ? 'Acest model primește mesajele conversației. Mesajele anterioare cer acord separat. Pot exista limite ale planului.'
          : 'This model receives chat messages. Prior turns require separate consent. Plan limits may apply.'}</p>
        <a href="https://chatgpt.com/settings/usage" target="_blank" rel="noopener noreferrer">
          {ro ? 'Verifică utilizarea ChatGPT' : 'Check ChatGPT usage'}</a>
        {consent && <ul>{consent.guards.map((guard, index) => <li key={index}>{guard.message}</li>)}</ul>}
        {choiceError && <div role="status">{choiceError}</div>}
        <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
          <button className="tool-btn" disabled={busy} onClick={() => void selectForChat(consent ? guardFlags(consent) : {})}>
            {consent ? ro ? 'Am înțeles, folosește acest model' : 'I understand, use this model'
              : ro ? 'Confirmă modelul pentru conversații' : 'Confirm chat model'}</button>
          <button className="tool-btn" onClick={closeChoice}>{ro ? 'Anulează' : 'Cancel'}</button>
        </div>
      </div>}
      {message && <div role="status">{message}</div>}
    </li>
  );
}
