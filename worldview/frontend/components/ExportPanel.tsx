"use client";

import { useState } from "react";
import type { LayerData } from "@/lib/useWorldViewData";
import type { FeatureCollection } from "@/lib/types";
import { useTimelineStore } from "@/lib/store/useTimelineStore";
import {
  downloadBlob,
  extForFormat,
  featureCollectionToGeoJson,
  fetchCaseExport,
  fetchReconstructionExport,
  mergeFeatureCollections,
  mimeForFormat,
  type ExportFormat,
} from "@/lib/export";

// Export panel (H19.4.6 / H19.2.7, client side). Sits top-right. Offers:
//   - Export the CURRENT view (the globe's in-memory features) as a tagged GeoJSON file.
//   - Given a case id, download its brief (Markdown) or GeoJSON from the backend export endpoint.
//   - Given a reconstruction id, download its GeoJSON / JSON.
// All backend fetches degrade gracefully (the endpoints are being built in parallel): on a
// 404 / offline they return null and we surface a one-line status instead of throwing.

type Status = { kind: "idle" | "ok" | "err"; msg: string };

const btn =
  "rounded bg-signal/20 px-2 py-1 font-medium text-signal hover:bg-signal/30 disabled:opacity-40 disabled:hover:bg-signal/20";

function tsSlug(epoch: number): string {
  // Compact UTC stamp for filenames, e.g. 20260608T065137Z.
  return new Date(epoch * 1000).toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
}

export function ExportPanel({ data }: { data: LayerData }) {
  const masterTime = useTimelineStore((s) => s.masterTime);
  const [caseId, setCaseId] = useState("");
  const [reconId, setReconId] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle", msg: "" });

  function exportCurrentView() {
    const fc = mergeFeatureCollections(data as unknown as Record<string, FeatureCollection>);
    const text = featureCollectionToGeoJson(fc);
    downloadBlob(text, `worldview-view-${tsSlug(masterTime)}.geojson`, mimeForFormat("geojson"));
    setStatus({ kind: "ok", msg: `Exported ${fc.features.length} features` });
  }

  async function downloadCase(format: ExportFormat) {
    const id = caseId.trim();
    if (!id) return;
    setStatus({ kind: "idle", msg: "Fetching…" });
    const result = await fetchCaseExport(id, format);
    if (!result) {
      setStatus({ kind: "err", msg: "Export unavailable (offline / not built)" });
      return;
    }
    downloadBlob(result.body, `case-${id}.${extForFormat(format)}`, result.contentType);
    setStatus({ kind: "ok", msg: `Downloaded case ${id}` });
  }

  async function downloadRecon(format: ExportFormat) {
    const id = reconId.trim();
    if (!id) return;
    setStatus({ kind: "idle", msg: "Fetching…" });
    const result = await fetchReconstructionExport(id, format);
    if (!result) {
      setStatus({ kind: "err", msg: "Export unavailable (offline / not built)" });
      return;
    }
    downloadBlob(result.body, `reconstruction-${id}.${extForFormat(format)}`, result.contentType);
    setStatus({ kind: "ok", msg: `Downloaded reconstruction ${id}` });
  }

  return (
    <div className="pointer-events-auto absolute right-4 top-4 z-10 flex w-64 flex-col gap-2 rounded-lg bg-cockpit/85 p-3 text-xs backdrop-blur">
      <div className="font-semibold text-signal">Export</div>

      <button type="button" onClick={exportCurrentView} className={btn}>
        ⬇ Current view (GeoJSON)
      </button>

      <div className="mt-1 flex flex-col gap-1">
        <label className="text-white/45">Case id</label>
        <input
          value={caseId}
          onChange={(e) => setCaseId(e.target.value)}
          placeholder="case-123"
          className="rounded bg-white/10 px-2 py-1 text-white/85 placeholder:text-white/30"
        />
        <div className="flex gap-1">
          <button type="button" onClick={() => downloadCase("brief")} disabled={!caseId.trim()} className={btn}>
            Brief
          </button>
          <button type="button" onClick={() => downloadCase("geojson")} disabled={!caseId.trim()} className={btn}>
            GeoJSON
          </button>
        </div>
      </div>

      <div className="mt-1 flex flex-col gap-1">
        <label className="text-white/45">Reconstruction id</label>
        <input
          value={reconId}
          onChange={(e) => setReconId(e.target.value)}
          placeholder="recon-456"
          className="rounded bg-white/10 px-2 py-1 text-white/85 placeholder:text-white/30"
        />
        <div className="flex gap-1">
          <button type="button" onClick={() => downloadRecon("geojson")} disabled={!reconId.trim()} className={btn}>
            GeoJSON
          </button>
          <button type="button" onClick={() => downloadRecon("json")} disabled={!reconId.trim()} className={btn}>
            JSON
          </button>
        </div>
      </div>

      {status.msg && (
        <div className={status.kind === "err" ? "text-red-300" : "text-white/55"}>{status.msg}</div>
      )}
    </div>
  );
}
