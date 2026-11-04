/* Remote skill import uses an admin request and immutable, verified source pins.
   A permitted request stages a quarantined copy; activation needs owner review.
   Imported sidecars and the marketplace registry remain separate stores. */
import React, { useState } from 'react';
import { useApi, arr, mono, asLive, Card, State, Row, Tag, Btn, actA, inpS, Json } from '../panel-kit';

const IMPORTED_PATH = '/skills/imported';
const IMPORT_PATH = '/skills/import';
const HERMES_CATALOG_PATH = '/skills/hermes/catalog';
const OPTIONAL_CATALOG_PATH = '/api/skills/optional/catalog';
const OPTIONAL_INSTALL_PATH = '/api/skills/optional/install';

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
  const [source, setSource] = useState('hermes');  // hermes | openclaw | github
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
  const generic = source !== 'hermes';
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
        if (r?.quarantined !== true || r?.status !== 'installed_review_required') {
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
      <div style={{ fontSize: 10, color: 'var(--ink-2)', marginTop: 10, lineHeight: 1.5, borderTop: '1px solid var(--panel-line)', paddingTop: 6 }}>
        GET {IMPORTED_PATH} is <b>user tier</b> and reads skills/&lt;slug&gt;/manifest.json sidecars ·
        POST {IMPORT_PATH} is <b>admin tier</b> (X-Admin-Token); it crosses skill.install and lands pending review · optional install is <b>admin tier</b> · a real remote import makes
        outbound requests to raw.githubusercontent.com. Marketplace registry rows, review status
        and rollback are a different store and live in the SKILLS MARKETPLACE panels.
      </div>
    </Card>
  );
}
