# Sprint: echivalarea funcțiilor Hermes

**Directiva owner-ului, 9 septembrie 2026:** progresul se raportează la cele
**697 de capabilități din inventar**, nu la numărul PR-urilor sau al bifelor HA.
Acesta este sprintul curent. [Deschide statusul și procentele](../HERMES_STATUS.md).

## Ce înseamnă terminat

Un rând este echivalent când cerința acceptată are implementare completă în Nerva,
inclusiv intrarea utilizabilă și limitele de autoritate necesare. O clasă, un adaptor,
un manifest, o rută fără client sau o demonstrație cu date fictive nu închid singure
rândul. Adaptarea la arhitectura Nerva este permisă; eliminarea unei cerințe doar
pentru a crește procentul nu este. Dacă rândul cere și generare și editare de imagini,
generarea singură îl lasă parțial.

Toate cele 697 de identități rămân fixe. Cele 107 decizii `skip` sunt excluderi de
produs păstrate explicit, nu funcții terminate. Ținta acceptată este de 590 de
rânduri; statusul arată atât procentul din 697, cât și cel din 590. O modificare
a excluderilor cere o decizie de produs documentată și o migrare explicită a
inventarului de referință. Niciun rând parțial nu primește automat 50% credit.

Statusul de pornire combină două clase de dovezi, afișate separat: auditul existent
din 7 septembrie și reevaluarea actuală a livrărilor recente. Nu pretinde că toate
cele 697 au fost reauditate acum. `keep` nu închide un rând cu stare inițială
`partial`; `update` nu devine terminat doar fiindcă descrierea veche spunea
`superior` sau `parity`. Exemplu: infrastructura de memorie poate fi superioară,
iar exploratorul cerut în același rând să fie încă incomplet.

**Verdict de cod și probă pe serviciul real sunt lucruri distincte.** ComfyUI,
Slack, GPU, memorie personală, aplicația nativă și furnizorii cloud au propriile
probe. Procentul de aici nu este un procent de pregătire pentru lansare. Un
backend configurat, un test simulat sau un build reușit nu afirmă proba live.

## Livrările reunite în acest PR de sprint

Codul de mai jos era deja integrat în GitHub, pe `main`. Acest PR îl reunește în
evidența sprintului și adaugă măsurarea progresului; nu îl introduce a doua oară.
Punctul de plecare este `efc87a20634d33f2d7950b762d90854812c0a841`.

