/* A daily column chart in plain SVG (no chart library: the bundle adds no runtime dependency).

   One series per chart — questions and report runs are shown as small multiples, never on a
   shared or dual axis. Marks follow the house specs: columns at most 24 px wide with a 2 px gap,
   4 px rounded data ends and a square baseline, hairline recessive grid, clean y ticks. The chart
   is measured to its container (crisp text at any width). Hover a day, or focus the chart and
   use the arrow keys, to read its value; the same numbers are always available in the data
   table below the charts, so the readout never gates information. */
import React, { useEffect, useId, useRef, useState } from 'react';
import type { UsageDay } from '../../api/types';
import { useI18n } from '../../i18n';

const HEIGHT = 196;
const MARGIN = { top: 14, right: 8, bottom: 26, left: 40 };
const MAX_BAR = 24;
const GAP = 2;
const RADIUS = 4;

/** Round tick steps (1, 2, 5 × 10^n) and the axis maximum they reach. The series are counts,
    so a step is never below 1: a day with one run must not draw a "0.5 runs" gridline. */
export function niceTicks(max: number, target = 3): number[] {
  if (max <= 0) return [0, 1];
  const rough = Math.max(1, max / target);
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 5, 10].map((m) => m * magnitude).find((s) => s >= rough) ?? 10 * magnitude;
  const top = Math.max(step, Math.ceil(max / step) * step);
  const ticks: number[] = [];
  for (let v = 0; v <= top + step / 2; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
  return ticks;
}

/** A column with rounded top corners and a square base. */
function columnPath(x: number, base: number, width: number, height: number): string {
  const r = Math.min(RADIUS, width / 2, height);
  const top = base - height;
  return `M${x},${base}V${top + r}Q${x},${top} ${x + r},${top}H${x + width - r}Q${x + width},${top} ${x + width},${top + r}V${base}Z`;
}

function useWidth(ref: React.RefObject<HTMLDivElement | null>, fallback: number): number {
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const node = ref.current;
    if (!node || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(([entry]) => {
      const next = Math.round(entry.contentRect.width);
      if (next > 0) setWidth(next);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

export interface DailyBarChartProps {
  title: string;
  days: UsageDay[];
  value: (day: UsageDay) => number;
  /** "{count} questions" style text for one day's value (plural-aware). */
  describe: (count: number) => string;
}

export function DailyBarChart({ title, days, value, describe }: DailyBarChartProps) {
  const { t, fmt } = useI18n();
  const wrapper = useRef<HTMLDivElement>(null);
  const width = useWidth(wrapper, 640);
  const [active, setActive] = useState<number | null>(null);
  const id = useId().replace(/:/g, '');

  const values = days.map(value);
  const total = values.reduce((a, b) => a + b, 0);
  const ticks = niceTicks(Math.max(0, ...values));
  const top = ticks[ticks.length - 1];
  const plotW = Math.max(40, width - MARGIN.left - MARGIN.right);
  const plotH = HEIGHT - MARGIN.top - MARGIN.bottom;
  const base = MARGIN.top + plotH;
  const band = days.length ? plotW / days.length : plotW;
  const barW = Math.max(1, Math.min(MAX_BAR, band - GAP));
  const y = (v: number) => base - (v / top) * plotH;
  const labelIndexes = days.length > 2 ? [0, Math.floor((days.length - 1) / 2), days.length - 1] : days.map((_, i) => i);

  const onKey = (event: React.KeyboardEvent) => {
    if (!days.length) return;
    const current = active ?? days.length - 1;
    const moves: Record<string, number> = { ArrowLeft: current - 1, ArrowRight: current + 1, Home: 0, End: days.length - 1 };
    if (!(event.key in moves)) return;
    event.preventDefault();
    setActive(Math.min(days.length - 1, Math.max(0, moves[event.key])));
  };

  const activeDay = active !== null ? days[active] : null;
  const readout = activeDay ? `${fmt.day(activeDay.date)}: ${describe(values[active as number])}` : '';
  const tipLeft = active !== null ? Math.min(Math.max(MARGIN.left + band * active + band / 2, 60), width - 60) : 0;
  // Just above the active column, so the readout never hides the mark it describes.
  const tipTop = active !== null ? y(values[active]) - 6 : 0;

  return (
    <figure className="ws-chart">
      <figcaption className="ws-chart__head">
        <span className="ws-chart__title">{title}</span>
        <span className="ws-chart__total">{describe(total)}</span>
      </figcaption>
      <div
        ref={wrapper}
        className="ws-chart__plot"
        tabIndex={days.length ? 0 : -1}
        role="group"
        aria-label={t('usage.chart.label', { title, summary: describe(total) })}
        aria-describedby={`${id}-help`}
        onKeyDown={onKey}
        onFocus={() => setActive((a) => a ?? (days.length ? days.length - 1 : null))}
        onBlur={() => setActive(null)}
        onPointerLeave={() => setActive(null)}
      >
        <span id={`${id}-help`} className="ws-sr-only">{t('usage.chart.keys')}</span>
        <svg width={width} height={HEIGHT} aria-hidden="true" focusable="false">
          {ticks.map((tick) => (
            <g key={tick}>
              <line className="ws-chart__grid" x1={MARGIN.left} x2={MARGIN.left + plotW} y1={y(tick)} y2={y(tick)} />
              <text className="ws-chart__tick" x={MARGIN.left - 8} y={y(tick)} dy="0.32em" textAnchor="end">{fmt.number(tick, { notation: 'compact' })}</text>
            </g>
          ))}
          {days.map((day, i) => {
            const v = values[i];
            const h = (v / top) * plotH;
            const x = MARGIN.left + band * i + (band - barW) / 2;
            return (
              <g key={day.date} className={active === i ? 'is-active' : undefined}>
                {h > 0 && <path className="ws-chart__bar" d={columnPath(x, base, barW, h)} />}
                <rect className="ws-chart__hit" x={MARGIN.left + band * i} y={MARGIN.top} width={band} height={plotH} onPointerEnter={() => setActive(i)} />
              </g>
            );
          })}
          <line className="ws-chart__axis" x1={MARGIN.left} x2={MARGIN.left + plotW} y1={base} y2={base} />
          {labelIndexes.map((i) => (
            <text
              key={days[i].date} className="ws-chart__tick" y={HEIGHT - 6}
              x={MARGIN.left + band * i + band / 2} textAnchor={i === 0 ? 'start' : i === days.length - 1 ? 'end' : 'middle'}
            >
              {fmt.day(days[i].date)}
            </text>
          ))}
        </svg>
        {activeDay && (
          <div className="ws-chart__tip" style={{ left: tipLeft, top: tipTop }} aria-hidden="true">
            <strong>{fmt.number(values[active as number])}</strong>
            <span>{fmt.day(activeDay.date)}</span>
          </div>
        )}
        <span className="ws-sr-only" aria-live="polite">{readout}</span>
      </div>
      {total === 0 && <p className="ws-chart__empty">{t('usage.chart.none')}</p>}
    </figure>
  );
}
