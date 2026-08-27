import { LAYER_IDS } from "@/lib/layers";
import type { LayerData } from "@/lib/layerData";
import { apiUrl } from "@/lib/env";
import { timelineStore } from "@/lib/store/timelineStore";
import { esc, mount, type Surface } from "./dom";
import { brandMark } from "./glyph";
import { BAR_BUTTON } from "./panel";

// First-run / degraded-state overlay (spec §3.1, P1): when the globe would otherwise be silently
// empty, a centered card explains WHAT this screen is, WHY it's empty, and the exact next steps
// — with the honesty footer. It renders nothing when data flows, so it never covers a working
// globe. Detection is state-driven (socket + per-layer fetch outcomes).

const GRACE_MS = 2500;

function step(n: number, title: string, detail: string): string {
  return `
    <div class="grid grid-cols-[26px_1fr] items-start gap-3 border-t border-line-2 py-2.5">
      <span class="flex h-[22px] w-[22px] items-center justify-center rounded-full border border-signal-dim font-mono text-[11px] text-signal-light">${n}</span>
      <div>
        <div class="text-[12.5px] text-ink">${esc(title)}</div>
        <div class="mt-0.5 font-mono text-[10px] text-ink/40">${detail}</div>
      </div>
    </div>`;
}

function code(text: string): string {
  return `<code class="rounded-[3px] bg-signal-faint px-1.5 py-px text-signal-light">${esc(text)}</code>`;
}

export function createSystemStatus(host: HTMLElement, data: () => LayerData): Surface {
  // Give the live socket a moment before declaring trouble, so a healthy fast connect never flashes.
  let graceElapsed = false;
  const surface = mount(host, {
    actions: {
      retry: () => timelineStore.getState().goLive(),
      help: () => timelineStore.getState().setHelpOpen(true),
    },
    render() {
      const s = timelineStore.getState();
      const layers = data();
      const totalFeatures = LAYER_IDS.reduce((n, id) => n + layers[id].features.length, 0);
      const visibleIds = LAYER_IDS.filter((id) => s.layerVisibility[id]);
      const allErrored =
        s.mode === "historical" &&
        visibleIds.length > 0 &&
        visibleIds.every((id) => s.layerStatus[id] === "error");
      const allEmpty = visibleIds.length > 0 && visibleIds.every((id) => s.layerStatus[id] === "empty");
      const liveUnhealthy = s.liveConnection !== "open";

      let variant: "down" | "connecting" | "empty" | null = null;
      if (s.mode === "live" && totalFeatures === 0 && graceElapsed && (s.liveConnection === "closed" || allErrored)) {
        variant = "down";
      } else if (s.mode === "live" && liveUnhealthy && graceElapsed && totalFeatures === 0) {
        variant = "connecting";
      } else if (allErrored) {
        variant = "down";
      } else if (allEmpty && totalFeatures === 0) {
        variant = "empty";
      }
      if (!variant) return "";

      const api = esc(apiUrl());
      const retry = `<button data-act="retry" class="ml-auto ${BAR_BUTTON}">RETRY ⟳</button>`;
      const shortcuts = `<button data-act="help" class="ml-auto ${BAR_BUTTON}">SHORTCUTS ?</button>`;

      const body = {
        down: `
          <div class="text-[21px] font-semibold tracking-[.01em]">WorldView is up — its data feed isn't.</div>
          <p class="mb-4 mt-2.5 text-[13px] leading-relaxed text-ink/65">
            This screen fuses live aircraft, vessels, satellites, GPS-jamming and intel onto one
            time-scrubbable globe. Right now the API at <code class="text-signal-light">${api}</code>
            isn't answering, so the globe is empty.
          </p>
          ${step(1, "Start the backend", `${code("npm run dev:api")} in ${code("worldview/")} — boots the API + a synthetic Hormuz demo feed`)}
          ${step(2, "Or point at a running API", `set ${code("VITE_API_URL")} and reload`)}
          ${step(3, "Then take the tour", `press ${code("?")} for shortcuts · ◈ TOUR flies the camera between AOIs`)}`,
        connecting: `
          <div class="text-[21px] font-semibold tracking-[.01em]">${
            s.liveConnection === "reconnecting" ? "Reconnecting to the live feed…" : "Connecting to the live feed…"
          }</div>
          <p class="mt-2.5 text-[13px] leading-relaxed text-ink/65">
            Waiting for data from <code class="text-signal-light">${api}</code>. If this persists, the
            API may be offline — start it with <code class="text-signal-light">npm run dev:api</code>.
          </p>`,
        empty: `
          <div class="text-[21px] font-semibold tracking-[.01em]">Connected — no data in this window yet.</div>
          <p class="mb-4 mt-2.5 text-[13px] leading-relaxed text-ink/65">The API is answering but has nothing for this moment in time.</p>
          ${step(1, "Seed the demo scenario", `${code("npm run db:seed")} — a Strait of Hormuz scenario across all 5 layers`)}
          ${step(2, "Or scrub to an active period", `drag the timeline below, or press ${code("L")} for live`)}
          ${step(3, "Shortcuts", `press ${code("?")} — space, L, arrows, 1–5, G, V, F`)}`,
      }[variant];

      return `
        <div class="absolute inset-0 z-[80] flex items-center justify-center bg-void/60 p-6 backdrop-blur-[3px]">
          <div role="status" aria-live="polite" class="w-[520px] max-w-full rounded-[10px] border border-line bg-surface-2 px-8 py-7">
            <div class="mb-3.5">${brandMark(34)}</div>
            ${body}
            <div class="mt-4 flex items-center gap-2.5 border-t border-line-2 pt-3.5 text-[11px] text-amber">
              <span aria-hidden="true">◐</span>
              <span>The demo feed is synthetic — WorldView will badge it. It never passes demo data as real.</span>
              ${variant === "connecting" ? shortcuts : retry}
            </div>
          </div>
        </div>`;
    },
  });

  setTimeout(() => {
    graceElapsed = true;
    surface.update();
  }, GRACE_MS);

  return surface;
}
