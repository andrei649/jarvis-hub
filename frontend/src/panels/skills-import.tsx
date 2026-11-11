/* Remote skill import uses an admin request and immutable, verified source pins.
   A permitted request stages a quarantined copy; activation needs owner review.
   Imported sidecars and the marketplace registry remain separate stores.

   The vendored Hermes catalog (Adopt lane slice 3, H336): GET /skills/imported also carries
   `hermes_catalog` (agents/vendor/hermes/SKILLS_CATALOG.json, one row a skill, no file bytes).
   An `installable` row is installed by POST /skills/import with source "hermes-catalog" or,
   from its buttons here, by the owner route POST /api/skills/catalog/install (admin, actA),
   which also repairs; a 409 `local_edits` names the edited files and offers a forced repair
   that keeps a copy of each on the hub. An `upstream_only` row carries code and is shown with
   its code files and no install button, an `excluded` row with its reason. A response without
   the key (an older hub) shows no catalog section at all — never an empty catalog. */
import React, { useState } from 'react';
import { useApi, arr, mono, asLive, Card, State, Row, Tag, Btn, actA, inpS, Json } from '../panel-kit';
import { apiDelete, apiGet, apiPost, apiPut } from '../api/client';

const IMPORTED_PATH = '/skills/imported';
const IMPORT_PATH = '/skills/import';
const HERMES_CATALOG_PATH = '/skills/hermes/catalog';
const OPTIONAL_CATALOG_PATH = '/api/skills/optional/catalog';
const OPTIONAL_INSTALL_PATH = '/api/skills/optional/install';
/* H336 — the owner's catalog install/repair (admin). */
const CATALOG_INSTALL_PATH = '/api/skills/catalog/install';

/* H342 — a skill's declared variables (admin). The value goes in and never comes back. */
const SETUP_PATH = '/api/skills/setup';

/* H025/H335 — skill taps: trusted sources, search across them, install through the pinned import. */
const TAPS_PATH = '/api/skills/taps';
const TAPS_SEARCH_PATH = '/api/skills/taps/search';
const TAPS_INSTALL_PATH = '/api/skills/taps/install';
const TRUST_COLOR: Record<string, string> = { official: 'var(--green)', trusted: 'var(--accent-light)', community: 'var(--amber)' };

/* A local naming hint; the server validates the complete import request. */
const SLUG_RE = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const slugOf = (s: string) => String(s || '').trim().toLowerCase().replace(/ /g, '-');

/* HTTP status off a thrown apiGet message ("GET /skills/imported -> 503"). apiGet throws
   before reading the body, so the status is all there is — and it is enough to tell
   "component down" from "no rows". */
const statusOf = (msg: any): number => {
  const m = /->\s*(\d{3})/.exec(String(msg || ''));
  return m ? Number(m[1]) : 0;
};

/* The refusal, straight off the wire. apiPost attaches the parsed body to err.body
   (client.ts:98-104). `kind` is the load-bearing part: `error` = the route answered,
   `detail` = _admin_guard answered and the route never ran. */
const refusal = (err: any): { status: number; kind: 'route' | 'guard' | 'none'; text: string } => {
  const b: any = err && err.body;
  const isObj = !!b && typeof b === 'object';
  const kind: 'route' | 'guard' | 'none' = isObj
    ? (b.error != null ? 'route' : b.detail != null ? 'guard' : 'none')
    : 'none';
  const raw = isObj ? b.reason ?? b.error ?? b.detail : undefined;
  const text = raw == null
    ? String((err && err.message) || 'request failed')
    : (typeof raw === 'string' ? raw : JSON.stringify(raw));
  return { status: Number(err && err.status) || 0, kind, text };
};

const H = ({ children }) => (
  <div style={{ ...mono, fontSize: 9.5, letterSpacing: '.14em', color: 'var(--ink-2)', margin: '10px 0 5px' }}>{children}</div>
);
const Note = ({ children }) => (
  <div style={{ fontSize: 10, color: 'var(--ink-2)', marginTop: 4, lineHeight: 1.5 }}>{children}</div>
);
const Fail = ({ children }) => (
  <div role="alert" style={{ ...mono, fontSize: 10.5, marginTop: 6, color: 'var(--red)' }}>{children}</div>
);
const Good = ({ children }) => (
  <div style={{ ...mono, fontSize: 10.5, marginTop: 6, color: 'var(--green)' }}>{children}</div>
);
const Amber = ({ children }) => (
  <div role="status" style={{ ...mono, fontSize: 10.5, marginTop: 6, color: 'var(--amber)' }}>{children}</div>
);

/* H342 — which environment variables a skill declares, which are set (stored for this skill,
   or in the hub's environment) and which are missing. A value is typed into a password field,
   sent once with PUT and cleared from the field; the hub never sends any part of it back. */
