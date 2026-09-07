# Hermes → Nerva — planul de absorbție

> **Directiva owner-ului, 2026-09-07:** *„vreau ca tot să fie în nerva — ce avem superior, păstrăm;
> ce nu avem, copiem; ce e sub hermes, facem update."*
>
> Sursa: [`docs/research/hermes-inventory-v2026.8.31/`](research/hermes-inventory-v2026.8.31/README.md)
> — 8.199 intrări, 53 de secțiuni, 17 MB, la adâncime de reimplementare.
> Ledgerul complet, mașină-lizibil: [`research/2026-09-07-hermes-absorption-ledger.json`](research/2026-09-07-hermes-absorption-ledger.json).

## Cum a fost făcut

20 de agenți, câte unul pe cluster de secțiuni. Fiecare a citit inventarul **și** a căutat în repo-ul
viu ce există de fapt — fiecare rând citează o cale din Nerva sau scrie `none`. Intrările brute au
fost rulate la nivel de **capabilitate** (un lucru pe care un om îl poate face), cu raportul de
comprimare notat per cluster, ca reducerea să fie vizibilă, nu tăcută.

**8.189 intrări brute → 697 capabilități.**

| | | | |
|---|---|---|---|
| **superior** 80 | **parity** 55 | **partial** 343 | **missing** 219 |
| **keep** 114 | **skip** 107 | **update** 258 | **copy** 218 |

Efort: 255×S · 289×M · 117×L · 36×XL.

## Regula de adaptare — singura non-negociabilă

> **Orice lucru copiat care produce un efect privilegiat aterizează ÎN SPATELE Action Kernel-ului,
> nu lângă el.**

Suntem în urmă pe suprafață și înainte pe guvernanță. Dacă absorbim cele 83 de unelte ale lui Hermes
fără kernel, ajungem la paritate pe funcții și **pierdem singura axă pe care conducem**. O funcție
portată care ocolește kernelul e o regresie chiar dacă merge.

`skip` e o decizie de primă clasă — dar motivul trebuie să fie despre produs, niciodată despre efort.
Cele 107 skip-uri sunt dominate de suprafață care nu servește utilizatorul Nerva: platforme de chat
regionale (DingTalk, Feishu, LINE, IRC), shell-ul Electron și pet-ul de desktop, runtime-uri de agent
deținute de vendor, deploy Nix, portalul de credite.

---

## Valul 0 — găuri funcționale, nu goluri de funcții

**Astea nu sunt lucruri pe care Hermes le are și noi nu. Sunt lucruri despre care Nerva crede că le
face și nu le face.** Se rezolvă primele, pentru că restul absorbției se sprijină pe ele.

### 0.1 — Uneltele sunt moarte pe drumul care rulează de fapt ⛔

`supports_tools = True` apare **exact o dată** în tot repo-ul: pe `LMStudioBackend`
(`agents/core/llm/base.py:443`). `ClaudeBackend`, `GeminiBackend`, `OpenRouterBackend`,
`VLMBackend` **și `OllamaBackend`** moștenesc `False` din ABC (`base.py:292`).

`agents/core/agent_runtime.py:97` închide tot runtime-ul de unelte pe flagul ăsta — *fail closed*.

Consecința: **în clipa în care un agent rutează spre cloud — exact drumul proiectat pentru munca grea,
și exact ce a spus owner-ul că e necesar fiindcă local nu duce contextul — modelul pierde complet
accesul la unelte.** Nu citește un fișier, nu caută, nu declanșează o acțiune guvernată. Devine un
model de chat. Local, funcționează doar prin LM Studio; nici măcar Ollama nu.

Fix: declararea corectă a capabilității per backend + traducerea schemei de unelte în dialectul
fiecărui provider. Kernelul rămâne pe drum — uneltele se aprind, guvernanța nu se stinge.

