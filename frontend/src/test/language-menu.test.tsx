// @ts-nocheck
/* H221 — the language is an appearance preference (cached locally, synced to the narrow
   preference endpoint like the other cosmetic choices) and it drives both the HUD's strings and
   the document's lang and dir.

   The App chooses it from the masthead's EN | RO radio group (LangSeg) and from the sheet's
   "Language · …" rows (PHASE_B_PLAN.md §8.3); the same claims as the HUD v2 globe menu's, which was
   deleted with the top bar: persistence, `lang`/`dir`, `hud.lang` for the v1 shell and
   `jarvis:locale_changed` from it. frame/Masthead.test.tsx pins the radio group itself. */
import React from 'react';
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LANGUAGES, V2 } from '../data';
import App from '../app';
import { resetPolling } from '../signals/poll';

vi.mock('../voice', () => ({useVoice: () => ({active:false, toggle:()=>{}, status:'idle'})}));
vi.mock('../mesh', () => ({NeuralMesh:()=>null,isExecutingAgent:()=>false}));
vi.mock('../api/loaders', () => ({loadJarvisData:async()=>({}),createLatestRefreshRunner:()=>({refresh:()=>{},stop:()=>{}})}));
vi.mock('../api/live', () => ({PREVIEW_MODE_LIVE_KEYS:{},useLiveModes:()=>({live:{}})}));
vi.mock('../analytics', () => ({initAnalytics:()=>{},trackPageview:()=>{}}));
vi.mock('../modes3', () => ({}));
vi.mock('../gap', () => ({FirstRunGate:()=>null}));

const defaults = {font:'theme',accent:'cyan',look:'obsidian',density:'normal',motion:'system',scanline:'on',dotgrid:'off',lang:'en'};

beforeEach(() => { resetPolling(); localStorage.clear(); history.replaceState(null, '', '/v2/chat?demo=1'); document.documentElement.lang = ''; document.documentElement.dir = ''; });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); resetPolling(); });

