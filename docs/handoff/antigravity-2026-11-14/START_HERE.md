# Nerva/Jarvis — handover Antigravity, 2026-11-14

Mandat: continuă dezvoltarea până la un produs complet și construiește avantaje demonstrabile față de Hermes/OpenClaw. Ownerul autorizează transferul întregii surse, implementarea autonomă, commits, push și draft PR-uri. **Fără merge sau deploy.** Reguli istorice despre local-only, modele, resurse și ceremonie pot fi înlocuite cu justificare datată; securitatea, datele, testele oneste și limitele platformei rămân obligatorii. Folosește [promptul de continuare](PROMPT.md).

## Sursa de pornire

Branchul `codex/antigravity-handoff-20261114` conține sursa cumulativă V70 și acest handover, peste baza `686fcbf4f25ebfbb416b3a35dff29045163cffbd`. Numărul noului draft PR nu este fixat aici. Verifică exact commitul primit și manifestele; documentul nu certifică transferul înaintea verificării.

```sh
git clone --branch codex/antigravity-handoff-20261114 --single-branch https://github.com/andrei649/jarvis-hub.git
cd jarvis-hub
git status --short
git rev-parse HEAD
git fetch origin refs/pull/1363/head:refs/remotes/origin/integration-v81
git rev-parse refs/remotes/origin/integration-v81
```

Compară SHA-ul V81 primit cu cel fixat mai jos; dacă a avansat, inspectează diferența înaintea integrării.

Sursa V70 este păstrată, **nu reconciliată cu V81**. La checkpointul V70, checkout-ul originar avea 439 căi dirty și zero staged; delta completă față de main `1338833d5a344d277c43828a9d9314e10af792f1` avea 463 căi. „Necomis/nepublicat” din dovezile vechi descrie acel moment, nu starea acestui branch.

Draftul existent #1363 rămâne separat, la head `702845ae45765583f996fdb5b2b08de9db6664bc`, tree `9deba0f24220f9f0f89fee585f2a923e549cecc1`. Reprezintă reconcilierea PR-urilor #1359–#1363 și corecțiile V81, nu întregul cumulativ V70. Nu îl suprascrie și nu aplica patchuri cumulative suprapuse peste el. [Comparația V70/V81](manifests/v70-v81-comparison.json) documentează diferențele; recuperează corecțiile mai noi într-un worktree izolat, păstrând funcțiile cumulative.

## Funcții implementate cumulativ

Cronologia exhaustivă, regresiile și rezultatele intermediare sunt în [CHECKPOINT V70](evidence/v70/CHECKPOINT.md). Rezumatul descrie implementări, nu acceptare live sau contracte complete:

- **V1–V10:** output literal al scripturilor programate, inclusiv `[SILENT]`; ingress slash Slack și comenzi Discord cu identitate/pairing; media și captionare WebP; discovery skills/plugins și meniuri native; sanitizare metadate/streaming; `/egress`, `/diff` working/staged/all/stat și checkpoint aproximativ; lifecycle platformă; update semnat/Kernel și singleton; reload MCP explicit cu confirmare expirabilă și revalidare după awaits.
- **V11–V20:** claims durabile pentru delivery keys, receipts și refuzul replay-urilor incerte; admission/drain și restart guvernat, ownership de workeri/subagenți, proveniența textului original Telegram; fraze private limitate de restart; `/update status`, filtre literale `/diff`, ACK Telegram strict și help adresabil în grupuri.
- **V21–V40:** observație `command.started` fără corp sau autoritate; metadate extension-command legate de consent; callbacks bounded queued+running; retry SQLite numai BUSY/LOCKED; discovery owner HUD/mobile și receipts opt-in; fencing pentru fallback după carduri incerte; ownership/claims între profile și procese, teardown SDK reținut, notificări redacted, circuit breakers/probe exclusive, Retry-After, ownership IMAP/ntfy, audit și deadline-uri de conectare.
- **V41–V51:** erori provider sanitizate inclusiv multiline/cancellation; plugin loadset prefilter; refresh Telegram postreload coalesced; doctor/CLI precis; readiness Discord; views desktop/mobile read-only; grant revision durabil, revoke/regrant și late-result fencing; restaurare lazy a rutelor de extensie la startup fără executarea codului candidat la boot.
- **V52–V58:** restore legat prin digest de snapshot privat; recovery desktop numai pentru exact session-missing; diagnostic first-party imports; rollback și stash replay pe baseline exact; ownership preflight POSIX venv; unlocked explicit și smoke `ok is True`.
- **V59–V69:** recuperare mobile cu prompt nestrimis păstrat; căutare în metadatele încărcate; paginare keyset owner web/mobile; preview și export JSON retained-only/redacted; save mobile fără overwrite; filtre agent/datǎ; CLI transcript, rename/pin/archive și history paginat cu limite și stdout atomic.
- **V70:** integrare cumulativă și regenerare documentație API, fără funcție runtime nouă.
- **V71–V81, lane separat:** reconcilierea celor cinci drafturi păstrează selectoare gateway, dispatch CLI organization/history/transcript, JSON flags și schema API aditivă. Corecțiile includ `[SILENT]` prin wrapper, estimare Unicode conservatoare, fixtures DNS/PDF concurente și OCR Windows, roadmap corect. V81 publică pe #1363. Detaliile loturilor V71–V79 sunt în INVENTORY-REVIEW.md.

