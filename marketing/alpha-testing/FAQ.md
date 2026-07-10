# Jarvis Hub — Alpha FAQ (întrebări reale de la testeri)

> Răspunsuri oneste la întrebările recurente din recrutarea alpha (culese din firul de FB,
> 2026-07). Sursă unică pentru DM-uri, reply-uri publice și pentru copy-ul de recrutare
> ([`../recruiting/2026-07-tester-call-ro.md`](../recruiting/2026-07-tester-call-ro.md)).
> Fiecare afirmație tehnică e verificabilă în cod (open-source).

---

### Cheia mea API rămâne locală sau trece prin serverele voastre?
Rămâne **strict la tine**. Cheia stă în fișierul `.env` de pe mașina ta, iar aplicația apelează
**direct** furnizorul (OpenAI / Anthropic / Google / OpenRouter). Nu există un backend operat de owner
prin care să treacă cheia sau conversațiile. Codul e open-source → verificabil. Pentru zero apeluri
externe: **mod strict-local** (rulezi pe GPU-ul tău, fără nicio cheie).

### Pot folosi abonamentul ChatGPT Plus / Claude Pro în loc de o cheie API?
Nu. Abonamentele de chat **nu** includ acces API — sunt produse diferite. Ai nevoie de o **cheie de
platformă cu billing activ** (`platform.openai.com` etc.; câțiva dolari/lună la testare), **sau** mergi
complet local cu un GPU de 8+ GB și nu plătești API deloc.

### Merge pe macOS / Apple Silicon (M1–M4)?
Instalarea `./install.sh` acoperă **Linux și macOS**, iar un Mac cu chip M (memorie unificată) e o
gazdă foarte bună pentru modele locale. **Nu e încă în matricea oficială de suport alpha** (pre-1.0,
suportul e ownerul) — dar dacă ești pe M-series și vrei să testezi, spune. Ținta e să avem și un
tester pe Mac.

### De ce Windows 11 și nu Windows 10?
Windows 10 a ajuns End-of-Life pe 14 oct. 2025. Nu e o barieră tehnică dură (stack-ul Python rulează),
dar pre-1.0 nu susținem un OS EOL — matricea de suport e **Windows 11 / Linux / (macoS best-effort)**.

### E open-source? Pot adăuga OpenRouter / alte endpoint-uri OpenAI-compatible / modele locale?
Da, open-source. **OpenRouter e deja integrat**: o singură cheie → sute de modele pe un endpoint
OpenAI-compatible, cu hot-swap din chat prin `/model <id>`. Local merge prin **LM Studio / Ollama**.
Orice endpoint OpenAI-compatible se conectează prin `base_url`.

### Local-only pe 8GB VRAM — chiar e utilizabil?
Onest: pe 8GB rulezi bine **bucla de asistent guvernat + voce (Whisper) + managementul memoriei** pe un
model mic. Pentru raționament de nivel „frontier" ai două căi: (a) un model local mai mare — mai mult
VRAM sau offload în RAM DDR5, cu scădere de viteză; (b) **hybrid** — un model mare în cloud ca
orchestrator, restul local. Recomandarea implicită e **hybrid**. Pragul exact de la care local-only
devine incomod e chiar una din întrebările pe care le testăm în alpha.

### Ce date pleacă de pe mașina mea?
Local-first. În configurația implicită / strict-local, datele personale și cele de familie **nu pleacă**
de pe mașina ta. În hybrid pleacă doar ce are nevoie un tur de orchestrator cloud — iar acțiunile
ireversibile trec oricum prin **coada de aprobare** cu preview.

### E sigur să-l rulez pe calculatorul personal?
E construit exact pe frica asta: orice acțiune ireversibilă **se oprește și cere aprobarea ta cu
preview**, totul intră într-un **audit log tamper-evident** local, iar codul e open-source (inspectabil
linie cu linie). Cine vrea maxim de izolare → **mod strict-local**, fără apeluri externe.

### Cât mă costă?
Software-ul e gratuit / open-source, fără abonament către owner. Costul e fie **curentul** (GPU local),
fie **consumul tău de API** (tipic câțiva dolari/lună la testare). Atât.

### De ce specificațiile alea (GPU/API) dacă „rulează local"?
Pentru că asistentul are nevoie de „un creier": ori un **model local** (de-aici GPU-ul de 8+ GB, sau
DDR5 pentru offload), ori un **model prin API** (de-aici cheia). Fără una din două nu are cu ce
raționa. Whisper + managementul memoriei rulează local în ambele cazuri.
