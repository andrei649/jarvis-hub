export type FieldAgent = { id: string; tier: string; status: string };
export type FieldTask = { owner: string; state: string };
export type FieldVoice = {
  status: 'off' | 'idle' | 'listening' | 'stopping' | 'transcribing' | 'speaking' | 'error';
  level?: number;
  error?: boolean;
};

export type FieldRegion = {
  key: string; label: string; color: string;
  count: number; busy: number; running: number; markerCount: number;
};
export type FieldMarker = { x: number; y: number; region: number; phase: number };
export type FieldEdge = { from: number; to: number };
export type FieldModel = {
  regions: FieldRegion[]; markers: FieldMarker[]; edges: FieldEdge[];
  totalAgents: number; runningTasks: number; unassignedRunningTasks: number;
};

const COLORS: Record<string, string> = {
  cns: '#2bb8f0', command: '#2bb8f0', bus: '#ffb23f', business: '#ffb23f',
  tec: '#a78bfa', tech: '#a78bfa', fnd: '#41f59b', foundation: '#41f59b',
};
const OTHER_COLORS = ['#5fa8d8', '#e89fd1', '#d7c879', '#70d5c7'];
const MAX_MARKERS = 96;
const MAX_REGIONS = 8;

function validText(value: unknown): string { return typeof value === 'string' ? value.trim() : ''; }
function hash(value: string): number {
  let result = 2166136261;
  for (let index = 0; index < value.length; index++) result = Math.imul(result ^ value.charCodeAt(index), 16777619);
  return result >>> 0;
}
function plural(count: number, noun: string) { return `${count} ${noun}${count === 1 ? '' : 's'}`; }

export function buildBriefingField(agents: FieldAgent[], tasks: FieldTask[]): FieldModel {
  const roster = (Array.isArray(agents) ? agents : []).filter(agent => agent && typeof agent === 'object');
  const groups = new Map<string, { label: string; agents: FieldAgent[]; busy: number; running: number }>();
  const owners = new Map<string, string | null>();
  for (const agent of roster) {
    const tier = validText(agent.tier);
    const key = tier.toLowerCase() || 'unclassified';
    const group = groups.get(key) ?? { label: tier || 'Unclassified', agents: [], busy: 0, running: 0 };
    if (tier && tier.localeCompare(group.label) < 0) group.label = tier;
    group.agents.push(agent);
    if (['busy', 'active'].includes(validText(agent.status).toLowerCase())) group.busy++;
    groups.set(key, group);
    const id = validText(agent.id).toLowerCase();
    if (id && !owners.has(id)) owners.set(id, key);
    else if (id && owners.get(id) !== key) owners.set(id, null);
  }
  const ordered = [...groups.keys()].sort();
  const keep = new Set(ordered.length <= MAX_REGIONS ? ordered : ordered.slice(0, MAX_REGIONS - 1));
  let overflowKey = 'other';
  if (keep.has(overflowKey) && ordered.length > MAX_REGIONS) {
    overflowKey = '__other_tiers__';
    while (groups.has(overflowKey)) overflowKey += '_';
  }
  const actual = new Map<string, { label: string; agents: FieldAgent[]; busy: number; running: number }>();
  for (const key of ordered) {
    const target = keep.has(key) ? key : overflowKey;
    const source = groups.get(key)!;
    const group = actual.get(target) ?? { label: target === overflowKey && !keep.has(target) ? 'Other reported tiers' : source.label,
      agents: [], busy: 0, running: 0 };
    for (const agent of source.agents) group.agents.push(agent);
    group.busy += source.busy;
    actual.set(target, group);
  }
  let runningTasks = 0;
  let unassignedRunningTasks = 0;
  for (const task of Array.isArray(tasks) ? tasks : []) {
    if (!task || validText(task.state).toLowerCase() !== 'running') continue;
    runningTasks++;
    const owner = owners.get(validText(task.owner).toLowerCase());
    const region = owner ? actual.get(keep.has(owner) ? owner : overflowKey) : undefined;
    if (region) region.running++;
    else unassignedRunningTasks++;
  }
  const regions: FieldRegion[] = [...actual.entries()].sort(([left], [right]) => left.localeCompare(right))
    .map(([key, group], index) => ({ key, label: group.label,
      color: COLORS[key] ?? OTHER_COLORS[hash(key) % OTHER_COLORS.length],
      count: group.agents.length, busy: group.busy, running: group.running, markerCount: 0 }));
  const queues = regions.map(region => [...actual.get(region.key)!.agents].sort((left, right) =>
    validText(left.id).localeCompare(validText(right.id))));
  const markers: FieldMarker[] = [];
  const edges: FieldEdge[] = [];
  const regionMarkers: number[][] = regions.map(() => []);
  while (markers.length < MAX_MARKERS && queues.some(queue => queue.length)) {
    for (let regionIndex = 0; regionIndex < regions.length && markers.length < MAX_MARKERS; regionIndex++) {
      const agent = queues[regionIndex].shift();
      if (!agent) continue;
      const serial = regions[regionIndex].markerCount++;
      const seed = hash(`${regions[regionIndex].key}/${validText(agent.id)}/${serial}`);
      const angle = -Math.PI / 2 + (regionIndex + 0.5) * (2 * Math.PI / regions.length)
        + (((seed & 255) / 255) - 0.5) * Math.min(0.55, Math.PI / regions.length);
      const radius = 0.12 + (serial % 6) * 0.047 + (((seed >>> 8) & 255) / 255) * 0.025;
      const markerIndex = markers.length;
      markers.push({ x: Math.max(0, Math.min(1, 0.5 + Math.cos(angle) * radius)),
        y: Math.max(0, Math.min(1, 0.5 + Math.sin(angle) * radius)),
        region: regionIndex, phase: ((seed >>> 16) & 255) / 255 });
      const previous = regionMarkers[regionIndex];
      if (previous.length) edges.push({ from: previous[previous.length - 1], to: markerIndex });
      if (previous.length > 1) edges.push({ from: previous[previous.length - 2], to: markerIndex });
      previous.push(markerIndex);
    }
  }
  return { regions, markers, edges, totalAgents: roster.length, runningTasks, unassignedRunningTasks };
}

export function fieldEnergy(agents: FieldAgent[], tasks: FieldTask[], voice: FieldVoice):
  { source: string; level: number } {
  const status = voice?.status;
  if (status === 'listening') {
    if (typeof voice.level === 'number' && Number.isFinite(voice.level)) {
      return { source: 'measured mic level', level: Math.max(0, Math.min(1, voice.level)) };
    }
    return { source: 'voice state, no measured level', level: 0 };
  }
  if (status === 'speaking' || status === 'transcribing') return { source: 'voice state', level: 0.42 };
  const busy = (Array.isArray(agents) ? agents : []).filter(agent =>
    ['busy', 'active'].includes(validText(agent?.status).toLowerCase())).length;
  const running = (Array.isArray(tasks) ? tasks : []).filter(task => validText(task?.state).toLowerCase() === 'running').length;
  if (busy || running) return { source: 'reported work', level: Math.min(1, busy * 0.18 + running * 0.1) };
  return { source: 'idle', level: 0 };
}
