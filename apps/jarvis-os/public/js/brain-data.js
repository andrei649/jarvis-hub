/**
 * Deterministic 550-node, 1959-connection Second Brain Knowledge Graph
 * Exact counts matching AI WORKSHOP OS:
 * Categories: Router(1) + Wiki(12) + Concepts(25) + Suites(13) + Skills(197) + Tools(19) + Worlds(15) + Notes(73) + Files(195) = 550
 * Top Hubs: Skill Suites(236), Local Businesses(123), AI Workshop(82), Zubair OS(51), Claude Code(48), YouTube Channel(47), SEO Suite(38), Build and Sell series(37)
 */

export const CATEGORIES = [
  { id: "Router", count: 1, color: "#22c55e" },
  { id: "Wiki", count: 12, color: "#e2e8f0" },
  { id: "Concepts", count: 25, color: "#f59e0b" },
  { id: "Suites", count: 13, color: "#a855f7" },
  { id: "Skills", count: 197, color: "#3b82f6" },
  { id: "Tools", count: 19, color: "#ec4899" },
  { id: "Worlds", count: 15, color: "#06b6d4" },
  { id: "Notes", count: 73, color: "#f97316" },
  { id: "Files", count: 195, color: "#64748b" },
];

export const TOP_HUBS = [
  { id: "hub-skill-suites", title: "Skill Suites", displayCount: 236, color: "#eab308", pos3d: [0, 8, 0], pos2d: [0, 8] },
  { id: "hub-local-biz", title: "Local Businesses", displayCount: 123, color: "#facc15", pos3d: [36, 14, -18], pos2d: [48, 22] },
  { id: "hub-ai-workshop", title: "AI Workshop", displayCount: 82, color: "#fbbf24", pos3d: [-32, -8, 24], pos2d: [-44, -14] },
  { id: "hub-zubair-os", title: "Zubair OS", displayCount: 51, color: "#fde047", pos3d: [12, -26, 30], pos2d: [16, -38] },
  { id: "hub-claude-code", title: "Claude Code", displayCount: 48, color: "#f59e0b", pos3d: [-42, 22, -16], pos2d: [-54, 30] },
  { id: "hub-youtube", title: "YouTube Channel", displayCount: 47, color: "#a855f7", pos3d: [-58, -18, -20], pos2d: [-72, -26] },
  { id: "hub-seo-suite", title: "SEO Suite", displayCount: 38, color: "#38bdf8", pos3d: [54, -14, 22], pos2d: [68, -20] },
  { id: "hub-build-sell", title: "Build and Sell series", displayCount: 37, color: "#f97316", pos3d: [22, 42, 26], pos2d: [28, 56] },
];

const EXTRA_SUITES = [
  { title: "Marketing Suite", pos3d: [46, 32, -8], pos2d: [60, 42] },
  { title: "Finance Suite", pos3d: [-14, 48, -22], pos2d: [-20, 62] },
  { title: "Real Estate Suite", pos3d: [28, -48, -14], pos2d: [36, -64] },
  { title: "Trading Suite", pos3d: [66, -26, -12], pos2d: [82, -36] },
  { title: "Legal Suite", pos3d: [-38, -42, 12], pos2d: [-48, -56] },
];

