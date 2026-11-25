/* This machine: RAM, VRAM, GPU load and latency, from /status `sys` (PHASE_B_PLAN.md §4.3, §5.2).

   The hub's _sys_info() fills every field with a 0 when its probe failed ("0 of 0 GB"), so a 0
   total is not a reading: a figure with no total is Unknown ("not reported"), never 0%. The same
   fill makes a 0 used or a 0 load unreliable: the probes do not always measure every field
   (Apple reports only the total, AMD no load), so a 0 next to a total is Unknown too, never a
   live 0%. GPU load is also unknown while VRAM total is 0. Latency p50 is never measured by the hub
   and is always Unknown — not measured, whatever `sys.latency` holds.

   Pure: `sys` and the hub's reading state in, four MachineReading out, with the detail line
   ("36 of 192 GB") in one language. Labels: machineLabel(). */
import { defineStrings, fmt, pick, type Lang } from '../frame/strings';
import type { StatusSys } from '../api/types';
import type { MachineReading, ReadingReason, ReadingState } from './types';

export const MACHINE_STRINGS = defineStrings({
  en: {
    ram: 'RAM',
    vram: 'VRAM',
    gpu: 'GPU load',
    latency: 'Latency p50',
    gbOf: '{used} of {total} GB',
    unknownNotMeasured: 'Unknown — not measured',
    unknownNotReported: 'Unknown — not reported',
    unknownChecking: 'Checking…',
    unknownOffline: 'Unknown — the hub is not answering',
    demoSample: 'Demo sample',
  },
  ro: {
    ram: 'RAM',
    vram: 'VRAM',
    gpu: 'Încărcare GPU',
    latency: 'Latență p50',
    gbOf: '{used} din {total} GB',
    unknownNotMeasured: 'Necunoscut — nemăsurat',
    unknownNotReported: 'Necunoscut — neraportat',
    unknownChecking: 'Se verifică…',
    unknownOffline: 'Necunoscut — hubul nu răspunde',
    demoSample: 'Mostră demo',
  },
});

export type MachineKey = MachineReading['key'];
export const MACHINE_KEYS: readonly MachineKey[] = ['ram', 'vram', 'gpu', 'latency'];

export function machineLabel(key: MachineKey, lang: Lang | string = 'en'): string {
  return pick(MACHINE_STRINGS, lang)[key];
}

export interface MachineInput {
  /** /status `sys`; null when /status did not answer or did not send it. */
  readonly sys: StatusSys | null | undefined;
  /** The hub snapshot's state as hubReading() gives it: live, stale, offline, demo, unknown. */
  readonly hubState: ReadingState;
  /** Why the hub is unknown ('checking' before the first answer). */
  readonly hubReason?: ReadingReason;
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : null);
const clampPct = (v: number): number => Math.max(0, Math.min(100, Math.round(v)));
const gb = (v: number): string => (Number.isInteger(v) ? String(v) : v.toFixed(1));

/** The four readings, in the foot's and the register's order. */
export function machineReadings(input: MachineInput, langIn: Lang | string = 'en'): MachineReading[] {
  const lang: Lang = langIn === 'ro' ? 'ro' : 'en';
  const s = pick(MACHINE_STRINGS, lang);
  const latency: MachineReading = { key: 'latency', state: 'unknown', reason: 'not-measured', pct: null, unit: 'ms' };
  const none = (state: ReadingState, reason: ReadingReason | undefined): MachineReading[] =>
    (['ram', 'vram', 'gpu'] as const).map((key): MachineReading => ({
      key, state, pct: null, ...(reason ? { reason } : {}), unit: key === 'gpu' ? '%' : 'GB',
    })).concat(latency);

  const { sys, hubState } = input;
  if (hubState === 'demo') return none('demo', undefined);
  if (!sys) {
    if (hubState === 'offline') return none('offline', 'network');
    if (hubState === 'unknown' && input.hubReason === 'checking') return none('unknown', 'checking');
    return none('unknown', 'not-reported');
  }

  const state: ReadingState = hubState === 'stale' ? 'stale' : 'live';
  const known = (used: unknown, total: unknown, key: 'ram' | 'vram'): MachineReading => {
    const u = num(used);
    const t = num(total);
    // A 0 used next to a measured total is the hub's default, not a reading: _sys_info() starts
    // every field at 0 and some probes leave it there (Apple: used and load are None).
    if (u === null || t === null || t <= 0 || u === 0) return { key, state: 'unknown', reason: 'not-reported', pct: null, used: null, total: null, unit: 'GB' };
    return {
      key, state, pct: clampPct((u / t) * 100), used: u, total: t, unit: 'GB',
      detail: fmt(s.gbOf, { used: gb(u), total: gb(t) }),
    };
  };
  const ram = known(sys.ram_used, sys.ram_total, 'ram');
  const vram = known(sys.vram_used, sys.vram_total, 'vram');
  const load = num(sys.gpu_load);
  const gpuName = typeof sys.gpu === 'string' && sys.gpu.trim() && sys.gpu.trim().toLowerCase() !== 'unknown' && sys.gpu.trim().toLowerCase() !== 'none'
    ? sys.gpu.trim().slice(0, 80) : null;
  const gpu: MachineReading = vram.state === 'unknown' || load === null || load === 0
    ? { key: 'gpu', state: 'unknown', reason: 'not-reported', pct: null, unit: '%' }
    : { key: 'gpu', state, pct: clampPct(load), unit: '%', ...(gpuName ? { detail: gpuName } : {}) };
  return [ram, vram, gpu, latency];
}

/** One reading as a short line: "19%", or the words for why it is unknown. */
export function machineValue(reading: MachineReading, langIn: Lang | string = 'en'): string {
  const lang: Lang = langIn === 'ro' ? 'ro' : 'en';
  const s = pick(MACHINE_STRINGS, lang);
  if (reading.pct !== null && (reading.state === 'live' || reading.state === 'stale')) return `${reading.pct}%`;
  if (reading.state === 'demo') return s.demoSample;
  if (reading.reason === 'not-measured') return s.unknownNotMeasured;
  if (reading.reason === 'checking') return s.unknownChecking;
  if (reading.state === 'offline') return s.unknownOffline;
  return s.unknownNotReported;
}