**Livrat 2026-09-07 (PR #1042).** `agents/core/llm/tool_dialects.py` traduce dialectul unic al
runtime-ului (forma OpenAI) în dialectul fiecărui provider și înapoi — blocuri `tool_use`/`tool_result`
la Claude, `functionDeclarations` pe subsetul OpenAPI acceptat + părți `functionCall`/`functionResponse`
cu thought signatures purtate între ture la Gemini, `/api/chat` cu argumente-obiect la Ollama;
OpenRouter vorbește nativ. `ClaudeBackend`, `GeminiBackend`, `OpenRouterBackend`, `OllamaBackend`
declară `supports_tools = True`; `VLMBackend` rămâne `False` deliberat. **Fiecare apel de la provider
trece tot prin `parse_openai_tool_calls`** — granița unică fail-closed — deci un `input` malformat de la
Claude ajunge în runtime ca `bad_tool_arguments`, exact ca unul de la LM Studio. Teste:
`tests/test_cloud_tool_turns.py` (39), inclusiv bucla guvernată cap-coadă peste Ollama.
*Nedovedit pe un provider live* — dialectele sunt construite din contractul documentat al fiecărui
API, nu dintr-un schimb capturat → `docs/OWNER_TASKS.md` **P15**.

### 0.2 — Modelul nu știe că există skill-uri
`agents/core/agent.py:124-128` construiește blocul de skill-uri din `context["skills"]`, și **nimic
din repo nu setează vreodată cheia aia**. Skill-urile sunt importate, semnate, pinuite — și invizibile.

**Livrat 2026-09-07.** `SkillLoader.prompt_catalog(agent_id)` produce rândurile (mărginit la 20 × 120
caractere; doar skill-urile pe care loader-ul le-ar executa — cele în carantină/sandbox nu sunt
niciodată anunțate; cele cu agenți declarați, doar agenților lor) și `Orchestrator._prompt_context`
le pune în context fără să mute contextul de intenție partajat. Setarea `llm.skills_in_prompt`
(implicit pornită) îl stinge. Teste: `tests/test_skills_in_prompt.py` (10).

### 0.3 — Nu există compactare în interiorul turei
`agents/core/agent_runtime.py:137` adaugă un mesaj de asistent plus un rezultat de unealtă pe apel,
până la 32 de iterații, **fără să măsoare niciodată lista care crește**. Compactarea există
(`context_compressor.py`) dar rulează între ture, nu în timpul lor. La iterația 32 se pierde muncă.

**Livrat 2026-09-07.** Fiecare tură după prima verifică `estimate_messages` față de un buget
(`llm.tool_loop_context_tokens`; 0 = 75 % din fereastra modelului minus rezerva de output, prag
minim 2.048). Rezultatele de unealtă mai vechi se pliază în plicuri de ≤512 bytes (`TOOL RESULT
COMPACTED`, cu head/tail) — niciodată șterse, niciodată reordonate, ca fiecare rezultat să răspundă
în continuare apelului care l-a produs — ultimele 2 iterații se pliază ultimele, iar un transcript
care tot nu încape oprește bucla cu un motiv numit și un eveniment
`tool_context_compacted{status=exhausted}`, nu cu o eroare de provider. Teste:
`tests/test_tool_loop_compaction.py` (5).

### 0.4 — Nicio poartă pe mesajele din grup
Vocabularul de gating al Nervei e o singură listă plată `allowed_user_ids`
(`agents/core/channels/telegram.py:26`). `require_mention`, detecția de mențiune, allowlist per
chat/topic, observe mode — zero apariții în repo. Un bot Nerva pus într-un grup **răspunde la fiecare
mesaj al fiecărui membru permis**, și fiecare mesaj din cameră devine context contaminat pe care
agentul raționează și acționează. E o graniță de autorizare, nu o comoditate.

**Livrat 2026-09-07.** `channels/group_policy.py` (`GroupPolicy`, `gate_message`), aplicat de
poll-loop-ul Telegram după allowlist-ul de utilizatori: DM-urile trec; într-un grup botul răspunde
doar la `@mențiune`, `/cmd@bot`, reply la el însuși sau `text_mention` (mențiunea e ștearsă înainte
ca modelul s-o vadă); `TELEGRAM_ALLOWED_CHAT_IDS` restrânge camerele (sau un singur topic
`chat:thread`); `TELEGRAM_GROUP_REQUIRE_MENTION=0` relaxează cerința; `TELEGRAM_GROUP_OBSERVE=1`
înregistrează mesajele neadresate drept context fără să răspundă — un mesaj observat nu ia lease
de tură, nu consumă bugetul de rate-limit al răspunsurilor și nu primește niciodată un mesaj de
pairing. Tipurile de chat necunoscute și un bot care nu și-a putut afla identitatea (getMe eșuat)
eșuează închis. Teste: `tests/test_telegram_group_gate.py` (21). *Nedovedit într-un grup Telegram
real* → `docs/OWNER_TASKS.md` **P16**.

### 0.5 — Fără lease pe tură
`agents/core/orchestrator.py:1109-1176` nu ține niciun lock. Un al doilea mesaj Telegram în timpul
unei ture pornește o tură **concurentă** pe aceeași cheie de sesiune — risc de corupere a
transcriptului, nu doar de confuzie.

**Livrat 2026-09-07.** `Orchestrator.turn_lease(session_key)`: `channel_handler` și cele două
endpoint-uri directe de chat web iau lease-ul sesiunii înainte de tură; al doilea mesaj pe aceeași
sesiune își așteaptă rândul, un mesaj pe altă sesiune nu așteaptă deloc, o așteptare peste 180 s
primește `TURN_BUSY_REPLY` în loc să pornească, lease-ul e reintrant în contextul async al turei (un
pas de workflow care apelează înapoi îl moștenește; un context străin nu), iar tabela e mărginită.
Teste: `tests/test_turn_lease.py` (8).

### 0.6 — Configurație moartă în registrul canonic
`general.cloud_llm_agents` din `agents/_system/agents.yaml` **nu e citit de niciun rând de cod**.
Rutarea reală trăiește în `hybrid_router.py:381`. Orice cititor — om sau agent — ar crede rezonabil
că acea cheie controlează rutarea.

**Livrat 2026-09-07 — și era mai mult decât o cheie.** Tot blocul `general:` (timezone, wake words,
backend și endpoint-uri LLM, mod de plugin cloud, bridge WhatsApp) și blocul `rules:` erau copiate în
`JarvisConfig` și niciodată consultate; `rules.promotion_criteria` chiar contrazicea butonul real
(`bench.<id>.threshold`). Ambele au dispărut — casa reală a fiecărui concept e numită în comentariul
din capul fișierului — `NERVA.md` descrie acum rutarea care există (`hybrid_router.py` +
`llm_policy` per agent), iar `tests/test_agents_yaml_dead_config.py` (4) ține fiecare cheie de
top-level consumată.

---

## Valul 1 — suprafața de operator

Deblochează ~26 de rânduri din ledger.

- **Comanda unificată `nerva`** — azi Nerva are 83 de routere HTTP și un kernel guvernat în spatele
  unui tab de browser pe 127.0.0.1, iar terminalul oferă `serve.py`, un Makefile cu 3 ținte și ~35 de
  scripturi argparse fără legătură. **O instalare headless sau pe SSH nu poate fi configurată,
  diagnosticată sau recuperată.** Fiecare verb care mută ceva apelează același serviciu in-process pe
  care îl apelează routerele HTTP, deci moștenește medierea prin kernel gratuit.
  Primele verbe: `doctor`, `kernel explain`, `config`, `approvals`.
- **`kernel explain`** (echivalentul `approvals test` din Hermes) — un simulator read-only care
  rejoacă porțile reale și tipărește traseul. Diferențiatorul Nervei e guvernanța, și azi e
  **invizibilă până se declanșează**.
- **Planul de comenzi slash în chat** — un registru comun servind chat, quickbar și HUD, cu tiere de
  acces per comandă. `/stop`, `/status`, `/pause`, `/sessions` primele. Azi butoanele din decision
  inbox merg pe Telegram, dar nu poți întreba ce rulează, nu poți opri, nu poți ridica e-stop-ul.

**Livrat 2026-09-07 (parțial, cu restul numit).** `agents/cli/` — comanda `nerva`
(`python scripts/nerva.py …`): `doctor`, `status`, `config list|get|set|check`, `approvals
list|accept|reject|defer|edit`, `kernel explain`, `logs`, `estop`, `sessions`, `chat`,
`completion bash|zsh`. Verbele online vorbesc cu hub-ul pe aceleași rute admin/user-guarded pe care
le folosește HUD-ul, cu aceleași credențiale — deci moștenesc kernelul și coada de aprobare; cele
offline citesc același data root. `kernel explain` rejoacă porțile reale (e-stop, registrul de
mediere, tier-ul de politică, ireversibilitatea, modul de autonomie, pragul de aprobare) fără să
execute nimic și spune că hub-ul viu poate doar să strângă verdictul. Construindu-l a ieșit la
iveală un defect real în `preview_task` (tier 0 = READ_ONLY era falsy și devenea 3). Planul de
comenzi slash: `agents/core/commands.py` — `/help`, `/status`, `/sessions` (user), `/pause`,
`/stop`, `/resume` (owner), dispecerizate de orchestrator înaintea skill-urilor și a modelului pe
orice suprafață; tura poartă un principal (allowlist-ul/chat-ul owner-ului pe Telegram, token admin
pe web). **Rămâne:** `nerva send <canal>` (nu există rută de trimitere; una nouă trece prin patru
porți de snapshot + poarta de caller HUD) și `GET /api/commands` + listarea în quickbar. Teste:
`tests/test_nerva_cli.py` (27), `tests/test_slash_commands.py` (12). *Nedovedit pe un hub viu* →
`docs/OWNER_TASKS.md` **P17**.

## Valul 2 — joburi programate de utilizator

**Cea mai mare lipsă, identificată independent în trei clustere** (web, automation, docs-features).

Nerva parsează deja „în fiecare zi lucrătoare la 7" într-o expresie cron — **și o aruncă**. Are toate
piesele (tiere de aprobare, buget de întreruperi, kill switch, lanț de audit) și niciun loc în care
owner-ul să-și armeze propriul job. Cu galerie de blueprint-uri tipizate (brief de dimineață, monitor
de mail important, watch de preț) ca să nu ceară sintaxă cron. E singura capabilitate unde stiva de
guvernanță nu e overhead, ci chiar produsul.

**Livrat 2026-09-07 (motorul și panoul HUD).** `agents/core/autonomy/jobs.py` — `JobStore`
(SQLite) + `JobRunner` pe APScheduler-ul existent; patru acțiuni: `remind` (mesaj fix, fără
model), `ask` (întrebare către un agent prin `Orchestrator.process`, cu un **notepad** păstrat între
rulări ca jobul zilnic să raporteze ce s-a schimbat), `brief` (briefingul pe ora owner-ului), `task`
(pus în coada de autonomie cu `origin=job:<id>` — politica decide act/notify/ask ca pentru orice
task; un job nu poate ocoli coada). Fiecare încercare e o rulare înregistrată; trei eșecuri
consecutive pun jobul pe pauză singur și ridică **un** incident; e-stop-ul pune toate joburile pe
pauză; prag de frecvență o dată la cinci minute. Cinci blueprint-uri (`morning_brief`,
`evening_retro`, `reminder`, `ask_agent`, `inbox_watch`). Suprafață: `/api/jobs` (admin),
`nerva jobs …`, `/jobs` și `/remind <când> | <mesaj>` în chat, plus panoul **Jobs** din HUD (Autonomy
& Agents: listă cu stare și ultimul rezultat, avertisment când scheduler-ul nu rulează, armare din
blueprint, run/pause/resume/delete cu motivele de refuz ale backend-ului, încercările per job). Găsit
pe drum: `HeartbeatScheduler`
pasează câmpul day-of-week din cron (0 = duminică) direct la APScheduler (0 = luni) — heartbeat-urile
pe zile lucrătoare trag cu o zi întârziere (BACKLOG HA-2c). Teste: `tests/test_owner_jobs.py` (22),
`tests/test_jobs_routes.py` (4). *Nedovedit pe un hub viu* → `docs/OWNER_TASKS.md` **P18**.

## Valul 3 — mâinile modelului

- `search_files` — căutare de conținut peste fișiere (ripgrep). Azi modelul are `file_read` și
  `file_list`, deci singura cale spre a găsi ceva e să listeze și să citească fișier cu fișier —
  arzând exact bugetul de context care e deja problema.
- `session_search` — modelul să-și caute propriile conversații trecute. Avem recall bogat peste
  fapte *derivate*, zero peste ce s-a spus.
- **Kernele de cod persistente pe sesiune** — `sandbox.py` pornește un run nou cu `mkdtemp` nou la
  fiecare apel, deci orice analiză reimportă bibliotecile și rederivează starea de fiecare dată.
- `image_generate` — azi există cadrul complet de guvernanță în jurul unei prize goale.

**Livrat 2026-09-07 (3a — mâinile modelului).** `file_search` în `agents/core/file_tools.py` —
căutare *literală* de conținut sub exact regulile lui `file_read` (rădăcinile `JARVIS_FILE_ROOTS`,
niciun symlink urmat, numele secrete sărite și numărate, binarele și fișierele peste plafonul de
bytes sărite), cu fiecare limită raportată (`truncated` + `stopped_by`: potriviri, potriviri per
fișier, fișiere vizitate, secunde). Fără regex și fără ripgrep, cu motiv: `re` din Python nu are
limită de timp, deci un pattern patologic venit de la model ar bloca CPU-ul gazdei și bucla; iar
`rg` ar face unealta dependentă de un binar pe care o instalare proaspătă de Windows/macOS nu îl
are. Extracția din PDF/docx pentru `file_read` rămâne de făcut. `session_search`
(`agents/core/memory/session_search.py`) — cuvinte-cheie (toate în aceeași replică) peste
snapshot-urile de sesiune din data root, cele mai relevante și apoi cele mai noi întâi, fragmente
mărginite, limite raportate; o replică marcată de scanerul de injecție e redactată ca la
`search_memory` și ridică taint-ul de recall al turei, deci o acțiune propusă după citirea ei intră
în coada de aprobare, nu pe auto. Nu se citește peste granița unui data space (decizie de
guvernanță, nu de căutare); demotarea surselor automate, dedupe pe lineage și admission records ca
la `recall_admission` rămân de făcut. În bucla de unelte (`agent_runtime.py`): al treilea apel
identic (aceeași unealtă, aceleași argumente) e refuzat cu motivul, al patrulea încheie tura cu un
răspuns numit și un eveniment; a cincea eșuare consecutivă a aceleiași unelte încheie tura la fel.
Rămân: stub-urile pentru rezultate identice și plafoanele per unealtă. Kernelele de cod
persistente și `image_generate` sunt amânate — au nevoie de backend-uri care nu există încă. Teste:
`tests/test_file_search.py` (14), `tests/test_session_search.py` (11),
`tests/test_tool_loop_repeats.py` (9). *Nedovedit cu un model viu care alege uneltele* →
`docs/OWNER_TASKS.md` **P19**.

**Livrat 2026-09-07 (3b — profilurile de unelte).** `agents/core/tool_profiles.py` — privilegiu
minim *în momentul oferirii*, nu doar al execuției: fiecare agent, pe fiecare suprafață, vedea
întreaga listă (inclusiv `desktop_run`), iar un musafir pe Telegram putea face modelul să propună o
acțiune gated care ajungea card în inbox-ul owner-ului. Profilul e rezolvat înainte ca modelul să
vadă lista, cu cheia agent × suprafață × principal: suprafața din canalul cu care s-a legat
principalul turei (`web`/`voice` → operator; orice canal extern sau o origine `inbound` → inbound;
fără principal → internal), principalul din același loc (owner / guest / system). Posturi implicite:
owner-ul la HUD primește tot; un musafir la HUD sau pe voce, owner-ul pe un canal inbound și orice
tură fără om (heartbeat, job, workflow) primesc doar uneltele ne-gated (`llm.inbound_actuation` /
`llm.internal_actuation` le lărgesc la cele gated, fiecare propunere rămânând sub aprobare); un
musafir pe canal inbound primește `llm.guest_tools` (implicit `echo`, `time`) și niciodată o
unealtă gated. `tools:` per agent în `agents.yaml` (nume sau glob-uri) îngustează postura și nu o
lărgește niciodată. Un apel la o unealtă reținută e `tool_not_allowed` înainte de server; o tură
căreia nu i se oferă nimic nu intră în buclă; un eveniment `tool_profile` spune suprafața,
principalul și ce s-a reținut. Seturile rezolvate peste registrul viu sunt fixate în
`tests/_snapshots/tool_profiles.json` ca `route_auth.json` pentru rute, cu un test că nicio postură
în afară de operator/owner nu oferă actuare implicit. Teste: `tests/test_tool_profiles.py` (26).
Dovedit pe registrul real al coordonatorului; *nedovedit cu un musafir viu pe un canal viu* →
**P19**.

## Valul 4 — adâncime

Descriptor de adaptor + split-ul clasei de bază pe canale (redare, chunking, media, streaming,
threads sunt toate blocate pe faptul că un canal n-are cum să declare ce poate); tiere de încredere
pe MCP cu `readOnlyHint` fail-closed; HUD mode pe desktop (fereastră fără chrome, always-on-top);
SDK de plugin-uri; hub de skill-uri.

**Livrat 2026-09-07 (4a — un canal spune ce poate afișa).** `channels/descriptor.py`
(`ChannelDescriptor`: dialect, plafon de mesaj, edit / media / threads; adaptorul de bază declară
minimul onest, Telegram declară `telegram_html` × 4096) și `channels/render.py` (un singur registru
de renderere pe dialect, cu un singur stripper de text simplu): doar marcajele *echilibrate* devin
markup, textul e escapat înainte de orice tag, chunking-ul se face pe sursă la granițe de paragraf
și apoi de linie și niciodată în interiorul unui bloc de cod — un bloc care ar traversa două
chunk-uri e închis și redeschis — deci fiecare chunk se redă valid de unul singur.
`TelegramChannel.send` împarte, redă în HTML și retrimite ca text simplu un chunk pe care Telegram
îl refuză totuși (400): cuvintele ajung întotdeauna, formatarea e best effort. Până azi un `*`
impar sau un răspuns peste 4.096 de caractere era un 400 și owner-ul nu vedea nimic. Tot în 4a,
două bug-uri în clientul MCP cu muchie de securitate: un nume de unealtă oferit de două servere
mergea la primul din dicționar — acum e refuzat ca `ambiguous_tool` dacă nu e fixat
(`server/tool` sau `server=`); caracterele Unicode TAG (invizibile pe ecran, citibile de model)
sunt eliminate din orice rezultat ToolRPC și din orice rezultat de apel MCP. Teste:
`tests/test_channel_render.py` (15), `tests/test_mcp_hardening.py` (6). *Nedovedit pe un bot
Telegram real* → `docs/OWNER_TASKS.md` **P20**.

**Livrat 2026-09-07 (4b — tiere de încredere MCP, `readOnlyHint` fail-closed).** Orice unealtă
listată de un server MCP putea fi apelată. `MCPServer.trust` e acum `read-only` (implicit pentru
orice server adăugat de acum) sau `full`: pe un server read-only rulează doar o unealtă pe care
serverul însuși a marcat-o `annotations.readOnlyHint: true` — o unealtă neadnotată, nelistată sau
mutantă e refuzată ca `trust_denied` înainte ca vreo cerere să plece; un string `"true"` nu e o
declarație. Indiciul e cuvântul serverului, deci poate doar îngusta un tier, niciodată lărgi;
`full` predă fiecare apel verificărilor de contract și kernel care îl guvernează deja. Adnotările
sunt captate din `tools/list` și arătate per unealtă în `GET /api/admin/mcp`; tier-ul e persistat
cu configul serverului și primit de `POST /api/admin/mcp` (un tier necunoscut e 400 înainte de
orice scriere). Un config salvat înainte să existe tiere se încarcă ca `full` **cu avertisment**,
nu rupe instalarea owner-ului la upgrade. Scriitorul WorldView al Nervei e fixat pe `full` (trece
deja prin gate-ul de plugin și kernel). Teste: `tests/test_mcp_trust.py` (10). *Nedovedit pe un
server MCP real* → **P21**. Rămân în 4c: streaming prin editări, renderere Slack/Discord,
include/exclude per server, `ntfy`, HUD mode, SDK-ul de plugin-uri.

---

## Ce nu se schimbă

Cele 80 de capabilități `superior` și 114 `keep` — memorie, aprobare/siguranță, audit, casă, plus
onestitatea de status (DEMO/OFFLINE/EMPTY/LIVE, EGRESS, %-local, care n-au analog la Hermes) și
lanțul de aprovizionare semnat pentru skill-uri, față de „lipește un URL de Git" la ei.
**Absorbția nu are voie să le erodeze.** Un val care aduce paritate de suprafață și taie o linie de
guvernanță a eșuat, chiar dacă bifează rânduri.
