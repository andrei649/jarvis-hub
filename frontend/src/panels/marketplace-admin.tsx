/* MARKETPLACE ADMIN — the three skill-lifecycle WRITES that shipped with no caller:
   POST /api/skills/marketplace/publish, /install-zip and /uninstall (all admin_guard'ed,
   agents/core/routers/skills.py:225 / :270 / :321).

   BOUNDARY. This is not the shipped SKILLS MARKETPLACE panel (gap.tsx:1626) in another
   coat. That one mirrors the REGISTRY (GET /api/skills/marketplace) and owns review +
   rollback. This one mirrors the INSTALLED TREE (GET /skills) and owns the lifecycle
   writes. The registry table is deliberately NOT re-rendered here.

   What the handlers actually do, and what this panel is therefore forbidden to imply:

   1. GET /skills answers `{"skills": {<name>: {...}}}` — an OBJECT MAP, not a list
      (skills.py:32-42). `arr(d,'skills')` returns [] for it, which would paint a
      permanent, honest-looking zero over a full skills tree. Object.keys is used.
      The 503 {"error":"not initialized"} makes apiGet throw, so it surfaces through
      <State e=…/> as "offline · …" and is never drawn as an empty tree.

   2. THE NAME-SPACE TRAP, and it is the whole ergonomic story of this panel: publish and
      uninstall are keyed by the ON-DISK DIRECTORY NAME under skills_dir
      (marketplace.py:326 / :622), while every read surface in the repo — GET /skills
      (loader keys = manifest names), GET /api/skills/marketplace and GET /api/packs
      (registry names = manifest names) — reports the MANIFEST TITLE. In this repo they
      differ for most bundled skills (skills/weather ships "# Weather Intel";
      skills/email_triage ships "# Email Triage"). A picker seeded from any read would
      post "Weather Intel" and collect a 404. So the folder is a TYPED field, and for the
      uninstall it is PREFILLED with the installer's own derivation
      (lower-case, spaces→underscores, marketplace.py:585) and labelled as derived —
      right for anything installed through the marketplace, wrong for repo-bundled
      skills, and the backend's 404 is what tells the difference.

   3. publish has unconditional side effects its response never mentions
      (marketplace.py:340-385): it SIGNS the folder (writes SKILL.sig), archives the row
      it replaces into marketplace_skill_versions, and INSERT-OR-REPLACEs the registry row
      with review_status hard-reset to REVIEW_PENDING. Re-publishing an approved skill
      silently makes it un-installable again under JARVIS_REQUIRE_REVIEWED_SKILLS. That
      is stated as STATIC text about the route — never as a field of the response, which
      carries only {name, version, author, description}.

   4. install-zip answers a bare {"ok": true}. No name, no version, no path, no count.
      The destination folder is derived INSIDE the zip (first "# " heading of SKILL.md,
      marketplace.py:673-692) and is not reported, so this panel never prints a
      destination and never says "installed <skill>". The only honest evidence of what
      landed is a DELTA of GET /skills taken across the call — and discover() is additive
      (loader.py:494-516), so an empty delta means "nothing new appeared, the package may
      have replaced an existing folder", which is exactly what is rendered. Not a failure,
      not a success naming a skill.

   5. install-zip also DELETES the owner-approval marker and writes source=marketplace
      (marketplace.py:718-725): the package loads external/untrusted and cannot self-grant
      in-process execution. GET /skills exposes no trusted/sandboxed/signature_reason
      field, so this is static text about the route, never a per-response tag. Installing
      is not approving.

   6. THE COLLAPSED REFUSALS ARE LEFT COLLAPSED. publish's 404 is one string,
      "skill not found", for BOTH "no such directory" and "SKILL.md missing" (error_json,
      CWE-209 — the path is logged, not sent). install-zip's 400 is one string,
      "skill package rejected (unsafe path or signature policy)", for missing SKILL.md,
      an unsafe derived folder, a zip-slip member, the signature gate AND invalid base64
      padding. The 403s discard the supply-chain contract's machine reason
      (invalid_skill_name / missing_field:name / contract_error) before answering. This
      panel prints what arrived and explains the collapse; it never guesses which cause
      fired.

   7. uninstall's success is `removed`, NOT `ok`. With purge=true and nothing on disk the
      route answers 200 {"ok":true,"removed":false,"purged":true} — nothing was deleted.
      The result branches on r.removed and the false branch is amber and never uses the
      word "uninstalled". rmtree is irreversible; the registry row and its package blob
      are a separate store, and the documented recovery is the already-shipped marketplace
      INSTALL control (frontend/src/api/actions.ts:77), which is why that is named instead
      of being re-implemented here.

   7b. `purged` IS NOT A RESULT. skills.py:356 answers `"purged": body.purge` — this
      panel's own request flag handed straight back. Underneath, uninstall_skill
      (marketplace.py:635-636) calls remove_from_registry(name) and DISCARDS its boolean,
      so no row count ever reaches the wire. Worse, that DELETE runs
      `WHERE name = ?` against a registry keyed by the MANIFEST TITLE (publish_skill
      stores manifest["name"], marketplace.py:361) while `name` here is the ON-DISK
      FOLDER — the same folder-vs-title split §2 is about. Reproduced against the real
      class: publish('weather') registers 'Weather Intel'; uninstall_skill('weather',
      purge=True) returns removed=True while list_skills() still shows ['Weather Intel'].
      Every skill bundled in this repo has a title that differs from its folder
      (weather -> "Weather Intel", brief -> "Brief", pm -> "PM" — all 12), so on a default
      install the purge box deletes NOTHING. Therefore: the checkbox is labelled as the
      literal string-match it is, the panel compares the folder it SENT against the tree's
      manifest title to say whether a row published from this skill could have matched,
      and the word "purged" is never printed as an outcome.

   8. apiPost THROWS on 4xx and the parsed body rides on err.body (client.ts:98-104);
      err.message is only "POST <path> -> <status>". Every write passes onErr and renders
      the backend's own body.error / body.detail (admin_guard 401/403 and 422 use
      `detail`) verbatim, in role="alert". No invented cause, ever.

   9. The zip arrives from a FILE PICKER, never a base64 textarea — a textarea for
      zip_base64 would be a form no human can honestly fill. The data: prefix is stripped
      before posting (gap.tsx:2007 idiom) because b64decode(validate=False) would corrupt
      it into a 500 rather than reject it. No size limit is claimed: the backend has none.

   All three writes are admin tier (actA → X-Admin-Token); /skills is read at user tier. */
