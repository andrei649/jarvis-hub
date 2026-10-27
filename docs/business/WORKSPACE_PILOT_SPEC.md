# Nerva Workspace — pilot specification (the build contract)

> **Status: ACTIVE build contract, v3** (v1 2026-10-17 → v2 the same day after an adversarial,
> code-grounded review that produced 41 amendments, 8 of them blocking → **v3, 2026-10-17, after
> the build: the builders' and reviewers' deviations are folded in so this file matches the code —
> response shapes, extra error codes, reasons and JSON fields, the extraction pool, the folded
> tokenizer, the delivery-status transitions, AUTOINCREMENT plus the id-reuse guards, and the
> cloud-only `provider_may_train` rule**; **v3.1, the same day, after the known-issues pass: the
> data directory moved to `data_path("business")` (NWS-14), loop-aware scheduler and run
> cancellation, `can_open` on conversation citations, the e2e lane in CI**; **v3.2, 2026-10-18,
> after the first assessment round: the audit key guard (§6 Audit), the CLI preflight (§5 `cli.py`),
> `invalid_identifier` sign-ins, `/admin/stats?tz=`, `ready_document_count`, `share_pending`, the
> withdrawal reason kept on superseded approvals, the localized delivery-failure notice,
> `LLMResult.failure_kind` and the model-server liveness probe, the interrupted-document sweep
> and the frontend behaviours in §10**); **v3.3, 2026-10-19, after the second assessment round
> and the polish pass: the round-2 frontend behaviours in §10 (drafts on every form, locality in
> words, translated audit values, status-dependent preview headings, lead citation chips, the
> verify sentence after a re-key, the export caption on phones), the scheduler pausing its
> audited steps while the audit key is not the trail's (§5, §9), private workspace files whatever
> the umask and the hub-side guard on explicit file / terminal roots (§3), operator hints naming
> `nerva-run` (§5), the backup CLI's paths and one-line errors (Appendix A), and the e2e lane's
> SMTP off switch and results directory (§13)**; **v3.4, 2026-10-19, after the third assessment
> round: schema v2 — a report run's `delivery_state` (`pending` → `sent` | `failed`, stored with
> `succeeded` in one statement) and `error_reason` (§4, §5, §7), the `deliveries_interrupted` sweep
> and the `delivery_interrupted` code for a hub that stopped mid-send (§5, §9), the run view that
> follows its email live and words a failure in the chat's sentences (§10), the shared-folder
> rule for a symlinked `business/` (§3), the e2e lane's model off switch, SMTP greeting hold and
> 1024 px layout pass with 31 steps (§13), the backup CLI's `nerva-run` usage line (Appendix A)**;
> **v3.4 review fixes (round 4, R4-01 … R4-08): schema v3 — `report_runs.delivery_attempted`, the
> count a delivery was addressed to, stored with `pending` and audited by the restart sweep (§4, §9);
> a company-shared run's failed delivery hidden outside its department with the rest of the delivery
> (§7 *Run fields*); a run or report that answers 404 while its page follows it stops the polling
> (§10); the shared-folder WARNING's verb agrees with its count (§3)**).
> Operator documentation: [`PILOT_GUIDE.md`](PILOT_GUIDE.md).
> Owner directive (2026-10-17): *„avansează, pregătește interfața B2B pentru un pilot … produsul să fie
> de nota 9/10 chiar și pentru pilot, toate funcțiile trebuie să funcționeze"*. This file is the single
> shared contract every builder, reviewer and integrator follows. When code and this file disagree,
> fix one of them in the same change — never leave drift. Upstream: the kickoff questionnaire
> [`docs/decisions/2026-10-14-nerva-business-suite-kickoff-questions.md`](../decisions/2026-10-14-nerva-business-suite-kickoff-questions.md).
> Appendix A lists verified facts about the codebase that every builder must respect.

## 0. Assumptions adopted for the pilot (D1–D7 are unanswered; these are the recommended defaults)

| Decision | Assumption used for this build |
|---|---|
| D1 customer #1 | One company, several departments; the first install can be Digitaholic itself. Departments are configurable. |
| D2 delivery | Software only. Runs wherever the hub runs. Model = a local OpenAI-compatible server on the hub host (Ollama / vLLM / llama.cpp / LM Studio) or an approved no-training cloud provider. No hardware work. |
| D3 identity | Single tenant per install, many users inside: local accounts, admin invites, scrypt passwords, httpOnly sessions, roles per department, optional SSO through a trusted reverse proxy that injects the user's email plus a shared secret. Native OIDC is out of scope for this slice. |
| D4 integrations | No ERP/CRM connectors in this slice. Knowledge comes from uploaded company documents. MCP-first connectors are the next slice. |
| D5–D7 | Not code; nothing here assumes an answer. |

## 1. Goal, non-goals, definition of done

**Goal.** A separate, polished web application — **Nerva Workspace** — where any employee logs in and,
inside their departments, (1) asks a governed AI assistant questions answered from company documents
with citations, (2) manages the department knowledge base, (3) defines and runs reports, scheduled or
on demand, and exports them, (4) requests and approves consequential actions (email delivery,
company-wide sharing) with a named approver, while (5) admins manage users, departments, model
policy, email delivery and a tamper-evident audit trail naming the person behind every action.

**Non-goals.** Native OIDC/SAML; ERP/CRM/accounting connectors; multi-tenant hosting; a native mobile
app; the personal HUD for employees; any use of the owner's personal pipeline, memory or agents (the
workspace never calls `orch.handle_input`, `orch.process` or the personal memory); hardware.

**Definition of done (all must hold).**
1. Every control visible in the UI performs its real effect end to end. No mock data, no dead button.
   Features needing configuration (model, SMTP) show an honest, actionable state when unconfigured.
2. Department isolation is enforced server-side in every query and proven by tests.
3. Backend pytest suites for every module, green; frontend vitest + `tsc --noEmit`, green; a Playwright
   journey drives the real server end to end with a fake OpenAI-compatible model server and a local
   SMTP sink, green, with an axe scan of every main page (zero serious/critical violations). The
   journey is `frontend/e2e/workspace-journey.spec.ts` under `frontend/playwright.workspace.config.ts`
   (`npm run e2e:workspace` in `frontend/`); CI runs it in `.github/workflows/e2e.yml` right after the
   HUD lane (nightly, on push to `main`, on dispatch) and uploads
   `frontend/e2e/.results/workspace-screens/` when it fails.
4. Every repo gate in §11 stays green.
5. A reviewer scoring the pilot against the rubric (§12) gives ≥ 9/10 on every dimension.

## 2. Code map and ownership (single writer per file)

| Slice | Owns (only these files) |
|---|---|
| **S1 Foundation** | `agents/core/workspace/__init__.py`, `config.py`, `db.py`, `errors.py`, `http.py`, `identity.py`, `auth.py`, `audit.py`, `notifications.py`, `effects_api.py`, `cli.py`, `__main__.py`; `agents/core/routers/workspace_auth.py`, `agents/core/routers/workspace_admin.py`; `tests/support/workspace_fixtures.py` (incl. `FakeEngine`); `tests/test_workspace_foundation_*.py` |
| **S2 Knowledge** | `agents/core/workspace/extract.py`, `documents.py`, `retrieval.py`; `agents/core/routers/workspace_documents.py`; `tests/test_workspace_documents*.py`, `tests/test_workspace_retrieval*.py`, `tests/fixtures/workspace/**`; `requirements.txt`, `requirements.lock`, `requirements-beta.txt`, `requirements-beta.lock` (adds `pypdf` and an unconditional `tzdata` only) |
| **S3 Assistant** | `agents/core/workspace/llm.py`, `assistant.py`; `agents/core/routers/workspace_chat.py`; `tests/support/fake_openai_server.py`; `tests/test_workspace_assistant*.py`, `tests/test_workspace_llm*.py` |
| **S4 Automation** | `agents/core/workspace/reports.py`, `scheduler.py`, `approvals.py`, `mailer.py`; `agents/core/routers/workspace_reports.py`, `agents/core/routers/workspace_approvals.py`; `tests/support/smtp_sink.py`; `tests/test_workspace_reports*.py`, `tests/test_workspace_scheduler*.py`, `tests/test_workspace_approvals*.py`, `tests/test_workspace_mailer*.py` |
| **S5 Frontend** | everything under `frontend/src/workspace/**`, `frontend/workspace.html`, `frontend/vite.workspace.config.ts`, the `scripts` block of `frontend/package.json`, any new font files under `frontend/src/assets/fonts/`, built output `agents/web/workspace/**` |
| **S6 Integration** | `agents/web.py` (static mount, router includes, lifespan start/stop, rate-limit exemption, `RequestValidationError` + `WorkspaceError` handler wiring), `agents/core/routers/workspace_ui.py`, `agents/core/data_purge.py` (KEEP_DIRS), `tests/test_route_auth_matrix.py`, `tests/test_route_parity_guard.py` snapshot, `tests/test_hud_v2_parity.py`, `scripts/gen_api_sweep.py`, `tests/test_api_sweep_current.py`, `docs/test-manual/14-api-surface-sweep.md`, `tests/_snapshots/*.json`, `frontend/src/api/schema.gen.ts`, `frontend/playwright.config.ts`, `frontend/playwright.workspace.config.ts`, `frontend/tsconfig.e2e.json`, `frontend/e2e/workspace*.spec.ts`, `frontend/e2e/support/workspace*`, `.github/workflows/ci.yml` (bundle check only), `.github/workflows/e2e.yml` (the journey step, v3.1), `Dockerfile` (tzdata only if needed), status files written by `scripts/status_sync.py`, `mobile/PARITY.md`, `tests/test_workspace_integration*.py`, and the docs in §13 |

Rules for every builder: never edit a file you do not own (report the need instead); never run
`git add/commit/stash/checkout/reset/restore`; never run repo-wide formatters; use
`/home/user/jarvis-hub/.venv/bin/python` (install with `uv pip install --python …`, the venv has no
pip); import as `agents.core.…`, never `core.…`. Slice tests build a minimal `FastAPI()` through
`tests/support/workspace_fixtures.make_app(...)`; they never rely on `get_orch()` returning `None`
(the conftest autouse fixture imports `agents.web` and an earlier test may leave an orchestrator
behind) and always install a model engine with `llm.set_engine_for_tests(...)` when a model is used.

## 3. Runtime configuration (`config.py`; parsing only through `agents/core/env_config.py`)

| Variable | Default | Rule |
|---|---|---|
| `NERVA_WORKSPACE` | off | `env_flag(name, False)`, read at request time. Off → every `/api/workspace/*` answers `404 {"error":"workspace_disabled"}` and the UI route answers a plain 404 page. `db.get_db` refuses before opening a connection, so a disabled workspace never creates `workspace.db`; the scheduler tick is a no-op; the CLI exits 2 (one of its preflight refusals, §5 `cli.py`). |
| `NERVA_WORKSPACE_SETUP_CODE` | unset | When unset, a code `secrets.token_urlsafe(18)` is generated on first need and written with `O_EXCL`, mode 0600, to `<data>/business/setup-code.txt`; never logged (the log line names the file and the command that prints it, `nerva-run -m agents.core.workspace setup-code`: the pilot guide's §2 wrapper, so it runs with the service's environment). Deleted after a successful setup. |
| `NERVA_WORKSPACE_COOKIE_SECURE` | `auto` | `raw = env_str(name, 'auto').strip().lower()`; `''`/`auto` → auto (Secure when `request.url.scheme == 'https'`); `is_recognized_bool(raw)` → `truthy(raw)`; anything else → auto plus one warning naming the variable. |
| `NERVA_WORKSPACE_SSO_HEADER` | unset | Header carrying the user's email (e.g. `X-Forwarded-Email`). SSO also requires `NERVA_WORKSPACE_SSO_SECRET` (see §6). |
| `NERVA_WORKSPACE_SSO_SECRET` | unset | Shared secret the proxy injects as `X-Nerva-Proxy-Secret` (constant names `config.ENV_SSO_KEY`, `auth.PROXY_KEY_HEADER`; `config.sso_configured()` needs both variables). |
| `NERVA_WORKSPACE_MAX_UPLOAD_MB` | 25 | `min(env_int(name, 25, minimum=1), 200)`, in MiB (× 1024²). |
| `NERVA_WORKSPACE_SESSION_IDLE_HOURS` | 12 | `env_int(minimum=1)`, clamped to 1..168. |
| `NERVA_WORKSPACE_SESSION_MAX_DAYS` | 7 | `env_int(minimum=1)`, clamped to 1..90. |
| `NERVA_WORKSPACE_MAX_CONCURRENT_LLM` | 2 | `env_int(minimum=1)`, clamped to 1..16; one process-wide semaphore. |
| `NERVA_WORKSPACE_SCHEDULER` | on | `env_flag(name, True)`; read by `scheduler.start_background()` only, so a change needs a restart. |

The numeric rows clamp only from above: `env_int(..., minimum=1)` returns the **default** for 0, a
negative or a non-integer value (`2.5`, `abc`), so the lower bound is never applied by clamping. No
numeric value is refused or logged.

Never write `"1", "true"`-style literal pairs or `== "1"` next to an env read (AUD-14 ratchet).

**Data location.** Everything lives under `data_path("business")` (`config.DATA_DIRNAME`), resolved
at call time: `workspace.db`, `files/<document_id>.bin`, `setup-code.txt`, `secrets.enc` (+
`secrets.enc.key` when no `JARVIS_SECRET_KEY`). The audit HMAC key lives outside the data root (§6).
The hub's nightly backup (03:20, kept a week) archives the whole data root including the workspace
(databases through the SQLite backup API); it is encrypted only when `JARVIS_BACKUP_KEY` is set, so the
pilot guide requires `JARVIS_BACKUP_KEY` and `JARVIS_SECRET_KEY` on pilot installs. The hub's "forget
me" purge never touches the workspace (`business` is in `data_purge.KEEP_DIRS`). **Why `business`
(v3.1, `BACKLOG.md` NWS-14, closed):** `data_path("workspace")` is the hub's default root of the
owner's file tools (`JARVIS_FILE_ROOTS`), of `JARVIS_TERMINAL_LOCAL_ROOTS` and of the tool-result
spill directory (`workspace/tool_results/`), so company data there was readable by the owner's
personal assistant, and keeping `workspace` in `KEEP_DIRS` kept the owner's spilled tool results
through a forget. No other hub module uses `business`; `tests/test_workspace_integration_purge.py`
proves the directory is disjoint from all three default roots, that no other module under `agents/`
names it, and that a forget empties the spill directory while the workspace survives. The pilot was
never released from `workspace/`, so there is no migration.

**Explicit hub roots (v3.3, `BACKLOG.md` NWS-17).** `config.hub_roots_without_workspace(setting,
roots)` drops every configured root whose real location (`~`, `..` and symlinks resolved) is,
contains or lies inside `data_path("business")` — `<data>/business` itself, the data root, `/`, a
home folder holding the data root, `business/files` — and logs one WARNING per (setting, root) per
process on `nerva.workspace.config`, which says what the drop keeps outside company data and no
more: the file tools, for `JARVIS_FILE_ROOTS`; the terminal's working directory, for
`JARVIS_TERMINAL_LOCAL_ROOTS`, with the limit below (review REV-POLISH-03); every other entry is kept unchanged and in order (blank,
relative or unresolvable ones included). `FileScope.from_env()` (`agents/core/file_tools.py`,
`JARVIS_FILE_ROOTS`) and `local_transport.default_roots()` / `LocalHostTransport.from_env()`
(`agents/core/environments/local_transport.py`, `JARVIS_TERMINAL_LOCAL_ROOTS`) apply it and fall
back to the default `data_path("workspace")` when no root is left; they import the workspace config
lazily, only when roots are configured, so the literal `business` still appears only in the
workspace package. Limits: nothing is dropped while the workspace is off and `<data>/business` does
not exist (no company data), or when the data root cannot be determined; roots passed in code (the
`FileScope([...])` and `LocalHostTransport(roots)` constructors, `from_env(roots=...)`) are not
filtered; and for the terminal the roots constrain only the working directory — an absolute path
inside an approved argv is governed by the terminal's own contract and approval, not by roots.

