import { SHORTCUTS } from "@/lib/shortcuts";
import { MODE_META, type UiMode } from "@/lib/uiMode";
import { timelineStore } from "@/lib/store/timelineStore";
import type { BasemapChoice } from "@/globe/basemap";
import { esc, mount, shortClock, type Surface } from "./dom";
import { BAR_BUTTON } from "./panel";

// The stage overlays: the mode frame, the arrival banner, the keyboard help, the tour chip, the
// demo lens and the basemap status line. Small surfaces, one file — each is a few lines of DOM
// over the same store the rest of the HUD reads.

/** Mode signal #1 of 3 (spec §3.3): a 2px strip across the top, tinted by the current mode. */
export function createModeFrame(host: HTMLElement, uiMode: () => UiMode): Surface {
  return mount(host, {
    render() {
      const mode = uiMode();
      return `<div aria-hidden="true" data-mode="${mode}" class="pointer-events-none absolute inset-0 z-[60] border-t-2 transition-colors duration-200 motion-reduce:transition-none ${MODE_META[mode].frame}"></div>`;
    },
  });
}

/**
 * The arrival moment (spec §5.1): landing from a JARVIS/Argus digest deep link, the session
 * opens with the camera pre-positioned, the replay window armed, the entity selected — and this
 * banner explaining where you came from, with the one action that matters.
 */
export function createArrivalBanner(host: HTMLElement): Surface {
  return mount(host, {
    actions: {
      replay: () => timelineStore.getState().setReplaying(true),
      dismiss: () => timelineStore.getState().setArrival(null),
    },
    render() {
      const arrival = timelineStore.getState().arrival;
      if (!arrival) return "";
      return `
        <div role="status" class="wv-arrive absolute left-1/2 top-[64px] z-30 flex -translate-x-1/2 items-center gap-3 rounded-lg border border-red/40 bg-surface-2 px-4 py-2.5 backdrop-blur-[10px]">
          <span class="flex items-center gap-1.5 font-mono text-[9px] tracking-[.12em] text-violet">◈ ${esc(arrival.agent)} · VIA JARVIS DIGEST</span>
          ${arrival.entity ? `<span class="text-[12px] text-ink">${esc(arrival.entity.layer.toUpperCase())} · ${esc(arrival.entity.id)}</span>` : ""}
          <span class="font-mono text-[9.5px] text-ink/40">window ${shortClock(arrival.window.from)} → ${shortClock(arrival.window.to)} pre-set</span>
          <button data-act="replay" class="rounded-md border border-red/45 bg-red/5 px-2.5 py-1 font-mono text-[9px] tracking-[.06em] text-red hover:bg-red/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal">▶ REPLAY THE GAP</button>
          <button data-act="dismiss" class="rounded-md border border-line px-2.5 py-1 font-mono text-[9px] tracking-[.06em] text-ink/65 hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal">DISMISS</button>
        </div>`;
    },
  });
}

/**
 * Keyboard-shortcuts overlay (spec §4). Opened from the app bar `?` button or the `?` key
 * (Esc routes here first). Focus moves into the dialog on open and is trapped until it closes;
 * click-away closes.
 */
