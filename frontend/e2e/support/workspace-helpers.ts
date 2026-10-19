/* Nerva Workspace e2e · shared helpers for workspace-journey.spec.ts.

   PageGuard  — fails a step on any console error or uncaught page error. The only console errors
                it lets through are HTTP failures the step declared up front (`expectHttp`), each
                matched by URL and status and each required to have happened: Chromium logs every
                non-2xx fetch as "Failed to load resource", so a deliberate 404 probe would read as
                a failure, and an undeclared one is exactly what this guard exists to catch.
   checkPage  — the per-page quality bar: an axe scan (WCAG 2.0/2.1 A + AA, failing on serious or
                critical) in the light theme at 1280×800 and 390×844 and in the dark theme at
                1280×800; layout faults at those sizes and at 320×640 and 1024×768 (a page wider
                than the screen, a badge out of its card, a locality chip that wraps or is cut
                short, a split table header, a dialog or drawer control outside its surface); and
                screenshots at the two main sizes. `tableScrollsSideways` measures a table's own
                sideways scroll (the run history must fit 1024 px, UX-22).
   focus      — keyboard checks axe cannot make: the focused control keeps a solid outline in
                forced-colours mode, and Shift+Tab never leaves focus under the sticky top bar.
   mail       — the SMTP sink's JSON-lines file, polled until the expected message arrives, the
                sink's off switch (setSmtpSink) and its greeting hold (holdSmtpGreeting,
                waitForSmtpConnection), through support/workspace_smtp.py.
   model      — the model server's off switch (setModelServer, through support/workspace_model.py).
   documents  — the four Romanian sample files, written by workspace_docs.py. */
import AxeBuilder from '@axe-core/playwright';
import { expect, test, type ConsoleMessage, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createConnection } from 'node:net';
import path from 'node:path';

export const RUN_DIR = process.env.WS_E2E_RUN_DIR || '';
export const SMTP_PORT = Number(process.env.WS_E2E_SMTP_PORT || 0);
export const MODEL_PORT = Number(process.env.WS_E2E_MODEL_PORT || 0);
export const SETUP_CODE = process.env.WS_E2E_SETUP_CODE || '';

export const DESKTOP = { width: 1280, height: 800 } as const;
export const PHONE = { width: 390, height: 844 } as const;

function testDir(): string {
  return test.info().project.testDir;
}

export function repoRoot(): string {
  return path.resolve(testDir(), '..', '..');
}

/** Screenshots and axe reports: e2e/.results/workspace-screens/, or WS_E2E_RESULTS_DIR/workspace-screens
    when a run must not overwrite the shared folder (several agents on one checkout). */
export function screenDir(): string {
  const base = process.env.WS_E2E_RESULTS_DIR || path.join(testDir(), '.results');
  return path.join(base, 'workspace-screens');
}

// ── console and page-error guard ────────────────────────────────────────────────────

interface ExpectedHttp { url: RegExp; status: number; seen: number; required: boolean }

const FAILED_RESOURCE = /^Failed to load resource: the server responded with a status of (\d{3})/;

export class PageGuard {
  readonly problems: string[] = [];
  private expected: ExpectedHttp[] = [];

  constructor(readonly page: Page, readonly who: string) {
    page.on('console', (message) => this.onConsole(message));
    page.on('pageerror', (error) => this.problems.push(`[${who}] uncaught page error: ${error.stack || error.message}`));
    page.on('crash', () => this.problems.push(`[${who}] the page crashed`));
  }

  /** Declares an HTTP failure this step causes on purpose (a 404 probe, a wrong password). */
  expectHttp(url: RegExp, status: number): void {
    this.expected.push({ url, status, seen: 0, required: true });
  }

  /** Tolerates an HTTP failure that may or may not happen in this step (a background poll that
      races a revoked session); unlike `expectHttp` it is not required to occur. */
  allowHttp(url: RegExp, status: number): void {
    this.expected.push({ url, status, seen: 0, required: false });
  }

  private onConsole(message: ConsoleMessage): void {
    if (message.type() !== 'error') return;
    const text = message.text();
    const failed = FAILED_RESOURCE.exec(text);
    if (failed) {
      const status = Number(failed[1]);
      const url = message.location().url || '';
      const match = this.expected.find((e) => e.status === status && e.url.test(url));
      if (match) { match.seen += 1; return; }
      this.problems.push(`[${this.who}] unexpected HTTP ${status} for ${url}`);
      return;
    }
    this.problems.push(`[${this.who}] console error: ${text} (${message.location().url || 'no location'})`);
  }