import React, { useState } from 'react';
import { useApi, mono, asLive, Card, State, Row, Tag, Btn, actA, inpS, Json } from '../panel-kit';

const PUBLISH_PATH = '/api/skills/marketplace/publish';
const INSTALL_ZIP_PATH = '/api/skills/marketplace/install-zip';
const UNINSTALL_PATH = '/api/skills/marketplace/uninstall';

/* The refusal string, straight off the wire. `error` covers the three handlers,
   `detail` covers admin_guard's 401/403 (a string) and FastAPI's 422 (an array of
   {loc,msg,type}), `message` covers the generic 500 shape. err.message is the LAST
   resort because it holds only "POST <path> -> <status>". */
const why = (err: any): string => {
  const b = err && err.body;
  const d = b && b.detail;
  return (b && typeof b.error === 'string' ? b.error : '')
    || (typeof d === 'string' ? d : d != null ? JSON.stringify(d) : '')
    || (b && typeof b.message === 'string' ? b.message : '')
    || (err && err.message)
    || 'request failed';
};

const H = ({ children }) => (
  <div style={{ ...mono, fontSize: 9.5, letterSpacing: '.14em', color: 'var(--ink-3)', margin: '10px 0 5px' }}>{children}</div>
);
const Note = ({ children }) => (
  <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 4, lineHeight: 1.5 }}>{children}</div>
);
const Fail = ({ msg, status }: { msg: any; status?: any }) => (
  <div role="alert" style={{ ...mono, fontSize: 10.5, marginTop: 6, color: 'var(--red)' }}>
    {msg} · HTTP {status == null ? '?' : status}
  </div>
);
const Good = ({ children }) => (
  <div style={{ ...mono, fontSize: 10.5, marginTop: 6, color: 'var(--green)' }}>{children}</div>
);
const Amber = ({ children }) => (
  <div role="status" style={{ ...mono, fontSize: 10.5, marginTop: 6, color: 'var(--amber)' }}>{children}</div>
);