export function SkillSetup({ initial = '' }: { initial?: string }) {
  const [name, setName] = useState(initial);
  const [view, setView] = useState<any>(null);
  const [err, setErr] = useState('');
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState('');
  const load = (skillName = name) => {
    const target = String(skillName || '').trim();
    if (!target) return;
    setErr('');
    apiGet(`/api/skills/setup/${encodeURIComponent(target)}`, { admin: true })
      .then((v: any) => setView(v))
      .catch((e: any) => { setView(null); setErr(`HTTP ${e?.status || '?'} · ${String(e?.body?.error || e?.message || 'failed')}`); });
  };
  const save = (variable: string) => {
    const value = values[variable] || '';
    if (!value || busy) return;
    setBusy(variable);
    apiPut(`/api/skills/setup/${encodeURIComponent(view.skill)}/${encodeURIComponent(variable)}`, { value }, { admin: true })
      .then((v: any) => { setView(v); setErr(''); })
      .catch((e: any) => setErr(`${variable}: refused · HTTP ${e?.status || '?'} · ${String(e?.body?.error || 'failed')}`))
      .finally(() => { setBusy(''); setValues((cur) => ({ ...cur, [variable]: '' })); });
  };
  const clear = (variable: string) => {
    if (busy) return;
    setBusy(variable);
    apiDelete(`/api/skills/setup/${encodeURIComponent(view.skill)}/${encodeURIComponent(variable)}`, { admin: true })
      .then((v: any) => setView(v))
      .catch((e: any) => setErr(`${variable}: HTTP ${e?.status || '?'}`))
      .finally(() => setBusy(''));
  };
  return (
    <div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <input aria-label="skill to set up" placeholder="installed skill name" value={name}
          onChange={(ev) => setName(ev.target.value)} style={{ ...inpS, flex: 1, minWidth: 120 }} />
        <button className="tool-btn" disabled={!name.trim()} onClick={() => load()}>show setup</button>
      </div>
      {err && <Fail>{err}</Fail>}
      {view && (
        <>
          <Note>{view.skill}: {view.ready ? 'ready' : `missing ${arr(view, 'missing').join(', ')}`}</Note>
          {arr(view, 'requirements').length === 0 && <Note>this skill declares no environment variables</Note>}
          {arr(view, 'requirements').map((r: any) => (
            <Row key={`setup-${r.name}`}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                  <span style={{ ...mono, color: 'var(--accent-light)' }}>{String(r.name)}</span>
                  {r.reserved ? <Tag c="var(--red)">reserved name · cannot be set for a skill</Tag>
                    : r.set ? <Tag c="var(--green)">set · {r.source === 'skill' ? 'for this skill' : 'hub environment'}</Tag>
                    : <Tag c={r.optional ? 'var(--ink-2)' : 'var(--amber)'}>{r.optional ? 'optional' : 'missing'}</Tag>}
                  {r.stale ? <Tag c="var(--amber)">set for an earlier install · set it again</Tag> : null}
                </div>
                <div style={{ fontSize: 10.5, color: 'var(--ink-2)', marginTop: 2 }}>{String(r.prompt || '')}{r.help ? ` · ${String(r.help)}` : ''}</div>
              </div>
              {r.settable && (
                <>
                  <input type="password" autoComplete="off" aria-label={`value for ${r.name}`} placeholder="value"
                    value={values[r.name] || ''} onChange={(ev) => setValues((cur) => ({ ...cur, [r.name]: ev.target.value }))}
                    style={{ ...inpS, width: 140 }} />
                  <button className="tool-btn" disabled={!!busy || !values[r.name]} aria-label={`save ${r.name}`}
                    onClick={() => save(String(r.name))}>save</button>
                  {r.source === 'skill' && (
                    <button className="tool-btn" disabled={!!busy} aria-label={`clear ${r.name}`}
                      onClick={() => clear(String(r.name))}>clear</button>
                  )}
                </>
              )}
            </Row>
          ))}
          <Note>values are stored encrypted on the hub, never shown again (not even in part), and handed only
            to this skill’s own commands, for this install of it — never to the hub’s environment, to another
            skill, or to the code interpreter (it runs code the model writes; it keeps reading only the hub’s
            .env). Removing the skill clears them. A runnable skill refuses while a required one is missing.</Note>
        </>
      )}
    </div>
  );
}

/* H025/H335 — the owner's skill sources. A tap is a trust root: adding one only queues an
   approval card (decision inbox) and nothing is fetched until a person accepts it; the ref is
   an exact commit. Search ranks official > trusted > community. A tap install goes through
   POST /skills/import's own pinned, kernel-gated, quarantined import; a catalog row keeps the
   vendored catalog's install route. The two official pins differ on purpose; the panel says
   which pin each row installs at. */