  /** Every problem since the last check, plus declared failures that never happened. */
  takeProblems(): string[] {
    const found = [...this.problems];
    for (const e of this.expected) {
      if (e.required && e.seen === 0) found.push(`[${this.who}] the declared HTTP ${e.status} for ${e.url} never happened`);
    }
    this.problems.length = 0;
    this.expected = [];
    return found;
  }
}

const guards: PageGuard[] = [];

export function guard(page: Page, who: string): PageGuard {
  const existing = guards.find((g) => g.page === page);
  if (existing) return existing;
  const created = new PageGuard(page, who);
  guards.push(created);
  page.on('close', () => {
    const index = guards.indexOf(created);
    if (index >= 0 && created.problems.length === 0) guards.splice(index, 1);
  });
  return created;
}

export function guardFor(page: Page): PageGuard {
  const found = guards.find((g) => g.page === page);
  if (!found) throw new Error('this page has no guard; create it with guard(page, who)');
  return found;
}

/** Called after every step: fails it on any console error, page error or missing expected error. */
export function assertNoPageProblems(): void {
  const problems = guards.flatMap((g) => g.takeProblems());
  for (const g of [...guards]) if (g.page.isClosed()) guards.splice(guards.indexOf(g), 1);
  expect(problems, `console / page errors during this step:\n${problems.join('\n')}`).toEqual([]);
}

// ── axe + screenshots ───────────────────────────────────────────────────────────────

type Impact = 'critical' | 'serious' | 'moderate' | 'minor';
const BLOCKING: readonly Impact[] = ['critical', 'serious'];

/** Fonts loaded, the network quiet, and every CSS animation (drawer slide, toast rise) finished
    — axe reads computed colours, so it must not scan a half-faded surface. Waits on the
    animations themselves rather than on a fixed delay. */
async function settle(page: Page): Promise<void> {
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  await page.waitForLoadState('networkidle').catch(() => undefined);
  await page.waitForFunction(
    () => document.getAnimations().every((a) => a.playState !== 'running' || (a.effect?.getTiming().iterations ?? 1) === Infinity),
    undefined, { timeout: 5_000 },
  ).catch(() => undefined);
}

async function axeScan(page: Page, name: string, size: string): Promise<string[]> {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  const dir = path.join(screenDir(), 'axe');
  mkdirSync(dir, { recursive: true });
  const focused = await page.evaluate(() => (document.activeElement ? document.activeElement.outerHTML.slice(0, 160) : null));
  writeFileSync(path.join(dir, `${name}-${size}.json`), JSON.stringify({ url: page.url(), focused, violations: results.violations }, null, 2));
  return results.violations
    .filter((v) => BLOCKING.includes((v.impact ?? 'minor') as Impact))
    .map((v) => `${name} @${size}: ${v.impact} ${v.id} — ${v.help}\n    ${v.nodes.slice(0, 5).map((n) => n.target.join(' ')).join('\n    ')}`);
}

/** Closes the toasts still showing, so a screenshot shows the page and not the last confirmation.
    A toast may close itself between the count and the click (they live 4–8 s): such a click is
    given up after a second instead of waiting out the whole test (the journey's one flake). */
async function dismissToasts(page: Page): Promise<void> {
  const close = page.locator('.ws-toasts .ws-toast__close');
  for (let guard = 0; guard < 10 && await close.count() > 0; guard += 1) {
    await close.first().click({ timeout: 1_000 }).catch(() => undefined);
  }
}

/** Layout faults axe does not look for: a page wider than the viewport (sideways scrolling on
    a phone), a badge or locality chip that sticks out of the card or drawer holding it, and a report table whose
    header is split inside a word. */
