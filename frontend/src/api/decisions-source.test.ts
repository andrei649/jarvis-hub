// @ts-nocheck — reads the source tree with node:fs (src/ builds against the DOM lib only)
/* Only api/decisions.ts posts to /autonomy/tasks/* (PHASE_B_PLAN.md §2.2, §9.4 E4).

   Every .ts/.tsx module under src/ (tests aside) is read, its comments are skipped, and every
   string and template literal is collected: none may name a /autonomy/tasks/ path, except in
   api/decisions.ts, the decision client, and api/schema.gen.ts, the generated OpenAPI types
   (route keys, never called). The feed itself (/autonomy/tasks?status=…) is a read and has no
   slash after "tasks", so the docket's and the inbox's GETs are not caught. The lexer is small
   on purpose: it knows comments, quotes, templates (with nested ${…}) and enough of regular
   expressions and JSX text for this tree; its own test below shows what it catches. */
import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';

const SRC = join(process.cwd(), 'src');
const ALLOWED = new Set(['api/decisions.ts', 'api/schema.gen.ts']);
const PATH = '/autonomy/tasks/';

/** Characters after which a '/' starts a regular expression rather than a division. */
const REGEX_AFTER = new Set(['', '(', ',', '=', ':', '[', '!', '&', '|', '?', '{', '}', ';', '+', '-', '*', '%', '~', '^']);
const KEYWORD_BEFORE = /(?:^|[^\w$])(?:return|typeof|case|do|else|in|of|new|delete|void|throw|yield|await)$/;

/** Every string and template literal of a module (a template's text between its ${…}). */
export function literalsOf(src) {
  const found = [];
  const modes = [{ kind: 'code', depth: 0, inTemplate: false }];
  let prev = '';
  let prev2 = '';
  let text = '';
  let i = 0;
  const n = src.length;
  const mark = (c) => { if (!/\s/.test(c)) { prev2 = prev; prev = /[\w$]/.test(c) ? 'a' : c; } };
  while (i < n) {
    const mode = modes[modes.length - 1];
    const c = src[i];
    if (mode.kind === 'template') {
      if (c === '\\') { text += src.slice(i, i + 2); i += 2; continue; }
      if (c === '`') { found.push(text); text = ''; modes.pop(); prev = 'a'; i += 1; continue; }
      if (c === '$' && src[i + 1] === '{') {
        found.push(text); text = '';
        modes.push({ kind: 'code', depth: 0, inTemplate: true });
        prev = '('; i += 2; continue;
      }
      text += c; i += 1; continue;
    }
    if (c === '/' && src[i + 1] === '/') { const end = src.indexOf('\n', i); i = end < 0 ? n : end; continue; }
    if (c === '/' && src[i + 1] === '*') { const end = src.indexOf('*/', i + 2); i = end < 0 ? n : end + 2; continue; }
    if (c === "'" || c === '"') {
      let j = i + 1;
      let s = '';
      while (j < n && src[j] !== c && src[j] !== '\n') {
        if (src[j] === '\\') { s += src.slice(j, j + 2); j += 2; } else { s += src[j]; j += 1; }
      }
      found.push(s); i = j + 1; prev = 'a'; continue;
    }
    if (c === '`') { modes.push({ kind: 'template' }); text = ''; i += 1; continue; }
    const arrow = prev === '>' && prev2 === '=';
    if (c === '/' && src[i + 1] !== '>' && (REGEX_AFTER.has(prev) || arrow || KEYWORD_BEFORE.test(src.slice(Math.max(0, i - 12), i).trimEnd()))) {
      let j = i + 1;
      let inClass = false;
      let closed = false;
      while (j < n && src[j] !== '\n') {
        const ch = src[j];
        if (ch === '\\') { j += 2; continue; }
        if (ch === '[') inClass = true;
        else if (ch === ']') inClass = false;
        else if (ch === '/' && !inClass) { closed = true; break; }
        j += 1;
      }
      if (closed) { i = j + 1; while (/[a-z]/i.test(src[i] || '')) i += 1; prev = 'a'; continue; }
    }
    if (c === '{') mode.depth += 1;
    if (c === '}') {
      if (mode.inTemplate && mode.depth === 0) { modes.pop(); i += 1; continue; }
      mode.depth -= 1;
    }
    mark(c);
    i += 1;
  }
  return found;
}

function sources(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) { out.push(...sources(full)); continue; }
    if (!/\.(ts|tsx)$/.test(name) || /\.test\.(ts|tsx)$/.test(name) || name.endsWith('.d.ts')) continue;
    out.push(full);
  }
  return out;
}

describe('the lexer', () => {
  it('finds the path in a string, a concatenation and a template, and not in a comment, JSX text or a regex', () => {
    const code = [
      "actA('/autonomy/tasks/' + id + '/decision', {});",
      'apiPost(`/autonomy/tasks/${id}/consent`, body);',
      'const nested = `a ${`/autonomy/tasks/${x}`} b`;',
      '// POST \'/autonomy/tasks/{id}/decision\' in a comment',
      '/* `POST /autonomy/tasks/{id}/decision` */',
      "const re = /'\\/autonomy\\/tasks\\//; const url = 'https://example.com/x';",
      "return <p>POST /autonomy/tasks/{'{id}'}/decision, which is INBOX's control, not this panel's.</p>;",
    ].join('\n');
    const hits = literalsOf(code).filter((s) => s.includes(PATH));
    expect(hits).toEqual(['/autonomy/tasks/', '/autonomy/tasks/', '/autonomy/tasks/']);
    expect(literalsOf(code)).toContain('https://example.com/x');
  });
});

describe('the decision client is the only module that posts to /autonomy/tasks/', () => {
  const files = sources(SRC);

  it('reads the tree', () => {
    expect(files.length).toBeGreaterThan(100);
    expect(files.map((f) => relative(SRC, f).split(sep).join('/'))).toContain('api/decisions.ts');
  });

  it('no other module names a /autonomy/tasks/ path', () => {
    const offenders = [];
    for (const file of files) {
      const rel = relative(SRC, file).split(sep).join('/');
      if (ALLOWED.has(rel)) continue;
      for (const literal of literalsOf(readFileSync(file, 'utf8'))) {
        if (literal.includes(PATH)) offenders.push(`${rel}: ${literal}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it('and the decision client does', () => {
    const own = literalsOf(readFileSync(join(SRC, 'api', 'decisions.ts'), 'utf8')).filter((s) => s.includes(PATH));
    expect(own.length).toBeGreaterThanOrEqual(4);
  });
});
