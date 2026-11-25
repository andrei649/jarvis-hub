/* Home's registers, measured (PHASE_B_PLAN.md §5.1, §5.3, §5.4; §1.3 "a register head never cuts its
   title"). A manual lane: playwright.home-registers.config.ts, the fixture hub on its own port. The
   main lane (playwright.config.ts, which boots serve.py) ignores this file, and it skips itself
   outside its own project.

     heads    The register heads — Home's conversation and docket heads, and the conversation page's
              head — at every width from 320 to 1920px, English and Romanian, live (the fixture
              hub's own answers) and the demo sample, in Ledger dark. At each width the page does not
              scroll sideways; each head's title is drawn whole (not clipped, not ellipsised, inside
              the viewport); every run of text in the head is inside the viewport and the head and is
              not clipped by an ancestor; no part of the meta sits on the title; the rules under
              the heads of the registers that stand side by side on Home (the day, the conversation
              and the docket from 1680px; the conversation and the docket from 1100px) have their
              tops on one line, within 0.5px, whichever head wraps (home.css gives the heads one row);
              and where none of those heads wraps, each is as tall as a register head is
              (--register-head-h), so their one row adds no space (in demo the docket draws its
              large figure, which made every head beside it taller with nothing wrapping).
     held     The To's question with its switch held (a reading of the roster that failed), at 320,
              390, 740 and 1440px, English and Romanian, on the conversation page: the page does not
              scroll sideways, and every run of text in the question and both its buttons is inside
              the viewport and not clipped by an ancestor.
     docket   The docket's entry rows in every look (the seven Nerva looks dark and light, Classic ·
              Obsidian and Graphite), English and Romanian, at 320, 390, 740, 1280 and 1920px, with the
              demo sample's entries: the tier word and the title never touch (their drawn text);
              a title that does not fit ends in an ellipsis drawn by the box that holds its words,
              with the whole title in the button's name and its tooltip; nothing of an entry is drawn
              past its row; the columns line up across rows (the tier words start together, the
              titles start together, the hands end together); and the total under the rows has no
              words drawn over each other or past the docket.

   Every measurement is of what is drawn: text is measured by its client rects (Range), and its
   visible part is what is left inside every ancestor that clips. Nothing here writes to the hub:
   the fixture answers every write, and the held question's stream is stubbed. */
import { expect, test, type Page, type Route } from '@playwright/test';

type Lang = 'en' | 'ro';
type Look = { look: string; scheme: 'dark' | 'light' };

test.beforeEach(async ({}, testInfo) => {
  test.skip(testInfo.project.name !== 'home-registers', 'manual lane: npx playwright test -c playwright.home-registers.config.ts');
});

/** The appearance cache (Phase A's format) and the hub's appearance answer pinned to one choice, the
 *  first run passed, so a sync cannot flip the look in the middle of a measurement. */
async function pin(page: Page, look: Look, lang: Lang) {
  const prefs = { look: look.look, scheme: look.scheme, lang, density: 'normal', motion: 'calm', font: 'theme',
    accent: 'cyan', scanline: 'off', dotgrid: 'off' };
  await page.addInitScript(({ cache }) => {
    localStorage.setItem('hud.appearance.v1:/', JSON.stringify({ version: 2, preferences: cache }));
    localStorage.setItem('hud.seen', '1');
    localStorage.setItem('hud.firstrun.dismissed', '1');
  }, { cache: prefs });
  await page.route('**/api/preferences/appearance', (route: Route) => route.fulfill({
    status: 200, contentType: 'application/json', json: { revision: 'home-registers', configured: true, preferences: prefs },
  }));
}

/** A width, then a pause for what follows a resize (the masthead's and the running head's fit, fonts). */
async function at(page: Page, width: number, height = 900) {
  await page.setViewportSize({ width, height });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(350);
}

/* ---- the register heads ------------------------------------------------------------------------- */

const HEAD_WIDTHS = [320, 390, 600, 740, 900, 1100, 1180, 1280, 1340, 1440, 1600, 1680, 1920];
const HEAD_PAGES: Array<{ id: string; path: string; registers: string[] }> = [
  { id: 'home', path: '/v2/cockpit', registers: ['talk', 'docket'] },
  { id: 'chat', path: '/v2/chat', registers: ['talk'] },
];

/** Every head named: its title whole, its text inside the viewport and the head and not clipped, no
 *  part of its meta on the title. The page's own sideways scroll is reported too. */
