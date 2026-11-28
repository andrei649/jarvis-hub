import { ApiError, normalizeBaseUrl } from './client';
import type { ServerConfig } from '../storage/settings';

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function buildHeaders(config: ServerConfig, json: boolean, admin: boolean): Record<string, string> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (json) headers['Content-Type'] = 'application/json';
  if (config.token.trim()) headers['X-User-Token'] = config.token.trim();
  if (admin && config.adminToken.trim()) headers['X-Admin-Token'] = config.adminToken.trim();
  return headers;
}

async function governedJson<T>(
  config: ServerConfig,
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
  path: string,
  opts: { body?: unknown; admin?: boolean; signal?: AbortSignal } = {},
): Promise<T> {
  const base = normalizeBaseUrl(config.baseUrl);
  if (!base) throw new ApiError('No server URL configured');
  if (opts.admin && !config.adminToken.trim()) {
    throw new ApiError('Admin token required — add one in Settings', 403);
  }
  const controller = new AbortController();
  const forwardAbort = () => controller.abort();
  opts.signal?.addEventListener('abort', forwardAbort);
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const res = await fetch(base + path, {
      method,
      headers: buildHeaders(config, opts.body !== undefined, opts.admin === true),
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: controller.signal,
      cache: 'no-store',
    });
    let payload: unknown = null;
    try {
      payload = await res.json();
    } catch {
      payload = null;
    }
    if (!res.ok) {
      const detail = isRecord(payload)
        ? (typeof payload.error === 'string' && payload.error.trim()
          ? payload.error
          : typeof payload.detail === 'string' && payload.detail.trim()
            ? payload.detail
            : '')
        : '';
      if (res.status === 401) throw new ApiError(detail || 'Unauthorized — check your user token', 401);
      if (res.status === 403) throw new ApiError(detail || 'Admin access required or denied by kernel', 403);
      throw new ApiError(detail || `Server returned HTTP ${res.status}`, res.status);
    }
    return payload as T;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (opts.signal?.aborted) throw new ApiError('Request cancelled', 499);
    throw new ApiError(`Could not reach ${base}`);
  } finally {
    clearTimeout(timer);
    opts.signal?.removeEventListener('abort', forwardAbort);
  }
}

// ── H422 / H18.35: Curated Memory Governance (/api/memory, switch, reset) ──

export type MemoryStoreBudget = {
  chars: number;
  max_chars: number;
  entries: number;
};

export type MemoryGovernanceStatus = {
  available: boolean;
  enabled: boolean;
  switch: boolean;
  block_max_chars: number;
  memory: MemoryStoreBudget;
  user: MemoryStoreBudget;
};

function parseBudget(raw: unknown): MemoryStoreBudget {
  if (!isRecord(raw)) return { chars: 0, max_chars: 0, entries: 0 };
  const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? Math.trunc(v) : 0);
  return {
    chars: num(raw.chars),
    max_chars: num(raw.char_budget !== undefined ? raw.char_budget : raw.max_chars),
    entries: num(raw.entries),
  };
}

export async function fetchMemoryGovernance(
  config: ServerConfig,
  signal?: AbortSignal,
): Promise<MemoryGovernanceStatus> {
  const raw = await governedJson<unknown>(config, 'GET', '/api/memory', { signal });
  if (!isRecord(raw) || typeof raw.enabled !== 'boolean') {
    throw new ApiError('Invalid memory governance payload');
  }
  const stores = isRecord(raw.stores) ? raw.stores : {};
  return {
    available: Boolean(raw.available),
    enabled: raw.enabled,
    switch: typeof raw.switch === 'boolean' ? raw.switch : raw.enabled,
    block_max_chars: typeof raw.block_max_chars === 'number' ? raw.block_max_chars : 0,
    memory: parseBudget(stores.memory),
    user: parseBudget(stores.user),
  };
}

