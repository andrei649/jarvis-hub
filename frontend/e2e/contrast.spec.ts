/* HUD v2 · PAINTED-CONTRAST INVENTORY — the measurement axe cannot make here.
 *
 * WHY THIS EXISTS. `a11y.spec.ts` and `a11y-modes.spec.ts` run axe's `color-contrast` rule and
 * gate on `violations`. On this shell that rule mostly cannot answer: the live 1280x720 lane of
 * `a11y-modes.spec.ts` records ~701 `incomplete` color-contrast nodes against 0 violations, and
 * ~630 of those carry "Element's background color could not be determined due to a background
 * gradient". styles.css has 21 gradient/backdrop-filter declarations. So `.center-tab` lands in
 * `incomplete` and the 16 `.rail-btn` labels are not reported at all — while both are styled
 * `--ink-3`, which composites to 2.79:1 on `--void` where AA wants 4.5:1. A green axe lane there
 * does not mean the contrast is fine; it means the contrast is UNKNOWN.
 *
 * WHAT THIS DOES. It recovers the true backdrop from RENDERED PIXELS rather than from a
 * compositing model, using a two-shot differential:
 *
 *   shot A  the surface as painted
 *   shot B  the identical surface with `-webkit-text-fill-color: transparent` (and
 *           `fill: transparent` for SVG text) forced on every node
 *
 * Both properties are paint-only, so B cannot reflow — and the spec asserts that, rect by rect. B
 * is therefore pixel-exact the surface the glyph fill composited over, with every gradient,
 * `backdrop-filter: blur()`, blend mode and stacked rgba already resolved by Chromium's own
 * compositor. No compositing model is written, so no compositing model can be wrong.
 *
 * WHAT THE NUMBER IS. The verdict is SC 1.4.3's own question — does the SPECIFIED colour,
 * composited at the run's effective alpha over the backdrop those pixels prove was there, reach
 * 4.5:1 (or 3.0:1 for large text)? That is `specMin`, minimised over the glyph mask. `paintBest` —
 * the best ratio any single painted pixel actually achieved — is reported beside it but never
 * decides, because glyph antialiasing caps it below the specified ratio for small or light text
 * (2.23 against a specified 2.78 on the 7.5px rail labels), so gating on it would report a palette
 * that genuinely passes AA as a failure.
 *
 * WHAT IT DOES NOT DO — printed into the artifact as `nonClaims`, because a harness that
 * overstates its reach is the exact failure this lane exists to end:
 *   - It does not decide or change the palette. No file under frontend/src/ is touched by this
 *     work. Retiring `--ink-3` as a text colour is an owner call and is costed in BACKLOG.md.
 *   - It does not gate a merge. It runs in the e2e lane, which has no `pull_request` trigger. It
 *     asserts only on its OWN integrity, never on a ratio.
 *   - It covers ONE surface: the HUD chrome, named part by part in CHROME_PARTS. The 16 mode
 *     surfaces and every overlay are NOT measured here; measuring 17 surfaces in one process
 *     exhausted this container's memory, so they are a follow-up that grows the registry without
 *     touching the measurement core.
 *   - One look (obsidian), one viewport (1440x900), dpr 1, Chromium, EN. Other looks —
 *     `[data-look="graphite"]` redefines the ink tokens — are not measured.
 *   - Text only (SC 1.4.3). Borders, focus rings and meters are SC 1.4.11 and out of scope.
 *
 * HOW IT REFUSES TO LIE. Every text run lands in exactly one bucket — `measured`, `unpainted`,
 * `excluded` or `hidden` — every bucket is printed with its reasons, and a run bucketed `measured`
 * without a ratio is a hard failure, so "0 failing" is never sayable without the rest of the
 * numbers beside it. Two calibration nodes with known ratios (21.00 and 2.789) are injected into
 * every surface and must come back within tolerance: a broken mask, a wrong stride, a dpr slip or
 * a gamma bug moves those before it can produce a silent green. It refuses to measure a run it
 * cannot attribute: a masked ancestor, or anything painted OVER the run, sends it to `excluded`
 * rather than to a number. And it does not use Playwright's `animations: 'disabled'`, which
 * fast-forwards finite animations to their END frame and cancels infinite ones to their initial
 * frame; it pauses every animation at t=0 and asserts they are paused, so shot A and shot B are
 * the same real frame of the same animation.
 *
 * WHAT THE FIRST VERSION OF THIS FILE GOT WRONG, kept here because it is the argument for the
 * buckets. It excluded `.workzone` wholesale, which silently dropped `.center-tab` and the input
 * bar — two of the things this header says the lane exists to measure. It let `paintBest` decide
 * the verdict, so every finding was labelled by an antialiasing artefact. And it had no notion of
 * occlusion, so it published `.rl "Admin" 1.55:1` — a real-looking ratio measured through the
 * translucent WORLD toggle parked on top of that label. All three were found by review, not by the
 * lane. A harness that measures the wrong thing confidently is worse than no harness, which is why
 * the reach proofs below assert each named part is present and measured.
 */
import { test, expect, Page } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';

const VIEWPORT = { width: 1440, height: 900 };

