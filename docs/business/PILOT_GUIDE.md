# Nerva Workspace — ghidul pilotului

> **Pentru cine:** cine instalează și operează un pilot Nerva Workspace la o companie, fără să
> cunoască deja codul. Pornește de la un server gol și se termină cu un spațiu de lucru în care
> angajații se autentifică, întreabă asistentul pe baza documentelor firmei, rulează rapoarte și
> aprobă acțiuni.
> **Stare:** pilot, 2026-10-17. Contractul tehnic este
> [`WORKSPACE_PILOT_SPEC.md`](WORKSPACE_PILOT_SPEC.md); întrebările de business încă deschise
> (D1–D7) sunt în [`../decisions/2026-10-14-nerva-business-suite-kickoff-questions.md`](../decisions/2026-10-14-nerva-business-suite-kickoff-questions.md).
> Fișierul proxy de referință: [`../../deploy/workspace/Caddyfile.example`](../../deploy/workspace/Caddyfile.example).
> Toate valorile din acest ghid (limite, durate, coduri de eroare) sunt citite din cod, din
> `agents/core/workspace/` și `agents/core/routers/workspace_*.py`.

## 0. Pe scurt

**Ce primiți.** O aplicație web separată, servită de hub-ul Nerva la `/workspace/`, cu conturi
proprii pentru angajați, departamente și roluri:

- **Asistent** — întrebări în limba utilizatorului, cu răspunsuri bazate pe documentele
  departamentului și pe cele publicate în toată compania, cu citări `[n]` care deschid pasajul sursă.
- **Documente** — încărcare PDF, DOCX, XLSX, CSV, TXT, MD; indexare full-text; previzualizare,
  descărcare, ștergere; cerere de publicare în toată compania.
- **Rapoarte** — rapoarte definite o dată și rulate la cerere, zilnic sau săptămânal; export
  Markdown/HTML, tipărire, partajare în companie, trimitere pe email.
- **Aprobări** — orice acțiune cu efect în afara spațiului de lucru (email, partajare în toată
  compania) cere decizia unei alte persoane, numite în jurnal.
- **Administrare** — utilizatori, departamente, organizație și politica modelului AI, email
  (SMTP), audit cu lanț HMAC verificabil, statistici de utilizare.

**Ce nu face acest pilot:** nu există OIDC/SAML nativ (doar SSO printr-un proxy, §11), nici
conectori ERP/CRM/contabilitate, nici OCR (§18). Spațiul de lucru nu folosește niciodată
memoria, agenții sau conversațiile personale ale proprietarului hub-ului.

**Arhitectura pe un server:**

```
browser ──HTTPS──▶ Caddy :443 (nerva.firma.ro)  ── doar /workspace* și /api/workspace/* ──▶ hub 127.0.0.1:8080
                                                                                             │
                                                     server de model pe loopback ◀──────────┘
                                                     (Ollama :11434 sau vLLM :8000)
```

Hub-ul ascultă doar pe loopback. Caddy publică numai căile spațiului de lucru, deci Command
Center-ul proprietarului (`/v2`) și restul API-ului hub-ului rămân accesibile doar de pe server.

## 1. Cerințe

