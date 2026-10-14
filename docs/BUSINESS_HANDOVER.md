# Nerva Business — handover curent

Actualizat: **14 octombrie 2026, Europe/Bucharest**. Obiectiv: un pilot Nerva
Business comercializat de Digitaholic, pornind de la un magazin de haine.
Acest fișier este punctul de reluare pentru alt calculator sau alt agent.

## Cod și publicare

- Repository: <https://github.com/andrei649/jarvis-hub>.
- Ramură: `feat/nerva-business-platform`; bază: `413a42ceedb9302f47b1dfff9f76f984cdd355e4`.
- `3d100ac144ee17b04ec2ffd871157796e28f612a`: implementarea inițială Business.
- `4ab3f848392023c20376ad0e2281b4c5155bb29e`: filtre, exporturi, exemple și ghidarea probei.
- Commitul care introduce acest handover actualizează numai documentația și
  descrierea regulii de continuitate; codul aplicației este cel de la `4ab3f84`.
- Regula proprietarului din 14 octombrie: înainte de pauză/final de sesiune,
  progresul trebuie salvat pe GitHub împreună cu handover. `AGENTS.md` o păstrează.
- Publicare vizată: ramura de mai sus și un draft PR către `main`. Confirmarea
  transportului este SHA-ul remote, verificabil prin `git ls-remote` și prin PR.
  Publicarea codului nu înseamnă instalare pe MacBook, merge sau deployment.

Mediul de dezvoltare a fost un executor Linux cloud, în `/workspace/jarvis-hub`.
Serverul temporar de verificare a fost oprit. Nu există o instalare nouă pe
MacBook și nu există un proces promis să lucreze în fundal după sesiune.

## Ce funcționează în pilot

Profil de companie; adaptoare WooCommerce/HubSpot numai pentru citire și import
CSV; sincronizare manuală; rapoarte deterministe de vânzări/stocuri/oportunități;
filtrare pe o sursă și, pentru vânzări, perioadă UTC; export JSON/CSV; întrebări
AI folosind indicatorii actuali sau un raport salvat; interfață web adaptată
telefonului, exemple sintetice și mesaje utile de eroare.

Principalele zone modificate sunt `agents/core/business/`,
`agents/core/routers/business.py`, `frontend/src/panels/business*`, API-ul
frontend, bundle-ul `agents/web/v2`, testele `tests/test_business*`, fișierul
`docker-compose.business.yml`, exemplele și documentația Business.
Inventarul exact: `git diff --name-only 413a42c..HEAD`.

O instalare / un `JARVIS_HOME` înseamnă o companie; utilizatorii autentificați
văd aceleași date Business. Nu există încă permisiuni separate pe departamente.
Limite: 500 de înregistrări/tip/sincronizare, maximum 100 de rânduri într-un
raport și ultimele 100 de rapoarte în istoric, 3 cereri AI simultane/proces.
Pilotul folosește un singur worker. Aceste limite nu sunt benchmark DGX.

## Reluare pe Mac sau alt calculator

Pentru un checkout nou, cu Git și Python 3.12+ instalate, rulează:

```bash
git clone --branch feat/nerva-business-platform --single-branch https://github.com/andrei649/jarvis-hub.git nerva-business
cd nerva-business
git log -3 --oneline
export JARVIS_HOME="$HOME/.nerva-business-pilot"
export NERVA_BUSINESS_ENABLED=1
export JARVIS_HOST=127.0.0.1
export JARVIS_PORT=8080
./install.sh --no-start
./start.sh
```

După pornire și răspunsul `/readyz`, deschide
<http://127.0.0.1:8080/v2/console/business>. Dacă portul 8080 este ocupat,
alege alt `JARVIS_PORT` și folosește același port în URL. La fiecare pornire,
păstrează aceleași variabile și același director de date. Instalarea nativă pe
Mac este documentată, dar nu a fost executată în mediul acestei sesiuni.

Într-un checkout existent, verifică întâi `git status`, păstrează modificările
locale și rulează `git fetch origin`. Comută pe ramura de mai sus, creând-o cu
tracking dacă nu există local, apoi folosește `git pull --ff-only`. Dacă ramurile
au divergențe, reconciliază-le explicit; nu reseta sau forța push-ul.

