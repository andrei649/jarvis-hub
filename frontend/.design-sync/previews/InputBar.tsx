import React from 'react';
import { InputBar, V2 } from 'jarvis-hud-v2';

const T = V2.I18N.en;
const noop = () => {};
const wrap: React.CSSProperties = { width: 760, background: 'var(--void, #04070e)', borderRadius: 8, padding: 16 };
const CFG = { mode: 'hands-free', tts: 'server', lang: 'auto', barge: 'off' };

/** Canonical idle bar — channel tag, prompt caret, mic + voice settings, transmit. */
export function Idle() {
  return (
    <div className="hud-root" style={wrap}>
      <InputBar onSubmit={noop} mic={false} setMic={noop} voice={null}
        cfg={CFG} onCfg={noop} micMuted={false} t={T} />
    </div>
  );
}

/** Hands-free listening — green level pill with live transcript, mic engaged. */
export function VoiceListening() {
  const voice = { active: true, supported: true, status: 'listening', level: 0.18, transcript: 'move my four o’clock with Vision' };
  return (
    <div className="hud-root" style={wrap}>
      <InputBar onSubmit={noop} mic={true} setMic={noop} voice={voice}
        cfg={CFG} onCfg={noop} micMuted={false} t={T} />
    </div>
  );
}

/** Voice failed — amber error pill, mic dimmed by the OS-level mute. */
export function MicError() {
  const voice = { active: false, supported: true, status: 'idle', error: 'mic permission denied — check browser settings' };
  return (
    <div className="hud-root" style={wrap}>
      <InputBar onSubmit={noop} mic={false} setMic={noop} voice={voice}
        cfg={CFG} onCfg={noop} micMuted={true} t={T} />
    </div>
  );
}
