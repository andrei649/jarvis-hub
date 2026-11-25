/* What a request's kind does, in words (PHASE_B_PLAN.md §1.4, §5.4).

   A hub kind ('restart_service', 'toolrpc.terminal_run', …) becomes words only through this
   fixed table — never through generated copy. Each entry is a whole sentence in both languages
   ("Restarts a local service."), so no translated fragment is ever spliced into another
   sentence. A kind the table does not know is said as itself, an identifier in mono:
   "Runs a request of kind `calendar.sync`."

   Also here, as fixed lists read from the hub's own code:
     - money: tier 3 with an amount, or a kind policy.py classes as money (pay, payment,
       purchase, buy, transfer, invoice, checkout, withdraw, submit_order);
     - the kinds whose approval takes effect only in Auto (agents/core/autonomy/mode.py
       RECEIPT_NOTE, an owner decision): terminal commands, checkpoint operations, browser
       steps, provider and endpoint changes (agents/core/kernel/registry.py names them). */
import { defineStrings, fmt, pick, type Lang } from '../frame/strings';
import type { DocketTask } from './types';

const SENTENCES = {
  restart_service: ['Restarts a local service.', 'Repornește un serviciu local.'],
  delete_file: ['Deletes a file.', 'Șterge un fișier.'],
  'toolrpc.file_delete': ['Deletes a file.', 'Șterge un fișier.'],
  'toolrpc.file_write': ['Writes a file.', 'Scrie un fișier.'],
  'file.write': ['Writes a file.', 'Scrie un fișier.'],
  'toolrpc.terminal_run': ['Runs a command in a terminal on this machine.', 'Rulează o comandă în terminal, pe acest calculator.'],
  'terminal.exec': ['Runs a command in a terminal on this machine.', 'Rulează o comandă în terminal, pe acest calculator.'],
  'toolrpc.browser_run': ['Takes steps in a browser.', 'Face pași într-un browser.'],
  'browser.step': ['Takes a step in a browser.', 'Face un pas într-un browser.'],
  'toolrpc.desktop_run': ['Acts on this computer’s desktop.', 'Acționează pe desktopul acestui calculator.'],
  'desktop.step': ['Acts on this computer’s desktop.', 'Acționează pe desktopul acestui calculator.'],
  'toolrpc.speak': ['Speaks aloud in a room.', 'Vorbește cu voce tare într-o cameră.'],
  'toolrpc.image_generate': ['Generates an image.', 'Generează o imagine.'],
  'plugin.egress': ['Sends a request from a plugin to the internet.', 'Trimite o cerere de la un plugin către internet.'],
  'monitor.alert': ['Records a monitoring alert.', 'Înregistrează o alertă de monitorizare.'],
  'monitor.recovery': ['Records that a service recovered.', 'Înregistrează revenirea unui serviciu.'],
  draft_email: ['Drafts an email.', 'Redactează un e-mail.'],
  research_market: ['Researches a market.', 'Cercetează o piață.'],
  'channel.reply': ['Replies in a channel.', 'Răspunde pe un canal.'],
  'call.outbound': ['Places a phone call.', 'Inițiază un apel telefonic.'],
  payment: ['Makes a payment.', 'Face o plată.'],
  'settings.retention': ['Changes how long data is kept.', 'Schimbă cât timp se păstrează datele.'],
  'settings.voice_command': ['Adds a voice command.', 'Adaugă o comandă vocală.'],
  'checkpoint.restore': ['Restores a checkpoint.', 'Restaurează un punct de salvare.'],
  'checkpoint.maintenance': ['Maintains the checkpoints.', 'Întreține punctele de salvare.'],
  'provider.credential': ['Changes a provider credential.', 'Schimbă un credențial de furnizor.'],
  'provider.selection': ['Changes the model provider.', 'Schimbă furnizorul de modele.'],
  'provider.custom_endpoint': ['Changes a custom model endpoint.', 'Schimbă un endpoint de model personalizat.'],
  'permission.grant': ['Grants a permission.', 'Acordă o permisiune.'],
  'skill.install': ['Installs a skill.', 'Instalează o abilitate.'],
  'model.pull': ['Downloads a local model.', 'Descarcă un model local.'],
  'report.export': ['Exports the day report to a file.', 'Exportă raportul zilei într-un fișier.'],
  'goal.approve': ['Starts a night of work on a goal.', 'Pornește o noapte de lucru pentru un obiectiv.'],
  'hub.update': ['Updates the hub.', 'Actualizează hubul.'],
  'hub.restart': ['Restarts the hub.', 'Repornește hubul.'],
  'hooks.define': ['Activates a hook program.', 'Activează un program de tip hook.'],
  'note.write': ['Writes a note.', 'Scrie o notă.'],
  'comms.send': ['Sends a message.', 'Trimite un mesaj.'],
  'social.post': ['Publishes a post.', 'Publică o postare.'],
  'calendar.move': ['Moves a calendar event.', 'Mută un eveniment din calendar.'],
} as const;