function mulberry32(seed) {
  let t = seed >>> 0;
  return function () {
    t += 0x6d2b79f5;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}

const TOPIC_WORDS = {
  Wiki: ["Architecture", "Memory Graph", "Voice Pipeline", "Prompt Engineering", "Agent Safety", "MCP Protocol", "RAG Indexer", "Three.js Studio", "Spatial CAD", "ElevenLabs Setup", "Local Vault Sync", "Fable 5.2 Upgrade"],
  Concepts: ["Fly-To-Source Camera", "Force Graph Physics", "Exploded Vector Math", "Idempotent Scene Edits", "Tilt-Shift Bokeh", " Butler Persona", "Autonomous Browser", "Multi-Brain Routing", "Context Compaction", "Semantic Linking", "Zero-Latency Wake", "Subagent Swarm"],
  Tools: ["3D Workshop Engine", "Floor Plan Architect", "Miniature Renderer", "Meta Ads Driver", "Brain Switcher", "Voice Transcriber", "Daniel TTS Stream", "Vault Markdown Parser", "Graph Path Tracer", "Optical Webcam Sensor", "Holo Hand Gesture", "Token Telemetry", "Snapshot Exporter"],
  Worlds: ["Jarvis Reactor Companion", "Pool Home Plan 3D", "Desert Diorama Miniature", "Second Brain Constellation", "Acoustic Chassis Lab", "Smart Villa Lanai", "Meta Campaign Sandbox", "Executive Briefing Room"],
  Skills: ["Lead Gen Funnel", "Cold Email Personalizer", "GEO SEO Audit", "Local Plumber AI Receptionist", "Dental Booking Agent", "Real Estate Comps", "Landing Page Builder", "Ad Copy Optimizer", "YouTube Hook Writer", "Thumbnail Critic", "Transcript Summarizer", "Skool Onboarding Bot", "Invoice Reconciler", "Contract Clause Checker", "Competitor Watcher", "Floorplan Extruder", "PBR Shader Tuner"],
  Notes: ["Q4 AI Workshop Roadmap", "Fable 5.2 Benchmark Notes", "Jarvis Hardware BOM", "Emerald Reactor Lighting Spec", "Pool Villa Client Brief", "Meta Ads Skool Funnel", "Voice Latency Optimization", "Prompt Pack v4 Release", "Daily Standup Log", "Subscriber Milestone Plan"],
  Files: ["jarvis_system_prompt.md", "workshop_scene_spec.ts", "pool_home_blueprint.svg", "reactor_exploded_offsets.json", "meta_ads_playbook.md", "elevenlabs_voice_profile.json", "geo_seo_checklist.md", "skool_launch_sequence.md", "local_agency_pricing.csv", "fable_52_migration.md"],
};

export function createBrainDataset() {
  const rand = mulberry32(47192026);
  const nodes = [];
  const categoryColorMap = Object.fromEntries(CATEGORIES.map((c) => [c.id, c.color]));

  // 0. Core Router (1)
  nodes.push({
    index: 0,
    id: "node-0",
    title: "AI Workshop OS Core Router",
    category: "Router",
    color: categoryColorMap.Router,
    isHub: true,
    hubLabel: "AI Workshop OS",
    radius: 3.1,
    base3d: [0, 0, 0],
    base2d: [0, 0],
    body: `# AI Workshop OS Core Router\nCentral orchestration kernel connecting **550 knowledge nodes** across **1,959 semantic links**.\n\n- Routes voice & text intents between **Claude Opus 5.5** and **Claude Fable 5.2**\n- Manages sandboxed Three.js **3D Workshop** (\`Jarvis Reactor Companion\` & \`Pool Home Plan\`)\n- Drives autonomous browser workflows in **Computer Use** mode.`,
  });

  // 1..8 Top Hubs + 5 Extra Suites = 13 "Suites"
  const allSuites = [
    ...TOP_HUBS.map((h) => ({ ...h, isTopHub: true })),
    ...EXTRA_SUITES.map((s, idx) => ({
      id: `suite-extra-${idx}`,
      title: s.title,
      displayCount: 24 + idx * 3,
      color: "#a855f7",
      pos3d: s.pos3d,
      pos2d: s.pos2d,
      isTopHub: false,
    })),
  ];

  allSuites.forEach((s) => {
    const idx = nodes.length;
    nodes.push({
      index: idx,
      id: s.id,
      title: s.title,
      category: "Suites",
      color: s.isTopHub ? s.color : categoryColorMap.Suites,
      isHub: true,
      isTopHub: s.isTopHub,
      displayCount: s.displayCount,
      hubLabel: s.title,
      radius: s.isTopHub ? 2.65 : 2.1,
      base3d: [...s.pos3d],
      base2d: [...s.pos2d],
      body: `# ${s.title}\nPrimary knowledge cluster inside **AI Workshop OS**.\n\n- Connected workflows, SOPs, skills, and local Markdown vaults\n- Click any satellite orb to read its underlying note, or **Shift-click** another hub to trace the semantic bridge.`,
    });
  });

  // Remaining categories to reach exactly 550 nodes
  const remainingSpec = CATEGORIES.filter((c) => c.id !== "Router" && c.id !== "Suites");

  remainingSpec.forEach((spec) => {
    const pool = TOPIC_WORDS[spec.id] || ["Knowledge Item"];
    for (let i = 0; i < spec.count; i++) {
      const idx = nodes.length;
      const parentSuite = allSuites[Math.floor(rand() * allSuites.length)];
      const theta = rand() * Math.PI * 2;
      const phi = Math.acos(2 * rand() - 1);
      const dist = 7 + Math.pow(rand(), 0.72) * 26;

      const ox = Math.sin(phi) * Math.cos(theta) * dist;
      const oy = Math.sin(phi) * Math.sin(theta) * dist * 0.85;
      const oz = Math.cos(phi) * dist;

      const baseLabel = pool[i % pool.length];
      const suffix = i >= pool.length ? ` #${Math.floor(i / pool.length) + 1}` : "";
      const title = `${baseLabel}${suffix}`;

      nodes.push({
        index: idx,
        id: `node-${idx}`,
        title,
        category: spec.id,
        color: spec.color,
        parentHubIndex: nodes.findIndex((n) => n.title === parentSuite.title),
        offset3d: [ox, oy, oz],
        base3d: [
          parentSuite.pos3d[0] + ox,
          parentSuite.pos3d[1] + oy,
          parentSuite.pos3d[2] + oz,
        ],
        base2d: [
          parentSuite.pos2d[0] + Math.cos(theta) * (dist * 1.15),
          parentSuite.pos2d[1] + Math.sin(theta) * (dist * 1.15),
        ],
        radius: spec.id === "Worlds" || spec.id === "Tools" ? 1.25 : spec.id === "Wiki" || spec.id === "Concepts" ? 1.1 : 0.78,
        body: `### ${title}\n**Category:** ${spec.id} · **Cluster:** ${parentSuite.title}\n\nIndexed inside your local Second Brain vault. J.A.R.V.I.S. can synthesize this ${spec.id.toLowerCase()} entry during live voice sessions, link it to 3D Workshop builds, or trigger downstream automations.`,
      });
    }
  });

  // Build exactly 1,959 unique undirected edges
  const TARGET_EDGES = 1959;
  const edgeSet = new Set();
  const edges = [];
  const adjacency = Array.from({ length: nodes.length }, () => []);

  function addEdge(a, b) {
    if (a === b || a < 0 || b < 0 || a >= nodes.length || b >= nodes.length) return false;
    const u = Math.min(a, b);
    const v = Math.max(a, b);
    const key = `${u}:${v}`;
    if (edgeSet.has(key)) return false;
    edgeSet.add(key);
    edges.push([u, v]);
    adjacency[u].push(v);
    adjacency[v].push(u);
    return true;
  }

  // 1. Connect Core Router (0) to all 13 Suite Hubs (1..13)
  for (let h = 1; h <= 13; h++) {
    addEdge(0, h);
    if (h < 13) addEdge(h, h + 1);
  }
  addEdge(1, 13);

  // 2. Connect every satellite node to its parent hub + 1-2 nearby siblings
  for (let i = 14; i < nodes.length; i++) {
    const p = nodes[i].parentHubIndex || 1;
    addEdge(i, p);
  }

  // 3. Fill up to exactly 1,959 connections preferentially within clusters & cross-bridges
  while (edges.length < TARGET_EDGES) {
    const a = Math.floor(rand() * nodes.length);
    if (rand() < 0.76 && nodes[a].parentHubIndex) {
      // Connect within same hub cluster or to sibling
      const candidate = 14 + Math.floor(rand() * (nodes.length - 14));
      if (nodes[candidate].parentHubIndex === nodes[a].parentHubIndex || rand() < 0.18) {
        addEdge(a, candidate);
      }
    } else {
      const b = Math.floor(rand() * nodes.length);
      addEdge(a, b);
    }
  }

  function findShortestPath(startIdx, endIdx) {
    if (startIdx === endIdx) return [startIdx];
    const visited = new Uint8Array(nodes.length);
    const prev = new Int32Array(nodes.length).fill(-1);
    const queue = [startIdx];
    visited[startIdx] = 1;

    while (queue.length > 0) {
      const curr = queue.shift();
      if (curr === endIdx) break;
      for (const next of adjacency[curr]) {
        if (!visited[next]) {
          visited[next] = 1;
          prev[next] = curr;
          queue.push(next);
        }
      }
    }
    if (!visited[endIdx]) return null;
    const path = [];
    for (let at = endIdx; at !== -1; at = prev[at]) {
      path.push(at);
    }
    return path.reverse();
  }

  return {
    mode: "demo_550",
    brandTitle: "AI WORKSHOP OS",
    vaultLabel: "Video Showcase Demo (550 nodes)",
    nodes,
    edges,
    adjacency,
    categories: CATEGORIES,
    topHubs: TOP_HUBS.map((h) => ({
      ...h,
      nodeIndex: nodes.findIndex((n) => n.title === h.title),
    })),
    findShortestPath,
  };
}

/**
 * Hydrates a real Second Brain graph returned by GET /api/brain
 * into the exact structure consumed by KnowledgeGalaxy.
 */
export function hydrateServerBrainDataset(apiData) {
  const nodes = apiData.nodes || [];
  const edges = apiData.edges || [];
  const adjacency = Array.from({ length: nodes.length }, () => []);

  for (const [u, v] of edges) {
    if (u >= 0 && v >= 0 && u < nodes.length && v < nodes.length) {
      adjacency[u].push(v);
      adjacency[v].push(u);
    }
  }

  function findShortestPath(startIdx, endIdx) {
    if (startIdx === endIdx) return [startIdx];
    if (startIdx < 0 || endIdx < 0 || startIdx >= nodes.length || endIdx >= nodes.length) return null;
    const visited = new Uint8Array(nodes.length);
    const prev = new Int32Array(nodes.length).fill(-1);
    const queue = [startIdx];
    visited[startIdx] = 1;

    while (queue.length > 0) {
      const curr = queue.shift();
      if (curr === endIdx) break;
      for (const next of adjacency[curr]) {
        if (!visited[next]) {
          visited[next] = 1;
          prev[next] = curr;
          queue.push(next);
        }
      }
    }
    if (!visited[endIdx]) return null;
    const path = [];
    for (let at = endIdx; at !== -1; at = prev[at]) {
      path.push(at);
    }
    return path.reverse();
  }

  return {
    mode: apiData.mode || "andrei_plus_nerva",
    brandTitle: apiData.brandTitle || "ANDREI OS",
    vaultLabel: apiData.vaultLabel || "Andrei OS Obsidian",
    vaultPath: apiData.vaultPath || "",
    nodes,
    edges,
    adjacency,
    categories: apiData.categories || [],
    topHubs: apiData.topHubs || [],
    discoveredSources: apiData.discoveredSources || [],
    findShortestPath,
  };
}