| Livrare | GitHub | Ce dovedește / ce rămâne |
|---|---|---|
| Fundația absorbției: CLI, joburi, unelte, profiluri, canale, MCP | [#1042](https://github.com/andrei649/jarvis-hub/pull/1042) | Mai multe mecanisme livrate; rândurile largi din inventar nu se închid în bloc. |
| Corecțiile găsite de probele din afara calculatorului owner-ului | [#1044](https://github.com/andrei649/jarvis-hub/pull/1044) | Corecții și dovezi delimitate; nu toate probele owner-host. |
| Catalogul comenzilor în HUD | [#1057](https://github.com/andrei649/jarvis-hub/pull/1057) | Comenzile înregistrate sunt vizibile; nu întregul catalog Hermes. |
| `nerva send` | [#1059](https://github.com/andrei649/jarvis-hub/pull/1059) | Răspunsuri propuse către threaduri cunoscute; nu send arbitrar către orice destinație. |
| Răspunsuri Slack/Discord prin inbox și aprobări | [#1060](https://github.com/andrei649/jarvis-hub/pull/1060) | Mesaje complete aprobate; streamingul rămâne deschis. |
| Răspunsul Ollama gol când bugetul se consumă pe raționament | [#1061](https://github.com/andrei649/jarvis-hub/pull/1061) | Refuz/degradare explicită și regresii pe calea fără streaming. |
| Recepție Slack Socket Mode | [#1062](https://github.com/andrei649/jarvis-hub/pull/1062) | Integrare SDK → pairing → inbox; fără probă de livrare pe un workspace real. |
| Probă raw-stream Ollama real | [#1063](https://github.com/andrei649/jarvis-hub/pull/1063) | Ollama real și răspuns degradat corect; nu toate probele P26. |
| Backend local de imagini cu aprobare durabilă | [#1064](https://github.com/andrei649/jarvis-hub/pull/1064) | Flux ComfyUI fix; fără editare, upscaling sau probă pe GPU. |
| Manifest, validare și inspecție extensii | [#1065](https://github.com/andrei649/jarvis-hub/pull/1065) | S1; execuția izolată S2 și evenimentele S3 nu sunt implementate. |
| Interfață pentru propunerea și citirea imaginilor | [#1066](https://github.com/andrei649/jarvis-hub/pull/1066) | Preview/download autentificat, reluare prin citire; nu galerie completă/native parity. |
| Legarea imaginilor la bridge-ul real de aprobare | [#1067](https://github.com/andrei649/jarvis-hub/pull/1067) | Compoziție în `off` și `enforce`; `hold` refuză intenționat. |
| Memorie navigabilă, inspirată de Darwin | [#1068](https://github.com/andrei649/jarvis-hub/pull/1068) | Entități și vecini reali, mostre doar în Demo. Nu adaugă un rând nou la numitorul Hermes și nu închide timeline/edit/share. |
| Editarea unui job deja armat (H146/H449) | [#1070](https://github.com/andrei649/jarvis-hub/pull/1070) | Nume, program și acțiune se schimbă fără a pierde istoricul; rândurile rămân parțiale (builder de program, ținte per job, galeria de blueprinturi). |
| Trimitere către o destinație configurată (H018/H480) | [#1071](https://github.com/andrei649/jarvis-hub/pull/1071) | Destinații numite, fără thread inbound; nu send arbitrar. |
| Editarea unei imagini generate de hub (H515/H598) | [#1072](https://github.com/andrei649/jarvis-hub/pull/1072) | Referință opacă + `strength`, niciodată o cale; fără upscaling și fără probă pe GPU. |
| Extensii S2 — suprafața declarată devine apelabilă (H566/H570/H615/H637) | [#1073](https://github.com/andrei649/jarvis-hub/pull/1073) | Consimțământ pe amprenta suprafeței, înregistrare dovedită în sandbox; izolarea rămâne a profilului de achiziție, nedovedită aici. |
| Extensii S3 — patru evenimente de ciclu de viață, doar observate (H567/H622) | [#1074](https://github.com/andrei649/jarvis-hub/pull/1074) | Nimic nu se întoarce dintr-un observator; hook-urile care blochează cer o decizie de kernel a owner-ului (`hook.exec`). |
| K0 — o rulare de sandbox își poartă autoritatea (H305/H595/H287) | [#1075](https://github.com/andrei649/jarvis-hub/pull/1075) | Identitate, ofertă și durată rezolvate de gazdă înainte de orice apel; K1–K3 rămân. |
| K1 — `execute_code` pe suprafața de unelte (H305/H595) | [#1076](https://github.com/andrei649/jarvis-hub/pull/1076) | Implicit oprit; reach-ul scriptului este exact oferta turei, iar fără backend izolat refuză. K2/K3 și spill-ul stdout rămân. |
| K2 — interpreter rezident pe sesiune (H660/H305/H595/H287) | [#1077](https://github.com/andrei649/jarvis-hub/pull/1077) | Starea persistă între celule, permisiunea nu: fiecare celulă releagă autoritatea K0, trece prin Action Kernel, primește propria cutie poștală și recitește ESTOP. Kernelul remote și K3 rămân; containerul nu e probat aici. |
| K3 — fereastra owner-ului peste propriul kernel (H660) | [#1078](https://github.com/andrei649/jarvis-hub/pull/1078) | Niciuna dintre cele două rute nu acceptă id de sesiune, principal sau token: cheia vine din autoritatea K0 a cererii, deci „altă sesiune nu poate inspecta sau reseta pe asta” e o proprietate a formei, nu o verificare care se poate uita. H660 rămâne parțial — varianta remote și proba pe un daemon Docker real. |
| H298 — un rezultat prea mare e scris pe disc, nu aruncat | [#1079](https://github.com/andrei649/jarvis-hub/pull/1079) | Cele cinci trepte ale pragului, preview mărginit cu calea fișierului în subsol, bugete scalate la fereastra reală a modelului (15 % / 30 %, praguri 8 KB / 16 KB) și retenție la fiecare scriere. Cele trei limite de output stau acum într-un singur modul și cele două limite de formă chiar se aplică. **H298 devine `equivalent`.** Spill-ul stdout-ului din `execute_code` (clauza H305/H595) NU e închis: stdout-ul e tăiat înainte de construirea rezultatului. |
| H305/H595 — stdout-ul unei rulări `execute_code` e păstrat, nu tăiat | [#1080](https://github.com/andrei649/jarvis-hub/pull/1080) | Fluxul e scurs pe disc pe drum (`ToolResultStore.open_stream` + `read_capped_stream(sink=…)`), nu copiat după ce cititorul mărginit i-a aruncat mijlocul; memoria gazdei rămâne mărginită. Închis pe calea K1 (implicită); pe calea K2 worker-ul taie în container, deci rămâne deschis și cere un protocol pe cadre. Tăierea celulei K2 nu mai e tăcută: cap+coadă cu notiță numărată în loc de doar coadă. **H305/H595/H660 rămân `partial`.** |
| H363 — caching de prompt pe Anthropic, și un contor care aude providerul | [#1081](https://github.com/andrei649/jarvis-hub/pull/1081) | Un breakpoint efemer pe blocul de sistem și unul pe ultima unealtă (marca acoperă tot ce e înaintea ei); `ToolTurn.usage` aduce contoarele providerului, `usage_sink` le însumează prin buclă până în contorul de cost, care preferă cifra raportată și marchează `usage_source`. Tariful `cached` din tabelul de prețuri era până acum necâștigabil. **H363: `missing` → `partial`** — rămâne `supports_prompt_cache_key` pe wire-urile compatibile OpenAI. |
| H364 — o scară de efort, tăiată la ce acceptă fiecare wire | [#1082](https://github.com/andrei649/jarvis-hub/pull/1082) | Scară unică de 8 trepte (none…ultra) cu clamp la treapta **mai slabă** cea mai apropiată; când wire-ul n-are nimic mai slab, răspunsul e podeaua vocabularului, nu tăcerea — tăcerea ar preda cererea default-ului vânzătorului (`high`). Tabelul per familie decide și ce se **scoate**: parametrii de sampling sunt respinși pe generația 4.7+, iar `anthropic.py` trimitea `temperature` pe fiecare cerere, deci orice rută către Opus 5 / Opus 4.8 / Sonnet 5 / Fable 5 era un 400 viu. De aceea potrivirea rulează pe fiecare cerere, nu doar când se cere efort. Model necunoscut → cererea de dinainte, neatinsă. **H364: `missing` → `partial`** — un singur vânzător din ~18, fără wire Grok și fără Gemini/OpenAI-compatibil. |

| H679 — un vocabular de efort per model, cu un singur clamp canonic | [#1083](https://github.com/andrei649/jarvis-hub/pull/1083) | `ProviderProfile.supported_reasoning_efforts(model)` răspunde **tri-state**: `None` = nedeclarat (transportul își ține default-urile), `()` = modelul nu acceptă nicio treaptă și câmpul se omite, tuplu nevid = vocabular în care se face clamp. Colapsul celor două era viu: toate profilele non-Anthropic purtau `()`, adică „respinge", când adevărul era „nedeclarat". Cache-ul se citește pe calea fierbinte și nu blochează — un model nedeclarat răspunde `None` imediat, nu așteaptă un catalog. Hook-ul e purtător de sarcină, nu interfață: `apply_anthropic` cere vocabularul registrului, deci o declarație schimbă corpul cererii fără release. Clamp-ul e cel canonic, cu test de monotonie pe toată scara (bug-ul Nebius e tăcut și greșit în direcția scumpă). **H679: `missing` → `partial`** — jumătatea de scriere n-are încă producător viu, deci singurul vocabular sincron rămâne Anthropic. |

| H673 — presiunea de context se măsoară din cifra providerului | [#1084](https://github.com/andrei649/jarvis-hub/pull/1084) | `UsageAnchor` poartă numărul **raportat** pentru ultima cerere (prompt de sistem + scheme de unelte + istoric) și câte ture acoperă; `compact()` estimează doar ce s-a adăugat de atunci, deci fereastra de eroare scade de la toată conversația la o singură tură și se recalibrează la fiecare răspuns. Ancora acoperă și ce transcriptul nu conține deloc — de aceea estimarea singură subevaluează cererea cu tot ce nu e conversație: zece ture scurte dau `none` pe 32k, în timp ce cererea reală de 28k trece pragul dur. Fără ancoră (orice backend local, prima tură) rezultatul e identic cu cel de dinainte. Podea la estimarea simplă: o ancoră poate compacta mai devreme, niciodată mai târziu. Capcana reală, prinsă și testată: ancora se **înlocuiește**, nu se acumulează — o buclă de unelte retrimite tot prefixul la fiecare iterație, iar suma ar raporta de câteva ori contextul real. **H673: `missing` → `partial`** — clampul pe `num_ctx`-ul Ollama nu e livrat: `num_ctx` nu există nicăieri în cod. |

| H048 — unde se duce bugetul de prompt, înainte să înceapă conversația | [#1085](https://github.com/andrei649/jarvis-hub/pull/1085) | `nerva prompt-size` sparge costul fix per apel pe componente, cel mai mare primul, **offline** — fără hub, fără backend, fără nicio cerere. Uneltele sunt costate ca JSON-ul care chiar traversează sârma, nu ca numele lor: un `input_schema` stufos poate cântări cât o persoană întreagă. Numărul scos în față e **podeaua per apel**, nu suma: prima versiune aduna toate cele 18 persoane și anunța 71,8 % dintr-o fereastră de 32k, când o cerere reală trimite una singură și plătește ~6,5 %. Un număr greșit e mai rău decât niciun număr, așa că podeaua per apel e ce se citește primul și un test o fixează. Fără agent numit se ia persoana cea mai grea — cazul realist cel mai prost, nu unul măgulitor. **H048: `missing` → `partial`** — tierele de prompt și profilul de utilizator nu există ca blocuri separate în Nerva, iar schemele de unelte apar doar când i se dau (verbul nu bootează un registru, și **spune** când lipsesc în loc să raporteze zero). |

| H671 — o conversație de lungă durată știe ce zi e acum | [#1086](https://github.com/andrei649/jarvis-hub/pull/1086) | Promptul de sistem poartă ceasul conversației: ziua nașterii, plus — **doar** când ziua rebuild-ului diferă — „Today's date … trust this over the start date". Proprietatea load-bearing: o sesiune din aceeași zi randează o singură linie, deci prefixul cacheabil de la H363 rămâne stabil; linia de refresh apare abia la granița de zi, unde cache-ul oricum se invalidează. Data se scrie pe litere (09/11 sunt două zile diferite), iar zona duce întotdeauna offsetul (`EST` e două offseturi). Ziua de naștere e rezolvată prin id-ul sesiunii, semănată o dată și niciodată reîmprospătată — recalcularea la rebuild ar reseta tăcut ziua de naștere a unei sesiuni perpetue la azi. **H671: `missing` → `partial`** — ceasul e montat pe calea orchestratorului, nu pe `Agent.process`; ziua de naștere e în memorie per proces, nu citită din `sessions.started_at`, deci un restart o resetează (`parse_started_at` e jumătatea de citire, încă fără apelant). |

Cele opt PR-uri #1061–#1068 raportate la încheierea lucrului sunt toate integrate, la
fel și livrările #1070–#1085 din sprintul curent; #1086 este în lucru.
Intrările anterioare arată dependențele și livrările conexe deja existente; numărul
lor nu este folosit în calculul progresului. SHA-urile, rezultatele verificărilor
și detaliile de implementare se găsesc în fiecare PR.

Sunt incluse și investigațiile rămase locale până acum:

- [Auditul K0/K1 și contractul de autoritate lipsă](plans/2026-09-09-hermes-execute-code.md),
  [proba sintetică](plans/2026-09-09-hermes-execute-code-probe.py) și
  [rezultatul capturat](plans/2026-09-09-hermes-execute-code-evidence.json).
- [Planul de continuare K0–K3, S1–S3 și desktop](plans/2026-09-09-hermes-remaining-delivery.md).

Acestea sunt capturi datate ale unei investigații. Nu afirmă că izolarea live sau
contractul K0 sunt implementate și nu autorizează modificări printr-un snapshot vechi.

## Automatizări — increment verificat la 15 septembrie

H453 rămâne parțial. Scripturile aprobate pot opri apelul la model și livrarea prin
`wakeAgent:false`, iar răspunsurile modelului pot opri notificarea prin convențiile
`[SILENT]`. Datele trunchiate sau JSON invalid nu declanșează suprimarea; istoricul
înregistrează motivul fără a consuma bugetul de notificare. Sunt 31 de cazuri noi
și 316 verificări țintite, cu acoperire integrală a ramurilor noului helper.
Monitorizarea prin hash și diff pentru scripturi/URL-uri rămâne deschisă.
[Contract și limite](automations-scripts.md#wake-and-silence-gates).

Monitorizarea scripturilor este acum verificată separat: hash pe întregul stdout,
capturi complete cu secrete mascate, suprimare fără schimbări și diff la schimbare.
Baseline-ul se persistă înainte de model; generația configurației protejează
înlocuirile și livrările întârziate. 26 de teste noi, 364 țintite trecute și 95%
acoperire a ramurilor pentru modulele noi. Capturile sunt limitate la UTF-8 complet
în plafonul terminalului; monitorizarea URL rămâne deschisă.
[Contract și limite](automations-scripts.md#bounded-script-monitors).

## Context local — actualizare verificată la 15 septembrie

Notele istorice H671/H673 de mai sus descriu golurile de la acele PR-uri. Între timp,
nașterea conversației se recuperează din checkpoint și calea Agent primește ceasul;
limita Ollama `num_ctx`, plafonul de 85% și rezerva Gemini sunt implementate.
Identitatea pe rădăcina unei linii de sesiuni și refresh-ul strict la compactare
rămân deschise.

Acest increment transmite și contoarele Ollama/LM Studio din răspunsurile cu
apeluri de unelte: contorizarea însumează cererile, iar ancora de context reține
ultima cerere. Metadatele invalide nu pierd răspunsul. 38 de teste noi și 215
verificări țintite trecute; H673 rămâne parțial pentru restul traseelor/providerilor
și estimarea imaginilor. [Plan și probe](superpowers/plans/2026-09-15-local-usage.md).

## Preferințe vizuale — progres H135 la 15 septembrie

H135 trece din lipsă în parțial: browserul, modul ambient și interfața responsive
folosesc preferințe persistente în Settings DB. Jurnalul local păstrează modificări
offline între tab-uri, iar reviziile serverului refuză salvările vechi. Preferința
System păstrează setarea OS pentru mișcare redusă. 13 teste backend și 18 frontend
noi; 24 de probe în browser și suita frontend de 1.247 teste trecute.
Consumatorul din aplicația mobilă nativă și opțiunile de font rămân de implementat.
[Contract și verificări](../frontend/docs/h135-appearance-sync.md).

## Monitorizare URL — increment H453 la 15 septembrie

Monitorizarea URL folosește acum coada semnată și aprobarea fiecărui GET, inclusiv
aprobări noi pentru redirecționări. Captura finală este limitată la 256 KiB UTF-8
necomprimat, mascată înainte de stocare și procesată de mecanismul de baseline/diff.
35 de teste noi; 232 verificări țintite trecute și revizuire independentă fără
constatări. H453 rămâne parțial: nu acordă execuție nesupravegheată și nu acoperă
URL-uri private/cu credențiale/comprimate ori configurarea contextelor per job.
[Contract și limite](automations-scripts.md#url-monitors-with-approval-per-request).

## Ordinea sprintului

1. **Reevaluarea restului inventarului pe clustere**, începând cu cele mai vechi
   verdicte `keep` și cu rândurile largi. Fiecare decizie păstrează cerința originală,
   codul, testele și lipsurile. Un verdict vechi prea optimist poate fi retrogradat.
2. **Completări delimitate, cu circuit utilizabil:** editarea joburilor existente
   (H146/H449), trimiterea către destinații configurate (H018/H480), controalele
   imaginilor și galeria (H515/H518/H523/H598). Fiecare rând își păstrează toate
   cerințele acceptate; o subfuncție livrată nu închide întregul pachet.
3. **Extensii S2/S3:** dispatch izolat și evenimente, peste S1; H566/H570/H615/H637.
   Fără imports cu încredere totală, extensii UI sau raw-shell hooks introduse tacit.
4. **Execuție de cod:** K0–K3 sunt livrate — autoritatea rulării, `execute_code` pe
   suprafața de unelte, interpretorul rezident pe sesiune și controalele de operator
   peste el (toate implicit oprite). Rămân kernelul remote și proba pe un daemon Docker
   real. Scurgerea stdout-ului într-un fișier e livrată pe calea implicită (K1) și
   rămâne deschisă pe calea cu kernel de sesiune (K2), unde worker-ul taie în container
   și gazda nu vede niciodată fluxul întreg. H305/H595/H660 rămân parțiale.
5. **Desktop și canale:** overlay nativ H178 și streaming Slack/Discord H104/H683,
   cu autoritate și cicluri de viață explicite.

Aceste priorități nu înlocuiesc celelalte rânduri din cele 697. Nu există un termen
de finalizare dedus din procent: efortul fiecărui rând diferă considerabil.

## Cum se menține statusul

[assessment.json](hermes/assessment.json) păstrează numai reevaluările explicite,
legate prin ID și hash de inventarul original. Restul rândurilor au baza de audit
vizibilă. Hash-urile dovezilor sunt SHA-256 peste text UTF-8 cu newline normalizat,
astfel încât checkout-urile Windows și Linux să aibă același verdict.

Pentru un rând reevaluat, citește cerința completă cu `show`, inspectează codul și
testele, apoi actualizează evaluarea. `equivalent` cere cod și teste referențiate
și zero lipsuri declarate; acestea sunt condiții necesare, nu un înlocuitor al
judecății tehnice. Nu reîmprospăta hash-urile fără reevaluare. Un fișier schimbat
sau dispărut produce `needs_review`, nu o promovare implicită.

```text
python scripts/hermes_status.py summary --json
python scripts/hermes_status.py list --state partial --cluster media
python scripts/hermes_status.py show H515
python scripts/hermes_status.py write
python scripts/hermes_status.py check
```

Pagina principală și lista completă sunt generate împreună. Testele de integritate
verifică numitorul, excluderile, identitatea rândurilor, dovezile modificate și
sincronizarea documentelor. Fiecare implementare viitoare actualizează statusul
în același PR dacă schimbă un rând evaluat. BACKLOG rămâne sursa de prioritate.

2026-09-15 — H684 ([PR #1104](https://github.com/andrei649/jarvis-hub/pull/1104)): read-only owner/native diagnostics, bounded persistent outcomes and non-zero health exit codes. Real APScheduler, migration and failure/skip tests pass; diagnostic coverage is 97% including branches. Existing evidence hashes are refreshed only where they matched the inspected base; older stale evidence remains stale. H684 is partial: script/no_agent/workdir diagnostics and production-host proof remain open.

Independent review corrections for H684: actual owner JobRun results now preserve skipped/missed and failed outcomes; auto-paused, disabled and repeat-exhausted jobs retain diagnostic execution/delivery failures without requiring registrations. Six added regressions reproduced the failures before the localized repairs.

## 2026-09-15 — heartbeat resume (#1105)

Startup and resume share the same cron conversion, including numeric Sunday and named weekdays. Invalid weekdays fail without arming a job; named ranges no longer crash cadence estimation. Regression tests use actual APScheduler triggers. Evidence hashes are refreshed only for previously matching inspected sources; no parity status is promoted.

## 2026-09-15 — H660 real Docker and native CLI selection

The unchanged containment suite passed all seven tests on Linux and again from native macOS through a local Lima daemon. Two additional real-container checks verified current/explicit context precedence, absence of proxy credentials in container environment, frozen daemon identity after configuration changes, and cancellation/removal/reuse. The verified CLI fix has 67 focused tests and an independent read-only review. Runtime versions, image digest, integrity hashes and limits are recorded in [the dated evidence](hermes/evidence/2026-09-15-docker-containment.json). Containers were removed and the disposable VM stopped. H595/H660 remain partial for the named unsupported transports; these are actual containment observations, not production deployment proof.

## 2026-09-15 — H129 HUD URL routing

Existing modes and console panels now support bookmark/reload/history URLs and page titles through one routing subscription. Real lazy chunks expose loading/error recovery; selected console panels have stable IDs and focus. Independent review reproduced and cleared the historical overlay return-path defect, including nested visits and malformed/external history destinations. The initial full frontend suite passed 1,208 tests; seven added history regressions bring collection to 1,215. Desktop and Pixel 7 Chromium smoke passed with a local stubbed backend; rebuilt assets were byte-identical. H129 remains partial for absent multi-profile/plugin route integration. Evidence for unchanged panel behavior is refreshed only where its previous hashes matched the inspected base.

## 2026-09-15 — Governed scheduled Python scripts

H146/H449/H453/H684 gain bounded script/no_agent runtime support through the existing local terminal approval path. Exact source is frozen in argv for each firing; no standing grant is created. Results remain pending until the durable task completes, with atomic repeat reservations, crash recovery and bounded fair reconciliation. Empty observations skip the model; other model context is fenced and carries inbound provenance. Independent review and regressions cover deletion/e-stop during awaits, uncertain fan-out, retained pending history beyond 200 skipped runs, and origin restoration on error/cancellation.

285 focused tests pass, including a harmless real local transport test with an injected grant. The prior runtime snapshot measured 88.12% branch-inclusive coverage; the final delta adds empty-context regressions. The operator guide documents POSIX/local/source-size limits. Workdir/provider/tool context, wakeAgent/monitor/[SILENT] mechanisms and live production proof remain open. These rows stay partial; source hashes are refreshed only if their previous value matched the inspected base.

## 2026-09-15 — H004 shell command-tree completion

Fish completion is generated recursively from the live argparse tree, with exact command-path predicates and two-stage quoting of metadata. No hub or CLI execution occurs when a generated script is sourced or queried. Real isolated fish 4.9.3 verification covers all installed paths, nested parser extensions, partial prefixes, leaf behavior, repeated sourcing and malicious command names. Bash/zsh output is byte-identical; both existing shell syntax checks pass.

Independent review cleared the frozen command-tree contract. The integrated CLI/completion suite passes 56 tests, including seven new tests; H004 is equivalent with source-bound evidence. Option/value completion is outside this row, and saved scripts need regeneration after upgrades. Temporary fish/PCRE2 bottle provenance is recorded in the module plan; no product dependency or shell configuration changed.

## 2026-09-15 — H130 reverse-proxy prefix hosting

A trusted static JARVIS_ROOT_PATH configures the server bootstrap and frontend public URLs. The same relocatable build supports root or nested prefix hosting behind a stripping proxy, including lazy assets/fonts, API and streaming paths, route history, PWA/offline cache isolation and the linked map/mission-control surfaces. Forwarded-prefix headers cannot select the mount. Native policy remains unchanged; native deployment uses the default empty root and legacy /v1 is not claimed prefix-aware.

The final full frontend suite passes 1,229 tests; 146 affected backend tests and 18 browser checks pass. Actual-app proxy acceptance uses isolated data with lifespan/providers disabled, plus fixture streams; an actual schedule-parse POST checks missing-token401 and valid-token200. Independent review caught and cleared console-toggle/World-Escape defects and /v2-/api-named prefix collisions. H130 is equivalent for the frozen SPA hosting contract; this is not production or live-provider evidence. Existing evidence hashes are refreshed only when they matched the inspected base.

### 2026-09-15 — H139 shared composer images

Authenticated transient vision turns support choose/paste/drop and explicit destination consent. Raster validation, one configuration snapshot, cross-process revision binding and cancellation were independently reviewed. Source tests: 27 new backend and 10 frontend cases; 1,257 frontend tests and six browser checks passed. The integration adds exactly two user-guarded routes (500 total), regenerates their OpenAPI types and preserves ordinary text chat. H139 remains partial: persisted artifacts, native agent image context/mobile and learn seeding remain open. See [the bounded contract](../frontend/docs/h139-composer-images.md).

### 2026-09-15 — H518 retained gallery pagination

A reproduced 220-record fixture exposed the old newest-200 search ceiling. Timestamp/key cursors now advance through at most 200 scanned candidates per request, including zero-match pages. Authenticated resolution and 200-file/128 MiB ZIP limits remain; selection is explicit and stale searches are cancelled. Independent review: 34 backend and nine gallery frontend tests pass, with two real-route browser cases. Native mobile and exact ingestion snapshots remain open. The existing catalog GET gains bounded limit/cursor parameters; route count remains 500. [Contract](../frontend/docs/h518-gallery-pagination.md).

### 2026-09-15 — H022 dependency vulnerability audit

The SBOM had been generated since H23.13 and checked against nothing. `nerva security audit` now enumerates the running interpreter's distributions and any named extension descriptor's exact Python pins, queries OSV.dev (`querybatch` in chunks of 1000, one detail fetch per unique advisory) through `PluginHTTPClient`, merges advisories that alias each other so a PYSEC mirror cannot fail a bar its rated GHSA twin clears, and ranks by stated severity. An unrated advisory fails every `--fail-on`; a database that could not be consulted is exit 5 and claims nothing. MCP — owner-configured stdio commands on Nerva — is listed as *not audited*, with that reason. Verified live against api.osv.dev with a scratch `requests==2.19.0` pin: 5 findings after merging 5 mirrors, exit 1; `--fail-on critical` exit 0; `--offline` exit 5 over 48 components. An independent adversarial review (no shared context) found nine defects; all were fixed in the same PR: the false MCP reason, a crash on undecodable distribution metadata (now skipped and named; an audit that cannot complete is exit 5, never a traceback's 1), raw advisory text on the terminal (now control-stripped), ignored `querybatch` pagination (pages followed; still open after 20 → `unavailable`), a fix version that could be a downgrade (now the range containing the installed version), duplicated alias spellings, a hardcoded header and a false `rg` claim in the docstring. Partial: MCP commands are not resolved to packages, the acquired extension catalog is hub-side and not read offline, there is no bare `nerva security` default or `--skip-*`, CVSS vectors are not scored, `--fail-on low` is deliberately stricter than Hermes's `critical`, there is no operator proxy setting, the egress ledger does not persist from the CLI process, and Hermes's 0/1/2 exit ladder is adapted to Nerva's 0/1/2/5. Evidence re-pins in the same review: H004, H146, H364, H449, H671, H684 cite `agents/cli/nerva.py` / `tests/test_nerva_cli.py`, which this row extends additively (no existing verb touched); their hashes were re-pinned after the cited tests passed (895 passed, 3 skipped — the skips are H004's real-`fish` tests, `fish` not being installed here). H004's surface did change in one respect: `nerva completion` now also emits `security`/`audit`.

### 2026-09-16 — H480 send from a script: body, subject, exit ladder

Hermes's `send` resolves its body from the argument, a file or piped stdin, prepends a subject, and exits 0/1/2; ours took one argument and stopped there. `nerva send` now reads the MESSAGE argument, else `-f PATH` (`-` is stdin), else piped stdin — and never a terminal, with or without `-f -`, so a script that forgot the body gets a usage error, not a hang; a closed stdin (cron, `<&-`) is a usage error too, not a traceback; only the bound plus one character is ever read, so a runaway file is refused without being loaded; a UTF-8 BOM is dropped. `-s LINE` is one *printable* line (`str.isprintable`: every control character and Unicode line separator refused, not just LF/CR): ntfy gets it as its native title — printable ASCII of at most 120 characters, refused with the reason rather than letting the adapter silently strip and cut it — every other channel gets Hermes's shape (subject, blank line, message), and a thread reply gets the same first line client-side. `-q` prints nothing on success; `--list CHANNEL` filters the targets: a name that can never be a direct-send channel is a usage error decided offline (the existing pin that `--list hello` never reaches the hub holds), and a channel an older hub does not list is exit 1 naming what it lists; a blank MESSAGE argument is no message and falls through to `--file`/stdin. The exit ladder is in `--help`: 0 sent · 1 not delivered · 2 usage · 3 no hub · 4 not authorised. A binary `--file` is refused with the attachment guidance and its bytes are never reflected; the 4,000-character bound is the seam's own `carried_length` — the subject counts where it becomes the first line, not for ntfy — and the CLI enforces that same rule before any request leaves the machine. Hub-supplied and shell-typed strings are cleaned of control characters before the terminal, as `nerva security audit` does. `POST /api/channels/send` gains an optional `subject` (one line, ≤200) and `send_to_target` applies the bound to what is actually delivered. The real `ChannelManager` probed to admit the ntfy `title` kwarg. An independent adversarial review found fifteen items — two majors (the slice had broken two pre-existing pins in `tests/test_nerva_send.py`: a blank argument and `--list hello` must never reach the hub) and thirteen smaller ones (`-f -` read a terminal; closed stdin crashed; ntfy titles were silently mangled by the adapter; the CLI bound was stricter than the hub's for ntfy; `\x0b`/U+2028/ESC passed the "one line" check; BOM; whole-file read before the bound; raw echoes; `schema.gen.ts` not regenerated; a wrong "21 rows" count; overstated red-proof claims) — every one fixed in the same PR, each with a test. Partial: `MEDIA:<path>` attachments (a route that reads local paths is file egress and belongs behind the kernel with a confined source directory), no-gateway operation (the hub is where the IntentLog and rate limit live — a documented divergence), no chunking past 4,000, Slack/Discord reply-only (H018), `JobRunner._send` left to the jobs lane. Evidence re-pins in the same review: H480 (full re-evaluation, five files) and H018 (same send surface, summary extended) come out of "De reverificat"; H004, H022, H146, H364, H449, H671, H684 cite `agents/cli/nerva.py` / `tests/test_nerva_cli.py`, which this slice changes only inside the `send` verb plus one additive `Context.inp` field — their cited test files were run in full before re-pinning. The 46 other rows that were already "De reverificat" at the base (48 minus H018 and H480) are untouched — an earlier draft of this note said 21, which was wrong; the reviewer counted. `tests/test_nerva_send.py` is now cited as evidence by H018 and H480.

### 2026-09-18 — H002 one scripted turn from a pipe

`nerva chat -z "prompt"` is the primitive that makes the agent scriptable: one turn in, the final assistant text out on stdout and nothing else, an exit code a cron entry or a CI step can branch on. Whole escape sequences and C0/C1 control bytes are stripped from the answer (newlines and tabs are content and stay); every other word goes to stderr. The prompt resolves the way `nerva send`'s body does — the argument, else `-f PATH` where `-` is stdin, else piped stdin — and a terminal is never read, so a script that forgot the prompt gets a usage error instead of a hang. A prompt over the hub's own 4,096-character `ChatRequest` bound is refused before the request, not after it as an HTTP 422 a caller would read as a failed turn. The ladder is in `--help`: 0 answered · 1 the turn did not complete · 2 usage · 3 no hub · 4 not authorised · 130 interrupted. Ctrl-C already exited 130, but through an uncaught traceback that in a pipeline is indistinguishable from a crash and can spill a partial answer; it is now one stderr line and an empty stdout.

The row's governance clause is the reason this is not a straight copy. Hermes sets `HERMES_YOLO_MODE=1` and `HERMES_ACCEPT_HOOKS=1` inside `-z` because "no user is watching". Nerva does the opposite and there is no flag that changes it: a turn that queues an action stays queued, the verb exits 1 naming the pending id with `nerva approvals` as the next step, and nothing in the one-shot path can approve or execute the queued item — a test asserts that no decision call reaches the hub. The pending list decides that verdict, not the reply text, so a hub that both composes a reply and queues an action still exits non-zero rather than handing a script an exit 0 over an undecided action. The CLI keeps a stdlib-only copy of the hub's seven refusal replies (importing the orchestrator would pull the runtime into `nerva --help`); a drift test imports the real constants, so a renamed reply is a red test instead of `-z` silently exiting 0 on a refused turn.

`--usage-file PATH` writes `nerva.chat.usage.v1` atomically — tempfile plus `os.replace` — on every path, including the failures: answered, refused, queued for approval, usage error, no hub, not authorised. An unwritable path warns on stderr and does not change the verdict. **What it does not do is invent a number.** The hub cannot attribute one turn's cost today: `AgentConfig.model` defaults to `google/gemma-4-31b-a4b`, none of the 18 agents in `agents/_system/agents.yaml` declares a model, so `cost_tracker` meters every turn at the default price row and reports $0.00 — measured here as a 1M/500k-token turn costing `total_cost_usd 0.0` — while an id it does not know is priced from the `default` row with no `priced` flag, unlike `cost_estimator.estimate_cost`. `estimated_cost_usd`, the token counts, `api_calls`, `model` and `provider` are therefore `null` with `cost_basis: "unavailable"`, and a test pins that they never become zeros.

29 tests cover the verb; nine mutations of the shipped behaviour each turn at least one of them red. H002 is recorded **partial**, not equivalent: the pipe half is done, the spend half is a schema waiting for a meter that can attribute a turn. Also open: `POST /chat` returns no trace, invocation or session id (`session_id` is echoed only when the caller supplied one), `-z` does not silence hub-side logging, there is no `--output-format` beyond the existing `--json`, and a piped body is read whole up to the bound rather than streamed. Evidence re-pins in the same slice: the nine rows citing `agents/cli/nerva.py` whose hashes still matched the inspected base (H004, H018, H022, H146, H364, H449, H480, H671, H684) were re-pinned after the full suite ran green; the 21 rows that were already "De reverificat" at the base are untouched. The headline is unchanged at 122/697 — this slice moves H002 from an inherited verdict to a reviewed one and adds no completion credit.