// The nightly runs a browser matrix. This lane is defined for Chromium at devicePixelRatio 1
// only: it composites 8-bit sRGB pixels 1:1 with CSS px, and `mobile-chrome` (Pixel 5) is
// Chromium at dpr 2.75, where that mapping does not hold. Not a quarantine — the measurement
// is undefined there, and the run says so rather than reporting numbers it cannot stand behind.
//
// The predicate reads FIXTURES, not the project name: a `test.skip(callback, ...)` callback is
// `ConditionBody<TestArgs & WorkerArgs>` and is handed exactly one argument, so a second
// `testInfo` parameter arrives `undefined` and throws before the browser opens. That is not a
// guess — the first draft of this guard did it, every test in the file errored with
// `Cannot read properties of undefined (reading 'project')`. Nothing on this
// branch compiles this file, which is why the mistake reached a run at all — a sibling PR adds
// `frontend/tsconfig.e2e.json` + `npm run typecheck:e2e`, and under that config it is named
// exactly: TS2769 "Target signature provides too few arguments. Expected 2 or more, but got 1."
// Keying on `deviceScaleFactor` is also the truer test: it is the property the pixel arithmetic
// actually needs, not a project label.
test.skip(
  ({ browserName, deviceScaleFactor }) => browserName !== 'chromium' || (deviceScaleFactor ?? 1) !== 1,
  'painted-contrast is defined for Chromium at devicePixelRatio 1 only',
);

const NON_CLAIMS = [
  'Does not decide or change the palette; no frontend/src file is touched by this lane.',
  'Does not gate a merge: it asserts only on its own integrity, never on a contrast ratio.',
  'Covers the HUD CHROME only — exactly the parts listed in header.parts. The 16 mode surfaces and every overlay (palette, console, ambient, cinema, first-run) are NOT measured by this lane.',
  'One look (obsidian), one viewport (1440x900), devicePixelRatio 1, Chromium, EN only.',
  'Text contrast (SC 1.4.3) only. Non-text contrast (SC 1.4.11) is out of scope.',
  'The verdict is specMin — the SPECIFIED colour over the measured backdrop. paintBest is reported but never decides: antialiasing caps it below the specified ratio for small or light text.',
  "A run with its own text-shadow is measured, and flagged ownShadow. CSS paints a text shadow beneath the glyph fill, so shot B is still what the fill composited over — but that backdrop includes the run's own halo, which is not the surface behind the element.",
  'A run under a masked ancestor, or under an element that paints over it (a background, image, backdrop-filter or shadow), is excluded rather than measured. The ticker marquee (mask-image edge fade) and the rail label under the fixed WORLD toggle land there.',
  'Occlusion detection samples 9 points per client rect and only counts an occluder that paints. A transparent element whose own GLYPHS overlap the run is not detected; those pixels are suppressed in shot B too, so they enter the mask and can move the ratio.',
  'Animations are paused at t=0, not disabled, so both shots are the same real frame; a different frame of a moving element could differ.',
  'A run whose glyphs paint no measurable pixels is reported as `unpainted`, never as a pass.',
];

