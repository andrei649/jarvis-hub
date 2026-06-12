"use client";

import { useEffect, useRef } from "react";
import { useTimelineStore } from "@/lib/store/useTimelineStore";
import { SHORTCUTS } from "@/lib/shortcuts";

/**
 * Keyboard-shortcuts overlay (spec §4). Opened from the app bar `?` button or the `?` key
 * (handled in useKeyboardShortcuts, which also routes Esc here first). Focus moves into the
 * dialog on open and is trapped until it closes; click-away closes.
 */
export function HelpOverlay() {
  const open = useTimelineStore((s) => s.helpOpen);
  const setOpen = useTimelineStore((s) => s.setHelpOpen);
  const cardRef = useRef<HTMLDivElement | null>(null);

  // Focus trap: focus the dialog on open; keep Tab cycling inside it.
  useEffect(() => {
    if (!open) return;
    const card = cardRef.current;
    card?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Tab" || !card) return;
      const focusables = card.querySelectorAll<HTMLElement>("button, [href], [tabindex]");
      if (focusables.length === 0) return;
      const first = focusables[0]!;
      const last = focusables[focusables.length - 1]!;
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="absolute inset-0 z-[80] flex items-center justify-center bg-void/80 backdrop-blur-[6px]"
      onClick={() => setOpen(false)}
    >
      <div
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-label="Keyboard shortcuts"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="w-[520px] max-w-[92vw] rounded-[10px] border border-line bg-surface-2 p-8 outline-none"
      >
        <div className="text-[21px] font-semibold tracking-[.01em]">Keyboard</div>
        <div className="mt-3.5 grid grid-cols-2 gap-x-6 gap-y-1">
          {SHORTCUTS.map(([key, label]) => (
            <div
              key={key}
              className="flex items-center justify-between border-b border-line-2 py-1.5"
            >
              <span className="text-[12px] text-ink/65">{label}</span>
              <kbd>{key}</kbd>
            </div>
          ))}
        </div>
        <div className="mt-4 flex items-center justify-between text-[11px] text-ink/40">
          <span>Esc or click anywhere to close.</span>
          <button
            onClick={() => setOpen(false)}
            className="rounded-md border border-line px-3 py-1 font-mono text-[9.5px] tracking-[.08em] text-ink/65 hover:border-signal-dim hover:text-signal-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal"
          >
            CLOSE
          </button>
        </div>
      </div>
    </div>
  );
}
