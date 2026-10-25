// @ts-nocheck
/* H221 — the globe button opens a language list (not a two-way toggle), the choice is an
   appearance preference (cached locally, synced to the narrow preference endpoint like the
   other cosmetic choices) and it drives both the I18N tables and the document's lang. */
import React from 'react';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TopBar } from '../shell';
import { LANGUAGES, V2 } from '../data';
import App from '../app';

vi.mock('../voice', () => ({useVoice: () => ({active:false, toggle:()=>{}})}));
vi.mock('../mesh', () => ({NeuralMesh:()=>null,isExecutingAgent:()=>false}));
vi.mock('../api/loaders', () => ({loadJarvisData:async()=>({}),createLatestRefreshRunner:()=>({refresh:()=>{},stop:()=>{}})}));
vi.mock('../api/live', () => ({PREVIEW_MODE_LIVE_KEYS:{},useLiveModes:()=>({live:{}})}));
vi.mock('../analytics', () => ({initAnalytics:()=>{},trackPageview:()=>{}}));
vi.mock('../modes3', () => ({ChatMode:()=> <div>Chat</div>}));
vi.mock('../gap', () => ({FirstRunGate:()=>null}));

const defaults = {font:'theme',accent:'cyan',look:'obsidian',density:'normal',motion:'system',scanline:'on',dotgrid:'off',lang:'en'};

beforeEach(() => { localStorage.clear(); history.replaceState(null, '', '/v2/chat?demo=1'); document.documentElement.lang = ''; });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('language list', () => {
  it('lists exactly the languages the I18N tables translate, English and Romanian first', () => {
    expect(LANGUAGES.map(l => l.code)).toEqual(Object.keys(V2.I18N));
    expect(LANGUAGES.slice(0, 2).map(l => l.code)).toEqual(['en', 'ro']);
    for (const l of LANGUAGES) {
      expect(l.label.trim()).not.toBe('');
      expect(['ltr', 'rtl']).toContain(l.dir);
    }
  });
});

describe('TopBar globe menu', () => {
  function renderBar(lang = 'en', setLang = vi.fn()) {
    render(<TopBar clock={new Date(0)} lang={lang} setLang={setLang} accent="cyan" agents={[]} localPct={null}
      live={false} trust={{mic:'on', strict_local:false}} llm={{state:'unknown', model:null}} demo={false} setDemo={() => {}}
      serverUp={false} onPalette={() => {}} onAmbient={() => {}} t={V2.I18N[lang]} />);
    return { setLang, globe: screen.getByRole('button', {name:/language/i}) };
  }

  it('is a menu button that opens a radio list with the active language checked', () => {
    const { globe } = renderBar('ro');
    expect(globe.getAttribute('aria-haspopup')).toBe('menu');
    expect(globe.getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByRole('menu')).toBeNull();
    fireEvent.click(globe);
    expect(globe.getAttribute('aria-expanded')).toBe('true');
    const menu = screen.getByRole('menu');
    expect(globe.getAttribute('aria-controls')).toBe(menu.id);
    const items = screen.getAllByRole('menuitemradio');
    expect(items.map(i => i.textContent)).toEqual(LANGUAGES.map(l => l.label));
    expect(items.map(i => i.getAttribute('aria-checked'))).toEqual(LANGUAGES.map(l => String(l.code === 'ro')));
    expect(screen.getByRole('menuitemradio', {name:'Română'}).getAttribute('lang')).toBe('ro');
  });

  it('chooses with the keyboard: focus lands in the list, arrows move, Enter selects and closes', () => {
    const { globe, setLang } = renderBar('en');
    fireEvent.click(globe);
    const [first, second] = screen.getAllByRole('menuitemradio');
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(first, {key:'ArrowDown'});
    expect(document.activeElement).toBe(second);
    fireEvent.keyDown(second, {key:'ArrowDown'});
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(first, {key:'End'});
    expect(document.activeElement).toBe(second);
    fireEvent.keyDown(second, {key:'Enter'});
    expect(setLang).toHaveBeenCalledWith('ro');
    expect(screen.queryByRole('menu')).toBeNull();
    expect(globe.getAttribute('aria-expanded')).toBe('false');
  });

  it('closes on Escape (returning focus to the globe) and on a click elsewhere', () => {
    const { globe, setLang } = renderBar('en');
    fireEvent.click(globe);
    fireEvent.keyDown(screen.getAllByRole('menuitemradio')[0], {key:'Escape'});
    expect(screen.queryByRole('menu')).toBeNull();
    expect(document.activeElement).toBe(globe);
    fireEvent.click(globe);
    expect(screen.getByRole('menu')).toBeTruthy();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole('menu')).toBeNull();
    expect(setLang).not.toHaveBeenCalled();
  });

  it('selects by click and shows the active language on the globe', () => {
    const { globe, setLang } = renderBar('en');
    expect(globe.textContent).toContain('EN');
    fireEvent.click(globe);
    fireEvent.click(screen.getByRole('menuitemradio', {name:'Română'}));
    expect(setLang).toHaveBeenCalledWith('ro');
    expect(screen.queryByRole('menu')).toBeNull();
  });
});

