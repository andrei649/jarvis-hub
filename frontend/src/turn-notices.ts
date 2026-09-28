// H674 — what the owner should know beside a reply, carried by the /chat/stream end
// event (e.g. "the conversation summary was still being written, so this reply saw a
// shorter view of the conversation"). Shown as system lines under the reply; the server
// sends at most one per kind, and this side still refuses anything malformed or noisy.

export interface TurnNotice { code: string; text: string }

const MAX_NOTICES = 5;
const MAX_TEXT = 400;

export function noticesFrom(evt: unknown): TurnNotice[] {
  const raw = evt && typeof evt === 'object' ? (evt as { notices?: unknown }).notices : undefined;
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  const out: TurnNotice[] = [];
  for (const item of raw) {
    if (out.length >= MAX_NOTICES) break;
    if (!item) continue;       // a primitive destructures to undefined fields and is skipped below
    const { code, text } = item as { code?: unknown; text?: unknown };
    if (typeof code !== 'string' || typeof text !== 'string' || !text.trim() || seen.has(code)) continue;
    seen.add(code);
    out.push({ code, text: text.trim().slice(0, MAX_TEXT) });
  }
  return out;
}

export function noticeMessages(evt: unknown, ts: string) {
  return noticesFrom(evt).map((n) => ({
    role: 'agent', who: 'system', role_label: '', ts, text: 'ℹ ' + n.text, notice: n.code,
  }));
}
