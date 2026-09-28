/* H247 — the HUD asks the hub before it opens the microphone.

   The hub keeps one lease per device (agents/core/voice/mic.py): a browser on the hub's
   own machine shares the hub's microphone, so its hands-free loop and the hub's wake-word
   listener cannot both open it. Before the loop takes the microphone it arms a lease as
   `hud:<this tab>`; while it runs it renews the lease (a lease not renewed for 45 s
   lapses); when it stops it releases it.

   Only the hub's own refusal stops the loop: 403 (the owner has not allowed the HUD to
   open a microphone, voice.mic_surfaces) or 409 (another surface on this device holds it,
   named, and the owner may take it over). A hub that cannot answer — an older one without
   the route, or one out of reach — does not; its speech-to-text would fail anyway. */
import { appUrl } from './base-path';
import { getToken } from './api/client';

export const MIC_ARM = '/api/voice/mic/arm';
export const MIC_STOP = '/api/voice/mic/stop';
export const RENEW_MS = 20_000;
const CLIENT_KEY = 'hud.mic_client';

let fallbackId = '';

/** This tab's lease id: kept for the tab's life, new in a new tab. */
export function micClientId(): string {
  try {
    const kept = sessionStorage.getItem(CLIENT_KEY);
    if (kept && /^[A-Za-z0-9-]{1,64}$/.test(kept)) return kept;
    const made = Math.random().toString(36).slice(2, 12);
    sessionStorage.setItem(CLIENT_KEY, made);
    return made;
  } catch {
    if (!fallbackId) fallbackId = Math.random().toString(36).slice(2, 12);
    return fallbackId;
  }
}

export type MicLease = { ok: true } | { ok: false; code: 'not_consented' | 'mic_busy'; holder?: string; message: string };

function headers(): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': 'application/json' };
  const t = getToken();
  if (t) h['X-User-Token'] = t;
  return h;
}

/** Arm (or renew) this tab's lease. `ok` unless the hub refused it. */
export async function armMic(takeOver = false): Promise<MicLease> {
  let res: any;
  try {
    res = await fetch(appUrl(MIC_ARM), {
      method: 'POST', headers: headers(),
      body: JSON.stringify({ surface: 'hud', client: micClientId(), take_over: takeOver }),
    });
  } catch {
    return { ok: true };                                    // the hub is out of reach: STT will say so
  }
  if (!res || (res.status !== 403 && res.status !== 409)) return { ok: true };
  let body: any = {};
  try { body = await res.json(); } catch { /* keep the status */ }
  if (res.status === 403) {
    return { ok: false, code: 'not_consented',
      message: 'The HUD may not open a microphone: the owner has not allowed it (Settings → voice → mic_surfaces).' };
  }
  const holder = String(body?.holder?.surface || 'another surface');
  return { ok: false, code: 'mic_busy', holder, message: `The microphone is held by ${holder}.` };
}

/** Release this tab's lease (best effort: a lapsed lease is released anyway). */
export function releaseMic(): void {
  try {
    fetch(appUrl(MIC_STOP), { method: 'POST', headers: headers(), body: JSON.stringify({ surface: `hud:${micClientId()}` }) })
      .catch(() => {});
  } catch { /* ignore */ }
}
