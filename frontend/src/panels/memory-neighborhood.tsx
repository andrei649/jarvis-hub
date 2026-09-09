import React, { useEffect, useState } from 'react';
import { memoryNodes, memoryNeighborhood, type MemoryNode, type MemoryNeighborhoodData } from '../api/memory-map';
import { inpS } from '../panel-kit';

const unavailable = (error: any) => error?.code === 'auth'
  ? 'Memory access requires your current user credentials.' : 'Memory graph unavailable. No sample data is shown.';

export function MemoryNeighborhood() {
  const [query, setQuery] = useState('');
  const [requestedQuery, setRequestedQuery] = useState('');
  const [revision, setRevision] = useState(0);
  const [nodes, setNodes] = useState<MemoryNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<MemoryNeighborhoodData | null>(null);
  const [detailError, setDetailError] = useState('');
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setNodes([]); setError(''); setSelected(null); setDetail(null);
    memoryNodes(requestedQuery, controller.signal).then(value => {
      if (!controller.signal.aborted) { setNodes(value); setLoading(false); }
    }).catch(error => { if (!controller.signal.aborted) { setError(unavailable(error)); setLoading(false); } });
    return () => controller.abort();
  }, [requestedQuery, revision]);

  useEffect(() => {
    const controller = new AbortController();
    setDetail(null); setDetailError(''); setDetailLoading(!!selected);
    if (selected) memoryNeighborhood(selected, controller.signal).then(value => {
      if (!controller.signal.aborted) { setDetail(value); setDetailLoading(false); }
    }).catch(error => { if (!controller.signal.aborted) { setDetailError(unavailable(error)); setDetailLoading(false); } });
    return () => controller.abort();
  }, [selected]);

  const select = (name: string) => { if (name !== selected) { setDetail(null); setDetailError(''); setSelected(name); } };
  const neighbors = detail ? [...new Set(detail.relations.map(row => row.source === detail.entity.name ? row.target : row.source))] : [];
  return <section aria-label="Memory neighborhood" style={{ border: '1px solid var(--panel-line)', borderRadius: 'var(--radius)', padding: 14 }}>
    <h3 style={{ fontSize: 13, marginTop: 0 }}>Memory neighborhood</h3>
    <p style={{ fontSize: 11, color: 'var(--ink-2)' }}>Explore stored entities and their connections.</p>
    <form onSubmit={event => { event.preventDefault(); setRequestedQuery(query); setRevision(value => value + 1); }} style={{ display: 'flex', gap: 6 }}>
      <input aria-label="Find memory entities" value={query} maxLength={200} onChange={event => setQuery(event.target.value)} style={{ ...inpS, minWidth: 0, flex: 1 }} />
      <button className="tool-btn" type="submit">Find</button>
    </form>
    <div role="status" style={{ fontSize: 12, marginTop: 8 }}>{loading ? 'Loading stored entities…' : error || (nodes.length ? `${nodes.length} entities in this page · up to 100` : 'No stored entities found.')}</div>
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, maxHeight: 160, overflowY: 'auto', margin: '10px 0' }}>
      {nodes.map(item => <button className={'tool-btn' + (selected === item.name ? ' on' : '')} key={item.name}
        aria-pressed={selected === item.name} onClick={() => select(item.name)} style={{ maxWidth: '100%', overflowWrap: 'anywhere' }}>{item.name}</button>)}
    </div>
    {!selected && !loading && !error && nodes.length > 0 && <p style={{ fontSize: 12 }}>Select an entity to inspect its connections.</p>}
    {selected && <div role="status" style={{ fontSize: 12 }}>{detailLoading ? `Loading connections for ${selected}…` : detailError}</div>}
    {detail && <>
      <h4 style={{ fontSize: 13, color: 'var(--accent-light)', overflowWrap: 'anywhere' }}>{detail.entity.name} <span style={{ color: 'var(--ink-2)', fontWeight: 400 }}>· {detail.entity.type}</span></h4>
      {neighbors.length > 0 && <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }} aria-label="Connected entities">
        {neighbors.map(name => <button key={name} className="tool-btn" onClick={() => select(name)} style={{ maxWidth: '100%', overflowWrap: 'anywhere' }} aria-label={'Explore ' + name}>{name}</button>)}
      </div>}
      <ul aria-label="Stored relationships" tabIndex={0} style={{ paddingLeft: 18, fontSize: 12, maxHeight: 240, overflowY: 'auto', overflowWrap: 'anywhere' }}>
        {detail.relations.map((relation, index) => <li key={index} style={{ margin: '6px 0' }}>
          {relation.source} <span style={{ color: 'var(--accent-light)' }}>— {relation.relation} —</span> {relation.target}
        </li>)}
      </ul>
      {detail.relations.length === 0 && <p style={{ fontSize: 12 }}>No stored relationships for this entity.</p>}
      {detail.clipped && <p style={{ fontSize: 12 }}>Showing the first 100 relationships. More are stored.</p>}
    </>}
  </section>;
}