async function measureHeads(page: Page, registers: string[]) {
  return page.evaluate((names) => {
    const vw = document.documentElement.clientWidth;
    const problems: string[] = [];
    if (document.documentElement.scrollWidth > vw + 0.5) problems.push(`the page scrolls sideways (${document.documentElement.scrollWidth} > ${vw})`);
    for (const name of names) {
      const head = document.querySelector<HTMLElement>(`[data-register="${name}"] > .n-register__head`);
      if (!head || !head.getBoundingClientRect().width) { problems.push(`${name}: no head drawn`); continue; }
      const hb = head.getBoundingClientRect();
      const title = head.querySelector<HTMLElement>('.n-register__title');
      if (!title) { problems.push(`${name}: no title`); continue; }
      const tb = title.getBoundingClientRect();
      if (title.scrollWidth > title.clientWidth + 0.5) problems.push(`${name}: title clipped ${title.scrollWidth} > ${title.clientWidth}`);
      if (tb.left < -0.5 || tb.right > vw + 0.5) problems.push(`${name}: title outside the viewport`);
      const walker = document.createTreeWalker(head, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        const text = (node.textContent || '').trim();
        if (!text) continue;
        const el = node.parentElement as HTMLElement;
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden' || el.closest('[data-visually-hidden]')) continue;
        const range = document.createRange();
        range.selectNodeContents(node);
        for (const r of Array.from(range.getClientRects())) {
          if (r.width === 0) continue;
          const words = `"${text.slice(0, 30)}"`;
          if (r.left < -0.5 || r.right > vw + 0.5) problems.push(`${name}: ${words} outside the viewport (${Math.round(r.left)}..${Math.round(r.right)} of ${vw})`);
          if (r.right > hb.right + 0.5 || r.left < hb.left - 0.5) problems.push(`${name}: ${words} outside the head`);
          for (let a: HTMLElement | null = el; a && a !== head.parentElement; a = a.parentElement) {
            const s = getComputedStyle(a);
            if (/(hidden|clip)/.test(s.overflowX) && a.scrollWidth > a.clientWidth + 1) { problems.push(`${name}: ${words} clipped by ${a.className || a.tagName}`); break; }
          }
        }
      }
      const meta = head.querySelector<HTMLElement>('.n-register__meta');
      if (meta) {
        for (const part of Array.from(meta.querySelectorAll<HTMLElement>('*'))) {
          const r = part.getBoundingClientRect();
          if (!r.width || !r.height) continue;
          const x = Math.min(r.right, tb.right) - Math.max(r.left, tb.left);
          const y = Math.min(r.bottom, tb.bottom) - Math.max(r.top, tb.top);
          if (x > 0.5 && y > 0.5) { problems.push(`${name}: a meta part (${part.className || part.tagName}) sits on the title`); break; }
        }
      }
    }
    // the rules under the heads of the registers side by side (their heads apart across the row and
    // level with each other): the top of each head's bottom rule, on one line within 0.5px. Registers
    // one under another (below 1100px) each keep their own head's height. And where none of the heads
    // side by side wraps (a title on two lines, a meta under its title or on two lines), each is as tall
    // as a register head is (--register-head-h): their one height adds no space in the usual case (the
    // docket's large figure made every head beside it taller with nothing wrapping)
    const textLines = (el: Element) => {
      const mids: Array<{ c: number; h: number }> = [];
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        if (!(node.textContent || '').trim() || node.parentElement?.closest('[data-visually-hidden]')) continue;
        const range = document.createRange();
        range.selectNodeContents(node);
        for (const q of Array.from(range.getClientRects())) if (q.width > 0.25 && q.height > 0.25) mids.push({ c: (q.top + q.bottom) / 2, h: q.height });
      }
      mids.sort((a, b) => a.c - b.c);
      let count = 0;
      let last = { c: 0, h: 0 };
      for (const q of mids) {
        if (count && Math.abs(q.c - last.c) < Math.min(q.h, last.h) / 2) continue;
        count += 1;
        last = q;
      }
      return count;
    };
    const ruled = Array.from(document.querySelectorAll<HTMLElement>('.n-spread > .n-spread__cell > .n-register > .n-register__head'))
      .filter((h) => h.getBoundingClientRect().width > 0)
      .map((h) => {
        const r = h.getBoundingClientRect();
        const cs = getComputedStyle(h);
        const title = h.querySelector<HTMLElement>(':scope > .n-register__title');
        const meta = h.querySelector<HTMLElement>(':scope > .n-register__meta');
        const tr = title?.getBoundingClientRect();
        const mr = meta && meta.getClientRects().length ? meta.getBoundingClientRect() : null;
        // under the title: on the head's next line, below the title's box (a meta beside the title, on its
        // baseline, overlaps the title's box, however tall the docket's figure makes it)
        const wraps = (!!title && textLines(title) > 1) || (!!mr && !!tr && (mr.top >= tr.bottom - 0.5 || textLines(meta as HTMLElement) > 1));
        return { name: h.parentElement?.getAttribute('data-register') || '?', left: r.left, right: r.right, top: r.top, height: r.height,
          rule: r.bottom - (parseFloat(cs.borderBottomWidth) || 0), own: parseFloat(cs.getPropertyValue('--register-head-h')) || 0, wraps };
      });
    const beside = new Set<number>();
    for (let i = 0; i < ruled.length; i += 1) {
      for (let j = i + 1; j < ruled.length; j += 1) {
        const [a, b] = [ruled[i], ruled[j]];
        const apart = a.right <= b.left + 0.5 || b.right <= a.left + 0.5;
        const level = Math.min(a.rule, b.rule) - Math.max(a.top, b.top) > 0;
        if (apart && level) { beside.add(i); beside.add(j); }
        if (apart && level && Math.abs(a.rule - b.rule) > 0.5) {
          problems.push(`the rules under the ${a.name} and ${b.name} heads are ${Math.abs(a.rule - b.rule).toFixed(1)}px apart (their tops at ${a.rule.toFixed(1)} and ${b.rule.toFixed(1)}px)`);
        }
      }
    }
    const side = [...beside].map((i) => ruled[i]);
    if (side.length > 1 && !side.some((h) => h.wraps)) {
      for (const h of side) {
        if (h.own > 0 && Math.abs(h.height - h.own) > 0.5) problems.push(`the ${h.name} head is ${h.height.toFixed(1)}px tall with nothing beside it wrapping; a register head is ${h.own}px`);
      }
    }
    return [...new Set(problems)];
  }, registers);
}