export async function setMemorySwitch(
  config: ServerConfig,
  enabled: boolean,
): Promise<{ ok: boolean; switch: boolean; enabled: boolean }> {
  const raw = await governedJson<unknown>(config, 'POST', '/api/memory/switch', {
    admin: true,
    body: { enabled },
  });
  if (!isRecord(raw)) throw new ApiError('Invalid memory switch response');
  const nextSwitch = typeof raw.switch === 'boolean' ? raw.switch : enabled;
  return {
    ok: raw.ok !== false,
    switch: nextSwitch,
    enabled: typeof raw.enabled === 'boolean' ? raw.enabled : nextSwitch,
  };
}

export type MemoryResetTarget = 'all' | 'memory' | 'user';

export async function resetCuratedMemory(
  config: ServerConfig,
  target: MemoryResetTarget,
  confirm: string,
): Promise<{ ok: boolean; cleared: string[] }> {
  if (confirm !== 'RESET') {
    throw new ApiError('Type RESET in capitals to confirm clearing curated memory', 400);
  }
  if (!['all', 'memory', 'user'].includes(target)) {
    throw new ApiError('Invalid memory reset target', 400);
  }
  const raw = await governedJson<unknown>(config, 'POST', '/api/memory/reset', {
    admin: true,
    body: { target, confirm: 'RESET' },
  });
  if (!isRecord(raw)) throw new ApiError('Invalid memory reset response');
  const cleared = Array.isArray(raw.cleared) ? raw.cleared.map(String) : [target];
  return { ok: raw.ok !== false, cleared };
}

// ── H026 / H18.35: Skill Bundles (/api/skills/bundles*, /api/skills/switch) ──

export type SkillBundleItem = {
  name: string;
  slug: string;
  description: string;
  skills: string[];
  installed: string[];
  missing: string[];
};

function parseSkillBundle(raw: unknown): SkillBundleItem | null {
  if (!isRecord(raw) || typeof raw.name !== 'string' || !raw.name.trim()) return null;
  const strList = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []);
  return {
    name: raw.name.trim(),
    slug: typeof raw.slug === 'string' && raw.slug.trim() ? raw.slug.trim() : raw.name.trim().toLowerCase(),
    description: typeof raw.description === 'string' ? raw.description : '',
    skills: strList(raw.skills),
    installed: strList(raw.installed),
    missing: strList(raw.missing),
  };
}

export async function fetchSkillBundles(
  config: ServerConfig,
  signal?: AbortSignal,
): Promise<{ bundles: SkillBundleItem[]; problemCount: number }> {
  const raw = await governedJson<unknown>(config, 'GET', '/api/skills/bundles', { signal });
  if (!isRecord(raw) || !Array.isArray(raw.bundles)) {
    throw new ApiError('Invalid skill bundles response');
  }
  const bundles = raw.bundles.map(parseSkillBundle).filter((b): b is SkillBundleItem => b !== null);
  const problemCount = Array.isArray(raw.problems) ? raw.problems.length : 0;
  return { bundles, problemCount };
}

export async function saveSkillBundle(
  config: ServerConfig,
  input: { name: string; skills: string[]; description?: string; overwrite?: boolean },
): Promise<SkillBundleItem> {
  const name = input.name.trim();
  const skills = input.skills.map(s => s.trim()).filter(Boolean);
  if (!name || skills.length === 0) {
    throw new ApiError('Bundle name and at least one installed skill are required', 422);
  }
  const raw = await governedJson<unknown>(config, 'POST', '/api/skills/bundles', {
    admin: true,
    body: {
      name,
      skills,
      description: (input.description ?? '').trim(),
      overwrite: Boolean(input.overwrite),
    },
  });
  const parsed = isRecord(raw) ? parseSkillBundle(raw.bundle) : null;
  if (!parsed) throw new ApiError('Invalid saved bundle response');
  return parsed;
}

export async function deleteSkillBundle(config: ServerConfig, name: string): Promise<void> {
  const trimmed = name.trim();
  if (!trimmed) throw new ApiError('Bundle name is required', 400);
  await governedJson<unknown>(
    config,
    'DELETE',
    `/api/skills/bundles/${encodeURIComponent(trimmed)}`,
    { admin: true },
  );
}