async function layoutFaults(page: Page, name: string, size: string): Promise<string[]> {
  const faults = await page.evaluate(() => {
    const found: string[] = [];
    const root = document.documentElement;
    if (root.scrollWidth > root.clientWidth + 1) found.push(`the page is ${root.scrollWidth}px wide in a ${root.clientWidth}px viewport`);
    for (const badge of Array.from(document.querySelectorAll<HTMLElement>('.ws-badge, .ws-locality'))) {
      const box = badge.closest<HTMLElement>('.ws-card, .ws-surface');
      if (!box || badge.closest('[role="region"][tabindex="0"]')) continue;
      const inner = badge.getBoundingClientRect();
      const outer = box.getBoundingClientRect();
      if (inner.width > 0 && (inner.right > outer.right + 1 || inner.left < outer.left - 1)) {
        found.push(`badge "${(badge.textContent || '').trim()}" overflows its ${box.className.split(' ')[0]}`);
      }
    }
    // A locality chip („Pe serverul companiei") on two lines, or cut short with an ellipsis: it
    // never wraps (UX-22), and the places that hold it give it the room or use the short form.
    for (const chip of Array.from(document.querySelectorAll<HTMLElement>('.ws-locality'))) {
      if (chip.getBoundingClientRect().width === 0) continue;
      // Every line box of the text it shows, whatever its markup (text read but not shown — a
      // 1 px visually hidden span — is not part of the look).
      const tops: number[] = [];
      let height = Infinity;
      const walker = document.createTreeWalker(chip, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        const holder = node.parentElement;
        if (!holder || !(node.textContent || '').trim() || holder.getBoundingClientRect().width <= 1) continue;
        const range = document.createRange();
        range.selectNodeContents(node);
        for (const r of Array.from(range.getClientRects()).filter((rect) => rect.width > 0 && rect.height > 0)) {
          tops.push(r.top);
          height = Math.min(height, r.height);
        }
      }
      for (const part of Array.from(chip.querySelectorAll<HTMLElement>('.ws-locality__text, .ws-locality__full'))) {
        if (part.getBoundingClientRect().width <= 1) continue;
        if (part.scrollWidth > part.clientWidth + 1) found.push(`locality chip "${(part.textContent || '').trim()}" is cut short (${part.clientWidth}px of ${part.scrollWidth}px)`);
      }
      if (tops.length > 0 && Math.max(...tops) - Math.min(...tops) > height / 2) {
        found.push(`locality chip "${chip.getAttribute('title') || (chip.textContent || '').trim()}" wraps onto more than one line (${Math.round(chip.getBoundingClientRect().width)}px wide)`);
      }
    }
    // A table header split inside a word ("Docum" + "ent"): the cell is narrower than its
    // longest word, which a table in a sideways-scrolling frame never needs to be.
    const probe = document.createElement('span');
    probe.style.cssText = 'position:absolute;visibility:hidden;white-space:nowrap;left:-9999px;top:0';
    document.body.appendChild(probe);
    for (const cell of Array.from(document.querySelectorAll<HTMLElement>('.ws-md th'))) {
      const style = getComputedStyle(cell);
      probe.style.font = style.font;
      probe.style.letterSpacing = style.letterSpacing;
      const room = cell.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      for (const word of (cell.textContent || '').split(/\s+/).filter(Boolean)) {
        probe.textContent = word;
        if (probe.getBoundingClientRect().width > room + 0.5) found.push(`table header word "${word}" is split (${Math.round(room)}px of room)`);
      }
    }
    probe.remove();
    // A segmented group's button whose label wraps onto a second line: the group's buttons share
    // the width equally, so on a phone a long label ("Exportă Markdown") broke in two (UX-21).
    // Text read but not shown (a 1 px screen-reader-only span) is not part of the look.
    for (const button of Array.from(document.querySelectorAll<HTMLElement>('.ws-btn-group > .ws-btn'))) {
      if (button.getBoundingClientRect().width === 0) continue;
      const lines: DOMRect[] = [];
      const walker = document.createTreeWalker(button, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        const holder = node.parentElement;
        if (!holder || !(node.textContent || '').trim() || holder.getBoundingClientRect().width <= 1) continue;
        const range = document.createRange();
        range.selectNodeContents(node);
        lines.push(...Array.from(range.getClientRects()).filter((r) => r.width > 0 && r.height > 0));
      }
      if (lines.length === 0) continue;
      const height = Math.min(...lines.map((r) => r.height));
      const tops = lines.map((r) => r.top);
      if (Math.max(...tops) - Math.min(...tops) > height / 2) {
        found.push(`the label of "${(button.getAttribute('aria-label') || button.textContent || '').trim()}" wraps onto more than one line (${Math.round(button.getBoundingClientRect().width)}px wide)`);
      }
    }
    // A dialog or drawer control outside its surface or off screen: a footer that spilled off
    // the left edge left Delete and Re-index unreachable on phones (UX-01 / A11Y-01).
    for (const surface of Array.from(document.querySelectorAll<HTMLElement>('.ws-surface'))) {
      const box = surface.getBoundingClientRect();
      for (const control of Array.from(surface.querySelectorAll<HTMLElement>('button, a[href], input, select, textarea'))) {
        if (control.closest('.ws-sr-only') || control.hidden || (control as HTMLInputElement).type === 'hidden') continue;
        const r = control.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) continue;
        const left = Math.max(box.left, 0);
        const right = Math.min(box.right, document.documentElement.clientWidth);
        if (r.left < left - 1 || r.right > right + 1) {
          found.push(`"${(control.textContent || control.getAttribute('aria-label') || control.tagName).trim()}" lies outside its ${surface.getAttribute('role') ?? 'surface'} (${Math.round(r.left)}..${Math.round(r.right)} in ${Math.round(left)}..${Math.round(right)})`);
        }
      }
    }
    return found;
  });
  return faults.map((fault) => `${name} @${size}: ${fault}`);
}