/** WCAG 2.x relative luminance from an 8-bit sRGB triple. */
function lum(r: number, g: number, b: number): number {
  const f = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
function ratioOf(l1: number, l2: number): number {
  const [hi, lo] = l1 >= l2 ? [l1, l2] : [l2, l1];
  return (hi + 0.05) / (lo + 0.05);
}

type Run = {
  identity: string; surface: string; cssPathHint: string; text: string;
  fg: [number, number, number]; alpha: number; fontPx: number; weight: number;
  required: number; rects: { x: number; y: number; w: number; h: number }[];
  cal?: 'pass' | 'fail'; bucket?: string; reason?: string; specMin?: number; paintBest?: number;
  ownShadow?: boolean; paintedBelow?: boolean; verdict?: string; instances?: number;
};

/* ---------------------------------------------------------------- in-page probe */
/** Collect every painted text run under `rootSel`, with the style facts a ratio needs. */
const PROBE = ([rootSel, includeSel]: [string, string[]]) => {
  const root = document.querySelector(rootSel);
  if (!root) return { error: `root ${rootSel} not found` } as any;
  const missing = includeSel.filter((s) => !root.querySelector(s));
  if (missing.length) return { error: `chrome parts absent from ${rootSel}: ${missing.join(', ')}` } as any;

  const parseRgb = (s: string): [number, number, number, number] | null => {
    const m = /rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.%]+))?\s*\)/.exec(s);
    if (!m) return null;
    let a = 1;
    if (m[4] !== undefined) a = m[4].endsWith('%') ? parseFloat(m[4]) / 100 : parseFloat(m[4]);
    return [+m[1], +m[2], +m[3], a];
  };

  const out: any[] = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) nodes.push(n as Text);

  for (const node of nodes) {
    const raw = node.textContent || '';
    if (!raw.replace(/\s+/g, '')) continue;                       // whitespace-only
    const el = node.parentElement;
    if (!el) continue;
    // An INCLUDE list, not an exclude list. The chrome is exactly these parts, and naming them
    // positively is what stops the file claiming reach it does not have: the first version
    // excluded `.workzone` wholesale, which silently dropped `.center-tab` and the input bar —
    // two of the things the header says this lane exists to measure — because both render inside
    // `.workzone cockpit` (app.tsx:424, 436-439, 446). A reach proof below asserts each part is
    // present and measured, so that failure mode cannot recur silently.
    if (!includeSel.some((s) => el.closest(s))) continue;

    // a masked ancestor makes the painted result unrelated to the specified colour
    let masked = false;
    for (let a: Element | null = el; a; a = a.parentElement) {
      const cs = getComputedStyle(a);
      if ((cs.maskImage && cs.maskImage !== 'none') || ((cs as any).webkitMaskImage && (cs as any).webkitMaskImage !== 'none')) { masked = true; break; }
    }

    const cs = getComputedStyle(el);
    const isSvg = el.namespaceURI === 'http://www.w3.org/2000/svg';
    const colourSrc = isSvg ? (cs.fill === 'currentcolor' ? cs.color : cs.fill) : cs.color;
    const parsed = parseRgb(colourSrc);

    // effective alpha: the node's own colour alpha times every ancestor opacity
    let alpha = parsed ? parsed[3] : 1;
    for (let a: Element | null = el; a && a !== document.documentElement.parentElement; a = a.parentElement) {
      const o = parseFloat(getComputedStyle(a).opacity);
      if (!Number.isNaN(o) && o < 1) alpha *= o;
    }

    const r = document.createRange();
    r.selectNodeContents(node);
    const rects = [...r.getClientRects()]
      .map((b) => ({ x: Math.floor(b.x), y: Math.floor(b.y), w: Math.ceil(b.width), h: Math.ceil(b.height) }))
      .filter((b) => b.w > 0 && b.h > 0 && b.x < innerWidth && b.y < innerHeight && b.x + b.w > 0 && b.y + b.h > 0);

    // Painted OVER by something else? The effective-alpha walk above climbs ANCESTORS, so it is
    // blind to an element stacked on top of this one. That is not hypothetical: at 1440x900 the
    // fixed z-60 WORLD toggle (`button.tool-btn`, rgba(10,22,38,.55), rect 16,855,73x29 —
    // world_app.tsx:32) covers the `Admin` rail label at rect 32,873,25x9. Because the veil is
    // only 55% opaque the glyphs still change pixels, so the |A-B| mask fires, the run looks
    // measurable, and shot B holds the VEIL rather than the rail's own backdrop. The first
    // version of this file published that as `.rl "Admin" 1.55:1` — a real-looking number for a
    // surface no one styled. Anything painted above the run makes the recovered backdrop the
    // wrong surface, so the run is excluded rather than guessed at.
    // Only an element that can PAINT counts. Hit-testing alone over-excludes badly: `.clock-time`
    // sits under `.clock-date`'s box and `div.k` under `.l1`'s, both fully transparent siblings
    // that put no pixel over the run. Measured on this surface, requiring a painting occluder is
    // the difference between excluding 7 runs and excluding the 1 that is actually veiled.
    const paints = (e: Element) => {
      const c = getComputedStyle(e);
      const bg = /rgba?\(\s*[\d.]+[,\s]+[\d.]+[,\s]+[\d.]+(?:[,\s/]+([\d.]+))?\s*\)/.exec(c.backgroundColor);
      const bgAlpha = bg ? (bg[1] === undefined ? 1 : parseFloat(bg[1])) : 0;
      return bgAlpha > 0 || c.backgroundImage !== 'none'
        || (c.backdropFilter && c.backdropFilter !== 'none')
        || (c.boxShadow && c.boxShadow !== 'none');
    };
    let occluded = false;
    for (const b of rects) {
      const xs = [b.x + 1, b.x + b.w / 2, b.x + b.w - 1];
      const ys = [b.y + 1, b.y + b.h / 2, b.y + b.h - 1];
      for (const px of xs) {
        for (const py of ys) {
          const stack = document.elementsFromPoint(px, py);
          const at = stack.indexOf(el);
          // A sample point can miss `el`'s inline box (a rect corner outside the glyph run). That
          // is not evidence of occlusion, so `at < 0` must not promote the whole stack to
          // "above" — doing so counted `.topbar`'s own gradient as an occluder and excluded the
          // clock and four status keys. Ancestors (`e.contains(el)`) and descendants
          // (`el.contains(e)`) are never occluders; only unrelated painting elements are.
          const above = at < 0 ? stack : stack.slice(0, at);
          if (above.some((e) => !el.contains(e) && !e.contains(el) && paints(e))) { occluded = true; break; }
        }
        if (occluded) break;
      }
      if (occluded) break;
    }

    // `text-shadow` survives `-webkit-text-fill-color: transparent` — Chromium keeps painting the
    // shadow from the glyph outline. That is NOT a defect and the run is NOT excluded: CSS paints
    // a text shadow BENEATH the glyph fill, so shot B is still exactly the surface the fill
    // composited over. It is recorded because "backdrop" then means something a reader would not
    // assume — the run's own halo is part of it — and a disclosed number beats a tidy one.
    const ownShadow = cs.textShadow !== 'none' && cs.textShadow !== '';

    const fontPx = parseFloat(cs.fontSize);
    const weight = parseInt(cs.fontWeight, 10) || 400;
    const pt = Math.ceil(fontPx * 72) / 96;                        // axe's arithmetic
    const large = weight >= 700 ? pt >= 14 : pt >= 18;

    // identity: owner path + normalised text + style tuple. NO nth-child, NO coordinates —
    // adding one roster row must not rename every finding.
    const owners: string[] = [];
    for (let a: Element | null = el; a && owners.length < 4; a = a.parentElement) {
      const c = (a.getAttribute && a.getAttribute('class')) || '';
      if (c.trim()) owners.push(c.trim().split(/\s+/).sort().join('.'));
    }
    const text = raw.trim().replace(/\s+/g, ' ').slice(0, 80);
    const styleTuple = `${colourSrc}/${alpha.toFixed(2)}/${fontPx}/${weight}`;

    out.push({
      ownerPath: owners.join('>'), text, styleTuple,
      cssPathHint: `${el.tagName.toLowerCase()}${el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).join('.') : ''}`,
      fg: parsed ? [parsed[0], parsed[1], parsed[2]] : null,
      alpha, fontPx, weight, required: large ? 3 : 4.5,
      rects, masked, occluded, ownShadow, unparseable: !parsed,
      cal: el.closest('[data-cc-cal]') ? el.closest('[data-cc-cal]')!.getAttribute('data-cc-cal') : null,
    });
  }
  return { runs: out };
};

