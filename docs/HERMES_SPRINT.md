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

The row's governance clause is the reason this is not a straight copy. Hermes sets `HERMES_YOLO_MODE=1` and `HERMES_ACCEPT_HOOKS=1` inside `-z` because "no user is watching". Nerva does the opposite and there is no flag that changes it: a turn that queues an action stays queued, the verb exits 1 naming the pending id with `nerva approvals` as the next step, and nothing in the one-shot path can approve or execute the queued item — a test asserts that no decision call reaches the hub. The pending list decides that verdict wherever the hub reports one — but it does not report one yet on this base, and an independent adversarial review found that the fallback was broken. See the correction below. The CLI keeps a stdlib-only copy of the hub's seven refusal replies (importing the orchestrator would pull the runtime into `nerva --help`); a drift test imports the real constants, so a renamed reply is a red test instead of `-z` silently exiting 0 on a refused turn.

`--usage-file PATH` writes `nerva.chat.usage.v1` atomically — tempfile plus `os.replace` — on every path, including the failures: answered, refused, queued for approval, usage error, no hub, not authorised. An unwritable path warns on stderr and does not change the verdict. **What it does not do is invent a number.** The hub cannot attribute one turn's cost today: `AgentConfig.model` defaults to `google/gemma-4-31b-a4b`, none of the 18 agents in `agents/_system/agents.yaml` declares a model, so `cost_tracker` meters every turn at the default price row and reports $0.00 — measured here as a 1M/500k-token turn costing `total_cost_usd 0.0` — while an id it does not know is priced from the `default` row with no `priced` flag, unlike `cost_estimator.estimate_cost`. `estimated_cost_usd`, the token counts, `api_calls`, `model` and `provider` are therefore `null` with `cost_basis: "unavailable"`, and a test pins that they never become zeros.

29 tests cover the verb; nine mutations of the shipped behaviour each turn at least one of them red. H002 is recorded **partial**, not equivalent: the pipe half is done, the spend half is a schema waiting for a meter that can attribute a turn. Also open: `POST /chat` returns no trace, invocation or session id (`session_id` is echoed only when the caller supplied one), `-z` does not silence hub-side logging, there is no `--output-format` beyond the existing `--json`, and a piped body is read whole up to the bound rather than streamed. Evidence re-pins in the same slice: nine rows cite `agents/cli/nerva.py` with a hash that still matched the inspected base (H004, H018, H022, H146, H364, H449, H480, H671, H684), and all nine were refreshed after the full suite ran green — but only **seven** of them return to «Evaluat pe cod». H146 and H449 stay «De reverificat» on a *different* citation, `frontend/src/api/schema.gen.ts`, which #1156 regenerated and this slice does not touch; refreshing that one here would be laundering a diff nobody re-read. Of the 30 rows citing the CLI file, the other 21 already carried a stale hash at the base and are untouched for the same reason. (Repo-wide «De reverificat» is 49 rows, not 21 — an earlier draft of this paragraph conflated the two numbers, and the reviewer caught it.) The headline is unchanged at 122/697 — this slice moves H002 from an inherited verdict to a reviewed one and adds no completion credit.

### 2026-09-18 — H002, after the adversarial review

Five independent reviewers, no shared context, one lens each, every finding then handed to a separate verifier whose default was to refute it. **38 findings survived verification, four of them major, and the first one broke the row's governance clause in a single line.**

**The verdict could not be an exact-string match.** `cmd_chat` decided whether a reply was an answer with `_NOT_AN_ANSWER.get(answer.strip())`. But the hub does not hand `/chat` the agent's reply verbatim: `agents/core/orchestrator.py:1676` sets `was_synthesized = len(responses) > 1 or "jarvis" not in responses`, so a turn the router sends to a single specialist — the ordinary path for a tool-using request — goes through `_synthesize`, which with no jarvis agent returns `"[athena]: {reply}"` and with one re-writes the whole text through a model. Reproduced here with the hub's own synthesiser: `nerva chat -z "delete the archive"` exited **0** and printed *"[athena]: I paused the tool loop because this action requires approval."* on stdout as if it were the answer. A cron entry doing `nerva chat -z … && deploy` would have read an undecided irreversible action as a completed turn — precisely the Hermes behaviour this row exists to invert. `--agent X` was never exposed, because that path returns the specialist's reply verbatim.