describe('App language preference', () => {
  function server(initial = {}) {
    let saved = {...defaults, ...initial};
    const fetch = vi.fn().mockImplementation(async (path, init) => {
      if (path !== '/api/preferences/appearance') return new Response(JSON.stringify({}), {status:404});
      if (init?.method === 'PUT') { const {_revision, ...patch} = JSON.parse(init.body); saved = {...saved, ...patch}; }
      return new Response(JSON.stringify({revision:'1', configured:true, preferences:saved}));
    });
    vi.stubGlobal('fetch', fetch);
    return { fetch, get saved() { return saved; } };
  }

  it('switches the strings and the document lang from the globe menu and saves it like the other preferences', async () => {
    const api = server();
    render(<App/>);
    await waitFor(() => expect(document.documentElement.lang).toBe('en'));
    fireEvent.click(screen.getByRole('button', {name:/language/i}));
    fireEvent.click(screen.getByRole('menuitemradio', {name:'Română'}));
    await waitFor(() => expect(document.documentElement.lang).toBe('ro'));
    expect(screen.getByRole('button', {name:/language/i}).textContent).toContain('RO');
    expect(screen.getByText(V2.I18N.ro.sub)).toBeTruthy();
    await waitFor(() => expect(api.saved.lang).toBe('ro'));
    expect(api.fetch.mock.calls.filter(c => c[1]?.method === 'PUT').map(c => JSON.parse(c[1].body))).toEqual([{lang:'ro', _revision:'1'}]);
    expect(localStorage.getItem('hud.lang')).toBe('ro');
  });

  it('keeps the chosen language across a reload from the local cache before the server answers', async () => {
    const api = server();
    const first = render(<App/>);
    fireEvent.click(screen.getByRole('button', {name:/language/i}));
    fireEvent.click(screen.getByRole('menuitemradio', {name:'Română'}));
    await waitFor(() => expect(api.saved.lang).toBe('ro'));
    first.unmount();
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
    render(<App/>);
    expect(screen.getByRole('button', {name:/language/i}).textContent).toContain('RO');
    expect(document.documentElement.lang).toBe('ro');
  });

  it('hydrates the language saved by another browser of the same owner', async () => {
    server({lang:'ro'});
    render(<App/>);
    await waitFor(() => expect(document.documentElement.lang).toBe('ro'));
    expect(screen.getByText(V2.I18N.ro.sub)).toBeTruthy();
  });

  it('shows the pre-sync hud.lang choice on an unconfigured server without uploading a default', async () => {
    localStorage.setItem('hud.lang', 'en');
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({configured:false, preferences:defaults})));
    vi.stubGlobal('fetch', fetch);
    render(<App/>);
    expect(screen.getByRole('button', {name:/language/i}).textContent).toContain('EN');
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    await new Promise(r => setTimeout(r, 30));
    expect(fetch.mock.calls.some(c => c[1]?.method === 'PUT')).toBe(false);
    expect(localStorage.getItem('hud.lang')).toBe('en');
  });

  // Upgrade path: the old globe wrote hud.lang ('en' by default), so 'ro' is an explicit choice. A
  // configured server document (an earlier accent/font pick) answers lang:'en' and must not revert it.
  const predatesLang = () => localStorage.setItem('hud.appearance.v1:/', JSON.stringify({version:1, preferences:{font:'theme',accent:'amber',look:'obsidian',density:'normal',motion:'system',scanline:'on',dotgrid:'off'}}));
  for (const [label, seed] of [['no v2 cache on this browser', () => {}], ['a v1 cache written before lang existed', predatesLang]]) {
    it(`keeps a legacy hud.lang=ro through hydration from a configured server and uploads it once — ${label}`, async () => {
      localStorage.setItem('hud.lang', 'ro');
      seed();
      const api = server({accent:'amber'});
      render(<App/>);
      expect(screen.getByRole('button', {name:/language/i}).textContent).toContain('RO');
      await waitFor(() => expect(api.saved.lang).toBe('ro'));
      await new Promise(r => setTimeout(r, 30));
      expect(screen.getByRole('button', {name:/language/i}).textContent).toContain('RO');
      expect(document.documentElement.lang).toBe('ro');
      expect(localStorage.getItem('hud.lang')).toBe('ro');
      expect(api.fetch.mock.calls.filter(c => c[1]?.method === 'PUT').map(c => JSON.parse(c[1].body).lang)).toEqual(['ro']);
      expect(Object.keys(localStorage).filter(k => k.includes(':edit:'))).toEqual([]);
    });
  }

  it('does not upload a legacy hud.lang twice across reloads', async () => {
    localStorage.setItem('hud.lang', 'ro');
    const api = server({accent:'amber'});
    render(<App/>);
    await waitFor(() => expect(api.saved.lang).toBe('ro'));
    cleanup();
    render(<App/>);
    await new Promise(r => setTimeout(r, 30));
    expect(api.fetch.mock.calls.filter(c => c[1]?.method === 'PUT')).toHaveLength(1);
    expect(screen.getByRole('button', {name:/language/i}).textContent).toContain('RO');
  });

  it('follows the v1 shell: jarvis:locale_changed and a hud.lang storage event reach the HUD', async () => {
    const api = server();
    render(<App/>);
    await waitFor(() => expect(document.documentElement.lang).toBe('en'));
    fireEvent(window, new CustomEvent('jarvis:locale_changed', {detail:'ro'}));
    await waitFor(() => expect(screen.getByRole('button', {name:/language/i}).textContent).toContain('RO'));
    await waitFor(() => expect(api.saved.lang).toBe('ro'));
    fireEvent(window, new StorageEvent('storage', {key:'hud.lang', newValue:'en'}));
    await waitFor(() => expect(screen.getByRole('button', {name:/language/i}).textContent).toContain('EN'));
    fireEvent(window, new CustomEvent('jarvis:locale_changed', {detail:'xx'}));
    expect(screen.getByRole('button', {name:/language/i}).textContent).toContain('EN');
  });

  it('offers every language as a palette row and switches from there', async () => {
    const api = server();
    render(<App/>);
    fireEvent.keyDown(window, {key:'k', ctrlKey:true});
    expect(await screen.findByText('Language · English ✓')).toBeTruthy();
    fireEvent.click(screen.getByText('Language · Română'));
    await waitFor(() => expect(document.documentElement.lang).toBe('ro'));
    await waitFor(() => expect(api.saved.lang).toBe('ro'));
  });
});
