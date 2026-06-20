export type SignalDomain = 'world' | 'personal' | 'business' | 'technical' | 'financial';

export type SignalSeverity = 'low' | 'normal' | 'elevated' | 'high' | 'critical';
export type SignalConfidence = 'low' | 'medium' | 'high';
export type ClaimStatus = 'confirmed' | 'raw_osint_lead' | 'model_inference' | 'forecast' | 'unknown';

export type EntityRef = {
  type: 'country' | 'city' | 'company' | 'market' | 'route' | 'airport' | 'actor' | 'infrastructure' | 'topic';
  id?: string;
  label: string;
};

export type Evidence = {
  id: string;
  provider: string;
  sourceName?: string;
  sourceFamily:
    | 'rss'
    | 'government'
    | 'ngo'
    | 'market'
    | 'aviation'
    | 'maritime'
    | 'cyber'
    | 'weather'
    | 'osint'
    | 'unknown';
  url?: string;
  observedAt?: string;
  publishedAt?: string;
  fetchedAt?: string;
  cachedAt?: string;
  stale: boolean;
  reliability: 'low' | 'medium' | 'high' | 'unknown';
  raw?: unknown;
};

export type WatchTarget = {
  id: string;
  type: 'country' | 'city' | 'airport' | 'route' | 'market' | 'topic' | 'company';
  value: string;
  label: string;
  priority: 'low' | 'normal' | 'high';
};

export type RelevanceScore = {
  score: number;
  reasons: string[];
  matchedTargets: WatchTarget[];
};

export type Signal = {
  id: string;
  domain: SignalDomain;
  type: string;
  title: string;
  summary: string;
  entities: EntityRef[];
  evidenceIds: string[];
  severity: SignalSeverity;
  confidence: SignalConfidence;
  claimStatus: ClaimStatus;
  status: 'new' | 'seen' | 'monitoring' | 'dismissed' | 'escalated';
  observedAt?: string;
  publishedAt?: string;
  fetchedAt?: string;
  cachedAt?: string;
  stale: boolean;
  provider: string;
  relevance: RelevanceScore;
  raw?: unknown;
};

export type Assessment = {
  id: string;
  subject: EntityRef;
  risk: {
    score: number;
    level: 'low' | 'moderate' | 'elevated' | 'high' | 'critical';
    components: Record<string, number>;
  };
  claim: string;
  confidence: SignalConfidence;
  drivers: Array<string | { title?: string; type?: string; severity?: SignalSeverity }>;
  recommendations: Array<string | ActionRecommendation>;
  evidenceIds: string[];
  evidence?: Evidence[];
  freshness: FreshnessState;
  provider: string;
  raw?: unknown;
};

export type FreshnessState = {
  stale: boolean;
  checkedAt: string;
  cachedAt?: string;
  degraded?: boolean;
  errors?: Array<{ code?: string; message?: string }>;
};

export type ActionRecommendation = {
  type: 'monitor' | 'brief' | 'review' | 'watchlist' | 'notify';
  label: string;
  requiresApproval: boolean;
};

export type Brief = {
  id: string;
  type: 'brief';
  scope: 'world' | 'country' | 'travel' | 'market' | 'cyber';
  title: string;
  executiveSummary: string;
  generatedAt: string;
  globalStatus: SignalSeverity | 'unknown';
  topSignals: Array<{
    id: string;
    title: string;
    type: string;
    severity: SignalSeverity;
    confidence: SignalConfidence;
    relevance: RelevanceScore;
    whyItMatters: string;
    evidenceIds: string[];
  }>;
  recommendations: ActionRecommendation[];
  evidenceIds: string[];
  sources: Evidence[];
  freshness: FreshnessState;
  provider: string;
  raw?: unknown;
};

export interface SignalProvider {
  id: string;
  name: string;
  mode: 'live' | 'replay';
  health(): Promise<ProviderHealth>;
  fetchSignals(input: FetchSignalsInput): Promise<SignalPayload>;
  fetchBrief(input: FetchBriefInput): Promise<{ provider: string; mode: 'live' | 'replay'; brief: Brief | null }>;
  fetchEntityAssessment(input: EntityAssessmentInput): Promise<{ provider: string; mode: 'live' | 'replay'; assessment: Assessment | null }>;
}

export type ProviderHealth = {
  provider: string;
  mode: 'live' | 'replay';
  status: 'ok' | 'degraded' | 'down' | string;
  checkedAt: string;
  latencyMs?: number;
  fresh?: number;
  stale?: number;
  error?: { code?: string; message?: string };
  raw?: unknown;
};

export type FetchSignalsInput = {
  type?: string;
  country?: string;
  minSeverity?: SignalSeverity;
  limit?: number;
};

export type FetchBriefInput = {
  scope?: 'world' | 'country' | 'travel' | 'market' | 'cyber';
};

export type EntityAssessmentInput = {
  type: 'country' | 'route' | 'market' | 'airport' | 'company';
  id: string;
};

export type SignalPayload = {
  provider: string;
  mode: 'live' | 'replay';
  signals: Signal[];
  evidence: Evidence[];
  freshness: FreshnessState;
};