**File modes (v3.3, review OPS2-05).** `db.connect()` creates `workspace.db` itself, empty, with
`O_CREAT | O_EXCL | O_NOFOLLOW` at 0600 plus an explicit chmod, whatever the umask (`sqlite3` alone
would make it `0644 & ~umask`); SQLite gives `-wal` / `-shm` the database's mode. `files/` (0700),
`files/<id>.bin`, `secrets.enc` with its `.key` / salt, and `setup-code.txt` (0600) were already
private at creation. The first `connect()` of each process for a workspace directory
(`db.secure_storage`, once per process — the scheduler's first tick at hub start, else the first
request or CLI command) walks `<data>/business` without following symlinks and removes the
group/other permission bits of every file and directory, so a tree a restore or a copy left
`0644` / `0755` becomes `0600` / `0700` (owner bits kept). A real `business/` directory is walked in
full. A `business/` that is itself a symlink to a folder (data on another disk) is resolved once
(review REV-POLISH-02) and below that folder no symlink is followed or changed; the change and
refusal WARNINGs then name `<data>/business → <folder>`. **v3.4 (review SEC-EDGE-1): only the
workspace's own entries there.** The folder is walked in full only while every entry directly in
it is one of the workspace's own names (`db.own_entry`): `workspace.db` and `workspace.db-*`,
`files` (`config.FILES_DIRNAME`), `secrets.enc` and `secrets.enc.*` (`config.SECRETS_FILE`: the
store's key, salt and temporary siblings), `setup-code.txt` and `.setup-code.txt.*`
(`config.SETUP_CODE_FILE`, written through a temporary sibling). A folder that holds anything else
too (a mount root with other data) gets one WARNING — `<data>/business is a link to <folder>, which
also holds N entries that are not the workspace's (a, b, c, …), so only the workspace's own files
there are made private and nothing else in that folder is changed — link business/ to a folder of
its own (PILOT_GUIDE §13)` (at most three names, then `…`; for a single one `1 entry that is not
the workspace's`, review R4-08) — and only those own entries are
tightened: `files/` in full while it holds nothing but what `documents` writes (`<id>.bin`,
`.upload-*.tmp`, `.deleted-<id>.tmp`), else just those files in it. The folder's own mode and every
foreign entry keep their modes. "The folder holds `workspace.db`" is deliberately not the test:
the first `connect()` creates the database there before the walk runs, so every shared folder
would pass it from the second start. A `business/` link to a folder that holds the data root
itself (`/`, `<data>`, a folder above it) is not walked at all: one WARNING says the modes were not
checked. It logs one WARNING on `nerva.workspace.db` when it changed something, one when the
system refuses a chmod (files owned by another user) — naming `chown -R jarvis:jarvis` and
`chmod -R go-rwx`, or in a shared folder `chown jarvis:jarvis` and `chmod go-rwx` on the
workspace's own entries only, "not on the whole folder" — and never fails the connect.
`db.connect_read_only` (`check`, the start check) changes no mode. This covers `<data>/business`
only: the rest of the data root (`backups/`, `settings.db`, …) still follows the service's umask,
hence `UMask=0077` in the pilot guide's §2.

## 4. Data model (`db.py` owns the whole schema; migrations through `PRAGMA user_version`)

Timestamps are UTC epoch seconds (REAL). Department references to "company-wide" use
`documents.visibility='company'`, never a NULL department. **AUTOINCREMENT** (v3) on every table
whose ids leave the row — `departments`, `documents`, `conversations`, `messages`, `reports`,
`report_runs`, `approvals`, `notifications` — because SQLite otherwise hands the id of the newest
deleted row to the next insert, so one id could name two objects (another department's) in audit
target ids, approval payloads, notification links, `files/<id>.bin` or a request held across an
`await`. The slices' own id-reuse guards stay as defence in depth (§6 Uploads, §8).

```sql
CREATE TABLE org (id INTEGER PRIMARY KEY CHECK (id = 1), name TEXT NOT NULL,
  default_locale TEXT NOT NULL DEFAULT 'ro' CHECK (default_locale IN ('ro','en')),
  model_policy TEXT NOT NULL DEFAULT 'local_only' CHECK (model_policy IN ('local_only','allow_cloud')),
  settings_json TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL);
CREATE TABLE departments (id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '', assistant_instructions TEXT NOT NULL DEFAULT '',
  archived INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL);
CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('admin','approver','member')),
  status TEXT NOT NULL CHECK (status IN ('invited','active','disabled')),
  password_hash TEXT, locale TEXT NOT NULL DEFAULT 'ro' CHECK (locale IN ('ro','en')),
  theme TEXT NOT NULL DEFAULT 'light' CHECK (theme IN ('light','dark','system')),
  last_login_at REAL, created_at REAL NOT NULL);
CREATE TABLE user_departments (user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
  PRIMARY KEY (user_id, department_id));
CREATE TABLE invites (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id)
  ON DELETE CASCADE, purpose TEXT NOT NULL CHECK (purpose IN ('invite','reset')),
  created_by INTEGER REFERENCES users(id), created_at REAL NOT NULL, expires_at REAL NOT NULL, used_at REAL);
CREATE TABLE sessions (id_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id)
  ON DELETE CASCADE, csrf_token TEXT NOT NULL, created_at REAL NOT NULL, last_seen_at REAL NOT NULL,
  expires_at REAL NOT NULL, ip TEXT NOT NULL DEFAULT '', user_agent TEXT NOT NULL DEFAULT '',
  via TEXT NOT NULL DEFAULT 'password' CHECK (via IN ('password','invite','setup','sso')),
  sso_email TEXT, revoked_at REAL);
CREATE TABLE login_attempts (id INTEGER PRIMARY KEY, ip TEXT NOT NULL, email TEXT NOT NULL,
  ok INTEGER NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('login','setup','invite_lookup','sso')),
  ts REAL NOT NULL);
CREATE TABLE documents (id INTEGER PRIMARY KEY AUTOINCREMENT, department_id INTEGER REFERENCES departments(id),
  visibility TEXT NOT NULL DEFAULT 'department' CHECK (visibility IN ('department','company')),
  title TEXT NOT NULL, filename TEXT NOT NULL, mime TEXT NOT NULL, size_bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL, uploader_id INTEGER REFERENCES users(id),
  status TEXT NOT NULL CHECK (status IN ('processing','ready','failed')), error TEXT,
  page_count INTEGER, chunk_count INTEGER NOT NULL DEFAULT 0, char_count INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL, updated_at REAL NOT NULL,
  CHECK (visibility = 'company' OR department_id IS NOT NULL));
-- invariant (enforced by the CHECK): visibility='department' ⇒ department_id NOT NULL; company-wide
-- uploads store the uploader's chosen department or NULL with visibility='company'.
CREATE TABLE chunks (id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id)
  ON DELETE CASCADE, ord INTEGER NOT NULL, page INTEGER, text TEXT NOT NULL, embedding BLOB);
CREATE VIRTUAL TABLE chunks_fts USING fts5(text, content='chunks', content_rowid='id',
  tokenize='unicode61 remove_diacritics 2');   -- + the standard ai/ad/au sync triggers
CREATE TABLE conversations (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id)
  ON DELETE CASCADE, department_id INTEGER NOT NULL REFERENCES departments(id), title TEXT NOT NULL,
  created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INTEGER NOT NULL
  REFERENCES conversations(id) ON DELETE CASCADE, role TEXT NOT NULL CHECK (role IN ('user','assistant')),
  content TEXT NOT NULL, citations_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'complete' CHECK (status IN ('pending','complete','error')), error_code TEXT,
  model TEXT, route TEXT, locality TEXT, latency_ms INTEGER, feedback INTEGER, feedback_note TEXT,
  created_at REAL NOT NULL);
CREATE TABLE reports (id INTEGER PRIMARY KEY AUTOINCREMENT, department_id INTEGER NOT NULL REFERENCES departments(id),
  name TEXT NOT NULL, instructions TEXT NOT NULL, document_ids_json TEXT NOT NULL DEFAULT '[]',
  schedule_kind TEXT NOT NULL DEFAULT 'manual' CHECK (schedule_kind IN ('manual','daily','weekly')),
  schedule_time TEXT, schedule_weekday INTEGER, timezone TEXT NOT NULL DEFAULT 'Europe/Bucharest',
  delivery_emails_json TEXT NOT NULL DEFAULT '[]', delivery_status TEXT NOT NULL DEFAULT 'none'
  CHECK (delivery_status IN ('none','pending','approved','rejected')),
  delivery_approved_json TEXT NOT NULL DEFAULT '[]', delivery_approval_id INTEGER,
  owner_id INTEGER REFERENCES users(id), active INTEGER NOT NULL DEFAULT 1,
  next_run_at REAL, last_run_at REAL, created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE report_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, report_id INTEGER NOT NULL REFERENCES reports(id)
  ON DELETE CASCADE, status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed')),
  trigger TEXT NOT NULL CHECK (trigger IN ('manual','schedule')), triggered_by INTEGER REFERENCES users(id),
  content_md TEXT, citations_json TEXT NOT NULL DEFAULT '[]', model TEXT, route TEXT, locality TEXT,
  error_code TEXT, error TEXT, shared_company INTEGER NOT NULL DEFAULT 0,
  delivered_to_json TEXT NOT NULL DEFAULT '[]', started_at REAL, finished_at REAL, created_at REAL NOT NULL);
-- schema v2 (v3.4, reviews NWS-20 / UX-23), db._SCHEMA_V2:
ALTER TABLE report_runs ADD COLUMN delivery_state TEXT
  CHECK (delivery_state IS NULL OR delivery_state IN ('pending','sent','failed'));
ALTER TABLE report_runs ADD COLUMN error_reason TEXT;
CREATE INDEX idx_report_runs_delivery_pending ON report_runs(delivery_state, finished_at);
-- schema v3 (v3.4 review fix R4-07), db._SCHEMA_V3:
ALTER TABLE report_runs ADD COLUMN delivery_attempted INTEGER;
CREATE TABLE approvals (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, department_id INTEGER REFERENCES departments(id),
  requester_id INTEGER NOT NULL REFERENCES users(id), summary TEXT NOT NULL, payload_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending','executing','approved','rejected','cancelled','expired','failed')),
  decided_by INTEGER REFERENCES users(id), decided_at REAL, decision_note TEXT, result_json TEXT,
  error_code TEXT, created_at REAL NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id)
  ON DELETE CASCADE, kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
  link TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, read_at REAL);
CREATE TABLE audit (id INTEGER PRIMARY KEY, ts REAL NOT NULL, actor_user_id INTEGER,
  actor_email TEXT NOT NULL DEFAULT '', action TEXT NOT NULL, target_type TEXT NOT NULL DEFAULT '',
  target_id TEXT NOT NULL DEFAULT '', department_id INTEGER, ip TEXT NOT NULL DEFAULT '',
  details_json TEXT NOT NULL DEFAULT '{}', prev_hash TEXT NOT NULL, hash TEXT NOT NULL,
  key_fp TEXT NOT NULL);
```
Indexes on every foreign key and on `login_attempts(email, ts)`, `login_attempts(ip, ts)`,
`notifications(user_id, read_at)`, `approvals(status, expires_at)`, `audit(ts)`,
`report_runs(report_id, created_at)`, `messages(conversation_id, id)`, `reports(active, next_run_at)`
(plus `login_attempts(ts)`, `chunks(document_id, ord)`, `conversations(user_id, updated_at)`,
`audit(actor_user_id)` and `audit(action)`; v2 `report_runs(delivery_state, finished_at)`, for the
delivery sweep).
**Schema versions.** `db.MIGRATIONS = [(1, _SCHEMA_V1), (2, _SCHEMA_V2), (3, _SCHEMA_V3)]`;
`db.schema_version()` is 3. A database at `user_version` N runs every script above N at the next
`connect()`, each in one `BEGIN IMMEDIATE` together with its `user_version` bump (each logged once at
INFO: `workspace database migrated to schema 2`, then `… schema 3`). v2 is the first forward
migration: `ADD COLUMN` keeps every run, and a schema-1 run reads `NULL` in both new columns; v3 adds
`delivery_attempted` the same way (`NULL` for every older run). On an un-migrated copy the CLI
`check` prints `schema 1; this code migrates it to 3 at the first start` (or `schema 2; …`) and
still counts it ready. `delivery_state` is `NULL` for a run with no approved delivery (§9 *Delivery
state*); `error_reason` qualifies `error_code` as an error body's `reason` does (§9 *Failure
reasons*); `delivery_attempted` is how many approved recipients the delivery was addressed to,
written with `delivery_state='pending'` (`NULL` with no delivery), what the restart sweep audits for
a delivery its sender never settled (§9).
Department names are unique ignoring case with Unicode `casefold` (SQLite `NOCASE` folds ASCII
only: „VÂNZĂRI" clashes with „Vânzări" → `409 department_exists`). Deleting an empty department
sets `approvals.department_id` to NULL on the approvals that referenced it (that foreign key has no
cascade).

## 5. Python contracts (exact names; other slices code against these)

```python
# errors.py
class WorkspaceError(Exception):
    def __init__(self, code: str, message: str = "", status: int = 400, **extra): ...
    # .code .message .status .extra
def error_response(exc: WorkspaceError) -> JSONResponse   # {"error", "message", **extra}; Cache-Control: no-store;
    # an int extra retry_after_seconds also sets Retry-After
def register_handlers(app) -> None   # WorkspaceError + RequestValidationError (reshaped on /api/workspace only)

# http.py
async def read_json(request, *, max_bytes: int = 65536, allow_empty: bool = False) -> dict
    # requires application/json; streamed cap → 413 payload_too_large; non-object/invalid → 422
    # invalid_request; NaN, Infinity, overflowing numbers and over-deep nesting → 422 field=body
    # reason=malformed; 415 unsupported_media_type. allow_empty: routes whose fields are all optional
def ws_json(data, status: int = 200, headers: dict | None = None, *,
            cookies_from: Response | None = None) -> JSONResponse   # Cache-Control: no-store; copies
    # the Set-Cookie of an injected Response (FastAPI does not merge it into a returned JSONResponse)
def require_str(d, key, *, max_len, min_len=0, required=True, strip=True, multiline=False) -> str
    # 422 invalid_request with "field" and "reason"; single-line fields refuse C0/C1 controls,
    # U+2028/U+2029 and lone surrogates (reason control_characters); multi-line fields turn
    # U+2028/U+2029 into newlines; passwords pass strip=False
def require_int(...), require_list(...), require_id_list(...), require_email(...), optional_*(...)
MAX_ID = 2 ** 63 - 1   # every id Path/Query parameter is Annotated[int, Path(ge=1, le=MAX_ID)]; body
    # integers stay in SQLite's range (422 reason too_large) — 10**20 must never reach sqlite3
# 422 reasons: required, too_long, too_short, too_small, too_large, malformed, type, invalid,
# control_characters, invalid_choice, invalid_email, too_few, too_many, not_ascii,
# not_an_object (field=body: valid JSON that is not an object), …

# config.py
def enabled() -> bool; def setup_code() -> str; def max_upload_bytes() -> int
def cookie_secure_mode() -> str          # 'auto' | 'on' | 'off'
def session_idle_seconds() -> int; def session_max_seconds() -> int; def max_concurrent_llm() -> int
def sso_header() -> str; def sso_secret() -> str; def sso_configured() -> bool; def scheduler_enabled() -> bool
def workspace_dir() -> Path               # data_path(DATA_DIRNAME) = <data>/business, created 0700 on demand;
    # made private again at each process's first connect (db.secure_storage, §3 File modes)
def hub_roots_without_workspace(setting: str, roots: Sequence[str]) -> list[str]
    # v3.3 (NWS-17, §3): roots minus any that is, contains or lies inside <data>/business
SETUP_CODE_FILE = "setup-code.txt"; FILES_DIRNAME = "files"; SECRETS_FILE = "secrets.enc"
    # v3.4: the workspace's own names under business/ (documents.FILES_DIR and mailer.STORE_FILE
    # point at the last two); db.own_entry reads them

# db.py
def db_path() -> Path
def connect() -> sqlite3.Connection
    # v3.3: creates the file 0600 when missing; the first connect of a process runs
    # secure_storage(<data>/business) once (§3 File modes)
    # sqlite3.connect(path, check_same_thread=False, isolation_level=None)  ← autocommit
    # PRAGMA journal_mode=WAL; foreign_keys=ON; busy_timeout=5000; row_factory=sqlite3.Row
    # schema ensured on every connect (one cheap PRAGMA user_version read; migrations by user_version)
    # NWS-13 (decided workspace-wide): synchronous SQLite work never runs on the event loop.
    # Sync `def` routes already run in FastAPI's thread pool; inside an `async def` handler, effect
    # executor or upload/reindex flow every `db.tx` (BEGIN IMMEDIATE, up to the 5 s busy timeout), FTS
    # query and read goes through `await http.offload(fn, *args)` (= asyncio.to_thread: one request
    # connection, one thread at a time, contextvars copied). The 5 s busy timeout is unchanged; a held
    # write lock delays only the requests that need it. Test: tests/test_workspace_sqlite_off_loop.py.
def connect_read_only(path: Path) -> sqlite3.Connection   # no migration, no write, no new file, no chmod
MIGRATIONS: list[tuple[int, str]] = [(1, _SCHEMA_V1), (2, _SCHEMA_V2), (3, _SCHEMA_V3)]   # v3.4: v2, v3 (§4)
def schema_version() -> int                # MIGRATIONS[-1][0] = 3
def migrate(conn) -> int                   # every pending script in one BEGIN IMMEDIATE with its bump
def secure_storage(directory: Path) -> list[Path]   # v3.3: group/other bits off under directory, no
    # symlink followed below it (directory itself a link → its folder, unless that folder holds
    # directory's parent: not walked, one WARNING); v3.4: a linked folder that also holds entries
    # own_entry rejects → one WARNING, only the workspace's own entries tightened (§3); returns
    # what changed; PRIVATE_FILE_MODE = 0o600, PRIVATE_DIR_MODE = 0o700
def own_entry(name: str) -> bool           # v3.4: name, directly under business/, is the workspace's:
    # workspace.db / workspace.db-*, files, secrets.enc / secrets.enc.*, setup-code.txt /
    # .setup-code.txt.*
@contextmanager
def tx(conn)        # BEGIN IMMEDIATE … COMMIT, ROLLBACK on exception; a no-op when conn.in_transaction
def get_db()        # FastAPI generator dependency: 404 workspace_disabled BEFORE connecting while off;
                    # yields connect(); finally: rollback if in_transaction, close
Db = Annotated[sqlite3.Connection, Depends(get_db)]
# Rules: every write runs inside `with tx(conn):`. Never hold a transaction across an `await` of the
# model, SMTP, extraction or any I/O. Writes that must survive an error response (failed login,
# throttling rows, approval.failed, email.failed) commit in their own tx BEFORE raising.
# Streaming routes use a fresh connect() for writes after the stream starts.

# identity.py
COMPANY = "company"                       # sentinel; never pass None for "company-wide"
SCRYPT_N = 2 ** 15                        # tests monkeypatch to 2**10; n is stored in the hash
@dataclass(frozen=True)
class WorkspaceUser:
    id: int; email: str; name: str; role: str; status: str; locale: str; theme: str
    department_ids: tuple[int, ...]
    @property
    def is_admin(self) -> bool
    def can_access_department(self, department_id: int) -> bool   # TypeError on None; archived → admin only
    def can_approve_in(self, department_id: int) -> bool           # admin, or approver who is a member
    def allowed_department_ids(self, conn) -> list[int]            # admin: all non-archived; else own non-archived
def hash_password(pw: str) -> str          # call through asyncio.to_thread in async code
def verify_password(pw: str, stored: str | None) -> bool   # None/unknown → verify against DUMMY hash, False
def validate_password(pw: str, *, email: str = "") -> None # WorkspaceError('weak_password', reason=…)
def get_user(conn, user_id: int) -> WorkspaceUser | None
def get_user_by_email(conn, email: str) -> sqlite3.Row | None
def user_to_json(u: WorkspaceUser, conn=None) -> dict      # id, email, name, role, status, locale, theme,
                                                           # department_ids, permissions{…}
def department_to_json(row, *, counts: dict | None = None) -> dict
def ensure_org(conn) -> sqlite3.Row | None; def org_to_json(row) -> dict

# auth.py (FastAPI dependencies; these exact __name__s are what the route-auth matrix reads)
def ws_enabled() -> None                    # 404 workspace_disabled when off
def ws_user_guard(request: Request, conn: Db, _on: Annotated[None, Depends(ws_enabled)]) -> WorkspaceUser
    # cookie nerva_ws_session → session (not revoked, not expired, idle ok) → active user;
    # mutating methods: Origin/Sec-Fetch-Site same-origin check + X-CSRF-Token compare_digest
    # → 401 auth_required | 403 csrf_failed; touches last_seen_at at most every 60 s (own tx)
def ws_admin_guard(user: Annotated[WorkspaceUser, Depends(ws_user_guard)]) -> WorkspaceUser  # 403 forbidden
WsUser = Annotated[WorkspaceUser, Depends(ws_user_guard)]
WsAdmin = Annotated[WorkspaceUser, Depends(ws_admin_guard)]
Enabled = Annotated[None, Depends(ws_enabled)]
def client_ip(request) -> str               # see Appendix A (trusted proxies)
def check_public_origin(request) -> None    # public POSTs: same-origin rule + JSON content type
def reserve_login_attempt(conn, *, email: str, ip: str) -> int
    # in ONE BEGIN IMMEDIATE: the throttle check (429 too_many_attempts) and a failure row stored up
    # front, so a parallel burst cannot outrun the limit while scrypt runs; returns the row id
def settle_login_success(conn, attempt_id: int) -> None   # flips the reserved row to ok=1
def record_login_failure(conn, request, *, attempt_id: int, email: str, reason: str,
                         target_user_id: int | None = None, actor: WorkspaceUser | None = None) -> None
    # commits auth.login_failed, and auth.throttled once — by the failure that reaches a limit
def issue_session(conn, response, request, user_id: int, *, via: str, sso_email: str | None = None) -> str
    # returns csrf_token; sets cookie; caller is inside tx
def clear_session_cookie(response, request) -> None
def current_session_hash(request) -> str | None

# audit.py
def record(conn, *, actor: WorkspaceUser | None, action: str, target_type: str = "",
           target_id: str | int = "", department_id: int | None = None, ip: str = "",
           details: dict | None = None, actor_email: str = "") -> None
    # requires conn.in_transaction (raises RuntimeError otherwise); reads the previous hash inside it.
    # Detail keys that would carry secrets or content (password, token, csrf_token, secret, setup_code,
    # prompt, answer, content, content_md, text, body, body_markdown, preview) are dropped at any
    # depth, as is any key containing password/token/secret/api_key whose value is text or a
    # structure (bools, numbers and None survive: has_password, prompt_tokens); each drop is logged
    # by key path and never fails the user's action. v3.2: raises AuditKeyMissing /
    # AuditKeyMismatch (503, nothing written — the caller's tx rolls back) when this process's
    # key is not the one the newest row was signed with
def verify_chain(conn) -> dict   # {"ok", "checked", "broken_at", "keyed": True, "key_mismatch": bool,
    # "unverified": int, "rekeyed_at": int | None}; after a re-key to the current key, the earlier
    # rows another key signed count as `unverified` (not a break) while the re-key row's pin of
    # them holds; `checked` counts the rows the current key verified
# v3.2 — the key guard (review OPS2-01)
class AuditKeyError(WorkspaceError)        # this process cannot extend the trail (503)
class AuditKeyMissing(AuditKeyError)       # 503 audit_key_missing: the trail has rows, the process
    # has neither JARVIS_AUDIT_KEY nor the key file (never minted: a new key would break the chain)
class AuditKeyMismatch(AuditKeyError)      # 503 audit_key_mismatch: a key, but not the newest row's
    # (logged with the key's source and both fingerprints, never the key)
def audit_key(conn=None) -> bytes          # env value, else the key file; a key file is created
    # only for an empty trail — with conn given and rows in its trail a missing key raises
    # AuditKeyMissing (record and verify_chain always pass their connection)
def existing_key() -> bytes | None; def key_source() -> str   # never create a key
def key_check(conn) -> str                 # 'ok' (empty trail, or the newest row's key) |
    # 'missing' | 'unreadable' | 'mismatch'; reads only, never creates a key
def startup_key_check() -> str | None      # the hub lifespan: workspace on and a database present →
    # opened read-only (db.connect_read_only), key_check, an ERROR log line when not 'ok'
    # ("Nerva Workspace cannot sign its audit trail: … check with: <CHECK_COMMAND> — the causes and
    # remedies are in PILOT_GUIDE §17."); never blocks the start
CHECK_COMMAND = "nerva-run -m agents.core.workspace check (PILOT_GUIDE §2; the service's environment)"
REKEY_COMMAND = "nerva-run -m agents.core.workspace audit-rekey (PILOT_GUIDE §16)"
    # v3.3 (review OPS2-07): the operator commands every log hint names — the missing-key and
    # mismatch refusals, the start check and the scheduler's pause line; no string outside a
    # docstring in agents/core/workspace names the bare `python -m agents.core.workspace` form
REKEY_ACTION = "audit.rekeyed"
def rekey_plan(conn) -> dict               # read-only: {state, rows, unverified, broken_at,
    # from_key_fp, to_key_fp, through_id, digest}
def rekey(conn, *, actor_email: str) -> int   # a key that is truly lost: one audit.rekeyed row,
    # signed with the new key, records both fingerprints and pins every earlier row (SHA-256 over
    # all their columns); RekeyRefused('not_needed' | 'no_key' | 'broken') writes nothing

# cli.py (v3.2) — `nerva-run -m agents.core.workspace <command>` (v3.3: PROG, the name usage and
# --help print; nerva-run is the pilot guide's §2 `python -m` with the service's environment, and
# --help says to run the commands that way): setup-code · reset-link --email E --base-url U · promote --email E · check ·
# audit-rekey [--confirm]. Preflight before anything is opened or created, exit 2 with a message
# naming nerva-run: NERVA_WORKSPACE off; no JARVIS_HOME / JARVIS_MEMORY_DIR and the data root
# inside the checkout; no database (reset-link, promote, audit-rekey; setup-code creates it);
# key_check not 'ok' (audit-rekey alone proceeds on 'mismatch'). Exit 1: no such user, user
# disabled (reset-link), already set up (setup-code), an invalid --base-url (scheme + host
# [+ root path]; a trailing /workspace is dropped, any other path under /workspace refused).
# `check` never refuses and writes nothing (the database opened read-only, no key created):
# workspace on/off, data root, database + schema, audit key state with fingerprints → "ready"
# exit 0, else "NOT ready" exit 1. `audit-rekey` without --confirm shows the plan and exits 2.

# notifications.py
def notify(conn, user_ids: Iterable[int], *, kind: str, title: str, body: str = "", link: str = "") -> None
    # link must be app-relative (/workspace/approvals/7); a backslash, whitespace or control
    # character stores '' (no protocol-relative open redirect from the bell menu)
def department_approvers(conn, department_id: int, *, exclude: int | None = None) -> list[int]
    # active approvers who are members of it + active admins, minus `exclude`
def admins(conn, *, exclude: int | None = None) -> list[int]

# approvals.py (S4) — the helpers other domain modules call
def notify_localized(conn, user_ids, *, kind: str, titles: Mapping[str, str], body: str = "",
                     link: str = "", bodies: Mapping[str, str] | None = None) -> None
    # one notification per active user, titled — and with `bodies` (v3.2) worded — in that
    # user's locale (fallback 'ro')
def cancel_superseded(conn, approval_ids, *, actor, reason: str, ip: str = "") -> list[int]
    # joins the caller's tx: pending → 'cancelled'; v3.2 stores `reason` in error_code
    # ('superseded' | 'recipients_removed' | 'report_deleted'), so the item says why it was
    # withdrawn; a request its requester cancelled keeps error_code null

# effects_api.py — the approval effect registry
@dataclass
class ValidatedRequest:
    department_id: int | None; summary: str; payload: dict
@dataclass
class EffectSpec:
    kind: str
    validate: Callable[[sqlite3.Connection, WorkspaceUser, dict], ValidatedRequest]   # raise WorkspaceError
    execute: Callable[[dict, WorkspaceUser, WorkspaceUser], Awaitable[dict]]
        # (approval row as dict incl. payload, requester, decider) -> result dict; opens its own connections
    decider_rule: str = "department"   # "department" | "admin"
def register_effect(spec: EffectSpec) -> None   # replaces an existing spec of the same kind
def get_effect(kind: str) -> EffectSpec         # WorkspaceError('unknown_kind', status=400)
def kinds() -> list[str]
# Each domain module calls register_effect() at import; its router imports that module.

# documents.py (S2)
STALE_PROCESSING_SECONDS = 600; INTERRUPTED = "interrupted"
def fail_interrupted(conn, now: float, *, claimed_before: float | None = None) -> int
    # v3.2, the scheduler's documents step: 'processing' rows claimed at or before now - 600 s,
    # or before claimed_before (the hub's start: one hub per data root, so that extraction died
    # with its process) → status 'failed', error 'interrupted', chunks deleted, counts 0, in one
    # tx; returns how many (logged as a count only). Re-index works on them at once

# retrieval.py (S2)
@dataclass
class Passage:
    chunk_id: int; document_id: int; title: str; department_id: int | None
    text: str; page: int | None; score: float
def search(conn, *, department_ids: Sequence[int], include_company: bool, query: str, k: int = 6,
           document_ids: Sequence[int] | None = None) -> list[Passage]
    # scope enforced in SQL even when document_ids is given; never raises on odd input (→ [])

# llm.py (S3)
@dataclass
class LLMResult:
    text: str; model: str; route: str; locality: str; latency_ms: int   # locality: local|cloud|unknown
    failure_kind: str = ""   # v3.2: what the backend noted for a failed call (provider_failure_scope;
    # 'unreachable' wins when noted); '' when nothing was noted. It only qualifies a degraded reply
class LLMUnavailable(WorkspaceError)       # code model_unavailable, status 503, extra reason=…:
    # hub_not_ready, no_local_model, no_model (allow_cloud, nothing selectable), model_not_approved,
    # backend_error (the data-handling gate could not decide, or an unexpected backend fault),
    # model_unreachable (the server cannot be reached: down, or the connection dropped mid-answer),
    # model_error (the server answered with an error), thinking_exhausted, empty_answer
class ModelPolicyBlocked(WorkspaceError)   # code model_policy_blocked, status 409, extra reason=…
    # data_policy_unacknowledged | provider_may_train
class ModelBusy(WorkspaceError)            # code model_busy, 503, extra retry_after_seconds=10
class ModelTimeout(WorkspaceError)         # code model_timeout, 504; constructible with no argument
class ContentBlocked(WorkspaceError)       # code content_blocked, 422 (guardrails SecurityBlockError)
def clean_text(text: str) -> str           # valid Unicode: split surrogate pairs re-paired, lone ones → '?'
async def complete(*, system: str, prompt: str, policy: str, max_tokens: int = 1200,
                   temperature: float = 0.2, on_token: Callable[[str], Awaitable[None]] | None = None,
                   timeout_seconds: float = 180.0) -> LLMResult
async def posture(policy: str) -> dict
    # {"available", "backend", "model", "route", "locality", "policy", "reason", "guardrails_mode"};
    # never raises: an unforeseen engine fault reads available=false, reason=backend_error,
    # guardrails_mode=unknown
def set_engine_for_tests(engine) -> None   # engine exposes async complete(**same kwargs) and async
    # posture(policy); None restores the real HubEngine
def note_liveness(backend, alive: bool) -> None   # v3.2: what a real call just learned about a local
    # model server (an unreachable failure reply → down, a non-empty answer → up); feeds the
    # posture's liveness cache (LIVENESS_TIMEOUT_SECONDS = 2.0, LIVENESS_TTL_SECONDS = 30.0, App. A)
# The semaphore (one per event loop — the hub runs one), the 64-character hold-back, clean_text and
# the failure-reply check live in the public complete() wrapper, so they apply to every engine,
# FakeEngine included, and reports share the one process-wide model semaphore.

# assistant.py (S3)
def build_sources_block(passages, *, locale: str) -> tuple[str, list[dict]]
    # prompt block + citations [{n, document_id, title, chunk_id, page, excerpt}]
def filter_citations(text: str, citations: list[dict]) -> list[dict]   # only the [n] the text uses

# reports.py (S4)
def create_run(conn, report_id: int, *, trigger: str, triggered_by: int | None, ip: str = "") -> int   # inside tx
async def execute_run(run_id: int) -> None          # own connections; Semaphore(2) per event loop (the hub has one)
def spawn_run(run_id: int) -> None                  # task on the running loop, kept in a module-level set; exceptions logged
async def cancel_runs() -> None                     # shutdown: the RUNNING loop's in-flight runs → failed / interrupted
    # (a run already succeeded and sending its email ends its delivery failed / delivery_interrupted)
def compute_next_run(report_row, now: float) -> float | None
# v3.4 (reviews NWS-20, UX-23; §9 Delivery state, Failure reasons)
DELIVERY_PENDING = "pending"; DELIVERY_SENT = "sent"; DELIVERY_FAILED = "failed"   # delivery_state
DELIVERY_INTERRUPTED = "delivery_interrupted"     # the error_code of a delivery whose sender stopped
DELIVERY_ERROR = "delivery_failed"                # report_runs.error of a succeeded run whose email failed
DELIVERY_TIMEOUT_SECONDS = 15 * 60
def failure_reason(error: WorkspaceError) -> str | None   # error.extra['reason'] when a non-empty str
    # (llm's model_unreachable …, mailer's smtp_failed timeout …), else None
def fail_stuck_deliveries(conn, now: float, *, stored_before: float | None = None) -> int
    # the scheduler's deliveries step: runs whose delivery_state is still 'pending' and that were
    # stored (finished_at) 900 s or more ago, or before stored_before (this hub's start: one
    # hub per data root, so their sender is gone) → failed / delivery_interrupted, at most 500 a
    # tick, each in its own tx through the same compare-and-set as the sender; returns how many

# scheduler.py (S4)
class WorkspaceScheduler:
    def __init__(self, interval_seconds: float = 30.0, started_at: float | None = None): ...
        # started_at (v3.2): db.now() when start_background() builds the process-wide scheduler;
        # None (tests) = only the age rules apply (600 s for documents.fail_interrupted, v3.4
        # 900 s for reports.fail_stuck_deliveries, which also takes it as stored_before)
    async def tick(self, now: float | None = None) -> dict   # the testable unit; {now, errors,
        # paused, audit_key (v3.3), runs_started, approvals_expired, approvals_interrupted,
        # runs_interrupted, deliveries_interrupted (v3.4), messages_interrupted,
        # documents_interrupted (v3.2), deleted} — or {skipped} while off. v3.3: `paused` lists
        # the steps skipped this tick, `audit_key` is 'ok' | 'mismatch' | 'missing' | 'unreadable'
        # (§9 Under a wrong audit key)
AUDITED_STEPS = ("runs_started", "approvals_expired", "approvals_interrupted", "runs_interrupted",
                 "deliveries_interrupted")
    # v3.3: the steps that sign audit rows; they pause while audit.key_check(conn) is not 'ok'
    # (v3.4 adds deliveries_interrupted, which audits email.failed)
    def start(self) -> None              # idempotent per loop: records the owning loop of each loop task
    async def stop(self) -> None         # stops only the running loop's task
def start_background() -> None; async def stop_background() -> None   # S6 calls from the hub lifespan
# v3.1: loop-aware. A lifespan can run more than once in one process on different event loops (a
# nested TestClient, an embedding host). start() on a loop without a live task starts one there even
# while another loop's task runs; stop() / stop_background() / cancel_runs() touch only the running
# loop's scheduler task and report runs, so a nested lifespan's shutdown never cancels or awaits a
# task of a foreign loop; the process-wide scheduler is released once no loop runs it.

# mailer.py (S4)
def smtp_settings(conn) -> dict          # without the password; has_password: bool, configured: bool
def smtp_configured(conn) -> bool        # host AND from_address set (cheap: no secret-store access)
async def send_mail(*, to: Sequence[str], subject: str, text: str, html: str | None = None,
                    reply_to: str | None = None) -> list[str]   # the recipients the server accepted
    # own connection for settings, smtplib in a worker thread; WorkspaceError smtp_not_configured (409),
    # recipient_not_allowed (422, extra recipients + allowed_domains), invalid_request (422),
    # smtp_password_unreadable (409: SecretStoreError — re-enter the password), smtp_failed (502,
    # reason auth_failed | not_supported | recipients_refused | sender_refused | data_refused |
    # tls_failed | timeout | connection_failed | smtp_error | insecure_transport). It does NOT audit:
    # callers write email.sent / email.failed themselves.
```

**Test fixtures (S1, `tests/support/workspace_fixtures.py`) — pinned API.**
`ws_env(monkeypatch, tmp_path)` (sets `JARVIS_HOME`, `JARVIS_KEY_DIR`, `NERVA_WORKSPACE=1`,
`NERVA_WORKSPACE_SETUP_CODE=test-setup-code`, `identity.SCRYPT_N=2**10`, installs a `FakeEngine`);
pytest fixture `ws` that yields that environment; `make_app(*routers) -> FastAPI` (registers the
`WorkspaceError` and validation handlers); `db() -> sqlite3.Connection`; `seed_org(conn, name='Acme') ->
dict`; `make_department(conn, name) -> int`; `make_user(conn, *, role, department_ids, email=None,
password=None, status='active') -> WorkspaceUser` (None resolves to `'Parola-Buna-2026!'`);
`login(client, email, password=None) -> str` (returns csrf); `authed(client, csrf) -> dict` of
headers; `FakeEngine(reply=..., *, stream=True, fail=None, delay=0, …)` (keyword-only options) with
`.calls` and deterministic citation-aware output (quotes `[1]` when the prompt holds a
`<source id="1">`).

## 6. Security model

- **Passwords.** `hashlib.scrypt` n=`SCRYPT_N`, r=8, p=1, dklen=32, 16-byte salt, `maxmem=64 MiB`,
  encoded `scrypt$<log2 n>$8$1$<salt b64>$<hash b64>`; constant-time verify; hashing runs in
  `asyncio.to_thread`. Policy: 12–256 chars, not containing the email's local part, not in an embedded
  list of ≥ 100 common passwords → `422 weak_password` with `reason` in
  {`too_short`,`too_long`,`contains_email`,`too_common`}.
- **Sessions.** Token `secrets.token_urlsafe(32)` in cookie `nerva_ws_session`, DB stores SHA-256 only.
  Cookie: `HttpOnly; SameSite=Lax; Path=<request.app.root_path>/api/workspace`; `Secure` per §3. (Lax,
  not Strict: an invite link opened from email must not land logged-out on the next click; CSRF is
  covered by the token and the Origin rule.) Idle and absolute expiry per §3. A new session on every
  login, accept and setup; password change revokes all other sessions; disabling a user or changing
  their role revokes all of theirs.
- **CSRF.** Synchronizer token: each session row holds `csrf_token`, returned in the JSON of
  `GET /session`, `/login`, `/setup`, `/invites/accept`, `/login/sso`. Every authenticated mutating
  request must send `X-CSRF-Token` equal to it (compare_digest) → `403 csrf_failed`. In addition, every
  mutating `/api/workspace` request (public or authenticated) with an `Origin` header must match the
  request's own origin (scheme://host from `request.base_url`), or `Sec-Fetch-Site` must be
  `same-origin`/`none`, else `403 csrf_failed`. Public mutating routes also require
  `Content-Type: application/json`. The workspace never sends CORS headers: the hub-wide
  `JARVIS_CORS_ORIGINS` middleware is installed as `http.WorkspaceExemptCORSMiddleware`, which passes
  every `/api/workspace*` and `/workspace*` request (preflights included, root-path aware) straight to
  the app, so a listed origin gets no `Access-Control-*` header there.
- **Login throttling (no enumeration).** Keyed on the lowercased email through `login_attempts`, for
  existing and nonexistent emails alike: after 5 consecutive failures for that email within 15 min the
  answer is `429 too_many_attempts` with `retry_after_seconds`. Per IP: 20 failures / 15 min → same 429.
  Failures answer the generic `401 invalid_credentials` (unknown, invited and disabled users included);
  unknown or password-less users are verified against a fixed dummy scrypt hash so timing does not leak.
  v3.2: what was typed in the email field is kept (attempt row, `auth.login_failed`) only when
  `http.normalize_email` accepts it; anything else — a password typed into the wrong field — is
  recorded as `''` with reason `invalid_identifier`, so it never reaches the append-only audit. `''`
  has no per-email bucket (no account can match it, and one shared bucket would let anyone's garbage
  lock the next mistyped login out); the per-IP limit still counts it.
  Setup code: 10 failures / hour / IP and 50 failures / hour globally → 429; invite lookup and accept:
  30 tries / hour / IP. Attempt rows are committed before the error is raised. Each login attempt is
  **reserved as a failure before its password is verified** (`reserve_login_attempt`: the check and the
  row in one `BEGIN IMMEDIATE`) and flipped on success, so a parallel burst cannot outrun the limit —
  an attempt still being verified counts for the ~250 ms of the hash; a `429` writes no row, so the
  lock lifts as the window slides; the email count runs since that email's last success;
  `auth.throttled` is written once, by the failure that reaches a limit. `POST /me/password` with a
  wrong current password answers `403 wrong_password` (not 401, so the UI does not sign out) and
  counts toward that email's lockout.
- **Invites.** 32-byte urlsafe token, stored hashed, 72 h, single use; purpose `invite` or `reset`;
  re-issuing revokes older unused ones for that user. The URL carries the token in the fragment:
  `<base>/workspace/invite#t=<token>` (never in a path or query, so it never reaches access logs).
  `<base>` = `request.base_url` without the trailing slash (root-path aware).
- **SSO through a proxy.** `POST /api/workspace/login/sso` succeeds only when all hold: both SSO
  variables are set; `agents.core.proxy_trust.is_trusted_peer(request.client.host)`; the email header
  occurs exactly once and holds a valid email without CR/LF; header `X-Nerva-Proxy-Secret` matches
  `NERVA_WORKSPACE_SSO_SECRET` (compare_digest). The email must belong to an active user (no
  auto-provisioning). The session stores `sso_email`; a later request from a trusted peer carrying a
  different email header revokes it. A malformed `JARVIS_TRUSTED_PROXIES` (ValueError) → `sso_disabled`
  in the route, but the boot guard (`proxy_trust.assert_parseable_trusted_proxies`, run by the web
  lifespan) refuses to start the hub with such a list, so a running hub does not reach that branch.
  The secret header must also occur exactly once. Requests from untrusted peers answer
  `401 sso_no_identity` and leave no attempt or audit rows (they cannot grow the trail).
- **Authorization (server-side, every query).**

| Capability | member | approver | admin |
|---|---|---|---|
| Chat in a department | own depts | own depts | all |
| Read documents | own depts + company-wide | same | all |
| Upload documents | own depts | own depts | any dept + company-wide |
| Delete / reindex a document | own uploads (kept after a company-wide publish) | any whose `department_id` is one of theirs, whatever its visibility | all |
| Reports: view, create, run | own depts | own depts | all |
| Reports: edit / delete | own reports | any in own depts | all |
| Request an approval | yes | yes | yes |
| Decide a `department` approval | — | in own depts, never own | all, never own |
| Decide an `admin` approval | — | — | yes; an admin's own request of this rule executes immediately |
| Admin console | — | — | yes |

  Archived departments are visible to admins only. A resource outside the caller's scope answers
  `404 not_found`, never 403. A company-wide document with no department is managed by admins and its
  uploader only. Uploading into, creating a conversation in, or asking in an archived department
  answers `409 department_archived`, for admins too (admins can still read those conversations). A
  department filter naming a department that does not exist answers `404 not_found` for everyone.
  Nobody, admins included, reads another user's conversations. The last active admin cannot be
  demoted or disabled (`409 last_admin`); nobody can disable themself (`409 cannot_disable_self`).
- **Uploads.** Raw body to `POST /api/workspace/documents?department_id=<id|company>&filename=<name>`,
  streamed with an early `413 file_too_large` (extra `max_bytes`; no multipart). Allow-list `.pdf .docx
  .xlsx .csv .txt .md` → else `415 unsupported_file_type` with `reason='extension'` and `allowed`; magic
  check (`%PDF-` in the first KiB; OOXML = ZIP naming `[Content_Types].xml` and its own `word/` or `xl/`
  part; text kinds must not be binary) — a mismatch (a renamed binary, an XLSX sent as `.docx`, a PDF
  sent as `.txt`) is refused before storage with `415 … reason='content'`. OOXML is opened only through
  `agents.core.archive_safe.extract_zip_bytes` (never `import zipfile`) with
  `ArchiveLimits(max_members=2000, max_bytes=100 MiB)` inside a `TemporaryDirectory()`; XML is read
  incrementally with `defusedxml.ElementTree.iterparse(..., forbid_dtd=True)` (the same protections as
  `fromstring`, with bounded memory): more than 500 000 elements in one tree or block (one paragraph,
  table, cell or shared string — a 5 000-row Word table fits) → `too_much_text`, nesting deeper than 256
  → `invalid_file`; the shared-strings table has its own text budget; number-format codes are cut at
  Excel's 255 characters. PDF via `pypdf`, ≤ 500 pages; a PDF protected only by an owner password (it
  opens with the empty user password) is read, one that needs a password gives `encrypted_pdf`.
  Extraction runs on a **dedicated** `ThreadPoolExecutor(max_workers=2,
  thread_name_prefix='nerva-ws-extract')` through `loop.run_in_executor` — not `asyncio.to_thread`, so a
  burst of long extractions cannot starve scrypt hashing and the hub's other `to_thread` users, and
  pure-Python parsing is GIL-bound anyway — under a 60 s bound that **counts queue time**, plus a
  cooperative deadline inside the worker (a thread stops at its next page, row or sheet checkpoint; it
  cannot be killed mid-page). **Opt-in containment (NWS-11):**
  `NERVA_WORKSPACE_KILLABLE_EXTRACTION=1` (default off) moves PDF/DOCX extraction to fresh child
  interpreters, at most two per hub process across request loops. The same 60 s deadline includes
  queue and startup time; timeout or cancellation kills and reaps the child before releasing its
  slot, and removes its parent-owned temporary directory. POSIX children set `RLIMIT_AS` to at most
  512 MiB before loading the parser; Windows enforces time only, with `memory_unavailable` in the
  internal `Extracted.limits` result (`wall_time`, `address_space` on POSIX). This is resource
  containment, not a filesystem or network sandbox. Text/CSV/XLSX retain the cooperative pool.
  A child that crashes or cannot start gives `invalid_file`; a deadline gives `timeout`.
  Any extraction problem → document `failed` with a stable `error` code
  (`invalid_file`, `encrypted_pdf`, `too_many_pages`, `no_text`, `timeout`, `too_much_text` — over
  10 000 000 extracted characters; v3.2 `interrupted`, set by the scheduler's sweep, §9, for an
  extraction that died with its process). Stored as `files/<id>.bin`, moved into place inside the transaction
  that inserts the row (nobody sees a row without its file; a delete renames the file aside inside its
  transaction); the user's filename never touches the filesystem. 60 uploads / hour / user, and
  **re-indexing spends from the same budget**; at most 3 uploads in flight per user → `429 rate_limited`
  with `retry_after_seconds=5`. A late extraction result is written only while the row is still the
  `processing` claim this run made (its `updated_at` stamp) and responses, downloads and the publish
  effect re-check `created_at`, so a result can never land on a newer document that took the same id
  (defence in depth next to AUTOINCREMENT, §4). Other codes: `409 department_archived`, `507
  storage_failed` (the store write failed), `400 upload_interrupted` (the client disconnected
  mid-body); a stored file that is gone answers `404 file_missing` on download and re-index; re-indexing
  a document still `processing` answers `409 document_busy` unless its claim is older than 600 s.