/* ------------------------------------------------- in-page pixel reduction (no deps) */
/** Decode both shots in the browser and reduce each run to specMin / paintBest. */
const REDUCE = async (payload: { a: string; b: string; runs: any[] }) => {
  const load = async (b64: string) => {
    // NOT fetch(dataURL) and NOT <img src=dataURL>: the served /v2 page ships a CSP that
    // blocks both. Decoding base64 to a Blob in-page touches no URL scheme at all.
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const bmp = await createImageBitmap(new Blob([bytes], { type: 'image/png' }));
    const c = new OffscreenCanvas(bmp.width, bmp.height);
    const ctx = c.getContext('2d')!;
    ctx.drawImage(bmp, 0, 0);
    return { d: ctx.getImageData(0, 0, bmp.width, bmp.height), w: bmp.width, h: bmp.height };
  };
  const A = await load(payload.a);
  const B = await load(payload.b);
  if (A.w !== B.w || A.h !== B.h) return { error: `shot size mismatch ${A.w}x${A.h} vs ${B.w}x${B.h}` };

  const f = (c: number) => { const s = c / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; };
  const L = (r: number, g: number, b: number) => 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  const R = (x: number, y: number) => { const [hi, lo] = x >= y ? [x, y] : [y, x]; return (hi + 0.05) / (lo + 0.05); };

  const results: any[] = [];
  for (const run of payload.runs) {
    let specMin = Infinity, paintBest = 0, painted = 0, area = 0;
    for (const rc of run.rects) {
      const x0 = Math.max(0, rc.x), y0 = Math.max(0, rc.y);
      const x1 = Math.min(A.w, rc.x + rc.w), y1 = Math.min(A.h, rc.y + rc.h);
      area += Math.max(0, x1 - x0) * Math.max(0, y1 - y0);
      for (let y = y0; y < y1; y++) {
        for (let x = x0; x < x1; x++) {
          const i = (y * A.w + x) * 4;
          const ar = A.d.data[i], ag = A.d.data[i + 1], ab = A.d.data[i + 2];
          const br = B.d.data[i], bg = B.d.data[i + 1], bb = B.d.data[i + 2];
          // the glyph mask: a pixel the text actually changed
          if (Math.max(Math.abs(ar - br), Math.abs(ag - bg), Math.abs(ab - bb)) < 3) continue;
          painted++;
          const lb = L(br, bg, bb);
          if (run.fg) {
            // composite the SPECIFIED colour at full coverage over this backdrop pixel
            const cr = run.alpha * run.fg[0] + (1 - run.alpha) * br;
            const cg = run.alpha * run.fg[1] + (1 - run.alpha) * bg;
            const cb = run.alpha * run.fg[2] + (1 - run.alpha) * bb;
            const s = R(L(cr, cg, cb), lb);
            if (s < specMin) specMin = s;
          }
          const p = R(L(ar, ag, ab), lb);          // what the pixel actually achieved
          if (p > paintBest) paintBest = p;
        }
      }
    }
    results.push({ painted, area, specMin: specMin === Infinity ? null : specMin, paintBest: paintBest || null });
  }
  return { results };
};

/* --------------------------------------------------------------------- surfaces */
/** The HUD chrome, named part by part. `.center-tabs` and `.inputbar` live INSIDE
 *  `.workzone cockpit` (app.tsx:424, 436-439, 446), so a `.workzone` exclusion would drop them —
 *  and `.center-tab` is half the reason this lane exists, being exactly what axe parks in
 *  `incomplete` over a gradient. Listing the parts positively keeps the claim and the code the
 *  same sentence, and PROBE errors if any of them is absent rather than measuring a smaller HUD. */
const CHROME_ROOT = '.hud-root';
const CHROME_PARTS = ['.topbar', '.ticker', '.rail', '.center-tabs', '.inputbar'];

