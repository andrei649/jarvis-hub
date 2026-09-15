// @ts-nocheck
/* 0.46 — the Console MediaGalleryPanel reads the generated-media catalog
   (GET /api/media/catalog) and renders items + per-kind stats. fetch is mocked
   (like skill-history-panel.test.tsx). Asserts the wiring, item rows, and the
   honesty banner when the catalog is disabled (flag off). */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MediaGalleryPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('MediaGalleryPanel — the media catalog read surface is live', () => {
  it('GETs /api/media/catalog and renders items + per-kind stats', async () => {
    const fn = mockFetch({
      enabled: true,
      stats: { total: 2, cloud: 0, by_kind: { image: 1, video: 1 } },
      items: [
        { id: 'md-1', kind: 'image', prompt: 'a red bicycle' },
        { id: 'md-2', kind: 'video', prompt: 'a sunset timelapse' },
      ],
    });
    render(<MediaGalleryPanel />);
    await waitFor(() => expect(screen.getByText('a red bicycle')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/media/catalog'))).toBe(true);
    expect(screen.getByText('1 image')).toBeTruthy();
    expect(screen.getByText('LIVE')).toBeTruthy(); // TASK-2 tail: per-panel honesty chip
  });

  it('shows the honesty banner when the catalog is disabled (flag off)', async () => {
    mockFetch({ enabled: false, items: [], stats: { total: 0, cloud: 0, by_kind: {} } });
    render(<MediaGalleryPanel />);
    await waitFor(() => expect(screen.getByText(/JARVIS_MEDIA_CATALOG is on/)).toBeTruthy());
    expect(screen.getByText('SEED')).toBeTruthy();
  });
});


it('labels preliminary file metadata as requiring validation when loaded', async () => {
  mockFetch({enabled:true, stats:{total:1, by_kind:{image:1}}, items:[{id:'md-aaaaaaaaaaaa',kind:'image',prompt:'preview',available:true,mime:'image/png',size:12,validation:'on_download'}]});
  render(<MediaGalleryPanel />);
  expect(await screen.findByText('Content is validated when loaded.')).toBeTruthy();
});

it('searches server pages and continues after a range with zero matches', async () => {
  global.fetch = vi.fn(async url => {
    const params = new URL(String(url), 'http://localhost').searchParams;
    const query = params.get('q');
    return {ok:true, json:async()=>({enabled:true, stats:{total:query ? 0 : 1, by_kind:{}},
      items:query ? (params.has('cursor') ? [{id:'md-old', prompt:'old needle', available:false}] : []) : [{id:'md-recent',prompt:'recent',available:false}],
      page:{catalog_total:220, scanned:params.has('cursor')?20:200, next_cursor:query&&!params.has('cursor')?'next':null, has_more:!!query&&!params.has('cursor')}})};
  });
  render(<MediaGalleryPanel />);
  expect(await screen.findByText('recent')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Search media'), {target:{value:'needle'}});
  fireEvent.click(await screen.findByRole('button', {name:'Continue search'}));
  expect(await screen.findByText('old needle')).toBeTruthy();
  expect(screen.queryByText('recent')).toBeNull();
  expect(screen.getByText(/220 retained/)).toBeTruthy();
});

it('aborts previous queries and ignores late responses after a search reset', async () => {
  let resolveOld;
  const fn = vi.fn((url, options) => String(url).includes('q=old') ? new Promise(resolve=>{resolveOld=resolve;}) : Promise.resolve({ok:true,json:async()=>({enabled:true,items:[{id:'md-new',prompt:'new match',available:false}],stats:{total:1,by_kind:{}}})}));
  global.fetch = fn;
  render(<MediaGalleryPanel />);
  await screen.findByText('new match');
  fireEvent.change(screen.getByLabelText('Search media'), {target:{value:'old'}});
  await waitFor(()=>expect(resolveOld).toBeTruthy());
  fireEvent.change(screen.getByLabelText('Search media'), {target:{value:'new'}});
  await screen.findByText('new match');
  resolveOld({ok:true,json:async()=>({enabled:true,items:[{id:'md-old',prompt:'stale match',available:false}],stats:{}})});
  await waitFor(()=>expect(fn.mock.calls.find(c=>String(c[0]).includes('q=old'))[1].signal.aborted).toBe(true));
  expect(screen.queryByText('stale match')).toBeNull();
});

it('caps explicit export selection at 200 and clears it on search changes', async () => {
  global.fetch = vi.fn(async url => ({ok:true,json:async()=>({enabled:true,stats:{total:200,by_kind:{}},items:Array.from({length:String(url).includes('cursor=')?1:200},(_,i)=>({id:'md-'+(String(url).includes('cursor=')?200:i),prompt:'item '+i,available:true})),page:{catalog_total:201,scanned:200,next_cursor:String(url).includes('cursor=')?null:'next'}})}));
  render(<MediaGalleryPanel />);
  fireEvent.click(await screen.findByRole('button',{name:'Select loaded media'}));
  fireEvent.click(screen.getByRole('button',{name:'Load more'}));
  const last = await screen.findByLabelText('Select md-200');
  expect(last.disabled).toBe(true);
  expect(screen.getByRole('button',{name:'Export selected media (200)'})).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Search media'), {target:{value:'reset'}});
  await waitFor(()=>expect(screen.getByRole('button',{name:'Export selected media (0)'}).disabled).toBe(true));
});

it('retries a failed continuation without duplicating already loaded records', async () => {
  let failed = false;
  global.fetch = vi.fn(async url => {
    if (String(url).includes('cursor=') && !failed) { failed = true; throw new Error('offline'); }
    return {ok:true,json:async()=>({enabled:true,stats:{},items:[{id:'md-'+(String(url).includes('cursor=')?'older':'recent'),prompt:String(url).includes('cursor=')?'older':'recent',available:false}],page:{catalog_total:2,scanned:1,next_cursor:String(url).includes('cursor=')?null:'next'}})};
  });
  render(<MediaGalleryPanel />);
  fireEvent.click(await screen.findByRole('button',{name:'Load more'}));
  fireEvent.click(await screen.findByRole('button',{name:'Retry gallery'}));
  expect(await screen.findByText('older')).toBeTruthy();
  expect(screen.getAllByText('recent')).toHaveLength(1);
});

it('drops stale selections when continuation authorization changes', async () => {
  global.fetch = vi.fn(async url => String(url).includes('cursor=') ? {ok:false,status:400} : {ok:true,json:async()=>({enabled:true,stats:{},items:[{id:'md-recent',prompt:'recent',available:true}],page:{catalog_total:2,scanned:1,next_cursor:'next'}})});
  render(<MediaGalleryPanel />);
  fireEvent.click(await screen.findByLabelText('Select md-recent'));
  fireEvent.click(screen.getByRole('button',{name:'Load more'}));
  await screen.findByRole('button',{name:'Retry gallery'});
  await waitFor(() => {
    expect(screen.getByRole('button',{name:'Export selected media (0)'}).disabled).toBe(true);
    expect(screen.queryByText('recent')).toBeNull();
  });
});

it('does not present a legacy response count as the full retained catalog total', async () => {
  mockFetch({enabled:true,stats:{total:1,by_kind:{}},items:[{id:'md-legacy',prompt:'legacy row',available:false}]});
  render(<MediaGalleryPanel />);
  await screen.findByText('legacy row');
  expect(screen.queryByText(/1 retained/)).toBeNull();
  expect(screen.getByText(/1 matches loaded/)).toBeTruthy();
});
