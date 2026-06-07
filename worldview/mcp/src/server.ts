// WorldView MCP server (ticket H18.3.1).
//
// Exposes the WorldView 4D OSINT REST API (`@worldview/backend-api`) as Model Context Protocol
// tools over **stdio**, so an MCP client — e.g. the JARVIS agent system — can query the platform.
//
// We use the SDK's low-level `Server` + `setRequestHandler` API (rather than the high-level
// `McpServer.registerTool`) so we can declare tool inputs as plain JSON Schema, keeping this
// package free of a direct Zod dependency and matching the backend's JSON contract 1:1.
//
// Wiring: each tool's `call` delegates to a pure handler in `./tools.ts`, injecting the configured
// backend URL and the global `fetch`. The handlers return `{ content: [{type:"text", text}], isError? }`,
// which is exactly the MCP `CallToolResult` shape, so we can forward them verbatim.

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  type CallToolResult,
  type Tool,
} from "@modelcontextprotocol/sdk/types.js";

import { apiUrl } from "./config.js";
import {
  LAYERS,
  TRACK_LAYERS,
  findDarkVessels,
  listLayers,
  stateAt,
  trackOf,
  type Deps,
  type FindDarkVesselsArgs,
  type StateAtArgs,
  type ToolResult,
  type TrackOfArgs,
} from "./tools.js";

// Dependencies handed to every pure handler. `fetch` is global in Node >= 18.
const deps: Deps = { apiUrl, fetchImpl: fetch };

// --- Tool declarations (JSON Schema input definitions) ----------------------

const TOOLS: Tool[] = [
  {
    name: "state_at",
    description:
      "As-of-T reconstruction of one WorldView layer at a unix timestamp. Returns a GeoJSON " +
      "FeatureCollection of every entity present at time t (optionally clipped to a bounding box).",
    inputSchema: {
      type: "object",
      properties: {
        layer: {
          type: "string",
          enum: [...LAYERS],
          description: "Which 4D layer to reconstruct (adsb, ais, tle, ew, context).",
        },
        t: {
          type: "number",
          description: "The instant to reconstruct, as unix seconds.",
        },
        bbox: {
          type: "string",
          description: "Optional viewport filter as 'w,s,e,n' (WGS84 degrees).",
        },
        lod: {
          type: "string",
          enum: ["raw", "minute"],
          description: "Level of detail: 'raw' points (default) or 'minute' rollups.",
        },
      },
      required: ["layer", "t"],
    },
  },
  {
    name: "find_dark_vessels",
    description:
      "Find 'dark vessels' (vessels with suspicious AIS gaps) at time t. Pulls the derived " +
      "'context' layer and returns only the dark-vessel detections as a GeoJSON FeatureCollection.",
    inputSchema: {
      type: "object",
      properties: {
        t: { type: "number", description: "The instant to inspect, as unix seconds." },
        bbox: {
          type: "string",
          description: "Optional viewport filter as 'w,s,e,n' (WGS84 degrees).",
        },
      },
      required: ["t"],
    },
  },
  {
    name: "track_of",
    description:
      "Retrieve one entity's movement trail as a GeoJSON LineString FeatureCollection. " +
      "Tracks exist only for the adsb/ais/tle layers; from/to default to the trailing hour.",
    inputSchema: {
      type: "object",
      properties: {
        layer: {
          type: "string",
          enum: [...TRACK_LAYERS],
          description: "Trackable layer (adsb, ais, tle).",
        },
        entityId: {
          type: "string",
          description: "Entity identifier (e.g. ICAO hex for adsb, MMSI for ais, NORAD id for tle).",
        },
        from: { type: "number", description: "Optional start of the window, unix seconds." },
        to: { type: "number", description: "Optional end of the window, unix seconds." },
      },
      required: ["layer", "entityId"],
    },
  },
  {
    name: "list_layers",
    description:
      "List the available WorldView 4D layers with a one-line description of each. No arguments.",
    inputSchema: { type: "object", properties: {} },
  },
];

// --- Dispatch: tool name -> pure handler ------------------------------------

async function dispatch(name: string, args: Record<string, unknown>): Promise<ToolResult> {
  switch (name) {
    case "state_at":
      return stateAt(args as unknown as StateAtArgs, deps);
    case "find_dark_vessels":
      return findDarkVessels(args as unknown as FindDarkVesselsArgs, deps);
    case "track_of":
      return trackOf(args as unknown as TrackOfArgs, deps);
    case "list_layers":
      return listLayers();
    default:
      return {
        content: [{ type: "text", text: `Unknown tool '${name}'.` }],
        isError: true,
      };
  }
}

// --- Server bootstrap -------------------------------------------------------

const server = new Server(
  { name: "@worldview/mcp", version: "0.1.0" },
  { capabilities: { tools: {} } },
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));

server.setRequestHandler(CallToolRequestSchema, async (request): Promise<CallToolResult> => {
  const { name, arguments: args } = request.params;
  const result = await dispatch(name, args ?? {});
  // `ToolResult` is structurally a `CallToolResult` (text content blocks + optional isError);
  // the SDK's broader union also admits a task-result variant we never produce.
  return result as CallToolResult;
});

async function main(): Promise<void> {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  // Stay silent on stdout (reserved for the JSON-RPC stream); log to stderr only.
  process.stderr.write(`worldview-mcp connected over stdio (backend: ${apiUrl})\n`);
}

main().catch((e: unknown) => {
  process.stderr.write(`worldview-mcp failed to start: ${(e as Error).message}\n`);
  process.exit(1);
});
