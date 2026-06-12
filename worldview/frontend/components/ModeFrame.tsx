"use client";

import { MODE_META, type UiMode } from "@/lib/uiMode";

// Mode signal #1 of 3 (spec §3.3): a 2px strip across the top of the whole app, tinted by the
// current mode, so the mode is readable from any corner of the screen at a glance.
export function ModeFrame({ uiMode }: { uiMode: UiMode }) {
  return (
    <div
      aria-hidden
      data-mode={uiMode}
      className={`pointer-events-none absolute inset-0 z-[60] border-t-2 transition-colors duration-200 motion-reduce:transition-none ${MODE_META[uiMode].frame}`}
    />
  );
}