/* ----------------------------------------------------------------- spec helpers */
async function settleAndFreeze(page: Page) {
  await page.waitForFunction(() => {
    const w = window as any;
    const n = document.querySelectorAll('*').length;
    const now = performance.now();
    if (!w.__ccSettle || w.__ccSettle.n !== n) { w.__ccSettle = { n, since: now }; return false; }
    return now - w.__ccSettle.since > 400;
  }, undefined, { timeout: 25_000 });
  await page.evaluate(() => {
    // NOT Playwright's animations:'disabled'. That option fast-forwards FINITE animations to
    // their end frame and cancels infinite ones to their initial frame — two different states,
    // neither of them a frame the page ever holds in normal use. Pausing at t=0 puts A and B on
    // the same real frame of the same animation. (For `.tex-scanbar` specifically the two happen
    // to coincide: `@keyframes scanmove` has an implicit `from`, so cancel() and currentTime=0
    // land on the same pixels. The reason to pause is the general case, not that element.)
    document.getAnimations().forEach((a) => { a.pause(); try { a.currentTime = 0; } catch { /* some are unseekable */ } });
  });
  expect(
    await page.evaluate(() => document.getAnimations().every((a) => a.playState === 'paused')),
    'every animation must be paused before the two shots, or A and B are different frames',
  ).toBe(true);
}

/** Two calibration nodes with known ratios. They prove the whole pixel chain, every surface. */
async function injectCalibration(page: Page, rootSel: string) {
  await page.evaluate((sel) => {
    document.querySelectorAll('[data-cc-cal]').forEach((n) => n.remove());
    const host = document.querySelector(sel) || document.body;
    const mk = (kind: string, bg: string, fg: string, top: number, label: string) => {
      const d = document.createElement('div');
      d.setAttribute('data-cc-cal', kind);
      d.style.cssText = `position:fixed;left:8px;top:${top}px;z-index:2147483647;padding:6px 10px;`
        + `font:700 18px/1.2 monospace;background:${bg};color:${fg};`;
      d.textContent = label;
      host.appendChild(d);   // inside the measured root, or the probe never walks it
    };
    mk('pass', '#000000', '#ffffff', 8, 'CALIBRATIONPASS');
    mk('fail', '#04070e', 'rgba(233,244,253,.34)', 48, 'CALIBRATIONFAIL');
  }, rootSel);
}

const SUPPRESS = '*,*::before,*::after{-webkit-text-fill-color:transparent !important;}'
  + 'svg text,svg tspan{fill:transparent !important;}';

/** Probe, shoot A, suppress text, assert no reflow, shoot B, reduce in-page. */
async function measure(page: Page, surface: string, root: string, include: string[], withCalibration = false) {
  // The calibration nodes are opaque and position:fixed, so while they are on screen they
  // OCCLUDE whatever sits under them — and the A/B mask cannot tell occluded content from
  // real content: it would report the calibration box's own pixels under the covered
  // element's identity. (Measured the hard way: the CALFAIL box at top:48 covers the brand
  // text at y=55, and "JARVIS" came back painting at 2.81:1 with A's brightest pixel 89/255
  // when nothing in its ancestor chain dims it at all.) So calibration gets its own pass,
  // and the inventory pass runs with no calibration on screen.
  if (withCalibration) await injectCalibration(page, root);
  else await page.evaluate(() => document.querySelectorAll('[data-cc-cal]').forEach((n) => n.remove()));
  await settleAndFreeze(page);

  // The include list names the chrome. The calibration nodes are not part of the chrome, so they
  // are only in reach on the pass that injects them — which also means the inventory pass cannot
  // accidentally measure them even if one survived a removal.
  const probeSel = withCalibration ? [...include, '[data-cc-cal]'] : include;

  const clip = { x: 0, y: 0, width: VIEWPORT.width, height: VIEWPORT.height };
  const geom = (rs: any[]) => rs.map((r: any) => `${r.ownerPath}|${JSON.stringify(r.rects)}`).join('\n');

  // The two shots must be of the SAME page. This HUD re-renders from timers — the clock
  // ticks, the ticker advances, demo rows arrive — and a row that appears between A and B
  // puts background in B that was not in A, so the |A-B| mask would light that whole region
  // up as "painted" and invent ratios for it. Text CHURN is fine (B holds no text at all);
  // a changed run count or a moved rect is not. Retry rather than measure a moving target,
  // and if it will not hold still, say so instead of reporting numbers.
  let raw: any[] | null = null;
  let shotA = '', shotB = '', styleId = '';
  let lastMismatch = '';
  for (let attempt = 0; attempt < 4 && !raw; attempt++) {
    const before: any = await page.evaluate(PROBE, [root, probeSel] as [string, string[]]);
    expect(before.error, `probe could not find root ${root} on ${surface}`).toBeFalsy();
    const a = (await page.screenshot({ clip, scale: 'css' })).toString('base64');

    styleId = await page.evaluate((css) => {
      const el = document.createElement('style');
      el.id = 'cc-suppress';
      el.textContent = css;
      document.head.appendChild(el);
      return el.id;
    }, SUPPRESS);

    const after: any = await page.evaluate(PROBE, [root, probeSel] as [string, string[]]);
    const b = (await page.screenshot({ clip, scale: 'css' })).toString('base64');
    await page.evaluate((id) => document.getElementById(id)?.remove(), styleId);

    if (after.runs.length === before.runs.length && geom(after.runs) === geom(before.runs)) {
      raw = before.runs; shotA = a; shotB = b;
    } else {
      lastMismatch = after.runs.length !== before.runs.length
        ? `run count ${before.runs.length} -> ${after.runs.length}`
        : 'a rect moved';
      await page.waitForTimeout(600);
    }
  }
  expect(
    raw,
    `${surface}: could not capture a stable A/B pair in 4 attempts (${lastMismatch}). `
    + 'Shot B is only shot A\'s backdrop if the page held still between them, so this '
    + 'surface is reported as uncapturable rather than measured.',
  ).not.toBeNull();

  const reduced: any = await page.evaluate(REDUCE, { a: shotA, b: shotB, runs: raw!.map((r: any) => ({ rects: r.rects, fg: r.fg, alpha: r.alpha })) });
  expect(reduced.error, `${surface}: ${reduced.error}`).toBeFalsy();

  const runs: Run[] = [];
  raw!.forEach((r: any, i: number) => {
    const m = reduced.results[i];
    let bucket = 'measured';
    let reason: string | undefined;
    if (r.unparseable) { bucket = 'excluded'; reason = 'unparseable-color'; }
    else if (r.masked) { bucket = 'excluded'; reason = 'masked-ancestor'; }
    else if (r.occluded) { bucket = 'excluded'; reason = 'occluded'; }
    else if (!r.rects.length) { bucket = 'hidden'; reason = 'no-box'; }
    else if (m.painted < 4 || m.painted < 0.01 * m.area) { bucket = 'unpainted'; reason = 'glyphs-changed-no-pixels'; }

    const specMin = m.specMin ?? undefined;
    const paintBest = m.paintBest ?? undefined;
    runs.push({
      identity: `${surface}|${r.ownerPath}|${r.text}|${r.styleTuple}`,
      surface, cssPathHint: r.cssPathHint, text: r.text,
      fg: r.fg, alpha: r.alpha, fontPx: r.fontPx, weight: r.weight, required: r.required,
      rects: r.rects, cal: r.cal || undefined, bucket, reason, specMin, paintBest,
      ownShadow: r.ownShadow || undefined, verdict: verdictOf(bucket, specMin, r.required),
      paintedBelow: bucket === 'measured' && paintBest !== undefined ? paintBest < r.required : undefined,
    });
  });
  return runs;
}