The fix is containment matching over the sanitised text, and it is honest about its ceiling: containment survives the deterministic `[agent]: …` wrapper, and nothing in a reply string survives an LLM re-write. **The verdict belonging in a reply's text at all is the actual defect**, which is why the hub reporting `pending_approvals` — the slice stacked directly on this one — is the real fix, and why the row's `remaining` now says so instead of claiming the pending list already decides. Sanitising also moved *before* the verdict: a reply of pure control bytes used to be "not empty" to the guard and an empty line on stdout, exit 0 over nothing.

**The table was missing five of the hub's own stop reasons** — `_DEADLINE_REPLY`, `_CONTEXT_REPLY`, `_WINDOW_REPLY`, `_REPEAT_REPLY`, `_FAILURE_REPLY` — so a tool loop that gave up part-way exited 0 with *"I stopped the tool loop because the same tool kept failing."* stored as the answer. A sixth is built with an f-string (`"…after N model turns…"`) and no table of exact strings can hold it, so the family is covered by a prefix rule as well. The drift test now imports all ten constants and asserts each is matched **both verbatim and wrapped**; the previous version only asserted they were keys, which is blind to the wrapper that caused the defect.

The rest, each with a test and each red-proofed: the receipt is written on the interrupt path too (`main()` catches `KeyboardInterrupt` outside `cmd_chat`, so the promise "written even when it fails" was false on the one rung this slice added); `_write_usage` unlinks its temp file when the write or the replace fails, instead of dropping one hidden report per run into the target's directory; it catches `ValueError`/`TypeError` as well as `OSError`, because `json.dump(..., ensure_ascii=False)` on a surrogate raises `UnicodeEncodeError` and used to crash the verb *after* the answer was already on stdout; `--usage-file ""` says so rather than vanishing; a non-`-z` receipt no longer reports `completed: true` beside a queued approval; a `pending_approvals` that is not a list is reported as unreadable instead of being exploded into one fabricated id per character; `-f /dev/tty` is refused rather than blocking forever, which the "a terminal is never read" rule had covered only for `-f -`; the OSC/DCS branch of the escape regex is bounded, so one stray `ESC ]` no longer swallows every character to the next BEL across newlines, and an unterminated sequence no longer leaks `0;rm -rf /` onto stdout as visible text; the answer survives a stdout that cannot encode it, instead of turning a completed turn into an uncaught exit 1; and `_read_body` applies its bound in characters, so a 3,000-character multi-byte body is no longer cut mid-character and misreported as "not UTF-8 text".

One test was replaced rather than kept: `test_the_usage_file_is_replaced_atomically` passed under a plain truncating write — both its assertions hold there — so it pinned "the file was overwritten", not atomicity. The new one kills the write half-way and asserts the **previous** report is still intact, which is the property that actually distinguishes the two implementations, and it goes red under `open(path, "w")`.

51 tests; 23 mutations of the shipped behaviour each turn at least one of them red. The headline is unchanged at 122/697.

### 2026-09-18 — the cost meter tells a measurement from a guess

Not a Hermes row of its own, but the reason H002's spend report ships as a schema of nulls, so it is recorded here with the same evidence discipline. `cost_tracker` had two ways to be confidently wrong. The record site in `_record_interactions` passed the agent's **configured** model, and `AgentConfig.model` defaults to `google/gemma-4-31b-a4b` while not one of the 18 agents in `agents/_system/agents.yaml` sets `model` — so the first term of `configured or agent_route or "default"` was always truthy, the two fallbacks were unreachable, and a 1M/500k-token Claude turn metered at `total_cost_usd 0.0`. And `_price_for` ended in `return MODEL_PRICES["default"]`, so an id the table did not recognise was billed $3/$15 — a number an owner could not distinguish from a measurement, feeding the same `spend_today_usd()` that backs the daily-cap refusal.

