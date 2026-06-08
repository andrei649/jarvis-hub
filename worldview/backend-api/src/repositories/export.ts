import type { Pool } from "pg";
import {
  buildFrames,
  getReconstruction,
  type Frame,
  type ReconstructionRow,
} from "./reconstruction.js";
import {
  getCase,
  listComments,
  listItems,
  listMembers,
  type CaseCommentRow,
  type CaseItemRow,
  type CaseMemberRow,
  type CaseRow,
} from "./cases.js";
import { listActions, type ActionAuditRow } from "./ontologyAudit.js";
import { getObject } from "./ontology.js";
import type { OntologyObject } from "../ontology/registry.js";
import type { FeatureCollection, GeoJSONFeature } from "../types.js";

// Export / reporting core (tickets H19.2.7 + H19.4.6). One shared export engine serves BOTH a saved
// reconstruction (a shareable, reproducible replay bundle) AND a case file (a reproducible brief +
// GeoJSON + replay). Everything here is built from the existing repositories — buildFrames re-derives
// reconstruction frames from history (reproducible from params, never a frozen copy), and the case
// export resolves pinned items to their CURRENT ontology objects via getObject and pulls the audited
// case history from the ontology_actions hash chain. Bundles are self-contained + portable (plain JSON
// /GeoJSON/Markdown — no heavy deps). PDF is intentionally NOT generated here: the `brief` is Markdown
// and a thin client (print-to-PDF) or a follow-up renders it.

export type ReconstructionFormat = "json" | "geojson";
export type CaseFormat = "json" | "geojson" | "brief";

// ---------------------------------------------------------------------------
// RECONSTRUCTION EXPORT
// ---------------------------------------------------------------------------

export interface ReconstructionBundle {
  kind: "reconstruction";
  reconstruction: ReconstructionRow;
  frameCount: number;
  frames: Frame[];
}

/**
 * Export a saved reconstruction as a self-contained, reproducible bundle. `json` = the manifest (the
 * saved handle + its params) plus ALL re-derived frames. `geojson` = a single FeatureCollection that
 * MERGES every frame's features, stamping a `t` (frame epoch) and `layer` property onto each feature so
 * the flattened collection stays time/layer-addressable. Returns null when the reconstruction is absent.
 *
 * REPRODUCIBILITY: the frames are re-derived from the stored params via buildFrames (same params -> same
 * frame timestamps -> same as-of-T history reads), so re-exporting the same handle yields the same bundle.
 */
export async function exportReconstruction(
  pool: Pool,
  id: number,
  format: ReconstructionFormat,
): Promise<{ format: ReconstructionFormat; body: ReconstructionBundle | FeatureCollection } | null> {
  const reconstruction = await getReconstruction(pool, id);
  if (!reconstruction) return null;
  const frames = await buildFrames(pool, reconstruction.params);

  if (format === "geojson") {
    return { format, body: framesToFeatureCollection(frames) };
  }
  const body: ReconstructionBundle = {
    kind: "reconstruction",
    reconstruction,
    frameCount: frames.length,
    frames,
  };
  return { format, body };
}

// Flatten frames into one FeatureCollection, stamping `t` (frame epoch) + `layer` on every feature so
// the merged collection stays addressable back to its frame/layer of origin.
function framesToFeatureCollection(frames: Frame[]): FeatureCollection {
  const features: GeoJSONFeature[] = [];
  for (const frame of frames) {
    for (const [layer, fc] of Object.entries(frame.layers)) {
      for (const feature of fc.features) {
        features.push({
          ...feature,
          properties: { ...feature.properties, t: frame.t, layer },
        });
      }
    }
  }
  return { type: "FeatureCollection", features };
}

// ---------------------------------------------------------------------------
// CASE EXPORT
// ---------------------------------------------------------------------------

// A pinned case item resolved to its CURRENT ontology object (or null when it no longer resolves).
export interface ResolvedCaseItem {
  item: CaseItemRow;
  object: OntologyObject | null;
}

export interface CaseBundle {
  kind: "case";
  case: CaseRow;
  members: CaseMemberRow[];
  items: ResolvedCaseItem[];
  comments: CaseCommentRow[];
  history: ActionAuditRow[];
}

/**
 * Export a case file as a reproducible bundle. `json` = the full structured bundle (metadata, members,
 * items resolved to their current ontology objects, comments, and the audited history). `brief` = a
 * structured Markdown report. `geojson` = the case items' geometries as a FeatureCollection. Returns
 * null when the case is absent.
 */
export async function exportCase(
  pool: Pool,
  caseId: number,
  format: CaseFormat,
): Promise<{ format: CaseFormat; body: CaseBundle | FeatureCollection | { markdown: string } } | null> {
  const caseRow = await getCase(pool, caseId);
  if (!caseRow) return null;

  const [members, rawItems, comments, history] = await Promise.all([
    listMembers(pool, caseId),
    listItems(pool, caseId),
    listComments(pool, caseId),
    // The audited case history is the filtered ontology_actions chain (objectType 'Case', objectId=:id).
    listActions(pool, { objectType: "Case", objectId: String(caseId) }),
  ]);

  // Resolve each pinned item to its CURRENT ontology object (provenance comes along for the brief).
  const items: ResolvedCaseItem[] = await Promise.all(
    rawItems.map(async (item) => ({
      item,
      object: await getObject(pool, item.objectType, item.objectId),
    })),
  );

  const bundle: CaseBundle = { kind: "case", case: caseRow, members, items, comments, history };

  if (format === "geojson") {
    return { format, body: caseItemsToFeatureCollection(items) };
  }
  if (format === "brief") {
    return { format, body: { markdown: renderBrief(bundle) } };
  }
  return { format, body: bundle };
}