/** The verdict is SC 1.4.3's own question: does the SPECIFIED colour, composited over the backdrop
 *  these pixels prove was there, reach the required ratio? `paintBest` deliberately does NOT decide
 *  it. paintBest is the best ratio any single painted pixel achieved, and glyph antialiasing caps
 *  it well below the specified ratio for small or light text — on the 7.5px rail labels it reads
 *  2.23 against a specified 2.78 — so gating on it would report a palette that genuinely passes AA
 *  as a painted failure. It is reported beside every measured run instead, as corroboration. */
function verdictOf(bucket: string, specMin: number | undefined, required: number) {
  if (bucket !== 'measured' || specMin === undefined) return 'n/a';
  return specMin < required ? 'FAIL' : 'PASS';
}

/** Collapse identical decisions; a chip repeated ten times is ONE decision with a blast radius. */
function collapse(runs: Run[]) {
  const byIdentity = new Map<string, Run>();
  for (const r of runs) {
    const prev = byIdentity.get(r.identity);
    if (!prev) { byIdentity.set(r.identity, { ...r, instances: 1 }); continue; }
    prev.instances = (prev.instances || 1) + 1;
    if (r.specMin !== undefined && (prev.specMin === undefined || r.specMin < prev.specMin)) prev.specMin = r.specMin;
    if (r.paintBest !== undefined && (prev.paintBest === undefined || r.paintBest > prev.paintBest)) prev.paintBest = r.paintBest;
    // The merged group takes the WORST specMin across its instances, so its verdict has to be
    // recomputed from that number. Carrying the first instance's verdict would let the group
    // print one ratio and be filtered on another — the two disagreeing is exactly the kind of
    // quiet inconsistency this lane exists to refuse, whether or not a page reaches it today.
    prev.verdict = verdictOf(prev.bucket!, prev.specMin, prev.required);
    if (r.paintedBelow) prev.paintedBelow = true;
  }
  return [...byIdentity.values()];
}

