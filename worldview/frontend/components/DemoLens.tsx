"use client";

// The demo lens (spec §5.2): the ONE restrained cinematic allowance — a 2.2% scanline
// screen-blend + soft vignette for the tour/demo journey. Clearly cosmetic, dismissable from
// its chip, hidden entirely under prefers-reduced-motion (globals.css), never on by default,
// and never rendered into exports (it's a DOM overlay, not part of the WebGL canvas).

export function DemoLens({ onOff }: { onOff: () => void }) {
  return (
    <>
      <div className="wv-lens" aria-hidden />
      <div className="absolute bottom-[120px] left-1/2 z-[56] flex -translate-x-1/2 items-center gap-2.5 rounded-[14px] border border-signal-dim bg-surface-2 px-3.5 py-1.5 font-mono text-[9px] tracking-[.14em] text-signal-light">
        LENS · MONO GRADE
        <button
          onClick={onOff}
          className="text-ink/40 hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal"
        >
          ✕ OFF
        </button>
      </div>
    </>
  );
}
