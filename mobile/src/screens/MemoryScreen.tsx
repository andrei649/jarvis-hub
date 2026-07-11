import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import {
  ApiError,
  deleteCanvasArtifact,
  fetchCanvasArtifacts,
  fetchKgEntities,
  fetchKgEntity,
  fetchKgFactHistory,
  fetchKgFacts,
  fetchMemory,
  fetchNotes,
  normalizeBaseUrl,
  pinCanvasArtifact,
  type CanvasArtifact,
  type KgEntityResponse,
  type KnowledgeEntity,
  type KnowledgeFact,
  type KnowledgeRelation,
  type MemoryResponse,
  type MemoryTurn,
  type NotesResponse,
} from '../api/client';
import { Markdown } from '../markdown/Markdown';
import { useServer } from '../context/ServerContext';
import { theme } from '../theme';

function EmptyState({ onGoToSettings }: { onGoToSettings: () => void }) {
  return (
    <View style={styles.empty}>
      <Text style={styles.emptyTitle}>No hub connected</Text>
      <Text style={styles.emptyBody}>Connect this phone to your Jarvis hub before viewing memory and notes.</Text>
      <Pressable style={styles.cta} onPress={onGoToSettings}>
        <Text style={styles.ctaText}>Open Settings</Text>
      </Pressable>
    </View>
  );
}