## Dovezi și limite

[V70 NEXT](evidence/v70/NEXT.md) consemnează backend complet Linux **36.570 passed/108 skipped**, zero failures/errors, 36.678 total; mobile fresh420; typechecks/builds și 27 assets reproduse. Frontend3.178 reutilizează V66 corelat prin hashuri, nu este un run nou V70.

V80 consemnează backend complet **34.904 passed/108 skipped**, zero failures/errors, pe commit `1104c921e776d9562e26117111c3cf3b085ff4c9`; frontend fresh3.009/mobile396. Import sorting ulterior în fixture OCR are dovadă separată. V81 are693 teste focalizate și typegen real, nu o nouă suită completă. Consultă [dovezile V81](evidence/v81/) pentru SHA și receipts; nu aduna suite suprapuse sau transfera verdictul între snapshoturi.

La ultima observație V81, toate joburile CI terminate erau verzi, Linux Chrome trecut, Windows backend încă pending. Citește rezultatul curent pe head-ul exact; pending/cancelled nu este pass.

Inventar cumulativ înregistrat: **171 equivalent/482 partial/8 missing/36 excluded=697**; V81: **170/483/8/36=697**. Sunt stări înregistrate distincte, **nu o reevaluare proaspătă** făcută de acest handover. Vezi [analiza inventarului](INVENTORY-REVIEW.md). Excluded rămân în obiectiv; passing area suites nu închide partial.

Acceptarea reală pe dispozitive/providers și Windows/Mac nu este certificată universal. Windows ACL și unele scripturi de instalare rămân gaps. Arhiva completă a conversațiilor cere occurrence/branch/coverage; nu uni loguri vechi ca transcript complet. [Propunerea tar](proposals/tar-inspection/) este neintegrată; nu aplica patchuri vechi orbește. Reviewul update/restart blocat de platformă rămâne incomplet, fără retry ocolitor. Un diagnostic Chrome nesigur a fost exclus.

## Primii pași executabili

1. Verifică commitul, [manifestul cumulativ](manifests/cumulative-source.json) și [verificatorul sursei](verify_source.py), citindu-i CLI înaintea rulării. Protejează checkout-ul dirty și reconciliază V70/V81 izolat.
2. Verifică CI exact; repară cauze confirmate și rulează integrarea combinată, typegen pinned, Chrome și Windows în mediile suportate. Păstrează drafturile fără merge/deploy.
3. Cu Pythonul proiectului rulează preflight și query-uri țintite: `scripts/development_preflight.py --frontend --smoke --json`, `scripts/hermes_status.py summary --json`, `scripts/backlog.py open`, `scripts/ledger.py stats`. Smoke sintetic nu dovedește provider live.
4. Închide loturi utilizabile: instalare/recovery cross-platform, gateway/extensions, sesiuni/arhivă cu proveniență, interfețe coerente. Continuă loturi independente când lipsește un prerechizit extern.
5. Demonstrează avantajele prin scenarii reproductibile de task success, recovery, latență, cost și erori; numărul de teste nu dovedește superioritatea produsului.

Convenții: [AGENTS](../../../AGENTS.md), [mandatul istoric](../../hermes/autonomous-development-objective.md), [raportul cumulativ](../../hermes/CAMPAIGN_HANDOFF.md). Mandatul actual al ownerului de mai sus prevalează asupra restricțiilor de proces istorice.

Manifestul sursei acoperă 7.294 fișiere prezente; cifra istorică 7.302 include și 8 căi șterse. Overlay-ul acestui handover modifică doar AGENTS.md și adaugă documentele/evidențele de aici. `python docs/handoff/antigravity-2026-11-14/verify_source.py` verifică octeții ambelor seturi; nu execută codul aplicației.