export function SkillTaps({ onInstalled }: { onInstalled?: (skill: string) => void }) {
  const { d, e, reload } = useApi(TAPS_PATH);
  const rows: any[] = d && !e ? arr(d, 'taps') : [];
  const align: any = d && !e ? (d as any).pin_alignment : null;
  const [repo, setRepo] = useState('');
  const [commit, setCommit] = useState('');
  const [path, setPath] = useState('skills');
  const [trust, setTrust] = useState('community');
  const [q, setQ] = useState('');
  const [results, setResults] = useState<any[] | null>(null);
  const [busy, setBusy] = useState('');
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const addValid = /^[A-Za-z0-9][A-Za-z0-9._-]*\/[A-Za-z0-9][A-Za-z0-9._-]*$/.test(repo.trim())
    && /^[a-f0-9]{40}$/.test(commit.trim()) && !!path.trim();
  const fail = (what: string) => (err: any) => {
    const x = refusal(err);
    setBusy('');
    setNote({ ok: false, text: `${what}: refused · HTTP ${x.status || '?'} · ${x.text}` });
  };
  const add = () => {
    if (!addValid || busy) return;
    setBusy('add'); setNote(null);
    actA(TAPS_PATH, { repo: repo.trim(), commit: commit.trim(), path: path.trim(), trust }, (r: any) => {
      setBusy('');
      setNote({ ok: true, text: `approval card #${String(r.task_id)} queued — accept it in the decision inbox to trust ${repo.trim()}@${commit.trim().slice(0, 8)}` });
      reload();
    }, fail('add tap'));
  };
  const refresh = (id: string) => {
    if (busy) return;
    setBusy(id); setNote(null);
    actA(`/api/skills/taps/${encodeURIComponent(id)}/refresh`, {}, (r: any) => {
      setBusy('');
      setNote({ ok: true, text: `${id}: index read at its commit · ${Number(r?.tap?.skills) || 0} skills · ${Number(r?.tap?.refused) || 0} refused` });
      reload();
    }, fail(`refresh ${id}`));
  };
  const remove = (id: string) => {
    if (busy) return;
    setBusy(id); setNote(null);
    apiDelete(`/api/skills/taps/${encodeURIComponent(id)}`, { admin: true })
      .then(() => { setBusy(''); setNote({ ok: true, text: `${id} removed` }); reload(); })
      .catch(fail(`remove ${id}`));
  };
  const search = () => {
    apiGet(`${TAPS_SEARCH_PATH}?q=${encodeURIComponent(q.trim())}&limit=40`)
      .then((r: any) => setResults(arr(r, 'results')))
      .catch((err: any) => { setResults(null); setNote({ ok: false, text: `search: HTTP ${err?.status || '?'}` }); });
  };
  const install = (row: any) => {
    if (busy || !row.installable) return;
    const key = `${row.tap}/${row.slug}`;
    setBusy(key); setNote(null);
    const done = (r: any) => {
      setBusy('');
      const missing = arr(r?.setup, 'missing').map(String);
      setNote({ ok: true, text: `${String(row.slug)} from ${String(row.tap)}: ${String(r?.status || (r?.ok ? 'installed' : '—'))}`
        + (r?.quarantined ? ' · quarantined, pending your review' : '')
        + (missing.length ? ` · needs ${missing.join(', ')} (Skill setup below)` : '') });
      if (onInstalled) onInstalled(String(row.slug));
    };
    if (row.install === 'catalog') {
      apiPost(CATALOG_INSTALL_PATH, { skill: String(row.slug), repair: false, force: false }, { admin: true })
        .then(done).catch(fail(`install ${row.slug}`));
    } else {
      apiPost(TAPS_INSTALL_PATH, { tap: String(row.tap), skill: String(row.slug) }, { admin: true })
        .then(done).catch(fail(`install ${row.slug}`));
    }
  };
  return (
    <div>
      {e ? <Amber>taps unavailable · HTTP {statusOf(e) || '?'}</Amber> : rows.map((t: any) => (
        <Row key={`tap-${t.id}`}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ ...mono, color: 'var(--accent-light)' }}>{String(t.id)}</span>
              <Tag c={TRUST_COLOR[t.trust] || 'var(--ink-2)'}>{String(t.trust)}</Tag>
              <Tag c={t.status === 'active' ? 'var(--green)' : 'var(--amber)'}>{t.status === 'pending' ? 'awaiting approval' : String(t.status)}</Tag>
              {t.release_tag ? <Tag>{String(t.release_tag)}</Tag> : null}
              {t.commit ? <Tag><span title={String(t.commit)}>@{String(t.commit).slice(0, 8)}</span></Tag> : null}
              {t.skills != null ? <Tag>{Number(t.skills) || 0} skills</Tag> : null}
              {t.refused ? <Tag c="var(--red)">{Number(t.refused)} refused</Tag> : null}
            </div>
            <div style={{ fontSize: 10.5, color: 'var(--ink-2)', marginTop: 2 }}>
              {String(t.repo || '')}{t.path ? `/${String(t.path)}` : ''}{t.note ? ` · ${String(t.note)}` : ''}
            </div>
          </div>
          {!t.builtin && t.status === 'active' && (
            <button className="tool-btn" disabled={!!busy} aria-label={`refresh ${t.id}`} onClick={() => refresh(String(t.id))}>
              {busy === t.id ? 'reading…' : 'refresh'}
            </button>
          )}
          {!t.builtin && (
            <button className="tool-btn" disabled={!!busy} aria-label={`remove ${t.id}`} onClick={() => remove(String(t.id))}>remove</button>
          )}
        </Row>
      ))}
      {align && align.available && (
        <Note>
          official pins: the import pin is {String(align.import_pin?.release_tag)} @{String(align.import_pin?.commit || '').slice(0, 8)};
          the vendored catalog is @{String(align.catalog_pin?.commit || '').slice(0, 8)}. Of the import pin’s {Number(align.import_pin?.skills) || 0} skills,
          {' '}{Number(align.same_bytes) || 0} have the same SKILL.md bytes in the catalog, {Number(align.changed) || 0} changed
          and {Number(align.not_in_catalog) || 0} are not in it. {String(align.why || '')}
        </Note>
      )}
      <div style={{ display: 'grid', gap: 6, marginTop: 8 }}>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <input aria-label="tap repository" placeholder="owner/repo" value={repo} onChange={(ev) => setRepo(ev.target.value)} style={{ ...inpS, width: 150 }} />
          <input aria-label="tap commit" placeholder="40-character commit SHA" value={commit} onChange={(ev) => setCommit(ev.target.value)} style={{ ...inpS, flex: 1, minWidth: 160 }} />
          <input aria-label="tap path" placeholder="skills" value={path} onChange={(ev) => setPath(ev.target.value)} style={{ ...inpS, width: 90 }} />
          <select aria-label="tap trust" value={trust} onChange={(ev) => setTrust(ev.target.value)} style={inpS}>
            <option value="community">community</option>
            <option value="trusted">trusted</option>
          </select>
          <button className="tool-btn" disabled={!addValid || !!busy} onClick={add}>{busy === 'add' ? 'asking…' : 'ask to add tap'}</button>
        </div>
        <Note>a tap is a trust root: this queues an approval card and does nothing else. Only an exact commit is
          accepted (a branch or tag can move). After you accept the card, refresh reads the tap’s index at that
          commit, through the kernel’s egress gate; entries that fail validation are listed as refused.</Note>
      </div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginTop: 8 }}>
        <input aria-label="search all skill sources" placeholder="search every source" value={q}
          onChange={(ev) => setQ(ev.target.value)} style={{ ...inpS, flex: 1, minWidth: 120 }} />
        <button className="tool-btn" onClick={search}>search</button>
      </div>
      {results && results.length === 0 && <Note>no source lists a match</Note>}
      {results && results.map((r: any) => (
        <Row key={`res-${r.tap}-${r.slug}`}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ ...mono, color: 'var(--accent-light)' }}>{String(r.slug)}</span>
              <Tag c={TRUST_COLOR[r.trust] || 'var(--ink-2)'}>{String(r.trust)}</Tag>
              <Tag>{String(r.tap)} @{String(r.commit || '').slice(0, 8)}</Tag>
              {arr(r, 'required_env').map((k: any) => <Tag key={`renv-${k}`} c="var(--amber)">needs {String(k)}</Tag>)}
              {arr(r, 'injection_flags').length ? <Tag c="var(--red)">injection-like text</Tag> : null}
              {r.carries_code ? <Tag c="var(--amber)">has code (not copied)</Tag> : null}
            </div>
            {r.description ? <div style={{ fontSize: 10.5, color: 'var(--ink-2)', marginTop: 2 }}>{String(r.description)}</div> : null}
            {!r.installable && r.reason ? <Note>not installable: {String(r.reason)}</Note> : null}
          </div>
          {r.installable && (
            <button className="tool-btn" disabled={!!busy} aria-label={`install ${r.slug} from ${r.tap}`} onClick={() => install(r)}>
              {busy === `${r.tap}/${r.slug}` ? 'installing…' : 'install'}
            </button>
          )}
        </Row>
      ))}
      {note && (note.ok ? <Good>{note.text}</Good> : <Fail>{note.text}</Fail>)}
    </div>
  );
}

