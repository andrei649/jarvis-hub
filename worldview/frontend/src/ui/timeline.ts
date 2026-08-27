import type { LayerData } from "@/lib/layerData";
import type { ReconWindow } from "@/lib/recon";
import type { UiMode } from "@/lib/uiMode";
import { deriveTimelineMarkers, markerPct } from "@/lib/timelineMarkers";
import { buildReplayLink } from "@/lib/export";
import { timelineStore } from "@/lib/store/timelineStore";
import { clockText, cx, esc, mount, shortClock, type Surface } from "./dom";

// Mode signal #3 of 3 (spec §3.3): the timeline restates the mode in words — the clock shows the
// VIEWED time, a mode note explains it, and the LIVE button is filled green only when live
// (hollow otherwise; one click back, plus `L`). Event markers (spec §4) pin alerts / recon
// passes / intel onto the 24 h track so history is navigable. The replay chip arms, plays and
// shares the reproducible window; the driver itself lives in src/app/replay.ts.

const WINDOW_SECONDS = 24 * 3600; // scrub the last 24h
const SPEEDS = [1, 10, 60, 300];
const TICKS = ["-24h", "-18h", "-12h", "-6h", "now"];
const DEFAULT_WINDOW_MINUTES = 15;

const MARKER_CLS: Record<string, string> = {
  alert: "bg-red shadow-[0_0_6px_rgba(255,90,82,.6)]",
  recon: "bg-[#E8D27A]",
  intel: "bg-violet",
};

const CHIP_BUTTON =
  "font-mono text-[9.5px] text-violet hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal";

export interface TimelineContext {
  data: () => LayerData;
  recon: () => ReconWindow[];
  uiMode: () => UiMode;
}