export type SkillBundleSwitchResult = {
  status: 'pending' | 'applied';
  taskId: string | null;
  bundle: string;
  missing: string[];
};

export async function switchSkillBundle(
  config: ServerConfig,
  bundle: string,
  enabled: boolean,
): Promise<SkillBundleSwitchResult> {
  const trimmed = bundle.trim();
  if (!trimmed) throw new ApiError('Bundle name is required', 422);
  const raw = await governedJson<unknown>(config, 'POST', '/api/skills/switch', {
    admin: true,
    body: { bundle: trimmed, enabled },
  });
  if (!isRecord(raw)) throw new ApiError('Invalid bundle switch response');
  return {
    status: raw.status === 'pending' ? 'pending' : 'applied',
    taskId: typeof raw.task_id === 'string' ? raw.task_id : null,
    bundle: typeof raw.bundle === 'string' ? raw.bundle : trimmed,
    missing: Array.isArray(raw.missing) ? raw.missing.map(String) : [],
  };
}

// ── H202 / H18.37: Agent Roster (/api/admin/agents/roster, create/rename/retire/restore) ──

export type RosterAgentItem = {
  id: string;
  name: string;
  status: 'active' | 'retired' | string;
  live: boolean;
  created: boolean;
  protected: boolean;
  template: string | null;
  reason: string;
  revision: number;
};

export type RosterTemplateItem = {
  key: string;
  name: string;
  description: string;
};

export type AgentRosterView = {
  agents: RosterAgentItem[];
  templates: RosterTemplateItem[];
  tiers: string[];
  safeMode: boolean;
  error?: string;
};

function parseRosterAgent(raw: unknown): RosterAgentItem | null {
  if (!isRecord(raw) || typeof raw.id !== 'string' || !raw.id.trim()) return null;
  return {
    id: raw.id.trim(),
    name: typeof raw.name === 'string' && raw.name.trim() ? raw.name.trim() : raw.id.trim(),
    status: typeof raw.status === 'string' ? raw.status : 'active',
    live: Boolean(raw.live),
    created: Boolean(raw.created),
    protected: Boolean(raw.protected),
    template: typeof raw.template === 'string' ? raw.template : null,
    reason: typeof raw.reason === 'string' ? raw.reason : '',
    revision: typeof raw.revision === 'number' && Number.isFinite(raw.revision) ? raw.revision : 0,
  };
}

export async function fetchAgentRoster(config: ServerConfig, signal?: AbortSignal): Promise<AgentRosterView> {
  const raw = await governedJson<unknown>(config, 'GET', '/api/admin/agents/roster', {
    admin: true,
    signal,
  });
  if (!isRecord(raw) || !Array.isArray(raw.agents)) {
    throw new ApiError('Invalid agent roster response');
  }
  const agents = raw.agents.map(parseRosterAgent).filter((a): a is RosterAgentItem => a !== null);
  const templates = Array.isArray(raw.templates)
    ? raw.templates
        .filter(isRecord)
        .filter(t => typeof t.key === 'string' && t.key.trim())
        .map(t => ({
          key: String(t.key),
          name: typeof t.name === 'string' ? t.name : String(t.key),
          description: typeof t.description === 'string' ? t.description : '',
        }))
    : [];
  const tiers = Array.isArray(raw.tiers) ? raw.tiers.filter((t): t is string => typeof t === 'string') : [];
  return {
    agents,
    templates,
    tiers,
    safeMode: Boolean(raw.safe_mode),
    ...(typeof raw.error === 'string' ? { error: raw.error } : {}),
  };
}

export async function createRosterAgent(
  config: ServerConfig,
  input: { name: string; template?: string; tier?: string },
): Promise<RosterAgentItem> {
  const name = input.name.trim();
  if (!name) throw new ApiError('Agent display name is required', 422);
  const raw = await governedJson<unknown>(config, 'POST', '/api/admin/agents', {
    admin: true,
    body: {
      name,
      template: (input.template ?? '').trim(),
      tier: (input.tier ?? '').trim(),
    },
  });
  const parsed = isRecord(raw) ? parseRosterAgent(raw.agent) : null;
  if (!parsed) throw new ApiError('Invalid create agent response');
  return parsed;
}