export const NARROW = { width: 320, height: 640 } as const;
/** A small laptop: the sidebar shows and the main column is at its narrowest (UX-22). */
export const LAPTOP = { width: 1024, height: 768 } as const;

/** The light-themed page's axe scan once more in the dark theme (the tokens differ). */
async function axeScanDark(page: Page, name: string): Promise<string[]> {
  const previous = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'));
  await settle(page);
  try {
    return await axeScan(page, `${name}-dark`, '1280x800');
  } finally {
    await page.evaluate((theme) => {
      if (theme === null) document.documentElement.removeAttribute('data-theme');
      else document.documentElement.setAttribute('data-theme', theme);
    }, previous);
    // Colour transitions run back to the light theme; the screenshot must not catch them midway.
    await settle(page);
  }
}

/** axe (serious/critical fail), layout faults and a full-page screenshot, at desktop and at phone
    size. The scan runs first, with any toast still on screen, so toasts are checked too. */
export async function checkPage(page: Page, name: string): Promise<void> {
  const original = page.viewportSize() ?? DESKTOP;
  const blocking: string[] = [];
  const layout: string[] = [];
  mkdirSync(screenDir(), { recursive: true });
  for (const [size, viewport] of [['1280x800', DESKTOP], ['390x844', PHONE]] as const) {
    await page.setViewportSize(viewport);
    await settle(page);
    blocking.push(...await axeScan(page, name, size));
    if (viewport === DESKTOP) blocking.push(...await axeScanDark(page, name));
    layout.push(...await layoutFaults(page, name, size));
    await dismissToasts(page);
    // A full-page capture of a scrolled page paints the sticky top bar mid-page.
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(screenDir(), `${name}-${size}.png`), fullPage: true });
  }
  // The narrowest phones and a 1280 px desktop zoomed to 400 %, and a small laptop: layout only.
  for (const [size, viewport] of [['320x640', NARROW], ['1024x768', LAPTOP]] as const) {
    await page.setViewportSize(viewport);
    await settle(page);
    layout.push(...await layoutFaults(page, name, size));
  }
  await page.setViewportSize(original);
  await settle(page);
  expect(blocking, `axe found serious/critical violations:\n${blocking.join('\n')}`).toEqual([]);
  expect(layout, `layout faults:\n${layout.join('\n')}`).toEqual([]);
}

/** Whether the table named *caption* scrolls sideways inside its frame at the current size
    (the page itself never does; the frame does when a table is wider than the room — UX-22).
    Returns the overflow in px (0 = it fits). */
export async function tableScrollsSideways(page: Page, caption: string): Promise<number> {
  const table = page.getByRole('table', { name: caption });
  await table.waitFor();
  return table.evaluate((node) => {
    const frame = node.closest<HTMLElement>('.ws-table-scroll');
    return frame ? Math.max(0, frame.scrollWidth - frame.clientWidth) : 0;
  });
}

// ── the SMTP sink ───────────────────────────────────────────────────────────────────

export interface SinkMail {
  mail_from: string;
  rcpt_tos: string[];
  subject: string;
  from: string;
  to: string;
  /** The decoded text/plain body ('' when absent). */
  text: string;
  /** The decoded text/html body ('' when absent). */
  html: string;
}

function python(): string {
  return process.env.E2E_PYTHON || path.join(repoRoot(), process.platform === 'win32' ? '.venv\\Scripts\\python.exe' : '.venv/bin/python');
}