for (const shot of HEAD_PAGES) {
  for (const lang of ['en', 'ro'] as const) {
    for (const demo of [false, true]) {
      test(`heads · ${shot.id} · ${lang}${demo ? ' · demo' : ' · live'}: whole at every width from 320 to 1920px`, async ({ page }) => {
        await pin(page, { look: 'ledger', scheme: 'dark' }, lang);
        await page.setViewportSize({ width: HEAD_WIDTHS[0], height: 900 });
        await page.goto(shot.path + (demo ? '?demo=1' : ''));
        for (const name of shot.registers) {
          await expect(page.locator(`[data-register="${name}"] > .n-register__head`)).toBeVisible({ timeout: 20_000 });
        }
        for (const width of HEAD_WIDTHS) {
          await at(page, width);
          const problems = await measureHeads(page, shot.registers);
          expect.soft(problems, `${shot.id} ${lang}${demo ? ' demo' : ''} at ${width}px:\n${problems.join('\n')}`).toEqual([]);
        }
      });
    }
  }
}

/* ---- the held question --------------------------------------------------------------------------- */

const HELD_WIDTHS = [320, 390, 740, 1440];
const JARVIS = { id: 'jarvis', name: 'Jarvis', chat_routing: 'orchestrated', enabled: true };
const FRIGGA = { id: 'frigga', name: 'Frigga', chat_routing: 'local', enabled: true };