export async function renameRosterAgent(
  config: ServerConfig,
  agentId: string,
  name: string,
): Promise<RosterAgentItem> {
  const id = agentId.trim().toLowerCase();
  const trimmed = name.trim();
  if (!id || !trimmed) throw new ApiError('Agent ID and new name are required', 422);
  const raw = await governedJson<unknown>(
    config,
    'POST',
    `/api/admin/agents/${encodeURIComponent(id)}/rename`,
    { admin: true, body: { name: trimmed } },
  );
  const parsed = isRecord(raw) ? parseRosterAgent(raw.agent) : null;
  if (!parsed) throw new ApiError('Invalid rename agent response');
  return parsed;
}

export async function retireRosterAgent(
  config: ServerConfig,
  agentId: string,
  confirm: string,
  reason = '',
): Promise<RosterAgentItem> {
  const id = agentId.trim().toLowerCase();
  if (!id) throw new ApiError('Agent ID is required', 400);
  if (confirm.trim().toLowerCase() !== id) {
    throw new ApiError(`Type "${id}" to confirm retiring this agent`, 400);
  }
  const raw = await governedJson<unknown>(
    config,
    'POST',
    `/api/admin/agents/${encodeURIComponent(id)}/retire`,
    { admin: true, body: { confirm: id, reason: reason.trim() } },
  );
  const parsed = isRecord(raw) ? parseRosterAgent(raw.agent) : null;
  if (!parsed) throw new ApiError('Invalid retire agent response');
  return parsed;
}

export async function restoreRosterAgent(config: ServerConfig, agentId: string): Promise<RosterAgentItem> {
  const id = agentId.trim().toLowerCase();
  if (!id) throw new ApiError('Agent ID is required', 400);
  const raw = await governedJson<unknown>(
    config,
    'POST',
    `/api/admin/agents/${encodeURIComponent(id)}/restore`,
    { admin: true },
  );
  const parsed = isRecord(raw) ? parseRosterAgent(raw.agent) : null;
  if (!parsed) throw new ApiError('Invalid restore agent response');
  return parsed;
}

// ── H046 / H18.37: Today Learned Entries (/api/dashboard/today/entries*) ──

export type LearnedStoreKind = 'facts' | 'memory' | 'user' | 'skill';

export type LearnedEntryItem = {
  id: string;
  store: LearnedStoreKind | string;
  value: string;
  key?: string;
  category?: string;
  pendingReview?: boolean;
};

function parseLearnedEntry(raw: unknown): LearnedEntryItem | null {
  if (!isRecord(raw)) return null;
  const id = typeof raw.id === 'string' ? raw.id : typeof raw.entry_id === 'string' ? raw.entry_id : '';
  if (!id.trim()) return null;
  const value = typeof raw.value === 'string'
    ? raw.value
    : typeof raw.description === 'string'
      ? raw.description
      : typeof raw.summary === 'string'
        ? raw.summary
        : '';
  return {
    id: id.trim(),
    store: typeof raw.store === 'string' ? raw.store : 'facts',
    value,
    ...(typeof raw.key === 'string' ? { key: raw.key } : {}),
    ...(typeof raw.category === 'string' ? { category: raw.category } : {}),
    ...(typeof raw.pending_review === 'boolean' ? { pendingReview: raw.pending_review } : {}),
  };
}

