# FB tester-call — triaj lead-uri + kit de răspuns (2026-07-10)

> Răspunsul la postarea personală de recrutare alpha (varianta „Short Personal Post" din
> [`INVITE_MESSAGE.md`](INVITE_MESSAGE.md)). Asset **intern al ownerului** — reflectă comentarii
> publice de la oameni care s-au oferit voluntar să testeze pe postarea proprie a ownerului.
> Nu se publică. Leagă-l de Lane A / **A7** din [`BACKLOG.md`](../../BACKLOG.md) („Recruit 1–3
> design partners").

---

## Snapshot (Jul 8–10)

| Metric | Valoare |
|---|---|
| Afișări / vizitatori unici | **39.642** / 24.182 |
| Interacțiuni | 165 |
| Reacții | 78 (77 👍/❤️, 3 😆) — **0 angry, 0 sad** |
| Comentarii | 67 |
| Salvări | **17** |
| Distribuiri | 3 |

**Citire rapidă:** engagement mult peste ținta „2–3 prieteni". Ton cald (zero reacții negative,
în ciuda glumelor „Ultron/card skimming"). 17 salvări pe o postare de recrutare = intenție reală.
Semnalul e *prea mare* pentru capacitatea de suport 1:1 a ownerului pre-1.0 → **filtrul de screening
e esențial**; nu răspunde tuturor cu „hai în test", răspunde cu întrebările de auto-calificare.

**Regula de capacitate:** ținta rămâne **1–3 testeri instalați** (per decizia GTM). Restul intră pe
o listă de așteptare politicoasă. Alege pe cine instalezi din bucket-urile A și C, nu din numărul brut
de „Jarvis".

---

## Triaj lead-uri

Filtru (din [`2026-07-tester-call-ro.md`](../recruiting/2026-07-tester-call-ro.md)): **Win 11 / Linux**
+ una din două: **GPU ≥ 8 GB VRAM** *sau* **cheie API proprie cu billing** (OpenAI/Anthropic/Google).

### A — Semnal calificat (hardware/experiență declarate; fit mare) → DM prioritar
| Persoană | Ce a spus | De ce contează | Următorul pas |
|---|---|---|---|
| **Balanescu Mircea Gabriel** | rulează Qwen 120B local + „groq" 70B pe un mini | rulează deja modele mari local — host ideal | DM screening; candidat tester **și** sparring tehnic |
| **Eugen Octavian** | „128gb ram și 5090FE" | hardware top — poate rula orice local | DM screening; potrivit pentru profilul „local greu" |
| **Luca Moretti** | setup mare (store de ~300GB), rulează frontier, s-a oferit să ajute la îmbunătățiri | foarte implicat, opinat, vrea cloud/frontier | DM personal — canalizează energia; vezi nota* |

\* Luca e mai degrabă colaborator + evanghelist decât tester „liniștit". Are teze puternice
(pro-frontier, sceptic pe LLM local). Nu-l contrazice public; folosește-l pentru feedback de
arhitectură și pentru poziționarea hybrid/local.

### B — Lead-uri calde („Jarvis" / „interesat") → trimite DM-ul de screening
Fără hardware declarat încă; toți au nevoie de cele 4 întrebări de auto-calificare înainte de „da".

Ion Artin · Maletici Miro (a scris explicit „aș dori să testez") · Roxana Taiss · Kirita Alex ·
Gabi Manole · George Marius Puscas · Dragoș Rădulescu · Dan Lupu · Andra Dobre · Dan Antonescu ·
Ovi Ovidiu · Clau · Raul Cosmin · Bogdan Nicolae · Negaci Viorel · Andrei Croitoru.

**Marginal (screening dar probabil low-commitment):** Razvan Bodnariu — „doar noaptea pe laptop,
în rest tel/tabletă". Angajamentul zilnic + mașină fixă e cheia; setează așteptările din DM.

### C — Colaboratori / cursanți (nu testeri clasici, dar valoroși)
| Persoană | Ce a spus | Următorul pas |
|---|---|---|
| **Stefan Vintila** | vrea OpenRouter + OpenAI-compatible + local; rulează deja alt „Jarvis" care controlează Windows | power-user; **deja livrat** (vezi reply #4). DM cu pointer la `/model` + OpenRouter → tester puternic |
| **Iulian Tu** | „vreau să învăț să construiesc, nu doar să testez. Ai nevoie de oameni în echipă?" | candidat contributor → trimite `README` + `CONTRIBUTING.md`; invită-l pe repo (vezi reply #7) |

### D — Întrebări de răspuns public (transformă scepticii în încredere — lurkerii citesc)
| Persoană | Întrebarea | Reply |
|---|---|---|
| Alexandru Timar · Octavian Preda | cheia API rămâne locală sau trece prin serverele voastre? | **#1** |
| Tudor ML | macOS / M4? | **#2** |
| Cristi Simion | să folosească subscripția în loc de API? | **#3** |
| Stefan Vintila | e open-source? pot adăuga OpenRouter / OpenAI-compatible? | **#4** |
| Robert Olah | local-only pe 8GB — chiar e utilizabil? | **#5** (ai răspuns deja; varianta curată mai jos) |
| Andrei Laurentiu Gubernu | „nu vă recomand pe calculatorul personal" | **#6** |
| Bogdan Gabriel Fuerea | „8GB VRAM… fă-l TUI-only, waste of memory" | **#8** (feedback real de produs — vezi BACKLOG) |
| Dan Truția | de ce doar Win 11, nu Win 10? | răspuns deja de comunitate (EOL). O propoziție opțional. |

### E — Zgomot / glume (fără acțiune)
Alin Giugea (bere; „card skimming de Râmnicu Vâlcea") · Tudor Juravlea (#tokenmaxxing) ·
Catalin Ivascu (Ultron) · Madalin Alexandru („teste pe banii testerului") · Ion Udrea (închiriere
DGX Spark — off-topic) · flame Win10 Eugen Paun ↔ Dan Truția.
> Semnal ascuns în glume: „banii testerului" + „card skimming" = anxietate reală pe **cost + încredere**.
> Pre-întâmpinat acum în copy (vezi FAQ + varianta FB actualizată).

---

## Kit de răspuns (copy-paste, RO)

> Ton: onest, scurt, fără hype. Nu promite ce nu e în matricea de suport alpha.

**#0 — Nudge pentru comentariile doar cu „Jarvis"**
> Mersi! 🙏 Ca să nu se piardă în comentarii, scrie-mi în privat `Jarvis alpha` și îți trimit
> cele câteva întrebări scurte de potrivire.

**#1 — Cheia API (încredere) — *cel mai important reply, îl citesc toți***
> Bună întrebare. Cheia **rămâne strict la tine**: stă în fișierul tău `.env`, pe mașina ta, iar
> aplicația vorbește **direct** cu OpenAI/Anthropic/Google — nu trece prin niciun server de-al meu
> (nu am un backend care să vadă cheia sau conversațiile). E open-source, deci poți verifica singur.
> Dacă vrei zero apeluri externe, există **mod strict-local**: rulezi pe GPU-ul tău, fără nicio cheie.

**#2 — macOS / Apple Silicon**
> Da, `./install.sh` acoperă și macOS, iar un Mac cu chip M (memorie unificată) e de fapt o gazdă
> foarte bună pentru modele locale. Nu e încă în matricea oficială de suport alpha (pre-1.0, suportul
> sunt eu), dar dacă ești pe M4 scrie-mi — chiar vreau măcar un tester pe Mac.

**#3 — Subscripție vs. cheie API**
> Din păcate abonamentul ChatGPT Plus / Claude Pro **nu** include acces API — sunt lucruri diferite.
> Ai nevoie fie de o cheie de la platformă cu billing (câțiva dolari/lună la testare), fie mergi
> **complet local** cu un GPU de 8+ GB și nu plătești API deloc.

**#4 — Open-source / OpenRouter / OpenAI-compatible**
> Da, e open-source. **OpenRouter e deja integrat** (o singură cheie → sute de modele pe endpoint
> OpenAI-compatible, cu hot-swap din chat: `/model <id>`), plus local prin LM Studio/Ollama. Orice
> endpoint OpenAI-compatible merge prin `base_url`. Dă-mi un DM și-ți arăt exact unde se configurează.

**#5 — Local-only pe 8GB VRAM (onest)**
> Sincer: pe 8GB rulezi bine bucla de asistent guvernat + voce (Whisper) + managementul memoriei pe
> un model mic. Pentru raționament „frontier" ai două opțiuni: un model local mai mare (mai mult VRAM
> sau offload în RAM DDR5 — scade viteza) **sau** hybrid (un model mare în cloud ca orchestrator).
> Recomandarea implicită e **hybrid**. Eu testez și pragul de la care devine inutilizabil — de-aia
> caut testeri pe configurații diferite.

**#6 — „Nu recomand pe calculatorul personal"**
> Înțeleg reținerea — de-aia am pornit exact invers față de valul de agenți autonomi: orice acțiune
> ireversibilă **se oprește și cere aprobare cu preview**, totul intră într-un audit log
> tamper-evident local, iar în configurația implicită datele nu pleacă de pe mașină. E open-source,
> deci se poate inspecta linie cu linie. Cine vrea și mai strict → mod strict-local, fără apeluri
> externe.

**#7 — Cursant / „ai nevoie de echipă?" (Iulian Tu)**
> Super că vrei să și construiești, nu doar să testezi. E open-source — `github.com/andrei649/jarvis-hub`,
> vezi `CONTRIBUTING.md` pentru cum e organizat. Dă-mi un DM cu ce te-ar interesa să atingi și îți
> arăt câteva zone bune de intrare.

**#8 — TUI-only / headless (Bogdan Gabriel Fuerea)**
> Fair — poate rula local-only, cloud-only sau hybrid, iar VRAM-ul e folosit doar pentru voce +
> management. Ideea de mod headless/TUI (fără UI-ul greu) o notez ca feedback real. (→ BACKLOG)

**#9 — DM de screening (standard)** — folosește „First DM Reply" din
[`INVITE_MESSAGE.md`](INVITE_MESSAGE.md): cele 4 întrebări (OS · GPU/VRAM · cheie API cu billing ·
angajament 2–4 săptămâni + check-in). Cine răspunde clar → ghid de instalare + prima sesiune
supravegheată.

---

## Checklist owner (după această postare)

- [ ] Răspunde **public** la #1 (cheie API) și #6 (siguranță) — sunt cele care conving lurkerii.
- [ ] Postează #2 (macOS), #3 (subscripție), #4 (OpenRouter) ca reply-uri scurte sub întrebările lor.
- [ ] DM cu #9 (screening) către bucket-urile A + C și 2–3 nume din B (nu toți deodată — capacitate).
- [ ] Bucket A/C: alege **1–3** pentru instalare; restul → listă de așteptare politicoasă.
- [ ] Iulian Tu → trimite repo + `CONTRIBUTING.md`.
- [ ] Reîmprospătează A7 în `BACKLOG.md` când primul tester non-owner e instalat ≥2 săptămâni.
