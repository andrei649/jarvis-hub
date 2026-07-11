// @ts-nocheck
/* Visual-artifact lane wave 1 — Artifacts tab (Canvas-backed) + explicit
   save-response control. Proves: typed rendering stays safe (no script/iframe,
   remote images gated behind consent with no-referrer), the save contract posts
   the exact governed Markdown payload with visible 4,000-char truncation, the
   control never appears for user/system/empty/in-flight replies, and pin/unpin/
   delete ride the existing /api/canvas endpoints with honest UI states. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ArtifactsPanel, SaveArtifactButton, MARKDOWN_LIMIT } from '../artifacts';
import { Conversation } from '../cockpit';
import { V2 } from '../data';

const t = V2.I18N.en;

const ok = (data) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(data) });
const fail = (status = 500) => Promise.resolve({ ok: false, status, json: () => Promise.resolve({}) });

const ELS = [
  { id: 'e1', agent: 'jarvis', type: 'text', payload: { title: 'Note', body: 'plain text body' }, pinned: false, created_at: 1770000000 },
  { id: 'e2', agent: 'vision', type: 'markdown', payload: { title: 'Brief', body: '# Heading line\n**bold move**\n- item one\n- item two\n`code bit`' }, pinned: false, created_at: 1770000001 },
  { id: 'e3', agent: 'friday', type: 'list', payload: { title: 'Groceries', items: ['apples', 'bread'] }, pinned: true, created_at: 1770000002 },
  { id: 'e4', agent: 'stark', type: 'link', payload: { title: 'Report', url: 'https://example.com/r', label: 'quarterly report' }, pinned: false, created_at: 1770000003 },
  { id: 'e5', agent: 'gecko', type: 'metric', payload: { label: 'MRR', value: '+6.2%', delta: 'WoW' }, pinned: false, created_at: 1770000004 },
  { id: 'e6', agent: 'pepper', type: 'table', payload: { title: 'Sprint', columns: ['task', 'owner'], rows: [['ship artifacts', 'claude']] }, pinned: false, created_at: 1770000005 },
  { id: 'e7', agent: 'hephaestus', type: 'image_ref', payload: { title: 'Diagram', src: '/static/diagram.png', alt: 'architecture diagram' }, pinned: false, created_at: 1770000006 },
];

function mockCanvas(elements) {
  global.fetch = vi.fn((url, init) => {
    const path = String(url);
    if (path === '/api/canvas' && (!init || !init.method || init.method === 'GET')) {
      return ok({ elements });
    }
    return Promise.reject(new Error('unexpected fetch: ' + path + ' ' + (init && init.method)));
  });
  return global.fetch;
}

afterEach(() => { delete global.fetch; });

describe('ArtifactsPanel — governed Canvas rendering', () => {
  it('fetches /api/canvas and renders every existing canvas type with agent + time', async () => {
    mockCanvas(ELS);
    const { container } = render(<ArtifactsPanel refreshKey={0} lang="en" />);

    expect(await screen.findByText('plain text body')).toBeTruthy();       // text
    expect(screen.getByText('Heading line')).toBeTruthy();                 // markdown heading
    expect(screen.getByText('bold move')).toBeTruthy();                    // markdown bold
    expect(screen.getByText('item one')).toBeTruthy();                     // markdown list line
    expect(screen.getByText('code bit')).toBeTruthy();                     // markdown inline code
    expect(screen.getByText('apples')).toBeTruthy();                       // list
    const link = screen.getByText(/quarterly report/).closest('a');        // link
    expect(link?.getAttribute('href')).toBe('https://example.com/r');
    expect(link?.getAttribute('rel')).toMatch(/noopener/);
    expect(screen.getByText('MRR')).toBeTruthy();                          // metric
    expect(screen.getByText('+6.2%')).toBeTruthy();
    expect(screen.getByText('ship artifacts')).toBeTruthy();               // table cell
    const img = container.querySelector('img.art-img');                    // same-origin image
    expect(img?.getAttribute('src')).toBe('/static/diagram.png');
    // producing agent + creation time are shown on the cards
    expect(screen.getByText('VISION')).toBeTruthy();
    const stamps = Array.from(container.querySelectorAll('.art-ts'));
    expect(stamps.length).toBe(ELS.length);
    expect(stamps.every((s) => (s.textContent || '').trim().length > 0)).toBe(true);
    // pinned state is visible
    expect(screen.getByText(/pinned/i)).toBeTruthy();
  });

  it('keeps unsafe markup inert — rendered as text, never as elements', async () => {
    mockCanvas([{
      id: 'x1', agent: 'jarvis', type: 'markdown', pinned: false, created_at: 1770000000,
      payload: { title: 'Evil', body: '<script>alert(1)</script>\n<img src=x onerror=alert(2)>\n<iframe src="https://evil.example"></iframe>' },
    }]);
    const { container } = render(<ArtifactsPanel refreshKey={0} lang="en" />);
    expect(await screen.findByText('<script>alert(1)</script>')).toBeTruthy();
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('iframe')).toBeNull();
    expect(container.querySelector('img')).toBeNull();   // the <img …> stays literal text
  });

  it('does not load remote images before explicit consent', async () => {
    mockCanvas([{
      id: 'r1', agent: 'friday', type: 'image_ref', pinned: false, created_at: 1770000000,
      payload: { title: 'Remote', src: 'https://remote.example/pix.png', alt: 'remote pic' },
    }]);
    const { container } = render(<ArtifactsPanel refreshKey={0} lang="en" />);
    expect(await screen.findByText(/remote image/i)).toBeTruthy();  // consent placeholder
    expect(container.querySelector('img')).toBeNull();              // nothing fetched
  });

  it('loads a consented remote image with referrerPolicy="no-referrer"', async () => {
    mockCanvas([{
      id: 'r1', agent: 'friday', type: 'image_ref', pinned: false, created_at: 1770000000,
      payload: { title: 'Remote', src: 'https://remote.example/pix.png', alt: 'remote pic' },
    }]);
    const { container } = render(<ArtifactsPanel refreshKey={0} lang="en" />);
    fireEvent.click(await screen.findByText(/remote image/i));
    const img = container.querySelector('img');
    expect(img?.getAttribute('src')).toBe('https://remote.example/pix.png');
    expect(img?.getAttribute('referrerpolicy')).toBe('no-referrer');
  });

  it('never renders a protocol-relative src as a same-origin image', async () => {
    mockCanvas([{
      id: 'p1', agent: 'friday', type: 'image_ref', pinned: false, created_at: 1770000000,
      payload: { title: 'Sneaky', src: '//attacker.example/pixel.png', alt: 'sneaky' },
    }]);
    const { container } = render(<ArtifactsPanel refreshKey={0} lang="en" />);
    await screen.findByText(/\/\/attacker\.example\/pixel\.png/);   // inert text, not an <img>
    expect(container.querySelector('img')).toBeNull();
  });

  it('never renders a control-char (tab/newline) URL as a same-origin image', async () => {
    // browsers strip TAB/LF/CR → "/\t/host" resolves to "//host" (cross-origin)
    for (const ctl of ['\t', '\n', '\r']) {
      mockCanvas([{
        id: 't1', agent: 'friday', type: 'image_ref', pinned: false, created_at: 1770000000,
        payload: { title: 'Ctl', src: `/${ctl}/attacker.example/pixel.png`, alt: 'ctl' },
      }]);
      const { container, unmount } = render(<ArtifactsPanel refreshKey={0} lang="en" />);
      await screen.findByText(/attacker\.example/);
      expect(container.querySelector('img')).toBeNull();
      unmount();
    }
  });

  it('pin and unpin call the existing endpoint with the right pinned flag', async () => {
    const el = ELS[0];
    global.fetch = vi.fn((url, init) => {
      const path = String(url);
      if (path === '/api/canvas') return ok({ elements: [el] });
      if (path === '/api/canvas/e1/pin?pinned=true' && init?.method === 'POST') return ok({ ...el, pinned: true });
      if (path === '/api/canvas/e1/pin?pinned=false' && init?.method === 'POST') return ok({ ...el, pinned: false });
      return Promise.reject(new Error('unexpected fetch: ' + path));
    });
    render(<ArtifactsPanel refreshKey={0} lang="en" />);
    fireEvent.click(await screen.findByText('pin'));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(
      '/api/canvas/e1/pin?pinned=true', expect.objectContaining({ method: 'POST' })));
    fireEvent.click(await screen.findByText('unpin'));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(
      '/api/canvas/e1/pin?pinned=false', expect.objectContaining({ method: 'POST' })));
  });

  it('delete calls the existing endpoint and removes the card', async () => {
    global.fetch = vi.fn((url, init) => {
      const path = String(url);
      if (path === '/api/canvas') return ok({ elements: [ELS[0]] });
      if (path === '/api/canvas/e1' && init?.method === 'DELETE') return ok({ removed: true });
      return Promise.reject(new Error('unexpected fetch: ' + path));
    });
    render(<ArtifactsPanel refreshKey={0} lang="en" />);
    expect(await screen.findByText('plain text body')).toBeTruthy();
    fireEvent.click(screen.getByText('delete'));
    await waitFor(() => expect(screen.queryByText('plain text body')).toBeNull());
    expect(global.fetch).toHaveBeenCalledWith('/api/canvas/e1', expect.objectContaining({ method: 'DELETE' }));
  });

  it('shows an honest loading state while the fetch is in flight', () => {
    global.fetch = vi.fn(() => new Promise(() => {}));   // never resolves
    render(<ArtifactsPanel refreshKey={0} lang="en" />);
    expect(screen.getByText(/loading artifacts/i)).toBeTruthy();
  });

  it('shows an honest empty state when the canvas has no elements', async () => {
    mockCanvas([]);
    render(<ArtifactsPanel refreshKey={0} lang="en" />);
    expect(await screen.findByText(/no artifacts yet/i)).toBeTruthy();
  });

  it('shows an honest API-error state with a working retry', async () => {
    let first = true;
    global.fetch = vi.fn(() => { const r = first ? fail(500) : ok({ elements: [ELS[0]] }); first = false; return r; });
    render(<ArtifactsPanel refreshKey={0} lang="en" />);
    expect(await screen.findByText(/couldn.t load artifacts/i)).toBeTruthy();
    fireEvent.click(screen.getByText(/retry/i));
    expect(await screen.findByText('plain text body')).toBeTruthy();
  });

  it('refreshes on demand via the refresh control', async () => {
    const f = mockCanvas([ELS[0]]);
    render(<ArtifactsPanel refreshKey={0} lang="en" />);
    await screen.findByText('plain text body');
    expect(f).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText(/refresh/i));
    await waitFor(() => expect(f).toHaveBeenCalledTimes(2));
  });

  it('refreshes when refreshKey changes (post-save signal from the cockpit)', async () => {
    const f = mockCanvas([ELS[0]]);
    const { rerender } = render(<ArtifactsPanel refreshKey={0} lang="en" />);
    await screen.findByText('plain text body');
    rerender(<ArtifactsPanel refreshKey={1} lang="en" />);
    await waitFor(() => expect(f).toHaveBeenCalledTimes(2));
  });
});

describe('SaveArtifactButton — explicit response saving', () => {
  // fresh object per test: the dedupe WeakSet is keyed by message identity and
  // module-level, so a shared literal saved by one test reads as "already saved"
  // in the next.
  const mkMsg = () => ({ role: 'agent', who: 'vision', text: 'the completed answer', ts: '09:02' });

  it('posts the exact governed Markdown artifact payload and reports saved', async () => {
    global.fetch = vi.fn(() => ok({ id: 'new1' }));
    const onSaved = vi.fn();
    render(<SaveArtifactButton message={mkMsg()} onSaved={onSaved} lang="en" />);
    fireEvent.click(screen.getByTitle('save to artifacts'));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(
      '/api/canvas/post',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          agent: 'vision',
          type: 'markdown',
          payload: { title: 'Saved response', body: 'the completed answer' },
          pinned: false,
        }),
      }),
    ));
    expect(await screen.findByText(/saved/i)).toBeTruthy();
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  it('truncates long replies to 4,000 chars and visibly discloses it', async () => {
    global.fetch = vi.fn(() => ok({ id: 'new2' }));
    const long = { ...mkMsg(), text: 'x'.repeat(MARKDOWN_LIMIT + 200) };
    render(<SaveArtifactButton message={long} onSaved={() => {}} lang="en" />);
    fireEvent.click(screen.getByTitle('save to artifacts'));
    expect(await screen.findByText(/truncated/i)).toBeTruthy();
    const call = global.fetch.mock.calls.find((c) => String(c[0]) === '/api/canvas/post');
    const parsed = JSON.parse(call[1].body);
    expect(parsed.payload.body.length).toBe(MARKDOWN_LIMIT);
    expect(MARKDOWN_LIMIT).toBe(4000);
  });

  it('truncates on a code-point boundary — never splits an astral char', async () => {
    global.fetch = vi.fn(() => ok({ id: 'new3' }));
    // an emoji straddling the 4,000th UTF-16 unit: a naive slice(0,4000) would
    // leave a lone high surrogate, poisoning the store on the UTF-8 write
    const text = 'x'.repeat(MARKDOWN_LIMIT - 1) + '😀' + 'y'.repeat(50);
    render(<SaveArtifactButton message={{ role: 'agent', who: 'jarvis', text }} onSaved={() => {}} lang="en" />);
    fireEvent.click(screen.getByTitle('save to artifacts'));
    expect(await screen.findByText(/truncated/i)).toBeTruthy();
    const call = global.fetch.mock.calls.find((c) => String(c[0]) === '/api/canvas/post');
    const cps = Array.from(JSON.parse(call[1].body).payload.body);
    expect(cps.length).toBe(MARKDOWN_LIMIT);
    expect(cps[cps.length - 1]).toBe('😀');   // kept whole, not split into a surrogate
  });

  it('prevents duplicate clicks while a save is in flight', async () => {
    let release;
    global.fetch = vi.fn(() => new Promise((res) => { release = res; }));
    render(<SaveArtifactButton message={mkMsg()} onSaved={() => {}} lang="en" />);
    const btn = screen.getByTitle('save to artifacts');
    fireEvent.click(btn);
    fireEvent.click(btn);
    fireEvent.click(btn);
    expect(global.fetch).toHaveBeenCalledTimes(1);
    release({ ok: true, status: 200, json: () => Promise.resolve({ id: 'n' }) });
    await screen.findByText(/saved/i);
  });

  it('shows an honest failure state and allows a retry', async () => {
    let first = true;
    global.fetch = vi.fn(() => { const r = first ? fail(500) : ok({ id: 'n' }); first = false; return r; });
    render(<SaveArtifactButton message={mkMsg()} onSaved={() => {}} lang="en" />);
    fireEvent.click(screen.getByTitle('save to artifacts'));
    expect(await screen.findByText(/save failed/i)).toBeTruthy();
    fireEvent.click(screen.getByTitle('save to artifacts'));   // retry
    expect(await screen.findByText(/✓ saved/i)).toBeTruthy();
    expect(global.fetch).toHaveBeenCalledTimes(2);
  });

  it('stays saved across an unmount/remount of the same reply (no duplicate save)', async () => {
    const once = { role: 'agent', who: 'vision', text: 'a one-time answer', ts: '09:09' };
    global.fetch = vi.fn(() => ok({ id: 'dedupe1' }));
    const { unmount } = render(<SaveArtifactButton message={once} onSaved={() => {}} lang="en" />);
    fireEvent.click(screen.getByTitle('save to artifacts'));
    await screen.findByText(/saved/i);
    expect(global.fetch).toHaveBeenCalledTimes(1);
    unmount();                                     // e.g. user switches the center tab away and back
    render(<SaveArtifactButton message={once} onSaved={() => {}} lang="en" />);
    expect(screen.getByText(/saved/i)).toBeTruthy();    // remembered — not back to '⬒ save'
    fireEvent.click(screen.getByTitle('save to artifacts'));
    expect(global.fetch).toHaveBeenCalledTimes(1);       // no duplicate POST
  });
});

describe('Conversation — save control visibility rules', () => {
  const messages = [
    { role: 'user', text: 'hello there', ts: '09:00' },
    { role: 'agent', who: 'system', text: '⚠ backend unreachable', ts: '09:00' },
    { role: 'agent', who: 'jarvis', text: '', ts: '09:01' },                    // empty
    { role: 'agent', who: 'jarvis', text: 'a completed reply', ts: '09:02' },   // completed
    { role: 'agent', who: 'vision', text: 'streaming partial…', ts: '09:03' },  // in-flight (last)
  ];

  it('shows the control only for completed non-system assistant replies', () => {
    render(<Conversation messages={messages} thinking={{ label: 'thinking' }}
      onStop={() => {}} onProv={() => {}} onArtifactSaved={() => {}} lang="en" t={t} />);
    const saves = screen.getAllByTitle('save to artifacts');
    expect(saves.length).toBe(1);   // ONLY the completed jarvis reply
  });

  it('shows the control on the last reply once streaming has finished', () => {
    render(<Conversation messages={messages} thinking={null}
      onStop={() => {}} onProv={() => {}} onArtifactSaved={() => {}} lang="en" t={t} />);
    expect(screen.getAllByTitle('save to artifacts').length).toBe(2);
  });

  it('renders no save control at all when the surface does not opt in', () => {
    render(<Conversation messages={messages} thinking={null}
      onStop={() => {}} onProv={() => {}} lang="en" t={t} />);
    expect(screen.queryByTitle('save to artifacts')).toBeNull();
  });
});
