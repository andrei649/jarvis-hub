# Nerva Business Suite („AI in a box” pentru companii) — întrebările de kickoff

> **Status: DRAFT — întrebările D1–D7 rămân deschise; pilotul a pornit pe ipoteze declarate.**
> **Directiva owner-ului, 2026-10-17:** *„avansează, pregătește interfața B2B pentru un pilot, rulează agenți
> pentru dezvoltarea armonioasă cu verificări astfel încât produsul să fie de nota 9/10 chiar și pentru pilot,
> toate funcțiile trebuie să funcționeze"*. Construcția urmează contractul
> [`docs/business/WORKSPACE_PILOT_SPEC.md`](../business/WORKSPACE_PILOT_SPEC.md), care adoptă recomandările de mai jos
> ca ipoteze: D1 o companie cu mai multe departamente (prima instalare poate fi Digitaholic); D2 software-only, modelul
> servit de router-ul hub-ului (local OpenAI-compatible sau cloud aprobat), fără hardware; D3 single-tenant cu conturi
> locale, invitații, sesiuni httpOnly, roluri admin/approver/member pe departamente și SSO prin header de la un
> reverse proxy de încredere; D4 fără conectori ERP/CRM în această felie — cunoașterea vine din documente încărcate.
> D5–D7 nu sunt cod și rămân la owner. Data inițială a chestionarului: 2026-10-14. Nu este o decizie; este
> chestionarul care precede decizia (regula din `AGENTS.md`: scop, non-scopuri, căi probabile, riscuri,
> *înainte* de orice implementare). Când owner-ul răspunde, răspunsurile intră în acest fișier sub
> fiecare întrebare și documentul devine decision record; abia apoi se deschid rânduri în `BACKLOG.md`.
>
> **Ideea (owner, 2026-10-13):** după Jarvis (asistent personal) și Nerva (AI OS personal), un
> **produs vândut de Digitaholic**: o suită de agenți care se conectează la abonamentele și API-urile
> principalelor sisteme ale unei companii, cu „AI in a box” — fie inferență locală pe un pachet de
> N × NVIDIA DGX Spark + accesorii, integrat în VPN-ul clientului, fie modele cloud — și o interfață
> web pentru orice angajat din departamentele uzuale (vânzări, financiar, HR, operațiuni, suport,
> management): rapoarte, răspunsuri la probleme, automatizare de procese.
>
> **Cum a fost produs documentul.** Șase dimensiuni ale codului au fost cartografiate fiecare de un
> agent și verificate adversarial de un al doilea (identitate · deployment/hardware · conectori ·
> rapoarte/automatizări · securitate/conformitate verificate; **licență/operare a rămas neverificată**
> de al doilea cititor și e marcată ca atare). Separat: o critică strategică pe `MOONSHOT.md`,
> `NERVA_VISION.md`, `docs/REVIEW_YEAR_ONE.md`, `docs/GTM_PLAN.md`, `docs/VALUATION_AND_PRICING.md`,
> `docs/NERVA_2_ROADMAP.md`, și o cercetare de piață online (13 oct 2026). Citările `cale:linie`
> sunt la HEAD `413a42c`. Datele de piață poartă nivel de încredere — **reconfirmă prețurile înainte de
> orice ofertă comercială.**

---

## 0. Verdictul scurt

Ideea este continuarea a ceea ce repo-ul deja planificase pe hârtie (MOONSHOT §4 Faza 3 „Sellable”,
VALUATION §5 planurile Team/Business/Enterprise cu on-prem, SSO, audit, MCP server mode) și, pentru
prima dată, îndreaptă sistemul spre un utilizator care poate pleca — cu buget. Nucleul de guvernanță
se transferă aproape intact și este rar în piața 2026: Action Kernel, coadă de aprobare, audit
Merkle, profil hardened, rutare hibridă local/cloud, atribuire de cost, podea de securitate impusă de
teste. **Dar ideea așa cum e formulată — șase departamente, rapoarte + Q&A + automatizare, două moduri
de livrare și un SKU hardware pe DGX Spark, vândut și susținut în România de un singur developer —
repetă greșeala anului unu la scară enterprise: lățime înainte de dovadă.** Azi: n = 1 utilizator,
zero conectori la sisteme de business, zero rulări pe ARM64, tabelul de benchmark hardware gol,
fără identitate per utilizator (decizia ratificată „single-user” este *singurul* gol tehnic blocant:
un audit care nu poate numi aprobatorul nu este un audit enterprise), iar enunțul de identitate
„owned by the person it serves” se inversează. Aproximativ jumătate din cod și 100% din roadmap-ul
deschis (casă, camere, media, twin, OSINT, drivere OS, sprintul Hermes 697) sunt balast pentru acest
cumpărător și trebuie **înghețate explicit, nu purtate tacit**.

Până la răspunsul la primele trei decizii de mai jos, nicio lucrare pe conectori, UI sau hardware nu
este justificată.

---

## 1. Deciziile blocante — în ordinea dependențelor

### D1 — Cine este clientul #1 și care este *singurul* flux de lucru livrat primul?

**Întrebarea.** Digitaholic însăși ca prima instalare (dogfood pe operațiuni de agenție), un partener
extern plătit cu un singur departament, sau șase departamente la o companie medie (ideea cum a fost
spusă)? Și din ce segment vin primii 2–3 parteneri: firme ICT/servicii profesionale (adopție AI 32%,
API-literate), mid-market reglementat (bănci, asigurări, utilități, spitale sub NIS2/DORA — vor
on-prem, dar împing obligații de supply-chain pe vânzător), sector public (împins spre Cloudul Privat
Guvernamental), sau export UE cu poziționare „sovereign AI”?

**Ce există azi.** Singurele plugin-uri cu caracter de business sunt cele ale propriei agenții:
`meta_ads.py` (Graph insights), `postiz.py` (programare social), `analytics.py` (KPI web first-party),
`revenuecat.py`, `crm_sync.py` (scrie un lead într-o bază Notion; nu are niciun apelant),
`gmail_plugin.py`, `google_calendar.py`. Zero cod pentru ERP, contabilitate, HR, ticketing, BI
(grep pe `sap|odoo|hubspot|salesforce|jira|zendesk|sharepoint|graph.microsoft|postgres|smartbill|saga|anaf`
găsește doar builder-ul de draft Outlook M365). `docs/REVIEW_YEAR_ONE.md` §8 recomandă „o buclă, apoi
1–3 parteneri”; niciun partener nu a fost recrutat (n = 1). România: 5,21% din firme folosesc AI (ultima
în UE), 24,9% cumpără cloud plătit (Eurostat 2025).