export function createTimeline(host: HTMLElement, ctx: TimelineContext): Surface {
  let copied = false;

  const surface = mount(host, {
    actions: {
      playPause: () => {
        const s = timelineStore.getState();
        s.setPlaying(!s.playing);
      },
      goLive: () => timelineStore.getState().goLive(),
      marker: (_e, _el, arg) => scrub(Number(arg)),
      armReplay: () => {
        const now = Math.floor(Date.now() / 1000);
        timelineStore.getState().setReplayWindow({ from: now - DEFAULT_WINDOW_MINUTES * 60, to: now });
      },
      toggleReplay: () => {
        const s = timelineStore.getState();
        s.setReplaying(!s.replaying);
      },
      copyLink: () => {
        const win = timelineStore.getState().replayWindow;
        if (!win || typeof window === "undefined") return;
        void navigator.clipboard?.writeText(buildReplayLink(window.location.href, win)).then(
          () => {
            copied = true;
            surface.update();
            setTimeout(() => {
              copied = false;
              surface.update();
            }, 1500);
          },
          () => {
            copied = false;
          },
        );
      },
      clearReplay: () => {
        const s = timelineStore.getState();
        s.setReplaying(false);
        s.setReplayWindow(null);
      },
    },
    inputs: {
      scrub: (e) => scrub(Number((e.target as HTMLInputElement).value)),
      speed: (e) => timelineStore.getState().setSpeed(Number((e.target as HTMLSelectElement).value)),
    },
    render() {
      const s = timelineStore.getState();
      const uiMode = ctx.uiMode();
      const now = Date.now() / 1000;
      const min = now - WINDOW_SECONDS;
      const headPct = Math.min(100, Math.max(0, ((Math.min(s.masterTime, now) - min) / WINDOW_SECONDS) * 100));
      const markers = deriveTimelineMarkers(ctx.data(), ctx.recon(), s.masterTime);

      const live = uiMode === "live" || uiMode === "demo";
      const modeNote = {
        live: "master clock · all layers in lockstep",
        demo: "master clock · synthetic feed",
        historical: "VIEWING THE PAST — world state as of this moment",
        replay: s.replayWindow
          ? `REPLAY ${shortClock(s.replayWindow.from)}→${shortClock(s.replayWindow.to)} · deterministic`
          : "REPLAY",
        offline: "feed unreachable — clock paused at last data",
      }[uiMode];

      const bracket = s.replayWindow
        ? (() => {
            const from = markerPct(s.replayWindow.from, min, now) ?? 0;
            const to = markerPct(s.replayWindow.to, min, now) ?? 100;
            return `<div aria-hidden="true" class="absolute top-[11px] h-2.5 rounded-[3px] border-[1.5px] border-violet bg-violet/10"
              style="left:${Math.max(0, from)}%;width:${Math.max(0.5, to - from)}%"></div>`;
          })()
        : "";

      const markerHtml = markers
        .map((m, i) => {
          const pct = markerPct(m.t, min, now);
          if (pct == null) return "";
          return `<button data-act="marker" data-arg="${m.t}" title="${esc(m.label)}" aria-label="Scrub to: ${esc(m.label)}"
            class="absolute top-[9px] z-10 h-3.5 w-[2.5px] -translate-x-1/2 rounded-[1px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal ${MARKER_CLS[m.kind] ?? ""}"
            style="left:${pct}%" key="${i}"></button>`;
        })
        .join("");

      const ticks = TICKS.map(
        (t, i) =>
          `<span aria-hidden="true" class="absolute top-[28px] -translate-x-1/2 font-mono text-[8px] text-ink/20" style="left:${i * 25}%">${t}</span>`,
      ).join("");

      const speedOptions = SPEEDS.map(
        (n) => `<option value="${n}" ${n === s.speed ? "selected" : ""}>${n}×</option>`,
      ).join("");

      return `
        <div class="flex items-center gap-3.5">
          <button data-act="playPause" aria-label="${s.playing ? "Pause" : "Play"}"
            class="h-8 w-8 rounded-full border border-line text-[12px] text-ink transition-colors hover:border-signal-dim hover:text-signal-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal">${s.playing ? "⏸" : "▶"}</button>

          <button data-act="goLive" title="${live ? "Receiving real-time data" : "Click (or press L) to return to real-time"}"
            class="${cx(
              "flex items-center gap-1.5 rounded-2xl border px-3.5 py-1.5 font-mono text-[10px] font-bold tracking-[.14em] transition-all focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal",
              live
                ? "border-green bg-green text-[#04150c] shadow-[0_0_16px_rgba(65,245,155,.35)]"
                : "border-line text-ink/40 hover:border-green/40 hover:text-green",
            )}">● LIVE</button>

          <span class="font-mono text-[14px] tabular-nums tracking-[.04em]">
            ${clockText(s.masterTime)}<span class="ml-1 text-[9px] text-ink/40">UTC · ${new Date(s.masterTime * 1000).toISOString().slice(0, 10)}</span>
          </span>

          <span class="font-mono text-[9px] tracking-[.06em] text-ink/40">${esc(modeNote)}</span>

          <div class="flex-1"></div>

          ${replayChip(s.replayWindow, s.replaying, s.masterTime, s.speed, copied)}

          <label class="flex items-center gap-1.5 font-mono text-[9px] text-ink/40">
            <select data-input="speed" aria-label="Playback speed" class="rounded-md border border-line bg-void-2 px-2 py-1 text-[9.5px] text-ink/65">${speedOptions}</select>
          </label>
        </div>

        <div class="relative mt-1.5 h-[34px]">
          <div class="absolute left-0 right-0 top-[14px] h-1 rounded-sm border border-line-2 bg-void-2" aria-hidden="true"></div>
          <div aria-hidden="true" class="absolute top-[14px] h-1 rounded-sm bg-gradient-to-r from-signal/25 to-signal" style="left:0;width:${headPct}%"></div>
          ${bracket}
          ${markerHtml}
          <div aria-hidden="true" class="absolute top-[8px] h-4 w-4 -translate-x-1/2 rounded-full border-2 border-void bg-signal-light shadow-[0_0_10px_rgba(43,184,240,.4)]" style="left:${headPct}%"></div>
          <input data-input="scrub" data-focus-key="scrub" type="range" min="${min}" max="${now}" step="1"
            value="${Math.min(s.masterTime, now)}" aria-label="24 hour timeline"
            class="absolute inset-x-0 top-0 h-[26px] w-full cursor-pointer opacity-0" />
          ${ticks}
        </div>`;
    },
  });

  function scrub(value: number) {
    if (!Number.isFinite(value)) return;
    const s = timelineStore.getState();
    // Scrubbing implies historical playback; the mode system announces it everywhere.
    if (s.mode !== "historical") s.setMode("historical");
    s.setMasterTime(value);
  }

  function replayChip(
    win: { from: number; to: number } | null,
    replaying: boolean,
    masterTime: number,
    speed: number,
    linkCopied: boolean,
  ): string {
    if (!win) {
      return `<button data-act="armReplay"
        class="flex items-center gap-2 rounded-md border border-violet/35 bg-violet/5 px-2.5 py-1 font-mono text-[9.5px] tracking-[.04em] text-violet/75 hover:bg-violet/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal"
        title="Arm a replay window (last 15 minutes) you can play, share and reproduce">SET REPLAY WINDOW ⧉</button>`;
    }
    const spanMin = Math.max(0, Math.round((win.to - win.from) / 60));
    const progress =
      replaying && win.to > win.from
        ? Math.min(1, Math.max(0, (masterTime - win.from) / (win.to - win.from)))
        : 0;
    return `
      <span class="flex items-center gap-2.5 rounded-md border border-violet/35 bg-violet/5 px-2.5 py-1 font-mono text-[9.5px] text-violet">
        <span class="tabular-nums">REPLAY ${clockText(win.from)} → ${clockText(win.to)} (${spanMin}m · ${speed}×)</span>
        <button data-act="toggleReplay" class="${CHIP_BUTTON}">${replaying ? `■ STOP (${Math.round(progress * 100)}%)` : "▶ REPLAY"}</button>
        <button data-act="copyLink" class="${CHIP_BUTTON}">${linkCopied ? "✓ COPIED" : "🔗 LINK"}</button>
        <button data-act="clearReplay" aria-label="Clear replay window"
          class="font-mono text-[9.5px] text-ink/40 hover:text-ink/80 focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal">✕</button>
      </span>`;
  }

  return surface;
}