Alternativa Docker este în [BUSINESS.md](BUSINESS.md); pe Docker Desktop 4.34+
activează host networking. Bundle-ul web este deja versionat, deci nu ai nevoie
de build frontend pentru proba inițială din checkout.

Git transferă codul, nu profilul companiei, bazele de date, cheile sau modelele.
În această sesiune s-au folosit numai date sintetice într-un director temporar.
Pentru migrarea unei instalări reale, oprește aplicația și transferă separat,
prin mecanismul privat de backup, directorul persistent `JARVIS_HOME` și materialul
de chei al instalării. SecretStore Business folosește în mod obișnuit fișierul
`business/credentials.secret.json.key`; dacă instalarea folosește o cheie din
configurarea mediului, păstrează acea configurare separat. Nu publica aceste
date în Git. Restaurarea/migrarea între calculatoare nu a fost validată aici.

## Dovezi și limite de verificare

Pentru codul aplicației de la `4ab3f84`, în această sesiune:

- **208 teste backend de integrare selectate au trecut**, inclusiv cele 73 Business.
- **2.198 teste frontend au trecut** în suita completă.
- 43 verificări suplimentare de schemă/status au trecut; TypeScript, build Vite,
  Ruff și verificările de paritate au trecut. Build-ul păstrează avertismentul
  existent de dimensiune a unui bundle.
- Chromium real, 1440 px și 390 px: import explicit, filtre, exporturile
  descărcate, stocuri, persistență la reîncărcare și refuz AI fără model au trecut.
  Exemplul produce 339,40 RON total, respectiv 249,90 RON pentru 2026-10-01.
- **25.614 teste backend au fost colectate; suita backend completă nu a fost rulată.**
- Conturile reale WooCommerce/HubSpot, inferența locală/cloud, DGX, VPN,
  construcția imaginii Docker și instalarea pe Mac rămân neverificate.

Comandă reproductibilă pentru integrarea backend (după instalarea dependențelor
de dezvoltare conform repository-ului):

```bash
.venv/bin/python -m pytest tests/test_business*.py tests/test_company_routes.py tests/test_route_parity_guard.py tests/test_route_auth_matrix.py tests/test_openapi_parity_guard.py tests/test_hud_v2_parity.py tests/test_lifespan_smoke.py tests/test_http_client_ssrf_pinning.py tests/test_h513_data_handling.py -o addopts='--timeout=30 --timeout-method=thread --allow-hosts=127.0.0.1,::1,localhost' -q
```

Frontend: în `frontend/`, după `npm ci`, rulează `npm test`,
`npm run typecheck` și `npm run build`. Logurile temporare din executor nu sunt
necesare pentru reluare; rezultatele sunt consemnate în această documentație.
Statusul CI GitHub se citește din PR, separat de aceste verificări locale.

## Următoarea acțiune

1. Execută [proba de zece minute](BUSINESS_TEST.md) pe calculatorul ales.
2. Pentru magazinul real, adaugă o conexiune cu chei de citire și compară un
   raport pe o singură sursă cu datele magazinului. Verifică explicit variațiile,
   rambursările și acoperirea; pilotul are limite documentate în ghid.
3. Configurează un model local sau un furnizor API permis de politica Nerva și
   verifică răspunsul despre raportul selectat. Abonamentul ChatGPT nu include
   consumul API al aplicației.
4. Continuă după constatările probei și rândurile BIZ-3–BIZ-7 din `BACKLOG.md`:
   automatizări, conectori email/telefon, permisiuni, facturare și dimensionare
   hardware. Nu declara aceste funcții livrate înainte de implementare.

Pentru alt agent: citește `AGENTS.md`, acest fișier, `docs/BUSINESS.md` și
`docs/BUSINESS_TEST.md`; inspectează branch/head/status înainte de modificări.
Actualizează acest handover și verifică push-ul înainte să închei sesiunea.

Rollback: oprește aplicația și dezactivează `NERVA_BUSINESS_ENABLED`; păstrează
directorul de date și cheile. Dacă trebuie eliminat codul, cele două commituri
de implementare sunt unitățile de revert, în ordine inversă; nu reseta istoricul
publicat și nu șterge datele companiei.