**Opțiuni.**
- a) Digitaholic intern primul (raportare de agenție: Meta Ads + analytics + Notion CRM + Gmail/Calendar
  — plugin-urile existente), apoi aceeași instalare la 2–3 clienți de agenție.
- b) Un partener SMB extern, un departament (ex. raport financiar săptămânal + Q&A pe exporturi
  contabile), plătit cu discount de design-partner (VALUATION §5).
- c) Șase departamente la o companie medie.

**Recomandare.** (a) imediat — n = 2 în săptămâni, zero ciclu de vânzare, date reale, rol GDPR real —
urmat de (b) în aceeași verticală. Pentru segment: doi parteneri ICT/servicii profesionale (feedback
rapid, agenți financiar + ops) și unul reglementat care să modeleze pachetul de conformitate; sectorul
public amânat până se așază legea națională AI Act și regulile de achiziție.

### D2 — Postura de livrare v1: serviciu gestionat cloud-first, software pe VM-ul clientului, sau appliance DGX Spark?

**Întrebarea.** Te angajezi la DGX Spark (aarch64) ca hardware de lansare, lansezi software-only
(VM al clientului în VPN, cu Ollama pe GPU-ul lor x86 dacă există, sau instanță gestionată de
Digitaholic într-o regiune UE) și adaugi Spark după un sprint de validare ARM64, sau vinzi
hardware-agnostic (imagine Docker + specificație minimă, cutia o aduce clientul/un VAR)?

**Ce există azi.** Nimic din repo nu a rulat vreodată pe ARM64: CI este Ubuntu x86 + Windows
(`ci.yml:46-53,125-131`), imaginea `linux/arm64` din `release.yml:122` e un cross-build QEMU, iar
pachetul GHCR este **privat** (verificat live: pull anonim → 403). Setul de dependențe e pur Python cu
hash-uri pentru wheel-uri aarch64 — deci ARM e probabil o treabă de *validare*, nu de portare.
`hardware.py:79-101` + `model_setup.py:94-104` ar clasifica probabil un GB10 (memorie unificată,
`nvidia-smi` poate raporta non-numeric) drept „cpu-only”; tier-urile se opresc la „24gb+”. LM Studio
(backend-ul sondat primul) nu are server pe Linux ARM64 — dar slotul „lm-studio” este de fapt un client
OpenAI-compatible generic (`base.py:520-549`), așa că **vLLM / llama.cpp-server pe același host
funcționează deja ca rută „local” fără cod**; un host de inferență din LAN e reetichetat „unknown” și
cere un ack (`data_handling.py:325-329`). `docs/HARDWARE_BENCHMARKS.md` e gol („— to measure —”).
Spec-ul demo-ului public (`2026-08-24-public-web-demo-digitaholic.md`, aprobat) descrie deja un
container hardened per client cu LLM cloud — modelul „cloud acum, local mai târziu” e aprobat.

**Opțiuni.**
- a) Cloud-first gestionat de Digitaholic în regiune UE; on-prem doar clientului care îl cere în scris.
- b) Software-only pe serverul/VM-ul clientului în VPN-ul lui (Ollama/vLLM local dacă are GPU), fără
  revânzare de hardware.
- c) Pachet DGX Spark (N unități + accesorii), livrat și instalat de Digitaholic.

**Recomandare.** (a)/(b) pentru v1; **cumpără un Spark acum** pentru sprintul de validare ARM64, dar
ofertează primii clienți hardware-agnostic (imagine Docker + spec minimă), ca o întârziere a portării
să nu blocheze venitul. Publică un BOM de referință pentru Spark; nu revinde și nu susține hardware
înainte de 3 logo-uri plătitoare și benchmark-uri ARM64 măsurate.

### D3 — Modelul de identitate și tenancy: cât de departe dincolo de „single-user per instalare”?

**Întrebarea.** Un hub per companie cu mulți utilizatori înăuntru (identitate SSO per angajat, roluri,
atribuire în audit), un hub per departament prin `JARVIS_PROFILE` în spatele unui proxy SSO (puțin
cod, fără vedere trans-departamentală), sau SaaS multi-tenant (multe companii într-o instanță)? Și
sub-întrebările care fixează schema: ce furnizor de identitate rulează primii clienți (Entra ID /
Google Workspace / Keycloak inclus pe cutie pentru air-gapped)? granularitate: doar roluri
(admin/angajat) sau date și agenți scopate pe departament? memoria: globală pe companie / trei straturi
companie–departament–personal / doar per angajat? cine aprobă acțiunile agenților (solicitantul, șeful
de departament, admin IT) și rămâne kill-switch-ul un control single-admin? canale: doar web în v1, sau
și Teams/Slack?

**Ce există azi.** Autentificarea are exact două scope-uri, `admin` și `user`
(`token_store.py:37`); token-urile nu au subiect. `Principal(channel, sender, admin, chat)`
(`commands.py:47-56`) este singura noțiune de „cine vorbește”; pe web `sender` e mereu `None`.
Matricea de rute: 626 rute = 292 user / 260 admin / 74 deschise, admin fiind superset plat. Deciziile
de aprobare sunt hardcodate `decided_by='admin'` (`routers/autonomy.py:375,392,427`); `security_events`
nu are coloană de actor (`audit.py:75-85`); `Action` din kernel are `origin`, nu `actor`
(`kernel/__init__.py:59-61`) — **lanțul HMAC nu poate spune cine a acționat**. Frontend-ul ține
token-urile în `localStorage` și cere X-User-Token printr-un `window.prompt` (`client.ts:56-66`); nu
există login/logout. Zero cod OIDC/SAML/LDAP în `agents/` și `frontend/src`. Memoria pe termen lung e
un singur tabel `UNIQUE(category,key)` fără coloană de utilizator; `/api/memory/*` și `/api/kg/*` sunt
user-tier. Data Spaces (H10.26) e per *agent*, default-open, aplicat pe un singur endpoint. OAuth: un
token per serviciu per instalare (`oauth.py:92-93`). `JARVIS_PROFILE` dă rădăcini de date complet
izolate, dar `hub.lock` impune un proces per rădăcină. Decizia single-user e ratificată
(`2026-07-11-single-user-1.0.md`, opțiunea A, 2026-09-01); `docs/NERVA_2_ROADMAP.md` nu are niciun
milestone de identitate între 1.1.0 și 2.0.0. Există seam-uri bune: `current_principal()` per tură
(`orchestrator.py:284-294`), `proxy_trust.py` (CIDR allowlist pentru X-Forwarded-For — refolosibil
pentru anteturi de identitate de la oauth2-proxy/Authelia), `tool_profiles.py`, adaptoare
Teams/Google Chat/WhatsApp/Signal/Matrix (`webhook_channels.py:143-268`, default-off, doar text, fără
validare Bot Framework).