for (const lang of ['en', 'ro'] as const) {
  test(`held · ${lang}: the question with its switch held fits at ${HELD_WIDTHS.join(', ')}px`, async ({ page }) => {
    await pin(page, { look: 'ledger', scheme: 'dark' }, lang);
    const roster = { served: true };
    await page.route((url) => url.pathname === '/api/agents', (route) => roster.served
      ? route.fulfill({ status: 200, contentType: 'application/json', json: { agents: [JARVIS, FRIGGA] } })
      : route.fulfill({ status: 503, contentType: 'application/json', json: { detail: 'not served in this test' } }));
    const gates: Array<() => void> = [];
    await page.route((url) => url.pathname === '/chat/stream', async (route) => {
      await new Promise<void>((open) => gates.push(open));
      const frames = [{ type: 'start', agent: 'jarvis' }, { type: 'end', agent: 'jarvis', text: 'Done.' }];
      try { await route.fulfill({ status: 200, contentType: 'text/event-stream', body: frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join('') }); } catch { /* stopped */ }
    });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/v2/chat');
    const select = page.locator('[data-composer-frame] select');
    await expect(select).toBeVisible({ timeout: 20_000 });
    await page.locator('[data-composer]').fill('Think this through');
    await page.locator('[data-composer]').press('Enter');
    await expect.poll(() => gates.length).toBe(1);
    await select.selectOption('frigga');
    const question = page.locator('[data-recipient-switch="frigga"]');
    await expect(question).toBeVisible();
    // a reading of the roster that fails: the question stays, its switch held, saying why
    roster.served = false;
    await page.keyboard.press('Control+k');
    const sheet = page.getByRole('dialog');
    await expect(sheet).toHaveCount(1);
    await sheet.getByRole('combobox').fill(lang === 'ro' ? 'reîmprospătează' : 'refresh');
    await sheet.locator('[data-command="action:refresh"]').click();
    await expect(question).toHaveAttribute('data-recipient-switch-held', '');
    await expect(question.locator('.n-composer__held')).toBeVisible();
    for (const width of HELD_WIDTHS) {
      await at(page, width);
      const problems = await page.evaluate(() => {
        const vw = document.documentElement.clientWidth;
        const out: string[] = [];
        if (document.documentElement.scrollWidth > vw + 0.5) out.push(`the page scrolls sideways (${document.documentElement.scrollWidth} > ${vw})`);
        const sw = document.querySelector<HTMLElement>('[data-recipient-switch]');
        if (!sw) return ['no question drawn'];
        const frame = sw.closest<HTMLElement>('[data-composer-frame]') as HTMLElement;
        const walker = document.createTreeWalker(sw, NodeFilter.SHOW_TEXT);
        for (let node = walker.nextNode(); node; node = walker.nextNode()) {
          const text = (node.textContent || '').trim();
          if (!text) continue;
          const el = node.parentElement as HTMLElement;
          const range = document.createRange();
          range.selectNodeContents(node);
          for (const r of Array.from(range.getClientRects())) {
            if (r.width === 0) continue;
            if (r.left < -0.5 || r.right > vw + 0.5) out.push(`"${text.slice(0, 30)}" outside the viewport (${Math.round(r.right)} > ${vw})`);
            for (let a: HTMLElement | null = el; a && a !== frame.parentElement; a = a.parentElement) {
              const s = getComputedStyle(a);
              if (s.overflowX !== 'visible' || s.overflowY !== 'visible') {
                const ab = a.getBoundingClientRect();
                if (r.right > ab.right + 0.5 || r.left < ab.left - 0.5 || r.bottom > ab.bottom + 0.5 || r.top < ab.top - 0.5) {
                  out.push(`"${text.slice(0, 30)}" clipped by ${a.className || a.tagName}`);
                }
              }
            }
          }
        }
        for (const b of Array.from(sw.querySelectorAll<HTMLButtonElement>('button'))) {
          const r = b.getBoundingClientRect();
          if (r.left < -0.5 || r.right > vw + 0.5) out.push(`button "${b.textContent}" outside the viewport`);
        }
        return [...new Set(out)];
      });
      expect.soft(problems, `${lang} at ${width}px:\n${problems.join('\n')}`).toEqual([]);
    }
    gates.splice(0).forEach((open) => open());
  });
}

/* ---- the docket's rows in every look ----------------------------------------------------------- */

const LOOKS: Look[] = [
  { look: 'ledger', scheme: 'dark' }, { look: 'ledger', scheme: 'light' },
  { look: 'presence', scheme: 'dark' }, { look: 'presence', scheme: 'light' },
  { look: 'briefing', scheme: 'light' }, { look: 'briefing', scheme: 'dark' },
  { look: 'workbench', scheme: 'dark' }, { look: 'workbench', scheme: 'light' },
  { look: 'threshold', scheme: 'dark' }, { look: 'threshold', scheme: 'light' },
  { look: 'console', scheme: 'dark' }, { look: 'console', scheme: 'light' },
  { look: 'atlas', scheme: 'dark' }, { look: 'atlas', scheme: 'light' },
  // Classic: dark only (theme/registry.ts)
  { look: 'obsidian', scheme: 'dark' }, { look: 'graphite', scheme: 'dark' },
];
const DOCKET_WIDTHS = [320, 390, 740, 1280, 1920];