// Build a FeatureCollection from the resolved case items. Ontology objects carry their position in a
// lon/lat property pair when available (e.g. a Vessel/Aircraft fix); we emit a Point for those and a
// geometry-less Feature (null geometry) otherwise, always carrying the object's properties + provenance
// so the export is self-describing. Each feature is stamped with its object type/id + the case note.
function caseItemsToFeatureCollection(items: ResolvedCaseItem[]): FeatureCollection {
  const features: GeoJSONFeature[] = items.map(({ item, object }) => {
    const coords = object ? lonLatOf(object.properties) : null;
    return {
      type: "Feature",
      geometry: coords ? { type: "Point", coordinates: coords } : null,
      properties: {
        objectType: item.objectType,
        objectId: item.objectId,
        note: item.note,
        title: object?.title ?? null,
        ...(object ? object.properties : {}),
        provenance: object?.provenance ?? null,
      },
    };
  });
  return { type: "FeatureCollection", features };
}

// Pull a [lon, lat] pair from an object's property bag when it exposes one (tolerant of a few common
// key spellings); null when the object isn't a positioned point.
function lonLatOf(props: Record<string, unknown>): [number, number] | null {
  const lon = firstNumber(props, ["lon", "lng", "longitude"]);
  const lat = firstNumber(props, ["lat", "latitude"]);
  if (lon == null || lat == null) return null;
  return [lon, lat];
}

function firstNumber(props: Record<string, unknown>, keys: string[]): number | null {
  for (const k of keys) {
    const v = props[k];
    if (typeof v === "number" && Number.isFinite(v)) return v;
    if (typeof v === "string" && v.trim() && Number.isFinite(Number(v))) return Number(v);
  }
  return null;
}

// Render the case brief as a structured Markdown report: title, summary, members, pinned items with
// provenance, the comment thread, and the audit list. Plain Markdown — a thin client (print-to-PDF) or
// a follow-up renders a PDF; we deliberately add no PDF dependency.
function renderBrief(b: CaseBundle): string {
  const L: string[] = [];
  const c = b.case;
  L.push(`# Case Brief: ${c.title}`);
  L.push("");

  // Summary
  L.push("## Summary");
  L.push(`- **Case ID:** ${c.id}`);
  L.push(`- **Status:** ${c.status}`);
  L.push(`- **Opened by:** ${c.createdBy ?? "(unknown)"}`);
  L.push(`- **Created:** ${isoOf(c.createdAt)}`);
  L.push(`- **Updated:** ${isoOf(c.updatedAt)}`);
  if (c.description) {
    L.push("");
    L.push(c.description);
  }
  L.push("");

  // Members
  L.push("## Members");
  if (b.members.length === 0) {
    L.push("_(no members)_");
  } else {
    for (const m of b.members) {
      L.push(`- **${m.actor}** — ${m.role} (added ${isoOf(m.addedAt)})`);
    }
  }
  L.push("");

  // Pinned items with provenance
  L.push("## Pinned items");
  if (b.items.length === 0) {
    L.push("_(no items)_");
  } else {
    for (const { item, object } of b.items) {
      const title = object?.title ?? `${item.objectType} ${item.objectId}`;
      L.push(`### ${title}`);
      L.push(`- **Object:** ${item.objectType} \`${item.objectId}\``);
      if (item.note) L.push(`- **Note:** ${item.note}`);
      if (item.addedBy) L.push(`- **Pinned by:** ${item.addedBy} (${isoOf(item.addedAt)})`);
      if (object) {
        const p = object.provenance;
        L.push(
          `- **Provenance:** source=${p.source ?? "n/a"}, ts=${p.ts != null ? isoOf(p.ts) : "n/a"}` +
            `, ingestedAt=${p.ingestedAt != null ? isoOf(p.ingestedAt) : "n/a"}`,
        );
      } else {
        L.push("- **Provenance:** object no longer resolves");
      }
      L.push("");
    }
  }

  // Comment thread
  L.push("## Comments");
  if (b.comments.length === 0) {
    L.push("_(no comments)_");
  } else {
    for (const cm of b.comments) {
      L.push(`- **${cm.actor ?? "(anonymous)"}** (${isoOf(cm.createdAt)}): ${cm.body}`);
    }
  }
  L.push("");

  // Audit list
  L.push("## Audit trail");
  if (b.history.length === 0) {
    L.push("_(no audited actions)_");
  } else {
    for (const a of b.history) {
      L.push(`- ${isoOf(a.ts)} — \`${a.action}\` by ${a.actor ?? "(system)"}`);
    }
  }
  L.push("");
  return L.join("\n");
}

// UNIX seconds (UTC instant) -> ISO 8601 string for the human-readable brief.
function isoOf(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toISOString();
}