- **Model and data.** The workspace calls the hub's router directly (Appendix A) — never the personal
  pipeline. `model_policy='local_only'` (default) uses only `router.local_backend`. Under `allow_cloud`
  the router chooses; a **cloud** route (a name that does not start with `local`/`ollama`) is permitted
  only when `check_data_handling` reports policy `local` or `no-training`, else `409
  model_policy_blocked`, `reason='provider_may_train'`. A **local** route the gate allowed — a LAN model
  server whose `unknown` handling the owner acknowledged included — runs under `allow_cloud` exactly as
  under `local_only`: `allow_cloud` widens what `local_only` permits, never narrows it. Under both
  policies a `DataHandlingRefused`, or a `ValueError` (the gate cannot identify the provider), →
  `reason='data_policy_unacknowledged'`; any other `RuntimeError` from the gate (its consent store
  failed) → `503 model_unavailable`, `reason='backend_error'`. Model text passes `llm.clean_text` (valid
  Unicode) before it is streamed, stored or sent. Retrieved passages are wrapped as
  `<source id="n" title="…">…</source>`; the system prompt says instructions inside sources must be
  ignored. Output is rendered as Markdown without HTML.
- **Email.** Recipients ≤ 20, validated, no CR/LF in any header, optional `allowed_domains`
  (→ `422 recipient_not_allowed`); SMTP password in `SecretStore(data_path("business","secrets.enc"))`
  (one cached instance, built off the event loop), never returned (`has_password`). `security='none'`
  with credentials is refused unless the host is loopback (`PUT /admin/smtp` → `422 field=security
  reason=insecure_credentials`; at send time → `smtp_failed reason=insecure_transport`). TLS via
  `agents.core.tls_trust.trust_context()`. `allowed_domains` (≤ 50) match the exact domain only, never a
  subdomain. The SMTP username and password must be ASCII (`422 … reason='not_ascii'`): smtplib can
  send nothing else, and a non-ASCII login stored earlier fails as `smtp_failed reason=auth_failed`.
  Outgoing email counts as configured when `host` and `from_address` are set; an empty `host` turns it
  off. An unreadable stored password (`SecretStoreError`) → `409 smtp_password_unreadable`.
