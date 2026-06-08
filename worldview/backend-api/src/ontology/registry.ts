// Ontology registry (ticket H19.4.1) — the Palantir-style object/link/action layer projects the
// relational System-of-Record (the existing dim + stream tables) as a small, EXPLICIT graph of
// Objects + Links, plus audited Actions. This file is the declarative heart of that projection:
// it says which table(s) back each object type, how to read the latest state, and how to extract a
// human title + a typed property bag. Keeping the registry pure/declarative is what makes the
// ontology extensible — adding an object/link/action type is a data edit here, not new query code.
//
// DESIGN: an object type is either dimension-only (a slowly-changing catalog row, e.g. Aircraft's
// `aircraft` dim) optionally enriched with the LATEST row of a stream table (adsb_positions) via a
// DISTINCT ON (id) ... ts DESC join, OR a single-table projection (recon_windows, dark_vessel_events,
// geofences). The repository (repositories/ontology.ts) consumes these specs to build parameterized
// SQL; this module stays SQL-free except for the column lists / id columns it declares.

// The canonical object JSON every projection query returns. `provenance` carries the bitemporal
// pair (valid time `ts`, transaction time `ingestedAt`) + the `source` lineage handle when the
// object is backed by a stream table; dimension-only objects (e.g. an Aoi) may have null fields.
export interface OntologyObject {
  id: string;
  type: string;
  title: string;
  properties: Record<string, unknown>;
  provenance: {
    source: string | null;
    ts: number | null;
    ingestedAt: number | null;
  };
}

// The canonical link JSON: a typed, directed edge between two objects, derived from a relational FK
// / recon_window / dark_vessel_event. `properties` carries edge attributes (e.g. the recon window's
// peak time, or the dark-vessel gap). Links are READ-projected (no link table of their own).
export interface OntologyLink {
  type: string;
  fromType: string;
  fromId: string;
  toType: string;
  toId: string;
  properties: Record<string, unknown>;
}

// How an object type is projected from the SoR. `kind` selects the repository query shape:
//   * "dim-stream" — a catalog dim joined to the LATEST row of a stream table (Aircraft/Vessel/
//                    Satellite). `streamTable`/`streamIdColumn` drive the DISTINCT ON enrichment.
//   * "table"      — a single table projected directly (Aoi/ReconWindow/DarkVesselEvent).
// `idColumn` is the projected object id; `numericId` mirrors the writers' coercion (mmsi/norad_id
// are numbers, icao24 is text). `selectColumns` is the property/title source column list (raw SQL
// column expressions, already epoch-extracted where they are timestamps). `title` builds the human
// title from a projected row; `properties` builds the typed property bag (excluding provenance).
export interface ObjectTypeSpec {
  type: string;
  kind: "dim-stream" | "table";
  /** Backing table the object id + most properties come from. */
  table: string;
  idColumn: string;
  numericId: boolean;
  /** For "dim-stream": the latest-state stream table joined on idColumn. */
  streamTable?: string;
  streamIdColumn?: string;
  /** SQL column expressions selected for this object (epoch-extracted timestamps). */
  selectColumns: string[];
  /** Whether the backing/stream table carries source/ts/ingested_at provenance columns. */
  hasProvenance: boolean;
  title: (row: Record<string, unknown>) => string;
  properties: (row: Record<string, unknown>) => Record<string, unknown>;
}

const str = (v: unknown): string | null => (v == null ? null : String(v));
const num = (v: unknown): number | null => (v == null ? null : Number(v));