**Opțiuni.**
- a) Single-tenant per companie + multi-user înăuntru: OIDC generic (Entra ID și Google testate întâi,
  Keycloak inclus pentru VPN-only), roluri viewer/requester/approver/admin, grupuri din IdP mapate pe
  Data Spaces închise implicit, actor în audit — H23.23 opțiunea (B) scopată la un tenant.
- b) Un hub per departament prin `JARVIS_PROFILE`, token partajat, în spatele proxy-ului SSO al
  clientului — doar ca formă de pilot.
- c) SaaS multi-tenant.

**Recomandare.** (a) este ținta produsului și **singura inginerie nouă de nucleu inevitabilă**; (b)
doar pentru un singur pilot de design-partner, cu (a) pornit imediat; (c) niciodată înainte de
izolare multi-tenant. Sub-decizii recomandate: OIDC generic + Keycloak opțional; roluri + grupuri de
departament (nu doar admin/angajat); trei straturi de memorie cu personalul privat implicit (adminii
văd metadate who/when, nu conținut); aprobare în trepte — reversibil → solicitant, ireversibil/extern
→ șef de departament, kill-switch și plafon de autonomie → admin platformă, toate atribuite unui
subiect IdP; web-only în v1, Teams al doilea (identitate din Entra), WhatsApp/Telegram doar notificări.
Punte ieftină (zile, nu luni): acceptarea anteturilor `X-Forwarded-User/Email/Groups` doar de la peer-i
din `JARVIS_TRUSTED_PROXIES`.

### D4 — Build vs. integrate pentru conectorii la sistemele companiei

**Întrebarea.** MCP-first (consumi serverele MCP ale vendorilor clientului + n8n pentru coada lungă,
sub guvernanța kernelului; plugin-uri native doar pentru 2–3 sisteme ale primei verticale), plugin
nativ per sistem (modelul actual cu 29 de fișiere), sau n8n ca bus de integrare cu Nerva doar
declanșând workflow-uri? Și: care trei sisteme rulează *de fapt* primul client (Microsoft 365 vs Google
Workspace; HubSpot/Pipedrive/Salesforce/Zoho; SmartBill/Saga/Oblio/SAP B1)? Te angajezi la conectorii
fiscali românești (ANAF e-Factura/SPV, SmartBill, Saga) ca diferențiator? Permiți SQL read-only pe o
replică a bazei clientului? Ce model de partiționare a cunoașterii (corpus comun / colecție per
departament / ACL-uri oglindite din SharePoint/Drive)? Credențiale app-only (service principal) în
SecretStore pe cutie sau OAuth delegat per angajat?

**Ce există azi.** Precondiție neplăcută: **bucla de tool-uri e default-off și etichetată
„experimental”** (`llm.tool_loop_enabled=False`, `settings_db.py:209`) — într-o instalare implicită
modelul nu are *niciun* tool; singura atingere a datelor externe e injecția pe cuvinte-cheie din
`plugin_gatherer` pentru 11 plugin-uri personale. Clientul MCP este suprafața de integrare cea mai
călită din repo (niveluri de încredere, HTTP prins SSRF, reținere de env, 210 funcții de test), dar
**nimic nu oferă tool-urile MCP modelului**; singurul consumator al `MCPManager.call_tool` e clientul
WorldView intern. Transportul Streamable HTTP e triplu blocat (`JARVIS_MCP_HTTP_CLIENT` off; `POST
/api/admin/mcp` refuză orice transport în afară de stdio — gardă veche, `routers/mcp.py:197-205`;
headerele bearer nu se persistă). Plugin-ul n8n e client REST real, container în compose, dar fără
niciun apelant; n8n are licență Sustainable Use (restricționează embedding comercial). Write-back: 12
acțiuni „create” (Notion/GitHub/Calendar/Linear/Asana/Trello/Todoist/ClickUp/Sheets/draft Outlook)
mediate de kernel, în spatele `JARVIS_WRITEBACK_LIVE` — șina de aprobare e gata, catalogul e de
consumator. RAG pe documente locale: md/txt/rst nativ, pdf/docx best-effort (pypdf/python-docx nu sunt
în requirements → sărite tăcut), fără xlsx/csv/pptx/eml, fără OCR; `drive_sync` = un remote rclone la
boot care re-embeddează totul la fiecare rulare; `search(embedding, k)` fără filtru, o singură colecție
Qdrant `jarvis_memory`; `search_memory` șterge cheile `file`/`chunk` → **fără citări**. Niciun driver
SQL nicăieri. Realitate românească: SmartBill (150–170k clienți, REST API, e-Factura), Oblio (OAuth2),
FGO (API pe Premium), SAGA (dominant, fără API public — doar import/export), e-Factura obligatoriu B2B
din 2024 și cu termen de 5 zile lucrătoare din 2026 — un flux structurat universal pentru orice SRL.

**Opțiuni.**
- a) Hibrid: MCP-first pentru citiri/tool-uri (M pentru wiring + S pentru HTTP/headere), n8n furnizat
  de client pentru automatizări multi-pas, native doar unde nu există server MCP (contabilitate RO/ANAF).
- b) Plugin nativ per sistem (XL pentru ERP/CRM/HR/ticketing/contabilitate).
- c) Doar încărcare de documente + Q&A (RAG pe exporturi), fără integrare.

**Recomandare.** (a). Primele sisteme: alege după primul LOI; dacă trebuie pre-construit, Microsoft
Graph (documente, mail, calendar, Teams într-un singur model de auth) + e-Factura/SPV (neutru față de
vendor și obligatoriu legal) + SmartBill (cea mai mare bază cu API). SQL read-only pe replică, cu
allowlist de tabele, în spatele unui flag — cea mai scurtă cale către un demo credibil de raport.
Partiționare: colecții per departament + filtru în `HybridRetriever`/payload Qdrant, cu regula dură
că HR și financiar sunt colecții separate; ACL-uri oglindite după SSO. Credențiale app-only în
SecretStore pe cutie pentru v1; delegare per utilizator și vault în tier-ul enterprise. Și, înainte de
orice: profilul B2B pornește cu bucla de tool-uri ON.

### D5 — Linia open-core, licența comercială, proprietarul IP-ului și brandul

