import { useCallback, useEffect, useRef, useState } from 'react';
import { apiFetchOnce } from './api/client';

export type GalleryItem = { id: string; source?: string; kind: string; prompt?: string; available?: boolean;
  mime?: string; size?: number; agent?: string; pinned?: boolean; validation?: 'on_download' };
export type GalleryData = { enabled: boolean; items: GalleryItem[];
  stats?: { total?: number; cloud?: number; by_kind?: Record<string, number> };
  page?: { catalog_total: number; scanned: number; matches: number; next_cursor: string | null; invalid_count?: number } };
export const galleryItemKey = (item: GalleryItem) => `${item.source || ''}:${item.id}`;

/** Explicit bounded scans. A zero-match response can still have a next cursor. */
export function useMediaGallery(query: string, kind: string) {
  const [data, setData] = useState<GalleryData | null>(null);
  const [items, setItems] = useState<GalleryItem[]>([]);
  const [scanned, setScanned] = useState(0);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const epoch = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const busy = useRef(false);
  const request = useCallback(async (cursor: string | null, current: number) => {
    if (busy.current) return;
    busy.current = true;
    const abort = new AbortController();
    controller.current = abort;
    setLoading(true); setError('');
    try {
      const params = new URLSearchParams({ limit: '50' });
      if (query) params.set('q', query);
      if (kind) params.set('kind', kind);
      if (cursor) params.set('cursor', cursor);
      const response = await apiFetchOnce(`/api/media/catalog?${params}`, { signal: abort.signal });
      if (current !== epoch.current || abort.signal.aborted) return;
      if (!response.ok) {
        if ([400, 401, 403].includes(response.status)) { setItems([]); setData(null); setScanned(0); }
        throw new Error(`Gallery request failed (${response.status}). Refresh to restart the search.`);
      }
      const next: GalleryData = await response.json();
      if (current !== epoch.current || abort.signal.aborted) return;
      if (!Array.isArray(next.items) || next.items.length > 200) throw new Error('Invalid gallery page.');
      setData(next);
      setItems(previous => next.enabled ? Array.from(new Map([...cursor ? previous : [], ...next.items].map(item => [galleryItemKey(item), item])).values()) : []);
      setScanned(previous => (cursor ? previous : 0) + (next.page?.scanned ?? next.items.length));
    } catch (e) {
      if (current === epoch.current && !abort.signal.aborted) setError(String(e));
    } finally {
      if (current === epoch.current) { busy.current = false; setLoading(false); }
    }
  }, [query, kind]);
  useEffect(() => {
    const current = ++epoch.current;
    controller.current?.abort(); busy.current = false;
    setItems([]); setData(null); setScanned(0);
    void request(null, current);
    return () => { ++epoch.current; controller.current?.abort(); busy.current = false; };
  }, [request, revision]);
  const reload = useCallback(() => setRevision(value => value + 1), []);
  const more = () => { if (data?.page?.next_cursor) void request(data.page.next_cursor, epoch.current); };
  return { data, items, scanned, error, loading, reload, more, revision };
}
