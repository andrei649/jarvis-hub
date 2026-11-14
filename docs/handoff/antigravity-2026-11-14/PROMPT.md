# Antigravity — dezvoltă Nerva până la produs complet

Folosește **Carbon, High**, modelul și setarea solicitate de owner, dacă sunt disponibile efectiv; raportează exact o eventuală diferență. Nu inventa identitatea modelului sau capabilități de tooluri. Preia dezvoltarea autonomă Nerva/Jarvis: finalizează produsul, apoi construiește avantaje demonstrabile față de Hermes/OpenClaw. Implementează și integrează funcții utilizabile; planurile și rapoartele sunt suport pentru livrare.

Citește [START_HERE](START_HERE.md), verifică branchul și manifestele, apoi începe. Ownerul autorizează dezvoltare, commits, push și draft PR-uri, precum și transferul sursei. **Nu face merge sau deploy și păstrează PR-urile draft.** Nu reactiva programe oprite ori servicii cu costuri implicit.

## Finalizează întâi integrarea reală

Branchul `codex/antigravity-handoff-20261114` livrează cumulativul V70 peste `686fcbf4f25ebfbb416b3a35dff29045163cffbd`, cu evidențe și handover. Verifică commitul primit; nu deduce succesul transferului din textul documentelor. Cumulativul V70 are463 căi delta față de main-ul fixat și include funcții absente din reconcilierea drafturilor.

V81 rămâne separat în draft #1363, head `702845ae45765583f996fdb5b2b08de9db6664bc`, tree `9deba0f24220f9f0f89fee585f2a923e549cecc1`. Compară cele două surse și integrează corecțiile mai noi fără pierderea cumulativului. Folosește worktree izolat, manifestele și probele. Nu suprascrie worktree-uri dirty, nu reseta munca altuia și nu aplica simultan patchuri cumulative și individuale care se suprapun.

Verifică CI pe head-ul exact. Ultima observație avea toate joburile terminate verzi, Linux Chrome trecut și Windows backend pending. Repară defectele confirmate, verifică typegen pinned și integrarea combinată pe Linux/Chrome/Windows. Un rezultat vechi, pending sau cancelled nu certifică noul candidat. Nu reintegra diagnosticul Chrome nesigur exclus. Reviewul update/restart blocat de platformă rămâne explicit incomplet; continuă lucrul independent fără a relansa aceeași acțiune blocată pe o cale ocolitoare.

## Livrează produsul și avantajul competitiv

Obiectivul fix rămâne **toate cele697 de contracte Hermes**, inclusiv H277 și cele anterior excluded. Stările înregistrate diferă: cumulativ171/482/8/36, V81 170/483/8/36; nu sunt o reevaluare actuală. Interoghează registrul sursei curente și păstrează inventarul/proveniența. Închide un contract numai când intrarea reală, comportamentul complet, erorile, autoritatea și interfața sunt implementate și verificate. Mocks, scaffolding sau area suites nu înseamnă acceptare live ori paritate completă.

Prioritizează fluxurile de la început la rezultat între CLI, API, HUD, Workspace și mobile: instalare și onboarding; skills/plugins și gateway; conversații/history/search/export; memorie și artefacte; backup/update/restart/recovery. Finalizează ce este început înainte să acumulezi alte interfețe parțiale. Compară donorul și refolosește implementări/teste existente, păstrând licențele.

Construiește diferențiatori concreți:

- Onboarding local-first simplu, diagnostic și recovery fără pierderea conversațiilor sau muncii.
- Workflows complete cu tools, artefacte și memorie, cu proveniență vizibilă și căutare utilă.
- Autonomie controlabilă: preview, consimțământ, revocare, anulare, rollback și rezultate incerte explicate corect.
- Fiabilitate fără dublări după răspunsuri ambigue, continuitate între interfețe, performanță și cost măsurate.
- UX coerent și accesibil pe desktop/mobile/CLI, inclusiv loading/error/empty și recuperare.

Nu fabrica arhive complete din loguri fără occurrence/branch/coverage. Definește câteva scenarii comparative reproductibile și măsoară task success, timp, recovery, erori și cost. Superioritatea față de concurenți trebuie demonstrată, nu dedusă din numărul de teste.

## Lucrează decisiv, cu probe proporționale

Ownerul autorizează înlocuirea regulilor repo învechite despre local-only, modele, resurse, ceremonie și checkpointuri. Înlocuiește obstacolele de proces cu reguli eficiente și justificare datată. Păstrează controalele care protejează securitatea, datele, identitatea, Kernelul, consentul și izolarea; respectă refuzurile platformei și nu falsifica probele. Nu folosi o schimbare de politică drept propria autorizație pentru efecte externe.

Alege un lot cu rezultat utilizabil, plan scurt și acceptare precisă, apoi implementează. Delegă numai dacă este permis și economisește muncă, cu responsabilități clare. Reproduce bugurile, rulează probe focalizate și integrarea afectată; suite complete la milestoneuri justificate. Folosește mediul proiectului și runnerul documentat, fără relaxarea permisiunilor pentru teste verzi. Separă full runs de composite/reruns și probele locale de CI/platform/provider/dispozitiv.

Menține un singur raport cumulativ cu base/head/tree, funcții, probe rulate efectiv, limitări și următorul pas. Păstrează rezultatele roșii și skipurile. Nu crea ceremonie nouă pentru fiecare pas și nu cere ownerului decizii reversibile de rutină. Când un prerechizit extern lipsește, numește contractul blocat și continuă alt lot executabil.

Continuă după primul lot verde. Obiectivul este produsul integrat, toate697 contracte evaluate onest și îmbunătățirile demonstrate. Contextul sau timpul epuizat nu înseamnă finalizare. Începe acum cu verificarea sursei, reconcilierea V70/V81 și livrarea următorului flux complet, fără merge/deploy.
