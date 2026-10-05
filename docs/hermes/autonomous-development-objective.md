# Mandat de dezvoltare autonomă Nerva

Decizia ownerului: 2026-10-05. Acest mandat înlocuiește metoda de execuție
anterioară în această conversație. Scopul final rămâne paritatea funcțională cu
cele 697 de capabilități din referința Hermes fixată, inclusiv H277 și capabilitățile
excluse anterior. Obiectivul persistent al aplicației a fost actualizat de owner în 2026-10-05.

## Text pentru obiectivul activ

Dezvoltă autonom Nerva/Jarvis până la paritate funcțională cu cele 697 de
capabilități Hermes din inventarul fixat. Optimizează pentru funcționalități
integrate și utilizabile, cu verificare proporțională riscului și consum minim
de resurse. Reutilizează codul existent și portează direct implementările și
testele Hermes; adaptează numai diferențele necesare arhitecturii Nerva.
Lucrează în loturi coerente care închid capabilități complete, rezolvă autonom
defectele și păstrează toate modificările existente. Folosește cel mult doi
implementeri Sol High când există muncă independentă; pentru sarcini mici
lucrează direct. Nu face stage, commit, push, merge, deploy sau activări cu
costuri. Continuă până la finalizarea scopului, cu checkpointuri clare și
dovezi verificabile; nu echivala volumul de cod, teste sau documentație cu
progresul funcțional.

## Reguli de execuție

1. **Închide lucrul început.** Înaintea unei funcționalități noi, finalizează
   integrarea și defectele lotului curent. Alege lotul următor după valoarea
   pentru utilizator, dependențe și efortul până la o livrare completă.
   Nu extinde un rând mare pentru îmbunătățiri opționale în timp ce contractul
   acceptat sau integrarea sa de bază rămâne deschisă.
2. **Plan scurt, apoi cod.** Pentru fiecare lot consemnează numai cerințele,
   sursa Hermes, diferențele necesare, fișierele deținute și probele de acceptare.
   Nu reaudita întregul repo la fiecare pas. Caută țintit și refolosește contextul
   verificat, grafurile locale și handoverul existent.
3. **Portare înainte de reinventare.** Compară întâi implementarea donorului cu
   ce există în Nerva. Copiază/adaptează modulele și testele relevante, păstrând
   licența. Folosește serviciile, aprobările, kernelul și interfețele existente;
   introduce o abstracție nouă numai pentru o incompatibilitate demonstrată.
4. **Agenți numai când economisesc muncă.** Cel mult doi Sol High, fără agenți
   copii, cu fișiere distincte și un contract clar. Nu folosi agenți pentru
   explorări duplicate, rapoarte sau revizuiri succesive ale aceleiași schimbări.
   Coordonatorul integrează și verifică, fără să refacă implementarea agentului.
5. **Testare proporțională.** Reproduce defectele și verifică comportamentul
   schimbat cu teste focalizate. Rulează o dată regresiile modulelor afectate
   după integrarea lotului. Repetă numai probele afectate de o corecție.
   Suitele complete și campaniile de mutații sunt pentru milestoneuri de
   integrare și schimbări ale contractelor comune; nu pentru fiecare fișier,
   actualizare de document sau hash. Niciun efect privilegiat nu ocolește
   aprobarea ori kernelul pentru a obține un test verde.
6. **Fiabilitate fără extinderea continuă a scopului.** Criteriile de acceptare
   provin din rândul Hermes și adaptarea Nerva necesară. Nu adăuga cerințe
   opționale în mijlocul lotului. După două încercări fără progres asupra
   aceleiași erori, verifică explicit cauza și contractul înaintea altei
   modificări; nu porni din nou aceeași explorare sau suită generală.
