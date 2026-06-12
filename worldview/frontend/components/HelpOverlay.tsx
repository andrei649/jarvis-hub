"use client";

import { useEffect, useState } from "react";

const SHORTCUTS: [string, string][] = [
  ["Space", "Play / pause playback"],
  ["L", "Jump to LIVE (real-time)"],
  ["← / →", "Scrub ±30 s (switches to historical)"],
  ["Esc", "Clear selected entity / close this help"],
  ["?", "Show / hide this help"],
];

/**
 * Keyboard-shortcuts help overlay (UX review P2#7 — the shortcuts existed but were
 * undiscoverable). Opens with `?` or the corner button; closes with Esc / ? / click-away.
 */
export function HelpOverlay() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      if (e.key === "?") setOpen((o) => !o);
      else if (e.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        title="Keyboard shortcuts (?)"
        aria-label="Keyboard shortcuts"
        className="pointer-events-auto absolute bottom-32 right-4 z-10 h-7 w-7 rounded-full bg-cockpit/85 text-sm font-semibold text-white/60 backdrop-blur hover:text-signal"
      >
        ?
      </button>

      {open && (
        <div
          className="absolute inset-0 z-30 flex items-center justify-center bg-black/40"
          onClick={() => setOpen(false)}
        >
          <div
            role="dialog"
            aria-label="Keyboard shortcuts"
            onClick={(e) => e.stopPropagation()}
            className="w-80 rounded-xl border border-white/15 bg-cockpit/95 p-5 text-sm shadow-2xl backdrop-blur-md"
          >
            <div className="mb-3 flex items-center justify-between">
              <span className="font-semibold text-signal">Keyboard shortcuts</span>
              <button
                onClick={() => setOpen(false)}
                className="rounded bg-white/10 px-1.5 leading-5 text-white/70 hover:bg-white/20"
                aria-label="Close"
              >
                ×
              </button>
            </div>
            <dl className="space-y-1.5">
              {SHORTCUTS.map(([key, desc]) => (
                <div key={key} className="flex items-baseline justify-between gap-4">
                  <dt>
                    <kbd className="rounded bg-white/15 px-1.5 py-0.5 font-mono text-xs text-white/90">
                      {key}
                    </kbd>
                  </dt>
                  <dd className="text-right text-white/70">{desc}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      )}
    </>
  );
}