type KindKey = keyof typeof SENTENCES;
const KEYS = Object.keys(SENTENCES) as KindKey[];
const column = (i: 0 | 1) => Object.fromEntries(KEYS.map((k) => [k, SENTENCES[k][i]])) as Record<KindKey, string>;

/** The kind sentences, plus the sentence for a kind the table does not know. */
export const KIND_STRINGS = defineStrings({
  en: { ...column(0), unknownKind: 'Runs a request of kind {kind}.', noKind: 'Runs a request the hub did not name.' },
  ro: { ...column(1), unknownKind: 'Rulează o cerere de tipul {kind}.', noKind: 'Rulează o cerere fără tip declarat.' },
});

export const KNOWN_KINDS: readonly string[] = KEYS;

/** The sentence for a kind, or null when the table does not know it (say it with unknownKind). */
export function kindSentence(kind: string | null | undefined, lang: Lang | string = 'en'): string | null {
  if (!kind || !Object.prototype.hasOwnProperty.call(SENTENCES, kind)) return null;
  return pick(KIND_STRINGS, lang)[kind as KindKey];
}

/** The unknown-kind sentence with its `{kind}` placeholder left for the caller to draw in mono,
 *  split into the text before and after it. */
export function unknownKindParts(lang: Lang | string = 'en'): [string, string] {
  const template = pick(KIND_STRINGS, lang).unknownKind;
  const at = template.indexOf('{kind}');
  return [template.slice(0, at), template.slice(at + '{kind}'.length)];
}

/** For a test or a plain-text caller: the whole sentence with the kind written in. */
export function kindWords(kind: string | null | undefined, lang: Lang | string = 'en'): string {
  if (!kind) return pick(KIND_STRINGS, lang).noKind;
  return kindSentence(kind, lang) ?? fmt(pick(KIND_STRINGS, lang).unknownKind, { kind });
}

// ---- fixed lists from the hub's code --------------------------------------------------------------

/** The words of a kind, lower-case ('toolrpc.file_delete' → toolrpc, file, delete). */
export function kindTokens(kind: unknown): string[] {
  return typeof kind === 'string' ? kind.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean) : [];
}

/** policy.py _MONEY_OR_IRREVERSIBLE's money words. */
const MONEY_WORDS = new Set(['pay', 'payment', 'payments', 'purchase', 'buy', 'transfer', 'invoice', 'checkout', 'withdraw']);

const DIGITS = /^\d+(?:\.\d+)?$/;

/** The amount a request carries, in digits ("4200", "12.5"), or null — also for a number
 *  JavaScript would write with an exponent (1e+21, 1e-7): that is not something to type. */
export function amountDigits(raw: unknown): string | null {
  if (typeof raw === 'number' && Number.isFinite(raw) && raw > 0) {
    const written = String(raw);
    return DIGITS.test(written) ? written : null;
  }
  if (typeof raw === 'string' && DIGITS.test(raw.trim()) && Number(raw) > 0) return raw.trim();
  return null;
}

/** Money (§5.4): tier 3 with an amount in the payload, or a money kind. */
export function isMoney(task: DocketTask): boolean {
  if (task.risk_tier !== 3) return false;
  const payload = task.payload as Record<string, unknown> | undefined;
  if (payload && typeof payload === 'object' && amountDigits(payload.amount) !== null) return true;
  if (typeof task.kind === 'string' && task.kind.toLowerCase().includes('submit_order')) return true;
  return kindTokens(task.kind).some((word) => MONEY_WORDS.has(word));
}

/** The kinds whose approval the kernel honours only in Auto (mode.py RECEIPT_NOTE). */
export function runsOnlyInAuto(kind: unknown): boolean {
  if (typeof kind !== 'string') return false;
  return kind === 'toolrpc.terminal_run' || kind === 'terminal.exec' || kind === 'toolrpc.browser_run'
    || kind.startsWith('browser.') || kind.startsWith('checkpoint.') || kind.startsWith('provider.');
}