function timeLabel(value?: unknown): string {
  if (!value) return '';
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function roleColor(role: string): string {
  const key = role.toLowerCase();
  if (key === 'user') return theme.accent;
  if (key === 'assistant') return theme.ok;
  if (key === 'system') return theme.warn;
  return theme.textDim;
}

function SummaryCell({ label, value }: { label: string; value: string | number }) {
  return (
    <View style={styles.summaryCell}>
      <Text style={styles.summaryValue}>{value}</Text>
      <Text style={styles.summaryLabel}>{label}</Text>
    </View>
  );
}

type ViewMode = 'turns' | 'graph' | 'artifacts';

function SegmentButton({
  label,
  active,
  onPress,
}: {
  label: string;
  active: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable style={[styles.segmentButton, active && styles.segmentActive]} onPress={onPress}>
      <Text style={[styles.segmentText, active && styles.segmentTextActive]}>{label}</Text>
    </Pressable>
  );
}

function TurnCard({ turn }: { turn: MemoryTurn }) {
  const stamp = timeLabel(turn.timestamp);
  const role = turn.role || 'turn';
  return (
    <View style={styles.card}>
      <View style={styles.cardTop}>
        <Text style={[styles.role, { color: roleColor(role) }]}>{role}</Text>
        {turn.agent_id ? <Text style={styles.agent}>{turn.agent_id}</Text> : null}
        {stamp ? <Text style={styles.stamp}>{stamp}</Text> : null}
      </View>
      <Text style={styles.contentText} numberOfLines={5}>
        {turn.content || 'Empty turn'}
      </Text>
    </View>
  );
}

function NotesCard({ notes }: { notes: NotesResponse | null }) {
  const content = notes?.content?.trim() ?? '';
  return (
    <View style={styles.card}>
      <View style={styles.cardTop}>
        <Text style={styles.sectionTitle}>Session Notes</Text>
        {notes?.session ? <Text style={styles.stamp}>{notes.session}</Text> : null}
      </View>
      {content ? (
        <Text style={styles.contentText}>{content}</Text>
      ) : (
        <Text style={styles.emptyText}>No session notes returned by the hub.</Text>
      )}
    </View>
  );
}

function propertyCount(properties: Record<string, unknown>): string {
  const count = Object.keys(properties).length;
  return `${count} prop${count === 1 ? '' : 's'}`;
}

function EntityCard({
  entity,
  selected,
  onPress,
}: {
  entity: KnowledgeEntity;
  selected: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable style={[styles.entityCard, selected && styles.entitySelected]} onPress={onPress}>
      <View style={styles.cardTop}>
        <View style={styles.cardTitleWrap}>
          <Text style={styles.entityName}>{entity.name}</Text>
          <Text style={styles.meta}>
            {entity.type || 'unknown'} · {propertyCount(entity.properties)}
          </Text>
        </View>
        {selected ? <Text style={styles.selectedMark}>selected</Text> : null}
      </View>
    </Pressable>
  );
}

function RelationRow({ relation }: { relation: KnowledgeRelation }) {
  return (
    <View style={styles.kgRow}>
      <Text style={styles.kgRowMain}>
        {relation.source || 'source'} → {relation.target || 'target'}
      </Text>
      <Text style={styles.kgRowMeta}>{relation.relation || 'related_to'}</Text>
    </View>
  );
}

function FactRow({ fact }: { fact: KnowledgeFact }) {
  const when = fact.valid_from === undefined ? '' : `from ${String(fact.valid_from)}`;
  return (
    <View style={styles.kgRow}>
      <Text style={styles.kgRowMain}>
        {fact.subject || 'subject'} · {fact.predicate || 'predicate'} · {fact.object || 'object'}
      </Text>
      {when ? <Text style={styles.kgRowMeta}>{when}</Text> : null}
    </View>
  );
}

function GraphView({
  entities,
  entityTotal,
  selected,
  facts,
  history,
  loading,
  error,
  search,
  onSearchChange,
  onSearch,
  onSelectEntity,
}: {
  entities: KnowledgeEntity[];
  entityTotal: number;
  selected: KgEntityResponse | null;
  facts: KnowledgeFact[];
  history: KnowledgeFact[];
  loading: boolean;
  error: string | null;
  search: string;
  onSearchChange: (value: string) => void;
  onSearch: () => void;
  onSelectEntity: (entity: KnowledgeEntity) => void;
}) {
  const selectedName = selected?.entity?.name ?? '';
  const relations = selected?.relations ?? [];

  return (
    <>
      <View style={styles.summary}>
        <SummaryCell label="entities" value={entityTotal || entities.length} />
        <SummaryCell label="relations" value={relations.length} />
        <SummaryCell label="facts" value={facts.length} />
      </View>

      <View style={styles.searchRow}>
        <TextInput
          value={search}
          onChangeText={onSearchChange}
          onSubmitEditing={onSearch}
          placeholder="Search graph"
          placeholderTextColor={theme.textDim}
          returnKeyType="search"
          style={styles.searchInput}
        />
        <Pressable style={styles.searchButton} onPress={onSearch}>
          <Text style={styles.searchButtonText}>Search</Text>
        </Pressable>
      </View>

      {error && (
        <View style={styles.errorBox}>
          <Text style={styles.errorText}>{error}</Text>
        </View>
      )}

      {loading && entities.length === 0 && (
        <View style={styles.loading}>
          <ActivityIndicator color={theme.accent} />
        </View>
      )}

      <View style={styles.sectionHeader}>
        <Text style={styles.sectionTitle}>Entities</Text>
        <Text style={styles.readOnly}>read-only</Text>
      </View>

      {entities.map((entity) => (
        <EntityCard
          key={entity.name}
          entity={entity}
          selected={entity.name === selectedName}
          onPress={() => onSelectEntity(entity)}
        />
      ))}

      {!loading && entities.length === 0 && !error && (
        <View style={styles.clearBox}>
          <Text style={styles.clearTitle}>No graph entities</Text>
          <Text style={styles.clearText}>The hub returned an empty knowledge graph for this query.</Text>
        </View>
      )}

      {selected?.entity ? (
        <View style={styles.card}>
          <View style={styles.cardTop}>
            <View style={styles.cardTitleWrap}>
              <Text style={styles.sectionTitle}>Relations</Text>
              <Text style={styles.meta}>{selected.entity.name}</Text>
            </View>
          </View>
          {relations.length ? (
            relations.map((relation, index) => (
              <RelationRow key={`${relation.source}-${relation.relation}-${relation.target}-${index}`} relation={relation} />
            ))
          ) : (
            <Text style={styles.emptyText}>No relations returned for this entity.</Text>
          )}
        </View>
      ) : null}

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>Current Facts</Text>
        {facts.length ? (
          facts.slice(0, 8).map((fact, index) => (
            <FactRow key={`${fact.subject}-${fact.predicate}-${fact.object}-${fact.id ?? index}`} fact={fact} />
          ))
        ) : (
          <Text style={styles.emptyText}>No current facts returned by the hub.</Text>
        )}
      </View>

      {selectedName ? (
        <View style={styles.card}>
          <View style={styles.cardTop}>
            <View style={styles.cardTitleWrap}>
              <Text style={styles.sectionTitle}>History</Text>
              <Text style={styles.meta}>{selectedName}</Text>
            </View>
          </View>
          {history.length ? (
            history.map((fact, index) => (
              <FactRow key={`history-${fact.subject}-${fact.predicate}-${fact.object}-${fact.id ?? index}`} fact={fact} />
            ))
          ) : (
            <Text style={styles.emptyText}>No fact history returned for this subject.</Text>
          )}
        </View>
      ) : null}
    </>
  );
}

/* ── Artifacts (H18.20) — governed Canvas browsing, same safety discipline as
   the browser Artifacts tab: React Native Text nodes are inert by construction;
   same-origin image paths resolve against the configured hub; remote http(s)
   images sit behind an explicit consent tap; anything else stays plain text. */

function cleanUrl(u: unknown): string {
  // browsers strip TAB/LF/CR before URL parsing — normalize identically before classifying
  return String(u ?? '').replace(/[\t\n\r]/g, '');
}
function isSameOriginPath(u: unknown): boolean {
  const s = cleanUrl(u);
  return s.startsWith('/') && !s.startsWith('//') && !s.startsWith('/\\');
}
function isRemoteHttp(u: unknown): boolean {
  return /^https?:\/\//i.test(cleanUrl(u));
}

function artifactTime(ts?: number): string {
  if (!ts || !Number.isFinite(ts)) return '';
  const date = new Date(ts * 1000);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function ArtifactImage({ src, alt, baseUrl }: { src: string; alt: string; baseUrl: string }) {
  const [consented, setConsented] = useState(false);
  const url = cleanUrl(src);
  if (isSameOriginPath(url)) {
    return <Image style={styles.artifactImage} source={{ uri: baseUrl + url }} accessibilityLabel={alt} />;
  }
  if (!isRemoteHttp(url)) return <Text style={styles.contentText}>{url}</Text>;
  if (!consented) {
    return (
      <Pressable style={styles.artifactConsent} onPress={() => setConsented(true)}>
        <Text style={styles.artifactConsentText}>Remote image — tap to load</Text>
        <Text style={styles.kgRowMeta}>{url}</Text>
      </Pressable>
    );
  }
  return <Image style={styles.artifactImage} source={{ uri: url }} accessibilityLabel={alt} />;
}

function ArtifactBody({ artifact, baseUrl }: { artifact: CanvasArtifact; baseUrl: string }) {
  const p = artifact.payload || {};
  const title = typeof p.title === 'string' && p.title ? p.title : '';
  const titleNode = title ? <Text style={styles.artifactTitle}>{title}</Text> : null;
  switch (artifact.type) {
    case 'text':
      return (
        <>
          {titleNode}
          <Text style={styles.contentText}>{String(p.body ?? '')}</Text>
        </>
      );
    case 'markdown':
      return (
        <>
          {titleNode}
          <Markdown text={String(p.body ?? '')} />
        </>
      );
    case 'list': {
      const items = Array.isArray(p.items) ? p.items : [];
      return (
        <>
          {titleNode}
          {items.map((it, i) => (
            <Text key={i} style={styles.contentText}>• {String(it)}</Text>
          ))}
        </>
      );
    }
    case 'link': {
      // display-only on mobile: the label + URL as inert text (no auto-open)
      const label = String(p.label || p.title || p.url || '');
      const url = cleanUrl(p.url);
      return (
        <>
          <Text style={styles.contentText}>{label}</Text>
          {url && url !== label ? <Text style={styles.kgRowMeta}>{url}</Text> : null}
        </>
      );
    }
    case 'metric':
      return (
        <View style={styles.artifactMetric}>
          <Text style={styles.kgRowMeta}>{String(p.label ?? '')}</Text>
          <Text style={styles.artifactMetricValue}>{String(p.value ?? '')}</Text>
          {p.delta ? <Text style={styles.artifactMetricDelta}>{String(p.delta)}</Text> : null}
        </View>
      );
    case 'table': {
      const cols = Array.isArray(p.columns) ? p.columns.map(String) : [];
      const rows = Array.isArray(p.rows) ? p.rows : [];
      return (
        <>
          {titleNode}
          {cols.length ? <Text style={styles.artifactTableHead}>{cols.join(' · ')}</Text> : null}
          {rows.map((row, i) => (
            <Text key={i} style={styles.contentText}>
              {(Array.isArray(row) ? row : []).map(String).join(' · ')}
            </Text>
          ))}
        </>
      );
    }
    case 'image_ref':
      return (
        <>
          {titleNode}
          <ArtifactImage src={String(p.src ?? '')} alt={String(p.alt || title || 'artifact image')} baseUrl={baseUrl} />
        </>
      );
    default:
      // future/unknown types stay inert: a JSON snapshot as plain text
      return <Text style={styles.contentText}>{JSON.stringify(p)}</Text>;
  }
}

function ArtifactCard({
  artifact,
  baseUrl,
  onPin,
  onDelete,
}: {
  artifact: CanvasArtifact;
  baseUrl: string;
  onPin: () => void;
  onDelete: () => void;
}) {
  const stamp = artifactTime(artifact.created_at);
  return (
    <View style={styles.card}>
      <View style={styles.cardTop}>
        <Text style={[styles.role, { color: theme.accent }]}>{artifact.agent.toUpperCase()}</Text>
        <Text style={styles.meta}>{artifact.type}</Text>
        {artifact.pinned ? <Text style={styles.artifactPinned}>◆ pinned</Text> : null}
        {stamp ? <Text style={styles.stamp}>{stamp}</Text> : null}
      </View>
      <ArtifactBody artifact={artifact} baseUrl={baseUrl} />
      <View style={styles.artifactActions}>
        <Pressable style={styles.artifactBtn} onPress={onPin} hitSlop={6}>
          <Text style={styles.artifactBtnText}>{artifact.pinned ? 'unpin' : 'pin'}</Text>
        </Pressable>
        <Pressable style={styles.artifactBtn} onPress={onDelete} hitSlop={6}>
          <Text style={[styles.artifactBtnText, styles.artifactBtnDanger]}>delete</Text>
        </Pressable>
      </View>
    </View>
  );
}

export function MemoryScreen({ onGoToSettings }: { onGoToSettings: () => void }) {
  const { config, configured } = useServer();
  const [mode, setMode] = useState<ViewMode>('turns');
  const [memory, setMemory] = useState<MemoryResponse | null>(null);
  const [notes, setNotes] = useState<NotesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [kgSearch, setKgSearch] = useState('');
  const [kgQuery, setKgQuery] = useState('');
  const [kgEntities, setKgEntities] = useState<KnowledgeEntity[]>([]);
  const [kgEntityTotal, setKgEntityTotal] = useState(0);
  const [selectedKgEntity, setSelectedKgEntity] = useState<KgEntityResponse | null>(null);
  const [kgFacts, setKgFacts] = useState<KnowledgeFact[]>([]);
  const [kgHistory, setKgHistory] = useState<KnowledgeFact[]>([]);
  const [kgError, setKgError] = useState<string | null>(null);
  const [kgLoading, setKgLoading] = useState(false);
  const [artifacts, setArtifacts] = useState<CanvasArtifact[]>([]);
  const [artifactsError, setArtifactsError] = useState<string | null>(null);
  const [artifactsLoading, setArtifactsLoading] = useState(false);
  const [artifactsLoaded, setArtifactsLoaded] = useState(false);

  const loadArtifacts = useCallback(async () => {
    if (!configured) return;
    setArtifactsLoading(true);
    setArtifactsError(null);
    try {
      const res = await fetchCanvasArtifacts(config);
      setArtifacts(res.elements);
      setArtifactsLoaded(true);
    } catch (err) {
      setArtifactsError(err instanceof ApiError ? err.message : 'Failed to load artifacts');
    } finally {
      setArtifactsLoading(false);
    }
  }, [config, configured]);

  const togglePinArtifact = useCallback(
    async (artifact: CanvasArtifact) => {
      try {
        const updated = await pinCanvasArtifact(config, artifact.id, !artifact.pinned);
        const pinned = updated ? updated.pinned : !artifact.pinned;
        setArtifacts((prev) => prev.map((a) => (a.id === artifact.id ? { ...a, pinned } : a)));
        setArtifactsError(null);
      } catch {
        setArtifactsError('Pin change failed — refresh and try again.');
      }
    },
    [config],
  );

  const removeArtifact = useCallback(
    async (artifact: CanvasArtifact) => {
      try {
        await deleteCanvasArtifact(config, artifact.id);
        setArtifacts((prev) => prev.filter((a) => a.id !== artifact.id));
        setArtifactsError(null);
      } catch {
        setArtifactsError('Delete failed — refresh and try again.');
      }
    },
    [config],
  );

  const loadTurns = useCallback(async () => {
    if (!configured) return;
    setLoading(true);
    setError(null);
    try {
      const [memoryResult, notesResult] = await Promise.allSettled([fetchMemory(config), fetchNotes(config)]);
      if (memoryResult.status === 'fulfilled') {
        setMemory(memoryResult.value);
      } else {
        const err = memoryResult.reason;
        setMemory({ turns: [] });
        setError(err instanceof ApiError ? err.message : 'Failed to load memory');
      }
      setNotes(notesResult.status === 'fulfilled' ? notesResult.value : { content: '' });
    } finally {
      setLoading(false);
    }
  }, [config, configured]);

  const selectKgEntity = useCallback(
    async (entity: KnowledgeEntity) => {
      if (!configured) return;
      setKgLoading(true);
      setKgError(null);
      try {
        const [detailResult, historyResult] = await Promise.allSettled([
          fetchKgEntity(config, entity.name),
          fetchKgFactHistory(config, entity.name),
        ]);
        setSelectedKgEntity(
          detailResult.status === 'fulfilled' ? detailResult.value : { entity, relations: [] },
        );
        setKgHistory(historyResult.status === 'fulfilled' ? historyResult.value.history : []);
      } finally {
        setKgLoading(false);
      }
    },
    [config, configured],
  );

  const loadGraph = useCallback(async () => {
    if (!configured) return;
    setKgLoading(true);
    setKgError(null);
    try {
      const [entitiesResult, factsResult] = await Promise.allSettled([
        fetchKgEntities(config, { query: kgQuery, limit: 50 }),
        fetchKgFacts(config),
      ]);
      const nextEntities = entitiesResult.status === 'fulfilled' ? entitiesResult.value.entities : [];
      setKgEntities(nextEntities);
      setKgEntityTotal(entitiesResult.status === 'fulfilled' ? entitiesResult.value.total : 0);
      setKgFacts(factsResult.status === 'fulfilled' ? factsResult.value.facts : []);
      if (entitiesResult.status === 'rejected') {
        const err = entitiesResult.reason;
        setKgError(err instanceof ApiError ? err.message : 'Failed to load knowledge graph');
      }
      const firstEntity = nextEntities[0];
      if (firstEntity) {
        const [detailResult, historyResult] = await Promise.allSettled([
          fetchKgEntity(config, firstEntity.name),
          fetchKgFactHistory(config, firstEntity.name),
        ]);
        setSelectedKgEntity(
          detailResult.status === 'fulfilled' ? detailResult.value : { entity: firstEntity, relations: [] },
        );
        setKgHistory(historyResult.status === 'fulfilled' ? historyResult.value.history : []);
      } else {
        setSelectedKgEntity(null);
        setKgHistory([]);
      }
    } finally {
      setKgLoading(false);
    }
  }, [config, configured, kgQuery]);

  const runKgSearch = useCallback(() => {
    const nextQuery = kgSearch.trim();
    if (nextQuery === kgQuery) {
      void loadGraph();
      return;
    }
    setKgQuery(nextQuery);
  }, [kgQuery, kgSearch, loadGraph]);

  useEffect(() => {
    loadTurns();
  }, [loadTurns]);

  useEffect(() => {
    if (mode === 'graph') void loadGraph();
  }, [loadGraph, mode]);

  useEffect(() => {
    if (mode === 'artifacts') void loadArtifacts();
  }, [loadArtifacts, mode]);

  const turns = memory?.turns ?? [];
  const summary = useMemo(() => {
    const noteChars = notes?.content?.length ?? 0;
    const session = memory?.session || notes?.session || 'current';
    return { noteChars, session };
  }, [memory?.session, notes?.content, notes?.session]);

  if (!configured) return <EmptyState onGoToSettings={onGoToSettings} />;

  const refreshing = mode === 'graph' ? kgLoading : mode === 'artifacts' ? artifactsLoading : loading;
  const refresh = mode === 'graph' ? loadGraph : mode === 'artifacts' ? loadArtifacts : loadTurns;
  const hubBase = normalizeBaseUrl(config.baseUrl);

  return (
    <ScrollView
      style={styles.flex}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={theme.accent} />}
    >
      <View style={styles.segments}>
        <SegmentButton label="Turns" active={mode === 'turns'} onPress={() => setMode('turns')} />
        <SegmentButton label="Graph" active={mode === 'graph'} onPress={() => setMode('graph')} />
        <SegmentButton label="Artifacts" active={mode === 'artifacts'} onPress={() => setMode('artifacts')} />
      </View>

      {mode === 'artifacts' ? (
        <>
          <View style={styles.summary}>
            <SummaryCell label="artifacts" value={artifacts.length} />
            <SummaryCell label="pinned" value={artifacts.filter((a) => a.pinned).length} />
          </View>

          {artifactsError && (
            <View style={styles.errorBox}>
              <Text style={styles.errorText}>{artifactsError}</Text>
            </View>
          )}

          {artifactsLoading && artifacts.length === 0 && (
            <View style={styles.loading}>
              <ActivityIndicator color={theme.accent} />
            </View>
          )}

          {artifacts.map((artifact) => (
            <ArtifactCard
              key={artifact.id}
              artifact={artifact}
              baseUrl={hubBase}
              onPin={() => void togglePinArtifact(artifact)}
              onDelete={() => void removeArtifact(artifact)}
            />
          ))}

          {!artifactsLoading && artifactsLoaded && artifacts.length === 0 && !artifactsError && (
            <View style={styles.clearBox}>
              <Text style={styles.clearTitle}>No artifacts yet</Text>
              <Text style={styles.clearText}>
                Save an assistant reply from Chat, or let an agent post to the canvas.
              </Text>
            </View>
          )}
        </>
      ) : mode === 'turns' ? (
        <>
          <View style={styles.summary}>
            <SummaryCell label="turns" value={turns.length} />
            <SummaryCell label="notes chars" value={summary.noteChars} />
            <SummaryCell label="session" value={summary.session.slice(0, 10)} />
          </View>

          {error && (
            <View style={styles.errorBox}>
              <Text style={styles.errorText}>{error}</Text>
            </View>
          )}

          {loading && turns.length === 0 && (
            <View style={styles.loading}>
              <ActivityIndicator color={theme.accent} />
            </View>
          )}

          <NotesCard notes={notes} />

          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Recent Turns</Text>
          </View>

          {turns.map((turn, index) => (
            <TurnCard key={`${turn.role}-${turn.timestamp || index}`} turn={turn} />
          ))}

          {!loading && turns.length === 0 && !error && (
            <View style={styles.clearBox}>
              <Text style={styles.clearTitle}>No recent turns</Text>
              <Text style={styles.clearText}>The hub returned an empty memory history for this session.</Text>
            </View>
          )}
        </>
      ) : (
        <GraphView
          entities={kgEntities}
          entityTotal={kgEntityTotal}
          selected={selectedKgEntity}
          facts={kgFacts}
          history={kgHistory}
          loading={kgLoading}
          error={kgError}
          search={kgSearch}
          onSearchChange={setKgSearch}
          onSearch={runKgSearch}
          onSelectEntity={(entity) => {
            void selectKgEntity(entity);
          }}
        />
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { padding: 12, paddingBottom: 24 },
  summary: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 12,
  },
  summaryCell: {
    flex: 1,
    backgroundColor: theme.surface,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: theme.border,
    paddingHorizontal: 10,
    paddingVertical: 10,
  },
  summaryValue: { color: theme.accent, fontSize: 16, fontWeight: '800' },
  summaryLabel: { color: theme.textDim, fontSize: 10, marginTop: 2, textTransform: 'uppercase' },
  segments: {
    flexDirection: 'row',
    backgroundColor: theme.surfaceAlt,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: theme.border,
    padding: 3,
    marginBottom: 12,
  },
  segmentButton: { flex: 1, alignItems: 'center', borderRadius: 10, paddingVertical: 9 },
  segmentActive: { backgroundColor: theme.accentDim },
  segmentText: { color: theme.textDim, fontSize: 13, fontWeight: '800' },
  segmentTextActive: { color: theme.text },
  sectionHeader: { paddingHorizontal: 2, paddingVertical: 8 },
  readOnly: { color: theme.textDim, fontSize: 11, fontWeight: '800', textTransform: 'uppercase' },
  sectionTitle: { color: theme.accent, fontSize: 12, fontWeight: '800', textTransform: 'uppercase' },
  cardTitleWrap: { flex: 1 },
  card: {
    backgroundColor: theme.surface,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: theme.border,
    padding: 14,
    marginBottom: 12,
  },
  cardTop: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 8 },
  meta: { color: theme.textDim, fontSize: 12, marginTop: 3 },
  role: { fontSize: 12, fontWeight: '800', textTransform: 'uppercase' },
  agent: { color: theme.textDim, fontSize: 12, fontWeight: '700' },
  stamp: { color: theme.textDim, fontSize: 11, marginLeft: 'auto', maxWidth: 140, textAlign: 'right' },
  contentText: { color: theme.text, fontSize: 14, lineHeight: 20 },
  emptyText: { color: theme.textDim, fontSize: 14, lineHeight: 20 },
  searchRow: { flexDirection: 'row', gap: 8, marginBottom: 12 },
  searchInput: {
    flex: 1,
    backgroundColor: theme.surface,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 12,
    color: theme.text,
    fontSize: 15,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  searchButton: {
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: theme.accent,
    borderRadius: 12,
    paddingHorizontal: 14,
    minWidth: 82,
  },
  searchButtonText: { color: '#02121b', fontSize: 14, fontWeight: '800' },
  entityCard: {
    backgroundColor: theme.surface,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: theme.border,
    padding: 14,
    marginBottom: 10,
  },
  entitySelected: { borderColor: theme.accent },
  entityName: { color: theme.text, fontSize: 16, fontWeight: '800' },
  selectedMark: { color: theme.accent, fontSize: 11, fontWeight: '800', textTransform: 'uppercase' },
  kgRow: {
    borderTopWidth: 1,
    borderTopColor: theme.border,
    paddingTop: 9,
    marginTop: 9,
  },
  kgRowMain: { color: theme.text, fontSize: 14, lineHeight: 19 },
  kgRowMeta: { color: theme.textDim, fontSize: 12, marginTop: 3 },
  errorBox: {
    backgroundColor: '#2a0d16',
    borderColor: theme.danger,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
  },
  errorText: { color: theme.danger, fontSize: 14 },
  loading: { alignItems: 'center', padding: 24 },
  clearBox: {
    alignItems: 'center',
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 14,
    padding: 28,
    backgroundColor: theme.surface,
  },
  clearTitle: { color: theme.ok, fontSize: 20, fontWeight: '800', marginBottom: 6 },
  clearText: { color: theme.textDim, fontSize: 14, textAlign: 'center' },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  emptyTitle: { color: theme.text, fontSize: 20, fontWeight: '700', marginBottom: 8 },
  emptyBody: { color: theme.textDim, fontSize: 15, textAlign: 'center', marginBottom: 24 },
  cta: { paddingHorizontal: 24, paddingVertical: 12, borderRadius: 24, backgroundColor: theme.accent },
  ctaText: { color: '#02121b', fontWeight: '700', fontSize: 15 },
  artifactTitle: { color: theme.text, fontSize: 14, fontWeight: '700', marginBottom: 4 },
  artifactPinned: { color: theme.warn, fontSize: 11, marginLeft: 8 },
  artifactMetric: { flexDirection: 'row', alignItems: 'baseline', gap: 8 },
  artifactMetricValue: { color: theme.accent, fontSize: 22, fontWeight: '700' },
  artifactMetricDelta: { color: theme.ok, fontSize: 12 },
  artifactTableHead: { color: theme.textDim, fontSize: 12, fontWeight: '700', textTransform: 'uppercase', marginBottom: 2 },
  artifactImage: { width: '100%', height: 180, borderRadius: 8, marginTop: 6, resizeMode: 'contain', backgroundColor: '#02070d' },
  artifactConsent: {
    borderWidth: 1,
    borderColor: theme.border,
    borderStyle: 'dashed',
    borderRadius: 8,
    padding: 14,
    marginTop: 6,
    alignItems: 'center',
    gap: 4,
  },
  artifactConsentText: { color: theme.textDim, fontSize: 13 },
  artifactActions: { flexDirection: 'row', gap: 10, marginTop: 10 },
  artifactBtn: {
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 5,
  },
  artifactBtnText: { color: theme.textDim, fontSize: 12, fontWeight: '600' },
  artifactBtnDanger: { color: theme.danger },
});
