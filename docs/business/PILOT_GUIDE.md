# Nerva Workspace — ghidul pilotului

> **Pentru cine:** cine instalează și operează un pilot Nerva Workspace la o companie, fără să
> cunoască deja codul. Pornește de la un server gol și se termină cu un spațiu de lucru în care
> angajații se autentifică, întreabă asistentul pe baza documentelor firmei, rulează rapoarte și
> aprobă acțiuni.
> **Stare:** pilot, 2026-10-17 (actualizat 2026-10-19). Contractul tehnic este
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
| Sistem | Linux cu systemd. Exemplele folosesc **Ubuntu 24.04 LTS**, al cărui Python 3.12 este versiunea pe care rulează testele proiectului. Debian 12 are Python 3.11, pe care instalatorul îl refuză, iar Debian 13 are Python 3.13, acceptat de instalator dar netestat: pe Debian instalați întâi un Python 3.12 separat (§2, *Debian*). Windows și macOS rulează hub-ul, dar acest ghid acoperă doar Linux. |
| Python | 3.12 sau mai nou (`python3 --version`). Instalatorul refuză versiunile mai vechi cu un motiv explicit (pe Debian 12: `python_too_old:3.11<3.12`). |
| Disc | Codul + mediul Python: câțiva GB. Datele: documentele încărcate (originalele se păstrează) plus 7 copii de siguranță zilnice. Modelul AI: de la ~2 GB (model mic, CPU) la zeci de GB. |
| Memorie | În primul rând modelul (§3). Hub-ul în sine este un proces Python, dar fiecare încărcare în curs este ținută întreagă în memorie — până la de două ori mărimea fișierului cât timp e primită —, cel mult 3 simultan per utilizator și fără o limită comună pe proces: 10 persoane care încarcă simultan câte 3 fișiere de 25 MiB înseamnă până la ~1,5 GiB în plus. |
| Rețea | Un nume DNS dedicat (ex. `nerva.firma.ro`) care indică serverul; portul 443 (și 80 pentru Let's Encrypt) deschis pentru utilizatori; ieșire HTTPS pentru instalare. |
| Email | Opțional: un cont SMTP al companiei pentru invitații, rapoarte și emailuri aprobate (§9). |
| Node.js | **Nu** este necesar: interfața este deja compilată în `agents/web/workspace/`. |

## 2. Instalarea hub-ului

Exemplele presupun codul în `/opt/jarvis-hub`, datele în `/var/lib/jarvis-hub`, cheile în
`/var/lib/jarvis-keys` și un utilizator de sistem `jarvis`. Le puteți schimba, dar atunci
schimbați-le peste tot (inclusiv în unitatea systemd).

```bash
# 1. utilizator de serviciu fără login; home-ul lui (/var/lib/jarvis) NU este directorul de date
sudo useradd --system --home-dir /var/lib/jarvis --create-home --shell /usr/sbin/nologin jarvis
sudo install -d -o jarvis -g jarvis -m 0700 /var/lib/jarvis-hub /var/lib/jarvis-keys

# 2. codul, la versiunea numită a pilotului (sau din pachetul git primit de la Digitaholic, mai jos)
sudo git clone --branch <eticheta-pilotului> https://github.com/andrei649/jarvis-hub.git /opt/jarvis-hub
sudo chown -R jarvis:jarvis /opt/jarvis-hub

# 3. mediul Python cu dependențele fixate prin hash + testul de pornire (fără a porni serverul)
sudo -u jarvis bash -c 'cd /opt/jarvis-hub && ./install.sh --no-start'
```

**Versiunea.** `<eticheta-pilotului>` este eticheta de versiune (git tag) pe care v-o comunică
Digitaholic. Nu instalați ramura implicită: un pilot rulează o versiune numită, nu ultimul commit, iar
upgrade-ul (§15) trece de la o etichetă la alta. Eticheta pilotului o creează proprietarul
proiectului, după ce aprobă lucrarea pilotului; la data acestui ghid ea **nu există încă**, iar
ghidul nu îi dă un nume — folosiți exact numele comunicat, nu unul presupus. Singura etichetă
publicată (`v1.0.0`) și ramura implicită sunt mai vechi decât spațiul de lucru: până apare eticheta
pilotului, folosiți checkout-ul primit de la Digitaholic. Acesta trebuie să fie un depozit git complet, cu
directorul `.git` — de exemplu un pachet `git bundle`, clonat cu `sudo git clone --branch
<eticheta-pilotului> /cale/nerva-pilot.bundle /opt/jarvis-hub` —, nu o simplă copie a fișierelor:
upgrade-ul și revenirea (§15) folosesc `git describe`, `git fetch --tags` și `git checkout`.

**Home-ul separat.** `sudo -u jarvis` setează `HOME` la home-ul utilizatorului, iar instalarea scrie
acolo cache-ul pip (~45 MB pentru `requirements-beta.lock`) și `~/.config/jarvis/`. Copia de
siguranță nocturnă (§14) arhivează tot directorul de date, deci un home egal cu
`/var/lib/jarvis-hub` ar pune aceste fișiere în fiecare arhivă.

`install.sh` creează `.venv`, instalează `requirements-beta.lock` cu `--require-hashes` și rulează
un test real de pornire. Un eșec se termină cu un motiv numit (tabelul din
[`../INSTALL.md`](../INSTALL.md) → *Troubleshooting by reason*). Ultimele rânduri ale instalării
(„Start it: ./start.sh” / „Then open: http://127.0.0.1:8080/v2”) sunt pentru un hub personal:
**ignorați-le** — serviciul pornește prin systemd (mai jos și §4), iar angajații folosesc
`/workspace/`. Testul de pornire își lasă datele de probă în `/opt/jarvis-hub/memory_logs/`;
serviciul nu le folosește (are `JARVIS_HOME=/var/lib/jarvis-hub`).

**Ubuntu cu mai multe versiuni de Python.** `install.sh` caută întâi `python3.13`, apoi
`python3.12`: dacă pe server există și un `python3.13` (de exemplu din PPA-ul deadsnakes), îl alege
pe acela — acceptat, dar netestat. Pentru versiunea testată rulați pasul 3 cu interpretorul numit:
`sudo -u jarvis bash -c 'cd /opt/jarvis-hub && python3.12 scripts/bootstrap.py'` (la upgrade, §15,
la fel).

**Debian (12 sau 13).** Instalați un Python 3.12 separat, în afara `/home` și `/root` — unitatea
systemd are `ProtectHome=yes`, deci un interpretor de acolo nu ar fi accesibil serviciului — și
rulați pasul 3 direct cu el. `uv` (de la Astral) aduce doar interpretorul:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
sudo env UV_PYTHON_INSTALL_DIR=/opt/python UV_PYTHON_BIN_DIR=/usr/local/bin uv python install 3.12
/usr/local/bin/python3.12 --version
# pasul 3, în locul lui ./install.sh --no-start:
sudo -u jarvis bash -c 'cd /opt/jarvis-hub && /usr/local/bin/python3.12 scripts/bootstrap.py'
```

`scripts/bootstrap.py` este exact ce rulează `install.sh` (mediul, dependențele, testul de pornire),
fără să pornească serverul; apelat direct, folosește interpretorul cu care îl porniți (`install.sh`
l-ar alege pe primul găsit, iar pe Debian 13 acela este `python3.13`). `.venv` rămâne legat de
interpretorul din `/opt/python`: nu îl ștergeți. La upgrade (§15) folosiți aceeași comandă la pasul 3.

**Serviciul systemd.** Folosiți unitatea din repo; ea pornește `serve.py` pe `127.0.0.1:8080`,
cu `JARVIS_HOME=/var/lib/jarvis-hub` și protecțiile systemd (`ProtectSystem=strict`,
`ProtectHome=yes`):

```bash
sudo cp /opt/jarvis-hub/deploy/systemd/jarvis-hub.service /etc/systemd/system/
sudo install -d -m 0700 /etc/jarvis-hub
sudo install -m 0600 /dev/null /etc/jarvis-hub/jarvis.env      # se completează în §4

# directorul de chei trebuie să fie inscriptibil pentru serviciu (ProtectSystem=strict), iar tot
# ce scrie serviciul (baza de date, copiile de siguranță) se creează doar pentru jarvis (UMask)
sudo install -d /etc/systemd/system/jarvis-hub.service.d
printf '[Service]\nReadWritePaths=/var/lib/jarvis-keys\nUMask=0077\n' \
  | sudo tee /etc/systemd/system/jarvis-hub.service.d/pilot.conf
sudo systemctl daemon-reload
```

`UMask=0077`: fără el, serviciul ar crea fișierele hub-ului cu umask-ul implicit `0022` — de
exemplu `settings.db` cu mod `0644` și `backups/` cu `0755` —, iar singura protecție ar rămâne
directorul de date, `0700` (pasul 1); o copie care păstrează modurile (`rsync -a`, §14) le-ar
duce așa mai departe. Cu el, fișierele noi sunt `0600`, iar directoarele `0700`. Datele companiei
(`business/`) sunt private oricum: spațiul de lucru își creează baza `workspace.db` cu `0600`,
indiferent de umask (`-wal`/`-shm` primesc același mod), iar la prima conectare a fiecărui proces
— la pornirea hub-ului — scoate accesul grupului și al celorlalți de pe tot ce găsește sub
`business/` (§13). Unitatea din repo nu setează `UMask`, de aceea fișierul `pilot.conf` de mai sus
rămâne necesar pentru restul datelor.

Nu porniți încă serviciul: întâi modelul (§3) și configurarea (§4). Detalii despre unitate:
[`../../deploy/systemd/README.md`](../../deploy/systemd/README.md).

**Comanda de operare.** Comenzile de recuperare și de backup trebuie să ruleze cu **exact
același mediu** ca serviciul: același `JARVIS_HOME` (altfel deschid alt director de date), aceeași
cheie de audit (`JARVIS_AUDIT_KEY`, altfel fișierul din același `JARVIS_KEY_DIR`), aceeași
`JARVIS_BACKUP_KEY` și același `NERVA_WORKSPACE`. Comenzile spațiului de lucru (§6, §16) verifică
asta: rulate altfel, refuză cu codul de ieșire 2 și nu schimbă nimic, iar mesajul numește
`nerva-run` (`check` doar raportează). Comenzile de backup nu verifică: cu alt `JARVIS_HOME` ar
salva sau ar căuta arhivele altui director. Cel mai sigur este să le rulați ca o unitate systemd
temporară care citește același fișier de mediu, cu același `UMask`:

```bash
# adăugați în ~/.bashrc al administratorului serverului
nerva-run() {
  sudo systemd-run --quiet --pipe --wait --collect \
    -p User=jarvis -p Group=jarvis -p UMask=0077 \
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

Sau, din linia de comandă pe server — varianta de folosit când `JARVIS_ADMIN_TOKEN` este setat
(recomandat, §4), fiindcă rutele de administrare ale hub-ului cer atunci tokenul; fără niciun token
de admin configurat, hub-ul acceptă doar cereri directe de pe localhost:

```bash
JARVIS_ADMIN_TOKEN=$(sudo sed -n 's/^JARVIS_ADMIN_TOKEN=//p' /etc/jarvis-hub/jarvis.env)
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
/opt/jarvis-hub/.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(32))"                               # tokenul de admin al hub-ului
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
# Cheia lanțului de audit. Dacă lipsește, se generează o dată în $JARVIS_KEY_DIR/workspace_audit.key,
# cât timp jurnalul este gol. Nu o schimbați după primul start (§13).
JARVIS_AUDIT_KEY=<64 de caractere hex>
# Recomandat: fără el, orice proces de pe server care ajunge la 127.0.0.1:8080 este administratorul
# hub-ului (ex. /api/admin/forget, /api/security/data-handling/ack); cu el, acele rute cer antetul
# X-Admin-Token. Spațiul de lucru nu îl folosește.
JARVIS_ADMIN_TOKEN=<token aleator>
# În spatele Caddy pe aceeași mașină (§5):
JARVIS_TRUSTED_PROXIES=127.0.0.1
JARVIS_ALLOWED_HOSTS=nerva.firma.ro
# JARVIS_CORS_ORIGINS — nu este necesar. Chiar setat (pentru altă suprafață a hub-ului), nu se aplică
# la /workspace* și /api/workspace/*: spațiul de lucru nu trimite niciodată antete CORS.

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

Valorile numerice peste maxim sunt aduse la maxim; zero, valorile negative și cele nenumerice
(inclusiv cu zecimale, ex. `2.5`) revin la valoarea implicită — nu la minim. Niciuna nu este
refuzată și niciuna nu produce un avertisment în jurnal. Variabilele se citesc
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
curl -s -o /dev/null -D - https://nerva.firma.ro/workspace/ | grep -iE '^HTTP|^strict-transport-security'
#   HTTP/2 200
#   strict-transport-security: max-age=31536000
curl -s  https://nerva.firma.ro/api/workspace/session          # {"enabled":true,…}
curl -s -o /dev/null -w '%{http_code}\n' https://nerva.firma.ro/v2   # 404: Command Center-ul nu e public
```

Folosiți `GET`, nu `HEAD` (`curl -I`): hub-ul răspunde la `HEAD` cu `405` (`allow: GET`), inclusiv pe
`/workspace/`, `/api/workspace/session` și `/healthz`. Un monitor de disponibilitate setat implicit pe
`HEAD` ar raporta pilotul căzut; configurați-l cu `GET https://nerva.firma.ro/api/workspace/session`
(200 și JSON, fără autentificare, prin Caddy).

## 6. Primul start: codul de configurare și administratorul

Configurarea inițială creează organizația, departamentul „General” și primul administrator. Este
protejată de un cod pe care îl poate citi doar cine are acces la server.

```bash
nerva-run -m agents.core.workspace setup-code
```

Comanda afișează codul (din `NERVA_WORKSPACE_SETUP_CODE`, sau îl generează în
`<JARVIS_HOME>/business/setup-code.txt`). Codul nu apare niciodată în jurnale — jurnalul numește
doar fișierul. Comanda refuză cu codul de ieșire 2 dacă `NERVA_WORKSPACE` este oprit sau dacă nu
rulează cu mediul serviciului (§16), și cu 1 după ce configurarea a fost făcută.

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

Administrare → Organizație arată starea modelului și butonul **Testează modelul** (un apel scurt,
cu limită de 60 s, auditat ca `model.tested`). Starea are patru valori, aceleași în cipul din bara
de sus (vizibil tuturor utilizatorilor) și în Administrare → Organizație:

| Cip | Când |
|---|---|
| **Local** | Ruta este un server de model pe loopback (§3): datele nu părăsesc mașina. |
| **Local, neverificat** | Un server de model din rețeaua locală, confirmat de proprietarul hub-ului (§3.3): hub-ul nu poate dovedi unde ajung datele, iar furnizorul nu își declară politica. |
| **Cloud** | O rută cloud, permisă de politica `allow_cloud`. |
| **Indisponibil** | Niciun model utilizabil acum; fereastra cipului arată motivul (§17). |

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
setate; cererea vine de la o adresă din `JARVIS_TRUSTED_PROXIES` (o listă invalidă oprește pornirea
hub-ului, cu motivul în jurnal — §17); antetul de email apare exact o dată și conține un email valid; antetul
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
| Autentificare | 5 eșecuri consecutive pentru un email în 15 min, sau 20 de eșecuri de la o adresă în 15 min. Un text care nu este o adresă de email (de exemplu o parolă scrisă în câmpul de email) nu se păstrează: încercarea se înregistrează fără identificator, cu motivul `invalid_identifier`, și contează doar la limita adresei de la care vine | `429 too_many_attempts` cu `retry_after_seconds` |
| Configurare / invitații | 10 coduri de configurare greșite / oră / adresă și 50 / oră în total; 30 de încercări cu linkuri de invitație sau resetare (deschidere ori acceptare, reușite sau nu) / oră / adresă | `429 too_many_attempts` |
| Audit | export CSV ≤ 50 000 de rânduri (cele mai noi); o pagină ≤ 200 | — |

Limita de cereri pe IP a hub-ului (`JARVIS_RATE_LIMIT`) nu se aplică la `/workspace*` și
`/api/workspace/*`: spațiul de lucru are limitele proprii de mai sus, pe utilizator.

Curățenia planificatorului (la fiecare 30 s, cât timp `NERVA_WORKSPACE_SCHEDULER` este pornit):
mesajele asistentului rămase `pending` > 10 min devin `error` / `interrupted`; documentele rămase
`processing` de peste 10 minute, sau începute înainte de pornirea hub-ului (o extracție oprită de
o repornire), devin `failed` / `interrupted` — **Reindexează** le reia imediat; se șterg
încercările de autentificare mai vechi de 24 h, invitațiile expirate de peste 7 zile, sesiunile
revocate, expirate sau inactive de peste 7 zile și notificările citite de peste 90 de zile.

Cât timp procesul nu are cheia cu care a fost scris jurnalul de audit (§13), planificatorul
**își suspendă pașii care scriu în audit**: nu pornește rapoartele programate, nu expiră
aprobările și nu marchează `failed` rulările sau aprobările blocate — nu schimbă și nu scrie nimic
pentru ele. Curățenia de mai sus (mesaje, documente, ștergeri) continuă. Jurnalul hub-ului o spune
o singură dată, la începutul pauzei (§17); primul ciclu după ce cheia serviciului este pusă la loc
recuperează: un raport programat ratat rulează o dată, aprobările trecute de termen expiră.

## 13. Postura de securitate

- **Parole:** scrypt (n=2¹⁵, r=8, p=1, sare de 16 octeți), verificare în timp constant; un email
  necunoscut este verificat contra unui hash fix, ca timpul să nu dezvăluie dacă există contul.
  Orice eșec răspunde același `401 invalid_credentials`.
- **Sesiuni:** token aleator de 32 de octeți în cookie-ul `nerva_ws_session` (`HttpOnly`,
  `SameSite=Lax`, `Path=/api/workspace`, `Secure` cu `NERVA_WORKSPACE_COOKIE_SECURE=1`); baza de date
  păstrează doar SHA-256 al tokenului. Fiecare autentificare creează o sesiune nouă.
- **CSRF:** fiecare cerere care modifică ceva trimite în `X-CSRF-Token` tokenul CSRF al sesiunii —
  o valoare aleatoare separată de cookie, primită în răspunsul autentificării (tokenul sesiunii
  rămâne doar în cookie-ul `HttpOnly`, inaccesibil scripturilor); în plus,
  o cerere marcată de browser ca venind de pe alt site este refuzată (`403 csrf_failed`), iar rutele
  publice cer `Content-Type: application/json`.
- **Izolarea departamentelor** se aplică în fiecare interogare SQL, pe server, inclusiv în
  căutarea full-text și la citări.
- **Antete:** răspunsurile JSON au `Cache-Control: no-store`; pagina aplicației are un CSP strict
  (`default-src 'self'`, scripturi doar cu hash, `frame-ancestors 'none'`); descărcările și exportul
  HTML au `Content-Disposition: attachment`, `nosniff` și un CSP cu `sandbox`. Exportul CSV al
  auditului neutralizează (prefixează cu `'`) celulele care încep cu `= + - @`, tab sau CR.
- **Auditul este un lanț HMAC-SHA256:** fiecare rând include hash-ul celui anterior, deci editarea,
  ștergerea sau reordonarea unui rând rupe verificarea (Administrare → Audit → **Verifică lanțul**).
  Cheia este `JARVIS_AUDIT_KEY`, altfel fișierul `$JARVIS_KEY_DIR/workspace_audit.key`, **în afara
  directorului de date**, ca o copie de siguranță sau un director de date scurs să nu conțină
  cheia. Fără `JARVIS_KEY_DIR`, directorul este `~/.config/jarvis/` al utilizatorului de serviciu —
  de aceea, în acest ghid, `JARVIS_KEY_DIR=/var/lib/jarvis-keys` este obligatoriu, iar home-ul
  utilizatorului `jarvis` (`/var/lib/jarvis`) nu este directorul de date (§2). **Faceți-i backup
  separat.** Fișierul cheii se generează o singură dată, cât timp jurnalul este gol. Odată ce
  jurnalul are rânduri, hub-ul scrie doar cu cheia cu care a fost semnat cel mai nou rând: fără
  nicio cheie (nici `JARVIS_AUDIT_KEY`, nici fișierul) răspunde `503 audit_key_missing`, cu altă
  cheie `503 audit_key_mismatch`, la orice acțiune care scrie în jurnal — deci nimeni nu se mai
  poate autentifica și nu se salvează nicio modificare (citirile funcționează în continuare) până
  când cheia serviciului este pusă la loc, iar planificatorul își suspendă rapoartele programate
  și expirările (§12). Hub-ul nu generează și nu adoptă niciodată singur o
  cheie nouă (ar rupe lanțul definitiv); o spune în jurnal încă de la pornire, iar
  `nerva-run -m agents.core.workspace check` arată starea cheii fără să schimbe nimic (§16, §17).
  Nu schimbați `JARVIS_AUDIT_KEY` pe o instalare în uz. Doar pentru o cheie **pierdută cu
  adevărat** există `audit-rekey` (§16), auditat: rândurile semnate cu cheia veche nu mai pot fi
  verificate niciodată, dar rămân fixate, deci o modificare ulterioară a lor tot se vede. Limita
  cunoscută: lipsa celor mai noi rânduri (trunchierea la coadă) nu este detectabilă fără o ancoră
  externă. Detaliile de audit nu conțin parole, tokenuri, prompturi, răspunsuri sau text din
  documente.
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
- **Fișierele companiei sunt private pe disc, indiferent de umask:** `workspace.db` se creează cu
  `0600` (iar `-wal`/`-shm` primesc același mod), `files/` cu `0700`, originalele, `secrets.enc`
  și codul de configurare cu `0600`. La prima conectare a fiecărui proces la baza de date — la
  pornirea hub-ului (primul ciclu al planificatorului) sau la prima cerere ori comandă — hub-ul
  parcurge `business/` fără să urmeze legăturile simbolice și scoate drepturile grupului și ale
  celorlalți de pe fiecare fișier și director (de exemplu `0644`/`0755` lăsate de o restaurare sau
  de o copie devin `0600`/`0700`), cu un singur avertisment în jurnal (§17). Dacă `business/` este
  el însuși o legătură simbolică spre un director (datele pe alt disc), hub-ul parcurge directorul
  spre care duce legătura, tot fără să urmeze legăturile din interiorul lui, iar avertismentul
  numește `…/business → <director>`. O legătură `business/` spre un director care conține chiar
  directorul de date (`/`, `<JARVIS_HOME>` sau un director de deasupra lui) nu este parcursă:
  jurnalul spune o dată că modurile nu au fost verificate (§17) — legați `business/` de un director
  doar al lui. Verificarea `check` doar citește și nu schimbă niciun mod. Restul directorului de date (`backups/`, `settings.db` și
  celelalte baze ale hub-ului) urmează umask-ul serviciului — de aceea `UMask=0077` (§2).
- **„Uită-mă” al hub-ului nu atinge spațiul de lucru:** ștergerea datelor personale ale
  proprietarului hub-ului păstrează directorul `business` (datele companiei nu sunt datele lui) și
  șterge, ca înainte, directorul `workspace` al proprietarului, cu rezultatele uneltelor lui.
- **Instrumentele de fișiere și terminalul hub-ului.** Pe serverul pilot lăsați
  `JARVIS_FILE_TOOLS` și `JARVIS_TERMINAL_LOCAL_HOST` oprite (implicit) — spațiul de lucru nu are
  nevoie de ele. Cu rădăcinile implicite nu ajung la datele companiei. O rădăcină setată explicit
  în `JARVIS_FILE_ROOTS` sau `JARVIS_TERMINAL_LOCAL_ROOTS` care **este, conține sau se află în**
  `<JARVIS_HOME>/business` — chiar directorul de date (`<JARVIS_HOME>`), `/`, un home care îl
  conține, `business/files` — este **ignorată** de hub: calea reală este comparată după rezolvarea
  `~`, `..` și a legăturilor simbolice, jurnalul spune o dată per proces care rădăcină a fost
  ignorată (§17), celelalte rămân neschimbate, iar dacă nu rămâne niciuna se folosește rădăcina
  implicită (`<JARVIS_HOME>/workspace`). Ce nu acoperă: cât timp spațiul de lucru este oprit și
  `business/` nu există încă, nu se ignoră nimic (nu există date ale companiei); pentru terminal,
  rădăcinile limitează doar directorul de lucru — o cale absolută în argumentele unei comenzi
  aprobate ține de contractul și de aprobarea terminalului, nu de rădăcini. De aceea recomandarea
  rămâne: nu setați astfel de rădăcini.
- **Ce rămâne în responsabilitatea operatorului:** firewall (doar 80/443 publice, plus SSH),
  actualizările sistemului de operare, accesul SSH, copiile off-site (§14), cheile (§4). Cu `ufw`
  (inclus în Ubuntu; pe Debian `sudo apt install ufw`), permiteți SSH **înainte** de activare, ca
  să nu vă blocați accesul:

  ```bash
  sudo ufw allow OpenSSH
  sudo ufw allow 80,443/tcp
  sudo ufw enable
  sudo ufw status verbose     # permise: doar OpenSSH și 80,443/tcp
  ```

  În configurația din acest ghid, hub-ul, serverul de model și oauth2-proxy ascultă oricum doar pe
  loopback; firewall-ul acoperă tot ce altceva ar asculta pe server.

## 14. Backup și restaurare

**Ce se salvează.** Hub-ul face o copie în fiecare noapte la 03:20 și păstrează ultimele 7, în
`<JARVIS_HOME>/backups/`. Copia cuprinde tot directorul de date — inclusiv `business/workspace.db`
(prin API-ul de backup SQLite, consistent cu serverul pornit), originalele documentelor
`business/files/<id>.bin` și `business/secrets.enc`. Cu `JARVIS_BACKUP_KEY` arhiva este criptată
(`.tar.gz.enc`).

**Ce NU se salvează și trebuie păstrat separat, off-site:** `/etc/jarvis-hub/jarvis.env` (toate
cheile) și `/var/lib/jarvis-keys/` (fișierul cheii de audit când `JARVIS_AUDIT_KEY` nu e setată și
materialul cheii de backup când `JARVIS_BACKUP_KEY` este o frază, nu o cheie Fernet). Fără ele, o
arhivă criptată nu poate fi deschisă (`JARVIS_BACKUP_KEY`); pe o copie restaurată nimeni nu se poate
autentifica (fără cheia de audit, hub-ul răspunde `503 audit_key_missing`, §13); iar parola SMTP nu
mai poate fi citită (`JARVIS_SECRET_KEY`, §4) și trebuie reintrodusă.

**Copiați arhivele în afara serverului, automat** — ele stau pe același disc ca datele. O dată, de
mână (verifică și cheia SSH a root-ului, care trebuie autorizată pe destinație), apoi în fiecare
noapte, după copia de la 03:20:

```bash
sudo rsync -a /var/lib/jarvis-hub/backups/ backup@nas.firma.ro:/backups/nerva/
echo '40 3 * * * root rsync -a /var/lib/jarvis-hub/backups/ backup@nas.firma.ro:/backups/nerva/' \
  | sudo tee /etc/cron.d/nerva-offsite
```

Fără `--delete`, destinația păstrează și copiile pe care hub-ul le-a curățat local; ștergeți-le
acolo după politica de retenție a companiei.

**Verificați săptămânal că rulează.** Copia nocturnă scrie în jurnal un rând la fiecare rulare:

```bash
journalctl -u jarvis-hub --since "8 days ago" | grep 'nightly backup'
#   … INFO  jarvis.orchestrator  nightly backup: [REDACTED:high_entropy_secret].tar.gz.enc (61440 bytes), pruned 1
#   … WARNING  jarvis.orchestrator  nightly backup failed     ← motivul urmează în traceback
nerva-run -m agents.core.backup list               # arhiva cea mai nouă trebuie să fie de azi-noapte
```

Numele arhivei apare mascat (`[REDACTED:high_entropy_secret]`): filtrul de secrete al jurnalului
maschează orice șir lung care pare aleator (§17); `backup list` îl arată întreg. Un rând cu
`.tar.gz` în loc de `.tar.gz.enc` înseamnă că `JARVIS_BACKUP_KEY` lipsește din mediul serviciului.

Comenzi manuale:

```bash
nerva-run -m agents.core.backup create --encrypt   # o copie acum
nerva-run -m agents.core.backup list               # cele existente, cele mai noi primele
nerva-run -m agents.core.backup verify <nume>      # restaurare de probă + PRAGMA integrity_check
```

`<nume>` este **numele fișierului**, așa cum îl arată `list` (de exemplu
`jarvis-backup-20261018T032000_…Z_….tar.gz.enc`), sau calea arhivei — de exemplu exact valoarea
câmpului `"archive"` afișat de `create` (`/var/lib/jarvis-hub/backups/jarvis-backup-….tar.gz.enc`).
Folosiți o cale absolută: `nerva-run` rulează din `/opt/jarvis-hub`, deci o cale relativă se
citește de acolo. Arhiva trebuie să fie chiar în `<JARVIS_HOME>/backups/` (legăturile simbolice și
`..` sunt rezolvate întâi): o copie din alt director, o cale care iese din `backups/`, o
legătură spre un fișier din altă parte sau o legătură din `backups/` spre o altă arhivă, sub alt
nume, sunt refuzate cu `no such backup` (codul 2) — o arhivă adusă
din afară se pune întâi în `backups/` (mai jos). Orice eșec este un singur rând, fără traceback
(§17): codul 1 înseamnă că comanda a rulat și a eșuat, codul 2 că argumentul nu numește o copie.

**Restaurare** (cu serviciul oprit, într-un director nou, apoi schimbarea directoarelor — nu peste
directorul în uz, unde fișierele `-wal`/`-shm` rămase ar putea strica baza restaurată):

```bash
sudo systemctl stop jarvis-hub
# o arhivă adusă din afară (de pe NAS, de pe alt server) se pune întâi în backups/, deținută de jarvis:
#   sudo install -d -o jarvis -g jarvis -m 0700 /var/lib/jarvis-hub/backups
#   sudo install -o jarvis -g jarvis -m 0600 <arhiva> /var/lib/jarvis-hub/backups/
sudo install -d -o jarvis -g jarvis -m 0700 /var/lib/jarvis-hub.restored
nerva-run -m agents.core.backup restore <nume> /var/lib/jarvis-hub.restored   # verificați "ok": true
sudo mv /var/lib/jarvis-hub /var/lib/jarvis-hub.old
sudo mv /var/lib/jarvis-hub.restored /var/lib/jarvis-hub
sudo mv /var/lib/jarvis-hub.old/backups /var/lib/jarvis-hub/   # arhivele nu sunt în arhivă: aduceți-le înapoi
sudo chmod -R go-rwx /var/lib/jarvis-hub                       # cu UMask=0077 (§2) e deja 0700/0600; fără el, restaurarea scrie 0755/0644 (business/ îl face privat și hub-ul la pornire, §13)
nerva-run -m agents.core.workspace check                        # verificarea mediului: ultimul rând trebuie să fie „ready”
sudo systemctl start jarvis-hub
```

Verificarea mediului (`check`) doar citește: baza de date este deschisă numai pentru citire și nu
se creează nicio cheie. Cu datele restaurate, aceeași cheie de audit și același `JARVIS_HOME`, se
termină cu `ready` (codul 0). Altfel rândul greșit spune ce lipsește și se termină cu `NOT ready`
(codul 1) — de obicei `audit key: missing` (puneți la loc `JARVIS_AUDIT_KEY` în
`/etc/jarvis-hub/jarvis.env` sau `/var/lib/jarvis-keys/workspace_audit.key` din copia off-site) sau
`audit key: mismatch` (cheia din mediu nu este cea cu care a fost scris jurnalul; rândul arată ambele
amprente). Porniți serviciul abia după `ready`: fără cheia potrivită, hub-ul pornește, dar refuză
orice autentificare (§13, §17).

Apoi, în Administrare → Audit, **Verifică lanțul** trebuie să răspundă `ok` (pentru `key_mismatch`,
§17). După ce lanțul e `ok` și o autentificare de probă reușește, ștergeți copia veche — conține
toate datele companiei, necriptate:

```bash
sudo rm -rf /var/lib/jarvis-hub.old
```

**Restaurare pe un server nou** (serverul vechi a căzut, sau mutați pilotul):

1. Faceți §2 și §3 ca la o instalare nouă, cu codul la versiunea de pe care provine arhiva (sau
   una mai nouă: baza de date migrează doar înainte, §15).
2. **Nu generați chei noi la §4.** Aduceți din copia off-site `/etc/jarvis-hub/jarvis.env` (root,
   `0600`) și conținutul lui `/var/lib/jarvis-keys/` (deținut de `jarvis`, `0700` / `0600`): ele
   conțin `JARVIS_BACKUP_KEY` (fără ea arhiva nu se deschide), cheia de audit (fără ea nimeni nu se
   autentifică) și `JARVIS_SECRET_KEY` (fără ea parola SMTP trebuie reintrodusă). Schimbați doar ce
   ține de noul server (de exemplu `JARVIS_ALLOWED_HOSTS`, dacă se schimbă numele).
3. Puneți arhiva în `/var/lib/jarvis-hub/backups/` (comenzile `install` din blocul de mai sus) și
   rulați restaurarea de mai sus, de la `install -d … jarvis-hub.restored` până la verificarea
   mediului inclusiv. Pe un server nou, `systemctl stop` nu are ce opri.
4. Abia apoi `sudo systemctl enable --now jarvis-hub`, Caddy (§5) și verificarea lanțului.

## 15. Upgrade

```bash
sudo -u jarvis git -C /opt/jarvis-hub describe --tags --always   # 0. notați versiunea curentă
nerva-run -m agents.core.backup create --encrypt                 # 1. o copie înainte (notați numele fișierului, §14)
sudo -u jarvis git -C /opt/jarvis-hub fetch --tags               # 2. codul nou, la eticheta comunicată
sudo -u jarvis git -C /opt/jarvis-hub checkout <eticheta-nouă>   #    (include interfața compilată)
sudo -u jarvis bash -c 'cd /opt/jarvis-hub && ./install.sh --no-start'   # 3. dependențele schimbate + testul de pornire
nerva-run -m agents.core.workspace check                         #    „ready” (o schemă mai veche migrează la pornire)
sudo systemctl restart jarvis-hub                                # 4. repornire (oprire grațioasă)
```

La pasul 1 notați valoarea `"archive"` (calea arhivei) sau numele pe care îl arată
`backup list`: `verify` și `restore` le acceptă pe amândouă (§14). Cu un pachet `git bundle` primit în locul accesului la GitHub (§2), pasul 2 este
`sudo -u jarvis git -C /opt/jarvis-hub fetch --tags /cale/nerva-pilot-nou.bundle` (pachetul trebuie
să poată fi citit de utilizatorul `jarvis`). Pe Debian, pasul 3 este comanda cu
`/usr/local/bin/python3.12 scripts/bootstrap.py` din §2 (pe Ubuntu cu `python3.13` instalat,
`python3.12 scripts/bootstrap.py`). Ca la instalare, ignorați rândurile finale „Start it … / Then
open …”.

Schema bazei de date a spațiului de lucru migrează automat la prima conectare (`PRAGMA
user_version`), doar înainte. O repornire întrerupe ce era în lucru: rulările de raport active
devin `failed` / `interrupted`, iar un răspuns în flux al asistentului se termină cu eroare —
faceți upgrade-ul în afara programului.

**Revenire.** Un cod mai vechi decât baza de date doar avertizează în jurnal („workspace database is
at schema N, newer than this code”; `check` spune atunci `NOT ready`), deci nu rulați un cod vechi pe
o bază nouă: reveniți la codul de la pasul 0 **și** la datele de la pasul 1, împreună.

```bash
sudo systemctl stop jarvis-hub
sudo -u jarvis git -C /opt/jarvis-hub checkout <versiunea-de-la-pasul-0>
sudo -u jarvis bash -c 'cd /opt/jarvis-hub && ./install.sh --no-start'
# apoi restaurarea din §14 cu arhiva de la pasul 1, de la „install -d … jarvis-hub.restored”
# până la „systemctl start jarvis-hub”, plus verificarea lanțului de audit
```

## 16. Recuperare din linia de comandă

Toate rulează cu `nerva-run` (§2), deci cu același mediu ca serviciul. În afară de `check` (care
doar raportează), înainte să schimbe ceva refuză cu **codul de ieșire 2** — fără nicio modificare,
cu un mesaj care numește `nerva-run` — când își dau seama că nu rulează cu mediul serviciului
(`nerva-run -m agents.core.workspace --help` le listează; ajutorul, mesajele lor și rândurile de
jurnal ale spațiului de lucru numesc comenzile în această formă, de exemplu
`check with: nerva-run -m agents.core.workspace check`):

- `NERVA_WORKSPACE` este oprit („Nerva Workspace is disabled in this environment”);
- `JARVIS_HOME` nu este setat, deci datele ar fi în `memory_logs/` din checkout, pe care serviciul
  nu îl folosește („JARVIS_HOME is not set, so the data root would be …”);
- baza de date lipsește, la `reset-link`, `promote` și `audit-rekey` („no Nerva Workspace database
  at …”; `setup-code` o creează, fiindcă la prima instalare încă nu există);
- jurnalul de audit are rânduri, iar cheia de audit lipsește („this environment has no audit key
  …”), nu poate fi citită sau diferă de cea cu care a fost scris jurnalul („the audit key differs
  …”): un rând semnat cu altă cheie ar rupe lanțul definitiv. Singura excepție este `audit-rekey`,
  a cărui treabă este tocmai o cheie diferită.

**Codul 1:** utilizator inexistent, cont dezactivat (la `reset-link`), configurare deja făcută (la
`setup-code`), `--base-url` invalid, mediu care nu este gata (la `check`), lanț de audit rupt din
alt motiv decât cheia (la `audit-rekey`). Linkurile, promovările și înlocuirea cheii de audit sunt auditate cu
`actor_email='cli'`: cineva cu acces la server a acționat, iar jurnalul o spune.

| Comandă | Când |
|---|---|
| `nerva-run -m agents.core.workspace setup-code` | Afișează codul de configurare inițială (doar înainte de configurare). |
| `nerva-run -m agents.core.workspace reset-link --email ana@firma.ro --base-url https://nerva.firma.ro` | Un link nou: de invitație pentru un cont `invited`, de resetare a parolei pentru unul `active` (72 h, o singură folosire). Linkul se afișează pe ecran; dați-l persoanei pe un canal sigur. Un cont dezactivat trebuie întâi reactivat sau promovat. |
| `nerva-run -m agents.core.workspace promote --email ana@firma.ro` | Face contul administrator (și îl reactivează dacă era dezactivat; fără parolă rămâne `invited` — emiteți apoi `reset-link`). Îi închide sesiunile. Pentru situația în care niciun administrator nu se mai poate autentifica. |
| `nerva-run -m agents.core.workspace check` | Verificarea mediului, doar citire (baza de date deschisă numai pentru citire, nicio cheie creată), oricând — și cu serviciul oprit: dacă spațiul de lucru este pornit, directorul de date, baza de date și versiunea schemei, starea cheii de audit (`ok`, `missing`, `unreadable`, `mismatch`, cu amprentele cheilor, niciodată cheia). Se termină cu `ready` (codul 0) sau `NOT ready` (codul 1), cu remediul sub rândul greșit. De rulat după o restaurare sau o mutare (§14) și înainte de un upgrade. |
| `nerva-run -m agents.core.workspace audit-rekey` · `… audit-rekey --confirm` | **Doar pentru o cheie de audit pierdută cu adevărat** (nicio copie, nicăieri): dacă cheia serviciului mai există, puneți-o la loc. Fără `--confirm` arată ce ar face — câte rânduri au fost semnate cu altă cheie — și se termină cu codul 2, fără nicio modificare. Cu `--confirm` scrie un rând `audit.rekeyed` (actor `cli`), semnat cu cheia din mediu, care fixează toate rândurile anterioare; de acum hub-ul semnează cu ea. Rândurile semnate cu cheia veche nu mai pot fi verificate niciodată, dar o modificare sau o ștergere ulterioară a lor tot se vede. Refuză (fără nicio modificare) un lanț rupt din alt motiv decât cheia (restaurați o copie, §14) și un mediu fără nicio cheie (nu creează una). |

`--base-url` este adresa hub-ului, așa cum o folosesc utilizatorii: schema și numele
(`https://nerva.firma.ro`), plus calea rădăcină dacă hub-ul este servit sub una, fără query sau
fragment. Adresa paginii (`https://nerva.firma.ro/workspace/`) este acceptată și ea — `/workspace`
de la final se elimină, ca linkul să nu devină `…/workspace/workspace/invite` —, iar orice altă cale
de sub `/workspace` (de exemplu `…/workspace/invite`) este refuzată cu codul 1.

## 17. Depanare

**Modelul (`model_unavailable` — 503, cu `reason`).** Fereastra cipului modelului și rezultatul
**Testează modelul** explică motivul în cuvinte; codul exact este câmpul `reason` din răspunsurile
`GET /api/workspace/model` și `POST /api/workspace/admin/model/test` (în browser: instrumentele de
dezvoltare, fila Network).

| `reason` | Cauza și remediul |
|---|---|
| `hub_not_ready` | Hub-ul încă pornește (încarcă agenții și routerul). Așteptați; dacă persistă, citiți `journalctl -u jarvis-hub`. |
| `no_local_model` | Politica `local_only` și niciun server local detectat. Porniți Ollama/vLLM, verificați `JARVIS_OLLAMA_URL` / `JARVIS_LM_STUDIO_URL` (`curl http://127.0.0.1:11434/api/tags` sau `…:8000/v1/models`). Hub-ul îl găsește în ≤ 5 minute sau la repornire. |
| `no_model` | Politica `allow_cloud` și nicio rută disponibilă (nici local, nici o cheie cloud). |
| `model_not_approved` | Routerul a ales un model care nu e în lista de modele aprobate a hub-ului pentru agentul `workspace`. Aprobați modelul în setările hub-ului sau serviți altul. |
| `backend_error` | Verificarea de tratare a datelor nu a putut decide (de ex. depozitul de consimțământ nu poate fi citit) sau backend-ul a eșuat neașteptat. Citiți jurnalul hub-ului (numește doar tipul erorii). |
| `model_unreachable` | Serverul de model nu poate fi contactat deloc (serviciu oprit, port închis, adresă greșită) sau conexiunea s-a rupt în timpul răspunsului. `systemctl status ollama` (sau serviciul vLLM), apoi `curl http://127.0.0.1:11434/api/tags` / `curl http://127.0.0.1:8000/v1/models`. Cipul îl arată fără să aștepte sondarea de 5 minute a hub-ului: imediat după un apel eșuat, altfel în cel mult ~1,5 minute (cipul se reîmprospătează o dată pe minut, iar verificarea serverului este reținută 30 s). |
| `model_error` | Serverul de model a răspuns, dar cu o eroare HTTP (ex. modelul nu e încărcat; la vLLM, un prompt mai lung decât `--max-model-len`). Verificați serverul de model și jurnalul lui; mesajul serverului apare în jurnalul hub-ului (mai jos). |
| `thinking_exhausted` | Modelul și-a consumat tot bugetul de tokeni raționând (§3.2). Folosiți un model instruct sau reduceți raționamentul. |
| `empty_answer` | Modelul a returnat un răspuns gol. Verificați modelul și fereastra de context (§3.1). |

Alte erori ale modelului: `409 model_policy_blocked` cu `data_policy_unacknowledged` (server de
model non-loopback neconfirmat, §3.3) sau `provider_may_train` (politica `allow_cloud` și o rută
cloud spre un furnizor care nu e `local`/`no-training`, §8); `503 model_busy` (toate locurile
ocupate 30 s — ridicați `NERVA_WORKSPACE_MAX_CONCURRENT_LLM` doar dacă serverul de model ține mai
multe cereri simultane); `504 model_timeout`; `422 content_blocked` (garda de securitate a hub-ului a blocat
conținutul). Când garda hub-ului rulează în modul REDACT sau BLOCK, răspunsurile sosesc dintr-o
bucată, nu în flux — interfața spune asta.

**Cum citiți jurnalul hub-ului la o eroare de model** (`journalctl -u jarvis-hub`, nivelul implicit
`info`). Slotul OpenAI-compatible se numește „LM Studio” în jurnal și pentru vLLM:

| Rând | Ce înseamnă |
|---|---|
| `INFO httpx HTTP Request: POST http://127.0.0.1:8000/v1/chat/completions "HTTP/1.1 500 Internal Server Error"` | Adresa exactă apelată și codul HTTP primit de la serverul de model (rândul vine chiar înaintea celui de mai jos). |
| `ERROR jarvis.llm.base LM Studio request failed — serving a degraded reply: [REDACTED:high_entropy_secret] \| server said: {…}` | Serverul a răspuns cu o eroare (`model_error`). După `server said:` este textul serverului de model. Partea mascată este mesajul bibliotecii HTTP (cod, adresă și un link spre documentația codului HTTP): linkul seamănă cu un secret, iar filtrul jurnalului maschează tot mesajul — adresa și codul sunt în rândul `httpx` de deasupra. |
| `WARNING jarvis.llm.base LM Studio unreachable — serving a degraded reply: All connection attempts failed` | Serverul nu poate fi contactat (`model_unreachable`). |
| `INFO nerva.workspace.llm workspace posture: the lm-studio model server does not answer` | Verificarea cipului nu a primit niciun răspuns de la server. |

`[REDACTED:high_entropy_secret]` apare și în alte rânduri: filtrul de secrete al jurnalului maschează
orice șir lung de litere, cifre, `/`, `-` și `_` care pare aleator (chei, identificatori, căi cu cifre
precum numele arhivelor de backup sau `business/files/12.bin`). Este intenționat; nu îl opriți pe un
pilot (`JARVIS_LOG_REDACTION=0` ar lăsa secretele în jurnal).

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
| SSO: `401 sso_no_identity` la „Continuă cu contul companiei”, iar în Administrare → Audit o intrare „Conectare eșuată” al cărei detaliu (clic pe rând) arată „Mod de conectare: Contul companiei (SSO)” și „Motiv: Proxy-ul de autentificare nu a trimis secretul corect” (codurile `via=sso`, `reason=bad_proxy_secret`; ultimul rând al detaliului este codul tehnic `auth.login_failed`) | Caddy nu trimite secretul sau trimite altul. `sudo systemctl show caddy -p EnvironmentFiles` trebuie să numească `/etc/caddy/nerva-sso.env`, iar valoarea de acolo să fie aceeași cu `NERVA_WORKSPACE_SSO_SECRET` din `/etc/jarvis-hub/jarvis.env`. Apoi `sudo systemctl restart caddy` (un `reload` nu recitește fișierul de mediu). |
| SSO: același `401`, cu motivul „Proxy-ul de autentificare nu a trimis o adresă de email” (`reason=no_identity`) | Secretul e corect, dar emailul lipsește sau apare de mai multe ori: verificați `--set-xauthrequest=true` la oauth2-proxy și `copy_headers X-Auth-Request-Email>X-Forwarded-Email` în Caddyfile (varianta B). |
| SSO: același `401`, fără niciun rând de audit | Cererea nu vine de la o adresă din `JARVIS_TRUSTED_PROXIES` (lipsește sau nu conține `127.0.0.1`). |
| SSO: `401 invalid_credentials`, cu motivul „Nu există un cont cu această adresă”, „Invitația nu a fost încă acceptată” sau „Contul este dezactivat” (`reason=unknown_user` / `user_invited` / `user_disabled`) | Emailul garantat de proxy nu are un cont activ: invitați persoana (§7) — SSO nu creează conturi. |
| Hub-ul nu pornește; jurnalul spune „Refusing to start: JARVIS_TRUSTED_PROXIES: …” | Lista nu poate fi citită (ex. un nume în loc de IP). Corectați-o (pe acest server: `127.0.0.1`); până atunci systemd repornește serviciul la fiecare 5 s, fără succes. |
| `503 audit_key_missing` la orice autentificare și modificare (interfața: „Jurnalul de audit nu poate fi scris…”), în timp ce `/readyz` și `GET /api/workspace/session` răspund 200 | Procesul nu are cheia de audit — `JARVIS_AUDIT_KEY` lipsește din mediul serviciului și `$JARVIS_KEY_DIR/workspace_audit.key` nu există —, deși jurnalul are rânduri (tipic după o restaurare sau o mutare fără chei, §14). În `journalctl -u jarvis-hub`, la pornire: „Nerva Workspace cannot sign its audit trail: the audit key is missing …”, iar la fiecare refuz „workspace audit key missing: … refusing to create a new key”; planificatorul își suspendă pașii care scriu în audit (rândul „workspace scheduler paused” de mai jos, §12). Nu s-a scris nimic. Puneți la loc cheia din copia off-site, verificați cu `nerva-run -m agents.core.workspace check` (`ready`) și reporniți; **nu** generați una nouă. |
| `503 audit_key_mismatch` la orice autentificare și modificare | Procesul are o cheie de audit, dar alta decât cea cu care a fost semnat cel mai nou rând (altă `JARVIS_AUDIT_KEY` — de exemplu chei generate din nou la §4 pe un server refăcut —, alt `JARVIS_KEY_DIR` cu alt fișier). În jurnal: „workspace audit key mismatch: the key from … (fingerprint …) is not the one the newest audit row was signed with (fingerprint …)”, plus o dată „workspace scheduler paused: …” (mai jos). Nu s-a scris nimic, deci lanțul este încă intact. Puneți la loc cheia serviciului (`check` arată amprenta cheii din mediu și pe cea a jurnalului: trebuie să coincidă) și reporniți. Doar dacă acea cheie s-a pierdut cu adevărat: `audit-rekey` (§16). |
| Verificarea auditului: „Cheia de audit nu corespunde” (`key_mismatch`) | Rânduri semnate cu altă cheie decât cea de acum. Cu cheia greșită în mediu (`check` spune `mismatch`; pagina se vede doar dintr-o sesiune deschisă înainte de schimbarea cheii, fiindcă o autentificare nouă este refuzată): puneți la loc cheia serviciului. Cu cheia corectă (`check` spune `ok`): rândul `broken_at` din răspunsul `GET /api/workspace/admin/audit/verify` (fila Network) și cele scrise după el cu aceeași altă cheie provin de la o versiune anterioară acestei protecții, care semna cu orice cheie avea; ruptura nu se mai repară — exportați CSV-ul ca dovadă, iar un lanț intact se obține doar restaurând arhiva de dinaintea incidentului (§14), cu pierderea datelor de după ea. |
| Verificarea auditului: „Lanțul este rupt la intrarea #N”, fără `key_mismatch` | Un rând a fost modificat, șters sau mutat după ce a fost scris (cheia este cea bună). Păstrați o copie a bazei de date (`nerva-run -m agents.core.backup create --encrypt`) și anunțați responsabilul de securitate. |
| Verificarea auditului răspunde `ok` după un `audit-rekey` | Normal: rândurile semnate cu cheia pierdută nu se mai pot verifica, dar sunt fixate de rândul `audit.rekeyed` („Cheia de audit înlocuită (din linia de comandă)” în listă). Pagina spune câte intrări a verificat și, separat, câte intrări de dinaintea schimbării cheii (intrarea #N, rândul re-cheierii) au fost semnate cu cheia pierdută și nu mai pot fi verificate; răspunsul API le numără în `unverified`, cu `rekeyed_at`. |

**Documente.** Un document `failed` are un cod stabil: `invalid_file` (fișier corupt sau structură
nevalidă), `encrypted_pdf`, `too_many_pages`, `no_text` (PDF scanat — faceți OCR înainte),
`timeout`, `too_much_text`, `interrupted` (extracția a fost oprită de o repornire sau de o cădere a
hub-ului; curățenia planificatorului, §12, marchează astfel documentele rămase `processing` —
**Reindexează** o reia). `404 file_missing` la descărcare sau reindexare: originalul lipsește de
pe disc (restaurați din backup). `409 document_busy`: documentul încă se procesează (o reindexare
este permisă oricum după 10 minute). `507 storage_failed`: discul nu poate fi scris (spațiu,
permisiuni).

**Avertismente ale spațiului de lucru în jurnalul hub-ului** (`journalctl -u jarvis-hub`; nivelul
`WARNING`, fără traceback):

| Rând | Cauza și remediul |
|---|---|
| `WARNING nerva.workspace.scheduler workspace scheduler paused: <motiv>, so scheduled reports, approval expiry and the failing of stuck runs and approvals wait — nothing is changed or written for them until the service's JARVIS_AUDIT_KEY / JARVIS_KEY_DIR are back; check with: nerva-run -m agents.core.workspace check (…)` | Procesul nu are cheia jurnalului de audit; motivul spune care caz: `the audit key of this process is not the one the audit trail was written with` (altă cheie), `this process has no audit key …` (lipsește) sau `the audit key file of this process cannot be read`. Apare o singură dată, la începutul pauzei (și din nou doar dacă starea cheii se schimbă), lângă eroarea de la pornire și refuzurile `503` de mai sus. Rapoartele programate și expirările așteaptă (§12); nu s-a scris nimic pentru ele. Puneți la loc cheia serviciului, verificați cu `nerva-run -m agents.core.workspace check` (`ready`) și reporniți: primul ciclu recuperează ce a așteptat. Fără repornire, revenirea apare ca `INFO … workspace scheduler resumed: …` (invizibil la `JARVIS_LOG_LEVEL=warning`); după o repornire cu cheia bună nu există un asemenea rând. |
| `WARNING nerva.workspace.db Nerva Workspace: N file(s) or folder(s) under …/business could be read by other users (a restore or a copy made with a permissive umask); they are private now — files 0600, folders 0700` (cu un `business/` care e o legătură: `under …/business → <director>`) | Informativ, de obicei la prima pornire după o restaurare sau o copiere fără `UMask=0077`: hub-ul a scos deja drepturile celorlalți de pe acele fișiere (§13). Nu e nimic de făcut pentru `business/`; restul directorului de date îl acoperă `chmod -R go-rwx` din §14. |
| `WARNING nerva.workspace.db Nerva Workspace: …/business is a link to <director>, which holds the hub's data directory, so the modes under it are not checked — link business/ to a folder of its own (PILOT_GUIDE §13)` | `business/` este o legătură simbolică spre `/`, spre directorul de date sau spre un director de deasupra lui, deci hub-ul nu schimbă modurile acolo (ar atinge mult mai mult decât fișierele companiei). Opriți serviciul, mutați datele într-un director doar al lor (de exemplu `/mnt/disc2/business`, deținut de `jarvis`, `0700`), refaceți legătura spre el și porniți din nou (§13). |
| `WARNING nerva.workspace.db Nerva Workspace: N file(s) or folder(s) under …/business can be read by other users and this process may not change that (PermissionError on …): make the service's user their owner and remove the access of others — chown -R jarvis:jarvis and chmod -R go-rwx (PILOT_GUIDE §14, §19)` | Fișierele aparțin altui utilizator (de exemplu o restaurare sau o copiere făcută ca root, fără `nerva-run`). Hub-ul pornește oricum. `sudo chown -R jarvis:jarvis /var/lib/jarvis-hub` și `sudo chmod -R go-rwx /var/lib/jarvis-hub`, apoi `sudo systemctl restart jarvis-hub`. |
| `WARNING nerva.workspace.config JARVIS_FILE_ROOTS lists <cale>, which <relația> the Nerva Workspace data directory …/business, so this root is ignored: the file tools stay outside company data …` (pentru `JARVIS_TERMINAL_LOCAL_ROOTS`: `… so this root is ignored: the terminal's working directory stays outside company data — its roots bound only the working directory; a path inside an approved command, absolute or ../, is governed by the terminal's approval …`) | O rădăcină explicită care este (`is`), conține (`contains`) sau se află în (`is inside`) directorul datelor companiei, deci hub-ul o ignoră (§13), o dată per proces; celelalte rămân, iar fără nicio rădăcină rămasă se folosește cea implicită. Pentru terminal, rădăcinile limitează doar directorul de lucru: o comandă aprobată care numește o cale absolută sau `../business/…` tot ajunge acolo — de aceea aprobarea fiecărei comenzi rămâne a proprietarului (§13, §18). Scoateți rădăcina din `/etc/jarvis-hub/jarvis.env` (pe serverul pilot cele două instrumente rămân oprite, §19). |
| `WARNING nerva.workspace.mailer sending email via <gazdă>:<port> failed (<motiv>, <tipul erorii>)` | Un email nu a putut fi trimis (motivul este unul din tabelul *Email* de mai sus, de exemplu `connection_failed` cu serverul SMTP oprit). O cerere `email.send` aprobată se termină `failed` cu `smtp_failed` (aprobatorul și solicitantul citesc motivul în română), iar o livrare de raport lasă rularea `succeeded`, cu „Raportul este gata, dar emailul nu a fost trimis” în pagina rulării (după o reîncărcare, §18) și „Email netrimis” în istoric; jurnalul de audit are `email.failed`. Verificați serverul SMTP, apoi **Email de test** (§9). |

**Backup** (`nerva-run -m agents.core.backup …`). `verify` și `restore` primesc numele din
`backup list` sau calea arhivei din `<JARVIS_HOME>/backups/` (§14); orice eșec este un singur rând,
fără traceback.

| Mesaj | Cauza și remediul |
|---|---|
| ``no such backup: <…> — verify and restore take a file name from `list`, or a path to an archive inside <…>/backups (copy one from elsewhere there first)`` (codul 2) | Argumentul nu numește o arhivă din `backups/`: un nume greșit, o copie aflată în alt director sau o cale care iese din `backups/`. Directorul din mesaj arată ce `JARVIS_HOME` are comanda: dacă nu este `/var/lib/jarvis-hub/backups`, nu rulează cu mediul serviciului — folosiți `nerva-run`. O arhivă adusă din afară se pune întâi în `<JARVIS_HOME>/backups/` (§14). |
| `cannot decrypt <nume>: JARVIS_BACKUP_KEY in this environment is not the key the archive was made with, or the archive is damaged; nothing was checked` (la `restore`: `…; nothing was restored`) (codul 1). Linia numește cheia încercată de fapt: `JARVIS_BACKUP_KEY in this environment (a passphrase, with the salt …/backup.cipher.salt)` pentru o cheie-frază; fără `JARVIS_BACKUP_KEY`, `JARVIS_SECRET_KEY in this environment (JARVIS_BACKUP_KEY is not set: run with the service's environment: nerva-run, PILOT_GUIDE §2)` sau `the key file <JARVIS_KEY_DIR>/backup.cipher.key (JARVIS_BACKUP_KEY is not set: …)` | Cheia numită nu este cea cu care a fost făcută arhiva (sau arhiva e deteriorată). Nu s-a verificat sau restaurat nimic. Dacă linia spune `JARVIS_BACKUP_KEY is not set`, comanda a rulat fără mediul serviciului: rulați-o cu `nerva-run` (§2). Altfel folosiți cheia din copia off-site a `/etc/jarvis-hub/jarvis.env`; pentru o cheie-frază, și `/var/lib/jarvis-keys/` (§14). |
| `cannot decrypt <nume>: JARVIS_BACKUP_KEY is not set (run with the service's environment: nerva-run, PILOT_GUIDE §2) and there is no key file …/backup.cipher.key — no key was made; nothing was checked` sau `cannot decrypt <nume>: JARVIS_BACKUP_KEY in this environment is a passphrase and its salt …/backup.cipher.salt does not exist (the key directory is kept off-site, PILOT_GUIDE §14) — no key was made; …` (codul 1) | Lipsește materialul cheii: comanda a rulat fără mediul serviciului (fără `nerva-run`), cu alt `JARVIS_KEY_DIR`, sau, pe un server nou, fără `/var/lib/jarvis-keys/` adus din copia off-site. `verify` și `restore` nu creează nicio cheie și nicio sare (una nouă n-ar deschide arhiva și ar rămâne pentru copiile următoare). Rulați cu `nerva-run` (§2) sau aduceți înapoi directorul cheilor (§14), apoi repetați comanda. |
| `target <director> is not empty, nothing restored — restore into a new, empty directory (--force overwrites, but never restore over the data directory in use)` (codul 1) | Directorul țintă al `restore` nu este gol. Folosiți un director nou și gol, ca în §14. |
| `no such backup: <nume> (it is no longer in <director>)` (codul 1) | Arhiva a dispărut între căutare și citire (de exemplu curățată de copia nocturnă, care păstrează doar ultimele 7). Rulați din nou `backup list`. |
| `verify failed: …` / `restore failed: …` (codul 1) | O eroare de sistem, numită în rând: de exemplu o țintă care este un fișier (`Not a directory`) sau lipsa unui drept de scriere. |
| `archive rejected, nothing restored: …` / `archive rejected partway through …` | Arhiva nu trece verificările de siguranță la dezarhivare. În al doilea caz ținta conține o restaurare parțială: ștergeți-o și încercați altă arhivă. |

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
- **Interfața** este un singur pachet JavaScript (~600 kB necomprimat, ~170–180 kB cu gzip, cât
  trimite Caddy), fără încărcare pe bucăți; câmpurile native de dată/oră urmează limba browserului,
  nu a aplicației.
- **Lista de documente** nu are paginare; trimiterea unui email nu are o limită totală de timp (doar
  15 s per operație SMTP).
- **O cheie de audit pierdută nu se recuperează:** fără ea hub-ul refuză orice scriere (§13), iar
  `audit-rekey` (§16) permite continuarea doar cu prețul ei — rândurile semnate cu cheia pierdută
  rămân fixate, dar nu mai pot fi verificate. Copia off-site a cheilor (§14) este singura apărare.
- **Rădăcinile explicite ale instrumentelor de fișiere și ale terminalului:** hub-ul ignoră
  acum, cu un avertisment, orice rădăcină din `JARVIS_FILE_ROOTS` / `JARVIS_TERMINAL_LOCAL_ROOTS`
  care este, conține sau se află în `<JARVIS_HOME>/business` (§13). Rămân în afara acestei
  verificări: rădăcinile setate cât timp spațiul de lucru este oprit și `business/` nu există încă
  (nu sunt date de protejat; pornirea spațiului de lucru cere oricum o repornire a hub-ului, după
  care verificarea se aplică), rădăcinile date direct din
  cod (nu din mediu) și căile absolute din argumentele unei comenzi de terminal aprobate, pe care
  rădăcinile nu le limitează (ele limitează doar directorul de lucru). Pe serverul pilot cele două
  instrumente rămân oprite (§19).
- **Modurile fișierelor din afara `business/`:** spațiul de lucru își face private doar propriile
  fișiere (§13); restul directorului de date urmează umask-ul serviciului, iar unitatea systemd din
  repo nu setează `UMask` — fișierul `pilot.conf` din §2 îl adaugă.
- **Pagina unei rulări urmărite în direct nu așteaptă rezultatul livrării pe email:** rularea
  devine `succeeded` înainte ca emailul către destinatarii aprobați să fie trimis (până la 15 s per
  operație SMTP), iar pagina se oprește din reîmprospătat la `succeeded`. Mențiunea „Trimis pe email
  către” sau avertismentul „Raportul este gata, dar emailul nu a fost trimis” apar după o
  reîncărcare a paginii; notificarea din clopoțel sosește oricum.

## 19. Lista de verificare înainte de primul utilizator

- [ ] `JARVIS_SECRET_KEY`, `JARVIS_BACKUP_KEY` și cheia de audit sunt setate, iar
      `/etc/jarvis-hub/jarvis.env` și `/var/lib/jarvis-keys/` sunt copiate off-site.
- [ ] `JARVIS_ADMIN_TOKEN` este setat (§4); firewall-ul permite doar SSH și 80/443 (§13).
- [ ] `curl -s http://127.0.0.1:8080/readyz` răspunde 200; cipul modelului arată **Local** (sau
      **Local, neverificat** pentru un server din LAN confirmat la §3.3); **Testează modelul** reușește.
- [ ] `https://nerva.firma.ro/v2` răspunde 404, `https://nerva.firma.ro/workspace/` se deschide cu
      certificat valid și HSTS.
- [ ] Un link de invitație începe cu `https://nerva.firma.ro/workspace/invite#t=`.
- [ ] Emailul de test ajunge (dacă folosiți SMTP), iar lista de domenii permise e completată.
- [ ] Fiecare departament are cel puțin un approver în afară de administratori, altfel cererile de
      email ale membrilor merg doar la administratori.
- [ ] `nerva-run -m agents.core.backup verify <ultima copie>` răspunde `"ok": true`, iar copiile
      ajung pe alt sistem în fiecare noapte (`/etc/cron.d/nerva-offsite`, §14).
- [ ] Administrare → Audit → **Verifică lanțul** răspunde `ok`, iar
      `nerva-run -m agents.core.workspace check` se termină cu `ready`.
- [ ] `sudo stat -c '%a %n' /var/lib/jarvis-hub/business/workspace.db /var/lib/jarvis-hub/settings.db /var/lib/jarvis-hub/backups`
      arată `600`, `600` și `700`: baza companiei este privată oricum (hub-ul o creează `0600` și
      închide la pornire tot ce e sub `business/`, §13), iar `settings.db` și `backups/` arată că
      `UMask=0077` din §2 este activ pentru restul datelor hub-ului. Jurnalul de la pornire nu are
      rândul „… can be read by other users and this process may not change that …” (§17).
- [ ] `JARVIS_FILE_TOOLS` și `JARVIS_TERMINAL_LOCAL_HOST` sunt oprite. Dacă le folosiți totuși,
      rădăcinile lor explicite nu numesc `<JARVIS_HOME>` ori `<JARVIS_HOME>/business` — hub-ul le-ar
      ignora oricum, cu avertismentul din §17, dar configurația trebuie să spună ce se întâmplă
      (§13).

## 20. Sfârșitul pilotului: predarea și ștergerea datelor

Când pilotul se încheie fără continuare, datele companiei se predau (dacă le cere) și se șterg de
pe server și de pe copiile off-site. Hotărâți împreună cu compania, în scris, ce primește și până
când se păstrează ceva.

```bash
# 1. copia finală, verificată (serviciul încă rulează); dacă se cere, exportați și auditul ca CSV
#    din Administrare → Audit (cele mai noi 50 000 de rânduri) înainte de pasul 3
nerva-run -m agents.core.backup create --encrypt            # notați valoarea "archive" (sau numele din backup list)
nerva-run -m agents.core.backup verify <nume>               # "ok": true
# 2. copiați arhiva de pe server și predați-o; pe canale separate predați și JARVIS_BACKUP_KEY,
#    cheia de audit (JARVIS_AUDIT_KEY sau fișierul /var/lib/jarvis-keys/workspace_audit.key) și
#    JARVIS_SECRET_KEY: fără cheia de audit nimeni nu se mai poate autentifica pe copia restaurată,
#    fără cheia secretelor parola SMTP trebuie reintrodusă
# 3. opriți tot ce a servit pilotul
sudo systemctl disable --now jarvis-hub
sudo rm -f /etc/cron.d/nerva-offsite
# 4. ștergeți datele, cheile și configurația de pe server
sudo rm -rf /var/lib/jarvis-hub /var/lib/jarvis-hub.old /var/lib/jarvis-hub.restored \
            /var/lib/jarvis-keys /etc/jarvis-hub /var/lib/jarvis /opt/jarvis-hub \
            /etc/systemd/system/jarvis-hub.service /etc/systemd/system/jarvis-hub.service.d
sudo systemctl daemon-reload
sudo userdel jarvis
```

Apoi ștergeți copiile de pe destinația off-site (`backup@nas.firma.ro:/backups/nerva/`) și, dacă nu
mai servesc altui scop, configurația Caddy a pilotului (`/etc/caddy/Caddyfile`,
`/etc/caddy/nerva-sso.env`), oauth2-proxy și modelul descărcat (`ollama rm <model>`). Arhiva
predată se deschide pe o instalare Nerva care are aceleași chei (`JARVIS_BACKUP_KEY`, cheia de
audit, `JARVIS_SECRET_KEY`): urmați *Restaurare pe un server nou* din §14 — arhiva se pune în
`<JARVIS_HOME>/backups/`, apoi `nerva-run -m agents.core.backup restore <nume> <director-gol>` și
verificarea mediului. `rm` șterge fișierele, dar nu suprascrie discul: dacă politica companiei cere
ștergere sigură, folosiți ștergerea la nivel de disc sau un disc criptat a cărui cheie se distruge.
