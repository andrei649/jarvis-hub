# Chemare de testeri (RO) — Facebook + LinkedIn

> Canal: rețeaua personală a ownerului (decizia GTM din sync-ul pre-go-live: fără
> lansare publică, fără Show HN — recrutare 1:1 și postări pe identitatea personală).
> Ținta: 1–3 testeri care chiar folosesc produsul 2–4 săptămâni, nu 30 de curioși.

---

## Cerințe de screening (filtrul — cine POATE testa)

**Eliminatorii (fără astea nu are sens):**

1. **Un „creier" pentru asistent — una din două:**
   - **GPU local** cu **minim 8 GB VRAM** (RTX 3060/3070/3080+) și disponibilitatea de a
     instala LM Studio sau Ollama (îl ghidăm noi), **SAU**
   - **Cheie API proprie cu facturare activă** la OpenAI / Anthropic / Google.
     ⚠️ **Abonamentul ChatGPT Plus NU e suficient** — Plus nu include acces API;
     e nevoie de cheie de la platform.openai.com cu billing setat (costul tipic
     de testare: câțiva dolari/lună). Conectorul OpenAI există în produs
     (`OPENAI_API_KEY` → gpt-4o), la fel Anthropic și Gemini.
2. **Windows 11 sau Linux** + confort minim cu un terminal / rulat un script.
3. **Angajament real:** folosire aproape zilnică 2–4 săptămâni + un check-in
   săptămânal de ~30 min (call sau mesaje) + acordul de a împărtăși niște
   metrici anonime de utilizare (numărul de acțiuni aprobate/respinse — nu conținut).

**Bonus (nu obligatoriu):** deja self-hostează ceva (Home Assistant, NAS, n8n);
16–24 GB VRAM; profesie cu date sensibile (avocat, medic, contabil) — exact
publicul pentru care privatul-local contează.

**Întrebări de auto-calificare** (pune-le în primul DM — cine nu răspunde clar, nu e omul):
- Ce placă video ai și câtă memorie VRAM?
- Rulezi deja ceva local (Ollama, LM Studio, Stable Diffusion)?
- Dacă nu: ai cheie API cu billing la OpenAI/Anthropic/Google? (nu abonament ChatGPT)
- Poți să-i dai 15 minute pe zi, 2–4 săptămâni, plus 30 min o dată pe săptămână cu mine?

---

## Varianta Facebook (ton personal)

> De un an construiesc un asistent AI personal care rulează **la tine acasă, pe
> calculatorul tău** — nu în cloudul nimănui. Îl cheamă Jarvis (da, știu 😄).
>
> Ce face diferit: orice acțiune „serioasă" (trimite mail, plătește, postează)
> **se oprește și îți cere aprobarea**, cu preview — și totul rămâne într-un
> jurnal criptografic pe care nimeni nu-l poate rescrie. Datele familiei nu
> pleacă NICIODATĂ de pe mașina ta. Zero abonament, zero cloud obligatoriu.
>
> **Caut 2–3 oameni** care să-l folosească pe bune, 2–4 săptămâni, și să-mi
> spună sincer unde doare. Nu e produs finisat — e software în stadiu „îl
> testăm împreună", cu ghid de instalare pas cu pas și cu mine ca suport direct.
>
> Ai nevoie de UNA din două: 🖥️ o placă video cu 8+ GB VRAM (gen RTX 3060+)
> — SAU — 🔑 o cheie API proprie la OpenAI/Anthropic/Google (atenție:
> abonamentul ChatGPT Plus NU e totuna cu o cheie API). Plus Windows 11 sau
> Linux și răbdare de early-adopter.
>
> Dacă te tentează (sau știi pe cineva), lasă un comentariu sau dă-mi un mesaj. 🙏

## Varianta LinkedIn (ton profesional)

> **Caut 2–3 testeri pentru un proiect personal: un „AI operating system" local-first.**
>
> Am construit în ultimul an un asistent AI multi-agent care rulează integral
> pe hardware-ul propriu al utilizatorului. Diferența față de valul de agenți
> autonomi din 2026 (și de eșecurile lor de securitate foarte mediatizate):
> **autonomie guvernată** — acțiunile ireversibile trec printr-o coadă de
> aprobare cu preview, fiecare acțiune e înregistrată într-un audit log
> tamper-evident, iar datele personale nu părăsesc mașina în configurația
> implicită. Open source, fără abonament.
>
> Caut oameni care să-l ruleze ca daily-driver 2–4 săptămâni și să-mi dea
> feedback structurat săptămânal. E pre-1.0: instalarea e ghidată, suportul
> sunt eu, iar feedbackul vostru stabilește direct ce se construiește.
>
> **Profil căutat:** GPU cu 8+ GB VRAM (LM Studio/Ollama) *sau* cheie API
> proprie OpenAI/Anthropic/Google cu facturare (un abonament ChatGPT nu oferă
> acces API); Windows 11/Linux; confort de bază cu un terminal. Bonus dacă
> lucrați cu date sensibile — pentru voi există modul strict-local.
>
> Interesați? Un mesaj aici e de ajuns. Detalii tehnice: github.com/andrei649/jarvis-hub

---

## Note pentru owner (nu se postează)

- Postarea pe FB/LinkedIn personal e conformă cu înghețul „no public surface"
  (rețea personală ≠ lansare; fără cross-post în grupuri/subreddits deocamdată).
- Înainte de primul tester instalat: bootstrap-ul de postură partener (Gate-2 #1),
  CLI-ul de support bundle (#2) și flip-ul de licență (#9) — vezi
  [docs/meetings/2026-07-07-pre-go-live-sync.md](../../docs/meetings/2026-07-07-pre-go-live-sync.md).
- Răspuns standard la candidați: întrebările de auto-calificare de mai sus + link
  la README; cine trece → ghidul de instalare + prima sesiune supravegheată
  (inclusiv drill-ul de backup/restore din decizia Ops).
