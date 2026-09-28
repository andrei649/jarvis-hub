/* H613 — the owner's TTS / STT command providers, in Settings → Voice.

   A command provider makes the hub run a program, so the two settings (voice.tts_command,
   voice.stt_command) are never edited in the settings list: they render read-only there,
   and this block is their one editor. It asks the hub (POST /api/admin/voice/commands);
   the hub validates the argv, and a set or a change goes to the Decision Inbox as a card
   naming the program — "Waiting for your approval in the Decision Inbox (task N)". Nothing
   runs until a person accepts it, the hub is started with JARVIS_VOICE_COMMANDS=1 and the
   program file is still the one approved. Clear applies at once.

   The argv is a JSON list of strings. Placeholders are whole elements: {text_file},
   {output} and {lang} for TTS, {audio} and {lang} for STT.

   VoiceCommandCard is the Decision Inbox card of a `settings.voice_command` request: the
   side, every file that runs (the program and an interpreter's script, each with its size
   and the first 16 hex digits of its sha256), the full argv with the placeholders marked,
   and that it runs on this machine as the hub's user and cannot be undone by the hub. The
   card has no edit: an edit could swap the program, so the hub refuses it — ask again. */
import React, { useEffect, useState } from 'react';
import { apiPost, apiPut } from '../api/client';
import { mono, useApi } from '../panel-kit';

export const VOICE_COMMANDS_PATH = '/api/admin/voice/commands';
export const VOICE_COMMAND_KIND = 'settings.voice_command';
const PLACEHOLDERS = new Set(['{text_file}', '{output}', '{audio}', '{lang}']);
const SIDES = ['tts', 'stt'] as const;
const EXAMPLE: Record<string, string> = {
  tts: '["/usr/local/bin/my-tts", "--lang", "{lang}", "--in", "{text_file}", "--out", "{output}"]',
  stt: '["/usr/local/bin/my-stt", "--lang", "{lang}", "{audio}"]',
};

/** The typed argv as a list of strings, or why it is not one. */
export function parseArgv(text: string): { argv?: string[]; error?: string } {
  let value: unknown;
  try { value = JSON.parse(text); } catch { return { error: 'not JSON: a list like ' + EXAMPLE.tts }; }
  if (!Array.isArray(value) || !value.length || !value.every((v) => typeof v === 'string')) {
    return { error: 'a JSON list of strings, the program first (an absolute path)' };
  }
  return { argv: value as string[] };
}

/** What the hub answered, as the owner reads it. */
export function commandNote(r: any): string {
  if (r && r.pending != null) return `Waiting for your approval in the Decision Inbox (task ${r.pending})`;
  if (r && r.cleared) return 'Cleared';
  if (r && r.dry_run) return `Valid · runs ${r.exe}`;
  return 'Done';
}

/** A refusal: the hub's problems, else its detail or error. */
export function commandRefusal(err: any): string {
  const body = err?.body || {};
  if (Array.isArray(body.problems) && body.problems.length) return body.problems.join(' · ');
  for (const key of ['detail', 'error']) {
    if (typeof body[key] === 'string' && body[key].trim()) return body[key].trim();
  }
  return err?.message || 'refused';
}

function SideRow({ side, state, onDone, providerId }: { side: string; state: any; onDone: () => void; providerId?: string }) {
  const [text, setText] = useState('');
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const post = (body: Record<string, unknown>) =>
    apiPost(VOICE_COMMANDS_PATH, { ...body, ...(providerId ? { provider_id: providerId } : {}) }, { admin: true })
      .then((r: any) => { setNote({ ok: true, text: commandNote(r) }); onDone(); })
      .catch((err: any) => setNote({ ok: false, text: commandRefusal(err) }));
  const send = (argv: string[]) => post({ side, argv });
  const clear = () => post({ side, clear: true });      // a clear is only ever explicit
  const request = () => {
    const parsed = parseArgv(text);
    if (parsed.error) { setNote({ ok: false, text: parsed.error }); return; }
    send(parsed.argv!);
  };
  const s = state || {};
  const status = s.ready ? 'ready' : s.configured ? `not running: ${s.reason}` : 'not set';
  return <div data-testid={`voice-command-${side}${providerId ? '-' + providerId : ''}`} style={{ margin: '4px 0 8px' }}>
    <div style={{ ...mono, fontSize: 10.5, color: 'var(--ink-2)' }}>
      {side.toUpperCase()} command · {status}
      {providerId && <span> · {providerId} · revision {s.provider_revision}</span>}
      {s.exe && <span style={{ color: 'var(--ink-3)' }}> · {s.exe}</span>}
      {s.pending_task != null && <span style={{ color: 'var(--amber)' }}> · waiting in the Decision Inbox (task {s.pending_task})</span>}
    </div>
    <textarea aria-label={`${side}${providerId ? ' ' + providerId : ''} command argv`} value={text} placeholder={EXAMPLE[side]} rows={2}
      onChange={(e) => setText(e.target.value)}
      style={{ width: '100%', background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 4, padding: 5, ...mono, fontSize: 10.5 }} />
    <div style={{ display: 'flex', gap: 6, marginTop: 3 }}>
      <button className="tool-btn" onClick={request}>Request</button>
      {(s.configured || (providerId && s.pending_task != null)) && <button className="tool-btn" onClick={clear}>Clear</button>}
    </div>
    {note && <div role={note.ok ? 'status' : 'alert'} style={{ ...mono, fontSize: 10, marginTop: 3, color: note.ok ? 'var(--amber)' : 'var(--red)' }}>{note.text}</div>}
  </div>;
}