The orchestrator now publishes `_last_models[agent_id]` — the id the router actually bound — on both the streaming path and the parallel fan-out, cleared per turn for the same reason the route and latency maps are, and left blank when `_timeout_inputs_for` could not get an answer from the router (substituting the configured model there would reintroduce the same bug). `_price_for` returns `None` for an unmatched id; `record()` counts that call's tokens and withholds its dollars; `get_summary()` reports `priced` per agent and `unpriced_calls` overall, mirroring the distinction `llm/cost_estimator.estimate_cost` already drew; `apm_summary()` carries the count through totals, per agent and per model, so the row that cannot be priced names the model to add. `record()`'s default argument is now `UNPRICED_MODEL` rather than `"default"`. `/api/analytics/model-tiers` gained an `unknown` bucket, because an unpriced turn falling through to `standard` claims a mid-priced cloud model nobody measured; the exact-key assertion in `tests/test_memory_endpoints.py` was updated with its reason, not loosened.

Seven behaviours were red-proofed by neutering each in turn and confirming a named test went red, then restoring the file byte-identically (md5 checked). Evidence re-pins: eight rows citing `agents/core/orchestrator.py` whose hashes still matched the inspected base (H146, H298, H363, H364, H449, H671, H673, H679) were re-pinned after the full suite ran green; H060, H061 and H398 were already stale at the base and are untouched. The headline is unchanged at 122/697 — this slice claims no row.

Still open on the same subject, and deliberately out of this slice: `/api/admin/stats` builds its records as `{'model': r.route_name or 'unknown'}` (`admin.py:573-579`), so cloud traffic there renders $0.00 through `estimate_cost` with the `priced` flag dropped; and the meter still bills a cached prefix at the uncached rate, over-billing the tokens DRA-24 exists to discount.

### 2026-09-18 — a turn can name the approvals it queued

The governance clause of H002 says a one-shot run must queue what the kernel would queue and exit non-zero **with the pending-approval id**. The id existed and was thrown away: the gated Tool-RPC path returns it beside `reason="approval_required"`, the tool loop turns that into one fixed sentence, and the turn returns a plain string. Every caller — `/chat`, the HUD's stream, `nerva chat -z` — was told an approval was due about something it could not show, poll or link to.

`agents/core/turn_approvals.py` is a per-turn collector. The ContextVar holds a **mutable list**, not a value a child re-sets: a gated tool call runs under `asyncio.create_task(..., context=...)`, which copies the context, so a `set()` in the child would never reach the turn awaiting it — the same reason `kernel/binding._OneShotDecision` hands its decision across that copy by mutation. Both gated enqueue sites in `tool_rpc.py` record the id they just queued, and their return values are unchanged. `handle_input` and `handle_input_stream` bind a collector beside the existing `bind_turn_action_origin` and reset it in the same `finally`; `bind_turn_approvals` **adopts** a sink the caller already opened — that is how `/chat` reads the ids back after the turn has reset its own binds — and otherwise binds a fresh one, so a voice or CLI turn can never append into a neighbouring turn's list. Outside a turn the recorder is a no-op, so the background autonomy ticks that reach the same enqueue sites record nothing.

`ChatResponse` gains `pending_approvals: list[int]`, the `/chat/stream` end event carries the same field, and `frontend/src/api/schema.gen.ts` was regenerated from the live `app.openapi()` dump. Both failure paths report as well: a turn that queued an action and then raised still left those rows on the queue, so the constant `"Internal error."` and the streamed `Eroare internă.` carry the ids instead of an empty list — reporting `[]` there would tell a caller nothing is pending while a row it cannot name is.

**Reporting only.** Nothing added approves, executes, transitions or unblocks a queued task; the only writes are appends to an in-process list and a response field. That is red-proofed rather than asserted: a test runs against a real `TaskQueue` and checks the reported row is still `status="proposed"` with `decision=None` and `result=None`, and it goes red when the record site is made to auto-approve. Ten behaviours were red-proofed in all, each by neutering it and naming the test that went red, then restoring byte-identically. The pinned SSE end-event shape in `tests/test_aud7_sse_hotpath.py` was updated with its reason; the exact-equality assertion was not loosened.

