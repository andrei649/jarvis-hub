# Execution Ledger — drumul prin restul backlogului

> Creat: 2026-06-09 · Owner: Andrei · Branch de lucru: `claude/backlog-status-rfod8p`
> Sursă de adevăr a *scope-ului*: [BACKLOG.md](../BACKLOG.md). Acest fișier e **ordinea de execuție** +
> realitatea „ce se poate termina și verifica în sandbox vs ce e poartă umană (hardware/serviciu extern)".

Decizia (2026-06-09): **gate-ul 1.0.0 întâi**, apoi post-1.0 (H20 Hermes, H21 Cognition). Un **draft PR per
item** (sau cluster mic coerent), fiecare cu teste offline, sub guvernare. Refresh acest ledger la fiecare item livrat.

## Cum se citește „Verificabil aici?"

| Marcaj | Înseamnă |
|--------|----------|
| ✅ **sandbox** | Cod pur (Python) + teste offline → **terminat și verificat** complet în acest mediu. |
| 🟡 **parțial** | Logica + testele offline (cu mock) se livrează aici; o cale reală (browser/clipboard/HUD live) cere verificare umană. |
| 🔌 **extern** | Are nevoie de un serviciu real (X/Twitter, Twilio, Notion live, device pereche) — livrez adaptor + teste mock; **live = poartă umană**. |
| 🖥️ **hardware** | Are nevoie de GPU / build nativ (GGUF, Rust, Tauri, training) — pot face pregătirea software + teste; **rularea reală = poartă umană**. |

