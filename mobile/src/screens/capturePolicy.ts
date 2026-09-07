/* Capture inbox — the decisions the screen makes, as pure functions (T-0.26).
 *
 * Kept out of the .tsx on purpose: jest here is scoped to non-React logic
 * (`jest.config.js`), so anything living in a component can only ever be checked by
 * grepping its source. The judgements below are the ones worth testing for real —
 * what "capturing" means, what an export is allowed to be called, and what a file
 * lands as — so they live where a test can actually run them.
 */
import type { CaptureExport, CaptureStatus, CaptureSurface } from '../api/client';
import { CAPTURE_SURFACES } from '../api/client';

/** What the hub is actually doing, as one of four distinguishable facts. */
export type CaptureState = 'off' | 'no_surfaces' | 'recording' | 'unknown';

export function enabledSurfaces(status: CaptureStatus | null): CaptureSurface[] {
  if (!status) return [];
  return CAPTURE_SURFACES.filter((s) => status.surfaces[s]);
}

/** The distinction the UI exists to make.
 *
 * A surface can be switched on while the master switch is off — the hub then
 * captures **nothing**, and `status.surfaces.clipboard === true` on its own would
 * read to a person as "my clipboard is being recorded". These are three different
 * facts and they get three different words; `unknown` is the fourth, for before the
 * first fetch lands or after one fails, because a spinner that looks like "off" is
 * the most dangerous default a privacy surface can have.
 */
export function captureState(status: CaptureStatus | null): CaptureState {
  if (!status) return 'unknown';
  if (!status.enabled) return 'off';
  return enabledSurfaces(status).length > 0 ? 'recording' : 'no_surfaces';
}

export function captureStateLabel(state: CaptureState): string {
  switch (state) {
    case 'off': return 'Capture is OFF on the hub — nothing is being recorded.';
    case 'no_surfaces': return 'Capture is on, but no surface is opted in — nothing is being recorded.';
    case 'recording': return 'Capturing.';
    default: return 'Unknown — the hub has not answered yet.';
  }
}

/** True only for the state where records are actually accumulating. */
export function isRecording(status: CaptureStatus | null): boolean {
  return captureState(status) === 'recording';
}

/** Why a surface toggled on is still not recording, or '' when it is. */
export function surfaceCaveat(status: CaptureStatus | null): string {
  if (captureState(status) !== 'no_surfaces' && captureState(status) !== 'off') return '';
  const on = enabledSurfaces(status);
  if (!on.length) return '';
  return `${on.join(', ')} ${on.length === 1 ? 'is' : 'are'} opted in, but the hub's master switch is off.`;
}

function pad(n: number, width = 2): string {
  return String(Math.floor(Math.abs(n))).padStart(width, '0');
}

/** UTC stamp, because an export is a file that travels: a local-time name is
 *  ambiguous the moment it leaves the phone that wrote it. */
export function exportStamp(epochSeconds: number | null): string {
  if (epochSeconds === null || !Number.isFinite(epochSeconds)) return 'unstamped';
  const d = new Date(epochSeconds * 1000);
  if (Number.isNaN(d.getTime())) return 'unstamped';
  return `${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}`
    + `-${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}${pad(d.getUTCSeconds())}Z`;
}

/** The filename an export lands under. The surface is in the name because a
 *  filtered export and a full one are the same shape, and only the name survives
 *  into a file browser. */
export function exportFileName(envelope: Pick<CaptureExport, 'surface' | 'exported_at'>): string {
  const scope = envelope.surface && CAPTURE_SURFACES.includes(envelope.surface as CaptureSurface)
    ? envelope.surface
    : 'all';
  return `nerva-capture-${scope}-${exportStamp(envelope.exported_at)}.json`;
}

/** One line describing what a file actually contains — never "everything".
 *
 * A filtered export named without its filter is the way a partial record gets
 * mistaken for a complete one later, when nobody remembers which button was
 * pressed. So the scope is always stated, including when it is everything.
 */
export function describeExport(envelope: CaptureExport): string {
  const scope = envelope.surface ? `the ${envelope.surface} surface` : 'all surfaces';
  const n = envelope.count;
  return `${n} record${n === 1 ? '' : 's'} from ${scope}`
    + ' · previews only, already redacted on the hub';
}