/** The docket's rows as drawn: what touches, what is cut and how, what leaves its row, what lines up. */
async function measureDocket(page: Page) {
  return page.evaluate(() => {
    const out: string[] = [];
    const vw = document.documentElement.clientWidth;
    if (document.documentElement.scrollWidth > vw + 0.5) out.push(`the page scrolls sideways (${document.documentElement.scrollWidth} > ${vw})`);
    const docket = document.querySelector<HTMLElement>('[data-register="docket"]');
    if (!docket) return { problems: ['no docket'], entries: 0 };
    const entries = Array.from(docket.querySelectorAll<HTMLElement>('[data-docket-entry]'));
    type Box = { left: number; right: number; top: number; bottom: number };
    const box = (r: DOMRect | Box): Box => ({ left: r.left, right: r.right, top: r.top, bottom: r.bottom });
    /** The part of `r` left inside every box from `from` up (to `stop`, without it) that clips
     *  horizontally; null when nothing of it is left. Vertical scrolling clips nothing here. Text is
     *  clipped by its own element too (`from` = the element holding it); an element's box only by
     *  its ancestors (`from` = its parent). */
    const visibleX = (from: Element | null, r: Box, stop: Element): Box | null => {
      let left = r.left;
      let right = r.right;
      for (let a = from as HTMLElement | null; a && a !== stop; a = a.parentElement) {
        if (getComputedStyle(a).overflowX === 'visible') continue;
        const ab = a.getBoundingClientRect();
        left = Math.max(left, ab.left);
        right = Math.min(right, ab.right);
      }
      return right - left > 0.5 ? { left, right, top: r.top, bottom: r.bottom } : null;
    };
    const textRuns = (root: Element) => {
      const runs: Array<{ node: Text; el: HTMLElement; rect: Box }> = [];
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode() as Text | null; node; node = walker.nextNode() as Text | null) {
        if (!(node.textContent || '').trim()) continue;
        const el = node.parentElement as HTMLElement;
        if (el.closest('[data-visually-hidden], [hidden]')) continue;
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden') continue;
        const range = document.createRange();
        range.selectNodeContents(node);
        for (const r of Array.from(range.getClientRects())) if (r.width > 0 && r.height > 0) runs.push({ node, el, rect: box(r) });
      }
      return runs;
    };
    const meets = (a: Box, b: Box) => Math.min(a.right, b.right) - Math.max(a.left, b.left) > 0.5
      && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 0.5;
    const lines: Record<string, number[]> = { risk: [], main: [], hand: [] };
    for (const li of entries) {
      const id = `entry ${li.getAttribute('data-docket-entry')}`;
      const open = li.classList.contains('n-entry--open');
      const lb = li.getBoundingClientRect();
      const stop = li.parentElement as Element;
      // the tier word and the title: their drawn text never touches
      const word = li.querySelector('.n-entry__lvl .n-tier__word');
      const title = li.querySelector('.n-entry__title');
      if (!word || !title) { out.push(`${id}: no tier word or no title`); continue; }
      const wordRuns = textRuns(word).map((r) => visibleX(r.el, r.rect, stop)).filter((r): r is Box => !!r);
      const titleRuns = textRuns(title).map((r) => visibleX(r.el, r.rect, stop)).filter((r): r is Box => !!r);
      if (!wordRuns.length) out.push(`${id}: the tier word is not drawn`);
      if (!titleRuns.length) out.push(`${id}: the title is not drawn`);
      if (wordRuns.some((w) => titleRuns.some((t) => meets(w, t)))) out.push(`${id}: the tier word "${word.textContent}" is drawn over the title`);
      // a title cut short ends in an ellipsis drawn by the box that holds its words, a box that is
      // itself whole, and the whole title stays in the button's name and in its tooltip
      if (!open) {
        const holder = title.querySelector('button') as HTMLButtonElement | null;
        const words = (title.textContent || '').trim();
        for (const run of textRuns(title)) {
          const seen = visibleX(run.el, run.rect, stop);
          const cut = !seen || run.rect.right - seen.right > 1 || seen.left - run.rect.left > 1;
          if (!cut) continue;
          const cs = getComputedStyle(run.el);
          const own = box(run.el.getBoundingClientRect());
          const ownSeen = visibleX(run.el.parentElement, own, stop);
          if (cs.textOverflow !== 'ellipsis' || cs.overflowX === 'visible' || cs.whiteSpace !== 'nowrap') {
            out.push(`${id}: the title "${words.slice(0, 40)}" is cut without an ellipsis (its box: text-overflow ${cs.textOverflow}, overflow ${cs.overflowX})`);
          } else if (!ownSeen || own.right - ownSeen.right > 1) {
            out.push(`${id}: the title's box is cut by an ancestor, so its ellipsis is not drawn`);
          }
          if (!holder || !(holder.getAttribute('aria-label') || '').includes(words)) out.push(`${id}: a cut title is not whole in its button's name`);
          if (!holder || holder.getAttribute('title') !== words) out.push(`${id}: a cut title has no tooltip with the whole title`);
        }
      }
      // nothing of the entry is drawn past its row
      for (const run of textRuns(li)) {
        const seen = visibleX(run.el, run.rect, stop);
        if (seen && (seen.left < lb.left - 0.5 || seen.right > lb.right + 0.5)) {
          out.push(`${id}: "${(run.node.textContent || '').trim().slice(0, 30)}" is drawn past the row (${Math.round(seen.left)}..${Math.round(seen.right)} of ${Math.round(lb.left)}..${Math.round(lb.right)})`);
        }
      }
      for (const el of Array.from(li.querySelectorAll<HTMLElement>('button, a, input, textarea, svg'))) {
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height) continue;
        const seen = visibleX(el.parentElement, box(r), stop);
        if (seen && (seen.left < lb.left - 0.5 || seen.right > lb.right + 0.5)) out.push(`${id}: a ${el.tagName.toLowerCase()} is drawn past the row`);
      }
      // where the columns start and end, for the closed rows (one line each below 1680px)
      if (!open) {
        const risk = li.querySelector('.n-entry__risk');
        const main = li.querySelector('.n-entry__main');
        const hand = li.querySelector('.n-entry__hand');
        if (risk) lines.risk.push(risk.getBoundingClientRect().left);
        if (main) lines.main.push(main.getBoundingClientRect().left);
        if (hand) lines.hand.push(hand.getBoundingClientRect().right);
      }
    }
    for (const [column, edges] of Object.entries(lines)) {
      if (edges.length > 1 && Math.max(...edges) - Math.min(...edges) > 0.5) {
        out.push(`the ${column} column does not line up across rows (${edges.map((e) => Math.round(e)).join(', ')})`);
      }
    }
    // the docket's total under the rows ("6 entries · 9 requests", "4 typed · 2 two-step · 0 one
    // click"): no run of its words drawn over another, none past the register
    const total = docket.querySelector('.n-docket__total');
    if (total) {
      const db = docket.getBoundingClientRect();
      const runs = textRuns(total).map((r) => ({ text: (r.node.textContent || '').trim(), rect: visibleX(r.el, r.rect, docket) }))
        .filter((r): r is { text: string; rect: Box } => !!r.rect);
      for (let i = 0; i < runs.length; i++) {
        if (runs[i].rect.left < db.left - 0.5 || runs[i].rect.right > db.right + 0.5) out.push(`the total's "${runs[i].text}" is drawn past the docket`);
        for (let j = i + 1; j < runs.length; j++) {
          if (meets(runs[i].rect, runs[j].rect)) out.push(`the total's "${runs[i].text}" and "${runs[j].text}" are drawn over each other`);
        }
      }
    }
    return { problems: [...new Set(out)], entries: entries.length };
  });
}

