import { env } from "@/lib/env";
import { timelineStore, SENSOR_MODES, type ViewMode } from "@/lib/store/timelineStore";
import { MODE_META, type UiMode } from "@/lib/uiMode";
import { SENSOR_LABELS } from "@/globe/sensors";
import { clockText, cx, esc, mount, type Surface } from "./dom";
import { brandMark } from "./glyph";
import { BAR_BUTTON } from "./panel";

// The app bar (spec §2): wordmark · AOI chip · projection toggle · sensor grade · tour ···
// mode pill · clock · connection badge · help. Top-center of the stage stays empty at rest.

const VIEWS: { id: ViewMode; label: string }[] = [
  { id: "map", label: "2.5D MAP" },
  { id: "globe", label: "3D GLOBE" },
];

export interface AppBarContext {
  uiMode: () => UiMode;
  lensAvailable: () => boolean;
  lens: () => boolean;
  toggleLens: () => void;
}

export function createAppBar(host: HTMLElement, ctx: AppBarContext): Surface {
  return mount(host, {
    actions: {
      view: (_e, _el, arg) => timelineStore.getState().setViewMode(arg as ViewMode),
      sensor: (e) => {
        const value = (e.target as HTMLSelectElement).value;
        timelineStore.getState().setSensor(value as (typeof SENSOR_MODES)[number]);
      },
      tour: () => {
        const s = timelineStore.getState();
        s.setTour(!s.tour);
      },
      lens: () => ctx.toggleLens(),
      goLive: () => timelineStore.getState().goLive(),
      help: () => timelineStore.getState().setHelpOpen(true),
    },
    inputs: {
      sensor: (e) =>
        timelineStore.getState().setSensor(
          (e.target as HTMLSelectElement).value as (typeof SENSOR_MODES)[number],
        ),
    },
    render() {
      const s = timelineStore.getState();
      const uiMode = ctx.uiMode();
      const meta = MODE_META[uiMode];
      const aoiLabel = env("VITE_AOI_LABEL", "STRAIT OF HORMUZ");

      const note = (() => {
        switch (uiMode) {
          case "live":
            return "real feed";
          case "demo":
            return "synthetic data";
          case "historical":
            return `as of ${clockText(s.masterTime)} UTC`;
          case "replay":
            return s.replayWindow
              ? `${clockText(s.replayWindow.from)} → ${clockText(s.replayWindow.to)} · ${s.speed}×`
              : "window armed";
          case "offline":
            return s.liveConnection === "reconnecting" ? "reconnecting…" : "feed unreachable";
        }
      })();

      // In historical mode the socket is closed by design — describe the data path instead of
      // dressing a deliberate close up as a failure.
      const conn =
        s.mode === "historical"
          ? { cls: "text-ink/40", dot: "bg-ink/40", label: "HTTP · AS-OF", pulse: "" }
          : {
              open: { cls: "text-green", dot: "bg-green", label: "WS OPEN", pulse: "" },
              connecting: { cls: "text-amber", dot: "bg-amber", label: "CONNECTING", pulse: "wv-pulse-fast" },
              reconnecting: { cls: "text-amber", dot: "bg-amber", label: "RECONNECTING", pulse: "wv-pulse-fast" },
              closed: { cls: "text-red", dot: "bg-red", label: "DISCONNECTED", pulse: "" },
            }[s.liveConnection];

      const views = VIEWS.map(
        (v) => `
          <button data-act="view" data-arg="${v.id}" aria-pressed="${s.viewMode === v.id}"
            class="${cx(
              "px-3 py-1.5 font-mono text-[9.5px] tracking-[.08em] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal",
              s.viewMode === v.id ? "bg-signal-faint text-signal-light" : "text-ink/40 hover:text-ink/80",
            )}">${v.label}</button>`,
      ).join("");

      const sensorOptions = SENSOR_MODES.map(
        (m) => `<option value="${m}" ${m === s.sensor ? "selected" : ""}>${SENSOR_LABELS[m]}</option>`,
      ).join("");

      const lensButton =
        ctx.lensAvailable()
          ? `<button data-act="lens" aria-pressed="${ctx.lens()}" class="${BAR_BUTTON}">${ctx.lens() ? "LENS ✕" : "LENS"}</button>`
          : "";

      const goLiveButton =
        uiMode === "historical" || uiMode === "replay"
          ? `<button data-act="goLive" class="rounded-[10px] bg-green px-2 py-0.5 font-mono text-[9px] font-bold tracking-[.1em] text-[#04150c] focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal">GO LIVE</button>`
          : "";

      return `
        <div class="flex items-center gap-2">
          ${brandMark()}
          <div>
            <div class="text-[12.5px] font-semibold tracking-[.22em]">WORLDVIEW</div>
            <div class="mt-px font-mono text-[8.5px] tracking-[.14em] text-ink/40">4D OSINT · JARVIS HUB</div>
          </div>
        </div>

        <span class="hidden rounded-xl border border-line px-2.5 py-1 font-mono text-[9.5px] tracking-[.1em] text-ink/65 lg:inline">
          AOI · ${esc(aoiLabel)}
        </span>

        <div class="flex overflow-hidden rounded-md border border-line" role="group" aria-label="Projection">${views}</div>

        <label class="flex items-center gap-1.5 font-mono text-[9px] tracking-[.08em] text-ink/40">
          SENSOR
          <select data-input="sensor" aria-label="Sensor grade"
            class="rounded-md border border-line bg-void-2 px-2 py-1 font-mono text-[9.5px] text-ink/65 focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal">
            ${sensorOptions}
          </select>
        </label>

        <button data-act="tour" aria-pressed="${s.tour}" class="${BAR_BUTTON}">${s.tour ? "■ STOP TOUR" : "◈ TOUR AOIs"}</button>
        ${lensButton}

        <div class="flex-1"></div>

        <span class="flex items-center gap-2 rounded-[13px] border px-3 py-1 font-mono text-[10px] font-semibold tracking-[.14em] ${meta.pill}">
          <span class="h-[7px] w-[7px] rounded-full ${meta.dot} ${uiMode === "live" ? "wv-pulse" : ""}" aria-hidden="true"></span>
          ${meta.label}
          <span class="font-normal opacity-75">· ${esc(note)}</span>
          ${goLiveButton}
        </span>

        <span class="font-mono text-[13px] tabular-nums tracking-[.06em]">
          ${clockText(s.masterTime)}<span class="ml-1 text-[9px] text-ink/40">UTC</span>
        </span>

        <span class="flex items-center gap-1.5 font-mono text-[9px] tracking-[.08em] ${conn.cls}">
          <span class="h-[7px] w-[7px] rounded-full ${conn.dot} ${conn.pulse}" aria-hidden="true"></span>
          ${conn.label}
        </span>

        <button data-act="help" class="${BAR_BUTTON}" aria-label="Keyboard shortcuts">?</button>`;
    },
  });
}
