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

Cele opt PR-uri #1061–#1068 raportate la încheierea lucrului sunt toate integrate, la
fel și livrările #1070–#1083 din sprintul curent; #1084 este în lucru.
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