Evidence re-pins: rows citing `agents/core/orchestrator.py` (H146, H298, H363, H364, H449, H671, H673, H679), `agents/core/tool_rpc.py` (H146, H298, H449, H595) and `agents/web.py` (H130, H135, H139, H364, H671) were re-pinned where their hashes still matched the inspected base, after the suite ran green. H060, H061, H398, H287, H305 and the three rows citing `schema.gen.ts` were already stale at the base and are untouched. The headline is unchanged at 122/697 — this slice claims no row; it is what makes H002's `pending_approvals` path real rather than conditional on an older hub.

### 2026-09-18 — six stale rows re-evaluated, and the shortcut refused

A 25-agent sweep over the 143 rows that had never been reviewed returned six as *"already equivalent — nothing shippable left"*: H270, H288, H456, H477, H510, H557. Six rows of free headline progress, if the claim held. It did not, and refusing it is the point of this entry.

Each row was re-read against the live code by an independent assessor working from the ledger row's own text rather than the triage's summary, and each assessment was then handed to a skeptic whose stated default was that an `equivalent` recommendation is wrong. **All six came back `partial`, unanimously, at high confidence, and the skeptic agreed with every one.** `scripts/hermes_status.py` refuses an `equivalent` with a non-empty `remaining`, and every one of the six had something to name.

The frozen `nerva_evidence` was nevertheless badly stale on most of them, and correcting that is the delivery. H510's "no Host-header validation anywhere" stood against `agents/core/host_policy.py`, 204 lines whose docstring names DNS rebinding, `parse_allowed_hosts` refusing `*` and suffix wildcards at boot, and a `_host_guard` returning `{"error": "host not allowed", "code": 400}` — verified live, `Host: evil.test` gets 400 on `/status`, `/dashboard` and `/api/agents` where the real host gets 200. H456's "no per-item toolset allowlist" stood against `agents/core/job_toolsets.py`, where `toolset_scope()` nests `parent.names.intersection(names)` so a child can only ever narrow, enforced at the offering boundary in `tool_profiles.py` rather than only at construction. H557 was recorded `missing` while its headline claim — the MCP tool-name collision — had been fixed in #1042 by `MCPManager._resolve`, which returns `ambiguous_tool` rather than picking whichever server came first in dict order.

What keeps each row `partial` is now named precisely instead of "Reevaluare pe cod". H510: the `_PROBE_PATHS` exemption means `/healthz`, `/readyz` and `/metrics` answer a rebound name, so an attacker page reads the full Prometheus body and the `/readyz` detail cross-origin — the middleware's own comment admits it, and it was reproduced live. H456: a job cannot pin its own reasoning effort; `hybrid_router` reads only the global admin setting. H477: the discovery half, with no `/v1/toolsets` equivalent. H288: three unmet cron clauses, the per-run wall clock among them. H557: no provider-agnostic repair of a third-party server's JSON Schema. H270: no write-side policy for environment-variable names at all.

**Two of the triage's own findings were wrong, and both were checked by hand rather than taken on report.** First: `stdio_env_baseline` applies per-server `env` overrides unfiltered in the *strict* path as well as the legacy one (`agents/core/mcp/client.py:141-142`; the docstring says it is deliberate — "explicit per-server overrides always win"), so turning `JARVIS_MCP_STDIO_ENV_BASELINE` on does not close it. That is recorded as **latent**, not as a live hole: `MCPServerConfig` has no `env` field, `to_config` does not export one and `load_from_config` does not read one, and the only production caller passing an override is Nerva's own WorldView writer with an in-repo secret. Second, and the concrete next slice: `MCPServerConfig` sets no `model_config`, so pydantic's default `extra="ignore"` makes `POST /api/admin/mcp {"env": {"LD_PRELOAD": "/tmp/evil.so"}}` answer 200 and **silently drop** the key instead of refusing it, with no test pinning either behaviour.

No production code changed in this slice, and **the headline is unchanged at 122/697**. `missing` goes 94 → 92 (H477 and H557 were recorded `missing` and are really `partial`), `partial` 325 → 327, current reviews 67 → 73. Six rows move from an inherited verdict to a reviewed one and not one of them gains completion credit — which is the correct outcome, and the reason the sweep's own verdict was not simply written down.

