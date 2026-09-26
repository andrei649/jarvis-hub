import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { apiGet } from './api/client';
import { fmtTimeShort } from './primitives';

type Action = 'show' | 'hide' | 'reset' | 'handoff' | 'drag' | 'resize';
type Capabilities = { compositor: string; positioning: boolean; alwaysOnTop: boolean };
function bridge() { return (window as any).__TAURI__?.core; }
export function isFloatingDesktop() { return !!bridge() && new URLSearchParams(window.location.search).get('desktop') === 'floating'; }
export function hasDesktopBridge() { return !!bridge(); }
// H222: tell the shell's tray whether this window has Nerva listening. Only a change is
// sent; a refused call is sent again with the next change.
let lastListening = '';
export function setDesktopListening(state: string) {
  const core = bridge();
  if (!core || state === lastListening) return;
  lastListening = state;
  Promise.resolve(core.invoke('desktop_listening', { state })).catch(() => { lastListening = ''; });
}
export function notifyDesktopConversation() {
  if (!bridge() || typeof BroadcastChannel === 'undefined') return;
  const channel = new BroadcastChannel('nerva-desktop-conversation');
  channel.postMessage('changed'); channel.close();
}
// Only invalidation crosses windows; credentials and messages stay in the existing
// same-origin client/server session. Cleanup prevents a slow read replacing a turn.
export function useDesktopConversation(setMessages: (messages: any[]) => void, busy: boolean, demo: boolean) {
  const sync = useRef({ busy, pending: false, generation: 0 });
  const resume = useRef<(() => void) | null>(null);
  useLayoutEffect(() => {
    sync.current.busy = busy;
    if (busy) sync.current.generation += 1;
  }, [busy]);
  useEffect(() => {
    if (!bridge() || demo) return;
    let active = true;
    const refresh = () => {
      // Keep one invalidation until an accepted read reconciles it. In particular,
      // a queued local turn cannot consume another window's completion while busy.
      sync.current.pending = true;
      if (sync.current.busy) return;
      const request = ++sync.current.generation;
      apiGet('/memory').then((r: any) => {
        if (!active || sync.current.busy || request !== sync.current.generation || !Array.isArray(r?.turns)) return;
        sync.current.pending = false;
        setMessages(r.turns.map((tn: any) => ({ role: tn.role === 'user' ? 'user' : 'agent', who: tn.agent_id || 'jarvis', role_label: '', text: tn.content, ts: fmtTimeShort(new Date(tn.timestamp || Date.now())) })));
      }).catch(() => {});
    };
    resume.current = () => { if (sync.current.pending) refresh(); };
    // Keep subscribers alive across busy changes so queued channel delivery is
    // not discarded by closing the channel during the busy-to-idle commit.
    const channel = typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel('nerva-desktop-conversation');
    if (channel) channel.onmessage = refresh;
    window.addEventListener('focus', refresh);
    window.addEventListener('nerva-desktop-handoff', refresh);
    resume.current();
    return () => {
      active = false; sync.current.generation += 1; resume.current = null;
      channel?.close(); window.removeEventListener('focus', refresh); window.removeEventListener('nerva-desktop-handoff', refresh);
    };
  }, [setMessages, demo]);
  useEffect(() => { if (!busy) resume.current?.(); }, [busy]);
}
export function DesktopControls({ floating = false }: { floating?: boolean }) {
  const [error, setError] = useState('');
  const [caps, setCaps] = useState<Capabilities | null>(null);
  useEffect(() => { if (bridge() && floating) bridge().invoke('desktop_capabilities').then(setCaps).catch((e: unknown) => setError(String(e))); }, [floating]);
  if (!bridge()) return null;
  const act = (action: Action) => { setError(''); bridge().invoke('desktop_action', { action }).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e))); };
  return <div className={floating ? 'desktop-controls floating-controls' : 'desktop-controls'}>
    {floating ? <>
      <button className="desktop-drag" aria-label="Move floating chat" onMouseDown={(e) => { if (e.button === 0) act('drag'); }}>NERVA · CHAT</button>
      <button onClick={() => act('handoff')}>Open in app</button>
      <button onClick={() => act('reset')}>Reset layout</button>
      <button onClick={() => act('hide')}>Hide chat</button>
      {caps && (!caps.positioning || !caps.alwaysOnTop) && <span role="status">{caps.compositor}: placement and topmost are controlled by your compositor.</span>}
      <button className="desktop-resize" aria-label="Resize floating chat" onMouseDown={(e) => { if (e.button === 0) act('resize'); }}>◢</button>
    </> : <button onClick={() => act('show')}>Float chat</button>}
    {error && <span role="alert">{error}</span>}
  </div>;
}