/* ------------------------------------------------------------------------ the lane */
test('painted-contrast inventory: the HUD chrome', async ({ page }) => {
  test.setTimeout(180_000);
  await page.setViewportSize(VIEWPORT);
  await page.addInitScript(() => { try { localStorage.setItem('hud.firstrun.dismissed', '1'); } catch { /* private mode */ } });
  await page.goto('/v2/?demo=1', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });

  expect(
    await page.evaluate(() => window.devicePixelRatio),
    'this lane composites 8-bit sRGB pixels 1:1 with CSS px; a dpr other than 1 invalidates that',
  ).toBe(1);
  await page.evaluate(() => (document as any).fonts.ready);

  // Reach proof: the chrome must actually contain the elements this lane exists for.
  // .rail-btn and .center-tab are styled --ink-3 and are exactly what axe cannot judge —
  // .center-tab lands in `incomplete` on a gradient backdrop and the rail labels are not
  // reported at all. If they are not here, the run proves nothing.
  const railCount = await page.locator('.rail-btn').count();
  expect(railCount, 'the chrome must expose the mode rail; it is the surface axe cannot read').toBe(16);
  expect(
    await page.locator('.rail-btn .rl').first().textContent(),
    'rail buttons must carry their text labels, or there is no text to measure',
  ).toBeTruthy();
  const tabCount = await page.locator('.center-tab').count();
  expect(tabCount, '.center-tab is the other blind spot — axe parks it in `incomplete` over a gradient').toBe(3);
  expect(
    await page.locator('.inputbar').count(),
    'the input bar is named in nonClaims as covered, so it must be on screen to be covered',
  ).toBe(1);

  // Pass 1 — calibration only. Proves the pixel chain end to end on this very run.
  const calPass = await measure(page, 'chrome', CHROME_ROOT, CHROME_PARTS, true);
  const cals = calPass.filter((r) => r.cal);
  expect(cals.length, 'calibration nodes vanished; the pixel chain is unproven').toBeGreaterThanOrEqual(2);
  for (const c of cals) {
    expect(c.bucket, `calibration node (${c.cal}) did not paint`).toBe('measured');
    const want = c.cal === 'pass' ? 21.0 : 2.789;
    expect(
      Math.abs((c.specMin ?? 0) - want),
      `calibration ${c.cal}: specMin ${c.specMin?.toFixed(3)} vs expected ${want} — the mask, `
      + 'stride, dpr or gamma is wrong, so every ratio in this run is suspect',
    ).toBeLessThan(0.05);
  }

  // Pass 2 — the real inventory, with nothing of ours on screen to occlude it.
  const all = await measure(page, 'chrome', CHROME_ROOT, CHROME_PARTS, false);
  expect(
    all.filter((r) => r.cal).length,
    'the calibration nodes must be gone for the inventory pass, or they occlude real content',
  ).toBe(0);

  const body = all;
  const groups = collapse(body);
  const buckets = body.reduce((acc: any, r) => { acc[r.bucket!] = (acc[r.bucket!] || 0) + 1; return acc; }, {});
  const reasons = body.filter((r) => r.reason).reduce((acc: any, r) => { acc[r.reason!] = (acc[r.reason!] || 0) + 1; return acc; }, {});
  const total = Object.values(buckets).reduce((a: any, b: any) => (a as number) + (b as number), 0) as number;
  const failing = groups.filter((g) => g.verdict === 'FAIL');

  mkdirSync('e2e/artifacts', { recursive: true });
  writeFileSync('e2e/artifacts/contrast-painted-chrome-obsidian-1440x900.json', JSON.stringify({
    header: {
      surface: 'chrome', lane: 'obsidian', viewport: VIEWPORT, dpr: 1,
      parts: CHROME_PARTS, railButtons: railCount, centerTabs: tabCount,
      method: 'two-shot differential: A as painted, B with text fill forced transparent (paint-only; geometry asserted identical)',
      convention: 'unrounded composite, WCAG 2.x relative luminance, ratio minimised over glyph-mask pixels',
      verdictFrom: 'specMin — the SPECIFIED colour composited over the measured backdrop (SC 1.4.3). '
        + 'paintBest is reported but never decides: glyph antialiasing caps it below the specified '
        + 'ratio for small or light text, so gating on it would fail a palette that passes AA.',
    },
    nonClaims: NON_CLAIMS,
    buckets, reasons, denominator: total,
    counts: { runs: body.length, decisions: groups.length, failingDecisions: failing.length },
    failing: failing.sort((a, b) => (a.specMin ?? 99) - (b.specMin ?? 99)).map((g) => ({
      text: g.text, cssPathHint: g.cssPathHint, instances: g.instances,
      fg: g.fg, alpha: g.alpha, fontPx: g.fontPx, weight: g.weight, ownShadow: g.ownShadow,
      required: g.required, specMin: g.specMin, paintBest: g.paintBest,
      paintedBelow: g.paintedBelow, verdict: g.verdict,
    })),
    // `ownShadow` rides on `decisions[]`, not only on `failing[]`: the sole shadowed run in this
    // chrome is `.clock-time`, 40px large text that passes at required 3.0, so it is never in
    // `failing[]`. Without this a reader greps the artifact for `ownShadow`, finds nothing, and
    // concludes no published number includes a glyph's own halo.
    decisions: groups.map((g) => ({
      identity: g.identity, bucket: g.bucket, instances: g.instances,
      specMin: g.specMin, paintBest: g.paintBest, ownShadow: g.ownShadow, verdict: g.verdict,
    })),
  }, null, 2));

  console.log(`painted contrast · chrome · ${body.length} runs -> ${groups.length} decisions`);
  console.log(`  buckets: ${JSON.stringify(buckets)} (denominator ${total})`);
  console.log(`  reasons: ${JSON.stringify(reasons)}`);
  for (const why of ['masked-ancestor', 'occluded', 'glyphs-changed-no-pixels']) {
    const owners = [...new Set(body.filter((r) => r.reason === why).map((r) => r.cssPathHint))];
    if (owners.length) console.log(`  ${why}: ${owners.slice(0, 6).join(', ')}${owners.length > 6 ? ` (+${owners.length - 6})` : ''}`);
  }
  console.log(`  ${failing.length} decisions below their AA threshold:`);
  for (const g of failing.slice(0, 30)) {
    console.log(`    ${(g.specMin ?? 0).toFixed(2)}:1 (need ${g.required}) x${g.instances}  ${g.cssPathHint}  "${g.text.slice(0, 44)}"`);
  }
  if (failing.length > 30) console.log(`    ... and ${failing.length - 30} more, all in the artifact`);

  // `total === body.length` is an arithmetic identity — `buckets` is one increment per run — so
  // asserting it proves nothing. These can fail: every run must carry a bucket this file knows how
  // to report, and every run called `measured` must actually carry both numbers. A future bucket
  // added without a reporting path, or a `measured` run with no ratio, goes red here instead of
  // quietly shrinking the denominator the report prints.
  const KNOWN = ['measured', 'unpainted', 'excluded', 'hidden'];
  const strayBucket = body.filter((r) => !KNOWN.includes(r.bucket!));
  expect(
    strayBucket.map((r) => `${r.bucket}:${r.cssPathHint}`),
    'every run must land in a bucket this report knows how to print',
  ).toEqual([]);
  const hollow = body.filter((r) => r.bucket === 'measured' && (r.specMin === undefined || r.paintBest === undefined));
  expect(
    hollow.map((r) => `${r.cssPathHint} "${r.text.slice(0, 20)}"`),
    'a run bucketed `measured` with no ratio would be counted as a pass it never earned',
  ).toEqual([]);
  expect(total, 'the printed denominator must be the run count').toBe(body.length);

  // Non-vacuity, stated as the thing this lane exists for rather than as a magic number:
  // the 16 rail labels are styled --ink-3 and axe does not report them at all. If they are
  // not in `measured`, this lane has not done the one job that justifies it.
  const railRuns = body.filter((r) => r.bucket === 'measured' && /\brl\b/.test(r.cssPathHint));
  expect(
    railRuns.length,
    `the rail labels must be MEASURED — they are what axe cannot see. Got ${railRuns.length} `
    + `in bucket 'measured' (buckets: ${JSON.stringify(buckets)})`,
  ).toBeGreaterThanOrEqual(15);
  const tabRuns = body.filter((r) => r.bucket === 'measured' && /center-tab/.test(r.cssPathHint));
  expect(
    tabRuns.length,
    `.center-tab is the run axe reports as \`incomplete\` over a gradient — the other half of this `
    + `lane's reason to exist. Got ${tabRuns.length} in bucket 'measured'`,
  ).toBe(3);
  // `header.parts` publishes `.inputbar` as covered, and NON_CLAIMS[2] defers to that list — so
  // "present" is not enough. This file has just added a bucket that removes runs quietly: a fixed
  // overlay over the composer, or a mask on an ancestor, would send every input-bar run to
  // `excluded` while the lane stayed green and still claimed the part. Then a reader pairing the
  // coverage claim with a short `failing` list would conclude the composer was measured and passed.
  const barRuns = body.filter((r) => r.bucket === 'measured' && /inputbar|chan|transmit|mic/.test(r.cssPathHint));
  expect(
    barRuns.length,
    `the input bar is published in header.parts as covered, so at least one of its runs must be `
    + `MEASURED and not merely on screen. Got ${barRuns.length} (buckets: ${JSON.stringify(buckets)})`,
  ).toBeGreaterThanOrEqual(1);
});