// ---------------------------------------------------------------------------
// OBJECT TYPES — the projected graph nodes. Title/property extractors are pure.
// ---------------------------------------------------------------------------
export const OBJECT_TYPES: Record<string, ObjectTypeSpec> = {
  // Aircraft = `aircraft` dim enriched with its latest adsb_positions fix.
  Aircraft: {
    type: "Aircraft",
    kind: "dim-stream",
    table: "aircraft",
    idColumn: "icao24",
    numericId: false,
    streamTable: "adsb_positions",
    streamIdColumn: "icao24",
    hasProvenance: true,
    selectColumns: [
      "d.icao24",
      "d.registration",
      "d.type_code",
      "d.operator",
      "d.is_military",
      "s.callsign",
      "s.alt_m",
      "s.gs_kt",
      "s.track_deg",
      "s.on_ground",
    ],
    title: (r) =>
      str(r.registration) ?? str(r.callsign) ?? `Aircraft ${String(r.icao24)}`,
    properties: (r) => ({
      icao24: str(r.icao24),
      registration: str(r.registration),
      typeCode: str(r.type_code),
      operator: str(r.operator),
      isMilitary: Boolean(r.is_military),
      callsign: str(r.callsign),
      altM: num(r.alt_m),
      gsKt: num(r.gs_kt),
      trackDeg: num(r.track_deg),
      onGround: r.on_ground == null ? null : Boolean(r.on_ground),
    }),
  },

  // Vessel = `vessels` dim enriched with its latest ais_positions fix.
  Vessel: {
    type: "Vessel",
    kind: "dim-stream",
    table: "vessels",
    idColumn: "mmsi",
    numericId: true,
    streamTable: "ais_positions",
    streamIdColumn: "mmsi",
    hasProvenance: true,
    selectColumns: [
      "d.mmsi",
      "d.imo",
      "d.name",
      "d.vessel_type",
      "d.flag",
      "d.length_m",
      "d.width_m",
      "s.sog_kt",
      "s.cog_deg",
      "s.heading_deg",
      "s.nav_status",
    ],
    title: (r) => str(r.name) ?? `Vessel ${String(r.mmsi)}`,
    properties: (r) => ({
      mmsi: str(r.mmsi),
      imo: str(r.imo),
      name: str(r.name),
      vesselType: str(r.vessel_type),
      flag: str(r.flag),
      lengthM: num(r.length_m),
      widthM: num(r.width_m),
      sogKt: num(r.sog_kt),
      cogDeg: num(r.cog_deg),
      headingDeg: num(r.heading_deg),
      navStatus: num(r.nav_status),
    }),
  },

  // Satellite = `satellites` dim enriched with its latest satellite_ephemeris fix.
  Satellite: {
    type: "Satellite",
    kind: "dim-stream",
    table: "satellites",
    idColumn: "norad_id",
    numericId: true,
    streamTable: "satellite_ephemeris",
    streamIdColumn: "norad_id",
    hasProvenance: true,
    selectColumns: [
      "d.norad_id",
      "d.name",
      "d.operator",
      "d.sensor_type",
      "d.is_classified",
      "s.velocity_kms",
      "s.is_sunlit",
    ],
    title: (r) => str(r.name) ?? `Satellite ${String(r.norad_id)}`,
    properties: (r) => ({
      noradId: str(r.norad_id),
      name: str(r.name),
      operator: str(r.operator),
      sensorType: str(r.sensor_type),
      isClassified: Boolean(r.is_classified),
      velocityKms: num(r.velocity_kms),
      isSunlit: r.is_sunlit == null ? null : Boolean(r.is_sunlit),
    }),
  },

  // Aoi = a geofence row (chokepoints / exclusion / aoi). Dimension-only (no stream provenance).
  Aoi: {
    type: "Aoi",
    kind: "table",
    table: "geofences",
    idColumn: "id",
    numericId: true,
    hasProvenance: false,
    selectColumns: [
      "id",
      "name",
      "category",
      "dark_gap_seconds",
      "extract(epoch FROM created_at) AS created_at",
    ],
    title: (r) => str(r.name) ?? `AOI ${String(r.id)}`,
    properties: (r) => ({
      id: str(r.id),
      name: str(r.name),
      category: str(r.category),
      darkGapSeconds: num(r.dark_gap_seconds),
      createdAt: num(r.created_at),
    }),
  },

  // ReconWindow = one predicted satellite overflight of an AOI. Its synthetic id is the natural
  // key joined with ':' (norad_id:aoi_id:t_ingress) since recon_windows has a composite PK.
  ReconWindow: {
    type: "ReconWindow",
    kind: "table",
    table: "recon_windows",
    idColumn: "norad_id || ':' || aoi_id || ':' || extract(epoch FROM t_ingress)",
    numericId: false,
    hasProvenance: true,
    selectColumns: [
      "(norad_id || ':' || aoi_id || ':' || extract(epoch FROM t_ingress)) AS id",
      "norad_id",
      "aoi_id",
      "sensor_type",
      "extract(epoch FROM t_ingress) AS t_ingress",
      "extract(epoch FROM t_peak) AS t_peak",
      "extract(epoch FROM t_egress) AS t_egress",
      "min_distance_km",
      "sunlit_at_peak",
      "quality",
      "source",
      "extract(epoch FROM t_peak) AS ts",
      "extract(epoch FROM ingested_at) AS ingested_at",
    ],
    title: (r) => `Recon ${String(r.norad_id)} → ${String(r.aoi_id)}`,
    properties: (r) => ({
      noradId: str(r.norad_id),
      aoiId: str(r.aoi_id),
      sensorType: str(r.sensor_type),
      tIngress: num(r.t_ingress),
      tPeak: num(r.t_peak),
      tEgress: num(r.t_egress),
      minDistanceKm: num(r.min_distance_km),
      sunlitAtPeak: r.sunlit_at_peak == null ? null : Boolean(r.sunlit_at_peak),
      quality: num(r.quality),
    }),
  },

  // DarkVesselEvent = a vessel that went silent inside a watched geofence. Composite PK (mmsi, ts);
  // synthetic id is mmsi:ts(epoch).
  DarkVesselEvent: {
    type: "DarkVesselEvent",
    kind: "table",
    table: "dark_vessel_events",
    idColumn: "mmsi || ':' || extract(epoch FROM ts)",
    numericId: false,
    hasProvenance: true,
    selectColumns: [
      "(mmsi || ':' || extract(epoch FROM ts)) AS id",
      "mmsi",
      "geofence_id",
      "extract(epoch FROM last_seen_ts) AS last_seen_ts",
      "gap_seconds",
      "status",
      "source",
      "extract(epoch FROM ts) AS ts",
      "extract(epoch FROM ingested_at) AS ingested_at",
    ],
    title: (r) => `Dark vessel ${String(r.mmsi)}`,
    properties: (r) => ({
      mmsi: str(r.mmsi),
      geofenceId: str(r.geofence_id),
      lastSeenTs: num(r.last_seen_ts),
      gapSeconds: num(r.gap_seconds),
      status: str(r.status),
    }),
  },
};