/** Every message the sink accepted so far, MIME-decoded by workspace_mail.py. */
export function readMail(): SinkMail[] {
  const out = execFileSync(python(), [path.join(testDir(), 'support', 'workspace_mail.py'), path.join(RUN_DIR, 'mail.jsonl')],
    { cwd: repoRoot(), encoding: 'utf8' });
  return JSON.parse(out) as SinkMail[];
}

/** Whether something speaks SMTP on the sink's port right now: true once the server greets
    (220), false when the port refuses the connection or stays silent. The probe says QUIT and
    waits for the server to close, so the sink never writes to a socket that is already gone. */
function smtpAnswers(): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = createConnection({ host: '127.0.0.1', port: SMTP_PORT });
    let greeted = false;
    let settled = false;
    const done = (answer: boolean) => {
      if (settled) return;
      settled = true;
      socket.destroy();
      resolve(answer);
    };
    socket.setTimeout(2_000, () => done(greeted));
    socket.on('error', () => done(greeted));
    socket.on('close', () => done(greeted));
    socket.on('data', (chunk) => {
      if (greeted) return;
      greeted = chunk.toString('utf8').startsWith('220');
      if (greeted) socket.write('QUIT\r\n');
      else done(false);
    });
  });
}

/** Takes the SMTP sink down (its port refuses connections, as when the mail relay is down) or
    brings it back on the same port, through support/workspace_smtp.py's control file; returns
    once the port itself agrees. The hub's email settings are not touched. */
export async function setSmtpSink(state: 'up' | 'down'): Promise<void> {
  const control = path.join(RUN_DIR, 'smtp.down');
  if (state === 'down') writeFileSync(control, 'down\n');
  else rmSync(control, { force: true });
  const stateFile = path.join(RUN_DIR, 'smtp.state');
  await expect.poll(() => (existsSync(stateFile) ? readFileSync(stateFile, 'utf8').trim() : ''),
    { message: `the SMTP sink did not report "${state}" (support/workspace_smtp.py)`, timeout: 10_000 }).toBe(state);
  await expect.poll(smtpAnswers, { message: `the SMTP port did not ${state === 'up' ? 'answer again' : 'stop answering'}`, timeout: 10_000 })
    .toBe(state === 'up');
}

function holdState(): { held: boolean; connections: number } | null {
  const file = path.join(RUN_DIR, 'smtp.hold.state');
  if (!existsSync(file)) return null;
  const [word, count] = readFileSync(file, 'utf8').trim().split(/\s+/);
  return { held: word === 'held', connections: Number(count) };
}

/** Holds every new SMTP connection before its greeting (a slow relay; at most 30 s, see
    tests/support/smtp_sink.py → GATE_TIMEOUT) or releases them, through workspace_smtp.py's
    control file; returns how many connections the sink had accepted once it agrees. */
export async function holdSmtpGreeting(held: boolean): Promise<number> {
  const control = path.join(RUN_DIR, 'smtp.hold');
  if (held) writeFileSync(control, 'hold\n');
  else rmSync(control, { force: true });
  await expect.poll(() => holdState()?.held, { message: `the SMTP sink did not report its greeting ${held ? 'held' : 'released'}`, timeout: 10_000 })
    .toBe(held);
  return holdState()?.connections ?? 0;
}

/** Waits until the sink has accepted more than *seen* connections (the hub started a delivery). */
export async function waitForSmtpConnection(seen: number, timeout = 60_000): Promise<void> {
  await expect.poll(() => holdState()?.connections ?? 0, { message: 'nobody connected to the SMTP sink', timeout }).toBeGreaterThan(seen);
}

// ── the model server ────────────────────────────────────────────────────────────────

/** Whether the model server answers HTTP on its port right now. */
async function modelAnswers(): Promise<boolean> {
  try {
    const response = await fetch(`http://127.0.0.1:${MODEL_PORT}/health`, { signal: AbortSignal.timeout(2_000) });
    return response.ok;
  } catch {
    return false;
  }
}

/** Stops the model server (its port refuses connections, as when LM Studio is stopped) or starts
    it again on the same port, through support/workspace_model.py's control file; returns once
    the port itself agrees. The hub's settings are not touched. */
export async function setModelServer(state: 'up' | 'down'): Promise<void> {
  const control = path.join(RUN_DIR, 'model.down');
  if (state === 'down') writeFileSync(control, 'down\n');
  else rmSync(control, { force: true });
  const stateFile = path.join(RUN_DIR, 'model.state');
  await expect.poll(() => (existsSync(stateFile) ? readFileSync(stateFile, 'utf8').trim() : ''),
    { message: `the model server did not report "${state}" (support/workspace_model.py)`, timeout: 10_000 }).toBe(state);
  await expect.poll(modelAnswers, { message: `the model port did not ${state === 'up' ? 'answer again' : 'stop answering'}`, timeout: 10_000 })
    .toBe(state === 'up');
}