export async function fetchLearnedEntries(
  config: ServerConfig,
  opts: { store?: LearnedStoreKind; limit?: number; signal?: AbortSignal } = {},
): Promise<{ entries: LearnedEntryItem[]; total: number; counts: Record<string, number>; drift?: string }> {
  const params = new URLSearchParams();
  params.set('limit', String(opts.limit ?? 50));
  if (opts.store) params.set('store', opts.store);
  const raw = await governedJson<unknown>(
    config,
    'GET',
    `/api/dashboard/today/entries?${params.toString()}`,
    { signal: opts.signal },
  );
  if (!isRecord(raw) || !Array.isArray(raw.entries)) {
    throw new ApiError('Invalid learned entries response');
  }
  const entries = raw.entries.map(parseLearnedEntry).filter((e): e is LearnedEntryItem => e !== null);
  const counts: Record<string, number> = {};
  if (isRecord(raw.counts)) {
    for (const [k, v] of Object.entries(raw.counts)) {
      if (typeof v === 'number' && Number.isFinite(v)) counts[k] = v;
    }
  }
  return {
    entries,
    total: typeof raw.total === 'number' ? raw.total : entries.length,
    counts,
    ...(typeof raw.drift === 'string' && raw.drift ? { drift: raw.drift } : {}),
  };
}

export type LearnedEntryDetail = LearnedEntryItem & {
  content: string | null;
  contentWithheld: string | null;
};

export async function fetchLearnedEntryDetail(
  config: ServerConfig,
  entryId: string,
  signal?: AbortSignal,
): Promise<LearnedEntryDetail> {
  const id = entryId.trim();
  if (!id) throw new ApiError('Entry ID is required', 400);
  const raw = await governedJson<unknown>(
    config,
    'GET',
    `/api/dashboard/today/entries/${encodeURIComponent(id)}`,
    { signal },
  );
  const entryObj = isRecord(raw) && isRecord(raw.entry) ? raw.entry : null;
  const base = parseLearnedEntry(entryObj);
  if (!entryObj || !base) throw new ApiError('Invalid learned entry detail response');
  return {
    ...base,
    content: typeof entryObj.content === 'string' ? entryObj.content : null,
    contentWithheld: typeof entryObj.content_withheld === 'string' ? entryObj.content_withheld : null,
  };
}

export async function editLearnedEntry(
  config: ServerConfig,
  entryId: string,
  value: string,
): Promise<{ changed: boolean; entry: LearnedEntryItem | null }> {
  const id = entryId.trim();
  const trimmed = value.trim();
  if (!id || !trimmed) throw new ApiError('Entry ID and non-empty value are required', 400);
  const raw = await governedJson<unknown>(
    config,
    'PATCH',
    `/api/dashboard/today/entries/${encodeURIComponent(id)}`,
    { admin: true, body: { value: trimmed } },
  );
  if (!isRecord(raw)) throw new ApiError('Invalid learned entry edit response');
  return {
    changed: Boolean(raw.changed),
    entry: parseLearnedEntry(raw.entry),
  };
}

export async function deleteLearnedEntry(config: ServerConfig, entryId: string): Promise<{ deleted: string }> {
  const id = entryId.trim();
  if (!id) throw new ApiError('Entry ID is required', 400);
  const raw = await governedJson<unknown>(
    config,
    'DELETE',
    `/api/dashboard/today/entries/${encodeURIComponent(id)}`,
    { admin: true },
  );
  if (!isRecord(raw)) throw new ApiError('Invalid learned entry delete response');
  return { deleted: typeof raw.deleted === 'string' ? raw.deleted : id };
}

// ── H18.38: ANDREI OS Vault & Workshop (/api/os/status, reindex, workshop/projects) ──

export type OsStatusSnapshot = {
  vaultMode: string;
  vaultPath: string;
  vaultAvailable: boolean;
  indexReady: boolean;
  indexedNotes: number;
  lastIndexedAt: string | null;
  copilotConnected: boolean;
  inboxFolder: string | null;
};

