/* SKILLS IMPORT — the on-disk skill-import surface that shipped with no caller:
   GET /skills/imported (agents/core/routers/skills.py:157) and
   POST /skills/import (skills.py:133).

   BOUNDARY. This is NOT the SKILLS MARKETPLACE panel (gap.tsx:1626) or MARKETPLACE ADMIN
   in another coat. Those read /api/skills/marketplace{,/history,/pending} — a sqlite
   registry (marketplace.py:393-418) keyed name/version/review_status/signature.
   /skills/imported is a different store entirely: the `manifest.json` sidecars the
   IMPORTER writes under skills/<slug>/ (importer.py:445-461). Its provenance keys —
   source_repository, source_release_tag, source_commit, source_tree, source_path,
   content_sha256 — exist nowhere else in the HUD.

   What the two handlers actually do, and what this panel is therefore forbidden to imply:

   1. GET /skills/imported carries NO Depends() guard at all (contrast POST /skills/import,
      which carries Depends(user_guard)). So it is read with useApi(path) — not admin,
      not user-flagged. Its ONLY refusal is 503 {"error":"not initialized"} (skills.py:160).
      apiGet throws BEFORE reading the body (client.ts:106-110), so the backend's literal
      "not initialized" never reaches this panel — only the message "GET /skills/imported
      -> 503". The status is therefore read off that message and the panel says
      "unavailable · HTTP 503", never quoting a body it did not fetch.

   2. 200 {"imported": []} is the NORMAL state on a stock install: skills/ here holds 12
      skill directories and ZERO manifest.json files, because a sidecar is written only by
      an import. The empty state and the 503 are rendered as visibly different things —
      a 503 drawn as "0 imported" would be a lie about a component that is down.

   3. list_imported() SWALLOWS json.JSONDecodeError / IOError per file (importer.py:611-612),
      so a corrupt sidecar is invisible in the payload. This panel therefore never claims
      the list is a complete inventory of skills/.

   4. Rows are the RAW parsed sidecar dicts — not a typed model. A legacy manifest.json on
      disk can carry arbitrary keys and may be missing name/version entirely. Every key is
      read defensively and the per-row `raw` toggle is the honest fallback for anything the
      typed line does not cover.

   5. POST /skills/import is DEV_MODE-gated (skills.py:138-139) and answers 403
      {"error":"skill import disabled — set DEV_MODE=1 to enable"}. Nothing else in the API
      discloses DEV_MODE — /sandbox/status exposes docker, /status and
      /api/health/components carry no such flag — so the panel would have to either ship a
      button that always 403s or guess. It does neither: the handler's own ordering gives a
      side-effect-free probe. POST {"skill": ""} passes the orch check, passes (or hits) the
      DEV_MODE check, and returns 400 "skill name required" BEFORE any importer call
      (skills.py:140-144). 400 => the gate was passed; 403 => it was not. No file is written
      and no network call is made on either path. The probe is a REAL POST, so it lands in
      the global action-failure sink (client.ts:84-88) and the ActionFailureBanner — which
      is why it is operator-initiated (a CHECK button) and never fires on mount, and why the
      panel says so in plain words.

   6. THE 403 IS AMBIGUOUS BY STATUS AND MUST BE CLASSIFIED BY BODY KEY. _user_guard
      (web.py:205-221) answers 401 {"detail":"user token required"} and 403
      {"detail":"user routes disabled from network — set JARVIS_USER_TOKEN to enable remote
      access"} — HTTPException bodies keyed `detail`. The route's own refusals are keyed
      `error`. A guard 403 means DEV_MODE was NEVER EVALUATED, so reading it as "DEV_MODE=0"
      would invent a fact. body.error => the route spoke; body.detail => the guard spoke.

   7. The 404 {"ok":false,"error":"Skill '<name>' not found in <source>"} is ONE string for
      several very different realities: not in the Hermes pin allowlist, a slug rejected by
      _safe_slug, a GitHub 404, a sha256 digest mismatch, a frontmatter identity mismatch
      (importer.py:200-272). It is printed verbatim and never paraphrased into a cause.

   8. A 200 echoes {"ok":true,"source":<as sent>,"skill":<as sent>} — the RAW input, not the
      slug that was written (_safe_slug lower-cases and maps spaces to '-'). So the success
      line prints only what the backend echoed and then RELOADS the list; it never presents
      the echo as the on-disk directory name.

   9. Hermes is allowlist-pinned to 84 slugs in agents/core/skills/hermes_pin_v1.json
      (NousResearch/hermes-agent @ v2026.8.27, sha256 per file). NO ROUTE EXPOSES THAT
      ALLOWLIST, so an import is guess-and-check for the operator. The slugs are backend
      data and are NOT hardcoded into this client as if they had been fetched — the gap is
      stated instead.

  10. There is NO route that sets DEV_MODE, so this panel offers no enable/disable control
      for it. It states the condition and the server-side remedy the backend itself named,
      and stops.

  11. Import performs OUTBOUND calls to raw.githubusercontent.com and api.github.com
      (importer.py:217, 302, 552) — stated once, plainly, in a privacy-conscious HUD.

   The read is unguarded; the write is USER tier (act → never actA). */