/* --------------------------------------------------------------- red proofs (§5.2) */
test('red proof: a deliberately dimmed node is reported, not passed', async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize(VIEWPORT);
  await page.addInitScript(() => { try { localStorage.setItem('hud.firstrun.dismissed', '1'); } catch { /* nope */ } });
  await page.goto('/v2/?demo=1', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });

  const before = await measure(page, 'chrome', CHROME_ROOT, CHROME_PARTS);
  const cleanFails = before.filter((r) => !r.cal && r.verdict === 'FAIL').length;

  await page.addStyleTag({ content: '.topbar,.topbar *{color:rgba(233,244,253,.06) !important;}' });
  const after = await measure(page, 'chrome', CHROME_ROOT, CHROME_PARTS);
  const dimmedFails = after.filter((r) => !r.cal && r.verdict === 'FAIL').length;

  expect(
    dimmedFails,
    'forcing the topbar to 6% alpha must produce MORE failures; if it does not, '
    + 'the measurement is not reading the page it thinks it is',
  ).toBeGreaterThan(cleanFails);
});

test('red proof: an invisible node lands in `unpainted`, never in `measured`', async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize(VIEWPORT);
  await page.addInitScript(() => { try { localStorage.setItem('hud.firstrun.dismissed', '1'); } catch { /* nope */ } });
  await page.goto('/v2/?demo=1', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#root')).not.toBeEmpty({ timeout: 20_000 });

  await page.addStyleTag({ content: '.brand .l1{visibility:hidden !important;}' });
  const runs = await measure(page, 'chrome', CHROME_ROOT, CHROME_PARTS);
  const hidden = runs.filter((r) => !r.cal && /JARVIS|NERVA/i.test(r.text));

  expect(hidden.length, 'the brand text run should still be enumerated even when invisible').toBeGreaterThan(0);
  for (const h of hidden) {
    expect(
      h.bucket,
      `an invisible run must be bucketed \`unpainted\`, not counted as a pass — got ${h.bucket} for "${h.text}"`,
    ).not.toBe('measured');
  }
});