### 2026-09-18 — H042 a taken port names itself instead of a raw errno

`serve.py` gains `probe_bind(host, port)`, called from `main()` after the posture guards and before uvicorn binds. A busy port prints the exact address, the command that identifies the holder (`nerva status`) and the way out (`JARVIS_PORT`), then exits **12**; `EACCES` on a privileged port exits **13**. The point is the *distinction*: uvicorn's `STARTUP_FAILURE` is **3** for every startup failure alike, so until now "the port is taken" and "the lifespan crashed" were the same exit code to a supervisor and the same wall of traceback to the owner. That collision was the defect, not the wording.

**The probe is a diagnostic, not a lock, and the safety case is the whole design.** It binds and closes immediately, reserving nothing — so the probe-to-bind race is real and deliberate, and losing it falls back to exactly today's raw error. Any `OSError` outside the two named arms is swallowed, because an unexpected probe failure must never turn a boot that would have worked into a refusal. The socket **constructor sits inside the guarded region** as well, and that arm is load-bearing rather than theoretical: `JARVIS_HOST=::1` on a box with no IPv6 stack raises `EAFNOSUPPORT` from `socket.socket()` itself, and a first cut that built the socket above the `try` replaced uvicorn's one-line `could not bind on any address` + exit 3 with an 8-frame traceback + exit 1 — the diagnostic for H042 inflicting the exact ergonomics failure H042 exists to remove.

It also refuses to be stricter than the real bind. On POSIX it sets `SO_REUSEADDR`, because `uvicorn.Server.startup` binds via `loop.create_server` and asyncio sets it there (`reuse_address = os.name == "posix"`); a probe without it would refuse a port merely holding a TIME_WAIT connection from the instance the owner just Ctrl-C'd — a restart uvicorn would have completed. That half is *executed*: a test reproduces the TIME_WAIT state, asserts a plain bind really is refused there, and then watches the probe stay silent. The Windows half is read off asyncio's source and has never been run here; the test skips off POSIX and the docstring says so rather than implying coverage.

9 probe tests, and **both exit codes are asserted by execution rather than by reading the branch**. The `EACCES` arm cannot be staged as root, where a sub-1024 bind simply succeeds, so it runs in a child dropped to uid 65534 with `setpriv` — with every premise (POSIX, root, `setpriv` present, `ip_unprivileged_port_start > 1`, a child that actually reached `probe_bind`) checked and skipped on rather than faked. A child that reached the probe and stayed silent is asserted as a failure, not skipped.

**H042 is recorded partial, and the missing half is the larger one.** The row is start, check *and stop*: Hermes ships `hermes dashboard --status/--stop`, backend ready sentinels, a ready file and a machine-readable `BACKEND_PORT_IN_USE`. Nerva has `nerva status` — which reads the HTTP surface, so it cannot report a hub that is starting or wedged before the port opens — and Ctrl-C. This slice signals the conflict as an exit code and an English sentence: enough for a supervisor, not enough for a caller parsing a status stream. `--isolated`, `--skip-build`, `--no-open`, the SSH session-token file and the owner-nonce are all absent too.

**One correction to the frozen evidence.** The 2026-09-07 audit recorded "no --status" for this row; `nerva status` has existed since the unified CLI (`agents/cli/nerva.py:101,481`). The row says so now. The headline is unchanged at 122/697 — H042 moves from an inherited verdict to a reviewed one and claims no completion credit.

**A known limit, in the safe direction.** The probe picks a single address family from the host string while uvicorn binds every address `getaddrinfo` returns, so a dual-stack name like `localhost` is probed on v4 only and can miss a conflict held on the v6 address. It misses *silently* — uvicorn then reports it exactly as it does today, which is the only direction this probe is allowed to be wrong in.

### 2026-09-18 — H495 a credential cannot reach a log record