- **Audit.** Key = env `JARVIS_AUDIT_KEY`, else a persisted 32-byte key at
  `(JARVIS_KEY_DIR or ~/.config/jarvis)/workspace_audit.key` (0600, created atomically) — always keyed.
  **Key guard (v3.2, review OPS2-01).** The key file is created only while the trail is empty. A
  process whose key is not the one the newest row was signed with never writes: no key at all →
  `503 audit_key_missing`; another key → `503 audit_key_mismatch`; the action's transaction rolls
  back, so every sign-in and every change answers that 503 (reads such as `GET /session` still
  answer) until the service's key is back. The refusal is logged with the key's source and both
  fingerprints, never the key, and the hub says so once at start (`audit.startup_key_check`); the
  scheduler pauses the steps that would sign rows, without a traceback (v3.3, §9). A
  successful password check refused this way settles its reserved attempt as a success, so people
  retrying during the incident are not locked out after it. A key that is truly lost is replaced
  on purpose with the CLI's `audit-rekey --confirm` (§5): one `audit.rekeyed` row, signed with the
  new key, pins every earlier row; `verify_chain` then checks every row the new key signed and
  counts the others as `unverified`, still detecting any later edit, deletion or reordering of them.
  `hash = HMAC-SHA256(key, b"nerva-ws-audit-v1" + prev_hash + canonical)`, `canonical = json.dumps({ts,
  actor_user_id, actor_email, action, target_type, target_id, department_id, ip, details},
  sort_keys=True, separators=(",",":"), ensure_ascii=False)`, first `prev_hash = "0"*64`, `key_fp` =
  first 16 hex of SHA-256(key). Details never contain passwords, tokens, prompts, answers or document
  text. Actions: `auth.setup auth.login auth.login_failed auth.throttled auth.logout auth.sso_login
  auth.invite_accepted auth.password_changed auth.reset_link_issued session.revoked user.created
  user.updated user.disabled user.enabled user.promoted user.invite_issued department.created
  department.updated department.archived department.deleted org.updated smtp.updated smtp.tested
  model.tested document.uploaded document.deleted document.reindexed document.published
  conversation.deleted chat.asked message.feedback report.created report.updated report.deleted
  report.run_started report.run_succeeded report.run_failed report.delivered approval.requested
  approval.approved approval.rejected approval.cancelled approval.expired approval.executed
  approval.failed email.sent email.failed audit.rekeyed` (CLI actions use `actor_email='cli'`, scheduler-driven ones
  `actor_email='scheduler'`). `approval.executed` / `approval.failed` carry `details.late=true` when an
  effect finished after the 10-minute sweep had already failed it — the row and the notifications then
  keep the sweep's outcome. An admin's immediate admin-rule action stores **no** decision note (stored
  notes are what people wrote, in their language); its `approval.approved` row carries `details
  {immediate: true, note: 'admin action'}`. The chain detects edits, deletions and reordering, not the
  truncation of the newest rows (there is no external anchor).
- **Headers.** All workspace JSON: `Cache-Control: no-store`. SPA shell: CSP `default-src 'self';
  script-src 'self' 'sha256-<hash of the injected bootstrap>'; style-src 'self' 'unsafe-inline'; img-src
  'self' data: blob:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none';
  frame-ancestors 'none'; form-action 'self'`. HTML report export and file downloads:
  `Content-Disposition: attachment; filename*=UTF-8''…`, `X-Content-Type-Options: nosniff`, CSP
  `default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox`. Audit CSV: any cell starting
  with `= + - @ \t \r` is prefixed with `'`.
- **Rate limits.** The hub's per-IP limiter skips `/api/workspace/*` and `/workspace*` (S6); the
  workspace enforces its own: login/setup/invites as above, 30 chat messages / min / user, 60 uploads /
  hour / user (re-index included) with 3 in flight, 10 manual report runs / hour / user → `429
  rate_limited` with `retry_after_seconds` (also sent as `Retry-After`). Chat and report counts are read
  from the append-only audit (`chat.asked`; `report.run_started` with `trigger='manual'`), so deleting
  conversations or reports never resets them.

## 7. HTTP API (`router = APIRouter(prefix="/api/workspace")`, decorators `@router.get("/…")` at column 0, double quotes)

JSON bodies are read with `http.read_json` (not pydantic). Responses use `ws_json`. Errors
`{"error","message",...}`. Query params are `Annotated[..., Query(max_length=…)]`. Length limits:
names/titles ≤ 200, slugs ≤ 64, description / assistant instructions / report instructions ≤ 4000,
notes ≤ 1000, chat content ≤ 8000, emails ≤ 254 and ≤ 20 per list, id lists ≤ 50.
Guard column: **P** public (`Enabled` + `check_public_origin` on POST), **U** `WsUser`, **A** `WsAdmin`.

