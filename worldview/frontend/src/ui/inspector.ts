import type { LayerData } from "@/lib/layerData";
import type { LayerId } from "@/lib/layers";
import { buildInspectorView } from "@/lib/inspectorFields";
import { downloadBlob, mimeForFormat } from "@/lib/export";
import { fetchProvenance, type Provenance } from "@/lib/provenance";
import { MARK_HEX } from "@/lib/markStyle";
import { timelineStore } from "@/lib/store/timelineStore";
import { clockText, cx, esc, mount, type Surface } from "./dom";
import { glyph } from "./glyph";
import { panel } from "./panel";

// Inspector (spec §4): humanized, unit-bearing rows instead of raw keys; a dark-vessel selection
// leads with its alert context; provenance in plain words; an actions row. Lives in the right
// rail between Stats and Alerts so alert → locate → inspect is one visual chain.

/** The property holding each layer's entity id (to match the selection back to its feature). */
const ID_PROP: Record<LayerId, string> = {
  adsb: "icao24",
  ais: "mmsi",
  tle: "norad_id",
  ew: "h3_index",
  context: "entity_id",
};

const ACT_BUTTON =
  "flex-1 rounded-md border border-line py-1.5 font-mono text-[8.5px] tracking-[.06em] text-ink/65 transition-colors hover:border-signal-dim hover:text-signal-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:border-line disabled:hover:text-ink/65";

function utc(ts: number | undefined | null): string | null {
  if (ts == null || !Number.isFinite(ts) || ts <= 0) return null;
  return `${clockText(ts)} UTC`;
}

/**
 * Provenance / chain-of-custody (H19.4.3, spec §4): the bitemporal pair in PLAIN WORDS —
 * "Reported by {source} — true at {valid time}, recorded by WorldView at {transaction time}."
 */
function provenanceSection(
  prov: Provenance | null,
  featureSource: unknown,
  featureIngestedAt: unknown,
  deadReckoned: boolean,
): string {
  const source = prov?.source ?? (typeof featureSource === "string" ? featureSource : undefined);
  const validTime = utc(prov?.ts);
  const txTime = utc(prov?.ingestedAt ?? (typeof featureIngestedAt === "number" ? featureIngestedAt : null));

  let sentence: string;
  if (source == null && validTime == null && txTime == null) {
    sentence = "Provenance unknown — this datum carries no source or custody record.";
  } else {
    const reporter = source ? `Reported by ${source}` : "Reported by an unrecorded source";
    sentence = `${reporter}${validTime ? ` — true at ${validTime}` : ""}${txTime ? `, recorded by WorldView at ${txTime}` : ""}.`;
    if (deadReckoned) sentence += " Position since then is estimated from last course and speed.";
  }

  return `
    <div class="mt-2.5 rounded-md border border-signal-dim bg-signal-faint px-2.5 py-2">
      <div class="font-mono text-[8px] tracking-[.14em] text-signal-light">PROVENANCE · CHAIN OF CUSTODY</div>
      <div class="mt-1 text-[10.5px] leading-relaxed text-ink/65">${esc(sentence)}</div>
    </div>`;
}

