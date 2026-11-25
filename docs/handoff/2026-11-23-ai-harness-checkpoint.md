# Reluarea lucrului la Nerva

## Reluare pe 25 noiembrie — PR #1380

Proprietarul a autorizat publicarea și integrarea după CI verde. Reparația pornește de la `77d6db88`. Pe Linux au trecut cele 3.577 de teste HUD și ambele verificări TypeScript. Ambele bundle-uri reconstruite coincid cu cele din Git. Pe Windows au trecut 96 de teste de izolare a vaultului. Contul local nu a putut crea linkurile simbolice necesare celorlalte două cazuri. Verificarea GitHub cere executarea lor.

### Probleme deschise în afara reparației

- Pe Windows, exportul CLI al unei transcrieri într-un fișier se oprește la verificarea `os.fchmod`. Testul de integrare `test_cli_hubclient_through_asgi_reads_real_retained_storage` reproduce problema și exista pe `main` înaintea acestui PR. Pentru închidere, exportul trebuie să creeze atomic un fișier privat și să păstreze intactă orice destinație deja existentă.
- Pe `main` la `fba0345b`, verificarea OpenAPI raportează diferențe în tipurile generate, iar testul Workspace pentru streaming nu observă afișarea progresivă a răspunsului. Confirmarea necesită trecerea ambelor verificări pe noul commit din `main`. [CI](https://github.com/andrei649/jarvis-hub/actions/runs/45593832593) · [HUD E2E](https://github.com/andrei649/jarvis-hub/actions/runs/45593832666)

## Checkpoint pentru 24 noiembrie

Lucrul la harness este în pauză până la reluarea de către proprietar. Branch-ul este `codex/harness-agent-selector`. Punctul de plecare al acestui lot a fost `7f8c12ca05b2d58db5bac3be79c10172cc8fe286`.

- Pe Windows, comanda de import a arhivat șase fișiere sintetice, inclusiv unul binar. Copiile au fost identice la nivel de octet, arhivele au drepturi de acces private și istoricul separat a rămas la sursă. Testele acoperă și eșecul copierii, modificarea sursei în timpul operației și reîncercarea. Dovadă locală: `memory_logs/selector-qa/import-archive-windows/20261123T062521608Z-801a5bd7/summary.json`.
- Din Chat, Cockpit și clientul mobil poți alege un fapt salvat, confirma ștergerea și folosi Undo cât timp memoria vizată nu a fost modificată. În browser, anularea a păstrat ciorna și faptul. O selecție veche a fost refuzată, iar un fapt identic din altă memorie a rămas acolo. Dovadă locală: `memory_logs/selector-qa/chat-forget-acceptance/run-20261123-063056/receipt.json`.
- În trei conversații noi cu Frigga și Ollama local, codul sintetic a fost prezent în cererea către model și în răspuns înainte de ștergere și după Undo. Între ele, codul a lipsit din cerere, iar modelul a răspuns că nu îl cunoaște. Faptul de control a rămas în toate cele trei cereri. Conversația sursă și nota Obsidian de test au rămas intacte. Modelul a adăugat explicații la toate cele trei răspunsuri. Dovadă locală: `memory_logs/selector-qa/forget-ollama/run-f49c59a0/acceptance.json`.
- Registrul Hermes de pe branch conține **187 echivalente, 474 parțiale, 36 excluse** din 697 de capabilități. Au echivalență documentată 187/661 (28,3%) din domeniul activ. Verificare: `python scripts/hermes_status.py summary --json`.

**Stare verificată la 23 noiembrie 2026, 08:38 EET.** Ultimul commit de implementare este `a2f4581eca80a112f411b0462de34c867a431dd4`. Inventarul acestui lot este disponibil cu `git diff --name-status 7f8c12ca a2f4581e`. Importul Windows este în `dbc76fda`, iar recuperarea Ollama în `a3ce35f0`.

Au trecut integral cele 3.577 de teste HUD și cele 535 mobile. Ambele builduri web, verificările TypeScript și exporturile Android/iOS au trecut. Pe Linux, 310 teste backend selectate au trecut și unul a fost omis. Pe Windows, 110 teste backend selectate au trecut și 9 au fost omise. Comanda publică de import a trecut separat și pe versiunea finală. Colectarea completă pe Linux a identificat 37.680 de cazuri și un modul omis. Rezultatele sunt în `memory_logs/selector-qa/resumed-memory-ownership/`.

**Primul pas la reluare.** Verifică rezultatul CI de pe branch, apoi testează pe un telefon fluxul Chat → Remember message → Forget → Undo cu un fapt sintetic. Repornește clientul și verifică într-o conversație nouă că faptul restaurat revine. Rularea integrală a suitei backend rămâne deschisă. Seiful Obsidian privat și datele locale ale profilului se accesează separat de Git. Rapoartele QA menționate sunt locale, în `memory_logs/`.

## Checkpoint anterior

Checkpointul publicat la 23 noiembrie 2026, 00:14 EET, a încheiat sesiunea din noaptea precedentă.
Branch-ul este `codex/harness-agent-selector`. Commitul de implementare este
`8ee710ece80cb2a2f0059183fc66d858d1c2661b`, peste `a2b9b4c23152be7387ff2be32186831a54e180c1` din draftul #1379.
Pentru inventarul exact al celor 315 fișiere modificate, rulează `git show --stat 8ee710ec`.

## Dezvoltare reluată pe 23 noiembrie

Lucrul a continuat de la `7f8c12ca` pe același branch.

- Chatul și streamingul au recuperat răspunsul de la modelul local. Cererea cu plafon de 64 de tokeni s-a încheiat cu `done_reason=length` și zero caractere vizibile. După verificarea capabilității, aceeași cerere cu `think=false` a produs răspunsul sintetic corect în 8 tokeni. În ambele cazuri, utilizarea raportată însumează 72 de tokeni generați în două apeluri locale. Direct reply explicit și o cerere reușită cu buget automat au folosit câte un singur apel. Dovezile pe mașina de lucru sunt în `memory_logs/selector-qa/local-empty-recovery/run-3468375a/`.
- În Chat și Cockpit poți parcurge un document Word în pagini de câte 12.000 de caractere și poți atașa o clauză de la final. În Chrome, pe un document sintetic cu 25.081 de caractere, selecția de la poziția 24.020 a ajuns singură în atașamentul primit de furnizorul de test. Anularea a păstrat ciorna și a produs zero cereri de chat. Proba acoperă Chat la 1.440 px și Cockpit la 390 px. Dovezile sunt în `memory_logs/selector-qa/word-passage-pages/acceptance.json`.
- Au trecut cele 3.564 de teste HUD, verificarea TypeScript, ambele builduri web și cele 506 teste backend selectate pe Linux. Colectarea Linux a găsit 37.675 de cazuri și un modul omis. La rularea pe Windows, testul de arhivare după importul unui profil Codex s-a oprit inițial la `os.fchmod` în `scripts/nerva_import.py`. Corecția este verificată în checkpointul curent. Testul a folosit un profil sintetic. Rapoartele sunt în `memory_logs/selector-qa/resumed-harness/`.

## Ce poți folosi

- În Chat și Cockpit poți compara răspunsuri de la agenți locali, urmări lucrul în paralel pe board și revizui rezultatele. Clientul mobil include fluxuri de chat și comparație.
- Poți salva în Obsidian informațiile aprobate, redeschide nota sursă și recupera faptele corectate. La reluare, selectează seiful privat existent, din afara checkoutului.
- Poți preda o procedură unui agent și aproba modificările din Chat sau Cockpit după ce vezi diferențele. În proba cu Ollama, Frigga a folosit valoarea veche cât timp corecția aștepta aprobarea și valoarea nouă într-o conversație proaspătă după aprobare și repornire. Ultron a rămas în afara domeniului procedurii. Proba a folosit date sintetice și modul Direct reply.
- Sunt incluse fluxuri de generare și export pentru Word, Excel, Blender, Photoshop și Godot.

## Istoricul investigației Ollama de la 00:14

În prima probă, cu raționamentul implicit, modelul local a generat 5.785 de tokeni și a lăsat răspunsul vizibil gol. Modul Direct reply a dat un răspuns utilizabil. Reproducerea ulterioară cu buget controlat, soluția și verificarea pentru chat și streaming sunt descrise mai sus.

## Verificări de la checkpointul anterior (00:14)

- Ultima rulare completă pentru HUD a trecut 3.562 de teste. Regresia focalizată pe Linux a trecut 256. Pe Windows au trecut 21 de teste de paritate HUD și 65 pentru status, scheme și fișiere web. Aprobarea corecției a fost verificată în browser la lățimi de 320 și 390 px.
- Înaintea publicării au trecut suitele pentru editarea și trimiterea procedurilor, procedurile învățate, manifestul web și opțiunea Ollama fără raționament. Au trecut și verificarea TypeScript, sincronizarea statusului, verificarea registrului Hermes și validarea politicii de dezvoltare.
- Pe Linux s-au colectat 37.652 de cazuri de backend și s-a omis un modul. Execuția integrală a backendului și verificarea pe un telefon fizic rămân deschise.
- Dovezile locale sunt în `memory_logs/selector-qa/ACCEPTANCE.md`, `procedure-revision-live/run-7d12cf9c/acceptance.json` și `procedure-revision-browser/run-1682d8fb/receipt.json`. Ultimele două căi sunt relative la `memory_logs/selector-qa/`.