function NamedProviders({ data, reload }: { data: any; reload: () => void }) {
  const [name, setName] = useState('');
  const [side, setSide] = useState('tts');
  const [argv, setArgv] = useState('');
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [selection, setSelection] = useState('');
  const [selectionNote, setSelectionNote] = useState<{ ok: boolean; text: string } | null>(null);
  const saved = data?.selected_stt_provider ?? '';
  useEffect(() => { setSelection(saved); }, [saved]);
  const providers = data?.providers || {};
  const stt = Array.isArray(providers.stt) ? providers.stt : [];
  const request = async () => {
    if (!/^[a-z][a-z0-9_-]{0,31}$/.test(name)) {
      setNote({ ok: false, text: 'Use a lowercase name starting with a letter, up to 32 letters, digits, underscores or hyphens.' });
      return;
    }
    const parsed = parseArgv(argv);
    if (parsed.error) { setNote({ ok: false, text: parsed.error }); return; }
    try {
      const result = await apiPost(VOICE_COMMANDS_PATH, { side, provider_id: name, argv: parsed.argv }, { admin: true });
      setNote({ ok: true, text: commandNote(result) }); reload();
    } catch (error) { setNote({ ok: false, text: commandRefusal(error) }); }
  };
  const saveSelection = async () => {
    try {
      await apiPut('/api/admin/settings/voice', { values: { stt_command_provider: selection } }, { admin: true });
      setSelectionNote({ ok: true, text: 'STT selection saved' }); reload();
    } catch (error) { setSelectionNote({ ok: false, text: commandRefusal(error) }); }
  };
  return <div style={{ borderTop: '1px solid var(--panel-line)', paddingTop: 6 }}>
    <div style={mono}>Named providers</div>
    {data?.error && <div role="alert">Named providers unavailable: {String(data.error)}</div>}
    {SIDES.flatMap(s => (Array.isArray(providers[s]) ? providers[s] : []).map((p: any) =>
      <SideRow key={`${s}-${p.provider_id}`} side={s} providerId={p.provider_id} state={p} onDone={reload} />))}
    <div style={{ display: 'flex', gap: 6, marginTop: 5 }}>
      <select aria-label="new provider kind" value={side} onChange={e => setSide(e.target.value)}>
        <option value="tts">TTS</option><option value="stt">STT</option>
      </select>
      <input aria-label="new provider name" placeholder="Provider name" maxLength={32} value={name} onChange={e => setName(e.target.value)} />
    </div>
    <textarea aria-label="new provider argv" placeholder={EXAMPLE[side]} rows={2} value={argv}
      onChange={e => setArgv(e.target.value)} style={{ width: '100%', marginTop: 4, ...mono }} />
    <button className="tool-btn" onClick={request}>Request named provider</button>
    {note && <div role={note.ok ? 'status' : 'alert'}>{note.text}</div>}
    <div style={{ marginTop: 6 }}>
      <label>STT command provider <select aria-label="STT command provider selection" value={selection} onChange={e => setSelection(e.target.value)}>
        <option value="">Legacy command</option>
        {stt.map((p: any) => <option key={p.provider_id} value={p.provider_id}>{p.provider_id}{p.ready ? '' : ' (unavailable)'}</option>)}
        {selection && !stt.some((p: any) => p.provider_id === selection) && <option value={selection}>{selection} (unavailable)</option>}
      </select></label>{' '}
      <button className="tool-btn" onClick={saveSelection}>Save STT selection</button>
      {selectionNote && <div role={selectionNote.ok ? 'status' : 'alert'}>{selectionNote.text}</div>}
    </div>
    <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 4 }}>
      Choose provider:name in TTS voice after approval. STT selection applies when the transcription mode uses a command.
      An unavailable selection stays unavailable; clearing a provider does not select another one.
    </div>
  </div>;
}