7. **Progres și dovezi separate.** Raportează capabilitățile acceptate,
   cele parțiale, lipsurile și prospețimea verificării separat. Un hash schimbat
   cere o analiză de impact; singur nu dovedește o regresie și nu trebuie
   prezentat ca funcționalitate pierdută. Retrage acceptarea când o cerință
   este încălcată demonstrabil sau verdictul anterior era nejustificat.
   Nu declara echivalare pentru scaffolding, verdict moștenit neverificat ori
   implementare cu lipsuri. Migrarea registrului existent necesită o schimbare
   explicită, testată; nu modifica procentele manual.
8. **Checkpoint și handover.** La cel mult 60 de minute consemnează rezultatul
   concret, probele, defectul rămas și următorul pas. În chat raportează scurt
   descoperirile importante și nu lăsa lucrul activ fără actualizare peste
   60 de secunde. Păstrează un singur raport cumulativ pentru lot, nu dosare
   noi pentru fiecare rulare. Consumul necunoscut nu se estimează inventat.

## Criteriul de acceptare al unei capabilități

Contractul complet este implementat; funcția este accesibilă prin intrarea
reală a produsului; comportamentul normal și erorile relevante sunt verificate;
aprobările și izolarea necesare sunt păstrate; nu există regresii cunoscute
introduse de lot. Dovezile locale, simulate, pe servicii reale și din CI sunt
etichetate distinct. Dacă lipsesc conturi sau runtime-uri externe, consemnează
exact ce nu poate fi demonstrat, fără a inventa validare live.

Finalizarea proiectului cere verificarea tuturor celor 697 de contracte;
încheierea unui lot sau epuizarea timpului nu înseamnă finalizarea obiectivului.

## Punct de reluare

Checkout: `/Users/andrei649/Projects/nerva-pr-worktrees/consent`.
HEAD: `a7ffad6676cfb28e7ac374d495b4a5889e5f4646`. Lucrul rămâne local,
necomis; modificările anterioare trebuie păstrate.

- Lotul început: H034, H256, H078; CLI și brokerul H034 sunt legate la hub,
  iar H078 trece prin aprobarea semnată, worker și execuție fizică.
- Lotul H034/H256/H078 este acceptat pe contractele fixate. Registrul are
  128/697 echivalente (18,4%): 20 reevaluate curent, 108 moștenite.
- Regresia istorică din lotul inițial 615/1 eșec este corectată. Lotul final
  207 și impactul separat 248 au zero eșecuri/erori/skipuri; nu aduna probele.
- H515/H595/H660 rămân parțiale; H067 este următorul lot început de închis.
- Nu există o nouă dovadă de suită completă ori mutații H277 pentru această
  stare finală; nici H277, nici cele 697 nu sunt declarate terminate.
- Agenții sunt opriți/completați; continuarea este directă, locală.
- Dovezi: `docs/hermes/evidence/2026-10-05-direct-ports/`; loguri externe
  `/tmp/nerva-direct-ports-affected-20261005.log` și
  `/tmp/nerva-direct-ports-ledger-impact-20261005.log`.

Prima livrare încheiată: defectul de terminal corectat, trei contracte acceptate
și registru actualizat. Continuă H067, apoi verifică milestoneul integrat. Nu relua implementările sau campaniile istorice de la zero.

Checkpoint de continuare: H067 are confirmări native Slack/Discord, owner explicit
și paired, întrebări în lot portate din Hermes, TTL durabil și ștergere de mesaje
confirmate, reluare de runtime/rute și fallback Other corectate. 1277 cazuri de
integrare și 197 probe finale de transport trec, fără eșec/eroare/skip; probele
se suprapun. Registrul păstrează128/697, H067 parțial. Următorul pas: referință
de conținut legată prin digest pentru prompturile mari, apoi producători pending
pe celelalte intrări și milestoneul integrat. Totul rămâne local/necomis.