export async function fetchOsStatus(config: ServerConfig, signal?: AbortSignal): Promise<OsStatusSnapshot> {
  const raw = await governedJson<unknown>(config, 'GET', '/api/os/status', { signal });
  if (!isRecord(raw) || raw.ok === false) {
    throw new ApiError(isRecord(raw) && typeof raw.error === 'string' ? raw.error : 'ANDREI OS status unavailable');
  }
  return {
    vaultMode: typeof raw.vaultMode === 'string' ? raw.vaultMode : 'unknown',
    vaultPath: typeof raw.vaultPath === 'string' ? raw.vaultPath : '',
    vaultAvailable: Boolean(raw.vaultAvailable),
    indexReady: Boolean(raw.indexReady),
    indexedNotes: typeof raw.indexedNotes === 'number' && Number.isFinite(raw.indexedNotes) ? raw.indexedNotes : 0,
    lastIndexedAt: typeof raw.lastIndexedAt === 'string' ? raw.lastIndexedAt : null,
    copilotConnected: Boolean(raw.copilotConnected),
    inboxFolder: typeof raw.inboxFolder === 'string' ? raw.inboxFolder : null,
  };
}

export async function reindexOsVault(
  config: ServerConfig,
): Promise<{ indexedNotes: number; lastIndexedAt: string | null }> {
  const raw = await governedJson<unknown>(config, 'POST', '/api/os/brain/reindex', {
    admin: Boolean(config.adminToken.trim()),
  });
  if (!isRecord(raw) || raw.ok !== true) {
    throw new ApiError(isRecord(raw) && typeof raw.error === 'string' ? raw.error : 'Vault reindex failed');
  }
  return {
    indexedNotes: typeof raw.indexedNotes === 'number' ? raw.indexedNotes : 0,
    lastIndexedAt: typeof raw.lastIndexedAt === 'string' ? raw.lastIndexedAt : null,
  };
}

export type OsWorkshopProjectSummary = {
  path: string;
  title: string;
  view: string;
  updatedAt: string | null;
};

export type OsWorkshopProjectDetail = {
  path: string;
  title: string;
  view: string;
  paramCount: number;
  summary: string;
};

export async function fetchOsWorkshopProjects(
  config: ServerConfig,
  signal?: AbortSignal,
): Promise<OsWorkshopProjectSummary[]> {
  const raw = await governedJson<unknown>(config, 'GET', '/api/os/workshop/projects', { signal });
  if (!isRecord(raw) || raw.ok === false || !Array.isArray(raw.projects)) {
    throw new ApiError(isRecord(raw) && typeof raw.error === 'string' ? raw.error : 'Workshop projects unavailable');
  }
  return raw.projects
    .filter(isRecord)
    .filter(p => typeof p.path === 'string' && p.path.trim())
    .map(p => ({
      path: String(p.path),
      title: typeof p.title === 'string' && p.title.trim() ? p.title : String(p.path),
      view: typeof p.view === 'string' ? p.view : 'workshop',
      updatedAt: typeof p.updatedAt === 'string' ? p.updatedAt : typeof p.mtime === 'string' ? p.mtime : null,
    }));
}

export async function fetchOsWorkshopProject(
  config: ServerConfig,
  path: string,
  signal?: AbortSignal,
): Promise<OsWorkshopProjectDetail> {
  const trimmed = path.trim();
  if (!trimmed) throw new ApiError('Workshop project path is required', 400);
  const raw = await governedJson<unknown>(
    config,
    'GET',
    `/api/os/workshop/project?path=${encodeURIComponent(trimmed)}`,
    { signal },
  );
  if (!isRecord(raw) || raw.ok === false) {
    throw new ApiError(isRecord(raw) && typeof raw.error === 'string' ? raw.error : 'Workshop project unavailable');
  }
  const project = isRecord(raw.project) ? raw.project : {};
  const state = isRecord(project.state)
    ? project.state
    : isRecord(project.params)
      ? project.params
      : {};
  const keys = Object.keys(state);
  const summary = typeof raw.summary === 'string' && raw.summary.trim()
    ? raw.summary.trim()
    : keys.slice(0, 6).join(', ');
  return {
    path: typeof raw.path === 'string' ? raw.path : trimmed,
    title: typeof raw.title === 'string' && raw.title.trim()
      ? raw.title
      : typeof project.title === 'string'
        ? project.title
        : trimmed,
    view: typeof project.view === 'string' ? project.view : 'workshop',
    paramCount: keys.length,
    summary,
  };
}
