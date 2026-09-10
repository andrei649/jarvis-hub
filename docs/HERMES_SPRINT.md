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

Cele opt PR-uri #1061–#1068 raportate la încheierea lucrului sunt toate integrate, la
fel și livrările #1070–#1075 din sprintul curent.
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
4. **Execuție de cod:** K0 și K1 sunt livrate — autoritatea rulării, apoi `execute_code`
   pe suprafața de unelte (implicit oprit). Rămân sesiunile persistente K2/K3 și
   scurgerea stdout într-un fișier; H305/H595/H660 rămân parțiale.
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