Checkpoint următor: prompturile mari H067 folosesc acum conținut efemer legat
prin digest și dimensiune de taskul semnat, fără relaxarea limitelor globale.
Preview-ul admin/HUD afișează textul și opțiunile complete înaintea aprobării.
15 probe noi includ ToolRPC și SDK Slack/Discord reale cu date sintetice;
247 probe afectate,191 probe de impact și163 teste HUD trec; numerele se
suprapun. HUD construit, Ruff/Bandit/scan strict trec, Graft explicit actual.
Registrul:128/697 echivalente,229 parțiale,56 lipsă,284 de reverificat. H067
rămâne parțial pentru alte intrări typed/producers. Următorul pas este să
închidă aceste intrări folosind același broker, apoi milestoneul integrat;
nu reia campaniile istorice. Dovezi cumulative în
`docs/hermes/evidence/2026-10-05-pending-input-completion/content/`.

Checkpoint ntfy: producer typed prin același broker semnat, cititor separat cu
coadă limitată și confirmări reset/undo integrate. Răspunsurile proprii nu mai
blochează modelul; consentul Always este legat de server și topic.126 probe
finale și16 probe settings trec. Scanarea strictă raportează o declarație
GA4 cu valoare goală, moștenită și verificată AST; nu a fost suprimată. Graful
surselor este actual. H067 rămâne parțial; următorul pas: anularea explicită
a clarificării din ingress ocupat, apoi ceilalți producers. Fără publicare.

Checkpoint anulare H067: /cancel și !cancel eliberează doar întrebarea livrată
curentă înaintea lane-ului ocupat, fără tur nou de model sau debit de rată.261
probe afectate trec (6 noi), scanarea celor2 fișiere schimbate și Bandit trec;
graful surselor este actual. Registrul rămâne128/697 echivalente (18,4%),
H067 parțial. Progresul este funcțional în H067, nu o capabilitate nouă completă.
Următorul pas: integrarea /chat/stream autenticat și HUD, apoi email/CLI și
mesajele prose/comenzile rămase la ingress ocupat. Folosește fluxul real
_chat_event_stream și _web_principal; WebChannel.clients nu dovedește identitatea
ownerului. Modificările rămân locale, fără stage/commit/push/merge/deploy.

Checkpoint HUD streaming H067 (2026-10-05): /chat/stream livrează acum întrebarea
ToolRPC în HUD, iar endpointul user-guarded /chat/pending/{prompt_id}/answer reia
același model. Opțiuni, multiselect, Other/free text, Cancel și retry sunt
integrate în App. Tokenul/rolul valid, sesiunea și promptul exact rămân legate;
metadatele obișnuite de canal nu pot crea acest producer HTTP. Ack-ul SSE precede
creditul uman; expirarea, revocarea și deconectarea retrag întrebarea.344 probe
afectate backend,60 HUD,54 garduri API și211 verificări finale de metadata/HUD
construit trec (suprapuneri). Typecheck, build, Ruff, Bandit, scan strict9 fișiere
și Graft explicit actual. Registrul rămâne128/697 (18,4%): H067 parțial.
Următorul pas: HTTP fără streaming cu discovery/poll legat de același actor,
apoi CLI/email și prose/comenzile din ingress ocupat. Nu relua implementările
ori campaniile istorice. Dovezi în web-report.json din folderul cumulativ H067.
Fără stage/commit/push/merge/deploy. HEAD a7ffad6676cfb28e7ac374d495b4a5889e5f4646.

Checkpoint HTTP fără streaming H067 (2026-10-05): POST /chat poate aștepta
clarificarea ToolRPC, descoperită prin GET /chat/pending de același actor valid
și rezolvată prin endpointul existent, fără încă un model. Discovery este
no-store/paginat și nu confirmă livrarea înaintea body-ului; o trimitere eșuată
nu permite răspunsul. Timeout, token revocat înainte/după discovery și eventul
real de deconectare retrag întrebarea. Defectul watcherului care absorbea cancel
în is_disconnected a fost reprodus și corectat prin receive-ul de deconectare.
354 probe backend afectate (10 noi) și54 garduri API/doc/typegen trec, fără
eșecuri/erori/skipuri. Typecheck/Ruff/Bandit și scan strict5 surse trec.
Dovezi: http-poll-report.json și http-poll-*-result.xml în folderul cumulativ.
Următorul pas: CLI/email cu aceleași parser/runtime/identități, apoi ingress
ocupat pentru prose/comenzi. Nu redeschide loturile deja verificate. H067 rămâne
parțial; obiectivul este în continuare toate697. Nicio publicare/staging.