export function MarketplaceAdminPanel() {
  /* User tier: GET /skills carries no guard dependency (skills.py:28). */
  const { d, e, loading, reload } = useApi('/skills');
  const map = (d && (d as any).skills) || null;
  const names: string[] = map ? Object.keys(map) : [];

  const [pubName, setPubName] = useState('');
  const [pubBusy, setPubBusy] = useState(false);
  const [pub, setPub] = useState(null);          // {ok:true, p} | {ok:false, msg, status}

  const [b64, setB64] = useState('');
  const [fileName, setFileName] = useState('');
  const [bytes, setBytes] = useState(0);
  const [zipBusy, setZipBusy] = useState(false);
  const [zip, setZip] = useState(null);          // {ok, raw} | {ok:false, msg, status}
  const [before, setBefore] = useState(null);    // Set<string> captured just before the POST

  const [armed, setArmed] = useState(null);      // manifest name of the row being confirmed
  const [unName, setUnName] = useState('');
  const [purge, setPurge] = useState(false);
  const [unBusy, setUnBusy] = useState(false);
  const [un, setUn] = useState(null);            // {res} | {msg, status}

  /* ── publish ─────────────────────────────────────────────────────────── */
  const publish = () => {
    if (pubBusy || !pubName.trim()) return;
    setPubBusy(true); setPub(null);
    actA(PUBLISH_PATH, { name: pubName },
      (r) => { setPub({ ok: true, p: (r && (r as any).published) || null, raw: r }); setPubBusy(false); },
      (err) => { setPub({ ok: false, msg: why(err), status: err && err.status }); setPubBusy(false); });
  };

  /* ── install-zip ─────────────────────────────────────────────────────── */
  const onFile = (ev) => {
    const f = ev && ev.target && ev.target.files && ev.target.files[0];
    setZip(null); setBefore(null);
    if (!f) { setB64(''); setFileName(''); setBytes(0); return; }
    const reader = new FileReader();
    reader.onload = () => {
      const res = String(reader.result || '');
      /* Strip "data:application/zip;base64," — b64decode(validate=False) silently
         discards the alphabet-foreign characters and then dies on the padding, so an
         unstripped prefix reads as a 500, not as a clean rejection. */
      setB64(res.slice(res.indexOf(',') + 1));
      setFileName(f.name || 'package.zip');
      setBytes(Number(f.size) || 0);
    };
    reader.readAsDataURL(f);
  };
  const install = () => {
    if (zipBusy || !b64) return;
    setZipBusy(true); setZip(null);
    setBefore(new Set(names));
    actA(INSTALL_ZIP_PATH, { zip_base64: b64 },
      (r) => { setZip({ ok: !!(r && (r as any).ok === true), raw: r }); setZipBusy(false); reload(); },
      (err) => { setZip({ ok: false, msg: why(err), status: err && err.status }); setZipBusy(false); });
  };
  const appeared = (zip && (zip as any).ok && before) ? names.filter((n) => !(before as any).has(n)) : [];

  /* ── uninstall ───────────────────────────────────────────────────────── */
  const arm = (manifestName) => {
    setArmed(manifestName);
    /* The installer's own derivation (marketplace.py:585). A PREFILL, not a fact. */
    setUnName(String(manifestName || '').toLowerCase().replace(/ /g, '_'));
    setPurge(false);
    setUn(null);
  };
  const confirmRemove = () => {
    if (unBusy || !unName.trim()) return;
    setUnBusy(true); setUn(null);
    /* What we SENT is the only trustworthy record of the purge request — the response's
       `purged` is that same flag echoed, and the box unmounts on success. */
    const sentFolder = unName.trim();
    const sentTitle = armed;
    const sentPurge = purge;
    actA(UNINSTALL_PATH, { name: unName, purge },
      (r) => { setUn({ res: r, sentFolder, sentTitle, sentPurge }); setUnBusy(false); setArmed(null); reload(); },
      /* Stay armed on a refusal — the folder name is usually what needs fixing. */
      (err) => { setUn({ msg: why(err), status: err && err.status }); setUnBusy(false); });
  };

  const p = pub && (pub as any).ok ? (pub as any).p : null;
  const ures = un && (un as any).res ? (un as any).res : null;

  return (
    <Card title="MARKETPLACE ADMIN" live={asLive(d)} sub={names.length} onReload={reload}>
      <State e={e} loading={loading} n={names.length} />

      {/* ── 1 · PUBLISH FROM DISK ─────────────────────────────────────── */}
      <H>PUBLISH FROM DISK · POST {PUBLISH_PATH}</H>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <input
          style={{ ...inpS, flex: 1 }}
          aria-label="skills directory name"
          placeholder="weather"
          value={pubName}
          onChange={(ev) => setPubName(ev.target.value)}
        />
        <button className="tool-btn" disabled={pubBusy || !pubName.trim()} onClick={publish}>
          {pubBusy ? 'publishing…' : 'publish'}
        </button>
      </div>
      <Note>
        keyed on the <b>skills/ FOLDER</b> name. GET /skills reports the manifest title, which differs
        (skills/weather ships “# Weather Intel”), and no route anywhere exposes folder names — so it is typed, not picked.
      </Note>
      <Note>
        every publish signs the folder, archives the registry row it replaces, and resets review_status to
        <b> pending</b> — an already-approved skill must be re-approved before it can be installed again.
      </Note>
      {pub && (pub as any).ok === false && <Fail msg={(pub as any).msg} status={(pub as any).status} />}
      {pub && (pub as any).ok === true && (p
        ? <Good>published {p.name ?? '—'} v{p.version ?? '—'} · {p.author ?? '—'}
            {p.description ? <span style={{ color: 'var(--ink-3)' }}> · {p.description}</span> : null}
          </Good>
        : <Amber>200 ok:true but the response carried no `published` object<Json v={(pub as any).raw} max={90} /></Amber>)}
      {pub && (pub as any).ok === false && (pub as any).status === 404 && (
        <Note>404 “skill not found” is one string for two causes — no such directory under skills/, or no SKILL.md
          inside it. The backend logs which and sends neither, so neither is claimed here.</Note>
      )}
      {pub && (pub as any).ok === false && (pub as any).status === 403 && (
        <Note>the supply-chain contract’s own machine reason (invalid_skill_name / missing_field:name /
          contract_error) is raised server-side and dropped before the response — only the sentence above arrives.</Note>
      )}

      {/* ── 2 · INSTALL PACKAGE ───────────────────────────────────────── */}
      <H>INSTALL PACKAGE (.zip) · POST {INSTALL_ZIP_PATH}</H>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <input type="file" accept=".zip,application/zip" aria-label="skill package zip" onChange={onFile} style={{ ...mono, fontSize: 10 }} />
        <button className="tool-btn" disabled={zipBusy || !b64} onClick={install}>
          {zipBusy ? 'installing…' : 'install package'}
        </button>
      </div>
      <Note>{b64 ? `loaded · ${fileName} · ${bytes} B` : 'pick a .zip skill package'} — the whole file is sent
        base64-encoded in one JSON body; neither this panel nor the backend enforces a size limit.</Note>
      {zip && (zip as any).ok === false && (zip as any).msg && <Fail msg={(zip as any).msg} status={(zip as any).status} />}
      {zip && (zip as any).ok === true && <>
        <Good>backend returned {'{"ok": true}'} — the response carries no skill name, version or path</Good>
        {loading ? <Amber>re-reading /skills to see what appeared…</Amber>
          : e ? <Amber>cannot diff /skills — the read failed: {e}</Amber>
          : appeared.length ? <Good>new in /skills: {appeared.join(', ')}</Good>
          : <Amber>no new name in /skills — the package may have replaced an existing folder</Amber>}
      </>}
      {zip && (zip as any).ok === false && !(zip as any).msg && (
        <Amber>200 without ok:true<Json v={(zip as any).raw} max={90} /></Amber>
      )}
      <Note>
        the destination folder is derived from the “# ” heading inside the zip’s SKILL.md (lower-cased,
        spaces→underscores) and is never reported back, so no path is printed here. The extracted package has its
        owner-approval marker removed and source=marketplace written: it loads external/untrusted —
        <b> installing is not approving</b>.
      </Note>
      <Note>
        a file that is not a zip answers 500 “internal error”. Bad base64 padding, a zip-slip member, a missing
        SKILL.md, an unsafe derived folder and a signature-gate refusal all answer the SAME 400 string, so which one
        fired is not knowable from the response and is not guessed.
      </Note>

      {/* ── 3 · UNINSTALL ─────────────────────────────────────────────── */}
      <H>INSTALLED TREE · UNINSTALL · POST {UNINSTALL_PATH}</H>
      {names.map((k) => {
        const s = (map && map[k]) || {};
        return (
          <Row key={k}>
            <span style={{ ...mono, color: 'var(--accent-light)' }}>{s.name || k}</span>
            <Tag>{s.version || '—'}</Tag>
            <Btn onClick={() => arm(s.name || k)}>uninstall…</Btn>
          </Row>
        );
      })}
      {armed && (
        <div style={{ marginTop: 8, padding: 8, border: '1px solid var(--red)', borderRadius: 4 }}>
          <div style={{ ...mono, fontSize: 10.5, color: 'var(--red)' }}>confirm removal of “{armed}”</div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6, flexWrap: 'wrap' }}>
            <input
              style={{ ...inpS, flex: 1, minWidth: 140 }}
              aria-label="skills/ folder"
              value={unName}
              onChange={(ev) => setUnName(ev.target.value)}
            />
            <label style={{ ...mono, fontSize: 10, display: 'flex', gap: 4, alignItems: 'center', color: 'var(--ink-2)' }}>
              <input type="checkbox" aria-label="purge registry row matching the folder string" checked={purge} onChange={(ev) => setPurge(!!ev.target.checked)} />
              purge · also delete the registry row whose name equals the folder string
            </label>
            <button className="tool-btn" disabled={unBusy || !unName.trim()} onClick={confirmRemove} style={{ color: 'var(--red)' }}>
              {unBusy ? 'removing…' : 'confirm remove'}
            </button>
            <button className="tool-btn" onClick={() => { setArmed(null); setUn(null); }}>cancel</button>
          </div>
          <Note>
            the folder above is <b>derived</b> (lower-cased, spaces→underscores) exactly the way the installer derives
            it. For a marketplace-installed package that is right; for a repo-bundled skill it can be wrong
            (“Weather Intel” → weather_intel, actual folder “weather”) and the 404 is what tells you.
          </Note>
          <Note>
            the registry is keyed by the <b>manifest title</b>, not by the folder, and the purge delete matches the
            folder string above verbatim — it can only hit a row published under that same string.{' '}
            {unName.trim() === armed
              ? <>here the two are identical (“{armed}”), so a row published from this skill is in range.</>
              : <>here they differ (“{unName.trim() || '—'}” vs the tree’s title “{armed}”), so ticking the box
                  deletes <b>no</b> row published from this skill — the package blob survives either way.</>}
          </Note>
          <Note>rmtree is irreversible. The registry row and its package blob live in a separate store, so the
            marketplace INSTALL control can restore the skill from there — through the moderation/signature gate.</Note>
        </div>
      )}
      {un && (un as any).msg && <Fail msg={(un as any).msg} status={(un as any).status} />}
      {ures && (ures.removed === true
        ? <Good>removed skills/{ures.uninstalled ?? '—'}</Good>
        : ures.removed === false
          ? <Amber>ok:true but removed:false — nothing was deleted from disk</Amber>
          : <Amber>the response carried no `removed` field<Json v={ures} max={90} /></Amber>)}
      {/* The registry half of the outcome. `removed` above is a real result; `purged` is NOT —
          it is the request flag echoed, so everything below is stated from what was SENT. */}
      {ures && ((un as any).sentPurge
        ? <Note>
            purge was requested. The response does not say whether a registry row was deleted — its `purged` field
            is this panel’s own flag handed back, and the backend drops the delete’s row count.{' '}
            {(un as any).sentFolder === (un as any).sentTitle
              ? <>the folder sent and the tree’s manifest title were the same string
                  (“{(un as any).sentTitle}”), so a row published under that name was in range of the delete.</>
              : <>the delete matched the literal folder “{(un as any).sentFolder}”, while a row published from this
                  skill is keyed by its manifest title “{(un as any).sentTitle}” — those differ, so that row was
                  <b> not</b> deleted and the published package is still installable.</>}
            {' '}Registry rows are shown in the SKILLS MARKETPLACE panel, not here.
          </Note>
        : <Note>purge was not requested: the registry row and its package blob are untouched, so the marketplace
            INSTALL control can restore the skill — through the moderation/signature gate.</Note>)}

      <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 10, lineHeight: 1.5, borderTop: '1px solid var(--panel-line)', paddingTop: 6 }}>
        all three writes are <b>admin tier</b> (actA · X-Admin-Token); the installed-tree read above is GET /skills at
        user tier, and a failed read shows as “offline · …” rather than as an empty tree. Registry rows, review status
        and package rollback live in the SKILLS MARKETPLACE panel — install-zip writes no registry row, so a
        zip-installed package appears in /skills only.
      </div>
    </Card>
  );
}