export function createHelpOverlay(host: HTMLElement): Surface {
  const surface = mount(host, {
    actions: {
      close: () => timelineStore.getState().setHelpOpen(false),
      stop: (e) => e.stopPropagation(),
    },
    render() {
      if (!timelineStore.getState().helpOpen) return "";
      const rows = SHORTCUTS.map(
        ([key, label]) => `
          <div class="flex items-center justify-between border-b border-line-2 py-1.5">
            <span class="text-[12px] text-ink/65">${esc(label)}</span>
            <kbd>${esc(key)}</kbd>
          </div>`,
      ).join("");
      return `
        <div data-act="close" class="absolute inset-0 z-[80] flex items-center justify-center bg-void/80 backdrop-blur-[6px]">
          <div data-act="stop" role="dialog" aria-modal="true" aria-label="Keyboard shortcuts" tabindex="-1"
            class="w-[520px] max-w-[92vw] rounded-[10px] border border-line bg-surface-2 p-8 outline-none">
            <div class="text-[21px] font-semibold tracking-[.01em]">Keyboard</div>
            <div class="mt-3.5 grid grid-cols-2 gap-x-6 gap-y-1">${rows}</div>
            <div class="mt-4 flex items-center justify-between text-[11px] text-ink/40">
              <span>Esc or click anywhere to close.</span>
              <button data-act="close" class="${BAR_BUTTON}">CLOSE</button>
            </div>
          </div>
        </div>`;
    },
  });

  // Focus trap: focus the dialog on open, keep Tab cycling inside it.
  function onKey(e: KeyboardEvent) {
    if (e.key !== "Tab" || !timelineStore.getState().helpOpen) return;
    const card = host.querySelector<HTMLElement>('[role="dialog"]');
    if (!card) return;
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

  let wasOpen = false;
  const unsubscribe = timelineStore.subscribe((state) => {
    if (state.helpOpen && !wasOpen) {
      requestAnimationFrame(() => host.querySelector<HTMLElement>('[role="dialog"]')?.focus());
    }
    wasOpen = state.helpOpen;
  });

  return {
    update: surface.update,
    destroy() {
      window.removeEventListener("keydown", onKey);
      unsubscribe();
      surface.destroy();
    },
  };
}

export interface StageOverlayContext {
  uiMode: () => UiMode;
  lens: () => boolean;
  setLens: (on: boolean) => void;
  tourLabel: () => string;
  basemap: BasemapChoice;
}

/**
 * The stage's non-panel chrome: the tour waypoint chip (the only thing allowed top-center, and
 * only mid-tour), the DEMO watermark (a synthetic feed is identifiable from any screenshot),
 * the basemap status line, and the demo lens — one restrained scanline grade, offered only on
 * the tour/demo journey, dismissable, never on by default (spec §5.2).
 */
export function createStageOverlays(host: HTMLElement, ctx: StageOverlayContext): Surface {
  return mount(host, {
    actions: {
      lensOff: () => ctx.setLens(false),
    },
    render() {
      const mode = ctx.uiMode();
      const label = ctx.tourLabel();

      const tourChip = label
        ? `<div class="pointer-events-none absolute left-1/2 top-3.5 z-10 -translate-x-1/2 rounded-2xl border border-signal-dim bg-surface-2 px-4 py-1.5 font-mono text-[10px] tracking-[.18em] text-signal-light backdrop-blur-[10px]">→ ${esc(label.toUpperCase())}</div>`
        : "";

      const watermark =
        mode === "demo"
          ? `<div class="pointer-events-none absolute bottom-3.5 right-[310px] z-[5] font-mono text-[9px] tracking-[.18em] text-amber/50">◐ SYNTHETIC FEED — NOT REAL-WORLD DATA</div>`
          : "";

      // Basemap status (spec §4): say plainly where the pixels come from and what it costs.
      const basemapTone = ctx.basemap.kind === "ion" ? "text-ink/30" : "text-amber/60";
      const basemapLine = `
        <div class="pointer-events-none absolute bottom-1.5 left-3.5 z-[5] max-w-xl font-mono text-[8.5px] leading-relaxed tracking-[.06em] ${basemapTone}">
          BASEMAP · ${esc(ctx.basemap.label)} — ${esc(ctx.basemap.detail)}
        </div>`;

      const lens = ctx.lens()
        ? `
          <div class="wv-lens" aria-hidden="true"></div>
          <div class="absolute bottom-[120px] left-1/2 z-[56] flex -translate-x-1/2 items-center gap-2.5 rounded-[14px] border border-signal-dim bg-surface-2 px-3.5 py-1.5 font-mono text-[9px] tracking-[.14em] text-signal-light">
            LENS · MONO GRADE
            <button data-act="lensOff" class="text-ink/40 hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal">✕ OFF</button>
          </div>`
        : "";

      return `${tourChip}${watermark}${basemapLine}${lens}`;
    },
  });
}

/**
 * The WebGL diagnosis card. Without it a GPU failure is a silent black screen; with it the user
 * gets the reason and the recovery steps.
 */
export function renderGlobeFailure(host: HTMLElement, error: unknown): void {
  const message = String((error as Error)?.message ?? error).slice(0, 160);
  host.innerHTML = `
    <div class="flex h-full w-full items-center justify-center bg-void p-6">
      <div class="w-[520px] max-w-full rounded-[10px] border border-red/40 bg-surface-2 px-8 py-7 text-sm">
        <div class="text-[21px] font-semibold tracking-[.01em]">This machine can't render the globe.</div>
        <p class="mt-2.5 text-[13px] leading-relaxed text-ink/65">
          WorldView needs WebGL for the 3D globe. This usually means GPU acceleration is
          unavailable or disabled.
        </p>
        <ol class="mt-2 list-decimal space-y-0.5 pl-4 text-[12.5px] text-ink/65">
          <li>Enable hardware acceleration in your browser settings.</li>
          <li>Update your graphics drivers.</li>
          <li>Try a current Chrome, Firefox, or Safari.</li>
        </ol>
        <p class="mt-2.5 font-mono text-[10px] text-ink/40">${esc(message)}</p>
        <button onclick="location.reload()" class="mt-3.5 ${BAR_BUTTON}">RELOAD ⟳</button>
      </div>
    </div>`;
}
