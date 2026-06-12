"use client";

import { useState } from "react";
import type { LayerData } from "@/lib/useWorldViewData";
import { useTimelineStore } from "@/lib/store/useTimelineStore";
import type { LayerId } from "@/lib/layers";
import { buildInspectorView } from "@/lib/inspectorFields";
import { downloadBlob, mimeForFormat } from "@/lib/export";
import { ProvenanceSection } from "./ProvenanceSection";
import { Panel } from "./Panel";
import { MarkGlyph } from "./MarkGlyph";
import { MARK_HEX } from "@/lib/markStyle";

// The property holding each layer's entity id (to match the selection back to its feature).
const ID_PROP: Record<LayerId, string> = {
  adsb: "icao24",
  ais: "mmsi",
  tle: "norad_id",
  ew: "h3_index",
  context: "entity_id",
};

// Inspector (spec §4): humanized, unit-bearing rows instead of raw keys; a dark-vessel
// selection leads with its alert context; provenance in plain words; an actions row. Lives in
// the right rail between Stats and Alerts so alert → locate → inspect is one visual chain.
export function Inspector({ data }: { data: LayerData }) {
  const selected = useTimelineStore((s) => s.selectedEntity);
  const selectEntity = useTimelineStore((s) => s.selectEntity);
  const masterTime = useTimelineStore((s) => s.masterTime);
  const mode = useTimelineStore((s) => s.mode);
  const goLive = useTimelineStore((s) => s.goLive);
  const [showRaw, setShowRaw] = useState(false);
  if (!selected) return null;

  const idProp = ID_PROP[selected.layer];
  const feature = data[selected.layer].features.find(
    (f) => String(f.properties[idProp] ?? f.properties.entity_id ?? "") === selected.id,
  );
  const props = feature?.properties ?? {};
  const view = buildInspectorView(selected.layer, props, masterTime);

  // A dark vessel's trail is its underlying AIS track — TRAIL re-targets the selection there.
  const isDarkVessel = props.kind === "dark_vessel";
  const trailTarget =
    isDarkVessel && props.mmsi != null
      ? { layer: "ais" as const, id: String(props.mmsi) }
      : selected;
  const trackable = trailTarget.layer === "adsb" || trailTarget.layer === "ais" || trailTarget.layer === "tle";

  function exportEntity() {
    if (!feature) return;
    downloadBlob(
      JSON.stringify({ type: "FeatureCollection", features: [feature] }, null, 2),
      `worldview-${selected!.layer}-${selected!.id}.geojson`,
      mimeForFormat("geojson"),
    );
  }

  const actBtn =
    "flex-1 rounded-md border border-line py-1.5 font-mono text-[8.5px] tracking-[.06em] text-ink/65 transition-colors hover:border-signal-dim hover:text-signal-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:border-line disabled:hover:text-ink/65";

  return (
    <Panel
      title="Inspector"
      meta={selected.id}
      tone={view.alert ? "alert" : "default"}
      onClose={() => selectEntity(null)}
    >
      <div className="flex items-center gap-2.5">
        <span
          className="flex h-[26px] w-[26px] items-center justify-center rounded-full border-[1.5px]"
          style={{ borderColor: view.alert ? MARK_HEX.dark : "rgba(139,196,240,.3)" }}
          aria-hidden
        >
          <MarkGlyph kind={view.glyph} size={14} />
        </span>
        <div>
          <div className="font-mono text-[13px] text-ink">{view.name}</div>
          <div className={`font-mono text-[8.5px] tracking-[.12em] ${view.alert ? "text-red" : "text-ink/40"}`}>
            {view.kind}
          </div>
        </div>
      </div>

      {feature ? (
        <>
          <div className="mt-2">
            {view.rows.map((row) => (
              <div
                key={row.label}
                className="grid grid-cols-[1fr_auto] gap-x-3 border-b border-line-2 py-1"
              >
                <span className="text-[10.5px] text-ink/40">{row.label}</span>
                <span
                  className={`whitespace-nowrap text-right font-mono text-[10px] tabular-nums ${
                    row.tone === "bad" ? "text-red" : row.tone === "warn" ? "text-amber" : "text-ink"
                  }`}
                >
                  {row.value}
                </span>
              </div>
            ))}
          </div>

          {view.raw.length > 0 && (
            <div className="mt-1.5">
              <button
                onClick={() => setShowRaw(!showRaw)}
                aria-expanded={showRaw}
                className="font-mono text-[8.5px] tracking-[.06em] text-ink/40 hover:text-signal-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal"
              >
                {showRaw ? "▾" : "▸"} raw fields ({view.raw.length})
              </button>
              {showRaw && (
                <div className="mt-1">
                  {view.raw.map(([k, v]) => (
                    <div key={k} className="grid grid-cols-[1fr_auto] gap-x-3 py-0.5">
                      <span className="font-mono text-[9px] text-ink/40">{k}</span>
                      <span className="truncate text-right font-mono text-[9px] text-ink/65">{v}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      ) : (
        <div className="mt-2 text-[10.5px] leading-relaxed text-ink/65">
          <p>
            No position for this entity at{" "}
            <span className="font-mono text-ink/80">
              {new Date(masterTime * 1000).toISOString().slice(11, 19)} UTC
            </span>
            {mode === "historical" ? " — it wasn't reporting at this moment." : "."}
          </p>
          <p className="mt-1 text-ink/40">
            Scrub along its white trail to where it was active{mode === "historical" ? ", or:" : "."}
          </p>
          {mode === "historical" && (
            <button
              onClick={goLive}
              className="mt-2 rounded-md bg-green px-2.5 py-1 font-mono text-[9px] font-bold tracking-[.1em] text-[#04150c] focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal"
            >
              ● JUMP TO LIVE
            </button>
          )}
        </div>
      )}

      <ProvenanceSection
        layer={selected.layer}
        entityId={selected.id}
        masterTime={masterTime}
        featureSource={props.source}
        featureIngestedAt={props.ingested_at}
        deadReckoned={isDarkVessel}
      />

      <div className="mt-2.5 flex gap-1.5">
        <button
          className={`${actBtn} ${trackable ? "border-signal-dim bg-signal-faint text-signal-light" : ""}`}
          disabled={!trackable}
          onClick={() => selectEntity(trailTarget)}
          title={trackable ? "Trace this entity's trailing-hour path" : "No track for this entity type"}
        >
          TRAIL
        </button>
        <button className={actBtn} disabled title="Watching an AOI requires analyst auth — available via the recon API / JARVIS (watch_aoi)">
          WATCH
        </button>
        <button className={actBtn} disabled title="Cases require analyst auth — available via the cases API">
          + CASE
        </button>
        <button className={actBtn} onClick={exportEntity} disabled={!feature} title="Download this entity as GeoJSON">
          EXPORT
        </button>
      </div>
    </Panel>
  );
}
