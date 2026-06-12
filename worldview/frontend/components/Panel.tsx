"use client";

import { useState, type ReactNode } from "react";

// The shared panel anatomy (spec §1.4): surface + line border + blur, a mono micro-title
// header with right-aligned meta, optional collapse. Every rail panel composes this so the
// chrome can never drift between panels.

export function Panel({
  title,
  meta,
  tone = "default",
  collapsible = false,
  defaultOpen = true,
  onClose,
  maxBodyClass,
  children,
}: {
  title: string;
  meta?: ReactNode;
  /** "alert" tints the border red for alert-context panels (e.g. dark-vessel inspector). */
  tone?: "default" | "alert";
  collapsible?: boolean;
  defaultOpen?: boolean;
  /** Renders an ✕ in the header instead of a collapse chevron. */
  onClose?: () => void;
  /** Extra classes for the scrollable body (e.g. a max-height). */
  maxBodyClass?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const border = tone === "alert" ? "border-red/30" : "border-line";
  return (
    <div
      className={`pointer-events-auto flex min-h-0 flex-col rounded-md border ${border} bg-surface backdrop-blur-[10px]`}
    >
      <div className="flex flex-none items-center gap-2 border-b border-line-2 px-3 py-2">
        <span
          className={`font-mono text-[9px] uppercase tracking-[.16em] ${
            tone === "alert" ? "text-red" : "text-signal-light"
          }`}
        >
          {title}
        </span>
        {meta != null && (
          <span className="ml-auto font-mono text-[8.5px] tracking-[.06em] text-ink/40">
            {meta}
          </span>
        )}
        {collapsible && (
          <button
            onClick={() => setOpen(!open)}
            aria-label={open ? `Collapse ${title}` : `Expand ${title}`}
            aria-expanded={open}
            className={`${meta == null ? "ml-auto" : ""} px-0.5 text-[10px] text-ink/40 hover:text-signal-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal`}
          >
            {open ? "▾" : "▸"}
          </button>
        )}
        {onClose && (
          <button
            onClick={onClose}
            aria-label={`Close ${title}`}
            className={`${meta == null && !collapsible ? "ml-auto" : ""} px-0.5 text-[10px] text-ink/40 hover:text-signal-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal`}
          >
            ✕
          </button>
        )}
      </div>
      {(!collapsible || open) && (
        <div className={`min-h-0 overflow-y-auto overflow-x-hidden px-3 py-2.5 ${maxBodyClass ?? ""}`}>
          {children}
        </div>
      )}
    </div>
  );
}