export const OBJECT_TYPE_NAMES = Object.keys(OBJECT_TYPES);

export function isObjectType(type: string): boolean {
  return type in OBJECT_TYPES;
}

export function getObjectSpec(type: string): ObjectTypeSpec | undefined {
  return OBJECT_TYPES[type];
}

// ---------------------------------------------------------------------------
// LINK TYPES — directed edges between object types, derived from relational keys. Each link type
// declares its endpoints and a `resolver` key the repository uses to pick the projection query.
// The set is intentionally small but REAL (every edge traces to a FK / recon_window / dark event):
//   * Satellite -covers-> Aoi          (via a recon_window joining norad_id + aoi_id)
//   * Vessel    -wentDark-> DarkVesselEvent  (a dark_vessel_event for that mmsi)
//   * DarkVesselEvent -inGeofence-> Aoi (the event's geofence_id FK)
// To add a link type, declare it here and add its arm to repositories/ontology.ts:linksOf.
// ---------------------------------------------------------------------------
export interface LinkTypeSpec {
  type: string;
  fromType: string;
  toType: string;
  /** Which side of the edge a getObject id binds to when listing links of an object. */
  resolver: "satCoversAoi" | "vesselWentDark" | "darkInGeofence";
  description: string;
}

export const LINK_TYPES: LinkTypeSpec[] = [
  {
    type: "covers",
    fromType: "Satellite",
    toType: "Aoi",
    resolver: "satCoversAoi",
    description: "A satellite's sensor footprint covers an AOI during a recon window.",
  },
  {
    type: "wentDark",
    fromType: "Vessel",
    toType: "DarkVesselEvent",
    resolver: "vesselWentDark",
    description: "A vessel went silent (AIS gap) inside a watched geofence.",
  },
  {
    type: "inGeofence",
    fromType: "DarkVesselEvent",
    toType: "Aoi",
    resolver: "darkInGeofence",
    description: "A dark-vessel event occurred inside a geofence/AOI.",
  },
];

export const LINK_TYPE_NAMES = LINK_TYPES.map((l) => l.type);

// ---------------------------------------------------------------------------
// ACTIONS — write operations exposed as AUDITED endpoints. Each action declares which object types
// it applies to and a pure `validate` that normalizes/guards its params (no DB here; the route +
// repository perform the audited write). First cut: `annotate` (attach a note/tag) and `watch`
// (mark an object/AOI watched). Both append an ontology_actions audit row; `annotate` also writes
// an ontology_annotations note row. Add an action by declaring it here + handling it in the route.
// ---------------------------------------------------------------------------
export interface ActionSpec {
  action: string;
  /** Object types this action may target (empty ⇒ any registered type). */
  appliesTo: string[];
  description: string;
  /** Pure param guard: returns normalized params or an error string (never throws). */
  validate: (params: Record<string, unknown>) => { params: Record<string, unknown> } | { error: string };
}

export const ACTIONS: Record<string, ActionSpec> = {
  annotate: {
    action: "annotate",
    appliesTo: [],
    description: "Attach a free-text note and optional tags to an object.",
    validate: (p) => {
      const note = typeof p.note === "string" ? p.note.trim() : "";
      if (!note) return { error: "'note' (non-empty string) is required" };
      const tags = Array.isArray(p.tags)
        ? p.tags.filter((t): t is string => typeof t === "string")
        : [];
      return { params: { note, tags } };
    },
  },
  watch: {
    action: "watch",
    appliesTo: [],
    description: "Mark an object/AOI watched (or unwatched with watched=false).",
    validate: (p) => {
      const watched = p.watched === undefined ? true : Boolean(p.watched);
      return { params: { watched } };
    },
  },
};

export const ACTION_NAMES = Object.keys(ACTIONS);

export function isAction(action: string): boolean {
  return action in ACTIONS;
}

export function getActionSpec(action: string): ActionSpec | undefined {
  return ACTIONS[action];
}

/** The full registry surface served by GET /ontology/types (object + link + action types). */
export function describeRegistry() {
  return {
    objectTypes: OBJECT_TYPE_NAMES.map((type) => {
      const spec = OBJECT_TYPES[type]!;
      return { type, kind: spec.kind, table: spec.table, idColumn: spec.idColumn };
    }),
    linkTypes: LINK_TYPES.map((l) => ({
      type: l.type,
      fromType: l.fromType,
      toType: l.toType,
      description: l.description,
    })),
    actions: ACTION_NAMES.map((action) => {
      const spec = ACTIONS[action]!;
      return {
        action,
        appliesTo: spec.appliesTo,
        description: spec.description,
      };
    }),
  };
}
