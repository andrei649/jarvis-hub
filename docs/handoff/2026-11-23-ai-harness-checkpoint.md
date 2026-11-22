# Reluarea lucrului la Nerva

Salvat la 23 noiembrie 2026, 00:14 EET. Obiectivul de dezvoltare este în pauză.
Branch-ul este `codex/harness-agent-selector`. Commitul de implementare este
`8ee710ece80cb2a2f0059183fc66d858d1c2661b`, peste `a2b9b4c23152be7387ff2be32186831a54e180c1` din draftul #1379.
Pentru inventarul exact al celor 315 fișiere modificate, rulează `git show --stat 8ee710ec`.

## Ce poți folosi

- În Chat și Cockpit poți compara răspunsuri de la agenți locali, urmări lucrul în paralel pe board și revizui rezultatele. Clientul mobil include fluxuri de chat și comparație.
- Poți salva în Obsidian informațiile aprobate, redeschide nota sursă și recupera faptele corectate. La reluare, selectează seiful privat existent, din afara checkoutului.
- Poți preda o procedură unui agent și aproba modificările din Chat sau Cockpit după ce vezi diferențele. În proba cu Ollama, Frigga a folosit valoarea veche cât timp corecția aștepta aprobarea și valoarea nouă într-o conversație proaspătă după aprobare și repornire. Ultron a rămas în afara domeniului procedurii. Proba a folosit date sintetice și modul Direct reply.
- Sunt incluse fluxuri de generare și export pentru Word, Excel, Blender, Photoshop și Godot.

## Unde s-a oprit investigația

Cu raționamentul implicit, o cerere către modelul local nativ `andrei-fast:latest:local` a generat 5.785 de tokeni într-un context de 8.192 și a lăsat răspunsul vizibil gol. Modul Direct reply a dat un răspuns utilizabil. Motivul de terminare raportat de Ollama și prezența câmpului de raționament în ultimul mesaj au rămas neconfirmate.

1. După reluarea dezvoltării, pornește un hub temporar cu Ollama pe loopback și repetă aceeași întrebare sintetică pentru Frigga pe `/chat` și `/chat/stream`. Compară setarea implicită cu Direct reply. Păstrează motivul de terminare, lungimile câmpurilor și contoarele de tokeni. Conținutul raționamentului rămâne privat.
2. Pe mașina de lucru există deja reproducătorul în `memory_logs/selector-qa/local-empty-recovery/physical.py`. Ultima rulare a pregătit scenariul. Rezultatele pentru bugetul limitat și pentru streaming sunt încă deschise.
3. Dacă reproducerea confirmă epuizarea bugetului fără text vizibil, verifică o singură reîncercare pe același model local cu `think: false`, pentru cereri text implicite și în limita de timp inițială. Păstrează comportamentul cererilor cu instrumente și al setărilor explicite. Punctele de intrare sunt `agents/core/agent.py`, `agents/core/llm/base.py` și `tests/test_ollama_no_think.py`. Această recuperare automată rămâne de implementat și verificat.

## Verificări disponibile

- Ultima rulare completă pentru HUD a trecut 3.562 de teste. Regresia focalizată pe Linux a trecut 256. Pe Windows au trecut 21 de teste de paritate HUD și 65 pentru status, scheme și fișiere web. Aprobarea corecției a fost verificată în browser la lățimi de 320 și 390 px.
- Înaintea publicării au trecut suitele pentru editarea și trimiterea procedurilor, procedurile învățate, manifestul web și opțiunea Ollama fără raționament. Au trecut și verificarea TypeScript, sincronizarea statusului, verificarea registrului Hermes și validarea politicii de dezvoltare.
- Pe Linux s-au colectat 37.652 de cazuri de backend și s-a omis un modul. Execuția integrală a backendului și verificarea pe un telefon fizic rămân deschise.
- Dovezile locale sunt în `memory_logs/selector-qa/ACCEPTANCE.md`, `procedure-revision-live/run-7d12cf9c/acceptance.json` și `procedure-revision-browser/run-1682d8fb/receipt.json`. Ultimele două căi sunt relative la `memory_logs/selector-qa/`.