export function SkillsImportPanel() {
  /* Imported-manifest reads use the existing user token. */
  const { d, e, loading, reload } = useApi(IMPORTED_PATH);
  const loaded = !!d && !e;
  const rows: any[] = loaded ? arr(d, 'imported') : [];
  const readStatus = e ? statusOf(e) : 0;
  const [open, setOpen] = useState(-1);
  const { d: hermesData, e: hermesError } = useApi(HERMES_CATALOG_PATH);
  const hermesRows: any[] = hermesData && !hermesError ? arr(hermesData, 'skills') : [];
  const [catalogQuery, setCatalogQuery] = useState('');
  const visibleHermes = hermesRows.filter((row: any) =>
    String(row.slug || '').includes(catalogQuery.trim().toLowerCase())).slice(0, 24);
  const { d: optionalData, e: optionalError, reload: reloadOptional } =
    useApi(OPTIONAL_CATALOG_PATH, true, true);
  const optionalRows: any[] = optionalData && !optionalError ? arr(optionalData, 'skills') : [];
  const [optionalBusy, setOptionalBusy] = useState('');
  const [optionalResult, setOptionalResult] = useState<{ ok: boolean; text: string } | null>(null);

  const installOptional = (name: string) => {
    if (optionalBusy) return;
    setOptionalBusy(name); setOptionalResult(null);
    actA(OPTIONAL_INSTALL_PATH, { name }, (answer: any) => {
      setOptionalBusy('');
      setOptionalResult({ ok: true, text: `${name}: ${String(answer.status)} · kernel ${String(answer.kernel)} · pending owner review before use` });
      reloadOptional();
      reload();
    }, (err: any) => {
      const body = err && err.body;
      setOptionalBusy('');
      setOptionalResult({ ok: false, text: `${name}: refused · HTTP ${err?.status || '?'} · ${String(body?.reason || body?.detail || err?.message || 'request failed')}` });
    });
  };

  const [skill, setSkill] = useState('');
  const [source, setSource] = useState('hermes');  // hermes | hermes-catalog | openclaw | github
  const [repo, setRepo] = useState('');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);          // {ok:boolean, text:string}

  const [commit, setCommit] = useState('');
  const [entryPath, setEntryPath] = useState('');
  const [digest, setDigest] = useState('');
  const [referenceText, setReferenceText] = useState('');
  const referenceLines = referenceText.split('\n').map((line) => line.trim()).filter(Boolean);
  const references = referenceLines.map((line) => {
    const [path, content_sha256, ...extra] = line.split(/\s+/);
    return { path, content_sha256, extra };
  });
  const pathOK = (path: string) => path.length <= 512 && /^[A-Za-z0-9][A-Za-z0-9._/-]*$/.test(path)
    && path.split('/').every((part) => part !== '.' && part !== '..' && !!part);
  /* The pinned Hermes allowlist and the vendored catalog carry their own pins server-side. */
  const generic = source !== 'hermes' && source !== 'hermes-catalog';
  const sourceValue = source === 'github' ? repo.trim() : source;
  const pinnedRepo = source === 'openclaw' ? 'openclaw/skills' : repo.trim();
  const pinValid = /^[A-Za-z0-9][A-Za-z0-9._-]*\/[A-Za-z0-9][A-Za-z0-9._-]*$/.test(pinnedRepo)
    && /^[a-f0-9]{40}$/.test(commit.trim()) && /^[a-f0-9]{64}$/.test(digest.trim())
    && pathOK(entryPath.trim()) && /\/(SKILL\.md|manifest\.json|manifest\.ya?ml)$/.test(entryPath.trim())
    && references.length <= 64 && new Set(references.map((r) => r.path)).size === references.length
    && references.every((r) => r.extra.length === 0 && pathOK(r.path)
      && r.path.startsWith(`${entryPath.trim().slice(0, entryPath.trim().lastIndexOf('/'))}/references/`)
      && /^[a-f0-9]{64}$/.test(r.content_sha256 || ''));
  const canSubmit = !busy && !!String(skill).trim() && (!generic || pinValid);

  const submit = () => {
    if (!canSubmit) return;
    setBusy(true); setNote(null);
    const pin = generic ? { repo: pinnedRepo, commit: commit.trim(), entry_path: entryPath.trim(),
      content_sha256: digest.trim(), references: references.map(({ path, content_sha256 }) => ({ path, content_sha256 })) } : undefined;
    actA(IMPORT_PATH, { skill, source: sourceValue, ...(pin ? { pin } : {}) },
      (r: any) => {
        setBusy(false);
        if (source === 'hermes-catalog' && r?.ok === true) {
          /* The vendored catalog lane installs instruction-only bytes checked against their manifest. */
          setNote({ ok: true, text: `imported · skill=${r.skill ?? '—'} · source=${r.source ?? '—'}` });
        } else if (r?.quarantined !== true || r?.status !== 'installed_review_required') {
          setNote({ ok: false, text: 'unexpected import response — reload the inventory before retrying' });
        } else {
          setNote({ ok: true, text: `staged · skill=${r.skill ?? '—'} · source=${r.source ?? '—'} · kernel ${r.kernel ?? 'unknown'} · pending owner review` });
        }
        reload();
      },
      (err) => {
        const x = refusal(err);
        setBusy(false);
        setNote({ ok: false, text: `refused · HTTP ${x.status || '?'} · ${x.text}` });
      });
  };

  /* The vendored Hermes catalog, only when the backend reported one (slice 3). */
  const catalog: any = loaded && d && typeof d === 'object' && (d as any).hermes_catalog
    && typeof (d as any).hermes_catalog === 'object' ? (d as any).hermes_catalog : null;
  const [catKind, setCatKind] = useState('instruction');
  const [catQ, setCatQ] = useState('');
  const catRows: any[] = catalog ? arr(catalog, 'skills') : [];
  const catShown = catRows.filter((r) => r && r.kind === catKind && (!catQ
    || [r.slug, r.category, r.description].some((v) => String(v || '').toLowerCase().includes(catQ.toLowerCase()))));
  const CAT_LIMIT = 40;
  /* H336 — the owner route; its own answer says what happened. */
  const [catBusy, setCatBusy] = useState('');
  const [catNote, setCatNote] = useState(null);   // {ok, text, edited?: {slug, files}}
  const catalogInstall = (slug: string, repair: boolean, force = false) => {
    if (catBusy) return;
    setCatBusy(slug); setCatNote(null);
    actA(CATALOG_INSTALL_PATH, { skill: slug, repair, force },
      (r: any) => {
        setCatBusy('');
        const status = r && r.status ? String(r.status) : '—';
        const restored = arr(r, 'restored').map(String);
        const replaced = arr(r, 'replaced').map(String);
        const parts = [`${r && r.action === 'install' ? 'installed' : 'repair'} · ${r && r.skill != null ? r.skill : slug} · ${status}`];
        if (restored.length) parts.push(`restored ${restored.join(', ')}`);
        if (replaced.length) parts.push(`replaced ${replaced.join(', ')} (a copy was kept)`);
        if (r && r.audited === false && r.changed) parts.push('not recorded in the intent log');
        setCatNote({ ok: true, text: parts.join(' · ') });
        reload();
      },
      (err) => {
        const x = refusal(err);
        setCatBusy('');
        const b: any = err && err.body;
        const edited = b && b.reason === 'local_edits' ? { slug, files: arr(b, 'files').map(String) } : null;
        setCatNote({ ok: false, text: `refused · HTTP ${x.status || '?'} · ${x.text}`, edited });
      });
  };

  const badSlug = !!String(skill).trim() && !SLUG_RE.test(slugOf(skill));
  const badRepo = source === 'github' && !!String(repo).trim() && String(repo).indexOf('/') < 0;

  return (
    <Card
      title="SKILLS IMPORT"
      live={asLive(loaded ? d : null)}
      sub={loaded ? `${rows.length} imported` : null}
      onReload={reload}
    >
      {/* ── 1 · IMPORTED SIDECARS ─────────────────────────────────────── */}
      <H>IMPORTED ON DISK · GET {IMPORTED_PATH}</H>
      {loading ? <State e={null} loading={true} n={null} />
        : e ? (readStatus === 503
          ? <Amber>
              unavailable · HTTP 503 — this route answers 503 only when the orchestrator is not
              initialized. That is NOT “zero imported”, so no list and no count is shown.
            </Amber>
          : <State e={e} loading={false} n={null} />)
        : rows.length === 0
          ? <div style={{ color: 'var(--ink-2)', fontSize: 12 }}>
              no imported skills on disk yet — skills/&lt;slug&gt;/manifest.json is written only by an import
            </div>
          : rows.map((row, i) => {
            const r: any = row || {};
            const commit = typeof r.source_commit === 'string' ? r.source_commit : '';
            const digest = typeof r.content_sha256 === 'string' ? r.content_sha256 : '';
            return (
              <Row key={`${r.name || r.source_path || 'row'}-${i}`}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <span style={{ ...mono, color: 'var(--accent-light)' }}>
                      {r.name || r.slug || '(unnamed manifest)'}
                    </span>
                    {r.version != null && <Tag>v{String(r.version)}</Tag>}
                    {r.source != null && <Tag>{String(r.source)}</Tag>}
                    {r.source_release_tag != null && <Tag>pin {String(r.source_release_tag)}</Tag>}
                    {r.source_tier != null && <Tag>tier {String(r.source_tier)}</Tag>}
                    {commit && <Tag><span title={commit}>{commit.slice(0, 8)}</span></Tag>}
                    {digest && <Tag><span title={digest}>sha256 {digest.slice(0, 12)}…</span></Tag>}
                  </div>
                  {r.description ? (
                    <div style={{ fontSize: 10.5, color: 'var(--ink-2)', marginTop: 2 }}>{String(r.description)}</div>
                  ) : null}
                  {open === i && <Json v={r} />}
                </div>
                <Btn onClick={() => setOpen(open === i ? -1 : i)}>{open === i ? 'hide raw' : 'raw'}</Btn>
              </Row>
            );
          })}
      <Note>
        rows are the <b>raw manifest.json sidecars</b> on disk, not a typed model — keys vary, and a legacy
        manifest may carry none of the fields above, which is what <b>raw</b> is for. A sidecar that fails to
        parse is silently skipped server-side, so this list is <b>not</b> a complete inventory of skills/.
      </Note>

      <H>IMPORT FOR OWNER REVIEW</H>
      <Note>Import requires admin access and current installation and network authorization. Each remote
        file is fetched at an immutable commit and checked against its SHA256 digest. A permitted import
        stays quarantined until the owner approves it for use.</Note>

      {/* ── 3 · IMPORT ────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginTop: 8 }}>
        <select
          aria-label="import source"
          value={source}
          onChange={(ev) => { setSource(ev.target.value); setNote(null); }}
          style={inpS}
        >
          <option value="hermes">hermes (pinned)</option>
          <option value="hermes-catalog">hermes catalog (vendored)</option>
          <option value="openclaw">openclaw</option>
          <option value="github">GitHub owner/repo</option>
        </select>
        {source === 'github' && (
          <input
            style={{ ...inpS, width: 160 }}
            aria-label="github owner/repo"
            placeholder="owner/repo"
            value={repo}
            onChange={(ev) => setRepo(ev.target.value)}
          />
        )}
        <input
          style={{ ...inpS, flex: 1, minWidth: 120 }}
          aria-label="skill name"
          placeholder="skill name"
          value={skill}
          onChange={(ev) => setSkill(ev.target.value)}
        />
        <button className="tool-btn" disabled={!canSubmit} onClick={submit}>
          {busy ? 'importing…' : 'import'}
        </button>
      </div>
      {generic && (
        <div style={{ display: 'grid', gap: 6, marginTop: 8 }}>
          <input aria-label="source commit" placeholder="40-character commit SHA" value={commit}
            onChange={(ev) => setCommit(ev.target.value)} style={inpS} />
          <input aria-label="source entry path" placeholder="skills/skill-name/SKILL.md" value={entryPath}
            onChange={(ev) => setEntryPath(ev.target.value)} style={inpS} />
          <input aria-label="source sha256" placeholder="64-character entry SHA256" value={digest}
            onChange={(ev) => setDigest(ev.target.value)} style={inpS} />
          <textarea aria-label="reference pins" placeholder="Optional references: one repository path and SHA256 per line"
            value={referenceText} onChange={(ev) => setReferenceText(ev.target.value)} style={inpS} />
          <Note>Supply a reviewed immutable commit, entry path and SHA256. If the skill needs reference
            files, list each full repository path under its references/ directory with its SHA256.
            Branches and release tags cannot serve as commit pins.</Note>
        </div>
      )}
      {badSlug && (
        <Note>
          local hint: “{slugOf(skill)}” is not a valid skill slug (lower-cased, spaces→“-”, matched against
          [a-z0-9][a-z0-9._-]&#123;0,63&#125;). The server validates the name before importing.
        </Note>
      )}
      {badRepo && (
        <Note>
          local hint: owner/repo required for an immutable source pin.
        </Note>
      )}
      {source === 'hermes' && (
        <Note>
          hermes imports are restricted to a pinned, sha256-verified allowlist (NousResearch/hermes-agent @
          v2026.8.31; bundled and optional tiers, with reference-file digests). Choose a slug below. The import requires current admin and kernel authorization and remains pending
          owner review before use.
        </Note>
      )}

      {source === 'hermes-catalog' && (
        <Note>
          the vendored Hermes catalog installs offline from the bytes shipped with this hub, checked against
          their manifest, through the same import gates (name check, provenance), with the same admin token. Only instruction skills
          install; a skill that carries code is refused. The list is below — its buttons are the owner’s
          install and repair.
        </Note>
      )}

      <H>PINNED HERMES CATALOG · GET {HERMES_CATALOG_PATH}</H>
      {hermesError ? <Amber>pinned catalog unavailable · HTTP {statusOf(hermesError) || '?'}</Amber>
        : <>
            <Note>{hermesRows.length} pinned skills · {String((hermesData as any)?.release_tag || 'release unknown')} · listing the local pin does not fetch upstream bytes</Note>
            <input aria-label="filter pinned skills" placeholder="filter pinned skills" value={catalogQuery}
              onChange={(ev) => setCatalogQuery(ev.target.value)} style={{ ...inpS, width: '100%', marginTop: 6 }} />
            {visibleHermes.map((row: any) => (
              <Row key={String(row.slug)}>
                <span style={{ flex: 1 }}>{String(row.slug)}</span>
                <Tag>{String(row.tier)}</Tag>
                <Tag>{Number(row.reference_count) || 0} references</Tag>
                <button className="tool-btn" aria-label={`choose ${String(row.slug)}`}
                  onClick={() => { setSource('hermes'); setSkill(String(row.slug)); setNote(null); }}>choose</button>
              </Row>
            ))}
            {hermesRows.length > visibleHermes.length && <Note>Showing up to 24 matches; filter by name to find another skill.</Note>}
          </>}

      <H>SHIPPED OPTIONAL SKILLS · GET {OPTIONAL_CATALOG_PATH}</H>
      <Note>These Nerva skills stay outside the default prompt index. An admin install copies the selected
        product skill to your writable skills root under pending review. A kernel grant or queue permits only
        that quarantined copy; owner approval is still required before executable use.</Note>
      {optionalError ? <Amber>optional catalog unavailable · HTTP {statusOf(optionalError) || '?'}</Amber>
        : optionalRows.map((row: any) => (
          <Row key={String(row.name)}>
            <span style={{ flex: 1 }}>{String(row.name)} <Tag>optional</Tag>{row.installed && <Tag>installed</Tag>}</span>
            <button className="tool-btn" disabled={!!optionalBusy || !row.available || !!row.installed}
              onClick={() => installOptional(String(row.name))}>
              {optionalBusy === row.name ? 'installing…' : row.installed ? 'installed' : 'install for review'}
            </button>
          </Row>
        ))}
      {optionalResult && (optionalResult.ok
        ? <Good>{optionalResult.text}</Good> : <Fail>{optionalResult.text}</Fail>)}
      {note && ((note as any).ok
        ? <Good>{(note as any).text}</Good>
        : <Fail>{(note as any).text}</Fail>)}
      {note && (note as any).ok && (
        <Note>
          those are the values the backend <b>echoed back</b> — the raw input, not the directory it wrote
          (the importer lower-cases and maps spaces to “-”). The list above was re-read; the row it produced is
          the only evidence of the on-disk name.
        </Note>
      )}
      {/* ── 4 · THE VENDORED HERMES CATALOG (slice 3) ─────────────────── */}
      {catalog && (
        <>
          <H>HERMES CATALOG · vendored{catalog.commit ? ` @${String(catalog.commit).slice(0, 8)}` : ''}</H>
          {catalog.available === false
            ? <Fail>catalog unavailable · {String(catalog.error || 'not reported')}</Fail>
            : (
              <>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                  <select aria-label="catalog kind" value={catKind} onChange={(ev) => setCatKind(ev.target.value)} style={inpS}>
                    <option value="instruction">installable ({Number((catalog.counts || {}).instruction) || 0})</option>
                    <option value="upstream_only">carries code ({Number((catalog.counts || {}).upstream_only) || 0})</option>
                    <option value="excluded">excluded ({Number((catalog.counts || {}).excluded) || 0})</option>
                  </select>
                  <input style={{ ...inpS, flex: 1, minWidth: 120 }} aria-label="filter catalog" placeholder="filter"
                    value={catQ} onChange={(ev) => setCatQ(ev.target.value)} />
                </div>
                {catShown.slice(0, CAT_LIMIT).map((r: any) => (
                  <Row key={`cat-${r.path || r.slug}`}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                        <span style={{ ...mono, color: 'var(--accent-light)' }}>{String(r.slug || '—')}</span>
                        {r.category ? <Tag>{String(r.category)}</Tag> : null}
                        {r.installed_commit ? <Tag c="var(--green)">installed @{String(r.installed_commit).slice(0, 8)}</Tag> : null}
                        {arr(r, 'required_env').map((k) => <Tag key={`env-${k}`} c="var(--amber)">needs {String(k)}</Tag>)}
                        {arr(r, 'injection_flags').length ? <Tag c="var(--red)">injection-like text</Tag> : null}
                      </div>
                      {r.description ? <div style={{ fontSize: 10.5, color: 'var(--ink-2)', marginTop: 2 }}>{String(r.description)}</div> : null}
                      {r.kind === 'upstream_only' && arr(r, 'code_files').length
                        ? <Note>code it carries: {arr(r, 'code_files').map(String).join(', ')}</Note> : null}
                      {r.kind === 'excluded' && r.reason ? <Note>excluded: {String(r.reason)}</Note> : null}
                      {arr(r, 'unmapped_keys').length
                        ? <Note>kept in its SKILL.md, not read by Nerva: {arr(r, 'unmapped_keys').map(String).join(', ')}</Note> : null}
                    </div>
                    {r.installable === true && !r.installed_commit && (
                      <button className="tool-btn" disabled={!!catBusy}
                        aria-label={`install ${r.slug}`}
                        onClick={() => catalogInstall(String(r.slug), false)}>
                        {catBusy === String(r.slug) ? 'installing…' : 'install'}
                      </button>
                    )}
                    {r.installable === true && r.installed_commit && (
                      <button className="tool-btn" disabled={!!catBusy}
                        aria-label={`repair ${r.slug}`}
                        onClick={() => catalogInstall(String(r.slug), true)}>
                        {catBusy === String(r.slug) ? 'repairing…' : 'repair'}
                      </button>
                    )}
                  </Row>
                ))}
                {catShown.length > CAT_LIMIT && <Note>{catShown.length - CAT_LIMIT} more — narrow the filter</Note>}
                {catShown.length === 0 && <Note>no catalog row matches</Note>}
                {catNote && ((catNote as any).ok
                  ? <Good>{(catNote as any).text}</Good>
                  : <Fail>{(catNote as any).text}</Fail>)}
                {catNote && (catNote as any).edited && (
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginTop: 4 }}>
                    <Note>you edited {(catNote as any).edited.files.join(', ')}. A forced repair replaces them with the
                      catalog’s bytes and keeps a copy of each on the hub.</Note>
                    <button className="tool-btn" disabled={!!catBusy}
                      aria-label={`force repair ${(catNote as any).edited.slug}`}
                      onClick={() => catalogInstall((catNote as any).edited.slug, true, true)}>
                      replace my edits
                    </button>
                  </div>
                )}
                <Note>
                  installed skills are imports like any other: their text is read as data until you vouch for it, and a
                  key they declare is offered to the code tool only after that. Install and repair are <b>owner</b>
                  actions (admin token, POST {CATALOG_INSTALL_PATH}): the catalog is pinned,
                  checked byte for byte against its manifest and carries instructions only. Repair restores deleted
                  files and refuses over your edits unless you choose to replace them.
                </Note>
              </>
            )}
        </>
      )}

      {/* ── 4b · SKILL TAPS (H025/H335) ──────────────────────────────── */}
      <H>SKILL SOURCES (TAPS) · GET {TAPS_PATH}</H>
      <SkillTaps onInstalled={() => reload()} />

      {/* ── 5 · SKILL SETUP (H342) ────────────────────────────────────── */}
      <H>SKILL SETUP · GET {SETUP_PATH}/&lt;skill&gt;</H>
      <SkillSetup />

      <div style={{ fontSize: 10, color: 'var(--ink-2)', marginTop: 10, lineHeight: 1.5, borderTop: '1px solid var(--panel-line)', paddingTop: 6 }}>
        GET {IMPORTED_PATH} is <b>user tier</b> and reads skills/&lt;slug&gt;/manifest.json sidecars ·
        POST {IMPORT_PATH} is <b>admin tier</b> (X-Admin-Token); it crosses skill.install and lands pending review · optional install and the vendored catalog’s install/repair are <b>admin tier</b> · a real remote import makes
        outbound requests to raw.githubusercontent.com. Marketplace registry rows, review status
        and rollback are a different store and live in the SKILLS MARKETPLACE panels.
      </div>
    </Card>
  );
}