export function createInspector(host: HTMLElement, data: () => LayerData): Surface {
  let showRaw = false;
  let prov: Provenance | null = null;
  let provKey = "";

  const surface = mount(host, {
    actions: {
      close: () => timelineStore.getState().selectEntity(null),
      raw: () => {
        showRaw = !showRaw;
        surface.update();
      },
      trail: (_e, _el, arg) => {
        const [layer, id] = arg.split("|");
        if (layer && id) timelineStore.getState().selectEntity({ layer: layer as LayerId, id });
      },
      follow: () => {
        const s = timelineStore.getState();
        s.setFollow(!s.follow);
      },
      goLive: () => timelineStore.getState().goLive(),
      exportEntity: () => {
        const s = timelineStore.getState();
        const selected = s.selectedEntity;
        if (!selected) return;
        const feature = findFeature(selected.layer, selected.id);
        if (!feature) return;
        downloadBlob(
          JSON.stringify({ type: "FeatureCollection", features: [feature] }, null, 2),
          `worldview-${selected.layer}-${selected.id}.geojson`,
          mimeForFormat("geojson"),
        );
      },
    },
    render() {
      const s = timelineStore.getState();
      const selected = s.selectedEntity;
      if (!selected) return "";

      // Refresh custody when the selection or a coarse (~60 s) time bucket changes.
      const key = `${selected.layer}:${selected.id}:${Math.floor(s.masterTime / 60)}`;
      if (key !== provKey) {
        provKey = key;
        void fetchProvenance(selected.layer, selected.id, s.masterTime).then((p) => {
          if (provKey !== key) return;
          prov = p;
          surface.update();
        });
      }

      const feature = findFeature(selected.layer, selected.id);
      const props = feature?.properties ?? {};
      const view = buildInspectorView(selected.layer, props, s.masterTime);

      // A dark vessel's trail is its underlying AIS track — TRAIL re-targets the selection there.
      const isDarkVessel = props.kind === "dark_vessel";
      const trailTarget =
        isDarkVessel && props.mmsi != null
          ? { layer: "ais" as LayerId, id: String(props.mmsi) }
          : selected;
      const trackable =
        trailTarget.layer === "adsb" || trailTarget.layer === "ais" || trailTarget.layer === "tle";

      const rows = view.rows
        .map(
          (row) => `
            <div class="grid grid-cols-[1fr_auto] gap-x-3 border-b border-line-2 py-1">
              <span class="text-[10.5px] text-ink/40">${esc(row.label)}</span>
              <span class="whitespace-nowrap text-right font-mono text-[10px] tabular-nums ${
                row.tone === "bad" ? "text-red" : row.tone === "warn" ? "text-amber" : "text-ink"
              }">${esc(row.value)}</span>
            </div>`,
        )
        .join("");

      const rawBlock =
        view.raw.length > 0
          ? `
            <div class="mt-1.5">
              <button data-act="raw" aria-expanded="${showRaw}" class="font-mono text-[8.5px] tracking-[.06em] text-ink/40 hover:text-signal-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal">
                ${showRaw ? "▾" : "▸"} raw fields (${view.raw.length})
              </button>
              ${
                showRaw
                  ? `<div class="mt-1">${view.raw
                      .map(
                        ([k, v]) => `
                          <div class="grid grid-cols-[1fr_auto] gap-x-3 py-0.5">
                            <span class="font-mono text-[9px] text-ink/40">${esc(k)}</span>
                            <span class="truncate text-right font-mono text-[9px] text-ink/65">${esc(v)}</span>
                          </div>`,
                      )
                      .join("")}</div>`
                  : ""
              }
            </div>`
          : "";

      const bodyWhenPresent = `${`<div class="mt-2">${rows}</div>`}${rawBlock}`;
      const bodyWhenAbsent = `
        <div class="mt-2 text-[10.5px] leading-relaxed text-ink/65">
          <p>No position for this entity at <span class="font-mono text-ink/80">${clockText(s.masterTime)} UTC</span>${
            s.mode === "historical" ? " — it wasn't reporting at this moment." : "."
          }</p>
          <p class="mt-1 text-ink/40">Scrub along its white trail to where it was active${s.mode === "historical" ? ", or:" : "."}</p>
          ${
            s.mode === "historical"
              ? `<button data-act="goLive" class="mt-2 rounded-md bg-green px-2.5 py-1 font-mono text-[9px] font-bold tracking-[.1em] text-[#04150c] focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal">● JUMP TO LIVE</button>`
              : ""
          }
        </div>`;

      const body = `
        <div class="flex items-center gap-2.5">
          <span class="flex h-[26px] w-[26px] items-center justify-center rounded-full border-[1.5px]"
            style="border-color: ${view.alert ? MARK_HEX.dark : "rgba(139,196,240,.3)"}" aria-hidden="true">
            ${glyph(view.glyph, 14)}
          </span>
          <div>
            <div class="font-mono text-[13px] text-ink">${esc(view.name)}</div>
            <div class="font-mono text-[8.5px] tracking-[.12em] ${view.alert ? "text-red" : "text-ink/40"}">${esc(view.kind)}</div>
          </div>
        </div>
        ${feature ? bodyWhenPresent : bodyWhenAbsent}
        ${provenanceSection(prov, props.source, props.ingested_at, isDarkVessel)}
        <div class="mt-2.5 flex gap-1.5">
          <button data-act="trail" data-arg="${esc(`${trailTarget.layer}|${trailTarget.id}`)}" ${trackable ? "" : "disabled"}
            class="${cx(ACT_BUTTON, trackable && "border-signal-dim bg-signal-faint text-signal-light")}"
            title="${trackable ? "Trace this entity's trailing-hour path" : "No track for this entity type"}">TRAIL</button>
          <button data-act="follow" aria-pressed="${s.follow}"
            class="${cx(ACT_BUTTON, s.follow && "border-signal-dim bg-signal-faint text-signal-light")}"
            title="Lock the camera onto this entity and follow it">FOLLOW</button>
          <button class="${ACT_BUTTON}" disabled title="Cases require analyst auth — available via the cases API">+ CASE</button>
          <button data-act="exportEntity" class="${ACT_BUTTON}" ${feature ? "" : "disabled"} title="Download this entity as GeoJSON">EXPORT</button>
        </div>`;

      return panel(
        {
          title: "Inspector",
          meta: selected.id,
          tone: view.alert ? "alert" : "default",
          closeAction: "close",
        },
        body,
      );
    },
  });

  function findFeature(layer: LayerId, id: string) {
    const idProp = ID_PROP[layer];
    return data()[layer].features.find(
      (f) => String(f.properties[idProp] ?? f.properties.entity_id ?? "") === id,
    );
  }

  return surface;
}
