import type { LayerData } from "@/lib/layerData";
import type { FeatureCollection } from "@/lib/types";
import { timelineStore } from "@/lib/store/timelineStore";
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
import { esc, mount, type Surface } from "./dom";
import { panel, MINI_BUTTON, TEXT_INPUT } from "./panel";

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

/** Compact UTC stamp for filenames, e.g. 20260608T065137Z. */
function tsSlug(epoch: number): string {
  return new Date(epoch * 1000).toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
}

export function createExportPanel(host: HTMLElement, data: () => LayerData): Surface {
  let open = false;
  let caseId = "";
  let reconId = "";
  let status: Status = { kind: "idle", msg: "" };
  let recents = loadRecents();

  const surface = mount(host, {
    inputs: {
      caseId: (e) => {
        caseId = (e.target as HTMLInputElement).value;
      },
      reconId: (e) => {
        reconId = (e.target as HTMLInputElement).value;
      },
    },
    actions: {
      collapse: () => {
        open = !open;
        surface.update();
      },
      currentView: () => {
        const fc = mergeFeatureCollections(data() as unknown as Record<string, FeatureCollection>);
        downloadBlob(
          featureCollectionToGeoJson(fc),
          `worldview-view-${tsSlug(timelineStore.getState().masterTime)}.geojson`,
          mimeForFormat("geojson"),
        );
        status = { kind: "ok", msg: `Exported ${fc.features.length} features` };
        surface.update();
      },
      downloadCase: (_e, _el, arg) => void download("case", caseId.trim(), arg as ExportFormat),
      downloadRecon: (_e, _el, arg) => void download("recon", reconId.trim(), arg as ExportFormat),
      recent: (_e, _el, arg) => {
        if (arg.startsWith("recon")) reconId = arg;
        else caseId = arg;
        surface.update();
      },
    },
    render() {
      const recentsHtml =
        recents.length > 0
          ? `<div class="mt-1.5 font-mono text-[8.5px] text-ink/40">recent: ${recents
              .map(
                (id) =>
                  `<button data-act="recent" data-arg="${esc(id)}" class="mr-2 text-signal-light hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal">${esc(id)}</button>`,
              )
              .join("")}</div>`
          : "";
      const statusHtml = status.msg
        ? `<div class="mt-1.5 text-[10px] ${status.kind === "err" ? "text-red" : "text-ink/55"}">${esc(status.msg)}</div>`
        : "";

      const body = `
        <button data-act="currentView" class="${MINI_BUTTON} w-full py-2">⬇ CURRENT VIEW · GEOJSON</button>

        <div class="mt-2 flex gap-1.5">
          <input data-input="caseId" data-focus-key="caseId" value="${esc(caseId)}" placeholder="case id…" aria-label="Case id" class="${TEXT_INPUT}" />
          <button data-act="downloadCase" data-arg="brief" ${caseId.trim() ? "" : "disabled"} class="${MINI_BUTTON}">BRIEF</button>
          <button data-act="downloadCase" data-arg="geojson" ${caseId.trim() ? "" : "disabled"} class="${MINI_BUTTON}">GEO</button>
        </div>

        <div class="mt-1.5 flex gap-1.5">
          <input data-input="reconId" data-focus-key="reconId" value="${esc(reconId)}" placeholder="reconstruction id…" aria-label="Reconstruction id" class="${TEXT_INPUT}" />
          <button data-act="downloadRecon" data-arg="geojson" ${reconId.trim() ? "" : "disabled"} class="${MINI_BUTTON}">GEO</button>
          <button data-act="downloadRecon" data-arg="json" ${reconId.trim() ? "" : "disabled"} class="${MINI_BUTTON}">JSON</button>
        </div>

        ${recentsHtml}${statusHtml}`;

      return panel(
        { title: "Export", meta: "GeoJSON · brief", collapseAction: "collapse", open },
        body,
      );
    },
  });

  async function download(kind: "case" | "recon", id: string, format: ExportFormat) {
    if (!id) return;
    status = { kind: "idle", msg: "Fetching…" };
    surface.update();
    const result =
      kind === "case" ? await fetchCaseExport(id, format) : await fetchReconstructionExport(id, format);
    if (!result) {
      status = { kind: "err", msg: "Export unavailable (offline / not built)" };
      surface.update();
      return;
    }
    const name = kind === "case" ? `case-${id}` : `reconstruction-${id}`;
    downloadBlob(result.body, `${name}.${extForFormat(format)}`, result.contentType);
    pushRecent(id);
    recents = loadRecents();
    status = { kind: "ok", msg: `Downloaded ${kind === "case" ? "case" : "reconstruction"} ${id}` };
    surface.update();
  }

  return surface;
}