| Ce | Minim pentru pilot |
|---|---|
| Sistem | Linux cu systemd (exemplele folosesc Ubuntu 24.04 / Debian 12). Windows și macOS rulează hub-ul, dar acest ghid acoperă doar Linux. |
| Python | 3.12 sau mai nou (`python3 --version`). Instalatorul refuză versiunile mai vechi cu un motiv explicit. |
| Disc | Codul + mediul Python: câțiva GB. Datele: documentele încărcate (originalele se păstrează) plus 7 copii de siguranță zilnice. Modelul AI: de la ~2 GB (model mic, CPU) la zeci de GB. |
| Memorie | Depinde aproape exclusiv de model (§3). Hub-ul în sine este un proces Python. |
| Rețea | Un nume DNS dedicat (ex. `nerva.firma.ro`) care indică serverul; portul 443 (și 80 pentru Let's Encrypt) deschis pentru utilizatori; ieșire HTTPS pentru instalare. |
| Email | Opțional: un cont SMTP al companiei pentru invitații, rapoarte și emailuri aprobate (§9). |
| Node.js | **Nu** este necesar: interfața este deja compilată în `agents/web/workspace/`. |

## 2. Instalarea hub-ului

Exemplele presupun codul în `/opt/jarvis-hub`, datele în `/var/lib/jarvis-hub`, cheile în
`/var/lib/jarvis-keys` și un utilizator de sistem `jarvis`. Le puteți schimba, dar atunci
schimbați-le peste tot (inclusiv în unitatea systemd).

```bash
# 1. utilizator de serviciu fără login și directoarele lui
sudo useradd --system --home /var/lib/jarvis-hub --create-home --shell /usr/sbin/nologin jarvis
sudo install -d -o jarvis -g jarvis -m 0700 /var/lib/jarvis-hub /var/lib/jarvis-keys

# 2. codul (sau copiați checkout-ul primit de la Digitaholic în /opt/jarvis-hub)
sudo git clone https://github.com/andrei649/jarvis-hub.git /opt/jarvis-hub
sudo chown -R jarvis:jarvis /opt/jarvis-hub

# 3. mediul Python cu dependențele fixate prin hash + testul de pornire (fără a porni serverul)
sudo -u jarvis bash -c 'cd /opt/jarvis-hub && ./install.sh --no-start'
```

`install.sh` creează `.venv`, instalează `requirements-beta.lock` cu `--require-hashes` și rulează
un test real de pornire. Un eșec se termină cu un motiv numit (tabelul din
[`../INSTALL.md`](../INSTALL.md) → *Troubleshooting by reason*).

**Serviciul systemd.** Folosiți unitatea din repo; ea pornește `serve.py` pe `127.0.0.1:8080`,
cu `JARVIS_HOME=/var/lib/jarvis-hub` și protecțiile systemd (`ProtectSystem=strict`,
`ProtectHome=yes`):

```bash
sudo cp /opt/jarvis-hub/deploy/systemd/jarvis-hub.service /etc/systemd/system/
sudo install -d -m 0700 /etc/jarvis-hub
sudo install -m 0600 /dev/null /etc/jarvis-hub/jarvis.env      # se completează în §4

# directorul de chei trebuie să fie inscriptibil pentru serviciu (ProtectSystem=strict)
sudo install -d /etc/systemd/system/jarvis-hub.service.d
printf '[Service]\nReadWritePaths=/var/lib/jarvis-keys\n' \
  | sudo tee /etc/systemd/system/jarvis-hub.service.d/keys.conf
sudo systemctl daemon-reload
```

Nu porniți încă serviciul: întâi modelul (§3) și configurarea (§4). Detalii despre unitate:
[`../../deploy/systemd/README.md`](../../deploy/systemd/README.md).

**Comanda de operare.** Comenzile de recuperare și de backup trebuie să ruleze cu **exact
același mediu** ca serviciul: același `JARVIS_HOME` (altfel deschid altă bază de date), același
`JARVIS_KEY_DIR` (altfel semnează rândurile de audit cu altă cheie, iar verificarea lanțului
raportează `key_mismatch`) și același `NERVA_WORKSPACE`. Cel mai sigur este să le rulați ca o
unitate systemd temporară care citește același fișier de mediu:

```bash
# adăugați în ~/.bashrc al administratorului serverului
nerva-run() {
  sudo systemd-run --quiet --pipe --wait --collect \
    -p User=jarvis -p Group=jarvis \
    -p EnvironmentFile=/etc/jarvis-hub/jarvis.env \
    -p WorkingDirectory=/opt/jarvis-hub \
    /opt/jarvis-hub/.venv/bin/python "$@"
}
```

Pentru asta, **toate** variabilele hub-ului stau în `/etc/jarvis-hub/jarvis.env` (inclusiv
`JARVIS_HOME`, deși unitatea îl setează și ea). `JARVIS_HOME` nu este citit niciodată dintr-un
fișier `.env` al repo-ului — doar din mediul procesului — de aceea fișierul systemd este locul
potrivit.

## 3. Serverul de model (pe loopback)

Spațiul de lucru cere modelul **routerului hub-ului**, sub politica organizației. Cu politica
implicită `local_only` folosește doar backend-ul local detectat de hub: un server
OpenAI-compatible (slotul `lm-studio`, adresa `JARVIS_LM_STUDIO_URL`, implicit
`http://localhost:1234`) sau Ollama (`JARVIS_OLLAMA_URL`, implicit `http://localhost:11434`).
Hub-ul îl sondează pe primul, apoi pe al doilea, la pornire și apoi la fiecare 5 minute — un
server pornit după hub este găsit fără repornire.

**Un server pe loopback (`127.0.0.1` / `localhost`) este clasificat `local`:** nicio dată nu
părăsește mașina și nu este nevoie de nicio confirmare. Este recomandarea pentru pilot.

**Hub-ul folosește primul model raportat de server** (`GET /api/tags` la Ollama,
`GET /v1/models` la un server OpenAI-compatible). Pe serverul pilot păstrați **un singur model**
descărcat/servit, ca să știți exact ce răspunde.

### 3.1 Ollama — server fără GPU sau cu un GPU obișnuit

```bash
curl -fsSL https://ollama.com/install.sh | sh     # instalează serviciul ollama, ascultă pe 127.0.0.1:11434
ollama pull qwen2.5:7b                            # alegeți o singură linie din tabelul de mai jos
ollama list
```

Sugestii de pornire, aceleași trepte pe care hub-ul le folosește pentru recomandarea locală
(`TIERS` în `agents/core/llm/model_setup.py`). Sunt alegeri de dimensiune, **nu** măsurători de
viteză; verificați întâi calitatea răspunsurilor în română pe documentele voastre:

| Hardware | Model Ollama sugerat | Descărcare aprox. |
|---|---|---|
| Doar CPU / RAM | `qwen2.5:3b` | 1,9 GB |
| GPU cu 8 GB VRAM | `qwen2.5:7b` | 4,7 GB |
| GPU cu 12–16 GB VRAM | `qwen2.5:14b` | 9 GB |
| GPU cu 24 GB+ | un model mai mare (ex. `qwen2.5:32b`) — testați-l înainte de a-l promite | ~20 GB |

**Fereastra de context.** Un prompt al asistentului conține până la 6 pasaje (≤ 1 500 de
caractere fiecare), ultimele 8 mesaje (≤ 6 000 de caractere în total) și întrebarea
(≤ 8 000 de caractere) — câteva mii de tokeni. Un raport folosește 10 pasaje și cere până la
2 000 de tokeni de răspuns. Fereastra implicită a Ollama poate fi mai mică, iar Ollama taie
promptul în tăcere. Setați fereastra în hub (setarea `llm.ollama_num_ctx`, „Ollama context
tokens”) după primul start al hub-ului (§4) și reporniți-l:

```bash
nerva-run scripts/nerva.py config set llm.ollama_num_ctx 16384   # 8192 pe un server doar cu CPU
sudo systemctl restart jarvis-hub
```

### 3.2 vLLM — DGX Spark sau o stație cu GPU RTX

vLLM expune un API OpenAI-compatible, pe care hub-ul îl folosește prin slotul `lm-studio`
(un client OpenAI-compatible generic — nu e nevoie de LM Studio):

```bash
vllm serve <model> --host 127.0.0.1 --port 8000 --max-model-len 16384
```

și în mediul hub-ului (§4): `JARVIS_LM_STUDIO_URL=http://127.0.0.1:8000` (fără `/v1`).

Pentru un DGX Spark, faptele datate din documentul de kickoff (§7, 13 oct 2026 — reconfirmați
înainte de orice ofertă): memoria unificată de 128 GB are lățime de bandă limitată, deci pe Spark
sunt utilizabile **doar modele MoE** — `gpt-oss-120b` MXFP4 a fost măsurat public la 55–60 tok/s pe
un singur flux, iar modelele dense de 70B la 2,7–4,6 tok/s, inutilizabile interactiv. Pe Spark,
vLLM se rulează de regulă din containerul publicat de NVIDIA; urmați documentația NVIDIA pentru
imagine și parametri.

**Modele care „gândesc” (reasoning).** Asistentul cere cel mult 1 200 de tokeni per răspuns. Un
model care își consumă bugetul raționând răspunde cu eroarea `model_unavailable` / motiv
`thinking_exhausted` (§17). Pentru pilot preferați un model *instruct* fără raționament lung, sau
reduceți efortul de raționament al modelului din serverul de model.

### 3.3 Un server de model pe altă mașină (non-loopback) — confirmarea de date

Dacă modelul rulează pe altă mașină din rețea (ex. un DGX Spark separat,
`JARVIS_LM_STUDIO_URL=http://10.0.0.20:8000`), hub-ul nu mai poate dovedi că datele rămân local:
politica de date a rutei devine `unknown`. Spațiul de lucru face apeluri **nesupravegheate**
(fără proprietarul hub-ului în buclă), așa că orice rută `unknown` este refuzată cu
`409 model_policy_blocked`, motiv `data_policy_unacknowledged`, până când proprietarul hub-ului
confirmă explicit cum sunt tratate datele:

1. Pe server, deschideți Command Center-ul hub-ului: `http://127.0.0.1:8080/v2` (de pe altă
   mașină: `ssh -L 8080:127.0.0.1:8080 admin@server`, apoi aceeași adresă în browserul local).
2. Panoul **SECURITY POSTURE** → secțiunea de *data handling* → confirmați rândul furnizorului
   local (consimțământul se salvează în setarea `security.data_training_ack`).

Sau, din linia de comandă pe server (cu `JARVIS_ADMIN_TOKEN` dacă l-ați setat; fără niciun token
de admin configurat, hub-ul acceptă doar cereri directe de pe localhost):

```bash
curl -s -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" http://127.0.0.1:8080/api/security/posture \
  | python3 -c 'import json,sys; [print(p) for p in json.load(sys.stdin)["data_handling"]["providers"]]'
# copiați "provider" și "scope" din rândul cu policy "unknown", apoi:
curl -s -X POST -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"provider": "<provider>", "acknowledged": true, "scope": "<scope>"}' \
  http://127.0.0.1:8080/api/security/data-handling/ack
```

Confirmarea este legată de configurația exactă (furnizor, adresă, cheie): dacă schimbați adresa
serverului, trebuie dată din nou. Ea nu adaugă nicio rută cloud, iar ruta locală confirmată
funcționează sub ambele politici ale organizației (§8). Limitați accesul la portul
serverului de model (firewall) doar la adresa hub-ului: traficul hub → model este HTTP simplu.

## 4. Configurarea

Completați `/etc/jarvis-hub/jarvis.env` (root, mod `0600` — systemd îl citește înainte de a
renunța la privilegii). Generați cheile cu Python-ul din `.venv`:

```bash
/opt/jarvis-hub/.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # de 2 ori: secret + backup
/opt/jarvis-hub/.venv/bin/python -c "import secrets; print(secrets.token_hex(32))"                                    # cheia de audit
```

```ini
# ── hub ───────────────────────────────────────────────────────────────────────────
JARVIS_HOME=/var/lib/jarvis-hub
JARVIS_KEY_DIR=/var/lib/jarvis-keys
JARVIS_HOST=127.0.0.1
JARVIS_PORT=8080
# Obligatorii pe un pilot. Fără ele, cheia secretelor stă lângă secrete în directorul de date,
# iar copiile de siguranță nu sunt criptate (§13).
JARVIS_SECRET_KEY=<cheie Fernet>
JARVIS_BACKUP_KEY=<altă cheie Fernet>
# Cheia lanțului de audit. Dacă lipsește, se generează o dată în $JARVIS_KEY_DIR/workspace_audit.key.
JARVIS_AUDIT_KEY=<64 de caractere hex>
# În spatele Caddy pe aceeași mașină (§5):
JARVIS_TRUSTED_PROXIES=127.0.0.1
JARVIS_ALLOWED_HOSTS=nerva.firma.ro
# JARVIS_CORS_ORIGINS — NU îl setați. Spațiul de lucru nu trimite niciodată antete CORS.

# ── model (§3; una dintre ele) ────────────────────────────────────────────────────
JARVIS_OLLAMA_URL=http://127.0.0.1:11434
# JARVIS_LM_STUDIO_URL=http://127.0.0.1:8000

# ── Nerva Workspace ───────────────────────────────────────────────────────────────
NERVA_WORKSPACE=1
NERVA_WORKSPACE_COOKIE_SECURE=1
# Opționale, cu valorile implicite:
# NERVA_WORKSPACE_SETUP_CODE=            # gol = cod generat (§6)
# NERVA_WORKSPACE_MAX_UPLOAD_MB=25       # 1..200, în MiB; ridicați și limita din Caddy
# NERVA_WORKSPACE_SESSION_IDLE_HOURS=12  # 1..168
# NERVA_WORKSPACE_SESSION_MAX_DAYS=7     # 1..90
# NERVA_WORKSPACE_MAX_CONCURRENT_LLM=2   # 1..16, apeluri simultane la model (chat + rapoarte)
# NERVA_WORKSPACE_SCHEDULER=1            # rapoarte programate + curățenie
# NERVA_WORKSPACE_SSO_HEADER=            # §11
# NERVA_WORKSPACE_SSO_SECRET=            # §11
```

**Ce face fiecare variabilă a spațiului de lucru** (detalii și costuri: [`../FLAGS.md`](../FLAGS.md),
secțiunea *Nerva Workspace*):

| Variabilă | Implicit | Efect |
|---|---|---|
| `NERVA_WORKSPACE` | oprit | Citit la fiecare cerere. Oprit: fiecare `/api/workspace/*` răspunde `404 workspace_disabled`, pagina `/workspace` un 404 simplu, iar baza de date nu este creată. |
| `NERVA_WORKSPACE_SETUP_CODE` | nesetat | Codul pentru configurarea inițială. Nesetat: generat la prima nevoie în `<JARVIS_HOME>/business/setup-code.txt` (mod 0600) și șters după configurare. |
| `NERVA_WORKSPACE_COOKIE_SECURE` | `auto` | `1` = cookie-ul de sesiune poartă mereu `Secure`. `auto` = doar când cererea ajunge ca `https`. O valoare nerecunoscută revine la `auto` cu un avertisment în jurnal. |
| `NERVA_WORKSPACE_MAX_UPLOAD_MB` | 25 | Cel mai mare fișier acceptat, în MiB, între 1 și 200. |
| `NERVA_WORKSPACE_SESSION_IDLE_HOURS` | 12 | O sesiune neatinsă atâtea ore expiră (1–168). |
| `NERVA_WORKSPACE_SESSION_MAX_DAYS` | 7 | Durata maximă a unei sesiuni, oricât de activă (1–90). |
| `NERVA_WORKSPACE_MAX_CONCURRENT_LLM` | 2 | Câte apeluri la model rulează simultan în tot procesul (1–16); restul așteaptă până la 30 s. |
| `NERVA_WORKSPACE_SCHEDULER` | pornit | Planificatorul intern (rapoarte programate, expirări, curățenie), la fiecare 30 s. |
| `NERVA_WORKSPACE_SSO_HEADER` / `_SSO_SECRET` | nesetate | SSO prin proxy; ambele sunt necesare (§11). |

Valorile numerice în afara intervalului sunt aduse la limită, nu refuzate. Variabilele se citesc
la fiecare utilizare, dar după o modificare a fișierului systemd trebuie oricum
`sudo systemctl restart jarvis-hub` ca procesul să le vadă.

**`JARVIS_SECRET_KEY` se setează înainte de primul start.** Dacă o schimbați mai târziu, secretele
deja criptate cu vechea cheie nu mai pot fi citite: parola SMTP a spațiului de lucru apare ca
`smtp_password_unreadable` și trebuie reintrodusă (§9).

Porniți serviciul și urmăriți jurnalul:

```bash
sudo systemctl enable --now jarvis-hub
journalctl -u jarvis-hub -f        # așteptați "LLM backend online: …" și răspunsul 200 de la /readyz
curl -s http://127.0.0.1:8080/readyz
curl -s http://127.0.0.1:8080/api/workspace/session   # {"enabled": true, "setup_required": true, …}
```

## 5. Hostname dedicat în spatele Caddy

Instalați Caddy din pachetele oficiale (caddyserver.com/docs/install), apoi:

```bash
sudo cp /opt/jarvis-hub/deploy/workspace/Caddyfile.example /etc/caddy/Caddyfile
sudoedit /etc/caddy/Caddyfile            # înlocuiți nerva.firma.ro cu numele vostru
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl reload caddy
```

Ce asigură fișierul (varianta A, conturi locale):

- **Doar căile spațiului de lucru:** `/workspace`, `/workspace/*` și `/api/workspace/*` ajung la
  hub; orice altă cale primește 404 de la Caddy.
- **TLS:** cu DNS public și porturile 80/443 deschise, Caddy obține și reînnoiește singur un
  certificat Let's Encrypt. Pentru un nume intern (VPN/intranet), folosiți `tls internal`
  (instalați rădăcina CA a Caddy pe stații) sau certificatul companiei
  (`tls /cale/cert.crt /cale/cert.key`).
- **HSTS:** `Strict-Transport-Security: max-age=31536000` — browserele refuză HTTP simplu pentru
  acest nume timp de un an.
- **Dimensiunea corpului cererii:** încărcările sunt trimise ca corp brut. Limita Caddy
  (`max_size 26MiB`) stă puțin peste `NERVA_WORKSPACE_MAX_UPLOAD_MB` (25 MiB), astfel încât
  hub-ul răspunde el însuși cu `413 file_too_large`, tradus în interfață. Dacă ridicați una,
  ridicați-le pe amândouă.
- **Antetele de proxy:** Caddy păstrează `Host` și setează el `X-Forwarded-For` /
  `X-Forwarded-Proto`, ignorând valorile trimise de client. Cu `JARVIS_TRUSTED_PROXIES=127.0.0.1`
  hub-ul crede aceste antete doar de la Caddy: vede adresa reală a clientului (folosită la
  limitarea încercărilor și în audit) și schema `https` (linkurile de invitație încep cu
  `https://`, cookie-ul primește `Secure`).
- **`JARVIS_ALLOWED_HOSTS=nerva.firma.ro`:** fără el, garda anti-DNS-rebinding a hub-ului răspunde
  `400 host not allowed` pentru orice nume care nu e loopback sau IP.
- **Răspunsurile în flux (SSE)** ale asistentului sunt transmise imediat; Caddy nu le tamponează.
  Doar fișierele statice din `/workspace/assets/` sunt comprimate.
- **Fără jurnal de acces** în exemplu. Dacă îl activați: numele fișierelor încărcate apar în query
  string (`?filename=…`). Tokenurile de invitație stau în fragmentul URL (`#t=…`) și nu ajung
  niciodată la server.

Verificare din afara serverului:

```bash
curl -sI https://nerva.firma.ro/workspace/ | head -5          # 200 + Strict-Transport-Security
curl -s  https://nerva.firma.ro/api/workspace/session          # {"enabled":true,…}
curl -s -o /dev/null -w '%{http_code}\n' https://nerva.firma.ro/v2   # 404: Command Center-ul nu e public
```

## 6. Primul start: codul de configurare și administratorul

Configurarea inițială creează organizația, departamentul „General” și primul administrator. Este
protejată de un cod pe care îl poate citi doar cine are acces la server.

```bash
nerva-run -m agents.core.workspace setup-code
```

Comanda afișează codul (din `NERVA_WORKSPACE_SETUP_CODE`, sau îl generează în
`<JARVIS_HOME>/business/setup-code.txt`). Codul nu apare niciodată în jurnale — jurnalul numește
doar fișierul. Comanda refuză cu codul de ieșire 2 dacă `NERVA_WORKSPACE` este oprit, și cu 1 după
ce configurarea a fost făcută.

Apoi, în browser, `https://nerva.firma.ro/workspace/` afișează ecranul de configurare:

1. codul de configurare;
2. numele organizației;
3. numele, emailul și parola voastră (12–256 de caractere, fără partea dinaintea `@` a emailului,
   nu o parolă comună — altfel `422 weak_password` cu motivul `too_short`, `too_long`,
   `contains_email` sau `too_common`);
4. limba implicită (română sau engleză).

După succes sunteți autentificat ca administrator, fișierul cu codul este șters, iar
`POST /setup` răspunde de acum `409 already_setup`. Dacă ați pus codul în
`NERVA_WORKSPACE_SETUP_CODE`, scoateți-l din fișierul de mediu. Încercările greșite sunt limitate:
10 coduri greșite pe oră de la o adresă și 50 pe oră în total → `429 too_many_attempts`.

## 7. Utilizatori, roluri și departamente

**Departamente** (Administrare → Departamente): nume (unic, fără diferență între majuscule, inclusiv
diacritice), descriere și **instrucțiuni pentru asistent** (≤ 4 000 de caractere: ton, terminologie,
ce să evite — nu puneți date confidențiale aici). Un departament **arhivat** dispare pentru membri
(doar administratorii îl mai văd); în el nu se mai pot încărca documente sau pune întrebări
(`409 department_archived`). Ștergerea definitivă este permisă doar unui departament fără membri,
documente, rapoarte și conversații (`409 department_not_empty`).

**Utilizatori** (Administrare → Utilizatori → Invită): email, nume, rol și cel puțin un departament.
Contul este creat `invited`, cu un link de invitație de 72 de ore, folosibil o singură dată. Linkul
se copiază din dialog sau, cu SMTP configurat (§9), se trimite pe email. Persoana își alege parola
pe pagina de invitație și intră direct.

| Ce poate face | member | approver | admin |
|---|---|---|---|
| Asistent în departament | departamentele proprii | departamentele proprii | toate |
| Citește documente | ale departamentelor proprii + cele publicate în companie | la fel | toate |
| Încarcă documente | în departamentele proprii | în departamentele proprii | în orice departament + direct în toată compania |
| Șterge / reindexează un document | propriile încărcări (și după publicarea lor în companie) | orice document al cărui departament este unul dintre ale sale, oricare i-ar fi vizibilitatea | toate (un document publicat în companie fără departament: doar administratorii și cine l-a încărcat) |
| Rapoarte: vede, creează, rulează | departamentele proprii | departamentele proprii | toate |
| Rapoarte: editează / șterge | propriile rapoarte | orice raport al departamentelor proprii | toate |
| Cere o aprobare | da | da | da |
| Decide o aprobare de departament | — | în departamentele proprii, niciodată pe a sa | toate, niciodată pe a sa |
| Decide o aprobare de administrator | — | — | da (cererea proprie se execută imediat, §10) |
| Consola de administrare | — | — | da |

Conversațiile sunt private: nimeni, nici administratorul, nu citește conversațiile altcuiva. O
resursă din afara drepturilor voastre răspunde `404 not_found`, niciodată 403, ca să nu dezvăluie
că există.

**Reguli de siguranță:** ultimul administrator activ nu poate fi retrogradat sau dezactivat
(`409 last_admin`); nimeni nu se poate dezactiva singur (`409 cannot_disable_self`). Dezactivarea
unui cont sau schimbarea rolului îi închide toate sesiunile. Pentru un cont activ, „Link de
resetare a parolei” emite un link nou (72 h; cele vechi nu mai funcționează, iar la folosire
sesiunile persoanei se închid); pentru un cont încă invitat, „Link de invitație nou”. Un cont
dezactivat trebuie întâi reactivat (`409 user_disabled`). Schimbarea parolei din Profil închide
celelalte sesiuni ale utilizatorului.

## 8. Modelul AI și politica de date

Administrare → Organizație arată starea modelului (cipul **Local / Cloud / Indisponibil**) și
butonul **Testează modelul** (un apel scurt, cu limită de 60 s, auditat ca `model.tested`).

| Politică | Ce permite |
|---|---|
| `local_only` (implicit) | Doar backend-ul local al hub-ului (§3). Fără server local → `model_unavailable` / `no_local_model`. Nu cade niciodată pe cloud. |
| `allow_cloud` | Routerul hub-ului alege ruta (implicit local cât timp promptul are ≤ 8 000 de tokeni, apoi cloud; setările de rutare ale hub-ului pot schimba ordinea). O rută **cloud** este permisă doar dacă politica ei de date este `local` sau `no-training`; altfel `409 model_policy_blocked` / `provider_may_train`. În hub, Anthropic este declarat `no-training`; Gemini și furnizorii OpenAI-compatible generici sunt `unknown`, deci sunt refuzați. O rută **locală** permisă de verificarea de date (inclusiv un server din LAN confirmat, §3.3) funcționează la fel ca sub `local_only`: `allow_cloud` doar lărgește ce permite `local_only`, nu restrânge. |

Indiferent de politică, apelurile trec prin garda de securitate a hub-ului (guardrails) și prin
verificarea de tratare a datelor. Spațiul de lucru trimite modelului doar ce trebuie pentru
răspuns: instrucțiunile departamentului, pasajele găsite, ultimele mesaje ale conversației și
întrebarea. Instrucțiunile aflate în documente sunt tratate ca text, nu ca ordine. Promptul și
răspunsul nu se scriu niciodată în jurnale sau în audit.

## 9. Email (SMTP) și domeniile permise

Administrare → Email:

| Câmp | Regulă |
|---|---|
| Server și port | Gazdă sau IP; portul implicit depinde de securitate: `starttls` 587, `ssl` 465, `none` 25. |
| Securitate | `starttls` (implicit), `ssl` sau `none`. TLS folosește depozitul de certificate al hub-ului (inclusiv `JARVIS_CA_BUNDLE`). |
| Utilizator și parolă | Doar caractere ASCII (`422 … reason not_ascii`; biblioteca SMTP din Python nu poate trimite altceva). Parola se păstrează criptat în `<JARVIS_HOME>/business/secrets.enc`, nu este returnată niciodată de API (doar `has_password`). |
| Expeditor | Adresa și numele afișat. |
| Domenii permise | Opțional, până la 50. Dacă lista nu e goală, fiecare destinatar trebuie să aibă **exact** unul dintre domenii (`sub.firma.ro` nu este acoperit de `firma.ro`) → altfel `422 recipient_not_allowed`. |

Emailul este „configurat” când are server **și** expeditor; un server gol oprește trimiterea.
`none` cu parolă este permis doar către un server de pe aceeași mașină (`localhost` / IP loopback):
o parolă nu traversează rețeaua necriptată (`422 … reason insecure_credentials`). **Email de test →
Trimite testul** trimite un mesaj prin setările salvate și arată `ok` sau eroarea cu motivul (§17).
Fiecare mesaj are cel mult 20 de destinatari; niciun antet nu poate conține caractere de control.

Fără SMTP totul funcționează în continuare: linkurile de invitație se copiază manual, iar acțiunile
de email arată că emailul nu este configurat (`409 smtp_not_configured`).

## 10. Aprobări — regula celor patru ochi

Orice acțiune cu efect în afara spațiului de lucru este o **cerere de aprobare**. Tipurile din pilot:

| Tip | Ce face | Cine decide |
|---|---|---|
| `email.send` | Trimite pe email un răspuns al asistentului sau o rulare de raport | approverii departamentului + administratorii |
| `report.delivery` | Aprobă lista de destinatari ai unui raport; fiecare rulare reușită ulterioară le este trimisă | approverii departamentului + administratorii |
| `report.share_company` | Face o rulare de raport vizibilă în toată compania | administratorii |
| `document.company_publish` | Publică un document al unui departament în toată compania | administratorii |

Reguli impuse de server:

- **Nimeni nu își decide propria cerere.** Singura excepție: un administrator care cere un tip
  decis de administratori — cererea se execută imediat, cu el ca decident, fiindcă un al doilea
  administrator nu ar adăuga control.
- **O cerere pe care nimeni altcineva nu o poate decide este refuzată imediat**
  (`409 no_eligible_approver`), nu lăsată să expire. Interfața verifică dinainte câți decidenți
  există.
- **Decizia este atomică:** două click-uri simultane produc o singură decizie și o singură
  execuție; al doilea primește `409 already_decided`.
- **Totul se reverifică în momentul execuției** (drepturile actuale ale solicitantului, starea
  documentului sau a raportului). Dacă lumea s-a schimbat, aprobarea se termină `failed` cu motivul
  (de ex. `requester_inactive` când contul solicitantului nu mai e activ).
- **Cererile în așteptare expiră după 7 zile**; o execuție blocată peste 10 minute este marcată
  `failed` / `interrupted`. O cerere identică cu una încă deschisă este refuzată
  (`409 already_requested`). Solicitantul își poate retrage cererea cât timp e în așteptare.
- **Livrarea unui raport:** setarea destinatarilor deschide o cerere `report.delivery`
  (`delivery_status` = `pending`); aprobată → `approved`, iar rulările reușite sunt trimise
  destinatarilor aprobați. Respinsă, expirată sau eșuată → `rejected`; retrasă → `none`.
  Schimbarea destinatarilor sau mutarea raportului în alt departament redeschide aprobarea. O
  livrare eșuată nu face rularea eșuată: rularea rămâne `succeeded`, cu `error='delivery_failed'`.

Fiecare pas (cerere, aprobare/respingere, execuție, eșec, email trimis/eșuat) este un rând de audit
care numește persoana.

## 11. SSO opțional prin oauth2-proxy

Conturile rămân în Nerva Workspace (fără auto-creare): SSO doar autentifică o persoană care are
deja un cont **activ**. Fluxul:

1. oauth2-proxy rulează pe `127.0.0.1:4180` și autentifică angajații la furnizorul de identitate
   al companiei (Microsoft Entra ID, Google Workspace, Keycloak — orice OIDC).
2. Caddy (varianta B din `Caddyfile.example`) întreabă oauth2-proxy pentru fiecare cerere a
   spațiului de lucru, șterge orice `X-Forwarded-Email` / `X-Nerva-Proxy-Secret` trimis de
   client, copiază emailul verificat în `X-Forwarded-Email` și adaugă secretul comun.
3. La deschiderea paginii, interfața încearcă o dată, silențios, `POST /api/workspace/login/sso`;
   există și butonul „Continuă cu contul companiei”. Autentificarea cu parolă rămâne disponibilă.

Mediul hub-ului:

```ini
NERVA_WORKSPACE_SSO_HEADER=X-Forwarded-Email
NERVA_WORKSPACE_SSO_SECRET=<valoare lungă aleatoare, aceeași și în mediul Caddy>
```

Hub-ul acceptă o autentificare SSO doar dacă **toate** sunt adevărate: ambele variabile sunt
setate; cererea vine de la o adresă din `JARVIS_TRUSTED_PROXIES` (o listă invalidă dezactivează SSO:
`404 sso_disabled`); antetul de email apare exact o dată și conține un email valid; antetul
`X-Nerva-Proxy-Secret` apare o dată și este egal cu secretul (comparație în timp constant); emailul
aparține unui utilizator activ. Altfel: `404 sso_disabled` (SSO neconfigurat), `401 sso_no_identity`
(proxy-ul nu a garantat o identitate) sau `401 invalid_credentials` (nu există utilizator activ).
Sesiunea reține emailul garantat; dacă o cerere ulterioară vine de la proxy cu **alt** email,
sesiunea este revocată. Pentru Caddy, puneți secretul într-un fișier de mediu al serviciului caddy
(`sudo systemctl edit caddy` → `[Service]` + `EnvironmentFile=/etc/caddy/nerva-sso.env`, fișier cu
mod 0600 care conține `NERVA_WORKSPACE_SSO_SECRET=…`): placeholder-ul `{env.NERVA_WORKSPACE_SSO_SECRET}`
este rezolvat din mediul procesului Caddy la fiecare cerere, deci secretul nu ajunge în configurația
adaptată a Caddy (vizibilă prin API-ul lui de administrare).

## 12. Limitele impuse de cod

| Domeniu | Limită | Ce se întâmplă peste ea |
|---|---|---|
| Încărcare | ≤ `NERVA_WORKSPACE_MAX_UPLOAD_MB` (25 MiB) | `413 file_too_large` (cu `max_bytes`), oprit în timpul transferului |
| Încărcare | 60 de încărcări pe oră per utilizator; **reindexarea consumă din același buget** | `429 rate_limited` cu `retry_after_seconds` |
| Încărcare | cel mult 3 încărcări simultane per utilizator | `429 rate_limited`, `retry_after_seconds=5` |
| Tipuri | `.pdf .docx .xlsx .csv .txt .md`, verificate și după conținut (un fișier redenumit este recunoscut) | `415 unsupported_file_type`, `reason` `extension` sau `content` |
| PDF | ≤ 500 de pagini; PDF-urile care cer parolă la deschidere sunt refuzate | document `failed`: `too_many_pages` / `encrypted_pdf` |
| Text | ≤ 10 000 000 de caractere extrase per document | `failed`: `too_much_text` |
| DOCX/XLSX | arhiva: ≤ 2 000 de fișiere interne și ≤ 100 MiB decomprimat; ≤ 500 000 de elemente XML într-un paragraf, tabel, celulă sau parte mică (≈ un tabel Word de 5 000 de rânduri); adâncime ≤ 256; codurile de format numeric peste 255 de caractere sunt tăiate | `failed`: `too_much_text` / `invalid_file` |
| Extracție | 60 s per document, **inclusiv așteptarea la coadă**; 2 extracții simultane în tot procesul (un fond de fire dedicat) | `failed`: `timeout` |
| Fără text | un PDF scanat fără strat de text | `failed`: `no_text` (fișierul rămâne; se poate reindexa) |
| Asistent | ≤ 8 000 de caractere per întrebare; 30 de întrebări pe minut per utilizator (numărate din auditul append-only — ștergerea conversațiilor nu resetează contorul) | `422 invalid_request` / `429 rate_limited` |
| Asistent | o singură întrebare în lucru per conversație | `409 conversation_busy` |
| Model | `NERVA_WORKSPACE_MAX_CONCURRENT_LLM` (2) apeluri simultane, comune chatului și rapoartelor; așteptare ≤ 30 s pentru un loc | `503 model_busy`, `retry_after_seconds=10` |
| Model | răspuns de chat ≤ 180 s; rulare de raport ≤ 300 s; testul din consolă ≤ 60 s | `504 model_timeout` |
| Rapoarte | 10 rulări manuale pe oră per utilizator (din audit); o singură rulare în coadă/în lucru per raport; 2 rulări simultane în tot procesul | `429 rate_limited` / `409 run_in_progress` |
| Rapoarte | o rulare `running` > 15 min sau `queued` > 30 min | `failed` / `interrupted` |
| Rapoarte | ≤ 50 de documente alese; instrucțiuni ≤ 4 000 de caractere; email ≤ 20 de destinatari | `422 invalid_request` |
| Aprobări | expiră după 7 zile; execuție blocată > 10 min | `expired` / `failed` (`interrupted`) |
| Sesiuni | inactivitate 12 h (1–168), durată maximă 7 zile (1–90); activitatea se înregistrează cel mult o dată pe minut | reautentificare |
| Invitații | link de 72 h, o singură folosire; un link nou îl anulează pe cel vechi | `404 invite_invalid` |
| Autentificare | 5 eșecuri consecutive pentru un email în 15 min, sau 20 de eșecuri de la o adresă în 15 min | `429 too_many_attempts` cu `retry_after_seconds` |
| Configurare / invitații | 10 coduri de configurare greșite / oră / adresă și 50 / oră în total; 30 de încercări cu linkuri de invitație sau resetare (deschidere ori acceptare, reușite sau nu) / oră / adresă | `429 too_many_attempts` |
| Audit | export CSV ≤ 50 000 de rânduri (cele mai noi); o pagină ≤ 200 | — |

Limita de cereri pe IP a hub-ului (`JARVIS_RATE_LIMIT`) nu se aplică la `/workspace*` și
`/api/workspace/*`: spațiul de lucru are limitele proprii de mai sus, pe utilizator.

Curățenia planificatorului (la fiecare 30 s): mesajele asistentului rămase `pending` > 10 min devin
`error` / `interrupted`; se șterg încercările de autentificare mai vechi de 24 h, invitațiile expirate
de peste 7 zile, sesiunile revocate, expirate sau inactive de peste 7 zile și notificările citite de
peste 90 de zile.

## 13. Postura de securitate

- **Parole:** scrypt (n=2¹⁵, r=8, p=1, sare de 16 octeți), verificare în timp constant; un email
  necunoscut este verificat contra unui hash fix, ca timpul să nu dezvăluie dacă există contul.
  Orice eșec răspunde același `401 invalid_credentials`.
- **Sesiuni:** token aleator de 32 de octeți în cookie-ul `nerva_ws_session` (`HttpOnly`,
  `SameSite=Lax`, `Path=/api/workspace`, `Secure` cu `NERVA_WORKSPACE_COOKIE_SECURE=1`); baza de date
  păstrează doar SHA-256 al tokenului. Fiecare autentificare creează o sesiune nouă.
- **CSRF:** fiecare cerere care modifică ceva trimite tokenul sesiunii în `X-CSRF-Token`; în plus,
  o cerere marcată de browser ca venind de pe alt site este refuzată (`403 csrf_failed`), iar rutele
  publice cer `Content-Type: application/json`.
- **Izolarea departamentelor** se aplică în fiecare interogare SQL, pe server, inclusiv în
  căutarea full-text și la citări.
- **Antete:** răspunsurile JSON au `Cache-Control: no-store`; pagina aplicației are un CSP strict
  (`default-src 'self'`, scripturi doar cu hash, `frame-ancestors 'none'`); descărcările și exportul
  HTML au `Content-Disposition: attachment`, `nosniff` și un CSP cu `sandbox`. Exportul CSV al
  auditului neutralizează celulele care încep cu `= + - @`.
- **Auditul este un lanț HMAC-SHA256:** fiecare rând include hash-ul celui anterior, deci editarea,
  ștergerea sau reordonarea unui rând rupe verificarea (Administrare → Audit → **Verifică lanțul**).
  Cheia este `JARVIS_AUDIT_KEY`, altfel fișierul `$JARVIS_KEY_DIR/workspace_audit.key` (implicit
  `~/.config/jarvis/`), **în afara directorului de date**, ca o copie de siguranță sau un director
  de date scurs să nu conțină cheia. **Faceți-i backup separat:** fără ea, lanțul existent nu mai
  poate fi verificat, iar verificarea raportează `key_mismatch`. Limita cunoscută: lipsa celor mai
  noi rânduri (trunchierea la coadă) nu este detectabilă fără o ancoră externă. Detaliile de audit
  nu conțin parole, tokenuri, prompturi, răspunsuri sau text din documente.
- **Secrete:** parola SMTP stă în `<JARVIS_HOME>/business/secrets.enc`. **`JARVIS_SECRET_KEY` și
  `JARVIS_BACKUP_KEY` sunt obligatorii pe un pilot:** fără `JARVIS_SECRET_KEY`, cheia secretelor este
  generată în `secrets.enc.key`, chiar lângă ele, în directorul de date; fără `JARVIS_BACKUP_KEY`,
  copiile de siguranță nocturne nu sunt criptate — deci o copie conține și secretele, și cheia lor.
- **Datele companiei au directorul lor: `<JARVIS_HOME>/business/`** (baza `workspace.db`,
  originalele `files/`, `secrets.enc`, codul de configurare). Nu îl folosește niciun alt modul al
  hub-ului — în special **nu** `<JARVIS_HOME>/workspace/`, care este rădăcina implicită a
  instrumentelor de fișiere (`JARVIS_FILE_ROOTS`), a terminalului local
  (`JARVIS_TERMINAL_LOCAL_ROOTS`) și a rezultatelor mari ale uneltelor (`workspace/tool_results/`)
  ale asistentului personal al proprietarului.
- **„Uită-mă” al hub-ului nu atinge spațiul de lucru:** ștergerea datelor personale ale
  proprietarului hub-ului păstrează directorul `business` (datele companiei nu sunt datele lui) și
  șterge, ca înainte, directorul `workspace` al proprietarului, cu rezultatele uneltelor lui.
- **Instrumentele de fișiere și terminalul hub-ului.** Pe serverul pilot lăsați
  `JARVIS_FILE_TOOLS` și `JARVIS_TERMINAL_LOCAL_HOST` oprite (implicit) — spațiul de lucru nu are
  nevoie de ele. Cu rădăcinile implicite nu ajung la datele companiei. Dacă setați explicit
  `JARVIS_FILE_ROOTS` / `JARVIS_TERMINAL_LOCAL_ROOTS`, **nu** le îndreptați spre directorul de date
  (`<JARVIS_HOME>`) sau spre `<JARVIS_HOME>/business`: asistentul personal ar putea citi atunci baza
  de date și documentele companiei.
- **Ce rămâne în responsabilitatea operatorului:** firewall (doar 80/443 publice), actualizările
  sistemului de operare, accesul SSH, copiile off-site (§14), cheile (§4).

## 14. Backup și restaurare

**Ce se salvează.** Hub-ul face o copie în fiecare noapte la 03:20 și păstrează ultimele 7, în
`<JARVIS_HOME>/backups/`. Copia cuprinde tot directorul de date — inclusiv `business/workspace.db`
(prin API-ul de backup SQLite, consistent cu serverul pornit), originalele documentelor
`business/files/<id>.bin` și `business/secrets.enc`. Cu `JARVIS_BACKUP_KEY` arhiva este criptată
(`.tar.gz.enc`).

**Ce NU se salvează și trebuie păstrat separat, off-site:** `/etc/jarvis-hub/jarvis.env` (toate
cheile) și `/var/lib/jarvis-keys/` (fișierul cheii de audit când `JARVIS_AUDIT_KEY` nu e setată și
materialul cheii de backup când `JARVIS_BACKUP_KEY` este o frază, nu o cheie Fernet). Fără ele, o
arhivă criptată nu poate fi deschisă, iar auditul nu poate fi verificat.

**Copiați arhivele în afara serverului** — ele stau pe același disc ca datele:

```bash
sudo rsync -a /var/lib/jarvis-hub/backups/ backup@nas.firma.ro:/backups/nerva/
```

Comenzi manuale:

```bash
nerva-run -m agents.core.backup create --encrypt   # o copie acum
nerva-run -m agents.core.backup list               # cele existente, cele mai noi primele
nerva-run -m agents.core.backup verify <nume>      # restaurare de probă + PRAGMA integrity_check
```

**Restaurare** (cu serviciul oprit, într-un director nou, apoi schimbarea directoarelor — nu peste
directorul în uz, unde fișierele `-wal`/`-shm` rămase ar putea strica baza restaurată):

```bash
sudo systemctl stop jarvis-hub
# o arhivă adusă din afară se pune întâi în /var/lib/jarvis-hub/backups/
sudo install -d -o jarvis -g jarvis -m 0700 /var/lib/jarvis-hub.restored
nerva-run -m agents.core.backup restore <nume> /var/lib/jarvis-hub.restored   # verificați "ok": true
sudo mv /var/lib/jarvis-hub /var/lib/jarvis-hub.old
sudo mv /var/lib/jarvis-hub.restored /var/lib/jarvis-hub
sudo systemctl start jarvis-hub
```

Apoi, în Administrare → Audit, **Verifică lanțul** trebuie să răspundă `ok`. Un `key_mismatch`
înseamnă că serverul nu folosește aceeași cheie de audit ca înainte: restaurați
`JARVIS_AUDIT_KEY` / `/var/lib/jarvis-keys/`.

## 15. Upgrade

```bash
nerva-run -m agents.core.backup create --encrypt          # 1. o copie înainte
sudo -u jarvis git -C /opt/jarvis-hub pull --ff-only      # 2. codul nou (include interfața compilată)
sudo -u jarvis bash -c 'cd /opt/jarvis-hub && ./install.sh --no-start'   # 3. doar dependențele schimbate + testul de pornire
sudo systemctl restart jarvis-hub                         # 4. repornire (oprire grațioasă)
```

Schema bazei de date a spațiului de lucru migrează automat la prima conectare (`PRAGMA
user_version`), doar înainte. O repornire întrerupe ce era în lucru: rulările de raport active
devin `failed` / `interrupted`, iar un răspuns în flux al asistentului se termină cu eroare —
faceți upgrade-ul în afara programului. **Revenire:** restaurați copia de dinainte (§14) și
reveniți la versiunea anterioară a codului; un cod mai vechi decât baza de date doar avertizează în
jurnal („workspace database is at schema N, newer than this code”), deci nu rulați un cod vechi pe
o bază nouă.

## 16. Recuperare din linia de comandă

Toate rulează cu `nerva-run` (§2), deci cu același mediu ca serviciul. Refuză cu codul de ieșire 2
cât timp `NERVA_WORKSPACE` este oprit. Linkurile și promovările sunt auditate cu
`actor_email='cli'`: cineva cu acces la server a acționat, iar jurnalul o spune.

| Comandă | Când |
|---|---|
| `nerva-run -m agents.core.workspace setup-code` | Afișează codul de configurare inițială (doar înainte de configurare). |
| `nerva-run -m agents.core.workspace reset-link --email ana@firma.ro --base-url https://nerva.firma.ro` | Un link nou: de invitație pentru un cont `invited`, de resetare a parolei pentru unul `active` (72 h, o singură folosire). Linkul se afișează pe ecran; dați-l persoanei pe un canal sigur. Un cont dezactivat trebuie întâi reactivat sau promovat. |
| `nerva-run -m agents.core.workspace promote --email ana@firma.ro` | Face contul administrator (și îl reactivează dacă era dezactivat; fără parolă rămâne `invited` — emiteți apoi `reset-link`). Îi închide sesiunile. Pentru situația în care niciun administrator nu se mai poate autentifica. |

`--base-url` este adresa pe care o deschid utilizatorii (`https://…`, fără query sau fragment).

## 17. Depanare

**Modelul (`model_unavailable` — 503, cu `reason`).** Cipul modelului și `GET /api/workspace/model`
arată același motiv.

| `reason` | Cauza și remediul |
|---|---|
| `hub_not_ready` | Hub-ul încă pornește (încarcă agenții și routerul). Așteptați; dacă persistă, citiți `journalctl -u jarvis-hub`. |
| `no_local_model` | Politica `local_only` și niciun server local detectat. Porniți Ollama/vLLM, verificați `JARVIS_OLLAMA_URL` / `JARVIS_LM_STUDIO_URL` (`curl http://127.0.0.1:11434/api/tags` sau `…:8000/v1/models`). Hub-ul îl găsește în ≤ 5 minute sau la repornire. |
| `no_model` | Politica `allow_cloud` și nicio rută disponibilă (nici local, nici o cheie cloud). |
| `model_not_approved` | Routerul a ales un model care nu e în lista de modele aprobate a hub-ului pentru agentul `workspace`. Aprobați modelul în setările hub-ului sau serviți altul. |
| `backend_error` | Verificarea de tratare a datelor nu a putut decide (de ex. depozitul de consimțământ nu poate fi citit) sau backend-ul a eșuat neașteptat. Citiți jurnalul hub-ului (numește doar tipul erorii). |
| `model_error` | Serverul de model a răspuns cu o eroare (ex. modelul nu e încărcat). Verificați serverul de model și jurnalul lui. |
| `thinking_exhausted` | Modelul și-a consumat tot bugetul de tokeni raționând (§3.2). Folosiți un model instruct sau reduceți raționamentul. |
| `empty_answer` | Modelul a returnat un răspuns gol. Verificați modelul și fereastra de context (§3.1). |

Alte erori ale modelului: `409 model_policy_blocked` cu `data_policy_unacknowledged` (server de
model non-loopback neconfirmat, §3.3) sau `provider_may_train` (politica `allow_cloud` și o rută
cloud spre un furnizor care nu e `local`/`no-training`, §8); `503 model_busy` (toate locurile
ocupate 30 s — ridicați `NERVA_WORKSPACE_MAX_CONCURRENT_LLM` doar dacă serverul de model ține mai
multe cereri simultane); `504 model_timeout`; `422 content_blocked` (garda de securitate a hub-ului a blocat
conținutul). Când garda hub-ului rulează în modul REDACT sau BLOCK, răspunsurile sosesc dintr-o
bucată, nu în flux — interfața spune asta.

**Email (`502 smtp_failed`, cu `reason`).**

| `reason` | Cauza |
|---|---|
| `auth_failed` | Utilizator/parolă respinse de server (sau o autentificare non-ASCII salvată înainte). |
| `not_supported` | Serverul nu oferă ce cere configurația (de ex. STARTTLS sau AUTH lipsă). |
| `recipients_refused` | Serverul a refuzat toți destinatarii. |
| `sender_refused` | Serverul a refuzat adresa expeditorului (de obicei nu are voie să trimită în numele ei). |
| `data_refused` | Serverul a refuzat mesajul. |
| `tls_failed` | Negocierea TLS a eșuat (certificat neîncrezut, port greșit pentru `ssl`/`starttls`). Pentru o CA internă: `JARVIS_CA_BUNDLE`. |
| `timeout` | Serverul nu a răspuns în 15 s (per operație). |
| `connection_failed` | Conexiune imposibilă (gazdă, port, firewall). |
| `smtp_error` | Altă eroare SMTP. |
| `insecure_transport` | `none` cu parolă către un server care nu e local — refuzat. |

Alte coduri: `409 smtp_not_configured` (lipsește serverul sau expeditorul), `409
smtp_password_unreadable` (parola nu mai poate fi decriptată, de obicei după schimbarea
`JARVIS_SECRET_KEY` — reintroduceți-o), `422 recipient_not_allowed` (domeniu în afara listei).

**Autentificare și sesiuni.**

| Simptom | Cauza și remediul |
|---|---|
| `429 too_many_attempts` la autentificare | 5 eșecuri pentru acel email (sau 20 de la acea adresă) în 15 min. Blocarea se ridică singură pe măsură ce fereastra avansează (`retry_after_seconds`); un succes resetează contorul emailului. O parolă uitată: `reset-link` (§16). |
| Toți utilizatorii par să vină de la `127.0.0.1` și se blochează unii pe alții | `JARVIS_TRUSTED_PROXIES` lipsește: hub-ul nu crede antetele Caddy. Setați-l la `127.0.0.1` și reporniți. |
| Linkurile de invitație încep cu `http://` | La fel: `X-Forwarded-Proto` nu e crezut fără `JARVIS_TRUSTED_PROXIES`. |
| `400 host not allowed` | Numele nu e în `JARVIS_ALLOWED_HOSTS`. |
| `403 csrf_failed` | Pagina e servită de pe alt nume decât API-ul, sau o extensie/proxy modifică `Origin`. Folosiți un singur nume pentru tot. |
| Cookie-ul nu „ține” (autentificare în buclă) | `NERVA_WORKSPACE_COOKIE_SECURE=1` pe HTTP simplu: browserul refuză un cookie `Secure`. Accesați prin HTTPS. |
| `401 auth_required` după o pauză | Sesiunea a expirat (12 h inactivitate / 7 zile). |
| `404 workspace_disabled` | `NERVA_WORKSPACE` nu e activ în mediul serviciului. |
| `404 invite_invalid` | Link folosit, expirat (72 h) sau înlocuit de unul mai nou. Emiteți altul. |
| Niciun administrator nu se mai poate autentifica | `promote` + `reset-link` (§16). |
| Verificarea auditului: `key_mismatch` | Serverul nu are cheia de audit cu care au fost scrise rândurile (altă `JARVIS_AUDIT_KEY`, alt `JARVIS_KEY_DIR`, sau o comandă CLI rulată fără același mediu). Restaurați cheia. |

**Documente.** Un document `failed` are un cod stabil: `invalid_file` (fișier corupt sau structură
nevalidă), `encrypted_pdf`, `too_many_pages`, `no_text` (PDF scanat — faceți OCR înainte),
`timeout`, `too_much_text`. `404 file_missing` la descărcare sau reindexare: originalul lipsește de
pe disc (restaurați din backup). `409 document_busy`: documentul încă se procesează. `507
storage_failed`: discul nu poate fi scris (spațiu, permisiuni).

## 18. Limitele cunoscute ale pilotului

- **Fără OCR:** un PDF scanat fără strat de text eșuează cu `no_text`; treceți-l printr-un OCR
  înainte de încărcare.
- **Fără OIDC/SAML nativ:** SSO doar prin proxy (§11). Fără auto-provizionare a conturilor.
- **Fără conectori ERP/CRM/contabilitate/e-Factura:** cunoașterea vine doar din documentele
  încărcate. Conectorii (MCP-first) sunt felia următoare.
- **Căutare lexicală:** indexul este full-text (SQLite FTS5/BM25, cu diacriticele normalizate), nu
  semantic; întrebările formulate cu alte cuvinte decât documentul găsesc mai puțin.
- **Extracție:** din DOCX nu se extrag antetele, subsolurile, notele de subsol și comentariile; din
  XLSX se citesc valorile calculate salvate în fișier, o celulă unită apare o singură dată, foile
  ascunse sunt incluse.
- **Extracția nu poate fi oprită forțat:** o pagină PDF patologică poate ține un fir de extracție
  ocupat peste 60 s (documentul e oricum marcat `timeout`); o extracție într-un subproces care poate
  fi oprit este o lucrare ulterioară.
- **Un singur proces:** o instanță a hub-ului per director de date; SQLite cu WAL. Potrivit pentru
  un pilot (sute de utilizatori numiți), nu pentru mii.
- **Interfața** este un singur pachet JavaScript (~160 kB comprimat), fără încărcare pe bucăți;
  câmpurile native de dată/oră urmează limba browserului, nu a aplicației.
- **Lista de documente** nu are paginare; trimiterea unui email nu are o limită totală de timp (doar
  15 s per operație SMTP).

## 19. Lista de verificare înainte de primul utilizator

- [ ] `JARVIS_SECRET_KEY`, `JARVIS_BACKUP_KEY` și cheia de audit sunt setate, iar
      `/etc/jarvis-hub/jarvis.env` și `/var/lib/jarvis-keys/` sunt copiate off-site.
- [ ] `curl -s http://127.0.0.1:8080/readyz` răspunde 200; cipul modelului arată **Local**;
      **Testează modelul** reușește.
- [ ] `https://nerva.firma.ro/v2` răspunde 404, `https://nerva.firma.ro/workspace/` se deschide cu
      certificat valid și HSTS.
- [ ] Un link de invitație începe cu `https://nerva.firma.ro/workspace/invite#t=`.
- [ ] Emailul de test ajunge (dacă folosiți SMTP), iar lista de domenii permise e completată.
- [ ] Fiecare departament are cel puțin un approver în afară de administratori, altfel cererile de
      email ale membrilor merg doar la administratori.
- [ ] `nerva-run -m agents.core.backup verify <ultima copie>` răspunde `"ok": true`, iar copiile
      ajung pe alt sistem.
- [ ] Administrare → Audit → **Verifică lanțul** răspunde `ok`.
- [ ] `JARVIS_FILE_TOOLS` și `JARVIS_TERMINAL_LOCAL_HOST` sunt oprite, sau rădăcinile lor explicite
      nu cuprind `<JARVIS_HOME>` ori `<JARVIS_HOME>/business` (§13).