export function VoiceCommands() {
  const { d, reload } = useApi(VOICE_COMMANDS_PATH, true, true);
  const sides = (d && (d as any).sides) || {};
  const armed = SIDES.some((side) => sides[side]?.armed);
  return <div data-testid="voice-commands" style={{ border: '1px solid var(--panel-line)', borderRadius: 4, padding: 6, margin: '2px 0 6px' }}>
    <div style={{ ...mono, fontSize: 9.5, letterSpacing: '.12em', color: 'var(--ink-3)' }}>COMMAND PROVIDERS</div>
    <div style={{ fontSize: 10, color: 'var(--ink-3)', margin: '2px 0 4px' }}>
      A program the hub runs to speak or to transcribe. Setting one asks you in the Decision Inbox first;
      it runs only with JARVIS_VOICE_COMMANDS=1{d && !armed ? ' (not set on this hub)' : ''}, never in safe mode,
      and needs approving again if any file it runs changes.
    </div>
    {SIDES.map((side) => <SideRow key={side} side={side} state={sides[side]} onDone={reload} />)}
    <NamedProviders data={d} reload={reload} />
  </div>;
}

const short = (sha: unknown) => (typeof sha === 'string' && sha ? sha.slice(0, 16) : 'unknown');
const bytes = (n: unknown) => (typeof n === 'number' ? `${n} bytes` : 'size unknown');

/** The Decision Inbox card of a `settings.voice_command` task, from the preview it carries. */
export function VoiceCommandCard({ task }: { task: any }) {
  const preview = task?.payload?.preview;
  if (!preview || typeof preview !== 'object') return null;
  const side = String(preview.kind || preview.side || task?.payload?.side || '?');
  const files: any[] = Array.isArray(preview.files) ? preview.files
    : preview.program ? [{ path: preview.program }] : [];
  const argv: string[] = Array.isArray(preview.argv) ? preview.argv.map(String) : [];
  const providerId = preview.provider_id ?? task?.payload?.provider_id;
  const revision = preview.provider_revision ?? task?.payload?.provider_revision;
  return <div data-testid="voice-command-card" style={{ margin: '3px 0 7px 12px', fontSize: 10, color: 'var(--ink-2)' }}>
    <div>kind: <span style={mono}>{side.toUpperCase()}</span> voice command provider</div>
    {providerId && <div>provider: <span style={mono}>{String(providerId)}</span> · revision {String(revision ?? '?')}</div>}
    <div style={{ marginTop: 2 }}>runs {files.length === 1 ? 'this file' : 'these files'}:</div>
    {files.map((f, i) => <div key={i} data-testid="voice-command-file" style={{ ...mono, marginLeft: 8, overflowWrap: 'anywhere' }}>
      {String(f?.path ?? '?')} · {bytes(f?.size)} · sha256 {short(f?.sha256)}
    </div>)}
    <div style={{ marginTop: 2 }}>argv:</div>
    <ol data-testid="voice-command-argv" start={0} style={{ ...mono, margin: '0 0 0 22px', padding: 0 }}>
      {argv.map((a, i) => <li key={i} style={{ overflowWrap: 'anywhere' }}>
        {PLACEHOLDERS.has(a) ? <span data-testid="voice-command-placeholder" style={{ color: 'var(--amber)' }}>{a} (filled in by the hub)</span> : a}
      </li>)}
    </ol>
    {preview.runs_as && <div style={{ marginTop: 2 }}>as user <span style={mono}>{String(preview.runs_as)}</span>
      {typeof preview.timeout_s === 'number' ? ` · stopped after ${preview.timeout_s}s` : ''}</div>}
    <div style={{ color: 'var(--red)', marginTop: 2 }}>runs on this machine as the hub user; cannot be undone by the hub</div>
    <div style={{ color: 'var(--ink-3)', marginTop: 2 }}>changing any of these files needs approving again · no edit here: ask again from Settings → Voice</div>
  </div>;
}