> Caveatul de onestitate: **nu raportez „done" pe ✅** decât când codul + testele trec aici. Pe 🟡/🔌/🖥️
> livrez partea software testabilă și marchez explicit ce rămâne verificare live (exact cum face deja
> backlogul cu TASK-1, H13.1 ⚠️, „verificare live restantă").

---

## FAZA 1 — Gate 1.0.0 (pre-1.0) · 25 iteme · ~207 SP

Ordine: P1 > P2 > P3; în interiorul aceleiași priorități, **întâi ce e complet verificabil aici** (loop rapid,
cadență dovedită), apoi clusterele hardware/externe (oricum au poartă umană).

### Val 1 — paritate guvernată, complet verificabilă aici (cadență rapidă)

| # | Item | SP | P | Verif. | Status |
|---|------|----|----|--------|--------|
| H12.19 | Pairing/aprobare expeditor inbound | 3 | P2 | ✅ sandbox | ✅ **DONE 2026-06-09** (PR în curs) |
| H12.20 | Rotație profile auth + failover model (hybrid router) | 3 | P3 | ✅ sandbox | ☐ |
| H12.25 | Transcript-watcher → taskuri (notițe ședință → coadă aprobare) | 3 | P2 | 🟡 (mock Notion/Todoist) | ☐ |
| H12.23 | Pack skill-uri „digest" (news/earnings/Reddit/arXiv/HF, scorer) | 5 | P3 | 🟡 (mock fetch) | ☐ |
| H12.18 | Agent Canvas / A2UI (spațiu vizual guvernat în HUD) | 8 | P3 | 🟡 (frontend; dep HUD v2) | ☐ |

### Val 2 — frontieră P1/P2 (capabilitate locală + computer-use)

| # | Item | SP | P | Verif. | Status |
|---|------|----|----|--------|--------|
| H13.1 | Tier VLM strict-local (Qwen3-VL-8B) — ecran/docs/bonuri | 8 | **P1** | 🖥️ hardware (GGUF+24GB) | ☐ — *singurul P1 rămas; soft-prep aici, rulare = poartă* |
| H15.1 | Agent browser-use local (approval-queue + sandbox + egress allowlist) | 8 | P2 | 🟡 (mock browser; real Playwright = host) | ☐ |
| H13.4 | Refresh model default → MoE reasoning hibrid (gpt-oss/Qwen3-30B-A3B) | 5 | P2 | 🟡 (router testabil; load model = hardware) | ☐ |
| H13.3 | Speculative decoding (draft→target) | 5 | P2 | 🖥️ hardware (GPU/vLLM) | ☐ |
| H15.2 | Modul înțelegere ecran local (UI-TARS-7B) | 8 | P2 | 🖥️ hardware (dep H13.1) | ☐ |
| H12.8 | Split sateliți-mic → server-inferență pe GPU acasă | 8 | P2 | 🖥️ hardware | ☐ |
| H12.7 | Captură pasivă multi-suprafață (opt-in, local) | 8 | P2 | 🟡 (logica+KG testabil; hook-uri OS = host) | ☐ |
| H15.3 | Operator în desktop virtual izolat (PiP) | 13 | P3 | 🖥️🔌 heavy | ☐ |

### Val 3 — restul Track E + write-back (P3, majoritar extern)

| # | Item | SP | P | Verif. | Status |
|---|------|----|----|--------|--------|
| H10.30 | Write-Back Integrations (Notion/GitHub/GCal ca tool-uri native) | 8 | P3 | 🔌 (tool + mock; live = poartă) | ☐ |
| H12.16 | Lărgire canale (WhatsApp/Signal/iMessage/Matrix/Teams/…) | 5 | P2 | 🔌 (adaptoare + mock) | ☐ |
| H12.21 | Acțiuni guvernate pe social (X post/reply/DM prin coadă) | 5 | P3 | 🔌 (X API) | ☐ |
| H12.22 | Voce outbound / call-back (Twilio/Telnyx, interrupt-budget) | 8 | P3 | 🔌 (telefonie) | ☐ |
| H12.24 | Generare media (imagini/thumbnail/video) | 5 | P3 | 🖥️🔌 | ☐ |
| H12.13 | Sync E2E opt-in între device-uri (GPU acasă ↔ telefon) | 13 | P3 | 🟡 (cripto+protocol testabil; pereche reală = poartă) | ☐ |
| H12.17 | Node mesh guvernat (telefon/desktop ca noduri de execuție) | 13 | P3 | 🔌 (dep H11.1) | ☐ |
| H12.14 | Model agentic mic, fine-tuned (router/tool) | 8 | P3 | 🖥️ (dep H11.3, GPU) | ☐ |

### Val 4 — Platform Parity H11 (P3, hardware/nativ)

| # | Item | SP | P | Verif. | Status |
|---|------|----|----|--------|--------|
| H11.4 | WASM Sandbox (wasmtime) — backend execuție complementar Docker | 8 | P3 | 🟡 (binding instalabil → testabil) | ☐ |
| H11.1 | Desktop App (Tauri) — tray, wake-word, auto-start | 13 | P3 | 🖥️ build nativ | ☐ |
| H11.3 | SFT/GRPO Training Pipeline (din trace-uri) | 13 | P3 | 🖥️ GPU | ☐ |
| H11.2 | Rust Extension / Hot-Path Crates (PyO3) | 21 | P3 | 🖥️ Rust+GPU bench | ☐ |

> **Verdict pre-1.0:** complet verificabile aici ~5–7 iteme; restul livrabile ca *software + teste*, cu
> rularea reală drept poartă umană pe hardware/servicii. Gate-ul 1.0.0 = **toate** terminate (incl. porțile umane).

---

## FAZA 2 — Post-1.0 · ~17 iteme · ~99 SP

Nu sunt în gate-ul 1.0.0. Pornesc după ce Faza 1 e închisă (sau la cererea ta, în paralel — ex. H21.0 e
fundație P1 care repară BUG-5).

### ORIZONT 21 — Cognition (cea mai importantă temă; refolosește H14)

| # | Item | SP | P | Verif. | Status |
|---|------|----|----|--------|--------|
| H21.0 | Schelet `cognition/` + CognitionFacade + **fix BUG-5** (TurnContext) | 5 | P1 | ✅ sandbox | ☐ |
| H21.1 | Cheia de onestitate (anti-sycophancy + Sycophancy Index) | 5 | P1 | ✅ sandbox | ☐ |
| H21.2 | Afect + expresie de personalitate (mood/trait/prosody) | 8 | P2 | 🟡 (logica ✅; prosody TTS = audio) | ☐ |
| H21.3 | Memorie vie nelimitată (predictive-coding, TCM, NREM/REM, re-projection) | 13 | P2 | ✅ sandbox | ☐ |
| H21.4 | Învățare guvernată (KC.db + calibrare; hrănește H20.4/H20.5) | 13 | P2 | ✅ sandbox | ☐ |
| H21.5 | Ansamblu & maturare (diversitate, drift ancorat, self-test psihometric) | 8 | P3 | ✅ sandbox | ☐ |
| H21.A | Secrete în afara `.env` (vaultwarden) | 5 | P2 | 🔌 (vault self-hosted) | ☐ |
| H21.B | Skill media (yt-dlp + Whisper) | 3 | P3 | 🟡 (binar yt-dlp opțional) | ☐ |
| H21.C | Skill generare imagini pe idle (ComfyUI/diffusers) | 5 | P3 | 🖥️ GPU | ☐ |
| H21.D | Prompt-builder video (cloud manual) | 2 | P3 | ✅ sandbox | ☐ |

### ORIZONT 20 — Hermes Mining

| # | Item | SP | P | Verif. | Status |
|---|------|----|----|--------|--------|
| H20.1 | Tool-RPC în sandbox (`execute_code`) — zero-context-cost pipelines | 13 | P2 | 🟡 (RPC+sandbox testabil; Docker host) | ☐ |
| H20.2 | Lățime providere + hot-swap (OpenRouter + `/model`) | 5 | P2 | 🔌 (OpenRouter key; mock testabil) | ☐ |
| H20.3 | ContextCompressor runtime | 8 | P2 | ✅ sandbox | ☐ |
| H20.4 | Self-evolution (DSPy/GEPA) | 8 | P3 | 🟡 | ☐ |
| H20.5 | Skill self-improvement + drift manifest | 5 | P3 | ✅ sandbox | ☐ |
| H20.6 | Delegare dinamică de sub-agenți | 8 | P3 | ✅ sandbox | ☐ |

### H18 (mobil) — task umbrelă

| # | Item | SP | P | Verif. | Status |
|---|------|----|----|--------|--------|
| H18.10 | Paritate continuă (bridge) — menține `mobile/PARITY.md` | — | P2 | ✅ standing | ☐ (mereu deschis) |

---

## Jurnal de livrare

| Dată | Item | PR | Note |
|------|------|----|------|
| 2026-06-09 | **H12.19** Pairing/aprobare expeditor inbound | (acest branch) | `core/channels/pairing.py` + gateway gate + 4 endpoints + 20 teste. Suită: 1820 passed, 1 skipped. |
