import { cx, esc } from "./dom";

// The shared panel anatomy (spec §1.4): surface + line border + blur, a mono micro-title header
// with right-aligned meta, optional collapse / close. Every rail panel composes this so the
// chrome can never drift between panels.

export interface PanelOptions {
  title: string;
  meta?: string;
  /** "alert" tints the border red for alert-context panels (e.g. dark-vessel inspector). */
  tone?: "default" | "alert";
  /** `data-act` name for the collapse toggle; omit for a non-collapsible panel. */
  collapseAction?: string;
  open?: boolean;
  /** `data-act` name for an ✕ close button in the header. */
  closeAction?: string;
  /** Extra classes for the scrollable body (e.g. a max-height). */
  bodyClass?: string;
}

const HEADER_BUTTON =
  "px-0.5 text-[10px] text-ink/40 hover:text-signal-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal";

export function panel(options: PanelOptions, body: string): string {
  const open = options.open ?? true;
  const border = options.tone === "alert" ? "border-red/30" : "border-line";
  const titleTone = options.tone === "alert" ? "text-red" : "text-signal-light";
  const metaHtml =
    options.meta != null
      ? `<span class="ml-auto font-mono text-[8.5px] tracking-[.06em] text-ink/40">${esc(options.meta)}</span>`
      : "";
  const collapse = options.collapseAction
    ? `<button data-act="${options.collapseAction}" aria-expanded="${open}" aria-label="${open ? "Collapse" : "Expand"} ${esc(options.title)}" class="${cx(options.meta == null && "ml-auto", HEADER_BUTTON)}">${open ? "▾" : "▸"}</button>`
    : "";
  const close = options.closeAction
    ? `<button data-act="${options.closeAction}" aria-label="Close ${esc(options.title)}" class="${cx(options.meta == null && !options.collapseAction && "ml-auto", HEADER_BUTTON)}">✕</button>`
    : "";

  return `
    <div class="pointer-events-auto flex min-h-0 flex-col rounded-md border ${border} bg-surface backdrop-blur-[10px]">
      <div class="flex flex-none items-center gap-2 border-b border-line-2 px-3 py-2">
        <span class="font-mono text-[9px] uppercase tracking-[.16em] ${titleTone}">${esc(options.title)}</span>
        ${metaHtml}${collapse}${close}
      </div>
      ${open ? `<div class="min-h-0 overflow-y-auto overflow-x-hidden px-3 py-2.5 ${options.bodyClass ?? ""}">${body}</div>` : ""}
    </div>`;
}

/** The button styling shared by the app bar and panel actions. */
export const BAR_BUTTON =
  "rounded-md border border-line px-2.5 py-1.5 font-mono text-[9.5px] tracking-[.08em] text-ink/65 transition-colors hover:border-signal-dim hover:text-signal-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal";

export const MINI_BUTTON =
  "rounded-md border border-line px-2.5 py-1.5 font-mono text-[9px] tracking-[.04em] text-ink/65 transition-colors hover:border-signal-dim hover:text-signal-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal disabled:opacity-35 disabled:hover:border-line disabled:hover:text-ink/65";

export const TEXT_INPUT =
  "min-w-0 flex-1 rounded-md border border-line bg-void-2 px-2 py-1.5 font-mono text-[10px] text-ink placeholder:text-ink/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal";