import React, { useState } from 'react';
import { useApi, arr, mono, asLive, Card, State, Row, Tag, Btn, act, inpS, Json } from '../panel-kit';

const IMPORTED_PATH = '/skills/imported';
const IMPORT_PATH = '/skills/import';

/* _safe_slug, mirrored (importer.py:57-65). A LOCAL HINT ONLY: it never blocks the POST
   and never pre-empts the backend, which reports a bad slug as the same 404 as a missing
   skill. */
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
   `detail` = _user_guard answered and the route never ran. */
const refusal = (err: any): { status: number; kind: 'route' | 'guard' | 'none'; text: string } => {
  const b: any = err && err.body;
  const isObj = !!b && typeof b === 'object';
  const kind: 'route' | 'guard' | 'none' = isObj
    ? (b.error != null ? 'route' : b.detail != null ? 'guard' : 'none')
    : 'none';
  const raw = kind === 'route' ? b.error : kind === 'guard' ? b.detail : undefined;
  const text = raw == null
    ? String((err && err.message) || 'request failed')
    : (typeof raw === 'string' ? raw : JSON.stringify(raw));
  return { status: Number(err && err.status) || 0, kind, text };
};

const H = ({ children }) => (
  <div style={{ ...mono, fontSize: 9.5, letterSpacing: '.14em', color: 'var(--ink-3)', margin: '10px 0 5px' }}>{children}</div>
);
const Note = ({ children }) => (
  <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 4, lineHeight: 1.5 }}>{children}</div>
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
  /* Unguarded read (skills.py:157 has no Depends). Not admin. */
  const { d, e, loading, reload } = useApi(IMPORTED_PATH);
  const loaded = !!d && !e;
  const rows: any[] = loaded ? arr(d, 'imported') : [];
  const readStatus = e ? statusOf(e) : 0;
  const [open, setOpen] = useState(-1);

  /* Availability of the WRITE half — only ever set from the backend's own answer. */
  const [avail, setAvail] = useState('unknown');   // unknown | checking | enabled | disabled | blocked
  const [availMsg, setAvailMsg] = useState('');

  const [skill, setSkill] = useState('');
  const [source, setSource] = useState('hermes');  // hermes | openclaw | github
  const [repo, setRepo] = useState('');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);          // {ok:boolean, text:string}

  /* The DEV_MODE probe. No `then`: skill "" can never reach a 200 (skills.py:143-144),
     so a success branch here would be dead code that only ever lies. */
  const check = () => {
    if (avail === 'checking') return;
    setAvail('checking'); setAvailMsg(''); setNote(null);
    act(IMPORT_PATH, { skill: '' }, undefined, (err) => {
      const r = refusal(err);
      if (r.status === 400 && r.kind === 'route') {
        setAvail('enabled');
        setAvailMsg(`HTTP 400 · ${r.text} — argument validation was reached, so the DEV_MODE gate was passed`);
      } else if (r.status === 403 && r.kind === 'route') {
        setAvail('disabled');
        setAvailMsg(`HTTP 403 · ${r.text}`);
      } else {
        /* 401/403 with `detail` (the guard — DEV_MODE never evaluated), 503, or an
           opaque 500 from an unhandled SkillImportError. Verbatim, never collapsed. */
        setAvail('blocked');
        setAvailMsg(`HTTP ${r.status || '?'} · ${r.text}`);
      }
    });
  };

  const sourceValue = source === 'github' ? repo : source;
  const canSubmit = avail === 'enabled' && !busy
    && !!String(skill).trim() && (source !== 'github' || !!String(repo).trim());

  const submit = () => {
    if (!canSubmit) return;
    setBusy(true); setNote(null);
    act(IMPORT_PATH, { skill, source: sourceValue },
      (r: any) => {
        setBusy(false);
        setNote({ ok: true, text: `imported · skill=${r && r.skill != null ? r.skill : '—'} · source=${r && r.source != null ? r.source : '—'}` });
        reload();
      },
      (err) => {
        const x = refusal(err);
        setBusy(false);
        setNote({ ok: false, text: `refused · HTTP ${x.status || '?'} · ${x.text}` });
        /* Availability is re-derived only from answers that actually carry it. */
        if (x.status === 403 && x.kind === 'route') { setAvail('disabled'); setAvailMsg(`HTTP 403 · ${x.text}`); }
        else if (x.kind === 'guard' || x.status === 503) { setAvail('blocked'); setAvailMsg(`HTTP ${x.status || '?'} · ${x.text}`); }
      });
  };

  const availTag = avail === 'enabled' ? null
    : avail === 'unknown' ? 'DEV_MODE unknown — press CHECK'
    : avail === 'checking' ? 'checking…'
    : avail === 'disabled' ? 'DEV_MODE=0 — import disabled by the server'
    : 'import unavailable — see the server’s answer below';

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
          ? <div style={{ color: 'var(--ink-3)', fontSize: 12 }}>
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
                    {commit && <Tag><span title={commit}>{commit.slice(0, 8)}</span></Tag>}
                    {digest && <Tag><span title={digest}>sha256 {digest.slice(0, 12)}…</span></Tag>}
                  </div>
                  {r.description ? (
                    <div style={{ fontSize: 10.5, color: 'var(--ink-3)', marginTop: 2 }}>{String(r.description)}</div>
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

      {/* ── 2 · DEV_MODE AVAILABILITY ─────────────────────────────────── */}
      <H>IMPORT · POST {IMPORT_PATH}</H>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <button className="tool-btn" onClick={check} disabled={avail === 'checking'}>
          {avail === 'checking' ? 'checking…' : 'check availability'}
        </button>
        {availTag
          ? <Tag c="var(--amber)">{availTag}</Tag>
          : <Tag c="var(--green)">import available</Tag>}
      </div>
      <Note>
        import requires <b>DEV_MODE=1</b> on the server and no route reports that flag, so availability is
        probed: the check is a <b>real POST</b> with an empty skill name, which the backend refuses at argument
        validation <i>before</i> importing anything. Nothing is written and nothing is fetched — but the refusal
        is real and is recorded in the action-failure banner.
      </Note>
      {availMsg ? (avail === 'enabled' ? <Good>{availMsg}</Good> : <Fail>{availMsg}</Fail>) : null}
      {avail === 'blocked' && (
        <Note>
          that answer carries <code>detail</code> (or no route body at all), so it came from the user-route guard
          or from an unhandled server error — the DEV_MODE gate was never reached and its state is unknown.
        </Note>
      )}

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
      {avail !== 'enabled' && (
        <Note>
          the import button stays disabled until the check above returns the backend’s own 400 — this panel does not
          ship a control it cannot show is reachable, and <b>no route can set DEV_MODE</b>, so there is nothing to
          toggle here.
        </Note>
      )}
      {badSlug && (
        <Note>
          local hint: “{slugOf(skill)}” is not a valid skill slug (lower-cased, spaces→“-”, matched against
          [a-z0-9][a-z0-9._-]&#123;0,63&#125;). The backend rejects it with the <i>same</i> 404 it uses for a missing
          skill, so the answer will not say which. The POST is still allowed.
        </Note>
      )}
      {badRepo && (
        <Note>
          local hint: owner/repo required — a bare name is fetched as
          raw.githubusercontent.com/{String(repo)}/main/skills/… and always 404s.
        </Note>
      )}
      {source === 'hermes' && (
        <Note>
          hermes imports are restricted to a pinned, sha256-verified allowlist (NousResearch/hermes-agent @
          v2026.8.27). A name outside it comes back as the backend’s generic 404. <b>No route exposes that
          allowlist</b>, so the slug has to be known in advance — that is a backend gap, not something this panel
          can fill.
        </Note>
      )}
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
      {note && !(note as any).ok && (note as any).text.indexOf('HTTP 404') >= 0 && (
        <Note>
          that one 404 string covers a name outside the pin allowlist, an unsafe slug, a GitHub 404, a sha256
          digest mismatch and a frontmatter identity mismatch. Which one fired is logged server-side and not sent,
          so it is not guessed here.
        </Note>
      )}

      <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 10, lineHeight: 1.5, borderTop: '1px solid var(--panel-line)', paddingTop: 6 }}>
        GET {IMPORTED_PATH} is <b>unguarded</b> and reads skills/&lt;slug&gt;/manifest.json sidecars ·
        POST {IMPORT_PATH} is <b>user tier</b> (X-User-Token, not admin) and DEV_MODE-gated · a real import makes
        outbound requests to raw.githubusercontent.com and api.github.com. Marketplace registry rows, review status
        and rollback are a different store and live in the SKILLS MARKETPLACE panels.
      </div>
    </Card>
  );
}