/** The masthead's language radio group, and the code of the language it has checked ('EN' | 'RO'). */
const langSeg = () => document.querySelector('[data-frame="masthead"] [role="radiogroup"]') as HTMLElement | null;
const chosen = () => langSeg()?.querySelector('[role="radio"][aria-checked="true"]')?.textContent ?? null;
/** The radio for a language, by the name the masthead gives it in the language on screen. */
const radio = (name: string) => within(langSeg() as HTMLElement).getByRole('radio', {name});

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

  it('switches the strings and the document lang from the masthead\'s EN | RO radio group and saves it like the other preferences', async () => {
    const api = server();
    render(<App/>);
    await waitFor(() => expect(document.documentElement.lang).toBe('en'));
    expect(chosen()).toBe('EN');
    expect(screen.getByRole('navigation', {name:'Areas'})).toBeTruthy();
    fireEvent.click(radio('Romanian'));
    await waitFor(() => expect(document.documentElement.lang).toBe('ro'));
    expect(document.documentElement.dir).toBe('ltr');
    expect(chosen()).toBe('RO');
    // the radio group names itself and its choices in the language on screen
    expect(langSeg()?.getAttribute('aria-label')).toBe('Limbă');
    expect(radio('Română').getAttribute('aria-checked')).toBe('true');
    // the frame's own strings switched: the masthead's areas, its Find and the page title
    expect(screen.getByRole('navigation', {name:'Zone'})).toBeTruthy();
    expect(screen.queryByRole('navigation', {name:'Areas'})).toBeNull();
    expect(screen.getByRole('button', {name:/^Caută sau rulează o comandă/})).toBeTruthy();
    await waitFor(() => expect(document.title).toBe('Conversație · Acasă · Nerva'));
    await waitFor(() => expect(api.saved.lang).toBe('ro'));
    expect(api.fetch.mock.calls.filter(c => c[1]?.method === 'PUT').map(c => JSON.parse(c[1].body))).toEqual([{lang:'ro', _revision:'1'}]);
    expect(localStorage.getItem('hud.lang')).toBe('ro');
  });

  it('chooses with the keyboard: one stop in the tab order, the arrows move the choice', async () => {
    const api = server();
    render(<App/>);
    await waitFor(() => expect(document.documentElement.lang).toBe('en'));
    const radios = within(langSeg() as HTMLElement).getAllByRole('radio');
    expect(radios.map(r => r.textContent)).toEqual(['EN', 'RO']);
    expect(radios.map(r => r.getAttribute('tabindex'))).toEqual(['0', '-1']);
    radios[0].focus();
    fireEvent.keyDown(radios[0], {key:'ArrowRight'});
    await waitFor(() => expect(document.documentElement.lang).toBe('ro'));
    expect(chosen()).toBe('RO');
    expect(document.activeElement?.getAttribute('lang')).toBe('ro');
    await waitFor(() => expect(api.saved.lang).toBe('ro'));
  });

  it('keeps the chosen language across a reload from the local cache before the server answers', async () => {
    const api = server();
    const first = render(<App/>);
    fireEvent.click(radio('Romanian'));
    await waitFor(() => expect(api.saved.lang).toBe('ro'));
    first.unmount();
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
    render(<App/>);
    expect(chosen()).toBe('RO');
    expect(document.documentElement.lang).toBe('ro');
  });

  it('hydrates the language saved by another browser of the same owner', async () => {
    server({lang:'ro'});
    render(<App/>);
    await waitFor(() => expect(document.documentElement.lang).toBe('ro'));
    expect(chosen()).toBe('RO');
    expect(screen.getByRole('navigation', {name:'Zone'})).toBeTruthy();
  });

  it('shows the pre-sync hud.lang choice on an unconfigured server without uploading a default', async () => {
    localStorage.setItem('hud.lang', 'en');
    const fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify({configured:false, preferences:defaults})));
    vi.stubGlobal('fetch', fetch);
    render(<App/>);
    expect(chosen()).toBe('EN');
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
      expect(chosen()).toBe('RO');
      await waitFor(() => expect(api.saved.lang).toBe('ro'));
      await new Promise(r => setTimeout(r, 30));
      expect(chosen()).toBe('RO');
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
    expect(chosen()).toBe('RO');
  });

  it('follows the v1 shell: jarvis:locale_changed and a hud.lang storage event reach the HUD', async () => {
    const api = server();
    render(<App/>);
    await waitFor(() => expect(document.documentElement.lang).toBe('en'));
    fireEvent(window, new CustomEvent('jarvis:locale_changed', {detail:'ro'}));
    await waitFor(() => expect(chosen()).toBe('RO'));
    expect(document.documentElement.lang).toBe('ro');
    await waitFor(() => expect(api.saved.lang).toBe('ro'));
    fireEvent(window, new StorageEvent('storage', {key:'hud.lang', newValue:'en'}));
    await waitFor(() => expect(chosen()).toBe('EN'));
    fireEvent(window, new CustomEvent('jarvis:locale_changed', {detail:'xx'}));
    expect(chosen()).toBe('EN');
    expect(document.documentElement.lang).toBe('en');
  });

  it('offers every language as a row of the search sheet and switches from there', async () => {
    const api = server();
    render(<App/>);
    fireEvent.keyDown(window, {key:'k', ctrlKey:true});
    const sheet = await screen.findByRole('dialog', {name:'Search or run a command'});
    // the appearance rows keep the palette's words; the sheet lists them for a query
    fireEvent.change(within(sheet).getByRole('combobox'), {target:{value:'language'}});
    for (const l of LANGUAGES) expect(within(sheet).getByText(`Language · ${l.label}${l.code === 'en' ? ' ✓' : ''}`)).toBeTruthy();
    fireEvent.click(within(sheet).getByText('Language · Română'));
    await waitFor(() => expect(document.documentElement.lang).toBe('ro'));
    expect(chosen()).toBe('RO');
    await waitFor(() => expect(api.saved.lang).toBe('ro'));
  });
});