**Response shapes (v3).** A list comes wrapped in a named key (`{departments:[…]}`,
`{documents:[…]}`, `{conversations:[…]}`, `{reports:[…]}`, `{runs:[…]}`, `{items:[…]}`, `{users:[…]}`);
a single resource comes back as the **bare object** — a document, a conversation, a report, a run, an
approval item, a department, the organisation, the SMTP settings — except where a row names a wrapper
(`POST /reports/{id}/run` → `{run}`, the sign-in payloads `{user, org, csrf_token}`, `GET /me` →
`{user, org, departments}`, `PATCH /me` and `PATCH /admin/users/{id}` → `{user}`). Path and query validation failures answer `422 invalid_request` with `field` and `reason`;
an unexpected exception on a workspace path answers `500 internal_error` in the same JSON shape (the
hub's generic handler defers to it there). Ids in paths are bounded `1..MAX_ID`.

**S1 — `routers/workspace_auth.py`**
| Method & path | G | Body → Response |
|---|---|---|
| GET `/session` | P | → `{enabled:true, setup_required, sso_available, authenticated, user?, org?, csrf_token?, departments?}` |
| POST `/setup` | P | `{setup_code, org_name, name, email, password, locale}` → 201 `{user, org, csrf_token}` + cookie; creates dept „General" with the admin in it; 409 `already_setup`, 403 `invalid_setup_code` |
| POST `/login` | P | `{email, password}` → `{user, org, csrf_token}` + cookie |
| POST `/login/sso` | P | — → as login; 404 `sso_disabled`, 401 `sso_no_identity`, 401 `invalid_credentials` |
| POST `/invites/lookup` | P | `{token}` → `{email, name, org_name, purpose, expires_at}`; 404 `invite_invalid` |
| POST `/invites/accept` | P | `{token, password, name?}` → `{user, org, csrf_token}` + cookie (activates an invited user; for `reset` sets the new password and revokes other sessions) |
| POST `/logout` | U | → 204, cookie cleared, session revoked |
| GET `/me` | U | → `{user, org, departments[]}` |
| PATCH `/me` | U | `{name?, locale?, theme?}` → `{user}` |
| POST `/me/password` | U | `{current_password, new_password}` → 204 (other sessions revoked); `403 wrong_password` (counts toward the lockout), `422 weak_password` |
| GET `/me/sessions` | U | → `{sessions:[{id, current, created_at, last_seen_at, ip, user_agent, via}]}` (`id` = first 12 hex of the hash) |
| DELETE `/me/sessions/{session_id}` | U | → 204; the current session answers `409 cannot_revoke_current` (use logout) |
| POST `/me/sessions/revoke-others` | U | → `{revoked}` |
| GET `/departments` | U | → departments the caller may use `{departments:[{id, slug, name, description, archived, created_at, member_count, document_count, ready_document_count}]}` (v3: wrapped like every list; `assistant_instructions` left out; v3.2 `ready_document_count` = documents with status `ready`, the ones the assistant can cite — the chat's empty state uses it, §10; also in the `departments` of `GET /session` and `GET /me`) |
| GET `/notifications` | U | `?unread=1&limit=` → `{items, unread_count}` |
| POST `/notifications/read` | U | `{ids?: [], all?: bool}` → `{unread_count}` |

**S1 — `routers/workspace_admin.py`** (all **A**)
| Method & path | Body → Response |
|---|---|
| GET `/admin/users` | → `{users:[user + department_ids + last_login_at + status + pending_invite]}` |
| POST `/admin/users` | `{email, name, role, department_ids[≥1], send_email?}` → 201 `{user, invite_url, emailed}`; `emailed` uses `mailer.send_mail` when SMTP is configured (import lazily; a mail failure — `smtp_configured` raising included — leaves the user created and answers `emailed:false, email_error`, and the router audits `email.sent` / `email.failed` itself); `409 email_taken` (field `email`) |
| PATCH `/admin/users/{user_id}` | `{name?, role?, department_ids?, status?: active|disabled}` → `{user}` |
| POST `/admin/users/{user_id}/invite` | `{send_email?}` (empty body allowed) → `{invite_url, purpose, emailed, expires_at}` (invite for `invited`, reset for `active`; `409 user_disabled` for `disabled`; enabling a disabled user without a password sets `invited`) |
| GET `/admin/departments` | → `{departments:[…]}`, all incl. archived, each with `member_count`, `document_count`, `ready_document_count` (v3.2), `report_count`, `conversation_count`; the department answered by POST and PATCH carries the same counts |
| POST `/admin/departments` | `{name, description?, assistant_instructions?}` → 201 department (slug derived, unique); `409 department_exists` (case-insensitive, Unicode-aware) |
| PATCH `/admin/departments/{department_id}` | `{name?, description?, assistant_instructions?, archived?}` |
| DELETE `/admin/departments/{department_id}` | → 204 only when it has no members, documents, reports or conversations; else 409 `department_not_empty` |
| GET `/admin/org` · PATCH `/admin/org` | `{name, default_locale, model_policy}` |
| GET `/admin/audit` | `?actor_id=&action=&since=&until=&limit≤200&before_id=` → `{items, next_before_id}` |
| GET `/admin/audit/export` | same filters → `text/csv` attachment (≤ 50 000 rows) |
| GET `/admin/audit/verify` | → `verify_chain()` (v3.2 adds `unverified` and `rekeyed_at`, §5). Without a key it answers `503 audit_key_missing`; with another key — reachable only through a session issued before the key changed, since a new sign-in is refused (§6) — it writes nothing and reports `key_mismatch` at the first row the key does not verify |
| GET `/admin/stats` | `?days=1..365` (default 30) `&tz=<IANA zone>` (v3.2, optional, ≤ 64 chars; an unknown or malformed zone → `422 invalid_request` `field=tz`, `reason=invalid`) → `{days, since, timezone, totals:{users, active_users_7d, documents, conversations, questions, reports, report_runs, approvals_pending, feedback_up, feedback_down}, per_department:[{department_id, slug, name, archived, members, documents, conversations, questions, reports, report_runs}], daily:[{date, questions, report_runs}]}`. The window is the last *days* calendar days (today included) in `timezone` — the `tz` asked for (the UI sends the browser's zone and, on a `field=tz` refusal, asks again without it), else `Europe/Bucharest` (`STATS_TIMEZONE`; `UTC`, named so in `timezone`, on a host whose zone database cannot load it); `since` is the local midnight of the first day, and each `daily` bucket runs from one local midnight to the next (a DST day is 23 or 25 h). `questions` and `report_runs` (totals, per department and daily) are counted from the append-only audit rows `chat.asked` (one per question, with its department) and `report.run_started` (one per queued manual or scheduled run), never from `messages` / `report_runs`, so deleting a conversation or a report never rewrites past usage; feedback counts the current rating of the answers still stored; the other totals are current counts |

**S2 — `routers/workspace_documents.py`** (all **U**)
| Method & path | Body → Response |
|---|---|
| GET `/documents` | `?department_id=&q=&status=` → `{documents:[{id, title, filename, mime, size_bytes, department_id, department_name, visibility, status, error, page_count, chunk_count, char_count, uploader:{id,name}, created_at, updated_at, publish_pending, can_delete, can_reindex, can_publish}]}` (no pagination; `q` searches titles and text within the caller's visible set) |
| POST `/documents` | raw body; query `department_id` (`company` = company-wide, admin only, else `403 forbidden`), `filename`, optional `title` → 201 document (extraction + indexing finished before answering; `status` ready or failed with `error`); errors `413 file_too_large {max_bytes}`, `415 unsupported_file_type {reason, allowed}`, `409 department_archived`, `429 rate_limited {retry_after_seconds}`, `507 storage_failed`, `400 upload_interrupted` (§6) |
| GET `/documents/{document_id}` | → document + `preview` (first 4 000 chars) |
| GET `/documents/{document_id}/file` | → original bytes as attachment; `404 file_missing` when the stored file is gone |
| DELETE `/documents/{document_id}` | → 204 |
| POST `/documents/{document_id}/reindex` | → document; `409 document_busy` while `processing`, `429 rate_limited` (shares the upload budget), `404 file_missing` |
Effect registered by S2: `document.company_publish` — decider `admin`; the UI sends `{document_id}`,
validate stores `{document_id, created_at}` (so a newer upload that reused the id is never published);
validate: the requester can see the document and it is `ready` and department-scoped; execute:
`visibility='company'`, notify the requester and the uploader (only the uploader for an admin's
immediate request). A document that changed since the request fails the approval with `not_found`,
`409 already_company` or `409 document_not_ready`.

**S3 — `routers/workspace_chat.py`** (all **U** unless noted)
| Method & path | Body → Response |
|---|---|
| GET `/conversations` | `?department_id=` → own conversations `{conversations:[{id, title, department_id, created_at, updated_at, message_count}]}` (the newest 500) |
| POST `/conversations` | `{department_id, title?}` → 201 bare conversation; `409 department_archived` |
| GET `/conversations/{conversation_id}` | → `{conversation, messages:[{id, conversation_id, role, content, citations, status, error_code, model, locality, latency_ms, feedback, feedback_note, created_at}], truncated}` (the newest 1 000 messages). v3.1: every citation carries `can_open` for the current reader, judged at read time with `documents.visible_ids` like a report run's (a document deleted or moved since → `false`; the excerpt stays); `can_open` is never stored. The `done` event, the JSON answer and the feedback `{message}` carry it too; the live `sources` event does not (its passages were just retrieved in the reader's scope) |
| PATCH `/conversations/{conversation_id}` | `{title}` → bare conversation |
| DELETE `/conversations/{conversation_id}` | → 204 |
| POST `/conversations/{conversation_id}/messages` | `{content}` (≤ 8 000 chars; body cap 128 KiB); `Accept: text/event-stream` → SSE (§8); otherwise JSON `201 {user_message, assistant_message, conversation}` — a failed answer answers that error's status (503/409/504/422/500) with the error body plus both stored messages; `409 conversation_busy` while a live `pending` assistant row exists; `409 department_archived`; `429 rate_limited` |
| POST `/messages/{message_id}/feedback` | `{value: 1|-1|0, note?}` → `{message}`; a user message, a pending or an errored answer → `404 not_found` |
| GET `/model` | → `llm.posture(org.model_policy)` (never fails: `available:false`, `reason:'backend_error'`, `guardrails_mode:'unknown'` on an engine fault) |
| POST `/admin/model/test` (**A**) | → `{ok, latency_ms, model, locality, route, error?, reason?, message?}` (max_tokens 64, 60 s; `THINKING_EXHAUSTED_REPLY` counts as reachable; an unforeseen fault → `ok:false, error:'internal_error'`); audited `model.tested` |

**S4 — `routers/workspace_reports.py`** (all **U**)
| Method & path | Body → Response |
|---|---|
| GET `/reports` | `?department_id=` → `{reports:[{…report, last_run:{id,status,finished_at}|null, can_edit, can_run}]}` |
| POST `/reports` | `{department_id, name, instructions, document_ids?, schedule:{kind, time?, weekday?, timezone?}, delivery_emails?}` → 201. `document_ids` must each be ready and visible in the report's department (else 404 `not_found`). Non-empty `delivery_emails` with SMTP configured creates a `report.delivery` approval (`delivery_status='pending'`); without SMTP → 409 `smtp_not_configured`; no eligible approver → 409 `no_eligible_approver`. Invalid timezone → 422 `invalid_timezone`. Answers the bare report. |
| GET `/reports/{report_id}` | → bare report + `next_run_at` |
| PATCH `/reports/{report_id}` | same fields → bare report; changing the recipients or moving the report re-opens the approval; saving recipients while delivery is `rejected` / `none` asks again; renaming alone does not |
| DELETE `/reports/{report_id}` | → 204 |
| POST `/reports/{report_id}/run` | → 202 `{run}` (queued; `create_run` → `spawn_run`); `409 run_in_progress {run_id}` while a run of this report is queued or running; `429 rate_limited`; `409 department_archived` |
| GET `/reports/{report_id}/runs` | → `{runs:[…without content]}` (the newest 100; each with `delivery_state` and `error_reason`, v3.4, below) |
| GET `/report-runs/{run_id}` | → bare run with `content_md`, `citations` (each with `can_open`: whether the reader may open its document now, `documents.visible_ids` at read time — `false` for another department's document in a company-shared run, or one deleted since), `can_share`, `share_pending` (v3.2: a `report.share_company` request for this run is `pending` or `executing`; `can_share` is then false — a second request would only answer `409 already_requested` — and the run view says the share is waiting), `can_email` (= succeeded; the UI combines it with `smtp_configured`), plus `report:{id, name, department_id}`, `report_name`, `department_id`, `department_name`; `delivered_to` is `[]` for a viewer outside the report's department (visible to the report's department; company-shared runs visible to everyone), and the rest of the delivery is hidden there too (`delivery_state` and a failed delivery's `error` / `error_code` / `error_reason` read `null`, *Run fields* below) |
| GET `/report-runs/{run_id}/export` | `?format=md|html` → attachment; HTML is a standalone, print-ready page (inline CSS, no scripts); `409 run_not_ready` for a run without a finished report |
| GET `/shared-reports` | → `{runs:[…]}`, company-shared succeeded runs visible to everyone (the newest 200), each in the run-list shape with `report:{id, name, department_id}`, `report_name`, `department_id` and **`department_name`** (the reader is mostly outside that department, so the UI cannot name it from its own department list); `delivered_to` is `[]` outside the report's department, and the delivery's state and failure read `null` there (*Run fields* below) |

**Run fields (v3.4, reviews NWS-20 / UX-23; `reports.run_json`).** Every run object above — the
run detail, each item of `/reports/{id}/runs` and of `/shared-reports` — also carries:
- `delivery_state`: `null` | `pending` | `sent` | `failed` — what the run's approved email delivery
  is doing (§9 *Delivery state*). `null` when the run has no approved delivery (`delivery_status`
  not `approved`, or no approved recipient), for a run that did not succeed, for a run stored
  before schema 2, and — like `delivered_to` — for a viewer outside the report's department.
  *Outside the department the whole delivery is hidden* (review R4-02): a company-shared run whose
  delivery failed reads `error`, `error_code` and `error_reason` `null` there as well, so a reader of
  another department learns neither that the report is mailed, nor that its email failed, nor the
  mail server's cause (a shared run is a succeeded one, whose only error is its delivery's), and the
  shared run view shows no delivery notice. Inside the department nothing is hidden.
  `pending` from the moment the run reads `succeeded` until the mail server answered (each SMTP
  step is bounded at 15 s); never `null` while a delivery is still to come. `sent`: `delivered_to`
  holds the addresses the server accepted (possibly fewer than approved). `failed`: the run stays
  `succeeded` with its `content_md`, `error='delivery_failed'` and `error_code` the mail code
  (`smtp_failed`, `smtp_not_configured`, `recipient_not_allowed`, `smtp_password_unreadable`,
  `invalid_request`, `internal_error`, or `delivery_interrupted`: the hub stopped mid-send).
- `error_reason`: `string | null`, qualifying `error_code` with the values an error body's `reason`
  carries — with `model_unavailable`: `model_unreachable`, `model_error`, `empty_answer`,
  `thinking_exhausted`, `no_local_model`, `hub_not_ready`, `no_model`, `model_not_approved`,
  `backend_error`; with `model_policy_blocked`: `data_policy_unacknowledged`, `provider_may_train`;
  with a delivery's `smtp_failed`: the mail server's cause (`auth_failed` … `insecure_transport`,
  §5 `mailer.py`). `null` for `model_timeout`, `model_busy`, `content_blocked`, `no_documents`,
  `interrupted`, `internal_error`, `timezone_unavailable` and whenever nothing more is known.
  `error_code` itself is unchanged (the stable code family), so the codes, hints, audit and
  notifications that read it keep working.

Effects registered by S4: `report.delivery` `{report_id, emails}` (decider `department`; execute
snapshots the approved list into `delivery_approved_json`, sets `approved`), `report.share_company`
`{run_id}` (decider `admin`), `email.send` `{to[], subject, body_markdown, source:{type:'message'|
'report_run', id}}` (decider `department`; validate requires the source message to be in one of the
requester's conversations, or the run to be visible to the requester; execute re-validates, then sends).
Successful runs of a report whose delivery is `approved` email the run to the approved recipients and
record `delivered_to_json` (the addresses the server accepted). **`delivery_status` transitions (v3):**
recipients set → `pending`; approved → `approved` (the approved list snapshotted); rejected, expired
or failed → `rejected`; withdrawn (cancelled, also when superseded) → `none`; recipients removed →
`none`. A succeeded run whose email delivery fails stays `succeeded`, with `error='delivery_failed'` and
`error_code` = the mail error code; the owner and the trigger user get a `report.delivery_failed`
notification whose body (v3.2) is a sentence in their language for that code (`smtp_failed`,
`smtp_not_configured`, `recipient_not_allowed`, `smtp_password_unreadable`, v3.4
`delivery_interrupted`, else a generic one), never the raw code. v3.4: the run's `delivery_state`
says where the delivery stands (`pending` → `sent` | `failed`, above and §9). A pending request a domain change withdrew is `cancelled` with `error_code` (v3.2,
`approvals.cancel_superseded`): `superseded` (the recipients changed, the report moved, a newer
delivery request replaced it), `recipients_removed`, or `report_deleted` (its pending
`report.delivery`, and the `report.share_company` / `email.send` requests about its runs); the UI
words each one. Effect failure codes: `stale_request` (`report.delivery`: the
recipients changed, or a newer delivery request replaced this one), `409 already_shared`, `409
run_not_ready`, `not_found`. `email.send` limits: subject ≤ 200, `body_markdown` ≤ 30 000 characters,
≤ 20 recipients; a source message must belong to one of the requester's conversations in a department
they can still use (else `404 not_found`); a source run must be visible to them and `succeeded` (else
`409 run_not_ready`), and a company-shared run of another department is decided by admins.

**S4 — `routers/workspace_approvals.py`** (all **U**; SMTP routes **A**)
| Method & path | Body → Response |
|---|---|
| GET `/approvals` | `?box=inbox|mine|all&status=` (`all` admin only, else `403 forbidden`; `status` filters the **effective** status — a pending request past its expiry lists as `expired`) → `{items:[{id, kind, department_id, department_name, summary, payload, status, requester:{id,name,email}, decider?, decided_at, decision_note, result, error_code, created_at, expires_at, can_decide, can_cancel}], pending_inbox_count}` |
| GET `/approvals/eligible` | `?kind=&department_id=` → `{count, immediate, smtp_configured}` (v3: eligible deciders other than the caller; `immediate` = an admin asking for an `admin`-rule kind; `smtp_configured` lets non-admin screens hide email actions); `404 not_found` for a department outside the caller's scope |
| POST `/approvals` | `{kind, payload}` → 201 bare item. Kind must be in `kinds()` (`400 unknown_kind`). An admin requesting an `admin`-rule kind executes immediately (`approved`, `decided_by` = requester, **no** decision note — the audit row carries `immediate: true, note: 'admin action'`). Otherwise no eligible decider → 409 `no_eligible_approver`; else pending, deciders notified. An identical open request (same kind and canonical payload; an immediate one still executing included) → `409 already_requested {approval_id}`. |
| GET `/approvals/{approval_id}` | → bare item + `eligible_deciders:[{id, name}]` while pending |
| POST `/approvals/{approval_id}/decide` | `{decision: approve|reject, note?}` → item. Atomic: `UPDATE … SET status='executing' … WHERE id=? AND status='pending' AND expires_at>?` (rowcount 1 or 409 `already_decided` with `current_status`); re-validate against the requester's current rights (`requester_inactive` when their account is no longer active); execute; then `approved` + `result_json` or `failed` + `error_code` (the effect's code, or `execution_failed` when an effect raised unexpectedly) in a fresh tx; requester notified; a non-decider → `403 forbidden` |
| POST `/approvals/{approval_id}/cancel` | requester only (`403 forbidden` otherwise), pending only → item |
| GET `/admin/smtp` · PUT `/admin/smtp` (**A**) | `{host, port, security: starttls|ssl|none, username, password?, from_address, from_name, allowed_domains[]}` → bare settings; GET and PUT return `has_password` and `configured`; PUT with `password: null` keeps it, `""` clears it, an empty `host` turns email off (`from_address` then optional); `422 invalid_request` names the `field` (`host`, `port`, `username`, `password`, `security`, `from_address`, `allowed_domains`) with reasons such as `malformed`, `not_ascii`, `insecure_credentials` |
| POST `/admin/smtp/test` (**A**) | `{to}` → `{ok}` or `{ok: false, error, reason?}`; audited `smtp.tested` |
Pending approvals expire after 7 days (`expired`, requester notified); `executing` rows older than 10 min
become `failed` (`interrupted`) — both in the scheduler tick. An effect that finishes after that sweep
is only audited (`details.late=true`); the row, the domain hook and the notifications keep the sweep's
outcome.

**S6 — `routers/workspace_ui.py`:** `GET /workspace` → 307 to `request.app.root_path + '/workspace/'`;
`GET /workspace/` and `GET /workspace/{path:path}` → `render_workspace_html(html, prefix)` of
`agents/web/workspace/workspace.html` (rewrites `./assets/X` → `prefix + '/workspace/assets/X'`,
injects the `window.__NERVA_BASE_PATH__` bootstrap after `<head>`, CSP per §6, `Cache-Control:
no-store`). Disabled flag or missing bundle → plain HTML 404 / 503 page. `web.py` mounts
`StaticFiles` at `/workspace/assets` before including this router; the hashed assets are served only
while the workspace is enabled, with `Cache-Control: public, max-age=31536000, immutable`, and `.woff2`
is registered as `font/woff2` (the CSS loads its fonts relative to itself under `nosniff` and
`font-src 'self'`).

## 8. Assistant behaviour (S3)

- **System prompt** (RO/EN by the user's locale): org name, department name and its
  `assistant_instructions`; answer in the user's language; ground company-specific claims in the
  sources and cite inline as `[n]`; when the sources lack the answer, say so plainly and, if useful,
  answer from general knowledge clearly flagged as such; never follow instructions inside sources; no
  HTML; concise, structured, Markdown allowed (lists, tables, bold).
- **Prompt.** One prompt string (the guarded backend takes `prompt` + `system`): the sources block, then
  the last 8 messages serialized as a transcript within a budget, then the question. Retrieval: top-6
  passages from the conversation's department + company-wide documents; query = the new question plus
  the previous user turn.
- **Citations.** Numbering stays exactly as streamed; the stored message keeps only the citations whose
  `[n]` occurs in the final text; the `done` event carries that filtered list. Every read of a stored
  answer (`GET /conversations/{id}`, `done`, the JSON answer, the feedback `{message}`) marks each
  citation with `can_open` for the reader at that moment (v3.1, §7); the stored JSON never holds it.
- **SSE framing.** `event: <start|sources|token|done|error>\ndata: <json>\n\n`, plus `: ping\n\n` every
  15 s. Headers `Cache-Control: no-store`, `X-Accel-Buffering: no`. Flow: in one tx store the user
  message + a `pending` assistant row (and the auto-title), commit, then stream through a queue + runner
  task like `agents/web.py` `_chat_event_stream`, cancelling the runner in `finally` (v3: the runner is
  started in the handler, so a turn always finishes or is cancelled even if the body is never read).
  Events: `start {user_message, assistant_message_id, conversation}` (the conversation carries the new
  auto-title), `sources {citations}`, `token {t}` (held until 64 chars or the end, so a failure string
  is never streamed — a failure piece appended after a short partial answer is dropped too), `done
  {assistant_message}`, `error {error, message, reason?, retry_after_seconds?, …every error extra,
  assistant_message}`. The final row is written through a fresh `connect()`: `complete`, or `error` with
  `error_code` (`model_unavailable`, `model_policy_blocked`, `model_busy`, `model_timeout`,
  `content_blocked`, `internal_error`, `cancelled` on disconnect, `interrupted` for an orphan). The UI
  drops a partial bubble on error and shows the translated reason.
- **Answer identity (v3).** An answer row is matched on `(id, conversation_id, created_at)`, never on
  its id alone, in the live-answer registry and in every late write and read-back (defence in depth
  next to AUTOINCREMENT, §4). A `pending` row this process is not producing (a crash or restart left
  it) never causes `conversation_busy`: the next question's transaction marks it `error` /
  `interrupted`, and the scheduler does the same after 10 minutes.
- **Failure reasons (v3.2).** A failure reply is `model_unreachable` (not `model_error`) when the
  backend noted the call as `unreachable` (`LLMResult.failure_kind`) or the reply is the local
  backend's „can't reach" string; the UI words the two reasons differently, and the posture's
  liveness probe (Appendix A) turns the model chip `Indisponibil` without waiting for the router's
  5-minute re-probe.
- **Concurrency.** `NERVA_WORKSPACE_MAX_CONCURRENT_LLM` semaphore, 30 s acquire → `503 model_busy`;
  180 s per answer → `model_timeout` (reports 300 s).
- **Title.** The first user message titles a conversation still called „Conversație nouă" / "New
  conversation" (first 60 chars, trimmed at a word boundary).

## 9. Reports behaviour (S4)

A run retrieves top-10 passages for `instructions`, restricted to `document_ids` ∩ {ready documents of
the report's department or company-wide} when set (out-of-scope ids are dropped; an empty result
fails the run with `no_documents`), else the department + company documents. It asks the model (300 s
bound) for a structured Markdown report (title, executive summary, sections, a table when the data
supports one, a "Surse" / "Sources" list), stores content and citations, notifies the owner and the
trigger user, and delivers by email when delivery is `approved`. Schedules use the report's IANA
timezone (`zoneinfo`, validated on create/edit; a tick that cannot load a zone fails the run with
`timezone_unavailable`). `next_run_at` is recomputed after each scheduled run and each schedule
change (v3 details below); due reports are claimed with compare-and-set on `next_run_at`. At most 2 runs execute concurrently; the tick marks `running` >
15 min and `queued` > 30 min as failed (`interrupted`), and (v3.4) resolves a delivery left
`pending` by a hub that stopped mid-send (*Delivery state* below). Housekeeping in the tick: pending messages > 10
min → `error interrupted`; documents left `processing` by an extraction that died — claimed over
600 s ago, or before this hub started — → `failed` / `interrupted` (v3.2, `documents.fail_interrupted`;
extraction runs inside the upload or re-index request under a 60 s bound, so such a claim has no
worker left); delete `login_attempts` > 24 h, invites expired > 7 d, sessions revoked,
expired or idle-dead > 7 d, read notifications > 90 d. The tick is a no-op while `NERVA_WORKSPACE` is
off; each step runs in its own short transactions and one failing step never stops the others.

**Delivery state (v3.4, review NWS-20).** A run whose report has an approved delivery is mailed
after it is stored, and `report_runs.delivery_state` follows that email:
- *Stored.* `_store_success` reads the approved recipients and sets `status='succeeded'`,
  `delivery_state='pending'` and `delivery_attempted` (how many recipients the email is addressed
  to; schema v3) in the same `UPDATE` (`NULL` / `NULL` when nobody is to be mailed), so no reader
  ever sees a succeeded run without a state while its email is still to come — no commit in between
  either (review R4-03: the test reads the row after every `COMMIT` of `_store_success`).
- *Sent.* `_deliver` → `mailer.send_mail` (a worker thread, 15 s per SMTP step, ≤ 20 recipients) →
  `delivery_state='sent'`, `delivered_to_json` = the addresses the server accepted,
  `report.delivered` audited (`details {report_id, to, refused}`).
- *Failed.* Whatever happens the pending delivery is resolved: a mailer `WorkspaceError` →
  `failed` with its code and `error_reason` = the mail server's reason (`failure_reason`); any
  other exception → `failed` / `internal_error` (logged with its traceback, `report run N: delivery
  crashed`); a cancellation — the hub shutting down mid-send, `cancel_runs` — → `failed` /
  `delivery_interrupted`, recorded before the cancellation propagates (if even that write fails,
  one WARNING and the restart sweep resolves it). Each failure keeps the report (`succeeded`,
  `content_md`), sets `error='delivery_failed'`, audits `email.failed` (`details {source:
  'report_delivery', report_id, error_code, recipient_count}`) and notifies the owner and the
  trigger user (`report.delivery_failed`, worded per code, §7).
- *Left pending by a stopped hub.* A process killed mid-send records nothing. The scheduler's
  `deliveries_interrupted` step (`reports.fail_stuck_deliveries`, an audited step) resolves every
  delivery still `pending` whose run was stored before this hub started (`stored_before =
  started_at`: the first tick after a restart) or 15 min ago or more (`DELIVERY_TIMEOUT_SECONDS`,
  in a live process, where a sender would have finished long before) to `failed` /
  `delivery_interrupted`: `email.failed` audited by actor `scheduler` with `recipient_count` =
  the run's `delivery_attempted` — what the delivery was addressed to, as the sender's own audit
  counts it, even when the report's recipients were removed since (review R4-07); only a delivery
  stored pending before schema 3 (no count) falls back to the report's approved list now —,
  `report.delivery_failed` notified with its own body („Raportul
  este gata, dar serverul Nerva s-a oprit în timp ce trimitea emailul, așa că nu se știe dacă
  destinatarii l-au primit. …"), and one WARNING on `nerva.workspace.reports`: `<n> report
  delivery(ies) left pending by a stopped hub marked failed (delivery_interrupted)`. It never
  claims the recipients did not get it: whether the message arrived is not known.
- *Exactly once.* The sender and the sweep settle a delivery through one compare-and-set on
  `delivery_state='pending'` (`_resolve_delivery`, in both its `sent` and its `failed` branch); an
  outcome that arrives after the delivery was resolved — a late `sent`, or a late `smtp_failed` /
  timeout after the sweep's `delivery_interrupted` — is not recorded again: no second
  `email.failed` / `report.delivered`, no second notification, `error_code` / `error_reason`
  unchanged (one WARNING, `the delivery outcome came after the delivery was resolved (…); it is not
  recorded again`).
- *Again.* A delivery that failed is not retried by the hub: the next run is mailed as usual, and
  this one can be sent with the run view's „Trimite pe email" (an `email.send` approval, §7).

**Failure reasons (v3.4, review UX-23).** A model failure stores its machine reason in
`report_runs.error_reason`, taken from the raised `WorkspaceError`'s `extra['reason']`
(`reports.failure_reason`), so a run names exactly what the chat's SSE `error` event names for the
same failure (`model_unavailable` + `model_unreachable` for a stopped model server, …; values in
§7 *Run fields*). `error_code` stays the stable code family; the `report.run_failed` audit row adds
`details.reason` when there is one. Delivery failures store the mail server's reason the same way.

**Under a wrong audit key (v3.3, review OPS2-08).** Each tick first asks `audit.key_check(conn)`
(`WorkspaceScheduler._key_gate`). While the answer is not `ok`, the steps that sign audit rows
(`AUDITED_STEPS`: `runs_started`, `approvals_expired`, `approvals_interrupted`, `runs_interrupted`,
and since v3.4 `deliveries_interrupted`) are skipped and listed in the summary's `paused`: no report
is claimed, no approval expires or fails, no run or delivery is failed, nothing is written for
them. `messages_interrupted`,
`documents_interrupted` and the housekeeping deletes sign nothing and keep running. The pause is
logged only when the key's state changes, on `nerva.workspace.scheduler`: one WARNING when it
starts or its state changes — `workspace scheduler paused: <reason>, so scheduled reports, approval
expiry and the failing of stuck runs and approvals wait — nothing is changed or written for them
until the service's JARVIS_AUDIT_KEY / JARVIS_KEY_DIR are back; check with: <CHECK_COMMAND>`, the
reason worded for `mismatch`, `missing` and `unreadable` — and one INFO when the key matches again
(`workspace scheduler resumed: …`; a restarted process starts in the `ok` state, so after a restart
with the right key there is no resume line). A step that still raises `audit.AuditKeyError` (the
key changed between the check and the step) is caught before the generic handler: no traceback,
the step is listed in `paused`, and the remaining audited steps of that tick are skipped. The first tick after the key is back catches up: a due report
runs once (its `next_run_at` is recomputed from that tick), overdue approvals expire, stuck runs
and approvals fail. A database the check cannot read (`sqlite3.Error`) is treated as `ok`, so the
steps meet and log that error themselves.

**Fixed during the build (v3).** A run is written in the report owner's locale (else the org default).
When the instructions match nothing in scope, the opening passages of the documents in scope are used
(up to 50 documents); `no_documents` means the scope holds no ready document. A manual run is refused
while any run of the report is queued or running (`409 run_in_progress`) and does not recompute
`next_run_at`. An edit that leaves the schedule unchanged keeps a due, not-yet-claimed `next_run_at`
(a save in the 30 s before the tick must not skip a run); a changed schedule always recomputes. A tick
that cannot load a zone fails that run with `timezone_unavailable` and retries in 24 h. Delivery
follows the `delivery_status` transitions in §7. Report runs wait up to 30 s for one of the shared
`NERVA_WORKSPACE_MAX_CONCURRENT_LLM` model slots, then fail honestly with `model_busy`. On hub shutdown
`scheduler.stop_background()` cancels in-flight runs, which end `failed` / `interrupted` (v3.4: a run
already `succeeded` and sending its email stays `succeeded`; its delivery ends `failed` /
`delivery_interrupted`) — only the runs and the scheduler task of the loop that is shutting down (v3.1, loop-aware, §5): a second
lifespan in the same process on another loop never cancels the first one's.

## 10. Frontend (S5)

- **Stack.** React 19 + TypeScript, no new runtime dependency. Entry `frontend/workspace.html`; config
  `vite.workspace.config.ts`: `base: './'`, `publicDir: false`, `build.outDir: '../agents/web/workspace'`,
  `emptyOutDir: true`, `rollupOptions.input: 'workspace.html'`. `package.json`: `"build": "vite build &&
  vite build -c vite.workspace.config.ts"`, plus `build:workspace` and `dev:workspace`. Path routing
  under `/workspace/…` through a tiny router using `base-path.ts` (`appUrl`, `logicalPath`).
- **API calls (parity gate).** Every request URL is written in full, on one line, as a literal
  containing `/api/workspace/…`, e.g. ``appUrl(`/api/workspace/documents/${id}/file`)``. Never build
  workspace URLs from a base constant; never name a route in a comment unless the code calls it.
- **Invite page.** Reads the token from `location.hash` (`#t=…`), calls `POST /api/workspace/invites/lookup`,
  then clears the fragment with `history.replaceState`.
- **Design.** Clean light theme by default plus dark and system; tokens in `workspace.css` (`--ws-*`).
  Accent signal blue tuned to WCAG AA on both themes; neutral slate grays; 8 px grid; 10 px radii;
  system-UI body font; Space Grotesk for headings/brand, JetBrains Mono for numbers/timestamps — check
  the vendored woff2 files cover ă â î ș ț (U+0103 U+00E2 U+00EE U+0219 U+021B); if not, vendor the
  latin-ext slices next to them or limit Space Grotesk to the wordmark. Sidebar layout ≥ 1024 px,
  drawer below; usable at 360 px.
- **Screens.** Login · First-run setup · Accept invite / reset password · Assistant (conversation list +
  streaming chat, citation chips opening a source drawer, copy, feedback, „Trimite pe email" → approval
  dialog, suggested prompts per department, model chip Local/Cloud/Indisponibil) · Documents
  (drag-and-drop multi-upload with progress, list with status, search, preview drawer, download,
  delete, „Publică în toată compania" request) · Reports (list, create/edit form with schedule builder
  and recipients, run now with live status, run history, run view with rendered Markdown + citations,
  export MD/HTML, print, share-company request, email request) · Shared reports · Approvals (inbox / my
  requests, detail, approve/reject with note, cancel) · Notifications menu · Profile (name, language,
  theme, password, active sessions) · Admin: Users (invite, copy link, edit role/departments,
  disable/enable, reset link), Departments (CRUD + assistant instructions), Organisation (name,
  default language, model policy + live model status + test), Email (SMTP + test), Audit (filters,
  table, CSV export, chain verification), Usage (KPIs + daily chart in SVG).
- **Behaviour fixed during the build (v3.1).**
  - *Source drawer.* The drawer behind a citation chip shows the document title, page and the
    exact excerpt, plus „Deschide documentul" (its preview in Documents) and „Descarcă
    originalul". v3.2: the excerpt is rendered through `CitedMarkdown` (the shared safe renderer,
    no HTML, headings one level below the drawer's h2) after `pages/shared/excerpt.ts`
    `excerptMarkdown()` has put back the line breaks a table extracted from DOCX/XLSX/CSV lost when
    the excerpt was stored with collapsed whitespace — it adds line breaks only and never changes a
    word; text that is not a table is left alone. When the citation says `can_open: false` (a
    report run shared company-wide that cites another department's document, or any answer or run
    whose document was deleted or moved since) it keeps the excerpt, hides both links (they could only answer `404`) and says why in the
    words of its context: in the assistant `source.notOpenableAnswer`, in a run view
    `source.notOpenable` (RO/EN). A citation without the flag (the live `sources` event) is openable.
  - *Shared reports.* The list's department column reads the run's `department_name` from the
    server; the reader's own department list is only a fallback.
  - *Theme and language.* The profile controls and the account menu apply a new theme or language
    at once (optimistically, into the signed-in user, so the controls themselves update), save it
    with `PATCH /me`, apply only the latest save's answer, and on failure revert to the previous
    value with a translated toast.
- **Behaviour added in the first assessment round (v3.2).**
  - *Document preview.* The document drawer renders its `preview` through `CitedMarkdown` too (the
    extractor writes tables, sheets and headings as Markdown).
  - *Unsent drafts.* The assistant composer (key `composer.<conversation id>`, or
    `composer.new.<department id>`) and the report form (`report.<id>` / `report.new`) mirror
    their text into `sessionStorage` (this tab only) under `nerva.workspace.draft.<user id>.<key>`,
    so a session ended under the user (a 401 after a revocation or an expiry) does not lose it: the
    same user's page restores it after signing in again. A draft is dropped when it is sent or
    saved, when the form is cancelled, and — every user's — on a deliberate sign-out; blocked
    storage just keeps no draft. v3.3 (round 2, F3): `app/drafts.ts` `useRestoredDraft` (read
    once, when the form mounts; `draftText` / `draftIds` check the restored values) and
    `useDraftMirror` give every other form the same behaviour, under these keys: the email
    request `email.<source type>.<source id>`, the admin's invite dialog `invite.new` (departments
    deleted since are dropped), the edit-user dialog `user.<id>`, the department drawer
    `department.<id>` or `department.new`, the organisation form `org`, the SMTP form `smtp` —
    every field except the password, which is never written to storage. These forms keep a draft
    only while they differ from the values they were prefilled with (an unchanged form keeps
    none), and after a send, a save or a cancel (Cancel, Escape or the close button) nothing is
    written again until the value changes. A restored dialog says so (`draft.restored`;
    `draft.restoredSend` for the email request); the two page forms (organisation, SMTP) say so
    (`draft.restoredPage` / `draft.restoredSmtp`, which adds that the password is never kept) with
    a „Renunță la modificări" (`draft.discard`) action that puts the saved values back. The
    composer and the report form keep the v3.2 rule: they mirror what is typed (a new report with
    nothing typed keeps no draft).
  - *„Primii pași" (getting started).* At the top of Admin → Users a card lists five steps, each
    checked from real data: email configured, a department besides General, a colleague invited,
    a `ready` document (`ready_document_count`), the newest `model.tested` audit row with
    `details.ok`. Each open step links to where it is done (the invite step opens the invite
    dialog); the card disappears once every step is done and can be hidden earlier (per admin, in
    this browser's `localStorage`).
  - *No citable documents.* The chat's empty state warns when the department has no `ready`
    document — worded differently when it has documents that all failed or are still processing —
    and links to Documents.
  - *Tables on small screens.* Below 768 px every `ui/Table` row becomes a stacked card: the first
    column is the card's title, the other cells follow with their column name, the actions column
    sits in the card's corner. From 768 px a wide table scrolls inside its own frame (focusable and
    labelled only while it really overflows) with the actions column sticky.
  - *Run view.* The h1 is the report's name; the report's own `# Title` renders one level down,
    inside the article. While `share_pending` is true the view says the share request is waiting
    and offers no second request.
  - *Approvals.* The approval drawer says why a request was withdrawn: its `error_code`
    (`superseded`, `recipients_removed`, `report_deleted`, §7) has its own sentence, a code without
    one reads as a generic withdrawal, and a request with no code was cancelled by its requester.
  - *Usage.* The admin usage page sends the browser's time zone as `tz` and names the zone the
    days were counted in.
- **Behaviour added in the second assessment round and the polish pass (v3.3).**
  - *Where an answer was made, in words (UX-13).* `pages/shared/LocalityChip.tsx` shows a
    locality in the model popover's words — `locality.local` „Pe serverul companiei",
    `locality.cloud` „La un furnizor cloud aprobat", `locality.unknown` „Locație neconfirmată"
    (EN: On the company's server / With an approved cloud provider / Location unconfirmed) —
    never the raw code. Model ids are technical and shown to admins only: in the chat meta (the
    chip, plus the mono model id for admins), in the run view (a row „Unde a fost generat",
    `run.field.where`, for everyone; the „Model" row for admins), in the run history (the column
    is headed „Unde a fost generat" for non-admins and „Model" with the id for admins); the
    shared-reports list shows the chip alone (column `run.field.where`).
  - *Audit drawer (UX-13).* `detailValue` first looks a coded detail up as
    `audit.value.<key>[<code>]` (the login-failure and cancellation reasons, `via`, the throttle
    and session scopes, invite purposes, credential changes, visibility, the
    `report_delivery` source, feedback values, the `admin action` note…), so it reads as words;
    roles, account statuses and the model policy in a `from` / `to` pair read as their labels,
    labelled „Înainte" / „După" (a lone `to` stays a recipient list); an email source reads as
    „Mesajul #12"; the `scheduler` actor reads „Planificatorul automat". The raw action code
    stays in the drawer's last row („Codul tehnic al acțiunii"), for support.
  - *Approval preview (UX-20).* The preview's heading follows the status
    (`ApprovalDrawer.previewHeading`): `pending` „Ce se întâmplă la aprobare"; `approved`,
    `executing`, `failed` „Acțiunea cerută"; `rejected`, `cancelled`, `expired`
    „Ce s-ar fi întâmplat la aprobare". The email preview's „Către" row is plain comma-separated
    text, like the other rows of its grid.
  - *Citation chips (A11Y-15).* `CitedMarkdown`'s tree walk marks a chip that starts its block
    (a table cell, a list item, a paragraph — no text before it) as `ws-cite--lead`, a 24 × 24 px
    target (min-width 24px, height 24px); a chip inside running text keeps the compact inline
    size (WCAG 2.5.8's inline exception).
  - *Audit verification after a re-key (OPS2-01 follow-up).* `AuditVerifyResult` reads the
    optional `unverified` and `rekeyed_at`; an intact chain with `unverified > 0` adds the
    plural-correct sentence `audit.verify.unverified` („… intrări de dinaintea schimbării cheii
    de audit (intrarea #N) au fost semnate cu cheia pierdută și nu mai pot fi verificate; o
    modificare ulterioară a lor tot s-ar observa.") to the notice and the status region;
    `audit.rekeyed` has its action label; `error.audit_key_mismatch` is translated next to
    `error.audit_key_missing`, and the `key_mismatch` notice points the server's administrator
    to the `check` command and the old key.
  - *Definition lists.* `.ws-dl`'s label column is `fit-content(45%)` and badges inside a `dd`
    wrap. (v3.3 let `.ws-locality` grow in height so its words could wrap at 320 px; v3.4, UX-22,
    replaced that: the chip never wraps, below.)
  - *Run view export on phones (UX-21, polish pass).* The export group sits in `.ws-export` with
    a caption „Exportă" (`run.exportGroup`; EN „Export") that names the segmented group through
    `aria-labelledby`. From 480 px nothing changes: the caption is hidden and the buttons read
    „Exportă Markdown | Exportă HTML | Tipărește". Below 480 px the caption shows above the
    group, the buttons read „Markdown | HTML | Tipărește" (`run.export.mdShort` /
    `run.export.htmlShort`, aria-hidden) and the full words stay their accessible names (kept
    screen-reader-only), so none of the three equal buttons wraps its label onto a second line.
- **Behaviour added in the third assessment round (v3.4).**
  - *The email outcome on the live run page (NWS-20; closes the v3.3 known gap).*
    `pages/reports/schedule.ts` `isDeliveryPending(run)` = `status === 'succeeded' &&
    delivery_state === 'pending'`. `RunView` tracks a phase — `active` (queued / running),
    `delivering`, `settled` — and polls `GET /report-runs/{id}` every 2 s (`RUN_POLL_MS`) while it
    is `active` or `delivering`; it stops once the run and its email are settled, and when the page
    is left. While delivering, the report is readable and an accent notice says
    „Raportul se trimite pe email…" (`run.delivery.sendingTitle`) with a spinner and
    `run.delivery.sendingNote` („… Pagina arată rezultatul trimiterii imediat ce serverul de email
    răspunde."). The outcome then appears without a reload: the meta row „Trimis pe email către
    <list>", or the warning notice. The one always-mounted status region (`role="status"`) says
    each change once: `run.live.sending` „Raportul este gata și se trimite pe email…", then
    `run.live.sent` „Raportul a fost trimis pe email către X." | `run.live.deliveryFailed`
    „Emailul cu raportul nu a fost trimis: <motiv>" | `run.live.deliveryUnknown` „Nu se știe dacă
    emailul cu raportul a ajuns: <motiv>"; a run that fails live says `run.live.failed`
    „Raportul nu a putut fi generat: <motiv>". A page opened on a run that has already settled
    announces nothing (its notice is the page). A `delivery_interrupted` delivery has its own title
    `run.delivery.interruptedTitle` („Raportul este gata, dar nu se știe dacă emailul a ajuns"),
    body `error.delivery_interrupted` („Serverul Nerva s-a oprit în timp ce trimitea emailul; nu se
    știe dacă destinatarii l-au primit.") and hint `run.delivery.interruptedHint` (check with the
    recipients or send it again with „Trimite pe email"); it never says the recipients did not get
    it. The reason of any other failed delivery depends on the role: admins read the mail server's
    own cause (`describeCode(code, error_reason)` → `error.smtp_failed.<reason>`, e.g. „Serverul
    de email nu a putut fi contactat. Verifică adresa și portul.") with
    `run.delivery.failedHintAdmin`; members read the plain `error.smtp_failed` sentence with
    `run.delivery.failedHint` („… Anunță un administrator …"), since the per-reason copy carries
    admin-only instructions. The report page's history (`ReportDetail`) also polls (4 s) while any
    run is active or its delivery pending, and flags a run „Se trimite pe email"
    (`run.history.deliverySending`), „Email netrimis" (`run.history.deliveryFailed`) or „Email
    neconfirmat" (`run.history.deliveryUnknown`, `delivery_interrupted`); its re-read of the
    report's last / next run still follows active runs only.
  - *A run or report deleted while its page follows it (review R4-01).* `useAsync` keeps the last
    copy it read when a reload fails, so a 404 is read as "gone": `RunView` drops its copy as soon
    as `GET /report-runs/{id}` answers `not_found` (the report was deleted, or the reader lost
    access, mid-run or mid-send) — the polling stops, the „se trimite pe email…" / „se scrie"
    notice goes, the not-found state (`error.not_found`, back to the reports list) shows, and the
    status region says `error.not_found` once. `ReportDetail` does the same when its report or its
    history answers `not_found` (no more 4 s polls, the not-found state instead of the stale page).
    Any other failed read (a `503`, the network) keeps the last copy and the polling, so a transient
    outage still ends on the real outcome.
  - *A failed run in the chat's words (UX-23).* The run's failure notice reads
    `describeCode(i18n, error_code, error_reason)` — `error.<code>` plus `model.reason.<reason>`,
    the chat's own sentence („Modelul AI nu este disponibil acum. Serverul modelului nu poate fi
    contactat (este oprit sau conexiunea s-a întrerupt).") — and, for the model codes
    (`model_unavailable`, `model_policy_blocked`, `model_busy`, `model_timeout`), the chat's next
    step through `app/errors.ts` `hintKey(i18n, 'chat.hint', code, reason)` (per code and reason,
    then per code; extracted from `MessageItem`'s private `hintFor`, so both screens use one
    lookup). Admins also get `chat.hint.admin.<code>[.<reason>]` and the „Setările modelului" link
    for `ADMIN_FIXABLE_CODES` (`model_unavailable`, `model_policy_blocked`, shared with the chat).
    No raw code is shown.
  - *The model chip recovers with the first answer.* `ChatPane` re-reads `GET /model` when an
    answer arrives while the posture says unavailable, and `RunView` does when a run it watched
    fails with a model code or succeeds while the chip says unavailable, so the chip and the
    composer's notice follow the model server at once instead of at the next 30 s poll
    (`POSTURE_POLL_MS`).
  - *Locality chips never wrap (UX-22).* `.ws-locality` is `white-space: nowrap`; its inner
    `.ws-locality__text` ends in an ellipsis only as a last resort. `LocalityChip`'s `short` form
    shows `locality.short.*` („Local" / „Cloud" / „Neconfirmat"; aria-hidden) with the full words
    as its accessible name (a visually hidden span) and its `title` tooltip; the run history and
    the shared-reports table use it, and a table stacked into cards below 768 px shows the full
    words again. In the run's details card the „Unde a fost generat" pair takes a row of its own
    where the card is narrow (the side column from 1100 px, and phones below 480 px). The report
    page's run history has four columns — „Început" (the date, with the trigger under it), „Stare"
    (status, the delivery badge and „Partajat în companie"), „Durată", „Unde a fost generat" /
    „Model" — so it fits a 1024 px screen without scrolling sideways. A long source pill in the
    run's side card ends in an ellipsis inside the card (`.ws-sources__list > li { min-width: 0 }`).
- **Quality bar.** Every async action has loading, success and error states; empty states teach the next
  step; destructive actions confirm; forms validate inline and map server `error` codes to translated
  messages; dialogs and drawers trap and return focus; everything keyboard reachable with visible focus;
  landmarks and labels; `aria-live` for streaming and toasts; no layout shift; no English in Romanian mode
  and vice versa (typed i18n dictionary, `ro` default + `en`, identical keys); Markdown rendered with the
  shared safe renderer `frontend/src/markdown.tsx` (no `dangerouslySetInnerHTML` on model or document
  text). When guardrails run in REDACT/BLOCK mode (`posture.guardrails_mode`), the chat says answers
  arrive in one piece.
- **Tests.** vitest + Testing Library: API client (CSRF header, error mapping, SSE parser incl. pings and
  split chunks), router, i18n completeness, and each screen's main flow with a mocked fetch.

## 11. Repo gates the integration must keep green

`ruff check .` (E,F,W,I,B,UP,SIM,C4 — use `Annotated`, `X | None`, `contextlib.suppress`, `raise … from`);
bandit (no new finding: no bare except-pass, no string-built SQL — use `json_each(?)` — no string
literals assigned to `*password*/*token*/*secret*` names); semgrep `p/python` + `p/security-audit`
(defusedxml only, no sha1/md5, no log lines naming password/token/secret with args); every text
`read_text/write_text/open` passes `encoding="utf-8"`; never the literal `safe_mode`; never
`import zipfile/tarfile` in `agents/`; routers never hand-roll an orchestrator-is-None 503 (raise
`WorkspaceError`); full `pytest tests/` with xdist; `tests/test_route_auth_matrix.py` (tiers `ws_user`/
`ws_admin` read before the hub tiers; public workspace routes in `INTENTIONALLY_OPEN` /
`INTENTIONALLY_OPEN_READS` with reasons; snapshot regenerated); `python tests/test_route_parity_guard.py
--update`; `tests/test_hud_v2_parity.py` (RULES `('/api/workspace','workspace')`, `('/workspace',
'workspace')`); `scripts/gen_api_sweep.py` + `tests/test_api_sweep_current.py` taught the new tiers, then
`python scripts/gen_api_sweep.py`; `npm run typegen:openapi` with the API on port 8765; `python
scripts/status_sync.py` after adding tests; frontend `npx tsc --noEmit`, `npm run typecheck:e2e`,
`npm test`, `npm run build` (both bundles committed; CI checks both); `./scripts/lock_deps.sh --check`
and `pip-audit -r requirements-beta.lock`; `frontend/playwright.config.ts` ignores `workspace*.spec.ts`.
The `ci.yml` and `e2e.yml` changes made the PR control-plane (owner merged); since the owner directive of 2026-10-26 such PRs merge unattended too (`selfdev-policy.json` → `merge.protected_merge_directive`).

## 12. Quality rubric (pilot must score ≥ 9 on each)

| Dimension | 9/10 means |
|---|---|
| Functional completeness | Every visible control works end to end in the real app; the Playwright journey covers each screen's primary action. |
| Security & isolation | Auth, CSRF, throttling, scoping and audit behave per §6; a member cannot reach another department's data through any API; no secret or content in logs or audit. |
| Correctness & robustness | Errors are handled and explained; model or SMTP outages degrade honestly; no unhandled exception in server logs during the journey. |
| UX & visual polish | Consistent, calm, professional; clear hierarchy; responsive; loading/empty/error states everywhere; Romanian copy natural and complete. |
| Accessibility | axe: zero serious/critical; full keyboard operation; visible focus; contrast AA. |
| Operability | The pilot guide gets a stranger from zero to a working install; backup, upgrade, security posture and limits documented. |
| Test depth | Backend, frontend and e2e tests prove the claims above, including negative and isolation paths. |

## 13. Docs delivered with the build (S6)

`docs/business/PILOT_GUIDE.md` (RO: install, model options incl. loopback rule and the data-handling
acknowledgment, enable flag, setup code, a dedicated hostname behind Caddy proxying only `/workspace*`
and `/api/workspace/*`, TLS, HSTS, `JARVIS_TRUSTED_PROXIES=127.0.0.1`, `JARVIS_ALLOWED_HOSTS`,
`NERVA_WORKSPACE_COOKIE_SECURE=1`, empty `JARVIS_CORS_ORIGINS`, SSO header + secret, users and
departments, SMTP, `JARVIS_BACKUP_KEY` + `JARVIS_SECRET_KEY`, backup/restore, upgrade, CLI recovery,
limits, troubleshooting), `deploy/workspace/Caddyfile.example`, `docs/FLAGS.md` rows for §3,
`docs/ARCHITECTURE.md` module index entry, `CLAUDE.md` B2B routing line (cites the directive and this
file), `mobile/PARITY.md` row („Nerva Workspace: web only, no native surface — intentional"), a
`BACKLOG.md` section for the pilot with delivered rows, and the kickoff decision record.
**Delivered (v3):** [`PILOT_GUIDE.md`](PILOT_GUIDE.md),
[`deploy/workspace/Caddyfile.example`](../../deploy/workspace/Caddyfile.example) (plus a commented
oauth2-proxy variant that injects the email header and `X-Nerva-Proxy-Secret`; both pass `caddy
validate`), the `docs/FLAGS.md` rows, the `docs/ARCHITECTURE.md` module index, the `CLAUDE.md` routing
line, the `BACKLOG.md` section „Nerva Workspace — pilot B2B (2026-10-17)” and the kickoff note.
**E2E lane (v3.1):** `frontend/playwright.workspace.config.ts` runs
`frontend/e2e/workspace-journey.spec.ts` (`npm run e2e:workspace` in `frontend/`; ports
`WS_E2E_MODEL_PORT` / `WS_E2E_SMTP_PORT` / `WS_E2E_HUB_PORT`, default 18491–18493; a run directory
from `WS_E2E_RUN_DIR`, else a fresh temporary one), and `.github/workflows/e2e.yml` runs it after the
HUD lane with `E2E_PYTHON=python`, uploading `frontend/e2e/.results/workspace-screens/` on failure.
**v3.3:** `WS_E2E_RESULTS_DIR` (optional) moves a run's traces (`<dir>/workspace`) and its
screenshots and axe reports (`<dir>/workspace-screens`) out of the shared `frontend/e2e/.results/`;
unset, nothing changes. The SMTP web server is `frontend/e2e/support/workspace_smtp.py --port
<WS_E2E_SMTP_PORT> --out <run>/mail.jsonl --run-dir <run>`: the same `SmtpSink` class as
`tests/support/smtp_sink.py`, with an off switch — while `<run>/smtp.down` exists the sink stops
listening and the port refuses connections (the hub's SMTP settings are left alone), when the file
is removed it listens again on the same port, `<run>/smtp.state` holds `up` or `down`, and a stale
`smtp.down` from an interrupted run is removed at start. The spec helper `setSmtpSink('up' |
'down')` (`frontend/e2e/support/workspace-helpers.ts`) flips it and waits until the state file and
a real SMTP probe agree. That pass brought the journey to 28 serial steps; its two new ones stop the sink:
an approved `email.send` that cannot reach the mail server ends `failed` / `smtp_failed`, nothing
sent, explained in Romanian to the approver and the requester (axe page `approval-failed`); an
approved report delivery that cannot reach it leaves the run `succeeded` with
`error='delivery_failed'`, the run view's warning and the history badge „Email netrimis" (axe page
`run-view-delivery-failed`), and with the sink back the next run is delivered — the lane's first
end-to-end coverage of scheduled-report delivery. Every `checkPage` also fails a segmented-group
button whose visible label wraps onto more than one line, at 1280, 390 and 320 px. During an SMTP
outage each failed send is one WARNING line on `nerva.workspace.mailer` (`sending email via
<host>:<port> failed (connection_failed, ConnectionRefusedError)`), never a traceback, so the
journey's final hub-log check stays strict.
**v3.4:** the journey has **31 serial steps**. The model web server is now
`frontend/e2e/support/workspace_model.py --port <WS_E2E_MODEL_PORT> --token-delay 0.02 --run-dir
<run>` (same `/health` URL and `READY` line): `tests/support/fake_openai_server.py`'s
`FakeOpenAIServer`, unchanged, with an off switch like the sink's — while `<run>/model.down` exists
the port refuses connections and open ones are dropped, removing it listens again on the same
port, `<run>/model.state` holds `up` / `down`, a stale `model.down` is removed at start; the
helper `setModelServer('up' | 'down')` waits for the state file and an HTTP probe.
`tests/support/smtp_sink.py`'s `SmtpSink` gained `greeting_delay` (seconds before every `220`,
a plain attribute; CLI `--greeting-delay SECONDS`), `greeting_gate` (a `threading.Event` each new
connection waits on, at most `GATE_TIMEOUT` = 30 s), `connections` and
`wait_for_connections(n, timeout)`. `workspace_smtp.py` maps `<run>/smtp.hold` onto that gate
(present → every new connection's greeting is held; removed → released) and writes
`<run>/smtp.hold.state` as `held <n>` / `released <n>` (*n* = connections accepted so far);
helpers `holdSmtpGreeting(held)` and `waitForSmtpConnection(seen)`. `checkPage` adds a layout-only
pass at 1024×768 and fails a locality chip whose visible text spans more than one line or is cut
short with an ellipsis; `tableScrollsSideways(page, caption)` measures a table frame's own
sideways overflow. The three new steps: **24** — while a run's email is still on its way (the
greeting held, the hub connected) the API reads `succeeded` / `delivery_state: 'pending'`, the
page shows „Raportul se trimite pe email…" and its status line, and once the greeting is released
the same page (a window marker proves no reload) shows „Trimis pe email către …", the API reads
`sent`, and the mail reaches the sink (NWS-20); **25** — the report page's run history, with
shared, failed-email and sent rows, does not scroll sideways at 1024, 1100, 800 and 1280 px
(screenshot `report-detail-history-1024x768.png`, axe page `report-detail-history`), and the run
view's chip is one line with its source pills inside their card at 1100 and 1180 px (UX-22);
**27** — with the model server stopped the chat says „Răspunsul nu a putut fi generat" with the
`model_unreachable` sentence and the chat's hint, the top bar reads „Modelul AI: Indisponibil",
the stored answer is `error` / `model_unavailable` (axe page `assistant-model-down`), a report
run fails live with the same sentence, hint and „Rulează din nou" and reads `failed` /
`model_unavailable` / `error_reason: 'model_unreachable'` / `delivery_state: null` (axe page
`run-view-model-down`); started again, the next question answers on the same page and the chip
returns to „Local" (T-GAP-2). The existing delivery step also pins `error_reason:
'connection_failed'`, `delivery_state` `failed` / `sent` and the live notices. The final hub-log
step still allows only the simulated model 500 as an error, and now also requires the outage to
have been noticed as a warning: a stopped model server logs `WARNING jarvis.llm.base LM Studio
unreachable — serving a degraded reply: All connection attempts failed`, never an ERROR or a
traceback.

---

## Appendix A — verified facts builders must know (from the code review, HEAD 2f9311e)

**Orchestrator and model**
- `agents.core.app_state.get_orch()` → `web.orch` or `None` (late `sys.modules` read). The router is
  `orch.llm_router` (HybridRouter); the guardrails policy is `orch.security` (`GuardrailsEngine`, or
  `None` before `load_agents()`).
- `router.select_backend(agent_id, prompt) -> (backend, model, route)`; raises `RuntimeError('No LLM
  backend available')`, `LocalBackendUnavailableError` (RuntimeError subclass), `ModelNotApprovedError`
  (PermissionError) or `job_selection.SelectionError`. `preview_backend` is the read-only twin.
  `router.local_backend` is the strict-local accessor (RuntimeError when none). `router.get_model(
  'workspace')` returns the local model name. Agent id `workspace` is POLICY_AUTO: local while the prompt
  is ≤ 8000 tokens, else Gemini `cloud-flash`/`cloud-pro`; `llm.cloud_fallback='always'` goes cloud
  first. Do not add ids to `LOCAL_ONLY_AGENTS` (protected kernel parity).
- Route names — local: `local`, `local-deep`, `local-fallback`, `ollama-howard`, `local-ollama`; cloud:
  `claude`, `cloud`, `cloud-flash`, `cloud-pro`, `cloud-fallback`, `cloud-compatible`. Test locality with
  `route.startswith(("local","ollama"))`, never `startswith("cloud")`.
- **`llm.complete` algorithm.** (1) orch/router from `get_orch()`; none → `LLMUnavailable(reason=
  'hub_not_ready')`. (2) `local_only`: `backend = router.local_backend` (RuntimeError →
  `LLMUnavailable(reason='no_local_model')`), `model = router.get_model('workspace')`, `route='local'`;
  never `select_backend`. `allow_cloud`: `select_backend('workspace', prompt)`. (3) `dh =
  router.check_data_handling(backend, model, route)`; `DataHandlingRefused` →
  `ModelPolicyBlocked(reason='data_policy_unacknowledged')`; under `allow_cloud` a **cloud** route whose
  policy is not in {`local`,`no-training`} → `ModelPolicyBlocked(reason='provider_may_train')` (v3: a
  local route the gate allowed runs under both policies). (4) `locality = 'local'
  if dh['policy']=='local' else ('unknown' if route.startswith(('local','ollama')) else 'cloud')`.
  (5) `guarded = agents.core.security.bind_guardrails(orch.security, backend)`. (6) Inside
  `with agents.core.llm.data_handling.physical_request_scope(lambda: router.check_data_handling(backend,
  model)):` await `guarded.generate_stream(model=…, prompt=…, system=…, max_tokens=…, temperature=…,
  on_token=<async def>)` under `agents.core.web_helpers.bounded(…, seconds=timeout)`; catch
  `DataHandlingRefused` at scope exit; `SecurityBlockError` (`agents.core.security.guardrails`) →
  `WorkspaceError('content_blocked', status=422)`; `RuntimeError`, `LocalBackendUnavailableError`,
  `ModelNotApprovedError`, `SelectionError` → `LLMUnavailable`; `BackendTimeout` → `ModelTimeout`.
  (7) Failure detection: `agents.core.llm.base.is_backend_failure_reply(text)` or `text.strip()==''` →
  `LLMUnavailable(reason='model_error'|'empty_answer')`; never `is_degraded_reply`. A failure reply the
  backend noted as `unreachable` (`provider_failure_scope`), or the „can't reach the local …” reply, is
  `reason='model_unreachable'` instead. (8) Hold tokens
  until 64 chars or end; forward nothing when the buffer is a failure reply.
- `posture()`: `router.local_backend` (local_only) or `router.preview_backend('workspace','x')`
  (allow_cloud), plus `check_data_handling(..., actual_use=False)` inside try (it still raises
  `DataHandlingRefused`); add `reason` and `guardrails_mode` (`orch.security.stats()['mode']`). Reasons:
  `hub_not_ready`, `no_local_model`, `data_policy_unacknowledged`, `provider_may_train` (v3, also
  `no_model`, `model_not_approved`, `backend_error`). The router re-probes local servers only every
  5 min, so for a local route the posture also GETs the server itself (`/v1/models` or `/api/tags`,
  2 s, cached 30 s; every real call refreshes the cache) and answers `available:false`,
  `reason='model_unreachable'` when it does not answer.
- `check_data_handling` → `{provider, policy ('local'|'no-training'|'unknown'|'trains-on-inputs'), note,
  scope, warning, acknowledged, last_used}`. Workspace calls are unattended (no bound principal), so any
  warning raises `DataHandlingRefused`. A loopback lm-studio/ollama endpoint is `local`; a non-loopback
  one is `unknown` (refused until the owner acknowledges via `POST /api/security/data-handling/ack`).
  Gemini and openai-compatible are `unknown`; Anthropic and openai-responses are `no-training`.
- `bind_guardrails(policy, backend)` returns a bound `GuardrailsEngine` or the backend.
  `generate(model, prompt, system='', max_tokens=1024, temperature=0.7) -> str`;
  `generate_stream(..., on_token=None) -> str`. In REDACT/BLOCK modes `on_token` fires once with the full
  text; BLOCK raises `SecurityBlockError`.
- `on_token` must be an `async def` (or bound async method) or a plain sync function — `base._emit` uses
  `inspect.iscoroutinefunction`, so a lambda returning a coroutine is silently dropped.
- Backends never raise on failure: they return (and stream) strings such as „⚠️ I can't reach the local
  LM Studio model…", `THINKING_EXHAUSTED_REPLY` or „[Gemini error…". The admin model test uses
  `max_tokens >= 64` and counts `THINKING_EXHAUSTED_REPLY` as reachable.
- A local OpenAI-compatible server is the `lm-studio` backend: `JARVIS_LM_STUDIO_URL=http://127.0.0.1:PORT`
  (no `/v1`). Probe `GET /v1/models` → `{"data":[{"id":"m"}]}`; `POST /v1/chat/completions`, streaming
  `data: {"choices":[{"delta":{"content":"x"},"finish_reason":null}]}` … `data: [DONE]`, non-streaming
  `{"choices":[{"message":{"content":"…"},"finish_reason":"stop"}]}`. For e2e also set
  `JARVIS_OLLAMA_URL` to a closed port and `JARVIS_LLM_WARMUP=0`. `agents.core.web_helpers.bounded(coro,
  what=…, seconds=…)` raises `BackendTimeout`.

**HTTP, cookies, proxies**
- Root path: `request.app.root_path == request.scope['root_path']` (e.g. `/nerva`); inside routes
  `request.url.path` includes it; outer `@app.middleware` code sees the logical path; `request.base_url`
  is `https://host/nerva/`. Redirects must prefix root_path; cookie Path = `root_path + '/api/workspace'`.
- `X-Forwarded-Proto` is applied by `_ForwardedProtoMiddleware` only from `JARVIS_TRUSTED_PROXIES`
  peers; minimal test apps lack it → use `TestClient(app, base_url='https://testserver')` to test
  Secure (httpx drops Secure cookies over http, so keep `auto` in http tests).
  `TestClient(app, client=('127.0.0.1', 50000))` + `monkeypatch.setenv('JARVIS_TRUSTED_PROXIES',
  '127.0.0.1')` tests SSO; the default client host `testclient` is never trusted.
- `client_ip(request)`: `peer = request.client.host if request.client else ''`; only if one of
  `x-forwarded-for`, `x-real-ip`, `forwarded` is present AND `proxy_trust.is_trusted_peer(peer)` →
  `proxy_trust.forwarded_client(peer, xff=…, x_real_ip=…) or peer`; catch ValueError.
- FastAPI 0.142.4 / Starlette 1.7.0: yield-dependency teardown runs AFTER a StreamingResponse finishes;
  `async for chunk in request.stream()` with an early 413 works; python-multipart is NOT installed;
  TestClient buffers — use `client.stream('POST', …)` for SSE tests.
- Hub app: handlers `JarvisError`→400, `SecurityBlockError`→403, `Exception`→500 (hub-shaped); no
  `RequestValidationError` handler (default `{"detail":[...]}`); `_NO_STORE_PATHS` is exact-match; CSP
  applied with `setdefault` (a route may set its own); `_host_guard` refuses non-IP hosts not in
  `JARVIS_ALLOWED_HOSTS`; the rate limit (`JARVIS_RATE_LIMIT`, 120/min) applies to requests without hub
  tokens. SSE reference: `agents/web.py` `_chat_event_stream` and `/chat/stream`. The HUD service worker
  ignores `/workspace`.

**Libraries and storage**
- Not installed: python-multipart, pypdf (S2 adds it), openpyxl, python-docx, aiosmtplib, markdown,
  bleach, sse_starlette, tzdata on Linux (S2 adds it unconditionally). Installed: defusedxml 0.7.1,
  cryptography 50.0.2. Install with `uv pip install --python /home/user/jarvis-hub/.venv/bin/python …`.
- Lockfiles: `./scripts/lock_deps.sh` re-resolves from scratch and bumps unrelated pins — do NOT use it
  to regenerate. Instead copy the existing lock to a temp file and run `uv pip compile <req.txt>
  --generate-hashes --universal --python-version 3.12 --no-header -o <temp copy>` (pins are kept), then
  prepend the 3-line header with `# source-sha256: <sha256 of the .txt>` and verify with
  `./scripts/lock_deps.sh --check`.
- SMTP: stdlib `smtplib` inside `asyncio.to_thread`, `timeout=15`; TLS context
  `agents.core.tls_trust.trust_context()` for `SMTP_SSL` and `starttls(context=…)`.
- `SecretStore(path)` (`agents/core/secrets.py`): `set(name, value)`, `get(name, default=None)` (raises
  `SecretStoreError` on a wrong key → show „parola nu poate fi citită, reintroduceți"), `delete(name)`,
  `names()`. Without `JARVIS_SECRET_KEY` it creates `<path>.key` (0600). A passphrase key costs ~230 ms
  per construction: cache one instance per path and build it off the event loop. Always pass
  `data_path('business','secrets.enc')` (the default store path is frozen at import).
- env_config: `truthy`, `is_recognized_bool`, `env_flag(name, default)`, `env_str` (no strip),
  `env_int(name, default, minimum=None)` (no max), `env_float`, `env_list`. `boot_guards` refuses only
  `NERVA_PUBLIC_PROFILE`, `JARVIS_CHANNEL_PAIRING`, `JARVIS_CHANNEL_OPEN` when malformed.
- SQLite 3.45.1: FTS5 `unicode61 remove_diacritics 2` folds ă/â/î/ș/ț; external-content table + ai/ad/au
  triggers + `ON DELETE CASCADE` keep the index clean; raw user text in `MATCH` raises
  `OperationalError` ('e-Factura') → build MATCH from `re.findall(r'[^\W_]+', fold(q))` (v3; `fold` =
  casefold + NFKD with combining marks removed: underscore is a separator for the FTS tokenizer, and
  folding before the stopword and stem steps makes `si`/`și` and `sedinta`/`ședința` behave alike), drop
  RO/EN stopwords and tokens < 2 chars, ≤ 16 tokens, each `"<stem>"*` with `stem = tok if len ≤ 4 else
  tok[:max(4, len-2)]`, joined by ` OR `, ranked by `bm25(chunks_fts)`, scope via
  `IN (SELECT value FROM json_each(?))`, `OperationalError` → `[]`.
- scrypt n=2**15 r=8 p=1 needs `maxmem=64*1024*1024` (fails at the 32 MiB default), ~260 ms here; n=2**10
  ~4 ms.
- `agents.core.archive_safe.extract_zip_bytes(data: bytes, dest: Path, *, limits=ArchiveLimits(
  max_members, max_bytes)) -> list[tuple[str, ...]]`; raises `ArchiveRejected`; `dest` must not exist yet
  (use a subdirectory of a TemporaryDirectory).

**Repo gates**
- Ruff selects E,F,W,I,B,UP,SIM,C4 (line length 100, E501 ignored). Bandit (`agents/`, `scripts/`)
  blocks NEW findings: B110/B112, B105, B608 (repo convention: whitelisted fragment + `# nosec B608`;
  prefer `json_each(?)`), B310, B311. Semgrep p/python + p/security-audit `--error` on `agents/`.
- `test_windows_text_encoding`: every text I/O passes `encoding="utf-8"`. `test_h275_safe_mode`: the
  literal `safe_mode` never appears in workspace code or comments. `test_archive_safe`: no
  `zipfile`/`tarfile` import in `agents/`. `test_require_component_sweep`: no hand-rolled
  orchestrator-None 503 in routers.
- Route-auth matrix: tiers come from dependency `__name__`s in the resolved dependant graph; hub names
  are `_user_guard`/`user_guard`/`_admin_guard`/`admin_guard` — never reuse them; `ws_admin_guard`
  depends on `ws_user_guard`, so check admin first. `gen_api_sweep.py` and `test_api_sweep_current.py`
  hard-code the three hub tiers and must learn `ws_user`/`ws_admin`.
- HUD parity callers: `frontend/src/**/*.ts(x)` excluding `*.test.*`, `/test/` and `schema.gen.ts`; for a
  path with params the stem must appear with each static segment within 60 chars on ONE line; mentions in
  comments count as calls. `_routes()` reads the APIRouter prefix only when it is a literal assigned to
  the name `router`.
- Pytest config: `--timeout=30` per test, `--allow-hosts=127.0.0.1,::1,localhost` (fake servers bind
  127.0.0.1), `asyncio_mode=auto`, xdist with a per-worker `JARVIS_HOME`, `JARVIS_RATE_LIMIT=0`,
  `JARVIS_TESTING=1`; conftest's autouse fixture imports `agents.web` in every test; `from
  tests.support.x import …` resolves.
- Frontend: Vite 8.3.2, vitest 5.0.3, TS 7.0.2, React 19.3. `npm test` = `vitest run` with projects
  [`vite.config.ts` (include `src/**/*.test.{ts,tsx}`, jsdom, setup `src/test/setup.ts`),
  `vitest.native.config.ts`] → `src/workspace` tests are picked up; tsconfig include `['src']`, strict
  false. Reuse `frontend/src/markdown.tsx` (`Markdown`, `renderInline`, `safeHref`) and
  `frontend/src/base-path.ts`. Fonts: `frontend/src/assets/fonts/space-grotesk-latin-var.woff2`,
  `jetbrains-mono-latin-var.woff2` (latin subset — check Romanian glyphs).
- Backup archives every regular file under the data root; `data_purge` removes everything except
  `KEEP_FILES`/`KEEP_DIRS` (S6 adds `business`, the workspace's directory since v3.1); one hub per data root (hub lock), so one in-process
  scheduler is safe.
- (v3.2) `paths.data_root()` is `JARVIS_HOME` / `JARVIS_MEMORY_DIR`, else `<user home>/memory` when
  a user home is active (`JARVIS_USER_HOME`, or a frozen build's default), else
  `<checkout>/memory_logs` — the last fallback, inside `paths.app_root()`, is what the CLI
  preflight refuses (a shell without the service's environment would create a second, empty
  workspace there). The backup CLI (`nerva-run -m agents.core.backup`, not workspace code; v3.3,
  `BACKLOG.md` NWS-18; v3.4, review OPS3-01: `backup.PROG = "nerva-run -m agents.core.backup"` is
  the name its usage lines and `--help` print, and the description says to run it with the
  service's environment — PILOT_GUIDE §2, `nerva-run` — never from a bare shell, which would use
  another data root and another backup key): `verify` / `restore` take the file name `list` shows or a path to an
  archive directly inside `<data root>/backups/` — absolute (the `"archive"` value `create`
  prints), relative to the working directory, or with `..` (`backup.resolve_backup_arg`).
  Symlinks and `..` are resolved first and the archive's real location must be the backups
  directory's real location (a symlinked `backups/` is followed): a copy elsewhere, a path that
  leaves the directory, an entry that links to a file elsewhere, or a name whose entry links
  to another archive of the directory (plain or encrypted is read from the entry's name;
  review REV-POLISH-05 — a path to such a link resolves to the archive it links to) names
  no backup, and the
  answer is always an entry of the directory listing. The admin route keeps `resolve_backup`
  (names only). Exit codes: 0 done; 1 the command ran and failed; 2 the argument names no backup.
  Every failure is one line on stdout, never a traceback: ``no such backup: <arg> — verify and
  restore take a file name from `list`, or a path to an archive inside <dir> (copy one from
  elsewhere there first)`` (2); `cannot decrypt <name>: <source> is not the key the archive was
  made with, or the archive is damaged; nothing was checked` (verify) / `…; nothing was restored`
  (restore) for a `SecretStoreError` (1), where `<source>` names the key actually tried, resolved
  as `SecretStore` resolves it (review REV-POLISH-04): `JARVIS_BACKUP_KEY in this environment`
  (a passphrase adds `(a passphrase, with the salt <key dir>/backup.cipher.salt)`), else
  `JARVIS_SECRET_KEY in this environment (JARVIS_BACKUP_KEY is not set: run with the service's
  environment: nerva-run, PILOT_GUIDE §2)`, else `the key file <key dir>/backup.cipher.key
  (JARVIS_BACKUP_KEY is not set: …)`. A read never mints key material: when that key file, or a
  passphrase's salt, does not exist, `verify` / `restore` create nothing and raise
  `backup.BackupKeyMissing` (a `SecretStoreError`) before the key directory is touched — `cannot
  decrypt <name>: JARVIS_BACKUP_KEY is not set (…) and there is no key file <path> — no key was
  made; nothing was checked`, or `… is a passphrase and its salt <path> does not exist (the key
  directory is kept off-site, PILOT_GUIDE §14) — no key was made; …` (1); `target <dir> is not empty,
  nothing restored — restore into a new, empty directory (--force overwrites, but never restore
  over the data directory in use)` (1); `no such backup: <name> (it is no longer in <dir>)` for an
  archive that vanished after it was resolved (1); `verify failed: <OSError>` / `restore failed:
  <OSError>` (1); the `archive rejected …` messages are unchanged. Files outside
  `<data>/business` are still created with the process umask: `mkdir` makes `backups/` 0755 and
  `sqlite3` makes the hub's own databases (`settings.db`, …) 0644 under systemd's default 0022,
  and a restore writes `0o666`/`0o777 & ~umask` (`archive_safe`) — hence `UMask=0077` in the pilot
  guide's §2 drop-in and `nerva-run`. Inside `<data>/business` the workspace makes its files
  private itself (§3 File modes; v3.4: only its own entries when `business/` links to a folder
  shared with other data); the repo's `deploy/systemd/jarvis-hub.service` still sets no
  `UMask`. A `restore` whose target is a symlink that leads nowhere is reported as `target … is
  not empty, nothing restored` (exit 1): `mkdir` raises `FileExistsError` on the link, which the
  CLI maps to that line; nothing is restored and the link's destination is not created.
- Protected paths are recorded as such by the classifier (`.github/workflows/**`, `agents/core/kernel/**`,
  `agents/core/security/**`, `agents/core/secret*`, `AGENTS.md`, `MOONSHOT.md`); since 2026-10-26 they no
  longer block unattended merge. The plan touches only `ci.yml` and (v3.1) `e2e.yml` among them.