**Întrebarea.** Cine este proprietarul legal al IP-ului și publisher-ul de contract — tu personal sau
Digitaholic SRL? Modelul comercial peste Apache-2.0: (a) totul Apache, vinzi cutia + suport + update-uri
gestionate; (b) open-core — motorul Apache în acest repo, stratul enterprise (identitate/SSO, agent de
flotă, metering, conectori ERP/CRM) într-un repo privat Digitaholic; (c) relicențiere viitoare
AGPL/BSL + excepție comercială? Vrei aplicare tehnică a licenței (fișier de licență semnat offline:
plan, locuri, expirare, grație — funcționează în VPN) sau doar contract? Brandul: înregistrezi „Nerva”
(OSIM + EUIPO, clasele 9/42) pe Digitaholic, sub-brand („Nerva for Business”) sau nume nou B2B?
*(Dimensiune neverificată de al doilea cititor — tratează citările ca probabile.)*

**Ce există azi.** Licență Apache-2.0 din 2026-09-02 (#1012), decizie „adoption-first” care presupunea
self-hosteri B2C. `LICENSE:190` e încă șablonul necompletat „Copyright [yyyy] [name of copyright
owner]”. `CONTRIBUTING.md` acordă drept de relicențiere „maintainer-ului”, nu unei companii.
`TRADEMARKS.md` protejează „Jarvis Hub” (0 mențiuni „Nerva”); nicio căutare de disponibilitate sau
înregistrare pentru „Nerva”; identificatorii livrați încă spun `com.jarvishub.app`, `JarvisHub`,
`jarvis-<ver>.tar.gz`. Niciun mecanism de cheie de licență / drepturi / locuri. Compose-ul complet
include n8n (SUL) și Neo4j 5 (Community = GPLv3, `NEO4J_AUTH: none`). Repo-ul e public și conține
`docs/VALUATION_AND_PRICING.md` (praguri de preț, „as-is €20–70k”), `docs/REVIEW_YEAR_ONE.md` („real
users: 1”) și rezidualele de securitate deschise — un cititor de due-diligence le va găsi.

**Recomandare.** Atribuie copyright-ul Digitaholic SRL înainte de prima conversație cu un client
(un commit). (b) open-core, cu linia trasă *acum* la identitate/flotă/metering/conectori — exact stratul
încă neconstruit, deci nu iei nimic înapoi. Fișier de licență semnat offline (Ed25519, grație). Rulează
căutarea de disponibilitate pentru „Nerva” (zile, ieftin); dacă e liber, înregistrează pe Digitaholic
și redenumește identificatorii într-o singură versiune; rescrie `TRADEMARKS.md` oricum. Decide și **unde
trăiesc documentele de strategie B2B** (acest fișier inclusiv) dacă repo-ul rămâne public.

### D6 — Cine operează, cu ce SLA, și în ce rol GDPR

**Întrebarea.** Appliance self-managed (Digitaholic = doar furnizor de software, fără DPA), operare
remote gestionată de Digitaholic (procesor GDPR: DPA Art. 28, ingineri în SEE, proces de incident 24h
pentru clienți NIS2, drepturi de audit/ieșire DORA), sau partener MSP/integrator românesc care operează
(Digitaholic furnizează software)? Cutia „sună acasă” (heartbeat versiune/sănătate/licență/utilizare,
opt-in, allowlist) sau rămâne promisiunea zero-telemetrie? Cum ajung update-urile în VPN-ul clientului
(pull dintr-un registry semnat Digitaholic cu card de aprobare în HUD, push peste VPN, bundle offline
USB/SFTP)? Ce SLA poți staffa realist?

**Ce există azi.** Promisiunea zero-telemetrie e testată (`tests/test_no_telemetry_proof.py`) și
`SECURITY.md` spune „no owner-operated backend” — deci **nu există inventar de flotă, heartbeat, cens
de versiuni sau diagnostic remote**. Update = `git pull --rebase origin main` + `pip` nelocked
(`UPDATE.bat:30,49`); GPG nesemnat (v1.0.0 fără `.asc`); 1.713 linii de changelog nelansate, inclusiv o
schimbare BREAKING de default de securitate (H502); Homebrew/winget/GHCR nepublicate; bridge-ul Oracle
poate face `git pull` pe cutie (periculos pe un appliance). Support bundle = doar contoare (fără
loguri); backup nightly local-only, restore doar CLI cu serverul oprit; `SECURITY.md` promite „~7 zile
best-effort, single maintainer”, iar VALUATION §5 promite NBD (Business) și 4h (Enterprise) — nu se pot
onora cu tooling-ul actual și fără un al doilea inginer. Protecția de branch nu e configurată
(`pr-auto-merge.yml` merge-uiește orarul orice PR CLEAN) — un cumpărător o va întreba.

**Recomandare.** Self-managed implicit, cu bundle-uri de update semnate aplicate de client (snapshot
înainte, rollback cod+date ca unitate) + pull dintr-un registry semnat ca variantă; tunel inițiat de
client (Tailscale/WireGuard) pentru sesiuni programate; support bundle v2 cu loguri; **NBD, nu 4h**,
până există un al doilea inginer. Heartbeat opt-in allow-listat doar pe SKU-urile plătite, build-ul
Community rămâne zero-telemetrie (promisiunea publică rămâne adevărată). Hardware și on-site prin
partener. Dezactivează bridge-ul Oracle pe appliance; adaugă cheile GPG/cosign acum.

### D7 — Îngheți roadmap-ul personal 1.x pe durata pivotului, sau rulezi ambele?

**Întrebarea.** Parchezi `docs/NERVA_2_ROADMAP.md` 1.2–1.6 și `HERMES_STATUS.md` (sprintul de echivalență
697 capabilități, drivere OS Windows/macOS/Linux, casă/camere/media, Howard, mesh), `main` primind doar
linia B2B + securitate, cu decizia în `docs/HISTORY.md` și o dată de redeschidere? Rulezi ambele
(BACKLOG_DRIVER autonom pe rândurile personale, owner-ul pe B2B)? Abandonezi produsul personal?

**Ce există azi.** Backlog deschis: 36 rânduri, toate personal-world; cele 10 „Live-vs-Plumbing” sunt
Google OAuth, Spotify, Home Assistant, Frigate, Telegram, actuatoare media/desktop. Sprintul curent
(`HERMES_STATUS.md`) urmărește 697 capabilități de agent personal. `REVIEW_YEAR_ONE.md` §10 numește bus
factor 1 „riscul cu severitatea cea mai mare și cel mai puțin discutat”. Un pivot care nu realocă
singura resursă rară e un deck de slide-uri.

**Recomandare.** Îngheață explicit, cu redeschidere legată de primul client plătitor.

---

## 2. Întrebări de produs (ce primește un angajat)

**Q8 — Primul livrabil: digest-uri narative sau rapoarte cu cifre?** Motorul DAG e real (128 teste)
dar are doar pași LLM/text (`agent/critic/router/transform/guardrail/loop/subflow`), fără nod
HTTP/SQL/conector/send; nu există driver SQL, tabele sau grafice în UI (frontend = react/react-dom, 2
`<table>`), nici writer PDF/XLSX/DOCX; toate „rapoartele” existente sunt despre activitatea Nervei
(`day_report.py`, json/html, payload-free). Narativ = extinzi jobs/blueprints + livrare (M); cifre = tool
SQL read-only + șabloane + tabele/grafice (L–XL). *Recomandare:* digest-uri narative întâi pe
ask-jobs/blueprints, tool SQL read-only ca a doua felie, MCP ca mecanism pentru ambele.

**Q9 — Pe ce canale trebuie să ajungă un raport în v1?** Brief-urile programate sunt doar Telegram
către owner (`scheduler_service.py:749-761`); emailul e exclus din trimiterea generică printr-o regulă
anti-injecție și nu are destinatar implicit la boot; Slack/Discord cer id-uri de canal pe care jobs nu
le furnizează; Teams există ca webhook adapter default-off, doar text. *Recomandare:* web UI + email
către destinatari allow-listați (un kind guvernat nou `report.deliver` pentru rapoarte generate de
sistem) + Slack/Teams pentru carduri de aprobare.

**Q10 — Cât investești într-un builder vizual de procese?** Builder-ul HUD e un textarea JSON
(`WorkflowBuilderPanel`; canvas-ul a existat doar în HUD v1); jobs nu pot declanșa un pipeline; doar
webhook-urile inbound pot rula un workflow; `WorkflowPendingQueue` nu are niciun apelant de enqueue.
*Recomandare:* șabloane form-based per departament (aprobare cheltuieli, escaladare ticket, review
săptămânal) + puntea n8n; canvas doar dacă două clienți plătitori îl cer.

**Q11 — Intră „agenți 24×7 care lucrează la obiectivele companiei” (company mode) în oferta v1?**
Company mode e flag-off, restart-to-enable, planner pe checklist, rute read-only fără buton de start
(`company.py:17-25`); kanban dispatch și runtime-ul Hermes sunt default-off. *Recomandare:* v1 = jobs +
workflow-uri + aprobări + rapoarte; company mode expus ca funcție pilot etichetată pentru design-partners.

**Q12 — Scrieri în sistemele clientului din prima zi, sau read-only + draft-uri?** Șina de write-back
e reală în spatele `JARVIS_WRITEBACK_LIVE`, dar verbele sunt de consumator (creează pagină/issue/
eveniment/draft); „update deal stage”, „răspunde la ticket”, „postează factura” sunt fiecare o intrare
de catalog + builder + credențial. *Recomandare:* read-only + draft-uri în v1; 3–5 scrieri de business
în spatele cozii de aprobare după ce un pilot le numește.

**Q13 — Semantica aprobărilor de business.** Azi: o singură cutie de aprobare, buget de întreruperi
4/zi calibrat pentru un owner, fără lanțuri multi-pas, SLA/escaladare la altă persoană, delegare,
revizuire pe formular (edit = JSON brut). Ce reguli de rutare și termene vrei pentru financiar/ops?

**Q14 — Interfața angajatului: shell de business nou, îngust, pe același API (rapoarte, aprobări, chat
de departament), HUD-ul rămânând consolă admin?** Codul răspunde deja: HUD-ul e o consolă de operator
cu 121 de paneluri și 18 moduri personale (House, Camera, Family, Finance), paneluri de decizie/jobs
admin-only. *Înregistrat ca recomandare, nu ca întrebare:* shell nou.

---

## 3. Întrebări tehnice (cutia)

**Q15 — Ce înseamnă „x DGX Spark” în ofertă?** Un Spark per companie (hub + inferență), un hub + N
Spark-uri de inferență în spatele unui load balancer OpenAI-compatible (fezabil: doar URL-uri de bază +
regula de host de inferență de încredere + failover), sau N appliance-uri independente per
departament/sediu (fezabil prin `JARVIS_PROFILE`)? **Agenți distribuiți pe mai multe Spark-uri sunt
imposibili azi**: `hub.lock` (`install_identity.py:168-190`), un singur proces uvicorn (`serve.py`),
47 store-uri SQLite, NodeMesh fără transport (`node_mesh.py:235`). *Recomandare:* opțiunea „hub + noduri
de inferență” ca poveste de scalare; appliance-uri independente pentru multi-sediu; nu promite niciodată
agenți distribuiți.

**Q16 — Ținta de concurență per appliance și latența acceptabilă.** Nu există control de admisie
(singurul mecanism e lease-ul per sesiune cu așteptare de 180 s, `orchestrator.py:2095-2127`), nu există
limite explicite de pool httpx, nici măsurători de debit. Măsurători publice pe un Spark (vLLM,
gpt-oss-120b MXFP4): vezi tabelul din §7 — ~16–32 sesiuni de chat simultane la 8–11 tok/s, ~10–20 rulări
de agent concurente; modelele dense 70B sunt inutilizabile (2,7–4,6 tok/s). *Recomandare:* definește
„tier Departament” (~20 concurenți / ~200 utilizatori numiți, p95 first-token < 5 s) ca produs, măsoară
pe un Spark întâi, și lasă măsurătoarea să decidă dacă „x” e 1 sau 2.

**Q17 — Politica de modele.** Doar MoE open-weight local (gpt-oss-120b, Qwen3-30B-A3B/235B-A22B,
Mistral Small, Nemotron 3), doar frontier cloud (Claude/GPT/Gemini pe regiuni UE), sau hibrid cu
rutare per departament și per clasă de date? Când clientul alege cloud: endpoint-uri enterprise UE
(Azure OpenAI Suedia/Franța, Vertex europe-west, Bedrock Frankfurt, Mistral — adaptoare noi) sau
endpoint-urile directe actuale (api.anthropic.com, api.openai.com, Gemini, OpenRouter, DeepInfra) cu
termeni zero-retention? `host_protocol.py` acceptă deja `eu.api.openai.com`, iar profilul
`openai-compatible` ia orice base URL (OpenAI EU, Mistral, vLLM self-hosted sunt accesibile acum);
`data_handling.py` forțează un ack per furnizor. *Recomandare:* local implicit; cloud opt-in per
departament și clasă de date prin poarta de consimțământ existentă; profil „air-gapped” cu un click
pentru cumpărători reglementați; endpoint-urile directe US rămân opt-in explicit și documentat.

**Q18 — Instalare și update offline în VPN.** Toate căile sunt online azi: `install.sh:63` clonează
GitHub, bootstrap-ul face `pip` din PyPI, modelele vin din registry.ollama.ai, runtime-ul Hermes (opt-in)
din codeload.github.com. *Recomandare:* construiește bundle-ul offline (imagine Docker tarball +
wheelhouse aarch64 + blob-uri de model); face și instalările online deterministe, iar „zero trafic
outbound” devine un argument demonstrabil cu ledger-ul de egress existent.

**Q19 — Rămâi pe SQLite + un proces pentru v1, sau introduci Postgres?** WAL e pe ~17 store-uri, nu pe
toate; backup-ul e local și fără țintă off-box. *Recomandare:* SQLite pentru v1, întărit (WAL peste tot,
`busy_timeout`, țintă de backup off-box SMB/NFS/S3 + runbook de cold spare din imaginea Docker, RPO 24h /
RTO < 4h în contract); Postgres doar ca declanșator v2 legat de o cerință HA semnată.

---

## 4. Întrebări de conformitate

**Q20 — EU AI Act: excluzi explicit cazurile de utilizare high-risk din v1?** Triajul/clasarea
candidaților, evaluarea angajaților și scoring-ul de credit sunt Anexa III (aplicabile din **2 dec 2027**
după Digital Omnibus, Reg. 2026/1744); obligațiile Art. 26 pentru deployer (supraveghere umană
competentă, loguri ≥ 6 luni, informarea reprezentanților angajaților) rămân. Rapoartele, Q&A și
automatizarea de procese sunt risc limitat: **Art. 50 transparență se aplică din 2 aug 2026** (grație
până la 2 dec 2026 pentru sisteme generative deja pe piață) — Nerva nu are hook de „interacționezi cu
un AI”. România: ANCOM (supraveghere) și ADR (notificare) desemnate prin memorandum 12 mar 2026;
legea națională cu puteri de sancționare era încă în redactare la 24 iul 2026. *Recomandare:* exclude
clasarea/scoring-ul de persoane din v1 prin ToS + o poartă de politică care refuză kind-urile HR
evaluative; livrează hook-urile Art. 50 acum; marketează „nu vă clasăm angajații sau candidații”.

**Q21 — Ce dovezi de conformitate cere primul segment plătitor înainte de semnare?** Whitepaper +
pen-test extern + șabloane DPA/DPIA (BACKLOG are zero rânduri GDPR/SOC 2/ISO/NIS2/SIEM/DPIA; nu
există pen-test de terță parte; lane-urile de securitate din CI nu blochează merge-ul,
`security.yml:13-16`), certificare ISO 27001 a Digitaholic, sau SOC 2 Type II? *Recomandare:*
whitepaper + pen-test + șabloane legale pentru pilot; ISO 27001 doar când un contract o cere; sari peste
SOC 2 dacă nu vinzi în afara UE.

**Q22 — Ce dovadă de audit primește IT-ul clientului și ce poartă chitanțele?** Auditul e JSON paginat
(`routers/admin.py:662`), „ancora externă” e un fișier JSON local (`anchor.py:12-16`), ledger-ul de
egress e în memorie; chitanțele sunt payload-free prin construcție (`FORBIDDEN_ACTION_FIELDS`) — un
auditor financiar vrea „care factură, ce sumă, cine a aprobat”. *Recomandare:* forwarder syslog/CEF +
ancorarea periodică a capului lanțului în WORM/object-lock controlat de client; chitanțe payload-free +
id-uri de înregistrare din sistemul sursă; retenție de payload redactat ca opt-in per client.

**Q23 — Cine ține cheile pe appliance?** Materialul de cheie implicit stă lângă store-ul criptat
(`secrets.py:104-118`), `JARVIS_AUDIT_KEY` e gol implicit, transcrierile/memoria/KG sunt plaintext la
rest; nu există adaptor Vault/Key Vault/KMS/TPM. *Recomandare:* LUKS obligatoriu, `JARVIS_AUDIT_KEY`
și `JARVIS_SECRET_KEY` furnizate de client la instalare, adaptor Vault pe roadmap; Digitaholic nu
depozitează niciodată chei (te ține în afara rolului de procesor).

**Q24 — Build-ul enterprise pornește hardened-by-default, inclusiv kernelul ON înainte de criteriile
de promovare (4 săptămâni dogfood, zero DENY-uri false, soak 72h)?** Fiecare afirmație de guvernanță din
pitch e default-off în produsul livrat: `JARVIS_ACTION_KERNEL=0` (`.env.example:403`), guardrails WARN
(nu REDACT — PII curge neredactat spre cloud), retenție off, permission ledger off; owner-ul a mandatat
deja `JARVIS_HARDENED=1` + cheie de audit off-box pe orice cutie găzduită (BACKLOG L8169, 2026-09-01)
și `system_profiles.py` are deja mecanismul de preset (6 profile, niciunul enterprise).
*Recomandare (mai mult inginerie decât decizie):* un profil „enterprise” care forțează tot, un endpoint
de atestare pe care clientul îl poate audita (există deja `GET /api/security/posture`), primele
săptămâni de pilot dublând soak-ul kernelului; produsul personal își păstrează default-urile.

---

## 5. Întrebări comerciale și de echipă

**Q25 — Modelul de business.** Hardware la cost-plus + €15–25/loc/lună (sub Copilot), licență anuală
per cutie €10–20k/an cu update-uri și suport, locuri nelimitate (modelul HTX), sau serviciu gestionat
lunar cu hardware în leasing, operare și raportare de conformitate? Ancore: Copilot $30, Gemini
Enterprise $21–30, Claude Enterprise $20, Dust €29, Glean $25–75/utilizator/lună; HTX ~€12–20k/an pentru
50 utilizatori. Marja pe un Spark de ~€6k e subțire și prețul se mișcă lunar. *Recomandare:* licență
anuală per cutie, locuri nelimitate înăuntru, hardware trecut la cost-plus; add-on de operare gestionată
pentru clienții reglementați.

**Q26 — Metricul de succes al pilotului.** North-star-ul actual („acțiuni autonome acceptate pe
utilizator activ”) și bugetul ≤4 întreruperi/zi sunt proiectate pentru atenția unui singur owner și
`north_star.py` are `active_users` hardcodat 0/1. Ce măsori la client: ore economisite, latența
raportului, tichete rezolvate, acțiuni acceptate per departament, % local?

**Q27 — Echipa și pista.** Bus factor 1 + vânzare enterprise + logistică hardware + suport on-site în
România + roadmap 1.x live. Al doilea inginer? Partener pentru hardware/on-site? Buget pentru un Spark de
validare (€5–6k net) și pentru pen-test? Ce aduce Digitaholic (clienți de agenție, vânzări, legal)?

**Q28 — Ce se întâmplă cu Nerva personal și cu brandul.** Rămâne produs OSS în același repo („Nerva”
motor + „Nerva for Business”), devine linie separată, sau se oprește? Legat de D5 și D7.

---

## 6. Harta onestă: ce se transferă, ce lipsește, ce aș îngheța

| Zonă | Se transferă (real) | Lipsește pentru B2B (mărime) |
|---|---|---|
| Guvernanță | Action Kernel `authorize` GRANT/DENY/QUEUE, contracte high-risk, taint, kill-switch + ESTOP, politică de risc 4 tier-uri always-on, bugete bani 50/200 | Kernel ON implicit (S), lanțuri de aprobare pe roluri (L) |
| Audit | Lanț Merkle + `verify_chain`, IntentLog HMAC, chitanțe Proof-of-Action | Actor/subiect în `security_events` și `Action` (M), export SIEM/CEF (M), ancoră WORM (S) |
| LLM | Router hibrid cu podea locală impusă în cod, LM Studio/Ollama/orice OpenAI-compatible local, Anthropic/Gemini/OpenRouter/DeepInfra, poartă de consimțământ per furnizor, cost per model | Control de admisie / backpressure (L), tier memorie unificată 64/128 GB (S), adaptoare Azure OpenAI/Vertex EU (M) |
| Identitate | `Principal` per tură, `proxy_trust.py`, TokenStore cu TTL/rotație, pairing per sender pe canale | OIDC relying party + sesiuni (L), roluri/departamente (L), partiționare per utilizator a memoriei/sesiunilor/canvas/aprobărilor (XL), credențiale per angajat (M) |
| Integrare | Client MCP călit (trust tiers, SSRF-pinned HTTP), MCP server mode cu OAuth 2.1 RS, write-back mediat de kernel, SecretBroker `{{secret:…}}`, webhook-uri inbound semnate, EventWatcher probes, n8n client | Bucla de tool-uri ON (S), tool-uri MCP oferite modelului (M), HTTP MCP deblocat (S), orice conector la sistem de business (XL), tool SQL read-only (M), n8n apelabil (S) |
| Cunoaștere | KG bi-temporal, fuziune RRF vector⊕graf, Embedder, local_docs, drive_sync | Formate xlsx/csv/pptx/eml + OCR (M), ingestie incrementală cu ștergere (M), filtrare per departament (M), citări (S), model de entități de companie (L) |
| Rapoarte/automatizare | Motor DAG, APScheduler, Jobs cu blueprint-uri, coadă de aprobare cu decision inbox, webhook → workflow | Nod date/SQL/HTTP în DAG (XL cu conectorii), writer PDF/XLSX + tabele/grafice (L), authoring non-tehnic (L), livrare email/Teams pentru rapoarte (M) |
| Deployment | systemd hardened, Docker hash-pinned, imagine multi-arch (privată), bootstrap stdlib + `nerva doctor`, backup nightly + restore drill, export/forget | Validare ARM64/Spark (M), bundle offline (M), canal de update semnat + rollback (M), backup off-box (M), reverse-proxy TLS + provisioning first-boot (S), benchmark pe Spark (S, owner) |
| Securitate | Guardrails PII/secret (CNP, IBAN RO), SSRF, egress allowlist strict, profil hardened, sandbox, 173 fișiere de test de securitate | Guardrails REDACT implicit (S), PII NER/EU (M), chei off-root + Vault (M), TLS inbound/segmentare (M), pen-test extern + politici (L), per-angajat export/ștergere (M) |
| Comercial | Apache-2.0 curat, pipeline de release în CI, SBOM, pricing B2B pe hârtie (VALUATION §5) | Copyright holder (S), open-core/EULA/DPA (S–M), licență semnată offline (M), metering per client (M), heartbeat de flotă opt-in (XL dacă e backend), brand Nerva (S) |

**Balast pentru acest cumpărător — de înghețat explicit, nu de șters:** House Brain / Atlas casă
(`agents/core/house/*`, Hestia, O30), camere/Vision (O31, Frigate), Media Director + Spotify, Frigga
(familie) și Howard (twin, pipeline SFT), `seed_graph.py` personal, WorldView 4D OSINT + Argus (stack
separat), plugin-urile de consumator (apple_health, homebridge, iot_control, whatsapp_bridge, weather,
news, stock_quotes, signal_layer, osint_enrich), programul „hands” (drivere Windows/macOS/Linux,
Playwright, grounding vizual, benchmark operator), sprintul Hermes 697 și bara S1–S4, vocea dincolo de
STT/TTS de bază (wake word, orb, cinema mode), autonomia ambientală de noapte și „finds its own work”
(fără contract de obiectiv e exact ce va bloca echipa de securitate a cumpărătorului), pachetul de
marketing consumer (ICP Hank/Priya/Carla, Show HN), aplicația mobilă în afara tab-ului Approvals.

---

## 7. Fapte de piață (13 oct 2026; reconfirmă înainte de ofertă)

### Hardware — DGX Spark și alternative

| Element | Valoare | Încredere |
|---|---|---|
| Spark GB10 | 20 nuclee Arm, 6.144 CUDA, 128 GB LPDDR5x unificat la **273 GB/s**, ConnectX-7 2×200 GbE, 1/4 TB NVMe, ~240 W | mare (docs NVIDIA) |
| Preț | US $3.999 → $4.699 (feb 2026); unități partener UE **€5.038–5.800 net** (sept 2026); retail RO **28–40k lei**; SKU 64 GB $4.999 din 23 oct 2026 (OEM only); 128 GB in-stock raportat ~$6.950 — **neverificat** | medie |
| gpt-oss-120b MXFP4, 1 stream | 55–60 tok/s (40 la 32K context) | mare |
| gpt-oss-120b, vLLM concurent | 8 streamuri → 15 tok/s fiecare; 16 → 11; 32 → 8; vârf agregat ~860 tok/s la 256 | mare (o singură sursă) |
| Dense 70B (Llama 3.3 Q4/FP8) | **2,7–4,6 tok/s** — inutilizabil interactiv | medie |
| Două Spark-uri (un cablu QSFP DAC ~€150) | Qwen3-235B-A22B ~12 tok/s; capacitate, nu viteză; suport oficial 2 unități | medie |
| RTX PRO 6000 Blackwell 96 GB | card €17–18k UE; ~1.000 tok/s agregat pe 70B dense, 5–10× Spark | medie |
| DGX Station GB300 | 784 GB, €105–175k UE, Q4 2026 | medie |
| Dual RTX 5090 | 27 tok/s pe 70B Q4, ~€8–10k, nu ține 120B+ MoE, nu e appliance | medie |

Regula de dimensionare: pe Spark viteza e limitată de bandă → **doar modele MoE**; ~16–32 sesiuni de
chat simultane sau ~10–20 rulări de agent concurente per cutie; raportele grele se programează noaptea.

### Competitori și ancore de preț

Microsoft 365 Copilot $30/utilizator/lună ($21 Business ≤300), Copilot Studio 25k credite = $200/lună,
Agent 365 $15; Gemini Enterprise $21–30; Claude Enterprise $20 + utilizare; Dust €29; Glean $25–75
(~$60k minim anual); n8n self-hosted Business €667/lună; Relevance AI de la $19–29; OpenAI Frontier
sales-led. Substitutul gratuit cel mai direct pe un Spark: **NVIDIA NemoClaw** (OpenClaw/Hermes în
sandbox OpenShell, Nemotron 3) — NVIDIA îl va promova cu cutia. Obiecția DIY: Open WebUI / Onyx (EE cu
SSO/RBAC) / AnythingLLM pe Spark. „AI in a box” există ca categorie în 2026 la €6k–130k (eRacks, Zanus,
HTX PRISMA ~€12–20k/an pentru 50 utilizatori); **niciunul cu conectori fiscali/ERP românești**.
Diferențiatorii rămași: conectori românești, workflow-uri de departament, coadă de aprobare + audit
Merkle, local-first demonstrabil.

### Reglementare

AI Act: vezi Q20. GDPR: clientul e controller; Digitaholic e procesor de îndată ce are acces remote
(suport, update-uri, monitorizare) → DPA Art. 28, ingineri în SEE sau TIA, listă de sub-procesori; orice
LLM cloud apelat e sub-procesor. NIS2 România: OUG 155/2024 (30 dec 2024) + Legea 124/2025; DNSC
autoritate; esențiale ≥250 angajați / €50M, importante ≥50 / €10M; amenzi până la €10M / 2%. DORA: din
17 ian 2025, BNR/ASF; nu s-a găsit o regulă care să impună on-prem pentru bănci sau sector public —
preferința e de politică, nu de lege.

### România — piața

Eurostat 2025: 5,21% din firme folosesc AI (UE 19,95%), 24,9% cumpără cloud (UE 52,7%). ~660–690k firme
active (INS/ONRC 2024). SmartBill 150–170k clienți, REST API; Oblio OAuth2; FGO API pe Premium; SAGA
dominant fără API public; e-Factura obligatoriu B2B din 2024, B2C din 2025, termen 5 zile lucrătoare
din 2026. Cota M365 vs Google Workspace în România: fără date.

---

## 8. Patru încadrări alternative (pentru a nu rămâne cu una singură)

1. **Analist AI guvernat pentru UN departament** (pană verticală): 2–3 sisteme prin MCP/n8n +
   ingestie de drive, un raport programat „verified-only” (work_runs + company_report), Q&A pe KG-ul
   bi-temporal, O automatizare cu aprobare. Single-tenant, SSO al clientului, model local-sau-cloud per
   politică. Refolosește kernel/audit/router/memorie/ingestie/aprobări; aruncă tot ce e fizic.
2. **Gateway AI privat + pachete de agenți**: cutia (sau VM-ul) ca poartă guvernată de inferență și
   acțiune — podele locale per data space, allowlist de egress, audit Merkle, kill switch, atribuire de
   cost — expusă prin MCP Server Mode clienților pe care compania îi are deja (Claude Desktop, Cursor,
   Copilot Studio, boți Teams), cu „pachete” de departament (șabloane SOUL + grant-uri de conectori +
   programări de rapoarte) vândute ca add-on. UI minim; concurează cu LiteLLM/Portkey/Open WebUI.
3. **Serviciu gestionat Digitaholic, cloud-first, cutia mai târziu**: spec-ul demo digitaholic.ro
   (container hardened per tenant, LLM cloud, auto-deploy din main) devine modelul de producție — o
   instanță per client într-o regiune UE sau pe VM-ul lui, NBD SLA, modele EU-cloud implicit cu listă
   de sub-procesori; Spark on-prem doar după semnătură și benchmark-uri ARM64.
4. **Agency OS pe propria mâncare**: implementezi în Digitaholic întâi (Meta Ads, Postiz, analytics,
   Notion CRM, Gmail/Calendar — toate plugin-uri existente) pentru raportare de clienți și operațiuni de
   campanie; n = 2 cu roluri GDPR și aprobări reale; apoi vinzi aceeași instalare la 2–3 clienți de
   agenție. Cel mai puțin cod nou dintre toate; aliniază lista de departamente cu credibilitatea reală.

---

## 9. Proveniență și ce nu e verificat

- Hărțile pentru identitate, deployment/hardware, conectori, rapoarte/automatizări și
  securitate/conformitate au trecut printr-un al doilea cititor adversarial care a refuzat ~30 de
  afirmații (ex. „Teams nu există” — fals, există adapter webhook; „vLLM nu e local” — fals, slotul
  lm-studio e OpenAI-compatible generic; „fără filtrare de metadate în vector store” — fals, există
  `search_by_text_subset` neapelat). **Licență/operare nu a avut al doilea cititor**: citările sunt
  probabile, nu confirmate.
- Fapte externe afirmate și neverificabile din repo: LM Studio fără build server Linux ARM64;
  `nvidia-smi` pe GB10 raportează memoria non-numeric; DGX OS include Docker; GitHub oferă runner-e
  `ubuntu-24.04-arm` pentru repo-uri publice.
- Piață neverificată: prețul US curent al Spark 128 GB; suport oficial > 2 Spark-uri stivuite; debit pe
  405B dense pe două Spark-uri; prețuri RO pentru Dell/HP/Lenovo/ASUS GB10 și tratamentul TVA (21%
  presupus); Mac Studio M5 Ultra 512 GB (neexpediat); prețuri Glean/Sierra/Frontier (estimări); cote
  SAGA/SeniorERP/Charisma; dacă Art. 26 e legat formal de 2 dec 2027; cifrele EIB pentru România.
- Numărătorile din cod sunt la HEAD `413a42c` (2026-10-13): 626 rute, 173 fișiere de test de securitate
  din 1.296, 17.308 funcții `def test_`, 24 clienți de integrare reali din 28 module plugin.
