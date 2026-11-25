/* This machine (xl only, PHASE_B_PLAN.md §5.2): RAM, VRAM, GPU load and latency from /status.sys.
   A figure with no total is "Unknown — not reported", never 0%; latency is always "Unknown — not
   measured" (the hub never fills it). Meters are decoration beside the figure. */
import React from 'react';
import { Mark, SecHead, SourceLabel } from '../../frame/kit';
import { pick, type Lang } from '../../frame/strings';
import { MACHINE_KEYS, machineLabel, machineValue } from '../../signals/machine';
import type { MachineReading, Reading } from '../../signals/types';
import { DAY_STRINGS } from './strings';
import './day.css';

export interface ThisMachineProps {
  readings: readonly MachineReading[];
  /** The hub as a reading: the section's source label. */
  hubState: Reading<null>;
  lang: Lang;
}

export function ThisMachine({ readings, hubState, lang }: ThisMachineProps) {
  const s = pick(DAY_STRINGS, lang);
  const byKey = new Map(readings.map((r) => [r.key, r]));
  return (
    <section className="n-day__block" aria-labelledby="n-day-machine" data-day-block="machine">
      <SecHead title={<span id="n-day-machine">{s.machine}</span>} aside={<SourceLabel reading={hubState} lang={lang} />} />
      <dl className="n-machine">
        {MACHINE_KEYS.map((key) => {
          const r = byKey.get(key);
          if (!r) return null;
          const known = r.pct !== null && (r.state === 'live' || r.state === 'stale');
          const value = machineValue(r, lang);
          return (
            <div key={key} className="n-machine__row" data-machine={key} data-machine-state={r.state}>
              <dt>{machineLabel(key, lang)}</dt>
              {known ? (
                <>
                  <dd className="n-machine__num">{value}</dd>
                  <dd className="n-machine__bar">
                    <span className="n-meter n-machine__meter" aria-hidden="true"><span className="n-meter__track"><span className="n-meter__fill" style={{ width: `${r.pct}%` }} /></span></span>
                  </dd>
                  <dd className="n-machine__detail">{r.detail ?? ''}</dd>
                </>
              ) : (
                <>
                  <dd className="n-machine__num" aria-hidden="true">—</dd>
                  <dd className="n-machine__bar"><Mark kind="unknown" size="sm" /></dd>
                  <dd className="n-machine__detail">{value}</dd>
                </>
              )}
            </div>
          );
        })}
      </dl>
    </section>
  );
}