Corecție finală HTTP: confirmările de discovery sunt indexate pe prompt_id,
nu împărțite de binding. Un clarifier concurent refuzat nu poate anula livrarea
întrebării existente. Regresia a fost reprodusă (404 în loc de200), apoi întregul
lot afectat354 a trecut pe sursa corectată. Următorul lot rămâne CLI/email.

Checkpoint canonic H067: inventarul fixat și planul Completion batch separă
CLI/HUD de rândul gateway. Notițele ulterioare au adăugat greșit aceste extensii
și milestoneul697 drept gate-uri H067. Clarify-by-reply, confirmările trei căi,
reset/undo cu permission.grant durabil și notificările efemere sunt integrate:
354 probe afectate finale plus173 probe contractuale trec. H067 echivalent;
registrul ajunge129/697 (18,5%),21 reevaluate curent și108 moștenite. Dovezi:
gateway-acceptance-report.json și gateway-contract-result.xml. Nu este o
reauditare/live acceptance completă. Următorul lot: reziduurile comune începute
H660/H595 (execuție de cod: resume/reconciliere și transporturi), apoi H515.
Nu adăuga gate-uri care lipsesc din rândul fixat; refolosește donorul și lucrul
existent. Obiectivul697 rămâne activ; toate modificările sunt locale/necomise.

Checkpoint H595/H660 (2026-10-05): resident mode now defaults on only when
execute_code is enabled and a pinned isolated manager is composed, retaining
explicit sessions=false. Model-facing cells need exact GRANT; refused reset
preserves variables; live permission is checked after the interpreter lock.
The existing bound kernel.revalidate avoids charging the same invocation twice.
Final affected regression525 passed, one Linux /proc-only macOS skip, no errors
or failures. Shared-impact553, API/doc54 and HUD7 passed at the earlier stage;
final metadata211 passed. Counts overlap; no live remote/whole-suite claim.
Scoped source hashes/scans and Graft graph are current. Exact immediate-preimage
pins were refreshed after impact review; verdicts and old unrelated stale pins
were preserved. Ledger remains129/697 (18.5%):21 current plus108 inherited,
228 partial,56 missing,284 needs_review. H595/H660 remain partial.
Evidence: docs/hermes/evidence/2026-10-05-resident-code/. All runs terminal;
no stage/commit/push/merge/deploy. Next: verify H595's exact pinned12 entries
before adding gates; then adapt donor isolated remote transports for H660 and
finish H515. Full697 goal stays active; this checkpoint does not end it.

Checkpoint H595 imports/lifecycle (2026-10-05): generated jarvis_tools functions
now wrap the live offered schemas and existing broker in both one-shot and
resident scripts. Actual model-registered calls preserve approvals and caps;
synthetic FileTools pipeline works; saved imports cannot retain revoked offers.
User code keeps its full32768-character allowance. One-shot cancellation owns
and awaits backend teardown before deleting RPC, including during host servicing;
backend exceptions still clean up. Donor generator pattern/MIT license retained.
Affected629 cases:620 passes,9 Docker/platform skips, zero failures/errors.
Final metadata211 passes. Existing tests unchanged; current scoped source checks
and Graft graph pass. Evidence: docs/hermes/evidence/2026-10-05-code-imports/.
H595/H660 stay partial and129/697 unchanged. The complete12-entry H595 map is
docs/hermes/code-execution-guide.md. Tool authority profiles are not project
cwd/interpreter selection. Next: actual project/strict context and owner/skill
scoped environment passthrough with the existing isolation/kernel architecture,
plus actual message-producer interruption evidence; then H660 remote/H515.
Do not add remote/native-fd/automatic-resume gates to H595 or restart historical
full suites. All local runs terminal; no stage/commit/push/merge/deploy. Full697
goal remains active; this is a coherent completed subfeature batch, not parity.


