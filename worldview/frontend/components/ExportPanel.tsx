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
import { Panel } from "./Panel";

// Export panel (spec §3.4): docked at the bottom of the right rail, collapsed to its header by
// default. Expanded: current-view download + case/reconstruction id fetches with paste-target
// "recent" chips so raw id entry feels intentional. Backend fetches degrade gracefully.

type Status = { kind: "idle" | "ok" | "err"; msg: string };

const RECENTS_KEY = "worldview.export.recents";

function loadRecents(): string[] {
  if (typeof localStorage === "undefined") return [];
  try {
    const raw = localStorage.getItem(RECENTS_KEY);
    const list = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(list) ? list.filter((x): x is string => typeof x === "string").slice(0, 4) : [];
  } catch {
    return [];
  }
}

function pushRecent(id: string) {
  if (typeof localStorage === "undefined") return;
  const next = [id, ...loadRecents().filter((x) => x !== id)].slice(0, 4);
  try {
    localStorage.setItem(RECENTS_KEY, JSON.stringify(next));
  } catch {
    /* quota/private mode — recents are a convenience, not state */
  }
}

function tsSlug(epoch: number): string {
  // Compact UTC stamp for filenames, e.g. 20260608T065137Z.
  return new Date(epoch * 1000).toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
}

export function ExportPanel({ data }: { data: LayerData }) {
  const masterTime = useTimelineStore((s) => s.masterTime);
  const [caseId, setCaseId] = useState("");
  const [reconId, setReconId] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle", msg: "" });
  const [recents, setRecents] = useState<string[]>(loadRecents);

  function remember(id: string) {
    pushRecent(id);
    setRecents(loadRecents());
  }

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
    remember(id);
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
    remember(id);
    setStatus({ kind: "ok", msg: `Downloaded reconstruction ${id}` });
  }

  const miniBtn =
    "rounded-md border border-line px-2.5 py-1.5 font-mono text-[9px] tracking-[.04em] text-ink/65 transition-colors hover:border-signal-dim hover:text-signal-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal disabled:opacity-35 disabled:hover:border-line disabled:hover:text-ink/65";
  const input =
    "min-w-0 flex-1 rounded-md border border-line bg-void-2 px-2 py-1.5 font-mono text-[10px] text-ink placeholder:text-ink/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal";

  return (
    <Panel title="Export" meta="GeoJSON · brief" collapsible defaultOpen={false}>
      <button onClick={exportCurrentView} className={`${miniBtn} w-full py-2`}>
        ⬇ CURRENT VIEW · GEOJSON
      </button>

      <div className="mt-2 flex gap-1.5">
        <input
          value={caseId}
          onChange={(e) => setCaseId(e.target.value)}
          placeholder="case id…"
          aria-label="Case id"
          className={input}
        />
        <button onClick={() => downloadCase("brief")} disabled={!caseId.trim()} className={miniBtn}>
          BRIEF
        </button>
        <button onClick={() => downloadCase("geojson")} disabled={!caseId.trim()} className={miniBtn}>
          GEO
        </button>
      </div>

      <div className="mt-1.5 flex gap-1.5">
        <input
          value={reconId}
          onChange={(e) => setReconId(e.target.value)}
          placeholder="reconstruction id…"
          aria-label="Reconstruction id"
          className={input}
        />
        <button onClick={() => downloadRecon("geojson")} disabled={!reconId.trim()} className={miniBtn}>
          GEO
        </button>
        <button onClick={() => downloadRecon("json")} disabled={!reconId.trim()} className={miniBtn}>
          JSON
        </button>
      </div>

      {recents.length > 0 && (
        <div className="mt-1.5 font-mono text-[8.5px] text-ink/40">
          recent:{" "}
          {recents.map((id) => (
            <button
              key={id}
              onClick={() => (id.startsWith("recon") ? setReconId(id) : setCaseId(id))}
              className="mr-2 text-signal-light hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal"
            >
              {id}
            </button>
          ))}
        </div>
      )}

      {status.msg && (
        <div className={`mt-1.5 text-[10px] ${status.kind === "err" ? "text-red" : "text-ink/55"}`}>
          {status.msg}
        </div>
      )}
    </Panel>
  );
}