/** Polls the sink until a message matching *predicate* arrives; returns it. */
export async function waitForMail(predicate: (mail: SinkMail) => boolean, what: string): Promise<SinkMail> {
  let found: SinkMail | undefined;
  await expect.poll(() => { found = readMail().find(predicate); return Boolean(found); },
    { message: `no message in mail.jsonl for: ${what}`, timeout: 20_000 }).toBe(true);
  return found as SinkMail;
}

// ── sample documents ────────────────────────────────────────────────────────────────

export interface SampleDoc { path: string; file: string; title: string; fact: string }
export type SampleKey = 'docx' | 'pdf' | 'xlsx' | 'csv';

export function buildDocuments(): Record<SampleKey, SampleDoc> {
  const out = execFileSync(python(), [path.join(testDir(), 'support', 'workspace_docs.py'), path.join(RUN_DIR, 'docs')],
    { cwd: repoRoot(), encoding: 'utf8' });
  return JSON.parse(out) as Record<SampleKey, SampleDoc>;
}

// ── the hub log ─────────────────────────────────────────────────────────────────────

export function hubLog(): string {
  const file = path.join(RUN_DIR, 'hub.log');
  return existsSync(file) ? readFileSync(file, 'utf8') : '';
}

// ── in-page requests ────────────────────────────────────────────────────────────────

/** A GET from inside *page* (its cookies, its origin); returns the status and the parsed body. */
export async function pageGet<T = unknown>(page: Page, url: string): Promise<{ status: number; body: T }> {
  return page.evaluate(async (target) => {
    const response = await fetch(target, { credentials: 'same-origin', headers: { Accept: 'application/json' }, cache: 'no-store' });
    const text = await response.text();
    let body: unknown = null;
    try { body = text ? JSON.parse(text) : null; } catch { body = text; }
    return { status: response.status, body };
  }, url) as Promise<{ status: number; body: T }>;
}

// ── keyboard focus checks axe does not make ───────────────────────────────────────────

/** The outline that marks *target* as focused, as computed (forced colours keep outlines and drop
    box-shadows, so a ring drawn with box-shadow alone disappears there). For the chat composer,
    the ring is on the box around the textarea. */
export async function focusRing(page: Page, selector: string): Promise<{ style: string; width: number }> {
  await page.locator(selector).first().waitFor();
  return page.evaluate((sel) => {
    const el = document.querySelector<HTMLElement>(sel);
    if (!el) throw new Error(`no element for ${sel}`);
    el.focus();
    const ringed = el.closest<HTMLElement>('.ws-composer__box') ?? el;
    const style = getComputedStyle(ringed);
    return { style: style.outlineStyle, width: parseFloat(style.outlineWidth) || 0 };
  }, selector);
}

/** Walks backwards with Shift+Tab from the last control of <main>; returns every focused control
    that sat (even partly) under the sticky top bar (WCAG 2.4.11). */
export async function controlsUnderTopBar(page: Page, steps = 30): Promise<string[]> {
  await page.locator('main [data-page-heading]').first().waitFor();
  await page.waitForLoadState('networkidle').catch(() => undefined);
  await page.evaluate(() => {
    const controls = Array.from(document.querySelectorAll<HTMLElement>('main a[href], main button:not([disabled]), main input:not([disabled]), main select, main textarea'))
      .filter((el) => el.getBoundingClientRect().height > 0);
    const last = controls[controls.length - 1];
    last?.focus();
    last?.scrollIntoView({ block: 'end' });
  });
  const hidden: string[] = [];
  for (let i = 0; i < steps; i += 1) {
    await page.keyboard.press('Shift+Tab');
    const hit = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      const bar = document.querySelector<HTMLElement>('.ws-topbar');
      if (!el || !bar || !el.closest('main')) return null;
      const r = el.getBoundingClientRect();
      const top = bar.getBoundingClientRect().bottom;
      return r.top < top - 1 && r.bottom > 0 ? `${(el.textContent || el.getAttribute('aria-label') || el.tagName).trim().slice(0, 40)} (top ${Math.round(r.top)} < ${Math.round(top)})` : null;
    });
    if (hit) hidden.push(hit);
  }
  return hidden;
}