`agents/core/security/log_redaction.py` adds `SecretRedactionFilter`, a `logging.Filter` that runs every record's message and its `args` through `SecretScanner.redact` before any handler writes it. The enable flag is snapshotted at import, so an agent-authored mid-session write to `JARVIS_LOG_REDACTION` cannot disable it — Hermes's `_REDACT_ENABLED` rule, ported deliberately rather than reinvented. A length and substring pre-check runs before any regex: about 8.75 µs per clean record, ~1.9× faster than the full scan. (The build report claimed 17.22 µs and ~2.1×; that did not reproduce on the same corpus, and the row records the measured figure.)

**The review found two majors, and either would have sunk the slice.** First, the module's own docstring tripped the AUD-14 raw-env-read ratchet. The ratchet greps file text line by line for `os.environ[`, the docstring's example contained a literal subscript, and so `tests/test_o26_p2_env_config.py` was **red in the delivered tree** — this could not have merged. The example is now prose, with a parenthetical naming the ratchet so the next editor does not reintroduce it. Second, and worse: `install_log_redaction()` walked `logging.getLogger().handlers` only, but `uvicorn` and `uvicorn.access` set `propagate=False` and own their handlers, so their records never reach a root handler. The production HTTP server's own access and error logs — exactly the ones that carry an `Authorization` header — were structurally unreachable by the filter, and the build report's gap disclosure had named a different mechanism and missed this case entirely. `install_log_redaction_everywhere()` now covers every handler owned by any logger in `logging.Logger.manager`, and a test drives a real uvicorn `dictConfig` and asserts a key in an access line comes out masked.

Three minors were fixed in the same pass. The length floor could be defeated by an extra pattern whose *name* collided with a built-in — it now identifies extras by regex **shape**, one-to-one against the built-ins, and returns 0 (fails closed) on a duplicate name, an unknown name, a changed source or a scanner exposing no `_compiled`. An ordinary `%`-format bug was being swallowed into a bare `[redaction-unavailable]`, replacing logging's loud diagnostic with an ambiguous one; it now emits `[log-format-error]` with the message repr, the args repr and the exception, all run through the scanner first because either may carry a secret. And the test fixture popped an ambient `JARVIS_LOG_FILE` and never put it back, corrupting the rest of the pytest session.

52 tests; every fix red-proofed by neutering it and naming the test that went red, then restoring byte-identically.

**H495 is recorded partial, and the gap is large on purpose.** Hermes applies its redactor to logs, verbose output, tool output, approval prompts, gateway messages, transcripts and memory. This is the logs. The row's own rationale names what still matters most and none of it is here: the hash-chained audit DB, where a `cat .env` from `terminal_run` permanently writes a live credential into an append-only log that by design cannot be edited; the decision-inbox card the owner reads on a phone; task payloads; terminal output; and the observability exports, which Hermes scrubs unconditionally with no knob. Nor is the second mask mode — the syntactically *invalid* `«redacted:ghp_…»` sentinel for file reads, which exists because a masked-but-plausible key gets written back by an agent and silently kills the credential.

Two ways this control could quietly cover less than it claims were named in the row rather than smoothed over: the `loggerDict` walk fell back to root-only if it raised, and `_cover` swallowed a per-handler failure. **Both are now closed, and the blocking SAST gate is what forced it.** Bandit flagged the two swallows as new findings (B110, B112). Only one deserved a suppression — `SecretRedactionFilter.filter`'s last-ditch blank, where a `logging.Filter` that raises takes down the caller's log call and the scanner has already failed — and it carries `# nosec B110` with that reason. The other two became signals: `_cover` returns `(covered, refused)`, the installers publish the figure through `uncovered_handler_count()` and warn naming how many handlers are writing unredacted, and a registry walk that raises warns that coverage fell back to root-only. A gate that only ever gets silenced teaches nothing; this one found a real hole the review had already written down as acceptable.

The same push restores `agents/core/turn_approvals.py`. The H495 commit carried a stale copy of that file out of its build worktree and dropped the `if sink is None: return` guard both its ancestors have — which does not merely lose an id: `record_pending_approval` runs after `tool_rpc` has queued the row, so `ToolRPCServer.handle` raised `AttributeError` at every surface reaching a gated tool with no turn bound, and `POST /api/toolrpc/call` answered 500 where it promises 422 with the task id. Three tests on `max/turn-approvals` now pin that no-op at the function, the RPC surface and the HTTP route.