for (const look of LOOKS) {
  for (const lang of ['en', 'ro'] as const) {
    test(`docket · ${look.look} ${look.scheme} · ${lang}: the rows at ${DOCKET_WIDTHS.join(', ')}px`, async ({ page }, testInfo) => {
      await pin(page, look, lang);
      await page.setViewportSize({ width: DOCKET_WIDTHS[0], height: 900 });
      await page.goto('/v2/cockpit?demo=1');
      await expect(page.locator('[data-register="docket"] [data-docket-entry]').first()).toBeAttached({ timeout: 20_000 });
      await expect(page.locator('html')).toHaveAttribute('data-look', look.look);
      for (const width of DOCKET_WIDTHS) {
        await at(page, width, width >= 1280 ? 900 : 1400);
        const report = await measureDocket(page);
        expect.soft(report.entries, `${look.look} ${look.scheme} ${lang} at ${width}px: the demo entries`).toBeGreaterThan(1);
        if (report.problems.length) {
          await page.locator('[data-register="docket"]').screenshot({ path: testInfo.outputPath(`docket-${look.look}-${look.scheme}-${lang}-${width}.png`) }).catch(() => {});
        }
        expect.soft(report.problems, `${look.look} ${look.scheme} ${lang} at ${width}px:\n${report.problems.join('\n')}`).toEqual([]);
      }
    });
  }
}