## Verified resident context batch —2026-10-05

H595 resident project/strict cwd/backend Python and scoped trusted-skill/config env are integrated. Exact authority context revisions destroy old state; live checks block revoked queued cells/startup values.1420 affected tests passed,2 platform skips; final71 focused and67 composition cases passed. Metadata/evidence checks are recorded in docs/hermes/evidence/2026-10-05-code-context/report.json. Binding coordinates were repaired without changing writer authority. Local only, existing changes preserved, no publication. H595/H660 remain partial; accounting stays129/69718.5%, with zero new equivalence credit. Next: one-shot context transport and product/backend interruption evidence; full697 goal remains active.


Checkpoint one-shot and product interruption (2026-10-05): project/strict context
now reaches one-shot and safe resident fallback. Admitted same-session messages
interrupt only active conversation code children, await teardown, preserve bounded
partial output/count/duration and discard resident state. Jobs, pending replies,
other sessions and rejected/observation-only messages retain their routing. Backend
timeout state and parent recall taint are explicit. Composition297, final affected109
and startup44 tests pass; counts overlap. Evidence: docs/hermes/evidence/2026-10-05-code-interruption/report.json.
Exact-preimage pins refreshed for21 rows; inherited stale evidence retained.
Registry stays129/69718.5%, with0 newly equivalent rows; H595/H660 remain partial
while fresh isolated-backend/platform evidence and separate transport/resume work
remain open. Docker is absent on this Mac. All changes local, no staging/publication.
Next: finish the HUD follow-up producer using docs/hermes/h595-hud-interruption-plan-2026-10-05.md, then H515 provider reuse using docs/hermes/h515-provider-reuse-plan-2026-10-05.md.
The full697 objective stays active.


## Local checkpoint — 2026-10-06

H595 now meets its twelve frozen code-execution entries after registered-tool,
real local-worker and HUD follow-up integration. Current assessed equivalence is
130/697 (18.7%): one new complete capability; 227 remain partial, 56 missing and
284 require review. The immutable inventory remains unchanged. This is not fresh
Docker/cross-OS runtime acceptance or full697 completion.

FAL generation/edit now reaches the registered model tool, authenticated API,
composed signed worker and local artifacts/catalog. All25 pinned donor catalog
rows retain their values. Final affected union:564 passed; complete frontend
checkpoint:1926 passed, typecheck/build passed. These test counts overlap with
focused runs. No activation, live paid call, commit or publication occurred.

Next coherent work: finish OpenAI gpt-image-2 quality tiers and Codex OAuth, then
remaining H515 providers, Clarity and UI discovery. Keep existing local changes
and use the canonical Python3.12 project environment for continued verification.
Evidence: `docs/hermes/evidence/2026-10-05-code-hud/` and
`docs/hermes/evidence/2026-10-06-fal-images/`.

## Image-provider checkpoint — 2026-10-06

OpenAI Image2 tiers and native Codex generation/edit now compose through the
registered tool, API and signed worker. Images HUD selects OpenAI/Codex/FAL models
and capability-bounded references; approval cards display the actual inputs.
Backend585, final producer48 and full frontend1949 pass; counts overlap. Typecheck
and build pass. No activation, credential import, live call or publication. H515
stays partial; there is no new equivalent credit for this adapter/UI batch.
Next: managed Codex OAuth and the five remaining image providers, Clarity and
local lifecycle/authority gaps. Full697 remains the objective. Evidence:
`docs/hermes/evidence/2026-10-06-openai-codex-images/report.json`.
